"""Message stash popup widget.

Allows users to stash draft messages and retrieve them later.
Similar to command completion popup but for stored messages.
"""

from textual.widgets import Static
from textual.message import Message
from textual.events import Key
from rich.text import Text

# Import data models from core
from core.stash import StashedMessage, MessageStash


class StashPopup(Static, can_focus=True):
    """Popup showing stashed messages for selection."""

    DEFAULT_CSS = """
    StashPopup {
        background: $surface;
        border: solid $secondary;
        padding: 0 1;
        min-width: 30;
        height: auto;
        max-height: 14;
    }
    StashPopup:focus {
        border: solid $accent;
    }
    """

    class MessageSelected(Message):
        """Emitted when user selects a stashed message."""
        def __init__(self, message: StashedMessage, index: int) -> None:
            self.message = message
            self.index = index
            super().__init__()

    class MessageDeleted(Message):
        """Emitted when user deletes a stashed message."""
        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    class Closed(Message):
        """Emitted when popup is closed without selection."""
        pass

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)  # Initialize with empty content
        self._messages: list[StashedMessage] = []
        self._selected_index: int = 0

    def show_messages(self, messages: list[StashedMessage]) -> None:
        """Show stash popup with given messages."""
        self._messages = messages
        self._selected_index = 0
        self._refresh_display()
        self.display = True
        self.focus()

    def hide(self) -> None:
        """Hide the popup."""
        self.display = False
        self._messages = []

    def cycle(self, delta: int) -> None:
        """Cycle through messages by delta."""
        if not self._messages:
            return
        self._selected_index = (self._selected_index + delta) % len(self._messages)
        self._refresh_display()

    def select_current(self) -> None:
        """Select the currently highlighted message."""
        if self._messages and 0 <= self._selected_index < len(self._messages):
            self.post_message(self.MessageSelected(
                self._messages[self._selected_index],
                self._selected_index
            ))

    def delete_current(self) -> None:
        """Delete the currently highlighted message."""
        if self._messages and 0 <= self._selected_index < len(self._messages):
            self.post_message(self.MessageDeleted(self._selected_index))

    @property
    def selected_index(self) -> int:
        return self._selected_index

    async def _on_key(self, event: Key) -> None:
        """Handle key events when popup has focus."""
        if event.key == "up":
            event.prevent_default()
            event.stop()
            self.cycle(-1)
        elif event.key == "down":
            event.prevent_default()
            event.stop()
            self.cycle(1)
        elif event.key == "enter":
            event.prevent_default()
            event.stop()
            self.select_current()
        elif event.key in ("delete", "backspace"):
            event.prevent_default()
            event.stop()
            self.delete_current()
        elif event.key == "escape":
            event.prevent_default()
            event.stop()
            self.post_message(self.Closed())

    def _refresh_display(self) -> None:
        """Update the displayed message list."""
        if not self._messages:
            self.update(Text("(empty)", style="dim italic"))
            return

        result = Text()

        # Header with title
        result.append("📋 Stash", style="bold cyan")
        result.append(f" ({len(self._messages)})\n", style="dim")

        # Message list
        for i, msg in enumerate(self._messages):
            name = msg.display_name()
            if i == self._selected_index:
                result.append(" › ", style="bold cyan")
                result.append(f"{name}\n", style="reverse")
            else:
                result.append("   ", style="dim")
                result.append(f"{name}\n", style="")

        # Help line with shortcuts
        result.append("─" * 28 + "\n", style="dim")
        result.append("↑↓", style="bold cyan")
        result.append(" nav  ", style="dim")
        result.append("Enter", style="bold cyan")
        result.append(" pop  ", style="dim")
        result.append("Del", style="bold cyan")
        result.append(" rm  ", style="dim")
        result.append("Esc", style="bold cyan")
        result.append(" close", style="dim")

        self.update(result)
