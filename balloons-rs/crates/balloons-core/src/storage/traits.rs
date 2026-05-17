use async_trait::async_trait;
use thiserror::Error;

use crate::generated::{
    SessionData, SessionMetadata, TurnData, UserData, UserPrefs, WatcherRelation,
};

#[derive(Debug, Error)]
pub enum Error {
    #[error("Session not found: {0}")]
    SessionNotFound(String),

    #[error("Turn not found: {0}")]
    TurnNotFound(String),

    #[error("User not found: {0}")]
    UserNotFound(String),

    #[error("Database error: {0}")]
    Database(String),

    #[error("Serialization error: {0}")]
    Serialization(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Schema version mismatch: database is version {db_version}, application expects {app_version}")]
    SchemaTooNew { db_version: u32, app_version: u32 },
}

pub type Result<T> = std::result::Result<T, Error>;

#[async_trait]
pub trait StorageEngine: Send + Sync {
    async fn save_session(&self, id: &str, data: &SessionData) -> Result<()>;
    async fn load_session(&self, id: &str) -> Result<Option<SessionData>>;
    async fn save_turn(&self, session_id: &str, turn: &TurnData) -> Result<()>;
    async fn load_turns(&self, session_id: &str) -> Result<Vec<TurnData>>;
    async fn get_turn_count(&self, session_id: &str) -> Result<usize>;
    async fn load_turns_range(
        &self,
        session_id: &str,
        offset: usize,
        limit: usize,
    ) -> Result<Vec<TurnData>>;
    async fn delete_turn(&self, session_id: &str, turn_id: &str) -> Result<()>;
    async fn reorder_turns(&self, session_id: &str, turn_ids: &[String]) -> Result<()>;
    async fn list_sessions(&self) -> Result<Vec<SessionMetadata>>;
    async fn delete_session(&self, id: &str) -> Result<()>;
    async fn save_session_with_turns(
        &self,
        id: &str,
        session: &SessionData,
        turns: &[TurnData],
    ) -> Result<()>;
    async fn replace_session_turns(
        &self,
        session_id: &str,
        turns: &[TurnData],
    ) -> Result<()>;
    async fn load_session_history(&self) -> Result<Vec<String>>;
    async fn save_session_history(&self, session_ids: &[String]) -> Result<()>;
    async fn load_user_prefs(&self) -> Result<UserPrefs>;
    async fn save_user_prefs(&self, prefs: &UserPrefs) -> Result<()>;
    async fn save_watcher(&self, watcher: &WatcherRelation) -> Result<()>;
    async fn delete_watcher(&self, id: &str) -> Result<()>;
    async fn get_watchers_for_target(&self, target_session_id: &str) -> Result<Vec<WatcherRelation>>;
    async fn get_targets_for_watcher(&self, watcher_session_id: &str) -> Result<Vec<WatcherRelation>>;
    async fn list_watchers(&self) -> Result<Vec<WatcherRelation>>;
    async fn save_user(&self, user: &UserData) -> Result<()>;
    async fn load_user(&self, id: &str) -> Result<Option<UserData>>;
    async fn load_user_by_username(&self, username: &str) -> Result<Option<UserData>>;
    async fn delete_user(&self, id: &str) -> Result<()>;
    async fn list_users(&self) -> Result<Vec<UserData>>;
}
