//! PyO3 bindings for balloons-core storage and balloons-supervisor.
//!
//! Uses core-executor's ThreadPoolExecutor for CPU-affine async execution.

use core_executor::ThreadPoolExecutor;
use futures_lite::future;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use std::sync::{Arc, Mutex, OnceLock};

use balloons_core::{
    GoalData, LmdbEngine, PlanData, SessionBinding, SessionData, StorageClient, TodoData,
    TodoDependency, TodoPlanLink,
};
use balloons_supervisor::{ProcessSupervisor, StartRequest};

// Global executor for supervisor operations
static SUPERVISOR_EXECUTOR: OnceLock<Mutex<ThreadPoolExecutor>> = OnceLock::new();

fn get_supervisor_executor() -> &'static Mutex<ThreadPoolExecutor> {
    SUPERVISOR_EXECUTOR.get_or_init(|| Mutex::new(ThreadPoolExecutor::new(1)))
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
        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.load_turns(&session_id).await });
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
            let mut executor = self.executor.lock().unwrap();
            let task = executor.spawn_on_any(async move { client.list_bindings().await });
            let bindings = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

            serde_json::to_string(&bindings).map_err(|e| PyRuntimeError::new_err(e.to_string()))
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

        py.allow_threads(|| {
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
    ///     JSON string with process info
    fn get_process(&self, py: Python<'_>, process_id: &str) -> PyResult<String> {
        let supervisor = Arc::clone(&self.inner);
        let process_id = process_id.to_string();

        py.allow_threads(|| {
            let mut executor = get_supervisor_executor().lock().unwrap();
            let task =
                executor.spawn_on_any(async move { supervisor.get_process(&process_id).await });
            let info = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
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
    ///     JSON array of process info objects
    #[pyo3(signature = (session_id=None))]
    fn list_processes(&self, py: Python<'_>, session_id: Option<&str>) -> PyResult<String> {
        let supervisor = Arc::clone(&self.inner);
        let session_id = session_id.map(|s| s.to_string());

        py.allow_threads(|| {
            let mut executor = get_supervisor_executor().lock().unwrap();
            let task = executor.spawn_on_any(async move {
                supervisor.list_processes(session_id.as_deref()).await
            });
            let infos = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?;

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
    ///     JSON array of log entries
    #[pyo3(signature = (process_id, limit=50))]
    fn get_output(&self, py: Python<'_>, process_id: &str, limit: usize) -> PyResult<String> {
        let supervisor = Arc::clone(&self.inner);
        let process_id = process_id.to_string();

        py.allow_threads(|| {
            let mut executor = get_supervisor_executor().lock().unwrap();
            let task = executor
                .spawn_on_any(async move { supervisor.get_output(&process_id, limit).await });
            let logs = future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
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

        py.allow_threads(|| {
            let mut executor = get_supervisor_executor().lock().unwrap();
            let task = executor.spawn_on_any(async move { supervisor.running_count().await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))
        })
    }

    /// Get the total count of all processes (running and completed).
    fn total_count(&self, py: Python<'_>) -> PyResult<usize> {
        let supervisor = Arc::clone(&self.inner);

        py.allow_threads(|| {
            let mut executor = get_supervisor_executor().lock().unwrap();
            let task = executor.spawn_on_any(async move { supervisor.total_count().await });
            future::block_on(task)
                .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))
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
///     Dict with keys: recovered, skipped, failed, history_entries
#[pyfunction]
fn recover_database(py: Python<'_>, source_path: &str, target_path: &str) -> PyResult<PyObject> {
    let source = source_path.to_string();
    let target = target_path.to_string();

    py.allow_threads(|| {
        let result = future::block_on(async {
            balloons_core::recover_database(&source, &target, None::<fn(&str)>).await
        })
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("recovered", result.recovered)?;
            dict.set_item("skipped", result.skipped)?;
            dict.set_item("failed", result.failed)?;
            dict.set_item("history_entries", result.history_entries)?;
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
) -> PyResult<PyObject> {
    let source = source_path.to_string();
    let backup = backup_dir.map(|s| std::path::PathBuf::from(s));

    py.allow_threads(|| {
        let result = balloons_core::create_backup(&source, backup.as_deref())
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
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
fn export_to_json(py: Python<'_>, source_path: &str, export_path: &str) -> PyResult<PyObject> {
    let source = source_path.to_string();
    let export = export_path.to_string();

    py.allow_threads(|| {
        let result = future::block_on(async {
            balloons_core::export_to_json(&source, &export, None::<fn(&str)>).await
        })
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
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
fn import_from_json(py: Python<'_>, export_path: &str, target_path: &str) -> PyResult<PyObject> {
    let export = export_path.to_string();
    let target = target_path.to_string();

    py.allow_threads(|| {
        let result = future::block_on(async {
            balloons_core::import_from_json(&export, &target, None::<fn(&str)>).await
        })
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
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
fn health_check(py: Python<'_>, path: &str) -> PyResult<PyObject> {
    let path = path.to_string();

    py.allow_threads(|| {
        let result = future::block_on(async { balloons_core::health_check(&path).await })
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
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
fn list_backups(py: Python<'_>, source_path: &str) -> PyResult<PyObject> {
    let source = source_path.to_string();

    py.allow_threads(|| {
        let backups = balloons_core::list_backups(&source)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
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
) -> PyResult<PyObject> {
    let backup = backup_path.to_string();
    let target = target_path.to_string();

    py.allow_threads(|| {
        let result = balloons_core::restore_from_backup(&backup, &target)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Python::with_gil(|py| {
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("backup_path", result.backup_path.to_string_lossy().to_string())?;
            dict.set_item("timestamp", result.timestamp)?;
            dict.set_item("size_bytes", result.size_bytes)?;
            dict.set_item("files_copied", result.files_copied)?;
            Ok(dict.into())
        })
    })
}

/// Python module definition
#[pymodule]
fn balloons_storage(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Storage>()?;
    m.add_class::<Supervisor>()?;
    m.add_function(wrap_pyfunction!(recover_database, m)?)?;
    // Backup and recovery functions
    m.add_function(wrap_pyfunction!(create_backup, m)?)?;
    m.add_function(wrap_pyfunction!(export_to_json, m)?)?;
    m.add_function(wrap_pyfunction!(import_from_json, m)?)?;
    m.add_function(wrap_pyfunction!(health_check, m)?)?;
    m.add_function(wrap_pyfunction!(list_backups, m)?)?;
    m.add_function(wrap_pyfunction!(restore_from_backup, m)?)?;
    Ok(())
}
