//! PyO3 bindings for balloons-core storage and balloons-supervisor.
//!
//! Uses core-executor's ThreadPoolExecutor for CPU-affine async execution.

use core_executor::ThreadPoolExecutor;
use futures_lite::future;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::sync::{Arc, Mutex, OnceLock};

use balloons_core::{
    GoalData, LmdbEngine, PlanData, SessionBinding, SessionData, StorageClient, TodoData,
    TodoDependency, TodoPlanLink, UserPrefs, WatcherRelation,
};
use balloons_supervisor::{ProcessSupervisor, StartRequest};

// Global executor for supervisor operations - needs multiple threads since
// each supervised process runs a long-lived event handler task
static SUPERVISOR_EXECUTOR: OnceLock<Mutex<ThreadPoolExecutor>> = OnceLock::new();

fn get_supervisor_executor() -> &'static Mutex<ThreadPoolExecutor> {
    SUPERVISOR_EXECUTOR.get_or_init(|| Mutex::new(ThreadPoolExecutor::new(8)))
}

/// Python-facing storage handle
///
/// All methods are synchronous from Python's perspective.
/// Internally we use core-executor's ThreadPoolExecutor for CPU-affine execution.
#[pyclass]
struct Storage {
    client: Arc<StorageClient>,
    executor: Arc<Mutex<ThreadPoolExecutor>>,
}

#[pymethods]
impl Storage {
    /// Open a storage database at the given path
    #[new]
    fn new(path: &str) -> PyResult<Self> {
        let engine = LmdbEngine::open(path).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        let client = StorageClient::new(engine);
        // Use a single-core executor for storage operations
        let executor = ThreadPoolExecutor::new(1);
        Ok(Self {
            client: Arc::new(client),
            executor: Arc::new(Mutex::new(executor)),
        })
    }

    /// Save a session from JSON string
    fn save_session(&self, py: Python<'_>, id: &str, json_data: &str) -> PyResult<()> {
        let data: SessionData =
            serde_json::from_str(json_data).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);
        let id = id.to_string();

        // Release GIL and execute on core-executor
        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.save_session(&id, &data).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Load a session, returns JSON string or None
    fn load_session(&self, py: Python<'_>, id: &str) -> PyResult<Option<String>> {
        let client = Arc::clone(&self.client);
        let id = id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.load_session(&id).await });
            let result = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            match result {
                Some(data) => {
                    let json = serde_json::to_string(&data)
                        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
                    Ok(Some(json))
                }
                None => Ok(None),
            }
        })
    }

    /// List all sessions, returns JSON array of metadata
    fn list_sessions(&self, py: Python<'_>) -> PyResult<String> {
        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.list_sessions().await });
            let sessions = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&sessions).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Delete a session by ID
    fn delete_session(&self, py: Python<'_>, id: &str) -> PyResult<()> {
        let client = Arc::clone(&self.client);
        let id = id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.delete_session(&id).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Save a single turn (JSON string) to a session
    fn save_turn(&self, py: Python<'_>, session_id: &str, json_data: &str) -> PyResult<()> {
        let turn: balloons_core::TurnData =
            serde_json::from_str(json_data).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);
        let session_id = session_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task =
                executor.spawn_on_any(async move { client.save_turn(&session_id, &turn).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Load all turns for a session, returns JSON array
    fn load_turns(&self, py: Python<'_>, session_id: &str) -> PyResult<String> {
        let client = Arc::clone(&self.client);
        let session_id = session_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.load_turns(&session_id).await });
            let turns = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&turns).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Get the number of turns for a session (without loading turn data)
    fn get_turn_count(&self, py: Python<'_>, session_id: &str) -> PyResult<usize> {
        let client = Arc::clone(&self.client);
        let session_id = session_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task =
                executor.spawn_on_any(async move { client.get_turn_count(&session_id).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Load a range of turns for a session (for chunked/paginated loading)
    ///
    /// Args:
    ///     session_id: Session ID
    ///     offset: Starting index (0-indexed)
    ///     limit: Maximum number of turns to return
    ///
    /// Returns: JSON array of turn data
    fn load_turns_range(
        &self,
        py: Python<'_>,
        session_id: &str,
        offset: usize,
        limit: usize,
    ) -> PyResult<String> {
        let client = Arc::clone(&self.client);
        let session_id = session_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor
                .spawn_on_any(async move { client.load_turns_range(&session_id, offset, limit).await });
            let turns = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&turns).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Delete a turn by ID
    fn delete_turn(&self, py: Python<'_>, session_id: &str, turn_id: &str) -> PyResult<()> {
        let client = Arc::clone(&self.client);
        let session_id = session_id.to_string();
        let turn_id = turn_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor
                .spawn_on_any(async move { client.delete_turn(&session_id, &turn_id).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Reorder turns within a session (JSON array of turn IDs)
    fn reorder_turns(&self, py: Python<'_>, session_id: &str, turn_ids_json: &str) -> PyResult<()> {
        let turn_ids: Vec<String> = serde_json::from_str(turn_ids_json)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);
        let session_id = session_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor
                .spawn_on_any(async move { client.reorder_turns(&session_id, &turn_ids).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Save a session and all its turns atomically (single transaction).
    ///
    /// Args:
    ///     id: Session ID
    ///     session_json: JSON-encoded session data (without turns)
    ///     turns_json: JSON array of turn data
    ///
    /// This is more efficient than calling save_session + N×save_turn.
    fn save_session_with_turns(
        &self,
        py: Python<'_>,
        id: &str,
        session_json: &str,
        turns_json: &str,
    ) -> PyResult<()> {
        let session: balloons_core::SessionData = serde_json::from_str(session_json)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        let turns: Vec<balloons_core::TurnData> = serde_json::from_str(turns_json)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);
        let id = id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move {
                client.save_session_with_turns(&id, &session, &turns).await
            });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Atomically replace all turns for a session (single transaction).
    ///
    /// Args:
    ///     session_id: Session ID (must already exist)
    ///     turns_json: JSON array of turn data
    ///
    /// This deletes any turns not in the new list, upserts all new turns,
    /// and updates the turn order - all atomically.
    fn replace_session_turns(
        &self,
        py: Python<'_>,
        session_id: &str,
        turns_json: &str,
    ) -> PyResult<()> {
        let turns: Vec<balloons_core::TurnData> = serde_json::from_str(turns_json)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);
        let session_id = session_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move {
                client.replace_session_turns(&session_id, &turns).await
            });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Load the session history (list of session IDs, most recent first).
    ///
    /// Returns:
    ///     JSON array of session IDs
    fn load_session_history(&self, py: Python<'_>) -> PyResult<String> {
        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.load_session_history().await });
            let history = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&history).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Save the session history (list of session IDs, most recent first).
    ///
    /// Args:
    ///     session_ids_json: JSON array of session IDs
    fn save_session_history(&self, py: Python<'_>, session_ids_json: &str) -> PyResult<()> {
        let session_ids: Vec<String> = serde_json::from_str(session_ids_json)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move {
                client.save_session_history(&session_ids).await
            });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    // =========================================================================
    // Goal System - Goals
    // =========================================================================

    /// Save a goal from JSON string (upsert).
    ///
    /// Args:
    ///     goal_json: JSON-encoded GoalData
    fn save_goal(&self, py: Python<'_>, goal_json: &str) -> PyResult<()> {
        let goal: GoalData =
            serde_json::from_str(goal_json).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.save_goal(&goal).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Load a goal by ID, returns JSON string or None.
    ///
    /// Args:
    ///     goal_id: The goal ID
    ///
    /// Returns:
    ///     JSON-encoded GoalData or None if not found
    fn load_goal(&self, py: Python<'_>, goal_id: &str) -> PyResult<Option<String>> {
        let client = Arc::clone(&self.client);
        let goal_id = goal_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.load_goal(&goal_id).await });
            let result = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            match result {
                Some(goal) => {
                    let json = serde_json::to_string(&goal)
                        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
                    Ok(Some(json))
                }
                None => Ok(None),
            }
        })
    }

    /// Delete a goal by ID.
    ///
    /// Args:
    ///     goal_id: The goal ID
    fn delete_goal(&self, py: Python<'_>, goal_id: &str) -> PyResult<()> {
        let client = Arc::clone(&self.client);
        let goal_id = goal_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.delete_goal(&goal_id).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// List all goals, returns JSON array.
    ///
    /// Returns:
    ///     JSON array of GoalData
    fn list_goals(&self, py: Python<'_>) -> PyResult<String> {
        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.list_goals().await });
            let goals = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&goals).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    // =========================================================================
    // Goal System - Plans
    // =========================================================================

    /// Save a plan from JSON string (upsert).
    ///
    /// Args:
    ///     plan_json: JSON-encoded PlanData
    fn save_plan(&self, py: Python<'_>, plan_json: &str) -> PyResult<()> {
        let plan: PlanData =
            serde_json::from_str(plan_json).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.save_plan(&plan).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Load a plan by ID, returns JSON string or None.
    ///
    /// Args:
    ///     plan_id: The plan ID
    ///
    /// Returns:
    ///     JSON-encoded PlanData or None if not found
    fn load_plan(&self, py: Python<'_>, plan_id: &str) -> PyResult<Option<String>> {
        let client = Arc::clone(&self.client);
        let plan_id = plan_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.load_plan(&plan_id).await });
            let result = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            match result {
                Some(plan) => {
                    let json = serde_json::to_string(&plan)
                        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
                    Ok(Some(json))
                }
                None => Ok(None),
            }
        })
    }

    /// Delete a plan by ID.
    ///
    /// Args:
    ///     plan_id: The plan ID
    fn delete_plan(&self, py: Python<'_>, plan_id: &str) -> PyResult<()> {
        let client = Arc::clone(&self.client);
        let plan_id = plan_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.delete_plan(&plan_id).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// List plans, optionally filtered by goal_id, returns JSON array.
    ///
    /// Args:
    ///     goal_id: Optional goal ID to filter by
    ///
    /// Returns:
    ///     JSON array of PlanData
    #[pyo3(signature = (goal_id=None))]
    fn list_plans(&self, py: Python<'_>, goal_id: Option<&str>) -> PyResult<String> {
        let client = Arc::clone(&self.client);
        let goal_id = goal_id.map(|s| s.to_string());

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor
                .spawn_on_any(async move { client.list_plans(goal_id.as_deref()).await });
            let plans = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&plans).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    // =========================================================================
    // Goal System - Todos
    // =========================================================================

    /// Save a todo from JSON string (upsert).
    ///
    /// Args:
    ///     todo_json: JSON-encoded TodoData
    fn save_todo(&self, py: Python<'_>, todo_json: &str) -> PyResult<()> {
        let todo: TodoData =
            serde_json::from_str(todo_json).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.save_todo(&todo).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Load a todo by ID, returns JSON string or None.
    ///
    /// Args:
    ///     todo_id: The todo ID
    ///
    /// Returns:
    ///     JSON-encoded TodoData or None if not found
    fn load_todo(&self, py: Python<'_>, todo_id: &str) -> PyResult<Option<String>> {
        let client = Arc::clone(&self.client);
        let todo_id = todo_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.load_todo(&todo_id).await });
            let result = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            match result {
                Some(todo) => {
                    let json = serde_json::to_string(&todo)
                        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
                    Ok(Some(json))
                }
                None => Ok(None),
            }
        })
    }

    /// Delete a todo by ID.
    ///
    /// Args:
    ///     todo_id: The todo ID
    fn delete_todo(&self, py: Python<'_>, todo_id: &str) -> PyResult<()> {
        let client = Arc::clone(&self.client);
        let todo_id = todo_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.delete_todo(&todo_id).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// List todos, optionally filtered by plan_id, returns JSON array.
    ///
    /// Args:
    ///     plan_id: Optional plan ID to filter by
    ///
    /// Returns:
    ///     JSON array of TodoData
    #[pyo3(signature = (plan_id=None))]
    fn list_todos(&self, py: Python<'_>, plan_id: Option<&str>) -> PyResult<String> {
        let client = Arc::clone(&self.client);
        let plan_id = plan_id.map(|s| s.to_string());

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor
                .spawn_on_any(async move { client.list_todos(plan_id.as_deref()).await });
            let todos = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&todos).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    // =========================================================================
    // Goal System - Todo-Plan Links
    // =========================================================================

    /// Save a todo-plan link from JSON string.
    ///
    /// Args:
    ///     link_json: JSON-encoded TodoPlanLink
    fn save_todo_plan_link(&self, py: Python<'_>, link_json: &str) -> PyResult<()> {
        let link: TodoPlanLink =
            serde_json::from_str(link_json).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.save_todo_plan_link(&link).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Delete a todo-plan link.
    ///
    /// Args:
    ///     todo_id: The todo ID
    ///     plan_id: The plan ID
    fn delete_todo_plan_link(&self, py: Python<'_>, todo_id: &str, plan_id: &str) -> PyResult<()> {
        let client = Arc::clone(&self.client);
        let todo_id = todo_id.to_string();
        let plan_id = plan_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor
                .spawn_on_any(async move { client.delete_todo_plan_link(&todo_id, &plan_id).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Get all plans that a todo belongs to, returns JSON array.
    ///
    /// Args:
    ///     todo_id: The todo ID
    ///
    /// Returns:
    ///     JSON array of PlanData
    fn get_plans_for_todo(&self, py: Python<'_>, todo_id: &str) -> PyResult<String> {
        let client = Arc::clone(&self.client);
        let todo_id = todo_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task =
                executor.spawn_on_any(async move { client.get_plans_for_todo(&todo_id).await });
            let plans = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&plans).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Get all todos in a plan, returns JSON array.
    ///
    /// Args:
    ///     plan_id: The plan ID
    ///
    /// Returns:
    ///     JSON array of TodoData
    fn get_todos_for_plan(&self, py: Python<'_>, plan_id: &str) -> PyResult<String> {
        let client = Arc::clone(&self.client);
        let plan_id = plan_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task =
                executor.spawn_on_any(async move { client.get_todos_for_plan(&plan_id).await });
            let todos = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&todos).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    // =========================================================================
    // Goal System - Todo Dependencies
    // =========================================================================

    /// Save a todo dependency from JSON string.
    ///
    /// Args:
    ///     dep_json: JSON-encoded TodoDependency
    fn save_todo_dependency(&self, py: Python<'_>, dep_json: &str) -> PyResult<()> {
        let dep: TodoDependency =
            serde_json::from_str(dep_json).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.save_todo_dependency(&dep).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Delete a todo dependency.
    ///
    /// Args:
    ///     todo_id: The todo that has the dependency
    ///     depends_on_id: The todo it depends on
    fn delete_todo_dependency(
        &self,
        py: Python<'_>,
        todo_id: &str,
        depends_on_id: &str,
    ) -> PyResult<()> {
        let client = Arc::clone(&self.client);
        let todo_id = todo_id.to_string();
        let depends_on_id = depends_on_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move {
                client.delete_todo_dependency(&todo_id, &depends_on_id).await
            });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Get todos that the given todo depends on (prerequisites), returns JSON array.
    ///
    /// Args:
    ///     todo_id: The todo ID
    ///
    /// Returns:
    ///     JSON array of TodoData (the prerequisites)
    fn get_dependencies(&self, py: Python<'_>, todo_id: &str) -> PyResult<String> {
        let client = Arc::clone(&self.client);
        let todo_id = todo_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task =
                executor.spawn_on_any(async move { client.get_dependencies(&todo_id).await });
            let deps = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&deps).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Get todos that depend on the given todo (blockers), returns JSON array.
    ///
    /// Args:
    ///     todo_id: The todo ID
    ///
    /// Returns:
    ///     JSON array of TodoData (the dependents/blockers)
    fn get_dependents(&self, py: Python<'_>, todo_id: &str) -> PyResult<String> {
        let client = Arc::clone(&self.client);
        let todo_id = todo_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.get_dependents(&todo_id).await });
            let deps = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&deps).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    // =========================================================================
    // Goal System - Session Bindings
    // =========================================================================

    /// Save a session binding from JSON string (upsert).
    ///
    /// Args:
    ///     binding_json: JSON-encoded SessionBinding
    fn save_session_binding(&self, py: Python<'_>, binding_json: &str) -> PyResult<()> {
        let binding: SessionBinding =
            serde_json::from_str(binding_json).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task =
                executor.spawn_on_any(async move { client.save_session_binding(&binding).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Load a session binding by ID, returns JSON string or None.
    ///
    /// Args:
    ///     binding_id: The binding ID
    ///
    /// Returns:
    ///     JSON-encoded SessionBinding or None if not found
    fn load_session_binding(&self, py: Python<'_>, binding_id: &str) -> PyResult<Option<String>> {
        let client = Arc::clone(&self.client);
        let binding_id = binding_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor
                .spawn_on_any(async move { client.load_session_binding(&binding_id).await });
            let result = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            match result {
                Some(binding) => {
                    let json = serde_json::to_string(&binding)
                        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
                    Ok(Some(json))
                }
                None => Ok(None),
            }
        })
    }

    /// Delete a session binding by ID.
    ///
    /// Args:
    ///     binding_id: The binding ID
    fn delete_session_binding(&self, py: Python<'_>, binding_id: &str) -> PyResult<()> {
        let client = Arc::clone(&self.client);
        let binding_id = binding_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor
                .spawn_on_any(async move { client.delete_session_binding(&binding_id).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Get all bindings for a session, returns JSON array.
    ///
    /// Args:
    ///     session_id: The session ID
    ///
    /// Returns:
    ///     JSON array of SessionBinding
    fn get_bindings_for_session(&self, py: Python<'_>, session_id: &str) -> PyResult<String> {
        let client = Arc::clone(&self.client);
        let session_id = session_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor
                .spawn_on_any(async move { client.get_bindings_for_session(&session_id).await });
            let bindings = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&bindings).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Get all bindings for an entity (goal, plan, or todo), returns JSON array.
    ///
    /// Args:
    ///     entity_type: One of "goal", "plan", or "todo"
    ///     entity_id: The entity ID
    ///
    /// Returns:
    ///     JSON array of SessionBinding
    fn get_bindings_for_entity(
        &self,
        py: Python<'_>,
        entity_type: &str,
        entity_id: &str,
    ) -> PyResult<String> {
        let client = Arc::clone(&self.client);
        let entity_type = entity_type.to_string();
        let entity_id = entity_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move {
                client
                    .get_bindings_for_entity(&entity_type, &entity_id)
                    .await
            });
            let bindings = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&bindings).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// List all session bindings, returns JSON array.
    ///
    /// Returns:
    ///     JSON array of SessionBinding
    fn list_bindings(&self, py: Python<'_>) -> PyResult<String> {
        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.list_bindings().await });
            let bindings = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&bindings).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    // =========================================================================
    // User Preferences
    // =========================================================================

    /// Load user preferences, returns JSON string.
    ///
    /// Returns default preferences if none have been saved.
    ///
    /// Returns:
    ///     JSON-encoded UserPrefs
    fn load_user_prefs(&self, py: Python<'_>) -> PyResult<String> {
        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.load_user_prefs().await });
            let prefs = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&prefs).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Save user preferences from JSON string.
    ///
    /// Args:
    ///     prefs_json: JSON-encoded UserPrefs
    fn save_user_prefs(&self, py: Python<'_>, prefs_json: &str) -> PyResult<()> {
        let prefs: UserPrefs =
            serde_json::from_str(prefs_json).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.save_user_prefs(&prefs).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    // =========================================================================
    // Watcher Relationships
    // =========================================================================

    /// Save a watcher relationship (upsert).
    fn save_watcher(&self, py: Python<'_>, watcher_json: &str) -> PyResult<()> {
        let watcher: WatcherRelation =
            serde_json::from_str(watcher_json).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.save_watcher(&watcher).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Delete a watcher relationship.
    fn delete_watcher(&self, py: Python<'_>, id: &str) -> PyResult<()> {
        let client = Arc::clone(&self.client);
        let id = id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.delete_watcher(&id).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Get all watchers for a target session. Returns JSON array.
    fn get_watchers_for_target(&self, py: Python<'_>, target_session_id: &str) -> PyResult<String> {
        let client = Arc::clone(&self.client);
        let target_session_id = target_session_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move {
                client.get_watchers_for_target(&target_session_id).await
            });
            let watchers = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
            serde_json::to_string(&watchers).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Get all targets a watcher session is watching. Returns JSON array.
    fn get_targets_for_watcher(&self, py: Python<'_>, watcher_session_id: &str) -> PyResult<String> {
        let client = Arc::clone(&self.client);
        let watcher_session_id = watcher_session_id.to_string();

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move {
                client.get_targets_for_watcher(&watcher_session_id).await
            });
            let watchers = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
            serde_json::to_string(&watchers).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// List all watcher relationships. Returns JSON array.
    fn list_watchers(&self, py: Python<'_>) -> PyResult<String> {
        let client = Arc::clone(&self.client);

        py.detach(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.list_watchers().await });
            let watchers = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
            serde_json::to_string(&watchers).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }
}

// =============================================================================
// Process Supervisor bindings
// =============================================================================

/// Python-facing process supervisor
///
/// Manages long-running background processes with streaming output capture.
/// Uses core-executor for async operations.
#[pyclass]
struct Supervisor {
    inner: Arc<ProcessSupervisor>,
}

#[pymethods]
impl Supervisor {
    /// Create a new process supervisor
    #[new]
    fn new() -> Self {
        Self {
            inner: Arc::new(ProcessSupervisor::new()),
        }
    }

    /// Start a new supervised process.
    ///
    /// Args:
    ///     command: Shell command to execute
    ///     session_id: Session this process belongs to
    ///     working_dir: Optional working directory
    ///     name: Optional friendly name for the process
    ///     env_json: Optional JSON object of environment variables
    ///
    /// Returns:
    ///     Process ID (UUID string)
    #[pyo3(signature = (command, session_id, working_dir=None, name=None, env_json=None))]
    fn start(
        &self,
        py: Python<'_>,
        command: &str,
        session_id: &str,
        working_dir: Option<&str>,
        name: Option<&str>,
        env_json: Option<&str>,
    ) -> PyResult<String> {
        let env: Vec<(String, String)> = if let Some(json) = env_json {
            let map: std::collections::HashMap<String, String> =
                serde_json::from_str(json).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
            map.into_iter().collect()
        } else {
            vec![]
        };

        let request = StartRequest {
            command: command.to_string(),
            working_dir: working_dir.map(|s| s.to_string()),
            session_id: session_id.to_string(),
            name: name.map(|s| s.to_string()),
            env,
        };

        let supervisor = Arc::clone(&self.inner);

        py.detach(|| {
            let mut executor = get_supervisor_executor().lock().unwrap();
            let task = executor.spawn_on_any(async move { supervisor.start(request).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Get information about a process.
    ///
    /// Args:
    ///     process_id: The process ID
    ///
    /// Returns:
    ///     Awaitable that resolves to JSON string with process info
    fn get_process<'py>(
        &self,
        py: Python<'py>,
        process_id: &str,
    ) -> PyResult<Bound<'py, PyAny>> {
        let supervisor = Arc::clone(&self.inner);
        let process_id = process_id.to_string();

        pyo3_async_runtimes::smol::future_into_py(py, async move {
            let info = supervisor
                .get_process(&process_id)
                .await
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&info).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// List all processes, optionally filtered by session.
    ///
    /// Args:
    ///     session_id: Optional session ID to filter by
    ///
    /// Returns:
    ///     Awaitable that resolves to JSON array of process info objects
    #[pyo3(signature = (session_id=None))]
    fn list_processes<'py>(
        &self,
        py: Python<'py>,
        session_id: Option<&str>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let supervisor = Arc::clone(&self.inner);
        let session_id = session_id.map(|s| s.to_string());

        pyo3_async_runtimes::smol::future_into_py(py, async move {
            let infos = supervisor.list_processes(session_id.as_deref()).await;
            serde_json::to_string(&infos).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Get output from a process.
    ///
    /// Args:
    ///     process_id: The process ID
    ///     limit: Maximum number of log entries to return (default 50)
    ///
    /// Returns:
    ///     Awaitable that resolves to JSON array of log entries
    #[pyo3(signature = (process_id, limit=50))]
    fn get_output<'py>(
        &self,
        py: Python<'py>,
        process_id: &str,
        limit: usize,
    ) -> PyResult<Bound<'py, PyAny>> {
        let supervisor = Arc::clone(&self.inner);
        let process_id = process_id.to_string();

        pyo3_async_runtimes::smol::future_into_py(py, async move {
            let logs = supervisor
                .get_output(&process_id, limit)
                .await
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&logs).map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Stop a running process.
    ///
    /// Args:
    ///     process_id: The process ID to stop
    fn stop_process(&self, py: Python<'_>, process_id: &str) -> PyResult<()> {
        let supervisor = Arc::clone(&self.inner);
        let process_id = process_id.to_string();

        py.detach(|| {
            let mut executor = get_supervisor_executor().lock().unwrap();
            let task =
                executor.spawn_on_any(async move { supervisor.stop_process(&process_id).await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))
        })
    }

    /// Stop all processes for a session.
    ///
    /// Args:
    ///     session_id: The session ID
    ///
    /// Returns:
    ///     Number of processes stopped
    fn stop_session_processes(&self, py: Python<'_>, session_id: &str) -> PyResult<usize> {
        let supervisor = Arc::clone(&self.inner);
        let session_id = session_id.to_string();

        py.detach(|| {
            let mut executor = get_supervisor_executor().lock().unwrap();
            let task = executor
                .spawn_on_any(async move { supervisor.stop_session_processes(&session_id).await });
            let results = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?;
            Ok(results.into_iter().filter(|r| r.is_ok()).count())
        })
    }

    /// Get the count of running processes.
    fn running_count(&self, py: Python<'_>) -> PyResult<usize> {
        let supervisor = Arc::clone(&self.inner);

        py.detach(|| {
            let mut executor = get_supervisor_executor().lock().unwrap();
            let task = executor.spawn_on_any(async move { supervisor.running_count().await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))
        })
    }

    /// Get the total count of all processes (running and completed).
    fn total_count(&self, py: Python<'_>) -> PyResult<usize> {
        let supervisor = Arc::clone(&self.inner);

        py.detach(|| {
            let mut executor = get_supervisor_executor().lock().unwrap();
            let task = executor.spawn_on_any(async move { supervisor.total_count().await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))
        })
    }

    /// Shutdown the supervisor, stopping all running processes.
    ///
    /// Call this before exiting to avoid panics from orphaned background tasks.
    fn shutdown(&self, py: Python<'_>) -> PyResult<()> {
        let supervisor = Arc::clone(&self.inner);

        py.detach(|| {
            let mut executor = get_supervisor_executor().lock().unwrap();
            let task = executor.spawn_on_any(async move {
                // Get all running processes and stop them
                let processes = supervisor.list_processes(None).await;
                for process in processes {
                    if process.status.is_running() {
                        let _ = supervisor.stop_process(&process.id).await;
                    }
                }
            });
            // Block until all processes are stopped
            let _ = future::block_on(task);
            Ok(())
        })
    }

    /// Set a callback to receive all process output events.
    ///
    /// The callback is called with (process_id, source, content) for each line
    /// of output from any supervised process. This enables real-time streaming
    /// of process output to Python.
    ///
    /// Args:
    ///     callback: A Python callable that takes (process_id: str, source: str, content: str)
    ///               where source is "stdout", "stderr", or "system".
    ///               Pass None to clear the callback.
    ///
    /// Example:
    ///     def on_output(process_id: str, source: str, content: str):
    ///         print(f"[{process_id}] {source}: {content}")
    ///
    ///     supervisor.set_output_callback(on_output)
    #[pyo3(signature = (callback=None))]
    fn set_output_callback(&self, py: Python<'_>, callback: Option<Py<PyAny>>) -> PyResult<()> {
        let supervisor = Arc::clone(&self.inner);

        // If callback is provided, wrap it in an Arc for thread-safe sharing
        let rust_callback: Option<balloons_supervisor::OutputCallback> = callback.map(|cb| {
            // Create a Rust closure that acquires the GIL and calls the Python callback
            let callback_fn: balloons_supervisor::OutputCallback = Arc::new(
                move |process_id: &str, source: &str, content: &str| {
                    // Acquire GIL to call Python
                    // Note: try_attach returns None if we can't get the GIL (e.g., during shutdown)
                    if let Some(()) = Python::try_attach(|py| {
                        // Call the Python callback, ignoring errors
                        // (we're in a background thread and can't propagate errors)
                        let _ = cb.call1(py, (process_id, source, content));
                    }) {
                        // Successfully called
                    }
                },
            );
            callback_fn
        });

        // Set the callback on the supervisor
        py.detach(|| {
            let mut executor = get_supervisor_executor().lock().unwrap();
            let task = executor.spawn_on_any(async move {
                supervisor.set_output_callback(rust_callback).await;
            });
            let _ = future::block_on(task);
            Ok(())
        })
    }
}

// =============================================================================
// Recovery function
// =============================================================================

/// Recover all sessions from a source database to a target database.
///
/// This function copies sessions and their turns from the source database
/// to the target database. Sessions that already exist in the target are skipped.
///
/// Args:
///     source_path: Path to the source LMDB database directory
///     target_path: Path to the target LMDB database directory
///
/// Returns:
///     Dict with keys: recovered, skipped, failed, history_entries, goals_recovered,
///     plans_recovered, todos_recovered, links_recovered, dependencies_recovered,
///     bindings_recovered
#[pyfunction]
fn recover_database(py: Python<'_>, source_path: &str, target_path: &str) -> PyResult<Py<PyAny>> {
    let source = source_path.to_string();
    let target = target_path.to_string();

    py.detach(|| {
        let result = future::block_on(async {
            balloons_core::recover_database(&source, &target, None::<fn(&str)>).await
        })
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::attach(|py| {
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("recovered", result.recovered)?;
            dict.set_item("skipped", result.skipped)?;
            dict.set_item("failed", result.failed)?;
            dict.set_item("history_entries", result.history_entries)?;
            dict.set_item("goals_recovered", result.goals_recovered)?;
            dict.set_item("plans_recovered", result.plans_recovered)?;
            dict.set_item("todos_recovered", result.todos_recovered)?;
            dict.set_item("links_recovered", result.links_recovered)?;
            dict.set_item("dependencies_recovered", result.dependencies_recovered)?;
            dict.set_item("bindings_recovered", result.bindings_recovered)?;
            Ok(dict.into())
        })
    })
}

// =============================================================================
// Backup and Recovery functions
// =============================================================================

/// Create a timestamped backup of the LMDB database.
///
/// This creates a consistent snapshot by copying the LMDB files.
/// The backup is placed in a timestamped subdirectory.
///
/// Args:
///     source_path: Path to the LMDB database directory
///     backup_dir: Optional custom backup directory. If None, creates backup
///                 next to source as `{name}.backup.{timestamp}/`
///
/// Returns:
///     Dict with keys: backup_path, timestamp, size_bytes, files_copied
#[pyfunction]
#[pyo3(signature = (source_path, backup_dir=None))]
fn create_backup(
    py: Python<'_>,
    source_path: &str,
    backup_dir: Option<&str>,
) -> PyResult<Py<PyAny>> {
    let source = source_path.to_string();
    let backup = backup_dir.map(|s| std::path::PathBuf::from(s));

    py.detach(|| {
        let result = balloons_core::create_backup(&source, backup.as_deref())
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::attach(|py| {
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("backup_path", result.backup_path.to_string_lossy().to_string())?;
            dict.set_item("timestamp", result.timestamp)?;
            dict.set_item("size_bytes", result.size_bytes)?;
            dict.set_item("files_copied", result.files_copied)?;
            Ok(dict.into())
        })
    })
}

/// Export all data from an LMDB database to JSON files.
///
/// Creates:
/// - `manifest.json`: Export metadata and session history
/// - `sessions/`: Directory containing one JSON file per session
///
/// Args:
///     source_path: Path to the LMDB database directory
///     export_path: Path for the export directory (will be created)
///
/// Returns:
///     Dict with keys: export_path, timestamp, sessions_exported, turns_exported, size_bytes
#[pyfunction]
fn export_to_json(py: Python<'_>, source_path: &str, export_path: &str) -> PyResult<Py<PyAny>> {
    let source = source_path.to_string();
    let export = export_path.to_string();

    py.detach(|| {
        let result = future::block_on(async {
            balloons_core::export_to_json(&source, &export, None::<fn(&str)>).await
        })
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::attach(|py| {
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("export_path", result.export_path.to_string_lossy().to_string())?;
            dict.set_item("timestamp", result.timestamp)?;
            dict.set_item("sessions_exported", result.sessions_exported)?;
            dict.set_item("turns_exported", result.turns_exported)?;
            dict.set_item("size_bytes", result.size_bytes)?;
            Ok(dict.into())
        })
    })
}

/// Import data from a JSON export into an LMDB database.
///
/// Sessions that already exist in the target are skipped.
///
/// Args:
///     export_path: Path to the export directory
///     target_path: Path to the target LMDB database (will be created if needed)
///
/// Returns:
///     Dict with keys: target_path, sessions_imported, sessions_skipped, turns_imported
#[pyfunction]
fn import_from_json(py: Python<'_>, export_path: &str, target_path: &str) -> PyResult<Py<PyAny>> {
    let export = export_path.to_string();
    let target = target_path.to_string();

    py.detach(|| {
        let result = future::block_on(async {
            balloons_core::import_from_json(&export, &target, None::<fn(&str)>).await
        })
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::attach(|py| {
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("target_path", result.target_path.to_string_lossy().to_string())?;
            dict.set_item("sessions_imported", result.sessions_imported)?;
            dict.set_item("sessions_skipped", result.sessions_skipped)?;
            dict.set_item("turns_imported", result.turns_imported)?;
            Ok(dict.into())
        })
    })
}

/// Check the health of an LMDB database.
///
/// Verifies:
/// - Database can be opened
/// - All sessions are readable
/// - Turn references are consistent
///
/// Args:
///     path: Path to the LMDB database directory
///
/// Returns:
///     Dict with health report (can_open, is_healthy, session_count, turn_count, etc.)
#[pyfunction]
fn health_check(py: Python<'_>, path: &str) -> PyResult<Py<PyAny>> {
    let path = path.to_string();

    py.detach(|| {
        let result = future::block_on(async { balloons_core::health_check(&path).await })
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::attach(|py| {
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("path", result.path.to_string_lossy().to_string())?;
            dict.set_item("can_open", result.can_open)?;
            dict.set_item("is_healthy", result.is_healthy)?;
            dict.set_item("session_count", result.session_count)?;
            dict.set_item("turn_count", result.turn_count)?;
            dict.set_item("orphaned_turns", result.orphaned_turns)?;
            dict.set_item("missing_turns", result.missing_turns)?;
            dict.set_item("size_bytes", result.size_bytes)?;
            dict.set_item("issues", result.issues)?;
            Ok(dict.into())
        })
    })
}

/// List available backups for a database.
///
/// Looks for directories matching the backup naming pattern next to the source.
///
/// Args:
///     source_path: Path to the LMDB database directory
///
/// Returns:
///     List of dicts with backup info (backup_path, timestamp, size_bytes, files_copied)
#[pyfunction]
fn list_backups(py: Python<'_>, source_path: &str) -> PyResult<Py<PyAny>> {
    let source = source_path.to_string();

    py.detach(|| {
        let backups = balloons_core::list_backups(&source)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::attach(|py| {
            let list = pyo3::types::PyList::empty(py);
            for backup in backups {
                let dict = pyo3::types::PyDict::new(py);
                dict.set_item("backup_path", backup.backup_path.to_string_lossy().to_string())?;
                dict.set_item("timestamp", backup.timestamp)?;
                dict.set_item("size_bytes", backup.size_bytes)?;
                dict.set_item("files_copied", backup.files_copied)?;
                list.append(dict)?;
            }
            Ok(list.into())
        })
    })
}

/// Restore from a backup directory.
///
/// Copies the backup files to the target location.
///
/// Args:
///     backup_path: Path to the backup directory
///     target_path: Path to restore to (will be overwritten if exists)
///
/// Returns:
///     Dict with restore info (backup_path, timestamp, size_bytes, files_copied)
#[pyfunction]
fn restore_from_backup(
    py: Python<'_>,
    backup_path: &str,
    target_path: &str,
) -> PyResult<Py<PyAny>> {
    let backup = backup_path.to_string();
    let target = target_path.to_string();

    py.detach(|| {
        let result = balloons_core::restore_from_backup(&backup, &target)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::attach(|py| {
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("backup_path", result.backup_path.to_string_lossy().to_string())?;
            dict.set_item("timestamp", result.timestamp)?;
            dict.set_item("size_bytes", result.size_bytes)?;
            dict.set_item("files_copied", result.files_copied)?;
            Ok(dict.into())
        })
    })
}

// =============================================================================
// Tokenizer bindings (non-blocking token counting)
// =============================================================================

// Global executor for tokenizer operations - uses multiple threads for CPU-bound work
static TOKENIZER_EXECUTOR: OnceLock<Mutex<ThreadPoolExecutor>> = OnceLock::new();

fn get_tokenizer_executor() -> &'static Mutex<ThreadPoolExecutor> {
    // Use 4 threads for token counting - this is CPU-bound work that benefits from parallelism
    TOKENIZER_EXECUTOR.get_or_init(|| Mutex::new(ThreadPoolExecutor::new(4)))
}

/// Python-facing tokenizer for async token counting.
///
/// Uses tiktoken-rs cl100k_base encoding (same as Python tiktoken).
/// Token counting runs on a dedicated thread pool to avoid blocking the UI.
#[pyclass]
struct Tokenizer {
    // No state needed - we use tiktoken's singleton
}

#[pymethods]
impl Tokenizer {
    /// Create a new tokenizer instance.
    #[new]
    fn new() -> Self {
        Self {}
    }

    /// Count tokens in text (blocking, releases GIL).
    ///
    /// This runs on the tokenizer thread pool, releasing Python's GIL
    /// so other Python code can run while counting.
    ///
    /// Args:
    ///     text: The text to count tokens for
    ///
    /// Returns:
    ///     Token count
    fn count_tokens(&self, py: Python<'_>, text: &str) -> PyResult<usize> {
        let text = text.to_string();

        py.detach(|| {
            let mut executor = get_tokenizer_executor().lock().unwrap();
            let task = executor.spawn_on_any(async move {
                // Use tiktoken's singleton for efficiency
                let bpe = tiktoken_rs::cl100k_base_singleton();
                let lock = bpe.lock();
                lock.encode_with_special_tokens(&text).len()
            });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))
        })
    }

    /// Count tokens for multiple texts in batch (blocking, releases GIL).
    ///
    /// More efficient than calling count_tokens repeatedly as it batches
    /// the work across the thread pool.
    ///
    /// Args:
    ///     texts: List of texts to count tokens for
    ///
    /// Returns:
    ///     List of token counts (same order as input)
    fn count_tokens_batch(&self, py: Python<'_>, texts: Vec<String>) -> PyResult<Vec<usize>> {
        py.detach(|| {
            let mut executor = get_tokenizer_executor().lock().unwrap();

            // Spawn all tasks
            let mut tasks = Vec::with_capacity(texts.len());
            for text in texts {
                let task = executor.spawn_on_any(async move {
                    let bpe = tiktoken_rs::cl100k_base_singleton();
                    let lock = bpe.lock();
                    lock.encode_with_special_tokens(&text).len()
                });
                tasks.push(task);
            }

            // Collect results
            let mut results = Vec::with_capacity(tasks.len());
            for task in tasks {
                let count = future::block_on(task)
                    .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?;
                results.push(count);
            }
            Ok(results)
        })
    }
}

// =========================================================================
// Browser Automation
// =========================================================================

use balloons_browser::{Browser as RustBrowser, BrowserConfig as RustBrowserConfig};

/// Python-facing browser configuration.
#[pyclass(skip_from_py_object)]
#[derive(Clone)]
struct BrowserConfig {
    inner: RustBrowserConfig,
}

#[pymethods]
impl BrowserConfig {
    /// Create a new browser config with default settings.
    ///
    /// Args:
    ///     browser_type: "firefox" (default) or "chrome"
    ///     headless: Run in headless mode (default: False)
    ///     port: WebDriver port (default: 4444)
    ///     webdriver_url: Optional WebDriver URL to connect to
    #[new]
    #[pyo3(signature = (browser_type="firefox", headless=false, port=4444, webdriver_url=None))]
    fn new(
        browser_type: &str,
        headless: bool,
        port: u16,
        webdriver_url: Option<String>,
    ) -> Self {
        let mut config = RustBrowserConfig {
            browser_type: browser_type.to_string(),
            headless,
            port,
            webdriver_url: None,
        };
        if let Some(url) = webdriver_url {
            config.webdriver_url = Some(url);
        }
        Self { inner: config }
    }

    /// Create a Firefox config.
    #[staticmethod]
    fn firefox() -> Self {
        Self {
            inner: RustBrowserConfig::firefox(),
        }
    }

    /// Create a Chrome config.
    #[staticmethod]
    fn chrome() -> Self {
        Self {
            inner: RustBrowserConfig::chrome(),
        }
    }

    /// Get browser type.
    #[getter]
    fn browser_type(&self) -> &str {
        &self.inner.browser_type
    }

    /// Get headless setting.
    #[getter]
    fn headless(&self) -> bool {
        self.inner.headless
    }

    /// Get port.
    #[getter]
    fn port(&self) -> u16 {
        self.inner.port
    }
}

/// Python-facing browser for web automation.
///
/// Uses surfer-rs for browser automation via WebDriver protocol.
/// All operations are synchronous from Python's perspective but release
/// the GIL to allow other Python threads to run.
#[pyclass]
struct Browser {
    inner: Option<RustBrowser>,
}

#[pymethods]
impl Browser {
    /// Create a new browser instance with the given config.
    ///
    /// The browser is not connected yet - call connect() to start it.
    #[new]
    fn new(config: &BrowserConfig) -> Self {
        Self {
            inner: Some(RustBrowser::new(config.inner.clone())),
        }
    }

    /// Get the browser ID.
    #[getter]
    fn id(&self) -> PyResult<String> {
        self.inner
            .as_ref()
            .map(|b| b.id().to_string())
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))
    }

    /// Check if browser is connected.
    fn is_connected(&self) -> bool {
        self.inner.as_ref().map(|b| b.is_connected()).unwrap_or(false)
    }

    /// Connect to the browser (starts webdriver and browser).
    ///
    /// This must be called before any navigation or interaction methods.
    fn connect(&mut self, py: Python<'_>) -> PyResult<()> {
        let browser = self
            .inner
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            smol::block_on(async { browser.connect().await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Disconnect and close the browser.
    fn disconnect(&mut self, py: Python<'_>) -> PyResult<()> {
        let browser = self
            .inner
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            smol::block_on(async { browser.disconnect().await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Navigate to a URL.
    fn goto(&self, py: Python<'_>, url: &str) -> PyResult<()> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;
        let url = url.to_string();

        py.detach(|| {
            smol::block_on(async { browser.goto(&url).await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Go back in history.
    fn back(&self, py: Python<'_>) -> PyResult<()> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            smol::block_on(async { browser.back().await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Go forward in history.
    fn forward(&self, py: Python<'_>) -> PyResult<()> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            smol::block_on(async { browser.forward().await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Refresh the page.
    fn refresh(&self, py: Python<'_>) -> PyResult<()> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            smol::block_on(async { browser.refresh().await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Get the current URL.
    fn url(&self, py: Python<'_>) -> PyResult<String> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            smol::block_on(async { browser.url().await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Get the page title.
    fn title(&self, py: Python<'_>) -> PyResult<String> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            smol::block_on(async { browser.title().await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Get the page HTML.
    fn html(&self, py: Python<'_>) -> PyResult<String> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            smol::block_on(async { browser.html().await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Take a screenshot (returns PNG bytes).
    fn screenshot(&self, py: Python<'_>) -> PyResult<Vec<u8>> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            smol::block_on(async { browser.screenshot().await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Click an element by CSS selector.
    fn click(&self, py: Python<'_>, selector: &str) -> PyResult<()> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;
        let selector = selector.to_string();

        py.detach(|| {
            smol::block_on(async { browser.click(&selector).await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Fill an input by CSS selector (clears first, then types).
    fn fill(&self, py: Python<'_>, selector: &str, text: &str) -> PyResult<()> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;
        let selector = selector.to_string();
        let text = text.to_string();

        py.detach(|| {
            smol::block_on(async { browser.fill(&selector, &text).await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Type text into an element (without clearing first).
    fn type_text(&self, py: Python<'_>, selector: &str, text: &str) -> PyResult<()> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;
        let selector = selector.to_string();
        let text = text.to_string();

        py.detach(|| {
            smol::block_on(async { browser.type_text(&selector, &text).await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Submit the currently focused form.
    fn submit(&self, py: Python<'_>) -> PyResult<()> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            smol::block_on(async { browser.submit().await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Discover all input elements on the page.
    ///
    /// Returns a JSON array of input info objects.
    fn inputs(&self, py: Python<'_>) -> PyResult<String> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            let inputs = smol::block_on(async { browser.inputs().await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))?;
            serde_json::to_string(&inputs)
                .map_err(|e| PyRuntimeError::new_err(format!("JSON error: {}", e)))
        })
    }

    /// Discover all button elements on the page.
    ///
    /// Returns a JSON array of button info objects.
    fn buttons(&self, py: Python<'_>) -> PyResult<String> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            let buttons = smol::block_on(async { browser.buttons().await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))?;
            serde_json::to_string(&buttons)
                .map_err(|e| PyRuntimeError::new_err(format!("JSON error: {}", e)))
        })
    }

    /// Discover all link elements on the page.
    ///
    /// Args:
    ///     limit: Optional maximum number of links to return
    ///
    /// Returns a JSON array of link info objects.
    #[pyo3(signature = (limit=None))]
    fn links(&self, py: Python<'_>, limit: Option<usize>) -> PyResult<String> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            let links = smol::block_on(async { browser.links(limit).await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))?;
            serde_json::to_string(&links)
                .map_err(|e| PyRuntimeError::new_err(format!("JSON error: {}", e)))
        })
    }

    /// Click a button by index (from buttons() discovery).
    fn click_button(&self, py: Python<'_>, index: usize) -> PyResult<()> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;

        py.detach(|| {
            smol::block_on(async { browser.click_button(index).await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Set an input by index (from inputs() discovery).
    fn set_input(&self, py: Python<'_>, index: usize, value: &str) -> PyResult<()> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;
        let value = value.to_string();

        py.detach(|| {
            smol::block_on(async { browser.set_input(index, &value).await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))
        })
    }

    /// Execute JavaScript and return the result as JSON string.
    fn execute_js(&self, py: Python<'_>, script: &str) -> PyResult<String> {
        let browser = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Browser was closed"))?;
        let script = script.to_string();

        py.detach(|| {
            let result = smol::block_on(async { browser.execute_js(&script).await })
                .map_err(|e| PyRuntimeError::new_err(format!("Browser error: {}", e)))?;
            serde_json::to_string(&result)
                .map_err(|e| PyRuntimeError::new_err(format!("JSON error: {}", e)))
        })
    }
}

// =========================================================================
// Git/File Browser
// =========================================================================

/// List a directory with git status information.
///
/// Returns a DirectoryListing with file entries enriched with git status.
/// Hidden files (starting with '.') are excluded.
///
/// Args:
///     path: Path to the directory to list
///
/// Returns:
///     JSON string containing DirectoryListing with entries and git info
#[pyfunction]
fn list_directory(py: Python<'_>, path: &str) -> PyResult<String> {
    let path = path.to_string();

    py.detach(|| {
        let listing = balloons_git::list_directory(&path)
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))?;

        serde_json::to_string(&listing)
            .map_err(|e| PyRuntimeError::new_err(format!("JSON error: {}", e)))
    })
}

/// Stage files for git commit.
///
/// Args:
///     repo_path: Path to the git repository (or a path within it)
///     paths: JSON array of file paths (relative to repo root) to stage
///
/// Returns:
///     Number of files staged
#[pyfunction]
fn git_stage_files(py: Python<'_>, repo_path: &str, paths_json: &str) -> PyResult<usize> {
    let paths: Vec<String> = serde_json::from_str(paths_json)
        .map_err(|e| PyRuntimeError::new_err(format!("JSON error: {}", e)))?;

    py.detach(|| {
        let repo = balloons_git::GitRepo::open(repo_path)
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))?;

        let path_refs: Vec<&str> = paths.iter().map(|s| s.as_str()).collect();
        repo.stage_files(&path_refs)
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))
    })
}

/// Stage all changes for git commit.
///
/// Args:
///     repo_path: Path to the git repository (or a path within it)
///
/// Returns:
///     Number of index entries after staging
#[pyfunction]
fn git_stage_all(py: Python<'_>, repo_path: &str) -> PyResult<usize> {
    py.detach(|| {
        let repo = balloons_git::GitRepo::open(repo_path)
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))?;

        repo.stage_all()
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))
    })
}

/// Unstage files (remove from index).
///
/// Args:
///     repo_path: Path to the git repository (or a path within it)
///     paths: JSON array of file paths (relative to repo root) to unstage
///
/// Returns:
///     Number of files unstaged
#[pyfunction]
fn git_unstage_files(py: Python<'_>, repo_path: &str, paths_json: &str) -> PyResult<usize> {
    let paths: Vec<String> = serde_json::from_str(paths_json)
        .map_err(|e| PyRuntimeError::new_err(format!("JSON error: {}", e)))?;

    py.detach(|| {
        let repo = balloons_git::GitRepo::open(repo_path)
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))?;

        let path_refs: Vec<&str> = paths.iter().map(|s| s.as_str()).collect();
        repo.unstage_files(&path_refs)
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))
    })
}

/// Create a git commit with staged changes.
///
/// Args:
///     repo_path: Path to the git repository (or a path within it)
///     message: The commit message
///
/// Returns:
///     JSON object with short_hash and full_hash
#[pyfunction]
fn git_commit(py: Python<'_>, repo_path: &str, message: &str) -> PyResult<String> {
    let message = message.to_string();

    py.detach(|| {
        let repo = balloons_git::GitRepo::open(repo_path)
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))?;

        let result = repo.commit(&message)
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))?;

        // Return as JSON
        serde_json::to_string(&serde_json::json!({
            "short_hash": result.short_hash,
            "full_hash": result.full_hash,
        }))
        .map_err(|e| PyRuntimeError::new_err(format!("JSON error: {}", e)))
    })
}

/// Check if there are staged changes.
///
/// Args:
///     repo_path: Path to the git repository (or a path within it)
///
/// Returns:
///     True if there are staged changes ready to commit
#[pyfunction]
fn git_has_staged_changes(py: Python<'_>, repo_path: &str) -> PyResult<bool> {
    py.detach(|| {
        let repo = balloons_git::GitRepo::open(repo_path)
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))?;

        repo.has_staged_changes()
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))
    })
}

/// Get list of staged file paths.
///
/// Args:
///     repo_path: Path to the git repository (or a path within it)
///
/// Returns:
///     JSON array of staged file paths
#[pyfunction]
fn git_staged_files(py: Python<'_>, repo_path: &str) -> PyResult<String> {
    py.detach(|| {
        let repo = balloons_git::GitRepo::open(repo_path)
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))?;

        let files = repo.staged_files()
            .map_err(|e| PyRuntimeError::new_err(format!("Git error: {}", e)))?;

        serde_json::to_string(&files)
            .map_err(|e| PyRuntimeError::new_err(format!("JSON error: {}", e)))
    })
}

/// Python module definition
#[pymodule]
fn balloons_storage(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Storage>()?;
    m.add_class::<Supervisor>()?;
    m.add_class::<Tokenizer>()?;
    m.add_class::<BrowserConfig>()?;
    m.add_class::<Browser>()?;
    m.add_function(wrap_pyfunction!(recover_database, m)?)?;
    // Backup and recovery functions
    m.add_function(wrap_pyfunction!(create_backup, m)?)?;
    m.add_function(wrap_pyfunction!(export_to_json, m)?)?;
    m.add_function(wrap_pyfunction!(import_from_json, m)?)?;
    m.add_function(wrap_pyfunction!(health_check, m)?)?;
    m.add_function(wrap_pyfunction!(list_backups, m)?)?;
    m.add_function(wrap_pyfunction!(restore_from_backup, m)?)?;
    // File browser / git functions
    m.add_function(wrap_pyfunction!(list_directory, m)?)?;
    m.add_function(wrap_pyfunction!(git_stage_files, m)?)?;
    m.add_function(wrap_pyfunction!(git_stage_all, m)?)?;
    m.add_function(wrap_pyfunction!(git_unstage_files, m)?)?;
    m.add_function(wrap_pyfunction!(git_commit, m)?)?;
    m.add_function(wrap_pyfunction!(git_has_staged_changes, m)?)?;
    m.add_function(wrap_pyfunction!(git_staged_files, m)?)?;
    Ok(())
}
