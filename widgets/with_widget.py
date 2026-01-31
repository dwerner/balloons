from textual.widgets import Static
from textual.message import Message
from rich.console import RenderableType
from rich.text import Text


class WithWidget(Static):
    """Displays a fork point in parent session - shows where a child session was spawned."""

    DEFAULT_CSS = """
    WithWidget {
        padding: 0 1;
        margin: 0 0 1 0;
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
        self.status = status  # "active" or "returned"
        self.return_condition = return_condition
        self.turn_id = turn_id
        if status == "returned":
            self.add_class("returned")

    def render(self) -> RenderableType:
        # Status indicator
        if self.status == "returned":
            status_icon = "[green]✓[/]"
            status_text = "returned"
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
