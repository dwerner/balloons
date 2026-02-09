"""
TreeState - Framework-agnostic shared state layer for tree views.

Architecture Overview
=====================

This module implements the Model in an MVC architecture where multiple
tree views (ContextTreeView, NestedTreeView) can observe the same state
and render it independently.

Components:
- TreeState: The central state container (this module)
- TurnData: Canonical turn data model (dataclass in this module)
- SessionData: Session metadata and loaded turn data (dataclass in this module)
- ContextTreeView: View with sorting, search, fork/merge display (widgets/context_tree.py)
- NestedTreeView: View with inline fork nesting (widgets/nested_tree.py)

The TreeState class:
- Holds all session and turn data
- Uses Observer pattern for change notifications
- Has no Textual/UI dependencies - pure Python
- Is unit-testable without UI framework

Data Flow:
1. App loads sessions and calls TreeState.add_session(), load_session()
2. TreeState notifies observers via callbacks
3. Views (ContextTreeView, NestedTreeView) receive events and update UI

Current State (Migration in Progress):
- NestedTreeView: Pure observer, uses TreeState exclusively
- ContextTreeView: Dual-state (has local dicts + TreeState), being migrated
"""

from dataclasses import dataclass, field
from typing import Callable, Any, Protocol
from enum import Enum

from models import (
    ContextMode, ContentBlock, TextBlock, ToolUseBlock, ToolResultBlock,
    InterruptionBlock, ErrorBlock, LinkBlock, ArchiveBlock, ForkBlock, MergeBlock, ReviewBlock
)
from core.context import ContextBuilder

# Module-level context builder for token counting
_context_builder = ContextBuilder()


class SessionProtocol(Protocol):
    """Protocol for Session objects to avoid circular imports."""
    id: str
    created: str
    last_modified: str
    model: str
    title: str
    messages: list
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float
    parent_id: str | None
    children: list[dict]
    fork_name: str
    fork_status: str
    merge_message: str
    backend_name: str


@dataclass
class TurnData:
    """Data for a single turn in a session.

    Each turn has exactly ONE content block (TextBlock, ToolUseBlock, ForkBlock, etc.).
    The block type determines the turn type.
    """
    idx: int
    role: str
    content: str  # Display text extracted from content_block
    content_block: ContentBlock | None = None  # Single content block
    events: list = field(default_factory=list)
    streaming: bool = False
    viewed: bool = True  # Whether user has seen this turn (False for new assistant turns)
    tool_use_ids: list[str] = field(default_factory=list)  # Tool IDs tracked during streaming
    exchange_id: str | None = None  # Groups turns in an agentic loop
    tokens: int = 0  # Estimated token count for this turn


@dataclass
class SessionData:
    """Metadata and optional loaded data for a session."""
    id: str
    created: str
    last_modified: str
    model: str
    title: str
    message_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float
    parent_id: str | None
    children: list[dict]
    fork_name: str
    fork_status: str
    backend_name: str = ""  # Name of backend to use (empty = default)
    cached_context_tokens: int = 0  # Cached token count from compiled context

    # Runtime state
    is_current: bool = False
    is_loaded: bool = False
    is_streaming: bool = False

    # Loaded data (None until session is expanded/activated)
    turns: list[TurnData] | None = None
    session_ref: Any = None  # Reference to original Session object


# Event types for observer notifications
class TreeEvent(Enum):
    """Events that TreeState notifies observers about."""
    SESSION_ADDED = "session_added"
    SESSION_REMOVED = "session_removed"
    SESSION_UPDATED = "session_updated"
    SESSION_SELECTED = "session_selected"
    SESSION_LOADED = "session_loaded"

    TURN_STARTED = "turn_started"
    TURN_UPDATED = "turn_updated"
    TURN_FINISHED = "turn_finished"
    TURN_VIEWED = "turn_viewed"

    TOOL_USE_STARTED = "tool_use_started"
    TOOL_USE_UPDATED = "tool_use_updated"
    TOOL_RESULT_ADDED = "tool_result_added"

    CONTEXT_MODE_CHANGED = "context_mode_changed"
    CONTEXT_TOKENS_CHANGED = "context_tokens_changed"

    STREAMING_STARTED = "streaming_started"
    STREAMING_STOPPED = "streaming_stopped"

    FULL_REBUILD = "full_rebuild"


# Type alias for observer callbacks
ObserverCallback = Callable[[TreeEvent, dict[str, Any]], None]


class TreeState:
    """
    Framework-agnostic state container for session tree data.

    Implements Observer pattern - views register callbacks to be
    notified of state changes. Views are responsible for translating
    state changes into their own UI updates.

    Thread-safety: Not thread-safe. All operations should be called
    from the main UI thread.
    """

    def __init__(self):
        # Session metadata and data
        self._sessions: dict[str, SessionData] = {}

        # Context modes per turn: (session_id, turn_idx) -> ContextMode
        self._context_modes: dict[tuple[str, int], ContextMode] = {}

        # Context modes for merges: (parent_session_id, fork_session_id) -> ContextMode
        self._merge_modes: dict[tuple[str, str], ContextMode] = {}

        # Current active session
        self._current_session_id: str | None = None

        # Sessions currently streaming
        self._streaming_sessions: set[str] = set()

        # Session color assignments for visual distinction
        self._session_colors: dict[str, str] = {}

        # Context token counts (set by app, consumed by views)
        self._selected_context_tokens: int = 0
        self._total_session_tokens: int = 0

        # Observer callbacks
        self._observers: list[ObserverCallback] = []

        # Color palette for sessions
        self._color_palette = [
            "blue", "magenta", "cyan", "green", "yellow", "red"
        ]

    # --- Observer Management ---

    def add_observer(self, callback: ObserverCallback) -> None:
        """Register a callback to be notified of state changes."""
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: ObserverCallback) -> None:
        """Unregister an observer callback."""
        if callback in self._observers:
            self._observers.remove(callback)

    def _notify(self, event: TreeEvent, data: dict[str, Any] = None) -> None:
        """Notify all observers of a state change."""
        data = data or {}
        for callback in self._observers:
            callback(event, data)

    # --- Session Operations ---

    def add_session(self, session: SessionProtocol, is_current: bool = False) -> None:
        """Add or update a session in the state."""
        cached_tokens = session.cached_context_tokens if hasattr(session, 'cached_context_tokens') else 0
        session_data = SessionData(
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
            cached_context_tokens=cached_tokens,
            is_current=is_current,
            session_ref=session,
        )

        is_new = session.id not in self._sessions
        self._sessions[session.id] = session_data

        if is_current:
            self._current_session_id = session.id

        # Assign color if new
        if session.id not in self._session_colors:
            color_idx = len(self._session_colors) % len(self._color_palette)
            self._session_colors[session.id] = self._color_palette[color_idx]

        if is_new:
            self._notify(TreeEvent.SESSION_ADDED, {"session_id": session.id})
        else:
            self._notify(TreeEvent.SESSION_UPDATED, {"session_id": session.id})

    def add_session_from_metadata(self, metadata: dict, is_current: bool = False) -> None:
        """Add a session from metadata dict (for lazy loading).

        Handles both Rust storage format (name, created_at, updated_at, turn_count)
        and legacy format (title, created, last_modified, message_count).
        """
        # Handle Rust storage field name mappings
        # Rust SessionMetadata uses: name, created_at, updated_at, turn_count
        # Python expects: title, created, last_modified, message_count
        title = metadata.get("title") or metadata.get("name", "")
        created = metadata.get("created") or metadata.get("created_at", "")
        last_modified = metadata.get("last_modified") or metadata.get("updated_at", "")
        message_count = metadata.get("message_count") or metadata.get("turn_count", 0)

        # Convert Unix timestamps from Rust to ISO format if needed
        if isinstance(created, (int, float)) and created > 0:
            from datetime import datetime, timezone
            created = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
        if isinstance(last_modified, (int, float)) and last_modified > 0:
            from datetime import datetime, timezone
            last_modified = datetime.fromtimestamp(last_modified, tz=timezone.utc).isoformat()

        session_data = SessionData(
            id=metadata["id"],
            created=created if isinstance(created, str) else "",
            last_modified=last_modified if isinstance(last_modified, str) else "",
            model=metadata.get("model", ""),
            title=title,
            message_count=message_count,
            total_input_tokens=metadata.get("total_input_tokens", 0),
            total_output_tokens=metadata.get("total_output_tokens", 0),
            total_cost=metadata.get("total_cost", 0.0),
            parent_id=metadata.get("parent_id"),
            children=metadata.get("children", []),
            fork_name=metadata.get("fork_name", ""),
            fork_status=metadata.get("fork_status", "active"),
            backend_name=metadata.get("backend_name", ""),
            cached_context_tokens=metadata.get("cached_context_tokens", 0),
            is_current=is_current,
        )

        is_new = metadata["id"] not in self._sessions
        self._sessions[metadata["id"]] = session_data

        if is_current:
            self._current_session_id = metadata["id"]

        # Assign color if new
        if metadata["id"] not in self._session_colors:
            color_idx = len(self._session_colors) % len(self._color_palette)
            self._session_colors[metadata["id"]] = self._color_palette[color_idx]

        if is_new:
            self._notify(TreeEvent.SESSION_ADDED, {"session_id": metadata["id"]})
        else:
            self._notify(TreeEvent.SESSION_UPDATED, {"session_id": metadata["id"]})

    def remove_session(self, session_id: str) -> None:
        """Remove a session from the state."""
        if session_id not in self._sessions:
            return

        del self._sessions[session_id]
        self._streaming_sessions.discard(session_id)

        # Clean up context modes for this session
        keys_to_remove = [k for k in self._context_modes if k[0] == session_id]
        for key in keys_to_remove:
            del self._context_modes[key]

        # Clean up merge modes
        merge_keys_to_remove = [k for k in self._merge_modes if session_id in k]
        for key in merge_keys_to_remove:
            del self._merge_modes[key]

        if self._current_session_id == session_id:
            self._current_session_id = None

        self._notify(TreeEvent.SESSION_REMOVED, {"session_id": session_id})

    def set_current_session(self, session_id: str) -> None:
        """Set the currently active session."""
        if session_id not in self._sessions:
            return

        prev_session_id = self._current_session_id

        # Update is_current flags
        if prev_session_id and prev_session_id in self._sessions:
            self._sessions[prev_session_id].is_current = False

        self._sessions[session_id].is_current = True
        self._current_session_id = session_id

        self._notify(TreeEvent.SESSION_SELECTED, {
            "session_id": session_id,
            "prev_session_id": prev_session_id,
        })

    def get_session(self, session_id: str) -> SessionData | None:
        """Get session data by ID."""
        return self._sessions.get(session_id)

    def get_current_session_id(self) -> str | None:
        """Get the current session ID."""
        return self._current_session_id

    def get_all_sessions(self) -> dict[str, SessionData]:
        """Get all sessions."""
        return self._sessions.copy()

    def get_session_color(self, session_id: str) -> str:
        """Get the color assigned to a session."""
        if session_id not in self._session_colors:
            color_idx = len(self._session_colors) % len(self._color_palette)
            self._session_colors[session_id] = self._color_palette[color_idx]
        return self._session_colors[session_id]

    # --- Session Loading ---

    def load_session(self, session_id: str, session: SessionProtocol) -> None:
        """Fully load a session with its turns.

        Each turn in session.turns has exactly one content_block.
        Maps directly to TurnData without expansion.
        """
        if session_id not in self._sessions:
            self.add_session(session, is_current=session_id == self._current_session_id)

        session_data = self._sessions[session_id]
        session_data.is_loaded = True
        session_data.session_ref = session

        # Direct mapping: one Turn → one TurnData
        turns = []

        for turn_idx, turn in enumerate(session.turns):
            content_block = turn.content_block if hasattr(turn, 'content_block') else None
            exchange_id = turn.exchange_id if hasattr(turn, 'exchange_id') else None
            turn_context_mode = turn.context_mode if hasattr(turn, 'context_mode') and turn.context_mode else None

            # Extract display content from the block
            display_content = self._content_from_block(content_block, turn.content if hasattr(turn, 'content') else "")

            turn_data = TurnData(
                idx=turn_idx,
                role=turn.role,
                content=display_content,
                content_block=content_block,
                exchange_id=exchange_id,
                tokens=_context_builder.count_turn_tokens(turn.role, [content_block] if content_block else []),
            )

            turn_key = (session_id, turn_idx)

            # Initialize context mode from turn or default
            if turn_context_mode:
                self._context_modes[turn_key] = turn_context_mode
            elif session_id == self._current_session_id:
                self._context_modes[turn_key] = ContextMode.COMPRESS

            turns.append(turn_data)

        session_data.turns = turns
        session_data.message_count = len(turns)

        # Update cached token count from freshly calculated turn tokens
        # Only count non-DROPped turns (consistent with finish_turn and set_context_mode)
        # Compare by .value to handle different ContextMode class instances
        session_data.cached_context_tokens = sum(
            t.tokens for t in turns
            if self.get_context_mode(session_id, t.idx).value != ContextMode.DROP.value
        )

        # Load merge modes for merged children
        for child in session.children:
            if child.get("status") == "merged":
                fork_id = child.get("session_id", "")
                merge_key = (session_id, fork_id)
                if merge_key not in self._merge_modes:
                    self._merge_modes[merge_key] = ContextMode.COPY

        self._notify(TreeEvent.SESSION_LOADED, {"session_id": session_id})

    def _content_from_block(self, block: ContentBlock | None, fallback: str) -> str:
        """Extract display content from a content block."""
        if block is None:
            return fallback
        if isinstance(block, TextBlock):
            return block.text or fallback
        elif isinstance(block, ToolUseBlock):
            return f"Tool: {block.name}"
        elif isinstance(block, ToolResultBlock):
            # Truncate long results for display
            result = block.content or ""
            if len(result) > 100:
                result = result[:100] + "..."
            prefix = "Error: " if block.is_error else "Result: "
            return prefix + result
        elif isinstance(block, InterruptionBlock):
            return f"Interrupted: {block.reason}"
        elif isinstance(block, ErrorBlock):
            return f"Error: {block.reason}"
        elif isinstance(block, LinkBlock):
            return f"Link: {block.summary}"
        elif isinstance(block, ArchiveBlock):
            return f"Archive: {block.get_display_summary()}"
        elif isinstance(block, ForkBlock):
            return f"Fork: {block.fork_name}"
        elif isinstance(block, MergeBlock):
            msg_preview = block.message[:50] + "..." if len(block.message) > 50 else block.message
            return f"Merged: {block.fork_name} - {msg_preview}"
        elif isinstance(block, ReviewBlock):
            status = f"[{block.status}]" if block.status != "active" else ""
            return f"Review: {block.model_under_review} {status}"
        return fallback

    def is_session_loaded(self, session_id: str) -> bool:
        """Check if a session's full data has been loaded."""
        session_data = self._sessions.get(session_id)
        return session_data.is_loaded if session_data else False

    # --- Turn Operations ---

    def start_turn(
        self,
        session_id: str,
        turn_idx: int,
        role: str,
        exchange_id: str | None = None,
        turn_type: str = "text",
        tool_name: str = "",
        tool_use_id: str = "",
        result_preview: str = "",
    ) -> None:
        """Start a new turn when streaming begins.

        Args:
            session_id: The session this turn belongs to
            turn_idx: The index of this turn
            role: "user", "assistant", or "tool"
            exchange_id: Optional ID to group turns in an agentic exchange
            turn_type: "text", "tool_use", or "tool_result" - used to create
                       a skeleton content_block for proper labeling during streaming
            tool_name: For tool_use turns, the name of the tool being called
            tool_use_id: For tool_use/tool_result turns, the tool use ID
            result_preview: For tool_result turns, a preview of the result
        """
        session_data = self._sessions.get(session_id)
        if not session_data or session_data.turns is None:
            return

        turn_key = (session_id, turn_idx)
        self._context_modes[turn_key] = ContextMode.COMPRESS

        # Assistant turns start as unviewed until user sees them
        is_viewed = role != "assistant"

        # Create a skeleton content_block for tool turns so labels display correctly
        # during streaming (before finish_turn sets the real content_block)
        content_block = None
        content = ""
        if turn_type == "tool_use" and tool_name:
            from models import ToolUseBlock
            content_block = ToolUseBlock(id=tool_use_id, name=tool_name, input={})
            content = tool_name
        elif turn_type == "tool_result":
            from models import ToolResultBlock
            content_block = ToolResultBlock(
                tool_use_id=tool_use_id,
                content=result_preview,
                is_error=False,
            )
            content = result_preview

        # Check if a turn with this index already exists
        existing_turn = None
        for t in session_data.turns:
            if t.idx == turn_idx:
                existing_turn = t
                break

        if existing_turn:
            # Update existing turn instead of creating duplicate
            existing_turn.role = role
            existing_turn.content = content
            existing_turn.content_block = content_block
            existing_turn.streaming = True
            existing_turn.viewed = is_viewed
            existing_turn.exchange_id = exchange_id
            turn = existing_turn
        else:
            turn = TurnData(
                idx=turn_idx,
                role=role,
                content=content,
                content_block=content_block,
                streaming=True,
                viewed=is_viewed,
                exchange_id=exchange_id,
            )
            session_data.turns.append(turn)
            session_data.message_count += 1

        self._notify(TreeEvent.TURN_STARTED, {
            "session_id": session_id,
            "turn_idx": turn_idx,
            "role": role,
            "exchange_id": exchange_id,
        })

    def update_turn_content(self, session_id: str, turn_idx: int, content: str) -> None:
        """Update turn content during streaming."""
        session_data = self._sessions.get(session_id)
        if not session_data or session_data.turns is None:
            return

        for turn in session_data.turns:
            if turn.idx == turn_idx:
                turn.content = content
                self._notify(TreeEvent.TURN_UPDATED, {
                    "session_id": session_id,
                    "turn_idx": turn_idx,
                })
                break

    def finish_turn(
        self,
        session_id: str,
        turn_idx: int,
        content: str,
        content_block: ContentBlock | None,
        events: list[dict] = None,
    ) -> None:
        """Finalize a streaming turn when complete."""
        session_data = self._sessions.get(session_id)
        if not session_data or session_data.turns is None:
            return

        for turn in session_data.turns:
            if turn.idx == turn_idx:
                turn.content = content
                turn.content_block = content_block
                turn.events = events or []
                turn.streaming = False
                turn.tokens = _context_builder.count_turn_tokens(turn.role, [content_block] if content_block else [])

                # Incremental update: add this turn's tokens if not DROP
                # (O(1) instead of O(N) sum over all turns)
                # Compare by .value to handle different ContextMode class instances
                if self.get_context_mode(session_id, turn_idx).value != ContextMode.DROP.value:
                    session_data.cached_context_tokens += turn.tokens

                self._notify(TreeEvent.TURN_FINISHED, {
                    "session_id": session_id,
                    "turn_idx": turn_idx,
                    "content": content,
                    "content_block": content_block,
                })
                break

    def get_turn(self, session_id: str, turn_idx: int) -> TurnData | None:
        """Get a specific turn."""
        session_data = self._sessions.get(session_id)
        if not session_data or session_data.turns is None:
            return None

        for turn in session_data.turns:
            if turn.idx == turn_idx:
                return turn
        return None

    def get_turns_grouped_by_exchange(self, session_id: str) -> list[list[TurnData]]:
        """Get turns grouped by exchange_id.

        Returns a list of groups, where each group is a list of TurnData
        sharing the same exchange_id. Turns without an exchange_id are
        placed in their own single-turn group.

        Groups are returned in order of their first turn's index.
        """
        session_data = self._sessions.get(session_id)
        if not session_data or session_data.turns is None:
            return []

        groups: list[list[TurnData]] = []
        exchange_to_group: dict[str, list[TurnData]] = {}

        for turn in session_data.turns:
            if turn.exchange_id:
                if turn.exchange_id in exchange_to_group:
                    exchange_to_group[turn.exchange_id].append(turn)
                else:
                    group = [turn]
                    exchange_to_group[turn.exchange_id] = group
                    groups.append(group)
            else:
                # No exchange_id - own group
                groups.append([turn])

        return groups

    # --- Tool Use Operations ---

    def add_tool_use(
        self,
        session_id: str,
        turn_idx: int,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict = None,
    ) -> None:
        """Add a tool use to a turn during streaming."""
        turn = self.get_turn(session_id, turn_idx)
        if not turn:
            return

        if tool_use_id not in turn.tool_use_ids:
            turn.tool_use_ids.append(tool_use_id)

        self._notify(TreeEvent.TOOL_USE_STARTED, {
            "session_id": session_id,
            "turn_idx": turn_idx,
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "tool_input": tool_input or {},
        })

    def update_tool_use(
        self,
        session_id: str,
        turn_idx: int,
        tool_use_id: str,
        tool_name: str,
        partial_json: str,
    ) -> None:
        """Update tool use with streaming partial JSON."""
        self._notify(TreeEvent.TOOL_USE_UPDATED, {
            "session_id": session_id,
            "turn_idx": turn_idx,
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "partial_json": partial_json,
        })

    def add_tool_result(
        self,
        session_id: str,
        turn_idx: int,
        tool_use_id: str,
        result: str,
        is_error: bool = False,
    ) -> None:
        """Add a tool result."""
        self._notify(TreeEvent.TOOL_RESULT_ADDED, {
            "session_id": session_id,
            "turn_idx": turn_idx,
            "tool_use_id": tool_use_id,
            "result": result,
            "is_error": is_error,
        })

    # --- Context Mode Operations ---

    def get_context_mode(self, session_id: str, turn_idx: int) -> ContextMode:
        """Get the context mode for a turn.

        For the current session, defaults to COPY (include in context).
        For other sessions, defaults to DROP (not in context).
        """
        key = (session_id, turn_idx)
        if key in self._context_modes:
            return self._context_modes[key]
        # Default: current session turns are COPY, others are DROP
        if session_id == self._current_session_id:
            return ContextMode.COPY
        return ContextMode.DROP

    def set_context_mode(self, session_id: str, turn_idx: int, mode: ContextMode) -> None:
        """Set the context mode for a turn.

        Also updates cached_context_tokens when toggling to/from DROP.
        """
        old_mode = self.get_context_mode(session_id, turn_idx)
        self._context_modes[(session_id, turn_idx)] = mode

        # Update cached token count if transitioning to/from DROP
        # Note: Compare by .value to handle different ContextMode class instances
        # (can happen when modules are imported through different paths)
        session_data = self._sessions.get(session_id)
        if session_data and session_data.turns is not None:
            turn = next((t for t in session_data.turns if t.idx == turn_idx), None)
            if turn:
                was_dropped = old_mode.value == ContextMode.DROP.value
                is_dropped = mode.value == ContextMode.DROP.value
                if was_dropped and not is_dropped:
                    # Adding turn back to context
                    session_data.cached_context_tokens += turn.tokens
                elif not was_dropped and is_dropped:
                    # Removing turn from context
                    session_data.cached_context_tokens -= turn.tokens

        self._notify(TreeEvent.CONTEXT_MODE_CHANGED, {
            "session_id": session_id,
            "turn_idx": turn_idx,
            "mode": mode,
        })

    def toggle_context_mode(self, session_id: str, turn_idx: int) -> ContextMode:
        """Toggle context mode: COPY -> COMPRESS -> DROP -> COPY."""
        current = self.get_context_mode(session_id, turn_idx)

        # Compare by value to handle different enum instances
        if current.value == ContextMode.COPY.value:
            new_mode = ContextMode.COMPRESS
        elif current.value in (ContextMode.COMPRESS.value, ContextMode.SUMMARIZE.value):
            new_mode = ContextMode.DROP
        else:  # DROP
            new_mode = ContextMode.COPY

        self.set_context_mode(session_id, turn_idx, new_mode)
        return new_mode

    def get_merge_mode(self, parent_session_id: str, fork_session_id: str) -> ContextMode:
        """Get the context mode for a merge."""
        return self._merge_modes.get((parent_session_id, fork_session_id), ContextMode.COPY)

    def set_merge_mode(self, parent_session_id: str, fork_session_id: str, mode: ContextMode) -> None:
        """Set the context mode for a merge."""
        self._merge_modes[(parent_session_id, fork_session_id)] = mode
        self._notify(TreeEvent.CONTEXT_MODE_CHANGED, {
            "type": "merge",
            "parent_session_id": parent_session_id,
            "fork_session_id": fork_session_id,
            "mode": mode,
        })

    def get_all_context_modes(self) -> dict[tuple[str, int], ContextMode]:
        """Get all context modes (for computing selected tokens, etc.)."""
        return self._context_modes.copy()

    def get_context_modes_for_session(self, session_id: str) -> dict[int, ContextMode]:
        """Get all context modes for a specific session.

        Returns dict mapping turn_idx -> ContextMode for the given session.
        """
        return {
            idx: mode
            for (sid, idx), mode in self._context_modes.items()
            if sid == session_id
        }

    def remove_context_mode(self, session_id: str, turn_idx: int) -> None:
        """Remove the context mode for a turn (sets it back to default DROP)."""
        key = (session_id, turn_idx)
        if key in self._context_modes:
            del self._context_modes[key]
            self._notify(TreeEvent.CONTEXT_MODE_CHANGED, {
                "session_id": session_id,
                "turn_idx": turn_idx,
                "mode": ContextMode.DROP,
            })

    def shift_context_modes_after_removal(self, session_id: str, removed_idx: int) -> None:
        """Shift context mode indices down after a turn is removed.

        All turns with idx > removed_idx have their indices decremented by 1.
        """
        keys_to_update = [
            (sid, idx) for sid, idx in self._context_modes.keys()
            if sid == session_id and idx > removed_idx
        ]
        for old_key in keys_to_update:
            mode = self._context_modes.pop(old_key)
            new_key = (session_id, old_key[1] - 1)
            self._context_modes[new_key] = mode

    def clear_context_modes_for_session(self, session_id: str) -> None:
        """Remove all context modes for a session."""
        keys_to_remove = [
            key for key in self._context_modes.keys()
            if key[0] == session_id
        ]
        for key in keys_to_remove:
            del self._context_modes[key]

    # --- Context Token Counts ---

    def set_context_tokens(self, selected_tokens: int, total_tokens: int) -> None:
        """Set the context token counts (called by app after calculating from compiled context).

        Args:
            selected_tokens: Tokens from selected (non-DROP) turns
            total_tokens: Total tokens from all turns in current session
        """
        if (self._selected_context_tokens != selected_tokens or
                self._total_session_tokens != total_tokens):
            self._selected_context_tokens = selected_tokens
            self._total_session_tokens = total_tokens
            self._notify(TreeEvent.CONTEXT_TOKENS_CHANGED, {
                "selected_tokens": selected_tokens,
                "total_tokens": total_tokens,
            })

    def get_context_tokens(self) -> tuple[int, int]:
        """Get the context token counts.

        Returns:
            Tuple of (selected_tokens, total_tokens)
        """
        return (self._selected_context_tokens, self._total_session_tokens)

    def update_session_tokens(self, session_id: str, cached_tokens: int) -> None:
        """Update a session's cached_context_tokens value.

        Called by app after recalculating context tokens (e.g., after archive).
        This updates the SessionData so tree labels reflect the new token count.

        Args:
            session_id: The session to update
            cached_tokens: The new cached token count
        """
        if session_id in self._sessions:
            self._sessions[session_id].cached_context_tokens = cached_tokens
            self._notify(TreeEvent.SESSION_UPDATED, {"session_id": session_id})

    # --- Streaming State ---

    def start_streaming(self, session_id: str) -> None:
        """Mark a session as currently streaming."""
        self._streaming_sessions.add(session_id)
        if session_id in self._sessions:
            self._sessions[session_id].is_streaming = True
        self._notify(TreeEvent.STREAMING_STARTED, {"session_id": session_id})

    def stop_streaming(self, session_id: str) -> None:
        """Mark a session as no longer streaming."""
        self._streaming_sessions.discard(session_id)
        if session_id in self._sessions:
            self._sessions[session_id].is_streaming = False
        self._notify(TreeEvent.STREAMING_STOPPED, {"session_id": session_id})

    def is_streaming(self, session_id: str) -> bool:
        """Check if a session is currently streaming."""
        return session_id in self._streaming_sessions

    def get_streaming_sessions(self) -> set[str]:
        """Get all session IDs that are currently streaming."""
        return self._streaming_sessions.copy()

    # --- Viewed State ---

    def mark_turn_viewed(self, session_id: str, turn_idx: int) -> bool:
        """Mark a turn as viewed by the user.

        Returns True if the turn was marked as viewed (was previously unviewed),
        False if already viewed or turn not found.
        """
        turn = self.get_turn(session_id, turn_idx)
        if not turn or turn.viewed:
            return False

        turn.viewed = True
        self._notify(TreeEvent.TURN_VIEWED, {
            "session_id": session_id,
            "turn_idx": turn_idx,
        })
        return True

    def mark_turns_viewed(self, session_id: str, turn_indices: list[int]) -> int:
        """Mark multiple turns as viewed.

        Returns the number of turns that were actually marked as viewed.
        """
        count = 0
        for turn_idx in turn_indices:
            if self.mark_turn_viewed(session_id, turn_idx):
                count += 1
        return count

    def get_unviewed_turns(self, session_id: str) -> list[int]:
        """Get list of turn indices that haven't been viewed."""
        session_data = self._sessions.get(session_id)
        if not session_data or session_data.turns is None:
            return []

        return [turn.idx for turn in session_data.turns if not turn.viewed]

    def has_unviewed_turns(self, session_id: str) -> bool:
        """Check if session has any unviewed turns."""
        session_data = self._sessions.get(session_id)
        if not session_data or session_data.turns is None:
            return False

        return any(not turn.viewed for turn in session_data.turns)

    def get_unviewed_count(self, session_id: str) -> int:
        """Get count of unviewed turns in a session."""
        session_data = self._sessions.get(session_id)
        if not session_data or session_data.turns is None:
            return 0

        return sum(1 for turn in session_data.turns if not turn.viewed)

    # --- Bulk Operations ---

    def clear(self, preserve_streaming: bool = True) -> None:
        """Clear all state.

        Args:
            preserve_streaming: If True (default), streaming session IDs are preserved
                so that sessions that were streaming before clear() remain streaming
                after being re-added. This prevents animation interruption during
                load_all_sessions() calls.
        """
        self._sessions.clear()
        self._context_modes.clear()
        self._merge_modes.clear()
        self._current_session_id = None
        if not preserve_streaming:
            self._streaming_sessions.clear()
        self._session_colors.clear()
        self._notify(TreeEvent.FULL_REBUILD, {})

    def request_rebuild(self) -> None:
        """Request that all observers rebuild their views."""
        self._notify(TreeEvent.FULL_REBUILD, {})
