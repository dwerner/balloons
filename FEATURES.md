# Balloons Features Specification

> **Living Document**: This specification mirrors the current implementation. Update when features are added, modified, or removed.

## Overview

Balloons is a TUI (Terminal User Interface) chat client for Claude, built with Textual. It provides session management, context control, and parallel conversation workflows.

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

**Storage**: Sessions persist to `~/.balloons/sessions/{id}.json`

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

### Context Tree Widget

The left panel provides a tree view of all sessions and their turns:

- **Session nodes**: Show title/ID, message count, token count
- **Turn nodes**: Show role, preview, token count
- **Tool use nodes**: Expandable under assistant turns
- **Visual indicators**: Streaming spinners, context mode colors

**Keyboard shortcuts in tree**:
| Key | Action |
|-----|--------|
| Space | Cycle context mode (COPY → COMPRESS → DROP) |
| Enter | Activate/navigate to session |
| `a` | Select all turns in current session |
| `n` | Deselect all turns in current session |
| `/` | Search |
| `d` / Delete | Delete turn (with confirmation) |

**Sorting options**:
- Recently used (modified_desc) - default
- Least recently used (modified_asc)
- Newest created (date_desc)
- Oldest created (date_asc)
- Title A-Z / Z-A
- Most/fewest messages
- Most tokens
- Highest cost

Sort preference persists in config.

---

## Session Forking & Merging

### Fork Command

Create a child session that inherits selected context.

```
:fork[=name] <prompt> [--bg]
```

| Parameter | Description |
|-----------|-------------|
| `=name` | Optional fork name (e.g., `:fork=auth-bug`) |
| `prompt` | Initial prompt for the fork |
| `--bg` | Run in background (stay in parent) |

**Context inheritance**:
1. COPY turns included verbatim
2. COMPRESS turns summarized by LLM before fork starts
3. DROP turns excluded

**Fork tracking**:
- `parent_id`: Link to parent session
- `fork_name`: User-friendly name
- `fork_status`: "active", "merged", "abandoned"
- `fork_point_turn`: Turn index in parent where forked

### Merge Command

Merge a fork back to its parent.

```
:merge [prompt]
```

- Optional prompt guides LLM summary generation
- Fork becomes read-only after merge
- Merge marker added to parent's chat log

### Derive Command

Create an independent session with selected context (no parent relationship).

```
:derive <prompt>
```

### Switch Command

Navigate between sessions/forks.

```
:switch [name]
```

Without name: shows picker. With name: switches to that fork.

---

## Commands Reference

| Command | Description |
|---------|-------------|
| `:new [prompt]` | Create new session, optionally with initial prompt |
| `:fork[=name] <prompt> [--bg]` | Fork with selected context |
| `:merge [prompt]` | Merge fork back to parent |
| `:derive <prompt>` | New independent session with context |
| `:switch [name]` | Switch to session/fork |
| `:copy-turns` | Copy selected turns to new session |
| `:query-with <prompt>` | Query with selected context, response to new session |
| `:title <title>` | Set session title |
| `:pwd` | Show working directory |
| `:cd <path>` | Change working directory |
| `:suspend <cmd>` | Suspend TUI, run interactive shell command |
| `:!<cmd>` | Run shell command, send output to Claude |
| `:reload` | Hot reload the app |

### Legacy Commands (Backwards Compatible)

| Command | Maps To |
|---------|---------|
| `:with <prompt>` | `:fork` with COMPRESS context |
| `:with-copy <prompt>` | `:fork` with COPY context |
| `:return [prompt]` | `:merge` |

---

## UI Components

### Main Layout

```
┌─────────────────────────────────────────────────────┐
│ Breadcrumb (hidden unless in fork)                  │
├──────────────┬──────────────────────────────────────┤
│ Context Tree │ Chat Log                             │
│              │                                      │
│ - Sessions   │ - User messages                      │
│   - Turns    │ - Assistant messages                 │
│     - Tools  │ - Tool use/result widgets            │
│              │ - Fork/merge markers                 │
│              │                                      │
├──────────────┴──────────────────────────────────────┤
│ Tool Bar (enabled tools: Bash, Read, Edit, etc.)   │
├─────────────────────────────────────────────────────┤
│ Debug Pane (collapsed, toggle with Ctrl+G)         │
├─────────────────────────────────────────────────────┤
│ Status Bar (model, tokens, cost, working dir)      │
├─────────────────────────────────────────────────────┤
│ Input Box                                           │
└─────────────────────────────────────────────────────┘
```

### Status Bar

Displays:
- Model name (abbreviated)
- Token usage: current / context_window (percentage)
- Cost in USD
- Working directory (abbreviated path)
- Follow indicator (when not auto-scrolling)
- Background streaming count
- Streaming spinner

### Breadcrumb

Shows navigation path when in a fork:
```
Main Session > auth-bug > deep-dive [merged]
```

Clickable to navigate up the hierarchy.

### Tool Widgets

Tool use and results display as collapsible widgets with:
- Syntax highlighting for code
- Diff view for edits
- Truncation with expand on click
- Context mode visual indicators

### Fork/Merge Markers

Visual markers in chat log showing:
- Fork points (with link to child session)
- Merge points (with summary)

---

## Keyboard Shortcuts

### Global

| Key | Action |
|-----|--------|
| Ctrl+C / Ctrl+Q | Quit |
| Escape | Cancel streaming / focus input |
| Ctrl+T | Toggle context tree |
| Ctrl+R | Toggle request pane |
| Ctrl+G | Toggle debug pane |
| Ctrl+Left/Right | Resize tree |
| Ctrl+End | Scroll to bottom (follow) |

---

## Backend Configuration

Configure multiple LLM backends in `~/.balloons/config.yaml`:

```yaml
default_backend: claude

backends:
  claude:
    # Native Claude API (no base_url needed)

  llama70b:
    base_url: "http://localhost:8080/v1"
    api_key: "optional-key"
    model: "llama-70b"

debug_log_file: /tmp/balloons_debug.log  # optional
```

**CLI options**:
- `--backend NAME` / `-b NAME`: Use specific backend
- `--list-backends`: List available backends
- `--resume ID` / `-r ID`: Resume session
- `--new` / `-n`: Start new session
- `--list` / `-l`: List sessions

---

## Streaming Architecture

### Event-Driven Model

All sessions stream in background mode. A poll timer checks for events from all active sessions and dispatches to UI components.

**Event types**:
| Event | Description |
|-------|-------------|
| `turn_started` | Stream began |
| `text` | Text delta |
| `tool_use` | Tool invocation |
| `tool_result` | Tool completed |
| `init` | Model/context info |
| `result` | Usage statistics |
| `done` | Stream complete |
| `error` | Error occurred |
| `rate_limit` | Rate limit hit |
| `cancelled` | Stream cancelled |
| `input_required` | Claude asking question |

### Background Streaming

Forks with `--bg` flag run in background:
- Stay in parent session
- WithWidget shows streaming progress
- Status bar shows background count
- Events polled and UI updated asynchronously

---

## Debug & Observability

### Debug Pane

Collapsible panel showing:
- Log entries grouped by Claude process run
- Color-coded by level (ERROR, WARNING, INFO, DEBUG)
- Auto-expands on errors
- Toggle with Ctrl+G

### Debug Log Persistence

Set `debug_log_file` in config to persist logs to file.

### Request Pane

Toggle with Ctrl+R to see:
- Raw request/response data
- Session info
- Message context

---

## Data Flow

### Prompt Submission

1. User enters text in InputBox
2. CommandParser checks for `:` prefix
3. If command: execute handler
4. If prompt: start streaming via SessionRunner

### Context Building

1. ContextTree tracks selected turns and their modes
2. On fork/prompt: ContextBuilder assembles context string
3. COPY messages included verbatim
4. COMPRESS messages summarized by LLM
5. DROP messages excluded

### Session Persistence

Sessions auto-save on:
- Message added
- Usage updated
- Title/settings changed
- Fork/merge operations

---

## File Structure

```
balloons/
├── app.py              # Main application, event handling
├── main.py             # CLI entry point
├── session.py          # Session data model
├── models.py           # Message, content blocks, events
├── config.py           # Configuration management
├── tokenizer.py        # Token counting
├── claude_runner.py    # Claude API streaming
├── core/
│   ├── commands.py     # Command parsing
│   ├── context.py      # Context building
│   ├── runner.py       # SessionRunner (async streaming)
│   ├── manager.py      # SessionManager (multi-session)
│   ├── formatter.py    # Output formatting
│   └── debug_log.py    # Debug logging
└── widgets/
    ├── chat_log.py     # Chat display
    ├── context_tree.py # Session/turn tree
    ├── input_box.py    # Text input
    ├── status_bar.py   # Status display
    ├── breadcrumb.py   # Fork navigation
    ├── debug_pane.py   # Debug display
    ├── tool_bar.py     # Tool toggles
    ├── request_pane.py # Request inspector
    ├── fork_marker.py  # Fork indicator
    ├── merge_marker.py # Merge indicator
    ├── with_widget.py  # Background session display
    └── splitter.py     # Pane resizing
```
