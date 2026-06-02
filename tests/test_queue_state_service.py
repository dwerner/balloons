"""Tests for QueueStateService."""

import pytest
import importlib.util
from pathlib import Path
from dataclasses import dataclass

# Import QueueState directly to avoid heavy core/__init__.py dependencies
_queue_state_path = Path(__file__).parent.parent / "core" / "queue_state.py"
_spec = importlib.util.spec_from_file_location("queue_state", _queue_state_path)
_queue_state_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_queue_state_module)

QueueState = _queue_state_module.QueueState
QueueEvent = _queue_state_module.QueueEvent

# Import service module
_service_path = Path(__file__).parent.parent / "service" / "queue_state_service.py"
_spec2 = importlib.util.spec_from_file_location("queue_state_service", _service_path)
_queue_state_service_module = importlib.util.module_from_spec(_spec2)

# Need to set up codegen imports for the service module
import sys

# Make sure codegen is importable
sys.path.insert(0, str(Path(__file__).parent.parent))
_spec2.loader.exec_module(_queue_state_service_module)

QueueStateService = _queue_state_service_module.QueueStateService
QueueInfo = _queue_state_service_module.QueueInfo
QueuedMessageInfo = _queue_state_service_module.QueuedMessageInfo
QueueEventData = _queue_state_service_module.QueueEventData


@pytest.fixture
def queue_state():
    """Get a fresh QueueState for each test."""
    QueueState.reset_instance()
    state = QueueState()
    return state


@pytest.fixture
def service(queue_state):
    """Get a QueueStateService wrapping a fresh QueueState."""
    return QueueStateService(queue_state)


@pytest.fixture(autouse=True)
def cleanup_singleton():
    """Clean up singleton after each test."""
    yield
    QueueState.reset_instance()


class TestGetQueue:
    """Tests for queue retrieval methods."""

    async def test_get_queue_empty(self, service):
        """Test getting an empty queue."""
        result = await service.get_queue("session-1")

        assert result.session_id == "session-1"
        assert result.messages == []
        assert result.is_blocked is False
        assert result.first_pause_index == -1
        assert result.message_count == 0

    async def test_get_queue_with_messages(self, service, queue_state):
        """Test getting a queue with messages."""
        queue_state.add_message("session-1", "First message")
        queue_state.add_message("session-1", "Second message")

        result = await service.get_queue("session-1")

        assert result.session_id == "session-1"
        assert len(result.messages) == 2
        assert result.message_count == 2
        assert result.messages[0].content == "First message"
        assert result.messages[1].content == "Second message"

    async def test_get_active_queue_none(self, service):
        """Test getting active queue when no session is active."""
        result = await service.get_active_queue()
        assert result is None

    async def test_get_active_queue(self, service, queue_state):
        """Test getting active queue."""
        queue_state.add_message("session-1", "Message")
        queue_state.set_active_session("session-1")

        result = await service.get_active_queue()

        assert result is not None
        assert result.session_id == "session-1"
        assert len(result.messages) == 1


class TestMessageOperations:
    """Tests for message add/remove/update operations."""

    async def test_add_message(self, service):
        """Test adding a message via service."""
        msg_id = await service.add_message("session-1", "Hello")

        assert msg_id is not None
        queue = await service.get_queue("session-1")
        assert len(queue.messages) == 1
        assert queue.messages[0].id == msg_id
        assert queue.messages[0].content == "Hello"

    async def test_remove_message(self, service):
        """Test removing a message via service."""
        msg_id = await service.add_message("session-1", "To remove")

        result = await service.remove_message("session-1", msg_id)

        assert result is True
        queue = await service.get_queue("session-1")
        assert len(queue.messages) == 0

    async def test_remove_nonexistent(self, service):
        """Test removing a nonexistent message."""
        result = await service.remove_message("session-1", "fake-id")
        assert result is False

    async def test_update_content(self, service):
        """Test updating message content via service."""
        msg_id = await service.add_message("session-1", "Original")

        result = await service.update_content("session-1", msg_id, "Updated")

        assert result is True
        queue = await service.get_queue("session-1")
        assert queue.messages[0].content == "Updated"

    async def test_update_nonexistent(self, service):
        """Test updating nonexistent message."""
        result = await service.update_content("session-1", "fake-id", "New")
        assert result is False


class TestPauseOperations:
    """Tests for pause/resume functionality."""

    async def test_toggle_pause(self, service):
        """Test toggling pause state."""
        msg_id = await service.add_message("session-1", "Message")

        # Initially not paused
        queue = await service.get_queue("session-1")
        assert queue.messages[0].paused is False

        # Toggle to paused
        new_state = await service.toggle_pause("session-1", msg_id)
        assert new_state is True

        queue = await service.get_queue("session-1")
        assert queue.messages[0].paused is True
        assert queue.is_blocked is True

        # Toggle back
        new_state = await service.toggle_pause("session-1", msg_id)
        assert new_state is False

        queue = await service.get_queue("session-1")
        assert queue.messages[0].paused is False
        assert queue.is_blocked is False

    async def test_toggle_pause_nonexistent(self, service):
        """Test toggling pause on nonexistent message."""
        result = await service.toggle_pause("session-1", "fake-id")
        assert result is None

    async def test_is_blocked(self, service):
        """Test is_blocked check."""
        msg_id = await service.add_message("session-1", "Message")

        assert await service.is_blocked("session-1") is False

        await service.toggle_pause("session-1", msg_id)

        assert await service.is_blocked("session-1") is True


class TestDrainClearOperations:
    """Tests for drain and clear operations."""

    async def test_drain_all(self, service):
        """Test draining all messages."""
        await service.add_message("session-1", "First")
        await service.add_message("session-1", "Second")

        result = await service.drain("session-1")

        assert result == ["First", "Second"]
        queue = await service.get_queue("session-1")
        assert len(queue.messages) == 0

    async def test_drain_up_to_paused(self, service):
        """Test draining stops at paused message."""
        await service.add_message("session-1", "First")
        msg_id = await service.add_message("session-1", "Second")
        await service.add_message("session-1", "Third")

        await service.toggle_pause("session-1", msg_id)

        result = await service.drain("session-1")

        assert result == ["First"]
        queue = await service.get_queue("session-1")
        assert len(queue.messages) == 2

    async def test_drain_blocked(self, service):
        """Test draining blocked queue returns empty."""
        msg_id = await service.add_message("session-1", "First")
        await service.toggle_pause("session-1", msg_id)

        result = await service.drain("session-1")

        assert result == []

    async def test_clear(self, service):
        """Test clearing a queue."""
        await service.add_message("session-1", "First")
        await service.add_message("session-1", "Second")

        count = await service.clear("session-1")

        assert count == 2
        queue = await service.get_queue("session-1")
        assert len(queue.messages) == 0


class TestQueryMethods:
    """Tests for query methods."""

    async def test_get_message_count(self, service):
        """Test getting message count."""
        assert await service.get_message_count("session-1") == 0

        await service.add_message("session-1", "Message")
        assert await service.get_message_count("session-1") == 1

    async def test_has_messages(self, service):
        """Test checking for messages."""
        assert await service.has_messages("session-1") is False

        await service.add_message("session-1", "Message")
        assert await service.has_messages("session-1") is True

    async def test_get_all_sessions_with_queues(self, service):
        """Test getting all sessions with queues."""
        await service.add_message("session-1", "Message")
        await service.add_message("session-2", "Message")

        result = await service.get_all_sessions_with_queues()

        assert set(result) == {"session-1", "session-2"}


class TestActiveSessionManagement:
    """Tests for active session management."""

    async def test_get_set_active_session(self, service):
        """Test getting and setting active session."""
        assert await service.get_active_session_id() is None

        await service.set_active_session("session-1")
        assert await service.get_active_session_id() == "session-1"

        await service.set_active_session(None)
        assert await service.get_active_session_id() is None


class TestMessageInfoFields:
    """Tests for message info field correctness."""

    async def test_message_has_created_iso(self, service):
        """Test that message created field is ISO format."""
        await service.add_message("session-1", "Message")

        queue = await service.get_queue("session-1")
        created = queue.messages[0].created

        # Should be ISO format string
        assert isinstance(created, str)
        assert "T" in created  # ISO format has T separator

    async def test_message_has_preview(self, service):
        """Test that message has preview field."""
        await service.add_message("session-1", "Short message")
        await service.add_message("session-1", "A" * 100)

        queue = await service.get_queue("session-1")

        # Short message preview is same
        assert queue.messages[0].preview == "Short message"

        # Long message preview is truncated
        assert len(queue.messages[1].preview) <= 51  # 50 chars + ellipsis


class TestEventHandler:
    """Tests for event handler registration."""

    def test_add_remove_event_handler(self, service):
        """Test adding and removing event handlers."""
        events = []

        def handler(event_name, data):
            events.append((event_name, data))

        service.add_event_handler(handler)
        # Should not raise
        service.remove_event_handler(handler)

        # Removing again should not raise
        service.remove_event_handler(handler)


class TestTypeExports:
    """Tests for exported types."""

    def test_queue_info_dataclass(self):
        """Test QueueInfo is a proper dataclass."""
        info = QueueInfo(
            session_id="test",
            messages=[],
            is_blocked=False,
            first_pause_index=-1,
            message_count=0,
        )
        assert info.session_id == "test"

    def test_queued_message_info_dataclass(self):
        """Test QueuedMessageInfo is a proper dataclass."""
        msg = QueuedMessageInfo(
            id="123",
            content="Hello",
            created="2024-01-01T00:00:00",
            paused=False,
            preview="Hello",
        )
        assert msg.id == "123"

    def test_queue_event_data_dataclass(self):
        """Test QueueEventData is a proper dataclass."""
        event = QueueEventData(
            event_type="messageAdded",
            session_id="session-1",
            message_id="msg-1",
        )
        assert event.event_type == "messageAdded"
