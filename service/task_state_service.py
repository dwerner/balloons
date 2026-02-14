"""WebSocket-exposed service for task state management.

This service wraps TaskState and exposes its functionality via WebSocket RPC.
The @ws_expose decorators mark methods for client generation.

Example usage:
    task_state = TaskState()
    service = TaskStateService(task_state)

    # Service methods are called via WebSocket RPC:
    # {"id": "1", "method": "getActiveTasks", "params": {}}
    # -> {"id": "1", "result": [{"taskId": "abc", "status": "streaming", ...}]}

    # Events are pushed to subscribed clients:
    # {"event": "taskStarted", "data": {"taskId": "abc", "taskType": "chat"}}
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

from codegen import ws_service, ws_expose, ws_event, ws_type
from core.task_state import (
    TaskState,
    Task,
    TaskEvent,
    TaskStatus,
    TaskType,
    SessionTaskInfo,
)


@ws_type
@dataclass
class TaskInfo:
    """Task information for WebSocket exposure.

    Lightweight view of a Task for sending over the wire.
    """

    task_id: str
    task_type: str  # TaskType enum value
    status: str  # TaskStatus enum value
    session_id: str | None
    backend_name: str
    started_at: str  # ISO format
    finished_at: str | None  # ISO format or None
    prompt: str  # Truncated for display
    tokens_streamed: int
    error: str | None
    tool_name: str | None
    tool_count: int
    input_tokens: int
    output_tokens: int
    context_window: int
    model: str
    duration_seconds: float
    is_active: bool
    current_token_rate: float


@ws_type
@dataclass
class SessionTaskSummary:
    """Summary of task activity for a session."""

    session_id: str
    session_title: str
    backend_name: str
    is_streaming: bool
    has_active_task: bool
    total_exchanges: int
    last_activity: str | None  # ISO format


@ws_type
@dataclass
class TaskEventData:
    """Event payload for task state changes."""

    event_type: str  # Maps to TaskEvent enum value
    task_id: str
    task_type: str
    status: str
    session_id: str | None = None
    error: str | None = None
    data: dict = field(default_factory=dict)


@ws_type
@dataclass
class BackendSummary:
    """Summary of active tasks per backend."""

    backend_name: str
    active_count: int


def _task_to_info(task: Task) -> TaskInfo:
    """Convert internal Task to wire-format TaskInfo."""
    return TaskInfo(
        task_id=task.task_id,
        task_type=task.task_type.value,
        status=task.status.value,
        session_id=task.session_id,
        backend_name=task.backend_name,
        started_at=task.started_at.isoformat(),
        finished_at=task.finished_at.isoformat() if task.finished_at else None,
        prompt=task.short_prompt,
        tokens_streamed=task.tokens_streamed,
        error=task.error,
        tool_name=task.tool_name,
        tool_count=task.tool_count,
        input_tokens=task.input_tokens,
        output_tokens=task.output_tokens,
        context_window=task.context_window,
        model=task.model,
        duration_seconds=task.duration_seconds,
        is_active=task.is_active,
        current_token_rate=task.current_token_rate,
    )


def _session_summary_to_wire(info: SessionTaskInfo) -> SessionTaskSummary:
    """Convert internal SessionTaskInfo to wire format."""
    return SessionTaskSummary(
        session_id=info.session_id,
        session_title=info.session_title,
        backend_name=info.backend_name,
        is_streaming=info.is_streaming,
        has_active_task=info.current_task is not None,
        total_exchanges=info.total_exchanges,
        last_activity=info.last_activity.isoformat() if info.last_activity else None,
    )


@ws_service
class TaskStateService:
    """WebSocket-exposed service for task state management.

    Provides access to LLM task lifecycle information including:
    - Active and completed tasks
    - Task status updates (streaming, executing, completed, error)
    - Session-level task summaries
    - Backend usage statistics

    All tasks are in-memory only and are not persisted across restarts.
    """

    def __init__(self, task_state: TaskState):
        """Initialize service with a TaskState instance.

        Args:
            task_state: The TaskState singleton to expose via WebSocket
        """
        self._state = task_state
        self._event_handlers: list[Callable[[str, dict], None]] = []

        # Wire up TaskState observer to emit WebSocket events
        # Note: TaskState uses async observers, so we create an async wrapper
        self._state.add_observer(self._on_task_event)

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Register a handler for WebSocket events.

        The handler will be called with (event_name, data) for each event.
        """
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    async def _on_task_event(self, event: TaskEvent, task: Task) -> None:
        """Convert TaskState events to WebSocket events."""
        # Map TaskEvent enum to camelCase wire name
        event_name = self._task_event_to_wire_name(event)

        # Create event data
        event_data = TaskEventData(
            event_type=event.value,
            task_id=task.task_id,
            task_type=task.task_type.value,
            status=task.status.value,
            session_id=task.session_id,
            error=task.error,
            data={
                "tokensStreamed": task.tokens_streamed,
                "toolName": task.tool_name,
                "toolCount": task.tool_count,
                "inputTokens": task.input_tokens,
                "outputTokens": task.output_tokens,
            },
        )

        # Emit to all registered handlers
        for handler in self._event_handlers:
            handler(event_name, event_data.__dict__)

    def _task_event_to_wire_name(self, event: TaskEvent) -> str:
        """Convert TaskEvent enum to camelCase wire name."""
        # TaskEvent.TASK_STARTED -> "taskStarted"
        parts = event.value.split("_")
        return parts[0] + "".join(p.title() for p in parts[1:])

    # --- Task Query Operations ---

    @ws_expose
    async def get_task(self, task_id: str) -> TaskInfo | None:
        """Get a task by ID.

        Args:
            task_id: The task ID to look up

        Returns:
            Task info if found, None otherwise
        """
        task = self._state.get_task(task_id)
        if not task:
            return None
        return _task_to_info(task)

    @ws_expose
    async def get_session_task(self, session_id: str) -> TaskInfo | None:
        """Get the current active task for a session.

        Args:
            session_id: The session ID to look up

        Returns:
            Current active task info, or None if no active task
        """
        task = self._state.get_session_task(session_id)
        if not task:
            return None
        return _task_to_info(task)

    @ws_expose
    async def get_all_tasks(self) -> list[TaskInfo]:
        """Get all tracked tasks (active and recent).

        Returns:
            List of all tasks, sorted by start time (newest first)
        """
        return [_task_to_info(t) for t in self._state.get_all_tasks()]

    @ws_expose
    async def get_active_tasks(self) -> list[TaskInfo]:
        """Get all active tasks (pending, streaming, or executing).

        Returns:
            List of active tasks
        """
        return [_task_to_info(t) for t in self._state.get_active_tasks()]

    @ws_expose
    async def get_streaming_tasks(self) -> list[TaskInfo]:
        """Get all tasks currently streaming.

        Returns:
            List of tasks with STREAMING status
        """
        return [_task_to_info(t) for t in self._state.get_streaming_tasks()]

    @ws_expose
    async def get_tasks_by_type(self, task_type: str) -> list[TaskInfo]:
        """Get all tasks of a specific type.

        Args:
            task_type: Task type string (chat, compression, merge, link, archive, title, report)

        Returns:
            List of matching tasks
        """
        try:
            tt = TaskType(task_type)
        except ValueError:
            return []
        return [_task_to_info(t) for t in self._state.get_tasks_by_type(tt)]

    @ws_expose
    async def get_tasks_by_session(self, session_id: str) -> list[TaskInfo]:
        """Get all tasks for a session (active and completed).

        Args:
            session_id: Session ID to look up

        Returns:
            List of tasks for the session
        """
        return [_task_to_info(t) for t in self._state.get_tasks_by_session(session_id)]

    @ws_expose
    async def get_tasks_by_backend(self, backend_name: str) -> list[TaskInfo]:
        """Get all active tasks using a specific backend.

        Args:
            backend_name: Backend to filter by (e.g., "claude", "openrouter")

        Returns:
            List of active tasks using that backend
        """
        return [_task_to_info(t) for t in self._state.get_tasks_by_backend(backend_name)]

    # --- Task Lifecycle Operations ---

    @ws_expose
    async def start_session_task(
        self,
        session_id: str,
        exchange_id: str,
        prompt: str,
        backend_name: str = "",
    ) -> TaskInfo:
        """Register a new chat task for a session.

        Args:
            session_id: The session this task belongs to
            exchange_id: Unique ID for this exchange (used as task_id)
            prompt: The user's prompt
            backend_name: Which backend is handling this

        Returns:
            The created task info
        """
        task = self._state.register_session_task(
            session_id=session_id,
            exchange_id=exchange_id,
            prompt=prompt,
            backend_name=backend_name,
        )
        return _task_to_info(task)

    @ws_expose
    async def start_helper_task(
        self,
        task_id: str,
        task_type: str,
        prompt: str = "",
        session_id: str | None = None,
        backend_name: str = "",
    ) -> TaskInfo | None:
        """Register a helper task (compression, summary, etc.).

        Args:
            task_id: Unique ID for this task
            task_type: Type of helper task (compression, merge, link, archive, title, report)
            prompt: Description of what's being done
            session_id: Associated session (if any)
            backend_name: Which backend is handling this

        Returns:
            The created task info, or None if invalid task_type
        """
        try:
            tt = TaskType(task_type)
        except ValueError:
            return None

        task = self._state.register_helper_task(
            task_id=task_id,
            task_type=tt,
            prompt=prompt,
            session_id=session_id,
            backend_name=backend_name,
        )
        return _task_to_info(task)

    @ws_expose
    async def update_task_progress(
        self,
        task_id: str,
        tokens_streamed: int | None = None,
        tool_name: str | None = None,
        tool_count: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        context_window: int | None = None,
        model: str | None = None,
    ) -> TaskInfo | None:
        """Update a task's progress (tokens, tool execution, etc.).

        Args:
            task_id: Task to update
            tokens_streamed: Updated estimated token count
            tool_name: Currently executing tool name
            tool_count: Updated tool count
            input_tokens: Actual input token count from API
            output_tokens: Actual output token count from API
            context_window: Model's context window size
            model: Model name

        Returns:
            Updated task info, or None if task not found
        """
        task = self._state.update_task(
            task_id,
            tokens_streamed=tokens_streamed,
            tool_name=tool_name,
            tool_count=tool_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            context_window=context_window,
            model=model,
        )
        if not task:
            return None
        return _task_to_info(task)

    @ws_expose
    async def set_task_executing(self, task_id: str, tool_name: str) -> TaskInfo | None:
        """Mark a task as executing a tool.

        Args:
            task_id: Task that is executing
            tool_name: Name of the tool being executed

        Returns:
            Updated task info, or None if task not found
        """
        task = self._state.update_task(
            task_id,
            status=TaskStatus.EXECUTING,
            tool_name=tool_name,
        )
        if not task:
            return None
        return _task_to_info(task)

    @ws_expose
    async def set_task_streaming(self, task_id: str) -> TaskInfo | None:
        """Mark a task as streaming (back from tool execution).

        Args:
            task_id: Task that is streaming

        Returns:
            Updated task info, or None if task not found
        """
        task = self._state.update_task(
            task_id,
            status=TaskStatus.STREAMING,
            tool_name=None,
        )
        if not task:
            return None
        return _task_to_info(task)

    @ws_expose
    async def complete_task(self, task_id: str) -> TaskInfo | None:
        """Mark a task as completed successfully.

        Args:
            task_id: Task to complete

        Returns:
            Completed task info, or None if task not found
        """
        task = self._state.complete_task(task_id)
        if not task:
            return None
        return _task_to_info(task)

    @ws_expose
    async def fail_task(self, task_id: str, error: str) -> TaskInfo | None:
        """Mark a task as failed with an error.

        Args:
            task_id: Task that failed
            error: Error message

        Returns:
            Failed task info, or None if task not found
        """
        task = self._state.fail_task(task_id, error)
        if not task:
            return None
        return _task_to_info(task)

    @ws_expose
    async def cancel_task(self, task_id: str) -> TaskInfo | None:
        """Mark a task as cancelled by user.

        Args:
            task_id: Task to cancel

        Returns:
            Cancelled task info, or None if task not found
        """
        task = self._state.cancel_task(task_id)
        if not task:
            return None
        return _task_to_info(task)

    # --- Summary Operations ---

    @ws_expose
    async def get_streaming_count(self) -> int:
        """Get count of tasks currently streaming.

        Returns:
            Number of tasks with STREAMING status
        """
        return self._state.get_streaming_count()

    @ws_expose
    async def get_active_count(self) -> int:
        """Get count of all active tasks.

        Returns:
            Number of active tasks (pending, streaming, executing)
        """
        return self._state.get_active_count()

    @ws_expose
    async def get_backend_summary(self) -> list[BackendSummary]:
        """Get count of active tasks per backend.

        Returns:
            List of backend summaries with active task counts
        """
        summary = self._state.get_backend_summary()
        return [
            BackendSummary(backend_name=name, active_count=count)
            for name, count in summary.items()
        ]

    @ws_expose
    async def get_session_summary(self, session_id: str) -> SessionTaskSummary:
        """Get task summary for a session.

        Args:
            session_id: Session to summarize

        Returns:
            Session task summary with current state
        """
        info = self._state.get_session_summary(session_id)
        return _session_summary_to_wire(info)

    # --- Cleanup Operations ---

    @ws_expose
    async def clear_completed(self, max_age_seconds: float = 300) -> int:
        """Remove completed tasks older than max_age_seconds.

        Args:
            max_age_seconds: Maximum age in seconds to keep completed tasks

        Returns:
            Number of tasks removed
        """
        return self._state.clear_completed(max_age_seconds)

    # --- Events ---

    @ws_event
    async def on_task_started(self) -> TaskEventData:
        """Emitted when a new task starts."""
        ...

    @ws_event
    async def on_task_updated(self) -> TaskEventData:
        """Emitted when a task's status or progress changes."""
        ...

    @ws_event
    async def on_task_completed(self) -> TaskEventData:
        """Emitted when a task completes successfully."""
        ...

    @ws_event
    async def on_task_error(self) -> TaskEventData:
        """Emitted when a task fails with an error."""
        ...

    @ws_event
    async def on_task_cancelled(self) -> TaskEventData:
        """Emitted when a task is cancelled by the user."""
        ...
