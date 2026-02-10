# @ws_expose Annotation Design

## Overview

The `@ws_expose` annotation system marks Python methods and types for WebSocket exposure,
enabling automatic codegen for TypeScript and Rust clients. This extends the existing
`@rust_schema` pattern to support bidirectional real-time communication.

## Design Goals

1. **Single source of truth**: Python defines the API contract
2. **Type safety**: Generated TypeScript/Rust types match Python signatures
3. **Minimal boilerplate**: Decorators capture intent, codegen handles wire format
4. **Bidirectional**: Support both RPC (request/response) and events (server push)

## Annotation Types

### 1. `@ws_expose` - Method Exposure

Marks a method as callable via WebSocket RPC.

```python
from ws_expose import ws_expose, ws_event

class TreeStateService:
    """WebSocket-exposed service for tree state management."""

    @ws_expose
    async def get_session(self, session_id: str) -> SessionData | None:
        """Get session by ID."""
        return self._state.get_session(session_id)

    @ws_expose
    async def set_context_mode(
        self,
        session_id: str,
        turn_idx: int,
        mode: ContextMode
    ) -> None:
        """Set context mode for a turn."""
        self._state.set_context_mode(session_id, turn_idx, mode)
```

**Generated TypeScript:**
```typescript
interface TreeStateService {
  getSession(sessionId: string): Promise<SessionData | null>;
  setContextMode(sessionId: string, turnIdx: number, mode: ContextMode): Promise<void>;
}
```

**Generated Rust:**
```rust
#[async_trait]
pub trait TreeStateService {
    async fn get_session(&self, session_id: String) -> Option<SessionData>;
    async fn set_context_mode(&self, session_id: String, turn_idx: i64, mode: ContextMode);
}
```

### 2. `@ws_event` - Event/Subscription Exposure

Marks a method that emits events to subscribers.

```python
class TreeStateService:
    @ws_event
    async def on_session_updated(self) -> SessionData:
        """Emitted when a session is updated."""
        ...

    @ws_event("tree.*")  # Wildcard pattern for multiple events
    async def on_tree_event(self) -> TreeEvent:
        """Emitted for any tree state change."""
        ...
```

**Generated TypeScript:**
```typescript
interface TreeStateEvents {
  onSessionUpdated(callback: (data: SessionData) => void): Unsubscribe;
  onTreeEvent(callback: (data: TreeEvent) => void): Unsubscribe;
}
```

### 3. `@ws_type` - Type Registration

Marks types that should be exposed in the WebSocket API (extends `@rust_schema`).

```python
from ws_expose import ws_type

@ws_type
@dataclass
class TreeEvent:
    """Event data for tree state changes."""
    event_type: str  # "session_added", "turn_updated", etc.
    session_id: str
    turn_idx: int | None = None
    data: dict = field(default_factory=dict)
```

This generates:
- Rust struct (via existing `@rust_schema` pipeline)
- TypeScript interface
- JSON schema for validation

## Wire Protocol

### Request Format (Client → Server)

```json
{
  "id": "uuid",           // Request ID for correlation
  "method": "getSession", // Method name (camelCase)
  "params": {             // Method parameters
    "sessionId": "abc123"
  }
}
```

### Response Format (Server → Client)

```json
{
  "id": "uuid",           // Matches request ID
  "result": {...}         // Method return value (on success)
}
```

Or on error:
```json
{
  "id": "uuid",
  "error": {
    "code": -32600,
    "message": "Invalid params"
  }
}
```

### Event Format (Server → Client)

```json
{
  "event": "sessionUpdated",  // Event name (camelCase)
  "data": {...}               // Event payload
}
```

## Decorator Implementation

### Basic Structure

```python
from dataclasses import dataclass, field
from typing import Callable, TypeVar, get_type_hints
from functools import wraps

# Registry for exposed methods and types
class WsExposeRegistry:
    _methods: dict[str, "MethodSpec"] = {}
    _events: dict[str, "EventSpec"] = {}
    _types: list[type] = []

    @classmethod
    def register_method(cls, method: Callable, spec: "MethodSpec"):
        cls._methods[spec.name] = spec

    @classmethod
    def register_event(cls, event_name: str, spec: "EventSpec"):
        cls._events[event_name] = spec

    @classmethod
    def register_type(cls, type_cls: type):
        cls._types.append(type_cls)


@dataclass
class MethodSpec:
    """Specification for an exposed method."""
    name: str                    # Python method name
    wire_name: str               # camelCase for wire
    params: list["ParamSpec"]    # Parameter types
    return_type: type | None     # Return type
    docstring: str               # Method docstring
    is_async: bool = True


@dataclass
class ParamSpec:
    """Specification for a method parameter."""
    name: str                    # Python param name
    wire_name: str               # camelCase for wire
    type_hint: type              # Python type
    default: any = None          # Default value
    required: bool = True


@dataclass
class EventSpec:
    """Specification for an exposed event."""
    name: str                    # Python event name
    wire_name: str               # camelCase for wire
    payload_type: type           # Event payload type
    pattern: str | None = None   # Optional wildcard pattern
```

### Decorator Functions

```python
def ws_expose(method: Callable = None, *, name: str = None):
    """Mark a method as WebSocket-exposed.

    Args:
        method: The method to expose
        name: Override the wire name (defaults to camelCase of method name)
    """
    def decorator(fn: Callable) -> Callable:
        hints = get_type_hints(fn)
        params = []

        for param_name, param_type in hints.items():
            if param_name == "return":
                continue
            params.append(ParamSpec(
                name=param_name,
                wire_name=to_camel_case(param_name),
                type_hint=param_type,
            ))

        spec = MethodSpec(
            name=fn.__name__,
            wire_name=name or to_camel_case(fn.__name__),
            params=params,
            return_type=hints.get("return"),
            docstring=fn.__doc__ or "",
            is_async=asyncio.iscoroutinefunction(fn),
        )

        WsExposeRegistry.register_method(fn, spec)

        # Add metadata to function for runtime introspection
        fn._ws_spec = spec
        return fn

    if method is not None:
        return decorator(method)
    return decorator


def ws_event(pattern_or_fn=None):
    """Mark a method as emitting WebSocket events.

    Can be used as:
        @ws_event
        async def on_session_updated(self) -> SessionData: ...

        @ws_event("tree.*")
        async def on_tree_event(self) -> TreeEvent: ...
    """
    def decorator(fn: Callable, pattern: str = None) -> Callable:
        hints = get_type_hints(fn)

        spec = EventSpec(
            name=fn.__name__,
            wire_name=to_camel_case(fn.__name__),
            payload_type=hints.get("return"),
            pattern=pattern,
        )

        WsExposeRegistry.register_event(spec.wire_name, spec)
        fn._ws_event_spec = spec
        return fn

    if callable(pattern_or_fn):
        return decorator(pattern_or_fn)
    return lambda fn: decorator(fn, pattern_or_fn)


def ws_type(cls: type) -> type:
    """Mark a type for WebSocket API exposure.

    This extends @rust_schema to also generate TypeScript types.
    """
    # Register for Rust codegen
    from codegen import rust_schema
    cls = rust_schema(cls)

    # Also register for TypeScript codegen
    WsExposeRegistry.register_type(cls)
    return cls
```

## Code Generation

### TypeScript Generator

```python
def generate_typescript(output_path: Path):
    """Generate TypeScript types and client from registry."""

    # 1. Generate type interfaces
    types_ts = []
    for type_cls in WsExposeRegistry._types:
        types_ts.append(generate_ts_interface(type_cls))

    # 2. Generate service interface
    methods = []
    for spec in WsExposeRegistry._methods.values():
        params = ", ".join(
            f"{p.wire_name}: {python_to_ts_type(p.type_hint)}"
            for p in spec.params
        )
        return_type = python_to_ts_type(spec.return_type)
        methods.append(f"  {spec.wire_name}({params}): Promise<{return_type}>;")

    # 3. Generate event subscriptions
    events = []
    for spec in WsExposeRegistry._events.values():
        payload_type = python_to_ts_type(spec.payload_type)
        events.append(
            f"  {spec.wire_name}(callback: (data: {payload_type}) => void): Unsubscribe;"
        )

    # 4. Combine into output
    output = f"""// AUTO-GENERATED - DO NOT EDIT
// Generated from Python @ws_expose decorators

{chr(10).join(types_ts)}

export interface BalloonsService {{
{chr(10).join(methods)}
}}

export interface BalloonsEvents {{
{chr(10).join(events)}
}}

export type Unsubscribe = () => void;
"""
    output_path.write_text(output)
```

## Service Implementation Pattern

The exposed service wraps the underlying state manager:

```python
class TreeStateService:
    """WebSocket-exposed service wrapping TreeState."""

    def __init__(self, tree_state: TreeState):
        self._state = tree_state
        self._subscribers: dict[str, list[Callable]] = {}

        # Wire up TreeState observer to emit events
        tree_state.add_observer(self._on_tree_event)

    def _on_tree_event(self, event: TreeEvent, data: dict):
        """Convert TreeState events to WebSocket events."""
        # Map TreeEvent enum to wire event name
        event_name = f"tree.{event.value}"  # e.g., "tree.session_updated"
        self._emit(event_name, data)

    def _emit(self, event_name: str, data: dict):
        """Emit event to all subscribers."""
        for callback in self._subscribers.get(event_name, []):
            callback(data)

    # --- Exposed Methods ---

    @ws_expose
    async def get_session(self, session_id: str) -> SessionData | None:
        return self._state.get_session(session_id)

    @ws_expose
    async def get_all_sessions(self) -> dict[str, SessionData]:
        return self._state.get_all_sessions()

    @ws_expose
    async def set_context_mode(
        self,
        session_id: str,
        turn_idx: int,
        mode: str  # "copy", "compress", "drop"
    ) -> None:
        context_mode = ContextMode(mode)
        self._state.set_context_mode(session_id, turn_idx, context_mode)

    @ws_expose
    async def toggle_context_mode(
        self,
        session_id: str,
        turn_idx: int
    ) -> str:
        """Toggle context mode and return new mode."""
        new_mode = self._state.toggle_context_mode(session_id, turn_idx)
        return new_mode.value

    # --- Events ---

    @ws_event("tree.*")
    async def on_tree_event(self) -> dict:
        """All tree state change events."""
        ...
```

## File Organization

```
balloons/
├── codegen/
│   ├── __init__.py           # Exports rust_schema, ws_expose
│   ├── rust_schema.py        # Existing Rust codegen
│   ├── ws_expose.py          # NEW: @ws_expose decorator and registry
│   ├── generate_rust.py      # Existing Rust generator
│   └── generate_typescript.py # NEW: TypeScript generator
├── service/
│   ├── __init__.py
│   ├── tree_state_service.py # NEW: WebSocket wrapper for TreeState
│   ├── goal_service.py       # NEW: WebSocket wrapper for GoalTreeState
│   └── ws_server.py          # NEW: WebSocket server implementation
└── web/
    └── generated/
        ├── types.ts           # Generated TypeScript types
        └── client.ts          # Generated TypeScript client
```

## Migration Path

1. **Phase 1**: Create `ws_expose.py` with decorators and registry
2. **Phase 2**: Create `TreeStateService` with `@ws_expose` methods
3. **Phase 3**: Add TypeScript generator to codegen pipeline
4. **Phase 4**: Create WebSocket server that dispatches to services
5. **Phase 5**: Migrate TUI to use WebSocket client (dogfooding)

## Open Questions

1. **Authentication**: How to handle session auth over WebSocket?
2. **Subscription management**: Client-side filtering vs server-side?
3. **Error handling**: Standard error codes? Structured error types?
4. **Batching**: Support for batched requests?
5. **Binary protocol**: Future optimization with MessagePack?

## Example: Full Flow

**Python (server):**
```python
@ws_expose
async def set_context_mode(self, session_id: str, turn_idx: int, mode: str) -> None:
    self._state.set_context_mode(session_id, turn_idx, ContextMode(mode))
```

**Generated TypeScript:**
```typescript
interface BalloonsService {
  setContextMode(sessionId: string, turnIdx: number, mode: string): Promise<void>;
}
```

**Generated Rust (for TUI client):**
```rust
#[async_trait]
pub trait BalloonsService {
    async fn set_context_mode(&self, session_id: String, turn_idx: i64, mode: String);
}
```

**Wire format (JSON-RPC style):**
```json
// Request
{"id": "abc", "method": "setContextMode", "params": {"sessionId": "xyz", "turnIdx": 5, "mode": "compress"}}

// Response
{"id": "abc", "result": null}

// Event (emitted as side effect)
{"event": "tree.contextModeChanged", "data": {"sessionId": "xyz", "turnIdx": 5, "mode": "compress"}}
```

---

## Implementation Status

### Completed (This Todo)

1. **`codegen/ws_expose.py`** - Decorator and registry module
   - `@ws_expose` - Mark methods for RPC exposure
   - `@ws_event` - Mark methods that emit events
   - `@ws_type` - Mark dataclasses for TypeScript generation (extends `@rust_schema`)
   - `@ws_service` - Mark classes as WebSocket services
   - `WsExposeRegistry` - Central registry for services, methods, events, types
   - Type conversion: Python → TypeScript (`python_to_ts_type`)
   - Interface generation: `generate_ts_interface`

2. **`codegen/generate_typescript.py`** - TypeScript code generator
   - Generates `web/generated/types.ts` - TypeScript interfaces
   - Generates `web/generated/client.ts` - Client classes with RPC and event methods
   - Automatic `Types.` prefixing for registered types

3. **`service/tree_state_service.py`** - First service implementation
   - Wraps `TreeState` with WebSocket-exposed methods
   - 14 methods for session/turn/context operations
   - 10 events for real-time state change notifications
   - Custom types: `SessionInfo`, `TurnInfo`, `TreeEventData`

4. **`tests/test_ws_expose.py`** - Comprehensive test suite
   - Tests for case conversion, type conversion
   - Tests for all decorators
   - Integration tests

### Next Steps (Future Todos)

1. Create WebSocket server that dispatches to services
2. Add more services (GoalService, StreamingService)
3. Migrate TUI to use WebSocket client for dogfooding
