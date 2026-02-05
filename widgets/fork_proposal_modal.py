"""Modal for displaying and accepting/rejecting fork proposals from the LLM."""

from dataclasses import dataclass
from typing import Optional

from textual.screen import ModalScreen
from textual.widgets import Static, Button, Label
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.message import Message

from models import ContextMode
from core.fork import ForkProposal, ContextAssignment


@dataclass
class ForkProposalResult:
    """Result from the fork proposal modal."""
    accepted: bool
    proposal: ForkProposal
    # Modified context assignments (user may have changed them)
    modified_assignments: dict[int, ContextMode] | None = None


class ForkProposalModal(ModalScreen[Optional[ForkProposalResult]]):
    """Modal for reviewing and accepting/rejecting a fork proposal.

    Displays the LLM's proposed fork with:
    - Fork name and description
    - Context plan showing which exchanges will be COPY/COMPRESS/DROP
    - Reasoning for each context decision

    User can accept (creates fork) or reject (dismisses proposal).
    """

    DEFAULT_CSS = """
    ForkProposalModal {
        align: center middle;
    }

    #proposal-dialog {
        width: 90;
        height: 80%;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }

    #proposal-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }

    #proposal-content {
        height: 1fr;
        padding: 1 0;
    }

    .section-title {
        text-style: bold;
        margin-top: 1;
        margin-bottom: 0;
        color: $primary;
    }

    .section-content {
        padding-left: 2;
        margin-bottom: 1;
    }

    #fork-name {
        color: $success;
        text-style: bold;
    }

    #fork-description {
        color: $text;
        margin-bottom: 1;
    }

    .context-item {
        height: auto;
        margin: 0;
        padding: 0 0 0 1;
        border-left: thick $primary-darken-2;
    }

    .context-item.copy {
        border-left: thick $success;
    }

    .context-item.compress {
        border-left: thick $warning;
    }

    .context-item.drop {
        border-left: thick $error-darken-2;
    }

    .context-range {
        text-style: bold;
    }

    .context-mode {
        margin-left: 1;
    }

    .context-mode.copy {
        color: $success;
    }

    .context-mode.compress {
        color: $warning;
    }

    .context-mode.drop {
        color: $error-darken-2;
    }

    .context-reason {
        color: $text-muted;
        padding-left: 2;
    }

    #initial-prompt {
        background: $surface-darken-1;
        padding: 1;
        margin-top: 1;
        max-height: 10;
        overflow-y: auto;
    }

    #proposal-buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }

    #proposal-buttons Button {
        margin: 0 1;
    }

    #accept-btn {
        background: $success;
    }

    #reject-btn {
        background: $error-darken-1;
    }
    """

    BINDINGS = [
        ("escape", "reject", "Reject"),
        ("enter", "accept", "Accept"),
    ]

    def __init__(
        self,
        proposal: ForkProposal,
        exchange_summaries: list[str] | None = None,
        **kwargs
    ):
        """Initialize the modal.

        Args:
            proposal: The ForkProposal from the LLM
            exchange_summaries: Optional list of short summaries for each exchange
                              (index i = summary for exchange i)
        """
        super().__init__(**kwargs)
        self._proposal = proposal
        self._exchange_summaries = exchange_summaries or []

    def compose(self):
        with Vertical(id="proposal-dialog"):
            yield Static("Fork Proposal", id="proposal-title")

            with ScrollableContainer(id="proposal-content"):
                # Fork name and description
                yield Static("Name", classes="section-title")
                with Vertical(classes="section-content"):
                    yield Static(self._proposal.name, id="fork-name")

                yield Static("Goal", classes="section-title")
                with Vertical(classes="section-content"):
                    yield Static(self._proposal.description, id="fork-description")

                # Context plan
                yield Static("Context Plan", classes="section-title")
                with Vertical(classes="section-content"):
                    if self._proposal.context_plan:
                        for assignment in self._proposal.context_plan:
                            yield self._make_context_item(assignment)
                    else:
                        yield Static("No context assignments specified", classes="context-reason")

                # Initial prompt if provided
                if self._proposal.initial_prompt:
                    yield Static("Starting Prompt", classes="section-title")
                    with Vertical(classes="section-content"):
                        yield Static(self._proposal.initial_prompt, id="initial-prompt")

            with Horizontal(id="proposal-buttons"):
                yield Button("Accept", id="accept-btn", variant="success")
                yield Button("Reject", id="reject-btn", variant="error")

    def _make_context_item(self, assignment: ContextAssignment) -> Vertical:
        """Create a widget showing a context assignment."""
        mode_class = assignment.mode.lower()
        mode_icons = {"copy": "[+]", "compress": "[~]", "drop": "[-]"}
        mode_icon = mode_icons.get(mode_class, "[?]")

        # Get exchange summary if available
        exchange_info = f"Exchanges {assignment.exchange_range}"

        # Build children list
        range_label = Static(f"{mode_icon} {exchange_info}", classes="context-range")
        mode_label = Static(assignment.mode.upper(), classes=f"context-mode {mode_class}")
        row = Horizontal(range_label, mode_label)

        children = [row]
        if assignment.reason:
            reason_label = Static(assignment.reason, classes="context-reason")
            children.append(reason_label)

        # Create container with children
        return Vertical(*children, classes=f"context-item {mode_class}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "accept-btn":
            self.action_accept()
        elif event.button.id == "reject-btn":
            self.action_reject()

    def action_accept(self) -> None:
        """Accept the fork proposal."""
        result = ForkProposalResult(
            accepted=True,
            proposal=self._proposal,
        )
        self.dismiss(result)

    def action_reject(self) -> None:
        """Reject the fork proposal."""
        result = ForkProposalResult(
            accepted=False,
            proposal=self._proposal,
        )
        self.dismiss(result)
