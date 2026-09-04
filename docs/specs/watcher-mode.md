# Watcher Mode MVP Implementation

This document describes the actual implementation of the watcher mode feature, as built for the MVP. It supersedes the original spec (deleted; see git history).

## Summary

Watcher mode allows a session to observe another session, receiving LLM-generated summaries of exchanges as they complete. The watcher can be customized through conversation ("flag SQL changes") and can send messages back to the target via the `send_to_target` tool.

## What's Implemented

### Data Model

**Turn types** (in `models.py`):

- `WatchStartBlock` - Marks the start of watching a target session
- `WatchStopBlock` - Marks the end of watching (with reason)
- `WatchSummaryBlock` - Contains an LLM-generated summary of a target exchange

These are stored as turns in the watcher session, making the watching relationship visible in conversation history.

**Storage** (in `core/async_storage.py`):

- `WatcherRelationData` - Persisted relationship record
- `WatcherStorage` - LMDB-backed storage for watcher relationships
- Indexed by both `watcher_session_id` and `target_session_id` for fast lookup

### Session Methods

`Session` class (in `session.py`) gained:

- `get_watch_target_id()` - Get the target ID (from most recent unended WatchStartBlock)
- `is_watcher()` - Check if this session is watching anything
- `get_all_watch_targets()` - Get all currently watched targets
- `is_watching(target_id)` - Check if watching a specific target
- `add_watch_start_turn()` - Add a WatchStartBlock
- `add_watch_stop_turn()` - Add a WatchStopBlock
- `add_watch_summary_turn()` - Add a WatchSummaryBlock

### Backend Service

`SessionManagerService` (in `service/session_manager_service.py`) handles:

**Watcher lifecycle:**
- `create_watcher_session(target_session_id)` - Creates a new watcher session with:
  - `WatchStartBlock` turn establishing the relationship
  - User turn with watcher instructions (explaining how to customize)
  - Session named for the watched target
- `start_watching_session(session_id, target_session_id)` - Attaches an existing session, including a fork, as a watcher of a target
- `stop_watching_session(session_id, target_session_id?, reason)` - Adds WatchStopBlock, unregisters

**In-memory tracking:**
- `_watcher_targets: dict[str, list[str]]` - target -> watchers
- `_watcher_watching: dict[str, list[tuple[str, str]]]` - watcher -> (target_id, target_name)

**Server startup:**
- `_rebuild_all_watcher_relationships()` - Loads from LMDB on initialize
- `_rebuild_watcher_for_session()` - Called when loading a session to restore relationships

**Live summarization flow:**
1. Target completes exchange → `_notify_watchers_of_exchange()`
2. For each watcher: `_start_watcher_summary_generation()` uses HelperRunner
3. HelperRunner generates summary using watcher's full context
4. On completion: `_inject_watch_summary()` adds turn to watcher session
5. `_trigger_watcher_response()` prompts watcher LLM to respond

**Message queue integration:**
- `_on_queue_event()` - When a watcher sends a message to an idle target, process immediately

### Watcher Tools

`core/watcher_tools.py` provides:

- `send_to_target(message)` - Queue a message for the target session
  - Finds target from watcher's WatchStartBlock
  - Adds to target's persisted message queue
  - Also adds to QueueState for immediate processing if target is idle
  - Returns confirmation with queue position

### UI Components

**Session Tree** (`SessionTreeView.tsx`):
- Groups watcher sessions and their targets in a "👁 Watching" section
- Detects watchers by `watching:` title prefix
- Sorts: targets first, then their watchers

**Context Menu:**
- "Watch this Session" option creates a watcher session
- Calls `client.sessions.createWatcherSession(targetSessionId)`

**Turn rendering** (`SystemCard.tsx`):
- Icons: `watch_start` (👁), `watch_stop` (👁), `watch_summary` (📋)
- Display content:
  - watch_start: "Watching **{target-name}**"
  - watch_stop: "Stopped watching ({reason})"
  - watch_summary: "**Exchange N** from *{target}*\n\n{summary}"
- Navigation: "Go to target" button links to target session

## UX Flow

### Starting a watcher

Path 1: create a new watcher session
1. Right-click a session in the tree
2. Select "Watch this Session"
3. New watcher session created for the target
4. Watcher session shows:
   - WatchStartBlock: "Watching **target**"
   - Instructions explaining how watchers work
5. User can customize by chatting: "Flag any database changes"

Path 2: attach an existing session
1. Call `start_watching_session(session_id, target_session_id)`
2. Existing session receives a WatchStartBlock for the target
3. That session now receives live summaries for the target
4. This is the path that allows forks to become watchers

### Watching in action

1. Target session streams an exchange
2. On completion, summary generated using watcher's context
3. WatchSummaryBlock injected into watcher session
4. Watcher LLM responds (default: minimal "✓", or commentary if user requested)
5. If user gave instructions like "alert on SQL changes", summary highlights those

### Cross-session messaging

Watcher can use `send_to_target`:
```
[Tool: send_to_target("Consider using token splitting instead of regex")]
```
- Message queued for target
- If target is idle, processed immediately
- If streaming, processed when exchange completes

### Stopping

- `stop_watching()` API adds WatchStopBlock
- Currently no UI button - need to implement

## Watcher Instructions (System Prompt)

When a watcher session is created, it receives these instructions:

```markdown
You are a **watcher session** observing the session "{target-name}".

## How This Works

You will receive **summary injections** when the target session completes an exchange.
These summaries are nicely formatted markdown that describe what happened...

## Your Response Options

1. **Acknowledge only**: Just respond "✓" (this is the default)
2. **Add commentary**: Provide analysis or observations
3. **Take action**: Use `send_to_target` tool to send the target a message

## Customization Options

You can tell me to change how I behave. Examples:

**Watch for specific things:**
- "Flag any database migrations"
- "Alert me if tests fail"
- "Highlight any security-related changes"
...
```

## Summary Generation

The summary prompt is built with the watcher's full context (previous summaries, user instructions) and the target exchange content:

```markdown
## Your Watching Context
[Previous summaries, user instructions...]

## Exchange N to Summarize
[Target's user message and assistant response]

## Instructions
Summarize this exchange for the watcher session:
- What was attempted
- Key outcomes
- Anything the user asked you to watch for
```

## What's NOT Implemented (vs. Spec)

From the spec's "Non-Goals for V1":

- **Split/swap UI** - Uses normal session switching
- **Automatic triggers/alerting** - No push notifications
- **Lockstep mode** - Watcher is async, not step-by-step
- **Archival suggestions** - No automatic archival prompts
- **Watcher-of-watcher chains** - Not blocked, but not tested

Additional gaps:

- **Stop watching UI** - No button to stop watching (API exists)
- **Fork follows** - When target forks, watcher should follow (specified but unclear if implemented)
- **Visual connection** - No lines/badges showing watcher-target relationship
- **Expand to full exchange** - Can't view full exchange from summary

## Future: Split/Swap UI

(From the original spec, which this document supersedes.) Side-by-side viewing of watcher and target:

- **Desktop**: split the streaming tab into two panes — watcher (summaries + user conversation) alongside target (full turn history), with a pane selector for message delivery.
- **Mobile**: quick-swap toggle between watcher and target in a single view.

Other deferred ideas: automatic triggers/alerting, watcher-initiated injection, lockstep mode, expand-to-full-exchange from a summary.

## File Locations

| Component | File |
|-----------|------|
| Turn types | `models.py` |
| Session methods | `session.py` |
| Watcher storage | `core/async_storage.py` |
| Service logic | `service/session_manager_service.py` |
| Watcher tools | `core/watcher_tools.py` |
| UI tree grouping | `web/ui/src/components/SessionTreeView/SessionTreeView.tsx` |
| Turn rendering | `web/ui/src/components/StreamingTurnsView/cards/SystemCard.tsx` |
| API types | `generated/types.ts` (WatchStartBlock, WatchStopBlock, WatchSummaryBlock) |
