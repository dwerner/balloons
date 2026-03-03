use async_trait::async_trait;
use thiserror::Error;

use crate::generated::{
    BoardData, ColumnData, EdgeData, GoalData, PlanData, SessionBinding, SessionData,
    SessionMetadata, TaskData, TodoData, TodoDependency, TodoPlanLink, TurnData, UserData,
    UserPrefs, WatcherRelation,
};

#[derive(Debug, Error)]
pub enum Error {
    #[error("Session not found: {0}")]
    SessionNotFound(String),

    #[error("Turn not found: {0}")]
    TurnNotFound(String),

    #[error("Goal not found: {0}")]
    GoalNotFound(String),

    #[error("Plan not found: {0}")]
    PlanNotFound(String),

    #[error("Todo not found: {0}")]
    TodoNotFound(String),

    #[error("Session binding not found: {0}")]
    BindingNotFound(String),

    #[error("User not found: {0}")]
    UserNotFound(String),

    #[error("Task not found: {0}")]
    TaskNotFound(String),

    #[error("Board not found: {0}")]
    BoardNotFound(String),

    #[error("Column not found: {0}")]
    ColumnNotFound(String),

    #[error("Edge not found: {0}")]
    EdgeNotFound(String),

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

    /// Get the number of turns for a session (without loading turn data)
    ///
    /// Returns 0 if the session has no turns or doesn't exist.
    async fn get_turn_count(&self, session_id: &str) -> Result<usize>;

    /// Load a range of turns for a session (for chunked/paginated loading)
    ///
    /// Returns turns starting at `offset` (0-indexed) up to `limit` turns.
    /// If offset is beyond the number of turns, returns an empty vec.
    /// Turns are returned in their stored order (oldest first by default).
    async fn load_turns_range(
        &self,
        session_id: &str,
        offset: usize,
        limit: usize,
    ) -> Result<Vec<TurnData>>;

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

    // =========================================================================
    // Session History - tracks recently viewed sessions (MRU list)
    // =========================================================================

    /// Load the session history (list of session IDs, most recent first).
    ///
    /// Returns an empty vector if no history exists.
    async fn load_session_history(&self) -> Result<Vec<String>>;

    /// Save the session history (list of session IDs, most recent first).
    ///
    /// This replaces the entire history. The caller is responsible for
    /// maintaining ordering and size limits.
    async fn save_session_history(&self, session_ids: &[String]) -> Result<()>;

    // =========================================================================
    // Goal System - Goals
    // =========================================================================

    /// Save a goal (upsert).
    async fn save_goal(&self, goal: &GoalData) -> Result<()>;

    /// Load a goal by ID.
    async fn load_goal(&self, id: &str) -> Result<Option<GoalData>>;

    /// Delete a goal by ID.
    ///
    /// Note: This does not cascade delete plans or todos. Callers should
    /// handle cleanup of related entities if needed.
    async fn delete_goal(&self, id: &str) -> Result<()>;

    /// List all goals.
    async fn list_goals(&self) -> Result<Vec<GoalData>>;

    // =========================================================================
    // Goal System - Plans
    // =========================================================================

    /// Save a plan (upsert).
    ///
    /// Automatically maintains the plans_by_goal index.
    async fn save_plan(&self, plan: &PlanData) -> Result<()>;

    /// Load a plan by ID.
    async fn load_plan(&self, id: &str) -> Result<Option<PlanData>>;

    /// Delete a plan by ID.
    ///
    /// Automatically cleans up the plans_by_goal index.
    /// Note: This does not cascade delete todos. Callers should handle cleanup.
    async fn delete_plan(&self, id: &str) -> Result<()>;

    /// List all plans, optionally filtered by goal_id.
    ///
    /// If goal_id is Some, returns only plans belonging to that goal.
    /// If goal_id is None, returns all plans.
    async fn list_plans(&self, goal_id: Option<&str>) -> Result<Vec<PlanData>>;

    // =========================================================================
    // Goal System - Todos
    // =========================================================================

    /// Save a todo (upsert).
    async fn save_todo(&self, todo: &TodoData) -> Result<()>;

    /// Load a todo by ID.
    async fn load_todo(&self, id: &str) -> Result<Option<TodoData>>;

    /// Delete a todo by ID.
    ///
    /// Automatically cleans up:
    /// - Todo-plan links (removes from all plans)
    /// - Todo dependencies (both directions)
    async fn delete_todo(&self, id: &str) -> Result<()>;

    /// List all todos, optionally filtered by plan_id.
    ///
    /// If plan_id is Some, returns only todos linked to that plan.
    /// If plan_id is None, returns all todos.
    async fn list_todos(&self, plan_id: Option<&str>) -> Result<Vec<TodoData>>;

    // =========================================================================
    // Goal System - Todo-Plan Links (many-to-many relationship)
    // =========================================================================

    /// Link a todo to a plan.
    ///
    /// A todo can belong to multiple plans. This creates the bidirectional
    /// relationship in both todos_by_plan and plans_by_todo indexes.
    async fn save_todo_plan_link(&self, link: &TodoPlanLink) -> Result<()>;

    /// Remove a todo from a plan.
    ///
    /// Removes the link from both indexes.
    async fn delete_todo_plan_link(&self, todo_id: &str, plan_id: &str) -> Result<()>;

    /// Get all plans that a todo belongs to.
    async fn get_plans_for_todo(&self, todo_id: &str) -> Result<Vec<PlanData>>;

    /// Get all todos in a plan.
    async fn get_todos_for_plan(&self, plan_id: &str) -> Result<Vec<TodoData>>;

    // =========================================================================
    // Goal System - Todo Dependencies
    // =========================================================================

    /// Create a dependency: todo_id depends on depends_on_id.
    ///
    /// Maintains both the dependencies and dependents indexes.
    async fn save_todo_dependency(&self, dependency: &TodoDependency) -> Result<()>;

    /// Remove a dependency.
    async fn delete_todo_dependency(&self, todo_id: &str, depends_on_id: &str) -> Result<()>;

    /// Get todos that the given todo depends on (prerequisites).
    async fn get_dependencies(&self, todo_id: &str) -> Result<Vec<TodoData>>;

    /// Get todos that depend on the given todo (blockers).
    async fn get_dependents(&self, todo_id: &str) -> Result<Vec<TodoData>>;

    // =========================================================================
    // Goal System - Session Bindings
    // =========================================================================

    /// Save a session binding (upsert).
    ///
    /// Automatically maintains the bindings_by_session and bindings_by_entity indexes.
    async fn save_session_binding(&self, binding: &SessionBinding) -> Result<()>;

    /// Load a session binding by ID.
    async fn load_session_binding(&self, id: &str) -> Result<Option<SessionBinding>>;

    /// Delete a session binding by ID.
    ///
    /// Automatically cleans up both indexes.
    async fn delete_session_binding(&self, id: &str) -> Result<()>;

    /// Get all bindings for a session.
    async fn get_bindings_for_session(&self, session_id: &str) -> Result<Vec<SessionBinding>>;

    /// Get all bindings for an entity (goal, plan, or todo).
    ///
    /// entity_type should be "goal", "plan", or "todo".
    async fn get_bindings_for_entity(
        &self,
        entity_type: &str,
        entity_id: &str,
    ) -> Result<Vec<SessionBinding>>;

    /// List all session bindings in the storage.
    ///
    /// Returns all bindings regardless of session or entity.
    async fn list_bindings(&self) -> Result<Vec<SessionBinding>>;

    // =========================================================================
    // User Preferences
    // =========================================================================

    /// Load user preferences.
    ///
    /// Returns default prefs if none have been saved.
    async fn load_user_prefs(&self) -> Result<UserPrefs>;

    /// Save user preferences.
    ///
    /// Replaces all existing preferences with the provided data.
    async fn save_user_prefs(&self, prefs: &UserPrefs) -> Result<()>;

    // =========================================================================
    // Watcher Relationships
    // =========================================================================

    /// Save a watcher relationship (upsert).
    ///
    /// Automatically maintains indexes for lookup by watcher and target.
    async fn save_watcher(&self, watcher: &WatcherRelation) -> Result<()>;

    /// Delete a watcher relationship by ID.
    async fn delete_watcher(&self, id: &str) -> Result<()>;

    /// Get all watchers for a target session.
    ///
    /// Returns all sessions watching the given target.
    async fn get_watchers_for_target(&self, target_session_id: &str) -> Result<Vec<WatcherRelation>>;

    /// Get all targets a watcher session is watching.
    ///
    /// Returns all sessions being watched by the given watcher.
    async fn get_targets_for_watcher(&self, watcher_session_id: &str) -> Result<Vec<WatcherRelation>>;

    /// List all watcher relationships.
    async fn list_watchers(&self) -> Result<Vec<WatcherRelation>>;

    // =========================================================================
    // User Management
    // =========================================================================

    /// Save a user (upsert).
    ///
    /// Automatically maintains the users_by_username index for efficient
    /// username lookups.
    async fn save_user(&self, user: &UserData) -> Result<()>;

    /// Load a user by ID.
    async fn load_user(&self, id: &str) -> Result<Option<UserData>>;

    /// Load a user by username (case-insensitive).
    ///
    /// Uses the users_by_username index for O(1) lookup.
    async fn load_user_by_username(&self, username: &str) -> Result<Option<UserData>>;

    /// Delete a user by ID.
    ///
    /// Automatically cleans up the users_by_username index.
    async fn delete_user(&self, id: &str) -> Result<()>;

    /// List all users.
    async fn list_users(&self) -> Result<Vec<UserData>>;

    // =========================================================================
    // Kanban System - Tasks
    // =========================================================================

    /// Save a task (upsert).
    async fn save_task(&self, task: &TaskData) -> Result<()>;

    /// Load a task by ID.
    async fn load_task(&self, id: &str) -> Result<Option<TaskData>>;

    /// Delete a task by ID.
    ///
    /// Note: This does not cascade delete edges. Callers should handle
    /// cleanup of related edges if needed.
    async fn delete_task(&self, id: &str) -> Result<()>;

    /// List all tasks.
    async fn list_tasks(&self) -> Result<Vec<TaskData>>;

    // =========================================================================
    // Kanban System - Boards
    // =========================================================================

    /// Save a board (upsert).
    async fn save_board(&self, board: &BoardData) -> Result<()>;

    /// Load a board by ID.
    async fn load_board(&self, id: &str) -> Result<Option<BoardData>>;

    /// Delete a board by ID.
    ///
    /// Note: This does not cascade delete columns or edges. Callers should
    /// handle cleanup of related entities if needed.
    async fn delete_board(&self, id: &str) -> Result<()>;

    /// List all boards.
    async fn list_boards(&self) -> Result<Vec<BoardData>>;

    // =========================================================================
    // Kanban System - Columns
    // =========================================================================

    /// Save a column (upsert).
    async fn save_column(&self, column: &ColumnData) -> Result<()>;

    /// Load a column by ID.
    async fn load_column(&self, id: &str) -> Result<Option<ColumnData>>;

    /// Delete a column by ID.
    ///
    /// Note: This does not cascade delete edges. Callers should handle
    /// cleanup of related edges if needed.
    async fn delete_column(&self, id: &str) -> Result<()>;

    // =========================================================================
    // Graph System - Edges
    // =========================================================================

    /// Save an edge (upsert).
    ///
    /// Automatically maintains the edges_by_source and edges_by_target indexes.
    async fn save_edge(&self, edge: &EdgeData) -> Result<()>;

    /// Load an edge by ID.
    async fn load_edge(&self, id: &str) -> Result<Option<EdgeData>>;

    /// Delete an edge by ID.
    ///
    /// Automatically cleans up both indexes.
    async fn delete_edge(&self, id: &str) -> Result<()>;

    /// Query edges by source entity.
    ///
    /// Returns all edges where the source matches the given type and ID.
    /// Results are ordered by position (if set), then by created_at.
    async fn get_edges_by_source(
        &self,
        source_type: &str,
        source_id: &str,
    ) -> Result<Vec<EdgeData>>;

    /// Query edges by target entity.
    ///
    /// Returns all edges where the target matches the given type and ID.
    /// Results are ordered by position (if set), then by created_at.
    async fn get_edges_by_target(
        &self,
        target_type: &str,
        target_id: &str,
    ) -> Result<Vec<EdgeData>>;

    /// Query edges by source and relationship type.
    ///
    /// Returns all edges from the source with the given relationship.
    /// Results are ordered by position (if set), then by created_at.
    async fn get_edges_by_source_and_relationship(
        &self,
        source_type: &str,
        source_id: &str,
        relationship: &str,
    ) -> Result<Vec<EdgeData>>;

    /// Query edges by target and relationship type.
    ///
    /// Returns all edges to the target with the given relationship.
    /// Results are ordered by position (if set), then by created_at.
    async fn get_edges_by_target_and_relationship(
        &self,
        target_type: &str,
        target_id: &str,
        relationship: &str,
    ) -> Result<Vec<EdgeData>>;

    /// List all edges.
    async fn list_edges(&self) -> Result<Vec<EdgeData>>;
}
