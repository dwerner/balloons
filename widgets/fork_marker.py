"""Fork marker widget - shows where a fork was created in the chat log."""

from textual.widgets import Static
from textual.message import Message
from rich.console import RenderableType
from rich.text import Text


class ForkMarker(Static):
    """Shows where a fork was created in the chat log.

    Displays:
        🔀 Fork: auth-bug [active]
        "investigate the auth bug"

    Clicking navigates to the fork.
    """

    DEFAULT_CSS = """
    ForkMarker {
        padding: 0 1;
        margin: 1 0 1 2;
        background: #1a2a3a;
        border-left: thick $warning;
    }

    ForkMarker:hover {
        background: #2a3a4a;
    }

    ForkMarker.hidden {
        display: none;
    }

    ForkMarker.merged {
        border-left: thick $success;
    }

    /* Context mode visual indicators - use background color to avoid layout shifts */
    /* COPY is the default - no special styling needed */
    ForkMarker.context-copy {
    }

    ForkMarker.context-compress {
        background: #2d2a1a;  /* Yellow/orange tint for summarize */
    }

    ForkMarker.context-drop {
        opacity: 0.4;
    }
    """

    class ChildClicked(Message):
        """Posted when user clicks to navigate to the fork."""

        def __init__(self, child_session_id: str) -> None:
            super().__init__()
            self.child_session_id = child_session_id

    def __init__(
        self,
        prompt: str,
        child_session_id: str,
        fork_name: str,
        status: str = "active",
        turn_id: int = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.prompt = prompt
        self.child_session_id = child_session_id
        self.fork_name = fork_name
        self.status = status
        self.turn_id = turn_id

        if status == "merged":
            self.add_class("merged")

    def render(self) -> RenderableType:
        # Status indicator
        if self.status == "active":
            status_text = "[yellow][active][/]"
        elif self.status == "merged":
            status_text = "[green][merged ✓][/]"
        elif self.status == "background":
            status_text = "[blue][background][/]"
        else:
            status_text = f"[dim][{self.status}][/]"

        # Build the display text
        text = Text()
        text.append("🔀 Fork: ", style="bold")
        text.append(self.fork_name, style="cyan bold")
        text.append(f" {status_text}")
        text.append("\n")
        text.append(f'"{self.prompt}"', style="dim italic")

        return text

    def on_click(self) -> None:
        """Navigate to the fork when clicked."""
        self.post_message(self.ChildClicked(self.child_session_id))

    def mark_merged(self) -> None:
        """Update status to merged."""
        self.status = "merged"
        self.add_class("merged")
        self.refresh()

    def update_streaming(self, text: str) -> None:
        """Update for background streaming (if needed)."""
        # For background forks, could show progress here
        pass

    def mark_done(self) -> None:
        """Mark background fork as done."""
        if self.status == "background":
            self.status = "active"
            self.refresh()
