"""Modal for renaming a session.

Shown when clicking on the session header in the chat log.
"""

from dataclasses import dataclass
from typing import Optional

from textual.screen import ModalScreen
from textual.widgets import Static, Button, Input, Label
from textual.containers import Vertical, Horizontal


@dataclass
class RenameSessionResult:
    """Result from RenameSessionModal."""
    session_id: str
    new_title: str


class RenameSessionModal(ModalScreen[Optional[RenameSessionResult]]):
    """Modal for renaming a session."""

    DEFAULT_CSS = """
    RenameSessionModal {
        align: center middle;
    }

    #rename-session-dialog {
        width: 60;
        height: auto;
        max-height: 50%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #dialog-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
        color: cyan;
        height: auto;
    }

    #current-info {
        height: auto;
        margin-bottom: 1;
        padding: 0 1;
        background: $surface-darken-1;
        border: solid $primary-darken-2;
    }

    #current-label {
        color: $text-muted;
        text-style: italic;
        height: 1;
    }

    #current-title {
        text-style: bold;
        color: yellow;
        height: auto;
    }

    .field-label {
        margin-top: 1;
        margin-bottom: 0;
        height: 1;
    }

    #title-input {
        margin-bottom: 1;
        width: 100%;
    }

    #buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }

    #buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        session_id: str,
        current_title: str,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.session_id = session_id
        self.current_title = current_title

    def compose(self):
        with Vertical(id="rename-session-dialog"):
            yield Static("Rename Session", id="dialog-title")

            # Show current title info
            with Vertical(id="current-info"):
                yield Static("[dim]Current Title[/]", id="current-label")
                yield Static(f"[bold yellow]{self.current_title or '(untitled)'}[/]", id="current-title")

            # Title input
            yield Label("New Title:", classes="field-label")
            yield Input(
                placeholder="Enter session title...",
                value=self.current_title,
                id="title-input"
            )

            # Buttons
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel-btn", variant="default")
                yield Button("Rename", id="rename-btn", variant="primary")

    def on_mount(self) -> None:
        """Focus and select the title input when modal opens."""
        title_input = self.query_one("#title-input", Input)
        title_input.focus()
        # Select all text
        title_input.selection = (0, len(title_input.value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "rename-btn":
            self._do_rename()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        if event.input.id == "title-input":
            self._do_rename()

    def _do_rename(self) -> None:
        """Process the rename."""
        title_input = self.query_one("#title-input", Input)
        new_title = title_input.value.strip()

        if not new_title:
            self.notify("Title cannot be empty", severity="warning")
            return

        if new_title == self.current_title:
            # No change, just dismiss
            self.dismiss(None)
            return

        self.dismiss(RenameSessionResult(
            session_id=self.session_id,
            new_title=new_title,
        ))

    def action_cancel(self) -> None:
        """Cancel the modal."""
        self.dismiss(None)
