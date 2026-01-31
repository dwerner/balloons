"""Merge marker widget - shows where a fork was merged back in the chat log."""

from textual.widgets import Static
from textual.message import Message
from rich.console import RenderableType
from rich.text import Text
from rich.markdown import Markdown
from rich.panel import Panel


class MergeMarker(Static):
    """Shows where a fork was merged back in the chat log.

    Displays:
        ⬅️ Merged from: auth-bug
        "Found the bug in JWT validation..."

    Clicking navigates to the (now read-only) fork.
    """

    DEFAULT_CSS = """
    MergeMarker {
        padding: 0 1;
        margin: 1 0;
        background: #1a3a1a;
        border-left: thick $success;
    }

    MergeMarker:hover {
        background: #2a4a2a;
    }

    MergeMarker.hidden {
        display: none;
    }

    /* Context mode visual indicators - use background color to avoid layout shifts */
    /* COPY is the default - no special styling needed */
    MergeMarker.context-copy {
    }

    MergeMarker.context-compress {
        background: #2d2a1a;  /* Yellow/orange tint for summarize */
    }

    MergeMarker.context-drop {
        opacity: 0.4;
    }
    """

    class ChildClicked(Message):
        """Posted when user clicks to navigate to the merged fork."""

        def __init__(self, child_session_id: str) -> None:
            super().__init__()
            self.child_session_id = child_session_id

    def __init__(
        self,
        message: str,
        child_session_id: str,
        fork_name: str,
        turn_id: int = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.message = message
        self.child_session_id = child_session_id
        self.fork_name = fork_name
        self.turn_id = turn_id

    def render(self) -> RenderableType:
        # Build the display text
        text = Text()
        text.append("⬅️ Merged from: ", style="bold green")
        text.append(self.fork_name, style="cyan bold")
        text.append("\n\n")
        text.append(self.message, style="")

        return text

    def on_click(self) -> None:
        """Navigate to the fork when clicked."""
        self.post_message(self.ChildClicked(self.child_session_id))
