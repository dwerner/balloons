use async_trait::async_trait;
use chrono::DateTime;
use heed::types::{Bytes, Str};
use heed::{Database, Env, EnvOpenOptions};
use std::path::Path;
use std::sync::Arc;

use crate::generated::{SessionData, SessionMetadata, TurnData, TurnOrder};
use super::traits::{Error, Result, StorageEngine};

/// Parse an ISO 8601 timestamp string to Unix timestamp (seconds).
/// Returns 0 if parsing fails (graceful fallback for legacy data).
fn parse_iso_to_unix(iso_str: &str) -> i64 {
    // Try parsing with timezone info first (e.g., "2024-01-01T00:00:00Z")
    if let Ok(dt) = DateTime::parse_from_rfc3339(iso_str) {
        return dt.timestamp();
    }
    // Try parsing as UTC without timezone suffix (e.g., "2024-01-01T00:00:00")
    if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(iso_str, "%Y-%m-%dT%H:%M:%S") {
        return dt.and_utc().timestamp();
    }
    // Try parsing date-only format (e.g., "2024-01-01")
    if let Ok(dt) = chrono::NaiveDate::parse_from_str(iso_str, "%Y-%m-%d") {
        return dt.and_hms_opt(0, 0, 0).map(|dt| dt.and_utc().timestamp()).unwrap_or(0);
    }
    0 // Fallback for unparseable timestamps
}

/// Default map size: 1GB
/// This is the maximum size the database can grow to. LMDB requires this to be
/// set upfront. If we hit MDB_MAP_FULL, we can reopen with a larger size.
const DEFAULT_MAP_SIZE: usize = 1024 * 1024 * 1024; // 1GB

/// LMDB-backed storage engine using heed
///
/// Uses the same table structure as the previous redb implementation:
/// - SESSIONS: session_id → JSON-encoded SessionData
/// - TURNS: turn_id → JSON-encoded TurnData
/// - TURN_ORDER: session_id → JSON-encoded TurnOrder
pub struct LmdbEngine {
    env: Arc<Env>,
    sessions: Database<Str, Bytes>,
    turns: Database<Str, Bytes>,
    turn_order: Database<Str, Bytes>,
}

impl LmdbEngine {
    /// Open or create a database at the given path
    ///
    /// The path should be a directory (LMDB uses a directory, not a single file).
    /// If the directory doesn't exist, it will be created.
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        Self::open_with_map_size(path, DEFAULT_MAP_SIZE)
    }

    /// Open with a custom map size (useful for testing or when you know you need more space)
    pub fn open_with_map_size(path: impl AsRef<Path>, map_size: usize) -> Result<Self> {
        let path = path.as_ref();

        // Create directory if it doesn't exist
        std::fs::create_dir_all(path)?;

        let env = unsafe {
            EnvOpenOptions::new()
                .map_size(map_size)
                .max_dbs(3) // sessions, turns, turn_order
                .open(path)
                .map_err(|e| Error::Database(e.to_string()))?
        };

        // Create databases (tables)
        let mut wtxn = env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        let sessions = env
            .create_database(&mut wtxn, Some("sessions"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let turns = env
            .create_database(&mut wtxn, Some("turns"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let turn_order = env
            .create_database(&mut wtxn, Some("turn_order"))
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(Self {
            env: Arc::new(env),
            sessions,
            turns,
            turn_order,
        })
    }
}

#[async_trait]
impl StorageEngine for LmdbEngine {
    async fn save_session(&self, id: &str, data: &SessionData) -> Result<()> {
        let bytes = serde_json::to_vec(data).map_err(|e| Error::Serialization(e.to_string()))?;

        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;
        self.sessions
            .put(&mut wtxn, id, &bytes)
            .map_err(|e| Error::Database(e.to_string()))?;
        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn load_session(&self, id: &str) -> Result<Option<SessionData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        match self.sessions.get(&rtxn, id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => {
                let data: SessionData = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                Ok(Some(data))
            }
            None => Ok(None),
        }
    }

    async fn save_turn(&self, session_id: &str, turn: &TurnData) -> Result<()> {
        // Verify session exists
        let _ = self
            .load_session(session_id)
            .await?
            .ok_or_else(|| Error::SessionNotFound(session_id.to_string()))?;

        let turn_bytes = serde_json::to_vec(turn).map_err(|e| Error::Serialization(e.to_string()))?;

        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Save turn to turns table
        self.turns
            .put(&mut wtxn, &turn.id, &turn_bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        // Update turn order
        let mut turn_order = match self.turn_order
            .get(&wtxn, session_id)
            .map_err(|e| Error::Database(e.to_string()))?
        {
            Some(bytes) => serde_json::from_slice::<TurnOrder>(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => TurnOrder {
                session_id: session_id.to_string(),
                turn_ids: vec![],
            },
        };

        // Add turn ID if not already present (upsert semantics)
        if !turn_order.turn_ids.contains(&turn.id) {
            turn_order.turn_ids.push(turn.id.clone());
        }

        let order_bytes = serde_json::to_vec(&turn_order).map_err(|e| Error::Serialization(e.to_string()))?;
        self.turn_order
            .put(&mut wtxn, session_id, &order_bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn load_turns(&self, session_id: &str) -> Result<Vec<TurnData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Get turn order
        let turn_order = match self.turn_order
            .get(&rtxn, session_id)
            .map_err(|e| Error::Database(e.to_string()))?
        {
            Some(bytes) => serde_json::from_slice::<TurnOrder>(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => return Ok(vec![]), // No turns for this session
        };

        // Load turns in order
        let mut turns = Vec::with_capacity(turn_order.turn_ids.len());
        for turn_id in &turn_order.turn_ids {
            if let Some(bytes) = self.turns
                .get(&rtxn, turn_id)
                .map_err(|e| Error::Database(e.to_string()))?
            {
                let turn: TurnData = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                turns.push(turn);
            }
            // Note: We silently skip missing turns (orphaned references)
        }

        Ok(turns)
    }

    async fn delete_turn(&self, session_id: &str, turn_id: &str) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Remove from turn order first
        let mut turn_order = match self.turn_order
            .get(&wtxn, session_id)
            .map_err(|e| Error::Database(e.to_string()))?
        {
            Some(bytes) => serde_json::from_slice::<TurnOrder>(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => return Err(Error::SessionNotFound(session_id.to_string())),
        };

        let original_len = turn_order.turn_ids.len();
        turn_order.turn_ids.retain(|id| id != turn_id);

        if turn_order.turn_ids.len() == original_len {
            return Err(Error::TurnNotFound(turn_id.to_string()));
        }

        let order_bytes = serde_json::to_vec(&turn_order).map_err(|e| Error::Serialization(e.to_string()))?;
        self.turn_order
            .put(&mut wtxn, session_id, &order_bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        // Remove from turns table
        self.turns
            .delete(&mut wtxn, turn_id)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn reorder_turns(&self, session_id: &str, turn_ids: &[String]) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Verify session has a turn order
        let turn_order = match self.turn_order
            .get(&wtxn, session_id)
            .map_err(|e| Error::Database(e.to_string()))?
        {
            Some(bytes) => serde_json::from_slice::<TurnOrder>(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => return Err(Error::SessionNotFound(session_id.to_string())),
        };

        // Verify all turn_ids exist in current order
        for id in turn_ids {
            if !turn_order.turn_ids.contains(id) {
                return Err(Error::TurnNotFound(id.clone()));
            }
        }

        // Create new order
        let new_order = TurnOrder {
            session_id: session_id.to_string(),
            turn_ids: turn_ids.to_vec(),
        };

        let order_bytes = serde_json::to_vec(&new_order).map_err(|e| Error::Serialization(e.to_string()))?;
        self.turn_order
            .put(&mut wtxn, session_id, &order_bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn list_sessions(&self) -> Result<Vec<SessionMetadata>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        let mut sessions = Vec::new();

        for entry in self.sessions.iter(&rtxn).map_err(|e| Error::Database(e.to_string()))? {
            let (key, value) = entry.map_err(|e| Error::Database(e.to_string()))?;
            let data: SessionData = serde_json::from_slice(value)
                .map_err(|e| Error::Serialization(e.to_string()))?;

            // Get turn count from turn order table
            let turn_count = match self.turn_order
                .get(&rtxn, key)
                .map_err(|e| Error::Database(e.to_string()))?
            {
                Some(bytes) => {
                    let order: TurnOrder = serde_json::from_slice(bytes)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    order.turn_ids.len() as i64
                }
                None => 0,
            };

            sessions.push(SessionMetadata {
                id: data.id,
                name: data.title.clone(),
                created_at: parse_iso_to_unix(&data.created),
                updated_at: parse_iso_to_unix(&data.last_modified),
                turn_count,
            });
        }

        Ok(sessions)
    }

    async fn delete_session(&self, id: &str) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Get turn order to know which turns to delete
        let turn_ids_to_delete = match self.turn_order
            .get(&wtxn, id)
            .map_err(|e| Error::Database(e.to_string()))?
        {
            Some(bytes) => {
                let order: TurnOrder = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                order.turn_ids
            }
            None => vec![],
        };

        // Delete turn order
        self.turn_order
            .delete(&mut wtxn, id)
            .map_err(|e| Error::Database(e.to_string()))?;

        // Delete all turns
        for turn_id in turn_ids_to_delete {
            self.turns
                .delete(&mut wtxn, &turn_id)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        // Delete session
        self.sessions
            .delete(&mut wtxn, id)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn save_session_with_turns(
        &self,
        id: &str,
        session: &SessionData,
        turns: &[TurnData],
    ) -> Result<()> {
        let session_bytes = serde_json::to_vec(session)
            .map_err(|e| Error::Serialization(e.to_string()))?;

        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Save session
        self.sessions
            .put(&mut wtxn, id, &session_bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        // Get existing turn order (if any) to merge with new turns
        let mut existing_turn_ids: Vec<String> = match self.turn_order
            .get(&wtxn, id)
            .map_err(|e| Error::Database(e.to_string()))?
        {
            Some(bytes) => {
                let order: TurnOrder = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                order.turn_ids
            }
            None => vec![],
        };

        // Save each turn and update the order
        for turn in turns {
            let turn_bytes = serde_json::to_vec(turn)
                .map_err(|e| Error::Serialization(e.to_string()))?;

            self.turns
                .put(&mut wtxn, &turn.id, &turn_bytes)
                .map_err(|e| Error::Database(e.to_string()))?;

            // Add to order if not already present
            if !existing_turn_ids.contains(&turn.id) {
                existing_turn_ids.push(turn.id.clone());
            }
        }

        // Save updated turn order
        let turn_order = TurnOrder {
            session_id: id.to_string(),
            turn_ids: existing_turn_ids,
        };
        let order_bytes = serde_json::to_vec(&turn_order)
            .map_err(|e| Error::Serialization(e.to_string()))?;
        self.turn_order
            .put(&mut wtxn, id, &order_bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn replace_session_turns(
        &self,
        session_id: &str,
        turns: &[TurnData],
    ) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Verify session exists
        if self.sessions
            .get(&wtxn, session_id)
            .map_err(|e| Error::Database(e.to_string()))?
            .is_none()
        {
            return Err(Error::SessionNotFound(session_id.to_string()));
        }

        // Get existing turn IDs to delete
        let old_turn_ids: Vec<String> = match self.turn_order
            .get(&wtxn, session_id)
            .map_err(|e| Error::Database(e.to_string()))?
        {
            Some(bytes) => {
                let order: TurnOrder = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                order.turn_ids
            }
            None => vec![],
        };

        // Build set of new turn IDs for efficient lookup
        let new_turn_ids: std::collections::HashSet<&str> = turns.iter()
            .map(|t| t.id.as_str())
            .collect();

        // Delete turns that are no longer present
        for old_id in &old_turn_ids {
            if !new_turn_ids.contains(old_id.as_str()) {
                self.turns
                    .delete(&mut wtxn, old_id)
                    .map_err(|e| Error::Database(e.to_string()))?;
            }
        }

        // Insert/update all new turns
        let mut ordered_ids = Vec::with_capacity(turns.len());
        for turn in turns {
            let turn_bytes = serde_json::to_vec(turn)
                .map_err(|e| Error::Serialization(e.to_string()))?;

            self.turns
                .put(&mut wtxn, &turn.id, &turn_bytes)
                .map_err(|e| Error::Database(e.to_string()))?;

            ordered_ids.push(turn.id.clone());
        }

        // Update turn order
        let turn_order = TurnOrder {
            session_id: session_id.to_string(),
            turn_ids: ordered_ids,
        };
        let order_bytes = serde_json::to_vec(&turn_order)
            .map_err(|e| Error::Serialization(e.to_string()))?;
        self.turn_order
            .put(&mut wtxn, session_id, &order_bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TestDir;
    use futures_lite::future;

    fn make_session(id: &str, title: &str) -> SessionData {
        SessionData {
            id: id.to_string(),
            created: "2024-01-01T00:00:00Z".to_string(),
            last_modified: "2024-01-01T00:00:00Z".to_string(),
            model: "test-model".to_string(),
            total_input_tokens: 0,
            total_output_tokens: 0,
            total_cost: 0.0,
            context_window: 200000,
            parent_id: None,
            children: vec![],
            returned: false,
            return_condition: "manual".to_string(),
            working_directories: vec![],
            title: title.to_string(),
            summary: String::new(),
            fork_name: String::new(),
            fork_status: "active".to_string(),
            fork_point_turn: -1,
            merge_point_turn: -1,
            merge_message: String::new(),
            backend_name: String::new(),
            cached_context_tokens: 0,
            message_queue: serde_json::json!({}),
        }
    }

    fn make_turn(id: &str, role: &str, content: &str) -> TurnData {
        TurnData {
            id: id.to_string(),
            role: role.to_string(),
            content_block: serde_json::json!({"type": "text", "text": content}),
            tokens: 100,
            timestamp: "2024-01-01T00:00:00Z".to_string(),
            context_mode: "compress".to_string(),
            summary: String::new(),
            exchange_id: None,
        }
    }

    /// Extract text content from a turn's content_block for testing
    fn get_turn_text(turn: &TurnData) -> String {
        turn.content_block
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    }

    #[test]
    fn test_open_creates_db() {
        let dir = TestDir::new("lmdb_test_open_creates_db");
        let db_path = dir.db_path();

        let engine = LmdbEngine::open(&db_path).unwrap();
        drop(engine);

        assert!(db_path.exists());
        assert!(db_path.is_dir()); // LMDB uses a directory
    }

    #[test]
    fn test_save_and_load_session() {
        let dir = TestDir::new("lmdb_test_save_and_load_session");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Test Session");

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            let loaded = engine.load_session("sess-1").await.unwrap();

            assert!(loaded.is_some());
            let loaded = loaded.unwrap();
            assert_eq!(loaded.id, "sess-1");
            assert_eq!(loaded.title, "Test Session");
        });
    }

    #[test]
    fn test_load_nonexistent_session() {
        let dir = TestDir::new("lmdb_test_load_nonexistent_session");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        future::block_on(async {
            let loaded = engine.load_session("nonexistent").await.unwrap();
            assert!(loaded.is_none());
        });
    }

    #[test]
    fn test_save_and_load_turns() {
        let dir = TestDir::new("lmdb_test_save_and_load_turns");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Test Session");
        let turn1 = make_turn("turn-1", "user", "Hello");
        let turn2 = make_turn("turn-2", "assistant", "Hi there!");

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            engine.save_turn("sess-1", &turn1).await.unwrap();
            engine.save_turn("sess-1", &turn2).await.unwrap();

            let turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(turns.len(), 2);
            assert_eq!(turns[0].id, "turn-1");
            assert_eq!(turns[1].id, "turn-2");
        });
    }

    #[test]
    fn test_update_existing_turn() {
        let dir = TestDir::new("lmdb_test_update_existing_turn");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Test Session");
        let turn = make_turn("turn-1", "user", "Hello");
        let updated_turn = make_turn("turn-1", "user", "Hello, updated!");

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            engine.save_turn("sess-1", &turn).await.unwrap();
            engine.save_turn("sess-1", &updated_turn).await.unwrap();

            let turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(turns.len(), 1);
            assert_eq!(get_turn_text(&turns[0]), "Hello, updated!");
        });
    }

    #[test]
    fn test_delete_turn() {
        let dir = TestDir::new("lmdb_test_delete_turn");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Test Session");
        let turn1 = make_turn("turn-1", "user", "Hello");
        let turn2 = make_turn("turn-2", "assistant", "Hi there!");

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            engine.save_turn("sess-1", &turn1).await.unwrap();
            engine.save_turn("sess-1", &turn2).await.unwrap();
            engine.delete_turn("sess-1", "turn-1").await.unwrap();

            let turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(turns.len(), 1);
            assert_eq!(turns[0].id, "turn-2");
        });
    }

    #[test]
    fn test_delete_nonexistent_turn() {
        let dir = TestDir::new("lmdb_test_delete_nonexistent_turn");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Test Session");

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            let result = engine.delete_turn("sess-1", "nonexistent").await;
            // Session exists but has no turns, so turn order doesn't exist
            assert!(matches!(result, Err(Error::SessionNotFound(_))));
        });
    }

    #[test]
    fn test_delete_turn_not_in_order() {
        let dir = TestDir::new("lmdb_test_delete_turn_not_in_order");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Test Session");
        let turn = make_turn("turn-1", "user", "Hello");

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            engine.save_turn("sess-1", &turn).await.unwrap();
            let result = engine.delete_turn("sess-1", "nonexistent").await;
            assert!(matches!(result, Err(Error::TurnNotFound(_))));
        });
    }

    #[test]
    fn test_reorder_turns() {
        let dir = TestDir::new("lmdb_test_reorder_turns");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Test Session");
        let turn1 = make_turn("turn-1", "user", "First");
        let turn2 = make_turn("turn-2", "user", "Second");
        let turn3 = make_turn("turn-3", "user", "Third");

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            engine.save_turn("sess-1", &turn1).await.unwrap();
            engine.save_turn("sess-1", &turn2).await.unwrap();
            engine.save_turn("sess-1", &turn3).await.unwrap();

            // Reorder: 3, 1, 2
            engine
                .reorder_turns(
                    "sess-1",
                    &[
                        "turn-3".to_string(),
                        "turn-1".to_string(),
                        "turn-2".to_string(),
                    ],
                )
                .await
                .unwrap();

            let turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(turns[0].id, "turn-3");
            assert_eq!(turns[1].id, "turn-1");
            assert_eq!(turns[2].id, "turn-2");
        });
    }

    #[test]
    fn test_list_sessions() {
        let dir = TestDir::new("lmdb_test_list_sessions");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session1 = make_session("sess-1", "First Session");
        let session2 = make_session("sess-2", "Second Session");
        let turn = make_turn("turn-1", "user", "Hello");

        future::block_on(async {
            engine.save_session("sess-1", &session1).await.unwrap();
            engine.save_session("sess-2", &session2).await.unwrap();
            engine.save_turn("sess-2", &turn).await.unwrap();

            let sessions = engine.list_sessions().await.unwrap();
            assert_eq!(sessions.len(), 2);

            // Find session2 and verify turn count
            let sess2_meta = sessions.iter().find(|s| s.id == "sess-2").unwrap();
            assert_eq!(sess2_meta.turn_count, 1);

            // Find session1 and verify zero turns
            let sess1_meta = sessions.iter().find(|s| s.id == "sess-1").unwrap();
            assert_eq!(sess1_meta.turn_count, 0);

            // Verify timestamps are parsed (2024-01-01T00:00:00Z = 1704067200)
            assert_eq!(sess1_meta.created_at, 1704067200);
            assert_eq!(sess1_meta.updated_at, 1704067200);
        });
    }

    #[test]
    fn test_parse_iso_to_unix() {
        // RFC3339 with Z suffix
        assert_eq!(parse_iso_to_unix("2024-01-01T00:00:00Z"), 1704067200);
        // RFC3339 with timezone offset
        assert_eq!(parse_iso_to_unix("2024-01-01T00:00:00+00:00"), 1704067200);
        // Without timezone (treated as UTC)
        assert_eq!(parse_iso_to_unix("2024-01-01T00:00:00"), 1704067200);
        // Date only
        assert_eq!(parse_iso_to_unix("2024-01-01"), 1704067200);
        // Invalid format returns 0
        assert_eq!(parse_iso_to_unix("not-a-date"), 0);
        assert_eq!(parse_iso_to_unix(""), 0);
    }

    #[test]
    fn test_delete_session() {
        let dir = TestDir::new("lmdb_test_delete_session");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Test Session");

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            engine.delete_session("sess-1").await.unwrap();

            let loaded = engine.load_session("sess-1").await.unwrap();
            assert!(loaded.is_none());
        });
    }

    #[test]
    fn test_delete_session_with_turns() {
        let dir = TestDir::new("lmdb_test_delete_session_with_turns");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Test Session");
        let turn1 = make_turn("turn-1", "user", "Hello");
        let turn2 = make_turn("turn-2", "assistant", "Hi!");

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            engine.save_turn("sess-1", &turn1).await.unwrap();
            engine.save_turn("sess-1", &turn2).await.unwrap();

            // Verify turns exist
            let turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(turns.len(), 2);

            // Delete session
            engine.delete_session("sess-1").await.unwrap();

            // Verify session is gone
            let loaded = engine.load_session("sess-1").await.unwrap();
            assert!(loaded.is_none());

            // Verify turns are gone
            let turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(turns.len(), 0);
        });
    }

    #[test]
    fn test_persistence_across_reopen() {
        let dir = TestDir::new("lmdb_test_persistence_across_reopen");
        let db_path = dir.db_path();

        let session = make_session("sess-1", "Persistent Session");
        let turn = make_turn("turn-1", "user", "Hello");

        // Save and close
        {
            let engine = LmdbEngine::open(&db_path).unwrap();
            future::block_on(async {
                engine.save_session("sess-1", &session).await.unwrap();
                engine.save_turn("sess-1", &turn).await.unwrap();
            });
        }

        // Reopen and verify
        {
            let engine = LmdbEngine::open(&db_path).unwrap();
            future::block_on(async {
                let loaded = engine.load_session("sess-1").await.unwrap();
                assert!(loaded.is_some());
                assert_eq!(loaded.unwrap().title, "Persistent Session");

                let turns = engine.load_turns("sess-1").await.unwrap();
                assert_eq!(turns.len(), 1);
                assert_eq!(turns[0].id, "turn-1");
            });
        }
    }

    #[test]
    fn test_turns_independent_of_session() {
        // Verify that turns can be loaded even after session is reloaded
        let dir = TestDir::new("lmdb_test_turns_independent");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Test Session");
        let turn1 = make_turn("turn-1", "user", "Hello");
        let turn2 = make_turn("turn-2", "assistant", "Hi!");

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            engine.save_turn("sess-1", &turn1).await.unwrap();
            engine.save_turn("sess-1", &turn2).await.unwrap();

            // Update session metadata (shouldn't affect turns)
            let mut updated_session = session.clone();
            updated_session.title = "Updated Title".to_string();
            engine.save_session("sess-1", &updated_session).await.unwrap();

            // Verify turns are still intact
            let turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(turns.len(), 2);
            assert_eq!(get_turn_text(&turns[0]), "Hello");
            assert_eq!(get_turn_text(&turns[1]), "Hi!");
        });
    }

    // =========================================================================
    // Batch Operation Tests
    // =========================================================================

    #[test]
    fn test_save_session_with_turns() {
        let dir = TestDir::new("lmdb_test_save_session_with_turns");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Batch Session");
        let turns = vec![
            make_turn("turn-1", "user", "Hello"),
            make_turn("turn-2", "assistant", "Hi there!"),
            make_turn("turn-3", "user", "How are you?"),
        ];

        future::block_on(async {
            // Save session with all turns atomically
            engine.save_session_with_turns("sess-1", &session, &turns).await.unwrap();

            // Verify session was saved
            let loaded = engine.load_session("sess-1").await.unwrap();
            assert!(loaded.is_some());
            assert_eq!(loaded.unwrap().title, "Batch Session");

            // Verify all turns were saved in order
            let loaded_turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(loaded_turns.len(), 3);
            assert_eq!(loaded_turns[0].id, "turn-1");
            assert_eq!(loaded_turns[1].id, "turn-2");
            assert_eq!(loaded_turns[2].id, "turn-3");
            assert_eq!(get_turn_text(&loaded_turns[0]), "Hello");
        });
    }

    #[test]
    fn test_save_session_with_turns_preserves_existing() {
        let dir = TestDir::new("lmdb_test_save_session_with_turns_preserves");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Session");
        let turn1 = make_turn("turn-1", "user", "First");

        future::block_on(async {
            // Save initial session with one turn
            engine.save_session("sess-1", &session).await.unwrap();
            engine.save_turn("sess-1", &turn1).await.unwrap();

            // Now save with additional turns (should preserve turn-1)
            let new_turns = vec![
                make_turn("turn-2", "assistant", "Second"),
                make_turn("turn-3", "user", "Third"),
            ];
            engine.save_session_with_turns("sess-1", &session, &new_turns).await.unwrap();

            // All three turns should exist
            let loaded_turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(loaded_turns.len(), 3);
            assert_eq!(loaded_turns[0].id, "turn-1");
            assert_eq!(loaded_turns[1].id, "turn-2");
            assert_eq!(loaded_turns[2].id, "turn-3");
        });
    }

    #[test]
    fn test_replace_session_turns() {
        let dir = TestDir::new("lmdb_test_replace_session_turns");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Session");
        let initial_turns = vec![
            make_turn("turn-1", "user", "First"),
            make_turn("turn-2", "assistant", "Second"),
            make_turn("turn-3", "user", "Third"),
        ];

        future::block_on(async {
            // Save initial session with turns
            engine.save_session_with_turns("sess-1", &session, &initial_turns).await.unwrap();

            // Replace with different turns (keep turn-2, remove turn-1 and turn-3, add turn-4)
            let replacement_turns = vec![
                make_turn("turn-2", "assistant", "Second (updated)"),
                make_turn("turn-4", "user", "Fourth"),
            ];
            engine.replace_session_turns("sess-1", &replacement_turns).await.unwrap();

            // Verify only the replacement turns exist, in order
            let loaded_turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(loaded_turns.len(), 2);
            assert_eq!(loaded_turns[0].id, "turn-2");
            assert_eq!(loaded_turns[1].id, "turn-4");
            assert_eq!(get_turn_text(&loaded_turns[0]), "Second (updated)");
            assert_eq!(get_turn_text(&loaded_turns[1]), "Fourth");
        });
    }

    #[test]
    fn test_replace_session_turns_empty() {
        let dir = TestDir::new("lmdb_test_replace_session_turns_empty");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Session");
        let turns = vec![
            make_turn("turn-1", "user", "Hello"),
            make_turn("turn-2", "assistant", "Hi!"),
        ];

        future::block_on(async {
            engine.save_session_with_turns("sess-1", &session, &turns).await.unwrap();

            // Replace with empty list (delete all turns)
            engine.replace_session_turns("sess-1", &[]).await.unwrap();

            // Verify no turns remain
            let loaded_turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(loaded_turns.len(), 0);

            // Session should still exist
            let loaded = engine.load_session("sess-1").await.unwrap();
            assert!(loaded.is_some());
        });
    }

    #[test]
    fn test_replace_session_turns_nonexistent_session() {
        let dir = TestDir::new("lmdb_test_replace_turns_nonexistent");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let turns = vec![make_turn("turn-1", "user", "Hello")];

        future::block_on(async {
            let result = engine.replace_session_turns("nonexistent", &turns).await;
            assert!(matches!(result, Err(Error::SessionNotFound(_))));
        });
    }
}
