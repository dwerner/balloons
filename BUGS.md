# Bug List

## ~~Bug #1: Fork/merge turns should link bidirectionally~~ (FIXED)
- ~~Fork turns have clickable links to navigate to the forked session~~
- ~~Merge turns should similarly have links back to the child session that was merged~~
- ~~Both sides of a fork or merge should link to the other session~~

**Fix**: Fork and merge turns now have bidirectional links - both sides link to each other.

## ~~Bug #2: Tool results and uses are grouped into the same turn~~ (FIXED)
- ~~Tool invocations and their results are currently collapsed into a single turn~~
- ~~They should be displayed as separate turns (or at least visually distinct)~~
- ~~**Symptom**: Shows placeholder text like `tool_result skipped (rendered with tool_use) | ID: f74d2165`~~
- ~~The rendering logic is intentionally skipping tool_result turns assuming they'll be shown with tool_use~~
- ~~But this creates confusion and loses information - need to properly split these into separate rendered turns~~
- ~~**Specific case**: Edit tool shows "file modified successfully" but the actual edit content (old_string/new_string) is not displayed because the tool_result is skipped~~

**Fix**: Tool uses and tool results are now rendered as separate, visually distinct turns.

## Bug #3: Rotating progress indicator has incorrect rotation axis
- The rotation pivot point is off, making the animation look wrong
- Likely needs manual adjustment to find a better center point for the rotation

## Bug #4: Expanded/selected sessions in tree view show no messages when not loaded
- When you select or expand a session in the tree view that isn't currently loaded, it shows empty (no messages)
- This is misleading - the session does have messages, they just aren't loaded yet
- Expected behavior: expanding a session should trigger loading its messages

## Bug #5: No local storage caching system (Enhancement)
- Currently sessions/messages are fetched fresh each time
- Should consider caching in localStorage or IndexedDB to:
  - Speed up loading previously viewed sessions
  - Reduce server requests
  - Enable some offline viewing capability

## Bug #6: Certain turn types don't observe the theme setting
- Some turn types aren't respecting the current theme (light/dark/custom colors)
- Likely hardcoded colors or missing theme variable references in specific turn type components

## Bug #7: Context tree "Today" section only shows last loaded session
- The "Today" / date-based sections in the context tree only track the most recently loaded session
- After server restart, the "Today" section is lost/empty
- Suspected cause: client-side tracking of "last modified" instead of properly reading and sorting by the `modified_at` timestamp stored in LMDB
- Should be sorting all sessions by their actual stored modification date

## Bug #8: Multiple failing test suites (15 failures)
Async/await issues - methods became async but tests aren't awaiting them:

| Test Area | Failures | Root Cause |
|-----------|----------|------------|
| `TestExecuteLinkTool` | 4 | `session_info` related |
| `TestSessionProgressiveSaving` | 6 | `session.save()` not awaited (now async) |
| `TestSessionArchive` | 2 | `session.save()` not awaited |
| `TestAsyncSessionIO` | 2 | `Session.list_sessions()` not awaited properly |
| `test_headless` | 1 | `Session.list_sessions()` async iteration issue |

## Bug #9: Fork acceptance shows misleading context in tree view
- When accepting a fork, the context tree initially shows all nodes from the parent session
- This gives the false impression that the entire context was copied
- Once the forked session actually starts/loads, it correctly shows only:
  - The compressed context summary
  - The turns that were actually marked for copy/compress
- The initial tree display should reflect the actual curated context, not the full parent history

## ~~Bug #10: Turn ordering bug - tool uses/results appear after assistant turn~~ (FIXED)
- ~~Tool invocations and results are rendering after the assistant's summary turn~~
- ~~The assistant turn (which should end the exchange) appears before tool uses that logically preceded it~~
- ~~Suspected cause: turns are being updated/appended in the wrong order - possibly tool results arriving and being appended after the assistant content is already rendered~~
- ~~Expected order: tool_use → tool_result → assistant summary~~
- ~~Actual order: assistant summary → tool_use → tool_result (or mixed)~~
- ~~**Key detail**: Loading historical turns shows the correct order - the bug is only in the live/streaming render, not persistence~~

**Fix**: The `done` event handler in `session_manager_service.py` was emitting `turn_finished` with
`ctx.assistant_turn_idx` which tracked the INITIAL assistant turn's index. The final text turn
(created after tool execution in `_finalize_stream`) never updated this index because it wasn't
emitting events. Changed `_finalize_stream` in `core/runner.py` to call `_flush_text_as_turn(emit_event=True)`
so the final text turn emits proper `text_turn_started` and `text_flush` events, which update
`ctx.assistant_turn_idx` to the correct index before the `done` event is processed.

## Bug #11: RPC method name collisions on startup
- When starting `headless.py`, warnings are logged about method name collisions:
  - `getActiveSessionId` exists in multiple services
  - `getSession` exists in multiple services
  - `getStreamingSessions` exists in multiple services
  - `clear` exists in multiple services
- Should use qualified names like `SessionManagerService.getActiveSessionId` or `GoalTreeStateService.clear`
- Need to either rename methods to be unique or implement proper namespacing in the RPC dispatch

## ~~Bug #12: Chat log auto-scrolls to bottom on every new message~~ (FIXED)
- ~~When new messages are added during streaming, the chat log automatically scrolls to the bottom~~
- ~~This makes it impossible to scroll up and stay at a particular region to read earlier content~~
- ~~User cannot review assistant messages or tool call details while streaming is in progress~~
- ~~Expected behavior: if user has scrolled up, maintain their scroll position; only auto-scroll if already at bottom~~
- ~~Common UX pattern: detect if user is "near bottom" and only auto-scroll in that case~~

**Fix**: Removed conflicting `useEffect` in `App.tsx` that unconditionally scrolled to bottom
whenever `turns` state changed. The `useAutoScroll` hook in `StreamingTurnsView` and
`SimpleTurnsView` already handles intelligent auto-scroll behavior (only scrolls when
`isFollowing` is true, pauses when user scrolls up).

## Bug #13: Status bar doesn't update with streaming status, token count is zero
- The status bar doesn't reflect streaming status during active streaming
- Token count displays as zero instead of actual token usage
- Should show real-time token count and streaming indicator
- **Architecture note**: Token counting is supposed to happen incrementally via the Rust backend
- Some infrastructure for this exists but doesn't seem to be wired up and functional
- Need to trace the data flow from Rust tokenizer → Python → WebSocket → React UI

## Bug #14: Tool use cards have fixed height with vertical scroll instead of being collapsible
- Tool use cards currently have a fixed height and are vertically scrollable
- They should expand to fit their content (no internal scroll)
- Need collapsible behavior:
  - Default/collapsed state: show first ~5 lines with header bar
  - Expanded state: show full content when tapping header bar
- Header bar should toggle between collapsed and expanded states

## ~~Bug #15: Streaming status bar doesn't appear until page refresh~~ (FIXED)
- ~~When streaming starts, the streaming status bar doesn't show up~~
- ~~Requires a page refresh during streaming for the status bar to appear~~
- ~~Should appear immediately when streaming begins without needing refresh~~

**Fix**: The issue was a race condition between two WebSocket events: `sessionDataStreamStarted`
set `isStreaming=true` immediately, but `onTaskStarted` required an extra async `getTask()`
round-trip before setting `streamingTask`. During this round-trip, the condition
`isStreaming && streamingTask` was `true && null = false`, so no status bar was shown.

Fixed by immediately setting a minimal `TaskInfo` object from the event data when
`onTaskStarted` fires, before the async `getTask()` call completes. This ensures
`streamingTask` is non-null as soon as the task event arrives.

## Bug #16: Cannot rename session while streaming via status bar
- Should be able to rename the session while it's actively streaming
- Status bar should provide an editable session name field that works during streaming
- Currently renaming may be blocked or unavailable during active streaming

## Bug #17: Deprecate and remove SimpleTurnsView / simple chat log
- The simple chat log view should be completely removed, not maintained for backward compatibility
- Remove `SimpleTurnsView` component and all related code
- Remove any toggles/settings that switch between simple and streaming views
- Consolidate on the streaming turns view as the only chat log implementation

## Bug #18: Token count drops to zero when pinning a session
- When pinning a session, the token usage count resets/drops to zero
- Suspected cause: session save operation during pinning may be resetting or not preserving the token count
- Token count should persist through pin operations

## ~~Bug #19: Status bar doesn't show for new sessions (before streaming starts)~~ (FIXED)
- ~~When creating a new session, the status bar is not displayed~~
- ~~Status bar only appears once streaming starts~~
- ~~Should show a status bar for new sessions even before any streaming begins (with session name, empty/zero token count, etc.)~~
- ~~**Key detail**: Refreshing the page on an empty session DOES show the status bar~~
- ~~This suggests the status bar rendering condition is correct on load, but the "new session" action doesn't trigger the same state update~~

**Fix**: Status bar now shows for new sessions before streaming starts.

## ~~Bug #20: Last assistant turn shows empty body in streaming mode~~ (FIXED)
- ~~In streaming mode, the final assistant turn (the summary/conclusion text) renders with an empty body~~
- ~~The content exists but is not being displayed~~
- ~~Possibly related to Bug #10 fix - the `_flush_text_as_turn(emit_event=True)` change may be creating a turn but the content isn't being streamed/rendered correctly~~
- ~~This is a regression from the turn ordering fix~~

**Fix**: Final assistant turn content now renders correctly in streaming mode.

## Bug #21: Tool use errors should render as error turns with single-line format
- Errors like `<tool_use_error>File does not exist.</tool_use_error>` should be displayed as dedicated error turns
- Should render as a compact single-line error message, not as a multi-line block
- Currently these may be rendering as regular text or in a verbose format

## Bug #22: Streaming turns show double pulsing dot indicator (●●)
- Turns that are actively streaming show two pulsing dots instead of one
- Should be a single pulsing indicator
- Likely a duplicate rendering or CSS issue

## Bug #23: Pinned sessions fall into date categories (TODAY/YESTERDAY/UNKNOWN)
- Pinned sessions should stay in the pinned section at the top of the context tree
- Instead they're being moved into date-based categories like TODAY, YESTERDAY, or UNKNOWN
- Client-side glitch - the pinned state is not being respected when sorting/categorizing sessions

## Bug #24: Don't return FORK_PROPOSAL_PENDING or MERGE_PROPOSAL_PENDING to LLM
- When a fork or merge proposal is pending user input, these status values should not be returned to the LLM
- The LLM should be waiting for user input in these cases, not receiving status updates
- These pending states are meant to block until user accepts/rejects, not to continue the conversation

## ~~Bug #25: Long messages are truncated instead of being collapsible~~ (FIXED)
- ~~Long turn content is being truncated, which loses information~~
- ~~Turns should NOT truncate content~~
- ~~Instead, turns should be collapsible:~~
  - ~~Default/collapsed state: show first 5 lines~~
  - ~~Header bar should display the total line count (e.g., "42 lines")~~
  - ~~Expanded state: show full content when clicking header~~
- ~~This is similar to Bug #14 but applies to all turn types, not just tool use cards~~

**Fix**: Turns are now collapsible with line count display.

## ~~Bug #26: Turn cards should support "raw" view toggle for debugging~~ (FIXED)
- ~~Any turn type that derives from the base turn card should provide a "raw" rendering mode~~
- ~~Should be easily toggleable (button/hotkey) to switch between:~~
  - ~~Default: special/formatted rendering (markdown, syntax highlighting, etc.)~~
  - ~~Raw: plain text/JSON representation of the turn data for debugging~~
- ~~Useful for debugging rendering issues and understanding turn data structure~~

**Fix**: Turn cards now support a "raw" view toggle for debugging.