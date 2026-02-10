"""Task state management for Balloons.

This module provides a centralized view of all active LLM tasks across sessions.
It tracks streaming sessions, helper tasks (summaries, compression), and their states.

This is the "model" layer - it doesn't interact with UI, just provides data about
what's happening. The UI can poll or observe this to update displays.

Concepts:
    - Task: Any in-flight LLM interaction (chat exchange, summary generation, etc.)
    - Session Task: A chat exchange within a session (user prompt -> assistant response)
    - Helper Task: A background LLM task (compression, merge summary, link summary)

Usage:
    # Get the global task state
    task_state = get_task_state()

    # Register a new streaming task (updates state, schedules observer notification)
    task_state.register_session_task(
        session_id="abc123",
        exchange_id="def456",
        prompt="Tell me about...",
        backend_name="claude",
    )

    # Update task status
    task_state.update_task(
        task_id="def456",
        status=TaskStatus.STREAMING,
        tokens_streamed=150,
    )

    # Query active tasks (sync - just reads in-memory state)
    all_tasks = task_state.get_all_tasks()
    streaming = task_state.get_streaming_tasks()

    # Subscribe to events (async observers only)
    async def on_task_event(event: TaskEvent, task: Task):
        print(f"Task {task.task_id}: {event}")

    task_state.add_observer(on_task_event)
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Awaitable


class TaskStatus(Enum):
    """Status of a task."""
    PENDING = "pending"      # Task created but not yet started
    STREAMING = "streaming"  # Actively receiving tokens from LLM
    EXECUTING = "executing"  # Tool is executing (between LLM responses)
    COMPLETED = "completed"  # Task finished successfully
    ERROR = "error"          # Task failed with an error
    CANCELLED = "cancelled"  # Task was cancelled by user


class TaskType(Enum):
    """Type of task."""
    CHAT = "chat"                # Normal chat exchange (user -> assistant)
    COMPRESSION = "compression"  # Context compression (for forking)
    MERGE_SUMMARY = "merge"      # Merge summary generation
    LINK_SUMMARY = "link"        # Link summary generation
    ARCHIVE_SUMMARY = "archive"  # Archive summary generation
    TITLE = "title"              # Session title generation


@dataclass
class Task:
    """A single LLM task.

    Attributes:
        task_id: Unique identifier for this task (often exchange_id for chats)
        task_type: What kind of task this is
        status: Current status of the task
        session_id: Associated session (if any)
        backend_name: Which backend is handling this task
        started_at: When the task started
        finished_at: When the task completed (if done)
        prompt: The prompt that started this task (truncated for display)
        tokens_streamed: Number of tokens received so far
        error: Error message if status is ERROR
        tool_name: Name of tool currently executing (if EXECUTING status)
        tool_count: Number of tools executed so far in this exchange
        token_samples: Recent (timestamp, token_count) samples for rate calculation
    """
    task_id: str
    task_type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    session_id: Optional[str] = None
    backend_name: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    prompt: str = ""  # Truncated for display
    tokens_streamed: int = 0  # Estimated output tokens (chars/4)
    error: Optional[str] = None
    tool_name: Optional[str] = None  # Currently executing tool
    tool_count: int = 0  # Tools executed in this exchange
    # Actual token counts from API
    input_tokens: int = 0  # Context/input tokens
    output_tokens: int = 0  # Generated output tokens
    context_window: int = 0  # Model's context window size
    model: str = ""  # Model name
    # Token rate tracking: list of (timestamp, cumulative_tokens) samples
    # Keep last 20 samples for sparkline (about 2 seconds at 10 updates/sec)
    token_samples: list[tuple[float, int]] = field(default_factory=list)
    _max_samples: int = field(default=20, repr=False)

    @property
    def duration_seconds(self) -> float:
        """Get task duration in seconds."""
        end = self.finished_at or datetime.now()
        return (end - self.started_at).total_seconds()

    @property
    def is_active(self) -> bool:
        """Check if task is still in progress."""
        return self.status in (TaskStatus.PENDING, TaskStatus.STREAMING, TaskStatus.EXECUTING)

    @property
    def short_prompt(self) -> str:
        """Get a shortened version of the prompt for display."""
        if len(self.prompt) <= 60:
            return self.prompt
        return self.prompt[:57] + "..."

    def add_token_sample(self, tokens: int) -> None:
        """Record a token sample for rate calculation."""
        import time
        now = time.monotonic()
        self.token_samples.append((now, tokens))
        # Keep only recent samples
        if len(self.token_samples) > self._max_samples:
            self.token_samples = self.token_samples[-self._max_samples:]

    def get_token_rates(self) -> list[float]:
        """Get token rates (tokens/sec) between each sample.

        Returns list of rates for sparkline display.
        """
        if len(self.token_samples) < 2:
            return []

        rates = []
        for i in range(1, len(self.token_samples)):
            prev_time, prev_tokens = self.token_samples[i - 1]
            curr_time, curr_tokens = self.token_samples[i]
            dt = curr_time - prev_time
            if dt > 0:
                rate = (curr_tokens - prev_tokens) / dt
                rates.append(rate)
        return rates

    @property
    def current_token_rate(self) -> float:
        """Get current token rate (tokens/sec) based on recent samples."""
        if len(self.token_samples) < 2:
            return 0.0
        # Use last few samples for smoother average
        samples = self.token_samples[-5:] if len(self.token_samples) >= 5 else self.token_samples
        if len(samples) < 2:
            return 0.0
        first_time, first_tokens = samples[0]
        last_time, last_tokens = samples[-1]
        dt = last_time - first_time
        if dt > 0:
            return (last_tokens - first_tokens) / dt
        return 0.0


@dataclass
class SessionTaskInfo:
    """Summary of task activity for a session.

    Provides a quick overview of what's happening in a session.
    """
    session_id: str
    session_title: str = ""
    backend_name: str = ""
    is_streaming: bool = False
    current_task: Optional[Task] = None
    total_exchanges: int = 0  # Number of completed exchanges
    last_activity: Optional[datetime] = None


class TaskEvent(Enum):
    """Events emitted by TaskState."""
    TASK_STARTED = "task_started"
    TASK_UPDATED = "task_updated"  # Status change, tokens updated, etc.
    TASK_COMPLETED = "task_completed"
    TASK_ERROR = "task_error"
    TASK_CANCELLED = "task_cancelled"


# Type alias for async observer callbacks
AsyncObserver = Callable[[TaskEvent, Task], Awaitable[None]]


class TaskState:
    """Centralized state for all LLM tasks.

    Singleton pattern - there's one TaskState for the application.

    All mutation methods are synchronous for easy use from any code path.
    Observer notifications are scheduled on the event loop asynchronously.
    Query methods are sync since they just read in-memory state.
    """

    _instance: "TaskState | None" = None

    def __new__(cls) -> "TaskState":
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize task state (only runs once due to singleton)."""
        if self._initialized:
            return
        self._initialized = True

        # Task storage
        self._tasks: dict[str, Task] = {}  # task_id -> Task

        # Session tracking (session_id -> current task_id)
        self._session_tasks: dict[str, str] = {}

        # Async observers for state changes
        self._observers: list[AsyncObserver] = []

    # =========================================================================
    # Observer Pattern
    # =========================================================================

    def add_observer(self, callback: AsyncObserver) -> None:
        """Add an async observer for task state changes.

        Args:
            callback: Async function called with (event_type, task) on changes
        """
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: AsyncObserver) -> None:
        """Remove an observer."""
        if callback in self._observers:
            self._observers.remove(callback)

    def _schedule_notification(self, event: TaskEvent, task: Task) -> None:
        """Schedule async observer notifications on the event loop.

        This is called from sync methods and schedules the async callbacks
        to run on the event loop without blocking.
        """
        if not self._observers:
            return

        for callback in self._observers:
            # Create a task for each observer
            asyncio.ensure_future(self._call_observer(callback, event, task))

    async def _call_observer(self, callback: AsyncObserver, event: TaskEvent, task: Task) -> None:
        """Safely call an async observer."""
        try:
            await callback(event, task)
        except Exception:
            pass  # Don't let observer errors break task tracking

    # =========================================================================
    # Task Registration
    # =========================================================================

    def register_session_task(
        self,
        session_id: str,
        exchange_id: str,
        prompt: str,
        backend_name: str = "",
    ) -> Task:
        """Register a new chat task for a session.

        Args:
            session_id: The session this task belongs to
            exchange_id: Unique ID for this exchange
            prompt: The user's prompt
            backend_name: Which backend is handling this

        Returns:
            The created Task
        """
        task = Task(
            task_id=exchange_id,
            task_type=TaskType.CHAT,
            status=TaskStatus.STREAMING,
            session_id=session_id,
            backend_name=backend_name,
            prompt=prompt,
        )

        self._tasks[exchange_id] = task
        self._session_tasks[session_id] = exchange_id

        self._schedule_notification(TaskEvent.TASK_STARTED, task)
        return task

    def register_helper_task(
        self,
        task_id: str,
        task_type: TaskType,
        prompt: str = "",
        session_id: Optional[str] = None,
        backend_name: str = "",
    ) -> Task:
        """Register a helper task (compression, summary, etc.).

        Args:
            task_id: Unique ID for this task
            task_type: Type of helper task
            prompt: Description of what's being done
            session_id: Associated session (if any)
            backend_name: Which backend is handling this

        Returns:
            The created Task
        """
        task = Task(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.STREAMING,
            session_id=session_id,
            backend_name=backend_name,
            prompt=prompt,
        )

        self._tasks[task_id] = task

        self._schedule_notification(TaskEvent.TASK_STARTED, task)
        return task

    # =========================================================================
    # Task Updates
    # =========================================================================

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        tokens_streamed: Optional[int] = None,
        tool_name: Optional[str] = None,
        tool_count: Optional[int] = None,
        error: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        context_window: Optional[int] = None,
        model: Optional[str] = None,
    ) -> Optional[Task]:
        """Update a task's status.

        Args:
            task_id: Task to update
            status: New status (if changing)
            tokens_streamed: Updated estimated token count
            tool_name: Currently executing tool name
            tool_count: Updated tool count
            error: Error message (if status is ERROR)
            input_tokens: Actual input token count from API
            output_tokens: Actual output token count from API
            context_window: Model's context window size
            model: Model name

        Returns:
            Updated task, or None if task not found
        """
        task = self._tasks.get(task_id)
        if not task:
            return None

        # Update fields
        if status is not None:
            task.status = status
            if status in (TaskStatus.COMPLETED, TaskStatus.ERROR, TaskStatus.CANCELLED):
                task.finished_at = datetime.now()

        if tokens_streamed is not None:
            task.tokens_streamed = tokens_streamed
            # Record sample for rate tracking
            task.add_token_sample(tokens_streamed)

        if tool_name is not None:
            task.tool_name = tool_name

        if tool_count is not None:
            task.tool_count = tool_count

        if error is not None:
            task.error = error

        if input_tokens is not None:
            task.input_tokens = input_tokens

        if output_tokens is not None:
            task.output_tokens = output_tokens
            # Also record for rate tracking (actual tokens are better than estimates)
            task.add_token_sample(output_tokens)

        if context_window is not None:
            task.context_window = context_window

        if model is not None:
            task.model = model

        # Schedule appropriate event notification
        if status == TaskStatus.COMPLETED:
            self._schedule_notification(TaskEvent.TASK_COMPLETED, task)
        elif status == TaskStatus.ERROR:
            self._schedule_notification(TaskEvent.TASK_ERROR, task)
        elif status == TaskStatus.CANCELLED:
            self._schedule_notification(TaskEvent.TASK_CANCELLED, task)
        else:
            self._schedule_notification(TaskEvent.TASK_UPDATED, task)

        return task

    def complete_task(self, task_id: str) -> Optional[Task]:
        """Mark a task as completed.

        Args:
            task_id: Task to complete

        Returns:
            Completed task, or None if not found
        """
        return self.update_task(task_id, status=TaskStatus.COMPLETED)

    def fail_task(self, task_id: str, error: str) -> Optional[Task]:
        """Mark a task as failed.

        Args:
            task_id: Task that failed
            error: Error message

        Returns:
            Failed task, or None if not found
        """
        return self.update_task(task_id, status=TaskStatus.ERROR, error=error)

    def cancel_task(self, task_id: str) -> Optional[Task]:
        """Mark a task as cancelled.

        Args:
            task_id: Task to cancel

        Returns:
            Cancelled task, or None if not found
        """
        return self.update_task(task_id, status=TaskStatus.CANCELLED)

    # =========================================================================
    # Query Methods (Sync - just read in-memory state)
    # =========================================================================

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID.

        Args:
            task_id: Task ID to look up

        Returns:
            Task if found, None otherwise
        """
        return self._tasks.get(task_id)

    def get_session_task(self, session_id: str) -> Optional[Task]:
        """Get the current active task for a session.

        Args:
            session_id: Session to look up

        Returns:
            Current task for session, or None if no active task
        """
        task_id = self._session_tasks.get(session_id)
        if task_id:
            task = self._tasks.get(task_id)
            if task and task.is_active:
                return task
        return None

    def get_all_tasks(self) -> list[Task]:
        """Get all tracked tasks (active and recent).

        Returns:
            List of all tasks, sorted by start time (newest first)
        """
        return sorted(
            self._tasks.values(),
            key=lambda t: t.started_at,
            reverse=True,
        )

    def get_active_tasks(self) -> list[Task]:
        """Get all active tasks (pending, streaming, or executing).

        Returns:
            List of active tasks
        """
        return [t for t in self._tasks.values() if t.is_active]

    def get_streaming_tasks(self) -> list[Task]:
        """Get all tasks currently streaming.

        Returns:
            List of tasks with STREAMING status
        """
        return [t for t in self._tasks.values() if t.status == TaskStatus.STREAMING]

    def get_tasks_by_type(self, task_type: TaskType) -> list[Task]:
        """Get all tasks of a specific type.

        Args:
            task_type: Type to filter by

        Returns:
            List of matching tasks
        """
        return [t for t in self._tasks.values() if t.task_type == task_type]

    def get_tasks_by_session(self, session_id: str) -> list[Task]:
        """Get all tasks for a session (active and completed).

        Args:
            session_id: Session to look up

        Returns:
            List of tasks for the session
        """
        return [t for t in self._tasks.values() if t.session_id == session_id]

    def get_tasks_by_backend(self, backend_name: str) -> list[Task]:
        """Get all active tasks using a specific backend.

        Args:
            backend_name: Backend to filter by

        Returns:
            List of active tasks using that backend
        """
        return [
            t for t in self._tasks.values()
            if t.backend_name == backend_name and t.is_active
        ]

    # =========================================================================
    # Summary Methods (Sync)
    # =========================================================================

    def get_streaming_count(self) -> int:
        """Get count of tasks currently streaming.

        Returns:
            Number of tasks with STREAMING status
        """
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.STREAMING)

    def get_active_count(self) -> int:
        """Get count of all active tasks.

        Returns:
            Number of active tasks (pending, streaming, executing)
        """
        return sum(1 for t in self._tasks.values() if t.is_active)

    def get_backend_summary(self) -> dict[str, int]:
        """Get count of active tasks per backend.

        Returns:
            Dict of backend_name -> active task count
        """
        summary = {}
        for task in self._tasks.values():
            if task.is_active and task.backend_name:
                summary[task.backend_name] = summary.get(task.backend_name, 0) + 1
        return summary

    def get_session_summary(self, session_id: str) -> SessionTaskInfo:
        """Get task summary for a session.

        Args:
            session_id: Session to summarize

        Returns:
            SessionTaskInfo with current state
        """
        session_tasks = self.get_tasks_by_session(session_id)
        current_task = self.get_session_task(session_id)

        completed_chats = sum(
            1 for t in session_tasks
            if t.task_type == TaskType.CHAT and t.status == TaskStatus.COMPLETED
        )

        last_activity = None
        if session_tasks:
            last_activity = max(
                t.finished_at or t.started_at
                for t in session_tasks
            )

        backend_name = ""
        if current_task:
            backend_name = current_task.backend_name
        elif session_tasks:
            # Use most recent task's backend
            recent = max(session_tasks, key=lambda t: t.started_at)
            backend_name = recent.backend_name

        return SessionTaskInfo(
            session_id=session_id,
            backend_name=backend_name,
            is_streaming=current_task is not None and current_task.status == TaskStatus.STREAMING,
            current_task=current_task,
            total_exchanges=completed_chats,
            last_activity=last_activity,
        )

    # =========================================================================
    # Cleanup
    # =========================================================================

    def clear_completed(self, max_age_seconds: float = 300) -> int:
        """Remove completed tasks older than max_age_seconds.

        Args:
            max_age_seconds: Maximum age in seconds to keep completed tasks

        Returns:
            Number of tasks removed
        """
        now = datetime.now()
        to_remove = []

        for task_id, task in self._tasks.items():
            if not task.is_active and task.finished_at:
                age = (now - task.finished_at).total_seconds()
                if age > max_age_seconds:
                    to_remove.append(task_id)

        for task_id in to_remove:
            del self._tasks[task_id]

        # Also clean up session task references
        self._session_tasks = {
            sid: tid
            for sid, tid in self._session_tasks.items()
            if tid in self._tasks
        }

        return len(to_remove)

    def clear_all(self) -> None:
        """Clear all task state. Use for testing or reset."""
        self._tasks.clear()
        self._session_tasks.clear()


# Convenience function to get the singleton
def get_task_state() -> TaskState:
    """Get the global TaskState instance."""
    return TaskState()
