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
from core.context import ContextBuilder
from core.fork import ForkManager, ForkResult, MergeResult, ForkData, DeriveResult, DeriveData, SwitchResult
from core.manager import SessionManager
from core.stream_state import (
    StreamState,
    StreamEvent as StreamStateEvent,
    Stream,
    StreamStatus,
    get_stream_state,
)
from core.tree_state import TreeState, TreeEvent
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
class ForkSessionResult:
    """Result of a fork_session operation.

    The fork may need context compression before it can start streaming.
    If needs_compression is True, the client should wait for compression
    to complete before the fork is ready.
    """

    success: bool
    child_session_id: str = ""
    parent_session_id: str = ""
    fork_name: str = ""
    exchange_id: str = ""  # Exchange ID for tracking the fork's stream
    needs_compression: bool = False
    helper_id: str = ""  # ID of compression helper if compression needed
    error: str = ""


@ws_type
@dataclass
class MergeSessionResult:
    """Result of a merge_session operation."""

    success: bool
    fork_session_id: str = ""
    parent_session_id: str = ""
    merge_id: str = ""
    merge_point: int = 0  # Turn index in parent where merge was inserted
    error: str = ""


@ws_type
@dataclass
class DeriveSessionResult:
    """Result of a derive_session operation.

    Derive creates a new independent session from selected context.
    Unlike fork, the new session has no parent relationship.
    """

    success: bool
    new_session_id: str = ""
    source_session_id: str = ""
    exchange_id: str = ""  # Exchange ID for tracking the session's stream
    needs_compression: bool = False
    helper_id: str = ""  # ID of compression helper if compression needed
    error: str = ""


@ws_type
@dataclass
class SwitchTargetResult:
    """Result of a find_switch_target operation."""

    success: bool
    target_session_id: str = ""
    available_forks: list[dict] = field(default_factory=list)
    error: str = ""


@ws_type
@dataclass
class ContextModeItem:
    """Describes context mode for a turn in fork/derive operations.

    Used by frontends to specify which turns to COPY, COMPRESS, or DROP.
    """

    turn_index: int
    mode: str  # "copy", "compress", "drop"


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

        # ForkManager for fork/derive/merge operations
        self._context_builder = ContextBuilder()
        self._fork_manager = ForkManager(self._context_builder)

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
    async def fork_session(
        self,
        parent_session_id: str,
        prompt: str,
        name: str = "",
        background: bool = False,
        context_modes: list[dict] | None = None,
        allowed_tools: list[str] | None = None,
        start_streaming: bool = True,
    ) -> ForkSessionResult:
        """Fork a new session from an existing parent session.

        Creates a child session with selected context from the parent.
        Context can be copied verbatim, compressed via LLM, or dropped.

        If compression is needed, returns immediately with needs_compression=True
        and helper_id. The client should then listen for helper events and call
        complete_fork_after_compression() when done.

        Args:
            parent_session_id: ID of the session to fork from
            prompt: Initial prompt for the fork
            name: Optional name for the fork (e.g., "auth-bug")
            background: If True, run in background and stay in parent session
            context_modes: List of {turn_index, mode} dicts. Mode is "copy", "compress", or "drop".
                          If not provided, all turns are copied.
            allowed_tools: List of tool names to allow, or None for all tools
            start_streaming: If True, start streaming after fork creation. Set False
                           if you want to handle streaming separately.

        Returns:
            ForkSessionResult with child session info and streaming state
        """
        # Get parent session
        parent_session = self._manager.get_session(parent_session_id)
        if not parent_session:
            parent_session = await self._manager.load_session(parent_session_id)
            if not parent_session:
                return ForkSessionResult(success=False, error=f"Parent session {parent_session_id} not found")

        # Get context modes - either from parameter or from TreeState
        from core.tree_state import ContextMode
        tree_modes: dict[int, ContextMode] = {}
        if context_modes:
            # Use provided context_modes
            for cm in context_modes:
                turn_idx = cm.get("turn_index")
                mode_str = cm.get("mode", "copy")
                if mode_str == "compress":
                    tree_modes[turn_idx] = ContextMode.COMPRESS
                elif mode_str == "drop":
                    tree_modes[turn_idx] = ContextMode.DROP
                else:
                    tree_modes[turn_idx] = ContextMode.COPY
        elif self._tree_state:
            # Use TreeState's context modes (set via UI)
            tree_modes = self._tree_state.get_context_modes_for_session(parent_session_id)

        # Build indexed messages with context modes
        from models import Message
        indexed_messages = []
        for turn_idx, turn in enumerate(parent_session.turns):
            # Get context mode for this turn
            mode = tree_modes.get(turn_idx, ContextMode.COPY)

            # Skip dropped turns
            if mode == ContextMode.DROP:
                continue

            # Create a message with context_mode attribute
            msg = Message(
                role=turn.role,
                content=turn.content,
                content_blocks=turn.content_blocks,
            )
            msg.context_mode = mode

            indexed_messages.append((msg, turn_idx))

        # Use provided tools or get all available
        tools = allowed_tools or []

        # Prepare fork via ForkManager
        result = await self._fork_manager.prepare_fork(
            current_session=parent_session,
            indexed_messages=indexed_messages,
            prompt=prompt,
            allowed_tools=tools,
            name=name,
            background=background,
        )

        if not result.success:
            return ForkSessionResult(success=False, error=result.error or "Fork failed")

        child_session = result.child_session

        # Register child session with manager (creates runner)
        self._manager.register_session(child_session)

        # Update TreeState
        if self._tree_state:
            self._tree_state.add_session(child_session, is_current=not background)
            self._tree_state.load_session(child_session.id, child_session)

        if result.needs_compression:
            # Start compression helper
            helper_id = result.helper_id
            self.start_helper(
                helper_id=helper_id,
                helper_type="compress",
                prompt=result.compression_prompt,
                session_id=parent_session_id,
                metadata={
                    "fork_data": result.fork_data,
                    "parent_session_id": parent_session_id,
                    "child_session_id": child_session.id,
                },
            )

            return ForkSessionResult(
                success=True,
                child_session_id=child_session.id,
                parent_session_id=parent_session_id,
                fork_name=name or child_session.id[:8],
                needs_compression=True,
                helper_id=helper_id,
            )

        # No compression needed - optionally start streaming
        exchange_id = ""
        if start_streaming and prompt:
            # Submit the prompt to start streaming
            submit_result = await self.submit_message(
                session_id=child_session.id,
                content=prompt,
                messages=child_session.turns,
                allowed_tools=tools,
            )
            exchange_id = submit_result.exchange_id

        self._emit_event(SessionManagerEvent.SESSION_CREATED, child_session.id)

        return ForkSessionResult(
            success=True,
            child_session_id=child_session.id,
            parent_session_id=parent_session_id,
            fork_name=name or child_session.id[:8],
            exchange_id=exchange_id,
            needs_compression=False,
        )

    @ws_expose
    async def complete_fork_after_compression(
        self,
        helper_id: str,
        compressed_summary: str,
        start_streaming: bool = True,
    ) -> ForkSessionResult:
        """Complete a fork after context compression finishes.

        Called when the compression helper completes. Inserts the summary
        at the correct position and finalizes the fork.

        Args:
            helper_id: ID of the compression helper
            compressed_summary: LLM-generated summary of compressed context
            start_streaming: If True, start streaming after fork is ready

        Returns:
            ForkSessionResult with the completed fork info
        """
        # Get the helper context with fork data
        helper_ctx = self._helper_contexts.get(helper_id)
        if not helper_ctx or not helper_ctx.metadata.get("fork_data"):
            return ForkSessionResult(success=False, error="No fork data found for helper")

        fork_data = helper_ctx.metadata["fork_data"]
        parent_session_id = helper_ctx.metadata.get("parent_session_id", "")

        # Complete the fork via ForkManager
        result = await self._fork_manager.complete_fork_after_compression(
            fork_data=fork_data,
            compressed_summary=compressed_summary,
        )

        if not result.success:
            return ForkSessionResult(success=False, error=result.error or "Fork completion failed")

        child_session = result.child_session

        # Clean up helper
        self._helper_contexts.pop(helper_id, None)
        self._helper_runners.pop(helper_id, None)

        # Start streaming if requested
        exchange_id = ""
        if start_streaming and result.prompt:
            submit_result = await self.submit_message(
                session_id=child_session.id,
                content=result.prompt,
                messages=child_session.turns,
                allowed_tools=result.allowed_tools or [],
            )
            exchange_id = submit_result.exchange_id

        self._emit_event(SessionManagerEvent.SESSION_CREATED, child_session.id)

        return ForkSessionResult(
            success=True,
            child_session_id=child_session.id,
            parent_session_id=parent_session_id,
            fork_name=result.name or child_session.id[:8],
            exchange_id=exchange_id,
            needs_compression=False,
        )

    @ws_expose
    async def validate_merge(
        self,
        fork_session_id: str,
    ) -> MergeSessionResult:
        """Validate that a merge is possible for a fork session.

        Use this to check if merge is valid before generating a summary.
        Returns the parent session ID if valid.

        Args:
            fork_session_id: ID of the fork session to validate

        Returns:
            MergeSessionResult with success=True if valid, otherwise error
        """
        # Get fork session
        fork_session = self._manager.get_session(fork_session_id)
        if not fork_session:
            fork_session = await self._manager.load_session(fork_session_id)
            if not fork_session:
                return MergeSessionResult(success=False, error=f"Fork session {fork_session_id} not found")

        # Validate the merge
        result = await self._fork_manager.prepare_merge(fork_session)
        if not result.success:
            return MergeSessionResult(success=False, error=result.error or "Not a valid fork")

        return MergeSessionResult(
            success=True,
            fork_session_id=fork_session_id,
            parent_session_id=result.parent_session.id,
        )

    @ws_expose
    async def merge_session(
        self,
        fork_session_id: str,
        merge_summary: str,
        files_changed: list[str] | None = None,
        key_accomplishments: list[str] | None = None,
        reason: str = "",
    ) -> MergeSessionResult:
        """Merge a fork session back to its parent.

        Creates a merge marker in both the fork and parent sessions,
        recording what was accomplished in the fork.

        Args:
            fork_session_id: ID of the fork session to merge
            merge_summary: Summary of what was accomplished in the fork
            files_changed: List of key files that were modified
            key_accomplishments: List of what was done
            reason: Why the merge is happening now

        Returns:
            MergeSessionResult with merge info
        """
        # Get fork session
        fork_session = self._manager.get_session(fork_session_id)
        if not fork_session:
            fork_session = await self._manager.load_session(fork_session_id)
            if not fork_session:
                return MergeSessionResult(success=False, error=f"Fork session {fork_session_id} not found")

        # Validate the merge
        result = await self._fork_manager.prepare_merge(fork_session)
        if not result.success:
            return MergeSessionResult(success=False, error=result.error or "Merge validation failed")

        parent_session = result.parent_session

        # Complete the merge
        merge_result = await self._fork_manager.complete_merge(
            fork_session=fork_session,
            parent_session=parent_session,
            merge_message=merge_summary,
            files_changed=files_changed,
            key_accomplishments=key_accomplishments,
            reason=reason,
        )

        if not merge_result.success:
            return MergeSessionResult(success=False, error=merge_result.error or "Merge failed")

        # Update manager with saved sessions
        self._manager.register_session(parent_session)

        # Update TreeState
        if self._tree_state:
            # Reload both sessions in tree state
            self._tree_state.load_session(fork_session.id, fork_session)
            self._tree_state.load_session(parent_session.id, parent_session)

        self._emit_event(SessionManagerEvent.SESSION_UPDATED, fork_session_id)
        self._emit_event(SessionManagerEvent.SESSION_UPDATED, parent_session.id)

        return MergeSessionResult(
            success=True,
            fork_session_id=fork_session_id,
            parent_session_id=parent_session.id,
            merge_id=merge_result.merge_id or "",
            merge_point=merge_result.merge_point or 0,
        )

    @ws_expose
    async def derive_session(
        self,
        source_session_id: str,
        prompt: str = "",
        context_modes: list[dict] | None = None,
        allowed_tools: list[str] | None = None,
        start_streaming: bool = True,
    ) -> DeriveSessionResult:
        """Derive a new independent session from selected context.

        Unlike fork, derive creates a session with no parent relationship.
        The new session is completely independent.

        Args:
            source_session_id: ID of the session to derive from
            prompt: Optional initial prompt for the derived session
            context_modes: List of {turn_index, mode} dicts. Mode is "copy", "compress", or "drop".
                          If not provided, all turns are copied.
            allowed_tools: List of tool names to allow, or None for all tools
            start_streaming: If True and prompt provided, start streaming after creation

        Returns:
            DeriveSessionResult with new session info
        """
        # Get source session
        source_session = self._manager.get_session(source_session_id)
        if not source_session:
            source_session = await self._manager.load_session(source_session_id)
            if not source_session:
                return DeriveSessionResult(success=False, error=f"Source session {source_session_id} not found")

        # Get context modes - either from parameter or from TreeState
        from core.tree_state import ContextMode
        tree_modes: dict[int, ContextMode] = {}
        if context_modes:
            # Use provided context_modes
            for cm in context_modes:
                turn_idx = cm.get("turn_index")
                mode_str = cm.get("mode", "copy")
                if mode_str == "compress":
                    tree_modes[turn_idx] = ContextMode.COMPRESS
                elif mode_str == "drop":
                    tree_modes[turn_idx] = ContextMode.DROP
                else:
                    tree_modes[turn_idx] = ContextMode.COPY
        elif self._tree_state:
            # Use TreeState's context modes (set via UI)
            tree_modes = self._tree_state.get_context_modes_for_session(source_session_id)

        # Build indexed messages with context modes
        from models import Message
        indexed_messages = []
        for turn_idx, turn in enumerate(source_session.turns):
            # Get context mode for this turn
            mode = tree_modes.get(turn_idx, ContextMode.COPY)

            # Skip dropped turns
            if mode == ContextMode.DROP:
                continue

            # Create a message with context_mode attribute
            msg = Message(
                role=turn.role,
                content=turn.content,
                content_blocks=turn.content_blocks,
            )
            msg.context_mode = mode

            indexed_messages.append((msg, turn_idx))

        # Use provided tools or get all available
        tools = allowed_tools or []

        # Prepare derive via ForkManager
        result = await self._fork_manager.prepare_derive(
            current_session=source_session,
            indexed_messages=indexed_messages,
            prompt=prompt,
            allowed_tools=tools,
        )

        if not result.success:
            return DeriveSessionResult(success=False, error=result.error or "Derive failed")

        new_session = result.new_session

        # Register new session with manager (creates runner)
        self._manager.register_session(new_session)

        # Update TreeState
        if self._tree_state:
            self._tree_state.add_session(new_session, is_current=True)
            self._tree_state.load_session(new_session.id, new_session)

        if result.needs_compression:
            # Start compression helper
            helper_id = result.helper_id
            self.start_helper(
                helper_id=helper_id,
                helper_type="derive",
                prompt=result.compression_prompt,
                session_id=source_session_id,
                metadata={
                    "derive_data": result.derive_data,
                    "source_session_id": source_session_id,
                    "new_session_id": new_session.id,
                },
            )

            return DeriveSessionResult(
                success=True,
                new_session_id=new_session.id,
                source_session_id=source_session_id,
                needs_compression=True,
                helper_id=helper_id,
            )

        # No compression needed - optionally start streaming
        exchange_id = ""
        if start_streaming and prompt:
            submit_result = await self.submit_message(
                session_id=new_session.id,
                content=prompt,
                messages=new_session.turns,
                allowed_tools=tools,
            )
            exchange_id = submit_result.exchange_id

        self._emit_event(SessionManagerEvent.SESSION_CREATED, new_session.id)

        return DeriveSessionResult(
            success=True,
            new_session_id=new_session.id,
            source_session_id=source_session_id,
            exchange_id=exchange_id,
            needs_compression=False,
        )

    @ws_expose
    async def complete_derive_after_compression(
        self,
        helper_id: str,
        compressed_summary: str,
        start_streaming: bool = True,
    ) -> DeriveSessionResult:
        """Complete a derive after context compression finishes.

        Args:
            helper_id: ID of the compression helper
            compressed_summary: LLM-generated summary of compressed context
            start_streaming: If True, start streaming after derive is ready

        Returns:
            DeriveSessionResult with the completed derive info
        """
        # Get the helper context with derive data
        helper_ctx = self._helper_contexts.get(helper_id)
        if not helper_ctx or not helper_ctx.metadata.get("derive_data"):
            return DeriveSessionResult(success=False, error="No derive data found for helper")

        derive_data = helper_ctx.metadata["derive_data"]
        source_session_id = helper_ctx.metadata.get("source_session_id", "")

        # Complete the derive via ForkManager
        result = await self._fork_manager.complete_derive_after_compression(
            derive_data=derive_data,
            compressed_summary=compressed_summary,
        )

        if not result.success:
            return DeriveSessionResult(success=False, error=result.error or "Derive completion failed")

        new_session = result.new_session

        # Clean up helper
        self._helper_contexts.pop(helper_id, None)
        self._helper_runners.pop(helper_id, None)

        # Start streaming if requested
        exchange_id = ""
        if start_streaming and result.prompt:
            submit_result = await self.submit_message(
                session_id=new_session.id,
                content=result.prompt,
                messages=new_session.turns,
                allowed_tools=result.allowed_tools or [],
            )
            exchange_id = submit_result.exchange_id

        self._emit_event(SessionManagerEvent.SESSION_CREATED, new_session.id)

        return DeriveSessionResult(
            success=True,
            new_session_id=new_session.id,
            source_session_id=source_session_id,
            exchange_id=exchange_id,
            needs_compression=False,
        )

    @ws_expose
    async def find_switch_target(
        self,
        session_id: str,
        name: str,
    ) -> SwitchTargetResult:
        """Find a session to switch to.

        Searches forks of current session, then parent's forks if in a fork.

        Args:
            session_id: Current session ID
            name: Fork name or session ID prefix, or "parent"/".."

        Returns:
            SwitchTargetResult with target session or available forks
        """
        # Get current session
        current_session = self._manager.get_session(session_id)
        if not current_session:
            current_session = await self._manager.load_session(session_id)
            if not current_session:
                return SwitchTargetResult(success=False, error=f"Session {session_id} not found")

        # Use ForkManager to find target
        result = await self._fork_manager.find_switch_target(current_session, name)

        if result.success and result.target_session:
            # Ensure target is loaded in manager
            await self._manager.load_session(result.target_session.id)
            return SwitchTargetResult(
                success=True,
                target_session_id=result.target_session.id,
            )
        else:
            return SwitchTargetResult(
                success=False,
                available_forks=result.available_forks or [],
                error=result.error or "",
            )

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

    # --- Backend Management ---

    @ws_expose
    async def list_backends(self) -> list[str]:
        """List all available backend names.

        Returns:
            List of backend name strings
        """
        from config import get_config

        config = get_config()
        return list(config.backends.keys())

    @ws_expose
    async def get_session_backend(self, session_id: str) -> str | None:
        """Get the backend name for a session.

        Args:
            session_id: ID of the session

        Returns:
            Effective backend name (explicit or default), or None if session not found
        """
        from config import get_config

        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return None

        # Return explicit backend if set, otherwise the default
        if session.backend_name:
            return session.backend_name
        config = get_config()
        return config.default_backend

    @ws_expose
    async def set_session_backend(
        self, session_id: str, backend_name: str
    ) -> bool:
        """Set the backend for a session.

        The new backend will be used for the next streaming request.
        Cannot change backend while streaming.

        Args:
            session_id: ID of the session to update
            backend_name: Name of the backend to use

        Returns:
            True if successful, False if session not found or invalid backend
        """
        from config import get_config
        from core.command_executor import CommandExecutor

        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return False

        # Can't change backend while streaming
        runner = self._manager.get_runner(session_id)
        if runner and runner.is_streaming:
            debug_log.warn(
                "Cannot change backend while streaming",
                category="backend",
                data={"session_id": session_id},
            )
            return False

        config = get_config()
        executor = CommandExecutor()
        result = executor.set_backend(session, backend_name, config)

        if result.success:
            # Save session to persist the change
            await session.save()

            # Update TreeState if available
            if self._tree_state:
                session_data = self._tree_state.get_session(session_id)
                if session_data:
                    # Update the SessionData cache so web UI sees the change
                    session_data.backend_name = backend_name
                    if session_data.session_ref:
                        # Also update the live Session object
                        session_data.session_ref.backend_name = backend_name
                # Notify observers about the session update
                self._tree_state.notify(TreeEvent.SESSION_UPDATED, session_id)

            debug_log.info(
                f"Backend changed to {backend_name}",
                category="backend",
                data={"session_id": session_id, "backend": backend_name},
            )
            return True
        else:
            debug_log.warn(
                f"Failed to set backend: {result.error}",
                category="backend",
                data={"session_id": session_id, "error": result.error},
            )
            return False

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
