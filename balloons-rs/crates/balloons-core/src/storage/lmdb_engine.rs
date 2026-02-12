use async_trait::async_trait;
use chrono::DateTime;
use heed::types::{Bytes, Str};
use heed::{Database, Env, EnvOpenOptions};
use std::path::Path;
use std::sync::Arc;

use crate::generated::{
    GoalData, PlanData, SessionBinding, SessionData, SessionMetadata, TodoData, TodoDependency,
    TodoPlanLink, TurnData, TurnOrder,
};
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

// ============================================================================
// Schema Versioning
// ============================================================================

/// Key used to store the schema version in the metadata table.
const SCHEMA_VERSION_KEY: &str = "__schema_version__";

/// Current schema version. Increment this when making breaking changes.
///
/// Version history:
/// - 1: Initial schema with goal system tables
const CURRENT_SCHEMA_VERSION: u32 = 1;

/// Result of checking the database schema version against the application's expected version.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SchemaStatus {
    /// Schema version matches - no action needed
    Current,
    /// Database has older schema - migrations available
    NeedsMigration { from: u32, to: u32 },
    /// Database has newer schema than application - cannot open safely
    TooNew { db_version: u32, app_version: u32 },
    /// Database has no version stamp (legacy or fresh database)
    Unversioned,
}

/// LMDB-backed storage engine using heed
///
/// ## Database Schema
///
/// ### Session Management
/// - `sessions`: session_id → JSON-encoded SessionData
/// - `turns`: turn_id → JSON-encoded TurnData
/// - `turn_order`: session_id → JSON-encoded TurnOrder (ordered list of turn_ids)
/// - `metadata`: key → value (for app-level metadata like session_history)
///
/// ### Goal System
///
/// Primary entity tables (key = entity id):
/// - `goals`: goal_id → JSON-encoded GoalData
/// - `plans`: plan_id → JSON-encoded PlanData
/// - `todos`: todo_id → JSON-encoded TodoData
///
/// Index tables for efficient lookups:
/// - `plans_by_goal`: goal_id → JSON-encoded Vec<plan_id>
///   Enables: "get all plans for a goal"
///
/// - `todos_by_plan`: plan_id → JSON-encoded Vec<todo_id>
///   Enables: "get all todos for a plan"
///   Note: A todo can belong to multiple plans (many-to-many via TodoPlanLink)
///
/// - `plans_by_todo`: todo_id → JSON-encoded Vec<plan_id>
///   Enables: "get all plans a todo belongs to" (reverse lookup)
///
/// - `todo_dependencies`: todo_id → JSON-encoded Vec<TodoDependency>
///   Enables: "get todos this todo depends on"
///
/// - `todo_dependents`: todo_id → JSON-encoded Vec<todo_id>
///   Enables: "get todos that depend on this todo" (reverse lookup)
///
/// Session binding tables:
/// - `session_bindings`: binding_id → JSON-encoded SessionBinding
///   Primary storage for all bindings
///
/// - `bindings_by_session`: session_id → JSON-encoded Vec<binding_id>
///   Enables: "get all bindings for a session"
///
/// - `bindings_by_entity`: "entity_type:entity_id" → JSON-encoded Vec<binding_id>
///   Enables: "get all sessions bound to a goal/plan/todo"
///
/// ## Key Design Decisions
///
/// 1. **Separate index tables vs composite keys**: Using index tables (like turn_order)
///    rather than composite keys because:
///    - Simpler key structure (just IDs)
///    - Easier to maintain ordering
///    - Consistent with existing session/turn pattern
///
/// 2. **Bidirectional indexes for many-to-many**: Both `todos_by_plan` and `plans_by_todo`
///    exist because we need efficient lookups in both directions.
///
/// 3. **Entity key format for bindings_by_entity**: Using "type:id" composite key
///    (e.g., "goal:abc123") to enable lookups by entity without scanning.
///
/// 4. **TodoPlanLink stored in indexes, not as separate table**: The link data is
///    simple enough that we store it implicitly in the index tables. The created_at
///    timestamp is stored in the Vec entries if needed.
pub struct LmdbEngine {
    env: Arc<Env>,

    // Session management (existing)
    sessions: Database<Str, Bytes>,
    turns: Database<Str, Bytes>,
    turn_order: Database<Str, Bytes>,
    metadata: Database<Str, Bytes>,

    // Goal system - primary entity tables
    goals: Database<Str, Bytes>,
    plans: Database<Str, Bytes>,
    todos: Database<Str, Bytes>,

    // Goal system - index tables for relationships
    plans_by_goal: Database<Str, Bytes>,   // goal_id → [plan_id]
    todos_by_plan: Database<Str, Bytes>,   // plan_id → [todo_id]
    plans_by_todo: Database<Str, Bytes>,   // todo_id → [plan_id] (reverse index)

    // Todo dependency tracking
    todo_dependencies: Database<Str, Bytes>, // todo_id → [TodoDependency]
    todo_dependents: Database<Str, Bytes>,   // todo_id → [todo_id] (reverse index)

    // Session bindings
    session_bindings: Database<Str, Bytes>,    // binding_id → SessionBinding
    bindings_by_session: Database<Str, Bytes>, // session_id → [binding_id]
    bindings_by_entity: Database<Str, Bytes>,  // "entity_type:entity_id" → [binding_id]
}

/// Key used for session history in the metadata table
const SESSION_HISTORY_KEY: &str = "session_history";

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

        // Database count: 4 session + 3 goal entities + 5 goal indexes + 3 binding = 15
        let env = unsafe {
            EnvOpenOptions::new()
                .map_size(map_size)
                .max_dbs(15)
                .open(path)
                .map_err(|e| Error::Database(e.to_string()))?
        };

        // Create databases (tables)
        let mut wtxn = env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Session management tables
        let sessions = env
            .create_database(&mut wtxn, Some("sessions"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let turns = env
            .create_database(&mut wtxn, Some("turns"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let turn_order = env
            .create_database(&mut wtxn, Some("turn_order"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let metadata = env
            .create_database(&mut wtxn, Some("metadata"))
            .map_err(|e| Error::Database(e.to_string()))?;

        // Goal system - primary entity tables
        let goals = env
            .create_database(&mut wtxn, Some("goals"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let plans = env
            .create_database(&mut wtxn, Some("plans"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let todos = env
            .create_database(&mut wtxn, Some("todos"))
            .map_err(|e| Error::Database(e.to_string()))?;

        // Goal system - relationship indexes
        let plans_by_goal = env
            .create_database(&mut wtxn, Some("plans_by_goal"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let todos_by_plan = env
            .create_database(&mut wtxn, Some("todos_by_plan"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let plans_by_todo = env
            .create_database(&mut wtxn, Some("plans_by_todo"))
            .map_err(|e| Error::Database(e.to_string()))?;

        // Todo dependency indexes
        let todo_dependencies = env
            .create_database(&mut wtxn, Some("todo_dependencies"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let todo_dependents = env
            .create_database(&mut wtxn, Some("todo_dependents"))
            .map_err(|e| Error::Database(e.to_string()))?;

        // Session binding tables
        let session_bindings = env
            .create_database(&mut wtxn, Some("session_bindings"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let bindings_by_session = env
            .create_database(&mut wtxn, Some("bindings_by_session"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let bindings_by_entity = env
            .create_database(&mut wtxn, Some("bindings_by_entity"))
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        let engine = Self {
            env: Arc::new(env),

            // Session management
            sessions,
            turns,
            turn_order,
            metadata,

            // Goal system entities
            goals,
            plans,
            todos,

            // Goal system indexes
            plans_by_goal,
            todos_by_plan,
            plans_by_todo,
            todo_dependencies,
            todo_dependents,

            // Session bindings
            session_bindings,
            bindings_by_session,
            bindings_by_entity,
        };

        // Ensure schema version is compatible and up-to-date
        engine.ensure_schema_version()?;

        Ok(engine)
    }

    // =========================================================================
    // Schema Versioning Methods
    // =========================================================================

    /// Check the database schema version against the application's expected version.
    ///
    /// Returns the schema status indicating whether:
    /// - The schema is current (no action needed)
    /// - The schema needs migration (older version)
    /// - The schema is too new (application is outdated)
    /// - The schema is unversioned (legacy or fresh database)
    pub fn check_schema_version(&self) -> Result<SchemaStatus> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        match self.metadata.get(&rtxn, SCHEMA_VERSION_KEY).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => {
                let version: u32 = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;

                if version == CURRENT_SCHEMA_VERSION {
                    Ok(SchemaStatus::Current)
                } else if version < CURRENT_SCHEMA_VERSION {
                    Ok(SchemaStatus::NeedsMigration {
                        from: version,
                        to: CURRENT_SCHEMA_VERSION,
                    })
                } else {
                    Ok(SchemaStatus::TooNew {
                        db_version: version,
                        app_version: CURRENT_SCHEMA_VERSION,
                    })
                }
            }
            None => Ok(SchemaStatus::Unversioned),
        }
    }

    /// Stamp the database with the current schema version.
    ///
    /// This should be called after:
    /// - Creating a new database
    /// - Successfully completing all migrations
    pub fn stamp_version(&self) -> Result<()> {
        let bytes = serde_json::to_vec(&CURRENT_SCHEMA_VERSION)
            .map_err(|e| Error::Serialization(e.to_string()))?;

        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;
        self.metadata
            .put(&mut wtxn, SCHEMA_VERSION_KEY, &bytes)
            .map_err(|e| Error::Database(e.to_string()))?;
        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    /// Run all necessary migrations to bring the database up to the current version.
    ///
    /// This is a no-op if the database is already at the current version or unversioned.
    /// Migrations are run in order from the current version to the target version.
    ///
    /// # Migration Framework
    ///
    /// When adding a new migration:
    /// 1. Increment CURRENT_SCHEMA_VERSION
    /// 2. Add a match arm for the old version in the loop below
    /// 3. Implement the migration function
    /// 4. Add the version to the history comment
    fn run_migrations(&self, from_version: u32) -> Result<()> {
        // Migration framework: when adding migrations, uncomment the loop and add match arms.
        // For now, we only have version 1 and no migrations to run.
        //
        // Example for future migrations:
        // let mut current = from_version;
        // while current < CURRENT_SCHEMA_VERSION {
        //     match current {
        //         0 => { self.migrate_v0_to_v1()?; current = 1; }
        //         1 => { self.migrate_v1_to_v2()?; current = 2; }
        //         _ => break,
        //     }
        // }

        // Currently no migrations defined - fail if we somehow get here with an old version
        if from_version < CURRENT_SCHEMA_VERSION {
            return Err(Error::Database(format!(
                "No migration path from version {} to {}",
                from_version, CURRENT_SCHEMA_VERSION
            )));
        }

        Ok(())
    }

    /// Ensure the database schema is compatible and up-to-date.
    ///
    /// This method:
    /// 1. Checks the current schema version
    /// 2. Runs migrations if needed
    /// 3. Stamps the version if unversioned or after migrations
    /// 4. Returns an error if the database is too new
    ///
    /// Called automatically during `open()`.
    fn ensure_schema_version(&self) -> Result<()> {
        match self.check_schema_version()? {
            SchemaStatus::Current => {
                // Nothing to do
                Ok(())
            }
            SchemaStatus::Unversioned => {
                // Fresh or legacy database - stamp with current version
                // (We assume legacy databases are compatible with v1 since we're just
                // adding the versioning system now)
                self.stamp_version()?;
                Ok(())
            }
            SchemaStatus::NeedsMigration { from, to: _ } => {
                // Run migrations and stamp the new version
                self.run_migrations(from)?;
                self.stamp_version()?;
                Ok(())
            }
            SchemaStatus::TooNew { db_version, app_version } => {
                Err(Error::SchemaTooNew { db_version, app_version })
            }
        }
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

            // Prefer fork_name over title for display (fork_name is set when forking)
            let name = if !data.fork_name.is_empty() {
                data.fork_name.clone()
            } else {
                data.title.clone()
            };
            sessions.push(SessionMetadata {
                id: data.id,
                name,
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

    async fn load_session_history(&self) -> Result<Vec<String>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        match self.metadata.get(&rtxn, SESSION_HISTORY_KEY).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => {
                let history: Vec<String> = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                Ok(history)
            }
            None => Ok(vec![]),
        }
    }

    async fn save_session_history(&self, session_ids: &[String]) -> Result<()> {
        let bytes = serde_json::to_vec(session_ids)
            .map_err(|e| Error::Serialization(e.to_string()))?;

        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;
        self.metadata
            .put(&mut wtxn, SESSION_HISTORY_KEY, &bytes)
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
            sentiment: None,
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

    // =========================================================================
    // Session History Tests
    // =========================================================================

    #[test]
    fn test_session_history_empty() {
        let dir = TestDir::new("lmdb_test_session_history_empty");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        future::block_on(async {
            let history = engine.load_session_history().await.unwrap();
            assert!(history.is_empty());
        });
    }

    #[test]
    fn test_session_history_save_and_load() {
        let dir = TestDir::new("lmdb_test_session_history_save_load");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let session_ids = vec![
            "sess-3".to_string(),
            "sess-1".to_string(),
            "sess-2".to_string(),
        ];

        future::block_on(async {
            engine.save_session_history(&session_ids).await.unwrap();
            let loaded = engine.load_session_history().await.unwrap();
            assert_eq!(loaded, session_ids);
        });
    }

    #[test]
    fn test_session_history_overwrite() {
        let dir = TestDir::new("lmdb_test_session_history_overwrite");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        future::block_on(async {
            // Save initial history
            let initial = vec!["sess-1".to_string(), "sess-2".to_string()];
            engine.save_session_history(&initial).await.unwrap();

            // Save new history (should overwrite)
            let updated = vec!["sess-3".to_string(), "sess-1".to_string()];
            engine.save_session_history(&updated).await.unwrap();

            let loaded = engine.load_session_history().await.unwrap();
            assert_eq!(loaded, updated);
        });
    }

    #[test]
    fn test_session_history_persistence() {
        let dir = TestDir::new("lmdb_test_session_history_persistence");
        let db_path = dir.db_path();

        let session_ids = vec![
            "sess-a".to_string(),
            "sess-b".to_string(),
        ];

        // Save and close
        {
            let engine = LmdbEngine::open(&db_path).unwrap();
            future::block_on(async {
                engine.save_session_history(&session_ids).await.unwrap();
            });
        }

        // Reopen and verify
        {
            let engine = LmdbEngine::open(&db_path).unwrap();
            future::block_on(async {
                let loaded = engine.load_session_history().await.unwrap();
                assert_eq!(loaded, session_ids);
            });
        }
    }

    // =========================================================================
    // Schema Versioning Tests
    // =========================================================================

    #[test]
    fn test_schema_version_stamped_on_open() {
        let dir = TestDir::new("lmdb_test_schema_version_stamped");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        // New database should be stamped with current version
        let status = engine.check_schema_version().unwrap();
        assert_eq!(status, SchemaStatus::Current);
    }

    #[test]
    fn test_schema_version_persists() {
        let dir = TestDir::new("lmdb_test_schema_version_persists");
        let db_path = dir.db_path();

        // Open and close
        {
            let _engine = LmdbEngine::open(&db_path).unwrap();
        }

        // Reopen and verify version is still there
        {
            let engine = LmdbEngine::open(&db_path).unwrap();
            let status = engine.check_schema_version().unwrap();
            assert_eq!(status, SchemaStatus::Current);
        }
    }

    #[test]
    fn test_schema_version_stamp() {
        let dir = TestDir::new("lmdb_test_schema_version_stamp");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        // After opening, we should be able to explicitly stamp (idempotent)
        engine.stamp_version().unwrap();

        let status = engine.check_schema_version().unwrap();
        assert_eq!(status, SchemaStatus::Current);
    }

}
