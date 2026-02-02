from dataclasses import dataclass
from typing import Optional

from textual.screen import ModalScreen
from textual.widgets import Static, Button, TextArea, DataTable, Input, Label
from textual.containers import Vertical, Horizontal

from claude_runner import ClaudeRunner
from tokenizer import count_tokens
from core.commands import COMMAND_DOCS


@dataclass
class NewSessionResult:
    """Result from NewSessionModal."""
    title: str
    prompt: str


class NewSessionModal(ModalScreen[Optional[NewSessionResult]]):
    """Modal for creating a new session with optional title and prompt."""

    DEFAULT_CSS = """
    NewSessionModal {
        align: center middle;
    }

    #new-session-dialog {
        width: 60;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #new-session-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    .field-label {
        margin-top: 1;
        margin-bottom: 0;
    }

    #title-input, #prompt-input {
        margin-bottom: 1;
    }

    #new-session-buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }

    #new-session-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self):
        with Vertical(id="new-session-dialog"):
            yield Static("New Session", id="new-session-title")
            yield Label("Title (optional):", classes="field-label")
            yield Input(placeholder="Session title...", id="title-input")
            yield Label("Initial prompt (optional):", classes="field-label")
            yield Input(placeholder="Start with a prompt...", id="prompt-input")
            with Horizontal(id="new-session-buttons"):
                yield Button("Cancel", id="cancel-btn", variant="default")
                yield Button("Create", id="create-btn", variant="primary")

    def on_mount(self) -> None:
        """Focus the title input when modal opens."""
        self.query_one("#title-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields."""
        if event.input.id == "title-input":
            # Move focus to prompt input
            self.query_one("#prompt-input", Input).focus()
        elif event.input.id == "prompt-input":
            # Submit the form
            self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        """Submit the form with current values."""
        title = self.query_one("#title-input", Input).value.strip()
        prompt = self.query_one("#prompt-input", Input).value.strip()
        self.dismiss(NewSessionResult(title=title, prompt=prompt))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ContextPreview(ModalScreen[None]):
    """Modal showing the context that will be sent to Claude."""

    DEFAULT_CSS = """
    ContextPreview {
        align: center middle;
    }

    #dialog {
        width: 80%;
        height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #context-text {
        height: 1fr;
        border: solid $primary;
    }

    #stats {
        height: auto;
        padding: 1 0;
        color: $text-muted;
    }

    #buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
    ]

    def __init__(self, messages: list, pending_prompt: str = "", **kwargs):
        super().__init__(**kwargs)
        self._messages = messages
        self._pending_prompt = pending_prompt

    def compose(self):
        # Build the context string
        if self._pending_prompt:
            context = ClaudeRunner.build_context(self._messages, self._pending_prompt)
        elif self._messages:
            # Show existing context without new prompt
            parts = []
            for msg in self._messages:
                prefix = "User" if msg.role == "user" else "Assistant"
                parts.append(f"{prefix}: {msg.content}")
            context = "\n\n".join(parts)
        else:
            context = "(empty - no messages yet)"

        # Token count using tiktoken
        token_count = count_tokens(context)

        with Vertical(id="dialog"):
            yield Static("Context Preview", id="title")
            yield TextArea(context, read_only=True, id="context-text")
            yield Static(f"{token_count:,} tokens", id="stats")
            with Horizontal(id="buttons"):
                yield Button("Close", id="close-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class ConfirmDialog(ModalScreen[bool]):
    """Simple confirmation dialog that returns True/False."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }

    #confirm-dialog {
        width: 50;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #confirm-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #confirm-message {
        text-align: center;
        padding: 1 0;
    }

    #confirm-buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }

    #confirm-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, title: str, message: str, **kwargs):
        super().__init__(**kwargs)
        self._title = title
        self._message = message

    def compose(self):
        with Vertical(id="confirm-dialog"):
            yield Static(self._title, id="confirm-title")
            yield Static(self._message, id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", id="cancel-btn", variant="default")
                yield Button("Delete", id="confirm-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class HelpModal(ModalScreen[None]):
    """Modal showing all available commands."""

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }

    #help-dialog {
        width: 80;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #help-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #help-table {
        height: auto;
        max-height: 20;
    }

    #help-buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def compose(self):
        with Vertical(id="help-dialog"):
            yield Static("Commands", id="help-title")
            table = DataTable(id="help-table", cursor_type="row")
            table.add_columns("Command", "Description")
            for cmd, desc in COMMAND_DOCS:
                table.add_row(cmd, desc)
            yield table
            with Horizontal(id="help-buttons"):
                yield Button("Close", id="close-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
