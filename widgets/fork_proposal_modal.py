"""Modal for displaying and accepting/rejecting fork proposals from the LLM."""

from dataclasses import dataclass
from typing import Optional

from textual.screen import ModalScreen
from textual.widgets import Static, Button, TextArea, Tree
from textual.widgets.tree import TreeNode
from textual.containers import Vertical, Horizontal, ScrollableContainer
from rich.markup import escape as escape_markup

from models import ContextMode
from core.fork import ForkProposal, ContextAssignment, ForkBindingSpec


@dataclass
class ResolvedBinding:
    """Pre-resolved binding information for display in the modal."""
    entity_type: str  # "goal", "plan", "todo"
    entity_id: str  # Full or prefix ID
    role: str  # "planning", "implementation", etc.
    title: str | None = None  # Resolved entity title (if looked up)
    inherit: bool = False  # True if bind_to was "inherit"


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
        width: 85;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }

    #proposal-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 0;
    }

    #fork-description {
        color: $text-muted;
        margin-bottom: 1;
    }

    #proposal-content {
        height: auto;
        max-height: 40;
        padding: 0;
    }

    .section-title {
        text-style: bold;
        margin: 0;
        color: $primary;
    }

    .context-item {
        height: auto;
        min-height: 2;
        margin: 0 0 1 0;
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

    .context-range.copy {
        color: $success;
    }

    .context-range.compress {
        color: $warning;
    }

    .context-range.drop {
        color: $text-muted;
    }

    .context-reason {
        color: $text-muted;
        padding-left: 2;
    }

    #context-tree {
        height: auto;
        max-height: 12;
        min-height: 2;
        padding: 0;
        margin: 0;
    }

    #initial-prompt {
        background: $surface-darken-1;
        height: 6;
        min-height: 3;
        border: solid $primary-darken-2;
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

    #binding-section {
        margin-bottom: 1;
    }

    #binding-info {
        color: $text;
        padding-left: 1;
        border-left: thick $secondary;
    }

    .binding-label {
        color: $text-muted;
    }

    .binding-value {
        color: $text;
        text-style: bold;
    }

    .binding-title {
        color: $primary;
    }

    .binding-inherit {
        color: $warning;
        text-style: italic;
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
        resolved_binding: ResolvedBinding | None = None,
        **kwargs
    ):
        """Initialize the modal.

        Args:
            proposal: The ForkProposal from the LLM
            exchange_summaries: Optional list of short summaries for each exchange
                              (index i = summary for exchange i)
            resolved_binding: Pre-resolved binding information to display
        """
        super().__init__(**kwargs)
        self._proposal = proposal
        self._exchange_summaries = exchange_summaries or []
        self._resolved_binding = resolved_binding

    def compose(self):
        with Vertical(id="proposal-dialog"):
            # Compact header: name on same line
            yield Static(f"Fork: {self._proposal.name}", id="proposal-title")
            yield Static(self._proposal.description, id="fork-description")

            # Show binding info if present
            if self._resolved_binding:
                yield from self._compose_binding_section()

            with ScrollableContainer(id="proposal-content"):
                # Context plan as collapsible tree - single line per item with reason inline
                yield Static(f"Context ({len(self._proposal.context_plan) if self._proposal.context_plan else 0})", classes="section-title")
                tree: Tree[str] = Tree("", id="context-tree")
                tree.show_root = False
                if self._proposal.context_plan:
                    for assignment in self._proposal.context_plan:
                        mode_icons = {"copy": "+", "compress": "~", "drop": "-"}
                        icon = mode_icons.get(assignment.mode.lower(), "?")
                        # Single line: icon, range, mode, reason all together
                        reason_part = f" - {escape_markup(assignment.reason)}" if assignment.reason else ""
                        label = f"[{icon}] {escape_markup(assignment.exchange_range)} {assignment.mode.upper()}{reason_part}"
                        tree.root.add_leaf(label)
                yield tree

                # Initial prompt - editable
                yield Static("Prompt", classes="section-title")
                yield TextArea(self._proposal.initial_prompt or "", id="initial-prompt")

            with Horizontal(id="proposal-buttons"):
                yield Button("Accept", id="accept-btn", variant="success")
                yield Button("Reject", id="reject-btn", variant="error")

    def _compose_binding_section(self):
        """Compose the binding info section."""
        binding = self._resolved_binding
        if not binding:
            return

        with Vertical(id="binding-section"):
            yield Static("Binding", classes="section-title")
            if binding.inherit:
                yield Static("[italic]Inherit from parent[/italic]", id="binding-info", classes="binding-inherit")
            else:
                # Show entity type, ID (with title if available), and role
                entity_display = binding.entity_type.capitalize()
                if binding.title:
                    id_display = f"{binding.title} ({binding.entity_id[:8]})"
                else:
                    id_display = binding.entity_id[:8]
                role_display = binding.role

                info_text = f"{entity_display}: {escape_markup(id_display)}\nRole: {role_display}"
                yield Static(info_text, id="binding-info")

    def _make_context_item(
        self,
        assignment: ContextAssignment,
        total_exchanges: int,
    ) -> Vertical:
        """Create a widget showing a context assignment.

        Args:
            assignment: The context assignment to render
            total_exchanges: Total number of exchanges (for resolving ranges)
        """
        mode_class = assignment.mode.lower()
        mode_icons = {"copy": "●", "compress": "◐", "drop": "○"}
        mode_icon = mode_icons.get(mode_class, "?")

        # Resolve the exchange range to show what it covers
        exchange_label = self._format_exchange_range(
            assignment.exchange_range,
            total_exchanges,
        )

        # Build the header row
        header = f"{mode_icon} {exchange_label}  [{assignment.mode.upper()}]"
        header_label = Static(header, classes=f"context-range {mode_class}")

        children = [header_label]

        # Add exchange previews for simple ranges
        previews = self._get_exchange_previews(assignment.exchange_range, total_exchanges)
        for preview in previews:
            children.append(Static(f"  {escape_markup(preview)}", classes="context-reason"))

        # Add reason if provided
        if assignment.reason:
            children.append(Static(f"  → {escape_markup(assignment.reason)}", classes="context-reason"))

        return Vertical(*children, classes=f"context-item {mode_class}")

    def _format_exchange_range(self, range_str: str, total: int) -> str:
        """Format an exchange range for display."""
        range_str = range_str.strip().lower()

        if range_str == "all":
            return f"All exchanges (0-{total - 1})" if total > 0 else "All exchanges"
        if range_str == "last":
            return f"Exchange {total - 1}" if total > 0 else "Last exchange"
        if range_str.startswith("last-"):
            try:
                n = int(range_str[5:])
                start = max(0, total - n - 1)
                return f"Exchanges {start}-{total - 1}"
            except ValueError:
                return f"Exchanges {range_str}"
        if "-" in range_str and not range_str.startswith("-"):
            return f"Exchanges {range_str}"
        if range_str.isdigit():
            return f"Exchange {range_str}"

        return f"Exchanges {range_str}"

    def _get_exchange_previews(self, range_str: str, total: int) -> list[str]:
        """Get preview text for exchanges in a range."""
        if not self._exchange_summaries:
            return []

        indices = self._resolve_range(range_str, total)
        previews = []
        for idx in indices[:3]:  # Show at most 3 previews
            if 0 <= idx < len(self._exchange_summaries):
                previews.append(self._exchange_summaries[idx])

        if len(indices) > 3:
            previews.append(f"... and {len(indices) - 3} more")

        return previews

    def _resolve_range(self, range_str: str, total: int) -> list[int]:
        """Resolve an exchange range string to indices."""
        range_str = range_str.strip().lower()

        if range_str == "all":
            return list(range(total))
        if range_str == "last":
            return [total - 1] if total > 0 else []
        if range_str.startswith("last-"):
            try:
                n = int(range_str[5:])
                start = max(0, total - n - 1)
                return list(range(start, total))
            except ValueError:
                return []
        if range_str.startswith("-") and range_str[1:].isdigit():
            try:
                n = int(range_str[1:])
                start = max(0, total - n)
                return list(range(start, total))
            except ValueError:
                return []
        if "-" in range_str and not range_str.startswith("-"):
            parts = range_str.split("-")
            if len(parts) == 2:
                try:
                    start, end = int(parts[0]), int(parts[1])
                    return list(range(start, min(end + 1, total)))
                except ValueError:
                    return []
        if range_str.isdigit():
            idx = int(range_str)
            return [idx] if idx < total else []

        return []

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "accept-btn":
            self.action_accept()
        elif event.button.id == "reject-btn":
            self.action_reject()

    def action_accept(self) -> None:
        """Accept the fork proposal with potentially edited initial prompt."""
        # Get the edited initial prompt from the TextArea
        prompt_area = self.query_one("#initial-prompt", TextArea)
        edited_prompt = prompt_area.text

        # Create a new proposal with the edited prompt, preserving bind_to
        edited_proposal = ForkProposal(
            name=self._proposal.name,
            description=self._proposal.description,
            context_plan=self._proposal.context_plan,
            initial_prompt=edited_prompt,
            bind_to=self._proposal.bind_to,
        )

        result = ForkProposalResult(
            accepted=True,
            proposal=edited_proposal,
        )
        self.dismiss(result)

    def action_reject(self) -> None:
        """Reject the fork proposal."""
        result = ForkProposalResult(
            accepted=False,
            proposal=self._proposal,
        )
        self.dismiss(result)
