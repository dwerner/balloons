# balloons-rs

Rust backend for Balloons. **Status: Working** - PyO3 bindings tested.

## Overview

Provides:
1. **ACID-compliant session storage** using LMDB, exposed to Python via PyO3
2. **Process Supervisor** for managing long-running commands with streaming output

This is part of a **progressive migration** towards Rust. The goal is to iterate incrementally:
1. Start with storage (done)
2. Add process supervision for LLM tool use (done)
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
│   │       ├── storage/    # LmdbEngine, StorageClient, traits
│   │       └── testutil.rs # Test helpers
│   ├── balloons-supervisor/ # Process management
│   │   └── src/
│   │       ├── lib.rs      # Public API
│   │       ├── supervisor.rs # ProcessSupervisor
│   │       ├── process.rs  # SupervisedProcess
│   │       ├── types.rs    # Common types
│   │       └── error.rs    # Error types
│   └── balloons-py/        # PyO3 bindings
│       └── src/lib.rs      # Python-facing Storage and Supervisor classes
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

### Storage Usage

```python
from balloons_storage import Storage

# Open/create a database
storage = Storage("/path/to/balloons.lmdb")

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

### Supervisor Usage

The `Supervisor` class manages long-running background processes with streaming output capture.
This is designed for LLM tool use - allowing an AI assistant to start, monitor, and control
background processes without blocking on completion.

```python
from balloons_storage import Supervisor
import json

# Create a supervisor
supervisor = Supervisor()

# Start a long-running process
process_id = supervisor.start(
    command="cargo build --release",
    session_id="my-session-123",
    working_dir="/path/to/project",
    name="build",  # Optional friendly name
)

# Get process info
info_json = supervisor.get_process(process_id)
info = json.loads(info_json)
print(f"Status: {info['status']}")  # e.g., {"state": "running", "pid": 12345}

# Get recent output
output_json = supervisor.get_output(process_id, limit=50)
logs = json.loads(output_json)
for entry in logs:
    print(f"[{entry['source']}] {entry['content']}")

# List all processes for a session
processes_json = supervisor.list_processes(session_id="my-session-123")
processes = json.loads(processes_json)

# Stop a process
supervisor.stop_process(process_id)

# Stop all processes for a session
count = supervisor.stop_session_processes("my-session-123")
print(f"Stopped {count} processes")

# Check counts
running = supervisor.running_count()
total = supervisor.total_count()
```

**Process Info Fields:**
- `id`: Unique process identifier (UUID)
- `name`: Friendly name (if provided)
- `command`: The shell command being executed
- `working_dir`: Working directory
- `session_id`: Session this process belongs to
- `status`: One of:
  - `{"state": "running", "pid": 12345}`
  - `{"state": "exited", "code": 0, "signal": null}`
  - `{"state": "failed", "error": "message"}`
- `started_at`: ISO timestamp
- `ended_at`: ISO timestamp (if completed)
- `log_count`: Number of log entries captured
- `output_preview`: Last line of output (for display)

**Log Entry Fields:**
- `timestamp`: ISO timestamp
- `source`: "stdout", "stderr", or "system"
- `content`: The log line content

All methods are synchronous from Python's perspective. Use `asyncio.run_in_executor()`
for async integration.

## Dependencies

- **heed/LMDB**: Embedded key-value database (ACID, single-writer MVCC)
- **procstream**: Process execution with streaming output
- **core-executor**: CPU-affine async executor
- **smol**: Lightweight async runtime for supervisor operations
- **serde_json**: JSON serialization
- **PyO3**: Python bindings
