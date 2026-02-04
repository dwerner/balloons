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
    Consecutive events matching GROUPABLE_PREFIXES are folded into expandable
    nodes with a count and latest timestamp.
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

    # Message prefixes that should be grouped when contiguous
    GROUPABLE_PREFIXES = [
        "content_block_delta",
        "CLI tool result received",
    ]

    def __init__(self, **kwargs):
        super().__init__("Debug Log", **kwargs)
        self._expanded = False
        self._auto_expanded = False
        self._run_nodes: dict[str, TreeNode] = {}  # run_id -> tree node
        self._misc_node: TreeNode | None = None  # For entries without run_id
        # Track current group per run_id: (node, count, group_key)
        self._message_groups: dict[str, tuple[TreeNode, int, str]] = {}
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

    def _get_group_key(self, entry: LogEntry) -> str | None:
        """Get a group key for this entry if it should be grouped.

        Returns a key string if the entry is groupable, None otherwise.
        Entries with the same group key (and run_id) are folded together.
        """
        for prefix in self.GROUPABLE_PREFIXES:
            if prefix in entry.message:
                return f"{entry.category}:{prefix}"
        return None

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

            # Check if this entry should be grouped
            group_key = self._get_group_key(entry)
            if group_key:
                self._add_grouped_event(entry, parent, group_key)
                return

            # Non-groupable event - close any open group for this run
            if entry.run_id in self._message_groups:
                del self._message_groups[entry.run_id]

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

    def _add_grouped_event(self, entry: LogEntry, parent: TreeNode, group_key: str) -> None:
        """Add an event to a group, creating or extending as needed.

        Groups contiguous events with the same group_key under a single
        expandable node, updating the timestamp to show the latest.
        """
        run_id = entry.run_id
        color = self.LEVEL_COLORS.get(entry.level, "white")
        symbol = self.LEVEL_SYMBOLS.get(entry.level, "?")

        # Extract the display name from group_key (category:prefix -> prefix)
        _, prefix = group_key.split(":", 1)

        if run_id in self._message_groups:
            group_node, count, existing_key = self._message_groups[run_id]
            if existing_key == group_key:
                # Same group - extend it
                count += 1
                self._message_groups[run_id] = (group_node, count, group_key)

                # Update the group label with latest timestamp
                label = Text()
                label.append(f"[{entry.timestamp}] ", style="dim")
                label.append(f"[{symbol}] ", style=color)
                if entry.category:
                    label.append(f"{entry.category}: ", style="cyan")
                label.append(f"{prefix} ", style="")
                label.append(f"({count} events)", style="yellow")
                group_node.set_label(label)

                # Add individual event as collapsed child
                child_label = self._format_grouped_child(entry)
                group_node.add_leaf(child_label)
                self.scroll_end(animate=False)
                return

            # Different group key - close old group and start new one
            del self._message_groups[run_id]

        # Start a new group
        label = Text()
        label.append(f"[{entry.timestamp}] ", style="dim")
        label.append(f"[{symbol}] ", style=color)
        if entry.category:
            label.append(f"{entry.category}: ", style="cyan")
        label.append(f"{prefix} ", style="")
        label.append("(1 event)", style="yellow")

        # Create expandable node (not a leaf)
        group_node = parent.add(label, expand=False)
        self._message_groups[run_id] = (group_node, 1, group_key)

        # Add first event as child
        child_label = self._format_grouped_child(entry)
        group_node.add_leaf(child_label)

        self.scroll_end(animate=False)

    def _format_grouped_child(self, entry: LogEntry) -> Text:
        """Format a grouped event for display as a child node."""
        text = Text()
        text.append(f"[{entry.timestamp}] ", style="dim")

        # Show details based on what's available
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
            # Show the full message for other grouped events
            msg = entry.message
            if "text_delta" in msg:
                text.append("text_delta", style="green")
            elif "input_json_delta" in msg:
                text.append("input_json_delta", style="blue")
            else:
                # For generic grouped messages, show a truncated version
                if len(msg) > 60:
                    msg = msg[:57] + "..."
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
        self._message_groups.clear()
        self._misc_node = None
        debug_log.clear()

    @property
    def is_expanded(self) -> bool:
        """Check if pane is expanded (manually or auto)."""
        return self._expanded or self._auto_expanded
