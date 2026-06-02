"""Tests for QueueState management."""

import pytest
import asyncio
from datetime import datetime

from core.queue_state import (
    QueueState,
    QueueEvent,
    QueueSnapshot,
    QueuedMessageSnapshot,
    get_queue_state,
)


@pytest.fixture
def queue_state():
    """Get a fresh QueueState for each test."""
    # Reset singleton to ensure clean state
    QueueState.reset_instance()
    state = QueueState()
    return state


@pytest.fixture(autouse=True)
def cleanup_singleton():
    """Clean up singleton after each test."""
    yield
    QueueState.reset_instance()


class TestMessageOperations:
    """Tests for basic message queue operations."""

    def test_add_message(self, queue_state):
        """Test adding a message to a queue."""
        msg_id = queue_state.add_message("session-1", "Hello")

        assert msg_id is not None
        assert queue_state.has_messages("session-1")
        assert queue_state.get_message_count("session-1") == 1

    def test_add_multiple_messages(self, queue_state):
        """Test adding multiple messages."""
        id1 = queue_state.add_message("session-1", "First")
        id2 = queue_state.add_message("session-1", "Second")
        id3 = queue_state.add_message("session-1", "Third")

        assert queue_state.get_message_count("session-1") == 3

        snapshot = queue_state.get_snapshot("session-1")
        assert len(snapshot.messages) == 3
        assert snapshot.messages[0].id == id1
        assert snapshot.messages[1].id == id2
        assert snapshot.messages[2].id == id3

    def test_remove_message(self, queue_state):
        """Test removing a message."""
        id1 = queue_state.add_message("session-1", "First")
        id2 = queue_state.add_message("session-1", "Second")

        result = queue_state.remove_message("session-1", id1)

        assert result is True
        assert queue_state.get_message_count("session-1") == 1

        snapshot = queue_state.get_snapshot("session-1")
        assert snapshot.messages[0].id == id2

    def test_remove_nonexistent_message(self, queue_state):
        """Test removing a message that doesn't exist."""
        queue_state.add_message("session-1", "First")

        result = queue_state.remove_message("session-1", "nonexistent-id")
        assert result is False

        # Also test removing from nonexistent session
        result = queue_state.remove_message("nonexistent-session", "any-id")
        assert result is False

    def test_update_content(self, queue_state):
        """Test updating message content."""
        msg_id = queue_state.add_message("session-1", "Original")

        result = queue_state.update_content("session-1", msg_id, "Updated")

        assert result is True
        snapshot = queue_state.get_snapshot("session-1")
        assert snapshot.messages[0].content == "Updated"

    def test_update_content_nonexistent(self, queue_state):
        """Test updating content of nonexistent message."""
        result = queue_state.update_content("session-1", "nonexistent", "New")
        assert result is False


class TestPauseOperations:
    """Tests for pause/blocked functionality."""

    def test_toggle_pause(self, queue_state):
        """Test toggling pause state."""
        msg_id = queue_state.add_message("session-1", "Message")

        # Initially not paused
        snapshot = queue_state.get_snapshot("session-1")
        assert snapshot.messages[0].paused is False
        assert snapshot.is_blocked is False

        # Toggle to paused
        new_state = queue_state.toggle_pause("session-1", msg_id)
        assert new_state is True

        snapshot = queue_state.get_snapshot("session-1")
        assert snapshot.messages[0].paused is True
        assert snapshot.is_blocked is True

        # Toggle back to unpaused
        new_state = queue_state.toggle_pause("session-1", msg_id)
        assert new_state is False

        snapshot = queue_state.get_snapshot("session-1")
        assert snapshot.messages[0].paused is False
        assert snapshot.is_blocked is False

    def test_toggle_pause_nonexistent(self, queue_state):
        """Test toggling pause on nonexistent message."""
        result = queue_state.toggle_pause("session-1", "nonexistent")
        assert result is None

    def test_is_blocked_with_paused_first_message(self, queue_state):
        """Test that queue is blocked when first message is paused."""
        id1 = queue_state.add_message("session-1", "First")
        queue_state.add_message("session-1", "Second")

        # Pause first message
        queue_state.toggle_pause("session-1", id1)

        assert queue_state.is_blocked("session-1") is True

    def test_not_blocked_when_later_message_paused(self, queue_state):
        """Test that queue is not blocked when later message is paused."""
        queue_state.add_message("session-1", "First")
        id2 = queue_state.add_message("session-1", "Second")

        # Pause second message
        queue_state.toggle_pause("session-1", id2)

        assert queue_state.is_blocked("session-1") is False

    def test_first_pause_index(self, queue_state):
        """Test first_pause_index calculation."""
        queue_state.add_message("session-1", "First")
        id2 = queue_state.add_message("session-1", "Second")
        queue_state.add_message("session-1", "Third")

        # Initially no paused messages
        snapshot = queue_state.get_snapshot("session-1")
        assert snapshot.first_pause_index == -1

        # Pause second message
        queue_state.toggle_pause("session-1", id2)
        snapshot = queue_state.get_snapshot("session-1")
        assert snapshot.first_pause_index == 1


class TestDrainOperation:
    """Tests for draining the queue."""

    def test_drain_all_messages(self, queue_state):
        """Test draining all messages when none are paused."""
        queue_state.add_message("session-1", "First")
        queue_state.add_message("session-1", "Second")
        queue_state.add_message("session-1", "Third")

        result = queue_state.drain("session-1")

        assert result == ["First", "Second", "Third"]
        assert queue_state.get_message_count("session-1") == 0

    def test_drain_up_to_paused(self, queue_state):
        """Test draining stops at first paused message."""
        queue_state.add_message("session-1", "First")
        id2 = queue_state.add_message("session-1", "Second")
        queue_state.add_message("session-1", "Third")

        # Pause second message
        queue_state.toggle_pause("session-1", id2)

        result = queue_state.drain("session-1")

        assert result == ["First"]
        assert queue_state.get_message_count("session-1") == 2

    def test_drain_blocked_queue(self, queue_state):
        """Test draining a blocked queue returns empty."""
        id1 = queue_state.add_message("session-1", "First")
        queue_state.add_message("session-1", "Second")

        # Pause first message (blocks queue)
        queue_state.toggle_pause("session-1", id1)

        result = queue_state.drain("session-1")

        assert result == []
        assert queue_state.get_message_count("session-1") == 2

    def test_drain_empty_queue(self, queue_state):
        """Test draining empty queue returns empty."""
        result = queue_state.drain("session-1")
        assert result == []

    def test_drain_nonexistent_session(self, queue_state):
        """Test draining nonexistent session returns empty."""
        result = queue_state.drain("nonexistent")
        assert result == []


class TestClearOperation:
    """Tests for clearing the queue."""

    def test_clear_all_messages(self, queue_state):
        """Test clearing all messages."""
        queue_state.add_message("session-1", "First")
        queue_state.add_message("session-1", "Second")
        queue_state.add_message("session-1", "Third")

        count = queue_state.clear("session-1")

        assert count == 3
        assert queue_state.get_message_count("session-1") == 0

    def test_clear_empty_queue(self, queue_state):
        """Test clearing empty queue."""
        count = queue_state.clear("session-1")
        assert count == 0

    def test_clear_nonexistent_session(self, queue_state):
        """Test clearing nonexistent session."""
        count = queue_state.clear("nonexistent")
        assert count == 0


class TestSessionManagement:
    """Tests for session management."""

    def test_set_active_session(self, queue_state):
        """Test setting active session."""
        queue_state.set_active_session("session-1")
        assert queue_state.get_active_session_id() == "session-1"

        queue_state.set_active_session("session-2")
        assert queue_state.get_active_session_id() == "session-2"

        queue_state.set_active_session(None)
        assert queue_state.get_active_session_id() is None

    def test_get_active_snapshot(self, queue_state):
        """Test getting active session snapshot."""
        queue_state.add_message("session-1", "Message")
        queue_state.set_active_session("session-1")

        snapshot = queue_state.get_active_snapshot()

        assert snapshot is not None
        assert snapshot.session_id == "session-1"
        assert len(snapshot.messages) == 1

    def test_get_active_snapshot_no_active(self, queue_state):
        """Test getting active snapshot when no active session."""
        snapshot = queue_state.get_active_snapshot()
        assert snapshot is None

    def test_remove_session(self, queue_state):
        """Test removing a session."""
        queue_state.add_message("session-1", "Message")
        queue_state.set_active_session("session-1")

        queue_state.remove_session("session-1")

        assert queue_state.get_message_count("session-1") == 0
        assert queue_state.get_active_session_id() is None

    def test_multiple_sessions_isolated(self, queue_state):
        """Test that queues for different sessions are isolated."""
        queue_state.add_message("session-1", "S1 Message")
        queue_state.add_message("session-2", "S2 Message")

        assert queue_state.get_message_count("session-1") == 1
        assert queue_state.get_message_count("session-2") == 1

        queue_state.clear("session-1")

        assert queue_state.get_message_count("session-1") == 0
        assert queue_state.get_message_count("session-2") == 1

    def test_get_all_session_ids_with_queues(self, queue_state):
        """Test getting all sessions with non-empty queues."""
        queue_state.add_message("session-1", "Message")
        queue_state.add_message("session-2", "Message")
        # session-3 has no messages

        sessions = queue_state.get_all_session_ids_with_queues()

        assert set(sessions) == {"session-1", "session-2"}


class TestSnapshots:
    """Tests for snapshot functionality."""

    def test_snapshot_is_immutable(self, queue_state):
        """Test that snapshots are immutable."""
        queue_state.add_message("session-1", "Message")
        snapshot = queue_state.get_snapshot("session-1")

        # Frozen dataclass - can't modify
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            snapshot.session_id = "modified"

    def test_snapshot_message_is_immutable(self, queue_state):
        """Test that message snapshots are immutable."""
        queue_state.add_message("session-1", "Message")
        snapshot = queue_state.get_snapshot("session-1")
        msg = snapshot.messages[0]

        with pytest.raises(Exception):
            msg.content = "modified"

    def test_empty_snapshot_for_unknown_session(self, queue_state):
        """Test that unknown session returns empty snapshot."""
        snapshot = queue_state.get_snapshot("unknown")

        assert snapshot.session_id == "unknown"
        assert len(snapshot.messages) == 0
        assert snapshot.is_blocked is False
        assert snapshot.first_pause_index == -1

    def test_snapshot_get_message(self, queue_state):
        """Test finding a message in snapshot."""
        msg_id = queue_state.add_message("session-1", "Test")
        snapshot = queue_state.get_snapshot("session-1")

        msg = snapshot.get_message(msg_id)
        assert msg is not None
        assert msg.content == "Test"

        assert snapshot.get_message("nonexistent") is None

    def test_snapshot_get_message_index(self, queue_state):
        """Test getting message index in snapshot."""
        id1 = queue_state.add_message("session-1", "First")
        id2 = queue_state.add_message("session-1", "Second")

        snapshot = queue_state.get_snapshot("session-1")

        assert snapshot.get_message_index(id1) == 0
        assert snapshot.get_message_index(id2) == 1
        assert snapshot.get_message_index("nonexistent") == -1

    def test_snapshot_preview(self, queue_state):
        """Test message preview generation."""
        queue_state.add_message("session-1", "Short")
        queue_state.add_message("session-1", "A" * 100)
        queue_state.add_message("session-1", "Line1\nLine2\nLine3")

        snapshot = queue_state.get_snapshot("session-1")

        # Short message unchanged
        assert snapshot.messages[0].preview == "Short"

        # Long message truncated with ellipsis
        assert len(snapshot.messages[1].preview) == 51  # 50 chars + ellipsis
        assert snapshot.messages[1].preview.endswith("…")

        # Newlines replaced with spaces
        assert "\n" not in snapshot.messages[2].preview
        assert "Line1 Line2 Line3" == snapshot.messages[2].preview


@pytest.mark.skip(reason="Requires pytest-asyncio which may not be installed")
class TestObservers:
    """Tests for the observer pattern."""

    async def test_observer_receives_add_event(self, queue_state):
        """Test that observers receive add events."""
        events_received = []

        async def observer(event, snapshot, data):
            events_received.append((event, snapshot.session_id, data))

        queue_state.add_observer(observer)
        queue_state.add_message("session-1", "Test")

        # Give event loop time to process
        await asyncio.sleep(0.01)

        assert len(events_received) == 1
        assert events_received[0][0] == QueueEvent.MESSAGE_ADDED
        assert events_received[0][1] == "session-1"
        assert "message_id" in events_received[0][2]

    async def test_observer_receives_remove_event(self, queue_state):
        """Test that observers receive remove events."""
        events_received = []

        async def observer(event, snapshot, data):
            events_received.append(event)

        queue_state.add_observer(observer)
        msg_id = queue_state.add_message("session-1", "Test")
        await asyncio.sleep(0.01)

        queue_state.remove_message("session-1", msg_id)
        await asyncio.sleep(0.01)

        assert QueueEvent.MESSAGE_ADDED in events_received
        assert QueueEvent.MESSAGE_REMOVED in events_received

    async def test_observer_receives_drain_event(self, queue_state):
        """Test that observers receive drain events."""
        events_received = []

        async def observer(event, snapshot, data):
            events_received.append((event, data))

        queue_state.add_observer(observer)
        queue_state.add_message("session-1", "First")
        queue_state.add_message("session-1", "Second")
        await asyncio.sleep(0.01)
        events_received.clear()

        queue_state.drain("session-1")
        await asyncio.sleep(0.01)

        assert len(events_received) == 1
        assert events_received[0][0] == QueueEvent.QUEUE_DRAINED
        assert events_received[0][1]["count"] == 2

    async def test_observer_receives_session_changed_event(self, queue_state):
        """Test that observers receive session change events."""
        events_received = []

        async def observer(event, snapshot, data):
            events_received.append((event, data))

        queue_state.add_observer(observer)
        queue_state.set_active_session("session-1")
        await asyncio.sleep(0.01)

        assert len(events_received) == 1
        assert events_received[0][0] == QueueEvent.SESSION_CHANGED
        assert events_received[0][1]["new_session_id"] == "session-1"

    async def test_remove_observer(self, queue_state):
        """Test removing an observer."""
        events_received = []

        async def observer(event, snapshot, data):
            events_received.append(event)

        queue_state.add_observer(observer)
        queue_state.add_message("session-1", "First")
        await asyncio.sleep(0.01)
        assert len(events_received) == 1

        queue_state.remove_observer(observer)
        queue_state.add_message("session-1", "Second")
        await asyncio.sleep(0.01)

        # No new events after removal
        assert len(events_received) == 1

    async def test_observer_receives_snapshot_at_notification_time(self, queue_state):
        """Test that snapshot reflects state at notification time."""
        snapshots_received = []

        async def observer(event, snapshot, data):
            snapshots_received.append(snapshot)

        queue_state.add_observer(observer)

        queue_state.add_message("session-1", "First")
        await asyncio.sleep(0.01)
        queue_state.add_message("session-1", "Second")
        await asyncio.sleep(0.01)

        # Each snapshot should show state at that time
        assert len(snapshots_received) == 2
        assert len(snapshots_received[0].messages) == 1
        assert len(snapshots_received[1].messages) == 2


class TestSingleton:
    """Tests for singleton behavior."""

    def test_get_queue_state_returns_singleton(self):
        """Test that get_queue_state returns the same instance."""
        QueueState.reset_instance()
        state1 = get_queue_state()
        state2 = get_queue_state()
        assert state1 is state2

    def test_queuestate_is_singleton(self):
        """Test that QueueState() returns the same instance."""
        QueueState.reset_instance()
        state1 = QueueState()
        state2 = QueueState()
        assert state1 is state2


class TestClearAll:
    """Tests for clear_all and reset."""

    def test_clear_all(self, queue_state):
        """Test clearing all state."""
        queue_state.add_message("session-1", "Message 1")
        queue_state.add_message("session-2", "Message 2")
        queue_state.set_active_session("session-1")

        queue_state.clear_all()

        assert queue_state.get_message_count("session-1") == 0
        assert queue_state.get_message_count("session-2") == 0
        assert queue_state.get_active_session_id() is None

    def test_reset_instance(self):
        """Test resetting singleton instance."""
        state1 = QueueState()
        state1.add_message("session-1", "Test")

        QueueState.reset_instance()
        state2 = QueueState()

        assert state1 is not state2
        assert state2.get_message_count("session-1") == 0
