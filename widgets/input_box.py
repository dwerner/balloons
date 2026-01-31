from textual.widgets import TextArea
from textual.message import Message
from textual.events import Key


class InputBox(TextArea):
    """Multi-line input box for user messages."""

    DEFAULT_CSS = """
    InputBox {
        height: auto;
        max-height: 5;
        border: solid $primary;
        background: $surface;
    }

    InputBox:focus {
        border: solid $accent;
    }

    InputBox.disabled {
        opacity: 0.5;
    }
    """

    class Submitted(Message):
        """Message sent when user submits input."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._disabled = False
        self._history: list[str] = []
        self._history_index: int = -1
        self._current_input: str = ""

    # Keys that should bubble up to the app (not handled by TextArea)
    APP_KEYS = {"ctrl+t", "ctrl+o", "ctrl+q", "ctrl+r", "ctrl+g", "ctrl+c"}

    async def _on_key(self, event: Key) -> None:
        """Intercept key events before TextArea processes them."""
        # Let app-level shortcuts pass through
        if event.key in self.APP_KEYS:
            return  # Don't stop, let it bubble up

        # Escape: if disabled, always bubble up; if has text, clear it; otherwise bubble up
        if event.key == "escape":
            if self._disabled:
                return  # Bubble up to app for cancel
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
        if event.key == "up" and not self.text.strip():
            # Cycle back through history when input is empty
            event.prevent_default()
            event.stop()
            self._history_back()
            return
        if event.key == "down" and self._history_index >= 0:
            # Cycle forward through history
            event.prevent_default()
            event.stop()
            self._history_forward()
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

    def _submit(self) -> None:
        """Submit the current input."""
        if self._disabled:
            return
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
