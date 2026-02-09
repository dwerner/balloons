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
from rich.markup import escape as escape_markup
from typing import TYPE_CHECKING, Any
from datetime import datetime

from session import Session
from models import ContextMode, TextBlock, ToolUseBlock, ToolResultBlock, ErrorBlock, ArchiveBlock, ForkBlock, MergeBlock, MergedToBlock, LinkBlock, InterruptionBlock
from core.tree_state import TreeState, TreeEvent, SessionData, TurnData
from core.debug_log import debug_log

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

    class ExchangeDeleteRequested(Message):
        """Fired when user presses d/Delete to delete an exchange group."""
        def __init__(self, session_id: str, turn_indices: list[int]) -> None:
            self.session_id = session_id
            self.turn_indices = turn_indices
            super().__init__()

    class LinkRequested(Message):
        """Fired when user ctrl+clicks on a session to create a link."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class ColonPressed(Message):
        """Fired when user types : to jump to text entry with colon."""
        pass

    class ArchiveRequested(Message):
        """Fired when user requests to archive turns (e.g., from exchange group)."""
        def __init__(self, session_id: str, turn_indices: list[int]) -> None:
            self.session_id = session_id
            self.turn_indices = turn_indices
            super().__init__()

    class JumpToExchangeEnd(Message):
        """Fired when user presses 'g' on an exchange group to jump to its last turn."""
        def __init__(self, session_id: str, last_turn_idx: int) -> None:
            self.session_id = session_id
            self.last_turn_idx = last_turn_idx
            super().__init__()

    # --- Click handling ---

    def on_click(self, event: Click) -> None:
        """Handle clicks on tree nodes.

        - Ctrl+Click on session: create link command

        Uses on_click (message handler) rather than _on_click (override)
        to avoid interfering with the Tree's default click handling.
        """
        meta = event.style.meta

        # Ctrl+Click on session: create link
        if event.ctrl:
            if "line" in meta:
                node = self.get_node_at_line(meta["line"])
                if node and node.data:
                    node_type = node.data.get("type")
                    if node_type == "session":
                        session_id = node.data.get("session_id")
                        debug_log.info(f"LINK DEBUG (nested): ctrl+click on node_type={node_type}, session_id='{session_id}' (len={len(session_id) if session_id else 0})", category="link")
                        debug_log.info(f"LINK DEBUG (nested): full node.data = {node.data}", category="link")
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
                elif node_type == "exchange_group":
                    turn_indices = node.data.get("turn_indices", [])
                    if turn_indices:
                        self.post_message(self.ExchangeDeleteRequested(
                            session_id=node.data.get("session_id"),
                            turn_indices=turn_indices,
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
        elif event.key == "x":
            # Archive selected node (exchange group or single turn)
            node = self.cursor_node
            if node and node.data:
                node_type = node.data.get("type")
                session_id = node.data.get("session_id")
                if session_id:
                    if node_type == "exchange_group":
                        turn_indices = node.data.get("turn_indices", [])
                        if turn_indices:
                            self.post_message(self.ArchiveRequested(session_id, turn_indices))
                            event.prevent_default()
                            event.stop()
                            return
                    elif node_type == "turn":
                        turn_idx = node.data.get("turn_idx")
                        if turn_idx is not None:
                            self.post_message(self.ArchiveRequested(session_id, [turn_idx]))
                            event.prevent_default()
                            event.stop()
                            return
        elif event.key == "colon":
            self.post_message(self.ColonPressed())
            event.prevent_default()
            event.stop()
            return
        elif event.key == "g":
            # Jump to end of exchange group (on exchange_group nodes)
            node = self.cursor_node
            if node and node.data:
                node_type = node.data.get("type")
                if node_type == "exchange_group":
                    session_id = node.data.get("session_id")
                    turn_indices = node.data.get("turn_indices", [])
                    if session_id and turn_indices:
                        last_turn_idx = max(turn_indices)
                        self.post_message(self.JumpToExchangeEnd(session_id, last_turn_idx))
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

    class ExchangeDeleteRequested(Message):
        """Fired when user requests to delete an exchange group."""
        def __init__(self, session_id: str, turn_indices: list[int]) -> None:
            self.session_id = session_id
            self.turn_indices = turn_indices
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

    class ArchiveRequested(Message):
        """Fired when user requests to archive turns (x key on turn or exchange group)."""
        def __init__(self, session_id: str, turn_indices: list[int]) -> None:
            self.session_id = session_id
            self.turn_indices = turn_indices
            super().__init__()

    class ColonPressed(Message):
        """Fired when user types : to jump to text entry."""
        pass

    class JumpToExchangeEnd(Message):
        """Fired when user presses 'g' on an exchange group to jump to its last turn."""
        def __init__(self, session_id: str, last_turn_idx: int) -> None:
            self.session_id = session_id
            self.last_turn_idx = last_turn_idx
            super().__init__()

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
            content_block = data.get("content_block")
            if session_id and turn_idx is not None:
                self._finalize_turn_node(session_id, turn_idx, content, content_block)

        elif event == TreeEvent.CONTEXT_MODE_CHANGED:
            session_id = data.get("session_id")
            turn_idx = data.get("turn_idx")
            if session_id and turn_idx is not None:
                self._update_turn_label(session_id, turn_idx)
                self._update_root_label()

        elif event == TreeEvent.TURN_VIEWED:
            # Turn was marked as viewed - update label to remove unviewed indicator
            session_id = data.get("session_id")
            turn_idx = data.get("turn_idx")
            if session_id and turn_idx is not None:
                self._update_turn_label(session_id, turn_idx)
                self._update_session_label(session_id)

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
        """Add a session and its nested forks to the tree.

        Forks are interleaved with exchange groups based on their fork_point,
        so they appear in the tree at the position where they were created.
        """
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

        # Get child session IDs and their fork points
        child_ids = children_map.get(session_id, [])

        # Build map of child_id -> fork_point from session_data.children
        child_fork_points: dict[str, int] = {}
        for child_info in session_data.children:
            child_id = child_info.get("session_id")
            fork_point = child_info.get("fork_point", -1)
            if child_id and fork_point >= 0:
                child_fork_points[child_id] = fork_point

        # If session is loaded, interleave turns and forks
        if session_data.is_loaded and session_data.turns:
            self._add_turns_and_forks_interleaved(
                session_node,
                session_id,
                session_data.turns,
                child_ids,
                child_fork_points,
                all_sessions,
                children_map,
                current_id,
            )
        else:
            # No turns loaded - just add child sessions at the end
            for child_id in child_ids:
                self._add_session_subtree(
                    session_node,
                    child_id,
                    all_sessions,
                    children_map,
                    current_id
                )

    def _add_turns_and_forks_interleaved(
        self,
        session_node,
        session_id: str,
        turns: list[TurnData],
        child_ids: list[str],
        child_fork_points: dict[str, int],
        all_sessions: dict[str, SessionData],
        children_map: dict[str | None, list[str]],
        current_id: str | None,
    ) -> None:
        """Add exchange groups and fork nodes interleaved by position.

        Forks appear after the exchange group containing their fork_point turn.
        """
        # Get exchange groups
        groups = self._state.get_turns_grouped_by_exchange(session_id)

        # Build list of (position, item_type, item_data)
        # position is the turn index AFTER which the item should appear
        items: list[tuple[int, str, any]] = []

        # Add exchange groups - position is the max turn index in the group
        for group in groups:
            max_turn_idx = max(t.idx for t in group)
            items.append((max_turn_idx, "exchange", group))

        # Add forks - position is fork_point (fork appears after turn at fork_point)
        for child_id in child_ids:
            fork_point = child_fork_points.get(child_id, -1)
            if fork_point >= 0:
                items.append((fork_point, "fork", child_id))
            else:
                # No fork_point - add at end
                max_turn = max(t.idx for t in turns) if turns else -1
                items.append((max_turn + 1, "fork", child_id))

        # Sort by position, with forks appearing after exchange groups at same position
        # (fork_point N means fork was created AFTER turn N, so it comes after that exchange)
        items.sort(key=lambda x: (x[0], 0 if x[1] == "exchange" else 1))

        # Add items in order
        for _, item_type, item_data in items:
            if item_type == "exchange":
                group = item_data
                if len(group) == 1:
                    self._add_single_turn_node(session_node, session_id, group[0])
                else:
                    self._add_exchange_group_node(session_node, session_id, group)
            else:  # fork
                child_id = item_data
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
        """Add turn nodes to a session node, grouping by exchange_id.

        Turns with the same exchange_id are grouped under a collapsible
        "exchange group" node showing total tokens. Single-turn groups
        are rendered as leaf nodes directly.
        """
        session_data = self._state.get_session(session_id)
        if not session_data or not session_data.turns:
            return

        # Get turns grouped by exchange_id
        groups = self._state.get_turns_grouped_by_exchange(session_id)

        for group in groups:
            if len(group) == 1:
                # Single turn - add as leaf node
                self._add_single_turn_node(session_node, session_id, group[0])
            else:
                # Multi-turn exchange - add as collapsible group
                self._add_exchange_group_node(session_node, session_id, group)

    def _add_single_turn_node(
        self,
        parent_node,
        session_id: str,
        turn: TurnData
    ) -> None:
        """Add a single turn node to a parent session node.

        Turns are leaf nodes - each turn has exactly one content_block.
        """
        mode = self._state.get_context_mode(session_id, turn.idx)
        label = self._make_turn_label(turn.role, turn.content, mode, turn.content_block, turn.viewed, turn.tokens)
        turn_node = parent_node.add(
            label,
            data={"type": "turn", "session_id": session_id, "turn_idx": turn.idx},
            allow_expand=False,  # Turns are leaf nodes
        )
        self._turn_nodes[(session_id, turn.idx)] = turn_node

    def _add_exchange_group_node(
        self,
        parent_node,
        session_id: str,
        turns: list[TurnData]
    ) -> None:
        """Add a collapsible exchange group node containing multiple turns.

        Exchange groups show total token count and can be archived as a unit.
        The first turn is typically a user message, followed by assistant
        responses with tool use/results.
        """
        if not turns:
            return

        # Calculate total tokens for the group
        total_tokens = sum(t.tokens for t in turns)
        turn_indices = [t.idx for t in turns]
        exchange_id = turns[0].exchange_id

        # Determine group mode (any non-DROP = included)
        modes = [self._state.get_context_mode(session_id, t.idx) for t in turns]
        if all(m == ContextMode.DROP for m in modes):
            group_mode = ContextMode.DROP
        elif all(m == ContextMode.COPY for m in modes):
            group_mode = ContextMode.COPY
        else:
            group_mode = ContextMode.COMPRESS  # Mixed modes

        # Create group label with tokens first (green)
        label = self._make_exchange_group_label(turns, total_tokens, group_mode)

        # Add the group node
        group_node = parent_node.add(
            label,
            data={
                "type": "exchange_group",
                "session_id": session_id,
                "exchange_id": exchange_id,
                "turn_indices": turn_indices,
            },
            allow_expand=True,
        )

        # Add child turn nodes
        for turn in turns:
            mode = self._state.get_context_mode(session_id, turn.idx)
            child_label = self._make_turn_label(turn.role, turn.content, mode, turn.content_block, turn.viewed, turn.tokens)
            turn_node = group_node.add(
                child_label,
                data={"type": "turn", "session_id": session_id, "turn_idx": turn.idx},
                allow_expand=False,
            )
            self._turn_nodes[(session_id, turn.idx)] = turn_node

        # Collapse by default (user can expand to see individual turns)
        group_node.collapse()

        # Store group node reference for updates
        if not hasattr(self, '_exchange_group_nodes'):
            self._exchange_group_nodes = {}
        self._exchange_group_nodes[(session_id, exchange_id)] = group_node

    def _make_exchange_group_label(
        self,
        turns: list[TurnData],
        total_tokens: int,
        group_mode: ContextMode,
    ) -> str:
        """Create a label for an exchange group node.

        Format: [green]1.2kt[/] 🤖 Agent exchange (5 turns)
        """
        from widgets.session_rendering import format_kt

        # Token count in green (like tool turns)
        kt_str = format_kt(total_tokens)
        token_part = f"[green]{kt_str}[/] " if kt_str else ""

        # Mode indicator
        if group_mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif group_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            indicator = "[yellow]Σ[/]"
        else:  # DROP
            indicator = "☐"

        # Count turn types
        turn_count = len(turns)

        # Get first user message preview if available
        first_turn = turns[0]
        if first_turn.role == "user" and first_turn.content:
            preview = first_turn.content[:25] + "..." if len(first_turn.content) > 25 else first_turn.content
            preview = preview.replace("\n", " ")
            return f"{token_part}{indicator} 🤖 {escape_markup(preview)} [dim]({turn_count} turns)[/]"

        return f"{token_part}{indicator} 🤖 Agent exchange [dim]({turn_count} turns)[/]"

    def _populate_session_turns(self, session_id: str) -> None:
        """Populate a session's turns after it's loaded.

        Rebuilds all children (turns and forks) interleaved by fork_point position.
        """
        session_node = self._session_nodes.get(session_id)
        if not session_node:
            return

        session_data = self._state.get_session(session_id)
        if not session_data or not session_data.turns:
            return

        # Clear turn nodes for this session
        keys_to_remove = [k for k in self._turn_nodes if k[0] == session_id]
        for key in keys_to_remove:
            del self._turn_nodes[key]

        # Clear exchange group nodes for this session
        if hasattr(self, '_exchange_group_nodes'):
            group_keys_to_remove = [k for k in self._exchange_group_nodes if k[0] == session_id]
            for key in group_keys_to_remove:
                del self._exchange_group_nodes[key]

        # Collect existing child session IDs (we need to rebuild them after clearing)
        existing_child_ids: list[str] = []
        for child in session_node.children:
            if child.data and child.data.get("type") == "session":
                child_session_id = child.data.get("session_id")
                if child_session_id:
                    existing_child_ids.append(child_session_id)
                    # Clear cached nodes for this fork subtree
                    self._clear_session_subtree_caches(child_session_id)

        # Remove ALL children
        for child in list(session_node.children):
            child.remove()

        # Build child_fork_points and child_ids from session metadata
        child_fork_points: dict[str, int] = {}
        child_ids: list[str] = []
        for child_info in session_data.children:
            child_id = child_info.get("session_id")
            fork_point = child_info.get("fork_point", -1)
            if child_id and child_id in existing_child_ids:
                child_ids.append(child_id)
                if fork_point >= 0:
                    child_fork_points[child_id] = fork_point

        # Build children_map for recursive _add_session_subtree calls
        all_sessions = self._state.get_all_sessions()
        children_map: dict[str | None, list[str]] = {}
        for sid, sdata in all_sessions.items():
            parent_id = sdata.parent_id
            children_map.setdefault(parent_id, []).append(sid)

        current_id = self._state.get_current_session_id()

        # Re-add turns and forks interleaved
        self._add_turns_and_forks_interleaved(
            session_node,
            session_id,
            session_data.turns,
            child_ids,
            child_fork_points,
            all_sessions,
            children_map,
            current_id,
        )

        # Update session label (may have new message count)
        self._update_session_label(session_id)

    def _clear_session_subtree_caches(self, session_id: str) -> None:
        """Clear all cached nodes for a session and its descendants."""
        # Clear session node cache
        if session_id in self._session_nodes:
            del self._session_nodes[session_id]

        # Clear turn nodes for this session
        keys_to_remove = [k for k in self._turn_nodes if k[0] == session_id]
        for key in keys_to_remove:
            del self._turn_nodes[key]

        # Clear exchange group nodes
        if hasattr(self, '_exchange_group_nodes'):
            group_keys_to_remove = [k for k in self._exchange_group_nodes if k[0] == session_id]
            for key in group_keys_to_remove:
                del self._exchange_group_nodes[key]

        # Recurse to child sessions
        session_data = self._state.get_session(session_id)
        if session_data:
            for child_info in session_data.children:
                child_id = child_info.get("session_id")
                if child_id:
                    self._clear_session_subtree_caches(child_id)

    def _add_turn_node(
        self,
        session_id: str,
        turn_idx: int,
        role: str,
        streaming: bool = False
    ) -> None:
        """Add a turn node (called during streaming), respecting exchange grouping.

        If the turn has an exchange_id:
        - If an exchange group for that ID already exists, add to it
        - Otherwise, create a new exchange group node

        If no exchange_id, add as a flat turn node.
        """
        session_node = self._session_nodes.get(session_id)
        if not session_node:
            return

        turn_data = self._state.get_turn(session_id, turn_idx)
        if not turn_data:
            return

        # Initialize exchange group tracking if needed
        if not hasattr(self, '_exchange_group_nodes'):
            self._exchange_group_nodes = {}

        exchange_id = turn_data.exchange_id

        if exchange_id:
            # Check if we already have a group for this exchange
            group_key = (session_id, exchange_id)
            group_node = self._exchange_group_nodes.get(group_key)

            if group_node:
                # Add turn to existing group
                self._add_turn_to_exchange_group(group_node, session_id, turn_data, streaming)
            else:
                # Create new exchange group with this turn
                self._create_streaming_exchange_group(session_node, session_id, turn_data, streaming)
        else:
            # No exchange_id - add as flat turn node
            if streaming:
                content = "[dim]streaming...[/]"
                viewed = True
            else:
                content = turn_data.content
                viewed = turn_data.viewed

            mode = self._state.get_context_mode(session_id, turn_idx)
            tokens = turn_data.tokens
            label = self._make_turn_label(role, content, mode, viewed=viewed, tokens=tokens)

            turn_node = session_node.add(
                label,
                data={"type": "turn", "session_id": session_id, "turn_idx": turn_idx}
            )
            turn_node.expand()
            self._turn_nodes[(session_id, turn_idx)] = turn_node

        # Update session label (message count)
        self._update_session_label(session_id)
        self._update_root_label()

    def _create_streaming_exchange_group(
        self,
        session_node,
        session_id: str,
        turn,
        streaming: bool = False,
    ) -> None:
        """Create a new exchange group node for a streaming turn."""
        exchange_id = turn.exchange_id
        if not exchange_id:
            return

        # Create group label with initial turn
        total_tokens = turn.tokens
        mode = self._state.get_context_mode(session_id, turn.idx)
        label = self._make_exchange_group_label([turn], total_tokens, mode)

        # Add the group node
        group_node = session_node.add(
            label,
            data={
                "type": "exchange_group",
                "session_id": session_id,
                "exchange_id": exchange_id,
                "turn_indices": [turn.idx],
            },
            allow_expand=True,
        )

        # Store group node reference
        self._exchange_group_nodes[(session_id, exchange_id)] = group_node

        # Add the turn as a child of the group
        if streaming:
            content = "[dim]streaming...[/]"
            viewed = True
        else:
            content = turn.content
            viewed = turn.viewed

        turn_mode = self._state.get_context_mode(session_id, turn.idx)
        child_label = self._make_turn_label(
            turn.role, content, turn_mode, turn.content_block, viewed, turn.tokens
        )
        turn_node = group_node.add(
            child_label,
            data={"type": "turn", "session_id": session_id, "turn_idx": turn.idx, "exchange_id": exchange_id},
            allow_expand=False,
        )
        self._turn_nodes[(session_id, turn.idx)] = turn_node

        # Expand for streaming visibility
        if streaming:
            group_node.expand()

    def _add_turn_to_exchange_group(
        self,
        group_node,
        session_id: str,
        turn,
        streaming: bool = False,
    ) -> None:
        """Add a turn to an existing exchange group node."""
        exchange_id = turn.exchange_id

        # Add turn index to the group's tracking list
        turn_indices = group_node.data.get("turn_indices", [])
        if turn.idx not in turn_indices:
            turn_indices.append(turn.idx)
            group_node.data["turn_indices"] = turn_indices

        # Add the turn as a child of the group
        if streaming:
            content = "[dim]streaming...[/]"
            viewed = True
        else:
            content = turn.content
            viewed = turn.viewed

        turn_mode = self._state.get_context_mode(session_id, turn.idx)
        child_label = self._make_turn_label(
            turn.role, content, turn_mode, turn.content_block, viewed, turn.tokens
        )
        turn_node = group_node.add(
            child_label,
            data={"type": "turn", "session_id": session_id, "turn_idx": turn.idx, "exchange_id": exchange_id},
            allow_expand=False,
        )
        self._turn_nodes[(session_id, turn.idx)] = turn_node

        # Update the group label with new totals
        self._update_exchange_group_label(session_id, exchange_id)

    def _finalize_turn_node(
        self,
        session_id: str,
        turn_idx: int,
        content: str,
        content_block
    ) -> None:
        """Finalize a streaming turn."""
        turn_node = self._turn_nodes.get((session_id, turn_idx))
        if not turn_node:
            return

        turn_data = self._state.get_turn(session_id, turn_idx)
        if not turn_data:
            return

        mode = self._state.get_context_mode(session_id, turn_idx)
        turn_node.label = self._make_turn_label(turn_data.role, content, mode, content_block, turn_data.viewed, turn_data.tokens)

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
            turn_data.role, turn_data.content, mode, turn_data.content_block, turn_data.viewed, turn_data.tokens
        )

    def _update_exchange_group_label(self, session_id: str, exchange_id: str) -> None:
        """Update an exchange group node's label after mode changes."""
        if not hasattr(self, '_exchange_group_nodes'):
            return

        group_node = self._exchange_group_nodes.get((session_id, exchange_id))
        if not group_node:
            return

        # Gather the turns in this group
        turn_indices = group_node.data.get("turn_indices", [])
        turns = []
        for turn_idx in turn_indices:
            turn_data = self._state.get_turn(session_id, turn_idx)
            if turn_data:
                turns.append(turn_data)

        if not turns:
            return

        # Calculate totals
        total_tokens = sum(t.tokens for t in turns)

        # Determine group mode
        modes = [self._state.get_context_mode(session_id, t.idx) for t in turns]
        if all(m == ContextMode.DROP for m in modes):
            group_mode = ContextMode.DROP
        elif all(m == ContextMode.COPY for m in modes):
            group_mode = ContextMode.COPY
        else:
            group_mode = ContextMode.COMPRESS

        # Update label
        group_node.label = self._make_exchange_group_label(turns, total_tokens, group_mode)

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

        # Unviewed turns indicator (hidden for now, tracking logic preserved)
        unviewed = ""

        # Name
        if session_data.fork_name:
            name = escape_markup(session_data.fork_name)
        elif session_data.title:
            title = session_data.title[:25] + "..." if len(session_data.title) > 25 else session_data.title
            name = escape_markup(title)
        else:
            name = None

        id_prefix = f"[dim]{session_data.id[:8]}[/] "

        if name:
            label = f"{id_prefix}{name} [dim]({msg_count}msg)[/]{unviewed}"
        else:
            label = f"{id_prefix}{date_str} [dim]({msg_count}msg)[/]{unviewed}"

        if is_active:
            return f"{prefix}{streaming}[bold cyan]{label}[/]"
        else:
            return f"{prefix}{streaming}{label}"

    def _make_turn_label(
        self,
        role: str,
        content: str,
        mode: ContextMode,
        content_block=None,
        viewed: bool = True,
        tokens: int = 0,
    ) -> str:
        """Create a label for a turn node.

        Each turn has exactly one content_block that determines its type and rendering.
        """
        from widgets.session_rendering import format_kt

        # Unviewed indicator (hidden for now, tracking logic preserved)
        unviewed_indicator = ""

        # Mode indicator: copy=green check, compress=yellow Σ, drop=empty box
        if mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            indicator = "[yellow]Σ[/]"
        else:  # DROP
            indicator = "☐"

        # Token count string (green, like other nodes)
        kt_str = format_kt(tokens) if tokens > 0 else ""
        token_part = f"[green]{kt_str}[/] " if kt_str else ""

        # Determine turn type and icon based on content_block
        if isinstance(content_block, ArchiveBlock):
            summary = content_block.structured_summary.work_done if content_block.structured_summary else content_block.summary
            preview = summary[:40] + "..." if len(summary) > 40 else summary
            preview = preview.replace("\n", " ")
            return f"{token_part}{unviewed_indicator}{indicator} 📦 {escape_markup(preview)}"

        if isinstance(content_block, ForkBlock):
            preview = f"{content_block.fork_name}"
            if content_block.status == "merged":
                return f"{token_part}{unviewed_indicator}{indicator} [green]🔀 Fork: {escape_markup(preview)} [dim]merged[/dim][/green]"
            return f"{token_part}{unviewed_indicator}{indicator} [bold]🔀 Fork: {escape_markup(preview)}[/]"

        if isinstance(content_block, MergeBlock):
            msg_preview = content_block.message[:40] + "..." if len(content_block.message) > 40 else content_block.message
            msg_preview = msg_preview.replace("\n", " ")
            return f"{token_part}{unviewed_indicator}{indicator} [green]⬅️ Merged: {escape_markup(content_block.fork_name)}[/] {escape_markup(msg_preview)}"

        if isinstance(content_block, MergedToBlock):
            msg_preview = content_block.message[:40] + "..." if len(content_block.message) > 40 else content_block.message
            msg_preview = msg_preview.replace("\n", " ")
            return f"{token_part}{unviewed_indicator}{indicator} [green]➡️ Merged to parent[/] {escape_markup(msg_preview)}"

        if isinstance(content_block, LinkBlock):
            preview = content_block.summary[:40] + "..." if len(content_block.summary) > 40 else content_block.summary
            preview = preview.replace("\n", " ")
            return f"{token_part}{unviewed_indicator}{indicator} [magenta]🔗 Link:[/] {escape_markup(preview)}"

        if isinstance(content_block, ToolUseBlock):
            return f"{token_part}{unviewed_indicator}{indicator} 🤖 [cyan]🔧 {escape_markup(content_block.name)}[/]"

        if isinstance(content_block, ToolResultBlock):
            result_preview = content[:30] + "..." if len(content) > 30 else content
            result_preview = result_preview.replace("\n", " ")
            error_indicator = "[red]❌[/] " if content_block.is_error else ""
            return f"{token_part}{unviewed_indicator}{indicator} {error_indicator}📋 {escape_markup(result_preview)}"

        if isinstance(content_block, ErrorBlock):
            return f"{token_part}{unviewed_indicator}{indicator} [yellow]⚠ Error:[/] {escape_markup(content_block.reason)}"

        if isinstance(content_block, InterruptionBlock):
            return f"{token_part}{unviewed_indicator}{indicator} [red]⚠ Interrupted:[/] {escape_markup(content_block.reason)}"

        # Default: text turn (user or assistant message)
        icon = "👤" if role == "user" else "🤖"

        preview = content[:30] + "..." if len(content) > 30 else content
        preview = preview.replace("\n", " ")

        return f"{token_part}{unviewed_indicator}{indicator} {icon} {escape_markup(preview)}"

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

        elif node_type == "exchange_group":
            # Toggle all turns in the exchange group together
            session_id = event.node_data.get("session_id")
            turn_indices = event.node_data.get("turn_indices", [])
            if not turn_indices:
                return

            # Get current mode of first turn to determine next mode
            first_mode = self._state.get_context_mode(session_id, turn_indices[0])
            if first_mode == ContextMode.COPY:
                new_mode = ContextMode.COMPRESS
            elif first_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
                new_mode = ContextMode.DROP
            else:  # DROP
                new_mode = ContextMode.COPY

            # Set all turns in the group to the new mode
            for turn_idx in turn_indices:
                self._state.set_context_mode(session_id, turn_idx, new_mode)
                self.post_message(self.ContextModeChanged(session_id, turn_idx, new_mode))

            # Update the group node label
            self._update_exchange_group_label(session_id, event.node_data.get("exchange_id"))

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
                    "content_block": turn_data.content_block,
                    "turn_idx": turn_idx,
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

    def on_nested_tree_exchange_delete_requested(self, event: NestedTreeWidget.ExchangeDeleteRequested) -> None:
        """Bubble up exchange delete request."""
        self.post_message(self.ExchangeDeleteRequested(event.session_id, event.turn_indices))

    def on_nested_tree_link_requested(self, event: NestedTreeWidget.LinkRequested) -> None:
        """Bubble up link request."""
        self.post_message(self.SessionLinkRequested(event.session_id))

    def on_nested_tree_colon_pressed(self, event: NestedTreeWidget.ColonPressed) -> None:
        """Bubble up colon pressed to jump to text entry."""
        self.post_message(self.ColonPressed())

    def on_nested_tree_jump_to_exchange_end(self, event: NestedTreeWidget.JumpToExchangeEnd) -> None:
        """Bubble up jump to exchange end request."""
        self.post_message(self.JumpToExchangeEnd(event.session_id, event.last_turn_idx))

    def on_nested_tree_archive_requested(self, event: NestedTreeWidget.ArchiveRequested) -> None:
        """Bubble up archive request."""
        self.post_message(self.ArchiveRequested(event.session_id, event.turn_indices))

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

    def on_tree_node_selected(self, event) -> None:
        """Handle node selection (click) - switch session and scroll to turn.

        When clicking on any node (turn, session), if it belongs to
        a different session than the current one, switch to that session.
        This enables cross-session navigation by clicking.
        """
        node_data = event.node.data
        if not node_data:
            return

        node_type = node_data.get("type")
        session_id = node_data.get("session_id")

        if node_type == "session":
            # Clicking a session node - load and activate it
            if session_id:
                session_data = self._state.get_session(session_id)
                if session_data:
                    # Request session load if not loaded yet
                    if not session_data.is_loaded:
                        self.post_message(self.SessionLoadRequested(session_id))
                    # Activate the session
                    if session_data.session_ref:
                        self.post_message(self.SessionActivated(session_data.session_ref))

        elif node_type == "turn":
            # Clicking a turn - inspect it (app handles session switch if needed)
            turn_idx = node_data.get("turn_idx")
            if session_id and turn_idx is not None:
                turn_data = self._state.get_turn(session_id, turn_idx)
                if turn_data:
                    self.post_message(self.TurnInspected({
                        "type": "turn",
                        "role": turn_data.role,
                        "content": turn_data.content,
                        "content_block": turn_data.content_block,
                        "turn_idx": turn_idx,
                    }, session_id))

        elif node_type in ("text", "tool_use", "tool_result"):
            # Clicking a content block - inspect the parent turn
            turn_idx = node_data.get("turn_idx")
            if session_id and turn_idx is not None:
                turn_data = self._state.get_turn(session_id, turn_idx)
                if turn_data:
                    self.post_message(self.TurnInspected({
                        "type": "turn",
                        "role": turn_data.role,
                        "content": turn_data.content,
                        "content_block": turn_data.content_block,
                        "turn_idx": turn_idx,
                    }, session_id))

        elif node_type == "exchange_group":
            # Clicking an exchange group - scroll to first turn
            turn_indices = node_data.get("turn_indices", [])
            exchange_id = node_data.get("exchange_id")
            if session_id and turn_indices:
                first_turn_idx = min(turn_indices)
                last_turn_idx = max(turn_indices)
                self.post_message(self.TurnInspected({
                    "type": "exchange_group",
                    "session_id": session_id,
                    "turn_idx": first_turn_idx,
                    "last_turn_idx": last_turn_idx,
                    "exchange_id": exchange_id,
                    "turn_count": len(turn_indices),
                }, session_id))

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
