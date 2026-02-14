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
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Any

from codegen import ws_service, ws_expose, ws_event, ws_type
from core.manager import SessionManager
from core.stream_state import (
    StreamState,
    StreamEvent as StreamStateEvent,
    Stream,
    StreamStatus,
    get_stream_state,
)
from models import TextBlock


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


@ws_service
class SessionManagerService:
    """WebSocket-exposed service for session lifecycle management.

    Provides operations for creating, switching, listing, and deleting sessions.
    Also exposes streaming status for all sessions.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        stream_state: StreamState | None = None,
    ):
        """Initialize service with a SessionManager instance.

        Args:
            session_manager: The SessionManager to expose via WebSocket
            stream_state: Optional StreamState for tracking streaming. Uses global if not provided.
        """
        self._manager = session_manager
        self._stream_state = stream_state or get_stream_state()
        self._event_handlers: list[Callable[[str, dict], None]] = []

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

        # Register the stream in StreamState for tracking
        self._stream_state.register_session_stream(
            session_id=session_id,
            exchange_id=exchange_id,
            prompt=content,
            backend_name=runner._runner.__class__.__name__ if hasattr(runner, '_runner') else "unknown",
        )

        # Start background streaming
        runner.start_background(
            prompt=content,
            messages=session.turns,
            allowed_tools=allowed_tools,
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
