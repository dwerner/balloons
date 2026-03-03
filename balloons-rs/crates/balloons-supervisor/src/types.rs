//! Common types for the supervisor.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Unique identifier for a managed process.
pub type ProcessId = String;

/// Process I/O mode - how stdout/stderr is parsed.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "snake_case")]
pub enum ProcessMode {
    /// Line-based reading (default). Each newline-delimited line is an event.
    #[default]
    Lines,
    /// LSP mode. Parses Content-Length headers and delivers complete JSON-RPC messages.
    Lsp,
    /// Raw mode. No parsing, delivers chunks as they arrive.
    Raw,
}

/// Status of a managed process.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum ProcessStatus {
    /// Process is currently running.
    Running {
        /// Operating system process ID.
        pid: u32,
    },
    /// Process has exited normally.
    Exited {
        /// Exit code (if available).
        code: Option<i32>,
        /// Signal number (if killed by signal).
        signal: Option<i32>,
    },
    /// Process failed to start or encountered an error.
    Failed {
        /// Error description.
        error: String,
    },
}

impl ProcessStatus {
    /// Returns true if the process is currently running.
    pub fn is_running(&self) -> bool {
        matches!(self, ProcessStatus::Running { .. })
    }

    /// Returns true if the process has completed (exited or failed).
    pub fn is_complete(&self) -> bool {
        !self.is_running()
    }
}

/// Source of a log entry.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum LogSource {
    /// Standard output.
    Stdout,
    /// Standard error.
    Stderr,
    /// System message (started, exited, etc.).
    System,
    /// Standard input (echoed back for visibility).
    Stdin,
}

impl std::fmt::Display for LogSource {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LogSource::Stdout => write!(f, "stdout"),
            LogSource::Stderr => write!(f, "stderr"),
            LogSource::System => write!(f, "system"),
            LogSource::Stdin => write!(f, "stdin"),
        }
    }
}

/// A single log entry from a process.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogEntry {
    /// When this log entry was received.
    pub timestamp: DateTime<Utc>,
    /// Source of the log (stdout, stderr, or system).
    pub source: LogSource,
    /// The log content.
    pub content: String,
    /// Parsed structured data (if EventParser matched).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parsed: Option<serde_json::Value>,
}

impl LogEntry {
    /// Create a new stdout log entry.
    pub fn stdout(content: impl Into<String>) -> Self {
        Self {
            timestamp: Utc::now(),
            source: LogSource::Stdout,
            content: content.into(),
            parsed: None,
        }
    }

    /// Create a new stderr log entry.
    pub fn stderr(content: impl Into<String>) -> Self {
        Self {
            timestamp: Utc::now(),
            source: LogSource::Stderr,
            content: content.into(),
            parsed: None,
        }
    }

    /// Create a new system log entry.
    pub fn system(content: impl Into<String>) -> Self {
        Self {
            timestamp: Utc::now(),
            source: LogSource::System,
            content: content.into(),
            parsed: None,
        }
    }

    /// Create a new stdin log entry (echoed input).
    pub fn stdin(content: impl Into<String>) -> Self {
        Self {
            timestamp: Utc::now(),
            source: LogSource::Stdin,
            content: content.into(),
            parsed: None,
        }
    }

    /// Attach parsed structured data to this entry.
    pub fn with_parsed(mut self, parsed: serde_json::Value) -> Self {
        self.parsed = Some(parsed);
        self
    }
}

/// Request to start a new supervised process.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StartRequest {
    /// The command to execute (passed to shell).
    pub command: String,
    /// Working directory for the process.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub working_dir: Option<String>,
    /// Session ID this process belongs to.
    pub session_id: String,
    /// Optional friendly name for display.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// Environment variables to set (in addition to inherited).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub env: Vec<(String, String)>,
    /// I/O mode for parsing stdout/stderr.
    #[serde(default)]
    pub mode: ProcessMode,
}

/// Summary information about a process (for listing).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProcessInfo {
    /// Unique process identifier.
    pub id: ProcessId,
    /// Friendly name (if provided).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// The command being executed.
    pub command: String,
    /// Working directory.
    pub working_dir: String,
    /// Session this process belongs to.
    pub session_id: String,
    /// Current status.
    pub status: ProcessStatus,
    /// When the process was started.
    pub started_at: DateTime<Utc>,
    /// When the process ended (if completed).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ended_at: Option<DateTime<Utc>>,
    /// Number of log entries captured.
    pub log_count: usize,
    /// Preview of recent output (last line or so).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output_preview: Option<String>,
}

/// Output query options.
#[derive(Debug, Clone, Default)]
pub struct OutputQuery {
    /// Maximum number of lines to return.
    pub limit: Option<usize>,
    /// Only return entries after this timestamp.
    pub since: Option<DateTime<Utc>>,
    /// Filter by source.
    pub source: Option<LogSource>,
    /// Search pattern (substring match).
    pub pattern: Option<String>,
}

impl OutputQuery {
    /// Create a new query with default options.
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the maximum number of lines.
    pub fn limit(mut self, limit: usize) -> Self {
        self.limit = Some(limit);
        self
    }

    /// Only return entries after this timestamp.
    pub fn since(mut self, since: DateTime<Utc>) -> Self {
        self.since = Some(since);
        self
    }

    /// Filter by source.
    pub fn source(mut self, source: LogSource) -> Self {
        self.source = Some(source);
        self
    }

    /// Search for a pattern.
    pub fn pattern(mut self, pattern: impl Into<String>) -> Self {
        self.pattern = Some(pattern.into());
        self
    }
}
