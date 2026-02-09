"""Message queue popup widget.

Shows queued messages waiting to be processed after streaming completes.
Allows users to view, edit, reorder, or remove queued messages.

This widget observes QueueState and renders from QueueSnapshot, following
the MVC pattern used by TreeState/TaskState.
"""

from textual.widgets import Static
from textual.message import Message
from textual.events import Key
from rich.text import Text

from core.queue_state import get_queue_state, QueueEvent, QueueSnapshot, QueuedMessageSnapshot

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

    This widget observes QueueState and re-renders when state changes.
    Selection is ID-based to avoid invalidation when messages are removed.
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
        # Current snapshot for rendering (immutable, from QueueState)
        self._snapshot: QueueSnapshot | None = None
        # ID-based selection (stable across removals)
        self._selected_message_id: str | None = None
        # QueueState observer registration
        self._queue_state = get_queue_state()

    def on_mount(self) -> None:
        """Initialize display and subscribe to queue state changes."""
        self._queue_state.add_observer(self._on_queue_event)
        self._refresh_display()

    def on_unmount(self) -> None:
        """Unsubscribe from queue state changes."""
        self._queue_state.remove_observer(self._on_queue_event)

    async def _on_queue_event(
        self,
        event: QueueEvent,
        snapshot: QueueSnapshot,
        data: dict,
    ) -> None:
        """Handle queue state change events.

        Called by QueueState when any mutation occurs. Updates our
        snapshot and re-renders.
        """
        # Store the new snapshot
        self._snapshot = snapshot

        # Handle selection updates based on event type
        if event == QueueEvent.MESSAGE_REMOVED:
            removed_id = data.get("message_id")
            if self._selected_message_id == removed_id:
                # Selected message was removed - move to next or previous
                self._select_nearest_message(snapshot)
        elif event == QueueEvent.QUEUE_CLEARED:
            self._selected_message_id = None
        elif event == QueueEvent.MESSAGE_ADDED:
            # Select the newly added message if nothing selected
            if not self._selected_message_id and snapshot.messages:
                self._selected_message_id = snapshot.messages[-1].id
        elif event == QueueEvent.SESSION_CHANGED:
            # Reset selection on session switch
            if snapshot.messages:
                self._selected_message_id = snapshot.messages[0].id
            else:
                self._selected_message_id = None
        elif event == QueueEvent.FULL_REBUILD:
            # Loaded from persistence - select first if nothing selected
            if snapshot.messages and not self._selected_message_id:
                self._selected_message_id = snapshot.messages[0].id
            elif not snapshot.messages:
                self._selected_message_id = None

        self._refresh_display()

    def _select_nearest_message(self, snapshot: QueueSnapshot) -> None:
        """Select the nearest message after current selection was removed."""
        if not snapshot.messages:
            self._selected_message_id = None
            return

        # Just select the first message for simplicity
        # A more sophisticated approach would track the previous index
        self._selected_message_id = snapshot.messages[0].id

    def _get_selected_index(self) -> int:
        """Get the index of the currently selected message, or -1."""
        if not self._snapshot or not self._selected_message_id:
            return -1
        return self._snapshot.get_message_index(self._selected_message_id)

    def _get_selected_message(self) -> QueuedMessageSnapshot | None:
        """Get the currently selected message snapshot."""
        if not self._snapshot or not self._selected_message_id:
            return None
        return self._snapshot.get_message(self._selected_message_id)

    # Legacy methods for compatibility (app.py may call these during transition)

    def show_queue(self, queue, take_focus: bool = False) -> None:
        """Legacy: Show the queue popup with current queue state.

        This method is deprecated. The popup now auto-updates via observer.
        """
        # No-op for legacy compatibility - popup auto-updates via observer
        if take_focus and self._snapshot and len(self._snapshot) > 0:
            self.focus()

    def hide(self) -> None:
        """Clear the queue content (popup stays visible with empty state)."""
        self._snapshot = None
        self._selected_message_id = None
        self._refresh_display()

    def dismiss(self) -> None:
        """Clear popup content (same as hide)."""
        self.hide()

    def reset_dismissed(self) -> None:
        """No-op for compatibility (dismissed state no longer tracked)."""
        pass

    def toggle(self, queue=None) -> bool:
        """Toggle focus to queue popup.

        Returns True if queue has items and was focused, False otherwise.
        """
        if self._snapshot and len(self._snapshot) > 0:
            if not self._selected_message_id:
                self._selected_message_id = self._snapshot.messages[0].id
            self._refresh_display()
            self.focus()
            return True
        return False

    def update_queue(self, queue) -> None:
        """Legacy: Update the displayed queue.

        This method is deprecated. The popup now auto-updates via observer.
        """
        # No-op for legacy compatibility - popup auto-updates via observer
        pass

    def cycle(self, delta: int) -> None:
        """Cycle through messages by delta."""
        if not self._snapshot or len(self._snapshot) == 0:
            return

        messages = self._snapshot.messages
        current_idx = self._get_selected_index()
        if current_idx < 0:
            current_idx = 0

        new_idx = (current_idx + delta) % len(messages)
        self._selected_message_id = messages[new_idx].id
        self._refresh_display()

    def remove_current(self) -> None:
        """Remove the currently selected message."""
        msg = self._get_selected_message()
        if msg:
            self.post_message(self.MessageRemoved(msg.id))

    def toggle_pause_current(self) -> None:
        """Toggle pause on the currently selected message."""
        msg = self._get_selected_message()
        if msg:
            self.post_message(self.MessagePauseToggled(msg.id))

    def edit_current(self) -> None:
        """Request to edit the currently selected message."""
        msg = self._get_selected_message()
        if msg:
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

        Renders from the current QueueSnapshot in a vertical format
        with each message on its own line.
        """
        if not self._snapshot or len(self._snapshot) == 0:
            result = Text()
            result.append("📬 Queue", style="dim")
            result.append(" (empty)", style="dim italic")
            result.append("  Shows prompts you submit while streaming", style="dim italic")
            self.update(result)
            return

        result = Text()
        snapshot = self._snapshot
        selected_idx = self._get_selected_index()

        # Header with count and blocked indicator
        result.append("📬 Queue", style="bold yellow")
        result.append(f" ({len(snapshot)})", style="dim")
        if snapshot.is_blocked:
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

        # Calculate available width for message preview
        # Account for: 2 spaces indent + checkbox + circled number + space + padding
        # Prefix is "  ☑① " which is about 6 chars, plus 2 for padding
        prefix_width = 8
        available_width = max(20, self.size.width - prefix_width)

        # Message items, one per line
        first_pause_idx = snapshot.first_pause_index
        for i, msg in enumerate(snapshot.messages):
            result.append("\n")

            # Preview: fill available width, single line
            preview = msg.content.replace("\n", " ")[:available_width]
            if len(msg.content) > available_width:
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

            if i == selected_idx:
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
