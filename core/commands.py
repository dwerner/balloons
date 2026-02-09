"""Command parsing for Balloons.

Extracts command parsing from app.py into a GUI-independent module.
Commands are prefixed with ':' and map to specific actions.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Command:
    """Base class for all commands.

    Attributes:
        is_global: If True, command can execute even during streaming.
                   Global commands don't need the current session to be idle.
    """
    # Class attribute - override in subclasses
    is_global: bool = False


@dataclass
class NewSessionCommand(Command):
    """Create a new blank session, optionally with an initial prompt."""
    is_global: bool = True  # Can create new session during streaming
    prompt: str = ""
    title: str = ""


@dataclass
class CopyTurnsCommand(Command):
    """Copy selected turns to a new session."""
    pass


@dataclass
class QueryWithCommand(Command):
    """Query with selected context, response goes to new session."""
    prompt: str = ""


@dataclass
class SuspendCommand(Command):
    """Suspend TUI and run interactive shell command."""
    shell_cmd: str = ""


@dataclass
class ShellCommand(Command):
    """Run shell command and send output to Claude."""
    shell_cmd: str = ""


@dataclass
class ForkCommand(Command):
    """Fork a child session from current session.

    Creates a child session that can be merged back.
    Context modes (COPY/COMPRESS/DROP) control what's inherited.
    """
    prompt: str = ""
    name: str = ""  # Optional fork name for easy reference
    background: bool = False


@dataclass
class MergeCommand(Command):
    """Merge fork back to parent.

    Takes a prompt that directs the LLM to summarize the fork's work.
    The LLM generates the merge message. Fork becomes read-only after merge.
    """
    prompt: str = ""  # Optional prompt to guide summary generation


@dataclass
class DeriveCommand(Command):
    """Create a new independent session with selected context.

    Like fork but no parent relationship - won't merge back.
    """
    prompt: str = ""


@dataclass
class SwitchCommand(Command):
    """Switch view to a different session or fork.

    Without name: show picker
    With name: switch to that named fork
    """
    is_global: bool = True  # Can switch sessions during streaming
    name: str = ""


@dataclass
class ReturnCommand(Command):
    """Return from child session to parent. (Legacy - use :merge)"""
    return_prompt: str = ""


@dataclass
class PwdCommand(Command):
    """Show current working directory."""
    is_global: bool = True  # UI-only, no session interaction


@dataclass
class CdCommand(Command):
    """Change working directory."""
    # Not global - changes session's working directory
    path: str = ""


@dataclass
class ReloadCommand(Command):
    """Hot reload the app."""
    # Not global - reloading during streaming could cause issues


@dataclass
class TitleCommand(Command):
    """Set session title."""
    title: str = ""


@dataclass
class HelpCommand(Command):
    """Show help modal with all commands."""
    is_global: bool = True  # UI-only


@dataclass
class DebugToggleCommand(Command):
    """Toggle the debug log pane visibility."""
    is_global: bool = True  # UI-only


@dataclass
class DebugClearCommand(Command):
    """Clear all debug log entries."""
    is_global: bool = True  # UI-only


@dataclass
class DebugPauseCommand(Command):
    """Toggle whether new entries are added to the debug log."""
    is_global: bool = True  # UI-only


@dataclass
class BackendCommand(Command):
    """Set or show the backend for this session."""
    # Not global - changing backend mid-stream would be confusing
    backend_name: str = ""  # Empty = show current, non-empty = set


@dataclass
class PrefsCommand(Command):
    """Open preferences modal."""
    is_global: bool = True  # UI-only


@dataclass
class EditConfigCommand(Command):
    """Open config file in external editor."""
    # Not global - config changes could affect streaming behavior


@dataclass
class EditPromptCommand(Command):
    """Open a prompt file in external editor."""
    # Not global - prompt changes could affect next message
    prompt_name: str = ""  # Empty = show picker


@dataclass
class LinkCommand(Command):
    """Create bidirectional link to one or more sessions.

    Links both sessions at their current positions with a shared summary.
    Unlike forks, links are symmetric - neither session is "parent".
    Multiple targets can be specified as comma-separated hashes.
    """
    target_session_prefixes: list[str] = None  # List of 8-char hash prefixes

    def __post_init__(self):
        if self.target_session_prefixes is None:
            self.target_session_prefixes = []


@dataclass
class ArchiveCommand(Command):
    """Archive selected turns to a file, replacing with summary marker.

    Can use explicit turn_indices from tree selection, or fall back to
    context mode selection if turn_indices is empty.
    LLM generates a structured summary of the archived content.
    """
    prompt: str = ""  # Optional hint for summary generation
    turn_indices: list[int] = None  # Turn indices to archive (0-indexed)

    def __post_init__(self):
        if self.turn_indices is None:
            self.turn_indices = []


@dataclass
class RehydrateCommand(Command):
    """Restore archived turns back into the conversation.

    Replaces the archive marker with the original messages.
    """
    archive_turn_index: int = -1  # Turn index of archive marker (-1 = auto-detect from selection)
    archive_id: str = ""  # Archive ID (optional, used when triggered from marker click)


@dataclass
class ReindexCommand(Command):
    """Rebuild the session index from disk.

    Scans all session files and rebuilds the index with their metadata.
    Use this if sessions are missing from the tree or index is corrupted.
    """
    is_global: bool = True  # Index operation, no session interaction


@dataclass
class FollowCommand(Command):
    """Toggle auto-scroll to follow new content.

    When enabled, chat scrolls to show new content as it arrives.
    When disabled, you can scroll freely without jumping.
    """
    is_global: bool = True  # UI toggle


@dataclass
class StashCommand(Command):
    """Stash current input for later.

    Saves the current input text to a persistent stash.
    Use :pop to retrieve stashed messages.
    """
    content: str = ""  # Content to stash (from input)
    name: str = ""  # Optional name for the stash entry


@dataclass
class PopCommand(Command):
    """Pop a message from the stash.

    Opens a picker to select and retrieve a stashed message.
    """
    is_global: bool = True  # UI-only, opens picker


@dataclass
class ClearAllSessionsCommand(Command):
    """Delete all sessions from disk.

    This is a destructive operation that removes all session files
    and clears the index. Requires confirmation.
    """
    pass


@dataclass
class SnapCommand(Command):
    """Capture the current screen as text and insert into conversation.

    Takes a snapshot of the TUI screen content and adds it to the next
    message as context. Useful for showing Claude the current UI state.
    """
    prompt: str = ""  # Optional prompt to send along with the snapshot


@dataclass
class NewSlideCommand(Command):
    """Create a new slide turn in the conversation.

    Slides are a first-class turn type for presentations. They appear
    in the Slides tab and can be presented fullscreen with :present.
    """
    title: str = ""  # Optional title (can be added later)
    content: str = ""  # Optional initial content


@dataclass
class PresentCommand(Command):
    """Enter fullscreen presentation mode.

    Shows slides one at a time with ←/→ navigation.
    Press Esc or q to exit.
    """
    is_global: bool = True  # UI mode switch


@dataclass
class SlidesCommand(Command):
    """Switch to the Slides tab view.

    Shows all presentation slides in the current session.
    """
    is_global: bool = True  # UI tab switch


@dataclass
class ChatCommand(Command):
    """Switch to the Chat tab view.

    Returns to the main chat conversation view.
    """
    is_global: bool = True  # UI tab switch


# =============================================================================
# Process Supervisor Commands
# =============================================================================

@dataclass
class SupervisorStartCommand(Command):
    """Start a supervised background process.

    The process runs in the background with output captured.
    Use :sup-logs to view output, :sup-stop to stop.
    """
    command: str = ""  # Shell command to run
    name: str = ""     # Optional friendly name


@dataclass
class SupervisorListCommand(Command):
    """List all supervised processes."""
    is_global: bool = True  # UI-only, no session interaction
    all_sessions: bool = False  # If True, show processes from all sessions


@dataclass
class SupervisorLogsCommand(Command):
    """View logs from a supervised process."""
    is_global: bool = True  # UI-only
    process_id: str = ""   # Process ID (or prefix)
    limit: int = 50        # Number of log entries


@dataclass
class SupervisorStopCommand(Command):
    """Stop a supervised process."""
    process_id: str = ""   # Process ID (or prefix) to stop


# =============================================================================
# Session Review Commands
# =============================================================================

@dataclass
class ReviewCommand(Command):
    """Start a quality review of the current session.

    Creates a review fork with:
    - Full session context (turns with sentiment markers)
    - Review agent system prompt
    - Switches to review_backend (or default_backend)

    The review agent guides the user through scoring the rubric dimensions
    and saves the structured review via the save_review tool.
    """
    pass


# Command documentation for help display
COMMAND_DOCS = [
    # Session management
    (":new[=title] [prompt]", "Create a new blank session, optionally with title and prompt"),
    (":title <title>", "Set the session title"),
    (":switch [name]", "Switch to another session (shows picker if no name)"),
    # Forking and merging
    (":fork[=name] <prompt>", "Fork with selected context, start a child session"),
    (":fork ... --bg", "Fork in background (continue working in parent)"),
    (":merge [prompt]", "Merge fork back to parent with LLM summary"),
    (":derive <prompt>", "New independent session with selected context (no merge)"),
    (":link=<hash>[,hash,...]", "Create bidirectional links to other sessions"),
    # Context operations
    (":query-with <prompt>", "Query with selected context, response in new session"),
    (":copy-turns", "Copy selected turns to a new session"),
    (":archive [hint]", "Archive selected turns to file with LLM summary"),
    (":rehydrate", "Restore archived turns (click archive marker or select it)"),
    # Message stash
    (":stash [name]", "Stash current input (Ctrl+S if text)"),
    (":pop", "Pop from stash (Ctrl+S if empty)"),
    # Shell integration
    (":!<cmd>", "Run shell command and send output to Claude"),
    (":suspend <cmd>", "Suspend TUI and run interactive shell command"),
    # Navigation
    (":pwd", "Show current working directory"),
    (":cd [path]", "Change working directory (shows browser if no path)"),
    # Misc
    (":reload", "Hot reload the app"),
    (":backend [name]", "Show or set the backend for this session"),
    (":prefs", "Open preferences (Ctrl+P)"),
    (":edit-config", "Edit config file in external editor"),
    (":edit-prompt [name]", "Edit a prompt file (shows picker if no name)"),
    (":debug", "Toggle debug log pane visibility"),
    (":debug-pause", "Toggle debug logging on/off"),
    (":debug-clear", "Clear all debug log entries"),
    (":reindex", "Rebuild session index from disk"),
    (":follow", "Toggle auto-scroll to follow new content"),
    (":clear-all-sessions", "Delete ALL sessions (requires confirmation)"),
    (":snap [prompt]", "Capture screen as text and send to Claude"),
    # Slides/Presentation
    (":new-slide [Title]", "Create a new slide (view in Slides tab)"),
    (":slides", "Switch to Slides tab view"),
    (":chat", "Switch to Chat tab view"),
    (":present", "Enter fullscreen presentation mode (Esc to exit)"),
    # Process Supervisor
    (":sup-start[=name] <cmd>", "Start supervised background process"),
    (":sup-list [--all]", "List supervised processes (--all for all sessions)"),
    (":sup-logs <id> [limit]", "View process logs (default 50 entries)"),
    (":sup-stop <id>", "Stop a supervised process"),
    # Session Review
    (":review", "Start quality review of current session"),
    (":help", "Show this help"),
]


class CommandParser:
    """Parse user input into Command objects.

    Usage:
        parser = CommandParser()
        cmd = parser.parse(":new")
        if cmd:
            # Handle command
        else:
            # Regular prompt, send to Claude

    Commands:
        :new[=title] [prompt]   - Create new session, optionally with title and prompt
        :fork[=name] <prompt>   - Fork with selected context, start working
        :merge [prompt]         - Merge fork back to parent (LLM summarizes)
        :derive <prompt>        - New independent session with selected context
        :switch [name]          - Switch to fork/session (picker if no name)
    """

    def parse(self, text: str) -> Optional[Command]:
        """Parse input text into a Command, or None if it's a regular prompt.

        Returns:
            Command if input is a recognized command
            None if input is a regular prompt to send to Claude

        Raises:
            ValueError if input is an unrecognized command
        """
        text = text.strip()

        if not text.startswith(":"):
            return None

        # Handle :copy-turns
        if text == ":copy-turns":
            return CopyTurnsCommand()

        # Handle :new[=title] [prompt]
        if text == ":new" or text.startswith(":new ") or text.startswith(":new="):
            return self._parse_new(text)

        # Handle :fork[=name] <prompt> [--bg]
        if text.startswith(":fork"):
            return self._parse_fork(text)

        # Handle :merge [prompt]
        if text == ":merge" or text.startswith(":merge "):
            prompt = text[6:].strip() if len(text) > 6 else ""
            return MergeCommand(prompt=prompt)

        # Handle :derive <prompt>
        if text.startswith(":derive"):
            prompt = text[7:].strip()
            if not prompt:
                raise ValueError(":derive requires a prompt")
            return DeriveCommand(prompt=prompt)

        # Handle :switch [name]
        if text == ":switch" or text.startswith(":switch "):
            name = text[7:].strip() if len(text) > 7 else ""
            return SwitchCommand(name=name)

        # Handle :query-with <prompt>
        if text == ":query-with" or text.startswith(":query-with "):
            prompt = text[len(":query-with"):].strip()
            if prompt:
                return QueryWithCommand(prompt=prompt)
            raise ValueError(":query-with requires a prompt")

        # Handle :suspend <cmd>
        if text == ":suspend" or text.startswith(":suspend "):
            shell_cmd = text[8:].strip()
            if shell_cmd:
                return SuspendCommand(shell_cmd=shell_cmd)
            raise ValueError(":suspend requires a command")

        # Handle :!<cmd>
        if text.startswith(":!"):
            shell_cmd = text[2:].strip()
            if shell_cmd:
                return ShellCommand(shell_cmd=shell_cmd)
            raise ValueError(":! requires a command")

        # Legacy: :return → convert to MergeCommand
        if text.startswith(":return"):
            return_prompt = text[7:].strip() if len(text) > 7 else ""
            return ReturnCommand(return_prompt=return_prompt)

        # Handle :pwd
        if text == ":pwd":
            return PwdCommand()

        # Handle :cd [path]
        if text.startswith(":cd"):
            path = text[3:].strip() if len(text) > 3 else ""
            return CdCommand(path=path)

        # Handle :reload
        if text == ":reload":
            return ReloadCommand()

        # Handle :title <title>
        if text.startswith(":title"):
            title = text[6:].strip() if len(text) > 6 else ""
            if not title:
                raise ValueError(":title requires a title")
            return TitleCommand(title=title)

        # Handle :help
        if text == ":help":
            return HelpCommand()

        # Handle :debug
        if text == ":debug":
            return DebugToggleCommand()

        # Handle :debug-pause
        if text == ":debug-pause":
            return DebugPauseCommand()

        # Handle :debug-clear
        if text == ":debug-clear":
            return DebugClearCommand()

        # Handle :backend [name]
        if text == ":backend" or text.startswith(":backend "):
            backend_name = text[8:].strip() if len(text) > 8 else ""
            return BackendCommand(backend_name=backend_name)

        # Handle :prefs
        if text == ":prefs":
            return PrefsCommand()

        # Handle :edit-config
        if text == ":edit-config":
            return EditConfigCommand()

        # Handle :edit-prompt [name]
        if text == ":edit-prompt" or text.startswith(":edit-prompt "):
            prompt_name = text[13:].strip() if len(text) > 13 else ""
            return EditPromptCommand(prompt_name=prompt_name)

        # Handle :link=<hash> <prompt>
        if text.startswith(":link"):
            return self._parse_link(text)

        # Handle :archive [hint]
        if text == ":archive" or text.startswith(":archive "):
            prompt = text[8:].strip() if len(text) > 8 else ""
            return ArchiveCommand(prompt=prompt)

        # Handle :rehydrate
        if text == ":rehydrate":
            return RehydrateCommand()

        # Handle :reindex
        if text == ":reindex":
            return ReindexCommand()

        # Handle :follow
        if text == ":follow":
            return FollowCommand()

        # Handle :stash [name]
        # Note: :stash alone (no content) is handled specially by the app
        # since we need to capture the input box content
        if text == ":stash" or text.startswith(":stash "):
            name = text[7:].strip() if len(text) > 7 else ""
            return StashCommand(name=name)

        # Handle :pop
        if text == ":pop":
            return PopCommand()

        # Handle :clear-all-sessions
        if text == ":clear-all-sessions":
            return ClearAllSessionsCommand()

        # Handle :snap [prompt]
        if text == ":snap" or text.startswith(":snap "):
            prompt = text[5:].strip() if len(text) > 5 else ""
            return SnapCommand(prompt=prompt)

        # Handle :new-slide [Title]
        if text == ":new-slide" or text.startswith(":new-slide "):
            title = text[10:].strip() if len(text) > 10 else ""
            return NewSlideCommand(title=title)

        # Handle :present
        if text == ":present":
            return PresentCommand()

        # Handle :slides
        if text == ":slides":
            return SlidesCommand()

        # Handle :chat
        if text == ":chat":
            return ChatCommand()

        # Handle :sup-start[=name] <cmd>
        if text.startswith(":sup-start"):
            return self._parse_sup_start(text)

        # Handle :sup-list [--all]
        if text == ":sup-list" or text.startswith(":sup-list "):
            all_sessions = "--all" in text
            return SupervisorListCommand(all_sessions=all_sessions)

        # Handle :sup-logs <id> [limit]
        if text.startswith(":sup-logs"):
            return self._parse_sup_logs(text)

        # Handle :sup-stop <id>
        if text.startswith(":sup-stop"):
            remaining = text[9:].strip()
            if not remaining:
                raise ValueError(":sup-stop requires a process ID")
            return SupervisorStopCommand(process_id=remaining)

        # Handle :review
        if text == ":review":
            return ReviewCommand()

        # Unknown command
        cmd_name = text.split()[0]
        raise ValueError(f"Unknown command: {cmd_name}")

    def _parse_fork(self, text: str) -> ForkCommand:
        """Parse :fork[=name] <prompt> [--bg] command."""
        # Check for =name syntax: :fork=auth-bug <prompt>
        name = ""
        remaining = text[5:]  # Remove ":fork"

        if remaining.startswith("="):
            # Extract name until space
            eq_part = remaining[1:]  # Remove "="
            if " " in eq_part:
                name, remaining = eq_part.split(" ", 1)
            else:
                name = eq_part
                remaining = ""
        else:
            remaining = remaining.strip()

        if not remaining:
            raise ValueError(":fork requires a prompt")

        # Check for --bg flag
        background = False
        if " --bg" in remaining or remaining.endswith("--bg"):
            background = True
            remaining = remaining.replace(" --bg", "").replace("--bg", "").strip()

        prompt = remaining.strip()
        if not prompt:
            raise ValueError(":fork requires a prompt")

        return ForkCommand(prompt=prompt, name=name, background=background)

    def _parse_new(self, text: str) -> NewSessionCommand:
        """Parse :new[=title] [prompt] command."""
        title = ""
        remaining = text[4:]  # Remove ":new"

        if remaining.startswith("="):
            # Extract title until space
            eq_part = remaining[1:]  # Remove "="
            if " " in eq_part:
                title, remaining = eq_part.split(" ", 1)
            else:
                title = eq_part
                remaining = ""
        else:
            remaining = remaining.strip()

        prompt = remaining.strip()
        return NewSessionCommand(prompt=prompt, title=title)

    def _parse_link(self, text: str) -> LinkCommand:
        """Parse :link=<hash>[,hash,...] command."""
        remaining = text[5:]  # Remove ":link"

        if not remaining.startswith("="):
            raise ValueError(":link requires =<session-hash> (e.g., :link=abc12345)")

        # Extract hashes (everything after "=")
        hashes_str = remaining[1:].strip()

        if not hashes_str:
            raise ValueError(":link requires at least one session hash prefix")

        # Parse comma-separated hashes
        target_prefixes = [h.strip() for h in hashes_str.split(",") if h.strip()]
        if not target_prefixes:
            raise ValueError(":link requires at least one session hash prefix")

        return LinkCommand(target_session_prefixes=target_prefixes)

    def _parse_sup_start(self, text: str) -> SupervisorStartCommand:
        """Parse :sup-start[=name] <cmd> command."""
        name = ""
        remaining = text[10:]  # Remove ":sup-start"

        if remaining.startswith("="):
            # Extract name until space: :sup-start=dev-server npm run dev
            eq_part = remaining[1:]  # Remove "="
            if " " in eq_part:
                name, remaining = eq_part.split(" ", 1)
            else:
                name = eq_part
                remaining = ""
        else:
            remaining = remaining.strip()

        command = remaining.strip()
        if not command:
            raise ValueError(":sup-start requires a command")

        return SupervisorStartCommand(command=command, name=name)

    def _parse_sup_logs(self, text: str) -> SupervisorLogsCommand:
        """Parse :sup-logs <id> [limit] command."""
        remaining = text[9:].strip()  # Remove ":sup-logs"

        if not remaining:
            raise ValueError(":sup-logs requires a process ID")

        parts = remaining.split()
        process_id = parts[0]
        limit = 50

        if len(parts) > 1:
            try:
                limit = int(parts[1])
            except ValueError:
                raise ValueError(f"Invalid limit: {parts[1]} (must be a number)")

        return SupervisorLogsCommand(process_id=process_id, limit=limit)
