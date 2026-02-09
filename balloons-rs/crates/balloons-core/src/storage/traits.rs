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

    // =========================================================================
    // Batch Operations - atomic multi-item operations in a single transaction
    // =========================================================================

    /// Save a session along with all its turns atomically.
    ///
    /// This is more efficient than calling save_session + N×save_turn because
    /// it uses a single database transaction. The turn order is determined by
    /// the order of turns in the slice.
    ///
    /// If the session already exists, it will be overwritten. Any existing turns
    /// for this session are preserved unless they have the same ID as a new turn.
    async fn save_session_with_turns(
        &self,
        id: &str,
        session: &SessionData,
        turns: &[TurnData],
    ) -> Result<()>;

    /// Atomically replace all turns for a session.
    ///
    /// This operation:
    /// 1. Deletes all existing turns for the session
    /// 2. Inserts all new turns in order
    /// 3. Updates the turn order to match the new turns
    ///
    /// All in a single transaction, so either everything succeeds or nothing changes.
    /// This is the preferred way to sync Python's in-memory turns to storage.
    async fn replace_session_turns(
        &self,
        session_id: &str,
        turns: &[TurnData],
    ) -> Result<()>;
}
