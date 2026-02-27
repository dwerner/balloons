# Subscription Layers Refactor Plan

## Problem Statement

The current subscription architecture has several issues:

1. **`loadTurnsViaSubscription` hack**: Subscribes, collects history, immediately unsubscribes. Leaves the UI with no persistent connection for live events.

2. **Missing clientId**: `useSessionData` hook calls `subscribeSession(sessionId)` without a clientId, causing subscriptions to silently fail.

3. **All-or-nothing subscriptions**: Either you get every event (deltas, tool events, everything) or nothing. Can't efficiently subscribe to multiple sessions.

4. **Link turns don't appear**: When `link_sessions` creates a turn, the UI doesn't see it because there's no active subscription receiving the `turnFinished` event.

## Solution: Header/Body/Delta Subscription Layers

### Layer Definitions

| Layer | Events | Use Case |
|-------|--------|----------|
| **HEADER** | `turnCreated`, `turnCompleted`, `turnDeleted`, `streamStarted`, `streamDone`, `streamError` | Tree view - know turn counts, streaming status |
| **BODY** | `turnBody` (full content block on completion) | See completed turn content, render previews |
| **DELTA** | `turnDelta`, `toolInputDelta`, `streamProgress` | Live streaming for active session |
| **HISTORY** | Triggers `historyChunk`/`historyComplete` | One-time load of existing turns |

### API Design

```python
# Add layers (creates subscription if needed)
subscribe_add(session_id: str, client_id: str, layers: list[str]) -> bool

# Remove layers (deletes subscription if empty)
subscribe_remove(session_id: str, client_id: str, layers: list[str]) -> bool

# Full unsubscribe
unsubscribe(session_id: str, client_id: str) -> bool
```

Client tracks its own subscription state. Server doesn't need query methods.

### Usage Patterns

```typescript
// Tree view - all visible sessions
sessions.forEach(s => client.subscribeAdd(s.id, clientId, ["header"]));

// User selects session - upgrade to full
client.subscribeAdd(sessionId, clientId, ["body", "delta", "history"]);

// User switches away - downgrade
client.subscribeRemove(oldSessionId, clientId, ["delta"]);
// Keeps header+body for tree preview
```

## Implementation Steps

### Phase 1: SubscriptionManager Class

Create `service/subscription_manager.py`:

```python
class Layer(Enum):
    HEADER = "header"
    BODY = "body"
    DELTA = "delta"
    HISTORY = "history"

@dataclass
class SubscriptionManager:
    """Manages client subscriptions to session event layers."""

    _subscriptions: dict[str, dict[str, set[Layer]]]  # client -> session -> layers

    async def add_layers(session_id, client_id, layers) -> bool
    def remove_layers(session_id, client_id, layers) -> bool
    def unsubscribe(session_id, client_id) -> bool
    def unsubscribe_client(client_id) -> None  # On disconnect
    def get_clients_for_layer(session_id, layer) -> set[str]  # For event routing
```

### Phase 2: Refactor SessionDataService

1. Replace `_session_subscribers` dict with `SubscriptionManager` instance
2. Add `subscribe_add` / `subscribe_remove` WebSocket-exposed methods
3. Update event emission to check layer subscriptions:
   - `emit_turn_created` → check HEADER layer
   - `emit_turn_body` → check BODY layer
   - `emit_turn_delta` → check DELTA layer

### Phase 3: New Event Types

Split current `turnFinished` into:
- `turnCompleted` (HEADER) - metadata only: turnId, tokenCount, timestamp
- `turnBody` (BODY) - full content block

Keep backward compat by emitting both during transition.

### Phase 4: Frontend Changes

1. Generate stable `clientId` on WebSocket connect (e.g., `web-client-${uuid}`)
2. Create subscription management hook or integrate into existing state
3. On session list load: `subscribeAdd` all sessions with `["header"]`
4. On session select: `subscribeAdd` with `["body", "delta", "history"]`
5. On session deselect: `subscribeRemove` with `["delta"]`
6. Remove `loadTurnsViaSubscription` hack

### Phase 5: Cleanup

1. Remove old `subscribeSession` / `unsubscribeSession` methods (or deprecate)
2. Remove `loadTurnsViaSubscription` function from App.tsx
3. Update `useSessionData` hook to use new layer-based subscriptions

## Expected Benefits

1. **Tree view scales**: HEADER-only subscriptions are cheap, can have many.
2. **Active session streams**: DELTA layer only for focused session.
3. **Link turns appear immediately**: HEADER subscription catches `turnCompleted`.
4. **Clean separation**: Clear mental model of what data flows where.
5. **Efficient switching**: Just add/remove DELTA layer when changing focus.

## Open Questions

1. Should BODY layer events include a preview field for tree rendering, or should tree use BODY content directly?
2. Do we need rate limiting for HEADER events if many sessions are active simultaneously?
3. Client-side state management approach (React context? Zustand? Hook-internal state?)

## Files to Modify

- `service/subscription_manager.py` (new)
- `service/session_data_service.py` (refactor subscriptions)
- `service/session_events.py` (add new event types)
- `web/ui/src/App.tsx` (remove hack, wire up new subscriptions)
- `web/ui/src/hooks/useSessionData.ts` (or replace with new hook)
- `codegen/` (regenerate client with new methods)
