"""Tests for TaskStateService WebSocket exposure."""

import pytest
import asyncio
from datetime import datetime

from core.stream_state import (
    StreamState as TaskState,
    StreamType as TaskType,
    StreamStatus as TaskStatus,
    StreamEvent as TaskEvent,
)
from service.task_state_service import (
    TaskStateService,
    TaskInfo,
    TaskEventData,
    SessionTaskSummary,
    BackendSummary,
    ContentDeltaEvent,
    TurnStartedEvent,
    TurnFinishedEvent,
    ToolUseStartedEvent,
    ToolInputDeltaEvent,
    ToolUseEvent,
    ToolResultEvent,
)


@pytest.fixture
def task_state():
    """Get a fresh TaskState for each test."""
    state = TaskState()
    state.clear_all()
    state._observers.clear()
    return state


@pytest.fixture
def service(task_state):
    """Get a TaskStateService wrapping the fresh TaskState."""
    return TaskStateService(task_state)


class TestTaskQuery:
    """Tests for task query operations."""

    async def test_get_task_returns_none_for_missing(self, service):
        """Test get_task returns None when task doesn't exist."""
        result = await service.get_task("nonexistent")
        assert result is None

    async def test_get_task_returns_task_info(self, service, task_state):
        """Test get_task returns TaskInfo for existing task."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Hello, Claude!",
            backend_name="claude",
        )

        result = await service.get_task("exchange-1")

        assert result is not None
        assert isinstance(result, TaskInfo)
        assert result.task_id == "exchange-1"
        assert result.task_type == "chat"
        assert result.status == "streaming"
        assert result.session_id == "session-1"
        assert result.backend_name == "claude"
        assert result.is_active is True

    async def test_get_session_task(self, service, task_state):
        """Test get_session_task returns active task for session."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        result = await service.get_session_task("session-1")

        assert result is not None
        assert result.task_id == "exchange-1"

        # Complete the task
        task_state.complete_task("exchange-1")

        result = await service.get_session_task("session-1")
        assert result is None

    async def test_get_all_tasks(self, service, task_state):
        """Test get_all_tasks returns all tracked tasks."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="First",
            backend_name="claude",
        )
        task_state.register_session_task(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Second",
            backend_name="openrouter",
        )

        result = await service.get_all_tasks()

        assert len(result) == 2
        assert all(isinstance(t, TaskInfo) for t in result)

    async def test_get_active_tasks(self, service, task_state):
        """Test get_active_tasks excludes completed tasks."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="First",
            backend_name="claude",
        )
        task_state.register_session_task(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Second",
            backend_name="claude",
        )
        task_state.complete_task("exchange-1")

        result = await service.get_active_tasks()

        assert len(result) == 1
        assert result[0].task_id == "exchange-2"

    async def test_get_streaming_tasks(self, service, task_state):
        """Test get_streaming_tasks filters by streaming status."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="First",
            backend_name="claude",
        )
        task_state.register_session_task(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Second",
            backend_name="claude",
        )
        # Put one in executing state
        task_state.update_task("exchange-1", status=TaskStatus.EXECUTING, tool_name="Read")

        result = await service.get_streaming_tasks()

        assert len(result) == 1
        assert result[0].task_id == "exchange-2"

    async def test_get_tasks_by_type(self, service, task_state):
        """Test filtering tasks by type."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Chat",
            backend_name="claude",
        )
        task_state.register_helper_task(
            task_id="helper-1",
            task_type=TaskType.COMPRESSION,
            prompt="Compress",
        )

        chat_tasks = await service.get_tasks_by_type("chat")
        assert len(chat_tasks) == 1
        assert chat_tasks[0].task_type == "chat"

        compression_tasks = await service.get_tasks_by_type("compression")
        assert len(compression_tasks) == 1
        assert compression_tasks[0].task_type == "compression"

        # Invalid type returns empty list
        invalid_tasks = await service.get_tasks_by_type("invalid")
        assert len(invalid_tasks) == 0

    async def test_get_tasks_by_session(self, service, task_state):
        """Test filtering tasks by session."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="First",
            backend_name="claude",
        )
        task_state.register_session_task(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Second",
            backend_name="claude",
        )

        result = await service.get_tasks_by_session("session-1")

        assert len(result) == 1
        assert result[0].session_id == "session-1"

    async def test_get_tasks_by_backend(self, service, task_state):
        """Test filtering tasks by backend."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="First",
            backend_name="claude",
        )
        task_state.register_session_task(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Second",
            backend_name="openrouter",
        )

        claude_tasks = await service.get_tasks_by_backend("claude")
        assert len(claude_tasks) == 1
        assert claude_tasks[0].backend_name == "claude"


class TestTaskLifecycle:
    """Tests for task lifecycle operations."""

    async def test_start_session_task(self, service):
        """Test starting a session task via service."""
        result = await service.start_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Hello!",
            backend_name="claude",
        )

        assert isinstance(result, TaskInfo)
        assert result.task_id == "exchange-1"
        assert result.task_type == "chat"
        assert result.status == "streaming"

    async def test_start_helper_task(self, service):
        """Test starting a helper task via service."""
        result = await service.start_helper_task(
            task_id="helper-1",
            task_type="compression",
            prompt="Compressing...",
            session_id="session-1",
            backend_name="claude",
        )

        assert isinstance(result, TaskInfo)
        assert result.task_id == "helper-1"
        assert result.task_type == "compression"

    async def test_start_helper_task_invalid_type(self, service):
        """Test starting helper task with invalid type returns None."""
        result = await service.start_helper_task(
            task_id="helper-1",
            task_type="invalid_type",
            prompt="Test",
        )
        assert result is None

    async def test_update_task_progress(self, service, task_state):
        """Test updating task progress."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        result = await service.update_task_progress(
            task_id="exchange-1",
            tokens_streamed=150,
            input_tokens=500,
            output_tokens=150,
        )

        assert result is not None
        assert result.tokens_streamed == 150
        assert result.input_tokens == 500
        assert result.output_tokens == 150

    async def test_update_task_progress_nonexistent(self, service):
        """Test updating nonexistent task returns None."""
        result = await service.update_task_progress(
            task_id="nonexistent",
            tokens_streamed=100,
        )
        assert result is None

    async def test_set_task_executing(self, service, task_state):
        """Test marking task as executing a tool."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        result = await service.set_task_executing("exchange-1", "Read")

        assert result is not None
        assert result.status == "executing"
        assert result.tool_name == "Read"

    async def test_set_task_streaming(self, service, task_state):
        """Test marking task as streaming (back from tool execution)."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )
        task_state.update_task("exchange-1", status=TaskStatus.EXECUTING, tool_name="Read")

        result = await service.set_task_streaming("exchange-1")

        assert result is not None
        assert result.status == "streaming"
        # Note: tool_name is not cleared by set_task_streaming currently
        # The status change is the important part

    async def test_complete_task(self, service, task_state):
        """Test completing a task."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        result = await service.complete_task("exchange-1")

        assert result is not None
        assert result.status == "completed"
        assert result.is_active is False
        assert result.finished_at is not None

    async def test_fail_task(self, service, task_state):
        """Test failing a task with error."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        result = await service.fail_task("exchange-1", "Rate limit exceeded")

        assert result is not None
        assert result.status == "error"
        assert result.error == "Rate limit exceeded"
        assert result.is_active is False

    async def test_cancel_task(self, service, task_state):
        """Test cancelling a task."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        result = await service.cancel_task("exchange-1")

        assert result is not None
        assert result.status == "cancelled"
        assert result.is_active is False


class TestSummaryOperations:
    """Tests for summary and count operations."""

    async def test_get_streaming_count(self, service, task_state):
        """Test counting streaming tasks."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test 1",
            backend_name="claude",
        )
        task_state.register_session_task(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Test 2",
            backend_name="claude",
        )

        assert await service.get_streaming_count() == 2

        task_state.complete_task("exchange-1")
        assert await service.get_streaming_count() == 1

    async def test_get_active_count(self, service, task_state):
        """Test counting active tasks (including executing)."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test 1",
            backend_name="claude",
        )
        task_state.register_session_task(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Test 2",
            backend_name="claude",
        )
        task_state.update_task("exchange-1", status=TaskStatus.EXECUTING, tool_name="Read")

        assert await service.get_active_count() == 2

        task_state.complete_task("exchange-1")
        assert await service.get_active_count() == 1

    async def test_get_backend_summary(self, service, task_state):
        """Test getting backend usage summary."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test 1",
            backend_name="claude",
        )
        task_state.register_session_task(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Test 2",
            backend_name="claude",
        )
        task_state.register_session_task(
            session_id="session-3",
            exchange_id="exchange-3",
            prompt="Test 3",
            backend_name="openrouter",
        )

        result = await service.get_backend_summary()

        assert isinstance(result, list)
        assert all(isinstance(s, BackendSummary) for s in result)

        # Sort by backend name for consistent testing
        by_name = {s.backend_name: s.active_count for s in result}
        assert by_name["claude"] == 2
        assert by_name["openrouter"] == 1

    async def test_get_session_summary(self, service, task_state):
        """Test getting session task summary."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="First prompt",
            backend_name="claude",
        )

        result = await service.get_session_summary("session-1")

        assert isinstance(result, SessionTaskSummary)
        assert result.session_id == "session-1"
        assert result.is_streaming is True
        assert result.has_active_task is True
        assert result.backend_name == "claude"

        # Complete the task
        task_state.complete_task("exchange-1")

        result = await service.get_session_summary("session-1")
        assert result.is_streaming is False
        assert result.has_active_task is False
        assert result.total_exchanges == 1


class TestCleanup:
    """Tests for cleanup operations."""

    async def test_clear_completed(self, service, task_state):
        """Test clearing completed tasks."""
        from datetime import timedelta

        task = task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )
        task_state.complete_task("exchange-1")

        # Manually backdate the finished_at
        task = task_state.get_task("exchange-1")
        task.finished_at = datetime.now() - timedelta(seconds=400)

        removed = await service.clear_completed(max_age_seconds=300)

        assert removed == 1
        assert await service.get_task("exchange-1") is None


class TestEventHandlers:
    """Tests for WebSocket event handling."""

    async def test_add_event_handler(self, service, task_state):
        """Test adding an event handler."""
        events = []

        def handler(event_name: str, data: dict):
            events.append((event_name, data))

        service.add_event_handler(handler)

        # Register a task - should trigger event via observer
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        # Give async observer time to run
        await asyncio.sleep(0.05)

        assert len(events) == 1
        assert events[0][0] == "taskStarted"
        assert events[0][1]["task_id"] == "exchange-1"

    async def test_remove_event_handler(self, service, task_state):
        """Test removing an event handler."""
        events = []

        def handler(event_name: str, data: dict):
            events.append((event_name, data))

        service.add_event_handler(handler)
        service.remove_event_handler(handler)

        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        await asyncio.sleep(0.05)

        # Handler was removed, should not receive events
        assert len(events) == 0

    async def test_event_types(self, service, task_state):
        """Test different event types are emitted correctly."""
        events = []

        def handler(event_name: str, data: dict):
            events.append(event_name)

        service.add_event_handler(handler)

        # Start task
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )
        await asyncio.sleep(0.02)

        # Update task
        task_state.update_task("exchange-1", tokens_streamed=100)
        await asyncio.sleep(0.02)

        # Complete task
        task_state.complete_task("exchange-1")
        await asyncio.sleep(0.02)

        assert "taskStarted" in events
        assert "taskUpdated" in events
        assert "taskCompleted" in events

    async def test_error_event(self, service, task_state):
        """Test task error event."""
        events = []

        def handler(event_name: str, data: dict):
            events.append((event_name, data))

        service.add_event_handler(handler)

        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )
        task_state.fail_task("exchange-1", "API error")

        await asyncio.sleep(0.05)

        event_names = [e[0] for e in events]
        assert "taskError" in event_names

        # Find the error event and check it has the error info
        error_event = next(e for e in events if e[0] == "taskError")
        assert error_event[1]["error"] == "API error"

    async def test_cancelled_event(self, service, task_state):
        """Test task cancelled event."""
        events = []

        def handler(event_name: str, data: dict):
            events.append(event_name)

        service.add_event_handler(handler)

        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )
        task_state.cancel_task("exchange-1")

        await asyncio.sleep(0.05)

        assert "taskCancelled" in events


class TestTaskInfoConversion:
    """Tests for TaskInfo wire type conversion."""

    async def test_task_info_has_all_fields(self, service, task_state):
        """Test TaskInfo includes all expected fields."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="A very long prompt that should be truncated for display purposes in the UI",
            backend_name="claude",
        )
        task_state.update_task(
            "exchange-1",
            tokens_streamed=100,
            input_tokens=500,
            output_tokens=100,
            context_window=200000,
            model="claude-3-sonnet",
        )

        result = await service.get_task("exchange-1")

        assert result.task_id == "exchange-1"
        assert result.task_type == "chat"
        assert result.status == "streaming"
        assert result.session_id == "session-1"
        assert result.backend_name == "claude"
        assert result.started_at is not None  # ISO format string
        assert result.finished_at is None
        assert len(result.prompt) <= 60  # Truncated
        assert result.tokens_streamed == 100
        assert result.error is None
        assert result.tool_name is None
        assert result.tool_count == 0
        assert result.input_tokens == 500
        assert result.output_tokens == 100
        assert result.context_window == 200000
        assert result.model == "claude-3-sonnet"
        assert result.duration_seconds >= 0
        assert result.is_active is True
        assert result.current_token_rate >= 0


class TestStreamingContentEvents:
    """Tests for streaming content event emission."""

    def test_emit_content_delta(self, service):
        """Test emitting content delta events."""
        events = []

        def handler(event_name: str, data: dict):
            events.append((event_name, data))

        service.add_event_handler(handler)

        service.emit_content_delta(
            session_id="session-1",
            exchange_id="exchange-1",
            turn_index=1,
            delta="Hello",
            accumulated="Hello",
        )

        assert len(events) == 1
        assert events[0][0] == "contentDelta"
        assert events[0][1]["session_id"] == "session-1"
        assert events[0][1]["exchange_id"] == "exchange-1"
        assert events[0][1]["turn_index"] == 1
        assert events[0][1]["delta"] == "Hello"
        assert events[0][1]["accumulated"] == "Hello"

    def test_emit_turn_started(self, service):
        """Test emitting turn started events."""
        events = []

        def handler(event_name: str, data: dict):
            events.append((event_name, data))

        service.add_event_handler(handler)

        service.emit_turn_started(
            session_id="session-1",
            exchange_id="exchange-1",
            turn_index=0,
            role="user",
        )

        assert len(events) == 1
        assert events[0][0] == "turnStarted"
        assert events[0][1]["role"] == "user"
        assert events[0][1]["turn_index"] == 0

    def test_emit_turn_finished(self, service):
        """Test emitting turn finished events."""
        events = []

        def handler(event_name: str, data: dict):
            events.append((event_name, data))

        service.add_event_handler(handler)

        service.emit_turn_finished(
            session_id="session-1",
            exchange_id="exchange-1",
            turn_index=1,
            role="assistant",
            content="Hello, I'm Claude!",
        )

        assert len(events) == 1
        assert events[0][0] == "turnFinished"
        assert events[0][1]["role"] == "assistant"
        assert events[0][1]["content"] == "Hello, I'm Claude!"

    def test_emit_tool_use_started(self, service):
        """Test emitting tool use started events."""
        events = []

        def handler(event_name: str, data: dict):
            events.append((event_name, data))

        service.add_event_handler(handler)

        service.emit_tool_use_started(
            session_id="session-1",
            exchange_id="exchange-1",
            turn_index=2,
            tool_use_id="tool-123",
            tool_name="Read",
            tool_index=0,
        )

        assert len(events) == 1
        assert events[0][0] == "toolUseStarted"
        assert events[0][1]["tool_use_id"] == "tool-123"
        assert events[0][1]["tool_name"] == "Read"
        assert events[0][1]["tool_index"] == 0

    def test_emit_tool_input_delta(self, service):
        """Test emitting tool input delta events."""
        events = []

        def handler(event_name: str, data: dict):
            events.append((event_name, data))

        service.add_event_handler(handler)

        service.emit_tool_input_delta(
            session_id="session-1",
            exchange_id="exchange-1",
            tool_use_id="tool-123",
            partial_json='{"file_path": "/home',
        )

        assert len(events) == 1
        assert events[0][0] == "toolInputDelta"
        assert events[0][1]["tool_use_id"] == "tool-123"
        assert events[0][1]["partial_json"] == '{"file_path": "/home'

    def test_emit_tool_use(self, service):
        """Test emitting tool use (input complete) events."""
        events = []

        def handler(event_name: str, data: dict):
            events.append((event_name, data))

        service.add_event_handler(handler)

        service.emit_tool_use(
            session_id="session-1",
            exchange_id="exchange-1",
            turn_index=2,
            tool_use_id="tool-123",
            tool_name="Read",
            tool_input={"file_path": "/home/user/file.txt"},
            tool_index=0,
        )

        assert len(events) == 1
        assert events[0][0] == "toolUse"
        assert events[0][1]["tool_input"] == {"file_path": "/home/user/file.txt"}

    def test_emit_tool_result(self, service):
        """Test emitting tool result events."""
        events = []

        def handler(event_name: str, data: dict):
            events.append((event_name, data))

        service.add_event_handler(handler)

        service.emit_tool_result(
            session_id="session-1",
            exchange_id="exchange-1",
            turn_index=3,
            tool_use_id="tool-123",
            tool_name="Read",
            result="File contents here...",
            is_error=False,
            tool_index=0,
        )

        assert len(events) == 1
        assert events[0][0] == "toolResult"
        assert events[0][1]["result"] == "File contents here..."
        assert events[0][1]["is_error"] is False

    def test_streaming_content_event_dataclasses(self):
        """Test that streaming event dataclasses have expected fields."""
        # ContentDeltaEvent
        delta = ContentDeltaEvent(
            session_id="s1",
            exchange_id="e1",
            turn_index=1,
            delta="Hello",
            accumulated="Hello World",
        )
        assert delta.delta == "Hello"
        assert delta.accumulated == "Hello World"

        # TurnStartedEvent
        turn_started = TurnStartedEvent(
            session_id="s1",
            exchange_id="e1",
            turn_index=0,
            role="user",
        )
        assert turn_started.role == "user"

        # TurnFinishedEvent
        turn_finished = TurnFinishedEvent(
            session_id="s1",
            exchange_id="e1",
            turn_index=1,
            role="assistant",
            content="Response",
        )
        assert turn_finished.content == "Response"

        # ToolUseStartedEvent
        tool_started = ToolUseStartedEvent(
            session_id="s1",
            exchange_id="e1",
            turn_index=2,
            tool_use_id="t1",
            tool_name="Read",
            tool_index=0,
        )
        assert tool_started.tool_name == "Read"

        # ToolInputDeltaEvent
        tool_delta = ToolInputDeltaEvent(
            session_id="s1",
            exchange_id="e1",
            tool_use_id="t1",
            partial_json='{"key":',
        )
        assert tool_delta.partial_json == '{"key":'

        # ToolUseEvent
        tool_use = ToolUseEvent(
            session_id="s1",
            exchange_id="e1",
            turn_index=2,
            tool_use_id="t1",
            tool_name="Read",
            tool_input={"file_path": "/test"},
            tool_index=0,
        )
        assert tool_use.tool_input == {"file_path": "/test"}

        # ToolResultEvent
        tool_result = ToolResultEvent(
            session_id="s1",
            exchange_id="e1",
            turn_index=3,
            tool_use_id="t1",
            tool_name="Read",
            result="contents",
            is_error=False,
            tool_index=0,
        )
        assert tool_result.result == "contents"
        assert tool_result.is_error is False
