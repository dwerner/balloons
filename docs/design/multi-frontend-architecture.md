# Multi-Frontend Architecture (Historical)

This document is retained as historical design context for the service-oriented split between backend services and clients.
It does not describe the current supported product surface directly.

## Still-useful ideas

The enduring value here is the architectural direction:
- services as the API boundary
- transport/client separation from orchestration logic
- generated types/clients from Python definitions

The old Textual-TUI-specific material below should be treated as superseded implementation history.

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTENDS                                       │
├─────────────────────┬─────────────────────┬─────────────────────────────────┤
│   Textual TUI       │   Web UI (React)    │   Future CLI/API               │
│   (app.py)          │   (TypeScript)      │                                │
└─────────┬───────────┴─────────┬───────────┴─────────────────┬───────────────┘
          │                     │                             │
          │  Direct Python      │  WebSocket JSON-RPC         │  HTTP/REST (future)
          │                     │                             │
┌─────────▼───────────────────────────────────────────────────▼───────────────┐
│                           SERVICE LAYER                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐           │
│  │SessionDataService│  │SessionManager    │  │GoalTreeState     │           │
│  │                  │  │Service           │  │Service           │           │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘           │
│  ┌────────┴─────────┐  ┌────────┴─────────┐  ┌────────┴─────────┐           │
│  │QueueStateService │  │TaskStateService  │  │                  │           │
│  │                  │  │                  │  │  (more services) │           │
│  └────────┬─────────┘  └────────┬─────────┘  └──────────────────┘           │
└───────────┼──────────────────────┼──────────────────────────────────────────┘
            │                      │
┌───────────▼──────────────────────▼──────────────────────────────────────────┐
│                         CORE STATE MANAGERS                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐           │
│  │ (Deleted)        │  │ SessionManager   │  │ GoalTreeState    │           │
│  │                  │  │ (core/manager.py)│  │ (core/goal_tree  │           │
│  │                  │  │                  │  │  _state.py)      │           │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘           │
│  ┌──────────────────┐  ┌──────────────────┐                                 │
│  │ QueueState       │  │ StreamState      │                                 │
│  │ (core/queue_    │  │ (core/stream_   │                                 │
│  │  state.py)       │  │  state.py)       │                                 │
│  └──────────────────┘  └──────────────────┘                                 │
└─────────────────────────────────────────────────────────────────────────────┘
            │
┌───────────▼─────────────────────────────────────────────────────────────────┐
│                           PERSISTENCE LAYER                                  │
│  ┌──────────────────┐  ┌──────────────────┐                                 │
│  │ Session          │  │ balloons_storage │                                 │
│  │ (session.py)     │  │ (Rust, via PyO3) │                                 │
│  └──────────────────┘  └──────────────────┘                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Principles

### 1. Services Are the API Boundary

All frontend interactions go through the **Service Layer**. Services:

- Wrap core state managers
- Handle serialization/deserialization
- Emit events when state changes
- Are decorated with `@ws_service`, `@ws_expose`, `@ws_event`

**Rule**: Frontends NEVER import core state managers directly. They use services.

### 2. Core State Managers Are Pure Python

Core state managers (`GoalTreeState`, `StreamState`, etc.):

- Contain domain logic
- Have no network concerns
- Use the Observer pattern to notify listeners
- Are testable in isolation

### 3. Wire Protocol Is JSON-RPC

The WebSocket server uses JSON-RPC 2.0:

```json
// Request
{"id": "uuid", "method": "getSession", "params": {"sessionId": "abc123"}}

// Response (success)
{"id": "uuid", "result": {"id": "abc123", "title": "..."}}

// Response (error)
{"id": "uuid", "error": {"code": -32600, "message": "Invalid params"}}

// Event (server push)
{"event": "sessionUpdated", "data": {"sessionId": "abc123"}}
```

### 4. TypeScript Types Are Generated

Run `python -m codegen.generate_typescript` to regenerate:

- `web/generated/types.ts` - TypeScript interfaces matching Python `@ws_type` dataclasses
- `web/generated/client.ts` - Service client classes with RPC methods and event subscriptions

## Available Services

### SessionDataService

**Purpose**: Session data events and subscription-based streaming for frontends.

| Method | Description |
|--------|-------------|
| `getAllSessionIds()` | Get all session IDs |
| `subscribe(sessionId)` | Subscribe to session events |
| `unsubscribe(sessionId)` | Unsubscribe from session |
| `setContextMode(sessionId, turnId, mode)` | Set context mode (copy/compress/drop) |
| `getExchangeSummaries(sessionId)` | Get exchange summaries |
| `requestChunkedHistory(sessionId)` | Request paginated turn history |

| Event | When Emitted |
|-------|--------------|
| `sessionAdded` | New session created |
| `sessionUpdated` | Session metadata changed |
| `sessionRemoved` | Session deleted |
| `turnStarted` | New turn streaming |
| `turnUpdated` | Turn content updated |
| `turnFinished` | Turn completed |
| `historyChunk` | Paginated history chunk delivered |
| `historyComplete` | All history chunks delivered |

### QueueStateService

**Purpose**: Message queue management for queued prompts.

| Method | Description |
|--------|-------------|
| `getQueue(sessionId)` | Get queued messages |
| `addMessage(sessionId, content)` | Add message to queue |
| `removeMessage(sessionId, messageId)` | Remove message |
| `togglePause(sessionId, messageId)` | Pause/resume message |
| `drain(sessionId)` | Get and remove messages up to pause |

| Event | When Emitted |
|-------|--------------|
| `messageAdded` | Message queued |
| `messageRemoved` | Message removed |
| `pauseToggled` | Message paused/resumed |
| `queueDrained` | Messages sent to LLM |

### SessionManagerService

**Purpose**: Session lifecycle management.

| Method | Description |
|--------|-------------|
| `createSession(workingDirectory?)` | Create new session |
| `switchSession(sessionId)` | Switch active session |
| `listSessions()` | List all sessions |
| `deleteSession(sessionId)` | Delete session |
| `getStreamingInfo(sessionId)` | Get streaming status |
| `cancelStreaming(sessionId)` | Cancel active stream |

| Event | When Emitted |
|-------|--------------|
| `sessionCreated` | New session created |
| `sessionSwitched` | Active session changed |
| `sessionDeleted` | Session removed |
| `streamingStarted` | LLM streaming began |
| `streamingStopped` | LLM streaming ended |

### GoalTreeStateService

**Purpose**: Goal/plan/todo management and session bindings.

| Method | Description |
|--------|-------------|
| `getGoal(goalId)` | Get goal info |
| `getRootGoals()` | Get top-level goals |
| `getPlansForGoal(goalId)` | Get plans under a goal |
| `getTodosForPlan(planId)` | Get todos under a plan |
| `bindSession(entityType, entityId, ...)` | Bind session to entity |
| `getStats()` | Get aggregate statistics |

| Event | When Emitted |
|-------|--------------|
| `goalAdded` | Goal created |
| `goalUpdated` | Goal modified |
| `planAdded` | Plan created |
| `todoAdded` | Todo created |
| `todoUpdated` | Todo modified |
| `sessionBound` | Session bound to entity |

### TaskStateService

**Purpose**: LLM task lifecycle tracking.

| Method | Description |
|--------|-------------|
| `getTask(taskId)` | Get task info |
| `getActiveTasks()` | Get all active tasks |
| `getStreamingTasks()` | Get tasks currently streaming |
| `getSessionTask(sessionId)` | Get active task for session |
| `getBackendSummary()` | Get tasks per backend |

| Event | When Emitted |
|-------|--------------|
| `taskStarted` | Task began |
| `taskUpdated` | Task progress updated |
| `taskCompleted` | Task finished successfully |
| `taskError` | Task failed |
| `taskCancelled` | Task cancelled by user |

## Adding a New Service

1. Create `service/my_new_service.py`:

```python
from codegen import ws_service, ws_expose, ws_event, ws_type
from dataclasses import dataclass

@ws_type
@dataclass
class MyData:
    id: str
    name: str

@ws_service
class MyNewService:
    """My new WebSocket-exposed service."""

    def __init__(self, state_manager: MyStateManager):
        self._state = state_manager
        self._event_handlers = []

    def add_event_handler(self, handler):
        self._event_handlers.append(handler)

    @ws_expose
    async def get_item(self, item_id: str) -> MyData | None:
        """Get an item by ID."""
        return self._state.get(item_id)

    @ws_event
    async def on_item_updated(self) -> MyData:
        """Emitted when an item is updated."""
        ...
```

2. Update `service/__init__.py` to export the new service.

3. Register the service with the WebSocket server (see "Server Startup" below).

4. Regenerate TypeScript types:
```bash
python -m codegen.generate_typescript
```

## Server Startup

The WebSocket server is created in `service/ws_server.py`. To start it:

```python
from service import (
    WsServer,
    SessionDataService,
    SessionManagerService,
    GoalTreeStateService,
    TaskStateService,
)
from core.manager import SessionManager
# ... etc

# Create state managers
session_manager = SessionManager(backend_config)
# ...

# Create services
session_data_service = SessionDataService(session_loader)
session_manager_service = SessionManagerService(session_manager)
# ...

# Create and start server
server = WsServer(config=ws_config)
server.register_service(session_data_service)
server.register_service(session_manager_service)
# ...

await server.start()
```

## TypeScript Client Usage

```typescript
import {
  SessionDataServiceClient,
  SessionManagerServiceClient,
} from './generated/client';

// Connect to WebSocket
const ws = new WebSocket('ws://localhost:8765');

// Create service clients
const sessionDataService = new SessionDataServiceClient(ws);
const sessionManagerService = new SessionManagerServiceClient(ws);

// RPC call
const session = await sessionDataService.getSession('abc123');
console.log(session.title);

// Event subscription
const unsubscribe = sessionDataService.onTurnUpdated((data) => {
  console.log('Turn updated:', data.turnIdx);
});

// Later: unsubscribe()
```

## Frontend-Specific Code

Each frontend needs minimal UI-specific code:

### Textual TUI (Current)

- **Widgets** in `widgets/` render session tree, turns, goals
- **app.py** wires services to widgets
- Uses direct Python service calls (no WebSocket needed for same-process)

### Web UI (Future)

- React/Vue components render the UI
- Uses generated TypeScript clients over WebSocket
- No Python knowledge needed; just consumes the service API

### Common Pattern

Both frontends should:

1. Subscribe to events for real-time updates
2. Call service methods for user actions
3. Maintain local view state derived from service data

## Security

### JWT Authentication

The WebSocket server supports JWT authentication:

```yaml
# config.yaml
websocket:
  jwt:
    enabled: true
    secret: "your-secret-key"  # or auto-generated
    expiration_seconds: 86400
```

Clients pass the token as a query parameter or subprotocol:
- `ws://localhost:8765?token=<jwt>`
- `Sec-WebSocket-Protocol: balloons.auth.<jwt>`

### TLS

For production, enable TLS:

```yaml
websocket:
  tls:
    enabled: true
    cert_path: ~/.local/share/balloons/certs/server.crt
    key_path: ~/.local/share/balloons/certs/server.key
```

Generate dev certs: `python scripts/generate_dev_certs.py`

## Next Steps

1. **Wire WebSocket server into app startup** - Start WsServer in `main.py`
2. **Create unified TypeScript client** - Single entry point combining all services
3. **Build web UI prototype** - Simple React app using the generated clients
4. **Add HTTP REST fallback** - For environments where WebSocket isn't available
