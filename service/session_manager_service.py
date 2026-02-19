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
from core.debug_log import debug_log
from core.manager import SessionManager
from core.stream_state import (
    StreamState,
    StreamEvent as StreamStateEvent,
    Stream,
    StreamStatus,
    get_stream_state,
)
from core.tree_state import TreeState
from models import TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock, Turn
from service.session_events import (
    SessionEventObserver,
    TurnCreatedEvent,
    TurnDeltaEvent,
    TurnFinishedEvent,
    StreamStartedEvent,
    StreamDoneEvent,
    StreamErrorEvent,
    ToolUseStartedEvent,
    ToolInputDeltaEvent,
    ToolUseEvent,
    ToolResultEvent,
    HelperStartedEvent,
    HelperDeltaEvent,
    HelperDoneEvent,
    HelperErrorEvent,
)

if TYPE_CHECKING:
    from service.task_state_service import TaskStateService
    from service.session_data_service import SessionDataService


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

    Used by the event pump to accumulate content and track turn indices/IDs.
    """

    session_id: str
    exchange_id: str
    # Turn tracking
    user_turn_idx: int  # Index of the user message turn
    user_turn_id: str = ""  # Stable UUID for the user turn
    assistant_turn_idx: int = -1  # Index of current assistant turn (text or tool_use)
    assistant_turn_id: str = ""  # Stable UUID for the assistant turn
    # Content accumulation
    content: str = ""  # Accumulated text content for current assistant turn
    # Tool tracking
    tool_count: int = 0
    tool_turn_indices: dict = field(default_factory=dict)  # (tool_use_id, turn_type) -> turn_idx
    tool_turn_ids: dict = field(default_factory=dict)  # (tool_use_id, turn_type) -> turn_id
    tool_names: dict = field(default_factory=dict)  # tool_use_id -> tool_name


@dataclass
class _HelperContext:
    """Internal context for tracking helper task state.

    Used by the event pump to track helper runners for background LLM tasks
    like context compression, merge summaries, archive summaries, etc.
    """

    helper_id: str  # Unique ID for this helper task
    helper_type: str  # "compress", "derive", "archive", "merge", "link", "return"
    session_id: str | None = None  # Associated session if applicable
    content: str = ""  # Accumulated text content
    metadata: dict = field(default_factory=dict)  # Type-specific data for continuation


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
        session_data_service: "SessionDataService | None" = None,
    ):
        """Initialize service with a SessionManager instance.

        Args:
            session_manager: The SessionManager to expose via WebSocket
            stream_state: Optional StreamState for tracking streaming. Uses global if not provided.
            task_state_service: Optional TaskStateService for emitting streaming events.
                               If provided, the event pump will relay events to frontends.
            session_data_service: Optional SessionDataService for emitting session data events.
                                 If provided, events will be emitted in parallel with TaskStateService.
        """
        self._manager = session_manager
        self._stream_state = stream_state or get_stream_state()
        self._task_service = task_state_service
        self._session_data_service = session_data_service
        # TreeState is owned by this service - authoritative source for session tree structure
        self._tree_state: TreeState = TreeState()
        self._event_handlers: list[Callable[[str, dict], None]] = []

        # Event pump state
        self._pump_task: asyncio.Task | None = None
        self._pump_running = False
        self._pump_interval = 0.05  # 50ms polling interval
        # Track streaming context per session (exchange_id, accumulated content, etc.)
        self._streaming_contexts: dict[str, _StreamingContext] = {}

        # Helper runner state (for background LLM tasks)
        # Imported here to avoid circular imports
        from core.runner import HelperRunner
        self._helper_runners: dict[str, HelperRunner] = {}
        self._helper_contexts: dict[str, _HelperContext] = {}
        # Backend config is needed to create new runners - will be set via set_backend_config
        self._backend_config: Any = None

        # Async observers for session events (SessionEventObserver protocol)
        self._observers: list[SessionEventObserver] = []

        # Register SessionDataService as observer if provided
        if session_data_service is not None:
            self.add_observer(session_data_service)

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

    def add_observer(self, observer: SessionEventObserver) -> None:
        """Register an async observer for session events.

        Observers receive typed event dataclasses for all streaming events.
        This is the primary mechanism for:
        - SessionDataService to emit WebSocket events
        - TUI to update widgets without polling
        - Any other component to observe session events

        Args:
            observer: Object implementing SessionEventObserver protocol
        """
        if observer not in self._observers:
            self._observers.append(observer)

    def remove_observer(self, observer: SessionEventObserver) -> None:
        """Unregister an async observer.

        Args:
            observer: The observer to remove
        """
        if observer in self._observers:
            self._observers.remove(observer)

    async def _notify_observers(self, method_name: str, event: Any) -> None:
        """Notify all observers of an event.

        Calls the specified method on all observers that have it implemented.
        Errors in individual observers are logged but don't stop other observers.

        Args:
            method_name: Name of the observer method to call (e.g., "on_turn_delta")
            event: The typed event dataclass to pass to observers
        """
        from core.debug_log import debug_log

        for observer in self._observers:
            method = getattr(observer, method_name, None)
            if method is not None:
                try:
                    await method(event)
                except Exception as e:
                    debug_log.error(
                        f"Observer {type(observer).__name__}.{method_name} failed: {e}",
                        category="websocket",
                    )

    def set_task_state_service(self, task_service: "TaskStateService") -> None:
        """Set the TaskStateService for emitting streaming events.

        This enables the event pump to relay SessionRunner events to frontends.
        Call start_event_pump() after setting this to begin pumping events.

        Args:
            task_service: The TaskStateService to emit events through
        """
        self._task_service = task_service

    def set_session_data_service(self, session_data_service: "SessionDataService") -> None:
        """Set the SessionDataService for emitting session data events.

        This enables the event pump to relay events to SessionDataService in parallel
        with TaskStateService. SessionDataService provides subscription-based filtering
        so only subscribed clients receive events.

        Also wires the TreeState and session loader to SessionDataService,
        enabling get_session_snapshot() to return full turn history.

        SessionDataService is also registered as an observer to receive events
        through the observer pattern (in addition to direct emit calls which
        will be removed in a future refactor).

        Args:
            session_data_service: The SessionDataService to emit events through
        """
        self._session_data_service = session_data_service
        # Wire TreeState if already set
        if self._tree_state:
            session_data_service.set_tree_state(self._tree_state)
        # Wire session loader so SessionDataService can load sessions from storage
        session_data_service.set_session_loader(self._manager.load_session)
        # Register as observer for the new event pattern
        self.add_observer(session_data_service)

    def get_tree_state(self) -> TreeState:
        """Get the TreeState owned by this service.

        Use this to share the TreeState with other services (e.g., TreeStateService)
        that need to read the session tree structure.

        Returns:
            The TreeState instance owned by this service
        """
        return self._tree_state

    def set_tree_state(self, tree_state: TreeState) -> None:
        """DEPRECATED: Set the TreeState.

        This method is deprecated. SessionManagerService now owns its own TreeState.
        Use get_tree_state() to share the service's TreeState with other components.

        This method is kept for backward compatibility but will be removed in a future version.
        For now, it replaces the owned TreeState with the provided one.

        Args:
            tree_state: The TreeState instance to use
        """
        self._tree_state = tree_state
        # Also wire to SessionDataService for snapshot loading
        if self._session_data_service:
            self._session_data_service.set_tree_state(tree_state)

    # --- Helper Runner Management ---

    def _get_backend_for_session(self, session) -> Any:
        """Get the backend config for a session, respecting session's backend preference.

        Args:
            session: The session to get backend for

        Returns:
            BackendConfig for the session (session's preference or default)
        """
        from config import get_config

        config = get_config()
        if session.backend_name and session.backend_name in config.backends:
            return config.get_backend(session.backend_name)
        return config.get_backend(config.default_backend)

    def _create_runner_for_session(self, session) -> Any:
        """Create a BaseRunner for a session using the session's backend config.

        Args:
            session: The session to create a runner for

        Returns:
            A BaseRunner instance (ClaudeRunner, OpenRouterRunner, etc.)
        """
        from core.runner_factory import create_runner

        backend = self._get_backend_for_session(session)
        return create_runner(backend)

    def start_helper(
        self,
        helper_id: str,
        helper_type: str,
        prompt: str,
        session_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Start a helper task for background LLM operations.

        Helper tasks are used for operations like context compression, merge summaries,
        archive summaries, etc. They use the session's configured backend.

        Args:
            helper_id: Unique ID for this helper task
            helper_type: Type of helper ("compress", "derive", "archive", "merge", "link", "return")
            prompt: The prompt to send to the LLM
            session_id: Session this helper is for (determines which backend to use)
            metadata: Type-specific data to pass to completion handlers
        """
        from core.runner import HelperRunner

        # Get the session to determine which backend to use
        session = None
        if session_id:
            session = self._manager.get_session(session_id)

        # Create runner using session's backend (or default if no session)
        if session:
            runner = self._create_runner_for_session(session)
        else:
            # Fallback to default backend if no session
            from config import get_config
            from core.runner_factory import create_runner

            config = get_config()
            backend = config.get_backend(config.default_backend)
            runner = create_runner(backend)

        # Create helper runner and context
        helper_runner = HelperRunner(helper_id, runner=runner)
        self._helper_runners[helper_id] = helper_runner

        ctx = _HelperContext(
            helper_id=helper_id,
            helper_type=helper_type,
            session_id=session_id,
            metadata=metadata or {},
        )
        self._helper_contexts[helper_id] = ctx

        # Notify observers that helper is starting
        asyncio.create_task(self._notify_observers(
            "on_helper_started",
            HelperStartedEvent(
                helper_id=helper_id,
                helper_type=helper_type,
                session_id=session_id,
                metadata=metadata or {},
            ),
        ))

        # Start background streaming
        helper_runner.start_background(prompt)

    def cancel_helper(self, helper_id: str) -> bool:
        """Cancel a running helper task.

        Args:
            helper_id: ID of the helper to cancel

        Returns:
            True if helper was found and cancelled, False otherwise
        """
        helper_runner = self._helper_runners.get(helper_id)
        if not helper_runner:
            return False

        helper_runner.cancel()
        return True

    def get_helper_result(self, helper_id: str) -> str | None:
        """Get the accumulated result from a helper task.

        Args:
            helper_id: ID of the helper

        Returns:
            Accumulated text content, or None if helper not found
        """
        ctx = self._helper_contexts.get(helper_id)
        return ctx.content if ctx else None

    def start_event_pump(self) -> None:
        """Start the event pump for relaying streaming events.

        The event pump polls all running sessions for events and relays them
        through TaskStateService. This should be called when the service is
        ready to handle WebSocket connections.

        The pump is idempotent - calling multiple times is safe.
        """
        if self._pump_running:
            debug_log.info("start_event_pump: already running", category="stream")
            return

        debug_log.info("start_event_pump: starting pump task", category="stream")
        self._pump_running = True
        self._pump_task = asyncio.create_task(self._event_pump_loop())

    def stop_event_pump(self) -> None:
        """Stop the event pump.

        Call this when shutting down the service.
        """
        self._pump_running = False
        if self._pump_task and not self._pump_task.done():
            self._pump_task.cancel()

    def register_streaming_context(
        self,
        session_id: str,
        exchange_id: str,
        user_turn_idx: int,
        user_turn_id: str = "",
        assistant_turn_idx: int = -1,
        assistant_turn_id: str = "",
    ) -> None:
        """Pre-register a streaming context with known turn information.

        Use this when starting a stream with known turn indices (e.g., from TUI
        or submit_message). The event pump will use this context to track state
        and emit proper turn IDs.

        If not pre-registered, the pump creates minimal contexts automatically
        when events arrive, but those won't have correct exchange_id or turn indices
        until they're discovered from the events themselves.

        Args:
            session_id: Session to register
            exchange_id: Exchange ID for tracking
            user_turn_idx: Index of the user turn
            user_turn_id: Stable UUID for the user turn
            assistant_turn_idx: Index of the assistant turn (if known)
            assistant_turn_id: Stable UUID for the assistant turn (if known)
        """
        from core.debug_log import debug_log
        if session_id in self._streaming_contexts:
            debug_log.debug(
                f"register_streaming_context: session already registered",
                category="websocket",
                session_id=session_id,
            )
            return

        ctx = _StreamingContext(
            session_id=session_id,
            exchange_id=exchange_id,
            user_turn_idx=user_turn_idx,
            user_turn_id=user_turn_id,
            assistant_turn_idx=assistant_turn_idx,
            assistant_turn_id=assistant_turn_id,
        )
        self._streaming_contexts[session_id] = ctx
        debug_log.debug(
            f"register_streaming_context: registered for event pumping",
            category="websocket",
            session_id=session_id,
        )

    def release_streaming_context(self, session_id: str) -> dict | None:
        """Release ownership of a streaming session to another component (e.g., TUI).

        This removes the streaming context from this service, allowing another
        component to poll events from the session without race conditions.

        Call this when the TUI wants to take ownership of a session that was
        submitted via React. The TUI will handle event dispatch and TaskStateService
        emission.

        Args:
            session_id: Session to release

        Returns:
            Dict with context state (content, assistant_turn_idx) if released, None otherwise
        """
        from core.debug_log import debug_log
        if session_id in self._streaming_contexts:
            ctx = self._streaming_contexts[session_id]
            # Capture state to return to caller so they can continue from where we left off
            state = {
                "content": ctx.content,
                "assistant_turn_idx": ctx.assistant_turn_idx,
                "assistant_turn_id": ctx.assistant_turn_id,
                "tool_count": ctx.tool_count,
            }
            debug_log.debug(
                f"release_streaming_context: turn_idx={ctx.assistant_turn_idx}, content_len={len(ctx.content)}",
                category="websocket",
                session_id=session_id,
            )
            del self._streaming_contexts[session_id]
            return state
        return None

    async def _event_pump_loop(self) -> None:
        """Main event pump loop - polls sessions and relays events."""
        debug_log.info("Event pump loop started", category="stream")
        while self._pump_running:
            try:
                await self._pump_events()
                await asyncio.sleep(self._pump_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log but don't crash the pump
                debug_log.error(f"Pump error: {e}", category="stream")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(self._pump_interval)

    async def _pump_events(self) -> None:
        """Poll ALL sessions and helper runners, relay events to observers.

        This is the central event pump for the application. It polls all active
        sessions and helper runners, dispatching events to registered observers
        (SessionDataService, TUI, etc.) through the observer pattern.

        Sessions are polled regardless of whether they have a streaming context.
        If a session has events but no context, a minimal context is created
        on-the-fly to track basic state (turn indices, accumulated content).
        """
        # Poll ALL sessions from the manager
        polled = list(self._manager.poll_all())
        for session_id, events in polled:
            if not events:
                continue

            # Log that we have events to process
            debug_log.debug(
                f"_pump_events: got {len(events)} events for session",
                category="stream",
                details={
                    "session_id": session_id[:8],
                    "event_types": [e.event_type for e in events[:5]],
                },
            )

            # Get or create streaming context for this session
            ctx = self._streaming_contexts.get(session_id)
            if not ctx:
                # Create minimal context for sessions without explicit registration
                # This handles sessions started via TUI that haven't called submit_message
                ctx = _StreamingContext(
                    session_id=session_id,
                    exchange_id="",  # Will be set by turn_started if present
                    user_turn_idx=-1,  # Unknown
                )
                self._streaming_contexts[session_id] = ctx

            for event in events:
                await self._dispatch_event(session_id, event, ctx)

        # Poll helper runners
        await self._pump_helper_events()

    async def _pump_helper_events(self) -> None:
        """Poll all helper runners and dispatch events to observers."""
        helpers_to_remove = []

        for helper_id, helper_runner in list(self._helper_runners.items()):
            ctx = self._helper_contexts.get(helper_id)
            if not ctx:
                continue

            events = helper_runner.drain_events()
            for event in events:
                await self._dispatch_helper_event(helper_id, event, ctx)

            # Mark for removal if done
            if helper_runner.is_done:
                helpers_to_remove.append(helper_id)

        # Clean up completed helpers
        for helper_id in helpers_to_remove:
            if helper_id in self._helper_runners:
                del self._helper_runners[helper_id]
            # Note: Keep context around briefly for result retrieval
            # It will be cleaned up by the completion handler

    async def _dispatch_helper_event(
        self, helper_id: str, event: Any, ctx: _HelperContext
    ) -> None:
        """Dispatch a helper runner event to observers.

        Args:
            helper_id: The helper this event belongs to
            event: StreamEvent from the HelperRunner
            ctx: Helper context for tracking state
        """
        event_type = event.event_type
        data = event.data

        if event_type == "text":
            # Text delta - accumulate and emit
            text = data if isinstance(data, str) else str(data)
            ctx.content += text

            await self._notify_observers(
                "on_helper_delta",
                HelperDeltaEvent(
                    helper_id=helper_id,
                    helper_type=ctx.helper_type,
                    delta=text,
                    accumulated_length=len(ctx.content),
                ),
            )

        elif event_type == "done":
            # Helper complete
            await self._notify_observers(
                "on_helper_done",
                HelperDoneEvent(
                    helper_id=helper_id,
                    helper_type=ctx.helper_type,
                    result=ctx.content,
                    metadata=ctx.metadata,
                ),
            )
            # Clean up context
            if helper_id in self._helper_contexts:
                del self._helper_contexts[helper_id]

        elif event_type == "error":
            # Helper failed
            error_msg = data if isinstance(data, str) else str(data)
            await self._notify_observers(
                "on_helper_error",
                HelperErrorEvent(
                    helper_id=helper_id,
                    helper_type=ctx.helper_type,
                    error=error_msg,
                    cancelled=False,
                ),
            )
            # Clean up context
            if helper_id in self._helper_contexts:
                del self._helper_contexts[helper_id]

        elif event_type == "cancelled":
            # Helper cancelled
            await self._notify_observers(
                "on_helper_error",
                HelperErrorEvent(
                    helper_id=helper_id,
                    helper_type=ctx.helper_type,
                    error=None,
                    cancelled=True,
                ),
            )
            # Clean up context
            if helper_id in self._helper_contexts:
                del self._helper_contexts[helper_id]

    async def _dispatch_event(
        self, session_id: str, event: Any, ctx: _StreamingContext
    ) -> None:
        """Dispatch a single streaming event to observers and legacy services.

        Converts SessionRunner events to typed observer events and service emit calls.
        All registered observers receive typed event dataclasses.
        Legacy TaskStateService and SessionDataService also receive events for
        backwards compatibility during migration.

        Args:
            session_id: The session this event belongs to
            event: StreamEvent from the SessionRunner
            ctx: Streaming context for tracking state
        """
        # Note: We always process events now, even without task_service or session_data_service,
        # because observers may be registered.

        event_type = event.event_type
        data = event.data

        if event_type == "turn_started":
            # Initial turn_started event - update context with turn info
            ctx.assistant_turn_idx = data.get("turn_index", ctx.user_turn_idx + 1)
            ctx.assistant_turn_id = data.get("turn_id", "")

            # Notify observers with typed event
            await self._notify_observers(
                "on_turn_created",
                TurnCreatedEvent(
                    session_id=session_id,
                    turn_id=ctx.assistant_turn_id,
                    turn_index=ctx.assistant_turn_idx,
                    role="assistant",
                    exchange_id=ctx.exchange_id,
                    content_block_type="text",
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
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

            # Update TreeState so TUI can observe streaming content
            if self._tree_state:
                self._tree_state.update_turn_content(
                    session_id, ctx.assistant_turn_idx, ctx.content
                )

            # Update stream state with approximate token count
            approx_tokens = len(ctx.content) // 4
            self._stream_state.update_stream(ctx.exchange_id, tokens_streamed=approx_tokens)

            # Notify observers with typed event
            await self._notify_observers(
                "on_turn_delta",
                TurnDeltaEvent(
                    session_id=session_id,
                    turn_id=ctx.assistant_turn_id,
                    turn_index=ctx.assistant_turn_idx,
                    delta=text,
                    accumulated_length=len(ctx.content),
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
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
            turn_id = data.get("turn_id", ctx.assistant_turn_id) if isinstance(data, dict) else ctx.assistant_turn_id

            # Notify observers with typed event
            await self._notify_observers(
                "on_turn_finished",
                TurnFinishedEvent(
                    session_id=session_id,
                    turn_id=turn_id,
                    turn_index=turn_idx,
                    role="assistant",
                    content=text,
                    tokens=len(text) // 4,
                    content_block=TextBlock(type="text", text=text),
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
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
            turn_id = data.get("turn_id", "") if isinstance(data, dict) else ""
            ctx.assistant_turn_idx = turn_idx  # Update for subsequent content deltas
            ctx.assistant_turn_id = turn_id  # Update turn_id for subsequent events
            ctx.content = ""  # Reset accumulated content for new turn

            # Notify observers with typed event
            await self._notify_observers(
                "on_turn_created",
                TurnCreatedEvent(
                    session_id=session_id,
                    turn_id=turn_id,
                    turn_index=turn_idx,
                    role="assistant",
                    exchange_id=ctx.exchange_id,
                    content_block_type="text",
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
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

            debug_log.info(
                f"_dispatch_event: tool_use_start",
                category="stream",
                details={
                    "session_id": session_id[:8],
                    "tool_name": tool_name,
                    "tool_use_id": tool_use_id[:12],
                    "num_observers": len(self._observers),
                },
            )

            # Update stream state
            self._stream_state.update_stream(
                ctx.exchange_id,
                status=StreamStatus.EXECUTING,
                tool_name=tool_name,
                tool_count=ctx.tool_count,
            )

            # Notify observers with typed event
            await self._notify_observers(
                "on_tool_use_started",
                ToolUseStartedEvent(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_index=ctx.assistant_turn_idx,
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    tool_index=tool_idx,
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
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

            # Notify observers with typed event
            await self._notify_observers(
                "on_tool_input_delta",
                ToolInputDeltaEvent(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    tool_use_id=tool_use_id,
                    partial_json=partial_json,
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
                self._task_service.emit_tool_input_delta(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    tool_use_id=tool_use_id,
                    partial_json=partial_json,
                )

        elif event_type == "tool_use_turn_started":
            # Tool use turn started - track turn index and ID
            turn_idx = data.get("turn_index", ctx.assistant_turn_idx) if isinstance(data, dict) else ctx.assistant_turn_idx
            turn_id = data.get("turn_id", "") if isinstance(data, dict) else ""
            tool_use_id = data.get("tool_use_id", "")
            ctx.tool_turn_indices[(tool_use_id, "tool_use")] = turn_idx
            ctx.tool_turn_ids[(tool_use_id, "tool_use")] = turn_id

            # Notify observers with typed event
            await self._notify_observers(
                "on_turn_created",
                TurnCreatedEvent(
                    session_id=session_id,
                    turn_id=turn_id,
                    turn_index=turn_idx,
                    role="assistant",
                    exchange_id=ctx.exchange_id,
                    content_block_type="tool_use",
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
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
            debug_log.info(
                f"_dispatch_event: tool_use",
                category="stream",
                details={
                    "session_id": session_id[:8],
                    "tool_use_id": tool_use_id[:20] if tool_use_id else "",
                    "tool_name": tool_name,
                },
            )
            tool_input = data.get("tool_input", {})
            tool_idx = data.get("tool_index", 0)
            turn_idx = data.get("turn_index", ctx.assistant_turn_idx)
            turn_id = ctx.tool_turn_ids.get((tool_use_id, "tool_use"), "")

            # Create ToolUseBlock for the content
            tool_use_block = ToolUseBlock(
                type="tool_use",
                id=tool_use_id,
                name=tool_name,
                input=tool_input,
            )

            # Notify observers with typed events
            await self._notify_observers(
                "on_tool_use",
                ToolUseEvent(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_index=turn_idx,
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_index=tool_idx,
                ),
            )
            # Also emit turn_finished for the tool_use turn
            await self._notify_observers(
                "on_turn_finished",
                TurnFinishedEvent(
                    session_id=session_id,
                    turn_id=turn_id,
                    turn_index=turn_idx,
                    role="assistant",
                    content="",  # Tool use turns have content_block instead
                    tokens=0,
                    content_block=tool_use_block,
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
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
            # Tool result turn started - track turn index and ID
            turn_idx = data.get("turn_index", ctx.assistant_turn_idx) if isinstance(data, dict) else ctx.assistant_turn_idx
            turn_id = data.get("turn_id", "") if isinstance(data, dict) else ""
            tool_use_id = data.get("tool_use_id", "")
            ctx.tool_turn_indices[(tool_use_id, "tool_result")] = turn_idx
            ctx.tool_turn_ids[(tool_use_id, "tool_result")] = turn_id

            # Notify observers with typed event
            await self._notify_observers(
                "on_turn_created",
                TurnCreatedEvent(
                    session_id=session_id,
                    turn_id=turn_id,
                    turn_index=turn_idx,
                    role="tool",
                    exchange_id=ctx.exchange_id,
                    content_block_type="tool_result",
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
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
            turn_id = data.get("turn_id", ctx.tool_turn_ids.get((tool_use_id, "tool_result"), ""))
            tool_name = ctx.tool_names.get(tool_use_id, "")

            # Update stream state - back to streaming
            self._stream_state.update_stream(
                ctx.exchange_id,
                status=StreamStatus.STREAMING,
                tool_name=None,
            )

            # Create ToolResultBlock for the content
            result_str = result if isinstance(result, str) else str(result)
            tool_result_block = ToolResultBlock(
                type="tool_result",
                tool_use_id=tool_use_id,
                content=result_str,
                is_error=False,
            )

            # Notify observers with typed events
            await self._notify_observers(
                "on_tool_result",
                ToolResultEvent(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_index=turn_idx,
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    result=result,
                    is_error=False,
                    tool_index=tool_idx,
                ),
            )
            # Also emit turn_finished for the tool_result turn
            await self._notify_observers(
                "on_turn_finished",
                TurnFinishedEvent(
                    session_id=session_id,
                    turn_id=turn_id,
                    turn_index=turn_idx,
                    role="tool",
                    content="",  # Tool result turns have content_block instead
                    tokens=0,
                    content_block=tool_result_block,
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
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
            # Note: No SessionDataService equivalent - this is metadata only
            model = data.get("model", "")
            context_window = data.get("context_window", 0)
            self._stream_state.update_stream(
                ctx.exchange_id,
                model=model,
                context_window=context_window,
            )

        elif event_type == "result":
            # Usage stats - update stream state
            # Note: No SessionDataService equivalent - this is metadata only
            input_tokens = data.get("input_tokens", 0)
            output_tokens = data.get("output_tokens", 0)
            self._stream_state.update_stream(
                ctx.exchange_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        elif event_type == "done":
            # Stream complete - emit final turn_finished and clean up
            # Always emit turnFinished to finalize the turn state (even if content is empty)
            # This ensures the web client properly clears streaming state

            # Get token counts from stream state (may have been updated by result event)
            stream = self._stream_state.get_stream(ctx.exchange_id)
            input_tokens = stream.input_tokens if stream else 0
            output_tokens = stream.output_tokens if stream else 0

            # Notify observers with typed events
            await self._notify_observers(
                "on_turn_finished",
                TurnFinishedEvent(
                    session_id=session_id,
                    turn_id=ctx.assistant_turn_id,
                    turn_index=ctx.assistant_turn_idx,
                    role="assistant",
                    content=ctx.content,
                    tokens=len(ctx.content) // 4,
                    content_block=TextBlock(type="text", text=ctx.content),
                ),
            )
            await self._notify_observers(
                "on_stream_done",
                StreamDoneEvent(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
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

            # Notify observers with typed event
            await self._notify_observers(
                "on_stream_error",
                StreamErrorEvent(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    error=error_msg,
                    error_type="error",
                ),
            )

            # Note: No SessionDataService equivalent for error events
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

            # Notify observers with typed event
            await self._notify_observers(
                "on_stream_error",
                StreamErrorEvent(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    error=f"Rate limit: {error_msg}",
                    error_type="rate_limit",
                ),
            )

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

            # Notify observers with typed event
            await self._notify_observers(
                "on_stream_error",
                StreamErrorEvent(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    error="Stream cancelled",
                    error_type="cancelled",
                ),
            )

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

            # Notify observers with typed events
            if ctx.content:
                await self._notify_observers(
                    "on_turn_finished",
                    TurnFinishedEvent(
                        session_id=session_id,
                        turn_id=ctx.assistant_turn_id,
                        turn_index=ctx.assistant_turn_idx,
                        role="assistant",
                        content=ctx.content,
                        tokens=len(ctx.content) // 4,
                        content_block=TextBlock(type="text", text=ctx.content),
                    ),
                )
            await self._notify_observers(
                "on_stream_done",
                StreamDoneEvent(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                ),
            )

            # Legacy service calls (to be removed after migration)
            if ctx.content and self._task_service:
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
            # Reload TreeState from Session so web clients see all turns via getTurns()
            # This is critical regardless of who drove the streaming (SessionManagerService or TUI)
            # because the session's turns are updated by the runner, and TreeState needs to
            # pick up those changes for the web UI to display them correctly
            if self._tree_state:
                self._tree_state.stop_streaming(stream.session_id)
                session = self._manager.get_session(stream.session_id)
                if session:
                    self._tree_state.load_session(stream.session_id, session)

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
        messages: list | None = None,  # Internal: list of Turn objects for context
        queue: bool = False,
        allowed_tools: list[str] | None = None,
    ) -> SubmitMessageResult:
        """Submit a message to a session and start streaming the response.

        This is the primary way for frontends to interact with the LLM.
        The message is added to the session and streaming begins immediately
        (unless queue=True, in which case it waits for current stream to finish).

        After calling this method, listen for streaming events via the observer pattern:
        - on_turn_delta: Streaming text chunks
        - on_tool_use_started: Tool execution beginning
        - on_tool_result: Tool execution completed
        - on_turn_finished: Exchange completed

        Args:
            session_id: ID of the session to submit to
            content: The message content (user prompt)
            messages: Context messages to include. If None, uses all session turns.
                      This allows frontends to curate which context is sent to the LLM.
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
        user_turn = session.add_message(
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

        # Emit user turn events via observer pattern
        await self._notify_observers(
            "on_turn_created",
            TurnCreatedEvent(
                session_id=session_id,
                turn_id=user_turn.id,
                turn_index=turn_index,
                role="user",
                exchange_id=exchange_id,
                content_block_type="text",
            ),
        )
        await self._notify_observers(
            "on_turn_finished",
            TurnFinishedEvent(
                session_id=session_id,
                turn_id=user_turn.id,
                turn_index=turn_index,
                role="user",
                content=content,
                tokens=0,  # User turns don't have token counts
                content_block=TextBlock(type="text", text=content),
            ),
        )

        # TaskStateService calls (doesn't use observer pattern)
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

        # Generate assistant turn ID for tracking streaming events
        assistant_turn_id = str(uuid.uuid4())
        assistant_turn_idx = turn_index + 1

        # Note: Don't pre-create assistant turn - it will be created when
        # turn_started event arrives from the runner with the actual turn_id

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
            user_turn_id=user_turn.id,
            assistant_turn_idx=turn_index + 1,  # Next turn will be assistant
            assistant_turn_id=assistant_turn_id,  # Track for streaming events (may be updated by runner)
        )

        # Notify observers that streaming is starting
        await self._notify_observers(
            "on_stream_started",
            StreamStartedEvent(
                session_id=session_id,
                exchange_id=exchange_id,
                prompt=content,
            ),
        )

        # Emit message submitted event BEFORE starting the runner
        # This allows TUI to call release_streaming_context before any events are processed
        self._emit_event(
            SessionManagerEvent.MESSAGE_SUBMITTED,
            session_id,
            {"exchange_id": exchange_id, "turn_index": turn_index, "content": content},
        )

        # Start background streaming
        # Use provided messages for context, or fall back to all session turns
        context_messages = messages if messages is not None else session.turns
        runner.start_background(
            prompt=content,
            messages=context_messages,
            allowed_tools=allowed_tools,
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
        user_turn = session.add_message(
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

        # Emit user turn events via observer pattern
        await self._notify_observers(
            "on_turn_created",
            TurnCreatedEvent(
                session_id=session_id,
                turn_id=user_turn.id,
                turn_index=turn_index,
                role="user",
                exchange_id=exchange_id,
                content_block_type="text",
            ),
        )
        await self._notify_observers(
            "on_turn_finished",
            TurnFinishedEvent(
                session_id=session_id,
                turn_id=user_turn.id,
                turn_index=turn_index,
                role="user",
                content=display_content,
                tokens=0,  # User turns don't have token counts
                content_block=TextBlock(type="text", text=display_content),
            ),
        )

        # TaskStateService calls (doesn't use observer pattern)
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

        # Generate assistant turn ID for tracking streaming events
        assistant_turn_id = str(uuid.uuid4())
        assistant_turn_idx = turn_index + 1

        # Note: Don't pre-create assistant turn - it will be created when
        # turn_started event arrives from the runner with the actual turn_id

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
            user_turn_id=user_turn.id,
            assistant_turn_idx=turn_index + 1,
            assistant_turn_id=assistant_turn_id,  # Track for streaming events (may be updated by runner)
        )

        # Notify observers that streaming is starting
        await self._notify_observers(
            "on_stream_started",
            StreamStartedEvent(
                session_id=session_id,
                exchange_id=exchange_id,
                prompt=content,
            ),
        )

        # Emit message submitted event BEFORE starting the runner
        # This allows TUI to call release_streaming_context before any events are processed
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
