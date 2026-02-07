# Delete Turns from Conversations

## Goal
Add the ability to delete turns from conversations, with debug logging.

## User Interaction
- In the context tree, select a turn node
- Press `d` or `Delete` key to delete the turn
- Turn is removed from session history and both the tree and chat log update

## Implementation

### 1. Add `TurnDeleteRequested` message in `widgets/context_tree.py`

```python
class TurnDeleteRequested(Message):
    """Posted when user requests to delete a turn."""
    def __init__(self, session_id: str, turn_index: int) -> None:
        self.session_id = session_id
        self.turn_index = turn_index
        super().__init__()
```

### 2. Handle `d`/`Delete` key in `SelectableTree.key_d()` and `key_delete()`

In `SelectableTree`, add key handlers that:
1. Check if the selected node is a turn node (not session, fork, or merge)
2. Extract session_id and turn_index from the node data
3. Post `TurnDeleteRequested` message

### 3. Add `delete_turn()` method to `Session` in `core/session.py`

```python
def delete_turn(self, turn_index: int) -> bool:
    """Delete a turn from the session history.

    Returns True if deleted, False if index invalid.
    """
    if 0 <= turn_index < len(self.history):
        del self.history[turn_index]
        return True
    return False
```

### 4. Handle `TurnDeleteRequested` in `app.py`

In `BalloonApp`, add handler:

```python
@on(TurnDeleteRequested)
def handle_turn_delete(self, event: TurnDeleteRequested) -> None:
    session = self.session_manager.get_session(event.session_id)
    if session and session.delete_turn(event.turn_index):
        # Log the deletion
        debug_log.info(
            f"Deleted turn {event.turn_index} from session",
            session_id=event.session_id,
            category="event",
            details={"turn_index": event.turn_index}
        )
        # Save and refresh UI
        self.session_manager.save_session(session)
        self._refresh_context_tree()
        if self.current_session and self.current_session.id == event.session_id:
            self._refresh_chat_log()
```

### 5. Debug logging

Log the deletion using `debug_log()` from `balloons.debug`:

```python
from balloons.debug import debug_log

# In the delete handler:
debug_log("turn_deleted", session_id=event.session_id, turn_index=event.turn_index)
```

This follows the existing pattern used throughout the codebase (e.g., `debug_log("session_saved", ...)`).

## Files to Modify

1. `widgets/context_tree.py` - Add message class and key handlers
2. `core/session.py` - Add `delete_turn()` method
3. `app.py` - Add message handler

## Edge Cases

- Cannot delete turns from merged (read-only) forks
- Deleting a turn that a fork was based on - the fork's `fork_point_turn` may become invalid
  - For now, allow deletion and let fork point be stale (fork still has its own history)
- Empty session after deleting last turn - allowed, session just has no history
