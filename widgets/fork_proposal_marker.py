"""Fork proposal marker widget - inline proposal with Accept/Reject buttons."""

from textual.widgets import Static, Button
from textual.containers import Vertical, Horizontal
from textual.message import Message
from rich.console import RenderableType
from rich.text import Text
from rich.markup import escape as escape_markup

from models import ContextAssignmentData, ForkBindingData


class ForkProposalMarker(Static):
    """Shows a fork proposal inline in the chat log with Accept/Reject buttons.

    This replaces the modal dialog approach, allowing proposals to persist
    in the conversation history and be acted upon even after switching sessions.

    Displays:
        Fork Proposal: implement-cache-layer
        "What this fork will accomplish"

        Context:
        [+] 0-2 COPY - Contains requirements
        [~] 3-5 COMPRESS - Background exploration
        [-] 6-7 DROP - Failed approaches

        Prompt: "Let's start by..."

        [Accept] [Reject]
    """

    DEFAULT_CSS = """
    ForkProposalMarker {
        padding: 1 1;
        margin: 0 0 1 2;
        background: #1a2a3a;
        border: thick $accent;
    }

    ForkProposalMarker.hidden {
        display: none;
    }

    ForkProposalMarker.accepted {
        border: thick $success;
        opacity: 0.7;
    }

    ForkProposalMarker.rejected {
        border: thick $error;
        opacity: 0.5;
    }

    ForkProposalMarker .proposal-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 0;
    }

    ForkProposalMarker .proposal-description {
        color: $text-muted;
        margin-bottom: 1;
    }

    ForkProposalMarker .section-title {
        text-style: bold;
        color: $primary;
        margin-top: 1;
    }

    ForkProposalMarker .context-item {
        padding-left: 1;
    }

    ForkProposalMarker .context-copy {
        color: $success;
    }

    ForkProposalMarker .context-compress {
        color: $warning;
    }

    ForkProposalMarker .context-drop {
        color: $text-muted;
    }

    ForkProposalMarker .prompt-preview {
        background: $surface-darken-1;
        padding: 0 1;
        margin-top: 1;
        border: solid $primary-darken-2;
    }

    ForkProposalMarker .button-row {
        margin-top: 1;
        height: auto;
    }

    ForkProposalMarker .button-row Button {
        margin: 0 1 0 0;
    }

    ForkProposalMarker .accept-btn {
        background: $success;
    }

    ForkProposalMarker .reject-btn {
        background: $error-darken-1;
    }

    ForkProposalMarker .status-text {
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
    }

    ForkProposalMarker .binding-info {
        color: $secondary;
        margin-top: 1;
    }

    /* Context mode visual indicators */
    ForkProposalMarker.context-copy {
    }

    ForkProposalMarker.context-compress {
        background: #2d2a1a;
    }

    ForkProposalMarker.context-drop {
        opacity: 0.4;
    }
    """

    class Accepted(Message):
        """Posted when user accepts the fork proposal."""

        def __init__(
            self,
            proposal_id: str,
            name: str,
            description: str,
            context_plan: list[ContextAssignmentData],
            initial_prompt: str,
            bind_to: ForkBindingData | None,
            bind_to_inherit: bool,
            turn_id: int,
        ) -> None:
            super().__init__()
            self.proposal_id = proposal_id
            self.name = name
            self.description = description
            self.context_plan = context_plan
            self.initial_prompt = initial_prompt
            self.bind_to = bind_to
            self.bind_to_inherit = bind_to_inherit
            self.turn_id = turn_id

    class Rejected(Message):
        """Posted when user rejects the fork proposal."""

        def __init__(self, proposal_id: str, turn_id: int) -> None:
            super().__init__()
            self.proposal_id = proposal_id
            self.turn_id = turn_id

    def __init__(
        self,
        proposal_id: str,
        name: str,
        description: str,
        context_plan: list[ContextAssignmentData],
        initial_prompt: str = "",
        bind_to: ForkBindingData | None = None,
        bind_to_inherit: bool = False,
        status: str = "pending",
        turn_id: int = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.proposal_id = proposal_id
        self.fork_name = name  # Can't use 'name' - conflicts with Widget.name property
        self.description = description
        self.context_plan = context_plan
        self.initial_prompt = initial_prompt
        self.bind_to = bind_to
        self.bind_to_inherit = bind_to_inherit
        self.status = status
        self.turn_id = turn_id

        if status == "accepted":
            self.add_class("accepted")
        elif status == "rejected":
            self.add_class("rejected")

    def compose(self):
        """Build the widget structure."""
        yield Static(f"Fork Proposal: {self.fork_name}", classes="proposal-title")
        yield Static(self.description, classes="proposal-description")

        # Show binding info if present
        if self.bind_to_inherit:
            yield Static("Binding: [italic]inherit from parent[/italic]", classes="binding-info")
        elif self.bind_to:
            binding_text = f"Binding: {self.bind_to.entity_type} {self.bind_to.entity_id[:8]}... (role: {self.bind_to.role})"
            yield Static(binding_text, classes="binding-info")

        # Context plan section
        if self.context_plan:
            yield Static(f"Context ({len(self.context_plan)} items)", classes="section-title")
            for assignment in self.context_plan:
                mode_icons = {"copy": "+", "compress": "~", "drop": "-"}
                icon = mode_icons.get(assignment.mode.lower(), "?")
                mode_class = f"context-{assignment.mode.lower()}"
                reason_part = f" - {escape_markup(assignment.reason)}" if assignment.reason else ""
                label = f"[{icon}] {escape_markup(assignment.exchange_range)} {assignment.mode.upper()}{reason_part}"
                yield Static(label, classes=f"context-item {mode_class}")

        # Initial prompt preview
        if self.initial_prompt:
            yield Static("Prompt", classes="section-title")
            # Truncate long prompts for display
            prompt_preview = self.initial_prompt
            if len(prompt_preview) > 200:
                prompt_preview = prompt_preview[:200] + "..."
            yield Static(prompt_preview, classes="prompt-preview")

        # Buttons or status
        if self.status == "pending":
            with Horizontal(classes="button-row"):
                yield Button("Accept", variant="success", classes="accept-btn", id=f"accept-{self.proposal_id}")
                yield Button("Reject", variant="error", classes="reject-btn", id=f"reject-{self.proposal_id}")
        elif self.status == "accepted":
            yield Static("[green]Accepted[/green]", classes="status-text")
        elif self.status == "rejected":
            yield Static("[red]Rejected[/red]", classes="status-text")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Accept/Reject button clicks."""
        button_id = event.button.id or ""

        if button_id.startswith("accept-"):
            self.post_message(self.Accepted(
                proposal_id=self.proposal_id,
                name=self.fork_name,
                description=self.description,
                context_plan=self.context_plan,
                initial_prompt=self.initial_prompt,
                bind_to=self.bind_to,
                bind_to_inherit=self.bind_to_inherit,
                turn_id=self.turn_id,
            ))
            # Update visual state
            self.status = "accepted"
            self.add_class("accepted")
            self.refresh(recompose=True)

        elif button_id.startswith("reject-"):
            self.post_message(self.Rejected(
                proposal_id=self.proposal_id,
                turn_id=self.turn_id,
            ))
            # Update visual state
            self.status = "rejected"
            self.add_class("rejected")
            self.refresh(recompose=True)

    def mark_accepted(self) -> None:
        """Mark the proposal as accepted."""
        self.status = "accepted"
        self.add_class("accepted")
        self.refresh(recompose=True)

    def mark_rejected(self) -> None:
        """Mark the proposal as rejected."""
        self.status = "rejected"
        self.add_class("rejected")
        self.refresh(recompose=True)
