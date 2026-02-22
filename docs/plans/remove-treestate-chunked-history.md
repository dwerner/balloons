# Plan: Remove TreeState & Implement Chunked History Loading

**Status**: In Progress (Phase 5 Complete)
**Created**: 2025-02-22
**Last Updated**: 2025-02-22

IMPORTANT: if you are implementing this, remember to update the file with progress and decisions made.

## Dev Environment Notes

- Project uses `.venv` in project root (`/home/dan/Development/balloons/.venv`)
- To build Rust Python module: `/path/to/.venv/bin/maturin develop --release` (from project root)
- Run tests with `uv run pytest`
- **Warning**: If `balloons_storage.so` exists in project root, it shadows the venv package. Delete it if rebuilding.
- **Warning**: If `.venv` exists in `balloons-rs/crates/balloons-py/`, maturin installs there instead. Delete it.

## Problem Statement

The current architecture has several issues:

1. **TreeState is a redundant cache layer** - Historical turn data is loaded from LMDB into TreeState's in-memory `sessions[id].turns` list, then served to clients. This duplicates data already in storage.

2. **All-or-nothing history loading** - `get_session_snapshot()` returns ALL turns at once, blocking initial render and causing memory pressure for large sessions.

3. **Race condition window** - Snapshot is generated before subscription is registered, potentially missing events that occur during the gap.

4. **Context modes stored twice** - Per-turn `context_mode` is already in LMDB (`TurnData.context_mode`), but TreeState maintains a redundant `_context_modes` dict.

## Goals

1. **Eliminate TreeState** as an in-memory cache
2. **Chunked history loading** - Progressive rendering as chunks arrive
3. **Direct LMDB access** - Services query storage directly
4. **Unified merge model** - Historical chunks and streaming events merge by `turn_id`

## Architecture: Current vs. Target

### Current (Redundant Caching)

```
LMDB → Session.load() → TreeState.load_session() → TreeStateService → Client
                              ↑
                   In-memory copy of turns
```

### Target (Direct Storage)

```
┌────────────────────────────────────────────────────┐
│              SessionDataService                     │
│  (subscriptions, streaming events, history chunks) │
└────────────────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
 ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
 │  Runtime    │  │   LMDB      │  │   LMDB      │
 │   State     │  │  Sessions   │  │   Turns     │
 │ (streaming, │  │ (metadata)  │  │ (content +  │
 │  current)   │  │             │  │ context_mode│
 └─────────────┘  └─────────────┘  └─────────────┘
```

## Key Insight: What's Already in LMDB

Context modes ARE already persisted per-turn:

- **Rust `TurnData`**: `context_mode: String`
- **Python `Turn`**: `context_mode: ContextMode`
- **async_storage.py**: Saves (line 553) and loads (lines 757-761)

TreeState's `_context_modes: dict[tuple[str, int], ContextMode]` is redundant.

## TreeState Inventory: What to Relocate

| TreeState Responsibility | Alternative |
|--------------------------|-------------|
| `_sessions: dict[str, SessionData]` | Query LMDB metadata directly |
| `_context_modes: dict` | **Already in LMDB per-turn** |
| `_merge_modes: dict` | Add to LMDB (session metadata or new table) |
| `_current_session_id: str` | Client state (UI concern) |
| `_session_history: list[str]` | **Already in LMDB** |
| `_streaming_sessions: set[str]` | SessionManagerService (runtime) |
| `_pinned_sessions: set[str]` | **Already in UserPrefs LMDB** |
| `_session_colors: dict[str, str]` | Client-derived on load |
| Observer notifications | Services emit WebSocket events |

---

## Implementation Phases

### Phase 1: Storage Layer - Range Queries

**Goal**: Add pagination support to LMDB storage

#### Rust Changes (`balloons-rs/crates/balloons-core/src/storage/`)

**traits.rs** - Add new methods:
```rust
/// Get the number of turns for a session
async fn get_turn_count(&self, session_id: &str) -> Result<usize>;

/// Load a range of turns (for chunked loading)
async fn load_turns_range(
    &self,
    session_id: &str,
    offset: usize,
    limit: usize,
) -> Result<Vec<TurnData>>;
```

**lmdb_engine.rs** - Implement range queries using cursor positioning

#### Python Changes (`core/async_storage.py`)

Add wrapper methods:
```python
async def get_turn_count(self, session_id: str) -> int:
    """Get number of turns without loading them."""

async def load_turns_range(
    self,
    session_id: str,
    offset: int = 0,
    limit: int = 50
) -> list[dict]:
    """Load a range of turns from storage."""
```

**Validation**: Range queries work in test harness

---

### Phase 2: New Events for Chunked History

**Goal**: Define wire protocol for incremental history loading

#### Service Events (`service/session_data_service.py`)

Add new event types:
```python
@ws_type
@dataclass
class HistoryChunkEvent:
    session_id: str
    chunk_id: str
    turns: list[TurnSnapshot]
    chunk_index: int
    total_chunks: int
    watermark: int  # Highest turn order in this chunk

@ws_type
@dataclass
class HistoryCompleteEvent:
    session_id: str
    total_turns: int
    final_watermark: int
```

Register events:
```python
@ws_event(name="sessionDataHistoryChunk")
async def on_history_chunk(self) -> HistoryChunkEvent: ...

@ws_event(name="sessionDataHistoryComplete")
async def on_history_complete(self) -> HistoryCompleteEvent: ...
```

---

### Phase 3: Chunked Loading in SessionDataService

**Goal**: Subscribe returns immediately, history streams from LMDB

#### Changes to `service/session_data_service.py`

1. Modify `subscribe_session()`:
   - Register subscription FIRST (capture concurrent streaming)
   - Return session metadata immediately (no turns)
   - Spawn async task to stream history chunks

2. Add `_stream_history_from_storage()`:
   - Load turns in chunks directly from LMDB
   - Emit `historyChunk` events
   - Emit `historyComplete` when done

3. Remove dependency on TreeState for turn data:
   - Keep TreeState reference only for session metadata (temporary)
   - Load turns from `AsyncStorage` directly

**Validation**: UI receives chunk events, renders progressively

---

### Phase 4: Client-Side Merge Logic

**Goal**: React UI handles chunked + streaming merge

#### Changes to `web/ui/src/hooks/useSessionData.ts`

1. Add state for history loading:
```typescript
const [isLoadingHistory, setIsLoadingHistory] = useState(false);
const [historyWatermark, setHistoryWatermark] = useState(-1);
```

2. Handle `historyChunk` events:
   - Merge turns by `turn_id` (idempotent)
   - Use server-provided `order` for sorting
   - Don't overwrite streaming turns with historical

3. Handle `historyComplete`:
   - Set `isLoadingHistory = false`
   - Gap detection: compare watermark with streaming

**Key insight**: Client already uses `Map<turn_id, Turn>` with `order` field - out-of-order merge already works!

**Validation**: Streaming + history merge correctly

---

### Phase 5: Extract Runtime State from TreeState

**Goal**: Identify and relocate non-storage state

#### Runtime State Relocation

| State | New Location |
|-------|--------------|
| `_streaming_sessions` | SessionManagerService (already tracks this) |
| `_current_session_id` | Client state (per-connection) |
| `_session_colors` | Client-derived (hash of session ID) |
| `_merge_modes` | Add to LMDB |

#### Merge Modes Storage

Option A: Add to SessionData
```rust
pub merge_modes: HashMap<String, String>,  // fork_session_id -> mode
```

Option B: New table (if we need history/versioning)
```rust
pub struct MergeModeData {
    parent_session_id: String,
    fork_session_id: String,
    mode: String,
}
```

---

### Phase 6: TreeStateService → Direct Storage

**Goal**: TreeStateService queries LMDB directly

#### Changes to `service/tree_state_service.py`

1. Replace TreeState dependency with AsyncStorage:
```python
def __init__(self, storage: AsyncStorage, ...):
    self._storage = storage
    # Remove: self._state = tree_state
```

2. Rewrite methods to query storage:
   - `get_session()` → `storage.load_session()`
   - `get_all_sessions()` → `storage.list_sessions()`
   - `get_turns()` → `storage.load_turns_range()` with chunked events

3. Context modes read from turns:
   - No separate tracking needed
   - `set_context_mode()` updates turn in LMDB directly

**Validation**: TreeStateService works without TreeState

---

### Phase 7: Eliminate TreeState Class

**Goal**: Remove `core/tree_state.py` entirely

1. Update all imports:
   - `service/session_manager_service.py`
   - `service/session_data_service.py`
   - `service/tree_state_service.py`
   - TUI widgets if still using TreeState

2. Delete `core/tree_state.py`

3. Update tests:
   - `tests/test_tree_state.py` → delete or migrate to service tests
   - Update fixtures that create TreeState instances

**Validation**: TreeState deleted, all tests pass

---

### Phase 8: TUI Migration (if needed)

**Goal**: TUI context tree uses same chunked pattern

If TUI still exists:
- Create `TUIStateManager` for runtime-only state (current session, view state)
- Wire to TreeStateService events

---

## Testing Strategy

### Unit Tests
- Storage range queries (Rust + Python)
- Chunk event serialization
- Merge logic (duplicate handling, ordering)

### Integration Tests
- Subscribe → chunk events → complete flow
- Interleaved streaming + history
- Reconnection with partial history

### Performance Tests
- Large session chunking (1000+ turns)
- Memory usage during chunked load
- Concurrent subscribers

---

## Files Changed Summary

**New/Modified:**
- `balloons-rs/.../storage/traits.rs` - Range query methods
- `balloons-rs/.../storage/lmdb_engine.rs` - Range query implementation
- `core/async_storage.py` - Python wrappers
- `service/session_data_service.py` - Chunked loading
- `service/tree_state_service.py` - Direct storage access
- `web/ui/src/hooks/useSessionData.ts` - Chunk handling

**Deleted:**
- `core/tree_state.py`
- `tests/test_tree_state.py` (or migrated)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking TUI | TUI may need parallel migration or temporary shim |
| Performance regression | Benchmark before/after, optimize LMDB range queries |
| Event ordering edge cases | Comprehensive tests for interleaved scenarios |
| Context mode sync | Ensure writes propagate to all subscribers |

---

## Open Questions

1. **Merge modes storage**: Session metadata vs. new table?
2. **TUI timeline**: Migrate simultaneously or defer?
3. **Chunk size**: Configurable? Default 50 turns?
4. **Priority loading**: Load recent chunks first (reverse order)?

---

## Lessons Learned

### Don't Break the App Between Phases

**Issue**: Between Phase 3 and Phase 4, there was a gap where the chat log was broken. Phase 3 changed the server to emit chunked history events, but the client (Phase 4) wasn't updated yet to handle them.

**Lesson**: When splitting work across server/client boundaries:

1. **Implement both sides together** when possible, or
2. **Add feature flags** so old behavior continues until new client is ready, or
3. **Make new behavior additive** - keep old snapshot behavior working while adding chunked events alongside

**For future phases**: If a phase changes the wire protocol or event flow, ensure the client can still function with the old behavior until the next phase lands. Consider:
- Dual-emit: Send both old events AND new events during transition
- Version negotiation: Client indicates which protocol version it supports
- Graceful degradation: New events are optional enhancements, not required

---

## Progress Log

| Date | Phase | Notes |
|------|-------|-------|
| 2025-02-22 | Planning | Initial plan documented |
| 2025-02-22 | Phase 1 | ✅ Added `get_turn_count()` and `load_turns_range()` to Rust traits, LMDB engine, StorageClient, PyO3 bindings, and Python async_storage.py |
| 2025-02-22 | Phase 2 | ✅ Added `SessionHistoryChunkEvent` and `SessionHistoryCompleteEvent` types with `@ws_event` decorators. Added `emit_history_chunk()` and `emit_history_complete()` helper methods. Regenerated TypeScript types. |
| 2025-02-22 | Phase 3 | ✅ Implemented chunked history loading in SessionDataService. Key changes: (1) `subscribe_session()` now registers subscription FIRST, returns metadata-only snapshot, spawns background task for history streaming. (2) Added `_stream_history_from_storage()` that loads turns via `load_turns_range()` and emits chunk/complete events. (3) Added `_turn_dict_to_snapshot()` and `_deserialize_content_block()` for LMDB → TurnSnapshot conversion. (4) Wired up AsyncStorage in headless.py and app.py. (5) Added comprehensive tests for chunked loading. |
| 2025-02-22 | Phase 4 | ✅ Implemented client-side merge logic in useSessionData.ts. Key changes: (1) Added `isLoadingHistory` and `historyWatermark` state for tracking history loading progress. (2) Added handler for `sessionDataHistoryChunk` events that merges historical turns by turn_id (without overwriting streaming turns). (3) Added handler for `sessionDataHistoryComplete` to finalize history loading. (4) Added `order` field to `TurnSnapshot` for client-side sorting. (5) Regenerated TypeScript types. This fixes the broken chat log from Phase 3. |
| 2025-02-22 | Phase 5 | ✅ Extracted runtime state from TreeState. Analysis: (1) `_streaming_sessions` → Already tracked in SessionManagerService via `_streaming_contexts`. (2) `_current_session_id` → Already client state (`selectedSessionId` prop in React). (3) `_session_colors` → Already client-derived (`SESSION_COLORS[index % len]` in SessionTreeView.tsx). (4) `_merge_modes` → Added persistence via session children. Changes: Updated `TreeState.load_session()` to read `context_mode` from children dict entries. Updated `TreeState.set_merge_mode()` to write `context_mode` back to session children and mark dirty for save. Added 2 new tests for merge mode persistence. |
