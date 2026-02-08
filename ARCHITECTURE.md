# Balloons Architecture

## Architectural Decisions

### Confirmed Decisions

1. **Python TUI with Textual** - Main application is Python using the Textual framework for terminal UI.

2. **Session-based conversation model** - Conversations are organized as sessions with turns, supporting forking and merging.

3. **Context management** - Per-turn COPY/COMPRESS/DROP modes for context window management.

### Tentative Decisions (Under Development)

1. **Rust storage layer (balloons-rs)** - Investigating a Rust-based ACID storage backend to replace JSON file storage. Status: scaffolded, not yet integrated.

   - **Problem**: JSON file writes are non-atomic, causing session corruption when interrupted mid-write (0-byte files).
   - **Solution**: redb (embedded key-value database) + PyO3 bindings
   - **Integration**: Not yet connected to Python session.py
   - **Approach**: Progressive migration - start with storage, iterate towards more Rust over time

2. **Python-to-Rust schema generation** - Python dataclasses as source of truth, with codegen to Rust structs.

   - **Rationale**: Avoids schema drift between Python and Rust
   - **Location**: `codegen/` module, `storage_schema.py` for DTOs

## Progressive Rust Migration Strategy

The Rust implementation is designed for **incremental adoption**:

1. **Phase 1 (current)**: Storage layer only
   - Python remains the primary language
   - Rust provides ACID storage as a library
   - Fallback to JSON if Rust unavailable

2. **Phase 2 (future)**: Performance-critical paths
   - Token counting, context compilation
   - Large text processing

3. **Phase 3 (future)**: Core domain logic
   - Session/Turn management
   - Fork/merge operations

This approach allows us to:
- Ship improvements incrementally
- Maintain working Python fallbacks
- Learn what works before committing

## Module Overview

```
balloons/
├── app.py              # Main Textual application
├── session.py          # Session management (current JSON backend)
├── models.py           # Domain entities (Turn, Message, ContentBlock types)
├── storage_schema.py   # Storage DTOs for Rust codegen
├── codegen/            # Python-to-Rust code generation
│   ├── rust_schema.py  # @rust_schema decorator and type mapping
│   └── generate_rust.py # Generator script
└── balloons-rs/        # Rust workspace (tentative)
    └── crates/
        ├── balloons-core/  # Storage engine, generated schema
        └── balloons-py/    # PyO3 bindings
```

## Rust Storage Layer (balloons-rs)

### Status: TENTATIVE

The Rust storage layer is scaffolded but not integrated. Current Python code still uses JSON files directly.

### Architecture

```
Python asyncio
    │
    │  JSON string (via run_in_executor)
    ▼
┌─────────────────────────────────┐
│  balloons-py (PyO3 sync bridge) │
│  - py.allow_threads()           │
│  - core-executor for async      │
│  - JSON <-> Rust struct         │
└─────────────────────────────────┘
    │
    │  Storage DTOs
    ▼
┌─────────────────────────────────┐
│  balloons-core (async Rust)     │
│  - StorageEngine trait          │
│  - RedbEngine implementation    │
│  - JSON serialization to redb   │
└─────────────────────────────────┘
    │
    │  JSON bytes
    ▼
┌─────────────────────────────────┐
│           redb                  │
│  (ACID key-value database)      │
└─────────────────────────────────┘
```

### Key Design Choices

| Choice | Decision | Rationale |
|--------|----------|-----------|
| Database | redb | Pure Rust, ACID, single-writer MVCC, 1.0 stable |
| Serialization | JSON (not postcard) | Schema uses `serde_json::Value` for flexible content blocks |
| Async executor | core-executor | CPU-affine threads, consistent with other Rust projects |
| Schema source | Python | `@rust_schema` decorator generates Rust structs |
| PyO3 API | Sync | Python calls sync Rust which internally blocks on async |

### Integration Path (TODO)

1. Build PyO3 wheel with maturin
2. Create Python wrapper in session.py that uses Rust storage
3. Add migration for existing JSON session files
4. Feature flag to switch between JSON and Rust backends
5. Gradual rollout: Rust for new sessions, JSON for existing
6. Eventually: Rust as default, JSON as fallback
