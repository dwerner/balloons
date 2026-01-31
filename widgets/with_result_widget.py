from textual.widgets import Static
from textual.message import Message
from rich.console import RenderableType
from rich.markdown import Markdown
from rich.text import Text
from rich.panel import Panel


class WithResultWidget(Static):
    """Displays content returned from a child session."""

    DEFAULT_CSS = """
    WithResultWidget {
        padding: 0 1;
        margin: 0 0 1 0;
        background: #1a2a1a;
        border-left: thick $success;
        max-height: 20;
        overflow-y: auto;
    }

    WithResultWidget:hover {
        background: #2a3a2a;
    }

    WithResultWidget.hidden {
        display: none;
    }

    /* Context mode visual indicators */
    WithResultWidget.context-copy {
        border-left: thick $success;
    }

    WithResultWidget.context-compress {
        border-left: thick $warning;
        opacity: 0.85;
    }

    WithResultWidget.context-drop {
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
        content: str,
        child_session_id: str,
        return_prompt: str = "",
        turn_id: int = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._content = content
        self.child_session_id = child_session_id
        self.return_prompt = return_prompt
        self.turn_id = turn_id

    def render(self) -> RenderableType:
        text = Text()

        # Header
        text.append("[green]✓[/] ", style="bold")
        text.append("returned", style="green bold")

        if self.return_prompt:
            prompt_preview = self.return_prompt[:40] + "..." if len(self.return_prompt) > 40 else self.return_prompt
            prompt_preview = prompt_preview.replace("\n", " ")
            text.append(f' "{prompt_preview}"', style="italic dim")

        text.append("\n")
        text.append("  Click to view child session", style="dim italic")
        text.append("\n\n")

        # Content preview
        content_preview = self._content
        if len(content_preview) > 500:
            content_preview = content_preview[:500] + "..."

        text.append(content_preview)

        return text

    def on_click(self) -> None:
        """Navigate to child session when clicked."""
        self.post_message(self.ChildClicked(self.child_session_id))

    @property
    def content(self) -> str:
        return self._content
