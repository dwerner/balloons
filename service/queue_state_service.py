"""WebSocket-exposed service for queue state management.

This service wraps QueueState and exposes its functionality via WebSocket RPC.
The @ws_expose decorators mark methods for client generation.

Example usage:
    queue_state = get_queue_state()
    service = QueueStateService(queue_state)

    # Service methods are called via WebSocket RPC:
    # {"id": "1", "method": "addMessage", "params": {"sessionId": "abc", "content": "Hello"}}
    # -> {"id": "1", "result": "message-uuid-123"}

    # Events are pushed to subscribed clients:
    # {"event": "messageAdded", "data": {"sessionId": "abc", "messageId": "..."}}
"""

from dataclasses import dataclass, field
from typing import Callable

from codegen import ws_service, ws_expose, ws_event, ws_type
from core.queue_state import QueueState, QueueEvent, QueueSnapshot


@ws_type
@dataclass
class QueuedMessageInfo:
    """Lightweight message info for display."""

    id: str
    content: str
    created: str  # ISO format datetime string
    paused: bool
    preview: str  # Short preview (first 50 chars)


@ws_type
@dataclass
class QueueInfo:
    """Queue state info for a session."""

    session_id: str
    messages: list[QueuedMessageInfo]
    is_blocked: bool
    first_pause_index: int
    message_count: int


@ws_type
@dataclass
class QueueEventData:
    """Event payload for queue state changes."""

    event_type: str  # Maps to QueueEvent enum value
    session_id: str
    message_id: str | None = None
    data: dict = field(default_factory=dict)


@ws_service
class QueueStateService:
    """WebSocket-exposed service for queue state management.

    Provides read/write access to message queues, pause/resume control,
    and real-time event subscriptions for queue changes.
    """

    def __init__(self, queue_state: QueueState):
        """Initialize service with a QueueState instance.

        Args:
            queue_state: The QueueState to expose via WebSocket
        """
        self._state = queue_state
        self._event_handlers: list[Callable[[str, dict], None]] = []

        # Wire up QueueState observer to emit WebSocket events
        queue_state.add_observer(self._on_queue_event)

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Register a handler for WebSocket events.

        The handler will be called with (event_name, data) for each event.
        """
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    async def _on_queue_event(
        self, event: QueueEvent, snapshot: QueueSnapshot, data: dict
    ) -> None:
        """Convert QueueState events to WebSocket events."""
        # Map QueueEvent enum to camelCase wire name
        event_name = self._queue_event_to_wire_name(event)

        event_data = {
            "sessionId": snapshot.session_id,
            **data,
        }

        for handler in self._event_handlers:
            handler(event_name, event_data)

    def _queue_event_to_wire_name(self, event: QueueEvent) -> str:
        """Convert QueueEvent enum to camelCase wire name."""
        # QueueEvent.MESSAGE_ADDED -> "messageAdded"
        parts = event.value.split("_")
        return parts[0] + "".join(p.title() for p in parts[1:])

    def _snapshot_to_queue_info(self, snapshot: QueueSnapshot) -> QueueInfo:
        """Convert a QueueSnapshot to QueueInfo for the wire."""
        return QueueInfo(
            session_id=snapshot.session_id,
            messages=[
                QueuedMessageInfo(
                    id=msg.id,
                    content=msg.content,
                    created=msg.created.isoformat(),
                    paused=msg.paused,
                    preview=msg.preview,
                )
                for msg in snapshot.messages
            ],
            is_blocked=snapshot.is_blocked,
            first_pause_index=snapshot.first_pause_index,
            message_count=len(snapshot.messages),
        )

    # --- Queue Operations ---

    @ws_expose
    async def get_queue(self, session_id: str) -> QueueInfo:
        """Get the queue state for a session.

        Args:
            session_id: The session ID to get queue for

        Returns:
            Queue info (may be empty if session has no queued messages)
        """
        snapshot = self._state.get_snapshot(session_id)
        return self._snapshot_to_queue_info(snapshot)

    @ws_expose
    async def get_active_queue(self) -> QueueInfo | None:
        """Get the queue for the active session.

        Returns:
            Queue info if there's an active session, None otherwise
        """
        snapshot = self._state.get_active_snapshot()
        if snapshot is None:
            return None
        return self._snapshot_to_queue_info(snapshot)

    @ws_expose
    async def add_message(self, session_id: str, content: str) -> str:
        """Add a message to a session's queue.

        Args:
            session_id: The session to add to
            content: Message content

        Returns:
            The new message's ID
        """
        return self._state.add_message(session_id, content)

    @ws_expose
    async def remove_message(self, session_id: str, message_id: str) -> bool:
        """Remove a message from a session's queue.

        Args:
            session_id: The session to remove from
            message_id: ID of message to remove

        Returns:
            True if message was found and removed
        """
        return self._state.remove_message(session_id, message_id)

    @ws_expose
    async def update_content(
        self, session_id: str, message_id: str, content: str
    ) -> bool:
        """Update a message's content.

        Args:
            session_id: The session containing the message
            message_id: ID of message to update
            content: New content

        Returns:
            True if message was found and updated
        """
        return self._state.update_content(session_id, message_id, content)

    # --- Pause/Resume Operations ---

    @ws_expose
    async def toggle_pause(self, session_id: str, message_id: str) -> bool | None:
        """Toggle the paused state of a message.

        Args:
            session_id: The session containing the message
            message_id: ID of message to toggle

        Returns:
            New paused state, or null if message not found
        """
        return self._state.toggle_pause(session_id, message_id)

    @ws_expose
    async def is_blocked(self, session_id: str) -> bool:
        """Check if a session's queue is blocked (first message paused).

        Args:
            session_id: The session to check

        Returns:
            True if queue is blocked
        """
        return self._state.is_blocked(session_id)

    # --- Drain/Clear Operations ---

    @ws_expose
    async def drain(self, session_id: str) -> list[str]:
        """Remove and return content of messages up to first paused message.

        This is called when streaming completes and queued messages should
        be sent to the LLM.

        Args:
            session_id: The session to drain

        Returns:
            List of message content strings that were drained
        """
        return self._state.drain(session_id)

    @ws_expose
    async def clear(self, session_id: str) -> int:
        """Clear all messages from a session's queue.

        Args:
            session_id: The session to clear

        Returns:
            Number of messages cleared
        """
        return self._state.clear(session_id)

    # --- Query Methods ---

    @ws_expose
    async def get_message_count(self, session_id: str) -> int:
        """Get number of messages in a session's queue.

        Args:
            session_id: The session ID

        Returns:
            Number of queued messages
        """
        return self._state.get_message_count(session_id)

    @ws_expose
    async def has_messages(self, session_id: str) -> bool:
        """Check if a session has any queued messages.

        Args:
            session_id: The session ID

        Returns:
            True if session has queued messages
        """
        return self._state.has_messages(session_id)

    @ws_expose
    async def get_all_sessions_with_queues(self) -> list[str]:
        """Get IDs of all sessions that have non-empty queues.

        Returns:
            List of session IDs with queued messages
        """
        return self._state.get_all_session_ids_with_queues()

    # --- Active Session Management ---

    @ws_expose
    async def get_active_session_id(self) -> str | None:
        """Get the currently active session ID.

        Returns:
            Active session ID or null if no session is active
        """
        return self._state.get_active_session_id()

    @ws_expose
    async def set_active_session(self, session_id: str | None) -> None:
        """Set the currently active session.

        Args:
            session_id: The active session ID, or null for no active session
        """
        self._state.set_active_session(session_id)

    # --- Events ---

    @ws_event
    async def on_message_added(self) -> QueueEventData:
        """Emitted when a message is added to a queue."""
        ...

    @ws_event
    async def on_message_removed(self) -> QueueEventData:
        """Emitted when a message is removed from a queue."""
        ...

    @ws_event
    async def on_message_updated(self) -> QueueEventData:
        """Emitted when a message's content is updated."""
        ...

    @ws_event
    async def on_pause_toggled(self) -> QueueEventData:
        """Emitted when a message's pause state is toggled."""
        ...

    @ws_event
    async def on_queue_drained(self) -> QueueEventData:
        """Emitted when messages are drained from a queue."""
        ...

    @ws_event
    async def on_queue_cleared(self) -> QueueEventData:
        """Emitted when a queue is cleared."""
        ...

    @ws_event
    async def on_session_changed(self) -> QueueEventData:
        """Emitted when the active session changes."""
        ...

    @ws_event
    async def on_full_rebuild(self) -> QueueEventData:
        """Emitted when a complete state rebuild is needed."""
        ...
