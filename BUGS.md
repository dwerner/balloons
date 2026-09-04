# Bug List

Open bugs only. Fixed entries have been removed (see git history). Numbers are kept stable — gaps mean a bug was fixed.

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

## Bug #8: Test suite reliability
- Previously: 15 failures from un-awaited async calls (e.g. `session.save()`, `Session.list_sessions()`)
- Current state: a full local run **hangs** — `pytest -q tests -m "not integration"` stalls after ~26 tests with no output (no per-test timeout configured)
- Needs: identify the blocking test, add timeouts/network guards, then re-assess the original failures

## Bug #9: Fork acceptance shows misleading context in tree view
- When accepting a fork, the context tree initially shows all nodes from the parent session
- This gives the false impression that the entire context was copied
- Once the forked session actually starts/loads, it correctly shows only:
  - The compressed context summary
  - The turns that were actually marked for copy/compress
- The initial tree display should reflect the actual curated context, not the full parent history

## Bug #11: RPC method name collisions on startup
- When starting `headless.py`, warnings are logged about method name collisions:
  - `getActiveSessionId` exists in multiple services
  - `getSession` exists in multiple services
  - `getStreamingSessions` exists in multiple services
  - `clear` exists in multiple services
- Should use qualified names like `SessionManagerService.getActiveSessionId` or `GoalTreeStateService.clear`
- Need to either rename methods to be unique or implement proper namespacing in the RPC dispatch

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

## Bug #16: Cannot rename session while streaming via status bar
- Should be able to rename the session while it's actively streaming
- Status bar should provide an editable session name field that works during streaming
- Currently renaming may be blocked or unavailable during active streaming

## Bug #17: Remove SimpleTurnsView remnants
- The component itself is gone; leftover CSS remains in `web/ui/src/styles.css`
- Remove the orphaned styles

## Bug #18: Token count drops to zero when pinning a session
- When pinning a session, the token usage count resets/drops to zero
- Suspected cause: session save operation during pinning may be resetting or not preserving the token count
- Token count should persist through pin operations

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