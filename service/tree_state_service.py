"""WebSocket-exposed service for tree state management.

This service wraps TreeState and exposes its functionality via WebSocket RPC.
The @ws_expose decorators mark methods for client generation.

Example usage:
    tree_state = TreeState()
    service = TreeStateService(tree_state)

    # Service methods are called via WebSocket RPC:
    # {"id": "1", "method": "getSession", "params": {"sessionId": "abc"}}
    # -> {"id": "1", "result": {"id": "abc", "title": "...", ...}}

    # Events are pushed to subscribed clients:
    # {"event": "sessionUpdated", "data": {"sessionId": "abc"}}
"""

from dataclasses import dataclass, field
from typing import Callable, Any

from codegen import ws_service, ws_expose, ws_event, ws_type
from core.tree_state import TreeState, TreeEvent, SessionData, TurnData
from models import ContextMode


# Re-export existing types with @ws_type to include in TypeScript codegen
# (These are already @rust_schema decorated in their original modules)


@ws_type
@dataclass
class SessionInfo:
    """Lightweight session info for listing."""

    id: str
    title: str
    created: str
    last_modified: str
    model: str
    message_count: int
    total_cost: float
    is_current: bool
    is_streaming: bool
    fork_name: str
    fork_status: str
    parent_id: str | None = None
    cached_context_tokens: int = 0
    binding_indicator: str = ""


@ws_type
@dataclass
class TurnInfo:
    """Turn information for display."""

    idx: int
    role: str
    content: str
    streaming: bool
    viewed: bool
    tokens: int
    context_mode: str  # "copy", "compress", "drop"
    exchange_id: str | None = None


@ws_type
@dataclass
class TreeEventData:
    """Event payload for tree state changes."""

    event_type: str  # Maps to TreeEvent enum value
    session_id: str
    turn_idx: int | None = None
    data: dict = field(default_factory=dict)


@ws_service
class TreeStateService:
    """WebSocket-exposed service for tree state management.

    Provides read/write access to session and turn data, context mode management,
    and real-time event subscriptions for state changes.
    """

    def __init__(self, tree_state: TreeState):
        """Initialize service with a TreeState instance.

        Args:
            tree_state: The TreeState to expose via WebSocket
        """
        self._state = tree_state
        self._event_handlers: list[Callable[[str, dict], None]] = []

        # Wire up TreeState observer to emit WebSocket events
        tree_state.add_observer(self._on_tree_event)

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Register a handler for WebSocket events.

        The handler will be called with (event_name, data) for each event.
        """
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def _on_tree_event(self, event: TreeEvent, data: dict) -> None:
        """Convert TreeState events to WebSocket events."""
        # Map TreeEvent enum to camelCase wire name
        event_name = self._tree_event_to_wire_name(event)

        # Debug: log event handling
        from core.debug_log import debug_log
        debug_log.debug(
            f"TreeStateService relaying event: {event_name}, handlers: {len(self._event_handlers)}",
            category="websocket",
        )

        for handler in self._event_handlers:
            handler(event_name, data)

    def _tree_event_to_wire_name(self, event: TreeEvent) -> str:
        """Convert TreeEvent enum to camelCase wire name."""
        # TreeEvent.SESSION_UPDATED -> "sessionUpdated"
        parts = event.value.split("_")
        return parts[0] + "".join(p.title() for p in parts[1:])

    # --- Session Operations ---

    @ws_expose
    async def get_session(self, session_id: str) -> SessionInfo | None:
        """Get session information by ID.

        Args:
            session_id: The session ID to look up

        Returns:
            Session info if found, None otherwise
        """
        session_data = self._state.get_session(session_id)
        if not session_data:
            return None

        return SessionInfo(
            id=session_data.id,
            title=session_data.title,
            created=session_data.created,
            last_modified=session_data.last_modified,
            model=session_data.model,
            message_count=session_data.message_count,
            total_cost=session_data.total_cost,
            is_current=session_data.is_current,
            is_streaming=session_data.is_streaming,
            fork_name=session_data.fork_name,
            fork_status=session_data.fork_status,
            parent_id=session_data.parent_id,
            cached_context_tokens=session_data.cached_context_tokens,
            binding_indicator=session_data.binding_indicator,
        )

    @ws_expose
    async def get_all_sessions(self) -> list[SessionInfo]:
        """Get all sessions.

        Returns:
            List of all session info objects
        """
        sessions = self._state.get_all_sessions()
        return [
            SessionInfo(
                id=s.id,
                title=s.title,
                created=s.created,
                last_modified=s.last_modified,
                model=s.model,
                message_count=s.message_count,
                total_cost=s.total_cost,
                is_current=s.is_current,
                is_streaming=s.is_streaming,
                fork_name=s.fork_name,
                fork_status=s.fork_status,
                parent_id=s.parent_id,
                cached_context_tokens=s.cached_context_tokens,
                binding_indicator=s.binding_indicator,
            )
            for s in sessions.values()
        ]

    @ws_expose
    async def get_current_session_id(self) -> str | None:
        """Get the current active session ID.

        Returns:
            Current session ID or None if no session is active
        """
        return self._state.get_current_session_id()

    @ws_expose
    async def set_current_session(self, session_id: str) -> bool:
        """Set the current active session.

        Args:
            session_id: The session to make current

        Returns:
            True if session was found and set, False otherwise
        """
        if session_id not in self._state.get_all_sessions():
            return False
        self._state.set_current_session(session_id)
        return True

    # --- Turn Operations ---

    @ws_expose
    async def get_turns(self, session_id: str) -> list[TurnInfo]:
        """Get all turns for a session.

        Args:
            session_id: The session to get turns for

        Returns:
            List of turn info objects, empty if session not found/loaded
        """
        session_data = self._state.get_session(session_id)
        if not session_data or session_data.turns is None:
            return []

        return [
            TurnInfo(
                idx=t.idx,
                role=t.role,
                content=t.content,
                streaming=t.streaming,
                viewed=t.viewed,
                tokens=t.tokens,
                context_mode=self._state.get_context_mode(session_id, t.idx).value,
                exchange_id=t.exchange_id,
            )
            for t in session_data.turns
        ]

    @ws_expose
    async def get_turn(self, session_id: str, turn_idx: int) -> TurnInfo | None:
        """Get a specific turn.

        Args:
            session_id: The session ID
            turn_idx: The turn index

        Returns:
            Turn info if found, None otherwise
        """
        turn = self._state.get_turn(session_id, turn_idx)
        if not turn:
            return None

        return TurnInfo(
            idx=turn.idx,
            role=turn.role,
            content=turn.content,
            streaming=turn.streaming,
            viewed=turn.viewed,
            tokens=turn.tokens,
            context_mode=self._state.get_context_mode(session_id, turn_idx).value,
            exchange_id=turn.exchange_id,
        )

    # --- Context Mode Operations ---

    @ws_expose
    async def get_context_mode(self, session_id: str, turn_idx: int) -> str:
        """Get the context mode for a turn.

        Args:
            session_id: The session ID
            turn_idx: The turn index

        Returns:
            Context mode string: "copy", "compress", or "drop"
        """
        return self._state.get_context_mode(session_id, turn_idx).value

    @ws_expose
    async def set_context_mode(
        self, session_id: str, turn_idx: int, mode: str
    ) -> None:
        """Set the context mode for a turn.

        Args:
            session_id: The session ID
            turn_idx: The turn index
            mode: The mode to set ("copy", "compress", or "drop")
        """
        context_mode = ContextMode(mode)
        self._state.set_context_mode(session_id, turn_idx, context_mode)

    @ws_expose
    async def toggle_context_mode(self, session_id: str, turn_idx: int) -> str:
        """Toggle context mode: COPY -> COMPRESS -> DROP -> COPY.

        Args:
            session_id: The session ID
            turn_idx: The turn index

        Returns:
            The new context mode string
        """
        new_mode = self._state.toggle_context_mode(session_id, turn_idx)
        return new_mode.value

    # --- Viewed State ---

    @ws_expose
    async def mark_turn_viewed(self, session_id: str, turn_idx: int) -> bool:
        """Mark a turn as viewed.

        Args:
            session_id: The session ID
            turn_idx: The turn index

        Returns:
            True if turn was marked viewed (was unviewed), False otherwise
        """
        return self._state.mark_turn_viewed(session_id, turn_idx)

    @ws_expose
    async def get_unviewed_count(self, session_id: str) -> int:
        """Get count of unviewed turns in a session.

        Args:
            session_id: The session ID

        Returns:
            Number of unviewed turns
        """
        return self._state.get_unviewed_count(session_id)

    # --- Context Tokens ---

    @ws_expose
    async def get_context_tokens(self) -> tuple[int, int]:
        """Get current context token counts.

        Returns:
            Tuple of (selected_tokens, total_tokens)
        """
        return self._state.get_context_tokens()

    # --- Streaming State ---

    @ws_expose
    async def is_streaming(self, session_id: str) -> bool:
        """Check if a session is currently streaming.

        Args:
            session_id: The session ID

        Returns:
            True if session is streaming
        """
        return self._state.is_streaming(session_id)

    @ws_expose
    async def get_streaming_sessions(self) -> list[str]:
        """Get all session IDs that are currently streaming.

        Returns:
            List of streaming session IDs
        """
        return list(self._state.get_streaming_sessions())

    # --- Events ---

    @ws_event
    async def on_session_added(self) -> TreeEventData:
        """Emitted when a session is added."""
        ...

    @ws_event
    async def on_session_updated(self) -> TreeEventData:
        """Emitted when a session is updated."""
        ...

    @ws_event
    async def on_session_removed(self) -> TreeEventData:
        """Emitted when a session is removed."""
        ...

    @ws_event
    async def on_session_selected(self) -> TreeEventData:
        """Emitted when the current session changes."""
        ...

    @ws_event
    async def on_turn_started(self) -> TreeEventData:
        """Emitted when a new turn starts streaming."""
        ...

    @ws_event
    async def on_turn_updated(self) -> TreeEventData:
        """Emitted when turn content is updated during streaming."""
        ...

    @ws_event
    async def on_turn_finished(self) -> TreeEventData:
        """Emitted when a turn finishes streaming."""
        ...

    @ws_event
    async def on_context_mode_changed(self) -> TreeEventData:
        """Emitted when a turn's context mode changes."""
        ...

    @ws_event
    async def on_streaming_started(self) -> TreeEventData:
        """Emitted when a session starts streaming."""
        ...

    @ws_event
    async def on_streaming_stopped(self) -> TreeEventData:
        """Emitted when a session stops streaming."""
        ...
