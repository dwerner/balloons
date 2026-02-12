use async_trait::async_trait;
use thiserror::Error;

use crate::generated::{
    GoalData, PlanData, SessionBinding, SessionData, SessionMetadata, TodoData, TodoDependency,
    TodoPlanLink, TurnData,
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
}
