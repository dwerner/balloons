# balloons-rs

Rust storage backend for Balloons. **Status: Working** - PyO3 bindings tested, pending full integration.

## Overview

Provides ACID-compliant session storage using redb, exposed to Python via PyO3.

This is the first step in a **progressive migration** towards Rust. The goal is to iterate incrementally:
1. Start with storage (current focus)
2. Add performance-critical operations
3. Eventually migrate core domain logic

See `../ARCHITECTURE.md` for the full migration strategy.

## Structure

```
balloons-rs/
├── Cargo.toml              # Workspace root
├── crates/
│   ├── balloons-core/      # Storage engine
│   │   └── src/
│   │       ├── generated/  # Auto-generated from Python (DO NOT EDIT)
│   │       ├── storage/    # RedbEngine, StorageClient, traits
│   │       └── testutil.rs # Test helpers
│   └── balloons-py/        # PyO3 bindings
│       └── src/lib.rs      # Python-facing Storage class
```

## Building

```bash
cd balloons-rs
cargo build
cargo test
```

## Testing

```bash
# Run all tests
cargo test

# Preserve test artifacts for debugging
BALLOONS_PRESERVE_TEST_RUNS=1 cargo test
# Artifacts saved to .test-runs/
```

## Generated Schema

The `src/generated/` directory contains Rust structs generated from Python.

**DO NOT EDIT** these files directly. To update:

```bash
cd ..  # balloons project root
python -m codegen.generate_rust
cd balloons-rs && cargo check
```

See `../codegen/README.md` for details.

## PyO3 Integration

Build and install the Python wheel:

```bash
cd crates/balloons-py
maturin develop  # Install to current venv
```

Usage in Python:

```python
from balloons_storage import Storage

# Open/create a database
storage = Storage("/path/to/balloons.redb")

# Save a session (JSON string)
storage.save_session("session-id", json_string)

# Load a session (returns JSON string or None)
loaded = storage.load_session("session-id")

# List all sessions (returns JSON array of metadata)
sessions = storage.list_sessions()

# Delete a session
storage.delete_session("session-id")

# Turn operations
storage.save_turn("session-id", turn_json)
turns_json = storage.load_turns("session-id")
storage.delete_turn("session-id", "turn-id")
storage.reorder_turns("session-id", '["turn-3", "turn-1", "turn-2"]')
```

All methods are synchronous from Python's perspective. Use `asyncio.run_in_executor()`
for async integration.

## Dependencies

- **redb**: Embedded key-value database (ACID, single-writer MVCC)
- **core-executor**: CPU-affine async executor
- **serde_json**: JSON serialization (for flexible content blocks)
- **PyO3**: Python bindings
