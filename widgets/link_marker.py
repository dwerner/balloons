"""Link marker widget - shows bidirectional links between sessions."""

from textual.widgets import Static
from textual.message import Message
from rich.console import RenderableType
from rich.text import Text


class LinkMarker(Static):
    """Shows a bidirectional link to another session.

    Displays:
        🔗 Link: session-name
        "summary of linked context"

    Clicking navigates to the linked session at the link point.
    """

    DEFAULT_CSS = """
    LinkMarker {
        padding: 0 1;
        margin: 1 0 1 2;
        background: #2a1a3a;
        border-left: thick $secondary;
    }

    LinkMarker:hover {
        background: #3a2a4a;
    }

    LinkMarker.hidden {
        display: none;
    }

    LinkMarker.orphaned {
        border-left: thick $error;
        opacity: 0.6;
    }

    /* Context mode visual indicators */
    LinkMarker.context-copy {
    }

    LinkMarker.context-compress {
        background: #2d2a1a;
    }

    LinkMarker.context-drop {
        opacity: 0.4;
    }
    """

    class LinkedSessionClicked(Message):
        """Posted when user clicks to navigate to the linked session."""

        def __init__(self, linked_session_id: str, link_point: int) -> None:
            super().__init__()
            self.linked_session_id = linked_session_id
            self.link_point = link_point

    def __init__(
        self,
        summary: str,
        linked_session_id: str,
        linked_session_name: str,
        link_point: int,
        turn_id: int = 0,
        is_orphaned: bool = False,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.summary = summary
        self.linked_session_id = linked_session_id
        self.linked_session_name = linked_session_name
        self.link_point = link_point
        self.turn_id = turn_id
        self.is_orphaned = is_orphaned

        if is_orphaned:
            self.add_class("orphaned")

    def render(self) -> RenderableType:
        text = Text()

        if self.is_orphaned:
            text.append("🔗 Link: ", style="bold dim")
            text.append("[deleted]", style="red dim")
            text.append("\n")
            text.append(f'"{self.summary}"', style="dim italic strikethrough")
        else:
            text.append("🔗 Link: ", style="bold magenta")
            text.append(self.linked_session_name, style="cyan bold")
            text.append("\n")
            text.append(f'"{self.summary}"', style="dim italic")

        return text

    def on_click(self) -> None:
        """Navigate to the linked session when clicked."""
        if not self.is_orphaned:
            self.post_message(self.LinkedSessionClicked(
                self.linked_session_id,
                self.link_point
            ))

    def mark_orphaned(self) -> None:
        """Mark this link as orphaned (target session deleted)."""
        self.is_orphaned = True
        self.add_class("orphaned")
        self.refresh()
