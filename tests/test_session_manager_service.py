"""Tests for SessionManagerService."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from service.session_manager_service import (
    SessionManagerService,
    SessionManagerEvent,
    ManagedSessionInfo,
    StreamingInfo,
    SessionEventData,
    SubmitMessageResult,
    _StreamingContext,
)
from service.task_state_service import TaskStateService
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

    def test_submit_message_result_fields(self):
        """Test SubmitMessageResult has expected fields."""
        result = SubmitMessageResult(
            session_id="test-123",
            exchange_id="exchange-456",
            turn_index=0,
            status="started",
        )
        assert result.session_id == "test-123"
        assert result.exchange_id == "exchange-456"
        assert result.turn_index == 0
        assert result.status == "started"


class TestSubmitMessage:
    @pytest.mark.asyncio
    async def test_submit_message_success(self, service, mock_manager, mock_session, mock_runner):
        """Test successfully submitting a message."""
        mock_session.turns = []
        mock_session.add_message = MagicMock()
        mock_session.save = AsyncMock()
        mock_runner.is_streaming = False
        mock_runner.start_background = MagicMock()

        result = await service.submit_message(
            session_id=mock_session.id,
            content="Hello, Claude!",
        )

        assert isinstance(result, SubmitMessageResult)
        assert result.session_id == mock_session.id
        assert result.turn_index == 0
        assert result.status == "started"
        assert result.exchange_id is not None

        # Verify message was added
        mock_session.add_message.assert_called_once()
        call_args = mock_session.add_message.call_args
        assert call_args[0][0] == "user"
        assert call_args[0][1] == "Hello, Claude!"

        # Verify session was saved
        mock_session.save.assert_called_once()

        # Verify background streaming was started
        mock_runner.start_background.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_message_session_not_found(self, service, mock_manager):
        """Test submitting to a nonexistent session."""
        mock_manager.get_session.return_value = None
        mock_manager.load_session.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await service.submit_message(
                session_id="nonexistent",
                content="Hello",
            )

    @pytest.mark.asyncio
    async def test_submit_message_already_streaming(self, service, mock_manager, mock_session, mock_runner):
        """Test submitting when session is already streaming."""
        mock_runner.is_streaming = True

        with pytest.raises(ValueError, match="already streaming"):
            await service.submit_message(
                session_id=mock_session.id,
                content="Hello",
            )

    @pytest.mark.asyncio
    async def test_submit_message_with_queue_not_implemented(self, service, mock_manager, mock_session, mock_runner):
        """Test that queue=True raises not implemented error."""
        mock_runner.is_streaming = True

        with pytest.raises(ValueError, match="queueing not yet implemented"):
            await service.submit_message(
                session_id=mock_session.id,
                content="Hello",
                queue=True,
            )

    @pytest.mark.asyncio
    async def test_submit_message_with_allowed_tools(self, service, mock_manager, mock_session, mock_runner):
        """Test submitting with specific allowed tools."""
        mock_session.turns = []
        mock_session.add_message = MagicMock()
        mock_session.save = AsyncMock()
        mock_runner.is_streaming = False
        mock_runner.start_background = MagicMock()

        await service.submit_message(
            session_id=mock_session.id,
            content="Hello",
            allowed_tools=["Bash", "Read"],
        )

        # Verify allowed_tools was passed
        call_args = mock_runner.start_background.call_args
        assert call_args[1]["allowed_tools"] == ["Bash", "Read"]

    @pytest.mark.asyncio
    async def test_submit_message_increments_turn_index(self, service, mock_manager, mock_session, mock_runner):
        """Test that turn_index reflects existing turns."""
        mock_session.turns = [MagicMock(), MagicMock()]  # 2 existing turns
        mock_session.add_message = MagicMock()
        mock_session.save = AsyncMock()
        mock_runner.is_streaming = False
        mock_runner.start_background = MagicMock()

        result = await service.submit_message(
            session_id=mock_session.id,
            content="Hello",
        )

        assert result.turn_index == 2  # Next turn index

    @pytest.mark.asyncio
    async def test_submit_message_registers_stream(self, service, mock_manager, mock_session, mock_runner, stream_state):
        """Test that submit_message registers the stream in StreamState."""
        mock_session.turns = []
        mock_session.add_message = MagicMock()
        mock_session.save = AsyncMock()
        mock_runner.is_streaming = False
        mock_runner.start_background = MagicMock()

        result = await service.submit_message(
            session_id=mock_session.id,
            content="Hello",
        )

        # Verify stream was registered
        stream = stream_state.get_session_stream(mock_session.id)
        assert stream is not None
        assert stream.stream_id == result.exchange_id
        assert stream.prompt == "Hello"

    @pytest.mark.asyncio
    async def test_submit_message_creates_streaming_context(self, service, mock_manager, mock_session, mock_runner):
        """Test that submit_message creates a streaming context for event pump."""
        mock_session.turns = []
        mock_session.add_message = MagicMock()
        mock_session.save = AsyncMock()
        mock_runner.is_streaming = False
        mock_runner.start_background = MagicMock()

        result = await service.submit_message(
            session_id=mock_session.id,
            content="Hello",
        )

        # Verify streaming context was created
        assert mock_session.id in service._streaming_contexts
        ctx = service._streaming_contexts[mock_session.id]
        assert ctx.session_id == mock_session.id
        assert ctx.exchange_id == result.exchange_id
        assert ctx.user_turn_idx == 0
        assert ctx.assistant_turn_idx == 1

    @pytest.mark.asyncio
    async def test_submit_message_emits_event(self, service, mock_manager, mock_session, mock_runner):
        """Test that submit_message emits MESSAGE_SUBMITTED event."""
        mock_session.turns = []
        mock_session.add_message = MagicMock()
        mock_session.save = AsyncMock()
        mock_runner.is_streaming = False
        mock_runner.start_background = MagicMock()

        handler = MagicMock()
        service.add_event_handler(handler)

        result = await service.submit_message(
            session_id=mock_session.id,
            content="Hello",
        )

        # Verify event was emitted
        handler.assert_called()
        call_args = handler.call_args[0]
        assert call_args[0] == "messageSubmitted"
        assert call_args[1]["session_id"] == mock_session.id
        assert call_args[1]["exchange_id"] == result.exchange_id


class TestEventPump:
    """Tests for the event pump functionality."""

    @pytest.fixture
    def task_service(self, stream_state):
        """Create a TaskStateService for testing."""
        return TaskStateService(stream_state)

    @pytest.fixture
    def service_with_pump(self, mock_manager, stream_state, task_service):
        """Create a SessionManagerService with task service wired up."""
        return SessionManagerService(
            mock_manager,
            stream_state,
            task_state_service=task_service,
        )

    def test_set_task_state_service(self, service, task_service):
        """Test setting the task state service."""
        assert service._task_service is None
        service.set_task_state_service(task_service)
        assert service._task_service == task_service

    @pytest.mark.asyncio
    async def test_start_event_pump(self, service_with_pump):
        """Test starting the event pump."""
        assert not service_with_pump._pump_running
        assert service_with_pump._pump_task is None

        service_with_pump.start_event_pump()

        assert service_with_pump._pump_running
        assert service_with_pump._pump_task is not None
        assert not service_with_pump._pump_task.done()

        # Clean up
        service_with_pump.stop_event_pump()
        # Give pump time to stop
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_start_event_pump_idempotent(self, service_with_pump):
        """Test that starting pump multiple times is safe."""
        service_with_pump.start_event_pump()
        task1 = service_with_pump._pump_task

        service_with_pump.start_event_pump()
        task2 = service_with_pump._pump_task

        # Should be the same task
        assert task1 is task2

        # Clean up
        service_with_pump.stop_event_pump()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_stop_event_pump(self, service_with_pump):
        """Test stopping the event pump."""
        service_with_pump.start_event_pump()
        service_with_pump.stop_event_pump()

        assert not service_with_pump._pump_running
        # Give pump time to stop
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_cancel_streaming_cleans_up_context(self, service_with_pump, mock_manager, mock_session, mock_runner, stream_state):
        """Test that cancelling streaming cleans up the streaming context."""
        # Set up streaming state
        mock_session.turns = []
        mock_session.add_message = MagicMock()
        mock_session.save = AsyncMock()
        mock_runner.is_streaming = False
        mock_runner.start_background = MagicMock()

        # Submit a message to create context
        result = await service_with_pump.submit_message(
            session_id=mock_session.id,
            content="Hello",
        )

        # Now mark runner as streaming
        mock_runner.is_streaming = True

        # Verify context exists
        assert mock_session.id in service_with_pump._streaming_contexts

        # Cancel streaming
        await service_with_pump.cancel_streaming(mock_session.id)

        # Verify context was cleaned up
        assert mock_session.id not in service_with_pump._streaming_contexts


class TestStreamingContextDataclass:
    """Tests for the _StreamingContext dataclass."""

    def test_streaming_context_defaults(self):
        """Test default values for streaming context."""
        ctx = _StreamingContext(
            session_id="test-123",
            exchange_id="exchange-456",
            user_turn_idx=0,
        )

        assert ctx.session_id == "test-123"
        assert ctx.exchange_id == "exchange-456"
        assert ctx.user_turn_idx == 0
        assert ctx.assistant_turn_idx == -1
        assert ctx.content == ""
        assert ctx.tool_count == 0
        assert ctx.tool_turn_indices == {}
        assert ctx.tool_names == {}

    def test_streaming_context_with_values(self):
        """Test streaming context with custom values."""
        ctx = _StreamingContext(
            session_id="test-123",
            exchange_id="exchange-456",
            user_turn_idx=0,
            assistant_turn_idx=1,
            content="Hello",
            tool_count=2,
        )

        assert ctx.assistant_turn_idx == 1
        assert ctx.content == "Hello"
        assert ctx.tool_count == 2


class TestEventDispatch:
    """Tests for the event dispatch functionality."""

    @pytest.fixture
    def task_service(self, stream_state):
        """Create a TaskStateService for testing."""
        return TaskStateService(stream_state)

    @pytest.fixture
    def service_with_task(self, mock_manager, stream_state, task_service):
        """Create a SessionManagerService with task service."""
        return SessionManagerService(
            mock_manager,
            stream_state,
            task_state_service=task_service,
        )

    @pytest.fixture
    def ctx(self):
        """Create a test streaming context."""
        return _StreamingContext(
            session_id="test-123",
            exchange_id="exchange-456",
            user_turn_idx=0,
            assistant_turn_idx=1,
        )

    @pytest.fixture
    def mock_event(self):
        """Create a mock event."""
        class MockEvent:
            def __init__(self, event_type, data=None):
                self.event_type = event_type
                self.data = data
        return MockEvent

    @pytest.mark.asyncio
    async def test_dispatch_text_event(self, service_with_task, task_service, ctx, mock_event):
        """Test dispatching a text event."""
        handler = MagicMock()
        task_service.add_event_handler(handler)

        event = mock_event("text", "Hello")
        await service_with_task._dispatch_event("test-123", event, ctx)

        # Verify content was accumulated
        assert ctx.content == "Hello"

        # Verify event was emitted
        handler.assert_called_once()
        args = handler.call_args[0]
        assert args[0] == "contentDelta"
        assert args[1]["delta"] == "Hello"
        assert args[1]["accumulated"] == "Hello"

    @pytest.mark.asyncio
    async def test_dispatch_text_accumulates(self, service_with_task, task_service, ctx, mock_event):
        """Test that text events accumulate content."""
        handler = MagicMock()
        task_service.add_event_handler(handler)

        await service_with_task._dispatch_event("test-123", mock_event("text", "Hello"), ctx)
        await service_with_task._dispatch_event("test-123", mock_event("text", " World"), ctx)

        assert ctx.content == "Hello World"

        # Check last emit
        args = handler.call_args[0]
        assert args[1]["delta"] == " World"
        assert args[1]["accumulated"] == "Hello World"

    @pytest.mark.asyncio
    async def test_dispatch_turn_started(self, service_with_task, task_service, ctx, mock_event):
        """Test dispatching turn_started event."""
        handler = MagicMock()
        task_service.add_event_handler(handler)

        event = mock_event("turn_started", {"turn_index": 5})
        await service_with_task._dispatch_event("test-123", event, ctx)

        # Verify turn index was updated
        assert ctx.assistant_turn_idx == 5

        # Verify event was emitted
        handler.assert_called_once()
        args = handler.call_args[0]
        assert args[0] == "turnStarted"
        assert args[1]["turn_index"] == 5
        assert args[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_dispatch_tool_use_start(self, service_with_task, task_service, ctx, mock_event):
        """Test dispatching tool_use_start event."""
        handler = MagicMock()
        task_service.add_event_handler(handler)

        event = mock_event("tool_use_start", {
            "tool_use_id": "tool-123",
            "tool_name": "Bash",
            "tool_index": 0,
        })
        await service_with_task._dispatch_event("test-123", event, ctx)

        # Verify tool tracking
        assert ctx.tool_count == 1
        assert ctx.tool_names["tool-123"] == "Bash"

        # Verify event was emitted
        handler.assert_called_once()
        args = handler.call_args[0]
        assert args[0] == "toolUseStarted"
        assert args[1]["tool_name"] == "Bash"

    @pytest.mark.asyncio
    async def test_dispatch_tool_result(self, service_with_task, task_service, ctx, mock_event):
        """Test dispatching tool_result event."""
        # Add tool to context
        ctx.tool_names["tool-123"] = "Bash"

        handler = MagicMock()
        task_service.add_event_handler(handler)

        event = mock_event("tool_result", {
            "tool_use_id": "tool-123",
            "result": "command output",
            "tool_index": 0,
            "turn_index": 2,
        })
        await service_with_task._dispatch_event("test-123", event, ctx)

        # Verify event was emitted
        handler.assert_called_once()
        args = handler.call_args[0]
        assert args[0] == "toolResult"
        assert args[1]["tool_name"] == "Bash"
        assert args[1]["result"] == "command output"

    @pytest.mark.asyncio
    async def test_dispatch_done_cleans_up(self, service_with_task, task_service, ctx, mock_event):
        """Test that done event cleans up streaming context."""
        ctx.content = "Final content"
        service_with_task._streaming_contexts["test-123"] = ctx

        handler = MagicMock()
        task_service.add_event_handler(handler)

        event = mock_event("done", {"result": {}})
        await service_with_task._dispatch_event("test-123", event, ctx)

        # Verify context was cleaned up
        assert "test-123" not in service_with_task._streaming_contexts

        # Verify turn finished was emitted
        handler.assert_called()
        # Find the turnFinished call
        calls = [c[0] for c in handler.call_args_list]
        assert any(c[0] == "turnFinished" for c in calls)

    @pytest.mark.asyncio
    async def test_dispatch_error_cleans_up(self, service_with_task, ctx, mock_event, stream_state):
        """Test that error event cleans up and marks stream failed."""
        service_with_task._streaming_contexts["test-123"] = ctx

        # Register a stream
        stream_state.register_session_stream(
            session_id="test-123",
            exchange_id=ctx.exchange_id,
            prompt="Test",
        )

        event = mock_event("error", "Something went wrong")
        await service_with_task._dispatch_event("test-123", event, ctx)

        # Verify context was cleaned up
        assert "test-123" not in service_with_task._streaming_contexts

        # Verify stream was marked as failed
        stream = stream_state.get_stream(ctx.exchange_id)
        assert stream.status == StreamStatus.ERROR

    @pytest.mark.asyncio
    async def test_dispatch_without_task_service(self, mock_manager, stream_state, ctx, mock_event):
        """Test that dispatch does nothing without task service."""
        service = SessionManagerService(mock_manager, stream_state)

        # Should not raise
        event = mock_event("text", "Hello")
        await service._dispatch_event("test-123", event, ctx)

        # Context should not be modified (no handler was called)
        # But we still accumulate content locally
        # Actually no - without task_service we return early
        assert ctx.content == ""  # Nothing happened
