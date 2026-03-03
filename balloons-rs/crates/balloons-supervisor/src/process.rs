//! Individual supervised process management.

use std::collections::VecDeque;
use std::sync::Arc;

use async_channel::{Receiver, Sender};
use async_lock::RwLock;
use async_process::{Child, ChildStdin};
use chrono::{DateTime, Utc};
use futures_lite::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use futures_lite::{future, StreamExt};
use procstream::{ProcessEvent, ProcessEventType, ProcessHandle};
use tracing::{debug, info, warn};

use crate::error::{Error, Result};
use crate::lsp::LspReader;
use crate::types::{LogEntry, LogSource, OutputQuery, ProcessId, ProcessInfo, ProcessStatus};

/// Maximum number of log entries to keep in memory per process.
const MAX_LOG_ENTRIES: usize = 10_000;

/// Channel for sending stdin input to a process.
/// Using a channel allows us to send input from anywhere while the event
/// handler task owns the actual stdin handle.
pub type StdinSender = Sender<String>;

/// A process being supervised with its log buffer.
pub struct SupervisedProcess {
    /// Unique identifier for this process.
    pub id: ProcessId,
    /// Friendly name (if provided).
    pub name: Option<String>,
    /// The command being executed.
    pub command: String,
    /// Working directory.
    pub working_dir: String,
    /// Session this process belongs to.
    pub session_id: String,
    /// When the process was started.
    pub started_at: DateTime<Utc>,
    /// When the process ended (if completed).
    pub ended_at: Option<DateTime<Utc>>,
    /// Current status.
    status: RwLock<ProcessStatus>,
    /// Captured log entries (circular buffer).
    logs: RwLock<VecDeque<LogEntry>>,
    /// Channel to send stop signal.
    stop_tx: Option<Sender<()>>,
    /// Channel to send stdin input to the process.
    stdin_tx: Option<StdinSender>,
}

impl SupervisedProcess {
    /// Create a new supervised process record.
    pub fn new(
        id: ProcessId,
        name: Option<String>,
        command: String,
        working_dir: String,
        session_id: String,
        pid: u32,
        stop_tx: Sender<()>,
        stdin_tx: Option<StdinSender>,
    ) -> Self {
        Self {
            id,
            name,
            command,
            working_dir,
            session_id,
            started_at: Utc::now(),
            ended_at: None,
            status: RwLock::new(ProcessStatus::Running { pid }),
            logs: RwLock::new(VecDeque::with_capacity(MAX_LOG_ENTRIES)),
            stop_tx: Some(stop_tx),
            stdin_tx,
        }
    }

    /// Get the current status.
    pub async fn status(&self) -> ProcessStatus {
        self.status.read().await.clone()
    }

    /// Check if the process is running.
    pub async fn is_running(&self) -> bool {
        self.status.read().await.is_running()
    }

    /// Add a log entry.
    pub async fn add_log(&self, entry: LogEntry) {
        let mut logs = self.logs.write().await;
        if logs.len() >= MAX_LOG_ENTRIES {
            logs.pop_front();
        }
        logs.push_back(entry);
    }

    /// Get log entries matching the query.
    pub async fn get_logs(&self, query: &OutputQuery) -> Vec<LogEntry> {
        let logs = self.logs.read().await;
        let mut result: Vec<LogEntry> = logs
            .iter()
            .filter(|entry| {
                // Filter by timestamp
                if let Some(since) = &query.since {
                    if entry.timestamp < *since {
                        return false;
                    }
                }
                // Filter by source
                if let Some(source) = &query.source {
                    if entry.source != *source {
                        return false;
                    }
                }
                // Filter by pattern
                if let Some(pattern) = &query.pattern {
                    if !entry.content.contains(pattern.as_str()) {
                        return false;
                    }
                }
                true
            })
            .cloned()
            .collect();

        // Apply limit (from the end, most recent first)
        if let Some(limit) = query.limit {
            if result.len() > limit {
                result = result.into_iter().rev().take(limit).rev().collect();
            }
        }

        result
    }

    /// Get the number of log entries.
    pub async fn log_count(&self) -> usize {
        self.logs.read().await.len()
    }

    /// Get a preview of recent output (last non-empty line).
    pub async fn output_preview(&self) -> Option<String> {
        let logs = self.logs.read().await;
        logs.iter()
            .rev()
            .find(|e| !e.content.trim().is_empty() && e.source != LogSource::System)
            .map(|e| {
                let content = e.content.trim();
                if content.len() > 100 {
                    format!("{}...", &content[..100])
                } else {
                    content.to_string()
                }
            })
    }

    /// Convert to ProcessInfo for API responses.
    pub async fn to_info(&self) -> ProcessInfo {
        ProcessInfo {
            id: self.id.clone(),
            name: self.name.clone(),
            command: self.command.clone(),
            working_dir: self.working_dir.clone(),
            session_id: self.session_id.clone(),
            status: self.status().await,
            started_at: self.started_at,
            ended_at: self.ended_at,
            log_count: self.log_count().await,
            output_preview: self.output_preview().await,
        }
    }

    /// Mark the process as exited.
    #[allow(dead_code)]
    pub async fn set_exited(&mut self, code: Option<i32>, signal: Option<i32>) {
        let mut status = self.status.write().await;
        *status = ProcessStatus::Exited { code, signal };
        self.ended_at = Some(Utc::now());
        self.stop_tx = None; // No longer need the stop channel

        // Add system log entry
        let exit_msg = match (code, signal) {
            (Some(c), _) => format!("Process exited with code {}", c),
            (_, Some(s)) => format!("Process killed by signal {}", s),
            (None, None) => "Process exited".to_string(),
        };
        self.add_log(LogEntry::system(exit_msg)).await;
    }

    /// Mark the process as killed (for use from Arc<Self>).
    pub async fn mark_killed(&self) {
        let mut status = self.status.write().await;
        *status = ProcessStatus::Exited {
            code: None,
            signal: Some(9), // SIGKILL
        };
        self.add_log(LogEntry::system("Process killed by supervisor".to_string()))
            .await;
    }

    /// Mark the process as failed.
    #[allow(dead_code)]
    pub async fn set_failed(&mut self, error: String) {
        let mut status = self.status.write().await;
        *status = ProcessStatus::Failed {
            error: error.clone(),
        };
        self.ended_at = Some(Utc::now());
        self.stop_tx = None;

        self.add_log(LogEntry::system(format!("Process failed: {}", error)))
            .await;
    }

    /// Request the process to stop.
    pub async fn stop(&self) -> Result<()> {
        if let Some(tx) = &self.stop_tx {
            tx.send(())
                .await
                .map_err(|_| Error::StopFailed("stop channel closed".to_string()))?;
            Ok(())
        } else {
            Err(Error::ProcessNotRunning(self.id.clone()))
        }
    }

    /// Send input to the process's stdin.
    ///
    /// The input is sent as a line (newline appended automatically).
    pub async fn send_input(&self, data: &str) -> Result<()> {
        if !self.is_running().await {
            return Err(Error::ProcessNotRunning(self.id.clone()));
        }

        if let Some(tx) = &self.stdin_tx {
            tx.send(data.to_string())
                .await
                .map_err(|_| Error::StdinWriteFailed("stdin channel closed".to_string()))?;

            // Log the input we sent
            self.add_log(LogEntry::stdin(data.to_string())).await;
            Ok(())
        } else {
            Err(Error::StdinWriteFailed("stdin not available for this process".to_string()))
        }
    }

    /// Check if stdin is available for this process.
    pub fn has_stdin(&self) -> bool {
        self.stdin_tx.is_some()
    }
}

/// Result of racing stop signal vs process events.
enum EventLoopAction {
    Stop,
    Event(Option<ProcessEvent>),
}

use crate::supervisor::OutputCallback;

/// Handle procstream events and update the supervised process.
///
/// If an output_callback is provided, it will be called for each stdout/stderr line
/// with (process_id, source, content).
pub async fn handle_process_events<H: ProcessHandle>(
    process: Arc<SupervisedProcess>,
    mut events: impl StreamExt<Item = ProcessEvent> + Unpin,
    stop_rx: Receiver<()>,
    output_callback: Option<OutputCallback>,
    mut handle: H,
) {
    debug!(process_id = %process.id, "Starting event handler");

    loop {
        // Race the stop signal against the next event
        let action = future::or(
            async {
                let _ = stop_rx.recv().await;
                EventLoopAction::Stop
            },
            async { EventLoopAction::Event(events.next().await) },
        )
        .await;

        match action {
            EventLoopAction::Stop => {
                info!(process_id = %process.id, "Received stop signal, killing process");
                // Kill the process
                if let Err(e) = handle.kill().await {
                    info!(process_id = %process.id, error = %e, "Failed to kill process (may have already exited)");
                }
                // Update status to reflect the kill
                process.mark_killed().await;
                break;
            }
            EventLoopAction::Event(Some(event)) => {
                let (entry, source) = match &event.event_type {
                    ProcessEventType::Started { pid } => {
                        debug!(process_id = %process.id, pid = pid, "Process started");
                        (LogEntry::system(format!("Process started (PID {})", pid)), "system")
                    }
                    ProcessEventType::Stdout => {
                        let content = event.data.clone().unwrap_or_default();
                        (LogEntry::stdout(content), "stdout")
                    }
                    ProcessEventType::Stderr => {
                        let content = event.data.clone().unwrap_or_default();
                        (LogEntry::stderr(content), "stderr")
                    }
                    ProcessEventType::Exited { code, signal } => {
                        info!(
                            process_id = %process.id,
                            code = ?code,
                            signal = ?signal,
                            "Process exited"
                        );
                        let msg = match (code, signal) {
                            (Some(c), _) => format!("Process exited with code {}", c),
                            (_, Some(s)) => format!("Process killed by signal {}", s),
                            (None, None) => "Process exited".to_string(),
                        };
                        (LogEntry::system(msg), "system")
                    }
                };

                // Call the output callback if registered
                if let Some(ref callback) = output_callback {
                    callback(&process.id, source, &entry.content);
                }

                process.add_log(entry).await;

                // If process exited, we're done
                if matches!(event.event_type, ProcessEventType::Exited { .. }) {
                    break;
                }
            }
            EventLoopAction::Event(None) => {
                // Stream ended
                debug!(process_id = %process.id, "Event stream ended");
                break;
            }
        }
    }

    debug!(process_id = %process.id, "Event handler finished");
}

/// Handle LSP process events with Content-Length framing.
///
/// Unlike line-based handling, this reads complete JSON-RPC messages
/// from stdout and delivers them as single log entries.
pub async fn handle_lsp_events(
    process: Arc<SupervisedProcess>,
    mut lsp_reader: LspReader<async_process::ChildStdout>,
    stderr_reader: BufReader<async_process::ChildStderr>,
    mut stdin: ChildStdin,
    stdin_rx: Receiver<String>,
    mut child: Child,
    stop_rx: Receiver<()>,
    output_callback: Option<OutputCallback>,
) {
    debug!(process_id = %process.id, "Starting LSP event handler");

    // Log that process started
    process.add_log(LogEntry::system(format!("LSP process started (PID {})", child.id()))).await;
    if let Some(ref callback) = output_callback {
        callback(&process.id, "system", &format!("LSP process started (PID {})", child.id()));
    }

    // Spawn a task to forward stdin
    let stdin_process_id = process.id.clone();
    let stdin_task = smol::spawn(async move {
        while let Ok(data) = stdin_rx.recv().await {
            // LSP stdin needs Content-Length framing
            let framed = crate::lsp::frame_lsp_message(&data);
            if let Err(e) = stdin.write_all(&framed).await {
                warn!(process_id = %stdin_process_id, error = %e, "Failed to write to LSP stdin");
                break;
            }
            if let Err(e) = stdin.flush().await {
                warn!(process_id = %stdin_process_id, error = %e, "Failed to flush LSP stdin");
                break;
            }
        }
    });

    // Spawn a task to read stderr (still line-based for error messages)
    let stderr_process = Arc::clone(&process);
    let stderr_callback = output_callback.clone();
    let stderr_task = smol::spawn(async move {
        let mut lines = stderr_reader.lines();
        while let Some(line_result) = lines.next().await {
            match line_result {
                Ok(line) => {
                    let entry = LogEntry::stderr(line.clone());
                    if let Some(ref callback) = stderr_callback {
                        callback(&stderr_process.id, "stderr", &line);
                    }
                    stderr_process.add_log(entry).await;
                }
                Err(e) => {
                    warn!(process_id = %stderr_process.id, error = %e, "Error reading stderr");
                    break;
                }
            }
        }
    });

    // Main loop: read LSP messages from stdout, handle stop signal
    loop {
        let action = future::or(
            async {
                let _ = stop_rx.recv().await;
                EventLoopAction::Stop
            },
            async {
                match lsp_reader.read_message().await {
                    Ok(Some(msg)) => EventLoopAction::Event(Some(ProcessEvent::new_with_data(
                        ProcessEventType::Stdout,
                        msg,
                    ))),
                    Ok(None) => EventLoopAction::Event(None), // EOF
                    Err(e) => {
                        warn!(process_id = %process.id, error = %e, "Error reading LSP message");
                        EventLoopAction::Event(None)
                    }
                }
            },
        )
        .await;

        match action {
            EventLoopAction::Stop => {
                info!(process_id = %process.id, "Received stop signal, killing LSP process");
                let _ = child.kill();
                process.mark_killed().await;
                break;
            }
            EventLoopAction::Event(Some(event)) => {
                if let ProcessEventType::Stdout = event.event_type {
                    let content = event.data.clone().unwrap_or_default();
                    let entry = LogEntry::stdout(content.clone());

                    if let Some(ref callback) = output_callback {
                        callback(&process.id, "stdout", &content);
                    }
                    process.add_log(entry).await;
                }
            }
            EventLoopAction::Event(None) => {
                // Stream ended, wait for process to exit
                debug!(process_id = %process.id, "LSP stdout ended, waiting for process exit");
                match child.status().await {
                    Ok(status) => {
                        let code = status.code();
                        #[cfg(unix)]
                        let signal = {
                            use std::os::unix::process::ExitStatusExt;
                            status.signal()
                        };
                        #[cfg(not(unix))]
                        let signal = None;

                        let msg = match (code, signal) {
                            (Some(c), _) => format!("LSP process exited with code {}", c),
                            (_, Some(s)) => format!("LSP process killed by signal {}", s),
                            (None, None) => "LSP process exited".to_string(),
                        };

                        process.add_log(LogEntry::system(msg.clone())).await;
                        if let Some(ref callback) = output_callback {
                            callback(&process.id, "system", &msg);
                        }
                    }
                    Err(e) => {
                        let msg = format!("Error waiting for LSP process: {}", e);
                        process.add_log(LogEntry::system(msg)).await;
                    }
                }
                break;
            }
        }
    }

    // Cancel background tasks
    stdin_task.cancel().await;
    stderr_task.cancel().await;

    debug!(process_id = %process.id, "LSP event handler finished");
}
