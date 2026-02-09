"""Review marker widget - shows where a quality review was initiated in the chat log."""

from textual.widgets import Static
from textual.message import Message
from rich.console import RenderableType
from rich.text import Text


class ReviewMarker(Static):
    """Shows where a quality review was initiated in the chat log.

    Displays:
        Review: fix-auth-bug [active]
        Model: claude-sonnet

    When completed:
        Review: fix-auth-bug [completed]
        Model: claude-sonnet | Score: 4.2 | debugging

    Clicking navigates to the review session.
    """

    DEFAULT_CSS = """
    ReviewMarker {
        padding: 0 1;
        margin: 0 0 1 2;
        background: #2a1a3a;
        border-left: thick $secondary;
    }

    ReviewMarker:hover {
        background: #3a2a4a;
    }

    ReviewMarker.hidden {
        display: none;
    }

    ReviewMarker.completed {
        border-left: thick $success;
    }

    ReviewMarker.abandoned {
        border-left: thick $error;
        opacity: 0.6;
    }

    /* Context mode visual indicators */
    ReviewMarker.context-copy {
    }

    ReviewMarker.context-compress {
        background: #2d2a1a;
    }

    ReviewMarker.context-drop {
        opacity: 0.4;
    }
    """

    class ChildClicked(Message):
        """Posted when user clicks to navigate to the review session."""

        def __init__(self, child_session_id: str) -> None:
            super().__init__()
            self.child_session_id = child_session_id

    def __init__(
        self,
        child_session_id: str,
        model_under_review: str,
        status: str = "active",
        overall_score: float = 0.0,
        task_category: str = "",
        task_description: str = "",
        turn_id: int = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.child_session_id = child_session_id
        self.model_under_review = model_under_review
        self.status = status
        self.overall_score = overall_score
        self.task_category = task_category
        self.task_description = task_description
        self.turn_id = turn_id

        if status == "completed":
            self.add_class("completed")
        elif status == "abandoned":
            self.add_class("abandoned")

    def render(self) -> RenderableType:
        # Status indicator
        if self.status == "active":
            status_text = "[magenta][active][/]"
        elif self.status == "completed":
            status_text = "[green][completed][/]"
        elif self.status == "abandoned":
            status_text = "[red][abandoned][/]"
        else:
            status_text = f"[dim][{self.status}][/]"

        # Build the display text
        text = Text()
        text.append(" Review ", style="bold magenta")
        text.append(f"{status_text}")
        text.append("\n")
        text.append(f"Model: ", style="dim")
        text.append(self.model_under_review, style="cyan")

        # Show score and category if completed
        if self.status == "completed" and self.overall_score > 0:
            text.append(f" | Score: ", style="dim")
            # Color code the score
            if self.overall_score >= 4:
                score_style = "green bold"
            elif self.overall_score >= 3:
                score_style = "yellow"
            else:
                score_style = "red"
            text.append(f"{self.overall_score:.1f}", style=score_style)

            if self.task_category:
                text.append(f" | ", style="dim")
                text.append(self.task_category, style="italic")

        # Show task description if available
        if self.task_description:
            text.append("\n")
            text.append(f'"{self.task_description}"', style="dim italic")

        return text

    def on_click(self) -> None:
        """Navigate to the review session when clicked."""
        self.post_message(self.ChildClicked(self.child_session_id))

    def mark_completed(self, score: float, category: str, description: str) -> None:
        """Update status to completed with results."""
        self.status = "completed"
        self.overall_score = score
        self.task_category = category
        self.task_description = description
        self.remove_class("abandoned")
        self.add_class("completed")
        self.refresh()

    def mark_abandoned(self) -> None:
        """Update status to abandoned."""
        self.status = "abandoned"
        self.remove_class("completed")
        self.add_class("abandoned")
        self.refresh()
