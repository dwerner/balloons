//! Error types for the supervisor.

use thiserror::Error;

/// Result type alias using the supervisor Error.
pub type Result<T> = std::result::Result<T, Error>;

/// Errors that can occur in the supervisor.
#[derive(Debug, Error)]
pub enum Error {
    /// Process was not found by ID.
    #[error("process not found: {0}")]
    ProcessNotFound(String),

    /// Process is not running (for operations that require running state).
    #[error("process is not running: {0}")]
    ProcessNotRunning(String),

    /// Process is already running (for operations that require stopped state).
    #[error("process is already running: {0}")]
    ProcessAlreadyRunning(String),

    /// Failed to spawn the process.
    #[error("failed to spawn process: {0}")]
    SpawnFailed(String),

    /// Failed to stop the process.
    #[error("failed to stop process: {0}")]
    StopFailed(String),

    /// I/O error during process operations.
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    /// Process stream error.
    #[error("process stream error: {0}")]
    ProcessStream(String),

    /// Invalid command (empty or malformed).
    #[error("invalid command: {0}")]
    InvalidCommand(String),

    /// Failed to write to process stdin.
    #[error("failed to write to stdin: {0}")]
    StdinWriteFailed(String),
}
