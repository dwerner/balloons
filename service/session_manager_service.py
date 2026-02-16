"""WebSocket-exposed service for session management.

This service wraps SessionManager and exposes session lifecycle operations
via WebSocket RPC. The @ws_expose decorators mark methods for client generation.

Example usage:
    manager = SessionManager(backend_config)
    service = SessionManagerService(manager)

    # Service methods are called via WebSocket RPC:
    # {"id": "1", "method": "createSession", "params": {}}
    # -> {"id": "1", "result": {"id": "abc123", "title": "...", ...}}

    # Events are pushed to subscribed clients:
    # {"event": "sessionCreated", "data": {"sessionId": "abc123"}}

Frontend Interaction:
    The service provides two main pieces for frontends:

    1. submit_message() - Submit a prompt and start streaming
       Returns a SubmitMessageResult with exchange_id for tracking.

    2. Streaming events via TaskStateService:
       - onContentDelta: Text chunks as they arrive
       - onToolUseStarted: Tool execution beginning
       - onToolResult: Tool execution completed
       - onTurnFinished: Exchange complete

    Frontend Pattern:
       1. Subscribe to TaskStateService events
       2. Call submitMessage(sessionId, content)
       3. Receive deltas via onContentDelta
       4. Render incrementally
       5. turnFinished signals completion
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Any, TYPE_CHECKING

from codegen import ws_service, ws_expose, ws_event, ws_type
from core.manager import SessionManager
from core.stream_state import (
    StreamState,
    StreamEvent as StreamStateEvent,
    Stream,
    StreamStatus,
    get_stream_state,
)
from core.tree_state import TreeState
from models import TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock

if TYPE_CHECKING:
    from service.task_state_service import TaskStateService


class SessionManagerEvent(Enum):
    """Events emitted by SessionManagerService."""

    SESSION_CREATED = "session_created"
    SESSION_SWITCHED = "session_switched"
    SESSION_DELETED = "session_deleted"
    SESSION_UPDATED = "session_updated"
    STREAMING_STARTED = "streaming_started"
    STREAMING_STOPPED = "streaming_stopped"
    MESSAGE_SUBMITTED = "message_submitted"


@ws_type
@dataclass
class ManagedSessionInfo:
    """Session information for the session manager service.

    This is different from TreeStateService's SessionInfo - it focuses on
    session lifecycle rather than tree view state.
    """

    id: str
    title: str
    created: str
    model: str
    message_count: int
    is_active: bool
    is_streaming: bool
    is_child: bool
    is_returned: bool
    parent_id: str | None = None
    working_directory: str = ""


@ws_type
@dataclass
class StreamingInfo:
    """Information about an active streaming session."""

    session_id: str
    stream_id: str
    status: str  # "pending", "streaming", "executing", "completed", "error", "cancelled"
    backend_name: str
    started_at: str
    tokens_streamed: int
    tool_name: str | None = None
    tool_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@ws_type
@dataclass
class SessionEventData:
    """Event payload for session manager events."""

    event_type: str  # Maps to SessionManagerEvent enum value
    session_id: str
    data: dict = field(default_factory=dict)


@ws_type
@dataclass
class SubmitMessageResult:
    """Result of submitting a message to a session.

    Contains the IDs needed to track the resulting stream and turn.
    """

    session_id: str
    exchange_id: str  # UUID grouping user prompt + assistant response
    turn_index: int  # Index of the user turn just created
    status: str  # "started" or "queued"


@ws_type
@dataclass
class ImageAttachment:
    """Image attachment for a message.

    Used when submitting messages with images via WebSocket.
    The file_path should point to an already-uploaded image.
    """

    file_path: str  # Path to uploaded image file
    media_type: str  # MIME type: image/png, image/jpeg, etc.
    filename: str = ""  # Display filename
    width: int = 0  # Image dimensions (optional)
    height: int = 0


@dataclass
class _StreamingContext:
    """Internal context for tracking streaming state per session.

    Used by the event pump to accumulate content and track turn indices.
    """

    session_id: str
    exchange_id: str
    # Turn tracking
    user_turn_idx: int  # Index of the user message turn
    assistant_turn_idx: int = -1  # Index of current assistant turn (text or tool_use)
    # Content accumulation
    content: str = ""  # Accumulated text content for current assistant turn
    # Tool tracking
    tool_count: int = 0
    tool_turn_indices: dict = field(default_factory=dict)  # (tool_use_id, turn_type) -> turn_idx
    tool_names: dict = field(default_factory=dict)  # tool_use_id -> tool_name


@ws_service
class SessionManagerService:
    """WebSocket-exposed service for session lifecycle management.

    Provides operations for creating, switching, listing, and deleting sessions.
    Also exposes streaming status for all sessions.

    For frontend interaction, use submit_message() to send prompts and receive
    streaming events via the wired TaskStateService. The event pump automatically
    converts SessionRunner events to TaskStateService events.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        stream_state: StreamState | None = None,
        task_state_service: "TaskStateService | None" = None,
    ):
        """Initialize service with a SessionManager instance.

        Args:
            session_manager: The SessionManager to expose via WebSocket
            stream_state: Optional StreamState for tracking streaming. Uses global if not provided.
            task_state_service: Optional TaskStateService for emitting streaming events.
                               If provided, the event pump will relay events to frontends.
        """
        self._manager = session_manager
        self._stream_state = stream_state or get_stream_state()
        self._task_service = task_state_service
        self._tree_state: TreeState | None = None
        self._event_handlers: list[Callable[[str, dict], None]] = []

        # Event pump state
        self._pump_task: asyncio.Task | None = None
        self._pump_running = False
        self._pump_interval = 0.05  # 50ms polling interval
        # Track streaming context per session (exchange_id, accumulated content, etc.)
        self._streaming_contexts: dict[str, _StreamingContext] = {}

        # Wire up StreamState observer to emit streaming events
        self._stream_state.add_observer(self._on_stream_event)

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Register a handler for WebSocket events.

        The handler will be called with (event_name, data) for each event.
        """
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def set_task_state_service(self, task_service: "TaskStateService") -> None:
        """Set the TaskStateService for emitting streaming events.

        This enables the event pump to relay SessionRunner events to frontends.
        Call start_event_pump() after setting this to begin pumping events.

        Args:
            task_service: The TaskStateService to emit events through
        """
        self._task_service = task_service

    def set_tree_state(self, tree_state: TreeState) -> None:
        """Set the TreeState for updating turn data when messages are submitted.

        This enables submit_message() to update TreeState so that React frontends
        can see the new turns via getTurns(). Without this, turns would only be
        saved to storage but not visible to WebSocket clients querying TreeState.

        Args:
            tree_state: The TreeState instance to update
        """
        self._tree_state = tree_state

    def start_event_pump(self) -> None:
        """Start the event pump for relaying streaming events.

        The event pump polls all running sessions for events and relays them
        through TaskStateService. This should be called when the service is
        ready to handle WebSocket connections.

        The pump is idempotent - calling multiple times is safe.
        """
        if self._pump_running:
            return

        self._pump_running = True
        self._pump_task = asyncio.create_task(self._event_pump_loop())

    def stop_event_pump(self) -> None:
        """Stop the event pump.

        Call this when shutting down the service.
        """
        self._pump_running = False
        if self._pump_task and not self._pump_task.done():
            self._pump_task.cancel()

    def release_streaming_context(self, session_id: str) -> bool:
        """Release ownership of a streaming session to another component (e.g., TUI).

        This removes the streaming context from this service, allowing another
        component to poll events from the session without race conditions.

        Call this when the TUI wants to take ownership of a session that was
        submitted via React. The TUI will handle event dispatch and TaskStateService
        emission.

        Args:
            session_id: Session to release

        Returns:
            True if a context was released, False if no context existed
        """
        if session_id in self._streaming_contexts:
            del self._streaming_contexts[session_id]
            return True
        return False

    async def _event_pump_loop(self) -> None:
        """Main event pump loop - polls sessions and relays events."""
        while self._pump_running:
            try:
                await self._pump_events()
                await asyncio.sleep(self._pump_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                # Log but don't crash the pump
                await asyncio.sleep(self._pump_interval)

    async def _pump_events(self) -> None:
        """Poll sessions owned by this service and relay events to TaskStateService.

        IMPORTANT: Only polls sessions that have streaming contexts in this service
        (i.e., sessions where submit_message was called). This prevents stealing
        events from the TUI's poll loop for sessions started via the TUI.
        """
        if not self._task_service:
            return

        # Only poll sessions we're tracking - don't steal events from TUI
        for session_id in list(self._streaming_contexts.keys()):
            runner = self._manager.get_runner(session_id)
            if not runner:
                continue

            events = runner.drain_events()
            if not events:
                continue

            ctx = self._streaming_contexts.get(session_id)
            if not ctx:
                # Context was removed (race condition) - skip
                continue

            for event in events:
                await self._dispatch_event(session_id, event, ctx)

    async def _dispatch_event(
        self, session_id: str, event: Any, ctx: _StreamingContext
    ) -> None:
        """Dispatch a single streaming event to TaskStateService.

        Converts SessionRunner events to TaskStateService emit calls.

        Args:
            session_id: The session this event belongs to
            event: StreamEvent from the SessionRunner
            ctx: Streaming context for tracking state
        """
        if not self._task_service:
            return

        event_type = event.event_type
        data = event.data

        if event_type == "turn_started":
            # Initial turn_started event - update context with turn info
            ctx.assistant_turn_idx = data.get("turn_index", ctx.user_turn_idx + 1)
            self._task_service.emit_turn_started(
                session_id=session_id,
                exchange_id=ctx.exchange_id,
                turn_index=ctx.assistant_turn_idx,
                role="assistant",
            )

        elif event_type == "text":
            # Text delta - accumulate and emit
            text = data if isinstance(data, str) else str(data)
            ctx.content += text

            # Update stream state with approximate token count
            approx_tokens = len(ctx.content) // 4
            self._stream_state.update_stream(ctx.exchange_id, tokens_streamed=approx_tokens)

            self._task_service.emit_content_delta(
                session_id=session_id,
                exchange_id=ctx.exchange_id,
                turn_index=ctx.assistant_turn_idx,
                delta=text,
                accumulated=ctx.content,
            )

        elif event_type == "text_flush":
            # Text segment complete before tool use
            text = data.get("text", "") if isinstance(data, dict) else ""
            turn_idx = data.get("turn_index", ctx.assistant_turn_idx) if isinstance(data, dict) else ctx.assistant_turn_idx
            self._task_service.emit_turn_finished(
                session_id=session_id,
                exchange_id=ctx.exchange_id,
                turn_index=turn_idx,
                role="assistant",
                content=text,
            )

        elif event_type == "text_turn_started":
            # Text turn started - update context and emit turn_started
            turn_idx = data.get("turn_index", ctx.assistant_turn_idx) if isinstance(data, dict) else ctx.assistant_turn_idx
            ctx.assistant_turn_idx = turn_idx  # Update for subsequent content deltas
            ctx.content = ""  # Reset accumulated content for new turn
            self._task_service.emit_turn_started(
                session_id=session_id,
                exchange_id=ctx.exchange_id,
                turn_index=turn_idx,
                role="assistant",
            )

        elif event_type == "tool_use_start":
            # Tool use started - update context and emit
            # The turnIndex here is the main assistant turn; tool uses are shown there
            tool_use_id = data.get("tool_use_id", "")
            tool_name = data.get("tool_name", "")
            tool_idx = data.get("tool_index", ctx.tool_count)

            ctx.tool_count += 1
            ctx.tool_names[tool_use_id] = tool_name

            # Update stream state
            self._stream_state.update_stream(
                ctx.exchange_id,
                status=StreamStatus.EXECUTING,
                tool_name=tool_name,
                tool_count=ctx.tool_count,
            )

            # Emit toolUseStarted with the main assistant turn index
            # This shows tool uses alongside the text response
            self._task_service.emit_tool_use_started(
                session_id=session_id,
                exchange_id=ctx.exchange_id,
                turn_index=ctx.assistant_turn_idx,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                tool_index=tool_idx,
            )

        elif event_type == "tool_input_delta":
            # Tool input JSON streaming
            tool_use_id = data.get("tool_use_id", "")
            partial_json = data.get("partial_json", "")
            self._task_service.emit_tool_input_delta(
                session_id=session_id,
                exchange_id=ctx.exchange_id,
                tool_use_id=tool_use_id,
                partial_json=partial_json,
            )

        elif event_type == "tool_use_turn_started":
            # Tool use turn started - track turn index
            turn_idx = data.get("turn_index", ctx.assistant_turn_idx) if isinstance(data, dict) else ctx.assistant_turn_idx
            tool_use_id = data.get("tool_use_id", "")
            ctx.tool_turn_indices[(tool_use_id, "tool_use")] = turn_idx

            # Emit turn started for the tool use turn
            self._task_service.emit_turn_started(
                session_id=session_id,
                exchange_id=ctx.exchange_id,
                turn_index=turn_idx,
                role="assistant",
            )

        elif event_type == "tool_use":
            # Tool input complete - emit tool_use event
            tool_use_id = data.get("tool_use_id", "")
            tool_name = data.get("tool_name", "")
            tool_input = data.get("tool_input", {})
            tool_idx = data.get("tool_index", 0)
            turn_idx = data.get("turn_index", ctx.assistant_turn_idx)

            self._task_service.emit_tool_use(
                session_id=session_id,
                exchange_id=ctx.exchange_id,
                turn_index=turn_idx,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_index=tool_idx,
            )

        elif event_type == "tool_result_turn_started":
            # Tool result turn started - track turn index
            turn_idx = data.get("turn_index", ctx.assistant_turn_idx) if isinstance(data, dict) else ctx.assistant_turn_idx
            tool_use_id = data.get("tool_use_id", "")
            ctx.tool_turn_indices[(tool_use_id, "tool_result")] = turn_idx
            self._task_service.emit_turn_started(
                session_id=session_id,
                exchange_id=ctx.exchange_id,
                turn_index=turn_idx,
                role="tool",
            )

        elif event_type == "tool_result":
            # Tool execution complete
            tool_use_id = data.get("tool_use_id", "")
            result = data.get("result", "")
            tool_idx = data.get("tool_index", 0)
            turn_idx = data.get("turn_index", ctx.assistant_turn_idx)
            tool_name = ctx.tool_names.get(tool_use_id, "")

            # Update stream state - back to streaming
            self._stream_state.update_stream(
                ctx.exchange_id,
                status=StreamStatus.STREAMING,
                tool_name=None,
            )

            self._task_service.emit_tool_result(
                session_id=session_id,
                exchange_id=ctx.exchange_id,
                turn_index=turn_idx,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                result=result,
                is_error=False,
                tool_index=tool_idx,
            )

        elif event_type == "init":
            # Model info - update stream state
            model = data.get("model", "")
            context_window = data.get("context_window", 0)
            self._stream_state.update_stream(
                ctx.exchange_id,
                model=model,
                context_window=context_window,
            )

        elif event_type == "result":
            # Usage stats - update stream state
            input_tokens = data.get("input_tokens", 0)
            output_tokens = data.get("output_tokens", 0)
            self._stream_state.update_stream(
                ctx.exchange_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        elif event_type == "done":
            # Stream complete - emit final turn_finished and clean up
            if ctx.content:
                self._task_service.emit_turn_finished(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_index=ctx.assistant_turn_idx,
                    role="assistant",
                    content=ctx.content,
                )
            # Complete the stream
            self._stream_state.complete_stream(ctx.exchange_id)
            # Mark session as no longer streaming so React frontend hides stop button
            if self._tree_state:
                self._tree_state.stop_streaming(session_id)
                # Reload TreeState from Session to pick up all turns that were added
                # during streaming (tool_use, tool_result, text turns after tools, etc.)
                # The SessionRunner adds turns directly to session.turns, but the event
                # pump only emitted WebSocket events without updating TreeState.
                session = self._manager.get_session(session_id)
                if session:
                    self._tree_state.load_session(session_id, session)
            # Clean up context
            if session_id in self._streaming_contexts:
                del self._streaming_contexts[session_id]

        elif event_type == "error":
            # Error - mark stream as failed
            error_msg = data if isinstance(data, str) else str(data)
            self._stream_state.fail_stream(ctx.exchange_id, error_msg)
            # Mark session as no longer streaming and reload turns
            if self._tree_state:
                self._tree_state.stop_streaming(session_id)
                session = self._manager.get_session(session_id)
                if session:
                    self._tree_state.load_session(session_id, session)
            # Clean up context
            if session_id in self._streaming_contexts:
                del self._streaming_contexts[session_id]

        elif event_type == "rate_limit":
            # Rate limit error - mark stream as failed
            error_msg = data if isinstance(data, str) else str(data)
            self._stream_state.fail_stream(ctx.exchange_id, f"Rate limit: {error_msg}")
            # Mark session as no longer streaming and reload turns
            if self._tree_state:
                self._tree_state.stop_streaming(session_id)
                session = self._manager.get_session(session_id)
                if session:
                    self._tree_state.load_session(session_id, session)
            if session_id in self._streaming_contexts:
                del self._streaming_contexts[session_id]

        elif event_type == "cancelled":
            # Cancelled - mark stream as cancelled
            self._stream_state.cancel_stream(ctx.exchange_id)
            # Mark session as no longer streaming and reload turns
            if self._tree_state:
                self._tree_state.stop_streaming(session_id)
                session = self._manager.get_session(session_id)
                if session:
                    self._tree_state.load_session(session_id, session)
            if session_id in self._streaming_contexts:
                del self._streaming_contexts[session_id]

        elif event_type == "input_required":
            # Claude is asking for input - this shouldn't happen for non-interactive frontends
            # Mark as completed since we can't respond
            if ctx.content:
                self._task_service.emit_turn_finished(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_index=ctx.assistant_turn_idx,
                    role="assistant",
                    content=ctx.content,
                )
            self._stream_state.complete_stream(ctx.exchange_id)
            # Mark session as no longer streaming and reload turns
            if self._tree_state:
                self._tree_state.stop_streaming(session_id)
                session = self._manager.get_session(session_id)
                if session:
                    self._tree_state.load_session(session_id, session)
            if session_id in self._streaming_contexts:
                del self._streaming_contexts[session_id]

        # Note: "raw" events are not relayed - they're for debugging only

    async def _on_stream_event(self, event: StreamStateEvent, stream: Stream) -> None:
        """Convert StreamState events to WebSocket events."""
        # Only emit events for session streams (not helper streams)
        if not stream.session_id:
            return

        if event == StreamStateEvent.STREAM_STARTED:
            self._emit_event(
                SessionManagerEvent.STREAMING_STARTED,
                stream.session_id,
                {"stream_id": stream.stream_id},
            )
        elif event in (
            StreamStateEvent.STREAM_COMPLETED,
            StreamStateEvent.STREAM_ERROR,
            StreamStateEvent.STREAM_CANCELLED,
        ):
            self._emit_event(
                SessionManagerEvent.STREAMING_STOPPED,
                stream.session_id,
                {
                    "stream_id": stream.stream_id,
                    "status": stream.status.value,
                    "error": stream.error,
                },
            )

    def _emit_event(
        self, event: SessionManagerEvent, session_id: str, data: dict | None = None
    ) -> None:
        """Emit an event to all registered handlers."""
        event_name = self._event_to_wire_name(event)
        event_data = {
            "session_id": session_id,
            **(data or {}),
        }

        for handler in self._event_handlers:
            handler(event_name, event_data)

    def _event_to_wire_name(self, event: SessionManagerEvent) -> str:
        """Convert SessionManagerEvent enum to camelCase wire name."""
        # SESSION_CREATED -> "sessionCreated"
        parts = event.value.split("_")
        return parts[0] + "".join(p.title() for p in parts[1:])

    # --- Session Lifecycle Operations ---

    @ws_expose
    async def create_session(
        self, working_directory: str | None = None
    ) -> ManagedSessionInfo:
        """Create a new session.

        Args:
            working_directory: Initial working directory (defaults to cwd)

        Returns:
            Info about the created session
        """
        session = await self._manager.create_session(working_directory)

        info = ManagedSessionInfo(
            id=session.id,
            title=session.title or f"Session {session.id[:8]}",
            created=session.created,
            model=session.model,
            message_count=len(session.turns),
            is_active=self._manager._active_session_id == session.id,
            is_streaming=False,
            is_child=session.parent_id is not None,
            is_returned=session.returned,
            parent_id=session.parent_id,
            working_directory=session.working_directory,
        )

        self._emit_event(SessionManagerEvent.SESSION_CREATED, session.id)
        return info

    @ws_expose
    async def switch_session(self, session_id: str) -> bool:
        """Switch to a different session.

        Args:
            session_id: ID of the session to switch to

        Returns:
            True if switch was successful, False if session not found
        """
        success = await self._manager.set_active(session_id)

        if success:
            self._emit_event(SessionManagerEvent.SESSION_SWITCHED, session_id)

        return success

    @ws_expose
    async def get_session(self, session_id: str) -> ManagedSessionInfo | None:
        """Get information about a specific session.

        Args:
            session_id: ID of the session to get

        Returns:
            Session info, or None if not found
        """
        session = self._manager.get_session(session_id)
        if not session:
            # Try loading from storage
            session = await self._manager.load_session(session_id)
            if not session:
                return None

        stream = self._stream_state.get_session_stream(session_id)
        is_streaming = stream is not None and stream.is_active

        return ManagedSessionInfo(
            id=session.id,
            title=session.title or f"Session {session.id[:8]}",
            created=session.created,
            model=session.model,
            message_count=len(session.turns),
            is_active=self._manager._active_session_id == session.id,
            is_streaming=is_streaming,
            is_child=session.parent_id is not None,
            is_returned=session.returned,
            parent_id=session.parent_id,
            working_directory=session.working_directory,
        )

    @ws_expose
    async def list_sessions(self) -> list[ManagedSessionInfo]:
        """List all available sessions.

        Returns:
            List of session info objects
        """
        session_infos = await self._manager.list_sessions()
        result = []

        for info in session_infos:
            session = self._manager.get_session(info.id)
            stream = self._stream_state.get_session_stream(info.id)
            is_streaming = stream is not None and stream.is_active

            # Get working directory from loaded session if available
            working_dir = ""
            if session:
                working_dir = session.working_directory

            result.append(
                ManagedSessionInfo(
                    id=info.id,
                    title=info.title,
                    created=info.created,
                    model=info.model,
                    message_count=info.message_count,
                    is_active=self._manager._active_session_id == info.id,
                    is_streaming=is_streaming,
                    is_child=info.is_child,
                    is_returned=info.is_returned,
                    parent_id=None,  # Not available from SessionInfo
                    working_directory=working_dir,
                )
            )

        return result

    @ws_expose
    async def get_active_session_id(self) -> str | None:
        """Get the ID of the currently active session.

        Returns:
            Active session ID, or None if no session is active
        """
        return self._manager._active_session_id

    @ws_expose
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Note: This removes the session from memory and storage.
        If the deleted session was active, no session will be active after.

        Args:
            session_id: ID of the session to delete

        Returns:
            True if session was deleted, False if not found
        """
        session = self._manager.get_session(session_id)
        if not session:
            # Try to load it first
            session = await self._manager.load_session(session_id)
            if not session:
                return False

        # Remove from manager's tracking
        if session_id in self._manager._sessions:
            del self._manager._sessions[session_id]
        if session_id in self._manager._runners:
            runner = self._manager._runners[session_id]
            if runner.is_streaming:
                runner.cancel()
            del self._manager._runners[session_id]

        # Clear active if this was the active session
        if self._manager._active_session_id == session_id:
            self._manager._active_session_id = None

        # Delete from storage (instance method)
        await session.delete()

        self._emit_event(SessionManagerEvent.SESSION_DELETED, session_id)
        return True

    # --- Streaming Status Operations ---

    @ws_expose
    async def get_streaming_sessions(self) -> list[str]:
        """Get IDs of all sessions currently streaming.

        Returns:
            List of session IDs that are streaming
        """
        return self._manager.get_streaming_sessions()

    @ws_expose
    async def get_streaming_info(self, session_id: str) -> StreamingInfo | None:
        """Get streaming information for a session.

        Args:
            session_id: ID of the session to check

        Returns:
            Streaming info if session is streaming, None otherwise
        """
        stream = self._stream_state.get_session_stream(session_id)
        if not stream or not stream.is_active:
            return None

        return StreamingInfo(
            session_id=session_id,
            stream_id=stream.stream_id,
            status=stream.status.value,
            backend_name=stream.backend_name,
            started_at=stream.started_at.isoformat(),
            tokens_streamed=stream.tokens_streamed,
            tool_name=stream.tool_name,
            tool_count=stream.tool_count,
            input_tokens=stream.input_tokens,
            output_tokens=stream.output_tokens,
        )

    @ws_expose
    async def get_all_streaming_info(self) -> list[StreamingInfo]:
        """Get streaming information for all active streams.

        Returns:
            List of streaming info for all active session streams
        """
        result = []
        for stream in self._stream_state.get_active_streams():
            # Only include session streams, not helper streams
            if stream.session_id:
                result.append(
                    StreamingInfo(
                        session_id=stream.session_id,
                        stream_id=stream.stream_id,
                        status=stream.status.value,
                        backend_name=stream.backend_name,
                        started_at=stream.started_at.isoformat(),
                        tokens_streamed=stream.tokens_streamed,
                        tool_name=stream.tool_name,
                        tool_count=stream.tool_count,
                        input_tokens=stream.input_tokens,
                        output_tokens=stream.output_tokens,
                    )
                )
        return result

    @ws_expose
    async def cancel_streaming(self, session_id: str) -> bool:
        """Cancel streaming for a session.

        Args:
            session_id: ID of the session to cancel

        Returns:
            True if streaming was cancelled, False if session wasn't streaming
        """
        runner = self._manager.get_runner(session_id)
        if not runner or not runner.is_streaming:
            return False

        runner.cancel()

        # Clean up streaming context
        if session_id in self._streaming_contexts:
            ctx = self._streaming_contexts.pop(session_id)
            self._stream_state.cancel_stream(ctx.exchange_id)

        return True

    # --- Message Submission ---

    @ws_expose
    async def submit_message(
        self,
        session_id: str,
        content: str,
        queue: bool = False,
        allowed_tools: list[str] | None = None,
    ) -> SubmitMessageResult:
        """Submit a message to a session and start streaming the response.

        This is the primary way for frontends to interact with the LLM.
        The message is added to the session and streaming begins immediately
        (unless queue=True, in which case it waits for current stream to finish).

        After calling this method, listen for streaming events on TaskStateService:
        - onContentDelta: Streaming text chunks
        - onToolUseStarted: Tool execution beginning
        - onToolResult: Tool execution completed
        - onTurnFinished: Exchange completed

        Args:
            session_id: ID of the session to submit to
            content: The message content (user prompt)
            queue: If True, queue the message instead of starting immediately.
                   If False and session is already streaming, returns error.
            allowed_tools: List of tool names to allow, or None for all tools

        Returns:
            SubmitMessageResult with IDs for tracking the stream

        Raises:
            ValueError: If session not found or already streaming (when queue=False)
        """
        # Get or load session
        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found")

        # Get runner
        runner = self._manager.get_runner(session_id)
        if not runner:
            raise ValueError(f"No runner for session {session_id}")

        # Check if already streaming
        if runner.is_streaming:
            if not queue:
                raise ValueError(
                    f"Session {session_id} is already streaming. "
                    "Use queue=True to queue this message."
                )
            # TODO: Implement actual message queueing
            # For now, just reject - full queue support is a future enhancement
            raise ValueError("Message queueing not yet implemented")

        # Generate exchange ID for this user prompt + assistant response
        exchange_id = str(uuid.uuid4())

        # Add user message to session (persists immediately)
        turn_index = len(session.turns)
        user_blocks = [TextBlock(text=content)]
        session.add_message(
            "user", content, content_blocks=user_blocks, exchange_id=exchange_id
        )
        await session.save()

        # Update TreeState so WebSocket clients can see the new turns via getTurns()
        if self._tree_state:
            # Ensure session is loaded in TreeState (it might not be if TUI is viewing a different session)
            if not self._tree_state.get_session(session_id):
                self._tree_state.add_session(session, is_current=False)
            if self._tree_state.get_session(session_id) and self._tree_state.get_session(session_id).turns is None:
                self._tree_state.load_session(session_id, session)

            # Add user turn to TreeState
            self._tree_state.start_turn(session_id, turn_index, "user", exchange_id=exchange_id)
            self._tree_state.update_turn_content(session_id, turn_index, content)
            # Mark user turn as finished (user turns complete immediately)
            # Note: We call finish_turn synchronously since user turns don't need async token counting
            import asyncio
            asyncio.create_task(self._tree_state.finish_turn(
                session_id, turn_index, content, TextBlock(text=content), []
            ))
            # Start assistant turn (will be streaming)
            self._tree_state.start_turn(session_id, turn_index + 1, "assistant", exchange_id=exchange_id)
            # Mark session as streaming so React frontend shows stop button
            self._tree_state.start_streaming(session_id)

        # Emit user turn events to TaskStateService so web clients display the user message
        # This is critical for web clients that rely on these events for turn rendering
        if self._task_service:
            self._task_service.emit_turn_started(
                session_id=session_id,
                exchange_id=exchange_id,
                turn_index=turn_index,
                role="user",
            )
            self._task_service.emit_turn_finished(
                session_id=session_id,
                exchange_id=exchange_id,
                turn_index=turn_index,
                role="user",
                content=content,
            )

        # Register the stream in StreamState for tracking
        self._stream_state.register_session_stream(
            session_id=session_id,
            exchange_id=exchange_id,
            prompt=content,
            backend_name=runner._runner.__class__.__name__ if hasattr(runner, '_runner') else "unknown",
        )

        # Create streaming context for event pump to track this exchange
        self._streaming_contexts[session_id] = _StreamingContext(
            session_id=session_id,
            exchange_id=exchange_id,
            user_turn_idx=turn_index,
            assistant_turn_idx=turn_index + 1,  # Next turn will be assistant
        )

        # Start background streaming
        runner.start_background(
            prompt=content,
            messages=session.turns,
            allowed_tools=allowed_tools,
        )

        # Emit message submitted event
        self._emit_event(
            SessionManagerEvent.MESSAGE_SUBMITTED,
            session_id,
            {"exchange_id": exchange_id, "turn_index": turn_index, "content": content},
        )

        return SubmitMessageResult(
            session_id=session_id,
            exchange_id=exchange_id,
            turn_index=turn_index,
            status="started",
        )

    @ws_expose
    async def submit_message_with_images(
        self,
        session_id: str,
        content: str,
        images: list[dict],
        queue: bool = False,
        allowed_tools: list[str] | None = None,
    ) -> SubmitMessageResult:
        """Submit a message with image attachments to a session.

        Similar to submit_message but includes images that Claude can see.
        Images should be uploaded first via ImageService.upload_image().

        Args:
            session_id: ID of the session to submit to
            content: The message content (user prompt)
            images: List of image attachment dicts with keys:
                - file_path: Path to uploaded image file
                - media_type: MIME type (image/png, image/jpeg, etc.)
                - filename: Optional display filename
                - width: Optional image width
                - height: Optional image height
            queue: If True, queue the message instead of starting immediately.
            allowed_tools: List of tool names to allow, or None for all tools

        Returns:
            SubmitMessageResult with IDs for tracking the stream

        Raises:
            ValueError: If session not found or already streaming (when queue=False)
        """
        # Get or load session
        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found")

        # Get runner
        runner = self._manager.get_runner(session_id)
        if not runner:
            raise ValueError(f"No runner for session {session_id}")

        # Check if already streaming
        if runner.is_streaming:
            if not queue:
                raise ValueError(
                    f"Session {session_id} is already streaming. "
                    "Use queue=True to queue this message."
                )
            raise ValueError("Message queueing not yet implemented")

        # Generate exchange ID for this user prompt + assistant response
        exchange_id = str(uuid.uuid4())

        # Convert image dicts to ImageBlock objects
        image_blocks: list[ImageBlock] = []
        for img in images:
            image_blocks.append(ImageBlock(
                file_path=img.get("file_path", ""),
                media_type=img.get("media_type", ""),
                filename=img.get("filename", ""),
                width=img.get("width", 0),
                height=img.get("height", 0),
            ))

        # Build user message content blocks (text + images)
        user_blocks: list = [TextBlock(text=content)]
        user_blocks.extend(image_blocks)

        # Build display content for the turn (text with image placeholders)
        display_content = content
        if image_blocks:
            img_count = len(image_blocks)
            img_text = f" [+{img_count} image{'s' if img_count > 1 else ''}]"
            display_content += img_text

        # Add user message to session (persists immediately)
        turn_index = len(session.turns)
        session.add_message(
            "user", display_content, content_blocks=user_blocks, exchange_id=exchange_id
        )
        await session.save()

        # Update TreeState so WebSocket clients can see the new turns via getTurns()
        if self._tree_state:
            if not self._tree_state.get_session(session_id):
                self._tree_state.add_session(session, is_current=False)
            if self._tree_state.get_session(session_id) and self._tree_state.get_session(session_id).turns is None:
                self._tree_state.load_session(session_id, session)

            self._tree_state.start_turn(session_id, turn_index, "user", exchange_id=exchange_id)
            self._tree_state.update_turn_content(session_id, turn_index, display_content)
            import asyncio as aio
            aio.create_task(self._tree_state.finish_turn(
                session_id, turn_index, display_content, TextBlock(text=content), []
            ))
            self._tree_state.start_turn(session_id, turn_index + 1, "assistant", exchange_id=exchange_id)
            self._tree_state.start_streaming(session_id)

        # Emit user turn events to TaskStateService
        if self._task_service:
            self._task_service.emit_turn_started(
                session_id=session_id,
                exchange_id=exchange_id,
                turn_index=turn_index,
                role="user",
            )
            self._task_service.emit_turn_finished(
                session_id=session_id,
                exchange_id=exchange_id,
                turn_index=turn_index,
                role="user",
                content=display_content,
            )

        # Register the stream in StreamState for tracking
        self._stream_state.register_session_stream(
            session_id=session_id,
            exchange_id=exchange_id,
            prompt=content,
            backend_name=runner._runner.__class__.__name__ if hasattr(runner, '_runner') else "unknown",
        )

        # Create streaming context for event pump
        self._streaming_contexts[session_id] = _StreamingContext(
            session_id=session_id,
            exchange_id=exchange_id,
            user_turn_idx=turn_index,
            assistant_turn_idx=turn_index + 1,
        )

        # Start background streaming with images
        # Note: The runner's underlying ClaudeRunner needs to handle images
        # We pass images via an extended interface
        if hasattr(runner._runner, 'set_pending_images'):
            runner._runner.set_pending_images(image_blocks)

        runner.start_background(
            prompt=content,
            messages=session.turns,
            allowed_tools=allowed_tools,
        )

        # Emit message submitted event
        self._emit_event(
            SessionManagerEvent.MESSAGE_SUBMITTED,
            session_id,
            {
                "exchange_id": exchange_id,
                "turn_index": turn_index,
                "content": content,
                "image_count": len(image_blocks),
            },
        )

        return SubmitMessageResult(
            session_id=session_id,
            exchange_id=exchange_id,
            turn_index=turn_index,
            status="started",
        )

    # --- Events ---

    @ws_event
    async def on_session_created(self) -> SessionEventData:
        """Emitted when a new session is created."""
        ...

    @ws_event
    async def on_session_switched(self) -> SessionEventData:
        """Emitted when the active session changes."""
        ...

    @ws_event
    async def on_session_deleted(self) -> SessionEventData:
        """Emitted when a session is deleted."""
        ...

    @ws_event
    async def on_session_updated(self) -> SessionEventData:
        """Emitted when a session's metadata is updated."""
        ...

    @ws_event
    async def on_streaming_started(self) -> SessionEventData:
        """Emitted when a session starts streaming."""
        ...

    @ws_event
    async def on_streaming_stopped(self) -> SessionEventData:
        """Emitted when a session stops streaming."""
        ...

    @ws_event
    async def on_message_submitted(self) -> SubmitMessageResult:
        """Emitted when a message is submitted and streaming begins."""
        ...
