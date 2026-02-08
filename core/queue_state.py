"""Queue state management for Balloons.

This module provides centralized message queue state with an observer pattern,
following the same architecture as TreeState and TaskState.

Key Design Decisions:
    - Views receive immutable snapshots, never mutate state directly
    - All mutations go through QueueState methods
    - Observers are notified after mutations complete
    - Selection is ID-based, not index-based (avoids invalidation issues)
    - Each session has its own queue; QueueState manages all of them

Architecture:
    - QueueState: Central state manager (this module)
    - QueueSnapshot: Immutable view of queue state for rendering
    - QueuedMessageSnapshot: Immutable view of a single queued message
    - MessageQueuePopup: View that observes QueueState (widgets/message_queue_popup.py)
    - App: Routes user actions through QueueState

Data Flow:
    1. User types during streaming → app calls queue_state.add_message()
    2. QueueState updates internal state, creates snapshot, notifies observers
    3. MessageQueuePopup receives QueueEvent, re-renders from snapshot
    4. User removes message → app calls queue_state.remove_message()
    5. QueueState updates, notifies, popup re-renders

Migration Notes:
    The existing MessageQueue class in session.py remains for persistence.
    QueueState wraps MessageQueue instances and provides the observer layer.
    Eventually, MessageQueue could be simplified to just serialization.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Awaitable, Optional


class QueueEvent(Enum):
    """Events emitted by QueueState to observers."""
    MESSAGE_ADDED = "message_added"       # New message queued
    MESSAGE_REMOVED = "message_removed"   # Message deleted
    MESSAGE_UPDATED = "message_updated"   # Content or pause state changed
    PAUSE_TOGGLED = "pause_toggled"       # Message pause state toggled
    QUEUE_DRAINED = "queue_drained"       # Messages sent to LLM
    QUEUE_CLEARED = "queue_cleared"       # All messages cleared
    SESSION_CHANGED = "session_changed"   # Active session switched
    FULL_REBUILD = "full_rebuild"         # Complete state rebuild needed


@dataclass(frozen=True)
class QueuedMessageSnapshot:
    """Immutable snapshot of a queued message for views.

    Views use this for rendering. The frozen=True makes it immutable,
    preventing accidental mutation of view data.
    """
    id: str
    content: str
    created: datetime
    paused: bool

    @property
    def preview(self) -> str:
        """Get a short preview of content for display (first 50 chars)."""
        text = self.content.replace("\n", " ")[:50]
        if len(self.content) > 50:
            text += "…"
        return text


@dataclass(frozen=True)
class QueueSnapshot:
    """Immutable snapshot of queue state for views.

    Views receive this on every update and use it for rendering.
    The tuple of messages is immutable, preventing mutation.
    """
    session_id: str
    messages: tuple[QueuedMessageSnapshot, ...]
    is_blocked: bool  # True if first message is paused
    first_pause_index: int  # -1 if no paused messages

    def __len__(self) -> int:
        return len(self.messages)

    def __bool__(self) -> bool:
        return len(self.messages) > 0

    def get_message(self, message_id: str) -> QueuedMessageSnapshot | None:
        """Find a message by ID."""
        for msg in self.messages:
            if msg.id == message_id:
                return msg
        return None

    def get_message_index(self, message_id: str) -> int:
        """Get index of a message by ID, or -1 if not found."""
        for i, msg in enumerate(self.messages):
            if msg.id == message_id:
                return i
        return -1


# Internal mutable message class (not exposed to views)
@dataclass
class _QueuedMessage:
    """Internal mutable message storage."""
    id: str
    content: str
    created: datetime
    paused: bool = False

    def to_snapshot(self) -> QueuedMessageSnapshot:
        """Create an immutable snapshot for views."""
        return QueuedMessageSnapshot(
            id=self.id,
            content=self.content,
            created=self.created,
            paused=self.paused,
        )


# Internal mutable queue class (not exposed to views)
@dataclass
class _MessageQueue:
    """Internal mutable queue storage."""
    session_id: str
    messages: list[_QueuedMessage] = field(default_factory=list)

    def to_snapshot(self) -> QueueSnapshot:
        """Create an immutable snapshot for views."""
        first_pause = -1
        for i, msg in enumerate(self.messages):
            if msg.paused:
                first_pause = i
                break

        is_blocked = len(self.messages) > 0 and self.messages[0].paused

        return QueueSnapshot(
            session_id=self.session_id,
            messages=tuple(msg.to_snapshot() for msg in self.messages),
            is_blocked=is_blocked,
            first_pause_index=first_pause,
        )


# Type alias for async observer callbacks
AsyncObserver = Callable[[QueueEvent, QueueSnapshot, dict], Awaitable[None]]


class QueueState:
    """Centralized state manager for message queues.

    Provides:
    - Per-session queue storage
    - Active session tracking
    - Observer pattern for change notifications
    - Immutable snapshots for views

    Thread Safety:
        Not thread-safe. All operations should be called from the main UI thread.
        Observer notifications are scheduled on the event loop asynchronously.

    Usage:
        # Get the global queue state
        queue_state = get_queue_state()

        # Add a message to a session's queue
        msg_id = queue_state.add_message("session-123", "Hello")

        # Get a snapshot for rendering
        snapshot = queue_state.get_snapshot("session-123")

        # Subscribe to changes
        async def on_queue_change(event, snapshot, data):
            print(f"Queue changed: {event}")
        queue_state.add_observer(on_queue_change)
    """

    _instance: "QueueState | None" = None

    def __new__(cls) -> "QueueState":
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize queue state (only runs once due to singleton)."""
        if self._initialized:
            return
        self._initialized = True

        # Queue storage: session_id -> _MessageQueue
        self._queues: dict[str, _MessageQueue] = {}

        # Currently active session
        self._active_session_id: str | None = None

        # Async observers for state changes
        self._observers: list[AsyncObserver] = []

    # =========================================================================
    # Observer Pattern
    # =========================================================================

    def add_observer(self, callback: AsyncObserver) -> None:
        """Add an async observer for queue state changes.

        Args:
            callback: Async function called with (event, snapshot, extra_data)
        """
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: AsyncObserver) -> None:
        """Remove an observer."""
        if callback in self._observers:
            self._observers.remove(callback)

    def _schedule_notification(
        self,
        event: QueueEvent,
        session_id: str,
        extra_data: dict | None = None,
    ) -> None:
        """Schedule async observer notifications on the event loop.

        Creates a snapshot at notification time to ensure observers
        see consistent state.
        """
        if not self._observers:
            return

        snapshot = self.get_snapshot(session_id)
        data = extra_data or {}

        try:
            loop = asyncio.get_running_loop()
            for callback in self._observers:
                asyncio.ensure_future(
                    self._call_observer(callback, event, snapshot, data)
                )
        except RuntimeError:
            # No running event loop - skip notifications
            pass

    async def _call_observer(
        self,
        callback: AsyncObserver,
        event: QueueEvent,
        snapshot: QueueSnapshot,
        data: dict,
    ) -> None:
        """Safely call an async observer."""
        try:
            await callback(event, snapshot, data)
        except Exception:
            pass  # Don't let observer errors break queue operations

    # =========================================================================
    # Queue Operations
    # =========================================================================

    def _ensure_queue(self, session_id: str) -> _MessageQueue:
        """Get or create a queue for a session."""
        if session_id not in self._queues:
            self._queues[session_id] = _MessageQueue(session_id=session_id)
        return self._queues[session_id]

    def add_message(self, session_id: str, content: str) -> str:
        """Add a message to a session's queue.

        Args:
            session_id: The session to add to
            content: Message content

        Returns:
            The new message's ID
        """
        queue = self._ensure_queue(session_id)

        msg = _QueuedMessage(
            id=str(uuid.uuid4()),
            content=content,
            created=datetime.now(),
        )
        queue.messages.append(msg)

        self._schedule_notification(
            QueueEvent.MESSAGE_ADDED,
            session_id,
            {"message_id": msg.id},
        )

        return msg.id

    def remove_message(self, session_id: str, message_id: str) -> bool:
        """Remove a message from a session's queue.

        Args:
            session_id: The session to remove from
            message_id: ID of message to remove

        Returns:
            True if message was found and removed
        """
        queue = self._queues.get(session_id)
        if not queue:
            return False

        for i, msg in enumerate(queue.messages):
            if msg.id == message_id:
                queue.messages.pop(i)
                self._schedule_notification(
                    QueueEvent.MESSAGE_REMOVED,
                    session_id,
                    {"message_id": message_id},
                )
                return True

        return False

    def update_content(self, session_id: str, message_id: str, content: str) -> bool:
        """Update a message's content.

        Args:
            session_id: The session containing the message
            message_id: ID of message to update
            content: New content

        Returns:
            True if message was found and updated
        """
        queue = self._queues.get(session_id)
        if not queue:
            return False

        for msg in queue.messages:
            if msg.id == message_id:
                msg.content = content
                self._schedule_notification(
                    QueueEvent.MESSAGE_UPDATED,
                    session_id,
                    {"message_id": message_id},
                )
                return True

        return False

    def toggle_pause(self, session_id: str, message_id: str) -> bool | None:
        """Toggle the paused state of a message.

        Args:
            session_id: The session containing the message
            message_id: ID of message to toggle

        Returns:
            New paused state, or None if message not found
        """
        queue = self._queues.get(session_id)
        if not queue:
            return None

        for msg in queue.messages:
            if msg.id == message_id:
                msg.paused = not msg.paused
                self._schedule_notification(
                    QueueEvent.PAUSE_TOGGLED,
                    session_id,
                    {"message_id": message_id, "paused": msg.paused},
                )
                return msg.paused

        return None

    def drain(self, session_id: str) -> list[str]:
        """Remove and return content of messages up to first paused message.

        This is called when streaming completes and queued messages should
        be sent to the LLM.

        Args:
            session_id: The session to drain

        Returns:
            List of message content strings that were drained
        """
        queue = self._queues.get(session_id)
        if not queue or not queue.messages:
            return []

        # Don't drain if first message is paused
        if queue.messages[0].paused:
            return []

        result: list[str] = []
        while queue.messages and not queue.messages[0].paused:
            msg = queue.messages.pop(0)
            result.append(msg.content)

        if result:
            self._schedule_notification(
                QueueEvent.QUEUE_DRAINED,
                session_id,
                {"count": len(result)},
            )

        return result

    def clear(self, session_id: str) -> int:
        """Clear all messages from a session's queue.

        Args:
            session_id: The session to clear

        Returns:
            Number of messages cleared
        """
        queue = self._queues.get(session_id)
        if not queue:
            return 0

        count = len(queue.messages)
        queue.messages.clear()

        if count > 0:
            self._schedule_notification(
                QueueEvent.QUEUE_CLEARED,
                session_id,
                {"count": count},
            )

        return count

    # =========================================================================
    # Session Management
    # =========================================================================

    def set_active_session(self, session_id: str | None) -> None:
        """Set the currently active session.

        Views may use this to determine which queue to display.

        Args:
            session_id: The active session ID, or None for no active session
        """
        prev_session_id = self._active_session_id
        self._active_session_id = session_id

        if prev_session_id != session_id:
            # Notify with the new session's snapshot (or empty if None)
            notify_id = session_id or prev_session_id or ""
            if notify_id:
                self._schedule_notification(
                    QueueEvent.SESSION_CHANGED,
                    notify_id,
                    {
                        "prev_session_id": prev_session_id,
                        "new_session_id": session_id,
                    },
                )

    def get_active_session_id(self) -> str | None:
        """Get the currently active session ID."""
        return self._active_session_id

    def remove_session(self, session_id: str) -> None:
        """Remove all queue data for a session.

        Called when a session is deleted.
        """
        if session_id in self._queues:
            del self._queues[session_id]

        if self._active_session_id == session_id:
            self._active_session_id = None

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_snapshot(self, session_id: str) -> QueueSnapshot:
        """Get an immutable snapshot of a session's queue.

        Args:
            session_id: The session to get snapshot for

        Returns:
            QueueSnapshot (may be empty if session has no queue)
        """
        queue = self._queues.get(session_id)
        if queue:
            return queue.to_snapshot()

        # Return empty snapshot for unknown session
        return QueueSnapshot(
            session_id=session_id,
            messages=(),
            is_blocked=False,
            first_pause_index=-1,
        )

    def get_active_snapshot(self) -> QueueSnapshot | None:
        """Get snapshot for the active session, if any."""
        if self._active_session_id:
            return self.get_snapshot(self._active_session_id)
        return None

    def get_message_count(self, session_id: str) -> int:
        """Get number of messages in a session's queue."""
        queue = self._queues.get(session_id)
        return len(queue.messages) if queue else 0

    def has_messages(self, session_id: str) -> bool:
        """Check if a session has any queued messages."""
        queue = self._queues.get(session_id)
        return bool(queue and queue.messages)

    def is_blocked(self, session_id: str) -> bool:
        """Check if a session's queue is blocked (first message paused)."""
        queue = self._queues.get(session_id)
        return bool(queue and queue.messages and queue.messages[0].paused)

    def get_all_session_ids_with_queues(self) -> list[str]:
        """Get IDs of all sessions that have non-empty queues."""
        return [
            sid for sid, queue in self._queues.items()
            if queue.messages
        ]

    # =========================================================================
    # Sync with MessageQueue (for persistence compatibility)
    # =========================================================================

    def sync_from_message_queue(
        self,
        session_id: str,
        message_queue: "MessageQueue",
    ) -> None:
        """Sync state from a session's MessageQueue.

        Called when loading a session to populate QueueState from
        the persisted MessageQueue.

        Args:
            session_id: The session ID
            message_queue: The MessageQueue from session.py
        """
        from models import MessageQueue  # Import from domain models

        queue = self._ensure_queue(session_id)
        queue.messages.clear()

        for msg in message_queue.messages:
            queue.messages.append(_QueuedMessage(
                id=msg.id,
                content=msg.content,
                created=msg.created,
                paused=msg.paused,
            ))

        # Notify observers of the rebuild
        self._schedule_notification(QueueEvent.FULL_REBUILD, session_id)

    def sync_to_message_queue(
        self,
        session_id: str,
        message_queue: "MessageQueue",
    ) -> None:
        """Sync state to a session's MessageQueue for persistence.

        Called before saving a session to update the MessageQueue
        with current QueueState.

        Args:
            session_id: The session ID
            message_queue: The MessageQueue to update
        """
        from models import MessageQueue, QueuedMessage  # Import from domain models

        queue = self._queues.get(session_id)
        if not queue:
            message_queue.messages.clear()
            return

        message_queue.messages.clear()
        for msg in queue.messages:
            message_queue.messages.append(QueuedMessage(
                id=msg.id,
                content=msg.content,
                created=msg.created,
                paused=msg.paused,
            ))

    # =========================================================================
    # Cleanup
    # =========================================================================

    def clear_all(self) -> None:
        """Clear all queue state. Use for testing or reset."""
        self._queues.clear()
        self._active_session_id = None

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance. Use only for testing."""
        cls._instance = None


# Convenience function to get the singleton
def get_queue_state() -> QueueState:
    """Get the global QueueState instance."""
    return QueueState()
