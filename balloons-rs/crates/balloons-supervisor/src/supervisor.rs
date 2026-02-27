//! Process Supervisor - manages multiple supervised processes.

use std::collections::HashMap;
use std::sync::Arc;

use async_channel;
use async_lock::RwLock;
use procstream::{Command, Executor, ManagedProcess, ProcessHandle, Target};
use tracing::info;
use uuid::Uuid;

use crate::error::{Error, Result};
use crate::process::{handle_process_events, SupervisedProcess};
use crate::types::{LogEntry, OutputQuery, ProcessId, ProcessInfo, StartRequest};

/// Callback type for streaming output events.
///
/// Called with (process_id, source, content) where:
/// - process_id: The UUID of the process
/// - source: "stdout", "stderr", or "system"
/// - content: The output line
pub type OutputCallback = Arc<dyn Fn(&str, &str, &str) + Send + Sync>;

/// The main process supervisor.
///
/// Manages multiple long-running processes with streaming output capture.
/// Thread-safe and designed to be shared across async tasks.
pub struct ProcessSupervisor {
    /// All managed processes, keyed by ID.
    processes: RwLock<HashMap<ProcessId, Arc<SupervisedProcess>>>,
    /// Optional callback for streaming output to external handlers.
    output_callback: RwLock<Option<OutputCallback>>,
}

impl Default for ProcessSupervisor {
    fn default() -> Self {
        Self::new()
    }
}

impl ProcessSupervisor {
    /// Create a new process supervisor.
    pub fn new() -> Self {
        Self {
            processes: RwLock::new(HashMap::new()),
            output_callback: RwLock::new(None),
        }
    }

    /// Set an output callback that receives all stdout/stderr events.
    ///
    /// The callback is called with (process_id, source, content) for each line.
    pub async fn set_output_callback(&self, callback: Option<OutputCallback>) {
        let mut cb = self.output_callback.write().await;
        *cb = callback;
    }

    /// Get a clone of the current output callback (if any).
    pub async fn get_output_callback(&self) -> Option<OutputCallback> {
        self.output_callback.read().await.clone()
    }

    /// Start a new supervised process.
    ///
    /// Returns the process ID which can be used to query status, get output,
    /// or stop the process.
    pub async fn start(&self, request: StartRequest) -> Result<ProcessId> {
        // Validate command
        if request.command.trim().is_empty() {
            return Err(Error::InvalidCommand("command cannot be empty".to_string()));
        }

        let process_id = Uuid::new_v4().to_string();
        let working_dir = request
            .working_dir
            .clone()
            .unwrap_or_else(|| std::env::current_dir().unwrap().to_string_lossy().to_string());

        info!(
            process_id = %process_id,
            command = %request.command,
            working_dir = %working_dir,
            session_id = %request.session_id,
            "Starting supervised process"
        );

        // Create the command
        let mut cmd = Command::new("sh");
        cmd.arg("-c").arg(&request.command);
        cmd.current_dir(&working_dir);

        // Add environment variables
        for (key, value) in &request.env {
            cmd.env(key, value);
        }

        // Build the managed process target
        let target = Target::ManagedProcess(ManagedProcess::new());

        // Create the executor using the local launcher
        let executor = Executor::local(
            request.name.clone().unwrap_or_else(|| process_id.clone()),
        );

        // Launch the process
        let (events, handle) = executor
            .launch(&target, cmd)
            .await
            .map_err(|e| Error::SpawnFailed(e.to_string()))?;

        // Get the PID
        let pid = handle.pid().unwrap_or(0);

        // Create stop channel (bounded(1) similar to mpsc::channel(1))
        let (stop_tx, stop_rx) = async_channel::bounded(1);

        // Create the supervised process
        let supervised = Arc::new(SupervisedProcess::new(
            process_id.clone(),
            request.name,
            request.command,
            working_dir,
            request.session_id,
            pid,
            stop_tx,
        ));

        // Add initial log entry
        supervised
            .add_log(LogEntry::system(format!(
                "Starting process: sh -c '{}'",
                supervised.command
            )))
            .await;

        // Store the process
        {
            let mut processes = self.processes.write().await;
            processes.insert(process_id.clone(), Arc::clone(&supervised));
        }

        // Get the output callback (if any) to pass to the event handler
        let output_callback = self.get_output_callback().await;

        // Spawn task to handle events using smol (fire-and-forget).
        // We use smol because procstream uses smol internally for its async streams,
        // so the event handler needs to run on smol's executor to poll correctly.
        //
        // IMPORTANT: We move `handle` into this task to keep it alive. If the handle
        // is dropped, procstream kills the process via its Drop impl.
        let process_clone = Arc::clone(&supervised);
        smol::spawn(async move {
            handle_process_events(process_clone, events, stop_rx, output_callback, handle).await;
        })
        .detach();

        Ok(process_id)
    }

    /// Get information about a specific process.
    pub async fn get_process(&self, process_id: &str) -> Result<ProcessInfo> {
        let processes = self.processes.read().await;
        let process = processes
            .get(process_id)
            .ok_or_else(|| Error::ProcessNotFound(process_id.to_string()))?;

        Ok(process.to_info().await)
    }

    /// List all processes, optionally filtered by session.
    pub async fn list_processes(&self, session_id: Option<&str>) -> Vec<ProcessInfo> {
        let processes = self.processes.read().await;

        let mut infos = Vec::new();
        for process in processes.values() {
            if let Some(sid) = session_id {
                if process.session_id != sid {
                    continue;
                }
            }
            infos.push(process.to_info().await);
        }

        // Sort by started_at descending (most recent first)
        infos.sort_by(|a, b| b.started_at.cmp(&a.started_at));

        infos
    }

    /// Get output from a process.
    pub async fn get_output(&self, process_id: &str, limit: usize) -> Result<Vec<LogEntry>> {
        let processes = self.processes.read().await;
        let process = processes
            .get(process_id)
            .ok_or_else(|| Error::ProcessNotFound(process_id.to_string()))?;

        let query = OutputQuery::new().limit(limit);
        Ok(process.get_logs(&query).await)
    }

    /// Get output from a process with custom query options.
    pub async fn query_output(&self, process_id: &str, query: &OutputQuery) -> Result<Vec<LogEntry>> {
        let processes = self.processes.read().await;
        let process = processes
            .get(process_id)
            .ok_or_else(|| Error::ProcessNotFound(process_id.to_string()))?;

        Ok(process.get_logs(query).await)
    }

    /// Stop a running process.
    pub async fn stop_process(&self, process_id: &str) -> Result<()> {
        let processes = self.processes.read().await;
        let process = processes
            .get(process_id)
            .ok_or_else(|| Error::ProcessNotFound(process_id.to_string()))?;

        if !process.is_running().await {
            return Err(Error::ProcessNotRunning(process_id.to_string()));
        }

        info!(process_id = %process_id, "Stopping process");
        process.stop().await
    }

    /// Stop all processes for a session.
    pub async fn stop_session_processes(&self, session_id: &str) -> Vec<Result<()>> {
        let processes = self.processes.read().await;

        let mut results = Vec::new();
        for process in processes.values() {
            if process.session_id == session_id && process.is_running().await {
                results.push(process.stop().await);
            }
        }

        results
    }

    /// Remove completed processes (cleanup).
    pub async fn cleanup_completed(&self) -> usize {
        let mut processes = self.processes.write().await;
        let before = processes.len();

        processes.retain(|_, _process| {
            // Keep running processes, remove completed ones
            // Note: This is sync, but we stored the status in the process
            // We'd need to make this async-aware in a real implementation
            true // For now, keep all
        });

        before - processes.len()
    }

    /// Get the count of running processes.
    pub async fn running_count(&self) -> usize {
        let processes = self.processes.read().await;
        let mut count = 0;
        for process in processes.values() {
            if process.is_running().await {
                count += 1;
            }
        }
        count
    }

    /// Get the total count of processes.
    pub async fn total_count(&self) -> usize {
        self.processes.read().await.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[smol_potat::test]
    async fn test_supervisor_new() {
        let supervisor = ProcessSupervisor::new();
        assert_eq!(supervisor.total_count().await, 0);
    }

    #[smol_potat::test]
    async fn test_start_simple_command() {
        let supervisor = ProcessSupervisor::new();

        let request = StartRequest {
            command: "echo hello".to_string(),
            working_dir: None,
            session_id: "test-session".to_string(),
            name: Some("echo-test".to_string()),
            env: vec![],
        };

        let process_id = supervisor.start(request).await.expect("should start");
        assert!(!process_id.is_empty());
        assert_eq!(supervisor.total_count().await, 1);

        // Give the process time to run
        smol::Timer::after(Duration::from_millis(500)).await;

        // Check we can get the process info
        let info = supervisor.get_process(&process_id).await.expect("should get info");
        assert_eq!(info.name, Some("echo-test".to_string()));
        assert_eq!(info.command, "echo hello");
        assert_eq!(info.session_id, "test-session");

        // Check output was captured
        let output = supervisor.get_output(&process_id, 10).await.expect("should get output");
        // Should have some logs (at least system messages)
        assert!(!output.is_empty());
    }

    #[smol_potat::test]
    async fn test_list_processes_by_session() {
        let supervisor = ProcessSupervisor::new();

        // Start two processes in different sessions
        let request1 = StartRequest {
            command: "sleep 0.1".to_string(),
            working_dir: None,
            session_id: "session-a".to_string(),
            name: Some("sleep-a".to_string()),
            env: vec![],
        };

        let request2 = StartRequest {
            command: "sleep 0.1".to_string(),
            working_dir: None,
            session_id: "session-b".to_string(),
            name: Some("sleep-b".to_string()),
            env: vec![],
        };

        supervisor.start(request1).await.expect("should start");
        supervisor.start(request2).await.expect("should start");

        // List all
        let all = supervisor.list_processes(None).await;
        assert_eq!(all.len(), 2);

        // List by session
        let session_a = supervisor.list_processes(Some("session-a")).await;
        assert_eq!(session_a.len(), 1);
        assert_eq!(session_a[0].session_id, "session-a");

        let session_b = supervisor.list_processes(Some("session-b")).await;
        assert_eq!(session_b.len(), 1);
        assert_eq!(session_b[0].session_id, "session-b");

        // Non-existent session
        let none = supervisor.list_processes(Some("no-such-session")).await;
        assert_eq!(none.len(), 0);
    }

    #[smol_potat::test]
    async fn test_invalid_command() {
        let supervisor = ProcessSupervisor::new();

        let request = StartRequest {
            command: "   ".to_string(), // Empty/whitespace command
            working_dir: None,
            session_id: "test-session".to_string(),
            name: None,
            env: vec![],
        };

        let result = supervisor.start(request).await;
        assert!(result.is_err());
    }

    #[smol_potat::test]
    async fn test_process_not_found() {
        let supervisor = ProcessSupervisor::new();

        let result = supervisor.get_process("nonexistent-id").await;
        assert!(result.is_err());

        let result = supervisor.stop_process("nonexistent-id").await;
        assert!(result.is_err());
    }
}
