from __future__ import annotations

from pathlib import Path
from textual.widgets import Tree, Input
from textual.containers import Vertical
from textual.message import Message
from textual.events import Key, Click
from textual.binding import Binding
from textual.timer import Timer
from datetime import datetime
from rich.text import Text
from rich.style import Style
from rich.markup import escape as escape_markup
from typing import TYPE_CHECKING

from tokenizer import count_tokens
from session import Session
from models import ContextMode, TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, ArchiveBlock, LinkBlock, ForkBlock, MergeBlock, MergedToBlock
from core.tree_state import TreeState, TreeEvent, SessionData, TurnData
from core.context import ContextBuilder
from core.json_stream import StreamingJsonParser
from core.debug_log import debug_log

# Import shared rendering utilities
from widgets.session_rendering import (
    SessionLabelRenderer,
    TurnLabelRenderer,
    format_kt,
    token_style,
    get_model_icon,
    CLAUDE_SYSTEM_OVERHEAD,
    SESSION_COLORS,
    SPINNER_CHARS,
)

if TYPE_CHECKING:
    from typing import Any


class SelectableTreeWidget(Tree):
    """Tree widget with space-bar toggle for multiselect.

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

    class ArchiveRequested(Message):
        """Fired when user ctrl+shift+clicks on a turn to archive it."""
        def __init__(self, session_id: str, turn_indices: list[int]) -> None:
            self.session_id = session_id
            self.turn_indices = turn_indices
            super().__init__()

    class ColonPressed(Message):
        """Fired when user types : to jump to text entry with colon."""
        pass

    class JumpToExchangeEnd(Message):
        """Fired when user presses 'e' on an exchange group to jump to its last turn."""
        def __init__(self, session_id: str, last_turn_idx: int) -> None:
            self.session_id = session_id
            self.last_turn_idx = last_turn_idx
            super().__init__()


    def on_click(self, event: Click) -> None:
        """Handle clicks on tree nodes.

        - Ctrl+Shift+Click on turn: archive those turns
        - Ctrl+Click on session: create link command

        Uses on_click (message handler) rather than _on_click (override)
        to avoid interfering with the Tree's default click handling.
        """
        meta = event.style.meta

        if "line" not in meta:
            return

        node = self.get_node_at_line(meta["line"])
        if not node or not node.data:
            return

        node_type = node.data.get("type")

        # Ctrl+Shift+Click: archive turn(s)
        if event.ctrl and event.shift:
            session_id = node.data.get("session_id")
            if session_id is None:
                return

            if node_type == "turn":
                turn_index = node.data.get("turn_idx")
                if turn_index is not None:
                    self.post_message(self.ArchiveRequested(session_id, [turn_index]))
                    event.stop()
            return

        # Ctrl+Click: create link
        if event.ctrl:
            if node_type in ("session", "fork", "merge"):
                session_id = node.data.get("session_id")
                if session_id:
                    self.post_message(self.LinkRequested(session_id))
                    event.stop()

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


class ContextTreeView(Vertical):
    """Left panel view showing all sessions with selectable turns.

    Note: Class is named ContextTreeView to maintain
    compatibility with Textual message handler naming conventions in app.py.
    """

    DEFAULT_CSS = """
    ContextTreeView {
        width: 40;
        height: 100%;
        border-right: solid $primary;
    }

    ContextTreeView > SelectableTreeWidget {
        height: 1fr;
        background: $background;
    }

    /* Subtle hover - slight darkening to preserve colored text visibility */
    ContextTreeView > SelectableTreeWidget > .tree--highlight {
        /* no text-style change - preserve original colors */
    }

    ContextTreeView > SelectableTreeWidget > .tree--highlight-line {
        background: #1a1a2e;
    }

    /* Override cursor (focused node) - slightly more visible dark background */
    ContextTreeView > SelectableTreeWidget > .tree--cursor {
        background: #252540;
        text-style: none;
    }

    ContextTreeView > #search-input {
        dock: top;
        display: none;
        height: auto;
        margin: 0;
        padding: 0 1;
        border: none;
        background: $surface;
    }

    ContextTreeView > #search-input.visible {
        display: block;
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

    class ArchiveRequested(Message):
        """Fired when user ctrl+shift+clicks a turn to archive it."""
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
    _spinner_chars = SPINNER_CHARS

    def __init__(
        self,
        tree_state: TreeState | None = None,
        **kwargs
    ):
        super().__init__(**kwargs)

        # Spinner animation state (also used for pulsing high-token nodes)
        self._spinner_frame: int = 0
        self._spinner_timer: Timer | None = None

        # Track nodes with high token counts that need pulsing animation
        # Set of (session_id, turn_idx) for turn nodes, or (session_id, exchange_id) for groups
        self._pulsing_nodes: set[tuple[str, str | int]] = set()

        # Background loading flag - when True, observer skips expensive updates
        self._background_loading: bool = False

        # Use provided TreeState or create internal one
        self._state = tree_state if tree_state is not None else TreeState()
        self._owns_state = tree_state is None  # Track if we created it

        # Shared renderers for consistent session/turn labels
        self._session_renderer = SessionLabelRenderer(
            spinner_chars=self._spinner_chars,
            include_model_icon=True,
            include_tokens=True,
        )
        self._turn_renderer = TurnLabelRenderer(include_tokens=True)

        # Node references (Textual-specific, not in TreeState)
        # session_id -> tree node
        self._session_nodes: dict[str, Any] = {}
        # (session_id, turn_idx) -> tree node
        self._turn_nodes: dict[tuple[str, int], Any] = {}
        # (session_id, turn_idx, tool_use_id) -> tool info dict (for streaming tool tracking)
        self._tool_use_nodes: dict[tuple[str, int, str], dict] = {}
        # (session_id, turn_idx) -> accumulated streaming text
        self._streaming_text: dict[tuple[str, int], str] = {}

        # Streaming label debounce state
        # Rate-limit tree label updates during streaming to reduce UI overhead
        self._streaming_label_timer: Timer | None = None
        self._streaming_label_dirty: set[tuple[str, int]] = set()  # (session_id, turn_idx) needing update
        self._streaming_label_interval: float = 0.1  # 100ms = 10 updates/sec max

        # Local UI state (not shared)
        self._search_query: str = ""

    def compose(self):
        yield Input(placeholder="Search sessions...", id="search-input")
        tree = SelectableTreeWidget("[dim]loading...[/]", id="turn-tree")
        tree.root.data = {"type": "root"}
        yield tree

    def on_mount(self) -> None:
        tree = self.query_one("#turn-tree", SelectableTreeWidget)
        tree.root.expand()
        tree.root.allow_expand = False
        tree.auto_expand = False  # Don't auto-expand on selection
        # Set callback for tree to get session colors for node icons
        tree.set_color_callback(self._get_session_color)

        # Register as observer of TreeState
        self._state.add_observer(self._on_tree_state_event)

        # Start spinner if any sessions are already streaming
        if self._state.get_streaming_sessions():
            self._start_spinner()

    def on_unmount(self) -> None:
        """Clean up observer registration and timers."""
        self._state.remove_observer(self._on_tree_state_event)
        self._stop_spinner()
        self._stop_streaming_label_timer()

    def _stop_streaming_label_timer(self) -> None:
        """Stop the streaming label debounce timer."""
        if self._streaming_label_timer is not None:
            self._streaming_label_timer.stop()
            self._streaming_label_timer = None
        self._streaming_label_dirty.clear()

    def _on_tree_state_event(self, event: TreeEvent, data: dict) -> None:
        """Handle state change notifications from TreeState.

        This is the observer callback - translates state changes to UI updates.
        All UI updates should flow through here in response to TreeState changes.
        """
        debug_log.debug(f"TreeState event: {event.name}", category="tree", details=data)
        if event == TreeEvent.FULL_REBUILD:
            # TreeState was cleared or requests full rebuild
            self._rebuild_tree()

        elif event == TreeEvent.SESSION_ADDED:
            session_id = data.get("session_id")
            if session_id and session_id not in self._session_nodes:
                # During background loading, skip tree node creation entirely
                # We'll do a single rebuild at the end
                if not self._background_loading:
                    self._add_session_node(session_id, update_root_label=True)

        elif event == TreeEvent.SESSION_REMOVED:
            session_id = data.get("session_id")
            if session_id and session_id in self._session_nodes:
                node = self._session_nodes.pop(session_id)
                node.remove()
                # Clean up turn nodes for this session
                keys_to_remove = [k for k in self._turn_nodes if k[0] == session_id]
                for key in keys_to_remove:
                    del self._turn_nodes[key]
                # Clean up tool use nodes
                tool_keys = [k for k in self._tool_use_nodes if k[0] == session_id]
                for key in tool_keys:
                    del self._tool_use_nodes[key]
                self._update_root_label()

        elif event == TreeEvent.SESSION_LOADED:
            # Session data loaded - populate its turns if node exists
            session_id = data.get("session_id")
            if session_id:
                session_node = self._session_nodes.get(session_id)
                if session_node:
                    self._populate_session_node(session_id, session_node)

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
                self._add_streaming_turn_node(session_id, turn_idx, role)

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
                # Don't call _update_root_label here - wait for CONTEXT_TOKENS_CHANGED
                # which fires after app recalculates from compiled context

        elif event == TreeEvent.TURN_VIEWED:
            # Turn was marked as viewed - update label to remove unviewed indicator
            session_id = data.get("session_id")
            turn_idx = data.get("turn_idx")
            if session_id and turn_idx is not None:
                self._update_turn_label(session_id, turn_idx)
                self._update_session_label(session_id)

        elif event == TreeEvent.CONTEXT_TOKENS_CHANGED:
            # App calculated new token counts - update root label
            self._update_root_label()

        elif event == TreeEvent.SESSION_SELECTED:
            # Current session changed - update labels
            session_id = data.get("session_id")
            prev_session_id = data.get("prev_session_id")
            if prev_session_id:
                self._update_session_label(prev_session_id)
            if session_id:
                self._update_session_label(session_id)
            # Don't call _update_root_label here - wait for CONTEXT_TOKENS_CHANGED

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
        """Advance the spinner to the next frame and update streaming/pulsing labels."""
        self._spinner_frame = (self._spinner_frame + 1) % len(self._spinner_chars)
        # Update labels for all streaming sessions
        for session_id in self._state.get_streaming_sessions():
            self._update_session_label(session_id)

        # Update labels for pulsing nodes (high token counts)
        self._update_pulsing_nodes()

    def _update_pulsing_nodes(self) -> None:
        """Update labels for all nodes that are pulsing due to high token counts."""
        # Use spinner_frame for pulse animation (0-9 mapped from spinner chars length)
        pulse_frame = self._spinner_frame % 10

        for key in list(self._pulsing_nodes):
            session_id, identifier = key
            if isinstance(identifier, int):
                # Turn node
                turn_node = self._turn_nodes.get((session_id, identifier))
                if turn_node:
                    turn_data = self._state.get_turn(session_id, identifier)
                    if turn_data:
                        mode = self._state.get_context_mode(session_id, identifier)
                        turn_node.label = self._make_turn_label(
                            turn_data.role, turn_data.content, mode,
                            turn_data.content_block, session_id=session_id,
                            tokens=turn_data.tokens, viewed=turn_data.viewed,
                            pulse_frame=pulse_frame
                        )
            else:
                # Exchange group node
                if hasattr(self, '_exchange_group_nodes'):
                    group_node = self._exchange_group_nodes.get((session_id, identifier))
                    if group_node and group_node.data:
                        turn_indices = group_node.data.get("turn_indices", [])
                        turns = [self._state.get_turn(session_id, idx) for idx in turn_indices]
                        turns = [t for t in turns if t]
                        if turns:
                            total_tokens = sum(t.tokens for t in turns)
                            # Determine group mode
                            modes = set(self._state.get_context_mode(session_id, t.idx) for t in turns)
                            if len(modes) == 1:
                                group_mode = modes.pop()
                            elif ContextMode.DROP in modes and len(modes) == 1:
                                group_mode = ContextMode.DROP
                            else:
                                group_mode = ContextMode.COMPRESS
                            group_node.label = self._make_exchange_group_label(
                                turns, total_tokens, group_mode, pulse_frame=pulse_frame
                            )

    def _update_session_label(self, session_id: str) -> None:
        """Update a session node's label (for streaming indicator, etc.)."""
        session_data = self._state.get_session(session_id)
        node = self._session_nodes.get(session_id)
        if not session_data or not node:
            return
        is_active = session_id == self._state.get_current_session_id()
        node.label = self._make_session_label(session_data, is_active)

    def _add_session_node(self, session_id: str, update_root_label: bool = True) -> None:
        """Add a single session node to the tree.

        Called when a new session is added (e.g., background fork or background load).
        Appends the session to the end of the tree.

        Args:
            session_id: The session ID to add
            update_root_label: Whether to update the root label (set False for batch adds)
        """
        session_data = self._state.get_session(session_id)
        if not session_data:
            return

        tree = self.query_one("#turn-tree", SelectableTreeWidget)
        is_current = session_id == self._state.get_current_session_id()

        # Build session label
        session_label = self._make_session_label_from_session_data(session_data, is_current)

        # Append session node
        session_node = tree.root.add(
            session_label,
            data={"type": "session", "session_id": session_id}
        )
        self._session_nodes[session_id] = session_node

        # If session is loaded and has turns, add them
        if session_data.is_loaded and session_data.turns:
            self._add_turns_to_node(session_node, session_id, session_data.turns)

        if update_root_label:
            self._update_root_label()

    def _add_streaming_turn_node(self, session_id: str, turn_idx: int, role: str) -> None:
        """Add a turn node when streaming starts.

        Called via observer when TreeState.start_turn() is called.
        """
        session_data = self._state.get_session(session_id)
        session_node = self._session_nodes.get(session_id)

        # Add tree node if session is loaded and has a visible node
        if session_data and session_data.is_loaded and session_node:
            # Get the turn data from TreeState (just created by start_turn)
            turn = self._state.get_turn(session_id, turn_idx)
            if turn:
                self._add_turn_to_tree(session_id, turn, is_streaming=True)

        # Update session label even if turn node wasn't created (session may be visible but collapsed)
        # Message count already updated by TreeState.start_turn
        if session_data and session_node:
            is_active = session_id == self._state.get_current_session_id()
            session_node.label = self._make_session_label(session_data, is_active)

        # Always update token counts when a turn starts
        self._update_root_label()

    def _finalize_turn_node(self, session_id: str, turn_idx: int, content: str, content_block) -> None:
        """Finalize a streaming turn node with final content.

        Called via observer when TreeState.finish_turn() is called.
        """
        turn_data = self._state.get_turn(session_id, turn_idx)
        turn_node = self._turn_nodes.get((session_id, turn_idx))

        # Update tree node if available
        if turn_data and turn_node:
            # Turns are leaf nodes - just update the label with final content
            mode = self._state.get_context_mode(session_id, turn_idx)
            turn_node.label = self._make_turn_label(
                turn_data.role, content, mode, content_block, session_id=session_id, tokens=turn_data.tokens, viewed=turn_data.viewed
            )

        # Update session label (streaming indicator, token counts) even if turn node wasn't visible
        session_data = self._state.get_session(session_id)
        session_node = self._session_nodes.get(session_id)
        if session_data and session_node:
            is_active = session_id == self._state.get_current_session_id()
            session_node.label = self._make_session_label(session_data, is_active)

        # Always update token counts when a turn finishes
        self._update_root_label()

    @property
    def state(self) -> TreeState:
        """Access the underlying TreeState."""
        return self._state

    def _get_session_color(self, session_id: str) -> str:
        """Get the color assigned to a session, assigning one if needed."""
        return self._state.get_session_color(session_id)

    async def load_all_sessions(self, current_session: Session) -> None:
        """Load all sessions into the tree.

        Uses lazy loading: only metadata is loaded initially.
        Full session data (turns) is loaded when a session is expanded or activated.
        The current session is always fully loaded.

        Note: This method populates TreeState and then triggers a rebuild.
        The observer handles UI updates in response to TreeState events.
        """
        # Get all session metadata (lightweight - no message content)
        all_session_metadata = []
        async for metadata in Session.list_sessions_async():
            all_session_metadata.append(metadata)

        # Clear TreeState - this fires FULL_REBUILD which clears and rebuilds the tree
        # (tree will be empty at this point since no sessions yet)
        self._state.clear()

        # Build metadata index
        session_ids_in_list = {s["id"] for s in all_session_metadata}

        # If current session is new (not in list), add it to TreeState
        if current_session.id not in session_ids_in_list:
            self._state.add_session(current_session, is_current=True)

        # Store all session metadata in TreeState
        for metadata in all_session_metadata:
            is_current = metadata["id"] == current_session.id
            if is_current:
                # Add to TreeState with in-memory current session data
                self._state.add_session(current_session, is_current=True)
            else:
                # Add to TreeState (from metadata for lazy loading)
                self._state.add_session_from_metadata(metadata, is_current=False)

        # Fully load the current session (always needed for chat)
        self._load_full_session(current_session.id, current_session)

        # Build tree with current sort order
        self._rebuild_tree()

    def load_current_session_only(self, current_session: Session) -> None:
        """Load only the current session into the tree immediately.

        This allows the UI to be responsive while other sessions load
        in the background via start_background_session_load().
        """
        # Clear TreeState
        self._state.clear()

        # Add and fully load the current session
        self._state.add_session(current_session, is_current=True)
        self._load_full_session(current_session.id, current_session)

        # Build tree with just this session
        self._rebuild_tree()

    async def start_background_session_load(self, current_session_id: str) -> None:
        """Load other sessions in the background, yielding to the event loop.

        This method reads session metadata from the index and adds them to
        TreeState incrementally. Sessions are appended directly to the tree
        (no rebuild) since the index is sorted by last_modified.

        Args:
            current_session_id: ID of current session to skip (already loaded)
        """
        import asyncio
        import time

        debug_log.info("Background session load: starting", category="tree")
        start_time = time.time()

        # Set flag to suppress tree node creation during bulk loading
        self._background_loading = True

        try:
            count = 0
            async for metadata in Session.list_sessions_async():
                # Skip the current session (already loaded)
                if metadata["id"] == current_session_id:
                    continue

                # Skip if already in state (shouldn't happen but be safe)
                if self._state.get_session(metadata["id"]):
                    continue

                # Add to TreeState only (no tree node creation due to flag)
                self._state.add_session_from_metadata(metadata, is_current=False)
                count += 1

                # Yield to event loop periodically to keep UI responsive
                if count % 100 == 0:
                    debug_log.debug(f"Background load: {count} sessions", category="tree")
                    await asyncio.sleep(0)

        finally:
            self._background_loading = False

        debug_log.info(f"Background session load: {count} sessions in {(time.time()-start_time)*1000:.0f}ms, starting rebuild", category="tree")

        # Single tree rebuild with all sessions
        self._rebuild_tree()

        debug_log.info(f"Background session load: complete in {(time.time()-start_time)*1000:.0f}ms", category="tree")

    def _make_session_label_from_session_data(self, session_data: SessionData, is_active: bool) -> str:
        """Create a label for a session node from SessionData."""
        try:
            dt = datetime.fromisoformat(session_data.created)
            date_str = dt.strftime("%b %d %H:%M")
        except:
            date_str = session_data.created[:16] if session_data.created else ""

        msg_count = session_data.message_count
        session_id = session_data.id

        # Use cached context tokens (actual context size calculated by tiktoken)
        # Add backend-specific overhead (Claude has ~19.3k system overhead)
        session_tokens = session_data.cached_context_tokens
        if session_data.backend_name == "claude" or (not session_data.backend_name and "claude" in (session_data.model or "").lower()):
            session_tokens += CLAUDE_SYSTEM_OVERHEAD

        # Show fork status indicator
        is_fork = session_data.parent_id is not None
        fork_status = session_data.fork_status
        if is_fork:
            if fork_status == "merged":
                prefix = "[green]✓[/] "
                status = "[dim]merged[/dim]"
            else:
                prefix = "[magenta]↳[/] "
                status = ""
        else:
            prefix = ""
            status = ""

        # Animated streaming indicator
        is_streaming = self._state.is_streaming(session_id)
        if is_streaming:
            spinner = self._spinner_chars[self._spinner_frame]
            streaming_indicator = f"[yellow]{spinner}[/] "
        else:
            streaming_indicator = ""

        # Unviewed turns indicator (hidden for now, tracking logic preserved)
        unviewed_indicator = ""

        # Model icon for visual differentiation
        model_icon = get_model_icon(session_data.model, session_data.backend_name)
        model_indicator = f"{model_icon} " if model_icon else ""

        # Build label: fork name or title (if present), session ID prefix, msg count, tokens, datetime
        fork_name = session_data.fork_name
        title = session_data.title
        if fork_name:
            name_part = escape_markup(fork_name)
        elif title:
            truncated = title[:25] + "..." if len(title) > 25 else title
            name_part = escape_markup(truncated)
        else:
            name_part = None

        # Always show session ID prefix for identification
        id_prefix = f"[dim]{session_id[:8]}[/] "

        # Format token count
        token_str = format_kt(session_tokens)

        if name_part:
            label = f"{model_indicator}{id_prefix}{name_part} [dim]({msg_count}msg {token_str})[/]{unviewed_indicator} {status}"
        else:
            label = f"{model_indicator}{id_prefix}{date_str} [dim]({msg_count}msg {token_str})[/]{unviewed_indicator} {status}"

        # Highlight active session
        if is_active:
            return f"{prefix}{streaming_indicator}[bold cyan]{label}[/]"
        else:
            return f"{prefix}{streaming_indicator}{label}"

    def _make_session_label(self, session: Session | SessionData, is_active: bool) -> str:
        """Create a label for a session node from a Session or SessionData object."""
        if isinstance(session, SessionData):
            return self._make_session_label_from_session_data(session, is_active)
        else:
            # Convert Session to SessionData for consistent rendering
            session_data = self._state.get_session(session.id)
            if session_data:
                return self._make_session_label_from_session_data(session_data, is_active)
            # Fallback: create temporary SessionData (shouldn't normally happen)
            temp_data = SessionData(
                id=session.id,
                created=session.created,
                last_modified=session.last_modified,
                model=session.model,
                title=session.title,
                message_count=len(session.turns),
                total_input_tokens=session.total_input_tokens,
                total_output_tokens=session.total_output_tokens,
                total_cost=session.total_cost,
                parent_id=session.parent_id,
                children=session.children,
                fork_name=session.fork_name,
                fork_status=session.fork_status,
                backend_name=session.backend_name,
            )
            return self._make_session_label_from_session_data(temp_data, is_active)

    def _load_full_session(self, session_id: str, session: Session) -> bool:
        """Fully load a session's messages and turns (sync - requires pre-loaded session).

        Args:
            session_id: The session to load
            session: Pre-loaded Session object (required)

        Returns True if loaded successfully.
        """
        if self._state.is_session_loaded(session_id):
            return True  # Already loaded

        # Load into TreeState (which manages session data, turns, context modes, and merge modes)
        self._state.load_session(session_id, session)

        return True

    async def _load_full_session_async(self, session_id: str, session: Session = None) -> bool:
        """Fully load a session's messages and turns (async - can load from disk).

        Args:
            session_id: The session to load
            session: Optional pre-loaded Session object (avoids re-loading from disk)

        Returns True if loaded successfully, False if session not found.
        """
        if self._state.is_session_loaded(session_id):
            return True  # Already loaded

        if session is None:
            session = await Session.load_async(session_id)
            if not session:
                return False

        # Load into TreeState (which manages session data, turns, context modes, and merge modes)
        self._state.load_session(session_id, session)

        return True

    def _is_session_loaded(self, session_id: str) -> bool:
        """Check if a session's full data has been loaded."""
        return self._state.is_session_loaded(session_id)

    async def _activate_session(self, session_id: str) -> None:
        """Activate a session - load it if needed and post SessionActivated."""
        # Ensure session is loaded
        if not self._is_session_loaded(session_id):
            if not await self._load_full_session_async(session_id):
                return  # Session not found

        session_data = self._state.get_session(session_id)
        if session_data and session_data.session_ref:
            self.post_message(self.SessionActivated(session_data.session_ref))

    def _add_turns_to_node(
        self,
        session_node,
        session_id: str,
        turns: list,
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
        turn,
    ) -> None:
        """Add a single turn node to a parent session node."""
        # Check if node already exists
        existing_node = self._turn_nodes.get((session_id, turn.idx))
        if existing_node:
            # Check if node needs to be re-parented
            if existing_node.parent != parent_node:
                # Remove from old parent and create new node under correct parent
                existing_node.remove()
                del self._turn_nodes[(session_id, turn.idx)]
                # Fall through to create new node
            else:
                # Same parent - just update the label
                mode = self._state.get_context_mode(session_id, turn.idx)
                existing_node.label = self._make_turn_label(
                    turn.role, turn.content, mode, turn.content_block,
                    session_id=session_id, tokens=turn.tokens, viewed=turn.viewed
                )
                existing_node.data["exchange_id"] = turn.exchange_id
                return

        mode = self._state.get_context_mode(session_id, turn.idx)
        label = self._make_turn_label(turn.role, turn.content, mode, turn.content_block, session_id=session_id, tokens=turn.tokens, viewed=turn.viewed)

        # All turns are leaf nodes - content is shown in the label
        turn_node = parent_node.add(
            label,
            data={"type": "turn", "session_id": session_id, "turn_idx": turn.idx, "exchange_id": turn.exchange_id},
            allow_expand=False,
        )
        self._turn_nodes[(session_id, turn.idx)] = turn_node

        # Register for pulsing animation if tokens are high
        PULSE_THRESHOLD = 10000
        if turn.tokens >= PULSE_THRESHOLD:
            self._pulsing_nodes.add((session_id, turn.idx))
            self._start_spinner()  # Ensure animation is running

    def _add_exchange_group_node(
        self,
        parent_node,
        session_id: str,
        turns: list,
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
            child_label = self._make_turn_label(turn.role, turn.content, mode, turn.content_block, session_id=session_id, tokens=turn.tokens, viewed=turn.viewed)
            turn_node = group_node.add(
                child_label,
                data={"type": "turn", "session_id": session_id, "turn_idx": turn.idx, "exchange_id": exchange_id},
                allow_expand=False,
            )
            self._turn_nodes[(session_id, turn.idx)] = turn_node

        # Collapse by default (user can expand to see individual turns)
        group_node.collapse()

        # Store group node reference for updates
        if not hasattr(self, '_exchange_group_nodes'):
            self._exchange_group_nodes = {}
        self._exchange_group_nodes[(session_id, exchange_id)] = group_node

        # Register for pulsing animation if tokens are high
        PULSE_THRESHOLD = 10000
        if total_tokens >= PULSE_THRESHOLD:
            self._pulsing_nodes.add((session_id, exchange_id))
            self._start_spinner()  # Ensure animation is running
        # Also register child turns that are high-token
        for turn in turns:
            if turn.tokens >= PULSE_THRESHOLD:
                self._pulsing_nodes.add((session_id, turn.idx))
                self._start_spinner()

    def _make_exchange_group_label(
        self,
        turns: list,
        total_tokens: int,
        group_mode: ContextMode,
        pulse_frame: int = 0,
    ) -> str:
        """Create a label for an exchange group node.

        Format: [green]1.2kt[/] ☑ 🤖 Agent exchange (5 turns)
        Token color lerps from green to red as tokens approach 50k.
        Nodes over 10k tokens will pulse with animated color.
        """
        # Token count with color based on size (green -> red), pulsing if over 10k
        kt_str = format_kt(total_tokens)
        style = token_style(total_tokens, pulse_frame=pulse_frame)
        token_part = f"{style}{kt_str}[/] " if kt_str else ""

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

    def _add_turn_to_tree(
        self,
        session_id: str,
        turn,
        is_streaming: bool = False,
    ) -> None:
        """Add a turn to the tree, respecting exchange grouping.

        If the turn has an exchange_id:
        - If an exchange group for that ID already exists, add to it
        - Otherwise, create a new exchange group node

        If no exchange_id, add as a flat turn node.

        Args:
            session_id: The session this turn belongs to
            turn: TurnData object with the turn info
            is_streaming: If True, expand the node for streaming visibility
        """
        session_node = self._session_nodes.get(session_id)
        if not session_node:
            return

        # Initialize exchange group tracking if needed
        if not hasattr(self, '_exchange_group_nodes'):
            self._exchange_group_nodes = {}

        exchange_id = turn.exchange_id

        if exchange_id:
            # Check if we already have a group for this exchange
            group_key = (session_id, exchange_id)
            group_node = self._exchange_group_nodes.get(group_key)

            if group_node:
                # Add turn to existing group
                self._add_turn_to_exchange_group(group_node, session_id, turn, is_streaming)
            else:
                # Create new exchange group with this turn
                self._create_streaming_exchange_group(session_node, session_id, turn, is_streaming)
        else:
            # No exchange_id - add as flat turn node
            self._add_single_turn_node(session_node, session_id, turn)

            # Expand for streaming visibility
            if is_streaming:
                turn_node = self._turn_nodes.get((session_id, turn.idx))
                if turn_node:
                    turn_node.expand()

    def _create_streaming_exchange_group(
        self,
        session_node,
        session_id: str,
        turn,
        is_streaming: bool = False,
    ) -> None:
        """Create a new exchange group node for a streaming turn.

        Called when we see the first turn with a new exchange_id.
        """
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
        turn_mode = self._state.get_context_mode(session_id, turn.idx)
        child_label = self._make_turn_label(
            turn.role, turn.content, turn_mode, turn.content_block,
            session_id=session_id, tokens=turn.tokens, viewed=turn.viewed
        )
        turn_node = group_node.add(
            child_label,
            data={"type": "turn", "session_id": session_id, "turn_idx": turn.idx, "exchange_id": exchange_id},
            allow_expand=False,
        )
        self._turn_nodes[(session_id, turn.idx)] = turn_node

        # Expand for streaming visibility
        if is_streaming:
            group_node.expand()

    def _add_turn_to_exchange_group(
        self,
        group_node,
        session_id: str,
        turn,
        is_streaming: bool = False,
    ) -> None:
        """Add a turn to an existing exchange group node."""
        exchange_id = turn.exchange_id

        # Add turn index to the group's tracking list
        turn_indices = group_node.data.get("turn_indices", [])
        if turn.idx not in turn_indices:
            turn_indices.append(turn.idx)
            group_node.data["turn_indices"] = turn_indices

        # Add the turn as a child of the group
        turn_mode = self._state.get_context_mode(session_id, turn.idx)
        child_label = self._make_turn_label(
            turn.role, turn.content, turn_mode, turn.content_block,
            session_id=session_id, tokens=turn.tokens, viewed=turn.viewed
        )
        turn_node = group_node.add(
            child_label,
            data={"type": "turn", "session_id": session_id, "turn_idx": turn.idx, "exchange_id": exchange_id},
            allow_expand=False,
        )
        self._turn_nodes[(session_id, turn.idx)] = turn_node

        # Update the group label with new totals
        self._update_exchange_group_label(session_id, exchange_id)

    def _make_turn_label(self, role: str, content: str, mode: ContextMode, content_block=None, session_id: str = None, tokens: int = 0, viewed: bool = True, pulse_frame: int = 0) -> str:
        """Create a label for a turn node.

        Args:
            role: The turn's role (user, assistant, system, tool)
            content: Display text for the turn
            mode: Context mode (COPY, COMPRESS, DROP)
            content_block: Single content block (TextBlock, ForkBlock, etc.)
            session_id: Session ID (for future use)
            tokens: Token count for this turn
            viewed: Whether this turn has been viewed
            pulse_frame: Animation frame for pulsing high-token nodes (0-9)
        """
        # Unviewed indicator (hidden for now, tracking logic preserved)
        unviewed_indicator = ""

        # Mode indicator: copy=green check, compress=yellow Σ, drop=empty box
        if mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            indicator = "[yellow]Σ[/]"
        else:  # DROP
            indicator = "☐"

        # Determine turn type and icon based on content_block
        if isinstance(content_block, ArchiveBlock):
            # Archive marker - special rendering
            summary = content_block.structured_summary.work_done if content_block.structured_summary else content_block.summary
            preview = summary[:40] + "..." if len(summary) > 40 else summary
            preview = preview.replace("\n", " ")
            return f"{unviewed_indicator}{indicator} 📦 {escape_markup(preview)}"

        if isinstance(content_block, ForkBlock):
            # Fork turn - show fork icon and name
            preview = f"{content_block.fork_name}"
            if content_block.status == "merged":
                return f"{unviewed_indicator}{indicator} [green]🔀 Fork: {escape_markup(preview)} [dim]merged[/dim][/green]"
            return f"{unviewed_indicator}{indicator} [bold]🔀 Fork: {escape_markup(preview)}[/]"

        if isinstance(content_block, MergeBlock):
            # Merge turn - show merge icon and summary
            msg_preview = content_block.message[:40] + "..." if len(content_block.message) > 40 else content_block.message
            msg_preview = msg_preview.replace("\n", " ")
            return f"{unviewed_indicator}{indicator} [green]⬅️ Merged: {escape_markup(content_block.fork_name)}[/] {escape_markup(msg_preview)}"

        if isinstance(content_block, MergedToBlock):
            # MergedTo turn - show that this fork was merged to parent
            msg_preview = content_block.message[:40] + "..." if len(content_block.message) > 40 else content_block.message
            msg_preview = msg_preview.replace("\n", " ")
            return f"{unviewed_indicator}{indicator} [green]➡️ Merged to parent[/] {escape_markup(msg_preview)}"

        if isinstance(content_block, LinkBlock):
            # Link turn - show link icon
            preview = content_block.summary[:40] + "..." if len(content_block.summary) > 40 else content_block.summary
            preview = preview.replace("\n", " ")
            return f"{unviewed_indicator}{indicator} [magenta]🔗 Link:[/] {escape_markup(preview)}"

        if isinstance(content_block, ToolUseBlock):
            # Tool use turn - show tool name + key input parameter
            kt_str = format_kt(tokens)
            style = token_style(tokens, pulse_frame=pulse_frame)
            token_str = f"{style}({kt_str})[/] " if kt_str else ""
            tool_name = content_block.name
            # Extract meaningful preview from input based on tool type
            tool_input = content_block.input or {}
            preview = ""
            if tool_name in ("Read", "Write", "Edit"):
                # Show relative path from cwd
                file_path = tool_input.get("file_path", "")
                if file_path:
                    try:
                        rel_path = str(Path(file_path).relative_to(Path.cwd()))
                        preview = f" {rel_path}"
                    except ValueError:
                        # Path not relative to cwd, show last 2 parts
                        parts = file_path.split("/")
                        if len(parts) >= 2:
                            preview = f" {parts[-2]}/{parts[-1]}"
                        else:
                            preview = f" {parts[-1]}"
            elif tool_name == "Glob":
                pattern = tool_input.get("pattern", "")
                if pattern:
                    preview = f" {pattern}"
            elif tool_name == "Grep":
                # Show pattern and path if available
                pattern = tool_input.get("pattern", "")
                grep_path = tool_input.get("path", "")
                if pattern:
                    pat_preview = pattern[:15] + "..." if len(pattern) > 15 else pattern
                    preview = f" /{pat_preview}/"
                    if grep_path:
                        try:
                            rel_path = str(Path(grep_path).relative_to(Path.cwd()))
                            preview += f" {rel_path}"
                        except ValueError:
                            path_parts = grep_path.split("/")
                            path_preview = path_parts[-1] if path_parts else grep_path
                            preview += f" {path_preview}"
            elif tool_name == "Bash":
                cmd = tool_input.get("command", "")
                if cmd:
                    # Show command up to reasonable length
                    cmd_preview = cmd[:30] + "..." if len(cmd) > 30 else cmd
                    cmd_preview = cmd_preview.replace("\n", " ")
                    preview = f" {cmd_preview}"
            return f"{unviewed_indicator}{indicator} [green]🔧[/]{token_str}[green]{escape_markup(tool_name)}[/][dim]{escape_markup(preview)}[/]"

        if isinstance(content_block, ToolResultBlock):
            # Tool result turn - show truncated result content
            result_content = content_block.content or ""
            # Clean up for preview
            result_preview = result_content.replace("\n", " ").strip()
            result_preview = result_preview[:40] + "..." if len(result_preview) > 40 else result_preview
            error_indicator = "[red]❌ [/]" if content_block.is_error else ""
            kt_str = format_kt(tokens)
            style = token_style(tokens, pulse_frame=pulse_frame)
            token_str = f"{style}({kt_str})[/] " if kt_str else ""
            return f"{unviewed_indicator}{indicator} {error_indicator}[green]📋[/]{token_str}[green]Result[/] [dim]{escape_markup(result_preview)}[/]"

        if isinstance(content_block, ErrorBlock):
            # Error turn
            return f"{unviewed_indicator}{indicator} [yellow]⚠ Error:[/] {escape_markup(content_block.reason)}"

        if isinstance(content_block, InterruptionBlock):
            # Interruption turn
            return f"{unviewed_indicator}{indicator} [red]⚠ Interrupted:[/] {escape_markup(content_block.reason)}"

        # Default: text turn (user or assistant message)
        icon = "👤" if role == "user" else "🤖"

        preview = content[:40] + "..." if len(content) > 40 else content
        preview = preview.replace("\n", " ")

        # Format token count with color based on size, pulsing if over 10k
        kt_str = format_kt(tokens)
        style = token_style(tokens, pulse_frame=pulse_frame)
        token_str = f"{style}({kt_str})[/] " if kt_str else ""

        return f"{unviewed_indicator}{indicator} {icon}{token_str}{escape_markup(preview)}"

    def _update_root_label(self) -> None:
        """Update root label with selected context tokens for current session.

        Token counts come from TreeState (calculated by app from compiled context).
        This method also builds turn_modes dict for the chat log.
        """
        debug_log.debug("_update_root_label called", category="tree")
        tree = self.query_one("#turn-tree", SelectableTreeWidget)

        current_session_turn_ids = []
        # Build turn_modes dict for current session (1-indexed turn_id -> mode name)
        turn_modes: dict[int, str] = {}

        current_session_id = self._state.get_current_session_id()

        # Build turn_modes and turn_ids for current session
        if current_session_id:
            session_data = self._state.get_session(current_session_id)
            if session_data and session_data.is_loaded and session_data.turns:
                for turn in session_data.turns:
                    mode = self._state.get_context_mode(current_session_id, turn.idx)
                    if mode != ContextMode.DROP:
                        current_session_turn_ids.append(turn.idx + 1)
                    # Build turn_modes for current session
                    turn_id = turn.idx + 1  # 1-indexed
                    turn_modes[turn_id] = mode.name

        included_count = sum(
            1 for m in self._state.get_context_modes_for_session(current_session_id).values()
            if m != ContextMode.DROP
        ) if current_session_id else 0

        # Get token counts from TreeState (calculated by app from compiled context)
        selected_tokens, total_tokens = self._state.get_context_tokens()

        # Root label shows context selection for current session
        tree.root.label = f"[bold]Context:[/] {selected_tokens:,} [dim]tokens[/]"

        self.post_message(self.SelectionChanged(
            included_count, total_tokens, selected_tokens, current_session_turn_ids, turn_modes
        ))

    def _update_turn_label(self, session_id: str, turn_idx: int) -> None:
        """Update a turn's mode indicator label."""
        turn_data = self._state.get_turn(session_id, turn_idx)
        if not turn_data:
            return

        mode = self._state.get_context_mode(session_id, turn_idx)
        turn_node = self._turn_nodes.get((session_id, turn_idx))
        if turn_node:
            turn_node.label = self._make_turn_label(
                turn_data.role, turn_data.content, mode, turn_data.content_block, session_id=session_id, tokens=turn_data.tokens, viewed=turn_data.viewed
            )

    def is_selection_curated(self) -> bool:
        """Check if selection differs from 'all current session turns as COPY'.

        Returns True if:
        - Any turn from another session is included, OR
        - Any turn from current session is not COPY, OR
        - Any turn uses COMPRESS mode
        """
        current_session_id = self._state.get_current_session_id()
        if not current_session_id:
            return False

        session_data = self._state.get_session(current_session_id)
        if not session_data or not session_data.is_loaded or not session_data.turns:
            return False

        # Check if any non-current session turns are included
        all_modes = self._state.get_all_context_modes()
        for turn_key, mode in all_modes.items():
            if mode != ContextMode.DROP and turn_key[0] != current_session_id:
                return True

        # Check if all current session turns are COPY
        for turn in session_data.turns:
            mode = self._state.get_context_mode(current_session_id, turn.idx)
            if mode != ContextMode.COPY:
                return True

        return False

    def add_turn_to_current(self, role: str, content: str, raw_events: list[dict], content_block=None) -> None:
        """Add a new turn to the current session."""
        current_session_id = self._state.get_current_session_id()
        if not current_session_id:
            return

        session_data = self._state.get_session(current_session_id)
        session_node = self._session_nodes.get(current_session_id)
        if not session_data or not session_data.is_loaded:
            return

        idx = len(session_data.turns) if session_data.turns else 0

        # Set context mode in TreeState
        self._state.set_context_mode(current_session_id, idx, ContextMode.COMPRESS)

        tokens = count_tokens(content) if content else 0
        # Streaming assistant turns start as unviewed, user turns are always viewed
        viewed = role != "assistant"
        label = self._make_turn_label(role, content, ContextMode.COMPRESS, content_block, session_id=current_session_id, tokens=tokens, viewed=viewed)
        if session_node:
            # All turns are leaf nodes
            turn_node = session_node.add(
                label,
                data={"type": "turn", "session_id": current_session_id, "turn_idx": idx},
                allow_expand=False,
            )
            self._turn_nodes[(current_session_id, idx)] = turn_node
        else:
            turn_node = None

        # Update session label with new count
        if session_node:
            session_node.label = self._make_session_label(session_data, True)

        self._update_root_label()

    def remove_turn(self, session_id: str, turn_idx: int, updated_session: Session = None) -> bool:
        """Remove a turn from the tree without reloading all sessions.

        Args:
            session_id: The session containing the turn
            turn_idx: The index of the turn to remove
            updated_session: Optional updated session object to use for label

        Returns True if the turn was removed, False if not found.
        """
        session_data = self._state.get_session(session_id)
        if not session_data or not session_data.is_loaded:
            return False

        # Remove the tree node
        turn_node = self._turn_nodes.get((session_id, turn_idx))
        if turn_node:
            turn_node.remove()
            del self._turn_nodes[(session_id, turn_idx)]

        # Update turn_nodes indices for turns after the removed one
        keys_to_update = [(sid, idx) for sid, idx in self._turn_nodes.keys()
                         if sid == session_id and idx > turn_idx]
        for old_key in keys_to_update:
            node = self._turn_nodes.pop(old_key)
            new_key = (session_id, old_key[1] - 1)
            self._turn_nodes[new_key] = node
            # Update node data
            if node.data:
                node.data["turn_idx"] = new_key[1]

        # Remove context mode for deleted turn and shift others in TreeState
        self._state.remove_context_mode(session_id, turn_idx)
        self._state.shift_context_modes_after_removal(session_id, turn_idx)

        # Update session label with new message count
        session_node = self._session_nodes.get(session_id)
        if session_node and session_data:
            is_active = session_id == self._state.get_current_session_id()
            session_node.label = self._make_session_label(session_data, is_active)

        self._update_root_label()
        return True

    def remove_session(self, session_id: str) -> bool:
        """Remove a session from the tree.

        Args:
            session_id: The session to remove

        Returns True if the session was removed, False if not found.

        Note: UI cleanup is handled by the SESSION_REMOVED event observer.
        """
        session_data = self._state.get_session(session_id)
        if not session_data:
            return False

        # Remove from TreeState - this fires SESSION_REMOVED event
        # The observer callback handles UI cleanup
        self._state.remove_session(session_id)

        return True

    # --- Streaming-aware methods for incremental tree updates ---

    def start_turn(
        self,
        session_id: str,
        turn_idx: int,
        role: str,
        exchange_id: str = None,
        turn_type: str = "text",
        tool_name: str = "",
        tool_use_id: str = "",
        result_preview: str = "",
    ) -> None:
        """Start a new turn node when streaming begins.

        Called when a 'turn_started' event is received from SessionRunner.
        Notifies TreeState which will fire TURN_STARTED event.
        The observer callback (_add_streaming_turn_node) handles UI updates.

        Args:
            session_id: The session this turn belongs to
            turn_idx: The index of this turn in the session
            role: "user", "assistant", or "tool"
            exchange_id: Optional ID to group turns in an agentic exchange
            turn_type: "text", "tool_use", or "tool_result" - for proper labels during streaming
            tool_name: For tool_use turns, the name of the tool
            tool_use_id: For tool_use/tool_result turns, the tool use ID
            result_preview: For tool_result turns, a preview of the result
        """
        # Notify TreeState - it will set context mode and fire TURN_STARTED event
        # The observer callback will create the UI node
        self._state.start_turn(
            session_id,
            turn_idx,
            role,
            exchange_id=exchange_id,
            turn_type=turn_type,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            result_preview=result_preview,
        )

    def add_tool_use_to_turn(
        self,
        session_id: str,
        turn_idx: int,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict,
        tool_index: int,
    ) -> None:
        """DEPRECATED: Tool uses are now separate turn nodes.

        Tool use turns are created by TurnStartedAction (tool_use_turn_started event).
        This method is kept for backwards compatibility but does nothing.
        """
        pass

    def update_tool_input_streaming(
        self,
        session_id: str,
        turn_idx: int,
        tool_use_id: str,
        tool_name: str,
        partial_json: str,
    ) -> None:
        """DEPRECATED: Tool uses are now separate turn nodes.

        Tool input streaming is handled by the chat log widget, not the context tree.
        This method is kept for backwards compatibility but does nothing.
        """
        pass

    def update_streaming_text(
        self,
        session_id: str,
        turn_idx: int,
        text_delta: str,
    ) -> None:
        """Update turn node to reflect streaming text content.

        Called when 'text_delta' events arrive.
        Each text turn shows its own streaming content; tool turns are separate nodes.

        Uses debouncing to reduce UI refresh overhead - labels are updated at most
        every 100ms (10 updates/sec) to prevent blocking the event loop during
        fast streaming.
        """
        turn_data = self._state.get_turn(session_id, turn_idx)
        turn_node = self._turn_nodes.get((session_id, turn_idx))
        if not turn_data or not turn_node:
            return

        # Accumulate text
        text_key = (session_id, turn_idx)
        if text_key not in self._streaming_text:
            self._streaming_text[text_key] = ""
        self._streaming_text[text_key] += text_delta

        # Mark this turn as needing a label update (debounced)
        self._streaming_label_dirty.add(text_key)

        # Start debounce timer if not already running
        if self._streaming_label_timer is None:
            self._streaming_label_timer = self.set_timer(
                self._streaming_label_interval,
                self._flush_streaming_labels,
            )

    def _flush_streaming_labels(self) -> None:
        """Flush all pending streaming label updates.

        Called by the debounce timer to batch-update all dirty labels at once.
        """
        self._streaming_label_timer = None

        if not self._streaming_label_dirty:
            return

        # Copy and clear to allow new updates during flush
        dirty_keys = list(self._streaming_label_dirty)
        self._streaming_label_dirty.clear()

        for text_key in dirty_keys:
            session_id, turn_idx = text_key
            turn_data = self._state.get_turn(session_id, turn_idx)
            turn_node = self._turn_nodes.get(text_key)
            if not turn_data or not turn_node:
                continue

            text = self._streaming_text.get(text_key, "")
            preview = text[:30].replace("\n", " ")
            if len(text) > 30:
                preview += "..."

            icon = "👤" if turn_data.role == "user" else "🤖"
            mode = self._state.get_context_mode(session_id, turn_idx)
            if mode == ContextMode.COPY:
                indicator = "[green]☑[/]"
            elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
                indicator = "[yellow]Σ[/]"
            else:
                indicator = "☐"

            turn_node.label = f"{indicator} {icon} [dim]{escape_markup(preview)}[/]"

    def flush_streaming_text(
        self,
        session_id: str,
        turn_idx: int,
        text: str,
    ) -> None:
        """Handle text segment completion during streaming.

        Called when a text segment completes (before tool use starts).
        Turns are leaf nodes - we don't add children, just clear the accumulator.
        The final turn label is set when finish_turn is called.
        """
        # Clear streaming accumulator - subsequent text will be a new segment
        text_key = (session_id, turn_idx)
        if text_key in self._streaming_text:
            del self._streaming_text[text_key]
        # Also remove from dirty set to avoid stale updates
        self._streaming_label_dirty.discard(text_key)

    def add_tool_result_to_turn(
        self,
        session_id: str,
        turn_idx: int,
        tool_use_id: str,
        result: str,
        is_error: bool = False,
        tool_index: int = None,
    ) -> None:
        """DEPRECATED: Tool results are now separate turn nodes.

        Tool result turns are created by TurnStartedAction (tool_result_turn_started event).
        This method is kept for backwards compatibility but does nothing.
        """
        pass

    def finish_turn(
        self,
        session_id: str,
        turn_idx: int,
        content: str,
        content_block,
        raw_events: list[dict],
    ) -> None:
        """Finalize a streaming turn when complete.

        Called when a 'done' event is received from SessionRunner.
        Notifies TreeState which will fire TURN_FINISHED event.
        The observer callback (_finalize_turn_node) handles UI updates.
        """
        # Notify TreeState - the observer will handle UI update
        self._state.finish_turn(session_id, turn_idx, content, content_block, raw_events)

        # Clean up streaming tracking state for this turn
        text_key = (session_id, turn_idx)
        if text_key in self._streaming_text:
            del self._streaming_text[text_key]
        # Also remove from dirty set to avoid stale updates
        self._streaming_label_dirty.discard(text_key)

        # Clean up tool use nodes for this turn
        keys_to_remove = [k for k in self._tool_use_nodes if k[0] == session_id and k[1] == turn_idx]
        for key in keys_to_remove:
            del self._tool_use_nodes[key]

    async def on_tree_node_expanded(self, event) -> None:
        """Handle node expansion - lazy load session data when expanded."""
        node_data = event.node.data
        if not node_data:
            return

        node_type = node_data.get("type")
        if node_type == "session":
            session_id = node_data.get("session_id")
            if session_id and not self._is_session_loaded(session_id):
                # Lazy load the session
                if await self._load_full_session_async(session_id):
                    # Rebuild just this session's children
                    self._populate_session_node(session_id, event.node)

    def _populate_session_node(self, session_id: str, session_node) -> None:
        """Populate a session node with its turns after lazy loading.

        Fork and merge markers are now proper turns (with ForkBlock/MergeBlock content),
        so they appear naturally in the turn iteration at their correct positions.
        """
        session_data = self._state.get_session(session_id)
        if not session_data or not session_data.is_loaded or not session_data.turns:
            return

        # Clear existing turn children to prevent double-nesting when streaming
        # adds nodes and SESSION_LOADED triggers rebuild.
        keys_to_remove = [k for k in self._turn_nodes if k[0] == session_id]
        for key in keys_to_remove:
            del self._turn_nodes[key]

        # Clear exchange group nodes for this session
        if hasattr(self, '_exchange_group_nodes'):
            group_keys_to_remove = [k for k in self._exchange_group_nodes if k[0] == session_id]
            for key in group_keys_to_remove:
                del self._exchange_group_nodes[key]

        children_to_remove = []
        for child in session_node.children:
            if child.data:
                node_type = child.data.get("type")
                if node_type in ("turn", "exchange_group"):
                    children_to_remove.append(child)
        for child in children_to_remove:
            child.remove()

        # Add turn nodes - fork/merge turns are included naturally since they're stored as turns
        self._add_turns_to_node(session_node, session_id, session_data.turns)

    def on_tree_node_selected(self, event) -> None:
        """Handle node selection - show info in preview pane.

        Selection doesn't activate sessions - use Enter for that.
        This allows browsing the session list without loading heavy sessions.
        """
        from core.debug_log import debug_log
        node_data = event.node.data
        if not node_data:
            debug_log.info("on_tree_node_selected: no node_data", category="tree")
            return

        node_type = node_data.get("type")
        debug_log.info(f"on_tree_node_selected: type={node_type}, data={node_data}", category="tree")

        if node_type == "session":
            # Just show session info in preview - don't activate
            session_id = node_data.get("session_id")
            session_data = self._state.get_session(session_id)
            if session_data:
                self.post_message(self.TurnInspected({
                    "type": "session_preview",
                    "session_id": session_id,
                    "title": session_data.title,
                    "created": session_data.created,
                    "message_count": session_data.message_count,
                    "model": session_data.model,
                }))
        elif node_type == "summary":
            # Show full summary in the inspection pane
            session_id = node_data.get("session_id")
            session_data = self._state.get_session(session_id)
            if session_data and session_data.session_ref:
                session = session_data.session_ref
                self.post_message(self.TurnInspected({
                    "type": "summary",
                    "title": session.title,
                    "summary": session.summary,
                    "session_id": session_id,
                }))
        elif node_type == "turn":
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            session_data = self._state.get_session(session_id)
            debug_log.info(f"on_tree_node_selected turn: session_id={session_id}, turn_idx={turn_idx}, session_data_loaded={session_data.is_loaded if session_data else False}", category="tree")
            if session_data and session_data.is_loaded and session_data.turns:
                turn = self._state.get_turn(session_id, turn_idx)
                if turn:
                    # Get context mode for this turn
                    mode = self._state.get_context_mode(session_id, turn_idx)
                    debug_log.info(f"on_tree_node_selected: posting TurnInspected for session_id={session_id}, turn_idx={turn_idx}", category="tree")
                    # Send turn data for inspection (includes session_id for cross-session navigation)
                    self.post_message(self.TurnInspected({
                        "type": "turn",
                        "role": turn.role,
                        "content": turn.content,
                        "events": turn.events,
                        "turn_idx": turn_idx,
                        "context_mode": mode.name,
                    }, session_id=session_id))
                else:
                    debug_log.warning(f"on_tree_node_selected: turn {turn_idx} not found in session_data", category="tree")
            else:
                debug_log.warning(f"on_tree_node_selected: session {session_id} not loaded", category="tree")
        elif node_type == "exchange_group":
            # Scroll to the first turn in the exchange group
            session_id = node_data.get("session_id")
            turn_indices = node_data.get("turn_indices", [])
            exchange_id = node_data.get("exchange_id")
            if turn_indices:
                first_turn_idx = min(turn_indices)
                last_turn_idx = max(turn_indices)
                self.post_message(self.TurnInspected({
                    "type": "exchange_group",
                    "session_id": session_id,
                    "turn_idx": first_turn_idx,  # For scrolling to first turn
                    "last_turn_idx": last_turn_idx,  # For "jump to end" feature
                    "exchange_id": exchange_id,
                    "turn_count": len(turn_indices),
                }, session_id=session_id))
        elif node_type == "text":
            # Send text block data for inspection and highlighting
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            mode = self._state.get_context_mode(session_id, turn_idx)
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
            mode = self._state.get_context_mode(session_id, turn_idx)
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
            mode = self._state.get_context_mode(session_id, turn_idx)
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
            # Show fork info in preview pane and scroll to fork point
            fork_session_id = node_data.get("session_id")
            parent_session_id = node_data.get("parent_session_id")
            fork_turn_idx = node_data.get("turn_idx", -1)
            session_data = self._state.get_session(fork_session_id)
            if session_data:
                self.post_message(self.TurnInspected({
                    "type": "fork",
                    "session_id": fork_session_id,
                    "parent_session_id": parent_session_id,
                    "title": session_data.title or node_data.get("fork_name", ""),
                    "created": session_data.created,
                    "message_count": session_data.message_count,
                    "model": session_data.model,
                    "is_fork": True,
                    "status": node_data.get("status", "active"),
                    "turn_idx": fork_turn_idx,  # Turn index for scrolling in parent
                }, session_id=parent_session_id))
        elif node_type == "merge":
            # Show merge details in inspection pane and scroll to merge point
            fork_id = node_data.get("session_id")
            parent_session_id = node_data.get("parent_session_id")
            fork_name = node_data.get("fork_name", "")
            merge_message = node_data.get("message", "")
            merge_turn_idx = node_data.get("turn_idx", -1)
            mode = self._state.get_merge_mode(parent_session_id, fork_id)
            self.post_message(self.TurnInspected({
                "type": "merge",
                "session_id": fork_id,
                "parent_session_id": parent_session_id,
                "fork_name": fork_name,
                "message": merge_message,
                "context_mode": mode.name,
                "turn_idx": merge_turn_idx,  # Turn index for scrolling in parent
            }, session_id=parent_session_id))
        elif node_type == "link":
            # Show link details in inspection pane and scroll to it
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            self.post_message(self.TurnInspected({
                "type": "link",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "linked_session_id": node_data.get("linked_session_id"),
                "link_id": node_data.get("link_id"),
                "summary": node_data.get("summary", ""),
                "is_orphaned": node_data.get("is_orphaned", False),
            }, session_id=session_id))
        elif node_type == "fork_block":
            # Fork turn - scroll to it and show info
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            self.post_message(self.TurnInspected({
                "type": "fork_block",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "child_session_id": node_data.get("child_session_id"),
                "fork_name": node_data.get("fork_name"),
                "prompt": node_data.get("prompt"),
                "status": node_data.get("status"),
            }, session_id=session_id))
        elif node_type == "merge_block":
            # Merge turn - scroll to it and show info
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            self.post_message(self.TurnInspected({
                "type": "merge_block",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "child_session_id": node_data.get("child_session_id"),
                "fork_name": node_data.get("fork_name"),
                "message": node_data.get("message"),
            }, session_id=session_id))

    async def on_selectable_tree_widget_activate_requested(self, event: SelectableTreeWidget.ActivateRequested) -> None:
        """Handle Enter key - activate session (load into chat view)."""
        node_data = event.node_data
        node_type = node_data.get("type")

        if node_type == "session":
            # Activate session - load and switch to it
            session_id = node_data.get("session_id")
            await self._activate_session(session_id)
        elif node_type == "fork":
            # Activate fork session
            session_id = node_data.get("session_id")
            await self._activate_session(session_id)
        elif node_type == "merge":
            # Activate merged fork session
            session_id = node_data.get("session_id")
            await self._activate_session(session_id)
        elif node_type == "fork_block":
            # Activate fork session from content_block
            child_session_id = node_data.get("child_session_id")
            if child_session_id:
                await self._activate_session(child_session_id)
        elif node_type == "merge_block":
            # Activate merged fork session from content_block
            child_session_id = node_data.get("child_session_id")
            if child_session_id:
                await self._activate_session(child_session_id)
        elif node_type == "link":
            # Activate linked session
            linked_session_id = node_data.get("linked_session_id")
            if linked_session_id and not node_data.get("is_orphaned"):
                await self._activate_session(linked_session_id)
        elif node_type == "turn":
            # Toggle context mode on Enter for turns (same as space)
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")

            # Use TreeState to toggle - it fires CONTEXT_MODE_CHANGED event
            new_mode = self._state.toggle_context_mode(session_id, turn_idx)

            self._update_turn_label(session_id, turn_idx)
            self._update_root_label()
            # Notify app to persist the change
            self.post_message(self.ContextModeChanged(session_id, turn_idx, new_mode))

    def on_selectable_tree_widget_toggle_requested(self, event: SelectableTreeWidget.ToggleRequested) -> None:
        """Handle space bar toggle - cycle through COPY -> COMPRESS -> DROP."""
        node_type = event.node_data.get("type")

        if node_type == "turn":
            session_id = event.node_data.get("session_id")
            turn_idx = event.node_data.get("turn_idx")

            # Use TreeState to toggle - it fires CONTEXT_MODE_CHANGED event
            new_mode = self._state.toggle_context_mode(session_id, turn_idx)

            self._update_turn_label(session_id, turn_idx)
            self._update_root_label()
            # Notify app to persist the change
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
                self._update_turn_label(session_id, turn_idx)
                self.post_message(self.ContextModeChanged(session_id, turn_idx, new_mode))

            # Update the group node label
            self._update_exchange_group_label(session_id, event.node_data.get("exchange_id"))
            self._update_root_label()

    def on_selectable_tree_widget_select_all_requested(self, event: SelectableTreeWidget.SelectAllRequested) -> None:
        """Set all turns in CURRENT session to COPY mode."""
        current_session_id = self._state.get_current_session_id()
        if not current_session_id:
            return
        session_data = self._state.get_session(current_session_id)
        if not session_data or not session_data.is_loaded or not session_data.turns:
            return
        for turn in session_data.turns:
            # Update TreeState
            self._state.set_context_mode(current_session_id, turn.idx, ContextMode.COPY)
            self._update_turn_label(current_session_id, turn.idx)
        self._update_root_label()

    def on_selectable_tree_widget_select_none_requested(self, event: SelectableTreeWidget.SelectNoneRequested) -> None:
        """Set all turns in CURRENT session to DROP mode."""
        current_session_id = self._state.get_current_session_id()
        if not current_session_id:
            return
        session_data = self._state.get_session(current_session_id)
        if not session_data or not session_data.is_loaded or not session_data.turns:
            return
        for turn in session_data.turns:
            # Update TreeState
            self._state.set_context_mode(current_session_id, turn.idx, ContextMode.DROP)
            self._update_turn_label(current_session_id, turn.idx)
        self._update_root_label()

    def on_selectable_tree_widget_search_requested(self, event: SelectableTreeWidget.SearchRequested) -> None:
        """Show the search input when / is pressed."""
        search_input = self.query_one("#search-input", Input)
        search_input.add_class("visible")
        search_input.focus()

    def on_selectable_tree_widget_turn_delete_requested(self, event: SelectableTreeWidget.TurnDeleteRequested) -> None:
        """Handle turn delete request - bubble up to app."""
        self.post_message(self.TurnDeleteRequested(event.session_id, event.turn_index))

    def on_selectable_tree_widget_session_delete_requested(self, event: SelectableTreeWidget.SessionDeleteRequested) -> None:
        """Handle session delete request - bubble up to app."""
        self.post_message(self.SessionDeleteRequested(event.session_id))

    def on_selectable_tree_widget_exchange_delete_requested(self, event: SelectableTreeWidget.ExchangeDeleteRequested) -> None:
        """Handle exchange delete request - bubble up to app."""
        self.post_message(self.ExchangeDeleteRequested(event.session_id, event.turn_indices))

    def on_selectable_tree_widget_link_requested(self, event: SelectableTreeWidget.LinkRequested) -> None:
        """Handle ctrl+click link request - bubble up to app."""
        self.post_message(self.SessionLinkRequested(event.session_id))

    def on_selectable_tree_widget_archive_requested(self, event: SelectableTreeWidget.ArchiveRequested) -> None:
        """Handle ctrl+shift+click archive request - bubble up to app."""
        self.post_message(self.ArchiveRequested(event.session_id, event.turn_indices))

    def on_selectable_tree_widget_colon_pressed(self, event: SelectableTreeWidget.ColonPressed) -> None:
        """Handle : key - bubble up to app to jump to text entry."""
        self.post_message(self.ColonPressed())

    def on_selectable_tree_widget_jump_to_exchange_end(self, event: SelectableTreeWidget.JumpToExchangeEnd) -> None:
        """Handle 'g' key on exchange group - bubble up to app to scroll to last turn."""
        self.post_message(self.JumpToExchangeEnd(event.session_id, event.last_turn_idx))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter tree nodes as user types."""
        if event.input.id == "search-input":
            self._search_query = event.value.lower()
            self._apply_search_filter()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Hide search and focus tree when Enter is pressed."""
        if event.input.id == "search-input":
            self._hide_search()

    def _rebuild_tree(self) -> None:
        """Rebuild the tree with sessions in the current sort order.

        Uses lazy loading: only loaded sessions show their turns.
        Unloaded sessions show as collapsed nodes.
        """
        import time
        start_time = time.time()
        debug_log.info("_rebuild_tree: starting", category="tree")

        tree = self.query_one("#turn-tree", SelectableTreeWidget)

        # Batch all updates to prevent per-node refreshes
        with self.app.batch_update():
            tree.root.remove_children()
            self._session_nodes.clear()
            self._turn_nodes.clear()
            self._tool_use_nodes.clear()

            all_sessions = self._state.get_all_sessions()
            debug_log.debug(f"_rebuild_tree: {len(all_sessions)} sessions to process", category="tree")
            if not all_sessions:
                self._update_root_label()
                return

            # Get session data sorted according to current order
            sorted_session_ids = self._get_session_ids()

            # Determine which sessions to expand (and thus need to be loaded):
            # - Always expand current session
            # - Also expand parent session if current is a fork
            current_session_id = self._state.get_current_session_id()
            sessions_to_expand = {current_session_id}
            if current_session_id:
                current_data = self._state.get_session(current_session_id)
                if current_data and current_data.parent_id:
                    sessions_to_expand.add(current_data.parent_id)
                    # Note: Parent loading is deferred to on_tree_node_expanded
                    # to avoid sync Session.load() calls here

            # Rebuild tree nodes for each session
            for session_id in sorted_session_ids:
                session_data = self._state.get_session(session_id)
                if not session_data:
                    continue
                is_current = session_data.is_current

                # Build session label
                session_label = self._make_session_label_from_session_data(session_data, is_current)
                session_node = tree.root.add(
                    session_label,
                    data={"type": "session", "session_id": session_id}
                )
                self._session_nodes[session_id] = session_node

                # Only add turn nodes if session is loaded
                if session_data.is_loaded and session_data.turns:
                    # Expand loaded sessions that should be expanded
                    if session_id in sessions_to_expand:
                        session_node.expand()

                    # Rebuild turn nodes - fork/merge turns are included since they're stored as turns
                    self._add_turns_to_node(session_node, session_id, session_data.turns)

        debug_log.info(f"_rebuild_tree: done in {(time.time()-start_time)*1000:.0f}ms", category="tree")
        self._update_root_label()

    def _get_session_ids(self) -> list[str]:
        """Return session IDs in index order (most recently used first)."""
        return list(self._state.get_all_sessions().keys())

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
        tree = self.query_one("#turn-tree", SelectableTreeWidget)
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
        tree = self.query_one("#turn-tree", SelectableTreeWidget)
        tree.root.remove_children()
        self._session_nodes.clear()
        self._turn_nodes.clear()

        # Determine which sessions to expand:
        # - Always expand current session
        # - Also expand parent session if current is a fork
        current_session_id = self._state.get_current_session_id()
        sessions_to_expand = {current_session_id}
        if current_session_id:
            current_data = self._state.get_session(current_session_id)
            if current_data and current_data.parent_id:
                sessions_to_expand.add(current_data.parent_id)

        # Use sorted session order
        sorted_session_ids = self._get_session_ids()

        for session_id in sorted_session_ids:
            session_data = self._state.get_session(session_id)
            if not session_data:
                continue
            is_current = session_data.is_current

            # Find matching turns (only for loaded sessions)
            matching_turns = []
            if session_data.is_loaded and session_data.turns and self._search_query:
                for turn in session_data.turns:
                    if self._turn_matches_search_data(turn, session_data):
                        matching_turns.append(turn)

            # Skip session if no matches and we have a search query
            if self._search_query and not matching_turns and session_data.is_loaded:
                continue

            # Recreate session node
            session_label = self._make_session_label_from_session_data(session_data, is_current)
            session_node = tree.root.add(
                session_label,
                data={"type": "session", "session_id": session_id}
            )
            self._session_nodes[session_id] = session_node

            # Only add turns if session is loaded
            if session_data.is_loaded and session_data.turns:
                # Add turns (filtered or all)
                turns_to_show = matching_turns if self._search_query else session_data.turns
                for turn in turns_to_show:
                    mode = self._state.get_context_mode(session_id, turn.idx)
                    label = self._make_turn_label(turn.role, turn.content, mode, turn.content_block, session_id=session_id, tokens=turn.tokens, viewed=turn.viewed)
                    # All turns are leaf nodes
                    turn_node = session_node.add(
                        label,
                        data={"type": "turn", "session_id": session_id, "turn_idx": turn.idx},
                        allow_expand=False,
                    )
                    self._turn_nodes[(session_id, turn.idx)] = turn_node

                # Expand session if it has matches, is current, or is parent of current fork
                if matching_turns or session_id in sessions_to_expand:
                    session_node.expand()

        self._update_root_label()

    def _turn_matches_search_data(self, turn, session_data: SessionData) -> bool:
        """Check if a TurnData matches the current search query."""
        if not self._search_query:
            return True

        # Check session title
        title = session_data.title or ""
        if title and self._search_query in title.lower():
            return True

        # Check turn content
        if self._search_query in turn.content.lower():
            return True

        # Check tool names in content_block
        if isinstance(turn.content_block, ToolUseBlock):
            if self._search_query in turn.content_block.name.lower():
                return True

        return False

    def get_cursor_turns(self) -> tuple[str, list[int]] | None:
        """Get the session_id and turn indices for the currently selected tree node.

        Returns (session_id, [turn_indices]) or None if no valid selection.
        """
        tree = self.query_one("#turn-tree", SelectableTreeWidget)
        node = tree.cursor_node
        if not node or not node.data:
            return None

        node_type = node.data.get("type")
        session_id = node.data.get("session_id")

        if node_type == "turn":
            turn_idx = node.data.get("turn_idx")
            if session_id is not None and turn_idx is not None:
                return (session_id, [turn_idx])

        return None

    def scroll_to_turn(self, session_id: str, turn_idx: int) -> bool:
        """Scroll to and select a specific turn in the tree.

        Args:
            session_id: The session containing the turn
            turn_idx: The 0-based turn index

        Returns:
            True if the turn was found and scrolled to, False otherwise
        """
        tree = self.query_one("#turn-tree", SelectableTreeWidget)

        # Ensure the session node exists and is expanded
        session_node = self._session_nodes.get(session_id)
        if session_node:
            session_node.expand()

        # Try to find the turn node
        turn_node = self._turn_nodes.get((session_id, turn_idx))
        if turn_node:
            # If the turn is inside an exchange group, expand the parent first
            parent = turn_node.parent
            if parent and parent.data and parent.data.get("type") == "exchange_group":
                parent.expand()

            tree.select_node(turn_node)
            tree.scroll_to_node(turn_node)
            return True

        return False

    def get_selected_messages(self) -> list:
        """Get included messages in order for context building.

        Returns Message objects with context_mode set from the original session data.
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
        current_session_id = self._state.get_current_session_id()
        if not current_session_id:
            return results

        # Use TreeState for turns (authoritative source during streaming)
        session_data = self._state.get_session(current_session_id)
        if not session_data or not session_data.is_loaded or session_data.turns is None:
            return results

        # Get session object for original turn data
        session = session_data.session_ref
        if not session:
            return results

        included_items = []  # Will hold both turns and merge markers

        # Collect turns from TreeState (includes streaming turns)
        for turn in session_data.turns:
            mode = self._state.get_context_mode(current_session_id, turn.idx)
            if mode != ContextMode.DROP:
                # Get original turn from session if available
                orig_turn = None
                if turn.idx < len(session.turns):
                    orig_turn = session.turns[turn.idx]

                included_items.append({
                    "type": "turn",
                    "session_created": session.created,
                    "sort_key": turn.idx,  # Integer for turns
                    "turn_idx": turn.idx,
                    "role": turn.role,
                    "content": turn.content,
                    "content_block": turn.content_block,  # Single content block
                    "mode": mode,
                    "orig_turn": orig_turn,
                })

        # Collect merge markers from session's children
        for child in session.children:
            if child.get("status") != "merged":
                continue
            fork_id = child.get("session_id", "")
            merge_point = child.get("merge_point", -1)
            if merge_point < 0:
                continue

            mode = self._state.get_merge_mode(session.id, fork_id)
            if mode == ContextMode.DROP:
                continue

            # Get the fork session to get the merge message
            # Try from state first to avoid sync disk load
            fork_data = self._state.get_session(fork_id)
            fork_session = fork_data.session_ref if fork_data else None
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
            orig_turn = item.get("orig_turn")
            content_block = item.get("content_block")

            if orig_turn:
                # Use content from original turn
                msg = Message(
                    role=item["role"],
                    content=item["content"],
                    content_blocks=[orig_turn.content_block] if orig_turn.content_block else [TextBlock(text=item["content"])],
                    context_mode=item["mode"],
                    summary=orig_turn.summary if hasattr(orig_turn, 'summary') else "",
                )
            elif content_block:
                # Use content_block from TreeState (for streaming turns not yet saved)
                msg = Message(
                    role=item["role"],
                    content=item["content"],
                    content_blocks=[content_block],
                    context_mode=item["mode"],
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
        Delegates to TreeState which fires STREAMING_STARTED/STOPPED events.
        The observer callback handles UI updates.
        """
        if is_streaming:
            self._state.start_streaming(session_id)
        else:
            self._state.stop_streaming(session_id)

    def set_active_session(self, session_id: str) -> None:
        """Set the active session and update visual highlighting.

        Also sets context modes for the new session's turns to COPY (default include).
        Delegates to TreeState which fires SESSION_SELECTED event.
        The observer callback handles UI label updates.
        """
        # Update TreeState - this fires SESSION_SELECTED event
        # The observer callback handles updating session labels
        self._state.set_current_session(session_id)

        # Set context modes for new session's turns to COPY if not already set
        # This ensures turns are included when forking
        # (CONTEXT_MODE_CHANGED events will update turn labels via observer)
        session_data = self._state.get_session(session_id)
        if session_data and session_data.turns:
            for turn in session_data.turns:
                current_mode = self._state.get_context_mode(session_id, turn.idx)
                if current_mode == ContextMode.DROP:
                    self._state.set_context_mode(session_id, turn.idx, ContextMode.COPY)

    def create_new_session(self) -> Session:
        """Create a new session and make it current.

        Note: UI updates are handled by observer callbacks:
        - SESSION_ADDED adds the new session node
        - SESSION_LOADED prepares for turns (empty for new session)
        """
        new_session = Session()

        # Update old active session's highlighting
        # (SESSION_SELECTED isn't fired by add_session, so do this manually)
        old_session_id = self._state.get_current_session_id()
        if old_session_id:
            old_node = self._session_nodes.get(old_session_id)
            old_data = self._state.get_session(old_session_id)
            if old_node and old_data:
                old_node.label = self._make_session_label_from_session_data(old_data, False)

        # Add to TreeState (sets as current) - fires SESSION_ADDED
        # Observer callback adds the session node
        self._state.add_session(new_session, is_current=True)

        # Expand the new session node
        session_node = self._session_nodes.get(new_session.id)
        if session_node:
            session_node.expand()

        # Load the session into TreeState (creates empty turns list) - fires SESSION_LOADED
        self._state.load_session(new_session.id, new_session)

        self._update_root_label()
        return new_session

    def clear(self) -> None:
        """Clear all data.

        Note: UI cleanup is handled by the FULL_REBUILD event observer.
        """
        # Clear local streaming state (not tracked in TreeState)
        self._streaming_text.clear()

        # Clear TreeState - this fires FULL_REBUILD event
        # The observer callback handles UI cleanup
        self._state.clear()
