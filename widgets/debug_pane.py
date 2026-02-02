"""Debug pane widget for Balloons.

Collapsible bottom drawer showing debug log entries for Claude observability.
Uses a tree structure to group events by Claude process run.
"""

from textual.widgets import Tree
from textual.widgets.tree import TreeNode
from rich.text import Text

from core.debug_log import debug_log, LogEntry, LogLevel


class DebugPane(Tree):
    """Collapsible debug pane showing log entries in a tree.

    Groups events by Claude process run (run_id/PID).
    Consecutive content_block_delta events are grouped under one expandable node.
    Toggle with Ctrl+G, auto-expands on errors.
    """

    DEFAULT_CSS = """
    DebugPane {
        height: 0;
        background: $surface;
        border-top: solid $primary;
        scrollbar-size: 1 1;
    }

    DebugPane.expanded {
        height: 14;
    }

    DebugPane.auto-expanded {
        height: 10;
        border-top: solid $error;
    }

    DebugPane > .tree--label {
        padding: 0 1;
    }

    DebugPane > .tree--cursor {
        background: $accent;
    }
    """

    LEVEL_COLORS = {
        LogLevel.ERROR: "red",
        LogLevel.WARNING: "yellow",
        LogLevel.INFO: "white",
        LogLevel.DEBUG: "dim white",
    }

    LEVEL_SYMBOLS = {
        LogLevel.ERROR: "E",
        LogLevel.WARNING: "W",
        LogLevel.INFO: "I",
        LogLevel.DEBUG: "D",
    }

    def __init__(self, **kwargs):
        super().__init__("Debug Log", **kwargs)
        self._expanded = False
        self._auto_expanded = False
        self._run_nodes: dict[str, TreeNode] = {}  # run_id -> tree node
        self._misc_node: TreeNode | None = None  # For entries without run_id
        # Track current delta group per run_id
        self._delta_groups: dict[str, tuple[TreeNode, int]] = {}  # run_id -> (node, count)
        self.show_root = False
        self.guide_depth = 2

    def on_mount(self) -> None:
        """Subscribe to debug log updates."""
        debug_log.add_listener(self._on_log_entry)
        # Load existing entries
        for entry in reversed(debug_log.get_entries(limit=100)):
            self._add_entry(entry)

    def on_unmount(self) -> None:
        """Unsubscribe from debug log updates."""
        debug_log.remove_listener(self._on_log_entry)

    def _on_log_entry(self, entry: LogEntry) -> None:
        """Handle new log entry."""
        self._add_entry(entry)

        # Auto-expand on errors
        if entry.level == LogLevel.ERROR and not self._expanded:
            self._auto_expanded = True
            self.add_class("auto-expanded")

    def _is_delta_event(self, entry: LogEntry) -> bool:
        """Check if this is a content_block_delta event that should be grouped."""
        return (
            entry.category == "claude" and
            "content_block_delta" in entry.message
        )

    def _add_entry(self, entry: LogEntry) -> None:
        """Add an entry to the appropriate tree node."""
        if entry.run_id:
            # Get or create run node
            if entry.run_id not in self._run_nodes:
                run_label = Text()
                run_label.append(f"[{entry.timestamp}] ", style="dim")
                run_label.append(f"pid {entry.run_id}", style="cyan bold")
                node = self.root.add(run_label, expand=True)
                self._run_nodes[entry.run_id] = node

            parent = self._run_nodes[entry.run_id]

            # Handle delta events - group consecutive ones
            if self._is_delta_event(entry):
                self._add_delta_event(entry, parent)
                return

            # Non-delta event - close any open delta group for this run
            if entry.run_id in self._delta_groups:
                del self._delta_groups[entry.run_id]

            # Handle process start/exit specially
            if entry.category == "process":
                if "started" in entry.message:
                    run_label = Text()
                    run_label.append(f"[{entry.timestamp}] ", style="dim")
                    run_label.append(f"pid {entry.run_id} ", style="cyan bold")
                    prompt_len = entry.details.get("prompt_len", "?")
                    run_label.append(f"(prompt: {prompt_len} chars)", style="dim")
                    parent.set_label(run_label)
                    return
                elif "exited" in entry.message:
                    label = self._format_entry(entry)
                    parent.add_leaf(label)
                    # Update parent label to show exit status
                    current = parent.label
                    if isinstance(current, Text):
                        if "code 0" in entry.message:
                            current.append(" ", style="")
                            current.append("[OK]", style="green")
                        else:
                            current.append(" ", style="")
                            current.append("[FAIL]", style="red bold")
                        parent.set_label(current)
                    return

            # Regular event - add as leaf
            label = self._format_entry(entry)
            parent.add_leaf(label)
        else:
            # No run_id - add to misc node
            if self._misc_node is None:
                self._misc_node = self.root.add(Text("Other", style="dim"), expand=True)
            label = self._format_entry(entry)
            self._misc_node.add_leaf(label)

        # Scroll to show new entry
        self.scroll_end(animate=False)

    def _add_delta_event(self, entry: LogEntry, parent: TreeNode) -> None:
        """Add a delta event, grouping consecutive ones."""
        run_id = entry.run_id

        if run_id in self._delta_groups:
            # Update existing group
            group_node, count = self._delta_groups[run_id]
            count += 1
            self._delta_groups[run_id] = (group_node, count)

            # Update the group label
            label = Text()
            label.append(f"[{entry.timestamp}] ", style="dim")
            label.append("[D] ", style="dim white")
            label.append("claude: ", style="cyan")
            label.append(f"content_block_delta ", style="")
            label.append(f"({count} events)", style="yellow")
            group_node.set_label(label)

            # Add individual delta as collapsed child
            child_label = self._format_delta_child(entry)
            group_node.add_leaf(child_label)
        else:
            # Start a new group
            label = Text()
            label.append(f"[{entry.timestamp}] ", style="dim")
            label.append("[D] ", style="dim white")
            label.append("claude: ", style="cyan")
            label.append(f"content_block_delta ", style="")
            label.append("(1 event)", style="yellow")

            # Create expandable node (not a leaf)
            group_node = parent.add(label, expand=False)
            self._delta_groups[run_id] = (group_node, 1)

            # Add first delta as child
            child_label = self._format_delta_child(entry)
            group_node.add_leaf(child_label)

        self.scroll_end(animate=False)

    def _format_delta_child(self, entry: LogEntry) -> Text:
        """Format a delta event for display as a child node."""
        text = Text()
        text.append(f"[{entry.timestamp}] ", style="dim")

        # Show delta type and content
        details = entry.details or {}
        if "text" in details:
            text.append("text: ", style="green")
            content = details["text"]
            # Escape newlines for display
            content = content.replace("\n", "\\n")
            if len(content) > 60:
                content = content[:57] + "..."
            text.append(f'"{content}"', style="white")
        elif "json" in details:
            text.append("json: ", style="blue")
            content = details["json"]
            if len(content) > 60:
                content = content[:57] + "..."
            text.append(content, style="dim white")
        else:
            # Fallback to message
            msg = entry.message
            if "text_delta" in msg:
                text.append("text_delta", style="green")
            elif "input_json_delta" in msg:
                text.append("input_json_delta", style="blue")
            else:
                text.append(msg, style="dim")

        return text

    def _format_entry(self, entry: LogEntry) -> Text:
        """Format a log entry for display."""
        color = self.LEVEL_COLORS.get(entry.level, "white")
        symbol = self.LEVEL_SYMBOLS.get(entry.level, "?")

        text = Text()
        text.append(f"[{entry.timestamp}] ", style="dim")
        text.append(f"[{symbol}] ", style=color)

        if entry.category and entry.category != "process":
            text.append(f"{entry.category}: ", style="cyan")

        # Truncate long messages
        message = entry.message
        if len(message) > 80:
            message = message[:77] + "..."
        text.append(message, style=color if entry.level in (LogLevel.ERROR, LogLevel.WARNING) else "")

        # Show key details inline
        if entry.details:
            details_parts = []
            for k, v in entry.details.items():
                if k == "stderr" and v:
                    first_line = str(v).split('\n')[0][:50]
                    details_parts.append(f"stderr={first_line}...")
                elif k != "prompt_len":
                    str_v = str(v)
                    if len(str_v) > 30:
                        str_v = str_v[:27] + "..."
                    details_parts.append(f"{k}={str_v}")
            if details_parts:
                text.append(f" ({', '.join(details_parts)})", style="dim")

        return text

    def toggle(self) -> None:
        """Toggle the debug pane visibility."""
        if self._expanded or self._auto_expanded:
            self._expanded = False
            self._auto_expanded = False
            self.remove_class("expanded")
            self.remove_class("auto-expanded")
        else:
            self._expanded = True
            self._auto_expanded = False
            self.add_class("expanded")
            self.remove_class("auto-expanded")

    def clear_entries(self) -> None:
        """Clear all displayed entries."""
        self.root.remove_children()
        self._run_nodes.clear()
        self._delta_groups.clear()
        self._misc_node = None
        debug_log.clear()

    @property
    def is_expanded(self) -> bool:
        """Check if pane is expanded (manually or auto)."""
        return self._expanded or self._auto_expanded
