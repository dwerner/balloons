"""Tests for SessionManagerService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from service.session_manager_service import (
    SessionManagerService,
    SessionManagerEvent,
    ManagedSessionInfo,
    StreamingInfo,
    SessionEventData,
)
from core.stream_state import StreamState, StreamStatus, StreamType, Stream


@pytest.fixture
def mock_session():
    """Create a mock Session."""
    session = MagicMock()
    session.id = "test-session-123"
    session.title = "Test Session"
    session.created = "2024-01-01T00:00:00"
    session.model = "claude-3-opus"
    session.turns = []
    session.parent_id = None
    session.returned = False
    session.working_directory = "/home/test"
    session.delete = AsyncMock(return_value=True)
    return session


@pytest.fixture
def mock_runner():
    """Create a mock SessionRunner."""
    runner = MagicMock()
    runner.is_streaming = False
    runner.cancel = MagicMock()
    return runner


@pytest.fixture
def mock_session_info():
    """Create a mock SessionInfo from core.manager."""
    info = MagicMock()
    info.id = "test-session-123"
    info.title = "Test Session"
    info.created = "2024-01-01T00:00:00"
    info.model = "claude-3-opus"
    info.message_count = 0
    info.is_child = False
    info.is_returned = False
    return info


@pytest.fixture
def mock_manager(mock_session, mock_runner, mock_session_info):
    """Create a mock SessionManager."""
    manager = MagicMock()
    manager._sessions = {mock_session.id: mock_session}
    manager._runners = {mock_session.id: mock_runner}
    manager._active_session_id = mock_session.id
    manager.create_session = AsyncMock(return_value=mock_session)
    manager.load_session = AsyncMock(return_value=mock_session)
    manager.set_active = AsyncMock(return_value=True)
    manager.get_session = MagicMock(return_value=mock_session)
    manager.get_runner = MagicMock(return_value=mock_runner)
    manager.list_sessions = AsyncMock(return_value=[mock_session_info])
    manager.get_streaming_sessions = MagicMock(return_value=[])
    return manager


@pytest.fixture
def stream_state():
    """Create a fresh StreamState for testing."""
    state = StreamState()
    state.clear_all()
    return state


@pytest.fixture
def service(mock_manager, stream_state):
    """Create a SessionManagerService with mocks."""
    return SessionManagerService(mock_manager, stream_state)


class TestSessionManagerServiceInit:
    def test_initialization(self, mock_manager, stream_state):
        """Test service initializes correctly."""
        service = SessionManagerService(mock_manager, stream_state)
        assert service._manager == mock_manager
        assert service._stream_state == stream_state
        assert len(service._event_handlers) == 0

    def test_uses_global_stream_state_if_not_provided(self, mock_manager):
        """Test service uses global StreamState if none provided."""
        service = SessionManagerService(mock_manager)
        assert service._stream_state is not None


class TestEventHandlers:
    def test_add_event_handler(self, service):
        """Test adding an event handler."""
        handler = MagicMock()
        service.add_event_handler(handler)
        assert handler in service._event_handlers

    def test_remove_event_handler(self, service):
        """Test removing an event handler."""
        handler = MagicMock()
        service.add_event_handler(handler)
        service.remove_event_handler(handler)
        assert handler not in service._event_handlers

    def test_remove_nonexistent_handler(self, service):
        """Test removing a handler that wasn't added."""
        handler = MagicMock()
        service.remove_event_handler(handler)  # Should not raise


class TestEventEmission:
    def test_event_to_wire_name(self, service):
        """Test event name conversion to camelCase."""
        assert (
            service._event_to_wire_name(SessionManagerEvent.SESSION_CREATED)
            == "sessionCreated"
        )
        assert (
            service._event_to_wire_name(SessionManagerEvent.STREAMING_STARTED)
            == "streamingStarted"
        )

    def test_emit_event_calls_handlers(self, service):
        """Test that emitting an event calls all handlers."""
        handler1 = MagicMock()
        handler2 = MagicMock()
        service.add_event_handler(handler1)
        service.add_event_handler(handler2)

        service._emit_event(
            SessionManagerEvent.SESSION_CREATED, "test-123", {"extra": "data"}
        )

        handler1.assert_called_once_with(
            "sessionCreated", {"session_id": "test-123", "extra": "data"}
        )
        handler2.assert_called_once_with(
            "sessionCreated", {"session_id": "test-123", "extra": "data"}
        )


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_create_session(self, service, mock_manager, mock_session):
        """Test creating a new session."""
        result = await service.create_session()

        assert isinstance(result, ManagedSessionInfo)
        assert result.id == mock_session.id
        assert result.title == mock_session.title
        mock_manager.create_session.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_create_session_with_working_dir(
        self, service, mock_manager, mock_session
    ):
        """Test creating a session with a working directory."""
        await service.create_session("/custom/path")
        mock_manager.create_session.assert_called_once_with("/custom/path")

    @pytest.mark.asyncio
    async def test_create_session_emits_event(self, service, mock_session):
        """Test that creating a session emits an event."""
        handler = MagicMock()
        service.add_event_handler(handler)

        await service.create_session()

        handler.assert_called_once()
        args = handler.call_args[0]
        assert args[0] == "sessionCreated"
        assert args[1]["session_id"] == mock_session.id


class TestSwitchSession:
    @pytest.mark.asyncio
    async def test_switch_session_success(self, service, mock_manager):
        """Test successfully switching sessions."""
        result = await service.switch_session("test-session-123")

        assert result is True
        mock_manager.set_active.assert_called_once_with("test-session-123")

    @pytest.mark.asyncio
    async def test_switch_session_failure(self, service, mock_manager):
        """Test switching to nonexistent session."""
        mock_manager.set_active.return_value = False

        result = await service.switch_session("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_switch_session_emits_event(self, service, mock_manager):
        """Test that switching sessions emits an event."""
        handler = MagicMock()
        service.add_event_handler(handler)

        await service.switch_session("test-session-123")

        handler.assert_called_once()
        args = handler.call_args[0]
        assert args[0] == "sessionSwitched"


class TestGetSession:
    @pytest.mark.asyncio
    async def test_get_session_found(self, service, mock_manager, mock_session):
        """Test getting an existing session."""
        result = await service.get_session(mock_session.id)

        assert result is not None
        assert result.id == mock_session.id

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, service, mock_manager):
        """Test getting a nonexistent session."""
        mock_manager.get_session.return_value = None
        mock_manager.load_session.return_value = None

        result = await service.get_session("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_loads_from_storage(self, service, mock_manager, mock_session):
        """Test that get_session loads from storage if not in memory."""
        mock_manager.get_session.return_value = None
        mock_manager.load_session.return_value = mock_session

        result = await service.get_session(mock_session.id)

        assert result is not None
        mock_manager.load_session.assert_called_once_with(mock_session.id)


class TestListSessions:
    @pytest.mark.asyncio
    async def test_list_sessions(self, service, mock_manager, mock_session_info):
        """Test listing all sessions."""
        result = await service.list_sessions()

        assert len(result) == 1
        assert result[0].id == mock_session_info.id


class TestDeleteSession:
    @pytest.mark.asyncio
    async def test_delete_session_success(self, service, mock_manager, mock_session):
        """Test successfully deleting a session."""
        result = await service.delete_session(mock_session.id)

        assert result is True
        assert mock_session.id not in mock_manager._sessions
        mock_session.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_session_not_found(self, service, mock_manager):
        """Test deleting a nonexistent session."""
        mock_manager.get_session.return_value = None
        mock_manager.load_session.return_value = None

        result = await service.delete_session("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_session_cancels_streaming(
        self, service, mock_manager, mock_session, mock_runner
    ):
        """Test that deleting a streaming session cancels the stream."""
        mock_runner.is_streaming = True

        await service.delete_session(mock_session.id)

        mock_runner.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_active_session_clears_active(
        self, service, mock_manager, mock_session
    ):
        """Test that deleting the active session clears the active ID."""
        mock_manager._active_session_id = mock_session.id

        await service.delete_session(mock_session.id)

        assert mock_manager._active_session_id is None

    @pytest.mark.asyncio
    async def test_delete_session_emits_event(self, service, mock_session):
        """Test that deleting a session emits an event."""
        handler = MagicMock()
        service.add_event_handler(handler)

        await service.delete_session(mock_session.id)

        handler.assert_called_once()
        args = handler.call_args[0]
        assert args[0] == "sessionDeleted"


class TestStreamingOperations:
    @pytest.mark.asyncio
    async def test_get_streaming_sessions(self, service, mock_manager):
        """Test getting streaming session IDs."""
        mock_manager.get_streaming_sessions.return_value = ["session-1", "session-2"]

        result = await service.get_streaming_sessions()

        assert result == ["session-1", "session-2"]

    @pytest.mark.asyncio
    async def test_get_streaming_info_when_streaming(self, service, stream_state):
        """Test getting streaming info for an active stream."""
        stream_state.register_session_stream(
            session_id="test-session-123",
            exchange_id="exchange-1",
            prompt="Hello",
            backend_name="claude",
        )

        result = await service.get_streaming_info("test-session-123")

        assert result is not None
        assert isinstance(result, StreamingInfo)
        assert result.session_id == "test-session-123"
        assert result.status == "streaming"

    @pytest.mark.asyncio
    async def test_get_streaming_info_when_not_streaming(self, service):
        """Test getting streaming info for a non-streaming session."""
        result = await service.get_streaming_info("test-session-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_streaming_info(self, service, stream_state):
        """Test getting all streaming info."""
        stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Hello",
            backend_name="claude",
        )
        stream_state.register_session_stream(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="World",
            backend_name="openai",
        )

        result = await service.get_all_streaming_info()

        assert len(result) == 2
        session_ids = {r.session_id for r in result}
        assert session_ids == {"session-1", "session-2"}

    @pytest.mark.asyncio
    async def test_cancel_streaming(self, service, mock_manager, mock_runner):
        """Test cancelling a streaming session."""
        mock_runner.is_streaming = True

        result = await service.cancel_streaming("test-session-123")

        assert result is True
        mock_runner.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_streaming_not_streaming(
        self, service, mock_manager, mock_runner
    ):
        """Test cancelling when not streaming."""
        mock_runner.is_streaming = False

        result = await service.cancel_streaming("test-session-123")

        assert result is False
        mock_runner.cancel.assert_not_called()


class TestWsTypeDataclasses:
    def test_managed_session_info_fields(self):
        """Test ManagedSessionInfo has expected fields."""
        info = ManagedSessionInfo(
            id="test-123",
            title="Test",
            created="2024-01-01",
            model="claude",
            message_count=5,
            is_active=True,
            is_streaming=False,
            is_child=False,
            is_returned=False,
        )
        assert info.id == "test-123"
        assert info.parent_id is None
        assert info.working_directory == ""

    def test_streaming_info_fields(self):
        """Test StreamingInfo has expected fields."""
        info = StreamingInfo(
            session_id="test-123",
            stream_id="stream-456",
            status="streaming",
            backend_name="claude",
            started_at="2024-01-01T00:00:00",
            tokens_streamed=100,
        )
        assert info.session_id == "test-123"
        assert info.tool_name is None
        assert info.tool_count == 0

    def test_session_event_data_fields(self):
        """Test SessionEventData has expected fields."""
        data = SessionEventData(
            event_type="sessionCreated",
            session_id="test-123",
        )
        assert data.event_type == "sessionCreated"
        assert data.data == {}
