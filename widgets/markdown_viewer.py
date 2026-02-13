"""Modal markdown viewer using Textual's Markdown widget."""

from pathlib import Path

from textual.screen import ModalScreen
from textual.widgets import Static, Button, Markdown
from textual.containers import Vertical, Horizontal, VerticalScroll


class MarkdownViewerModal(ModalScreen[None]):
    """Modal for viewing markdown files with full rendering.

    Displays markdown content using Textual's native Markdown widget,
    which supports syntax highlighting, tables, headers, etc.
    """

    DEFAULT_CSS = """
    MarkdownViewerModal {
        align: center middle;
    }

    #markdown-dialog {
        width: 90%;
        height: 90%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #markdown-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
        color: $primary;
    }

    #markdown-path {
        text-align: center;
        color: $text-muted;
        padding-bottom: 1;
    }

    #markdown-scroll {
        height: 1fr;
        border: solid $primary-darken-2;
        padding: 1;
    }

    #markdown-content {
        width: 100%;
    }

    #markdown-buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }

    #markdown-buttons Button {
        margin: 0 1;
    }

    /* Markdown styling overrides */
    MarkdownViewerModal Markdown {
        padding: 0 1;
    }

    MarkdownViewerModal MarkdownH1 {
        color: $primary;
        text-style: bold;
        padding: 0;
        margin: 0 0 1 0;
    }

    MarkdownViewerModal MarkdownH2 {
        color: $secondary;
        text-style: bold;
        padding: 0;
        margin: 1 0 0 0;
    }

    MarkdownViewerModal MarkdownH3 {
        color: $accent;
        text-style: bold;
        padding: 0;
        margin: 1 0 0 0;
    }

    MarkdownViewerModal MarkdownBulletList {
        margin: 0 0 0 2;
        padding: 0;
    }

    MarkdownViewerModal MarkdownOrderedList {
        margin: 0 0 0 2;
        padding: 0;
    }

    MarkdownViewerModal MarkdownTable {
        margin: 1 0;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(
        self,
        content: str | None = None,
        file_path: Path | str | None = None,
        title: str = "Markdown Viewer",
        **kwargs
    ):
        """Initialize the markdown viewer.

        Args:
            content: Markdown content to display. If not provided, file_path must be set.
            file_path: Path to a markdown file to load. Ignored if content is provided.
            title: Title to display at the top of the modal.
        """
        super().__init__(**kwargs)
        self._content = content
        self._file_path = Path(file_path) if file_path else None
        self._title = title

        # Load from file if no content provided
        if self._content is None and self._file_path:
            self._content = self._file_path.read_text(encoding="utf-8")
        elif self._content is None:
            self._content = "*No content to display*"

    def compose(self):
        with Vertical(id="markdown-dialog"):
            yield Static(self._title, id="markdown-title")

            # Show file path if provided
            if self._file_path:
                yield Static(str(self._file_path), id="markdown-path")

            with VerticalScroll(id="markdown-scroll"):
                yield Markdown(self._content, id="markdown-content")

            with Horizontal(id="markdown-buttons"):
                yield Button("Close", id="close-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
