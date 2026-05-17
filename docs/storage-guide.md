# Extending Rust Storage with New Entity Types

This guide documents the process for adding new entity types to the Balloons Rust storage layer. It was distilled from the Goal System refactor that added Goals, Plans, Todos, and SessionBindings to the storage layer.

## Architecture Overview

```
Python Domain Layer                    Rust Storage Layer
┌──────────────────┐                   ┌──────────────────────────────┐
│ storage_schema.py│                   │ balloons-core/               │
│ @rust_schema     │─── codegen ──────>│   generated/schema.rs        │
│ dataclasses      │                   │                              │
└──────────────────┘                   │ StorageEngine trait (traits.rs)
                                       │   └── LmdbEngine (lmdb_engine.rs)
┌──────────────────┐                   │                              │
│ async_storage.py │<──── PyO3 ───────>│ balloons-py/lib.rs          │
│ (Python async)   │      bindings     │   (sync PyO3 bindings)       │
└──────────────────┘                   └──────────────────────────────┘
```

**Data flow:**
1. Python domain types are defined in `storage_schema.py`
2. Codegen produces Rust structs in `generated/schema.rs`
3. `StorageEngine` trait defines the storage interface
4. `LmdbEngine` implements storage using LMDB
5. PyO3 bindings expose Rust storage to Python
6. `AsyncStorage` wraps synchronous PyO3 calls for async Python

---

## Step-by-Step Process

### Step 1: Define Python Dataclass with `@rust_schema`

Add your entity type to `storage_schema.py`:

```python
from codegen import rust_schema

@rust_schema
@dataclass
class MyEntityData:
    """Description of what this entity represents.

    Include notes about relationships, constraints, etc.
    """
    id: str  # UUID
    name: str
    status: str  # "active", "completed", "abandoned"
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601

    # Optional fields MUST have defaults
    description: Optional[str] = None
    parent_id: Optional[str] = None

    # Lists should use default_factory
    tags: list[str] = field(default_factory=list)
```

**Guidelines:**
- Use `str` for UUIDs (not uuid.UUID)
- Use ISO 8601 strings for timestamps
- All `Optional[T]` and `list[T]` fields get `#[serde(default)]` in Rust
- Enum-like fields use `str` with allowed values in docstring
- Relationships use IDs, not nested objects

### Step 2: Run Codegen

```bash
python -m codegen.generate_rust
```

This generates/updates:
- `balloons-rs/crates/balloons-core/src/generated/schema.rs`
- `balloons-rs/crates/balloons-core/src/generated/mod.rs`

The generated Rust looks like:

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MyEntityData {
    pub id: String,
    pub name: String,
    pub status: String,
    pub created_at: String,
    pub updated_at: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub parent_id: Option<String>,
    #[serde(default)]
    pub tags: Vec<String>,
}
```

### Step 3: Design Table Structure

Plan your LMDB table layout in `lmdb_engine.rs`. Consider:

1. **Primary table**: `entity_name: id → JSON data`
2. **Index tables**: For efficient lookups by non-primary keys
3. **Relationship tables**: For many-to-many relationships

**Example from Goal System:**

```
Primary tables:
├── goals: goal_id → GoalData
├── plans: plan_id → PlanData
└── todos: todo_id → TodoData

Index tables (for 1:N relationships):
├── plans_by_goal: goal_id → [plan_id, ...]
├── todos_by_plan: plan_id → [todo_id, ...]
└── plans_by_todo: todo_id → [plan_id, ...]  (reverse index)

Dependency tracking:
├── todo_dependencies: todo_id → [TodoDependency, ...]
└── todo_dependents: todo_id → [todo_id, ...]  (reverse index)
```

**Key design decisions:**

| Pattern | When to Use | Example |
|---------|-------------|---------|
| Primary table | Every entity | `goals: id → GoalData` |
| Forward index | Query children by parent | `plans_by_goal: goal_id → [plan_ids]` |
| Reverse index | Query parents by child | `plans_by_todo: todo_id → [plan_ids]` |
| Composite key | Multi-key lookups | `bindings_by_entity: "type:id" → [binding_ids]` |

### Step 4: Add Trait Methods to `StorageEngine`

Add your CRUD operations to `storage/traits.rs`:

```rust
// In traits.rs, add to the StorageEngine trait:

/// Save an entity (upsert).
async fn save_my_entity(&self, entity: &MyEntityData) -> Result<()>;

/// Load an entity by ID.
async fn load_my_entity(&self, id: &str) -> Result<Option<MyEntityData>>;

/// Delete an entity by ID.
///
/// Document cascade behavior here (does it delete related entities?).
async fn delete_my_entity(&self, id: &str) -> Result<()>;

/// List all entities, optionally filtered.
async fn list_my_entities(&self, filter_id: Option<&str>) -> Result<Vec<MyEntityData>>;
```

Add error variants if needed:

```rust
#[derive(Debug, Error)]
pub enum Error {
    // ... existing variants ...

    #[error("MyEntity not found: {0}")]
    MyEntityNotFound(String),
}
```

### Step 5: Implement in `LmdbEngine`

#### 5.1 Add Database Fields

```rust
pub struct LmdbEngine {
    // ... existing fields ...

    // Primary table
    my_entities: Database<Str, Bytes>,

    // Index table (if needed)
    my_entities_by_parent: Database<Str, Bytes>,
}
```

#### 5.2 Update `max_dbs` Count

```rust
// In open_with_map_size():
let env = unsafe {
    EnvOpenOptions::new()
        .map_size(map_size)
        .max_dbs(N)  // Increment this!
        .open(path)
```

#### 5.3 Create Database in `open()`

```rust
// In open_with_map_size(), inside the write transaction:
let my_entities = env
    .create_database(&mut wtxn, Some("my_entities"))
    .map_err(|e| Error::Database(e.to_string()))?;

let my_entities_by_parent = env
    .create_database(&mut wtxn, Some("my_entities_by_parent"))
    .map_err(|e| Error::Database(e.to_string()))?;
```

#### 5.4 Add to Struct Constructor

```rust
Ok(Self {
    // ... existing fields ...
    my_entities,
    my_entities_by_parent,
})
```

#### 5.5 Implement Trait Methods

Basic CRUD pattern:

```rust
async fn save_my_entity(&self, entity: &MyEntityData) -> Result<()> {
    let bytes = serde_json::to_vec(entity)
        .map_err(|e| Error::Serialization(e.to_string()))?;

    let mut wtxn = self.env.write_txn()
        .map_err(|e| Error::Database(e.to_string()))?;

    // If entity has a parent relationship, update the index
    if let Some(ref parent_id) = entity.parent_id {
        self.update_parent_index(&mut wtxn, parent_id, &entity.id)?;
    }

    self.my_entities
        .put(&mut wtxn, &entity.id, &bytes)
        .map_err(|e| Error::Database(e.to_string()))?;

    wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;
    Ok(())
}

async fn load_my_entity(&self, id: &str) -> Result<Option<MyEntityData>> {
    let rtxn = self.env.read_txn()
        .map_err(|e| Error::Database(e.to_string()))?;

    match self.my_entities.get(&rtxn, id)
        .map_err(|e| Error::Database(e.to_string()))?
    {
        Some(bytes) => {
            let data: MyEntityData = serde_json::from_slice(bytes)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            Ok(Some(data))
        }
        None => Ok(None),
    }
}

async fn delete_my_entity(&self, id: &str) -> Result<()> {
    let mut wtxn = self.env.write_txn()
        .map_err(|e| Error::Database(e.to_string()))?;

    // Clean up indexes BEFORE deleting the entity
    // (need to read entity to find related keys)
    if let Some(bytes) = self.my_entities.get(&wtxn, id)
        .map_err(|e| Error::Database(e.to_string()))?
    {
        let entity: MyEntityData = serde_json::from_slice(bytes)
            .map_err(|e| Error::Serialization(e.to_string()))?;

        // Remove from parent's index
        if let Some(ref parent_id) = entity.parent_id {
            self.remove_from_parent_index(&mut wtxn, parent_id, id)?;
        }
    }

    self.my_entities
        .delete(&mut wtxn, id)
        .map_err(|e| Error::Database(e.to_string()))?;

    wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;
    Ok(())
}

async fn list_my_entities(&self, parent_id: Option<&str>) -> Result<Vec<MyEntityData>> {
    let rtxn = self.env.read_txn()
        .map_err(|e| Error::Database(e.to_string()))?;

    match parent_id {
        Some(pid) => {
            // Use index for filtered query
            let entity_ids: Vec<String> = match self.my_entities_by_parent
                .get(&rtxn, pid)
                .map_err(|e| Error::Database(e.to_string()))?
            {
                Some(bytes) => serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?,
                None => return Ok(vec![]),
            };

            let mut entities = Vec::with_capacity(entity_ids.len());
            for entity_id in entity_ids {
                if let Some(bytes) = self.my_entities.get(&rtxn, &entity_id)
                    .map_err(|e| Error::Database(e.to_string()))?
                {
                    let entity: MyEntityData = serde_json::from_slice(bytes)
                        .map_err(|e| Error::Serialization(e.to_string()))?;
                    entities.push(entity);
                }
            }
            Ok(entities)
        }
        None => {
            // Full table scan
            let mut entities = Vec::new();
            for entry in self.my_entities.iter(&rtxn)
                .map_err(|e| Error::Database(e.to_string()))?
            {
                let (_key, value) = entry
                    .map_err(|e| Error::Database(e.to_string()))?;
                let entity: MyEntityData = serde_json::from_slice(value)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                entities.push(entity);
            }
            Ok(entities)
        }
    }
}
```

#### 5.6 Index Maintenance Helpers

```rust
fn update_parent_index(
    &self,
    wtxn: &mut heed::RwTxn,
    parent_id: &str,
    entity_id: &str,
) -> Result<()> {
    let mut ids: Vec<String> = match self.my_entities_by_parent
        .get(wtxn, parent_id)
        .map_err(|e| Error::Database(e.to_string()))?
    {
        Some(bytes) => serde_json::from_slice(bytes)
            .map_err(|e| Error::Serialization(e.to_string()))?,
        None => vec![],
    };

    if !ids.contains(&entity_id.to_string()) {
        ids.push(entity_id.to_string());
        let bytes = serde_json::to_vec(&ids)
            .map_err(|e| Error::Serialization(e.to_string()))?;
        self.my_entities_by_parent
            .put(wtxn, parent_id, &bytes)
            .map_err(|e| Error::Database(e.to_string()))?;
    }
    Ok(())
}

fn remove_from_parent_index(
    &self,
    wtxn: &mut heed::RwTxn,
    parent_id: &str,
    entity_id: &str,
) -> Result<()> {
    if let Some(bytes) = self.my_entities_by_parent
        .get(wtxn, parent_id)
        .map_err(|e| Error::Database(e.to_string()))?
    {
        let mut ids: Vec<String> = serde_json::from_slice(bytes)
            .map_err(|e| Error::Serialization(e.to_string()))?;
        ids.retain(|id| id != entity_id);

        if ids.is_empty() {
            self.my_entities_by_parent
                .delete(wtxn, parent_id)
                .map_err(|e| Error::Database(e.to_string()))?;
        } else {
            let new_bytes = serde_json::to_vec(&ids)
                .map_err(|e| Error::Serialization(e.to_string()))?;
            self.my_entities_by_parent
                .put(wtxn, parent_id, &new_bytes)
                .map_err(|e| Error::Database(e.to_string()))?;
        }
    }
    Ok(())
}
```

### Step 6: Add PyO3 Bindings

In `balloons-py/src/lib.rs`:

```rust
/// Save an entity from JSON string (upsert).
fn save_my_entity(&self, py: Python<'_>, json_data: &str) -> PyResult<()> {
    let entity: MyEntityData = serde_json::from_str(json_data)
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

    let client = Arc::clone(&self.client);

    py.allow_threads(|| {
        let mut executor = self.executor.lock().unwrap();
        let task = executor.spawn_on_any(async move {
            client.save_my_entity(&entity).await
        });
        future::block_on(task)
            .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))
    })
}

/// Load an entity by ID, returns JSON string or None.
fn load_my_entity(&self, py: Python<'_>, id: &str) -> PyResult<Option<String>> {
    let client = Arc::clone(&self.client);
    let id = id.to_string();

    py.allow_threads(|| {
        let mut executor = self.executor.lock().unwrap();
        let task = executor.spawn_on_any(async move {
            client.load_my_entity(&id).await
        });
        let result = future::block_on(task)
            .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        match result {
            Some(entity) => {
                let json = serde_json::to_string(&entity)
                    .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
                Ok(Some(json))
            }
            None => Ok(None),
        }
    })
}

/// Delete an entity by ID.
fn delete_my_entity(&self, py: Python<'_>, id: &str) -> PyResult<()> {
    let client = Arc::clone(&self.client);
    let id = id.to_string();

    py.allow_threads(|| {
        let mut executor = self.executor.lock().unwrap();
        let task = executor.spawn_on_any(async move {
            client.delete_my_entity(&id).await
        });
        future::block_on(task)
            .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))
    })
}

/// List entities with optional filter, returns JSON array.
#[pyo3(signature = (parent_id=None))]
fn list_my_entities(&self, py: Python<'_>, parent_id: Option<&str>) -> PyResult<String> {
    let client = Arc::clone(&self.client);
    let parent_id = parent_id.map(|s| s.to_string());

    py.allow_threads(|| {
        let mut executor = self.executor.lock().unwrap();
        let task = executor.spawn_on_any(async move {
            client.list_my_entities(parent_id.as_deref()).await
        });
        let entities = future::block_on(task)
            .map_err(|e| PyRuntimeError::new_err(format!("executor error: {:?}", e)))?
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        serde_json::to_string(&entities)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))
    })
}
```

### Step 7: Create Async Python Wrapper

In `core/async_storage.py`:

```python
# Add to AsyncStorage class:

async def save_my_entity(self, entity: MyEntityData) -> None:
    """Save an entity to storage."""
    entity_json = json.dumps(asdict(entity))
    await self._run_sync(self._storage.save_my_entity, entity_json)

async def load_my_entity(self, entity_id: str) -> Optional[MyEntityData]:
    """Load an entity from storage."""
    json_data = await self._run_sync(self._storage.load_my_entity, entity_id)
    if json_data is None:
        return None
    data = json.loads(json_data)
    return MyEntityData(**data)

async def delete_my_entity(self, entity_id: str) -> None:
    """Delete an entity from storage."""
    await self._run_sync(self._storage.delete_my_entity, entity_id)

async def list_my_entities(self, parent_id: str | None = None) -> list[MyEntityData]:
    """List entities, optionally filtered by parent."""
    json_data = await self._run_sync(self._storage.list_my_entities, parent_id)
    entities_data = json.loads(json_data)
    return [MyEntityData(**data) for data in entities_data]
```

### Step 8: Write Tests

#### Rust Tests

Add tests in `lmdb_engine.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TestDir;

    fn make_test_entity(id: &str) -> MyEntityData {
        MyEntityData {
            id: id.to_string(),
            name: format!("Test {}", id),
            status: "active".to_string(),
            created_at: "2026-01-01T00:00:00Z".to_string(),
            updated_at: "2026-01-01T00:00:00Z".to_string(),
            description: None,
            parent_id: None,
            tags: vec![],
        }
    }

    #[tokio::test]
    async fn test_save_and_load_my_entity() {
        let dir = TestDir::new("test_my_entity_save_load");
        let engine = LmdbEngine::open(&dir.path).unwrap();

        let entity = make_test_entity("test-1");
        engine.save_my_entity(&entity).await.unwrap();

        let loaded = engine.load_my_entity("test-1").await.unwrap();
        assert!(loaded.is_some());
        let loaded = loaded.unwrap();
        assert_eq!(loaded.id, "test-1");
        assert_eq!(loaded.name, "Test test-1");
    }

    #[tokio::test]
    async fn test_delete_my_entity() {
        let dir = TestDir::new("test_my_entity_delete");
        let engine = LmdbEngine::open(&dir.path).unwrap();

        let entity = make_test_entity("to-delete");
        engine.save_my_entity(&entity).await.unwrap();

        engine.delete_my_entity("to-delete").await.unwrap();

        let loaded = engine.load_my_entity("to-delete").await.unwrap();
        assert!(loaded.is_none());
    }

    #[tokio::test]
    async fn test_list_my_entities() {
        let dir = TestDir::new("test_my_entity_list");
        let engine = LmdbEngine::open(&dir.path).unwrap();

        engine.save_my_entity(&make_test_entity("e1")).await.unwrap();
        engine.save_my_entity(&make_test_entity("e2")).await.unwrap();

        let all = engine.list_my_entities(None).await.unwrap();
        assert_eq!(all.len(), 2);
    }

    #[tokio::test]
    async fn test_index_cleanup_on_delete() {
        let dir = TestDir::new("test_my_entity_index_cleanup");
        let engine = LmdbEngine::open(&dir.path).unwrap();

        let mut entity = make_test_entity("child");
        entity.parent_id = Some("parent-1".to_string());
        engine.save_my_entity(&entity).await.unwrap();

        // Verify it's in the parent index
        let children = engine.list_my_entities(Some("parent-1")).await.unwrap();
        assert_eq!(children.len(), 1);

        // Delete and verify index is cleaned up
        engine.delete_my_entity("child").await.unwrap();
        let children = engine.list_my_entities(Some("parent-1")).await.unwrap();
        assert_eq!(children.len(), 0);
    }
}
```

Run tests:

```bash
cd balloons-rs
cargo test --package balloons-core
```

### Step 9: Write Migration (if needed)

If you're adding tables to an existing schema, update the schema version:

```rust
// In lmdb_engine.rs
const CURRENT_SCHEMA_VERSION: u32 = 2;  // Was 1

fn run_migrations(&self, from_version: u32) -> Result<()> {
    let mut current = from_version;

    while current < CURRENT_SCHEMA_VERSION {
        match current {
            1 => {
                // v1 → v2: Add my_entities table
                // Table is created automatically in open(), this just stamps version
                log::info!("Migrating v1 → v2: Adding my_entities table");
                current = 2;
            }
            _ => break,
        }
    }

    Ok(())
}
```

**Note:** For additive changes (new tables), the migration is typically a no-op because `create_database` in LMDB is idempotent - it just returns the existing database if it exists.

---

## Common Pitfalls

### 1. Forgetting to Increment `max_dbs`

LMDB requires pre-declaring the maximum number of databases. If you forget:

```
Error: Database error: Mdb error: DbsFull
```

**Fix:** Increment `max_dbs` in `EnvOpenOptions::new()`.

### 2. Index Inconsistency on Delete

If you delete an entity without cleaning up indexes, you'll have orphaned references.

**Pattern:** Always clean up indexes BEFORE deleting the primary entity, while you can still read it to find related keys.

### 3. Missing `#[serde(default)]`

If you add a new optional field without `#[serde(default)]`, deserialization will fail for old data.

**Pattern:** The codegen automatically adds `#[serde(default)]` for `Option<T>` and `Vec<T>`.

### 4. Blocking the Event Loop

PyO3 bindings run synchronously. If you call them from async Python without `run_in_executor`, you'll block the event loop.

**Pattern:** Always wrap PyO3 calls in `AsyncStorage._run_sync()`.

### 5. Forgetting to Export in `lib.rs`

New types need to be re-exported from `balloons-core/src/lib.rs`:

```rust
pub use generated::{
    // ... existing types ...
    MyEntityData,  // Add new types here
};
```

### 6. Transaction Scope Issues

LMDB transactions must be committed or they're rolled back. Don't hold transactions across await points.

**Pattern:** Open transaction, do work, commit - all in one synchronous block.

---

## Testing Strategies

### 1. Isolated Test Directories

Use `TestDir` for isolated test environments:

```rust
let dir = TestDir::new("test_name");
let engine = LmdbEngine::open(&dir.path).unwrap();
// Test runs isolated, cleaned up automatically
```

Set `BALLOONS_PRESERVE_TEST_RUNS=1` to preserve directories for debugging.

### 2. Test CRUD Cycle

Always test the full cycle:

```rust
#[tokio::test]
async fn test_crud_cycle() {
    let dir = TestDir::new("test_crud");
    let engine = LmdbEngine::open(&dir.path).unwrap();

    // Create
    let entity = make_test_entity("test");
    engine.save_my_entity(&entity).await.unwrap();

    // Read
    let loaded = engine.load_my_entity("test").await.unwrap().unwrap();
    assert_eq!(loaded.name, entity.name);

    // Update
    let mut updated = loaded;
    updated.name = "Updated".to_string();
    engine.save_my_entity(&updated).await.unwrap();
    let reloaded = engine.load_my_entity("test").await.unwrap().unwrap();
    assert_eq!(reloaded.name, "Updated");

    // Delete
    engine.delete_my_entity("test").await.unwrap();
    assert!(engine.load_my_entity("test").await.unwrap().is_none());
}
```

### 3. Test Index Consistency

When you have indexes, test they're maintained correctly:

```rust
#[tokio::test]
async fn test_index_maintained() {
    // Create entity with parent
    // Verify listed under parent
    // Delete entity
    // Verify NOT listed under parent
    // Delete parent
    // Verify no orphaned index entries
}
```

### 4. Test Concurrent Operations

LMDB handles concurrency via MVCC, but test it:

```rust
#[tokio::test]
async fn test_concurrent_writes() {
    let dir = TestDir::new("test_concurrent");
    let engine = Arc::new(LmdbEngine::open(&dir.path).unwrap());

    let handles: Vec<_> = (0..10).map(|i| {
        let engine = Arc::clone(&engine);
        tokio::spawn(async move {
            let entity = make_test_entity(&format!("entity-{}", i));
            engine.save_my_entity(&entity).await
        })
    }).collect();

    for handle in handles {
        handle.await.unwrap().unwrap();
    }

    let all = engine.list_my_entities(None).await.unwrap();
    assert_eq!(all.len(), 10);
}
```

---

## Schema Evolution

### Adding Optional Fields

Safe with `#[serde(default)]` - no migration needed:

```python
@rust_schema
@dataclass
class MyEntityData:
    # ... existing fields ...
    new_field: Optional[str] = None  # Added later
```

### Adding Required Fields with Defaults

Use `#[serde(default = "...")]`:

```rust
#[serde(default = "default_priority")]
pub priority: i64,

fn default_priority() -> i64 { 5 }
```

### Renaming Fields

Use serde's `alias`:

```rust
#[serde(alias = "old_name")]
pub new_name: String,
```

### Removing Fields

Requires migration to avoid deserialization errors with old data. Better to make optional first.

---

## Backup & Recovery

See [backup-recovery.md](./backup-recovery.md) for detailed backup procedures.

**Quick commands:**

```bash
# Health check
python scripts/backup_db.py health

# Create backup before changes
python scripts/backup_db.py backup

# Export to JSON (portable)
python scripts/backup_db.py export ~/backup

# Restore from backup
python scripts/backup_db.py restore ~/.balloons/sessions.lmdb.backup.20260212_120000
```

---

## Build & Verify Checklist

After making changes:

1. [ ] Run codegen: `python -m codegen.generate_rust`
2. [ ] Check generated schema: `cat balloons-rs/crates/balloons-core/src/generated/schema.rs`
3. [ ] Verify Rust compiles: `cd balloons-rs && cargo check`
4. [ ] Run Rust tests: `cargo test --package balloons-core`
5. [ ] Build Python bindings: `cd balloons-rs && maturin develop`
6. [ ] Test Python import: `python -c "import balloons_py; print('OK')"`
7. [ ] Run integration tests: `pytest tests/test_storage.py`
