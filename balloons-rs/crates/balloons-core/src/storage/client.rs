use std::sync::Arc;

use crate::generated::{SessionData, SessionMetadata, TurnData};
use super::traits::{Result, StorageEngine};

/// High-level async client for storage operations
///
/// Wraps a StorageEngine implementation and provides the public API
/// that balloons-py will call into.
pub struct StorageClient {
    engine: Arc<dyn StorageEngine>,
}

impl StorageClient {
    pub fn new(engine: impl StorageEngine + 'static) -> Self {
        Self {
            engine: Arc::new(engine),
        }
    }

    pub async fn save_session(&self, id: &str, data: &SessionData) -> Result<()> {
        self.engine.save_session(id, data).await
    }

    pub async fn load_session(&self, id: &str) -> Result<Option<SessionData>> {
        self.engine.load_session(id).await
    }

    pub async fn save_turn(&self, session_id: &str, turn: &TurnData) -> Result<()> {
        self.engine.save_turn(session_id, turn).await
    }

    pub async fn load_turns(&self, session_id: &str) -> Result<Vec<TurnData>> {
        self.engine.load_turns(session_id).await
    }

    pub async fn delete_turn(&self, session_id: &str, turn_id: &str) -> Result<()> {
        self.engine.delete_turn(session_id, turn_id).await
    }

    pub async fn reorder_turns(&self, session_id: &str, turn_ids: &[String]) -> Result<()> {
        self.engine.reorder_turns(session_id, turn_ids).await
    }

    pub async fn list_sessions(&self) -> Result<Vec<SessionMetadata>> {
        self.engine.list_sessions().await
    }

    pub async fn delete_session(&self, id: &str) -> Result<()> {
        self.engine.delete_session(id).await
    }

    /// Save a session along with all its turns atomically.
    ///
    /// This is more efficient than calling save_session + N×save_turn because
    /// it uses a single database transaction.
    pub async fn save_session_with_turns(
        &self,
        id: &str,
        session: &SessionData,
        turns: &[TurnData],
    ) -> Result<()> {
        self.engine.save_session_with_turns(id, session, turns).await
    }

    /// Atomically replace all turns for a session.
    ///
    /// Deletes any turns not in the new list, upserts all new turns,
    /// and updates the turn order - all in a single transaction.
    pub async fn replace_session_turns(
        &self,
        session_id: &str,
        turns: &[TurnData],
    ) -> Result<()> {
        self.engine.replace_session_turns(session_id, turns).await
    }

    /// Load the session history (list of session IDs, most recent first).
    pub async fn load_session_history(&self) -> Result<Vec<String>> {
        self.engine.load_session_history().await
    }

    /// Save the session history (list of session IDs, most recent first).
    pub async fn save_session_history(&self, session_ids: &[String]) -> Result<()> {
        self.engine.save_session_history(session_ids).await
    }
}
