# @ws_expose Annotation Design

The `@ws_expose` decorator system is the live mechanism behind Balloons' WebSocket API: Python services define the API contract with decorators, and codegen generates the TypeScript client and types used by the web UI.

Examples below use the early `TreeStateService`; current services (`SessionManagerService`, `SessionDataService`, `SupervisorStateService`, etc.) follow the same pattern.

## Design Goals

1. **Single source of truth**: Python defines the API contract
2. **Type safety**: Generated TypeScript types match Python signatures
3. **Minimal boilerplate**: Decorators capture intent, codegen handles wire format
4. **Bidirectional**: Support both RPC (request/response) and events (server push)

## Annotation Types

### `@ws_service` — Service registration

Marks a class as a WebSocket-exposed service. The class name becomes the client-side namespace (`client.sessionData.*`).

### `@ws_expose` — Method exposure

Marks a method as callable via WebSocket RPC. Parameter and return type hints drive codegen; wire names are camelCase.

```python
class ExampleService:
    @ws_expose
    async def set_context_mode(self, session_id: str, turn_idx: int, mode: str) -> None:
        """Set context mode for a turn."""
        ...
```

Generates:

```typescript
setContextMode(sessionId: string, turnIdx: number, mode: string): Promise<void>;
```

### `@ws_event` — Event/subscription exposure

Marks a method that emits events to subscribers. Optionally takes a wildcard pattern for grouped event names.

```python
@ws_event("tree.*")
async def on_tree_event(self) -> TreeEvent:
    """Emitted for any tree state change."""
    ...
```

Generates a subscription helper returning an `Unsubscribe`.

### `@ws_type` — Type registration

Marks dataclasses for TypeScript interface generation (extends `@rust_schema`, so the same type also flows through the Rust storage codegen).

## Wire Protocol

Request (client → server):

```json
{
  "id": "uuid",
  "method": "setContextMode",
  "params": { "sessionId": "abc123", "turnIdx": 5 }
}
```

Response (server → client):

```json
{ "id": "uuid", "result": { } }
```

Or on error:

```json
{ "id": "uuid", "error": { "code": -32600, "message": "Invalid params" } }
```

Event (server → client push):

```json
{ "event": "sessionUpdated", "data": { } }
```

## Current Implementation

- `codegen/ws_expose.py` — decorators (`@ws_service`, `@ws_expose`, `@ws_event`, `@ws_type`) and the central registry
- `codegen/generate_typescript.py` — emits `web/generated/types.ts` and `web/generated/client.ts`
- `service/*_service.py` — services using the decorators
- `service/ws_server.py` — JSON-RPC dispatch to registered methods

## Open Questions

1. **Subscription management**: more client-side filtering vs server-side?
2. **Error handling**: richer standard error codes / structured error types?
3. **Batching**: support for batched requests?
4. **Binary protocol**: future optimization with MessagePack?