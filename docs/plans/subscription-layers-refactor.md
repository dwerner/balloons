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

### Phase 1: SubscriptionManager Class ✅ COMPLETE

Created `service/subscription_manager.py` with:
- `Layer` enum: HEADER, BODY, DELTA, HISTORY
- `SubscriptionManager` class with full test coverage (28 tests)
- Methods: `add_layers`, `remove_layers`, `unsubscribe`, `unsubscribe_client`, `get_clients_for_layer`

### Phase 2: Refactor SessionDataService ✅ COMPLETE

1. ✅ Added `SubscriptionManager` instance alongside legacy `_session_subscribers`
2. ✅ Added `subscribe_add` / `subscribe_remove` WebSocket-exposed methods
3. ✅ Updated all event emission to check layer subscriptions:
   - `emit_turn_created` → HEADER layer
   - `emit_turn_delta` → DELTA layer
   - `emit_turn_finished` → HEADER + BODY layers
   - `on_stream_started/done/error` → HEADER layer
   - `on_stream_progress` → DELTA layer
   - `on_tool_*` events → DELTA layer
4. ✅ Updated `client_disconnected` to clean up both legacy and layer subscriptions
5. ✅ Added 12 new integration tests for layer-based subscriptions

**Backward compatibility**: Both legacy `_session_subscribers` and layer-based subscriptions work together. Events are sent to the union of both subscriber sets.

### Phase 3: New Event Types (DEFERRED)

Split current `turnFinished` into:
- `turnCompleted` (HEADER) - metadata only: turnId, tokenCount, timestamp
- `turnBody` (BODY) - full content block

Keep backward compat by emitting both during transition.

**Note**: This is optional optimization. Current implementation sends full turnFinished to both HEADER and BODY subscribers.

### Phase 4: Frontend Changes ✅ COMPLETE

1. ✅ Generate stable `clientId` on WebSocket connect
   - Added `clientIdRef` with format `web-client-${Date.now()}-${random}`
2. ✅ Created `loadSessionWithLayers()` function
   - Uses new `subscribeAdd` API with configurable layers
   - Keeps subscription active (unlike old `loadTurnsViaSubscription`)
3. ✅ Updated all call sites to use new API:
   - Initial session load: full layers (header, body, delta, history)
   - Session selection: full layers
   - Tree view lazy load: header, body, history (no delta - efficient)
   - Reload after task/archive/delete/link: history only (already subscribed)

**Key insight**: Different scenarios need different layer combinations:
- Active session viewing: all layers (header, body, delta, history)
- Tree view preview: header + body + history (no expensive delta streaming)
- Refresh existing session: history only (already have other subscriptions)

### Phase 5: Cleanup ✅ COMPLETE

1. ✅ Deprecate old `subscribeSession` / `unsubscribeSession` methods (kept for backward compat)
2. ✅ Remove `loadTurnsViaSubscription` function from App.tsx
3. ✅ Update `useSessionData` hook to use new layer-based subscriptions
   - Added optional `clientId` parameter with auto-generation
   - Updated `subscribe()` to use `subscribeAdd` with full layers
   - Updated `unsubscribe()` to use `subscribeRemove`
   - Removed snapshot handling (history now arrives via events)
4. Subscription downgrade when switching sessions (FUTURE - optimization)

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
