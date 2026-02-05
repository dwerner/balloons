"""Tests for TaskState management."""

import pytest
import asyncio
from datetime import datetime, timedelta

from core.task_state import (
    TaskState,
    Task,
    TaskStatus,
    TaskType,
    TaskEvent,
    SessionTaskInfo,
    get_task_state,
)


@pytest.fixture
def task_state():
    """Get a fresh TaskState for each test."""
    state = TaskState()
    state.clear_all()  # Reset singleton state between tests
    # Reset observers too
    state._observers.clear()
    return state


class TestTaskRegistration:
    """Tests for registering tasks."""

    def test_register_session_task(self, task_state):
        """Test registering a chat task for a session."""
        task = task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Hello, Claude!",
            backend_name="claude",
        )

        assert task.task_id == "exchange-1"
        assert task.task_type == TaskType.CHAT
        assert task.status == TaskStatus.STREAMING
        assert task.session_id == "session-1"
        assert task.backend_name == "claude"
        assert task.prompt == "Hello, Claude!"
        assert task.is_active

    def test_register_helper_task(self, task_state):
        """Test registering a helper task."""
        task = task_state.register_helper_task(
            task_id="helper-1",
            task_type=TaskType.COMPRESSION,
            prompt="Compressing context...",
            session_id="session-1",
            backend_name="claude",
        )

        assert task.task_id == "helper-1"
        assert task.task_type == TaskType.COMPRESSION
        assert task.status == TaskStatus.STREAMING
        assert task.is_active

    def test_register_multiple_tasks(self, task_state):
        """Test registering multiple tasks."""
        task1 = task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="First prompt",
            backend_name="claude",
        )
        task2 = task_state.register_session_task(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Second prompt",
            backend_name="openrouter",
        )

        all_tasks = task_state.get_all_tasks()
        assert len(all_tasks) == 2

        streaming = task_state.get_streaming_tasks()
        assert len(streaming) == 2


class TestTaskUpdates:
    """Tests for updating task state."""

    def test_update_tokens_streamed(self, task_state):
        """Test updating token count."""
        task = task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        task_state.update_task("exchange-1", tokens_streamed=150)

        updated = task_state.get_task("exchange-1")
        assert updated.tokens_streamed == 150

    def test_update_tool_execution(self, task_state):
        """Test updating tool execution state."""
        task = task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        task_state.update_task(
            "exchange-1",
            status=TaskStatus.EXECUTING,
            tool_name="Read",
            tool_count=1,
        )

        updated = task_state.get_task("exchange-1")
        assert updated.status == TaskStatus.EXECUTING
        assert updated.tool_name == "Read"
        assert updated.tool_count == 1
        assert updated.is_active  # Still active during tool execution

    def test_complete_task(self, task_state):
        """Test completing a task."""
        task = task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        completed = task_state.complete_task("exchange-1")

        assert completed.status == TaskStatus.COMPLETED
        assert completed.finished_at is not None
        assert not completed.is_active

    def test_fail_task(self, task_state):
        """Test marking a task as failed."""
        task = task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        failed = task_state.fail_task("exchange-1", "Rate limit exceeded")

        assert failed.status == TaskStatus.ERROR
        assert failed.error == "Rate limit exceeded"
        assert not failed.is_active

    def test_cancel_task(self, task_state):
        """Test cancelling a task."""
        task = task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        cancelled = task_state.cancel_task("exchange-1")

        assert cancelled.status == TaskStatus.CANCELLED
        assert not cancelled.is_active


class TestTaskQueries:
    """Tests for querying tasks."""

    def test_get_session_task(self, task_state):
        """Test getting the active task for a session."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        active = task_state.get_session_task("session-1")
        assert active is not None
        assert active.task_id == "exchange-1"

        # After completion, should return None
        task_state.complete_task("exchange-1")
        active = task_state.get_session_task("session-1")
        assert active is None

    def test_get_active_tasks(self, task_state):
        """Test getting all active tasks."""
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

        # Complete one
        task_state.complete_task("exchange-1")

        active = task_state.get_active_tasks()
        assert len(active) == 1
        assert active[0].task_id == "exchange-2"

    def test_get_tasks_by_type(self, task_state):
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

        chat_tasks = task_state.get_tasks_by_type(TaskType.CHAT)
        assert len(chat_tasks) == 1

        compression_tasks = task_state.get_tasks_by_type(TaskType.COMPRESSION)
        assert len(compression_tasks) == 1

    def test_get_tasks_by_backend(self, task_state):
        """Test filtering tasks by backend."""
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
            backend_name="openrouter",
        )

        claude_tasks = task_state.get_tasks_by_backend("claude")
        assert len(claude_tasks) == 1
        assert claude_tasks[0].task_id == "exchange-1"


class TestSummaryMethods:
    """Tests for summary and count methods."""

    def test_get_streaming_count(self, task_state):
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

        assert task_state.get_streaming_count() == 2

        task_state.complete_task("exchange-1")
        assert task_state.get_streaming_count() == 1

    def test_get_backend_summary(self, task_state):
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

        summary = task_state.get_backend_summary()
        assert summary["claude"] == 2
        assert summary["openrouter"] == 1

    def test_get_session_summary(self, task_state):
        """Test getting session task summary."""
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="First prompt",
            backend_name="claude",
        )

        summary = task_state.get_session_summary("session-1")

        assert summary.session_id == "session-1"
        assert summary.is_streaming
        assert summary.current_task is not None
        assert summary.backend_name == "claude"

        # Complete the task
        task_state.complete_task("exchange-1")

        summary = task_state.get_session_summary("session-1")
        assert not summary.is_streaming
        assert summary.current_task is None
        assert summary.total_exchanges == 1


class TestObservers:
    """Tests for the observer pattern."""

    async def test_async_observer_receives_events(self, task_state):
        """Test that async observers receive task events."""
        events_received = []

        async def observer(event: TaskEvent, task: Task):
            events_received.append((event, task.task_id))

        task_state.add_observer(observer)

        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        # Give event loop time to process
        await asyncio.sleep(0.01)

        assert len(events_received) == 1
        assert events_received[0][0] == TaskEvent.TASK_STARTED
        assert events_received[0][1] == "exchange-1"

        task_state.complete_task("exchange-1")
        await asyncio.sleep(0.01)

        assert len(events_received) == 2
        assert events_received[1][0] == TaskEvent.TASK_COMPLETED

    async def test_remove_observer(self, task_state):
        """Test removing an observer."""
        events_received = []

        async def observer(event: TaskEvent, task: Task):
            events_received.append(event)

        task_state.add_observer(observer)
        task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )
        await asyncio.sleep(0.01)
        assert len(events_received) == 1

        task_state.remove_observer(observer)
        task_state.complete_task("exchange-1")
        await asyncio.sleep(0.01)
        assert len(events_received) == 1  # No new events


class TestCleanup:
    """Tests for cleanup methods."""

    def test_clear_completed_old_tasks(self, task_state):
        """Test clearing old completed tasks."""
        task = task_state.register_session_task(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )
        task_state.complete_task("exchange-1")

        # Manually set finished_at to simulate old task
        task = task_state.get_task("exchange-1")
        task.finished_at = datetime.now() - timedelta(seconds=400)

        # Clear tasks older than 300 seconds
        removed = task_state.clear_completed(max_age_seconds=300)

        assert removed == 1
        assert task_state.get_task("exchange-1") is None

    def test_clear_all(self, task_state):
        """Test clearing all tasks."""
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

        task_state.clear_all()

        assert len(task_state.get_all_tasks()) == 0


class TestTaskProperties:
    """Tests for Task dataclass properties."""

    def test_short_prompt(self):
        """Test prompt truncation."""
        short_task = Task(
            task_id="1",
            task_type=TaskType.CHAT,
            prompt="Short prompt",
        )
        assert short_task.short_prompt == "Short prompt"

        long_prompt = "A" * 100
        long_task = Task(
            task_id="2",
            task_type=TaskType.CHAT,
            prompt=long_prompt,
        )
        assert len(long_task.short_prompt) == 60
        assert long_task.short_prompt.endswith("...")

    def test_duration_seconds(self):
        """Test duration calculation."""
        task = Task(
            task_id="1",
            task_type=TaskType.CHAT,
            started_at=datetime.now() - timedelta(seconds=10),
        )

        # Should be approximately 10 seconds (allow for test execution time)
        assert 9 <= task.duration_seconds <= 12


class TestSingleton:
    """Tests for singleton behavior."""

    def test_get_task_state_returns_singleton(self):
        """Test that get_task_state returns the same instance."""
        state1 = get_task_state()
        state2 = get_task_state()
        assert state1 is state2

    def test_taskstate_is_singleton(self):
        """Test that TaskState() returns the same instance."""
        state1 = TaskState()
        state2 = TaskState()
        assert state1 is state2
