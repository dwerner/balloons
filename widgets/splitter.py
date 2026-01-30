from textual.widgets import Static
from textual.events import MouseDown, MouseMove, MouseUp
from textual.message import Message
from textual.reactive import reactive


class VerticalSplitter(Static):
    """A draggable vertical splitter between panes."""

    DEFAULT_CSS = """
    VerticalSplitter {
        width: 1;
        height: 100%;
        background: $primary;
    }

    VerticalSplitter:hover {
        background: $accent;
    }

    VerticalSplitter.dragging {
        background: $accent;
    }
    """

    class Resized(Message):
        """Message sent when splitter is dragged."""
        def __init__(self, delta_x: int) -> None:
            self.delta_x = delta_x
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__("│", **kwargs)
        self._dragging = False
        self._drag_start_x = 0

    def on_mouse_down(self, event: MouseDown) -> None:
        self._dragging = True
        self._drag_start_x = event.screen_x
        self.add_class("dragging")
        self.capture_mouse()
        event.stop()

    def on_mouse_move(self, event: MouseMove) -> None:
        if self._dragging:
            delta = event.screen_x - self._drag_start_x
            if delta != 0:
                self.post_message(self.Resized(delta))
                self._drag_start_x = event.screen_x
            event.stop()

    def on_mouse_up(self, event: MouseUp) -> None:
        if self._dragging:
            self._dragging = False
            self.remove_class("dragging")
            self.release_mouse()
            event.stop()
