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
    ContextMode, TextBlock, ToolUseBlock, ToolResultBlock,
    InterruptionBlock, ErrorBlock, LinkBlock, ArchiveBlock
)


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
    """Data for a single turn in a session."""
    idx: int
    role: str
    content: str
    content_blocks: list = field(default_factory=list)
    events: list = field(default_factory=list)
    streaming: bool = False
    tool_use_ids: list[str] = field(default_factory=list)
    exchange_id: str | None = None  # Groups turns in an agentic loop


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

    TOOL_USE_STARTED = "tool_use_started"
    TOOL_USE_UPDATED = "tool_use_updated"
    TOOL_RESULT_ADDED = "tool_result_added"

    CONTEXT_MODE_CHANGED = "context_mode_changed"

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
        """Add a session from metadata dict (for lazy loading)."""
        session_data = SessionData(
            id=metadata["id"],
            created=metadata.get("created", ""),
            last_modified=metadata.get("last_modified", ""),
            model=metadata.get("model", ""),
            title=metadata.get("title", ""),
            message_count=metadata.get("message_count", 0),
            total_input_tokens=metadata.get("total_input_tokens", 0),
            total_output_tokens=metadata.get("total_output_tokens", 0),
            total_cost=metadata.get("total_cost", 0.0),
            parent_id=metadata.get("parent_id"),
            children=metadata.get("children", []),
            fork_name=metadata.get("fork_name", ""),
            fork_status=metadata.get("fork_status", "active"),
            backend_name=metadata.get("backend_name", ""),
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

        Transforms legacy message format where a single Message contains multiple
        content_blocks into the new model where each content block is its own turn.
        """
        if session_id not in self._sessions:
            self.add_session(session, is_current=session_id == self._current_session_id)

        session_data = self._sessions[session_id]
        session_data.is_loaded = True
        session_data.session_ref = session

        # Load turns, expanding multi-block messages into separate turns
        turns = []
        turn_idx = 0

        for msg in session.turns:
            content_blocks = msg.content_blocks if hasattr(msg, 'content_blocks') else []
            exchange_id = msg.exchange_id if hasattr(msg, 'exchange_id') else None
            msg_context_mode = msg.context_mode if hasattr(msg, 'context_mode') and msg.context_mode else None

            # Transform: expand multiple content_blocks into separate turns
            expanded_turns = self._expand_message_to_turns(
                msg.role, msg.content, content_blocks, exchange_id
            )

            for turn_data in expanded_turns:
                turn_data.idx = turn_idx
                turn_key = (session_id, turn_idx)

                # Initialize context mode from message or default
                if msg_context_mode:
                    self._context_modes[turn_key] = msg_context_mode
                elif session_id == self._current_session_id:
                    self._context_modes[turn_key] = ContextMode.COMPRESS

                turns.append(turn_data)
                turn_idx += 1

        session_data.turns = turns
        session_data.message_count = len(turns)

        # Load merge modes for merged children
        for child in session.children:
            if child.get("status") == "merged":
                fork_id = child.get("session_id", "")
                merge_key = (session_id, fork_id)
                if merge_key not in self._merge_modes:
                    self._merge_modes[merge_key] = ContextMode.COPY

        self._notify(TreeEvent.SESSION_LOADED, {"session_id": session_id})

    def _expand_message_to_turns(
        self,
        role: str,
        content: str,
        content_blocks: list,
        exchange_id: str | None,
    ) -> list[TurnData]:
        """Expand a message with multiple content_blocks into separate turns.

        This handles the transformation from legacy format (single Message with
        multiple content_blocks) to the new model (one turn per block).

        For messages with 0-1 blocks, returns a single turn (no expansion needed).
        For messages with multiple blocks, each block becomes its own turn.
        """
        # No blocks or single text block - no expansion needed
        if not content_blocks:
            return [TurnData(
                idx=0,  # Will be set by caller
                role=role,
                content=content,
                content_blocks=[],
                exchange_id=exchange_id,
            )]

        if len(content_blocks) == 1:
            block = content_blocks[0]
            # Single block - create one turn with that block
            return [TurnData(
                idx=0,
                role=role,
                content=self._content_from_block(block, content),
                content_blocks=[block],
                exchange_id=exchange_id,
            )]

        # Multiple blocks - expand into separate turns
        turns = []
        for block in content_blocks:
            block_role = self._role_from_block(block, role)
            block_content = self._content_from_block(block, "")

            turns.append(TurnData(
                idx=0,  # Will be set by caller
                role=block_role,
                content=block_content,
                content_blocks=[block],
                exchange_id=exchange_id,
            ))

        return turns

    def _role_from_block(self, block, default_role: str) -> str:
        """Determine the role for a turn based on its content block type."""
        if isinstance(block, TextBlock):
            return default_role
        elif isinstance(block, ToolUseBlock):
            return "assistant"  # Claude is calling a tool
        elif isinstance(block, ToolResultBlock):
            return "tool"  # Tool result
        elif isinstance(block, (InterruptionBlock, ErrorBlock)):
            return "system"  # Markers
        elif isinstance(block, LinkBlock):
            return "system"  # Links are system-level
        elif isinstance(block, ArchiveBlock):
            return "system"  # Archives are system-level
        return default_role

    def _content_from_block(self, block, fallback: str) -> str:
        """Extract display content from a content block."""
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
        return fallback

    def is_session_loaded(self, session_id: str) -> bool:
        """Check if a session's full data has been loaded."""
        session_data = self._sessions.get(session_id)
        return session_data.is_loaded if session_data else False

    # --- Turn Operations ---

    def start_turn(self, session_id: str, turn_idx: int, role: str, exchange_id: str | None = None) -> None:
        """Start a new turn when streaming begins."""
        session_data = self._sessions.get(session_id)
        if not session_data or session_data.turns is None:
            return

        turn_key = (session_id, turn_idx)
        self._context_modes[turn_key] = ContextMode.COMPRESS

        turn = TurnData(
            idx=turn_idx,
            role=role,
            content="",
            streaming=True,
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
        content_blocks: list,
        events: list[dict] = None,
    ) -> None:
        """Finalize a streaming turn when complete."""
        session_data = self._sessions.get(session_id)
        if not session_data or session_data.turns is None:
            return

        for turn in session_data.turns:
            if turn.idx == turn_idx:
                turn.content = content
                turn.content_blocks = content_blocks
                turn.events = events or []
                turn.streaming = False
                self._notify(TreeEvent.TURN_FINISHED, {
                    "session_id": session_id,
                    "turn_idx": turn_idx,
                    "content": content,
                    "content_blocks": content_blocks,
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
        """Get the context mode for a turn."""
        return self._context_modes.get((session_id, turn_idx), ContextMode.DROP)

    def set_context_mode(self, session_id: str, turn_idx: int, mode: ContextMode) -> None:
        """Set the context mode for a turn."""
        self._context_modes[(session_id, turn_idx)] = mode
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

    # --- Bulk Operations ---

    def clear(self) -> None:
        """Clear all state."""
        self._sessions.clear()
        self._context_modes.clear()
        self._merge_modes.clear()
        self._current_session_id = None
        self._streaming_sessions.clear()
        self._session_colors.clear()
        self._notify(TreeEvent.FULL_REBUILD, {})

    def request_rebuild(self) -> None:
        """Request that all observers rebuild their views."""
        self._notify(TreeEvent.FULL_REBUILD, {})
