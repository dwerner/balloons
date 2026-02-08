//! PyO3 bindings for balloons-core storage.
//!
//! Uses core-executor's ThreadPoolExecutor for CPU-affine async execution.

use core_executor::ThreadPoolExecutor;
use futures_lite::future;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use std::sync::{Arc, Mutex};

use balloons_core::{RedbEngine, SessionData, StorageClient};

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
        let engine = RedbEngine::open(path).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
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
}

/// Python module definition
#[pymodule]
fn balloons_storage(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Storage>()?;
    Ok(())
}
