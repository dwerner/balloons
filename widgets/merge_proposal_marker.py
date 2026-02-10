"""Merge proposal marker widget - inline proposal with Accept/Reject buttons."""

from textual.widgets import Static, Button, TextArea
from textual.containers import Vertical, Horizontal
from textual.message import Message
from rich.console import RenderableType
from rich.text import Text
from rich.markup import escape as escape_markup


class MergeProposalMarker(Static):
    """Shows a merge proposal inline in the chat log with Accept/Reject buttons.

    This replaces the modal dialog approach, allowing proposals to persist
    in the conversation history and be acted upon even after switching sessions.

    Displays:
        Merge Proposal
        "Why the merge is appropriate now"

        Summary:
        [editable text area with summary]

        Files Changed:
        - src/cache.py
        - src/config.py

        Accomplishments:
        + Added Redis cache client
        + Implemented cache-aside pattern

        [Accept] [Reject]
    """

    DEFAULT_CSS = """
    MergeProposalMarker {
        padding: 1 1;
        margin: 0 0 1 2;
        background: #1a3a2a;
        border: thick $success;
    }

    MergeProposalMarker.hidden {
        display: none;
    }

    MergeProposalMarker.accepted {
        opacity: 0.7;
    }

    MergeProposalMarker.rejected {
        border: thick $error;
        opacity: 0.5;
    }

    MergeProposalMarker .proposal-title {
        text-style: bold;
        color: $success;
        margin-bottom: 0;
    }

    MergeProposalMarker .proposal-reason {
        color: $text-muted;
        margin-bottom: 1;
    }

    MergeProposalMarker .section-title {
        text-style: bold;
        color: $primary;
        margin-top: 1;
    }

    MergeProposalMarker .summary-area {
        background: $surface-darken-1;
        height: 4;
        min-height: 3;
        max-height: 8;
        border: solid $success-darken-2;
        margin-bottom: 1;
    }

    MergeProposalMarker .summary-readonly {
        background: $surface-darken-1;
        padding: 0 1;
        margin-bottom: 1;
    }

    MergeProposalMarker .file-list {
        color: $warning;
        padding-left: 1;
    }

    MergeProposalMarker .accomplishment-list {
        color: $success;
        padding-left: 1;
    }

    MergeProposalMarker .button-row {
        margin-top: 1;
        height: auto;
    }

    MergeProposalMarker .button-row Button {
        margin: 0 1 0 0;
    }

    MergeProposalMarker .accept-btn {
        background: $success;
    }

    MergeProposalMarker .reject-btn {
        background: $error-darken-1;
    }

    MergeProposalMarker .status-text {
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
    }

    /* Context mode visual indicators */
    MergeProposalMarker.context-copy {
    }

    MergeProposalMarker.context-compress {
        background: #2d2a1a;
    }

    MergeProposalMarker.context-drop {
        opacity: 0.4;
    }
    """

    class Accepted(Message):
        """Posted when user accepts the merge proposal."""

        def __init__(
            self,
            proposal_id: str,
            summary: str,  # May be edited by user
            files_changed: list[str],
            key_accomplishments: list[str],
            reason: str,
            turn_id: int,
        ) -> None:
            super().__init__()
            self.proposal_id = proposal_id
            self.summary = summary
            self.files_changed = files_changed
            self.key_accomplishments = key_accomplishments
            self.reason = reason
            self.turn_id = turn_id

    class Rejected(Message):
        """Posted when user rejects the merge proposal."""

        def __init__(self, proposal_id: str, turn_id: int) -> None:
            super().__init__()
            self.proposal_id = proposal_id
            self.turn_id = turn_id

    def __init__(
        self,
        proposal_id: str,
        summary: str,
        reason: str = "",
        files_changed: list[str] | None = None,
        key_accomplishments: list[str] | None = None,
        status: str = "pending",
        turn_id: int = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.proposal_id = proposal_id
        self.summary = summary
        self.reason = reason
        self.files_changed = files_changed or []
        self.key_accomplishments = key_accomplishments or []
        self.status = status
        self.turn_id = turn_id

        if status == "accepted":
            self.add_class("accepted")
        elif status == "rejected":
            self.add_class("rejected")

    def compose(self):
        """Build the widget structure."""
        yield Static("Merge Proposal", classes="proposal-title")
        if self.reason:
            yield Static(self.reason, classes="proposal-reason")

        # Summary section
        yield Static("Summary", classes="section-title")
        if self.status == "pending":
            # Editable summary for pending proposals
            yield TextArea(self.summary, id=f"summary-{self.proposal_id}", classes="summary-area")
        else:
            # Read-only summary for resolved proposals
            yield Static(self.summary, classes="summary-readonly")

        # Files changed
        if self.files_changed:
            yield Static(f"Files Changed ({len(self.files_changed)})", classes="section-title")
            files_text = "\n".join(f"  - {f}" for f in self.files_changed)
            yield Static(files_text, classes="file-list")

        # Key accomplishments
        if self.key_accomplishments:
            yield Static(f"Accomplishments ({len(self.key_accomplishments)})", classes="section-title")
            acc_text = "\n".join(f"  + {a}" for a in self.key_accomplishments)
            yield Static(acc_text, classes="accomplishment-list")

        # Buttons or status
        if self.status == "pending":
            with Horizontal(classes="button-row"):
                yield Button("Merge", variant="success", classes="accept-btn", id=f"accept-{self.proposal_id}")
                yield Button("Cancel", variant="error", classes="reject-btn", id=f"reject-{self.proposal_id}")
        elif self.status == "accepted":
            yield Static("[green]Merged[/green]", classes="status-text")
        elif self.status == "rejected":
            yield Static("[red]Cancelled[/red]", classes="status-text")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Accept/Reject button clicks."""
        button_id = event.button.id or ""

        if button_id.startswith("accept-"):
            # Get the (potentially edited) summary from the TextArea
            try:
                summary_area = self.query_one(f"#summary-{self.proposal_id}", TextArea)
                edited_summary = summary_area.text
            except Exception:
                edited_summary = self.summary

            self.post_message(self.Accepted(
                proposal_id=self.proposal_id,
                summary=edited_summary,
                files_changed=self.files_changed,
                key_accomplishments=self.key_accomplishments,
                reason=self.reason,
                turn_id=self.turn_id,
            ))
            # Update visual state
            self.summary = edited_summary  # Store the edited version
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
