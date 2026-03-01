# Watcher Mode Specification

## Overview

Watcher mode provides a way to observe and interact with another chat session. A "watcher" is a **real, persistent session** that maintains a compressed summary chain of the target session's exchanges. The watcher session is automatically named `watching:{target-session-name}`.

## Terminology

- **Watcher**: The observing session that receives summaries
- **Target**: The session being watched

## Key Decisions

- **Real session**: Watcher is a full session, persists across reloads, appears in session tree
- **Explicit user control**: User initiates watching via UI
- **User-guided summarization**: Conversation with the watcher influences how summaries are generated
- **One watcher per target**: V1 limits to one watcher per target session
- **Fork follows**: When target forks, watcher follows, summary chain continues

## Core Mechanism

**When a target session completes an exchange, a summary turn is automatically created in the watcher session.**

The summary is generated using the **watcher's full context** - including:
- Previous summaries
- Any conversation the user has had with the watcher
- Instructions the user has given ("watch for X", "highlight Y")

This means the user can guide summarization by chatting with the watcher:

```
WATCHER SESSION:
----------------
[WatchStart] Watching fix-auth-bug

User: "Let me know if it touches any SQL queries - those have been problematic"

Watcher: "Got it, I'll flag any SQL-related changes."

[Summary 1] Initial investigation of auth bug...
[Summary 2] Regex approach failed...

--- TARGET COMPLETES EXCHANGE 3 ---
--- Exchange touches db/queries.py ---

[Summary 3] "Modified SQL queries in db/queries.py (flagging per your
            request). Migration adds index on user_tokens table. Tests pass."
```

The user's instructions persist in context and influence all future summaries - no special "watch criteria" feature needed.

## Data Model

### Turn-Based Watch Relationship

Watching is established via special turn types in the watcher session:

```python
class WatchStartBlock:
    """Turn marking start of watching a session."""
    type: Literal["watch_start"]
    target_session_id: str
    target_session_name: str

class WatchStopBlock:
    """Turn marking end of watching a session."""
    type: Literal["watch_stop"]
    target_session_id: str
    reason: str  # "user", "session_closed", "session_archived"

class WatchSummaryBlock:
    """Turn containing a summary of a target session exchange, through the lens of the watcher's context."""
    type: Literal["watch_summary"]
    target_session_id: str
    target_session_name: str
    exchange_index: int
    summary: str
```

This approach:
- Allows a session to watch multiple targets (multiple `watch_start` turns)
- Makes the watch relationship visible in conversation history
- Summaries from multiple targets can interleave
- User conversation naturally influences summaries

## Summary Injection and Response

### How Summaries Arrive

When a target session completes an exchange:
1. Summary is generated using watcher's context (previous summaries + user instructions)
2. `WatchSummaryBlock` is **injected** into the watcher session as an external input
3. Watcher LLM **responds** to the summary (like any other input)

```
TARGET SESSION                           WATCHER SESSION
--------------                           ---------------
                                         Context: [WatchStart, user instructions,
                                                   Summary 1, Summary 2, ...]
Exchange 3 completes:
  User: "try a different approach"
  Claude: [edits file, runs tests]
  Claude: "Tests pass!"
       |
       +-----(exchange_complete)-------> Generate summary using watcher context
                                                |
                                                v
                                         [Summary 3] injected as turn
                                                |
                                                v
                                         Watcher LLM responds to summary
                                         (guided by user's instructions)
```

### Watcher Response Options

The watcher's prompt guides how it responds to summaries:

**Minimal acknowledgment** (default):
```
[Summary 3] "Fixed auth bug, tests passing."
Watcher: "✓"
```

**Commentary** (if user requested):
```
User: "Give me your analysis of each step"
...
[Summary 3] "Fixed auth bug, tests passing."
Watcher: "Good progress. Note they used token splitting -
          this is the approach I suggested earlier."
```

**Action via tool** (if user requested):
```
User: "If it tries regex again, tell it to try something else"
...
[Summary 3] "Trying regex approach again..."
Watcher: "I see they're repeating the regex approach."
[Tool: send_to_target("Consider token splitting instead of regex")]
```

### Watcher Tools

The watcher has access to cross-session tools:

```python
def send_to_target(message: str) -> str:
    """Send a message to the target session.
    The message is queued and sent after any current exchange completes."""
```

This lets the watcher actively intervene when instructed by the user.

### Queueing Rules

When multiple things want to happen:
- **Summary arrives while watcher is mid-exchange**: Queue the summary, inject after exchange completes
- **User message while watcher is processing summary**: Queue user message, process after summary response
- **send_to_target while target is mid-exchange**: Queue message, send after target exchange completes

Order: FIFO within each queue. Summary injection waits for current watcher exchange to finish before triggering its own exchange.

## MVP Implementation

### What to Build

1. **Turn types**: Add `WatchStartBlock`, `WatchStopBlock`, `WatchSummaryBlock`
2. **Watcher tools**: Add `send_to_target` tool for cross-session messaging
3. **Initiation**: "Watch in new session" action creates watcher session with:
   - `WatchStartBlock` turn
   - System prompt for watching (includes minimal-ack default behavior)
   - Initial planning conversation with user
4. **Live summarization**: Subscribe to target's exchange events, generate summaries, inject into watcher
5. **Summary response**: Watcher LLM responds to each injected summary
6. **Queue management**: Handle concurrent exchanges gracefully
7. **UI rendering**: Display watch blocks in `TurnCard`

### How to Initiate (MVP)

Right-click session in tree -> "Watch in new session":
1. Creates new session named `watching-{target-name}`
2. Adds `WatchStartBlock` turn
3. Starts a conversation where user can give watching instructions
4. Kicks off the target session (if not already running)
5. User switches between sessions using normal session tree

No split-pane UI for MVP - just normal session switching.

### Summary Prompt

When target exchange completes, send to watcher's LLM:

```
[Watcher's existing context - turns, summaries, user instructions]

---
The target session just completed an exchange. Summarize it:

Exchange {N}:
{user message}
{assistant response with tool calls}

Provide a 2-4 sentence summary capturing:
- What was attempted
- Key outcomes
- Anything the user asked you to watch for
```

The response becomes the `WatchSummaryBlock` content.

## Future: Split/Swap UI

Later phases will add side-by-side viewing:

DESKTOP - Split view in Streaming tab:
```
+-----------------------------------+-----------------------------------+
|  WATCHER: watching-fix-auth       |  TARGET: fix-auth-bug             |
|  StreamingTurnsView               |  StreamingTurnsView               |
|  (summaries + user conversation)  |  (full turn history)              |
+-----------------------------------+-----------------------------------+
| [* Watcher] [ ] Target  Message...                             [Send] |
+-----------------------------------------------------------------------+
```

MOBILE - Quick swap:
```
+-----------------------------------+
| [* Watcher] [ ] fix-auth-bug      |  <- Tap to swap
+-----------------------------------+
| StreamingTurnsView (one at a time)|
+-----------------------------------+
| [Message...]                [Send]|
+-----------------------------------+
```

## Non-Goals for V1

- Split/swap UI (use normal session switching)
- Automatic triggers/alerting
- Watcher-initiated injection
- Lockstep mode
- Archival suggestions
- Watcher-of-watcher chains
