use async_trait::async_trait;
use thiserror::Error;

use crate::generated::{SessionData, SessionMetadata, TurnData};

#[derive(Debug, Error)]
pub enum Error {
    #[error("Session not found: {0}")]
    SessionNotFound(String),

    #[error("Turn not found: {0}")]
    TurnNotFound(String),

    #[error("Database error: {0}")]
    Database(String),

    #[error("Serialization error: {0}")]
    Serialization(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, Error>;

/// Abstract storage engine trait
///
/// Implementations must be Send + Sync for use across async boundaries.
/// All operations are atomic - partial writes are not possible.
#[async_trait]
pub trait StorageEngine: Send + Sync {
    /// Save a complete session (overwrites if exists)
    async fn save_session(&self, id: &str, data: &SessionData) -> Result<()>;

    /// Load a session by ID
    async fn load_session(&self, id: &str) -> Result<Option<SessionData>>;

    /// Save a single turn (upsert)
    async fn save_turn(&self, session_id: &str, turn: &TurnData) -> Result<()>;

    /// Load all turns for a session
    async fn load_turns(&self, session_id: &str) -> Result<Vec<TurnData>>;

    /// Delete a specific turn
    async fn delete_turn(&self, session_id: &str, turn_id: &str) -> Result<()>;

    /// Reorder turns within a session
    async fn reorder_turns(&self, session_id: &str, turn_ids: &[String]) -> Result<()>;

    /// List all sessions (metadata only)
    async fn list_sessions(&self) -> Result<Vec<SessionMetadata>>;

    /// Delete a session and all its turns
    async fn delete_session(&self, id: &str) -> Result<()>;
}
