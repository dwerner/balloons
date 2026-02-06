from textual.widgets import Static
from textual.message import Message
from rich.console import RenderableType
from rich.text import Text


class WithWidget(Static):
    """Displays a fork point in parent session - shows where a child session was spawned."""

    DEFAULT_CSS = """
    WithWidget {
        padding: 0 1;
        margin: 0 0 1 2;
        background: #2a1a2a;
        border-left: thick $secondary;
    }

    WithWidget.returned {
        border-left: thick $success;
    }

    WithWidget:hover {
        background: #3a2a3a;
    }

    WithWidget.hidden {
        display: none;
    }

    /* Context mode visual indicators */
    WithWidget.context-copy {
        border-left: thick $success;
    }

    WithWidget.context-compress {
        border-left: thick $warning;
        opacity: 0.85;
    }

    WithWidget.context-drop {
        opacity: 0.4;
        border-left: thick $surface-darken-1;
    }
    """

    class ChildClicked(Message):
        """Fired when user clicks to navigate to child session."""
        def __init__(self, child_session_id: str) -> None:
            self.child_session_id = child_session_id
            super().__init__()

    def __init__(
        self,
        prompt: str,
        child_session_id: str,
        status: str = "active",
        return_condition: str = "manual",
        turn_id: int = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.prompt = prompt
        self.child_session_id = child_session_id
        self.status = status  # "active", "background", "streaming", or "returned"
        self.return_condition = return_condition
        self.turn_id = turn_id
        self._streaming_preview = ""  # Preview of streaming content
        if status == "returned":
            self.add_class("returned")

    def render(self) -> RenderableType:
        # Status indicator
        if self.status == "returned":
            status_icon = "[green]✓[/]"
            status_text = "returned"
        elif self.status == "background":
            status_icon = "[cyan]⋯[/]"
            status_text = "background"
        elif self.status == "streaming":
            status_icon = "[yellow]▶[/]"
            status_text = "streaming"
        else:
            status_icon = "[magenta]→[/]"
            status_text = "active"

        # Condition display
        if self.return_condition == "manual":
            condition_text = ""
        elif self.return_condition == "done":
            condition_text = " [dim](until done)[/]"
        elif self.return_condition.startswith("turns:"):
            n = self.return_condition.split(":")[1]
            condition_text = f" [dim](until {n} turns)[/]"
        else:
            condition_text = f" [dim](until {self.return_condition})[/]"

        # Prompt preview
        prompt_preview = self.prompt[:60] + "..." if len(self.prompt) > 60 else self.prompt
        prompt_preview = prompt_preview.replace("\n", " ")

        text = Text()
        text.append(f"{status_icon} ", style="bold")
        text.append("with ", style="magenta bold")
        text.append(f'"{prompt_preview}"', style="italic")
        text.append(condition_text)
        text.append(f" [{status_text}]", style="dim")

        # Show streaming preview if available
        if self._streaming_preview and self.status == "streaming":
            preview = self._streaming_preview.replace("\n", " ")
            text.append("\n")
            text.append(f"  {preview}", style="dim cyan")
        else:
            text.append("\n")
            text.append("  Click to view child session", style="dim italic")

        return text

    def on_click(self) -> None:
        """Navigate to child session when clicked."""
        self.post_message(self.ChildClicked(self.child_session_id))

    def mark_returned(self) -> None:
        """Update widget to show returned status."""
        self.status = "returned"
        self.add_class("returned")
        self.refresh()

    def update_streaming(self, text: str = "") -> None:
        """Update widget with streaming progress."""
        self.status = "streaming"
        if text:
            self._streaming_preview = text[-50:]  # Keep last 50 chars as preview
        self.refresh()

    def mark_done(self) -> None:
        """Mark background streaming as done (waiting for return)."""
        self.status = "background"
        self._streaming_preview = ""
        self.refresh()
