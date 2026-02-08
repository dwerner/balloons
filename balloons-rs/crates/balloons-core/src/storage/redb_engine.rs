use async_trait::async_trait;
use redb::{Database, ReadableTable, TableDefinition};
use std::path::Path;
use std::sync::Arc;

use crate::generated::{SessionData, SessionMetadata, TurnData};
use super::traits::{Error, Result, StorageEngine};

// Table definitions
// Key: session_id, Value: JSON-encoded SessionData
// Note: We use JSON instead of postcard because the schema contains serde_json::Value
// fields (for flexible content_block storage), and postcard doesn't support self-describing types.
const SESSIONS: TableDefinition<&str, &[u8]> = TableDefinition::new("sessions");

/// Redb-backed storage engine with JSON serialization
pub struct RedbEngine {
    db: Arc<Database>,
}

impl RedbEngine {
    /// Open or create a database at the given path
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let db = Database::create(path).map_err(|e| Error::Database(e.to_string()))?;

        // Ensure tables exist
        let write_txn = db.begin_write().map_err(|e| Error::Database(e.to_string()))?;
        {
            // Opening the table creates it if it doesn't exist
            let _ = write_txn
                .open_table(SESSIONS)
                .map_err(|e| Error::Database(e.to_string()))?;
        }
        write_txn
            .commit()
            .map_err(|e| Error::Database(e.to_string()))?;

        Ok(Self { db: Arc::new(db) })
    }
}

#[async_trait]
impl StorageEngine for RedbEngine {
    async fn save_session(&self, id: &str, data: &SessionData) -> Result<()> {
        let bytes =
            serde_json::to_vec(data).map_err(|e| Error::Serialization(e.to_string()))?;

        let write_txn = self
            .db
            .begin_write()
            .map_err(|e| Error::Database(e.to_string()))?;
        {
            let mut table = write_txn
                .open_table(SESSIONS)
                .map_err(|e| Error::Database(e.to_string()))?;
            table
                .insert(id, bytes.as_slice())
                .map_err(|e| Error::Database(e.to_string()))?;
        }
        write_txn
            .commit()
            .map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn load_session(&self, id: &str) -> Result<Option<SessionData>> {
        let read_txn = self
            .db
            .begin_read()
            .map_err(|e| Error::Database(e.to_string()))?;
        let table = read_txn
            .open_table(SESSIONS)
            .map_err(|e| Error::Database(e.to_string()))?;

        match table.get(id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => {
                let data: SessionData = serde_json::from_slice(bytes.value())
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                Ok(Some(data))
            }
            None => Ok(None),
        }
    }

    async fn save_turn(&self, session_id: &str, turn: &TurnData) -> Result<()> {
        // Load session, update turn, save session
        let mut session = self
            .load_session(session_id)
            .await?
            .ok_or_else(|| Error::SessionNotFound(session_id.to_string()))?;

        // Find and update or append turn
        if let Some(existing) = session.turns.iter_mut().find(|t| t.id == turn.id) {
            *existing = turn.clone();
        } else {
            session.turns.push(turn.clone());
        }

        self.save_session(session_id, &session).await
    }

    async fn load_turns(&self, session_id: &str) -> Result<Vec<TurnData>> {
        match self.load_session(session_id).await? {
            Some(session) => Ok(session.turns),
            None => Ok(vec![]),
        }
    }

    async fn delete_turn(&self, session_id: &str, turn_id: &str) -> Result<()> {
        let mut session = self
            .load_session(session_id)
            .await?
            .ok_or_else(|| Error::SessionNotFound(session_id.to_string()))?;

        let original_len = session.turns.len();
        session.turns.retain(|t| t.id != turn_id);

        if session.turns.len() == original_len {
            return Err(Error::TurnNotFound(turn_id.to_string()));
        }

        self.save_session(session_id, &session).await
    }

    async fn reorder_turns(&self, session_id: &str, turn_ids: &[String]) -> Result<()> {
        let mut session = self
            .load_session(session_id)
            .await?
            .ok_or_else(|| Error::SessionNotFound(session_id.to_string()))?;

        // Build a map of turn_id -> TurnData
        let turn_map: std::collections::HashMap<_, _> = session
            .turns
            .drain(..)
            .map(|t| (t.id.clone(), t))
            .collect();

        // Rebuild turns in the specified order
        for id in turn_ids {
            if let Some(turn) = turn_map.get(id) {
                session.turns.push(turn.clone());
            } else {
                return Err(Error::TurnNotFound(id.clone()));
            }
        }

        self.save_session(session_id, &session).await
    }

    async fn list_sessions(&self) -> Result<Vec<SessionMetadata>> {
        let read_txn = self
            .db
            .begin_read()
            .map_err(|e| Error::Database(e.to_string()))?;
        let table = read_txn
            .open_table(SESSIONS)
            .map_err(|e| Error::Database(e.to_string()))?;

        let mut sessions = Vec::new();
        for entry in table.iter().map_err(|e| Error::Database(e.to_string()))? {
            let (_, value) = entry.map_err(|e| Error::Database(e.to_string()))?;
            let data: SessionData = serde_json::from_slice(value.value())
                .map_err(|e| Error::Serialization(e.to_string()))?;

            sessions.push(SessionMetadata {
                id: data.id,
                name: data.title.clone(),
                created_at: 0, // TODO: parse ISO timestamp to unix
                updated_at: 0, // TODO: parse ISO timestamp to unix
                turn_count: data.turns.len() as i64,
            });
        }

        Ok(sessions)
    }

    async fn delete_session(&self, id: &str) -> Result<()> {
        let write_txn = self
            .db
            .begin_write()
            .map_err(|e| Error::Database(e.to_string()))?;
        {
            let mut table = write_txn
                .open_table(SESSIONS)
                .map_err(|e| Error::Database(e.to_string()))?;
            table
                .remove(id)
                .map_err(|e| Error::Database(e.to_string()))?;
        }
        write_txn
            .commit()
            .map_err(|e| Error::Database(e.to_string()))?;

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
            turns: vec![],
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
        let dir = TestDir::new("test_open_creates_db");
        let db_path = dir.db_path();

        let engine = RedbEngine::open(&db_path).unwrap();
        drop(engine);

        assert!(db_path.exists());
    }

    #[test]
    fn test_save_and_load_session() {
        let dir = TestDir::new("test_save_and_load_session");
        let engine = RedbEngine::open(dir.db_path()).unwrap();

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
        let dir = TestDir::new("test_load_nonexistent_session");
        let engine = RedbEngine::open(dir.db_path()).unwrap();

        future::block_on(async {
            let loaded = engine.load_session("nonexistent").await.unwrap();
            assert!(loaded.is_none());
        });
    }

    #[test]
    fn test_save_and_load_turns() {
        let dir = TestDir::new("test_save_and_load_turns");
        let engine = RedbEngine::open(dir.db_path()).unwrap();

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
        let dir = TestDir::new("test_update_existing_turn");
        let engine = RedbEngine::open(dir.db_path()).unwrap();

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
        let dir = TestDir::new("test_delete_turn");
        let engine = RedbEngine::open(dir.db_path()).unwrap();

        let mut session = make_session("sess-1", "Test Session");
        session.turns.push(make_turn("turn-1", "user", "Hello"));
        session
            .turns
            .push(make_turn("turn-2", "assistant", "Hi there!"));

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            engine.delete_turn("sess-1", "turn-1").await.unwrap();

            let turns = engine.load_turns("sess-1").await.unwrap();
            assert_eq!(turns.len(), 1);
            assert_eq!(turns[0].id, "turn-2");
        });
    }

    #[test]
    fn test_delete_nonexistent_turn() {
        let dir = TestDir::new("test_delete_nonexistent_turn");
        let engine = RedbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Test Session");

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            let result = engine.delete_turn("sess-1", "nonexistent").await;
            assert!(matches!(result, Err(Error::TurnNotFound(_))));
        });
    }

    #[test]
    fn test_reorder_turns() {
        let dir = TestDir::new("test_reorder_turns");
        let engine = RedbEngine::open(dir.db_path()).unwrap();

        let mut session = make_session("sess-1", "Test Session");
        session.turns.push(make_turn("turn-1", "user", "First"));
        session.turns.push(make_turn("turn-2", "user", "Second"));
        session.turns.push(make_turn("turn-3", "user", "Third"));

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();

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
        let dir = TestDir::new("test_list_sessions");
        let engine = RedbEngine::open(dir.db_path()).unwrap();

        let session1 = make_session("sess-1", "First Session");
        let mut session2 = make_session("sess-2", "Second Session");
        session2.turns.push(make_turn("turn-1", "user", "Hello"));

        future::block_on(async {
            engine.save_session("sess-1", &session1).await.unwrap();
            engine.save_session("sess-2", &session2).await.unwrap();

            let sessions = engine.list_sessions().await.unwrap();
            assert_eq!(sessions.len(), 2);

            // Find session2 and verify turn count
            let sess2_meta = sessions.iter().find(|s| s.id == "sess-2").unwrap();
            assert_eq!(sess2_meta.turn_count, 1);
        });
    }

    #[test]
    fn test_delete_session() {
        let dir = TestDir::new("test_delete_session");
        let engine = RedbEngine::open(dir.db_path()).unwrap();

        let session = make_session("sess-1", "Test Session");

        future::block_on(async {
            engine.save_session("sess-1", &session).await.unwrap();
            engine.delete_session("sess-1").await.unwrap();

            let loaded = engine.load_session("sess-1").await.unwrap();
            assert!(loaded.is_none());
        });
    }

    #[test]
    fn test_persistence_across_reopen() {
        let dir = TestDir::new("test_persistence_across_reopen");
        let db_path = dir.db_path();

        let session = make_session("sess-1", "Persistent Session");

        // Save and close
        {
            let engine = RedbEngine::open(&db_path).unwrap();
            future::block_on(engine.save_session("sess-1", &session)).unwrap();
        }

        // Reopen and verify
        {
            let engine = RedbEngine::open(&db_path).unwrap();
            let loaded = future::block_on(engine.load_session("sess-1")).unwrap();
            assert!(loaded.is_some());
            assert_eq!(loaded.unwrap().title, "Persistent Session");
        }
    }
}
