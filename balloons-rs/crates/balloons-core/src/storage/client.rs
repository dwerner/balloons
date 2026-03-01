use std::sync::Arc;

use crate::generated::{
    GoalData, PlanData, SessionBinding, SessionData, SessionMetadata, TodoData, TodoDependency,
    TodoPlanLink, TurnData, UserData, UserPrefs, WatcherRelation,
};
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

    /// Get the number of turns for a session (without loading turn data).
    pub async fn get_turn_count(&self, session_id: &str) -> Result<usize> {
        self.engine.get_turn_count(session_id).await
    }

    /// Load a range of turns for a session (for chunked/paginated loading).
    ///
    /// Returns turns starting at `offset` (0-indexed) up to `limit` turns.
    pub async fn load_turns_range(
        &self,
        session_id: &str,
        offset: usize,
        limit: usize,
    ) -> Result<Vec<TurnData>> {
        self.engine.load_turns_range(session_id, offset, limit).await
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

    // =========================================================================
    // Goal System - Goals
    // =========================================================================

    /// Save a goal (upsert).
    pub async fn save_goal(&self, goal: &GoalData) -> Result<()> {
        self.engine.save_goal(goal).await
    }

    /// Load a goal by ID.
    pub async fn load_goal(&self, id: &str) -> Result<Option<GoalData>> {
        self.engine.load_goal(id).await
    }

    /// Delete a goal by ID.
    pub async fn delete_goal(&self, id: &str) -> Result<()> {
        self.engine.delete_goal(id).await
    }

    /// List all goals.
    pub async fn list_goals(&self) -> Result<Vec<GoalData>> {
        self.engine.list_goals().await
    }

    // =========================================================================
    // Goal System - Plans
    // =========================================================================

    /// Save a plan (upsert).
    pub async fn save_plan(&self, plan: &PlanData) -> Result<()> {
        self.engine.save_plan(plan).await
    }

    /// Load a plan by ID.
    pub async fn load_plan(&self, id: &str) -> Result<Option<PlanData>> {
        self.engine.load_plan(id).await
    }

    /// Delete a plan by ID.
    pub async fn delete_plan(&self, id: &str) -> Result<()> {
        self.engine.delete_plan(id).await
    }

    /// List all plans, optionally filtered by goal_id.
    pub async fn list_plans(&self, goal_id: Option<&str>) -> Result<Vec<PlanData>> {
        self.engine.list_plans(goal_id).await
    }

    // =========================================================================
    // Goal System - Todos
    // =========================================================================

    /// Save a todo (upsert).
    pub async fn save_todo(&self, todo: &TodoData) -> Result<()> {
        self.engine.save_todo(todo).await
    }

    /// Load a todo by ID.
    pub async fn load_todo(&self, id: &str) -> Result<Option<TodoData>> {
        self.engine.load_todo(id).await
    }

    /// Delete a todo by ID.
    pub async fn delete_todo(&self, id: &str) -> Result<()> {
        self.engine.delete_todo(id).await
    }

    /// List all todos, optionally filtered by plan_id.
    pub async fn list_todos(&self, plan_id: Option<&str>) -> Result<Vec<TodoData>> {
        self.engine.list_todos(plan_id).await
    }

    // =========================================================================
    // Goal System - Todo-Plan Links
    // =========================================================================

    /// Link a todo to a plan.
    pub async fn save_todo_plan_link(&self, link: &TodoPlanLink) -> Result<()> {
        self.engine.save_todo_plan_link(link).await
    }

    /// Remove a todo from a plan.
    pub async fn delete_todo_plan_link(&self, todo_id: &str, plan_id: &str) -> Result<()> {
        self.engine.delete_todo_plan_link(todo_id, plan_id).await
    }

    /// Get all plans that a todo belongs to.
    pub async fn get_plans_for_todo(&self, todo_id: &str) -> Result<Vec<PlanData>> {
        self.engine.get_plans_for_todo(todo_id).await
    }

    /// Get all todos in a plan.
    pub async fn get_todos_for_plan(&self, plan_id: &str) -> Result<Vec<TodoData>> {
        self.engine.get_todos_for_plan(plan_id).await
    }

    // =========================================================================
    // Goal System - Todo Dependencies
    // =========================================================================

    /// Create a dependency: todo_id depends on depends_on_id.
    pub async fn save_todo_dependency(&self, dependency: &TodoDependency) -> Result<()> {
        self.engine.save_todo_dependency(dependency).await
    }

    /// Remove a dependency.
    pub async fn delete_todo_dependency(&self, todo_id: &str, depends_on_id: &str) -> Result<()> {
        self.engine.delete_todo_dependency(todo_id, depends_on_id).await
    }

    /// Get todos that the given todo depends on (prerequisites).
    pub async fn get_dependencies(&self, todo_id: &str) -> Result<Vec<TodoData>> {
        self.engine.get_dependencies(todo_id).await
    }

    /// Get todos that depend on the given todo (blockers).
    pub async fn get_dependents(&self, todo_id: &str) -> Result<Vec<TodoData>> {
        self.engine.get_dependents(todo_id).await
    }

    // =========================================================================
    // Goal System - Session Bindings
    // =========================================================================

    /// Save a session binding (upsert).
    pub async fn save_session_binding(&self, binding: &SessionBinding) -> Result<()> {
        self.engine.save_session_binding(binding).await
    }

    /// Load a session binding by ID.
    pub async fn load_session_binding(&self, id: &str) -> Result<Option<SessionBinding>> {
        self.engine.load_session_binding(id).await
    }

    /// Delete a session binding by ID.
    pub async fn delete_session_binding(&self, id: &str) -> Result<()> {
        self.engine.delete_session_binding(id).await
    }

    /// Get all bindings for a session.
    pub async fn get_bindings_for_session(&self, session_id: &str) -> Result<Vec<SessionBinding>> {
        self.engine.get_bindings_for_session(session_id).await
    }

    /// Get all bindings for an entity (goal, plan, or todo).
    pub async fn get_bindings_for_entity(
        &self,
        entity_type: &str,
        entity_id: &str,
    ) -> Result<Vec<SessionBinding>> {
        self.engine.get_bindings_for_entity(entity_type, entity_id).await
    }

    /// List all session bindings in the storage.
    pub async fn list_bindings(&self) -> Result<Vec<SessionBinding>> {
        self.engine.list_bindings().await
    }

    // =========================================================================
    // User Preferences
    // =========================================================================

    /// Load user preferences.
    pub async fn load_user_prefs(&self) -> Result<UserPrefs> {
        self.engine.load_user_prefs().await
    }

    /// Save user preferences.
    pub async fn save_user_prefs(&self, prefs: &UserPrefs) -> Result<()> {
        self.engine.save_user_prefs(prefs).await
    }

    // =========================================================================
    // Watcher Relationships
    // =========================================================================

    /// Save a watcher relationship (upsert).
    pub async fn save_watcher(&self, watcher: &WatcherRelation) -> Result<()> {
        self.engine.save_watcher(watcher).await
    }

    /// Delete a watcher relationship.
    pub async fn delete_watcher(&self, id: &str) -> Result<()> {
        self.engine.delete_watcher(id).await
    }

    /// Get all watchers for a target session.
    pub async fn get_watchers_for_target(&self, target_session_id: &str) -> Result<Vec<WatcherRelation>> {
        self.engine.get_watchers_for_target(target_session_id).await
    }

    /// Get all targets a watcher session is watching.
    pub async fn get_targets_for_watcher(&self, watcher_session_id: &str) -> Result<Vec<WatcherRelation>> {
        self.engine.get_targets_for_watcher(watcher_session_id).await
    }

    /// List all watcher relationships.
    pub async fn list_watchers(&self) -> Result<Vec<WatcherRelation>> {
        self.engine.list_watchers().await
    }

    // =========================================================================
    // User Management
    // =========================================================================

    /// Save a user (upsert).
    pub async fn save_user(&self, user: &UserData) -> Result<()> {
        self.engine.save_user(user).await
    }

    /// Load a user by ID.
    pub async fn load_user(&self, id: &str) -> Result<Option<UserData>> {
        self.engine.load_user(id).await
    }

    /// Load a user by username (case-insensitive).
    pub async fn load_user_by_username(&self, username: &str) -> Result<Option<UserData>> {
        self.engine.load_user_by_username(username).await
    }

    /// Delete a user by ID.
    pub async fn delete_user(&self, id: &str) -> Result<()> {
        self.engine.delete_user(id).await
    }

    /// List all users.
    pub async fn list_users(&self) -> Result<Vec<UserData>> {
        self.engine.list_users().await
    }
}
