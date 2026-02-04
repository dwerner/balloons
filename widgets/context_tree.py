from __future__ import annotations

from textual.widgets import Tree, Input, Select
from textual.containers import Vertical, Horizontal
from textual.message import Message
from textual.events import Key, Click
from textual.binding import Binding
from textual.timer import Timer
from datetime import datetime
from rich.text import Text
from rich.style import Style
from typing import TYPE_CHECKING

from tokenizer import count_tokens
from session import Session
from models import ContextMode, TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock
from core.tree_state import TreeState, TreeEvent, SessionData, TurnData
from core.json_stream import StreamingJsonParser

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


def get_model_icon(model: str, backend_name: str) -> str:
    """Get a visual icon for a model/backend combination.

    Icons help users quickly identify which model a session uses.
    Uses unicode symbols that render well in terminals.

    Args:
        model: Model identifier (e.g., "claude-opus-4-5-20251101", "gpt-4")
        backend_name: Backend name (e.g., "claude", "openrouter", "ollama")

    Returns:
        A short icon string with Rich markup for coloring.
    """
    model_lower = model.lower() if model else ""
    backend_lower = backend_name.lower() if backend_name else ""

    # Claude models - use different icons for different tiers
    if "opus" in model_lower or "opus" in backend_lower:
        return "[bold magenta]◆[/]"  # Diamond for Opus (premium)
    elif "sonnet" in model_lower:
        return "[cyan]◇[/]"  # Hollow diamond for Sonnet (balanced)
    elif "haiku" in model_lower:
        return "[green]○[/]"  # Circle for Haiku (fast/cheap)
    elif "claude" in model_lower or backend_lower == "claude":
        return "[blue]●[/]"  # Filled circle for generic Claude

    # OpenAI models
    if "gpt-4" in model_lower or "gpt4" in model_lower:
        return "[yellow]★[/]"  # Star for GPT-4
    elif "gpt-3" in model_lower or "gpt3" in model_lower:
        return "[yellow]☆[/]"  # Hollow star for GPT-3.5
    elif "o1" in model_lower or "o3" in model_lower:
        return "[red]✦[/]"  # Four-pointed star for reasoning models

    # Local/open models
    if "llama" in model_lower:
        return "[orange1]▲[/]"  # Triangle for Llama
    elif "qwen" in model_lower:
        return "[bright_blue]◈[/]"  # Diamond with dot for Qwen
    elif "mistral" in model_lower:
        return "[bright_cyan]◎[/]"  # Bullseye for Mistral
    elif "deepseek" in model_lower:
        return "[bright_green]◉[/]"  # Fisheye for DeepSeek
    elif "gemma" in model_lower:
        return "[bright_magenta]❖[/]"  # Diamond for Gemma

    # Backend-based fallbacks
    if backend_lower in ("ollama", "llamacpp"):
        return "[dim]▪[/]"  # Small square for local models
    elif backend_lower == "openrouter":
        return "[dim]◦[/]"  # Small circle for OpenRouter

    # Default - no icon if we can't identify the model
    return ""


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

    class LinkRequested(Message):
        """Fired when user ctrl+clicks on a session to create a link."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    def on_click(self, event: Click) -> None:
        """Handle ctrl+click on session to create link command.

        Uses on_click (message handler) rather than _on_click (override)
        to avoid interfering with the Tree's default click handling.
        Only stops propagation for ctrl+click on valid sessions.
        """
        if event.ctrl:
            meta = event.style.meta
            if "line" in meta:
                node = self.get_node_at_line(meta["line"])
                if node and node.data:
                    node_type = node.data.get("type")
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

    ContextTreeView > #sort-container {
        dock: top;
        height: auto;
        padding: 0 1;
        background: $surface;
    }

    ContextTreeView > #sort-container > #sort-select {
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

    class SessionLinkRequested(Message):
        """Fired when user ctrl+clicks a session to create a link command."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    # Spinner animation for streaming sessions
    _spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(
        self,
        initial_sort_order: str = "modified_desc",
        tree_state: TreeState | None = None,
        **kwargs
    ):
        super().__init__(**kwargs)

        # Spinner animation state
        self._spinner_frame: int = 0
        self._spinner_timer: Timer | None = None

        # Use provided TreeState or create internal one
        self._state = tree_state if tree_state is not None else TreeState()
        self._owns_state = tree_state is None  # Track if we created it

        # Node references (Textual-specific, not in TreeState)
        # session_id -> tree node
        self._session_nodes: dict[str, Any] = {}
        # (session_id, turn_idx) -> tree node
        self._turn_nodes: dict[tuple[str, int], Any] = {}
        # (session_id, exchange_id) -> tree node (for exchange group nodes)
        self._exchange_nodes: dict[tuple[str, str], Any] = {}
        # (session_id, turn_idx, tool_use_id) -> tree node (for streaming tool use tracking)
        self._tool_use_nodes: dict[tuple[str, int, str], Any] = {}
        # (session_id, turn_idx) -> accumulated streaming text
        self._streaming_text: dict[tuple[str, int], str] = {}

        # Local UI state (not shared)
        self._search_query: str = ""
        self._sort_order: str = initial_sort_order

    def compose(self):
        yield Input(placeholder="Search sessions...", id="search-input")
        with Horizontal(id="sort-container"):
            yield Select(
                [(label, key) for key, label in SORT_OPTIONS],
                value=self._sort_order,
                id="sort-select",
                allow_blank=False,
            )
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
        """Clean up observer registration."""
        self._state.remove_observer(self._on_tree_state_event)
        self._stop_spinner()

    def _on_tree_state_event(self, event: TreeEvent, data: dict) -> None:
        """Handle state change notifications from TreeState.

        This is the observer callback - translates state changes to UI updates.

        NOTE: Currently using dual-write pattern. The ContextTreeView methods
        (start_turn, finish_turn, etc.) both update TreeState AND update UI.
        So we skip TURN_STARTED/TURN_FINISHED here to avoid duplicate work.
        Once we migrate to app calling TreeState directly, these handlers
        will be enabled.
        """
        if event == TreeEvent.SESSION_ADDED:
            session_id = data.get("session_id")
            if session_id and session_id not in self._session_nodes:
                self._add_session_node(session_id)

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
            content_blocks = data.get("content_blocks", [])
            if session_id and turn_idx is not None:
                self._finalize_turn_node(session_id, turn_idx, content, content_blocks)

        elif event == TreeEvent.CONTEXT_MODE_CHANGED:
            session_id = data.get("session_id")
            turn_idx = data.get("turn_idx")
            if session_id and turn_idx is not None:
                self._update_turn_label(session_id, turn_idx)
                self._update_root_label()

        elif event == TreeEvent.SESSION_SELECTED:
            # Current session changed - update labels
            session_id = data.get("session_id")
            prev_session_id = data.get("prev_session_id")
            if prev_session_id:
                self._update_session_label(prev_session_id)
            if session_id:
                self._update_session_label(session_id)
            self._update_root_label()

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

    def _update_session_label(self, session_id: str) -> None:
        """Update a session node's label (for streaming indicator, etc.)."""
        session_data = self._state.get_session(session_id)
        node = self._session_nodes.get(session_id)
        if not session_data or not node:
            return
        is_active = session_id == self._state.get_current_session_id()
        node.label = self._make_session_label(session_data, is_active)

    def _add_session_node(self, session_id: str) -> None:
        """Add a single session node to the tree.

        Called when a new session is added (e.g., background fork).
        Adds the session at the top of the tree (most recent).
        """
        session_data = self._state.get_session(session_id)
        if not session_data:
            return

        tree = self.query_one("#turn-tree", SelectableTreeWidget)
        is_current = session_id == self._state.get_current_session_id()

        # Build session label
        session_label = self._make_session_label_from_session_data(session_data, is_current)

        # Add at the beginning (index 0) so new sessions appear at top
        # Note: Tree.add() appends, but we want to prepend for "most recent" order
        # We'll add normally and rely on the next rebuild to sort properly
        session_node = tree.root.add(
            session_label,
            data={"type": "session", "session_id": session_id}
        )
        self._session_nodes[session_id] = session_node

        # If session is loaded and has turns, add them
        if session_data.is_loaded and session_data.turns:
            self._add_turns_to_node(session_node, session_id, session_data.turns)

        self._update_root_label()

    def _add_streaming_turn_node(self, session_id: str, turn_idx: int, role: str) -> None:
        """Add a placeholder turn node when streaming starts.

        Called via observer when TreeState.start_turn() is called.
        """
        session_data = self._state.get_session(session_id)
        session_node = self._session_nodes.get(session_id)

        # Add tree node if session is loaded and has a visible node
        if session_data and session_data.is_loaded and session_node:
            # Create placeholder label
            label = self._make_turn_label(role, "[dim]streaming...[/]", ContextMode.COMPRESS, session_id=session_id)
            turn_node = session_node.add(
                label,
                data={"type": "turn", "session_id": session_id, "turn_idx": turn_idx}
            )
            turn_node.expand()
            self._turn_nodes[(session_id, turn_idx)] = turn_node

        # Update session label even if turn node wasn't created (session may be visible but collapsed)
        # Message count already updated by TreeState.start_turn
        if session_data and session_node:
            is_active = session_id == self._state.get_current_session_id()
            session_node.label = self._make_session_label(session_data, is_active)

        # Always update token counts when a turn starts
        self._update_root_label()

    def _finalize_turn_node(self, session_id: str, turn_idx: int, content: str, content_blocks: list) -> None:
        """Finalize a streaming turn node with final content.

        Called via observer when TreeState.finish_turn() is called.
        """
        turn_data = self._state.get_turn(session_id, turn_idx)
        turn_node = self._turn_nodes.get((session_id, turn_idx))

        # Update tree node if available
        if turn_data and turn_node:
            # Clear existing children and rebuild
            turn_node.remove_children()
            self._add_content_block_nodes(turn_node, session_id, turn_idx, content_blocks)

            # Update label with final content
            mode = self._state.get_context_mode(session_id, turn_idx)
            turn_node.label = self._make_turn_label(
                turn_data.role, content, mode, content_blocks, session_id=session_id
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

    def load_all_sessions(self, current_session: Session) -> None:
        """Load all sessions into the tree.

        Uses lazy loading: only metadata is loaded initially.
        Full session data (turns) is loaded when a session is expanded or activated.
        The current session is always fully loaded.
        """
        # Get all session metadata (lightweight - no message content)
        all_session_metadata = Session.list_sessions()

        tree = self.query_one("#turn-tree", SelectableTreeWidget)
        tree.root.remove_children()
        self._session_nodes.clear()
        self._turn_nodes.clear()
        self._exchange_nodes.clear()

        # Clear TreeState (which now owns session data, context modes, and merge modes)
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
        self._rebuild_tree_with_sort()

    def _make_session_label_from_session_data(self, session_data: SessionData, is_active: bool) -> str:
        """Create a label for a session node from SessionData."""
        try:
            dt = datetime.fromisoformat(session_data.created)
            date_str = dt.strftime("%b %d %H:%M")
        except:
            date_str = session_data.created[:16] if session_data.created else ""

        msg_count = session_data.message_count
        session_id = session_data.id

        # Calculate token count - use stored total if available, else calculate from loaded data
        if session_data.is_loaded:
            session_tokens = self._calculate_session_tokens(session_id)
        else:
            # Use stored token count from session data
            session_tokens = session_data.total_input_tokens + session_data.total_output_tokens

        # Show fork status indicator
        is_fork = session_data.parent_id is not None
        fork_status = session_data.fork_status
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

        # Animated streaming indicator
        is_streaming = self._state.is_streaming(session_id)
        if is_streaming:
            spinner = self._spinner_chars[self._spinner_frame]
            streaming_indicator = f"[yellow]{spinner}[/] "
        else:
            streaming_indicator = ""

        # Model icon for visual differentiation
        model_icon = get_model_icon(session_data.model, session_data.backend_name)
        model_indicator = f"{model_icon} " if model_icon else ""

        # Build label: fork name or title (if present), session ID prefix, msg count, tokens, datetime
        fork_name = session_data.fork_name
        title = session_data.title
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
            label = f"{model_indicator}{id_prefix}{name_part} [dim]({msg_count}msg {token_str})[/] {status}"
        else:
            label = f"{model_indicator}{id_prefix}{date_str} [dim]({msg_count}msg {token_str})[/] {status}"

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
                message_count=len(session.messages),
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

    def _calculate_session_tokens(self, session_id: str) -> int:
        """Calculate total tokens for a specific session."""
        session_data = self._state.get_session(session_id)
        if not session_data or not session_data.turns:
            return 0

        total = 0
        for turn in session_data.turns:
            content = f"{'User' if turn.role == 'user' else 'Assistant'}: {turn.content}"
            total += count_tokens(content)
        return total

    def _load_full_session(self, session_id: str, session: Session = None) -> bool:
        """Fully load a session's messages and turns.

        Args:
            session_id: The session to load
            session: Optional pre-loaded Session object (avoids re-loading from disk)

        Returns True if loaded successfully, False if session not found.
        """
        if self._state.is_session_loaded(session_id):
            return True  # Already loaded

        if session is None:
            session = Session.load(session_id)
            if not session:
                return False

        # Load into TreeState (which manages session data, turns, context modes, and merge modes)
        self._state.load_session(session_id, session)

        return True

    def _is_session_loaded(self, session_id: str) -> bool:
        """Check if a session's full data has been loaded."""
        return self._state.is_session_loaded(session_id)

    def _activate_session(self, session_id: str) -> None:
        """Activate a session - load it if needed and post SessionActivated."""
        # Ensure session is loaded
        if not self._is_session_loaded(session_id):
            if not self._load_full_session(session_id):
                return  # Session not found

        session_data = self._state.get_session(session_id)
        if session_data and session_data.session_ref:
            self.post_message(self.SessionActivated(session_data.session_ref))

    def _add_fork_node(self, parent_node, parent_session_id: str, fork: dict, tree: SelectableTreeWidget) -> None:
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

        # Get context mode for this merge from TreeState
        mode = self._state.get_merge_mode(parent_session_id, fork_id)

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

    def _add_turns_to_node(
        self,
        session_node,
        session_id: str,
        turns: list,
    ) -> None:
        """Add turn nodes to a session node, grouped by exchange_id.

        Turns with the same exchange_id are nested under an exchange group node.
        Single-turn groups (or turns without exchange_id) are added directly.
        """
        groups = self._state.get_turns_grouped_by_exchange(session_id)

        for group in groups:
            if len(group) == 1:
                # Single turn - add directly to session
                turn = group[0]
                self._add_single_turn_node(session_node, session_id, turn)
            else:
                # Multi-turn exchange - create a group node
                exchange_id = group[0].exchange_id
                first_turn = group[0]
                turn_indices = [turn.idx for turn in group]

                # Create exchange label from first turn's role/content with mode indicator
                exchange_label = self._make_exchange_label(session_id, first_turn, len(group), turn_indices)

                exchange_node = session_node.add(
                    exchange_label,
                    data={
                        "type": "exchange",
                        "session_id": session_id,
                        "exchange_id": exchange_id,
                        "first_turn_idx": first_turn.idx,
                        "turn_indices": turn_indices,
                    }
                )
                self._exchange_nodes[(session_id, exchange_id)] = exchange_node

                # Add turns as children of the exchange node
                for turn in group:
                    self._add_single_turn_node(exchange_node, session_id, turn)

    def _add_single_turn_node(
        self,
        parent_node,
        session_id: str,
        turn,
    ) -> None:
        """Add a single turn node to a parent (session or exchange group)."""
        mode = self._state.get_context_mode(session_id, turn.idx)
        label = self._make_turn_label(turn.role, turn.content, mode, turn.content_blocks, session_id=session_id)
        turn_node = parent_node.add(
            label,
            data={"type": "turn", "session_id": session_id, "turn_idx": turn.idx}
        )
        self._turn_nodes[(session_id, turn.idx)] = turn_node

        # Add tool use blocks as children
        self._add_content_block_nodes(turn_node, session_id, turn.idx, turn.content_blocks)

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
            elif isinstance(block, InterruptionBlock):
                if block.reason == "user_cancelled":
                    label = "[red]⚠ Interrupted by user[/]"
                elif block.reason == "timeout":
                    label = "[red]⚠ Timed out[/]"
                else:
                    label = f"[red]⚠ Interrupted: {block.reason}[/]"
                turn_node.add(
                    label,
                    data={
                        "type": "interruption",
                        "session_id": session_id,
                        "turn_idx": turn_idx,
                        "block_idx": block_idx,
                        "reason": block.reason,
                    }
                )
            elif isinstance(block, ErrorBlock):
                if block.reason == "truncated" and block.partial_tool_name:
                    label = f"[yellow]⚠ Truncated during {block.partial_tool_name}[/]"
                elif block.reason == "truncated":
                    label = "[yellow]⚠ Truncated[/]"
                elif block.reason == "json_decode_error":
                    label = "[yellow]⚠ Parse error[/]"
                else:
                    label = f"[yellow]⚠ Error: {block.reason}[/]"
                if block.dump_file:
                    label += f" [dim](dump: {block.dump_file})[/]"
                turn_node.add(
                    label,
                    data={
                        "type": "error",
                        "session_id": session_id,
                        "turn_idx": turn_idx,
                        "block_idx": block_idx,
                        "reason": block.reason,
                        "partial_tool_name": block.partial_tool_name,
                        "details": block.details,
                        "dump_file": block.dump_file,
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

    def _get_exchange_aggregate_mode(self, session_id: str, turn_indices: list[int]) -> ContextMode | None:
        """Get aggregate mode for exchange group if all turns share the same mode.

        Returns:
            The shared ContextMode if all turns have the same mode, None if mixed.
        """
        if not turn_indices:
            return None

        modes = [self._state.get_context_mode(session_id, idx) for idx in turn_indices]
        first_mode = modes[0]

        # Normalize SUMMARIZE to COMPRESS for comparison
        def normalize(m):
            return ContextMode.COMPRESS if m == ContextMode.SUMMARIZE else m

        if all(normalize(m) == normalize(first_mode) for m in modes):
            return first_mode
        return None

    def _make_exchange_label(self, session_id: str, first_turn, group_size: int, turn_indices: list[int]) -> str:
        """Create label for an exchange group node with aggregate mode indicator."""
        # Check if all turns in the exchange have the same mode
        aggregate_mode = self._get_exchange_aggregate_mode(session_id, turn_indices)

        if aggregate_mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif aggregate_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            indicator = "[yellow]Σ[/]"
        elif aggregate_mode == ContextMode.DROP:
            indicator = "☐"
        else:
            # Mixed modes - show a distinct indicator
            indicator = "[dim]◐[/]"

        user_content = first_turn.content if first_turn.role == "user" else ""
        preview = user_content[:25] + "..." if len(user_content) > 25 else user_content
        preview = preview.replace("\n", " ")
        return f"{indicator} [dim]⟨{group_size}⟩[/] {preview or 'Exchange'}"

    def _update_exchange_label(self, session_id: str, exchange_id: str) -> None:
        """Update exchange node label to reflect current aggregate mode."""
        exchange_node = self._exchange_nodes.get((session_id, exchange_id))
        if not exchange_node:
            return

        node_data = exchange_node.data
        if not node_data:
            return

        turn_indices = node_data.get("turn_indices", [])
        first_turn_idx = node_data.get("first_turn_idx")

        # Get the first turn data from TreeState
        first_turn = self._state.get_turn(session_id, first_turn_idx)
        if not first_turn:
            return

        new_label = self._make_exchange_label(session_id, first_turn, len(turn_indices), turn_indices)
        exchange_node.set_label(new_label)

    def _update_root_label(self) -> None:
        """Update root label with selected context tokens for current session."""
        tree = self.query_one("#turn-tree", SelectableTreeWidget)

        selected_tokens = 0
        current_session_tokens = 0
        current_session_turn_ids = []
        # Build turn_modes dict for current session (1-indexed turn_id -> mode name)
        turn_modes: dict[int, str] = {}

        current_session_id = self._state.get_current_session_id()

        # Only count tokens for the current session's context
        if current_session_id:
            session_data = self._state.get_session(current_session_id)
            if session_data and session_data.is_loaded and session_data.turns:
                for turn in session_data.turns:
                    content = f"{'User' if turn.role == 'user' else 'Assistant'}: {turn.content}"
                    tokens = count_tokens(content)
                    current_session_tokens += tokens
                    mode = self._state.get_context_mode(current_session_id, turn.idx)
                    if mode != ContextMode.DROP:
                        selected_tokens += tokens
                        current_session_turn_ids.append(turn.idx + 1)

                    # Build turn_modes for current session
                    turn_id = turn.idx + 1  # 1-indexed
                    turn_modes[turn_id] = mode.name

                # Count merge summaries for current session
                if session_data.session_ref:
                    session = session_data.session_ref
                    for child in session.children:
                        if child.get("status") == "merged":
                            fork_id = child.get("session_id", "")
                            # Load fork to get merge message
                            fork_session = Session.load(fork_id)
                            if fork_session and fork_session.merge_message:
                                merge_tokens = count_tokens(fork_session.merge_message)
                                current_session_tokens += merge_tokens
                                mode = self._state.get_merge_mode(current_session_id, fork_id)
                                if mode != ContextMode.DROP:
                                    selected_tokens += merge_tokens

        included_count = sum(
            1 for m in self._state.get_context_modes_for_session(current_session_id).values()
            if m != ContextMode.DROP
        ) if current_session_id else 0
        # TODO: Add merge mode counting via TreeState when API is available

        # Root label shows context selection for current session
        tree.root.label = f"[bold]Context:[/] {selected_tokens:,} / {current_session_tokens:,} [dim]tokens[/]"

        self.post_message(self.SelectionChanged(
            included_count, current_session_tokens, selected_tokens, current_session_turn_ids, turn_modes
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
                turn_data.role, turn_data.content, mode, turn_data.content_blocks, session_id=session_id
            )

    def _update_merge_label(self, parent_session_id: str, fork_id: str, node_data: dict) -> None:
        """Update a merge node's mode indicator label."""
        # Find the merge node in the tree by walking children
        session_node = self._session_nodes.get(parent_session_id)
        if not session_node:
            return

        mode = self._state.get_merge_mode(parent_session_id, fork_id)

        # Find the node in the session's children
        for node in session_node.children:
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

    def add_turn_to_current(self, role: str, content: str, raw_events: list[dict], content_blocks: list = None) -> None:
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

        label = self._make_turn_label(role, content, ContextMode.COMPRESS, content_blocks, session_id=current_session_id)
        if session_node:
            turn_node = session_node.add(
                label,
                data={"type": "turn", "session_id": current_session_id, "turn_idx": idx}
            )
            self._turn_nodes[(current_session_id, idx)] = turn_node

            # Add child nodes for tool uses and results
            if content_blocks:
                self._add_content_block_nodes(turn_node, current_session_id, idx, content_blocks)
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
        """
        session_data = self._state.get_session(session_id)
        if not session_data:
            return False

        # Remove the tree node
        session_node = self._session_nodes.get(session_id)
        if session_node:
            session_node.remove()
            del self._session_nodes[session_id]

        # Clean up turn nodes for this session
        keys_to_remove = [k for k in self._turn_nodes if k[0] == session_id]
        for key in keys_to_remove:
            del self._turn_nodes[key]

        # Remove from TreeState (handles context modes and merge modes cleanup)
        self._state.remove_session(session_id)

        self._update_root_label()
        return True

    # --- Streaming-aware methods for incremental tree updates ---

    def start_turn(self, session_id: str, turn_idx: int, role: str, exchange_id: str = None) -> None:
        """Start a new turn node when streaming begins.

        Called when a 'turn_started' event is received from SessionRunner.
        Notifies TreeState which will fire TURN_STARTED event.
        The observer callback (_add_streaming_turn_node) handles UI updates.

        Args:
            session_id: The session this turn belongs to
            turn_idx: The index of this turn in the session
            role: "user" or "assistant"
            exchange_id: Optional ID to group turns in an agentic exchange
        """
        # Notify TreeState - it will set context mode and fire TURN_STARTED event
        # The observer callback will create the UI node
        self._state.start_turn(session_id, turn_idx, role, exchange_id=exchange_id)

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
        turn_data = self._state.get_turn(session_id, turn_idx)
        turn_node = self._turn_nodes.get((session_id, turn_idx))
        if not turn_data or not turn_node:
            return

        import json
        input_preview = json.dumps(tool_input)[:50]
        if len(json.dumps(tool_input)) > 50:
            input_preview += "..."
        label = f"[cyan]🔧 {tool_name}[/] {input_preview}"

        tool_key = (session_id, turn_idx, tool_use_id)

        # Check if node already exists (from tool_use_start) - update instead of creating
        if tool_key in self._tool_use_nodes:
            existing_node = self._tool_use_nodes[tool_key]
            existing_node.label = label
            existing_node.data["tool_input"] = tool_input
            return

        tool_node = turn_node.add(
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
        self._tool_use_nodes[tool_key] = tool_node

        # Update turn label to show tool count
        tool_count = sum(1 for k in self._tool_use_nodes if k[0] == session_id and k[1] == turn_idx)
        icon = "👤" if turn_data.role == "user" else "🤖"
        mode = self._state.get_context_mode(session_id, turn_idx)
        if mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            indicator = "[yellow]Σ[/]"
        else:
            indicator = "☐"
        turn_node.label = f"{indicator} {icon} [cyan]🔧{tool_count}[/] [dim]streaming...[/]"

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
        tool_key = (session_id, turn_idx, tool_use_id)
        node = self._tool_use_nodes.get(tool_key)
        if not node:
            return

        # Initialize streaming parser if needed
        if "_json_parser" not in node.data:
            node.data["_json_parser"] = StreamingJsonParser()
            node.data["_streaming_input"] = ""

        # Feed the delta to the parser and accumulate raw input
        node.data["_json_parser"].feed(partial_json)
        node.data["_streaming_input"] += partial_json

        # Try to get a meaningful preview from parsed data
        parsed = node.data["_json_parser"].get_partial()
        if parsed and isinstance(parsed, dict):
            # Show key fields in a compact format
            preview = self._format_tool_preview(tool_name, parsed)
        else:
            # Fallback to raw JSON preview
            accumulated = node.data["_streaming_input"]
            preview = accumulated[:50]
            if len(accumulated) > 50:
                preview += "..."

        node.label = f"[cyan]🔧 {tool_name}[/] [dim]{preview}[/]"

    def _format_tool_preview(self, tool_name: str, parsed: dict) -> str:
        """Format a tool input preview based on the tool type."""
        # Common fields to look for, in order of preference
        if tool_name in ("Read", "read_file"):
            if "file_path" in parsed:
                return parsed["file_path"]
        elif tool_name in ("Edit", "edit_file", "Write", "write_file"):
            if "file_path" in parsed:
                return parsed["file_path"]
        elif tool_name in ("Bash", "bash", "execute"):
            if "command" in parsed:
                cmd = parsed["command"]
                if len(cmd) > 50:
                    cmd = cmd[:47] + "..."
                return cmd
        elif tool_name in ("Grep", "grep", "search"):
            if "pattern" in parsed:
                return f"/{parsed['pattern']}/"
        elif tool_name in ("Glob", "glob"):
            if "pattern" in parsed:
                return parsed["pattern"]

        # Generic fallback: show first string value
        for key, value in parsed.items():
            if isinstance(value, str) and value:
                display = value[:40] if len(value) <= 40 else value[:37] + "..."
                return f"{key}={display}"

        return str(parsed)[:50]

    def update_streaming_text(
        self,
        session_id: str,
        turn_idx: int,
        text_delta: str,
    ) -> None:
        """Update turn node to reflect streaming text content.

        Called when 'text_delta' events arrive.
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

        # Update turn label with text preview
        text = self._streaming_text[text_key]
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

        # Show tool count if any
        tool_count = sum(1 for k in self._tool_use_nodes if k[0] == session_id and k[1] == turn_idx)
        if tool_count > 0:
            turn_node.label = f"{indicator} {icon} [cyan]🔧{tool_count}[/] [dim]{preview}[/]"
        else:
            turn_node.label = f"{indicator} {icon} [dim]{preview}[/]"

    def flush_streaming_text(
        self,
        session_id: str,
        turn_idx: int,
        text: str,
    ) -> None:
        """Commit accumulated streaming text as a visible text node.

        Called when a text segment completes (before tool use starts).
        Creates a text child node and clears the streaming accumulator.
        """
        turn_node = self._turn_nodes.get((session_id, turn_idx))
        if not turn_node or not text.strip():
            return

        # Create text node as child of turn
        text_preview = text[:50].replace("\n", " ")
        if len(text) > 50:
            text_preview += "..."
        label = f"[dim]💬[/] {text_preview}"

        # Track how many text nodes we've added for this turn
        text_key = (session_id, turn_idx)
        text_node_count = sum(
            1 for child in turn_node.children
            if child.data and child.data.get("type") == "text"
        )

        turn_node.add(
            label,
            data={
                "type": "text",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "block_idx": text_node_count,  # Index among text blocks
                "text": text,
            }
        )

        # Clear streaming accumulator - subsequent text will be a new segment
        if text_key in self._streaming_text:
            del self._streaming_text[text_key]

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
        turn_node = self._turn_nodes.get((session_id, turn_idx))
        if not turn_node:
            return

        content_preview = str(result)[:50]
        if len(str(result)) > 50:
            content_preview += "..."
        error_indicator = "[red]❌[/] " if is_error else ""
        label = f"{error_indicator}[blue]📋 Result[/] {content_preview}"

        # Find parent tool use node, or fall back to turn node
        tool_key = (session_id, turn_idx, tool_use_id)
        parent_node = self._tool_use_nodes.get(tool_key, turn_node)
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
        Notifies TreeState which will fire TURN_FINISHED event.
        The observer callback (_finalize_turn_node) handles UI updates.
        """
        # Notify TreeState - the observer will handle UI update
        self._state.finish_turn(session_id, turn_idx, content, content_blocks, raw_events)

        # Clean up streaming tracking state for this turn
        text_key = (session_id, turn_idx)
        if text_key in self._streaming_text:
            del self._streaming_text[text_key]

        # Clean up tool use nodes for this turn
        keys_to_remove = [k for k in self._tool_use_nodes if k[0] == session_id and k[1] == turn_idx]
        for key in keys_to_remove:
            del self._tool_use_nodes[key]

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
        session_data = self._state.get_session(session_id)
        if not session_data or not session_data.is_loaded or not session_data.turns:
            return

        tree = self.query_one("#turn-tree", SelectableTreeWidget)

        # Add turn nodes grouped by exchange_id
        self._add_turns_to_node(session_node, session_id, session_data.turns)

        # Add fork and merge nodes from session_ref
        session = session_data.session_ref
        if session:
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
            # Show fork info in preview pane - don't activate
            session_id = node_data.get("session_id")
            session_data = self._state.get_session(session_id)
            if session_data:
                self.post_message(self.TurnInspected({
                    "type": "session_preview",
                    "session_id": session_id,
                    "title": session_data.title or node_data.get("fork_name", ""),
                    "created": session_data.created,
                    "message_count": session_data.message_count,
                    "model": session_data.model,
                    "is_fork": True,
                    "status": node_data.get("status", "active"),
                }))
        elif node_type == "exchange":
            # Exchange group selected - scroll to first turn in the group
            session_id = node_data.get("session_id")
            first_turn_idx = node_data.get("first_turn_idx")
            session_data = self._state.get_session(session_id)
            if session_data and session_data.is_loaded and first_turn_idx is not None:
                turn = self._state.get_turn(session_id, first_turn_idx)
                if turn:
                    mode = self._state.get_context_mode(session_id, first_turn_idx)
                    self.post_message(self.TurnInspected({
                        "type": "turn",
                        "role": turn.role,
                        "content": turn.content,
                        "events": turn.events,
                        "turn_idx": first_turn_idx,
                        "context_mode": mode.name,
                        "exchange_id": node_data.get("exchange_id"),
                    }, session_id=session_id))
        elif node_type == "merge":
            # Show merge details in inspection pane
            fork_id = node_data.get("session_id")
            parent_session_id = node_data.get("parent_session_id")
            fork_name = node_data.get("fork_name", "")
            merge_message = node_data.get("message", "")
            mode = self._state.get_merge_mode(parent_session_id, fork_id)
            self.post_message(self.TurnInspected({
                "type": "merge",
                "session_id": fork_id,
                "parent_session_id": parent_session_id,
                "fork_name": fork_name,
                "message": merge_message,
                "context_mode": mode.name,
            }, session_id=parent_session_id))

    def on_selectable_tree_widget_activate_requested(self, event: SelectableTreeWidget.ActivateRequested) -> None:
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

            self._update_turn_label(session_id, turn_idx)

            # Update parent exchange label if this turn is in an exchange
            turn_data = self._state.get_turn(session_id, turn_idx)
            if turn_data and turn_data.exchange_id:
                self._update_exchange_label(session_id, turn_data.exchange_id)

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

            # Update parent exchange label if this turn is in an exchange
            turn_data = self._state.get_turn(session_id, turn_idx)
            if turn_data and turn_data.exchange_id:
                self._update_exchange_label(session_id, turn_data.exchange_id)

            self._update_root_label()
            # Notify app to persist the change
            self.post_message(self.ContextModeChanged(session_id, turn_idx, new_mode))

        elif node_type == "exchange":
            session_id = event.node_data.get("session_id")
            exchange_id = event.node_data.get("exchange_id")
            turn_indices = event.node_data.get("turn_indices", [])

            if not turn_indices:
                return

            # Determine next mode based on aggregate mode of the group
            aggregate_mode = self._get_exchange_aggregate_mode(session_id, turn_indices)

            if aggregate_mode == ContextMode.COPY:
                new_mode = ContextMode.COMPRESS
            elif aggregate_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
                new_mode = ContextMode.DROP
            elif aggregate_mode == ContextMode.DROP:
                new_mode = ContextMode.COPY
            else:
                # Mixed modes - cycle to COPY to make them uniform
                new_mode = ContextMode.COPY

            # Set all turns in the exchange to the new mode
            for turn_idx in turn_indices:
                self._state.set_context_mode(session_id, turn_idx, new_mode)
                self._update_turn_label(session_id, turn_idx)
                # Notify app to persist each change
                self.post_message(self.ContextModeChanged(session_id, turn_idx, new_mode))

            self._update_exchange_label(session_id, exchange_id)
            self._update_root_label()

        elif node_type == "merge":
            fork_id = event.node_data.get("session_id")
            parent_session_id = event.node_data.get("parent_session_id")

            # Get current mode and cycle
            current_mode = self._state.get_merge_mode(parent_session_id, fork_id)
            if current_mode == ContextMode.COPY:
                new_mode = ContextMode.COMPRESS
            elif current_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
                new_mode = ContextMode.DROP
            else:  # DROP
                new_mode = ContextMode.COPY

            # Update TreeState (which fires CONTEXT_MODE_CHANGED event)
            self._state.set_merge_mode(parent_session_id, fork_id, new_mode)

            self._update_merge_label(parent_session_id, fork_id, event.node_data)
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
        # Update all exchange labels for this session
        for (session_id, exchange_id), node in self._exchange_nodes.items():
            if session_id == current_session_id:
                self._update_exchange_label(session_id, exchange_id)
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
        # Update all exchange labels for this session
        for (session_id, exchange_id), node in self._exchange_nodes.items():
            if session_id == current_session_id:
                self._update_exchange_label(session_id, exchange_id)
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

    def on_selectable_tree_widget_link_requested(self, event: SelectableTreeWidget.LinkRequested) -> None:
        """Handle ctrl+click link request - bubble up to app."""
        self.post_message(self.SessionLinkRequested(event.session_id))

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
        all_sessions = self._state.get_all_sessions()
        if not all_sessions:
            return

        tree = self.query_one("#turn-tree", SelectableTreeWidget)
        tree.root.remove_children()
        self._session_nodes.clear()
        self._turn_nodes.clear()
        self._exchange_nodes.clear()

        # Get session data sorted according to current order
        sorted_session_ids = self._get_sorted_session_ids()

        # Determine which sessions to expand (and thus need to be loaded):
        # - Always expand current session
        # - Also expand parent session if current is a fork
        current_session_id = self._state.get_current_session_id()
        sessions_to_expand = {current_session_id}
        if current_session_id:
            current_data = self._state.get_session(current_session_id)
            if current_data and current_data.parent_id:
                sessions_to_expand.add(current_data.parent_id)
                # Ensure parent is loaded too
                if not self._is_session_loaded(current_data.parent_id):
                    self._load_full_session(current_data.parent_id)

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

                # Rebuild turn nodes grouped by exchange_id
                self._add_turns_to_node(session_node, session_id, session_data.turns)

                # Rebuild fork and merge nodes from session_ref if available
                if session_data.session_ref:
                    session = session_data.session_ref
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
        for session_id, session_data in self._state.get_all_sessions().items():
            title = session_data.title or ""
            session_items.append({
                "id": session_id,
                "created": session_data.created,
                "last_modified": session_data.last_modified,
                "title": title.lower() if title else "",
                "messages": session_data.message_count,
                "tokens": session_data.total_input_tokens + session_data.total_output_tokens,
                "cost": session_data.total_cost,
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
        self._exchange_nodes.clear()

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
        sorted_session_ids = self._get_sorted_session_ids()

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
                    label = self._make_turn_label(turn.role, turn.content, mode, turn.content_blocks, session_id=session_id)
                    turn_node = session_node.add(
                        label,
                        data={"type": "turn", "session_id": session_id, "turn_idx": turn.idx}
                    )
                    self._turn_nodes[(session_id, turn.idx)] = turn_node

                    # Add content block children
                    self._add_content_block_nodes(turn_node, session_id, turn.idx, turn.content_blocks)

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

        # Check tool names
        for block in turn.content_blocks:
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
        current_session_id = self._state.get_current_session_id()
        if not current_session_id:
            return results

        # Use TreeState for turns (authoritative source during streaming)
        session_data = self._state.get_session(current_session_id)
        if not session_data or not session_data.is_loaded or session_data.turns is None:
            return results

        # Get session object for original message data (content_blocks, summary)
        session = session_data.session_ref
        if not session:
            return results

        included_items = []  # Will hold both turns and merge markers

        # Collect turns from TreeState (includes streaming turns)
        for turn in session_data.turns:
            mode = self._state.get_context_mode(current_session_id, turn.idx)
            if mode != ContextMode.DROP:
                # Get original message from session if available
                orig_msg = None
                if turn.idx < len(session.messages):
                    orig_msg = session.messages[turn.idx]

                included_items.append({
                    "type": "turn",
                    "session_created": session.created,
                    "sort_key": turn.idx,  # Integer for turns
                    "turn_idx": turn.idx,
                    "role": turn.role,
                    "content": turn.content,
                    "content_blocks": turn.content_blocks,  # Use TreeState's content_blocks
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

            mode = self._state.get_merge_mode(session.id, fork_id)
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
            elif item.get("content_blocks"):
                # Use content_blocks from TreeState (for streaming turns not yet saved)
                msg = Message(
                    role=item["role"],
                    content=item["content"],
                    content_blocks=item["content_blocks"],
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
        old_session_id = self._state.get_current_session_id()

        # Update TreeState - this fires SESSION_SELECTED event
        self._state.set_current_session(session_id)

        # Update old session's label via node reference
        if old_session_id:
            old_node = self._session_nodes.get(old_session_id)
            old_data = self._state.get_session(old_session_id)
            if old_node and old_data:
                old_node.label = self._make_session_label_from_session_data(old_data, False)

        # Update new session's label via node reference and set context modes
        session_data = self._state.get_session(session_id)
        if session_data:
            new_node = self._session_nodes.get(session_id)
            if new_node:
                new_node.label = self._make_session_label_from_session_data(session_data, True)

            # Set context modes for new session's turns to COPY if not already set
            # This ensures turns are included when forking
            if session_data.turns:
                for turn in session_data.turns:
                    current_mode = self._state.get_context_mode(session_id, turn.idx)
                    if current_mode == ContextMode.DROP:
                        self._state.set_context_mode(session_id, turn.idx, ContextMode.COPY)
                        self._update_turn_label(session_id, turn.idx)

    def create_new_session(self) -> Session:
        """Create a new session and make it current."""
        new_session = Session()

        tree = self.query_one("#turn-tree", SelectableTreeWidget)

        # Update old active session's highlighting
        old_session_id = self._state.get_current_session_id()
        if old_session_id:
            old_node = self._session_nodes.get(old_session_id)
            old_data = self._state.get_session(old_session_id)
            if old_node and old_data:
                old_node.label = self._make_session_label_from_session_data(old_data, False)

        # Add to TreeState (sets as current)
        self._state.add_session(new_session, is_current=True)

        # Add new session node to tree (will be highlighted as active)
        session_label = self._make_session_label(new_session, True)
        session_node = tree.root.add(
            session_label,
            data={"type": "session", "session_id": new_session.id}
        )
        session_node.expand()
        self._session_nodes[new_session.id] = session_node

        # Load the session into TreeState (creates empty turns list)
        self._state.load_session(new_session.id, new_session)

        self._update_root_label()
        return new_session

    def clear(self) -> None:
        """Clear all data."""
        tree = self.query_one("#turn-tree", SelectableTreeWidget)
        tree.root.remove_children()
        self._session_nodes.clear()
        self._turn_nodes.clear()
        self._exchange_nodes.clear()
        self._tool_use_nodes.clear()
        self._streaming_text.clear()
        self._state.clear()
        self._update_root_label()
