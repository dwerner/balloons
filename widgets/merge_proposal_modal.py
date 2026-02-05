"""Modal for displaying and accepting/rejecting merge proposals from the LLM."""

from dataclasses import dataclass
from typing import Optional

from textual.screen import ModalScreen
from textual.widgets import Static, Button, TextArea
from textual.containers import Vertical, Horizontal, ScrollableContainer

from core.fork import MergeProposal


@dataclass
class MergeProposalResult:
    """Result from the merge proposal modal."""
    accepted: bool
    proposal: MergeProposal
    # Modified summary (user may have edited it)
    edited_summary: str | None = None


class MergeProposalModal(ModalScreen[Optional[MergeProposalResult]]):
    """Modal for reviewing and accepting/rejecting a merge proposal.

    Displays the LLM's proposed merge with:
    - Summary of what was accomplished
    - Reason for merging now
    - Files changed and key accomplishments

    User can accept (executes merge), edit the summary, or reject.
    """

    DEFAULT_CSS = """
    MergeProposalModal {
        align: center middle;
    }

    #merge-dialog {
        width: 85;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $success;
        padding: 1 2;
    }

    #merge-title {
        text-style: bold;
        color: $success;
        margin-bottom: 0;
    }

    #merge-reason {
        color: $text-muted;
        margin-bottom: 1;
    }

    #merge-content {
        height: auto;
        max-height: 40;
        padding: 0;
    }

    .section-title {
        text-style: bold;
        margin: 1 0 0 0;
        color: $primary;
    }

    #summary-area {
        background: $surface-darken-1;
        height: 6;
        min-height: 3;
        border: solid $success-darken-2;
        margin-bottom: 1;
    }

    .file-list {
        color: $text;
        padding-left: 2;
        margin-bottom: 1;
    }

    .file-item {
        color: $warning;
    }

    .accomplishment-list {
        color: $text;
        padding-left: 2;
    }

    .accomplishment-item {
        color: $success;
    }

    #merge-buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }

    #merge-buttons Button {
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
        proposal: MergeProposal,
        fork_name: str = "",
        **kwargs
    ):
        """Initialize the modal.

        Args:
            proposal: The MergeProposal from the LLM
            fork_name: Name of the fork being merged (for display)
        """
        super().__init__(**kwargs)
        self._proposal = proposal
        self._fork_name = fork_name

    def compose(self):
        with Vertical(id="merge-dialog"):
            # Header with fork name
            title = f"Merge: {self._fork_name}" if self._fork_name else "Merge Fork"
            yield Static(title, id="merge-title")

            if self._proposal.reason:
                yield Static(self._proposal.reason, id="merge-reason")

            with ScrollableContainer(id="merge-content"):
                # Editable summary
                yield Static("Summary", classes="section-title")
                yield TextArea(self._proposal.summary, id="summary-area")

                # Files changed
                if self._proposal.files_changed:
                    yield Static(f"Files Changed ({len(self._proposal.files_changed)})", classes="section-title")
                    files_text = "\n".join(f"  - {f}" for f in self._proposal.files_changed)
                    yield Static(files_text, classes="file-list")

                # Key accomplishments
                if self._proposal.key_accomplishments:
                    yield Static(f"Accomplishments ({len(self._proposal.key_accomplishments)})", classes="section-title")
                    acc_text = "\n".join(f"  + {a}" for a in self._proposal.key_accomplishments)
                    yield Static(acc_text, classes="accomplishment-list")

            with Horizontal(id="merge-buttons"):
                yield Button("Merge", id="accept-btn", variant="success")
                yield Button("Cancel", id="reject-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "accept-btn":
            self.action_accept()
        elif event.button.id == "reject-btn":
            self.action_reject()

    def action_accept(self) -> None:
        """Accept the merge proposal with potentially edited summary."""
        # Get the edited summary from the TextArea
        summary_area = self.query_one("#summary-area", TextArea)
        edited_summary = summary_area.text

        result = MergeProposalResult(
            accepted=True,
            proposal=self._proposal,
            edited_summary=edited_summary,
        )
        self.dismiss(result)

    def action_reject(self) -> None:
        """Reject the merge proposal."""
        result = MergeProposalResult(
            accepted=False,
            proposal=self._proposal,
        )
        self.dismiss(result)
