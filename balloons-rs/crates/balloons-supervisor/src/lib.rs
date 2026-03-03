//! Process Supervisor for Balloons
//!
//! Manages long-running background processes with streaming output capture.
//! Designed to be used by LLMs to spawn, monitor, and control processes
//! without blocking on their completion.
//!
//! # Features
//!
//! - **Session-scoped processes**: Each process is tagged with a session ID
//! - **Streaming output**: Real-time stdout/stderr capture with timestamps
//! - **Typed log parsing**: Optional structured log parsing via procstream
//! - **Process control**: Start, stop, list, and query processes
//!
//! # Example
//!
//! ```rust,ignore
//! use balloons_supervisor::{ProcessSupervisor, StartRequest};
//!
//! let supervisor = ProcessSupervisor::new();
//!
//! // Start a process
//! let process_id = supervisor.start(StartRequest {
//!     command: "cargo build".to_string(),
//!     working_dir: Some("/path/to/project".to_string()),
//!     session_id: "session-123".to_string(),
//!     name: Some("build".to_string()),
//! }).await?;
//!
//! // Check status
//! let info = supervisor.get_process(&process_id).await?;
//! println!("Status: {:?}", info.status);
//!
//! // Get recent output
//! let logs = supervisor.get_output(&process_id, 50).await?;
//! for entry in logs {
//!     println!("[{}] {}", entry.source, entry.content);
//! }
//! ```

mod error;
mod process;
mod supervisor;
pub mod types;

pub use error::{Error, Result};
pub use process::{StdinSender, SupervisedProcess};
pub use supervisor::{OutputCallback, ProcessSupervisor};
pub use types::{LogEntry, LogSource, OutputQuery, ProcessId, ProcessInfo, ProcessStatus, StartRequest};
