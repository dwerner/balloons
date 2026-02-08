"""Message queue popup widget.

Shows queued messages waiting to be processed after streaming completes.
Allows users to view, edit, reorder, or remove queued messages.
"""

from textual.widgets import Static
from textual.message import Message
from textual.events import Key
from rich.text import Text

from session import MessageQueue, QueuedMessage

# Circled numbers for visual ordering
CIRCLED_NUMBERS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]


def get_circled_number(n: int) -> str:
    """Get circled number for 1-based index, fallback to (N) for > 10."""
    if 1 <= n <= 10:
        return CIRCLED_NUMBERS[n - 1]
    return f"({n})"


class MessageQueuePopup(Static, can_focus=True):
    """Popup showing queued messages for management.

    Features:
    - Shows numbered list of pending messages with circled numbers ①②③
    - Checkbox controls ☑/☐ to pause/resume items
    - Paused messages block those behind them (shown as ◌ blocked)
    - Allows editing and removing individual messages
    - Shows preview of message content
    """

    DEFAULT_CSS = """
    MessageQueuePopup {
        background: $surface;
        border-top: solid $warning;
        border-bottom: none;
        border-left: none;
        border-right: none;
        padding: 0 1;
        height: auto;
        max-height: 10;
    }
    MessageQueuePopup:focus {
        border-top: solid $accent;
    }
    """

    class MessageRemoved(Message):
        """Emitted when user removes a queued message."""
        def __init__(self, message_id: str) -> None:
            self.message_id = message_id
            super().__init__()

    class MessagePauseToggled(Message):
        """Emitted when user toggles pause on a message."""
        def __init__(self, message_id: str) -> None:
            self.message_id = message_id
            super().__init__()

    class MessageEditRequested(Message):
        """Emitted when user wants to edit a message."""
        def __init__(self, message_id: str, content: str) -> None:
            self.message_id = message_id
            self.content = content
            super().__init__()

    class QueueCleared(Message):
        """Emitted when user clears all queued messages."""
        pass

    class Closed(Message):
        """Emitted when popup is closed."""
        pass

    class FocusInput(Message):
        """Emitted when user wants to switch focus to input box."""
        pass

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._queue: MessageQueue | None = None
        self._selected_index: int = 0

    def on_mount(self) -> None:
        """Initialize display on mount."""
        self._refresh_display()

    def show_queue(self, queue: MessageQueue, take_focus: bool = False) -> None:
        """Show the queue popup with current queue state.

        The queue popup is always visible (as a status area), even when empty.

        Args:
            queue: The message queue to display
            take_focus: If True, focus the popup for interaction. Default False
                       keeps it as informational overlay.
        """
        self._queue = queue
        self._selected_index = 0 if queue and len(queue) > 0 else -1
        self._refresh_display()
        if take_focus and queue and len(queue) > 0:
            self.focus()

    def hide(self) -> None:
        """Clear the queue content (popup stays visible with empty state)."""
        self._queue = None
        self._selected_index = -1
        self._refresh_display()

    def dismiss(self) -> None:
        """Clear popup content (same as hide)."""
        self.hide()

    def reset_dismissed(self) -> None:
        """No-op for compatibility (dismissed state no longer tracked)."""
        pass

    def toggle(self, queue: MessageQueue) -> bool:
        """Toggle focus to queue popup.

        Returns True if queue has items and was focused, False otherwise.
        """
        if queue and len(queue) > 0:
            self._queue = queue
            self._selected_index = 0 if self._selected_index < 0 else self._selected_index
            self._refresh_display()
            self.focus()
            return True
        return False

    def update_queue(self, queue: MessageQueue) -> None:
        """Update the displayed queue (always visible, even when empty)."""
        self._queue = queue
        if queue and len(queue) > 0:
            if self._selected_index >= len(queue):
                self._selected_index = max(0, len(queue) - 1)
        else:
            self._selected_index = -1
        self._refresh_display()

    def cycle(self, delta: int) -> None:
        """Cycle through messages by delta."""
        if not self._queue or len(self._queue) == 0:
            return
        self._selected_index = (self._selected_index + delta) % len(self._queue)
        self._refresh_display()

    def remove_current(self) -> None:
        """Remove the currently selected message."""
        if self._queue and 0 <= self._selected_index < len(self._queue):
            msg = self._queue.messages[self._selected_index]
            self.post_message(self.MessageRemoved(msg.id))

    def toggle_pause_current(self) -> None:
        """Toggle pause on the currently selected message."""
        if self._queue and 0 <= self._selected_index < len(self._queue):
            msg = self._queue.messages[self._selected_index]
            self.post_message(self.MessagePauseToggled(msg.id))

    def edit_current(self) -> None:
        """Request to edit the currently selected message."""
        if self._queue and 0 <= self._selected_index < len(self._queue):
            msg = self._queue.messages[self._selected_index]
            self.post_message(self.MessageEditRequested(msg.id, msg.content))

    def clear_all(self) -> None:
        """Clear all queued messages."""
        self.post_message(self.QueueCleared())

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
        elif event.key == "tab":
            # Switch focus to input box
            event.prevent_default()
            event.stop()
            self.post_message(self.FocusInput())
        elif event.key in ("delete", "backspace", "x"):
            event.prevent_default()
            event.stop()
            self.remove_current()
        elif event.key == "space":
            # Toggle pause on current message
            event.prevent_default()
            event.stop()
            self.toggle_pause_current()
        elif event.key == "e":
            # Edit current message
            event.prevent_default()
            event.stop()
            self.edit_current()
        elif event.key == "c":
            # Clear all
            event.prevent_default()
            event.stop()
            self.clear_all()
        elif event.key == "q":
            # Close/dismiss popup (not Esc - that's for cancelling stream)
            event.prevent_default()
            event.stop()
            self.dismiss()
            self.post_message(self.Closed())
        # Note: Escape intentionally NOT handled - let it bubble up to cancel streaming

    def _refresh_display(self) -> None:
        """Update the displayed queue list.

        Renders in a vertical format with each message on its own line.
        """
        if not self._queue or len(self._queue) == 0:
            result = Text()
            result.append("📬 Queue", style="dim")
            result.append(" (empty)", style="dim italic")
            result.append("  Type during streaming to queue messages", style="dim italic")
            self.update(result)
            return

        result = Text()

        # Find first paused message to determine blocked state
        first_pause_idx = self._queue.first_pause_index()

        # Header with count and blocked indicator
        result.append("📬 Queue", style="bold yellow")
        result.append(f" ({len(self._queue)})", style="dim")
        if self._queue.is_blocked():
            result.append(" ⏸BLOCKED", style="bold red")
        result.append("  ")
        # Help on header line
        result.append("↑↓", style="dim yellow")
        result.append(" nav ", style="dim")
        result.append("Space", style="dim yellow")
        result.append(" pause ", style="dim")
        result.append("e", style="dim yellow")
        result.append(" edit ", style="dim")
        result.append("x", style="dim yellow")
        result.append(" rm", style="dim")

        # Message items, one per line
        for i, msg in enumerate(self._queue.messages):
            result.append("\n")

            # Preview: first 50 chars, single line (more room in vertical layout)
            preview = msg.content.replace("\n", " ")[:50]
            if len(msg.content) > 50:
                preview += "…"

            # Determine state: paused, blocked (after a paused), or active
            is_paused = msg.paused
            is_blocked = first_pause_idx != -1 and i > first_pause_idx

            # Checkbox: ☑ active, ☐ paused, ◌ blocked
            if is_paused:
                checkbox = "☐"
                checkbox_style = "bold red"
            elif is_blocked:
                checkbox = "◌"
                checkbox_style = "dim"
            else:
                checkbox = "☑"
                checkbox_style = "bold green"

            # Circled number for ordering
            num = get_circled_number(i + 1)

            if i == self._selected_index:
                # Selected item - highlight
                result.append(f"  {checkbox}", style=checkbox_style)
                result.append(f"{num} ", style="bold yellow")
                result.append(f"{preview}", style="reverse")
            else:
                # Unselected item
                if is_blocked:
                    result.append(f"  {checkbox}{num} ", style="dim")
                    result.append(f"{preview}", style="dim")
                elif is_paused:
                    result.append(f"  {checkbox}", style=checkbox_style)
                    result.append(f"{num} ", style="dim red")
                    result.append(f"{preview}", style="dim")
                else:
                    result.append(f"  {checkbox}", style=checkbox_style)
                    result.append(f"{num} ", style="dim")
                    result.append(f"{preview}", style="")

        self.update(result)
