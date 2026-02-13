# Schema Versioning and Migration Strategy for LMDB Storage

**Status**: Design Document (Spike Output)
**Author**: Claude (spike session)
**Date**: 2026-02-12
**Related**: `balloons-rs/crates/balloons-core/src/storage/`, `storage_schema.py`

## Executive Summary

This document proposes a hybrid versioning strategy for balloons' LMDB storage:

1. **Database-level version** in metadata table for coordinating breaking changes
2. **Serde's `#[serde(default)]`** for additive/compatible field changes
3. **Explicit migration functions** triggered on version mismatch

This approach minimizes overhead for the common case (compatible changes) while providing a clear path for breaking changes.

---

## 1. Context & Current State

### Current Storage Architecture

```
LMDB Database (via heed) - 15 tables
├── Session Management
│   ├── sessions: session_id → JSON SessionData
│   ├── turns: turn_id → JSON TurnData
│   ├── turn_order: session_id → JSON TurnOrder
│   └── metadata: key → value (session_history, schema_version, etc.)
├── Goal System - Primary Entities
│   ├── goals: goal_id → JSON GoalData
│   ├── plans: plan_id → JSON PlanData
│   └── todos: todo_id → JSON TodoData
├── Goal System - Relationship Indexes
│   ├── plans_by_goal: goal_id → [plan_id]
│   ├── todos_by_plan: plan_id → [todo_id]
│   ├── plans_by_todo: todo_id → [plan_id] (reverse)
│   ├── todo_dependencies: todo_id → [TodoDependency]
│   └── todo_dependents: todo_id → [todo_id] (reverse)
└── Session Bindings
    ├── session_bindings: binding_id → JSON SessionBinding
    ├── bindings_by_session: session_id → [binding_id]
    └── bindings_by_entity: "type:id" → [binding_id]
```

All data is stored as JSON via `serde_json`, providing:
- Human-readable storage for debugging
- Flexible schema evolution through JSON's additive nature
- Cross-language compatibility (Python ↔ Rust)

### Schema Sources

- **Python side**: `storage_schema.py` defines `@rust_schema`-decorated dataclasses
- **Rust side**: `generated/schema.rs` is auto-generated from Python
- Both serialize to identical JSON via serde

---

## 2. Questions Answered

### Q1: How do we detect schema version mismatches?

**Approach**: Store a `schema_version` integer in the metadata table.

```rust
const SCHEMA_VERSION_KEY: &str = "schema_version";
const CURRENT_SCHEMA_VERSION: u32 = 1;  // Bump on breaking changes

impl LmdbEngine {
    fn check_schema_version(&self) -> Result<SchemaStatus> {
        let rtxn = self.env.read_txn()?;
        match self.metadata.get(&rtxn, SCHEMA_VERSION_KEY)? {
            Some(bytes) => {
                let stored: u32 = serde_json::from_slice(bytes)?;
                if stored == CURRENT_SCHEMA_VERSION {
                    Ok(SchemaStatus::Current)
                } else if stored < CURRENT_SCHEMA_VERSION {
                    Ok(SchemaStatus::NeedsMigration { from: stored })
                } else {
                    Ok(SchemaStatus::TooNew { version: stored })
                }
            }
            None => Ok(SchemaStatus::Unversioned), // Legacy DB
        }
    }
}

enum SchemaStatus {
    Current,                        // No action needed
    NeedsMigration { from: u32 },   // Run migrations from `from` to CURRENT
    TooNew { version: u32 },        // Error: DB from newer version
    Unversioned,                    // Legacy: needs version stamp
}
```

**On first open**:
1. Check `schema_version` key
2. If missing → stamp with `CURRENT_SCHEMA_VERSION` (assume new or legacy-compatible)
3. If present and older → run migrations
4. If present and newer → error (can't downgrade)

### Q2: How do we migrate data when schema changes?

**Strategy**: Explicit migration functions, run lazily on database open.

```rust
/// Registry of migrations. Each migrates from version N to N+1.
fn get_migrations() -> Vec<Box<dyn Fn(&mut heed::RwTxn, &LmdbTables) -> Result<()>>> {
    vec![
        // v1 → v2: Add sentiment field to turns
        Box::new(migrate_v1_to_v2),
        // v2 → v3: Restructure children field in sessions
        Box::new(migrate_v2_to_v3),
    ]
}

impl LmdbEngine {
    pub fn open_with_migration(path: impl AsRef<Path>) -> Result<Self> {
        let engine = Self::open_internal(path)?;

        match engine.check_schema_version()? {
            SchemaStatus::Current => Ok(engine),
            SchemaStatus::NeedsMigration { from } => {
                engine.run_migrations(from)?;
                Ok(engine)
            }
            SchemaStatus::TooNew { version } => {
                Err(Error::SchemaTooNew {
                    db_version: version,
                    code_version: CURRENT_SCHEMA_VERSION
                })
            }
            SchemaStatus::Unversioned => {
                engine.stamp_version()?;
                Ok(engine)
            }
        }
    }

    fn run_migrations(&self, from_version: u32) -> Result<()> {
        let migrations = get_migrations();
        let mut wtxn = self.env.write_txn()?;

        for version in from_version..CURRENT_SCHEMA_VERSION {
            let idx = (version - 1) as usize;  // v1→v2 is migrations[0]
            log::info!("Running migration v{} → v{}", version, version + 1);
            migrations[idx](&mut wtxn, &self.tables())?;
        }

        // Update stored version
        let version_bytes = serde_json::to_vec(&CURRENT_SCHEMA_VERSION)?;
        self.metadata.put(&mut wtxn, SCHEMA_VERSION_KEY, &version_bytes)?;

        wtxn.commit()?;
        log::info!("Migrations complete, now at v{}", CURRENT_SCHEMA_VERSION);
        Ok(())
    }
}
```

**Example migration**:

```rust
/// v1 → v2: Add sentiment field to TurnData
///
/// TurnData previously had no sentiment field. With serde(default),
/// old records deserialize fine, but we run this migration to:
/// 1. Verify all records are readable
/// 2. Set explicit null values for audit trail
fn migrate_v1_to_v2(wtxn: &mut heed::RwTxn, tables: &LmdbTables) -> Result<()> {
    // Iterate all turns, deserialize with new schema, re-save
    for entry in tables.turns.iter(wtxn)? {
        let (key, value) = entry?;

        // Deserialize - serde(default) handles missing field
        let mut turn: TurnDataV2 = serde_json::from_slice(value)?;

        // Explicit migration logic (if needed beyond defaults)
        if turn.sentiment.is_none() {
            // Could set based on heuristics, or leave as None
        }

        // Re-serialize and save
        let bytes = serde_json::to_vec(&turn)?;
        tables.turns.put(wtxn, key, &bytes)?;
    }

    Ok(())
}
```

### Q3: Should we version at the database level or per-entity?

**Recommendation**: **Database-level versioning only.**

**Rationale**:

| Approach | Pros | Cons |
|----------|------|------|
| **Database-level** | Simple, one check on open, atomic migrations | All-or-nothing migration |
| **Per-record** | Lazy migration, mixed versions | Complexity, storage overhead, version in every read |
| **Per-entity-type** | Targeted migrations | Multiple version keys, complex coordination |

Per-record versioning adds a version field to every record:
```rust
struct TurnData {
    _v: u32,  // Version tag in every record
    // ... fields
}
```
This is overkill for our use case because:
1. All records are created by the same codebase version
2. Migrations are fast (LMDB is fast, our datasets are small)
3. JSON already handles missing fields gracefully

**Database-level is simpler and sufficient.** We can always add per-entity versioning later if needed.

### Q4: How do we handle backwards compatibility?

**Three-tier approach**:

#### Tier 1: Serde Defaults (No Version Bump)

For additive changes that don't require migration:

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TurnData {
    pub id: String,
    pub role: String,
    // ... existing fields ...

    // NEW: Added in 2026-02, backwards compatible
    #[serde(default)]
    pub exchange_id: Option<String>,

    #[serde(default)]
    pub sentiment: Option<String>,
}
```

**No version bump needed** because:
- Old records deserialize with `None`/default values
- New records serialize with the field present
- Python and Rust stay in sync via codegen

#### Tier 2: Migration with Version Bump

For changes requiring data transformation:

```rust
// Old format (v1)
struct SessionDataV1 {
    children: Vec<String>,  // Just session IDs
}

// New format (v2)
struct SessionDataV2 {
    children: Vec<ChildInfo>,  // Rich info: {session_id, status, fork_name}
}

// Migration converts v1 → v2
fn migrate_v1_to_v2(wtxn: &mut RwTxn, tables: &LmdbTables) -> Result<()> {
    for entry in tables.sessions.iter(wtxn)? {
        let (key, value) = entry?;

        // Try parsing as V1 first (uses serde untagged)
        let v1: SessionDataV1 = serde_json::from_slice(value)?;

        // Convert to V2
        let v2 = SessionDataV2 {
            // ... copy fields ...
            children: v1.children.iter().map(|id| ChildInfo {
                session_id: id.clone(),
                status: "active".to_string(),
                fork_name: String::new(),
            }).collect(),
        };

        let bytes = serde_json::to_vec(&v2)?;
        tables.sessions.put(wtxn, key, &bytes)?;
    }
    Ok(())
}
```

#### Tier 3: Breaking Changes (Major Version)

For incompatible changes (e.g., removing fields, changing key structure):

1. Bump major schema version
2. Provide explicit migration path
3. Document in CHANGELOG
4. Consider backup/export before migration

---

## 3. Recommended Implementation

### Phase 1: Add Version Infrastructure (Now)

```rust
// In lmdb_engine.rs

const SCHEMA_VERSION_KEY: &str = "schema_version";
const CURRENT_SCHEMA_VERSION: u32 = 1;

pub enum SchemaStatus {
    Current,
    NeedsMigration { from: u32 },
    TooNew { version: u32 },
    Unversioned,
}

impl LmdbEngine {
    /// Open database with automatic migration
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let engine = Self::open_raw(path)?;
        engine.ensure_schema_version()?;
        Ok(engine)
    }

    fn ensure_schema_version(&self) -> Result<()> {
        match self.check_schema_version()? {
            SchemaStatus::Current => Ok(()),
            SchemaStatus::Unversioned => {
                // New DB or legacy - stamp current version
                self.stamp_version(CURRENT_SCHEMA_VERSION)
            }
            SchemaStatus::NeedsMigration { from } => {
                self.run_migrations(from)
            }
            SchemaStatus::TooNew { version } => {
                Err(Error::Database(format!(
                    "Database schema v{} is newer than code v{}. Please upgrade.",
                    version, CURRENT_SCHEMA_VERSION
                )))
            }
        }
    }

    fn check_schema_version(&self) -> Result<SchemaStatus> {
        let rtxn = self.env.read_txn().map_err(|e| Error::Database(e.to_string()))?;
        match self.metadata.get(&rtxn, SCHEMA_VERSION_KEY).map_err(|e| Error::Database(e.to_string()))? {
            Some(bytes) => {
                let stored: u32 = serde_json::from_slice(bytes)
                    .map_err(|e| Error::Serialization(e.to_string()))?;
                if stored == CURRENT_SCHEMA_VERSION {
                    Ok(SchemaStatus::Current)
                } else if stored < CURRENT_SCHEMA_VERSION {
                    Ok(SchemaStatus::NeedsMigration { from: stored })
                } else {
                    Ok(SchemaStatus::TooNew { version: stored })
                }
            }
            None => Ok(SchemaStatus::Unversioned),
        }
    }

    fn stamp_version(&self, version: u32) -> Result<()> {
        let bytes = serde_json::to_vec(&version)
            .map_err(|e| Error::Serialization(e.to_string()))?;
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;
        self.metadata.put(&mut wtxn, SCHEMA_VERSION_KEY, &bytes)
            .map_err(|e| Error::Database(e.to_string()))?;
        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;
        Ok(())
    }

    fn run_migrations(&self, from: u32) -> Result<()> {
        let mut wtxn = self.env.write_txn().map_err(|e| Error::Database(e.to_string()))?;

        for version in from..CURRENT_SCHEMA_VERSION {
            log::info!("Migrating schema v{} → v{}", version, version + 1);
            match version {
                // Add migration cases as needed:
                // 1 => migrate_v1_to_v2(&mut wtxn, &self.sessions, &self.turns)?,
                _ => {} // No-op for versions with no structural migration
            }
        }

        // Update version
        let bytes = serde_json::to_vec(&CURRENT_SCHEMA_VERSION)
            .map_err(|e| Error::Serialization(e.to_string()))?;
        self.metadata.put(&mut wtxn, SCHEMA_VERSION_KEY, &bytes)
            .map_err(|e| Error::Database(e.to_string()))?;

        wtxn.commit().map_err(|e| Error::Database(e.to_string()))?;
        log::info!("Migration complete, now at v{}", CURRENT_SCHEMA_VERSION);
        Ok(())
    }
}
```

### Phase 2: Ensure Serde Defaults on All Optional Fields

```rust
// In generated/schema.rs (via codegen changes)

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TurnData {
    pub id: String,
    pub role: String,
    pub content_block: serde_json::Value,
    pub tokens: i64,
    pub timestamp: String,
    pub context_mode: String,
    pub summary: String,

    #[serde(default)]  // <-- Add to all Option<T> fields
    pub exchange_id: Option<String>,

    #[serde(default)]
    pub sentiment: Option<String>,
}
```

Update codegen to emit `#[serde(default)]` for:
- All `Option<T>` fields
- All `Vec<T>` fields
- All fields with default values in Python

### Phase 3: Document Migration Procedures

Create `docs/migrations/README.md`:

```markdown
# Schema Migrations

## Adding a New Migration

1. Increment `CURRENT_SCHEMA_VERSION` in `lmdb_engine.rs`
2. Add migration function: `fn migrate_vN_to_vN+1(...)`
3. Add case to `run_migrations()` match
4. Test with a copy of production data
5. Document in CHANGELOG

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1 | 2026-02 | Initial schema version |
```

---

## 4. Example: Complete Migration Flow

Let's walk through adding a `priority` field to `TodoData`:

### Step 1: Additive Change (No Migration Needed)

```python
# storage_schema.py
@rust_schema
@dataclass
class TodoData:
    # ... existing fields ...
    priority: Optional[int] = None  # NEW: 1-10 priority override
```

After codegen:
```rust
// generated/schema.rs
pub struct TodoData {
    // ... existing fields ...
    #[serde(default)]
    pub priority: Option<i64>,
}
```

**No version bump**. Old records deserialize with `priority: None`.

### Step 2: Later, Make Priority Required with Default

Now we want all todos to have a priority, defaulting to 5:

```python
# storage_schema.py
@rust_schema
@dataclass
class TodoData:
    # ... existing fields ...
    priority: int = 5  # Changed: now required with default
```

After codegen (with updated codegen for non-Option defaults):
```rust
pub struct TodoData {
    // ...
    #[serde(default = "default_priority")]
    pub priority: i64,
}

fn default_priority() -> i64 { 5 }
```

**Still no version bump** - serde handles the default on deserialization.

### Step 3: Complex Migration (Version Bump Required)

Later, we restructure: replace `priority` with `priority_mode` enum:

```rust
// Migration v2 → v3
fn migrate_v2_to_v3(wtxn: &mut RwTxn, tables: &LmdbTables) -> Result<()> {
    // Read todos with old schema
    for entry in tables.todos.iter(wtxn)? {
        let (key, value) = entry?;
        let old: TodoDataV2 = serde_json::from_slice(value)?;

        // Convert priority number to mode
        let priority_mode = match old.priority {
            1..=3 => "low",
            4..=6 => "normal",
            7..=10 => "high",
            _ => "normal",
        }.to_string();

        let new = TodoDataV3 {
            // ... copy fields ...
            priority_mode,
        };

        tables.todos.put(wtxn, key, &serde_json::to_vec(&new)?)?;
    }
    Ok(())
}
```

---

## 5. Rejected Alternatives

### Per-Record Version Tags

```rust
struct TurnData {
    #[serde(rename = "_v")]
    version: u32,
    // ... fields
}
```

**Rejected because**:
- Adds 8+ bytes per record
- Requires version check on every read
- Complicates all serialization code
- Overkill for single-user desktop app

### Tagged Enum Variants

```rust
#[serde(tag = "schema_version")]
enum SessionData {
    V1(SessionDataV1),
    V2(SessionDataV2),
}
```

**Rejected because**:
- Major code churn for each version
- All consumers must handle all variants
- Doesn't compose well with codegen from Python

### External Migration Tool

Separate CLI tool that migrates databases offline.

**Rejected because**:
- Extra step for users
- Risk of data loss if forgotten
- Balloons is a single-user app - inline migration is fine

---

## 6. Open Questions for Future Work

1. **Backup before migration?** Should we auto-backup the DB dir before running migrations?

2. **Python-side versioning?** Do we need schema versioning in `async_storage.py` too, or just Rust?

3. **Concurrent access during migration?** Currently single-process, but if we add multi-process support, migrations need coordination.

4. **Goal entity migrations?** The goal system is new - do we need migration planning for GoalData/PlanData/TodoData specifically?

---

## 7. Summary

| Change Type | Action | Version Bump |
|-------------|--------|--------------|
| Add optional field | `#[serde(default)]` | No |
| Add field with default | `#[serde(default = "...")]` | No |
| Rename field | `#[serde(alias = "old_name")]` | No |
| Remove field | Migration to drop data | Yes |
| Restructure field | Migration to transform | Yes |
| Change field type | Migration to convert | Yes |

**Key principle**: Use serde's flexibility for compatible changes; reserve explicit migrations for breaking changes. Database-level versioning keeps things simple.

---

## See Also

- [Storage Extension Guide](../storage-guide.md) - Step-by-step process for adding new entity types
- [Backup & Recovery](../backup-recovery.md) - Database backup and recovery procedures
