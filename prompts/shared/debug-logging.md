## Debug Logging

Balloons has a structured debug logging system with per-category ring buffers.

**Architecture:**
- `core/debug_log.py` - Server-side singleton with per-category ring buffers
- `core/server_identity.py` - Captures git state and server metadata at startup
- `core/debug_tools.py` - LLM-facing tools for log querying
- `service/debug_log_service.py` - WebSocket API for the UI
- `web/ui/src/utils/debugLog.ts` - Client-side logger that sends to server

**Log files:**
- `~/.balloons/logs/{category}.log` - Category-specific logs (JSONL format)
- `~/.balloons/debug/interactions/` - Full interaction dumps on API errors

**Categories (8 core):**

| Category | What it logs |
|----------|--------------|
| `client` | Web UI events |
| `api` | Internal APIs (WebSocket, HTTP auth) |
| `runner` | LLM calls, tool execution, context building |
| `session` | Session lifecycle, fork/merge |
| `storage` | DB reads/writes |
| `supervisor` | Background process lifecycle |
| `lifecycle` | Server start/stop, config changes, git identity |
| `perf` | Timing markers, latency measurements |

Note: Unknown categories go to a default buffer for backward compatibility.

**How it works:**
- Each category has its own ring buffer (500 entries by default)
- All entries go to their category buffer (no filtering on write)
- When you enable categories, entries also write to `~/.balloons/logs/{category}.log`
- Query specific categories for efficient debugging

**Debug Tools (LLM self-debugging):**

Query log entries from in-memory buffer (default: 10 entries, compact format):
```json
{"name": "debug_log_query", "args": {"category": "api"}}
{"name": "debug_log_query", "args": {"category": "api", "level": "error"}}
{"name": "debug_log_query", "args": {"category": "api", "limit": 20, "offset": 10}}
{"name": "debug_log_query", "args": {"category": "runner", "run_id": "run-123", "verbose": true}}
```

Configure logging and check server identity:
```json
{"name": "debug_log_config", "args": {"action": "identity"}}
{"name": "debug_log_config", "args": {"action": "stats"}}
{"name": "debug_log_config", "args": {"action": "enable", "category": "api"}}
```

Tail log files for historical debugging (default: 20 lines, compact format):
```json
{"name": "debug_log_tail", "args": {"category": "api"}}
{"name": "debug_log_tail", "args": {"category": "api", "grep": "error"}}
{"name": "debug_log_tail", "args": {"category": "api", "lines": 50, "offset": 20, "verbose": true}}
```

**Tailing logs (bash):**
```bash
tail -f ~/.balloons/logs/api.log      # API requests/responses
tail -f ~/.balloons/logs/runner.log   # LLM orchestration
tail -f ~/.balloons/logs/tool.log     # Tool execution
tail -f ~/.balloons/logs/lifecycle.log # Server start/stop
```

**From code:**
```python
from core.debug_log import debug_log, Category

# Log at various levels (category is required)
debug_log.info("Message", category=Category.API, details={"key": "value"})
debug_log.error("Failed", category=Category.RUNNER)
debug_log.perf("Timing", category=Category.PERF, details={"ms": 150})

# Query entries
entries = debug_log.query(Category.API, limit=50)
entries = debug_log.query(Category.RUNNER, level=LogLevel.ERROR)

# Get buffer stats
stats = debug_log.get_buffer_stats()  # {"api": {"count": 42, "maxsize": 500}, ...}

# Enable category for file logging
debug_log.enable_category(Category.API)
```

**Server Identity:**

At startup, the server captures:
- Git commit (full and short hash)
- Git branch
- Dirty status (uncommitted changes)
- Diff hash (fingerprint of local changes)
- Slot (A or B), port, PID, start time

Query identity:
```json
{"name": "debug_log_config", "args": {"action": "identity"}}
```

Or via WebSocket:
```typescript
const identity = await client.debugLog.getServerIdentity();
// { gitCommit: "abc123...", gitBranch: "main", gitDirty: true, ... }
```

**Lifecycle Events:**

Server start/stop events are logged to the `lifecycle` category:
- `server_started` - with git identity, slot, port
- `server_stopping` - with reason and uptime
