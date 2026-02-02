# Plan: Multiple Active Sessions

## Goal
Allow multiple sessions to stream simultaneously while switching between them via the context tree. The "focused" session is displayed in the chat log, but other sessions can continue streaming in the background.

## Current State Analysis

### What Already Works
1. **Background streaming infrastructure**: `poll_all()` in SessionManager polls ALL runners for events
2. **StreamingContext per session**: `_streaming_contexts` dict tracks state per streaming session
3. **Background forks**: `:fork & <prompt>` already streams in background with WithWidget status
4. **Session switching**: `_switch_to_session()` loads a session into the chat log
5. **Multiple sessions in tree**: ContextTree shows all sessions, click to switch

### Current Limitations
1. **`self.streaming` boolean**: Single flag - True if THE focused session is streaming
2. **Input disable**: Tied to `self.streaming` - can't type while ANY session streams
3. **No switch while streaming**: UI blocks switching when streaming active
4. **No visual indicator**: Tree doesn't show which sessions are currently streaming

## Design Decisions

### Q1: What does "multiple active" mean?
- Multiple sessions can stream simultaneously
- UI shows ONE session at a time (the "focused" session)
- User can switch between sessions while streams continue
- Input is only disabled if the FOCUSED session is streaming

### Q2: How to indicate background streaming?
- Tree: Show streaming indicator (spinner/pulse) on session nodes
- Status bar: Show count "N sessions streaming" when N > 0
- Keep it minimal - no tab bar for now

### Q3: Commands?
- `:switch` already exists - enhance to work while streaming
- `:new &` - create new session in background (future)
- Tree click - primary way to switch

## Implementation Plan

### Phase 1: Decouple Focused from Streaming
**Goal**: Allow switching sessions while streams continue in background.

#### Step 1.1: Rename for clarity
In `app.py`:
- Keep `self.streaming` but clarify: means "focused session is streaming"
- Add comment explaining the distinction

#### Step 1.2: Update `_switch_to_session()`
Current behavior:
- Loads new session into chat log
- Updates context tree active session
- Updates breadcrumb and request pane

New behavior:
- If OLD focused session is streaming:
  - Mark its StreamingContext as `is_active = False`
  - Continue polling via `poll_all()` - already works
- If NEW session has a StreamingContext:
  - Mark it as `is_active = True`
  - Set `self.streaming = True` and disable input
- Else (new session not streaming):
  - Set `self.streaming = False` and enable input
- Load chat history for new session
- If new session IS streaming, resume showing its stream in chat

#### Step 1.3: Update input disable logic
In `_switch_to_session()`:
```python
# Check if NEW session is streaming
new_ctx = self._streaming_contexts.get(session.id)
if new_ctx:
    new_ctx.is_active = True
    self.streaming = True
    input_box.set_disabled(True)
    status_bar.set_streaming(True)
else:
    self.streaming = False
    input_box.set_disabled(False)
    status_bar.set_streaming(False)
```

#### Step 1.4: Update event dispatching for switched sessions
When switching TO a streaming session mid-stream:
- Need to reconstruct chat display from partial content
- `StreamingContext.content` has accumulated text
- Add method `chat_log.resume_streaming(content)` to:
  1. Show history
  2. Add partial assistant message with accumulated content
  3. Continue appending via normal `append_to_current()`

### Phase 2: Tree Streaming Indicators
**Goal**: Visual feedback showing which sessions are streaming.

#### Step 2.1: Add streaming indicator to session labels
In `context_tree.py`:
- Add method `set_session_streaming(session_id, is_streaming)`
- Update `_make_session_label()` to show indicator:
  ```python
  if is_streaming:
      prefix = "[yellow blink]⟳[/] "  # Or animated if Textual supports
  ```
- Call from `app.py` when streaming starts/ends

#### Step 2.2: Update indicators on streaming events
In `app.py`:
- When `_start_streaming()`: call `context_tree.set_session_streaming(session_id, True)`
- When `_finalize_streaming()`: call `context_tree.set_session_streaming(session_id, False)`

### Phase 3: Background Streaming Count in Status Bar
**Goal**: Show "N streaming" in status bar.

#### Step 3.1: Add streaming count display
In `widgets/status_bar.py`:
- Add `_streaming_count` property
- Add `set_streaming_count(count)` method
- Display: "[yellow]2 streaming[/]" when count > 0

#### Step 3.2: Update count from app
In `app.py`:
- After any streaming start/stop, update count:
  ```python
  count = len(self._streaming_contexts)
  status_bar.set_streaming_count(count)
  ```

## Files to Modify

### Core Changes
- `app.py`:
  - Update `_switch_to_session()` to handle streaming sessions
  - Update `_start_streaming()` to update tree indicator
  - Update `_finalize_streaming()` to update tree indicator
  - Add streaming count updates

### Widget Changes
- `widgets/context_tree.py`:
  - Add `set_session_streaming()` method
  - Update `_make_session_label()` for streaming indicator
  - Track `_streaming_sessions: set[str]`

- `widgets/status_bar.py`:
  - Add streaming count display

- `widgets/chat_log.py`:
  - Add `resume_streaming()` method for mid-stream switch

## Implementation Order

1. **Phase 1.1-1.3**: Basic session switching while streaming (foundational)
2. **Phase 1.4**: Resume streaming display when switching to streaming session
3. **Phase 2**: Tree indicators (visibility)
4. **Phase 3**: Status bar count (polish)

Each step is independently testable:
1. After Phase 1: Can switch sessions while one streams in background
2. After Phase 2: Tree shows which sessions are streaming
3. After Phase 3: Status bar shows streaming count

## Testing Scenarios

1. Start streaming in session A, switch to idle session B
   - Expected: A continues streaming in background, B shows normally
2. Start streaming in A, switch to B, switch back to A
   - Expected: A's chat shows accumulated content, continues streaming
3. Start streaming in A, start streaming in B (via fork &), switch between
   - Expected: Both continue, UI updates appropriately
4. Session finishes streaming while viewing another session
   - Expected: Tree indicator updates, status bar updates

## Edge Cases

1. **Switching to finished session**: If session finished while away, show full history
2. **Cancel while viewing other session**: Cancel only focused session? Or all?
   - Decision: Cancel only focused session (Escape = cancel focused)
3. **Memory**: Many streaming sessions = many contexts
   - Accept for now, add cleanup later if needed
