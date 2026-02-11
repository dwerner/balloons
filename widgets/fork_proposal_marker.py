"""Fork proposal marker widget - inline proposal with Accept/Reject buttons."""

from textual.widgets import Static, Button
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.message import Message

from models import ContextAssignmentData, ForkBindingData, ExchangeInfo
from .context_plan_tree import ContextPlanTree, ContextPlanTreeStatic


class ForkProposalMarker(Vertical):
    """Shows a fork proposal inline in the chat log with Accept/Reject buttons.

    This replaces the modal dialog approach, allowing proposals to persist
    in the conversation history and be acted upon even after switching sessions.

    Features:
    - Interactive context tree for pending proposals (click/space to toggle modes)
    - Scrollable prompt preview for long prompts
    - Static view for already-resolved proposals
    """

    DEFAULT_CSS = """
    ForkProposalMarker {
        padding: 1 1;
        margin: 0 0 1 2;
        background: #1a2a3a;
        border: thick $accent;
        height: auto;
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
        margin-bottom: 0;
    }

    ForkProposalMarker .prompt-scroll {
        max-height: 8;
        height: auto;
        background: $surface-darken-1;
        border: solid $primary-darken-2;
        margin-top: 1;
        padding: 0 1;
    }

    ForkProposalMarker .prompt-text {
        width: 100%;
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

    ForkProposalMarker .edit-hint {
        color: $text-muted;
        text-style: italic;
        margin-top: 0;
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
        all_exchanges: list[ExchangeInfo] | None = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.proposal_id = proposal_id
        self.fork_name = name  # Can't use 'name' - conflicts with Widget.name property
        self.description = description
        self.context_plan = list(context_plan)  # Make a mutable copy
        self.initial_prompt = initial_prompt
        self.bind_to = bind_to
        self.bind_to_inherit = bind_to_inherit
        self.status = status
        self.turn_id = turn_id
        self.all_exchanges = all_exchanges or []

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

        # Context plan section - interactive tree for pending, static for resolved
        # Use all_exchanges if available (shows all exchanges with modes from context_plan)
        # Otherwise fall back to just showing what's in context_plan
        if self.status == "pending":
            if self.all_exchanges:
                yield Static(f"Context ({len(self.all_exchanges)} exchanges) [dim]click/space to toggle[/dim]", classes="section-title")
                yield ContextPlanTree(
                    self.context_plan,
                    all_exchanges=self.all_exchanges,
                    id=f"context-tree-{self.proposal_id}",
                )
            elif self.context_plan:
                yield Static(f"Context ({len(self.context_plan)} items) [dim]click/space to toggle[/dim]", classes="section-title")
                yield ContextPlanTree(
                    self.context_plan,
                    id=f"context-tree-{self.proposal_id}",
                )
        else:
            # For resolved proposals, show the context plan as static
            if self.context_plan:
                yield Static(f"Context ({len(self.context_plan)} items)", classes="section-title")
                yield ContextPlanTreeStatic(
                    self.context_plan,
                    id=f"context-tree-{self.proposal_id}",
                )

        # Initial prompt preview - scrollable for long prompts
        if self.initial_prompt:
            yield Static("Prompt", classes="section-title")
            with VerticalScroll(classes="prompt-scroll"):
                yield Static(self.initial_prompt, classes="prompt-text")

        # Buttons or status
        if self.status == "pending":
            with Horizontal(classes="button-row"):
                yield Button("Accept", variant="success", classes="accept-btn", id=f"accept-{self.proposal_id}")
                yield Button("Reject", variant="error", classes="reject-btn", id=f"reject-{self.proposal_id}")
        elif self.status == "accepted":
            yield Static("[green]✓ Accepted[/green]", classes="status-text")
        elif self.status == "rejected":
            yield Static("[red]✗ Rejected[/red]", classes="status-text")

    def on_context_plan_tree_plan_changed(self, event: ContextPlanTree.PlanChanged) -> None:
        """Update our context plan when user modifies it in the tree."""
        self.context_plan = event.context_plan

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Accept/Reject button clicks."""
        button_id = event.button.id or ""

        if button_id.startswith("accept-"):
            # Get the potentially modified context plan from the tree
            try:
                tree = self.query_one(f"#context-tree-{self.proposal_id}", ContextPlanTree)
                current_plan = tree.get_context_plan()
            except Exception:
                current_plan = self.context_plan

            self.post_message(self.Accepted(
                proposal_id=self.proposal_id,
                name=self.fork_name,
                description=self.description,
                context_plan=current_plan,
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
