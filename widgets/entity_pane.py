"""Entity browser pane for viewing redb storage entities.

Provides a tree view of sessions and their turns, with a detail panel
for inspecting individual records. Useful for debugging and understanding
the underlying storage structure.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from textual.widgets import Static, Tree, Button
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.reactive import reactive
from rich.text import Text
from rich.panel import Panel

from core.async_storage import is_rust_storage_available
from session import _get_storage

if TYPE_CHECKING:
    from core.async_storage import AsyncStorage


class EntityPane(Vertical):
    """Pane for browsing the redb database entities.

    Shows a tree of sessions with their turns as children.
    Selecting an item shows its raw data in the detail panel.
    """

    DEFAULT_CSS = """
    EntityPane {
        width: 100%;
        height: 100%;
        background: $background;
        display: none;
    }

    EntityPane.visible {
        display: block;
    }

    EntityPane > #entity-header {
        dock: top;
        height: auto;
        padding: 1;
        background: $surface;
        border-bottom: solid $primary;
    }

    EntityPane > #entity-header > #header-title {
        width: 1fr;
    }

    EntityPane > #entity-header > Button {
        margin-left: 1;
    }

    EntityPane > #entity-content {
        height: 1fr;
    }

    EntityPane > #entity-content > #entity-tree {
        width: 1fr;
        min-width: 30;
        height: 1fr;
        border-right: solid $primary-darken-2;
    }

    EntityPane > #entity-content > #entity-detail-scroll {
        width: 2fr;
        height: 1fr;
        padding: 1;
    }

    EntityPane > #no-storage {
        height: 1fr;
        content-align: center middle;
        text-style: italic;
        color: $text-muted;
    }
    """

    # Track if we've loaded data
    _loaded = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._storage: AsyncStorage | None = None
        self._sessions_data: list[dict] = []
        self._turns_cache: dict[str, list[dict]] = {}  # session_id -> turns

    def compose(self):
        with Horizontal(id="entity-header"):
            yield Static("🗄️ Entities", id="header-title")
            yield Button("↻ Refresh", id="refresh-btn", variant="default")

        if not is_rust_storage_available():
            yield Static(
                "Rust storage not available.\n\n"
                "Run 'maturin develop' in balloons-rs/\n"
                "to build the storage backend.",
                id="no-storage"
            )
        else:
            with Horizontal(id="entity-content"):
                tree: Tree[dict] = Tree("Sessions", id="entity-tree")
                tree.root.expand()
                yield tree
                with VerticalScroll(id="entity-detail-scroll"):
                    yield Static("Select a session or turn to view details", id="entity-detail")

    async def on_mount(self) -> None:
        """Initialize storage and load data."""
        if is_rust_storage_available():
            try:
                self._storage = _get_storage()
                await self._refresh_data()
            except Exception as e:
                self._show_error(f"Failed to open storage: {e}")

    async def _refresh_data(self) -> None:
        """Reload all sessions from storage."""
        if not self._storage:
            return

        try:
            # Get session list
            self._sessions_data = await self._storage.list_sessions()
            self._turns_cache.clear()
            self._rebuild_tree()
            self._loaded = True
        except Exception as e:
            self._show_error(f"Failed to load sessions: {e}")

    def _rebuild_tree(self) -> None:
        """Rebuild the tree from cached data."""
        try:
            tree = self.query_one("#entity-tree", Tree)
        except Exception:
            return

        tree.root.remove_children()

        # Update root label with count
        count = len(self._sessions_data)
        tree.root.set_label(f"[bold]Sessions[/] [dim]({count})[/]")

        # Sort by updated_at descending (most recent first)
        sorted_sessions = sorted(
            self._sessions_data,
            key=lambda s: s.get("updated_at", 0),
            reverse=True
        )

        for session in sorted_sessions:
            session_id = session.get("id", "unknown")
            name = session.get("name") or session.get("title") or session_id[:8]
            turn_count = session.get("turn_count", 0)

            # Format the label
            label = Text()
            label.append("📁 ", style="")
            label.append(name, style="bold")
            label.append(f" ({turn_count} turns)", style="dim")

            node = tree.root.add(
                label,
                data={"type": "session", "id": session_id, "data": session},
                expand=False
            )

            # Add placeholder for turns (loaded on expand)
            if turn_count > 0:
                node.add_leaf("[dim]Loading turns...[/]", data={"type": "placeholder"})

        tree.root.expand()

    async def _load_turns_for_session(self, session_id: str, node) -> None:
        """Load turns for a session and add them to the tree node."""
        if not self._storage:
            return

        # Check cache first
        if session_id in self._turns_cache:
            turns = self._turns_cache[session_id]
        else:
            try:
                turns = await self._storage.load_turns(session_id)
                self._turns_cache[session_id] = turns
            except Exception as e:
                node.remove_children()
                node.add_leaf(f"[red]Error: {e}[/]", data={"type": "error"})
                return

        # Remove placeholder and add actual turns
        node.remove_children()

        for i, turn in enumerate(turns):
            turn_id = turn.get("id", f"turn-{i}")
            role = turn.get("role", "unknown")
            content_block = turn.get("content_block", {})
            block_type = content_block.get("type", "unknown")

            # Format turn label
            label = Text()
            if role == "user":
                label.append("👤 ", style="")
            elif role == "assistant":
                label.append("🤖 ", style="")
            else:
                label.append("📝 ", style="")

            label.append(f"{role}", style="cyan" if role == "user" else "green")
            label.append(f" [{block_type}]", style="dim")

            # Add preview of content
            preview = self._get_content_preview(content_block)
            if preview:
                label.append(f" - {preview}", style="dim italic")

            node.add_leaf(
                label,
                data={"type": "turn", "id": turn_id, "session_id": session_id, "data": turn}
            )

    def _get_content_preview(self, content_block: dict) -> str:
        """Get a short preview of content block."""
        block_type = content_block.get("type", "")

        if block_type == "text":
            text = content_block.get("text", "")
            # First line, truncated
            first_line = text.split("\n")[0]
            if len(first_line) > 40:
                return first_line[:37] + "..."
            return first_line

        elif block_type == "tool_use":
            name = content_block.get("name", "unknown")
            return f"tool: {name}"

        elif block_type == "tool_result":
            is_error = content_block.get("is_error", False)
            return "error result" if is_error else "result"

        elif block_type == "slide":
            title = content_block.get("title", "")
            return f"slide: {title[:30]}" if title else "slide"

        elif block_type == "fork":
            fork_name = content_block.get("fork_name", "")
            return f"fork: {fork_name}"

        elif block_type == "merge":
            fork_name = content_block.get("fork_name", "")
            return f"merge: {fork_name}"

        return ""

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        """Load turns when a session node is expanded."""
        node_data = event.node.data
        if not node_data:
            return

        if node_data.get("type") == "session":
            session_id = node_data.get("id")
            if session_id and session_id not in self._turns_cache:
                # Load turns asynchronously
                self.run_worker(
                    self._load_turns_for_session(session_id, event.node),
                    name=f"load-turns-{session_id}"
                )

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Show details for selected node."""
        node_data = event.node.data
        if not node_data:
            return

        node_type = node_data.get("type")
        if node_type in ("session", "turn"):
            self._show_detail(node_data)

    def _show_detail(self, node_data: dict) -> None:
        """Show detailed view of selected item."""
        try:
            detail = self.query_one("#entity-detail", Static)
        except Exception:
            return

        node_type = node_data.get("type")
        data = node_data.get("data", {})

        lines = []

        if node_type == "session":
            lines.append(Text("Session Details", style="bold underline cyan"))
            lines.append(Text(""))

            # Basic info
            lines.append(Text("ID: ", style="dim").append(data.get("id", "unknown")))
            lines.append(Text("Name: ", style="dim").append(data.get("name") or data.get("title") or "(untitled)"))
            lines.append(Text("Turn Count: ", style="dim").append(str(data.get("turn_count", 0))))

            # Timestamps
            created = data.get("created_at")
            if created:
                if isinstance(created, (int, float)):
                    created = datetime.fromtimestamp(created).isoformat()
                lines.append(Text("Created: ", style="dim").append(str(created)))

            updated = data.get("updated_at")
            if updated:
                if isinstance(updated, (int, float)):
                    updated = datetime.fromtimestamp(updated).isoformat()
                lines.append(Text("Updated: ", style="dim").append(str(updated)))

            lines.append(Text(""))
            lines.append(Text("Raw Data", style="bold underline"))
            lines.append(Text(""))

            # Pretty print JSON
            try:
                formatted = json.dumps(data, indent=2, default=str)
                # Truncate if too long
                if len(formatted) > 2000:
                    formatted = formatted[:2000] + "\n... (truncated)"
                lines.append(Text(formatted, style="dim"))
            except Exception:
                lines.append(Text(str(data), style="dim"))

        elif node_type == "turn":
            lines.append(Text("Turn Details", style="bold underline cyan"))
            lines.append(Text(""))

            # Basic info
            lines.append(Text("ID: ", style="dim").append(data.get("id", "unknown")))
            lines.append(Text("Role: ", style="dim").append(data.get("role", "unknown")))
            lines.append(Text("Tokens: ", style="dim").append(str(data.get("tokens", 0))))

            context_mode = data.get("context_mode", "unknown")
            mode_style = {
                "copy": "green",
                "compress": "yellow",
                "drop": "red"
            }.get(context_mode, "dim")
            lines.append(Text("Context Mode: ", style="dim").append(context_mode, style=mode_style))

            timestamp = data.get("timestamp", "")
            if timestamp:
                lines.append(Text("Timestamp: ", style="dim").append(timestamp))

            # Content block
            content_block = data.get("content_block", {})
            lines.append(Text(""))
            lines.append(Text("Content Block", style="bold underline"))
            lines.append(Text(f"Type: ", style="dim").append(content_block.get("type", "unknown")))

            # Show content based on type
            block_type = content_block.get("type", "")
            if block_type == "text":
                text = content_block.get("text", "")
                lines.append(Text(""))
                lines.append(Text("Text:", style="dim"))
                # Truncate long text
                if len(text) > 1000:
                    text = text[:1000] + "\n... (truncated)"
                lines.append(Text(text))

            elif block_type == "tool_use":
                lines.append(Text("Tool: ", style="dim").append(content_block.get("name", "unknown"), style="yellow"))
                lines.append(Text("Tool ID: ", style="dim").append(content_block.get("id", "")))
                lines.append(Text(""))
                lines.append(Text("Input:", style="dim"))
                try:
                    input_data = content_block.get("input", {})
                    formatted = json.dumps(input_data, indent=2, default=str)
                    if len(formatted) > 1000:
                        formatted = formatted[:1000] + "\n... (truncated)"
                    lines.append(Text(formatted, style="dim"))
                except Exception:
                    lines.append(Text(str(content_block.get("input", {})), style="dim"))

            elif block_type == "tool_result":
                lines.append(Text("Tool Use ID: ", style="dim").append(content_block.get("tool_use_id", "")))
                is_error = content_block.get("is_error", False)
                lines.append(Text("Is Error: ", style="dim").append(str(is_error), style="red" if is_error else "green"))
                lines.append(Text(""))
                lines.append(Text("Content:", style="dim"))
                result_content = content_block.get("content", "")
                if len(result_content) > 1000:
                    result_content = result_content[:1000] + "\n... (truncated)"
                lines.append(Text(result_content))

            else:
                # Generic: show raw JSON
                lines.append(Text(""))
                lines.append(Text("Raw:", style="dim"))
                try:
                    formatted = json.dumps(content_block, indent=2, default=str)
                    if len(formatted) > 1000:
                        formatted = formatted[:1000] + "\n... (truncated)"
                    lines.append(Text(formatted, style="dim"))
                except Exception:
                    lines.append(Text(str(content_block), style="dim"))

            # Summary if present
            summary = data.get("summary", "")
            if summary:
                lines.append(Text(""))
                lines.append(Text("Summary:", style="bold underline"))
                lines.append(Text(summary, style="italic"))

        # Combine all lines
        output = Text()
        for i, line in enumerate(lines):
            if i > 0:
                output.append("\n")
            if isinstance(line, Text):
                output.append_text(line)
            else:
                output.append(str(line))

        detail.update(output)

    def _show_error(self, message: str) -> None:
        """Show an error message in the detail pane."""
        try:
            detail = self.query_one("#entity-detail", Static)
            detail.update(Text(f"Error: {message}", style="red"))
        except Exception:
            pass

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "refresh-btn":
            await self._refresh_data()

    def show(self) -> None:
        """Show the entity pane."""
        self.add_class("visible")
        if not self._loaded and self._storage:
            self.run_worker(self._refresh_data(), name="initial-load")

    def hide(self) -> None:
        """Hide the entity pane."""
        self.remove_class("visible")
