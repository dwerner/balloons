use async_trait::async_trait;
use chrono::DateTime;
use heed::types::{Bytes, Str};
use heed::{Database, Env, EnvOpenOptions};
use std::path::Path;
use std::sync::Arc;

use crate::generated::{
    GoalData, PlanData, SessionBinding, SessionData, SessionMetadata, TodoData, TodoDependency,
    TodoPlanLink, TurnData, TurnOrder, UserData, UserPrefs, WatcherRelation,
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
    // Try parsing with microseconds (e.g., "2024-01-01T00:00:00.123456" from Python's isoformat())
    if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(iso_str, "%Y-%m-%dT%H:%M:%S%.f") {
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

    // Watcher relationships
    watchers: Database<Str, Bytes>,             // watcher_id → WatcherRelation
    watchers_by_target: Database<Str, Bytes>,   // target_session_id → [watcher_id]
    watchers_by_watcher: Database<Str, Bytes>,  // watcher_session_id → [watcher_id]

    // User management
    users: Database<Str, Bytes>,              // user_id → UserData
    users_by_username: Database<Str, Bytes>,  // lowercase_username → user_id
}

/// Key used for session history in the metadata table
const SESSION_HISTORY_KEY: &str = "session_history";

/// Key used for user preferences in the metadata table
const USER_PREFS_KEY: &str = "user_prefs";

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

        // Database count: 4 session + 3 goal entities + 5 goal indexes + 3 binding + 3 watcher + 2 users = 20
        let env = unsafe {
            EnvOpenOptions::new()
                .map_size(map_size)
                .max_dbs(20)
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

        // Watcher relationship tables
        let watchers = env
            .create_database(&mut wtxn, Some("watchers"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let watchers_by_target = env
            .create_database(&mut wtxn, Some("watchers_by_target"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let watchers_by_watcher = env
            .create_database(&mut wtxn, Some("watchers_by_watcher"))
            .map_err(|e| Error::Database(e.to_string()))?;

        // User management tables
        let users = env
            .create_database(&mut wtxn, Some("users"))
            .map_err(|e| Error::Database(e.to_string()))?;
        let users_by_username = env
            .create_database(&mut wtxn, Some("users_by_username"))
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

            // Watcher relationships
            watchers,
            watchers_by_target,
            watchers_by_watcher,

            // User management
            users,
            users_by_username,
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

    /// Add an ID to a string list index.
    fn add_to_index(
        &self,
        wtxn: &mut heed::RwTxn,
        db: &Database<Str, Bytes>,
        key: &str,
        id: &str,
    ) -> Result<()> {
        let mut ids: Vec<String> = db
            .get(wtxn, key)
            .map_err(|e| Error::Database(e.to_string()))?
            .and_then(|b| serde_json::from_slice(b).ok())
            .unwrap_or_default();

        if !ids.contains(&id.to_string()) {
            ids.push(id.to_string());
            let bytes = serde_json::to_vec(&ids)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            db.put(wtxn, key, &bytes)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        Ok(())
    }

    /// Remove an ID from a string list index.
    fn remove_from_index(
        &self,
        wtxn: &mut heed::RwTxn,
        db: &Database<Str, Bytes>,
        key: &str,
        id: &str,
    ) -> Result<()> {
        if let Some(bytes) = db.get(wtxn, key).map_err(|e| Error::Database(e.to_string()))? {
            if let Ok(mut ids) = serde_json::from_slice::<Vec<String>>(bytes) {
                ids.retain(|existing| existing != id);
                if ids.is_empty() {
                    db.delete(wtxn, key).map_err(|e| Error::Database(e.to_string()))?;
                } else {
                    let new_bytes = serde_json::to_vec(&ids)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    db.put(wtxn, key, &new_bytes)
                        .map_err(|e| Error::Database(e.to_string()))?;
                }
            }
        }
        Ok(())
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

    async fn get_turn_count(&self, session_id: &str) -> Result<usize> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Get turn order and return the length
        match self.turn_order
            .get(&rtxn, session_id)
            .map_err(|e| Error::Database(e.to_string()))?
        {
            Some(bytes) => {
                let turn_order = serde_json::from_slice::<TurnOrder>(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                Ok(turn_order.turn_ids.len())
            }
            None => Ok(0), // No turns for this session
        }
    }

    async fn load_turns_range(
        &self,
        session_id: &str,
        offset: usize,
        limit: usize,
    ) -> Result<Vec<TurnData>> {
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

        // Calculate the range to load
        let total = turn_order.turn_ids.len();
        if offset >= total {
            return Ok(vec![]); // Offset beyond available turns
        }

        let end = std::cmp::min(offset + limit, total);
        let turn_ids_slice = &turn_order.turn_ids[offset..end];

        // Load turns in order
        let mut turns = Vec::with_capacity(turn_ids_slice.len());
        for turn_id in turn_ids_slice {
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
                working_directories: data.working_directories.clone(),
                cached_context_tokens: data.cached_context_tokens,
                context_window: data.context_window,
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

    // =========================================================================
    // Goal System - Goals
    // =========================================================================

    async fn save_goal(&self, goal: &GoalData) -> Result<()> {
        let bytes = serde_json::to_vec(goal).map_err(|e| Error::Serialization(e.to_string()))?;

        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;
        self.goals
            .put(&mut wtxn, &goal.id, &bytes)
            .map_err(|e| Error::Database(e.to_string()))?;
        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn load_goal(&self, id: &str) -> Result<Option<GoalData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        match self.goals.get(&rtxn, id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => {
                let data: GoalData = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                Ok(Some(data))
            }
            None => Ok(None),
        }
    }

    async fn delete_goal(&self, id: &str) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;
        self.goals
            .delete(&mut wtxn, id)
            .map_err(|e| Error::Database(e.to_string()))?;
        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn list_goals(&self) -> Result<Vec<GoalData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        let mut goals = Vec::new();
        for entry in self.goals.iter(&rtxn).map_err(|e| Error::Database(e.to_string()))? {
            let (_key, value) = entry.map_err(|e| Error::Database(e.to_string()))?;
            let data: GoalData = serde_json::from_slice(value)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            goals.push(data);
        }

        Ok(goals)
    }

    // =========================================================================
    // Goal System - Plans
    // =========================================================================

    async fn save_plan(&self, plan: &PlanData) -> Result<()> {
        let bytes = serde_json::to_vec(plan).map_err(|e| Error::Serialization(e.to_string()))?;

        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Check if plan already exists to handle goal_id changes
        let old_goal_id: Option<String> = match self.plans.get(&wtxn, &plan.id).map_err(|e| Error::Database(e.to_string()))? {
            Some(old_bytes) => {
                let old_plan: PlanData = serde_json::from_slice(old_bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                if old_plan.goal_id != plan.goal_id {
                    Some(old_plan.goal_id)
                } else {
                    None
                }
            }
            None => None,
        };

        // Save the plan
        self.plans
            .put(&mut wtxn, &plan.id, &bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        // Remove from old goal's index if goal_id changed
        if let Some(old_goal_id) = old_goal_id {
            if let Some(index_bytes) = self.plans_by_goal.get(&wtxn, &old_goal_id).map_err(|e| Error::Database(e.to_string()))? {
                let mut plan_ids: Vec<String> = serde_json::from_slice(index_bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                plan_ids.retain(|id| id != &plan.id);
                if plan_ids.is_empty() {
                    self.plans_by_goal
                        .delete(&mut wtxn, &old_goal_id)
                        .map_err(|e| Error::Database(e.to_string()))?;
                } else {
                    let new_bytes = serde_json::to_vec(&plan_ids)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    self.plans_by_goal
                        .put(&mut wtxn, &old_goal_id, &new_bytes)
                        .map_err(|e| Error::Database(e.to_string()))?;
                }
            }
        }

        // Update plans_by_goal index
        let mut plan_ids: Vec<String> = match self.plans_by_goal.get(&wtxn, &plan.goal_id).map_err(|e| Error::Database(e.to_string()))? {
            Some(index_bytes) => serde_json::from_slice(index_bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => vec![],
        };

        if !plan_ids.contains(&plan.id) {
            plan_ids.push(plan.id.clone());
            let index_bytes = serde_json::to_vec(&plan_ids)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            self.plans_by_goal
                .put(&mut wtxn, &plan.goal_id, &index_bytes)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn load_plan(&self, id: &str) -> Result<Option<PlanData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        match self.plans.get(&rtxn, id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => {
                let data: PlanData = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                Ok(Some(data))
            }
            None => Ok(None),
        }
    }

    async fn delete_plan(&self, id: &str) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Get the plan to find its goal_id for index cleanup
        if let Some(bytes) = self.plans.get(&wtxn, id).map_err(|e| Error::Database(e.to_string()))? {
            let plan: PlanData = serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?;

            // Remove from plans_by_goal index
            if let Some(index_bytes) = self.plans_by_goal.get(&wtxn, &plan.goal_id).map_err(|e| Error::Database(e.to_string()))? {
                let mut plan_ids: Vec<String> = serde_json::from_slice(index_bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                plan_ids.retain(|pid| pid != id);
                if plan_ids.is_empty() {
                    self.plans_by_goal
                        .delete(&mut wtxn, &plan.goal_id)
                        .map_err(|e| Error::Database(e.to_string()))?;
                } else {
                    let new_bytes = serde_json::to_vec(&plan_ids)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    self.plans_by_goal
                        .put(&mut wtxn, &plan.goal_id, &new_bytes)
                        .map_err(|e| Error::Database(e.to_string()))?;
                }
            }
        }

        // Delete the plan
        self.plans
            .delete(&mut wtxn, id)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn list_plans(&self, goal_id: Option<&str>) -> Result<Vec<PlanData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        match goal_id {
            Some(gid) => {
                // Filter by goal_id using the index
                let plan_ids: Vec<String> = match self.plans_by_goal.get(&rtxn, gid).map_err(|e| Error::Database(e.to_string()))? {
                    Some(bytes) => serde_json::from_slice(bytes)
                        .map_err(|e| Error::Serialization(e.to_string()))?,
                    None => return Ok(vec![]),
                };

                let mut plans = Vec::with_capacity(plan_ids.len());
                for plan_id in plan_ids {
                    if let Some(bytes) = self.plans.get(&rtxn, &plan_id).map_err(|e| Error::Database(e.to_string()))? {
                        let plan: PlanData = serde_json::from_slice(bytes)
                            .map_err(|e| Error::Serialization(e.to_string()))?;
                        plans.push(plan);
                    }
                }
                Ok(plans)
            }
            None => {
                // Return all plans
                let mut plans = Vec::new();
                for entry in self.plans.iter(&rtxn).map_err(|e| Error::Database(e.to_string()))? {
                    let (_key, value) = entry.map_err(|e| Error::Database(e.to_string()))?;
                    let plan: PlanData = serde_json::from_slice(value)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    plans.push(plan);
                }
                Ok(plans)
            }
        }
    }

    // =========================================================================
    // Goal System - Todos
    // =========================================================================

    async fn save_todo(&self, todo: &TodoData) -> Result<()> {
        let bytes = serde_json::to_vec(todo).map_err(|e| Error::Serialization(e.to_string()))?;

        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;
        self.todos
            .put(&mut wtxn, &todo.id, &bytes)
            .map_err(|e| Error::Database(e.to_string()))?;
        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn load_todo(&self, id: &str) -> Result<Option<TodoData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        match self.todos.get(&rtxn, id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => {
                let data: TodoData = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                Ok(Some(data))
            }
            None => Ok(None),
        }
    }

    async fn delete_todo(&self, id: &str) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Clean up todo-plan links (plans_by_todo index tells us which plans to update)
        if let Some(bytes) = self.plans_by_todo.get(&wtxn, id).map_err(|e| Error::Database(e.to_string()))? {
            let plan_ids: Vec<String> = serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?;

            // Remove from each plan's todos_by_plan index
            for plan_id in plan_ids {
                if let Some(index_bytes) = self.todos_by_plan.get(&wtxn, &plan_id).map_err(|e| Error::Database(e.to_string()))? {
                    let mut todo_ids: Vec<String> = serde_json::from_slice(index_bytes)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    todo_ids.retain(|tid| tid != id);
                    if todo_ids.is_empty() {
                        self.todos_by_plan
                            .delete(&mut wtxn, &plan_id)
                            .map_err(|e| Error::Database(e.to_string()))?;
                    } else {
                        let new_bytes = serde_json::to_vec(&todo_ids)
                            .map_err(|e| Error::Serialization(e.to_string()))?;
                        self.todos_by_plan
                            .put(&mut wtxn, &plan_id, &new_bytes)
                            .map_err(|e| Error::Database(e.to_string()))?;
                    }
                }
            }

            // Delete the plans_by_todo entry
            self.plans_by_todo
                .delete(&mut wtxn, id)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        // Clean up todo dependencies (where this todo depends on others)
        self.todo_dependencies
            .delete(&mut wtxn, id)
            .map_err(|e| Error::Database(e.to_string()))?;

        // Clean up todo dependents (where others depend on this todo)
        if let Some(bytes) = self.todo_dependents.get(&wtxn, id).map_err(|e| Error::Database(e.to_string()))? {
            let dependent_ids: Vec<String> = serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?;

            // Remove this todo from each dependent's dependencies list
            for dep_id in dependent_ids {
                if let Some(dep_bytes) = self.todo_dependencies.get(&wtxn, &dep_id).map_err(|e| Error::Database(e.to_string()))? {
                    let mut deps: Vec<TodoDependency> = serde_json::from_slice(dep_bytes)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    deps.retain(|d| d.depends_on_id != id);
                    if deps.is_empty() {
                        self.todo_dependencies
                            .delete(&mut wtxn, &dep_id)
                            .map_err(|e| Error::Database(e.to_string()))?;
                    } else {
                        let new_bytes = serde_json::to_vec(&deps)
                            .map_err(|e| Error::Serialization(e.to_string()))?;
                        self.todo_dependencies
                            .put(&mut wtxn, &dep_id, &new_bytes)
                            .map_err(|e| Error::Database(e.to_string()))?;
                    }
                }
            }

            // Delete the dependents entry
            self.todo_dependents
                .delete(&mut wtxn, id)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        // Delete the todo itself
        self.todos
            .delete(&mut wtxn, id)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn list_todos(&self, plan_id: Option<&str>) -> Result<Vec<TodoData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        match plan_id {
            Some(pid) => {
                // Filter by plan_id using the todos_by_plan index
                let todo_ids: Vec<String> = match self.todos_by_plan.get(&rtxn, pid).map_err(|e| Error::Database(e.to_string()))? {
                    Some(bytes) => serde_json::from_slice(bytes)
                        .map_err(|e| Error::Serialization(e.to_string()))?,
                    None => return Ok(vec![]),
                };

                let mut todos = Vec::with_capacity(todo_ids.len());
                for todo_id in todo_ids {
                    if let Some(bytes) = self.todos.get(&rtxn, &todo_id).map_err(|e| Error::Database(e.to_string()))? {
                        let todo: TodoData = serde_json::from_slice(bytes)
                            .map_err(|e| Error::Serialization(e.to_string()))?;
                        todos.push(todo);
                    }
                }
                Ok(todos)
            }
            None => {
                // Return all todos
                let mut todos = Vec::new();
                for entry in self.todos.iter(&rtxn).map_err(|e| Error::Database(e.to_string()))? {
                    let (_key, value) = entry.map_err(|e| Error::Database(e.to_string()))?;
                    let todo: TodoData = serde_json::from_slice(value)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    todos.push(todo);
                }
                Ok(todos)
            }
        }
    }

    // =========================================================================
    // Goal System - Todo-Plan Links
    // =========================================================================

    async fn save_todo_plan_link(&self, link: &TodoPlanLink) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Update todos_by_plan index
        let mut todo_ids: Vec<String> = match self.todos_by_plan.get(&wtxn, &link.plan_id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => vec![],
        };

        if !todo_ids.contains(&link.todo_id) {
            todo_ids.push(link.todo_id.clone());
            let bytes = serde_json::to_vec(&todo_ids)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            self.todos_by_plan
                .put(&mut wtxn, &link.plan_id, &bytes)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        // Update plans_by_todo index
        let mut plan_ids: Vec<String> = match self.plans_by_todo.get(&wtxn, &link.todo_id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => vec![],
        };

        if !plan_ids.contains(&link.plan_id) {
            plan_ids.push(link.plan_id.clone());
            let bytes = serde_json::to_vec(&plan_ids)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            self.plans_by_todo
                .put(&mut wtxn, &link.todo_id, &bytes)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn delete_todo_plan_link(&self, todo_id: &str, plan_id: &str) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Update todos_by_plan index
        if let Some(bytes) = self.todos_by_plan.get(&wtxn, plan_id).map_err(|e| Error::Database(e.to_string()))? {
            let mut todo_ids: Vec<String> = serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            todo_ids.retain(|tid| tid != todo_id);
            if todo_ids.is_empty() {
                self.todos_by_plan
                    .delete(&mut wtxn, plan_id)
                    .map_err(|e| Error::Database(e.to_string()))?;
            } else {
                let new_bytes = serde_json::to_vec(&todo_ids)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                self.todos_by_plan
                    .put(&mut wtxn, plan_id, &new_bytes)
                    .map_err(|e| Error::Database(e.to_string()))?;
            }
        }

        // Update plans_by_todo index
        if let Some(bytes) = self.plans_by_todo.get(&wtxn, todo_id).map_err(|e| Error::Database(e.to_string()))? {
            let mut plan_ids: Vec<String> = serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            plan_ids.retain(|pid| pid != plan_id);
            if plan_ids.is_empty() {
                self.plans_by_todo
                    .delete(&mut wtxn, todo_id)
                    .map_err(|e| Error::Database(e.to_string()))?;
            } else {
                let new_bytes = serde_json::to_vec(&plan_ids)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                self.plans_by_todo
                    .put(&mut wtxn, todo_id, &new_bytes)
                    .map_err(|e| Error::Database(e.to_string()))?;
            }
        }

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn get_plans_for_todo(&self, todo_id: &str) -> Result<Vec<PlanData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        let plan_ids: Vec<String> = match self.plans_by_todo.get(&rtxn, todo_id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => return Ok(vec![]),
        };

        let mut plans = Vec::with_capacity(plan_ids.len());
        for plan_id in plan_ids {
            if let Some(bytes) = self.plans.get(&rtxn, &plan_id).map_err(|e| Error::Database(e.to_string()))? {
                let plan: PlanData = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                plans.push(plan);
            }
        }

        Ok(plans)
    }

    async fn get_todos_for_plan(&self, plan_id: &str) -> Result<Vec<TodoData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        let todo_ids: Vec<String> = match self.todos_by_plan.get(&rtxn, plan_id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => return Ok(vec![]),
        };

        let mut todos = Vec::with_capacity(todo_ids.len());
        for todo_id in todo_ids {
            if let Some(bytes) = self.todos.get(&rtxn, &todo_id).map_err(|e| Error::Database(e.to_string()))? {
                let todo: TodoData = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                todos.push(todo);
            }
        }

        Ok(todos)
    }

    // =========================================================================
    // Goal System - Todo Dependencies
    // =========================================================================

    async fn save_todo_dependency(&self, dependency: &TodoDependency) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Update todo_dependencies index (todo_id -> [TodoDependency])
        let mut deps: Vec<TodoDependency> = match self.todo_dependencies.get(&wtxn, &dependency.todo_id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => vec![],
        };

        // Check if dependency already exists
        if !deps.iter().any(|d| d.depends_on_id == dependency.depends_on_id) {
            deps.push(dependency.clone());
            let bytes = serde_json::to_vec(&deps)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            self.todo_dependencies
                .put(&mut wtxn, &dependency.todo_id, &bytes)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        // Update todo_dependents index (depends_on_id -> [todo_id])
        let mut dependents: Vec<String> = match self.todo_dependents.get(&wtxn, &dependency.depends_on_id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => vec![],
        };

        if !dependents.contains(&dependency.todo_id) {
            dependents.push(dependency.todo_id.clone());
            let bytes = serde_json::to_vec(&dependents)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            self.todo_dependents
                .put(&mut wtxn, &dependency.depends_on_id, &bytes)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn delete_todo_dependency(&self, todo_id: &str, depends_on_id: &str) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Update todo_dependencies index
        if let Some(bytes) = self.todo_dependencies.get(&wtxn, todo_id).map_err(|e| Error::Database(e.to_string()))? {
            let mut deps: Vec<TodoDependency> = serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            deps.retain(|d| d.depends_on_id != depends_on_id);
            if deps.is_empty() {
                self.todo_dependencies
                    .delete(&mut wtxn, todo_id)
                    .map_err(|e| Error::Database(e.to_string()))?;
            } else {
                let new_bytes = serde_json::to_vec(&deps)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                self.todo_dependencies
                    .put(&mut wtxn, todo_id, &new_bytes)
                    .map_err(|e| Error::Database(e.to_string()))?;
            }
        }

        // Update todo_dependents index
        if let Some(bytes) = self.todo_dependents.get(&wtxn, depends_on_id).map_err(|e| Error::Database(e.to_string()))? {
            let mut dependents: Vec<String> = serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            dependents.retain(|tid| tid != todo_id);
            if dependents.is_empty() {
                self.todo_dependents
                    .delete(&mut wtxn, depends_on_id)
                    .map_err(|e| Error::Database(e.to_string()))?;
            } else {
                let new_bytes = serde_json::to_vec(&dependents)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                self.todo_dependents
                    .put(&mut wtxn, depends_on_id, &new_bytes)
                    .map_err(|e| Error::Database(e.to_string()))?;
            }
        }

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn get_dependencies(&self, todo_id: &str) -> Result<Vec<TodoData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        let deps: Vec<TodoDependency> = match self.todo_dependencies.get(&rtxn, todo_id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => return Ok(vec![]),
        };

        let mut todos = Vec::with_capacity(deps.len());
        for dep in deps {
            if let Some(bytes) = self.todos.get(&rtxn, &dep.depends_on_id).map_err(|e| Error::Database(e.to_string()))? {
                let todo: TodoData = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                todos.push(todo);
            }
        }

        Ok(todos)
    }

    async fn get_dependents(&self, todo_id: &str) -> Result<Vec<TodoData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        let dependent_ids: Vec<String> = match self.todo_dependents.get(&rtxn, todo_id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => return Ok(vec![]),
        };

        let mut todos = Vec::with_capacity(dependent_ids.len());
        for dep_id in dependent_ids {
            if let Some(bytes) = self.todos.get(&rtxn, &dep_id).map_err(|e| Error::Database(e.to_string()))? {
                let todo: TodoData = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                todos.push(todo);
            }
        }

        Ok(todos)
    }

    // =========================================================================
    // Goal System - Session Bindings
    // =========================================================================

    async fn save_session_binding(&self, binding: &SessionBinding) -> Result<()> {
        let bytes = serde_json::to_vec(binding).map_err(|e| Error::Serialization(e.to_string()))?;

        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Check if binding already exists to handle session/entity changes
        let old_binding: Option<SessionBinding> = match self.session_bindings.get(&wtxn, &binding.id).map_err(|e| Error::Database(e.to_string()))? {
            Some(old_bytes) => Some(serde_json::from_slice(old_bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?),
            None => None,
        };

        // Save the binding
        self.session_bindings
            .put(&mut wtxn, &binding.id, &bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        // Handle index updates if session_id or entity changed
        if let Some(ref old) = old_binding {
            // Remove from old session index if session changed
            if old.session_id != binding.session_id {
                if let Some(index_bytes) = self.bindings_by_session.get(&wtxn, &old.session_id).map_err(|e| Error::Database(e.to_string()))? {
                    let mut binding_ids: Vec<String> = serde_json::from_slice(index_bytes)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    binding_ids.retain(|id| id != &binding.id);
                    if binding_ids.is_empty() {
                        self.bindings_by_session
                            .delete(&mut wtxn, &old.session_id)
                            .map_err(|e| Error::Database(e.to_string()))?;
                    } else {
                        let new_bytes = serde_json::to_vec(&binding_ids)
                            .map_err(|e| Error::Serialization(e.to_string()))?;
                        self.bindings_by_session
                            .put(&mut wtxn, &old.session_id, &new_bytes)
                            .map_err(|e| Error::Database(e.to_string()))?;
                    }
                }
            }

            // Remove from old entity index if entity changed
            let old_entity_key = format!("{}:{}", old.entity_type, old.entity_id);
            let new_entity_key = format!("{}:{}", binding.entity_type, binding.entity_id);
            if old_entity_key != new_entity_key {
                if let Some(index_bytes) = self.bindings_by_entity.get(&wtxn, &old_entity_key).map_err(|e| Error::Database(e.to_string()))? {
                    let mut binding_ids: Vec<String> = serde_json::from_slice(index_bytes)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    binding_ids.retain(|id| id != &binding.id);
                    if binding_ids.is_empty() {
                        self.bindings_by_entity
                            .delete(&mut wtxn, &old_entity_key)
                            .map_err(|e| Error::Database(e.to_string()))?;
                    } else {
                        let new_bytes = serde_json::to_vec(&binding_ids)
                            .map_err(|e| Error::Serialization(e.to_string()))?;
                        self.bindings_by_entity
                            .put(&mut wtxn, &old_entity_key, &new_bytes)
                            .map_err(|e| Error::Database(e.to_string()))?;
                    }
                }
            }
        }

        // Update bindings_by_session index
        let mut session_binding_ids: Vec<String> = match self.bindings_by_session.get(&wtxn, &binding.session_id).map_err(|e| Error::Database(e.to_string()))? {
            Some(index_bytes) => serde_json::from_slice(index_bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => vec![],
        };

        if !session_binding_ids.contains(&binding.id) {
            session_binding_ids.push(binding.id.clone());
            let index_bytes = serde_json::to_vec(&session_binding_ids)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            self.bindings_by_session
                .put(&mut wtxn, &binding.session_id, &index_bytes)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        // Update bindings_by_entity index
        let entity_key = format!("{}:{}", binding.entity_type, binding.entity_id);
        let mut entity_binding_ids: Vec<String> = match self.bindings_by_entity.get(&wtxn, &entity_key).map_err(|e| Error::Database(e.to_string()))? {
            Some(index_bytes) => serde_json::from_slice(index_bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => vec![],
        };

        if !entity_binding_ids.contains(&binding.id) {
            entity_binding_ids.push(binding.id.clone());
            let index_bytes = serde_json::to_vec(&entity_binding_ids)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            self.bindings_by_entity
                .put(&mut wtxn, &entity_key, &index_bytes)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn load_session_binding(&self, id: &str) -> Result<Option<SessionBinding>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        match self.session_bindings.get(&rtxn, id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => {
                let data: SessionBinding = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                Ok(Some(data))
            }
            None => Ok(None),
        }
    }

    async fn delete_session_binding(&self, id: &str) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Get the binding to find its indexes
        if let Some(bytes) = self.session_bindings.get(&wtxn, id).map_err(|e| Error::Database(e.to_string()))? {
            let binding: SessionBinding = serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?;

            // Remove from bindings_by_session index
            if let Some(index_bytes) = self.bindings_by_session.get(&wtxn, &binding.session_id).map_err(|e| Error::Database(e.to_string()))? {
                let mut binding_ids: Vec<String> = serde_json::from_slice(index_bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                binding_ids.retain(|bid| bid != id);
                if binding_ids.is_empty() {
                    self.bindings_by_session
                        .delete(&mut wtxn, &binding.session_id)
                        .map_err(|e| Error::Database(e.to_string()))?;
                } else {
                    let new_bytes = serde_json::to_vec(&binding_ids)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    self.bindings_by_session
                        .put(&mut wtxn, &binding.session_id, &new_bytes)
                        .map_err(|e| Error::Database(e.to_string()))?;
                }
            }

            // Remove from bindings_by_entity index
            let entity_key = format!("{}:{}", binding.entity_type, binding.entity_id);
            if let Some(index_bytes) = self.bindings_by_entity.get(&wtxn, &entity_key).map_err(|e| Error::Database(e.to_string()))? {
                let mut binding_ids: Vec<String> = serde_json::from_slice(index_bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                binding_ids.retain(|bid| bid != id);
                if binding_ids.is_empty() {
                    self.bindings_by_entity
                        .delete(&mut wtxn, &entity_key)
                        .map_err(|e| Error::Database(e.to_string()))?;
                } else {
                    let new_bytes = serde_json::to_vec(&binding_ids)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    self.bindings_by_entity
                        .put(&mut wtxn, &entity_key, &new_bytes)
                        .map_err(|e| Error::Database(e.to_string()))?;
                }
            }
        }

        // Delete the binding
        self.session_bindings
            .delete(&mut wtxn, id)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn get_bindings_for_session(&self, session_id: &str) -> Result<Vec<SessionBinding>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        let binding_ids: Vec<String> = match self.bindings_by_session.get(&rtxn, session_id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => return Ok(vec![]),
        };

        let mut bindings = Vec::with_capacity(binding_ids.len());
        for bid in binding_ids {
            if let Some(bytes) = self.session_bindings.get(&rtxn, &bid).map_err(|e| Error::Database(e.to_string()))? {
                let binding: SessionBinding = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                bindings.push(binding);
            }
        }

        Ok(bindings)
    }

    async fn get_bindings_for_entity(
        &self,
        entity_type: &str,
        entity_id: &str,
    ) -> Result<Vec<SessionBinding>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        let entity_key = format!("{}:{}", entity_type, entity_id);
        let binding_ids: Vec<String> = match self.bindings_by_entity.get(&rtxn, &entity_key).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => return Ok(vec![]),
        };

        let mut bindings = Vec::with_capacity(binding_ids.len());
        for bid in binding_ids {
            if let Some(bytes) = self.session_bindings.get(&rtxn, &bid).map_err(|e| Error::Database(e.to_string()))? {
                let binding: SessionBinding = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                bindings.push(binding);
            }
        }

        Ok(bindings)
    }

    async fn list_bindings(&self) -> Result<Vec<SessionBinding>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        let mut bindings = Vec::new();
        let iter = self.session_bindings.iter(&rtxn)
            .map_err(|e| Error::Database(e.to_string()))?;

        for result in iter {
            let (_key, bytes) = result.map_err(|e| Error::Database(e.to_string()))?;
            let binding: SessionBinding = serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            bindings.push(binding);
        }

        Ok(bindings)
    }

    // =========================================================================
    // User Preferences Implementation
    // =========================================================================

    async fn load_user_prefs(&self) -> Result<UserPrefs> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        match self.metadata.get(&rtxn, USER_PREFS_KEY).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => {
                let prefs: UserPrefs = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                Ok(prefs)
            }
            None => Ok(UserPrefs {
                goal_tree_collapsed_ids: vec![],
                pinned_session_ids: vec![],
            }),
        }
    }

    async fn save_user_prefs(&self, prefs: &UserPrefs) -> Result<()> {
        let bytes = serde_json::to_vec(prefs)
            .map_err(|e| Error::Serialization(e.to_string()))?;

        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;
        self.metadata
            .put(&mut wtxn, USER_PREFS_KEY, &bytes)
            .map_err(|e| Error::Database(e.to_string()))?;
        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    // =========================================================================
    // Watcher Relationships
    // =========================================================================

    async fn save_watcher(&self, watcher: &WatcherRelation) -> Result<()> {
        let bytes = serde_json::to_vec(watcher)
            .map_err(|e| Error::Serialization(e.to_string()))?;

        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Check if this watcher already exists to handle index updates
        let existing = self.watchers
            .get(&wtxn, &watcher.id)
            .map_err(|e| Error::Database(e.to_string()))?
            .and_then(|b| serde_json::from_slice::<WatcherRelation>(b).ok());

        // Save the watcher
        self.watchers
            .put(&mut wtxn, &watcher.id, &bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        // Update indexes
        // If there was an existing watcher with different target/watcher, clean up old indexes
        if let Some(ref old) = existing {
            if old.target_session_id != watcher.target_session_id {
                // Remove from old target index
                self.remove_from_index(&mut wtxn, &self.watchers_by_target, &old.target_session_id, &watcher.id)?;
            }
            if old.watcher_session_id != watcher.watcher_session_id {
                // Remove from old watcher index
                self.remove_from_index(&mut wtxn, &self.watchers_by_watcher, &old.watcher_session_id, &watcher.id)?;
            }
        }

        // Add to target index
        self.add_to_index(&mut wtxn, &self.watchers_by_target, &watcher.target_session_id, &watcher.id)?;

        // Add to watcher index
        self.add_to_index(&mut wtxn, &self.watchers_by_watcher, &watcher.watcher_session_id, &watcher.id)?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;
        Ok(())
    }

    async fn delete_watcher(&self, id: &str) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Load the watcher first to clean up indexes
        if let Some(bytes) = self.watchers.get(&wtxn, id).map_err(|e| Error::Database(e.to_string()))? {
            if let Ok(watcher) = serde_json::from_slice::<WatcherRelation>(bytes) {
                // Remove from indexes
                self.remove_from_index(&mut wtxn, &self.watchers_by_target, &watcher.target_session_id, id)?;
                self.remove_from_index(&mut wtxn, &self.watchers_by_watcher, &watcher.watcher_session_id, id)?;
            }
        }

        // Delete the watcher
        self.watchers
            .delete(&mut wtxn, id)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;
        Ok(())
    }

    async fn get_watchers_for_target(&self, target_session_id: &str) -> Result<Vec<WatcherRelation>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Get watcher IDs from index
        let ids: Vec<String> = self.watchers_by_target
            .get(&rtxn, target_session_id)
            .map_err(|e| Error::Database(e.to_string()))?
            .and_then(|b| serde_json::from_slice(b).ok())
            .unwrap_or_default();

        // Load each watcher
        let mut watchers = Vec::new();
        for id in ids {
            if let Some(bytes) = self.watchers.get(&rtxn, &id).map_err(|e| Error::Database(e.to_string()))? {
                if let Ok(watcher) = serde_json::from_slice(bytes) {
                    watchers.push(watcher);
                }
            }
        }

        Ok(watchers)
    }

    async fn get_targets_for_watcher(&self, watcher_session_id: &str) -> Result<Vec<WatcherRelation>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Get watcher IDs from index
        let ids: Vec<String> = self.watchers_by_watcher
            .get(&rtxn, watcher_session_id)
            .map_err(|e| Error::Database(e.to_string()))?
            .and_then(|b| serde_json::from_slice(b).ok())
            .unwrap_or_default();

        // Load each watcher
        let mut watchers = Vec::new();
        for id in ids {
            if let Some(bytes) = self.watchers.get(&rtxn, &id).map_err(|e| Error::Database(e.to_string()))? {
                if let Ok(watcher) = serde_json::from_slice(bytes) {
                    watchers.push(watcher);
                }
            }
        }

        Ok(watchers)
    }

    async fn list_watchers(&self) -> Result<Vec<WatcherRelation>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;
        let mut watchers = Vec::new();

        let iter = self.watchers.iter(&rtxn).map_err(|e| Error::Database(e.to_string()))?;
        for result in iter {
            let (_, bytes) = result.map_err(|e| Error::Database(e.to_string()))?;
            if let Ok(watcher) = serde_json::from_slice(bytes) {
                watchers.push(watcher);
            }
        }

        Ok(watchers)
    }

    // =========================================================================
    // User Management Implementation
    // =========================================================================

    async fn save_user(&self, user: &UserData) -> Result<()> {
        let bytes = serde_json::to_vec(user).map_err(|e| Error::Serialization(e.to_string()))?;
        let username_key = user.username.to_lowercase();

        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Check if user already exists to handle username changes
        let old_username: Option<String> = match self.users.get(&wtxn, &user.id).map_err(|e| Error::Database(e.to_string()))? {
            Some(old_bytes) => {
                let old_user: UserData = serde_json::from_slice(old_bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                let old_key = old_user.username.to_lowercase();
                if old_key != username_key {
                    Some(old_key)
                } else {
                    None
                }
            }
            None => None,
        };

        // Save the user
        self.users
            .put(&mut wtxn, &user.id, &bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        // Remove old username index if username changed
        if let Some(old_key) = old_username {
            self.users_by_username
                .delete(&mut wtxn, &old_key)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        // Update users_by_username index (store user_id, not full user)
        let id_bytes = serde_json::to_vec(&user.id)
            .map_err(|e| Error::Serialization(e.to_string()))?;
        self.users_by_username
            .put(&mut wtxn, &username_key, &id_bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn load_user(&self, id: &str) -> Result<Option<UserData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        match self.users.get(&rtxn, id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => {
                let data: UserData = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                Ok(Some(data))
            }
            None => Ok(None),
        }
    }

    async fn load_user_by_username(&self, username: &str) -> Result<Option<UserData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;
        let username_key = username.to_lowercase();

        // Look up user_id from username index
        let user_id: String = match self.users_by_username.get(&rtxn, &username_key).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?,
            None => return Ok(None),
        };

        // Load the full user record
        match self.users.get(&rtxn, &user_id).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => {
                let data: UserData = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                Ok(Some(data))
            }
            None => Ok(None), // Index orphan - shouldn't happen
        }
    }

    async fn delete_user(&self, id: &str) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        // Get the user to find their username for index cleanup
        if let Some(bytes) = self.users.get(&wtxn, id).map_err(|e| Error::Database(e.to_string()))? {
            let user: UserData = serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?;

            // Remove from users_by_username index
            let username_key = user.username.to_lowercase();
            self.users_by_username
                .delete(&mut wtxn, &username_key)
                .map_err(|e| Error::Database(e.to_string()))?;
        }

        // Delete the user
        self.users
            .delete(&mut wtxn, id)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;

        Ok(())
    }

    async fn list_users(&self) -> Result<Vec<UserData>> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;

        let mut users = Vec::new();
        for entry in self.users.iter(&rtxn).map_err(|e| Error::Database(e.to_string()))? {
            let (_key, value) = entry.map_err(|e| Error::Database(e.to_string()))?;
            let data: UserData = serde_json::from_slice(value)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            users.push(data);
        }

        Ok(users)
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
            context_window: 150000,
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
            started_at: None,
            ended_at: None,
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
        // With microseconds (Python's datetime.now().isoformat() format)
        assert_eq!(parse_iso_to_unix("2024-01-01T00:00:00.123456"), 1704067200);
        // With milliseconds
        assert_eq!(parse_iso_to_unix("2024-01-01T00:00:00.123"), 1704067200);
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
    // User Preferences Tests
    // =========================================================================

    #[test]
    fn test_user_prefs_default() {
        let dir = TestDir::new("lmdb_test_user_prefs_default");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        future::block_on(async {
            let prefs = engine.load_user_prefs().await.unwrap();
            assert!(prefs.goal_tree_collapsed_ids.is_empty());
        });
    }

    #[test]
    fn test_user_prefs_save_and_load() {
        let dir = TestDir::new("lmdb_test_user_prefs_save_load");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let prefs = UserPrefs {
            goal_tree_collapsed_ids: vec![
                "goal-1".to_string(),
                "plan-2".to_string(),
                "todo-3".to_string(),
            ],
            pinned_session_ids: vec!["session-1".to_string()],
        };

        future::block_on(async {
            engine.save_user_prefs(&prefs).await.unwrap();
            let loaded = engine.load_user_prefs().await.unwrap();
            assert_eq!(loaded.goal_tree_collapsed_ids, prefs.goal_tree_collapsed_ids);
            assert_eq!(loaded.pinned_session_ids, prefs.pinned_session_ids);
        });
    }

    #[test]
    fn test_user_prefs_persistence() {
        let dir = TestDir::new("lmdb_test_user_prefs_persistence");
        let db_path = dir.db_path();

        let prefs = UserPrefs {
            goal_tree_collapsed_ids: vec!["goal-abc".to_string(), "plan-xyz".to_string()],
            pinned_session_ids: vec!["session-abc".to_string()],
        };

        // Save and close
        {
            let engine = LmdbEngine::open(&db_path).unwrap();
            future::block_on(async {
                engine.save_user_prefs(&prefs).await.unwrap();
            });
        }

        // Reopen and verify
        {
            let engine = LmdbEngine::open(&db_path).unwrap();
            future::block_on(async {
                let loaded = engine.load_user_prefs().await.unwrap();
                assert_eq!(loaded.goal_tree_collapsed_ids, prefs.goal_tree_collapsed_ids);
                assert_eq!(loaded.pinned_session_ids, prefs.pinned_session_ids);
            });
        }
    }

    #[test]
    fn test_user_prefs_overwrite() {
        let dir = TestDir::new("lmdb_test_user_prefs_overwrite");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        future::block_on(async {
            // Save initial prefs
            let initial = UserPrefs {
                goal_tree_collapsed_ids: vec!["node-1".to_string()],
                pinned_session_ids: vec!["session-a".to_string()],
            };
            engine.save_user_prefs(&initial).await.unwrap();

            // Save new prefs (should overwrite)
            let updated = UserPrefs {
                goal_tree_collapsed_ids: vec!["node-2".to_string(), "node-3".to_string()],
                pinned_session_ids: vec!["session-b".to_string(), "session-c".to_string()],
            };
            engine.save_user_prefs(&updated).await.unwrap();

            let loaded = engine.load_user_prefs().await.unwrap();
            assert_eq!(loaded.goal_tree_collapsed_ids, updated.goal_tree_collapsed_ids);
            assert_eq!(loaded.pinned_session_ids, updated.pinned_session_ids);
        });
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

    // =========================================================================
    // Goal System Tests - Goals
    // =========================================================================

    fn make_goal(id: &str, title: &str) -> GoalData {
        GoalData {
            id: id.to_string(),
            title: title.to_string(),
            description: "Test goal description".to_string(),
            weight: 5,
            status: "active".to_string(),
            acceptance_criteria: vec!["Criterion 1".to_string()],
            created_at: "2024-01-01T00:00:00Z".to_string(),
            updated_at: "2024-01-01T00:00:00Z".to_string(),
            completed_at: None,
            supersedes_id: None,
            parent_goal_id: None,
        }
    }

    fn make_plan(id: &str, goal_id: &str, title: &str) -> PlanData {
        PlanData {
            id: id.to_string(),
            goal_id: goal_id.to_string(),
            title: title.to_string(),
            description: "Test plan description".to_string(),
            status: "active".to_string(),
            created_at: "2024-01-01T00:00:00Z".to_string(),
            updated_at: "2024-01-01T00:00:00Z".to_string(),
            completed_at: None,
            postmortem: None,
        }
    }

    fn make_todo_data(id: &str, title: &str) -> TodoData {
        TodoData {
            id: id.to_string(),
            title: title.to_string(),
            description: "Test todo description".to_string(),
            status: "pending".to_string(),
            is_spike: false,
            created_at: "2024-01-01T00:00:00Z".to_string(),
            updated_at: "2024-01-01T00:00:00Z".to_string(),
            completed_at: None,
            timebox_minutes: None,
            completed_by_session: None,
            completed_by: None,
        }
    }

    fn make_binding(id: &str, session_id: &str, entity_type: &str, entity_id: &str) -> SessionBinding {
        SessionBinding {
            id: id.to_string(),
            session_id: session_id.to_string(),
            entity_type: entity_type.to_string(),
            entity_id: entity_id.to_string(),
            role: "implementation".to_string(),
            created_at: "2024-01-01T00:00:00Z".to_string(),
            released_at: None,
        }
    }

    #[test]
    fn test_save_and_load_goal() {
        let dir = TestDir::new("lmdb_test_save_and_load_goal");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let goal = make_goal("goal-1", "Test Goal");

        future::block_on(async {
            engine.save_goal(&goal).await.unwrap();
            let loaded = engine.load_goal("goal-1").await.unwrap();

            assert!(loaded.is_some());
            let loaded = loaded.unwrap();
            assert_eq!(loaded.id, "goal-1");
            assert_eq!(loaded.title, "Test Goal");
        });
    }

    #[test]
    fn test_list_goals() {
        let dir = TestDir::new("lmdb_test_list_goals");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let goal1 = make_goal("goal-1", "First Goal");
        let goal2 = make_goal("goal-2", "Second Goal");

        future::block_on(async {
            engine.save_goal(&goal1).await.unwrap();
            engine.save_goal(&goal2).await.unwrap();

            let goals = engine.list_goals().await.unwrap();
            assert_eq!(goals.len(), 2);
        });
    }

    #[test]
    fn test_delete_goal() {
        let dir = TestDir::new("lmdb_test_delete_goal");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let goal = make_goal("goal-1", "Test Goal");

        future::block_on(async {
            engine.save_goal(&goal).await.unwrap();
            engine.delete_goal("goal-1").await.unwrap();

            let loaded = engine.load_goal("goal-1").await.unwrap();
            assert!(loaded.is_none());
        });
    }

    // =========================================================================
    // Goal System Tests - Plans
    // =========================================================================

    #[test]
    fn test_save_and_load_plan() {
        let dir = TestDir::new("lmdb_test_save_and_load_plan");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let goal = make_goal("goal-1", "Test Goal");
        let plan = make_plan("plan-1", "goal-1", "Test Plan");

        future::block_on(async {
            engine.save_goal(&goal).await.unwrap();
            engine.save_plan(&plan).await.unwrap();
            let loaded = engine.load_plan("plan-1").await.unwrap();

            assert!(loaded.is_some());
            let loaded = loaded.unwrap();
            assert_eq!(loaded.id, "plan-1");
            assert_eq!(loaded.title, "Test Plan");
            assert_eq!(loaded.goal_id, "goal-1");
        });
    }

    #[test]
    fn test_list_plans_by_goal() {
        let dir = TestDir::new("lmdb_test_list_plans_by_goal");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let goal1 = make_goal("goal-1", "Goal 1");
        let goal2 = make_goal("goal-2", "Goal 2");
        let plan1 = make_plan("plan-1", "goal-1", "Plan 1");
        let plan2 = make_plan("plan-2", "goal-1", "Plan 2");
        let plan3 = make_plan("plan-3", "goal-2", "Plan 3");

        future::block_on(async {
            engine.save_goal(&goal1).await.unwrap();
            engine.save_goal(&goal2).await.unwrap();
            engine.save_plan(&plan1).await.unwrap();
            engine.save_plan(&plan2).await.unwrap();
            engine.save_plan(&plan3).await.unwrap();

            // Filter by goal-1
            let plans = engine.list_plans(Some("goal-1")).await.unwrap();
            assert_eq!(plans.len(), 2);

            // Filter by goal-2
            let plans = engine.list_plans(Some("goal-2")).await.unwrap();
            assert_eq!(plans.len(), 1);
            assert_eq!(plans[0].id, "plan-3");

            // All plans
            let all_plans = engine.list_plans(None).await.unwrap();
            assert_eq!(all_plans.len(), 3);
        });
    }

    #[test]
    fn test_delete_plan_cleans_index() {
        let dir = TestDir::new("lmdb_test_delete_plan_cleans_index");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let goal = make_goal("goal-1", "Test Goal");
        let plan = make_plan("plan-1", "goal-1", "Test Plan");

        future::block_on(async {
            engine.save_goal(&goal).await.unwrap();
            engine.save_plan(&plan).await.unwrap();

            // Verify plan is in index
            let plans = engine.list_plans(Some("goal-1")).await.unwrap();
            assert_eq!(plans.len(), 1);

            // Delete plan
            engine.delete_plan("plan-1").await.unwrap();

            // Verify index is cleaned up
            let plans = engine.list_plans(Some("goal-1")).await.unwrap();
            assert_eq!(plans.len(), 0);
        });
    }

    // =========================================================================
    // Goal System Tests - Todos
    // =========================================================================

    #[test]
    fn test_save_and_load_todo() {
        let dir = TestDir::new("lmdb_test_save_and_load_todo");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let todo = make_todo_data("todo-1", "Test Todo");

        future::block_on(async {
            engine.save_todo(&todo).await.unwrap();
            let loaded = engine.load_todo("todo-1").await.unwrap();

            assert!(loaded.is_some());
            let loaded = loaded.unwrap();
            assert_eq!(loaded.id, "todo-1");
            assert_eq!(loaded.title, "Test Todo");
        });
    }

    #[test]
    fn test_list_todos() {
        let dir = TestDir::new("lmdb_test_list_todos");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let todo1 = make_todo_data("todo-1", "Todo 1");
        let todo2 = make_todo_data("todo-2", "Todo 2");

        future::block_on(async {
            engine.save_todo(&todo1).await.unwrap();
            engine.save_todo(&todo2).await.unwrap();

            let todos = engine.list_todos(None).await.unwrap();
            assert_eq!(todos.len(), 2);
        });
    }

    // =========================================================================
    // Goal System Tests - Todo-Plan Links
    // =========================================================================

    #[test]
    fn test_todo_plan_link() {
        let dir = TestDir::new("lmdb_test_todo_plan_link");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let goal = make_goal("goal-1", "Test Goal");
        let plan = make_plan("plan-1", "goal-1", "Test Plan");
        let todo = make_todo_data("todo-1", "Test Todo");

        future::block_on(async {
            engine.save_goal(&goal).await.unwrap();
            engine.save_plan(&plan).await.unwrap();
            engine.save_todo(&todo).await.unwrap();

            // Create link
            let link = TodoPlanLink {
                todo_id: "todo-1".to_string(),
                plan_id: "plan-1".to_string(),
                created_at: "2024-01-01T00:00:00Z".to_string(),
            };
            engine.save_todo_plan_link(&link).await.unwrap();

            // Verify bidirectional lookup
            let plans = engine.get_plans_for_todo("todo-1").await.unwrap();
            assert_eq!(plans.len(), 1);
            assert_eq!(plans[0].id, "plan-1");

            let todos = engine.get_todos_for_plan("plan-1").await.unwrap();
            assert_eq!(todos.len(), 1);
            assert_eq!(todos[0].id, "todo-1");

            // List todos filtered by plan
            let filtered = engine.list_todos(Some("plan-1")).await.unwrap();
            assert_eq!(filtered.len(), 1);
        });
    }

    #[test]
    fn test_todo_multiple_plans() {
        let dir = TestDir::new("lmdb_test_todo_multiple_plans");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let goal = make_goal("goal-1", "Test Goal");
        let plan1 = make_plan("plan-1", "goal-1", "Plan 1");
        let plan2 = make_plan("plan-2", "goal-1", "Plan 2");
        let todo = make_todo_data("todo-1", "Shared Todo");

        future::block_on(async {
            engine.save_goal(&goal).await.unwrap();
            engine.save_plan(&plan1).await.unwrap();
            engine.save_plan(&plan2).await.unwrap();
            engine.save_todo(&todo).await.unwrap();

            // Link todo to both plans
            let link1 = TodoPlanLink {
                todo_id: "todo-1".to_string(),
                plan_id: "plan-1".to_string(),
                created_at: "2024-01-01T00:00:00Z".to_string(),
            };
            let link2 = TodoPlanLink {
                todo_id: "todo-1".to_string(),
                plan_id: "plan-2".to_string(),
                created_at: "2024-01-01T00:00:00Z".to_string(),
            };
            engine.save_todo_plan_link(&link1).await.unwrap();
            engine.save_todo_plan_link(&link2).await.unwrap();

            // Todo should belong to 2 plans
            let plans = engine.get_plans_for_todo("todo-1").await.unwrap();
            assert_eq!(plans.len(), 2);
        });
    }

    #[test]
    fn test_delete_todo_plan_link() {
        let dir = TestDir::new("lmdb_test_delete_todo_plan_link");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let goal = make_goal("goal-1", "Test Goal");
        let plan = make_plan("plan-1", "goal-1", "Test Plan");
        let todo = make_todo_data("todo-1", "Test Todo");

        future::block_on(async {
            engine.save_goal(&goal).await.unwrap();
            engine.save_plan(&plan).await.unwrap();
            engine.save_todo(&todo).await.unwrap();

            let link = TodoPlanLink {
                todo_id: "todo-1".to_string(),
                plan_id: "plan-1".to_string(),
                created_at: "2024-01-01T00:00:00Z".to_string(),
            };
            engine.save_todo_plan_link(&link).await.unwrap();

            // Delete the link
            engine.delete_todo_plan_link("todo-1", "plan-1").await.unwrap();

            // Verify link is gone
            let plans = engine.get_plans_for_todo("todo-1").await.unwrap();
            assert_eq!(plans.len(), 0);

            let todos = engine.get_todos_for_plan("plan-1").await.unwrap();
            assert_eq!(todos.len(), 0);
        });
    }

    // =========================================================================
    // Goal System Tests - Todo Dependencies
    // =========================================================================

    #[test]
    fn test_todo_dependency() {
        let dir = TestDir::new("lmdb_test_todo_dependency");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let todo1 = make_todo_data("todo-1", "First Todo");
        let todo2 = make_todo_data("todo-2", "Second Todo");

        future::block_on(async {
            engine.save_todo(&todo1).await.unwrap();
            engine.save_todo(&todo2).await.unwrap();

            // todo-2 depends on todo-1
            let dep = TodoDependency {
                todo_id: "todo-2".to_string(),
                depends_on_id: "todo-1".to_string(),
                created_at: "2024-01-01T00:00:00Z".to_string(),
            };
            engine.save_todo_dependency(&dep).await.unwrap();

            // Check dependencies (what todo-2 depends on)
            let deps = engine.get_dependencies("todo-2").await.unwrap();
            assert_eq!(deps.len(), 1);
            assert_eq!(deps[0].id, "todo-1");

            // Check dependents (what depends on todo-1)
            let dependents = engine.get_dependents("todo-1").await.unwrap();
            assert_eq!(dependents.len(), 1);
            assert_eq!(dependents[0].id, "todo-2");
        });
    }

    #[test]
    fn test_delete_todo_dependency() {
        let dir = TestDir::new("lmdb_test_delete_todo_dependency");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let todo1 = make_todo_data("todo-1", "First Todo");
        let todo2 = make_todo_data("todo-2", "Second Todo");

        future::block_on(async {
            engine.save_todo(&todo1).await.unwrap();
            engine.save_todo(&todo2).await.unwrap();

            let dep = TodoDependency {
                todo_id: "todo-2".to_string(),
                depends_on_id: "todo-1".to_string(),
                created_at: "2024-01-01T00:00:00Z".to_string(),
            };
            engine.save_todo_dependency(&dep).await.unwrap();

            // Delete the dependency
            engine.delete_todo_dependency("todo-2", "todo-1").await.unwrap();

            // Verify dependency is gone
            let deps = engine.get_dependencies("todo-2").await.unwrap();
            assert_eq!(deps.len(), 0);

            let dependents = engine.get_dependents("todo-1").await.unwrap();
            assert_eq!(dependents.len(), 0);
        });
    }

    #[test]
    fn test_delete_todo_cleans_up_links_and_deps() {
        let dir = TestDir::new("lmdb_test_delete_todo_cleanup");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let goal = make_goal("goal-1", "Test Goal");
        let plan = make_plan("plan-1", "goal-1", "Test Plan");
        let todo1 = make_todo_data("todo-1", "Todo 1");
        let todo2 = make_todo_data("todo-2", "Todo 2");

        future::block_on(async {
            engine.save_goal(&goal).await.unwrap();
            engine.save_plan(&plan).await.unwrap();
            engine.save_todo(&todo1).await.unwrap();
            engine.save_todo(&todo2).await.unwrap();

            // Link todo-1 to plan
            let link = TodoPlanLink {
                todo_id: "todo-1".to_string(),
                plan_id: "plan-1".to_string(),
                created_at: "2024-01-01T00:00:00Z".to_string(),
            };
            engine.save_todo_plan_link(&link).await.unwrap();

            // todo-2 depends on todo-1
            let dep = TodoDependency {
                todo_id: "todo-2".to_string(),
                depends_on_id: "todo-1".to_string(),
                created_at: "2024-01-01T00:00:00Z".to_string(),
            };
            engine.save_todo_dependency(&dep).await.unwrap();

            // Delete todo-1
            engine.delete_todo("todo-1").await.unwrap();

            // Verify todo-1 is gone
            let loaded = engine.load_todo("todo-1").await.unwrap();
            assert!(loaded.is_none());

            // Verify link is cleaned up
            let todos = engine.get_todos_for_plan("plan-1").await.unwrap();
            assert_eq!(todos.len(), 0);

            // Verify dependency is cleaned up
            let deps = engine.get_dependencies("todo-2").await.unwrap();
            assert_eq!(deps.len(), 0);
        });
    }

    // =========================================================================
    // Goal System Tests - Session Bindings
    // =========================================================================

    #[test]
    fn test_save_and_load_session_binding() {
        let dir = TestDir::new("lmdb_test_save_and_load_binding");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let binding = make_binding("bind-1", "sess-1", "todo", "todo-1");

        future::block_on(async {
            engine.save_session_binding(&binding).await.unwrap();
            let loaded = engine.load_session_binding("bind-1").await.unwrap();

            assert!(loaded.is_some());
            let loaded = loaded.unwrap();
            assert_eq!(loaded.id, "bind-1");
            assert_eq!(loaded.session_id, "sess-1");
            assert_eq!(loaded.entity_type, "todo");
            assert_eq!(loaded.entity_id, "todo-1");
        });
    }

    #[test]
    fn test_bindings_by_session() {
        let dir = TestDir::new("lmdb_test_bindings_by_session");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let binding1 = make_binding("bind-1", "sess-1", "todo", "todo-1");
        let binding2 = make_binding("bind-2", "sess-1", "goal", "goal-1");
        let binding3 = make_binding("bind-3", "sess-2", "todo", "todo-2");

        future::block_on(async {
            engine.save_session_binding(&binding1).await.unwrap();
            engine.save_session_binding(&binding2).await.unwrap();
            engine.save_session_binding(&binding3).await.unwrap();

            let bindings = engine.get_bindings_for_session("sess-1").await.unwrap();
            assert_eq!(bindings.len(), 2);

            let bindings = engine.get_bindings_for_session("sess-2").await.unwrap();
            assert_eq!(bindings.len(), 1);
        });
    }

    #[test]
    fn test_bindings_by_entity() {
        let dir = TestDir::new("lmdb_test_bindings_by_entity");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let binding1 = make_binding("bind-1", "sess-1", "todo", "todo-1");
        let binding2 = make_binding("bind-2", "sess-2", "todo", "todo-1");
        let binding3 = make_binding("bind-3", "sess-1", "goal", "goal-1");

        future::block_on(async {
            engine.save_session_binding(&binding1).await.unwrap();
            engine.save_session_binding(&binding2).await.unwrap();
            engine.save_session_binding(&binding3).await.unwrap();

            // Two sessions bound to todo-1
            let bindings = engine.get_bindings_for_entity("todo", "todo-1").await.unwrap();
            assert_eq!(bindings.len(), 2);

            // One session bound to goal-1
            let bindings = engine.get_bindings_for_entity("goal", "goal-1").await.unwrap();
            assert_eq!(bindings.len(), 1);
        });
    }

    #[test]
    fn test_delete_session_binding() {
        let dir = TestDir::new("lmdb_test_delete_binding");
        let engine = LmdbEngine::open(dir.db_path()).unwrap();

        let binding = make_binding("bind-1", "sess-1", "todo", "todo-1");

        future::block_on(async {
            engine.save_session_binding(&binding).await.unwrap();

            // Verify indexes are populated
            let by_session = engine.get_bindings_for_session("sess-1").await.unwrap();
            assert_eq!(by_session.len(), 1);
            let by_entity = engine.get_bindings_for_entity("todo", "todo-1").await.unwrap();
            assert_eq!(by_entity.len(), 1);

            // Delete binding
            engine.delete_session_binding("bind-1").await.unwrap();

            // Verify binding is gone
            let loaded = engine.load_session_binding("bind-1").await.unwrap();
            assert!(loaded.is_none());

            // Verify indexes are cleaned up
            let by_session = engine.get_bindings_for_session("sess-1").await.unwrap();
            assert_eq!(by_session.len(), 0);
            let by_entity = engine.get_bindings_for_entity("todo", "todo-1").await.unwrap();
            assert_eq!(by_entity.len(), 0);
        });
    }

}
