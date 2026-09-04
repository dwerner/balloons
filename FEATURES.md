# Balloons Features Specification

> **Living Document**: This specification mirrors the current implementation. Update when features are added, modified, or removed.

## Overview

Balloons is a headless server and web-based conversation platform for LLM-powered coding agents. It provides session management, context control, tool use, and parallel conversation workflows over a WebSocket API.

**Status note:** The Textual TUI is dead and unsupported, and `:commands` are dead and unsupported.

---

## Core Architecture

### Session Management

Sessions are the primary unit of conversation state.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique session identifier |
| `created` | ISO datetime | Creation timestamp |
| `last_modified` | ISO datetime | Last modification timestamp |
| `model` | string | Model used (e.g., "claude-3-opus") |
| `messages` | list | Conversation history |
| `total_input_tokens` | int | Cumulative input tokens |
| `total_output_tokens` | int | Cumulative output tokens |
| `total_cost` | float | Cumulative cost in USD |
| `context_window` | int | Model's context window size |
| `working_directory` | string | Session's working directory |
| `title` | string | User-set or LLM-generated title |
| `summary` | string | Session summary |

**Storage**: Sessions are stored through the current Rust-backed persistence layer, with legacy JSON paths retained only for migration and cleanup compatibility.

### Message Model

Each message contains:
- `role`: "user" or "assistant"
- `content`: Plain text (for display/backwards compat)
- `content_blocks`: Rich content (TextBlock, ToolUseBlock, ToolResultBlock)
- `tokens`: Token count
- `timestamp`: ISO datetime
- `context_mode`: How to include in fork context (COPY, COMPRESS, DROP)
- `summary`: Cached summary for COMPRESS mode

---

## Context Management

### Context Modes

Each turn can be marked with a context mode that controls how it's included when forking:

| Mode | Behavior |
|------|----------|
| **COPY** | Include turn verbatim in fork (default) |
| **COMPRESS** | LLM summarizes turn before fork starts |
| **DROP** | Exclude from fork context |

### Context Selection and Curation

Supported clients expose session and turn context controls so users can:

- inspect sessions and their turns
- review tool-use history alongside assistant turns
- adjust per-turn context modes (COPY / COMPRESS / DROP)
- inspect token usage and preview the context that will be sent to the model
- navigate between related sessions and derived conversations
- sort or filter session history according to the active client experience

---

## Session Forking & Merging

### Forking and Merging

Sessions support fork/merge workflows with explicit tracking:

**Fork tracking**:
- `parent_id`: Link to parent session
- `fork_name`: User-friendly name
- `fork_status`: "active", "merged", "abandoned"
- `fork_point_turn`: Turn index in parent where forked

**Merge behavior**:
- Forks can be merged back to their parent with summary information
- Merge markers and the child session's work summary are preserved in session history
- Forks become concluded/read-only after merge depending on workflow

### Derive Sessions

The system also supports creating independent sessions from selected context without a parent/child relationship.

### Session Navigation

Users can navigate between sessions, forks, and linked conversations in the supported UI surfaces.

---

## Backend Configuration

Configure backends in `~/.balloons/config.yaml`:

```yaml
default_backend: claude

backends:
  claude:
    type: claude
    context_window: 150000

  openrouter:
    type: openai
    base_url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
    model: anthropic/claude-sonnet-4
    system_prompt: ~/.balloons/prompts/coding-assistant.md

  ollama:
    type: openai
    base_url: http://localhost:11434/v1
    api_key: ollama
    model: llama3.2
    system_prompt: ~/.balloons/prompts/minimal.md
```

See `config/config.sample.yaml` for the full configuration surface, including optional WebSocket, auth, voice-input, sound, and report settings.

---

## Streaming Architecture

### Event-Driven Model

All sessions stream through an event-driven model. Backend services publish task-state and session-data events, and supported clients subscribe and react to those updates.

### Task-state streaming events

`TaskStateService` exposes fine-grained streaming events for rendering active exchanges and tool execution:

| Event | Description |
|-------|-------------|
| `onContentDelta` | Text chunks streaming from the LLM |
| `onTurnStarted` | A new user, assistant, or tool turn began |
| `onTurnFinished` | A turn completed |
| `onToolUseStarted` | A tool call began and its input may still be streaming |
| `onToolInputDelta` | Partial tool input JSON streamed |
| `onToolUse` | Full tool input is complete and execution begins |
| `onToolResult` | Tool execution completed |
| `onTaskStarted` | A task started |
| `onTaskUpdated` | Task status or progress changed |
| `onTaskCompleted` | A task completed successfully |
| `onTaskError` | A task failed |
| `onTaskCancelled` | A task was cancelled |

### Session-data streaming events

`SessionDataService` exposes session-oriented subscription events so clients can hydrate and update conversation state incrementally:

| Event | Description |
|-------|-------------|
| `sessionDataTurnCreated` | A turn was created in a subscribed session |
| `sessionDataTurnDelta` | Streaming turn content was updated |
| `sessionDataTurnFinished` | A turn finished streaming |
| `sessionDataStreamStarted` | A session stream started |
| `sessionDataStreamDone` | A session stream completed successfully |
| `sessionDataStreamProgress` | Session stream progress updated |
| `sessionDataStreamError` | Streaming failed, was rate-limited, or was cancelled |
| `sessionDataToolUseStarted` | A tool-use turn began |
| `sessionDataToolInputDelta` | Tool input JSON streamed |
| `sessionDataToolUse` | Tool input completed |
| `sessionDataToolResult` | Tool execution completed |
| `sessionDataHistoryChunk` | A chunk of historical turns arrived |
| `sessionDataHistoryComplete` | Historical backfill completed |
| `sessionDataTurnsDeleted` | Turns were deleted |
| `sessionDataTurnsReordered` | Turn ordering was recomputed |

### Background Streaming

Fork and task workflows can continue asynchronously while the user remains focused on other sessions or views:
- work can continue outside the currently viewed session
- clients can show background activity and progress indicators
- events are delivered asynchronously through the service layer

---

## Process Supervisor

The process supervisor manages long-running background processes such as dev servers, watchers, builds, and other session-associated commands.

### Supported surfaces

The current architecture exposes supervisor functionality through both tool and service interfaces:

- LLM/tool access via:
  - `supervisor_start`
  - `supervisor_list`
  - `supervisor_output`
  - `supervisor_stop`
- WebSocket/service access via `SupervisorStateService`

### Supervisor capabilities

Supported capabilities include:

- starting a supervised process
- listing processes for the current session or across sessions
- retrieving captured process output and history
- stopping a running process
- sending input to interactive processes
- inspecting configured execution hosts and their status
- mapping backends to execution hosts where applicable

### Process model

Processes are represented with structured metadata including:
- `process_id`
- command
- optional friendly name
- host
- session association
- status
- exit code (when finished)
- start time and runtime
- process type

### Output and history

Supervisor output is tracked as structured entries that include:
- timestamp
- source (`stdout`, `stderr`, `system`, or input history where applicable)
- content

The service layer supports both real-time output streaming and paginated history retrieval.

### Event model

Supervisor state changes are exposed as events, including:
- process started
- process output
- process stopped
- host status changes

### Use Cases

- running dev servers while continuing other work
- monitoring build or test output asynchronously
- checking background process status from the web client
- managing remote or host-specific process execution

---

## Debug & Observability

### Debug Logging

The current system exposes debug logging through `DebugLogService`, backed by per-category in-memory ring buffers (`core/debug_log.py`).
Supported observability capabilities include:
- structured log entries for runtime and tool activity
- severity/category-based inspection
- log retrieval and buffer management through service surfaces
- LLM-facing debug tools (`debug_log_query`, `debug_log_config`, `debug_log_tail`)

### Request and Session Inspection

Supported debugging surfaces may expose operational state needed to inspect active work, including:
- session metadata
- conversation/message context
- runtime events and related diagnostics

---

## Data Flow

### Prompt Submission

1. A supported client submits a message or action through the WebSocket/RPC service layer.
2. `SessionManagerService` routes the request into session orchestration and streaming execution.
3. Task/session services emit incremental events as turns, tool calls, and results progress.
4. Connected clients update their views from those emitted events and on-demand state reads.

### Context Building

1. Session state and selected turn history are loaded through the session data/context pipeline.
2. Context modes determine how prior turns are included.
3. COPY turns are included verbatim.
4. COMPRESS turns are summarized before inclusion.
5. DROP turns are excluded from derived context.

### Session Persistence

Session state is persisted incrementally through the current storage layer as conversation and metadata change, including events such as:
- turn/message additions
- usage/statistics updates
- title or settings changes
- fork/merge and related session-relationship updates

---

## File Structure

```text
balloons/
├── headless.py               # Supported headless server entry point
├── session.py                # Session model and persistence-heavy logic
├── models.py                 # Shared message/content/event types
├── config.py                 # Configuration loading
├── claude_runner.py          # Claude streaming backend integration
├── core/                     # Context building, runners, tools, debug helpers
├── service/                  # WebSocket/RPC-facing service layer
├── plugins/                  # Plugin integrations and domain extensions
├── web/ui/                   # React web frontend
├── config/                   # Sample and auxiliary configuration files
└── balloons-rs/              # Rust-backed storage/process components
```

This structure is intentionally high-level. Prefer the architecture and module docs over this section for detailed responsibilities, since the exact file layout is still evolving.
