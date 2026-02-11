"""Mini context tree widget for fork proposal editing.

Displays the context plan as an editable tree where users can:
- See each exchange range with its mode
- Toggle modes by clicking or pressing space/enter
- View the reason for each assignment

When `all_exchanges` is provided, shows ALL exchanges with modes
determined by matching against the context_plan. This gives users
full control over what gets copied/compressed/dropped.
"""

from textual.binding import Binding
from textual.widgets import Tree
from textual.widgets.tree import TreeNode
from textual.message import Message
from rich.text import Text

from models import ContextAssignmentData, ExchangeInfo


# Mode colors matching ContextTreeView
MODE_COLORS = {
    "copy": "green",
    "compress": "yellow",
    "drop": "dim",
}

MODE_ICONS = {
    "copy": "☑",
    "compress": "Σ",
    "drop": "☐",
}

MODE_CYCLE = ["copy", "compress", "drop"]


class ContextPlanTree(Tree[ContextAssignmentData]):
    """Editable tree view of context plan assignments.

    Displays exchange ranges with their modes, allowing users to
    toggle modes before accepting a fork proposal.

    When `all_exchanges` is provided:
    - Shows ALL exchanges (not just those in context_plan)
    - Resolves ranges like "-5", "last", "all" to actual exchange indices
    - Applies modes from context_plan to matching exchanges
    - Defaults unmentioned exchanges to "compress"
    """

    # Override space to toggle mode instead of expand/collapse
    BINDINGS = [
        Binding("space", "toggle_mode", "Toggle mode", show=False),
        Binding("enter", "toggle_mode", "Toggle mode", show=False),
    ]

    DEFAULT_CSS = """
    ContextPlanTree {
        height: auto;
        max-height: 10;
        scrollbar-gutter: stable;
        overflow-y: auto;
        background: $surface-darken-1;
        padding: 0 1;
    }

    ContextPlanTree > .tree--cursor {
        background: $primary-darken-2;
    }

    ContextPlanTree > .tree--highlight-line {
        background: $surface-darken-2;
    }
    """

    class PlanChanged(Message):
        """Fired when the context plan is modified."""
        def __init__(self, context_plan: list[ContextAssignmentData]) -> None:
            super().__init__()
            self.context_plan = context_plan

    def __init__(
        self,
        context_plan: list[ContextAssignmentData],
        all_exchanges: list[ExchangeInfo] | None = None,
        **kwargs
    ):
        super().__init__("Context Plan", **kwargs)
        self._original_plan = list(context_plan)
        self._all_exchanges = all_exchanges
        self._assignment_nodes: dict[int, TreeNode[ContextAssignmentData]] = {}
        # Hide the root node's expand/collapse since we don't need it
        self.show_root = False

        # Build the expanded context plan (one entry per exchange)
        if all_exchanges:
            self._context_plan = self._expand_context_plan(context_plan, all_exchanges)
        else:
            self._context_plan = list(context_plan)

    def _expand_context_plan(
        self,
        context_plan: list[ContextAssignmentData],
        all_exchanges: list[ExchangeInfo],
    ) -> list[ContextAssignmentData]:
        """Expand context_plan to cover all exchanges.

        Resolves ranges like "-5", "last", "all" and creates one
        ContextAssignmentData per exchange with the appropriate mode.
        """
        num_exchanges = len(all_exchanges)
        if num_exchanges == 0:
            return []

        # Start with default mode for all exchanges
        modes: dict[int, tuple[str, str]] = {}  # idx -> (mode, reason)
        for i in range(num_exchanges):
            modes[i] = ("compress", "")  # Default

        # Apply context_plan assignments
        for assignment in context_plan:
            indices = self._resolve_range(assignment.exchange_range, num_exchanges)
            for idx in indices:
                if 0 <= idx < num_exchanges:
                    modes[idx] = (assignment.mode, assignment.reason)

        # Build expanded plan with exchange summaries
        result = []
        for i in range(num_exchanges):
            mode, reason = modes[i]
            # Include the exchange summary in the reason if not already set
            summary = all_exchanges[i].summary if all_exchanges[i].summary else ""
            display_reason = reason if reason else summary
            result.append(ContextAssignmentData(
                exchange_range=str(i),
                mode=mode,
                reason=display_reason,
            ))
        return result

    def _resolve_range(self, range_str: str, num_exchanges: int) -> list[int]:
        """Resolve an exchange range string to a list of indices.

        Handles:
        - "0", "5" - single index
        - "0-3" - range (inclusive)
        - "last" - last exchange
        - "last-2" - last 3 exchanges
        - "-3" - last 3 exchanges (negative indexing)
        - "all" - all exchanges
        """
        range_str = range_str.strip()

        if range_str == "all":
            return list(range(num_exchanges))

        if range_str == "last":
            return [num_exchanges - 1] if num_exchanges > 0 else []

        # Handle "last-N" format (e.g., "last-2" = last 3 exchanges)
        if range_str.startswith("last-"):
            try:
                n = int(range_str[5:])
                start = max(0, num_exchanges - n - 1)
                return list(range(start, num_exchanges))
            except ValueError:
                pass

        # Handle negative indexing (e.g., "-3" = last 3 exchanges)
        if range_str.startswith("-") and not "-" in range_str[1:]:
            try:
                n = int(range_str[1:])
                start = max(0, num_exchanges - n)
                return list(range(start, num_exchanges))
            except ValueError:
                pass

        # Handle "X-Y" range (e.g., "0-3" = exchanges 0, 1, 2, 3)
        if "-" in range_str:
            parts = range_str.split("-")
            if len(parts) == 2:
                try:
                    start = int(parts[0])
                    end = int(parts[1])
                    return list(range(start, end + 1))
                except ValueError:
                    pass

        # Try single index
        try:
            idx = int(range_str)
            if idx < 0:
                idx = num_exchanges + idx
            return [idx]
        except ValueError:
            pass

        return []

    def on_mount(self) -> None:
        """Build the tree from context plan."""
        self.root.expand()
        self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        """Rebuild tree nodes from current context plan."""
        self.root.remove_children()
        self._assignment_nodes.clear()

        for idx, assignment in enumerate(self._context_plan):
            label = self._make_label(assignment)
            node = self.root.add(label, data=assignment)
            node.allow_expand = False
            self._assignment_nodes[idx] = node

    def _make_label(self, assignment: ContextAssignmentData) -> Text:
        """Create a styled label for an assignment.

        Format: [icon] index - summary
        The icon shows the mode (☑ copy, Σ compress, ☐ drop)
        The summary shows what the exchange contains.
        """
        mode = assignment.mode.lower()
        color = MODE_COLORS.get(mode, "white")
        icon = MODE_ICONS.get(mode, "?")

        text = Text()
        text.append(f"[{icon}] ", style=color)
        text.append(f"{assignment.exchange_range} ", style=f"bold {color}")

        # Show the exchange summary (more useful than showing "COPY"/"COMPRESS")
        if assignment.reason:
            # Truncate long summaries for display
            reason = assignment.reason
            if len(reason) > 55:
                reason = reason[:52] + "..."
            text.append(reason, style="dim" if mode == "drop" else "")

        return text

    def _toggle_mode(self, node: TreeNode[ContextAssignmentData]) -> None:
        """Toggle the mode of an assignment."""
        assignment = node.data
        if not assignment:
            return

        # Find current mode index and cycle to next
        current_mode = assignment.mode.lower()
        try:
            idx = MODE_CYCLE.index(current_mode)
        except ValueError:
            idx = 0

        new_mode = MODE_CYCLE[(idx + 1) % len(MODE_CYCLE)]

        # Update the assignment
        assignment.mode = new_mode

        # Update node label
        node.set_label(self._make_label(assignment))

        # Notify that plan changed
        self.post_message(self.PlanChanged(self._context_plan))

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle node selection - toggle on click."""
        if event.node.data is not None:
            self._toggle_mode(event.node)

    def action_toggle_mode(self) -> None:
        """Toggle mode on current node (bound to space/enter)."""
        if self.cursor_node and self.cursor_node.data is not None:
            self._toggle_mode(self.cursor_node)

    def get_context_plan(self) -> list[ContextAssignmentData]:
        """Return the current (possibly modified) context plan."""
        return self._context_plan


class ContextPlanTreeStatic(Tree[ContextAssignmentData]):
    """Read-only tree view of context plan for already-resolved proposals."""

    DEFAULT_CSS = """
    ContextPlanTreeStatic {
        height: auto;
        max-height: 8;
        background: $surface-darken-1;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        context_plan: list[ContextAssignmentData],
        **kwargs
    ):
        super().__init__("Context Plan", **kwargs)
        self._context_plan = context_plan
        self.show_root = False

    def on_mount(self) -> None:
        """Build the tree from context plan."""
        self.root.expand()

        for assignment in self._context_plan:
            label = self._make_label(assignment)
            node = self.root.add(label, data=assignment)
            node.allow_expand = False

    def _make_label(self, assignment: ContextAssignmentData) -> Text:
        """Create a styled label for an assignment."""
        mode = assignment.mode.lower()
        color = MODE_COLORS.get(mode, "white")
        icon = MODE_ICONS.get(mode, "?")

        text = Text()
        text.append(f"[{icon}] ", style=color)
        text.append(f"{assignment.exchange_range} ", style=f"bold {color}")

        if assignment.reason:
            reason = assignment.reason
            if len(reason) > 55:
                reason = reason[:52] + "..."
            text.append(reason, style="dim" if mode == "drop" else "")

        return text
