"""MergedTo marker widget - shows that this fork was merged to its parent."""

from textual.widgets import Static
from textual.message import Message
from rich.console import RenderableType
from rich.text import Text


class MergedToMarker(Static):
    """Shows that this fork was merged back to its parent.

    Displays:
        ➡️ Merged to: parent-session-name
        Summary of what was accomplished
        Files changed: file1.py, file2.py
        ✓ Key accomplishment 1
        ✓ Key accomplishment 2

    Clicking navigates to the parent session.
    """

    DEFAULT_CSS = """
    MergedToMarker {
        padding: 0 1;
        margin: 0 0 1 2;
        background: #1a3a1a;
        border-left: thick $success;
    }

    MergedToMarker:hover {
        background: #2a4a2a;
    }

    MergedToMarker.hidden {
        display: none;
    }

    /* Context mode visual indicators */
    MergedToMarker.context-copy {
    }

    MergedToMarker.context-compress {
        background: #2d2a1a;
    }

    MergedToMarker.context-drop {
        opacity: 0.4;
    }
    """

    class ParentClicked(Message):
        """Posted when user clicks to navigate to the parent session."""

        def __init__(self, parent_session_id: str) -> None:
            super().__init__()
            self.parent_session_id = parent_session_id

    def __init__(
        self,
        message: str,
        parent_session_id: str,
        parent_name: str = "",
        parent_turn: int = 0,
        merge_id: str = "",
        files_changed: list[str] | None = None,
        key_accomplishments: list[str] | None = None,
        reason: str = "",
        turn_id: int = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.message = message
        self.parent_session_id = parent_session_id
        self.parent_name = parent_name or parent_session_id[:8]
        self.parent_turn = parent_turn
        self.merge_id = merge_id
        self.files_changed = files_changed or []
        self.key_accomplishments = key_accomplishments or []
        self.reason = reason
        self.turn_id = turn_id

    def render(self) -> RenderableType:
        # Build the display text
        text = Text()
        text.append("➡️ Merged to: ", style="bold green")
        text.append(self.parent_name, style="cyan bold")
        text.append("\n\n")

        # Summary
        if self.message:
            text.append(self.message, style="")
            text.append("\n")

        # Files changed
        if self.files_changed:
            text.append("\n")
            text.append("Files: ", style="dim")
            text.append(", ".join(self.files_changed), style="yellow")

        # Key accomplishments
        if self.key_accomplishments:
            text.append("\n")
            for accomplishment in self.key_accomplishments:
                text.append("\n  ✓ ", style="green")
                text.append(accomplishment, style="")

        return text

    def on_click(self) -> None:
        """Navigate to the parent when clicked."""
        self.post_message(self.ParentClicked(self.parent_session_id))
