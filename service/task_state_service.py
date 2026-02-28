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
from core.debug_log import debug_log, Category
from core.stream_state import (
    StreamState as TaskState,
    Stream as Task,
    StreamEvent as TaskEvent,
    StreamStatus as TaskStatus,
    StreamType as TaskType,
    SessionStreamInfo as SessionTaskInfo,
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


# --- Streaming Content Event Types ---
# These events provide fine-grained streaming updates for frontends.


@ws_type
@dataclass
class ContentDeltaEvent:
    """Event payload for streaming text content.

    Emitted as text tokens arrive from the LLM.
    """

    session_id: str
    exchange_id: str
    turn_index: int
    turn_id: str  # Stable UUID for this turn
    delta: str  # The new text chunk
    accumulated: str  # All text so far in this turn (for late-joining clients)


@ws_type
@dataclass
class TurnStartedEvent:
    """Event payload when a new turn begins in a session.

    Emitted at the start of user, assistant, or tool turns.
    """

    session_id: str
    exchange_id: str
    turn_index: int
    turn_id: str  # Stable UUID for this turn
    role: str  # "user", "assistant", or "tool"
    turn_type: str | None = None  # "text_turn", "tool_use", "tool_result", or None
    parallel_group_id: str | None = None  # Groups parallel tool calls


@ws_type
@dataclass
class TurnFinishedEvent:
    """Event payload when a turn completes.

    Emitted when an assistant response or tool result finishes.
    """

    session_id: str
    exchange_id: str
    turn_index: int
    turn_id: str  # Stable UUID for this turn
    role: str
    content: str  # Final content of the turn
    parallel_group_id: str | None = None  # Groups parallel tool calls


@ws_type
@dataclass
class ToolUseStartedEvent:
    """Event payload when a tool execution begins.

    Emitted when the LLM starts a tool call (input may still be streaming).
    """

    session_id: str
    exchange_id: str
    turn_index: int
    turn_id: str  # Stable UUID for this turn
    tool_use_id: str
    tool_name: str
    tool_index: int  # Order of this tool in the current exchange
    parallel_group_id: str | None = None  # Groups parallel tool calls


@ws_type
@dataclass
class ToolInputDeltaEvent:
    """Event payload for streaming tool input JSON.

    Emitted as tool input JSON streams from the LLM.
    """

    session_id: str
    exchange_id: str
    turn_id: str  # Stable UUID for this turn
    tool_use_id: str
    partial_json: str  # The new JSON chunk


@ws_type
@dataclass
class ToolUseEvent:
    """Event payload when tool input is complete and ready for execution.

    Emitted when the LLM finishes streaming tool input.
    """

    session_id: str
    exchange_id: str
    turn_index: int
    turn_id: str  # Stable UUID for this turn
    tool_use_id: str
    tool_name: str
    tool_input: dict  # Complete parsed tool input
    tool_index: int
    parallel_group_id: str | None = None  # Groups parallel tool calls


@ws_type
@dataclass
class ToolResultEvent:
    """Event payload when a tool execution completes.

    Emitted after the tool runs with its result.
    """

    session_id: str
    exchange_id: str
    turn_index: int
    turn_id: str  # Stable UUID for this turn
    tool_use_id: str
    tool_name: str
    result: str  # Tool output as string
    is_error: bool
    tool_index: int
    parallel_group_id: str | None = None  # Groups parallel tool calls


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
        # Track finished turns to prevent duplicate turn_finished events
        # Key: (session_id, turn_index), Value: content length (for debugging)
        self._finished_turns: dict[tuple[str, int], int] = {}

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
        """Convert TaskEvent enum to camelCase wire name.

        Maps StreamEvent values to backward-compatible "task*" wire names:
        - stream_started -> taskStarted
        - stream_updated -> taskUpdated
        - etc.
        """
        # Map stream_* to task_* for backward compatibility
        value = event.value
        if value.startswith("stream_"):
            value = "task_" + value[7:]  # Replace "stream_" with "task_"
        parts = value.split("_")
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

    # --- Streaming Content Event Emission ---
    # These methods are called by the event pump to relay SessionRunner events.

    def emit_content_delta(
        self,
        session_id: str,
        exchange_id: str,
        turn_index: int,
        turn_id: str,
        delta: str,
        accumulated: str,
    ) -> None:
        """Emit a content delta event for streaming text.

        Called by the event pump when SessionRunner emits a "text" event.

        Args:
            session_id: Session the content belongs to
            exchange_id: Exchange ID for this prompt/response
            turn_index: Index of the current turn
            turn_id: Stable UUID for this turn
            delta: New text chunk
            accumulated: All text accumulated so far
        """
        event_data = ContentDeltaEvent(
            session_id=session_id,
            exchange_id=exchange_id,
            turn_index=turn_index,
            turn_id=turn_id,
            delta=delta,
            accumulated=accumulated,
        )
        for handler in self._event_handlers:
            handler("contentDelta", event_data.__dict__)

    def emit_turn_started(
        self,
        session_id: str,
        exchange_id: str,
        turn_index: int,
        turn_id: str,
        role: str,
        turn_type: str | None = None,
        parallel_group_id: str | None = None,
    ) -> None:
        """Emit a turn started event.

        Called when a new turn begins (user message added, assistant starts, tool starts).

        Args:
            session_id: Session ID
            exchange_id: Exchange ID
            turn_index: Index of the new turn
            turn_id: Stable UUID for this turn
            role: Turn role ("user", "assistant", or "tool")
            turn_type: Content block type ("text_turn", "tool_use", "tool_result", or None)
            parallel_group_id: Groups parallel tool calls from same LLM response
        """
        # Clear finished turns tracking for this session when a new user turn starts
        # This prevents memory leak and ensures fresh tracking for each exchange
        if role == "user":
            keys_to_remove = [k for k in self._finished_turns if k[0] == session_id]
            for k in keys_to_remove:
                del self._finished_turns[k]

        event_data = TurnStartedEvent(
            session_id=session_id,
            exchange_id=exchange_id,
            turn_index=turn_index,
            turn_id=turn_id,
            role=role,
            turn_type=turn_type,
            parallel_group_id=parallel_group_id,
        )
        for handler in self._event_handlers:
            handler("turnStarted", event_data.__dict__)

    def emit_turn_finished(
        self,
        session_id: str,
        exchange_id: str,
        turn_index: int,
        turn_id: str,
        role: str,
        content: str,
        parallel_group_id: str | None = None,
    ) -> None:
        """Emit a turn finished event.

        Called when a turn completes (assistant response done, tool result received).

        Args:
            session_id: Session ID
            exchange_id: Exchange ID
            turn_index: Index of the completed turn
            turn_id: Stable UUID for this turn
            role: Turn role
            content: Final content of the turn
            parallel_group_id: Groups parallel tool calls from same LLM response
        """
        content_len = len(content) if content else 0
        turn_key = (session_id, turn_index)

        # Check for duplicate turn_finished events (race condition between SessionManagerService and TUI)
        if turn_key in self._finished_turns:
            prev_len = self._finished_turns[turn_key]
            # Allow re-emit if new content is longer (incremental update)
            if content_len <= prev_len:
                debug_log.debug(
                    f"emit_turn_finished: SKIP duplicate idx={turn_index}, prev_len={prev_len}, new_len={content_len}",
                    category=Category.API,
                    session_id=session_id,
                )
                return

        # Track this turn as finished
        self._finished_turns[turn_key] = content_len

        event_data = TurnFinishedEvent(
            session_id=session_id,
            exchange_id=exchange_id,
            turn_index=turn_index,
            turn_id=turn_id,
            role=role,
            content=content,
            parallel_group_id=parallel_group_id,
        )
        for handler in self._event_handlers:
            handler("turnFinished", event_data.__dict__)

    def emit_tool_use_started(
        self,
        session_id: str,
        exchange_id: str,
        turn_index: int,
        turn_id: str,
        tool_use_id: str,
        tool_name: str,
        tool_index: int,
        parallel_group_id: str | None = None,
    ) -> None:
        """Emit a tool use started event.

        Called when the LLM begins generating a tool call.

        Args:
            session_id: Session ID
            exchange_id: Exchange ID
            turn_index: Index of the tool_use turn
            turn_id: Stable UUID for this turn
            tool_use_id: Unique ID for this tool invocation
            tool_name: Name of the tool being called
            tool_index: Order of this tool in the exchange
            parallel_group_id: Groups parallel tool calls from same LLM response
        """
        event_data = ToolUseStartedEvent(
            session_id=session_id,
            exchange_id=exchange_id,
            turn_index=turn_index,
            turn_id=turn_id,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            tool_index=tool_index,
            parallel_group_id=parallel_group_id,
        )
        for handler in self._event_handlers:
            handler("toolUseStarted", event_data.__dict__)

    def emit_tool_input_delta(
        self,
        session_id: str,
        exchange_id: str,
        turn_id: str,
        tool_use_id: str,
        partial_json: str,
    ) -> None:
        """Emit a tool input delta event.

        Called as tool input JSON streams from the LLM.

        Args:
            session_id: Session ID
            exchange_id: Exchange ID
            turn_id: Stable UUID for this turn
            tool_use_id: Tool invocation ID
            partial_json: New JSON chunk
        """
        event_data = ToolInputDeltaEvent(
            session_id=session_id,
            exchange_id=exchange_id,
            turn_id=turn_id,
            tool_use_id=tool_use_id,
            partial_json=partial_json,
        )
        for handler in self._event_handlers:
            handler("toolInputDelta", event_data.__dict__)

    def emit_tool_use(
        self,
        session_id: str,
        exchange_id: str,
        turn_index: int,
        turn_id: str,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict,
        tool_index: int,
        parallel_group_id: str | None = None,
    ) -> None:
        """Emit a tool use event (input complete, ready for execution).

        Called when tool input is fully streamed and parsed.

        Args:
            session_id: Session ID
            exchange_id: Exchange ID
            turn_index: Index of the tool_use turn
            turn_id: Stable UUID for this turn
            tool_use_id: Tool invocation ID
            tool_name: Name of the tool
            tool_input: Complete parsed input
            tool_index: Order of this tool in the exchange
            parallel_group_id: Groups parallel tool calls from same LLM response
        """
        event_data = ToolUseEvent(
            session_id=session_id,
            exchange_id=exchange_id,
            turn_index=turn_index,
            turn_id=turn_id,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_index=tool_index,
            parallel_group_id=parallel_group_id,
        )
        for handler in self._event_handlers:
            handler("toolUse", event_data.__dict__)

    def emit_tool_result(
        self,
        session_id: str,
        exchange_id: str,
        turn_index: int,
        turn_id: str,
        tool_use_id: str,
        tool_name: str,
        result: str,
        is_error: bool,
        tool_index: int,
        parallel_group_id: str | None = None,
    ) -> None:
        """Emit a tool result event.

        Called when a tool execution completes.

        Args:
            session_id: Session ID
            exchange_id: Exchange ID
            turn_index: Index of the tool_result turn
            turn_id: Stable UUID for this turn
            tool_use_id: Tool invocation ID
            tool_name: Name of the tool
            result: Tool output as string
            is_error: Whether the tool errored
            tool_index: Order of this tool in the exchange
            parallel_group_id: Groups parallel tool calls from same LLM response
        """
        event_data = ToolResultEvent(
            session_id=session_id,
            exchange_id=exchange_id,
            turn_index=turn_index,
            turn_id=turn_id,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            result=result,
            is_error=is_error,
            tool_index=tool_index,
            parallel_group_id=parallel_group_id,
        )
        for handler in self._event_handlers:
            handler("toolResult", event_data.__dict__)

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

    # --- Streaming Content Events ---
    # These provide fine-grained updates for rendering streaming responses.

    @ws_event
    async def on_content_delta(self) -> ContentDeltaEvent:
        """Emitted when new text content streams from the LLM.

        Subscribe to this event to render streaming text in real-time.
        The `accumulated` field allows late-joining clients to catch up.
        """
        ...

    @ws_event
    async def on_turn_started(self) -> TurnStartedEvent:
        """Emitted when a new turn begins (user, assistant, or tool).

        Use this to create UI elements for the new turn.
        """
        ...

    @ws_event
    async def on_turn_finished(self) -> TurnFinishedEvent:
        """Emitted when a turn completes.

        Use this to finalize UI rendering for the turn.
        """
        ...

    @ws_event
    async def on_tool_use_started(self) -> ToolUseStartedEvent:
        """Emitted when the LLM begins a tool call.

        The tool input may still be streaming at this point.
        """
        ...

    @ws_event
    async def on_tool_input_delta(self) -> ToolInputDeltaEvent:
        """Emitted when tool input JSON streams from the LLM.

        Use this to show tool input as it's being generated.
        """
        ...

    @ws_event
    async def on_tool_use(self) -> ToolUseEvent:
        """Emitted when tool input is complete and execution begins.

        The full tool input is now available.
        """
        ...

    @ws_event
    async def on_tool_result(self) -> ToolResultEvent:
        """Emitted when a tool execution completes.

        Contains the tool's output or error.
        """
        ...
