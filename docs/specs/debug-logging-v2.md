# Debug Logging v2 Spec

## Overview

A structured logging system that enables both humans and the LLM to debug the Balloons application. Logs are organized by component, stored both in-memory (for fast queries) and on disk (for persistence).

## Design Goals

1. **LLM self-debugging** - The LLM can query logs, enable categories, and diagnose issues
2. **Component-based categories** - Categories map to system topology, not ad-hoc concerns
3. **Dual storage** - In-memory buffers for fast queries, disk files for persistence
4. **Server identity** - Each server knows its git commit and can report it
5. **Lifecycle events** - System events (start, stop, config changes) are logged

## Categories (8 core)

| Category | Component | What it logs |
|----------|-----------|--------------|
| `client` | Web UI | React events, user interactions |
| `api` | Internal APIs | WebSocket, HTTP auth routes |
| `runner` | LLM orchestration | LLM calls, tool execution, context building |
| `session` | Session management | Lifecycle, fork/merge, context modes |
| `storage` | Persistence | DB reads/writes |
| `supervisor` | Process supervisor | Background process lifecycle |
| `lifecycle` | Server lifecycle | Start/stop, config changes, git identity |
| `perf` | Performance | Timing markers, latency measurements |

Unknown categories go to a default buffer for backward compatibility.

## Storage Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ DebugLog (server singleton)                                 │
│                                                             │
│  Per-category ring buffers:                                 │
│    api: RingBuffer(size=N)                                  │
│    runner: RingBuffer(size=N)                               │
│    session: RingBuffer(size=N)                              │
│    ...                                                      │
│                                                             │
│  On log(entry):                                             │
│    1. Add to category's ring buffer                         │
│    2. Async write to ~/.balloons/logs/{category}.log        │
│    3. Notify listeners (for real-time subscriptions)        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Ring Buffers

- One buffer per category
- Size configurable (default TBD, maybe 500 per category)
- Buffer size adjustable via Options pane
- No filtering on write - everything is buffered

### Disk Files

- Location: `~/.balloons/logs/{category}.log`
- Format: JSONL (one JSON object per line)
- Written async (fire-and-forget)
- Survives server restarts

### Entry Format

```json
{
  "seq": 12345,
  "timestamp": "2024-02-28T12:34:56.789Z",
  "level": "info",
  "category": "api",
  "message": "Request completed",
  "session_id": "abc-123",
  "run_id": "run-456",
  "details": {"status": 200, "latency_ms": 150}
}
```

## Server Identity

At startup, capture and log:

```python
{
  "git_commit": "abc123def...",      # git rev-parse HEAD
  "git_branch": "main",               # git branch --show-current
  "git_dirty": True,                  # git status --porcelain != ""
  "git_diff_hash": "a1b2c3",          # sha256(git diff)[:12] - fingerprint of local changes
  "slot": "B",                        # A or B
  "port": 8710,
  "pid": 12345,
  "start_time": "2024-02-28T12:00:00Z"
}
```

This enables:
- Knowing what code version the server is running
- Detecting when source differs from running server
- Correlating logs with specific code states

## Lifecycle Events

Events logged to the `lifecycle` category:

| Event | When | Details |
|-------|------|---------|
| `server_started` | Server startup | git identity, slot, port |
| `server_stopping` | Graceful shutdown | reason (restart, signal) |
| `config_changed` | Config reload/change | what changed |
| `category_enabled` | Debug category toggled | category name |
| `category_disabled` | Debug category toggled | category name |

## Balloons Tools for LLM

### debug_log_query

Query recent log entries from in-memory buffer.

```json
{
  "name": "debug_log_query",
  "args": {
    "category": "api",           // required
    "limit": 50,                 // optional, default 50
    "level": "error",            // optional, filter by level
    "run_id": "run-123",         // optional, filter by run
    "session_id": "sess-456"     // optional, filter by session
  }
}
```

Returns: Array of log entries (most recent first)

### debug_log_config

Query or modify log configuration.

```json
// List enabled categories
{"name": "debug_log_config", "args": {"action": "list"}}

// Enable a category
{"name": "debug_log_config", "args": {"action": "enable", "category": "runner"}}

// Disable a category
{"name": "debug_log_config", "args": {"action": "disable", "category": "runner"}}

// Get server identity
{"name": "debug_log_config", "args": {"action": "identity"}}
```

### debug_log_tail

Tail a log file (for historical/long-term debugging).

```json
{
  "name": "debug_log_tail",
  "args": {
    "category": "api",
    "lines": 100,                // last N lines
    "grep": "error"              // optional, filter pattern
  }
}
```

## WebSocket API

The existing `DebugLogService` will be extended:

```python
@ws_expose
def query_entries(
    self,
    category: str,
    limit: int = 50,
    level: str | None = None,
    run_id: str | None = None,
    session_id: str | None = None
) -> list[LogEntry]:
    """Query in-memory buffer for a category."""

@ws_expose
def get_identity(self) -> ServerIdentity:
    """Get server git identity and metadata."""

@ws_expose
def get_buffer_sizes(self) -> dict[str, int]:
    """Get current buffer size per category."""

@ws_expose
def set_buffer_size(self, category: str, size: int) -> bool:
    """Set buffer size for a category."""
```

Events emitted:
- `onLogEntry(category, entry)` - real-time log entries (if subscribed)
- `onConfigChanged(key, value)` - config changes

## Options Pane UI

The Options tab will show:

1. **Debug Logging** (master toggle)
   - Enable/disable debug logging globally

2. **Category Toggles**
   - Checkboxes for each category
   - Shows current enabled state

3. **Buffer Sizes** (advanced)
   - Per-category buffer size sliders
   - Shows current entry count vs max

4. **Server Identity** (read-only)
   - Git commit, branch, dirty status
   - Slot, port, uptime

## Usage Patterns

### "Something just broke"
1. Use `debug_log_query(category="api", limit=20)` to see recent entries
2. Check for errors/warnings
3. Filter by `run_id` if you know which call failed

### "When did this start happening"
1. Tail the log file: `tail -100 ~/.balloons/logs/api.log | grep error`
2. Or use `debug_log_tail(category="api", lines=500, grep="error")`

### "Am I running my changes"
1. Use `debug_log_config(action="identity")`
2. Compare `git_commit` with local `git rev-parse HEAD`
3. Check `git_dirty` and `git_diff_hash`

### "Track a specific LLM call"
1. Note the `run_id` from streaming events
2. Query: `debug_log_query(category="runner", run_id="run-123")`

## Migration from v1

1. Remove `debug_log_file` config option ✓
2. Remove single-file logging path ✓
3. Add `Category` class with component-based constants ✓
4. Add per-category ring buffers (replacing single shared buffer) ✓
5. Add `RingBuffer` class with resize support ✓
6. Add `query()` method for category-specific queries ✓
7. Add WebSocket API for query and buffer management ✓
8. Add server identity capture at startup ✓ (`core/server_identity.py`)
9. Add lifecycle event logging ✓ (`headless.py` start/stop events)
10. Add balloons-tools for LLM querying ✓ (`core/debug_tools.py`)
11. Update prompt documentation ✓

## Files Modified

| File | Changes | Status |
|------|---------|--------|
| `core/debug_log.py` | Per-category buffers, new categories, RingBuffer class | ✓ |
| `core/server_identity.py` | Server identity capture (git state, metadata) | ✓ New |
| `core/debug_tools.py` | LLM-facing debug tools | ✓ New |
| `core/tools.py` | DEBUG_TOOLS definitions, get_tools_for_request | ✓ |
| `core/tool_executor.py` | Dispatch for debug tools | ✓ |
| `service/debug_log_service.py` | Query endpoints, identity endpoint, buffer management | ✓ |
| `headless.py` | Capture git identity at startup, lifecycle events | ✓ |
| `web/ui/src/components/OptionsTab/` | Buffer size controls, identity display | ✓ |
| `prompts/shared/debug-logging.md` | Document new categories and tools | ✓ |

## Open Questions

1. ~~What should default buffer sizes be per category?~~ → 500 per category (implemented)
2. Should buffer sizes persist in config or be session-only?
3. ~~Should we add a "clear buffer" action?~~ → Yes, implemented via `clear_buffer()` WebSocket API
4. Do we need log rotation for disk files?
5. Should lifecycle events also go to their own file (`lifecycle.log`)?
