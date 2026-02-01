from __future__ import annotations

from textual.widgets import Tree, Input, Select
from textual.containers import Vertical, Horizontal
from textual.message import Message
from textual.events import Key
from textual.binding import Binding
from datetime import datetime
from rich.text import Text
from rich.style import Style
from typing import TYPE_CHECKING

from tokenizer import count_tokens
from session import Session
from models import ContextMode, TextBlock, ToolUseBlock, ToolResultBlock
from core.tree_state import TreeState, TreeEvent

if TYPE_CHECKING:
    from typing import Any


# Sorting options for sessions
SORT_OPTIONS = [
    ("modified_desc", "Recently used"),
    ("modified_asc", "Least recently used"),
    ("date_desc", "Newest created"),
    ("date_asc", "Oldest created"),
    ("title_asc", "Title A-Z"),
    ("title_desc", "Title Z-A"),
    ("messages_desc", "Most messages"),
    ("messages_asc", "Fewest messages"),
    ("tokens_desc", "Most tokens"),
    ("cost_desc", "Highest cost"),
]

# Colors for session grouping (cycling through these for visual distinction)
SESSION_COLORS = [
    "blue",
    "magenta",
    "cyan",
    "green",
    "yellow",
    "red",
]


class SelectableTree(Tree):
    """Tree with space-bar toggle for multiselect.

    Behavior:
    - Space: toggle context mode (COPY -> COMPRESS -> DROP)
    - Enter: activate/navigate to session (doesn't toggle expand)
    - a: select all turns in current session
    - n: deselect all turns in current session
    - /: search
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._get_session_color_callback = None

    def set_color_callback(self, callback):
        """Set callback to get session color: callback(session_id) -> color_name"""
        self._get_session_color_callback = callback

    def render_label(self, node, base_style: Style, style: Style) -> Text:
        """Render label with colored expand/collapse icons based on session."""
        # TOGGLE_STYLE adds meta={"toggle": True} so clicking the icon triggers expand/collapse
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
                # Color the expand/collapse icon, include TOGGLE_STYLE for click handling
                prefix = Text(icon, style=Style(color=session_color) + TOGGLE_STYLE)
            else:
                prefix = Text(icon, style=base_style + TOGGLE_STYLE)
        else:
            prefix = Text("", style=base_style)

        text = Text.assemble(prefix, node_label)
        return text

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

    async def _on_key(self, event: Key) -> None:
        if event.key == "space":
            node = self.cursor_node
            if node and node.data:
                self.post_message(self.ToggleRequested(node.data))
                event.prevent_default()
                event.stop()
                return
        elif event.key == "enter":
            # Enter activates AND toggles expand
            node = self.cursor_node
            if node and node.data:
                self.post_message(self.ActivateRequested(node.data))
                if node._allow_expand:
                    node.toggle()
                event.prevent_default()
                event.stop()
                return
        elif event.key == "e":
            # Toggle expand/collapse
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
        elif event.key == "right":
            # Expand current node
            node = self.cursor_node
            if node and node._allow_expand and not node.is_expanded:
                node.expand()
                event.prevent_default()
                event.stop()
                return
        elif event.key == "left":
            # Collapse current node, or go to parent if already collapsed
            node = self.cursor_node
            if node:
                if node.is_expanded:
                    node.collapse()
                    event.prevent_default()
                    event.stop()
                    return
                elif node.parent and node.parent != self.root:
                    # Move to parent node
                    self.select_node(node.parent)
                    event.prevent_default()
                    event.stop()
                    return
        await super()._on_key(event)


class ContextTree(Vertical):
    """Left panel showing all sessions with selectable turns."""

    DEFAULT_CSS = """
    ContextTree {
        width: 40;
        height: 100%;
        border-right: solid $primary;
    }

    ContextTree > SelectableTree {
        height: 1fr;
        background: $background;
    }

    /* Subtle hover - slight darkening to preserve colored text visibility */
    ContextTree > SelectableTree > .tree--highlight {
        /* no text-style change - preserve original colors */
    }

    ContextTree > SelectableTree > .tree--highlight-line {
        background: #1a1a2e;
    }

    /* Override cursor (focused node) - slightly more visible dark background */
    ContextTree > SelectableTree > .tree--cursor {
        background: #252540;
        text-style: none;
    }

    ContextTree > #search-input {
        dock: top;
        display: none;
        height: auto;
        margin: 0;
        padding: 0 1;
        border: none;
        background: $surface;
    }

    ContextTree > #search-input.visible {
        display: block;
    }

    ContextTree > #sort-container {
        dock: top;
        height: auto;
        padding: 0 1;
        background: $surface;
    }

    ContextTree > #sort-container > #sort-select {
        width: 100%;
        min-width: 20;
    }
    """

    class SelectionChanged(Message):
        """Fired when turn selection changes."""
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
            # Turn IDs for current session (1-indexed to match chat_log)
            self.selected_turn_ids = current_session_turn_ids
            self.show_all = False  # Could be computed if all current session turns selected
            # Full mapping of turn_id -> mode name for visual indication
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
            self.session_id = session_id  # Session this turn belongs to
            super().__init__()

    class ContextModeChanged(Message):
        """Fired when a turn's context mode is toggled, so app can persist it."""
        def __init__(self, session_id: str, turn_idx: int, new_mode: ContextMode) -> None:
            self.session_id = session_id
            self.turn_idx = turn_idx
            self.new_mode = new_mode
            super().__init__()

    class SortOrderChanged(Message):
        """Fired when user changes sort order, so app can persist it."""
        def __init__(self, sort_order: str) -> None:
            self.sort_order = sort_order
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

    def __init__(
        self,
        initial_sort_order: str = "modified_desc",
        tree_state: TreeState | None = None,
        **kwargs
    ):
        super().__init__(**kwargs)

        # Use provided TreeState or create internal one
        self._state = tree_state if tree_state is not None else TreeState()
        self._owns_state = tree_state is None  # Track if we created it

        # Node references (Textual-specific, not in TreeState)
        # session_id -> tree node
        self._session_nodes: dict[str, Any] = {}
        # (session_id, turn_idx) -> tree node
        self._turn_nodes: dict[tuple[str, int], Any] = {}

        # Local UI state (not shared)
        self._search_query: str = ""
        self._sort_order: str = initial_sort_order

        # Legacy compatibility - these now delegate to TreeState
        # Keep as properties for gradual migration

        # Context mode per turn: (session_id, turn_idx) -> ContextMode
        # Missing entries default to DROP (not in context)
        self._context_modes: dict[tuple[str, int], ContextMode] = {}
        # Context mode per merge: ("merge", parent_session_id, fork_session_id) -> ContextMode
        # Merges default to COPY (include merge summary in context)
        self._merge_modes: dict[tuple[str, str, str], ContextMode] = {}
        # Session metadata (lightweight, always loaded)
        # session_id -> {metadata dict from Session.list_sessions(), node, is_current, loaded}
        self._sessions: dict[str, dict] = {}
        # Fully loaded sessions with turns (lazy loaded on expand/activate)
        # session_id -> {session: Session, turns: list[dict]}
        self._loaded_sessions: dict[str, dict] = {}
        self._current_session_id: str | None = None
        # Sessions currently streaming (for visual indicator)
        self._streaming_sessions: set[str] = set()
        # Session color assignments (session_id -> color name)
        self._session_colors: dict[str, str] = {}

    def compose(self):
        yield Input(placeholder="Search sessions...", id="search-input")
        with Horizontal(id="sort-container"):
            yield Select(
                [(label, key) for key, label in SORT_OPTIONS],
                value=self._sort_order,
                id="sort-select",
                allow_blank=False,
            )
        tree = SelectableTree("[dim]loading...[/]", id="turn-tree")
        tree.root.data = {"type": "root"}
        yield tree

    def on_mount(self) -> None:
        tree = self.query_one("#turn-tree", SelectableTree)
        tree.root.expand()
        tree.root.allow_expand = False
        tree.auto_expand = False  # Don't auto-expand on selection
        # Set callback for tree to get session colors for node icons
        tree.set_color_callback(self._get_session_color)

        # Register as observer of TreeState
        self._state.add_observer(self._on_tree_state_event)

    def on_unmount(self) -> None:
        """Clean up observer registration."""
        self._state.remove_observer(self._on_tree_state_event)

    def _on_tree_state_event(self, event: TreeEvent, data: dict) -> None:
        """Handle state change notifications from TreeState.

        This is the observer callback - translates state changes to UI updates.

        NOTE: Currently using dual-write pattern. The ContextTree methods
        (start_turn, finish_turn, etc.) both update TreeState AND update UI.
        So we skip TURN_STARTED/TURN_FINISHED here to avoid duplicate work.
        Once we migrate to app calling TreeState directly, these handlers
        will be enabled.
        """
        if event == TreeEvent.STREAMING_STARTED:
            session_id = data.get("session_id")
            if session_id:
                self._streaming_sessions.add(session_id)
                self._update_session_label(session_id)

        elif event == TreeEvent.STREAMING_STOPPED:
            session_id = data.get("session_id")
            if session_id:
                self._streaming_sessions.discard(session_id)
                self._update_session_label(session_id)

        # NOTE: TURN_STARTED and TURN_FINISHED are handled directly by
        # start_turn() and finish_turn() methods for now. When we migrate
        # to having the app call TreeState directly, uncomment these:
        #
        # elif event == TreeEvent.TURN_STARTED:
        #     session_id = data.get("session_id")
        #     turn_idx = data.get("turn_idx")
        #     role = data.get("role")
        #     if session_id and turn_idx is not None and role:
        #         self._add_streaming_turn_node(session_id, turn_idx, role)
        #
        # elif event == TreeEvent.TURN_FINISHED:
        #     session_id = data.get("session_id")
        #     turn_idx = data.get("turn_idx")
        #     content = data.get("content", "")
        #     content_blocks = data.get("content_blocks", [])
        #     if session_id and turn_idx is not None:
        #         self._finalize_turn_node(session_id, turn_idx, content, content_blocks)

        # NOTE: CONTEXT_MODE_CHANGED is handled directly by toggle methods
        # which call _update_turn_label after TreeState update. Skip here
        # to avoid duplicate label updates.
        #
        # elif event == TreeEvent.CONTEXT_MODE_CHANGED:
        #     session_id = data.get("session_id")
        #     turn_idx = data.get("turn_idx")
        #     if session_id and turn_idx is not None:
        #         self._update_turn_label(session_id, turn_idx)
        #         self._update_root_label()

        elif event == TreeEvent.SESSION_SELECTED:
            # Current session changed - update labels
            session_id = data.get("session_id")
            prev_session_id = data.get("prev_session_id")
            if prev_session_id:
                self._update_session_label(prev_session_id)
            if session_id:
                self._update_session_label(session_id)
            self._update_root_label()

    def _update_session_label(self, session_id: str) -> None:
        """Update a session node's label (for streaming indicator, etc.)."""
        metadata = self._sessions.get(session_id)
        if not metadata or not metadata.get("node"):
            return
        is_active = session_id == self._current_session_id
        metadata["node"].label = self._make_session_label_from_metadata(metadata, is_active)

    def _add_streaming_turn_node(self, session_id: str, turn_idx: int, role: str) -> None:
        """Add a placeholder turn node when streaming starts.

        Called via observer when TreeState.start_turn() is called.
        """
        metadata = self._sessions.get(session_id)
        loaded_data = self._loaded_sessions.get(session_id)
        if not metadata or not loaded_data:
            return

        # Create placeholder label
        label = self._make_turn_label(role, "[dim]streaming...[/]", ContextMode.COMPRESS, session_id=session_id)
        session_node = metadata.get("node")
        if session_node:
            turn_node = session_node.add(
                label,
                data={"type": "turn", "session_id": session_id, "turn_idx": turn_idx}
            )
            turn_node.expand()
            self._turn_nodes[(session_id, turn_idx)] = turn_node
        else:
            turn_node = None

        # Update local tracking (will be migrated to use TreeState fully later)
        loaded_data["turns"].append({
            "idx": turn_idx,
            "role": role,
            "content": "",
            "content_blocks": [],
            "node": turn_node,
            "events": [],
            "_streaming": True,
            "_tool_use_nodes": {},
        })

        # Update metadata message count
        metadata["message_count"] = metadata.get("message_count", 0) + 1

        if session_node:
            is_active = session_id == self._current_session_id
            session_node.label = self._make_session_label_from_metadata(metadata, is_active)

        self._update_root_label()

    def _finalize_turn_node(self, session_id: str, turn_idx: int, content: str, content_blocks: list) -> None:
        """Finalize a streaming turn node with final content.

        Called via observer when TreeState.finish_turn() is called.
        """
        loaded_data = self._loaded_sessions.get(session_id)
        if not loaded_data:
            return

        # Find the turn
        turn = None
        for t in loaded_data["turns"]:
            if t["idx"] == turn_idx:
                turn = t
                break
        if not turn:
            return

        # Update turn data
        turn["content"] = content
        turn["content_blocks"] = content_blocks
        turn["_streaming"] = False

        # Clear existing children and rebuild
        if turn.get("node"):
            turn["node"].remove_children()
            self._add_content_block_nodes(turn["node"], session_id, turn_idx, content_blocks)

            # Update label with final content
            mode = self._context_modes.get((session_id, turn_idx), ContextMode.DROP)
            turn["node"].label = self._make_turn_label(
                turn["role"], content, mode, content_blocks, session_id=session_id
            )

        self._update_root_label()

    @property
    def state(self) -> TreeState:
        """Access the underlying TreeState."""
        return self._state

    def _get_session_color(self, session_id: str) -> str:
        """Get the color assigned to a session, assigning one if needed."""
        if session_id not in self._session_colors:
            # Assign next color in cycle based on number of sessions
            color_index = len(self._session_colors) % len(SESSION_COLORS)
            self._session_colors[session_id] = SESSION_COLORS[color_index]
        return self._session_colors[session_id]

    def load_all_sessions(self, current_session: Session) -> None:
        """Load all sessions into the tree.

        Uses lazy loading: only metadata is loaded initially.
        Full session data (turns) is loaded when a session is expanded or activated.
        The current session is always fully loaded.
        """
        self._current_session_id = current_session.id

        # Get all session metadata (lightweight - no message content)
        all_session_metadata = Session.list_sessions()

        tree = self.query_one("#turn-tree", SelectableTree)
        tree.root.remove_children()
        self._sessions.clear()
        self._loaded_sessions.clear()
        self._context_modes.clear()
        self._merge_modes.clear()
        self._session_colors.clear()
        self._color_index = 0
        self._session_nodes.clear()
        self._turn_nodes.clear()

        # Also clear TreeState
        self._state.clear()

        # Build metadata index
        session_ids_in_list = {s["id"] for s in all_session_metadata}

        # If current session is new (not in list), add its metadata
        if current_session.id not in session_ids_in_list:
            self._sessions[current_session.id] = {
                "id": current_session.id,
                "created": current_session.created,
                "last_modified": current_session.last_modified,
                "model": current_session.model,
                "title": current_session.title,
                "message_count": len(current_session.messages),
                "total_input_tokens": current_session.total_input_tokens,
                "total_output_tokens": current_session.total_output_tokens,
                "total_cost": current_session.total_cost,
                "parent_id": current_session.parent_id,
                "children": current_session.children,
                "fork_name": current_session.fork_name,
                "fork_status": current_session.fork_status,
                "node": None,
                "is_current": True,
            }
            # Add to TreeState
            self._state.add_session(current_session, is_current=True)

        # Store all session metadata
        for metadata in all_session_metadata:
            is_current = metadata["id"] == current_session.id
            if is_current:
                # Use in-memory current session data (may be more recent than disk)
                self._sessions[metadata["id"]] = {
                    **metadata,
                    "last_modified": current_session.last_modified,
                    "node": None,
                    "is_current": True,
                }
                # Add to TreeState
                self._state.add_session(current_session, is_current=True)
            else:
                self._sessions[metadata["id"]] = {
                    **metadata,
                    "node": None,
                    "is_current": False,
                }
                # Add to TreeState (from metadata for lazy loading)
                self._state.add_session_from_metadata(metadata, is_current=False)

        # Fully load the current session (always needed for chat)
        self._load_full_session(current_session.id, current_session)

        # Build tree with current sort order
        self._rebuild_tree_with_sort()

    def _make_session_label_from_metadata(self, metadata: dict, is_active: bool) -> str:
        """Create a label for a session node from metadata dict."""
        try:
            dt = datetime.fromisoformat(metadata["created"])
            date_str = dt.strftime("%b %d %H:%M")
        except:
            date_str = metadata["created"][:16]

        msg_count = metadata.get("message_count", 0)
        session_id = metadata["id"]

        # Calculate token count - use stored total if available, else calculate from loaded data
        if session_id in self._loaded_sessions:
            session_tokens = self._calculate_session_tokens(session_id)
        else:
            # Use stored token count from metadata
            session_tokens = metadata.get("total_input_tokens", 0) + metadata.get("total_output_tokens", 0)

        # Show fork status indicator
        is_fork = metadata.get("parent_id") is not None
        fork_status = metadata.get("fork_status", "active")
        if is_fork:
            if fork_status == "merged":
                prefix = "[green]✓[/] "
                status = "[dim][merged][/]"
            else:
                prefix = "[magenta]↳[/] "
                status = ""
        else:
            prefix = ""
            status = ""

        # Show streaming indicator
        is_streaming = session_id in self._streaming_sessions
        if is_streaming:
            streaming_indicator = "[yellow]⟳[/] "
        else:
            streaming_indicator = ""

        # Build label: fork name or title (if present), session ID prefix, msg count, tokens, datetime
        fork_name = metadata.get("fork_name", "")
        title = metadata.get("title", "")
        if fork_name:
            name_part = fork_name
        elif title:
            name_part = title[:25] + "..." if len(title) > 25 else title
        else:
            name_part = None

        # Always show session ID prefix for identification
        id_prefix = f"[dim]{session_id[:8]}[/] "

        # Format token count
        token_str = f"{session_tokens:,}tok" if session_tokens > 0 else ""

        if name_part:
            label = f"{id_prefix}{name_part} [dim]({msg_count}msg {token_str})[/] {status}"
        else:
            label = f"{id_prefix}{date_str} [dim]({msg_count}msg {token_str})[/] {status}"

        # Highlight active session
        if is_active:
            return f"{prefix}{streaming_indicator}[bold cyan]{label}[/]"
        else:
            return f"{prefix}{streaming_indicator}{label}"

    def _make_session_label(self, session: Session, is_active: bool) -> str:
        """Create a label for a session node from a Session object."""
        # Convert Session to metadata dict format and use shared logic
        metadata = {
            "id": session.id,
            "created": session.created,
            "message_count": len(session.messages),
            "total_input_tokens": session.total_input_tokens,
            "total_output_tokens": session.total_output_tokens,
            "parent_id": session.parent_id,
            "fork_status": session.fork_status,
            "fork_name": session.fork_name,
            "title": session.title,
        }
        return self._make_session_label_from_metadata(metadata, is_active)

    def _calculate_session_tokens(self, session_id: str) -> int:
        """Calculate total tokens for a specific session."""
        loaded_data = self._loaded_sessions.get(session_id)
        if not loaded_data:
            return 0

        total = 0
        for turn in loaded_data["turns"]:
            content = f"{'User' if turn['role'] == 'user' else 'Assistant'}: {turn['content']}"
            total += count_tokens(content)
        return total

    def _load_full_session(self, session_id: str, session: Session = None) -> bool:
        """Fully load a session's messages and turns.

        Args:
            session_id: The session to load
            session: Optional pre-loaded Session object (avoids re-loading from disk)

        Returns True if loaded successfully, False if session not found.
        """
        if session_id in self._loaded_sessions:
            return True  # Already loaded

        if session is None:
            session = Session.load(session_id)
            if not session:
                return False

        is_current = session_id == self._current_session_id

        turns = []
        for idx, msg in enumerate(session.messages):
            turn_key = (session.id, idx)
            # Use persisted context_mode from message
            if hasattr(msg, 'context_mode'):
                self._context_modes[turn_key] = msg.context_mode
            elif is_current:
                # Default: current session turns are COMPRESS
                self._context_modes[turn_key] = ContextMode.COMPRESS

            content_blocks = msg.content_blocks if hasattr(msg, 'content_blocks') else []

            turns.append({
                "idx": idx,
                "role": msg.role,
                "content": msg.content,
                "content_blocks": content_blocks,
                "node": None,  # Will be set when tree is built
                "events": [],  # Could load from storage if we save them
            })

        # Also load merge modes for any merged children
        for child in session.children:
            if child.get("status") == "merged":
                fork_id = child.get("session_id", "")
                merge_key = ("merge", session.id, fork_id)
                if merge_key not in self._merge_modes:
                    self._merge_modes[merge_key] = ContextMode.COPY

        self._loaded_sessions[session_id] = {
            "session": session,
            "turns": turns,
        }

        # Also load into TreeState
        self._state.load_session(session_id, session)

        return True

    def _is_session_loaded(self, session_id: str) -> bool:
        """Check if a session's full data has been loaded."""
        return session_id in self._loaded_sessions

    def _activate_session(self, session_id: str) -> None:
        """Activate a session - load it if needed and post SessionActivated."""
        # Ensure session is loaded
        if not self._is_session_loaded(session_id):
            if not self._load_full_session(session_id):
                return  # Session not found

        loaded_data = self._loaded_sessions.get(session_id)
        if loaded_data:
            self.post_message(self.SessionActivated(loaded_data["session"]))

    def _load_session_data(self, session: Session, is_current: bool) -> None:
        """Load session data into _sessions dict without adding to tree.

        DEPRECATED: Use _load_full_session instead for lazy loading.
        This method is kept for backwards compatibility.
        """
        # Store metadata
        self._sessions[session.id] = {
            "id": session.id,
            "created": session.created,
            "last_modified": session.last_modified,
            "model": session.model,
            "title": session.title,
            "message_count": len(session.messages),
            "total_input_tokens": session.total_input_tokens,
            "total_output_tokens": session.total_output_tokens,
            "total_cost": session.total_cost,
            "parent_id": session.parent_id,
            "children": session.children,
            "fork_name": session.fork_name,
            "fork_status": session.fork_status,
            "node": None,
            "is_current": is_current,
        }
        # Also fully load the session
        self._load_full_session(session.id, session)

    def _add_session_to_tree(self, tree: SelectableTree, session: Session, is_current: bool) -> None:
        """Add a session and its turns to the tree.

        Forks are shown inline at their fork point in the parent session.
        Note: This is kept for backwards compatibility but load_all_sessions
        now uses _load_session_data + _rebuild_tree_with_sort.
        """
        session_label = self._make_session_label(session, is_current)

        session_node = tree.root.add(
            session_label,
            data={"type": "session", "session_id": session.id}
        )
        if is_current:
            session_node.expand()

        # Build a map of fork_point -> fork info for inline display
        fork_points = {}  # turn_idx -> list of forks
        merge_points = {}  # turn_idx -> list of merges
        for child in session.children:
            fork_point = child.get("fork_point", -1)
            merge_point = child.get("merge_point", -1)
            if fork_point >= 0:
                fork_points.setdefault(fork_point, []).append(child)
            if merge_point >= 0 and child.get("status") == "merged":
                merge_points.setdefault(merge_point, []).append(child)

        turns = []
        for idx, msg in enumerate(session.messages):
            turn_key = (session.id, idx)
            # Use persisted context_mode from message
            if hasattr(msg, 'context_mode'):
                self._context_modes[turn_key] = msg.context_mode
            elif is_current:
                # Default: current session turns are COMPRESS
                self._context_modes[turn_key] = ContextMode.COMPRESS

            mode = self._context_modes.get(turn_key, ContextMode.DROP)
            content_blocks = msg.content_blocks if hasattr(msg, 'content_blocks') else []
            label = self._make_turn_label(msg.role, msg.content, mode, content_blocks, session_id=session.id)
            turn_node = session_node.add(
                label,
                data={"type": "turn", "session_id": session.id, "turn_idx": idx}
            )

            # Add child nodes for tool uses and results
            self._add_content_block_nodes(turn_node, session.id, idx, content_blocks)

            turns.append({
                "idx": idx,
                "role": msg.role,
                "content": msg.content,
                "content_blocks": content_blocks,
                "node": turn_node,
                "events": [],  # Could load from storage if we save them
            })

            # Add any forks that started after this turn
            for fork in fork_points.get(idx, []):
                self._add_fork_node(session_node, session.id, fork, tree)

            # Add any merges that happened after this turn
            for merge in merge_points.get(idx, []):
                self._add_merge_node(session_node, session.id, merge)

        # Add any forks at the end (fork_point == len(messages))
        for fork in fork_points.get(len(session.messages), []):
            self._add_fork_node(session_node, session.id, fork, tree)

        # Add any merges at the end (merge_point == len(messages))
        for merge in merge_points.get(len(session.messages), []):
            self._add_merge_node(session_node, session.id, merge)

        self._sessions[session.id] = {
            "id": session.id,
            "created": session.created,
            "last_modified": session.last_modified,
            "message_count": len(session.messages),
            "node": session_node,
            "is_current": is_current,
        }
        # Also populate _loaded_sessions for consistency with lazy loading
        self._loaded_sessions[session.id] = {
            "session": session,
            "turns": turns,
        }

    def _add_fork_node(self, parent_node, parent_session_id: str, fork: dict, tree: SelectableTree) -> None:
        """Add a fork link node inline in the parent session.

        This is just a reference/link to the forked session - the actual session
        content is shown in the session's own node in the main tree.
        """
        fork_id = fork.get("session_id", "")
        fork_name = fork.get("name", "") or fork_id[:8]
        status = fork.get("status", "active")

        # Status indicator
        if status == "active":
            status_text = "[yellow][active][/]"
        elif status == "merged":
            status_text = "[green][merged ✓][/]"
        else:
            status_text = f"[dim][{status}][/]"

        label = f"[bold]🔀 {fork_name}[/] {status_text}"
        parent_node.add(
            label,
            data={
                "type": "fork",
                "session_id": fork_id,
                "parent_session_id": parent_session_id,
                "fork_name": fork_name,
                "status": status,
            },
            allow_expand=False,  # No children - just a link
        )

    def _add_merge_node(self, parent_node, parent_session_id: str, merge: dict) -> None:
        """Add a merge result node inline in the parent session."""
        fork_id = merge.get("session_id", "")
        fork_name = merge.get("name", "") or fork_id[:8]

        # Load fork to get merge message
        fork_session = Session.load(fork_id)
        merge_message = fork_session.merge_message if fork_session else ""

        # Get or initialize context mode for this merge
        merge_key = ("merge", parent_session_id, fork_id)
        # Default merges to COPY (include in context)
        if merge_key not in self._merge_modes:
            self._merge_modes[merge_key] = ContextMode.COPY
        mode = self._merge_modes[merge_key]

        label = self._make_merge_label(fork_name, merge_message, mode, session_id=parent_session_id)
        parent_node.add(
            label,
            data={
                "type": "merge",
                "session_id": fork_id,
                "parent_session_id": parent_session_id,
                "fork_name": fork_name,
                "message": merge_message,
            }
        )

    def _make_merge_label(self, fork_name: str, merge_message: str, mode: ContextMode, session_id: str = None) -> str:
        """Create a label for a merge node with context mode indicator."""
        # Mode indicator (same style as turns)
        if mode == ContextMode.COPY:
            mode_indicator = "[green]●[/] "
        elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            mode_indicator = "[yellow]◐[/] "
        else:  # DROP
            mode_indicator = "[dim]○[/] "

        # Truncate message for display
        msg_preview = merge_message[:40] + "..." if len(merge_message) > 40 else merge_message
        msg_preview = msg_preview.replace("\n", " ")

        return f"{mode_indicator}[green]⬅️ Merged: {fork_name}[/] {msg_preview}"

    def _add_content_block_nodes(self, turn_node, session_id: str, turn_idx: int, content_blocks: list) -> None:
        """Add child nodes for text blocks, tool uses and results within a turn."""
        if not content_blocks:
            return

        import json
        # Track tool use nodes by their id so we can nest results under them
        tool_use_nodes: dict[str, any] = {}

        for block_idx, block in enumerate(content_blocks):
            if isinstance(block, TextBlock):
                # Only add text blocks with meaningful content
                if block.text.strip():
                    text_preview = block.text[:50].replace("\n", " ")
                    if len(block.text) > 50:
                        text_preview += "..."
                    label = f"[dim]💬[/] {text_preview}"
                    turn_node.add(
                        label,
                        data={
                            "type": "text",
                            "session_id": session_id,
                            "turn_idx": turn_idx,
                            "block_idx": block_idx,
                            "text": block.text,
                        }
                    )
            elif isinstance(block, ToolUseBlock):
                # Truncate input preview
                input_preview = json.dumps(block.input)[:50]
                if len(json.dumps(block.input)) > 50:
                    input_preview += "..."
                label = f"[cyan]🔧 {block.name}[/] {input_preview}"
                tool_node = turn_node.add(
                    label,
                    data={
                        "type": "tool_use",
                        "session_id": session_id,
                        "turn_idx": turn_idx,
                        "block_idx": block_idx,
                        "tool_name": block.name,
                        "tool_input": block.input,
                        "tool_use_id": block.id,
                    }
                )
                tool_use_nodes[block.id] = tool_node
            elif isinstance(block, ToolResultBlock):
                content_preview = str(block.content)[:50]
                if len(str(block.content)) > 50:
                    content_preview += "..."
                error_indicator = "[red]❌[/] " if block.is_error else ""
                label = f"{error_indicator}[blue]📋 Result[/] {content_preview}"
                # Find parent tool use node, or fall back to turn node
                parent_node = tool_use_nodes.get(block.tool_use_id, turn_node)
                parent_node.add(
                    label,
                    data={
                        "type": "tool_result",
                        "session_id": session_id,
                        "turn_idx": turn_idx,
                        "block_idx": block_idx,
                        "content": block.content,
                        "is_error": block.is_error,
                        "tool_use_id": block.tool_use_id,
                    }
                )

    def _make_turn_label(self, role: str, content: str, mode: ContextMode, content_blocks: list = None, session_id: str = None) -> str:
        # Mode indicator: copy=green check, compress=yellow Σ, drop=empty box
        if mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            indicator = "[yellow]Σ[/]"
        else:  # DROP
            indicator = "☐"

        icon = "👤" if role == "user" else "🤖"

        # Count tool uses if content_blocks provided
        tool_count = 0
        if content_blocks:
            tool_count = sum(1 for b in content_blocks if isinstance(b, ToolUseBlock))

        preview = content[:30] + "..." if len(content) > 30 else content
        preview = preview.replace("\n", " ")

        # Add tool indicator
        tool_indicator = f" [cyan]🔧{tool_count}[/]" if tool_count > 0 else ""
        return f"{indicator} {icon}{tool_indicator} {preview}"

    def _update_root_label(self) -> None:
        """Update root label with selected context tokens for current session."""
        tree = self.query_one("#turn-tree", SelectableTree)

        selected_tokens = 0
        current_session_tokens = 0
        current_session_turn_ids = []
        # Build turn_modes dict for current session (1-indexed turn_id -> mode name)
        turn_modes: dict[int, str] = {}

        # Only count tokens for the current session's context
        if self._current_session_id and self._is_session_loaded(self._current_session_id):
            loaded_data = self._loaded_sessions.get(self._current_session_id)
            if loaded_data:
                for turn in loaded_data["turns"]:
                    turn_key = (self._current_session_id, turn["idx"])
                    content = f"{'User' if turn['role'] == 'user' else 'Assistant'}: {turn['content']}"
                    tokens = count_tokens(content)
                    current_session_tokens += tokens
                    mode = self._context_modes.get(turn_key, ContextMode.DROP)
                    if mode != ContextMode.DROP:
                        selected_tokens += tokens
                        current_session_turn_ids.append(turn["idx"] + 1)

                    # Build turn_modes for current session
                    turn_id = turn["idx"] + 1  # 1-indexed
                    turn_modes[turn_id] = mode.name

                # Count merge summaries for current session
                session = loaded_data["session"]
                for child in session.children:
                    if child.get("status") == "merged":
                        fork_id = child.get("session_id", "")
                        merge_key = ("merge", self._current_session_id, fork_id)
                        # Load fork to get merge message
                        fork_session = Session.load(fork_id)
                        if fork_session and fork_session.merge_message:
                            merge_tokens = count_tokens(fork_session.merge_message)
                            current_session_tokens += merge_tokens
                            mode = self._merge_modes.get(merge_key, ContextMode.COPY)
                            if mode != ContextMode.DROP:
                                selected_tokens += merge_tokens

        included_count = sum(
            1 for (sid, _), m in self._context_modes.items()
            if m != ContextMode.DROP and sid == self._current_session_id
        )
        included_count += sum(
            1 for key, m in self._merge_modes.items()
            if m != ContextMode.DROP and key[1] == self._current_session_id
        )

        # Root label shows context selection for current session
        tree.root.label = f"[bold]Context:[/] {selected_tokens:,} / {current_session_tokens:,} [dim]tokens[/]"

        self.post_message(self.SelectionChanged(
            included_count, current_session_tokens, selected_tokens, current_session_turn_ids, turn_modes
        ))

    def _update_turn_label(self, session_id: str, turn_idx: int) -> None:
        """Update a turn's mode indicator label."""
        loaded_data = self._loaded_sessions.get(session_id)
        if not loaded_data:
            return

        for turn in loaded_data["turns"]:
            if turn["idx"] == turn_idx:
                turn_key = (session_id, turn_idx)
                mode = self._context_modes.get(turn_key, ContextMode.DROP)
                if turn.get("node"):
                    turn["node"].label = self._make_turn_label(
                        turn["role"], turn["content"], mode, turn.get("content_blocks"), session_id=session_id
                    )
                break

    def _update_merge_label(self, parent_session_id: str, fork_id: str, node_data: dict) -> None:
        """Update a merge node's mode indicator label."""
        # Find the merge node in the tree by walking children
        metadata = self._sessions.get(parent_session_id)
        if not metadata or not metadata.get("node"):
            return

        merge_key = ("merge", parent_session_id, fork_id)
        mode = self._merge_modes.get(merge_key, ContextMode.COPY)

        # Find the node in the session's children
        for node in metadata["node"].children:
            if node.data and node.data.get("type") == "merge" and node.data.get("session_id") == fork_id:
                fork_name = node_data.get("fork_name", fork_id[:8])
                merge_message = node_data.get("message", "")
                node.label = self._make_merge_label(fork_name, merge_message, mode, session_id=parent_session_id)
                break

    def is_selection_curated(self) -> bool:
        """Check if selection differs from 'all current session turns as COPY'.

        Returns True if:
        - Any turn from another session is included, OR
        - Any turn from current session is not COPY, OR
        - Any turn uses COMPRESS mode
        """
        if not self._current_session_id:
            return False

        loaded_data = self._loaded_sessions.get(self._current_session_id)
        if not loaded_data:
            return False

        # Check if any non-current session turns are included
        for turn_key, mode in self._context_modes.items():
            if mode != ContextMode.DROP and turn_key[0] != self._current_session_id:
                return True

        # Check if all current session turns are COPY
        for turn in loaded_data["turns"]:
            turn_key = (self._current_session_id, turn["idx"])
            mode = self._context_modes.get(turn_key, ContextMode.DROP)
            if mode != ContextMode.COPY:
                return True

        return False

    def add_turn_to_current(self, role: str, content: str, raw_events: list[dict], content_blocks: list = None) -> None:
        """Add a new turn to the current session."""
        if not self._current_session_id:
            return

        metadata = self._sessions.get(self._current_session_id)
        loaded_data = self._loaded_sessions.get(self._current_session_id)
        if not metadata or not loaded_data:
            return

        idx = len(loaded_data["turns"])
        turn_key = (self._current_session_id, idx)

        # Update both local and TreeState
        self._context_modes[turn_key] = ContextMode.COMPRESS  # Auto-include new turns as COMPRESS
        self._state.set_context_mode(self._current_session_id, idx, ContextMode.COMPRESS)

        label = self._make_turn_label(role, content, ContextMode.COMPRESS, content_blocks, session_id=self._current_session_id)
        session_node = metadata.get("node")
        if session_node:
            turn_node = session_node.add(
                label,
                data={"type": "turn", "session_id": self._current_session_id, "turn_idx": idx}
            )

            # Add child nodes for tool uses and results
            if content_blocks:
                self._add_content_block_nodes(turn_node, self._current_session_id, idx, content_blocks)
        else:
            turn_node = None

        loaded_data["turns"].append({
            "idx": idx,
            "role": role,
            "content": content,
            "content_blocks": content_blocks or [],
            "node": turn_node,
            "events": raw_events,
        })

        # Update metadata message count
        metadata["message_count"] = metadata.get("message_count", 0) + 1

        # Update session label with new count
        if session_node:
            session_node.label = self._make_session_label_from_metadata(metadata, True)

        self._update_root_label()

    def remove_turn(self, session_id: str, turn_idx: int, updated_session: Session = None) -> bool:
        """Remove a turn from the tree without reloading all sessions.

        Args:
            session_id: The session containing the turn
            turn_idx: The index of the turn to remove
            updated_session: Optional updated session object to use for label

        Returns True if the turn was removed, False if not found.
        """
        metadata = self._sessions.get(session_id)
        loaded_data = self._loaded_sessions.get(session_id)
        if not loaded_data:
            return False

        # Find and remove the turn from our data
        turn_to_remove = None
        for i, turn in enumerate(loaded_data["turns"]):
            if turn["idx"] == turn_idx:
                turn_to_remove = turn
                # Remove the tree node
                if turn.get("node"):
                    turn["node"].remove()
                # Remove from turns list
                loaded_data["turns"].pop(i)
                break

        if not turn_to_remove:
            return False

        # Update indices for turns after the removed one
        for turn in loaded_data["turns"]:
            if turn["idx"] > turn_idx:
                turn["idx"] -= 1
                # Update node data
                if turn.get("node") and turn["node"].data:
                    turn["node"].data["turn_idx"] = turn["idx"]

        # Remove context mode for deleted turn and shift others
        turn_key = (session_id, turn_idx)
        self._context_modes.pop(turn_key, None)

        # Shift context modes for turns after the removed one
        keys_to_update = [
            (sid, idx) for sid, idx in self._context_modes.keys()
            if sid == session_id and idx > turn_idx
        ]
        for old_key in keys_to_update:
            mode = self._context_modes.pop(old_key)
            new_key = (session_id, old_key[1] - 1)
            self._context_modes[new_key] = mode

        # Update cached session if provided
        if updated_session:
            loaded_data["session"] = updated_session

        # Update metadata message count
        if metadata:
            metadata["message_count"] = max(0, metadata.get("message_count", 1) - 1)

            # Update session label with new message count
            is_active = session_id == self._current_session_id
            if metadata.get("node"):
                metadata["node"].label = self._make_session_label_from_metadata(metadata, is_active)

        self._update_root_label()
        return True

    def remove_session(self, session_id: str) -> bool:
        """Remove a session from the tree.

        Args:
            session_id: The session to remove

        Returns True if the session was removed, False if not found.
        """
        session_data = self._sessions.get(session_id)
        if not session_data:
            return False

        # Remove the tree node
        if session_data["node"]:
            session_data["node"].remove()

        # Remove from sessions dict
        del self._sessions[session_id]

        # Remove context modes for this session's turns
        keys_to_remove = [
            key for key in self._context_modes.keys()
            if key[0] == session_id
        ]
        for key in keys_to_remove:
            del self._context_modes[key]

        # Remove merge modes for this session
        merge_keys_to_remove = [
            key for key in self._merge_modes.keys()
            if key[1] == session_id or key[2] == session_id
        ]
        for key in merge_keys_to_remove:
            del self._merge_modes[key]

        self._update_root_label()
        return True

    # --- Streaming-aware methods for incremental tree updates ---

    def start_turn(self, session_id: str, turn_idx: int, role: str) -> None:
        """Start a new turn node when streaming begins.

        Called when a 'turn_started' event is received from SessionRunner.
        Creates a placeholder turn node that will be populated as events arrive.

        Note: This method also notifies TreeState. In the future, the app
        should call TreeState directly, and ContextTree will react via observer.
        """
        metadata = self._sessions.get(session_id)
        loaded_data = self._loaded_sessions.get(session_id)
        if not metadata or not loaded_data:
            return

        turn_key = (session_id, turn_idx)
        self._context_modes[turn_key] = ContextMode.COMPRESS  # Auto-include as COMPRESS

        # Also notify TreeState (it will fire TURN_STARTED event)
        self._state.start_turn(session_id, turn_idx, role)

        # Create placeholder label
        label = self._make_turn_label(role, "[dim]streaming...[/]", ContextMode.COMPRESS, session_id=session_id)
        session_node = metadata.get("node")
        if session_node:
            turn_node = session_node.add(
                label,
                data={"type": "turn", "session_id": session_id, "turn_idx": turn_idx}
            )
            turn_node.expand()
        else:
            turn_node = None

        # Track the streaming turn
        loaded_data["turns"].append({
            "idx": turn_idx,
            "role": role,
            "content": "",  # Will be updated when streaming completes
            "content_blocks": [],
            "node": turn_node,
            "events": [],
            "_streaming": True,  # Mark as streaming
            "_tool_use_nodes": {},  # Track tool use nodes by id for nesting results
        })

        # Update metadata message count
        metadata["message_count"] = metadata.get("message_count", 0) + 1

        # Update session label with new count
        is_active = session_id == self._current_session_id
        if session_node:
            session_node.label = self._make_session_label_from_metadata(metadata, is_active)

        self._update_root_label()

    def add_tool_use_to_turn(
        self,
        session_id: str,
        turn_idx: int,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict,
        tool_index: int,
    ) -> None:
        """Add a tool use node during streaming.

        Called when a 'tool_use' event is received from SessionRunner.
        """
        loaded_data = self._loaded_sessions.get(session_id)
        if not loaded_data:
            return

        # Find the streaming turn
        turn = None
        for t in loaded_data["turns"]:
            if t["idx"] == turn_idx:
                turn = t
                break
        if not turn:
            return

        import json
        input_preview = json.dumps(tool_input)[:50]
        if len(json.dumps(tool_input)) > 50:
            input_preview += "..."
        label = f"[cyan]🔧 {tool_name}[/] {input_preview}"

        # Check if node already exists (from tool_use_start) - update instead of creating
        tool_use_nodes = turn.get("_tool_use_nodes", {})
        if tool_use_id in tool_use_nodes:
            # Update existing node
            existing_node = tool_use_nodes[tool_use_id]
            existing_node.label = label
            existing_node.data["tool_input"] = tool_input
            return

        tool_node = turn["node"].add(
            label,
            data={
                "type": "tool_use",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "block_idx": tool_index,  # Use tool_index as block_idx
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_use_id": tool_use_id,
            }
        )

        # Track for nesting results
        if "_tool_use_nodes" not in turn:
            turn["_tool_use_nodes"] = {}
        turn["_tool_use_nodes"][tool_use_id] = tool_node

        # Update turn label to show tool count
        tool_count = len(turn.get("_tool_use_nodes", {}))
        icon = "👤" if turn["role"] == "user" else "🤖"
        mode = self._context_modes.get((session_id, turn_idx), ContextMode.DROP)
        if mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            indicator = "[yellow]Σ[/]"
        else:
            indicator = "☐"
        if turn.get("node"):
            turn["node"].label = f"{indicator} {icon} [cyan]🔧{tool_count}[/] [dim]streaming...[/]"

    def update_tool_input_streaming(
        self,
        session_id: str,
        turn_idx: int,
        tool_use_id: str,
        tool_name: str,
        partial_json: str,
    ) -> None:
        """Update tool use node label with streaming partial JSON.

        Called when 'tool_input_delta' events arrive.
        """
        loaded_data = self._loaded_sessions.get(session_id)
        if not loaded_data:
            return

        # Find the streaming turn
        turn = None
        for t in loaded_data["turns"]:
            if t["idx"] == turn_idx:
                turn = t
                break
        if not turn:
            return

        # Find the tool node
        tool_use_nodes = turn.get("_tool_use_nodes", {})
        if tool_use_id not in tool_use_nodes:
            return

        node = tool_use_nodes[tool_use_id]

        # Accumulate partial JSON in node data
        if "_streaming_input" not in node.data:
            node.data["_streaming_input"] = ""
        node.data["_streaming_input"] += partial_json

        # Update label with preview of accumulated input
        accumulated = node.data["_streaming_input"]
        preview = accumulated[:50]
        if len(accumulated) > 50:
            preview += "..."
        node.label = f"[cyan]🔧 {tool_name}[/] [dim]{preview}[/]"

    def update_streaming_text(
        self,
        session_id: str,
        turn_idx: int,
        text_delta: str,
    ) -> None:
        """Update turn node to reflect streaming text content.

        Called when 'text_delta' events arrive.
        """
        loaded_data = self._loaded_sessions.get(session_id)
        if not loaded_data:
            return

        # Find the streaming turn
        turn = None
        for t in loaded_data["turns"]:
            if t["idx"] == turn_idx:
                turn = t
                break
        if not turn or not turn.get("node"):
            return

        # Accumulate text
        if "_streaming_text" not in turn:
            turn["_streaming_text"] = ""
        turn["_streaming_text"] += text_delta

        # Update turn label with text preview
        text = turn["_streaming_text"]
        preview = text[:30].replace("\n", " ")
        if len(text) > 30:
            preview += "..."

        icon = "👤" if turn["role"] == "user" else "🤖"
        mode = self._context_modes.get((session_id, turn_idx), ContextMode.DROP)
        if mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            indicator = "[yellow]Σ[/]"
        else:
            indicator = "☐"

        # Show tool count if any
        tool_count = len(turn.get("_tool_use_nodes", {}))
        if tool_count > 0:
            turn["node"].label = f"{indicator} {icon} [cyan]🔧{tool_count}[/] [dim]{preview}[/]"
        else:
            turn["node"].label = f"{indicator} {icon} [dim]{preview}[/]"

    def add_tool_result_to_turn(
        self,
        session_id: str,
        turn_idx: int,
        tool_use_id: str,
        result: str,
        is_error: bool = False,
        tool_index: int = None,
    ) -> None:
        """Add a tool result node during streaming.

        Called when a 'tool_result' event is received from SessionRunner.
        Results are nested under their corresponding tool use.
        """
        loaded_data = self._loaded_sessions.get(session_id)
        if not loaded_data:
            return

        # Find the streaming turn
        turn = None
        for t in loaded_data["turns"]:
            if t["idx"] == turn_idx:
                turn = t
                break
        if not turn:
            return

        content_preview = str(result)[:50]
        if len(str(result)) > 50:
            content_preview += "..."
        error_indicator = "[red]❌[/] " if is_error else ""
        label = f"{error_indicator}[blue]📋 Result[/] {content_preview}"

        # Find parent tool use node, or fall back to turn node
        tool_use_nodes = turn.get("_tool_use_nodes", {})
        parent_node = tool_use_nodes.get(tool_use_id, turn["node"])
        parent_node.add(
            label,
            data={
                "type": "tool_result",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "block_idx": tool_index,
                "content": result,
                "is_error": is_error,
                "tool_use_id": tool_use_id,
            }
        )

    def finish_turn(
        self,
        session_id: str,
        turn_idx: int,
        content: str,
        content_blocks: list,
        raw_events: list[dict],
    ) -> None:
        """Finalize a streaming turn when complete.

        Called when a 'done' event is received from SessionRunner.
        Updates the turn label with final content and rebuilds child nodes in order.

        Note: This method also notifies TreeState. In the future, the app
        should call TreeState directly, and ContextTree will react via observer.
        """
        loaded_data = self._loaded_sessions.get(session_id)
        if not loaded_data:
            return

        # Find the streaming turn
        turn = None
        for t in loaded_data["turns"]:
            if t["idx"] == turn_idx:
                turn = t
                break
        if not turn:
            return

        # Also notify TreeState (it will fire TURN_FINISHED event)
        self._state.finish_turn(session_id, turn_idx, content, content_blocks, raw_events)

        # Update turn data
        turn["content"] = content
        turn["content_blocks"] = content_blocks
        turn["events"] = raw_events
        turn["_streaming"] = False

        # Clear existing children (added during streaming) and rebuild in correct order
        if turn.get("node"):
            turn["node"].remove_children()
            self._add_content_block_nodes(turn["node"], session_id, turn_idx, content_blocks)

            # Update label with final content
            mode = self._context_modes.get((session_id, turn_idx), ContextMode.DROP)
            turn["node"].label = self._make_turn_label(
                turn["role"], content, mode, content_blocks, session_id=session_id
            )

        self._update_root_label()

    def on_tree_node_expanded(self, event) -> None:
        """Handle node expansion - lazy load session data when expanded."""
        node_data = event.node.data
        if not node_data:
            return

        node_type = node_data.get("type")
        if node_type == "session":
            session_id = node_data.get("session_id")
            if session_id and not self._is_session_loaded(session_id):
                # Lazy load the session
                if self._load_full_session(session_id):
                    # Rebuild just this session's children
                    self._populate_session_node(session_id, event.node)

    def _populate_session_node(self, session_id: str, session_node) -> None:
        """Populate a session node with its turns after lazy loading."""
        if not self._is_session_loaded(session_id):
            return

        loaded_data = self._loaded_sessions[session_id]
        tree = self.query_one("#turn-tree", SelectableTree)

        # Add turn nodes
        for turn in loaded_data["turns"]:
            idx = turn["idx"]
            mode = self._context_modes.get((session_id, idx), ContextMode.DROP)
            content_blocks = turn.get("content_blocks", [])
            label = self._make_turn_label(turn["role"], turn["content"], mode, content_blocks, session_id=session_id)
            turn_node = session_node.add(
                label,
                data={"type": "turn", "session_id": session_id, "turn_idx": idx}
            )
            turn["node"] = turn_node
            self._add_content_block_nodes(turn_node, session_id, idx, content_blocks)

        # Add fork and merge nodes
        session = loaded_data["session"]
        fork_points = {}
        merge_points = {}
        for child in session.children:
            fork_point = child.get("fork_point", -1)
            merge_point = child.get("merge_point", -1)
            if fork_point >= 0:
                fork_points.setdefault(fork_point, []).append(child)
            if merge_point >= 0 and child.get("status") == "merged":
                merge_points.setdefault(merge_point, []).append(child)

        for fork_point, forks in fork_points.items():
            for fork in forks:
                self._add_fork_node(session_node, session_id, fork, tree)

        for merge_point, merges in merge_points.items():
            for merge in merges:
                self._add_merge_node(session_node, session_id, merge)

    def on_tree_node_selected(self, event) -> None:
        """Handle node selection - show info in preview pane.

        Selection doesn't activate sessions - use Enter for that.
        This allows browsing the session list without loading heavy sessions.
        """
        from core.debug_log import debug_log
        node_data = event.node.data
        if not node_data:
            debug_log.debug("on_tree_node_selected: no node_data", category="tree")
            return

        node_type = node_data.get("type")
        debug_log.info(f"on_tree_node_selected: type={node_type}, data={node_data}", category="tree")

        if node_type == "session":
            # Just show session info in preview - don't activate
            session_id = node_data.get("session_id")
            metadata = self._sessions.get(session_id)
            if metadata:
                self.post_message(self.TurnInspected({
                    "type": "session_preview",
                    "session_id": session_id,
                    "title": metadata.get("title", ""),
                    "created": metadata.get("created", ""),
                    "message_count": metadata.get("message_count", 0),
                    "model": metadata.get("model", ""),
                }))
        elif node_type == "summary":
            # Show full summary in the inspection pane
            session_id = node_data.get("session_id")
            loaded_data = self._loaded_sessions.get(session_id)
            if loaded_data:
                session = loaded_data["session"]
                self.post_message(self.TurnInspected({
                    "type": "summary",
                    "title": session.title,
                    "summary": session.summary,
                    "session_id": session_id,
                }))
        elif node_type == "turn":
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            loaded_data = self._loaded_sessions.get(session_id)
            if loaded_data:
                for turn in loaded_data["turns"]:
                    if turn["idx"] == turn_idx:
                        # Get context mode for this turn
                        turn_key = (session_id, turn_idx)
                        mode = self._context_modes.get(turn_key, ContextMode.DROP)
                        # Send turn data for inspection (includes session_id for cross-session navigation)
                        self.post_message(self.TurnInspected({
                            "type": "turn",
                            "role": turn["role"],
                            "content": turn["content"],
                            "events": turn.get("events", []),
                            "turn_idx": turn_idx,
                            "context_mode": mode.name,
                        }, session_id=session_id))
                        break
        elif node_type == "text":
            # Send text block data for inspection and highlighting
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            turn_key = (session_id, turn_idx)
            mode = self._context_modes.get(turn_key, ContextMode.DROP)
            self.post_message(self.TurnInspected({
                "type": "text",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "block_idx": node_data.get("block_idx"),
                "text": node_data.get("text"),
                "context_mode": mode.name,
            }, session_id=session_id))
        elif node_type == "tool_use":
            # Send tool use data for inspection and highlighting
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            turn_key = (session_id, turn_idx)
            mode = self._context_modes.get(turn_key, ContextMode.DROP)
            self.post_message(self.TurnInspected({
                "type": "tool_use",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "block_idx": node_data.get("block_idx"),
                "tool_name": node_data.get("tool_name"),
                "tool_input": node_data.get("tool_input"),
                "tool_use_id": node_data.get("tool_use_id"),
                "context_mode": mode.name,
            }, session_id=session_id))
        elif node_type == "tool_result":
            # Send tool result data for inspection and highlighting
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            turn_key = (session_id, turn_idx)
            mode = self._context_modes.get(turn_key, ContextMode.DROP)
            self.post_message(self.TurnInspected({
                "type": "tool_result",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "block_idx": node_data.get("block_idx"),
                "content": node_data.get("content"),
                "is_error": node_data.get("is_error"),
                "tool_use_id": node_data.get("tool_use_id"),
                "context_mode": mode.name,
            }, session_id=session_id))
        elif node_type == "fork":
            # Show fork info in preview pane - don't activate
            session_id = node_data.get("session_id")
            metadata = self._sessions.get(session_id)
            if metadata:
                self.post_message(self.TurnInspected({
                    "type": "session_preview",
                    "session_id": session_id,
                    "title": metadata.get("title", "") or node_data.get("fork_name", ""),
                    "created": metadata.get("created", ""),
                    "message_count": metadata.get("message_count", 0),
                    "model": metadata.get("model", ""),
                    "is_fork": True,
                    "status": node_data.get("status", "active"),
                }))
        elif node_type == "merge":
            # Show merge details in inspection pane
            fork_id = node_data.get("session_id")
            parent_session_id = node_data.get("parent_session_id")
            fork_name = node_data.get("fork_name", "")
            merge_message = node_data.get("message", "")
            merge_key = ("merge", parent_session_id, fork_id)
            mode = self._merge_modes.get(merge_key, ContextMode.COPY)
            self.post_message(self.TurnInspected({
                "type": "merge",
                "session_id": fork_id,
                "parent_session_id": parent_session_id,
                "fork_name": fork_name,
                "message": merge_message,
                "context_mode": mode.name,
            }, session_id=parent_session_id))

    def on_selectable_tree_activate_requested(self, event: SelectableTree.ActivateRequested) -> None:
        """Handle Enter key - activate session (load into chat view)."""
        node_data = event.node_data
        node_type = node_data.get("type")

        if node_type == "session":
            # Activate session - load and switch to it
            session_id = node_data.get("session_id")
            self._activate_session(session_id)
        elif node_type == "fork":
            # Activate fork session
            session_id = node_data.get("session_id")
            self._activate_session(session_id)
        elif node_type == "merge":
            # Activate merged fork session
            session_id = node_data.get("session_id")
            self._activate_session(session_id)
        elif node_type == "turn":
            # Toggle context mode on Enter for turns (same as space)
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")

            # Use TreeState to toggle - it fires CONTEXT_MODE_CHANGED event
            new_mode = self._state.toggle_context_mode(session_id, turn_idx)

            # Keep local state in sync (will be removed when fully migrated)
            turn_key = (session_id, turn_idx)
            if new_mode == ContextMode.DROP:
                self._context_modes.pop(turn_key, None)
            else:
                self._context_modes[turn_key] = new_mode

            self._update_turn_label(session_id, turn_idx)
            self._update_root_label()
            # Notify app to persist the change
            self.post_message(self.ContextModeChanged(session_id, turn_idx, new_mode))

    def on_selectable_tree_toggle_requested(self, event: SelectableTree.ToggleRequested) -> None:
        """Handle space bar toggle - cycle through COPY -> COMPRESS -> DROP."""
        node_type = event.node_data.get("type")

        if node_type == "turn":
            session_id = event.node_data.get("session_id")
            turn_idx = event.node_data.get("turn_idx")

            # Use TreeState to toggle - it fires CONTEXT_MODE_CHANGED event
            new_mode = self._state.toggle_context_mode(session_id, turn_idx)

            # Keep local state in sync (will be removed when fully migrated)
            turn_key = (session_id, turn_idx)
            if new_mode == ContextMode.DROP:
                self._context_modes.pop(turn_key, None)
            else:
                self._context_modes[turn_key] = new_mode

            self._update_turn_label(session_id, turn_idx)
            self._update_root_label()
            # Notify app to persist the change
            self.post_message(self.ContextModeChanged(session_id, turn_idx, new_mode))

        elif node_type == "merge":
            fork_id = event.node_data.get("session_id")
            parent_session_id = event.node_data.get("parent_session_id")
            merge_key = ("merge", parent_session_id, fork_id)

            # Get current mode and cycle
            current_mode = self._merge_modes.get(merge_key, ContextMode.COPY)
            if current_mode == ContextMode.COPY:
                new_mode = ContextMode.COMPRESS
            elif current_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
                new_mode = ContextMode.DROP
            else:  # DROP
                new_mode = ContextMode.COPY

            # Update TreeState
            self._state.set_merge_mode(parent_session_id, fork_id, new_mode)

            # Keep local state in sync
            self._merge_modes[merge_key] = new_mode

            self._update_merge_label(parent_session_id, fork_id, event.node_data)
            self._update_root_label()

    def on_selectable_tree_select_all_requested(self, event: SelectableTree.SelectAllRequested) -> None:
        """Set all turns in CURRENT session to COPY mode."""
        if not self._current_session_id:
            return
        loaded_data = self._loaded_sessions.get(self._current_session_id)
        if not loaded_data:
            return
        for turn in loaded_data["turns"]:
            turn_key = (self._current_session_id, turn["idx"])
            # Update both local and TreeState
            self._context_modes[turn_key] = ContextMode.COPY
            self._state.set_context_mode(self._current_session_id, turn["idx"], ContextMode.COPY)
            self._update_turn_label(self._current_session_id, turn["idx"])
        self._update_root_label()

    def on_selectable_tree_select_none_requested(self, event: SelectableTree.SelectNoneRequested) -> None:
        """Set all turns in CURRENT session to DROP mode."""
        if not self._current_session_id:
            return
        loaded_data = self._loaded_sessions.get(self._current_session_id)
        if not loaded_data:
            return
        for turn in loaded_data["turns"]:
            turn_key = (self._current_session_id, turn["idx"])
            # Update both local and TreeState
            self._context_modes.pop(turn_key, None)
            self._state.set_context_mode(self._current_session_id, turn["idx"], ContextMode.DROP)
            self._update_turn_label(self._current_session_id, turn["idx"])
        self._update_root_label()

    def on_selectable_tree_search_requested(self, event: SelectableTree.SearchRequested) -> None:
        """Show the search input when / is pressed."""
        search_input = self.query_one("#search-input", Input)
        search_input.add_class("visible")
        search_input.focus()

    def on_selectable_tree_turn_delete_requested(self, event: SelectableTree.TurnDeleteRequested) -> None:
        """Handle turn delete request - bubble up to app."""
        self.post_message(self.TurnDeleteRequested(event.session_id, event.turn_index))

    def on_selectable_tree_session_delete_requested(self, event: SelectableTree.SessionDeleteRequested) -> None:
        """Handle session delete request - bubble up to app."""
        self.post_message(self.SessionDeleteRequested(event.session_id))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter tree nodes as user types."""
        if event.input.id == "search-input":
            self._search_query = event.value.lower()
            self._apply_search_filter()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Hide search and focus tree when Enter is pressed."""
        if event.input.id == "search-input":
            self._hide_search()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle sort order change."""
        if event.select.id == "sort-select":
            self._sort_order = str(event.value)
            self._rebuild_tree_with_sort()
            # Notify app to persist the sort order
            self.post_message(self.SortOrderChanged(self._sort_order))

    def _rebuild_tree_with_sort(self) -> None:
        """Rebuild the tree with sessions in the current sort order.

        Uses lazy loading: only loaded sessions show their turns.
        Unloaded sessions show as collapsed nodes.
        """
        if not self._sessions:
            return

        tree = self.query_one("#turn-tree", SelectableTree)
        tree.root.remove_children()

        # Get session data sorted according to current order
        sorted_session_ids = self._get_sorted_session_ids()

        # Determine which sessions to expand (and thus need to be loaded):
        # - Always expand current session
        # - Also expand parent session if current is a fork
        sessions_to_expand = {self._current_session_id}
        current_metadata = self._sessions.get(self._current_session_id)
        if current_metadata:
            parent_id = current_metadata.get("parent_id")
            if parent_id:
                sessions_to_expand.add(parent_id)
                # Ensure parent is loaded too
                if not self._is_session_loaded(parent_id):
                    self._load_full_session(parent_id)

        # Rebuild tree nodes for each session
        for session_id in sorted_session_ids:
            metadata = self._sessions[session_id]
            is_current = metadata.get("is_current", False)

            # Build session label from metadata
            session_label = self._make_session_label_from_metadata(metadata, is_current)
            session_node = tree.root.add(
                session_label,
                data={"type": "session", "session_id": session_id}
            )
            metadata["node"] = session_node

            # Only add turn nodes if session is loaded
            if self._is_session_loaded(session_id):
                loaded_data = self._loaded_sessions[session_id]

                # Expand loaded sessions that should be expanded
                if session_id in sessions_to_expand:
                    session_node.expand()

                # Rebuild turn nodes
                for turn in loaded_data["turns"]:
                    idx = turn["idx"]
                    mode = self._context_modes.get((session_id, idx), ContextMode.DROP)
                    content_blocks = turn.get("content_blocks", [])
                    label = self._make_turn_label(turn["role"], turn["content"], mode, content_blocks, session_id=session_id)
                    turn_node = session_node.add(
                        label,
                        data={"type": "turn", "session_id": session_id, "turn_idx": idx}
                    )
                    turn["node"] = turn_node
                    self._add_content_block_nodes(turn_node, session_id, idx, content_blocks)

                # Rebuild fork and merge nodes from loaded session
                session = loaded_data["session"]
                fork_points = {}
                merge_points = {}
                for child in session.children:
                    fork_point = child.get("fork_point", -1)
                    merge_point = child.get("merge_point", -1)
                    if fork_point >= 0:
                        fork_points.setdefault(fork_point, []).append(child)
                    if merge_point >= 0 and child.get("status") == "merged":
                        merge_points.setdefault(merge_point, []).append(child)

                # Add forks at appropriate positions
                for fork_point, forks in fork_points.items():
                    for fork in forks:
                        self._add_fork_node(session_node, session_id, fork, tree)

                # Add merges at appropriate positions
                for merge_point, merges in merge_points.items():
                    for merge in merges:
                        self._add_merge_node(session_node, session_id, merge)

        self._update_root_label()

    def _get_sorted_session_ids(self) -> list[str]:
        """Return session IDs sorted according to current sort order."""
        session_items = []
        for session_id, metadata in self._sessions.items():
            title = metadata.get("title", "")
            session_items.append({
                "id": session_id,
                "created": metadata.get("created", ""),
                "last_modified": metadata.get("last_modified", ""),
                "title": title.lower() if title else "",
                "messages": metadata.get("message_count", 0),
                "tokens": metadata.get("total_input_tokens", 0) + metadata.get("total_output_tokens", 0),
                "cost": metadata.get("total_cost", 0.0),
            })

        # Sort based on current order
        if self._sort_order == "modified_desc":
            session_items.sort(key=lambda x: x["last_modified"], reverse=True)
        elif self._sort_order == "modified_asc":
            session_items.sort(key=lambda x: x["last_modified"])
        elif self._sort_order == "date_desc":
            session_items.sort(key=lambda x: x["created"], reverse=True)
        elif self._sort_order == "date_asc":
            session_items.sort(key=lambda x: x["created"])
        elif self._sort_order == "title_asc":
            session_items.sort(key=lambda x: (x["title"] == "", x["title"]))
        elif self._sort_order == "title_desc":
            session_items.sort(key=lambda x: (x["title"] == "", x["title"]), reverse=True)
        elif self._sort_order == "messages_desc":
            session_items.sort(key=lambda x: x["messages"], reverse=True)
        elif self._sort_order == "messages_asc":
            session_items.sort(key=lambda x: x["messages"])
        elif self._sort_order == "tokens_desc":
            session_items.sort(key=lambda x: x["tokens"], reverse=True)
        elif self._sort_order == "cost_desc":
            session_items.sort(key=lambda x: x["cost"], reverse=True)

        return [item["id"] for item in session_items]

    def _on_key(self, event: Key) -> None:
        """Handle Escape to clear search."""
        if event.key == "escape":
            search_input = self.query_one("#search-input", Input)
            if search_input.has_class("visible"):
                self._clear_search()
                event.prevent_default()
                event.stop()

    def _hide_search(self) -> None:
        """Hide search input and focus tree."""
        search_input = self.query_one("#search-input", Input)
        search_input.remove_class("visible")
        tree = self.query_one("#turn-tree", SelectableTree)
        tree.focus()

    def _clear_search(self) -> None:
        """Clear search and show all nodes."""
        search_input = self.query_one("#search-input", Input)
        search_input.value = ""
        self._search_query = ""
        self._apply_search_filter()
        self._hide_search()

    def _apply_search_filter(self) -> None:
        """Rebuild tree showing only nodes matching the search query.

        Note: Search only works for loaded sessions.
        """
        tree = self.query_one("#turn-tree", SelectableTree)
        tree.root.remove_children()

        # Determine which sessions to expand:
        # - Always expand current session
        # - Also expand parent session if current is a fork
        sessions_to_expand = {self._current_session_id}
        current_metadata = self._sessions.get(self._current_session_id)
        if current_metadata:
            parent_id = current_metadata.get("parent_id")
            if parent_id:
                sessions_to_expand.add(parent_id)

        # Use sorted session order
        sorted_session_ids = self._get_sorted_session_ids()

        for session_id in sorted_session_ids:
            metadata = self._sessions[session_id]
            is_current = metadata.get("is_current", False)
            loaded_data = self._loaded_sessions.get(session_id)

            # Find matching turns (only for loaded sessions)
            matching_turns = []
            if loaded_data and self._search_query:
                for turn in loaded_data["turns"]:
                    if self._turn_matches_search(turn, metadata):
                        matching_turns.append(turn)

            # Skip session if no matches and we have a search query
            if self._search_query and not matching_turns and loaded_data:
                continue

            # Recreate session node
            session_label = self._make_session_label_from_metadata(metadata, is_current)
            session_node = tree.root.add(
                session_label,
                data={"type": "session", "session_id": session_id}
            )
            metadata["node"] = session_node

            # Only add turns if session is loaded
            if loaded_data:
                # Add turns (filtered or all)
                turns_to_show = matching_turns if self._search_query else loaded_data["turns"]
                for turn in turns_to_show:
                    idx = turn["idx"]
                    mode = self._context_modes.get((session_id, idx), ContextMode.DROP)
                    content_blocks = turn.get("content_blocks", [])
                    label = self._make_turn_label(turn["role"], turn["content"], mode, content_blocks, session_id=session_id)
                    turn_node = session_node.add(
                        label,
                        data={"type": "turn", "session_id": session_id, "turn_idx": idx}
                    )
                    turn["node"] = turn_node

                    # Add content block children
                    self._add_content_block_nodes(turn_node, session_id, idx, content_blocks)

                # Expand session if it has matches, is current, or is parent of current fork
                if matching_turns or session_id in sessions_to_expand:
                    session_node.expand()

        self._update_root_label()

    def _turn_matches_search(self, turn: dict, metadata: dict) -> bool:
        """Check if a turn matches the current search query."""
        if not self._search_query:
            return True

        # Check session title
        title = metadata.get("title", "")
        if title and self._search_query in title.lower():
            return True

        # Check turn content
        if self._search_query in turn["content"].lower():
            return True

        # Check tool names
        for block in turn.get("content_blocks", []):
            if isinstance(block, ToolUseBlock):
                if self._search_query in block.name.lower():
                    return True

        return False

    def get_selected_messages(self) -> list:
        """Get included messages in order for context building.

        Returns Message objects with context_mode and content_blocks set
        from the original session message data.
        """
        # Use the indexed version and strip the indices
        indexed = self.get_selected_messages_with_indices()
        return [msg for msg, _idx in indexed]

    def get_selected_messages_with_indices(self) -> list[tuple]:
        """Get included messages with their original indices for context building.

        Returns list of (Message, original_index) tuples, sorted by original index.
        This preserves positioning information for proper context reconstruction
        when some messages are summarized and others are copied.

        Also includes merge marker content at their merge points, so the LLM
        knows about work done in merged forks.
        """
        from models import Message, TextBlock
        results = []

        # Only process the current session if it's loaded
        if not self._current_session_id:
            return results

        loaded_data = self._loaded_sessions.get(self._current_session_id)
        metadata = self._sessions.get(self._current_session_id)
        if not loaded_data or not metadata:
            return results

        session = loaded_data["session"]
        included_items = []  # Will hold both turns and merge markers

        # Collect turns
        for turn in loaded_data["turns"]:
            turn_key = (self._current_session_id, turn["idx"])
            mode = self._context_modes.get(turn_key, ContextMode.DROP)
            if mode != ContextMode.DROP:
                # Get original message from session if available
                orig_msg = None
                if turn["idx"] < len(session.messages):
                    orig_msg = session.messages[turn["idx"]]

                included_items.append({
                    "type": "turn",
                    "session_created": session.created,
                    "sort_key": turn["idx"],  # Integer for turns
                    "turn_idx": turn["idx"],
                    "role": turn["role"],
                    "content": turn["content"],
                    "mode": mode,
                    "orig_msg": orig_msg,
                })

        # Collect merge markers from session's children
        for child in session.children:
            if child.get("status") != "merged":
                continue
            fork_id = child.get("session_id", "")
            merge_point = child.get("merge_point", -1)
            if merge_point < 0:
                continue

            merge_key = ("merge", session.id, fork_id)
            mode = self._merge_modes.get(merge_key, ContextMode.COPY)
            if mode == ContextMode.DROP:
                continue

            # Load the fork session to get the merge message
            fork_session = Session.load(fork_id)
            if not fork_session or not fork_session.merge_message:
                continue

            fork_name = child.get("name") or fork_session.get_fork_display_name()
            merge_content = f"[Merged from fork '{fork_name}']\n{fork_session.merge_message}"

            included_items.append({
                "type": "merge",
                "session_created": session.created,
                "sort_key": merge_point + 0.5,  # Place after the turn at merge_point
                "turn_idx": merge_point,  # Use merge_point for index
                "role": "user",  # Treat as user message for context
                "content": merge_content,
                "mode": mode,
                "orig_msg": None,
                    "fork_id": fork_id,
                    "fork_name": fork_name,
                })

        # Sort by session date then sort_key (turns are integers, merges are .5)
        included_items.sort(key=lambda t: (t["session_created"], t["sort_key"]))

        for item in included_items:
            orig = item.get("orig_msg")
            if orig:
                # Use rich content from original message
                msg = Message(
                    role=item["role"],
                    content=item["content"],
                    content_blocks=orig.content_blocks,
                    context_mode=item["mode"],
                    summary=orig.summary,
                )
            else:
                # Fallback to text-only (includes merge markers)
                msg = Message(
                    role=item["role"],
                    content=item["content"],
                    content_blocks=[TextBlock(text=item["content"])],
                    context_mode=item["mode"],
                )
            results.append((msg, item["turn_idx"]))

        return results

    def set_session_streaming(self, session_id: str, is_streaming: bool) -> None:
        """Update the streaming indicator for a session.

        Called when a session starts or stops streaming.
        """
        if is_streaming:
            self._streaming_sessions.add(session_id)
        else:
            self._streaming_sessions.discard(session_id)

        # Update session label to show/hide streaming indicator
        metadata = self._sessions.get(session_id)
        if metadata and metadata.get("node"):
            is_active = metadata.get("is_current", False)
            metadata["node"].label = self._make_session_label_from_metadata(metadata, is_active)

    def set_active_session(self, session_id: str) -> None:
        """Set the active session and update visual highlighting.

        Also sets context modes for the new session's turns to COPY (default include).
        """
        old_session_id = self._current_session_id
        self._current_session_id = session_id

        # Update old session's label (remove highlight)
        if old_session_id and old_session_id in self._sessions:
            old_metadata = self._sessions[old_session_id]
            old_metadata["is_current"] = False
            if old_metadata.get("node"):
                old_metadata["node"].label = self._make_session_label_from_metadata(old_metadata, False)

        # Update new session's label (add highlight) and set context modes
        if session_id in self._sessions:
            new_metadata = self._sessions[session_id]
            new_metadata["is_current"] = True
            if new_metadata.get("node"):
                new_metadata["node"].label = self._make_session_label_from_metadata(new_metadata, True)

            # Set context modes for new session's turns to COPY if not already set
            # This ensures turns are included when forking
            loaded_data = self._loaded_sessions.get(session_id)
            if loaded_data:
                for turn in loaded_data["turns"]:
                    turn_key = (session_id, turn["idx"])
                    if turn_key not in self._context_modes:
                        self._context_modes[turn_key] = ContextMode.COPY
                        self._update_turn_label(session_id, turn["idx"])

    def create_new_session(self) -> Session:
        """Create a new session and make it current."""
        new_session = Session()

        tree = self.query_one("#turn-tree", SelectableTree)

        # Add new session node (will be highlighted as active)
        session_label = self._make_session_label(new_session, True)
        session_node = tree.root.add(
            session_label,
            data={"type": "session", "session_id": new_session.id}
        )
        session_node.expand()

        # Update old active session's highlighting
        if self._current_session_id and self._current_session_id in self._sessions:
            old_metadata = self._sessions[self._current_session_id]
            old_metadata["is_current"] = False
            if old_metadata.get("node"):
                old_metadata["node"].label = self._make_session_label_from_metadata(old_metadata, False)

        self._current_session_id = new_session.id

        # Add metadata entry
        self._sessions[new_session.id] = {
            "id": new_session.id,
            "created": new_session.created,
            "last_modified": new_session.last_modified,
            "model": new_session.model,
            "title": new_session.title,
            "message_count": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost": 0.0,
            "parent_id": new_session.parent_id,
            "children": new_session.children,
            "fork_name": new_session.fork_name,
            "fork_status": new_session.fork_status,
            "node": session_node,
            "is_current": True,
        }

        # Add loaded session data
        self._loaded_sessions[new_session.id] = {
            "session": new_session,
            "turns": [],
        }

        self._update_root_label()
        return new_session

    def clear(self) -> None:
        """Clear all data."""
        tree = self.query_one("#turn-tree", SelectableTree)
        tree.root.remove_children()
        self._sessions.clear()
        self._loaded_sessions.clear()
        self._context_modes.clear()
        self._merge_modes.clear()
        self._session_colors.clear()
        self._color_index = 0
        self._current_session_id = None
        self._update_root_label()
