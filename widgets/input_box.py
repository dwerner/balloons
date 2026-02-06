from textual.widgets import TextArea, Static
from textual.containers import Vertical
from textual.message import Message
from textual.events import Key
from textual.reactive import reactive
from rich.text import Text

# Commands available for completion with descriptions
COMMANDS = [
    (":new", "New session"),
    (":title", "Set title"),
    (":switch", "Switch session"),
    (":fork", "Fork session"),
    (":merge", "Merge to parent"),
    (":derive", "Derive session"),
    (":link", "Link sessions"),
    (":query-with", "Query with context"),
    (":copy-turns", "Copy turns"),
    (":archive", "Archive turns"),
    (":rehydrate", "Restore archive"),
    (":stash", "Stash current input"),
    (":pop", "Pop from stash"),
    (":!", "Shell command"),
    (":suspend", "Suspend for shell"),
    (":pwd", "Show directory"),
    (":cd", "Change directory"),
    (":reload", "Reload app"),
    (":backend", "Set backend"),
    (":prefs", "Preferences"),
    (":edit-config", "Edit config"),
    (":edit-prompt", "Edit prompt"),
    (":debug", "Toggle debug"),
    (":debug-pause", "Pause debug"),
    (":debug-clear", "Clear debug"),
    (":follow", "Toggle follow"),
    (":help", "Show help"),
]


class CompletionPopup(Static):
    """Popup showing command completion candidates."""

    DEFAULT_CSS = """
    CompletionPopup {
        background: $surface;
        border: solid green;
        padding: 0 1;
        width: auto;
        height: auto;
        max-height: 12;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)  # Initialize with empty content
        self._candidates: list[tuple[str, str]] = []
        self._selected_index: int = 0

    def show_candidates(self, candidates: list[tuple[str, str]], selected: int = 0) -> None:
        """Show completion candidates with one highlighted."""
        self._candidates = candidates
        self._selected_index = selected
        self._render_candidates()
        self.display = True

    def hide(self) -> None:
        """Hide the popup."""
        self.display = False
        self._candidates = []

    def _render_candidates(self) -> None:
        """Render the candidate list."""
        if not self._candidates:
            self.update("")
            return

        lines = []
        for i, (cmd, desc) in enumerate(self._candidates):
            if i == self._selected_index:
                # Highlighted
                line = Text(f" {cmd} ", style="reverse")
                line.append(f" {desc}", style="dim")
            else:
                line = Text(f" {cmd} ", style="bold green")
                line.append(f" {desc}", style="dim")
            lines.append(line)

        # Join with newlines
        result = Text()
        for i, line in enumerate(lines):
            if i > 0:
                result.append("\n")
            result.append_text(line)
        self.update(result)


class InputBox(TextArea):
    """Multi-line input box for user messages.

    Features:
    - Auto-expands height as content grows
    - Bounded by max_height (adjustable via drag)
    - Shows scrollbar when content exceeds max_height
    """

    DEFAULT_CSS = """
    InputBox {
        height: auto;
        border: solid $primary;
        background: $surface;
        overflow-y: auto;
    }

    InputBox:focus {
        border: solid $accent;
    }

    InputBox.disabled {
        opacity: 0.5;
    }

    InputBox.command-mode {
        border: solid green;
    }

    InputBox.command-mode:focus {
        border: solid green;
    }
    """

    MIN_HEIGHT = 3
    MAX_HEIGHT_LIMIT = 20
    DEFAULT_MAX_HEIGHT = 5

    max_height = reactive(DEFAULT_MAX_HEIGHT)

    class Submitted(Message):
        """Message sent when user submits input."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    class CompletionChanged(Message):
        """Message sent when completion candidates change."""

        def __init__(self, candidates: list[tuple[str, str]], selected: int, visible: bool) -> None:
            self.candidates = candidates
            self.selected = selected
            self.visible = visible
            super().__init__()

    class StashRequested(Message):
        """Message sent when user wants to stash current input (Ctrl+S)."""

        def __init__(self, content: str, name: str | None = None) -> None:
            self.content = content
            self.name = name
            super().__init__()

    class PopRequested(Message):
        """Message sent when user wants to pop from stash (Ctrl+D)."""
        pass

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._disabled = False
        self._history: list[str] = []
        self._history_index: int = -1
        self._current_input: str = ""
        # Command completion state
        self._completion_candidates: list[tuple[str, str]] = []  # (cmd, description)
        self._completion_index: int = -1
        self._completion_original: str = ""  # Text before starting completion
        self._completion_visible: bool = False  # True while showing completion popup

    def watch_max_height(self, new_max: int) -> None:
        """Update CSS when max_height changes."""
        self.styles.max_height = new_max

    def on_mount(self) -> None:
        """Set initial max-height."""
        self.styles.max_height = self.max_height

    def adjust_max_height(self, delta: int) -> None:
        """Adjust max_height by delta, respecting bounds."""
        new_height = self.max_height - delta  # Negative delta = drag up = increase height
        new_height = max(self.MIN_HEIGHT, min(self.MAX_HEIGHT_LIMIT, new_height))
        self.max_height = new_height

    # Keys that should bubble up to the app (not handled by TextArea)
    APP_KEYS = {"ctrl+t", "ctrl+o", "ctrl+q", "ctrl+r", "ctrl+g", "ctrl+c", "ctrl+s"}

    async def _on_key(self, event: Key) -> None:
        """Intercept key events before TextArea processes them."""
        # Let app-level shortcuts pass through
        if event.key in self.APP_KEYS:
            return  # Don't stop, let it bubble up

        # Escape: close completions first, then clear text, then bubble up
        if event.key == "escape":
            if self._disabled:
                return  # Bubble up to app for cancel
            if self._completion_visible:
                event.prevent_default()
                event.stop()
                self._hide_completions()
                return
            if self.text:
                event.prevent_default()
                event.stop()
                self.clear()
                return
            else:
                return  # Bubble up to app (will focus us anyway)

        if event.key == "enter":
            # Submit on Enter
            event.prevent_default()
            event.stop()
            self._submit()
            return
        if event.key == "shift+enter":
            # Insert newline on Shift+Enter
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        if event.key == "up":
            if self._completion_visible:
                # Cycle up through completions
                event.prevent_default()
                event.stop()
                self._cycle_completion(-1)
                return
            elif not self.text.strip():
                # Cycle back through history when input is empty
                event.prevent_default()
                event.stop()
                self._history_back()
                return
        if event.key == "down":
            if self._completion_visible:
                # Cycle down through completions
                event.prevent_default()
                event.stop()
                self._cycle_completion(1)
                return
            elif self._history_index >= 0:
                # Cycle forward through history
                event.prevent_default()
                event.stop()
                self._history_forward()
                return
        if event.key == "tab" and self._completion_visible:
            # Accept current completion
            event.prevent_default()
            event.stop()
            self._accept_completion()
            return
        await super()._on_key(event)

    def _history_back(self) -> None:
        """Go back in history."""
        if not self._history:
            return
        if self._history_index == -1:
            self._current_input = self.text
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        self.clear()
        self.insert(self._history[self._history_index])

    def _history_forward(self) -> None:
        """Go forward in history."""
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.clear()
            self.insert(self._history[self._history_index])
        else:
            # Return to current input
            self._history_index = -1
            self.clear()
            self.insert(self._current_input)

    def _update_completions(self) -> None:
        """Update completion candidates based on current text.

        Shows all commands but highlights the first one matching the typed prefix.
        """
        current_text = self.text

        if not current_text.startswith(":"):
            self._hide_completions()
            return

        # Get command prefix (text before any space or '=')
        cmd_text = current_text.split(" ")[0].split("=")[0]

        # Always show all commands
        candidates = list(COMMANDS)

        # Find the first matching command to highlight
        selected_index = 0
        for i, (cmd, _) in enumerate(candidates):
            if cmd.startswith(cmd_text):
                selected_index = i
                break

        self._completion_candidates = candidates
        self._completion_original = current_text
        self._completion_index = selected_index
        self._completion_visible = True

        self.post_message(self.CompletionChanged(
            candidates=candidates,
            selected=selected_index,
            visible=True,
        ))

    def _cycle_completion(self, delta: int) -> None:
        """Cycle through completions by delta (-1 for up, 1 for down)."""
        if not self._completion_candidates:
            return

        self._completion_index = (self._completion_index + delta) % len(self._completion_candidates)

        self.post_message(self.CompletionChanged(
            candidates=self._completion_candidates,
            selected=self._completion_index,
            visible=True,
        ))

    def _accept_completion(self) -> None:
        """Accept the currently selected completion."""
        if not self._completion_candidates or self._completion_index < 0:
            return

        candidate_cmd, _ = self._completion_candidates[self._completion_index]

        # Preserve any text after the command (space or =)
        original_cmd = self._completion_original.split(" ")[0].split("=")[0]
        rest = self._completion_original[len(original_cmd):]

        # Add a space after the command if there isn't one
        if not rest:
            rest = " "

        new_text = candidate_cmd + rest

        self.clear()
        self._completion_visible = False  # Prevent update_completions during insert
        self.insert(new_text)
        self._hide_completions()

    def _hide_completions(self) -> None:
        """Hide the completion popup."""
        if self._completion_visible:
            self._completion_visible = False
            self._completion_candidates = []
            self._completion_index = -1
            self.post_message(self.CompletionChanged(
                candidates=[],
                selected=-1,
                visible=False,
            ))

    def _submit(self) -> None:
        """Submit the current input."""
        if self._disabled:
            return
        self._hide_completions()
        value = self.text.strip()
        if value:
            # Add to history (avoid duplicates)
            if not self._history or self._history[-1] != value:
                self._history.append(value)
            self._history_index = -1
            self._current_input = ""
            self.post_message(self.Submitted(value))
            self.clear()

    def set_disabled(self, disabled: bool) -> None:
        """Enable or disable the input box."""
        self._disabled = disabled
        if disabled:
            self.add_class("disabled")
        else:
            self.remove_class("disabled")
            self.focus()

    def _on_text_area_changed(self, event) -> None:
        """Update command-mode class and completions when text changes."""
        if self.text.startswith(":"):
            self.add_class("command-mode")
            # Show/update completions while typing the command (before space/=)
            cmd_part = self.text.split(" ")[0].split("=")[0]
            if cmd_part == self.text:
                # Still typing the command part, show completions
                self._update_completions()
            else:
                # Have space or = after command, hide completions
                self._hide_completions()
        else:
            self.remove_class("command-mode")
            self._hide_completions()
