# Plan: Remove TreeState & Implement Chunked History Loading

**Status**: Substantially Complete - TUI Deleted, TreeState Minimized
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

### Phase 7: TreeState Audit & Scope Revision ⚠️

**Original Goal**: Remove `core/tree_state.py` entirely

**Revised Goal**: Audit remaining dependencies, document, revise scope

#### Audit Results

TreeState is used for two distinct purposes:

**A. Data Caching (Eliminated by Phase 6)** ✅
- Turn data queries → Now use LMDB directly via AsyncStorage
- Context mode queries → Now read from turn storage
- Session metadata → Could use LMDB but still uses TreeState

**B. Observer/Event Pattern (Still Required)** ❌
- TreeStateService subscribes to TreeState events → Converts to WebSocket events
- TUI widgets (NestedTreeView, ContextTreeView, GoalTreeView) → Pure observers
- SessionManagerService → Emits events during streaming

#### Remaining TreeState Dependencies

| Component | Usage | Can Eliminate? |
|-----------|-------|----------------|
| `SessionManagerService._tree_state` | Owns TreeState; calls `start_turn()`, `update_turn_content()`, `stop_streaming()`, `load_session()` during streaming | No - needs event emitter |
| `TreeStateService._state` | Subscribes to TreeState events → WebSocket events | No - needs event source |
| `SessionDataService._tree_state` | Uses `get_session()` for metadata in snapshots | Maybe - could use LMDB |
| `NestedTreeView` (TUI) | Pure observer of TreeState | No - needs event source |
| `ContextTreeView` (TUI) | Pure observer of TreeState | No - needs event source |
| `GoalTreeView` (TUI) | Observer for session data | No - needs event source |
| `headless.py` | Creates TreeState, loads sessions | No - needed for events |
| `app.py` | Creates TreeState, loads sessions | No - needed for TUI |

#### Why Deletion Is Not Feasible Now

1. **Observer Pattern**: TreeState implements a publish/subscribe system. WebSocket clients receive updates via:
   ```
   TreeState._notify() → TreeStateService._on_tree_event() → WebSocket event
   ```
   Deleting TreeState would break this event chain.

2. **Streaming Turn Updates**: During LLM streaming, SessionManagerService calls:
   - `self._tree_state.start_turn()` → TURN_STARTED event
   - `self._tree_state.update_turn_content()` → TURN_UPDATED event
   - `self._tree_state.stop_streaming()` → STREAMING_STOPPED event

   These events are how WebSocket clients know about streaming progress.

3. **TUI Widget Architecture**: The TUI widgets are designed as "pure observers" of TreeState. They have no local state and rely entirely on TreeState events for updates.

#### Revised Approach

**Option A: Keep TreeState as Event Bus** (Recommended for now)
- TreeState continues to serve as the event pub/sub system
- Data queries use LMDB directly (Phase 6 accomplished this)
- TreeState becomes a "thin" event bus, not a data cache

**Option B: Create New EventEmitter** (Future work)
- Create `SessionEventBus` to replace TreeState's observer pattern
- Migrate SessionManagerService to emit events directly
- Migrate TreeStateService to listen to EventBus
- Delete TreeState

**Decision**: Proceed with Option A. TreeState is already "thin" after Phase 6 (turn data is not cached, it's queried from LMDB). The remaining value is the observer pattern which works fine.

#### Phase 7 Completed Items

1. ✅ Audited all TreeState imports and usages
2. ✅ Documented why deletion is not feasible
3. ✅ Identified TreeState's remaining role (event bus only)
4. ✅ Updated plan with realistic scope

**Validation**: Audit complete, plan updated

---

### Phase 8: TUI Migration (Deferred)

**Status**: Deferred indefinitely

**Original Goal**: TUI context tree uses same chunked pattern

**Reason for Deferral**: The TUI widgets work correctly with TreeState's observer pattern. Since we're keeping TreeState as an event bus (Phase 7 decision), TUI migration is not needed for the chunked history feature to work.

If TUI performance becomes an issue with large sessions, consider:
- TUI widgets could subscribe to SessionDataService WebSocket events instead of TreeState
- This would unify headless and TUI code paths

For now, the current architecture is acceptable:
- Headless: SessionDataService → WebSocket → React UI (chunked history)
- TUI: TreeState observer → Widget updates (full history in memory)
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
| 2025-02-22 | Phase 6 | ✅ TreeStateService queries LMDB directly. Key changes: (1) Added optional `storage: AsyncStorage` parameter to `TreeStateService.__init__()`. (2) Added `_turn_dict_to_info()` helper to convert storage turn dicts to `TurnInfo` for wire protocol. (3) `get_turns()` now loads from `storage.load_turns()` directly when storage is available (falls back to TreeState cache). (4) `get_turn()` now uses `storage.load_turns_range(turn_idx, 1)` when storage is available. (5) `get_context_mode()` reads from turn data in storage (context_mode field). (6) `set_context_mode()` and `toggle_context_mode()` persist changes to storage AND update TreeState for events. (7) Updated `headless.py` and `app.py` to pass AsyncStorage to TreeStateService. TreeState is still used for observer/event pattern and runtime state (streaming, current session per TUI). |
| 2025-02-22 | Phase 7 | ⚠️ REVISED - TreeState cannot be deleted yet. **Audit Results**: TreeState is deeply embedded in 3 critical areas: (1) **SessionManagerService** - owns TreeState, uses it for turn operations (`start_turn`, `update_turn_content`, `stop_streaming`, `load_session`) during streaming. (2) **TreeStateService** - uses TreeState's observer pattern to convert tree events → WebSocket events. (3) **TUI Widgets** (NestedTreeView, ContextTreeView, GoalTreeView) - pure observers of TreeState. **Decision**: Phase 7 scope reduced to audit + documentation. Full deletion requires creating an alternative event bus (EventEmitter pattern) and is deferred. |
| 2025-02-22 | Phase 7 (Revised) | ✅ **DELETED TUI ENTIRELY**. Removed: (1) `widgets/` directory (46 files, ~27K lines). (2) `app.py` (~7K lines). (3) `main.py` TUI entry point. (4) TUI-specific tests: `test_markdown_viewer.py`, `test_actionable_toast.py`, `test_tree_render.py`, `test_frame_monitor.py`, `test_scroll_controller.py`, `test_widget_registry.py`, `test_slides_pane.py`, `test_entity_pane.py`, `test_cli.py`. (5) Textual dependency from `requirements.txt`. (6) Cleaned up `test_archiver.py` (removed `TestArchiveMarkerWidget` class) and `test_slides.py` (removed `TestPresentationScreen` class). **1523 tests pass**, 14 pre-existing failures unrelated to this change. |
| 2025-02-22 | Phase 8 (Analysis) | ⏳ **TreeState deletion deferred**. Analysis shows TreeState is still needed for: (1) **TreeStateService** - session metadata queries (`get_session`, `get_all_sessions`), pinning state (`is_pinned`, `pin_session`), streaming state (`is_streaming`). (2) **GoalTreeSyncManager** - uses TreeState for session binding info. Future work: Migrate remaining TreeStateService queries to AsyncStorage. For now, TreeState remains as a thin session metadata and state manager. Turn queries already use LMDB directly (Phase 6). |

---

## Current State Summary

**What's Complete:**
- ✅ Chunked history loading (Phases 1-4): Sessions load progressively from LMDB
- ✅ Turn data queries LMDB-direct (Phase 6): TreeStateService uses AsyncStorage for turn data
- ✅ TUI deleted (Phase 7 Revised): ~35K lines of TUI code removed, headless-only mode
- ✅ SessionEventObserver pattern: Modern event delivery via WebSocket

**What Remains (TreeState):**
- TreeState is kept for session metadata (title, created, model, etc.)
- TreeState is kept for pinning and streaming state
- TreeState is kept for context token counting
- Future: Migrate remaining queries to LMDB, then delete TreeState

**Architecture (Current):**
```
SessionManagerService
    ├── SessionEventObserver → SessionDataService → WebSocket → React UI  (streaming events)
    └── TreeState → TreeStateService → WebSocket → React UI  (session metadata)
```

---

## Rescoped Plan: Kill the TUI, Delete TreeState

### Key Insight

The Phase 7 audit revealed TreeState is kept alive primarily for TUI widgets. But:

1. **SessionManagerService already has `SessionEventObserver`** - it's the event bus we need
2. **SessionDataService implements `SessionEventObserver`** - converts to WebSocket events
3. **React UI consumes WebSocket** - works great with chunked history

**The TUI is the only reason we can't delete TreeState.**

### New Approach: Delete TUI, Then Delete TreeState

The web UI is now mature enough. Rather than:
- ❌ Creating a new event bus
- ❌ Migrating TUI to SessionEventObserver
- ❌ Maintaining two rendering paths

We should:
- ✅ Delete the TUI entirely
- ✅ Delete TreeState (no longer has observers)
- ✅ One UI, one event delivery mechanism (WebSocket)

### Revised Phases 7-8

**Phase 7 (Revised)**: Delete TUI
- Remove TUI widgets (NestedTreeView, ContextTreeView, GoalTreeView, etc.)
- Remove `app.py` TUI entry point (keep headless.py)
- Remove Textual dependency
- Update any TUI-specific tests or delete them

**Phase 8 (Revised)**: Delete TreeState
- Remove TreeState from SessionManagerService
- SessionManagerService already emits to `SessionEventObserver` - just remove TreeState calls
- Remove TreeState from TreeStateService
- TreeStateService already queries LMDB (Phase 6) - just remove fallback
- Delete `core/tree_state.py`
- Delete `tests/test_tree_state.py`

### Target Architecture (Post Phase 8)

```
┌────────────────────────────────────────────────────┐
│              SessionManagerService                  │
│  (streaming context, SessionEventObserver pattern) │
└────────────────────────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────┐
│              SessionDataService                     │
│  (implements SessionEventObserver)                 │
│  (subscriptions, streaming events, history chunks) │
└────────────────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
 ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
 │  WebSocket  │  │   LMDB      │  │   LMDB      │
 │  → React UI │  │  Sessions   │  │   Turns     │
 │             │  │ (metadata)  │  │ (content +  │
 │             │  │             │  │ context_mode│
 └─────────────┘  └─────────────┘  └─────────────┘
```

**No TreeState** - SessionManagerService → SessionEventObserver → WebSocket → React UI
