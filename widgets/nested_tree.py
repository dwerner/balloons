"""Nested session tree - shows fork sessions inline at their fork points.

This is an alternative view to the flat ContextTreeView. Instead of showing all
sessions as siblings at the root level, this tree embeds fork sessions
directly under their parent sessions at the fork point.

Uses TreeState as the source of truth via observer pattern - no local state
duplication. This serves as the reference implementation for pure observer views.
"""

from __future__ import annotations

from textual.widgets import Tree
from textual.containers import Vertical
from textual.message import Message
from textual.events import Key, Click
from textual.timer import Timer
from rich.text import Text
from rich.style import Style
from typing import TYPE_CHECKING, Any
from datetime import datetime

from session import Session
from models import ContextMode, TextBlock, ToolUseBlock, ToolResultBlock, ErrorBlock, ArchiveBlock
from core.tree_state import TreeState, TreeEvent, SessionData, TurnData

if TYPE_CHECKING:
    pass


class NestedTreeWidget(Tree):
    """Tree widget with nested fork sessions shown inline.

    Behavior:
    - Space: toggle context mode (COPY -> COMPRESS -> DROP)
    - Enter: activate/navigate to session
    - a: select all turns in current session
    - n: deselect all turns in current session
    - /: search
    - d/Delete: delete turn or session
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._get_session_color_callback = None

    def set_color_callback(self, callback):
        """Set callback to get session color: callback(session_id) -> color_name"""
        self._get_session_color_callback = callback

    def render_label(self, node, base_style: Style, style: Style) -> Text:
        """Render label with colored expand/collapse icons based on session."""
        TOGGLE_STYLE = Style.from_meta({"toggle": True})

        node_label = node._label.copy()
        node_label.stylize(style)

        if node._allow_expand:
            icon = self.ICON_NODE_EXPANDED if node.is_expanded else self.ICON_NODE

            # Get session color from node data
            session_color = None
            if self._get_session_color_callback and node.data:
                session_id = node.data.get("session_id")
                if session_id:
                    session_color = self._get_session_color_callback(session_id)

            if session_color:
                prefix = Text(icon, style=Style(color=session_color) + TOGGLE_STYLE)
            else:
                prefix = Text(icon, style=base_style + TOGGLE_STYLE)
        else:
            prefix = Text("", style=base_style)

        text = Text.assemble(prefix, node_label)
        return text

    # --- Messages ---

    class ToggleRequested(Message):
        def __init__(self, node_data: dict) -> None:
            self.node_data = node_data
            super().__init__()

    class ActivateRequested(Message):
        """Fired when user presses Enter to activate/navigate."""
        def __init__(self, node_data: dict) -> None:
            self.node_data = node_data
            super().__init__()

    class SelectAllRequested(Message):
        pass

    class SelectNoneRequested(Message):
        pass

    class SearchRequested(Message):
        """Fired when user presses / to start searching."""
        pass

    class TurnDeleteRequested(Message):
        """Fired when user presses d/Delete to delete a turn."""
        def __init__(self, session_id: str, turn_index: int) -> None:
            self.session_id = session_id
            self.turn_index = turn_index
            super().__init__()

    class SessionDeleteRequested(Message):
        """Fired when user presses d/Delete to delete a session."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class LinkRequested(Message):
        """Fired when user ctrl+clicks on a session to create a link."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class ColonPressed(Message):
        """Fired when user types : to jump to text entry with colon."""
        pass

    class ExchangeJumpRequested(Message):
        """Fired when user presses [ or ] on an exchange to jump to first/last turn."""
        def __init__(self, node_data: dict, jump_to: str) -> None:
            self.node_data = node_data
            self.jump_to = jump_to  # "first" or "last"
            super().__init__()

    # --- Click handling ---

    def on_click(self, event: Click) -> None:
        """Handle clicks on tree nodes.

        - Click on exchange navigation controls (⏮/⏭): jump to first/last turn
        - Ctrl+Click on session: create link command

        Uses on_click (message handler) rather than _on_click (override)
        to avoid interfering with the Tree's default click handling.
        """
        meta = event.style.meta

        # Check for exchange navigation control clicks
        if "exchange_jump" in meta:
            if "line" in meta:
                node = self.get_node_at_line(meta["line"])
                if node and node.data and node.data.get("type") == "exchange":
                    self.post_message(self.ExchangeJumpRequested(node.data, meta["exchange_jump"]))
                    event.stop()
                    return

        # Ctrl+Click on session: create link
        if event.ctrl:
            if "line" in meta:
                node = self.get_node_at_line(meta["line"])
                if node and node.data:
                    node_type = node.data.get("type")
                    if node_type == "session":
                        session_id = node.data.get("session_id")
                        if session_id:
                            self.post_message(self.LinkRequested(session_id))
                            event.stop()

    # --- Key handling ---

    async def _on_key(self, event: Key) -> None:
        if event.key == "space":
            node = self.cursor_node
            if node and node.data:
                self.post_message(self.ToggleRequested(node.data))
                event.prevent_default()
                event.stop()
                return
        elif event.key == "enter":
            node = self.cursor_node
            if node and node.data:
                self.post_message(self.ActivateRequested(node.data))
                if node._allow_expand:
                    node.toggle()
                event.prevent_default()
                event.stop()
                return
        elif event.key == "e":
            node = self.cursor_node
            if node and node._allow_expand:
                node.toggle()
                event.prevent_default()
                event.stop()
                return
        elif event.key == "a":
            self.post_message(self.SelectAllRequested())
            event.prevent_default()
            event.stop()
            return
        elif event.key == "n":
            self.post_message(self.SelectNoneRequested())
            event.prevent_default()
            event.stop()
            return
        elif event.key == "slash":
            self.post_message(self.SearchRequested())
            event.prevent_default()
            event.stop()
            return
        elif event.key in ("d", "delete"):
            node = self.cursor_node
            if node and node.data:
                node_type = node.data.get("type")
                if node_type == "turn":
                    self.post_message(self.TurnDeleteRequested(
                        session_id=node.data.get("session_id"),
                        turn_index=node.data.get("turn_idx"),
                    ))
                    event.prevent_default()
                    event.stop()
                    return
                elif node_type == "session":
                    self.post_message(self.SessionDeleteRequested(
                        session_id=node.data.get("session_id"),
                    ))
                    event.prevent_default()
                    event.stop()
                    return
        elif event.key == "colon":
            self.post_message(self.ColonPressed())
            event.prevent_default()
            event.stop()
            return
        elif event.key == "left_square_bracket":
            # Jump to first turn in exchange
            node = self.cursor_node
            if node and node.data and node.data.get("type") == "exchange":
                self.post_message(self.ExchangeJumpRequested(node.data, "first"))
                event.prevent_default()
                event.stop()
                return
        elif event.key == "right_square_bracket":
            # Jump to last turn in exchange
            node = self.cursor_node
            if node and node.data and node.data.get("type") == "exchange":
                self.post_message(self.ExchangeJumpRequested(node.data, "last"))
                event.prevent_default()
                event.stop()
                return
        elif event.key == "right":
            node = self.cursor_node
            if node and node._allow_expand and not node.is_expanded:
                node.expand()
                event.prevent_default()
                event.stop()
                return
        elif event.key == "left":
            node = self.cursor_node
            if node:
                if node.is_expanded:
                    node.collapse()
                    event.prevent_default()
                    event.stop()
                    return
                elif node.parent and node.parent != self.root:
                    self.select_node(node.parent)
                    event.prevent_default()
                    event.stop()
                    return
        await super()._on_key(event)


class NestedTreeView(Vertical):
    """View container for nested session tree.

    Shows sessions with forks embedded inline at their fork points,
    rather than as separate root-level nodes.

    This is a PURE OBSERVER implementation - all state comes from TreeState.
    No local state duplication. This serves as the reference implementation
    for how views should interact with TreeState.
    """

    DEFAULT_CSS = """
    NestedTreeView {
        width: 40;
        height: 100%;
        border-right: solid $primary;
    }

    NestedTreeView > NestedTreeWidget {
        height: 1fr;
        background: $background;
    }
    """

    # --- Messages (mirror ContextTreeView's interface) ---

    class SelectionChanged(Message):
        """Fired when selection changes."""
        def __init__(
            self,
            selected_count: int,
            total_tokens: int,
            selected_tokens: int,
            current_session_turn_ids: list[int],
            turn_modes: dict[int, str] | None = None,
        ) -> None:
            self.selected_count = selected_count
            self.total_tokens = total_tokens
            self.selected_tokens = selected_tokens
            self.selected_turn_ids = current_session_turn_ids
            self.show_all = False
            self.turn_modes = turn_modes or {}
            super().__init__()

    class SessionActivated(Message):
        """Fired when user clicks on a session to view it."""
        def __init__(self, session: Session) -> None:
            self.session = session
            super().__init__()

    class TurnInspected(Message):
        """Fired when user selects a turn to inspect its data."""
        def __init__(self, turn_data: dict, session_id: str | None = None) -> None:
            self.turn_data = turn_data
            self.session_id = session_id
            super().__init__()

    class ContextModeChanged(Message):
        """Fired when a turn's context mode is toggled."""
        def __init__(self, session_id: str, turn_idx: int, new_mode: ContextMode) -> None:
            self.session_id = session_id
            self.turn_idx = turn_idx
            self.new_mode = new_mode
            super().__init__()

    class TurnDeleteRequested(Message):
        """Fired when user requests to delete a turn."""
        def __init__(self, session_id: str, turn_index: int) -> None:
            self.session_id = session_id
            self.turn_index = turn_index
            super().__init__()

    class SessionDeleteRequested(Message):
        """Fired when user requests to delete a session."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class SessionLinkRequested(Message):
        """Fired when user ctrl+clicks a session to create a link command."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class SessionLoadRequested(Message):
        """Fired when a session needs to be loaded to show its turns."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class ColonPressed(Message):
        """Fired when user types : to jump to text entry."""
        pass

    # Spinner animation for streaming sessions
    _spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, tree_state: TreeState, **kwargs):
        super().__init__(**kwargs)
        # TreeState is the ONLY source of truth
        self._state = tree_state

        # Node references only (Textual-specific, not state)
        # session_id -> tree node
        self._session_nodes: dict[str, Any] = {}
        # (session_id, turn_idx) -> tree node
        self._turn_nodes: dict[tuple[str, int], Any] = {}

        # Spinner animation state
        self._spinner_frame: int = 0
        self._spinner_timer: Timer | None = None

    def compose(self):
        tree = NestedTreeWidget("[dim]loading...[/]", id="nested-tree-widget")
        tree.root.data = {"type": "root"}
        tree.set_color_callback(self._get_session_color)
        yield tree

    def on_mount(self) -> None:
        tree = self.query_one("#nested-tree-widget", NestedTreeWidget)
        tree.root.expand()
        tree.root.allow_expand = False
        tree.auto_expand = False

        # Register as observer
        self._state.add_observer(self._on_tree_state_event)

        # Initial build from current state
        self._rebuild_tree()

        # Start spinner if any sessions are already streaming
        if self._state.get_streaming_sessions():
            self._start_spinner()

    def on_unmount(self) -> None:
        self._state.remove_observer(self._on_tree_state_event)
        self._stop_spinner()

    # --- Observer Event Handler ---

    def _on_tree_state_event(self, event: TreeEvent, data: dict) -> None:
        """Handle all state change notifications from TreeState.

        This is the PURE OBSERVER approach - all UI updates come through here.
        """
        if event == TreeEvent.FULL_REBUILD:
            self._rebuild_tree()

        elif event == TreeEvent.SESSION_ADDED:
            # A new session was added - rebuild to show it
            self._rebuild_tree()

        elif event == TreeEvent.SESSION_REMOVED:
            session_id = data.get("session_id")
            if session_id and session_id in self._session_nodes:
                node = self._session_nodes.pop(session_id)
                node.remove()
                # Clean up turn nodes for this session
                keys_to_remove = [k for k in self._turn_nodes if k[0] == session_id]
                for key in keys_to_remove:
                    del self._turn_nodes[key]
                self._update_root_label()

        elif event == TreeEvent.SESSION_SELECTED:
            # Update labels to show which session is current
            prev_id = data.get("prev_session_id")
            new_id = data.get("session_id")
            if prev_id:
                self._update_session_label(prev_id)
            if new_id:
                self._update_session_label(new_id)
            self._update_root_label()

        elif event == TreeEvent.SESSION_LOADED:
            # Session data loaded - populate its turns
            session_id = data.get("session_id")
            if session_id:
                self._populate_session_turns(session_id)

        elif event == TreeEvent.SESSION_UPDATED:
            # Session data changed (e.g., cached_context_tokens updated after archive)
            # Re-render the session label to show new values
            session_id = data.get("session_id")
            if session_id:
                self._update_session_label(session_id)

        elif event == TreeEvent.STREAMING_STARTED:
            session_id = data.get("session_id")
            if session_id:
                self._update_session_label(session_id)
                self._start_spinner()

        elif event == TreeEvent.STREAMING_STOPPED:
            session_id = data.get("session_id")
            if session_id:
                self._update_session_label(session_id)
                # Stop spinner if no sessions are streaming
                if not self._state.get_streaming_sessions():
                    self._stop_spinner()

        elif event == TreeEvent.TURN_STARTED:
            session_id = data.get("session_id")
            turn_idx = data.get("turn_idx")
            role = data.get("role")
            if session_id and turn_idx is not None and role:
                self._add_turn_node(session_id, turn_idx, role, streaming=True)

        elif event == TreeEvent.TURN_FINISHED:
            session_id = data.get("session_id")
            turn_idx = data.get("turn_idx")
            content = data.get("content", "")
            content_blocks = data.get("content_blocks", [])
            if session_id and turn_idx is not None:
                self._finalize_turn_node(session_id, turn_idx, content, content_blocks)

        elif event == TreeEvent.CONTEXT_MODE_CHANGED:
            session_id = data.get("session_id")
            turn_idx = data.get("turn_idx")
            if session_id and turn_idx is not None:
                self._update_turn_label(session_id, turn_idx)
                self._update_root_label()

        elif event == TreeEvent.TOOL_USE_STARTED:
            # Could add tool use nodes during streaming
            pass

        elif event == TreeEvent.TOOL_RESULT_ADDED:
            # Could add tool result nodes
            pass

    # --- Spinner Animation ---

    def _start_spinner(self) -> None:
        """Start the spinner animation for streaming sessions."""
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.1, self._advance_spinner)

    def _stop_spinner(self) -> None:
        """Stop the spinner animation."""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
            self._spinner_frame = 0

    def _advance_spinner(self) -> None:
        """Advance the spinner to the next frame and update streaming labels."""
        self._spinner_frame = (self._spinner_frame + 1) % len(self._spinner_chars)
        # Update labels for all streaming sessions
        for session_id in self._state.get_streaming_sessions():
            self._update_session_label(session_id)

    # --- Helper Methods ---

    def _get_session_color(self, session_id: str) -> str | None:
        """Get color for a session from TreeState."""
        return self._state.get_session_color(session_id)

    def _rebuild_tree(self) -> None:
        """Rebuild the entire tree from TreeState."""
        tree = self.query_one("#nested-tree-widget", NestedTreeWidget)
        tree.root.remove_children()
        self._session_nodes.clear()
        self._turn_nodes.clear()

        # Get all sessions from TreeState
        all_sessions = self._state.get_all_sessions()
        current_id = self._state.get_current_session_id()

        # Build parent -> children map
        children_map: dict[str | None, list[str]] = {}
        for session_id, session_data in all_sessions.items():
            parent_id = session_data.parent_id
            children_map.setdefault(parent_id, []).append(session_id)

        # Add root sessions (those with no parent)
        root_sessions = children_map.get(None, [])

        # Sort by last_modified descending
        root_sessions.sort(
            key=lambda sid: all_sessions[sid].last_modified,
            reverse=True
        )

        for session_id in root_sessions:
            self._add_session_subtree(
                tree.root,
                session_id,
                all_sessions,
                children_map,
                current_id
            )

        self._update_root_label()

    def _add_session_subtree(
        self,
        parent_node,
        session_id: str,
        all_sessions: dict[str, SessionData],
        children_map: dict[str | None, list[str]],
        current_id: str | None,
    ) -> None:
        """Add a session and its nested forks to the tree."""
        session_data = all_sessions.get(session_id)
        if not session_data:
            return

        is_current = session_id == current_id
        label = self._make_session_label(session_data, is_current)

        session_node = parent_node.add(
            label,
            data={"type": "session", "session_id": session_id}
        )
        self._session_nodes[session_id] = session_node

        if is_current:
            session_node.expand()

        # If session is loaded, add turns
        if session_data.is_loaded and session_data.turns:
            self._add_turns_to_node(session_node, session_id, session_data.turns)

        # Add child sessions (forks) directly as children of this session
        child_ids = children_map.get(session_id, [])
        for child_id in child_ids:
            # Add fork session directly under parent (no wrapper node)
            self._add_session_subtree(
                session_node,
                child_id,
                all_sessions,
                children_map,
                current_id
            )

    def _add_turns_to_node(
        self,
        session_node,
        session_id: str,
        turns: list[TurnData]
    ) -> None:
        """Add turn nodes to a session node, grouped by exchange_id.

        Turns with the same exchange_id are grouped under an exchange node.
        Turns without an exchange_id (or alone in their exchange) are added directly.
        """
        session_data = self._state.get_session(session_id)
        if not session_data or not session_data.turns:
            return

        groups = self._state.get_turns_grouped_by_exchange(session_id)

        for group in groups:
            if len(group) == 1:
                # Single turn - add directly to session node
                self._add_single_turn_node(session_node, session_id, group[0])
            else:
                # Multiple turns - create exchange group node
                exchange_id = group[0].exchange_id
                exchange_label = self._make_exchange_label(group)
                exchange_node = session_node.add(
                    exchange_label,
                    data={
                        "type": "exchange",
                        "session_id": session_id,
                        "exchange_id": exchange_id,
                        "turn_indices": [t.idx for t in group],
                    }
                )
                # Add turns under the exchange node
                for turn in group:
                    self._add_single_turn_node(exchange_node, session_id, turn)

    def _has_displayable_children(self, content_blocks: list) -> bool:
        """Check if content_blocks contains any items that will be displayed as children."""
        if not content_blocks:
            return False
        for block in content_blocks:
            if isinstance(block, TextBlock) and block.text.strip():
                return True
            elif isinstance(block, (ToolUseBlock, ToolResultBlock)):
                return True
        return False

    def _add_single_turn_node(
        self,
        parent_node,
        session_id: str,
        turn: TurnData
    ) -> None:
        """Add a single turn node to a parent (session or exchange group)."""
        mode = self._state.get_context_mode(session_id, turn.idx)
        label = self._make_turn_label(turn.role, turn.content, mode, turn.content_blocks)
        has_children = self._has_displayable_children(turn.content_blocks)
        turn_node = parent_node.add(
            label,
            data={"type": "turn", "session_id": session_id, "turn_idx": turn.idx},
            allow_expand=has_children,
        )
        self._turn_nodes[(session_id, turn.idx)] = turn_node

        # Add tool use blocks as children
        if has_children:
            self._add_content_block_nodes(turn_node, session_id, turn.idx, turn.content_blocks)

    def _add_content_block_nodes(
        self,
        turn_node,
        session_id: str,
        turn_idx: int,
        content_blocks: list
    ) -> None:
        """Add child nodes for tool uses and results."""
        import json
        tool_use_nodes: dict[str, Any] = {}

        for block_idx, block in enumerate(content_blocks):
            if isinstance(block, TextBlock):
                if block.text.strip():
                    text_preview = block.text[:50].replace("\n", " ")
                    if len(block.text) > 50:
                        text_preview += "..."
                    turn_node.add(
                        f"[dim]💬[/] {text_preview}",
                        data={
                            "type": "text",
                            "session_id": session_id,
                            "turn_idx": turn_idx,
                            "block_idx": block_idx,
                        }
                    )
            elif isinstance(block, ToolUseBlock):
                input_preview = json.dumps(block.input)[:50]
                if len(json.dumps(block.input)) > 50:
                    input_preview += "..."
                tool_node = turn_node.add(
                    f"[cyan]🔧 {block.name}[/] {input_preview}",
                    data={
                        "type": "tool_use",
                        "session_id": session_id,
                        "turn_idx": turn_idx,
                        "block_idx": block_idx,
                        "tool_use_id": block.id,
                    }
                )
                tool_use_nodes[block.id] = tool_node
            elif isinstance(block, ToolResultBlock):
                content_preview = str(block.content)[:50]
                if len(str(block.content)) > 50:
                    content_preview += "..."
                error_indicator = "[red]❌[/] " if block.is_error else ""
                parent = tool_use_nodes.get(block.tool_use_id, turn_node)
                parent.add(
                    f"{error_indicator}[blue]📋 Result[/] {content_preview}",
                    data={
                        "type": "tool_result",
                        "session_id": session_id,
                        "turn_idx": turn_idx,
                        "block_idx": block_idx,
                    }
                )

    def _populate_session_turns(self, session_id: str) -> None:
        """Populate a session's turns after it's loaded.

        Adds turn nodes at the beginning of the session node's children,
        before any fork session children.
        """
        session_node = self._session_nodes.get(session_id)
        if not session_node:
            return

        session_data = self._state.get_session(session_id)
        if not session_data or not session_data.turns:
            return

        # Clear ALL turn-related children from session node (turns AND exchange groups)
        # to prevent double-nesting when streaming adds flat nodes and then
        # SESSION_LOADED triggers grouped rebuild
        keys_to_remove = [k for k in self._turn_nodes if k[0] == session_id]
        for key in keys_to_remove:
            del self._turn_nodes[key]

        # Remove all children that are turns or exchanges (keep fork sessions)
        children_to_remove = []
        for child in session_node.children:
            if child.data:
                node_type = child.data.get("type")
                if node_type in ("turn", "exchange"):
                    children_to_remove.append(child)
        for child in children_to_remove:
            child.remove()

        # Add turn nodes using the grouping logic
        self._add_turns_to_node(session_node, session_id, session_data.turns)

        # Update session label (may have new message count)
        self._update_session_label(session_id)

    def _add_turn_node(
        self,
        session_id: str,
        turn_idx: int,
        role: str,
        streaming: bool = False
    ) -> None:
        """Add a turn node (called during streaming)."""
        session_node = self._session_nodes.get(session_id)
        if not session_node:
            return

        if streaming:
            content = "[dim]streaming...[/]"
        else:
            turn_data = self._state.get_turn(session_id, turn_idx)
            content = turn_data.content if turn_data else ""

        mode = self._state.get_context_mode(session_id, turn_idx)
        label = self._make_turn_label(role, content, mode)

        turn_node = session_node.add(
            label,
            data={"type": "turn", "session_id": session_id, "turn_idx": turn_idx}
        )
        turn_node.expand()
        self._turn_nodes[(session_id, turn_idx)] = turn_node

        # Update session label (message count)
        self._update_session_label(session_id)
        self._update_root_label()

    def _finalize_turn_node(
        self,
        session_id: str,
        turn_idx: int,
        content: str,
        content_blocks: list
    ) -> None:
        """Finalize a streaming turn."""
        turn_node = self._turn_nodes.get((session_id, turn_idx))
        if not turn_node:
            return

        turn_data = self._state.get_turn(session_id, turn_idx)
        if not turn_data:
            return

        mode = self._state.get_context_mode(session_id, turn_idx)
        turn_node.label = self._make_turn_label(turn_data.role, content, mode, content_blocks)

        # Clear and rebuild content block children
        turn_node.remove_children()
        self._add_content_block_nodes(turn_node, session_id, turn_idx, content_blocks)

        self._update_root_label()

    def _update_turn_label(self, session_id: str, turn_idx: int) -> None:
        """Update a turn's label (e.g., after context mode change)."""
        turn_node = self._turn_nodes.get((session_id, turn_idx))
        if not turn_node:
            return

        turn_data = self._state.get_turn(session_id, turn_idx)
        if not turn_data:
            return

        mode = self._state.get_context_mode(session_id, turn_idx)
        turn_node.label = self._make_turn_label(
            turn_data.role, turn_data.content, mode, turn_data.content_blocks
        )

    def _update_session_label(self, session_id: str) -> None:
        """Update a session node's label."""
        session_node = self._session_nodes.get(session_id)
        if not session_node:
            return

        session_data = self._state.get_session(session_id)
        if not session_data:
            return

        is_current = session_id == self._state.get_current_session_id()
        session_node.label = self._make_session_label(session_data, is_current)

    def _update_root_label(self) -> None:
        """Update root label with token counts.

        Token counts come from TreeState (calculated by app from compiled context).
        This ensures consistency with context_tree.py and status bar.
        """
        tree = self.query_one("#nested-tree-widget", NestedTreeWidget)

        current_id = self._state.get_current_session_id()
        if not current_id:
            tree.root.label = "[bold]Sessions[/]"
            return

        session_data = self._state.get_session(current_id)
        if not session_data or not session_data.turns:
            tree.root.label = "[bold]Sessions[/]"
            return

        # Build turn_modes for SelectionChanged message
        turn_modes: dict[int, str] = {}
        for turn in session_data.turns:
            mode = self._state.get_context_mode(current_id, turn.idx)
            turn_modes[turn.idx + 1] = mode.name

        # Get token counts from TreeState (calculated by app from compiled context)
        # This ensures consistency with context_tree.py and status bar
        selected_tokens, total_tokens = self._state.get_context_tokens()

        tree.root.label = f"[bold]Context:[/] {selected_tokens:,} [dim]tokens[/]"

        # Post selection changed message
        selected_count = sum(
            1 for (sid, _), m in self._state.get_all_context_modes().items()
            if m != ContextMode.DROP and sid == current_id
        )
        selected_turn_ids = [
            idx + 1 for (sid, idx) in self._state.get_all_context_modes()
            if self._state.get_context_mode(sid, idx) != ContextMode.DROP and sid == current_id
        ]

        self.post_message(self.SelectionChanged(
            selected_count, total_tokens, selected_tokens, selected_turn_ids, turn_modes
        ))

    # --- Label Formatters ---

    def _make_session_label(self, session_data: SessionData, is_active: bool) -> str:
        """Create a label for a session node."""
        try:
            dt = datetime.fromisoformat(session_data.created)
            date_str = dt.strftime("%b %d %H:%M")
        except:
            date_str = session_data.created[:16] if session_data.created else ""

        msg_count = session_data.message_count

        # Fork indicator
        if session_data.parent_id:
            if session_data.fork_status == "merged":
                prefix = "[green]✓[/] "
            else:
                prefix = "[magenta]↳[/] "
        else:
            prefix = ""

        # Animated streaming indicator
        if self._state.is_streaming(session_data.id):
            spinner = self._spinner_chars[self._spinner_frame]
            streaming = f"[yellow]{spinner}[/] "
        else:
            streaming = ""

        # Name
        if session_data.fork_name:
            name = session_data.fork_name
        elif session_data.title:
            name = session_data.title[:25] + "..." if len(session_data.title) > 25 else session_data.title
        else:
            name = None

        id_prefix = f"[dim]{session_data.id[:8]}[/] "

        if name:
            label = f"{id_prefix}{name} [dim]({msg_count}msg)[/]"
        else:
            label = f"{id_prefix}{date_str} [dim]({msg_count}msg)[/]"

        if is_active:
            return f"{prefix}{streaming}[bold cyan]{label}[/]"
        else:
            return f"{prefix}{streaming}{label}"

    def _make_exchange_label(self, group: list[TurnData]) -> Text:
        """Create a label for an exchange group node.

        Shows the first turn's content preview and a count of turns in the exchange.
        Shows an error indicator if any turn in the exchange has an ErrorBlock.
        Includes clickable ⏮ and ⏭ controls to jump to first/last turn.
        """
        turn_count = len(group)
        first_turn = group[0]

        # Get a preview from the first turn's content
        preview = first_turn.content[:25] + "..." if len(first_turn.content) > 25 else first_turn.content
        preview = preview.replace("\n", " ")

        # Count tool uses and check for errors across all turns in the exchange
        tool_count = 0
        has_error = False
        for turn in group:
            if turn.content_blocks:
                tool_count += sum(1 for b in turn.content_blocks if isinstance(b, ToolUseBlock))
                if not has_error:
                    has_error = any(isinstance(b, ErrorBlock) for b in turn.content_blocks)

        # Build the label as a Text object with clickable navigation controls
        label = Text()
        label.append(f"⟨{turn_count}⟩", style="dim")

        if tool_count > 0:
            label.append(f" 🔧{tool_count}", style="cyan")

        if has_error:
            label.append(" ⚠", style="yellow")

        # Add clickable navigation controls for exchanges with multiple turns
        if turn_count > 1:
            label.append(" ")
            # First turn button - clickable with meta
            label.append("⏮", style=Style(color="blue", meta={"exchange_jump": "first"}))
            label.append(" ")
            # Last turn button - clickable with meta
            label.append("⏭", style=Style(color="blue", meta={"exchange_jump": "last"}))

        label.append(f" {preview}")

        return label

    def _make_turn_label(
        self,
        role: str,
        content: str,
        mode: ContextMode,
        content_blocks: list = None
    ) -> str:
        """Create a label for a turn node."""
        # Check for archive block first
        if content_blocks:
            for block in content_blocks:
                if isinstance(block, ArchiveBlock):
                    # Archive marker - use 📦 and show work summary
                    if mode == ContextMode.COPY:
                        indicator = "[green]☑[/]"
                    elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
                        indicator = "[yellow]Σ[/]"
                    else:
                        indicator = "☐"
                    summary = block.structured_summary.work_done if block.structured_summary else block.summary
                    preview = summary[:40] + "..." if len(summary) > 40 else summary
                    preview = preview.replace("\n", " ")
                    return f"{indicator} 📦 {preview}"

        if mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            indicator = "[yellow]Σ[/]"
        else:
            indicator = "☐"

        icon = "👤" if role == "user" else "🤖"

        # Count tool uses and check for errors
        tool_count = 0
        has_error = False
        if content_blocks:
            tool_count = sum(1 for b in content_blocks if isinstance(b, ToolUseBlock))
            has_error = any(isinstance(b, ErrorBlock) for b in content_blocks)

        preview = content[:30] + "..." if len(content) > 30 else content
        preview = preview.replace("\n", " ")

        tool_indicator = f" [cyan]🔧{tool_count}[/]" if tool_count > 0 else ""
        error_indicator = " [yellow]⚠[/]" if has_error else ""
        return f"{indicator} {icon}{tool_indicator}{error_indicator} {preview}"

    # --- Event Handlers (from NestedTreeWidget) ---

    def on_nested_tree_toggle_requested(self, event: NestedTreeWidget.ToggleRequested) -> None:
        """Handle space bar toggle."""
        node_type = event.node_data.get("type")

        if node_type == "turn":
            session_id = event.node_data.get("session_id")
            turn_idx = event.node_data.get("turn_idx")

            # Use TreeState to toggle
            new_mode = self._state.toggle_context_mode(session_id, turn_idx)

            # TreeState fires CONTEXT_MODE_CHANGED, which updates our UI
            # Also notify app to persist
            self.post_message(self.ContextModeChanged(session_id, turn_idx, new_mode))

    def on_nested_tree_activate_requested(self, event: NestedTreeWidget.ActivateRequested) -> None:
        """Handle Enter key - activate session."""
        node_type = event.node_data.get("type")

        if node_type == "session":
            session_id = event.node_data.get("session_id")
            session_data = self._state.get_session(session_id)
            if session_data:
                # Request session load if not loaded yet
                if not session_data.is_loaded:
                    self.post_message(self.SessionLoadRequested(session_id))
                # Activate if we have the session ref
                if session_data.session_ref:
                    self.post_message(self.SessionActivated(session_data.session_ref))

        elif node_type == "turn":
            session_id = event.node_data.get("session_id")
            turn_idx = event.node_data.get("turn_idx")
            turn_data = self._state.get_turn(session_id, turn_idx)
            if turn_data:
                self.post_message(self.TurnInspected({
                    "type": "turn",
                    "role": turn_data.role,
                    "content": turn_data.content,
                    "content_blocks": turn_data.content_blocks,
                    "turn_idx": turn_idx,
                }, session_id))

        elif node_type == "exchange":
            session_id = event.node_data.get("session_id")
            turn_indices = event.node_data.get("turn_indices", [])
            if turn_indices:
                # Get first turn in exchange to scroll to
                # Use scroll_to_top=True so the first turn is at the top of viewport
                first_turn_idx = turn_indices[0]
                turn_data = self._state.get_turn(session_id, first_turn_idx)
                if turn_data:
                    self.post_message(self.TurnInspected({
                        "type": "turn",
                        "role": turn_data.role,
                        "content": turn_data.content,
                        "content_blocks": turn_data.content_blocks,
                        "turn_idx": first_turn_idx,
                        "scroll_to_top": True,  # Exchange clicks should scroll first turn to top
                    }, session_id))

    def on_nested_tree_select_all_requested(self, event: NestedTreeWidget.SelectAllRequested) -> None:
        """Set all turns in current session to COPY."""
        current_id = self._state.get_current_session_id()
        if not current_id:
            return

        session_data = self._state.get_session(current_id)
        if not session_data or not session_data.turns:
            return

        for turn in session_data.turns:
            self._state.set_context_mode(current_id, turn.idx, ContextMode.COPY)

    def on_nested_tree_select_none_requested(self, event: NestedTreeWidget.SelectNoneRequested) -> None:
        """Set all turns in current session to DROP."""
        current_id = self._state.get_current_session_id()
        if not current_id:
            return

        session_data = self._state.get_session(current_id)
        if not session_data or not session_data.turns:
            return

        for turn in session_data.turns:
            self._state.set_context_mode(current_id, turn.idx, ContextMode.DROP)

    def on_nested_tree_turn_delete_requested(self, event: NestedTreeWidget.TurnDeleteRequested) -> None:
        """Bubble up turn delete request."""
        self.post_message(self.TurnDeleteRequested(event.session_id, event.turn_index))

    def on_nested_tree_session_delete_requested(self, event: NestedTreeWidget.SessionDeleteRequested) -> None:
        """Bubble up session delete request."""
        self.post_message(self.SessionDeleteRequested(event.session_id))

    def on_nested_tree_link_requested(self, event: NestedTreeWidget.LinkRequested) -> None:
        """Bubble up link request."""
        self.post_message(self.SessionLinkRequested(event.session_id))

    def on_nested_tree_colon_pressed(self, event: NestedTreeWidget.ColonPressed) -> None:
        """Bubble up colon pressed to jump to text entry."""
        self.post_message(self.ColonPressed())

    def on_nested_tree_exchange_jump_requested(self, event: NestedTreeWidget.ExchangeJumpRequested) -> None:
        """Handle [ and ] keys to jump to first/last turn in exchange."""
        session_id = event.node_data.get("session_id")
        turn_indices = event.node_data.get("turn_indices", [])
        if not session_id or not turn_indices:
            return

        # Select the first or last turn index
        if event.jump_to == "first":
            target_idx = turn_indices[0]
        else:  # "last"
            target_idx = turn_indices[-1]

        # Find and scroll to the turn node
        turn_node = self._turn_nodes.get((session_id, target_idx))
        if turn_node:
            tree = self.query_one("#nested-tree-widget", NestedTreeWidget)
            tree.select_node(turn_node)
            tree.scroll_to_node(turn_node)

            # Also fire TurnInspected so chat log scrolls to the turn
            turn_data = self._state.get_turn(session_id, target_idx)
            if turn_data:
                self.post_message(self.TurnInspected({
                    "type": "turn",
                    "role": turn_data.role,
                    "content": turn_data.content,
                    "content_blocks": turn_data.content_blocks,
                    "turn_idx": target_idx,
                    "scroll_to_top": event.jump_to == "first",
                }, session_id))

    def on_tree_node_expanded(self, event) -> None:
        """Handle node expansion - request session load if not loaded."""
        node_data = event.node.data
        if not node_data:
            return

        node_type = node_data.get("type")
        if node_type == "session":
            session_id = node_data.get("session_id")
            if session_id:
                session_data = self._state.get_session(session_id)
                if session_data and not session_data.is_loaded:
                    self.post_message(self.SessionLoadRequested(session_id))

    # --- Public API (for compatibility with app) ---

    @property
    def state(self) -> TreeState:
        """Access the underlying TreeState."""
        return self._state

    def scroll_to_turn(self, session_id: str, turn_idx: int) -> bool:
        """Scroll to and highlight a specific turn in the tree.

        Args:
            session_id: The session containing the turn
            turn_idx: The 0-based turn index

        Returns:
            True if the turn was found and scrolled to, False otherwise
        """
        tree = self.query_one("#nested-tree-widget", NestedTreeWidget)

        # Ensure the session node exists and is expanded
        session_node = self._session_nodes.get(session_id)
        if session_node:
            session_node.expand()

        # Try to find the turn node
        turn_node = self._turn_nodes.get((session_id, turn_idx))
        if turn_node:
            tree.select_node(turn_node)
            tree.scroll_to_node(turn_node)
            return True

        return False

    def expand_session(self, session_id: str) -> None:
        """Expand a session node to show its turns."""
        session_node = self._session_nodes.get(session_id)
        if session_node:
            session_node.expand()
