# Plan: TreeState - Shared State Layer for Tree Views

## Goal
Extract tree state management into a framework-agnostic class that multiple tree views can observe.

## Architecture

```
┌─────────────┐     observes     ┌────────────┐
│ ContextTree │ ◄──────────────── │            │
└─────────────┘                   │ TreeState  │
                                  │  (Model)   │
┌─────────────────────┐           │            │
│ NestedSessionTree   │ ◄──────── └────────────┘
└─────────────────────┘
```

**TreeState** (Model):
- Pure Python, no Textual dependencies
- Holds: sessions, loaded_sessions, context_modes, streaming_sessions, current_session_id
- Methods: start_turn(), finish_turn(), load_session(), toggle_context_mode(), etc.
- Observer pattern: callbacks registered, notified on changes

**Views** (ContextTree, NestedSessionTree):
- Subscribe to TreeState
- Render state changes into Textual tree nodes
- Each view renders differently but from same data

## Implementation Steps

1. [x] Create `core/tree_state.py` with TreeState class
2. [x] Implement observer pattern (add_observer, remove_observer, _notify)
3. [x] Implement state methods (session, turn, context mode, streaming)
4. [x] Write unit tests (29 tests in tests/test_tree_state.py)
5. [x] Refactor ContextTree to use TreeState (Phase 1 - integration)
6. [x] Connect data flow: populate TreeState, sync context modes (Phase 2)
7. [x] Implement NestedSessionTree using TreeState (Phase 3 - pure observer)
8. [x] Add UI toggle to switch between tree views (Ctrl+N)

## Current Status: Complete - Both Trees Working

### What's Done

**TreeState (`core/tree_state.py`)**:
- `SessionData` and `TurnData` dataclasses
- `TreeEvent` enum for 13 event types
- Observer pattern (add_observer, remove_observer, _notify)
- Session operations (add, remove, set_current, load)
- Turn operations (start, update, finish)
- Tool use tracking
- Context mode management
- Streaming state
- 29 unit tests passing

**ContextTree Integration (Dual-Write Pattern)**:
- Accepts optional `TreeState` in constructor
- Registers as observer on mount, unregisters on unmount
- Handles `STREAMING_STARTED/STOPPED` events via observer
- Handles `SESSION_SELECTED` event via observer
- Exposes `state` property for external access
- Still maintains local state for full functionality

**NestedSessionTree (Pure Observer Pattern)**:
- Requires `TreeState` in constructor (not optional)
- ALL state comes from TreeState - no local state duplication
- Handles ALL TreeEvent types via observer:
  - `SESSION_ADDED/REMOVED` → rebuild tree
  - `SESSION_LOADED` → populate turns
  - `SESSION_SELECTED` → update labels
  - `TURN_STARTED/FINISHED` → streaming turn UI
  - `CONTEXT_MODE_CHANGED` → update labels
  - `STREAMING_STARTED/STOPPED` → update indicators
  - `FULL_REBUILD` → rebuild entire tree
- Nested structure: forks appear inline under parent sessions
- Only stores node references locally (Textual-specific)

**App Integration**:
- Creates shared `TreeState` instance (`self._tree_state`)
- Passes it to both `ContextTree` and `NestedSessionTree`
- Calls `start_streaming()` and `stop_streaming()` on TreeState
- `Ctrl+T` toggles tree sidebar visibility
- `Ctrl+N` switches between flat and nested tree views
- All tree events handled for both views

### How to Use

**Keyboard shortcuts:**
- `Ctrl+T` - Toggle tree sidebar on/off
- `Ctrl+N` - Switch between flat (ContextTree) and nested (NestedSessionTree) views

**Behavior:**
- Both trees share the same TreeState
- When you toggle context mode in one tree, both update automatically
- Streaming indicators sync across both views
- Session switching works from either tree

### Two Implementation Patterns

**1. ContextTree - Dual-Write Pattern**:
- Updates both local state AND TreeState on every operation
- Most observer handlers disabled to avoid duplicate work
- Safe for migration - can verify TreeState correctness

**2. NestedSessionTree - Pure Observer Pattern**:
- TreeState is the ONLY source of truth
- ALL UI updates happen in response to TreeEvent notifications
- Reference implementation for how views should work

### Next Steps (Future)

1. **Remove duplicate state from ContextTree**:
   - Remove `_sessions`, `_loaded_sessions`, `_context_modes`, `_merge_modes`
   - Read all state from TreeState instead
   - Enable all observer handlers
   - Follow NestedSessionTree as the reference

2. **Have app call TreeState directly for turn operations**:
   - Instead of `context_tree.start_turn()`, call `tree_state.start_turn()`
   - Both trees react purely via observer

## Files Modified

- `core/tree_state.py` - TreeState class (570 lines)
- `tests/test_tree_state.py` - 29 unit tests
- `widgets/context_tree.py` - TreeState integration (dual-write)
- `widgets/nested_tree.py` - Pure observer implementation (~860 lines)
- `widgets/__init__.py` - Export NestedSessionTree
- `app.py` - Creates shared TreeState, Ctrl+N toggle, event handlers
