use std::sync::Arc;

use crate::generated::{SessionData, SessionMetadata, TurnData, UserData, UserPrefs, WatcherRelation};
use super::traits::{Result, StorageEngine};

pub struct StorageClient {
    engine: Arc<dyn StorageEngine>,
}

impl StorageClient {
    pub fn new(engine: impl StorageEngine + 'static) -> Self {
        Self { engine: Arc::new(engine) }
    }

    pub async fn save_session(&self, id: &str, data: &SessionData) -> Result<()> { self.engine.save_session(id, data).await }
    pub async fn load_session(&self, id: &str) -> Result<Option<SessionData>> { self.engine.load_session(id).await }
    pub async fn save_turn(&self, session_id: &str, turn: &TurnData) -> Result<()> { self.engine.save_turn(session_id, turn).await }
    pub async fn load_turns(&self, session_id: &str) -> Result<Vec<TurnData>> { self.engine.load_turns(session_id).await }
    pub async fn get_turn_count(&self, session_id: &str) -> Result<usize> { self.engine.get_turn_count(session_id).await }
    pub async fn load_turns_range(&self, session_id: &str, offset: usize, limit: usize) -> Result<Vec<TurnData>> {
        self.engine.load_turns_range(session_id, offset, limit).await
    }
    pub async fn delete_turn(&self, session_id: &str, turn_id: &str) -> Result<()> { self.engine.delete_turn(session_id, turn_id).await }
    pub async fn reorder_turns(&self, session_id: &str, turn_ids: &[String]) -> Result<()> { self.engine.reorder_turns(session_id, turn_ids).await }
    pub async fn list_sessions(&self) -> Result<Vec<SessionMetadata>> { self.engine.list_sessions().await }
    pub async fn delete_session(&self, id: &str) -> Result<()> { self.engine.delete_session(id).await }
    pub async fn save_session_with_turns(&self, id: &str, session: &SessionData, turns: &[TurnData]) -> Result<()> {
        self.engine.save_session_with_turns(id, session, turns).await
    }
    pub async fn replace_session_turns(&self, session_id: &str, turns: &[TurnData]) -> Result<()> {
        self.engine.replace_session_turns(session_id, turns).await
    }
    pub async fn load_session_history(&self) -> Result<Vec<String>> { self.engine.load_session_history().await }
    pub async fn save_session_history(&self, session_ids: &[String]) -> Result<()> { self.engine.save_session_history(session_ids).await }
    pub async fn load_user_prefs(&self) -> Result<UserPrefs> { self.engine.load_user_prefs().await }
    pub async fn save_user_prefs(&self, prefs: &UserPrefs) -> Result<()> { self.engine.save_user_prefs(prefs).await }
    pub async fn save_watcher(&self, watcher: &WatcherRelation) -> Result<()> { self.engine.save_watcher(watcher).await }
    pub async fn delete_watcher(&self, id: &str) -> Result<()> { self.engine.delete_watcher(id).await }
    pub async fn get_watchers_for_target(&self, target_session_id: &str) -> Result<Vec<WatcherRelation>> { self.engine.get_watchers_for_target(target_session_id).await }
    pub async fn get_targets_for_watcher(&self, watcher_session_id: &str) -> Result<Vec<WatcherRelation>> { self.engine.get_targets_for_watcher(watcher_session_id).await }
    pub async fn list_watchers(&self) -> Result<Vec<WatcherRelation>> { self.engine.list_watchers().await }
    pub async fn save_user(&self, user: &UserData) -> Result<()> { self.engine.save_user(user).await }
    pub async fn load_user(&self, id: &str) -> Result<Option<UserData>> { self.engine.load_user(id).await }
    pub async fn load_user_by_username(&self, username: &str) -> Result<Option<UserData>> { self.engine.load_user_by_username(username).await }
    pub async fn delete_user(&self, id: &str) -> Result<()> { self.engine.delete_user(id).await }
    pub async fn list_users(&self) -> Result<Vec<UserData>> { self.engine.list_users().await }
}
