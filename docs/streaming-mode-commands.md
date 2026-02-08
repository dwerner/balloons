# Streaming Mode: Global Commands & Message Queue

## Overview

When Claude is streaming a response, the UI enters "streaming mode". This mode allows:

1. **Global commands** - Always work (`:new`, `:switch`, `:help`, etc.)
2. **Message queue** - Regular prompts are queued and sent after streaming completes
3. **Visual indicators** - Input box shows "commands only (N queued)" during streaming

This allows users to:
- Switch to another session while one is streaming
- Open help or preferences
- Create a new session
- Toggle UI elements (debug pane, auto-follow)
- **Queue follow-up messages** that will be processed automatically

## Command Categories

### Global Commands (Available During Streaming)

These commands don't interact with the current session's state and are safe to run anytime:

| Command | Description |
|---------|-------------|
| `:new` | Create a new session |
| `:switch` | Switch to another session |
| `:help` | Show help modal |
| `:prefs` | Open preferences |
| `:debug` | Toggle debug pane |
| `:debug-clear` | Clear debug log |
| `:debug-pause` | Pause debug logging |
| `:pwd` | Show working directory (read-only) |
| `:pop` | Pop from message stash |
| `:follow` | Toggle auto-scroll |
| `:reindex` | Rebuild session index |
| `:slides` | Switch to Slides tab |
| `:chat` | Switch to Chat tab |
| `:present` | Enter presentation mode |

### Session-Specific Commands (Blocked During Streaming)

These commands modify the current session or require it to be idle:

| Command | Why Blocked |
|---------|-------------|
| `:fork` | Starts new streaming in child session |
| `:merge` | Requires session context |
| `:derive` | Creates session from current context |
| `:archive` | Modifies session turns |
| `:!` (shell) | Sends output to Claude |
| `:backend` | Changing backend mid-stream is confusing |
| `:cd` | Changes session's working directory |
| `:reload` | Could interrupt streaming |
| `:edit-config` | Config changes could affect stream |
| `:edit-prompt` | Prompt changes affect next message |
| `:title` | Modifies session metadata |
| `:stash` | Captures input for later |
| `:snap` | Sends screenshot to Claude |

### Regular Prompts → Message Queue

When you type a regular prompt (not a command) during streaming, it's added to the **message queue**:

- The prompt is saved to the session's queue
- A status message shows "Message queued (N pending)"
- The input box title shows the queue count
- When streaming completes, the next queued message is automatically sent

## Implementation

### Command Class

Each command class has an `is_global` attribute:

```python
@dataclass
class Command:
    """Base class for all commands."""
    is_global: bool = False  # Default: session-specific

@dataclass
class NewSessionCommand(Command):
    is_global: bool = True  # Can create new session during streaming
    prompt: str = ""
    title: str = ""
```

### Input Handler

The `on_input_box_submitted` handler checks `is_global`:

```python
async def on_input_box_submitted(self, event):
    cmd = self._command_parser.parse(prompt)

    if cmd is not None:
        # During streaming, only allow global commands
        if self.streaming and not cmd.is_global:
            status_bar.set_error(
                "Command unavailable during streaming (use :new, :switch, :help, etc.)"
            )
            return
        await self._execute_command(cmd)
        return

    # Regular prompts blocked during streaming
    if self.streaming:
        return
```

### UI Streaming Mode

Multiple widgets respond to streaming mode:

1. **InputBox**: Shows warning-colored border, still accepts commands
2. **DirectoryBrowser**: Disables Select button (`:cd` equivalent)

```python
def _set_ui_streaming_mode(self, streaming: bool) -> None:
    """Update all streaming-sensitive UI widgets."""
    input_box.set_streaming_mode(streaming)
    dir_browser.set_streaming_mode(streaming)
```

### Visual Indicators

- **InputBox.streaming-mode**: Warning-colored border (`$warning`) with title "commands only"
- **InputBox with queue**: Title shows "commands only (N queued)" when messages are pending
- **InputBox.command-mode**: Green border when typing `:` (takes precedence)
- **DirectoryBrowser**: Select button becomes disabled/grayed

### Message Queue

The `MessageQueue` class in `session.py` stores pending prompts:

```python
@dataclass
class MessageQueue:
    messages: list[QueuedMessage] = field(default_factory=list)

    def add(self, content: str) -> QueuedMessage: ...
    def pop(self) -> Optional[QueuedMessage]: ...
    def clear(self) -> int: ...
```

Queue is persisted with the session, so pending messages survive app restarts.

## Adding New Commands

When adding a new command:

1. Decide if it's global or session-specific
2. If global, add `is_global: bool = True` to the dataclass
3. Add a comment explaining why it's global/not global

```python
@dataclass
class MyNewCommand(Command):
    is_global: bool = True  # UI-only, no session interaction
    # ... other fields
```

## Error Messages

When a user tries a session-specific command during streaming:

```
Command unavailable during streaming (use :new, :switch, :help, etc.)
```

This hints at what IS available.
