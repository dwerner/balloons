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
from core.debug_log import debug_log, Category
from core.context import ContextBuilder
from core.fork import ForkManager, ForkResult, MergeResult, ForkData, DeriveResult, DeriveData, SwitchResult, ForkProposal, MergeProposal
from core.tool_executor import parse_fork_proposal, parse_merge_proposal
from core.manager import SessionManager
from core.stream_state import (
    StreamState,
    StreamEvent as StreamStateEvent,
    Stream,
    StreamStatus,
    get_stream_state,
)
# TreeState removed in Phase 8 - events go directly to SessionDataService
from core.queue_state import QueueState, QueueEvent, QueueSnapshot
from models import TextBlock, MarkdownBlock, ImageBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, Turn, SessionSummaryBlock
from service.session_events import (
    SessionEventObserver,
    TurnCreatedEvent,
    TurnDeltaEvent,
    TurnFinishedEvent,
    StreamStartedEvent,
    StreamDoneEvent,
    StreamProgressEvent,
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
class LinkSessionsResult:
    """Result of a link_sessions operation.

    Links create bidirectional references between sessions, allowing
    navigation and context sharing without a parent/child relationship.
    """

    success: bool
    link_id: str = ""  # Shared link ID in both sessions
    source_session_id: str = ""
    target_session_id: str = ""
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
class ExchangeSummary:
    """Summary of an exchange for display in fork/merge proposal UIs.

    Used by frontends to show what each exchange contains when reviewing
    a fork/merge proposal.
    """

    index: int  # Exchange index (0-based)
    summary: str  # Short summary of the exchange content
    mode: str = "compress"  # Default context mode for this exchange


@ws_type
@dataclass
class RespondToForkProposalResult:
    """Result of responding to a fork proposal (accept/reject).

    If accepted, contains the same fields as ForkSessionResult.
    If rejected, just indicates success.
    """

    success: bool
    accepted: bool = False
    # Only set if accepted and fork created:
    child_session_id: str = ""
    parent_session_id: str = ""
    fork_name: str = ""
    exchange_id: str = ""
    needs_compression: bool = False
    helper_id: str = ""
    error: str = ""


@ws_type
@dataclass
class RespondToMergeProposalResult:
    """Result of responding to a merge proposal (accept/reject).

    If accepted, contains the same fields as MergeSessionResult.
    If rejected, just indicates success.
    """

    success: bool
    accepted: bool = False
    # Only set if accepted and merge completed:
    fork_session_id: str = ""
    parent_session_id: str = ""
    merge_id: str = ""
    merge_point: int = 0
    error: str = ""


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


@ws_type
@dataclass
class StartArchiveResult:
    """Result of starting an archive operation.

    Archives require LLM-generated summaries, so the operation runs asynchronously.
    The helper_id can be used to track progress via helper events.
    """

    success: bool
    helper_id: str = ""  # ID for tracking the archive helper task
    session_id: str = ""  # Session being archived
    turn_start: int = 0  # First turn index being archived
    turn_end: int = 0  # End turn index (exclusive)
    error: str = ""


@ws_type
@dataclass
class CompleteArchiveResult:
    """Result of completing an archive after summary generation."""

    success: bool
    session_id: str = ""
    archive_id: str = ""  # ID of the archive block created
    turn_index: int = 0  # Index of the archive turn
    turns_archived: int = 0  # Number of turns that were archived
    helper_id: str = ""  # Helper ID for correlating with startArchive
    error: str = ""


@ws_type
@dataclass
class StartSessionReviewResult:
    """Result of starting a session review operation.

    Reviews require LLM-generated summaries, so the operation runs asynchronously.
    The helper_id can be used to track progress via helper events.
    """

    success: bool
    helper_id: str = ""  # ID for tracking the review helper task
    session_id: str = ""  # Session being reviewed
    backend_name: str = ""  # Backend generating the review
    error: str = ""


@ws_type
@dataclass
class CompleteSessionReviewResult:
    """Result of completing a session review after summary generation."""

    success: bool
    session_id: str = ""
    summary_id: str = ""  # ID of the SessionSummaryBlock created
    turn_index: int = 0  # Index of the review turn
    proposed_title: str = ""  # LLM-suggested title
    markdown_content: str = ""  # Full markdown summary
    error: str = ""


@ws_type
@dataclass
class ApproveSessionReviewResult:
    """Result of approving a session review."""

    success: bool
    session_id: str = ""
    summary_id: str = ""
    approved_title: str = ""
    error: str = ""


@ws_type
@dataclass
class GenerateCommitMessageResult:
    """Result of starting commit message generation.

    Commit message generation runs asynchronously via a helper task.
    The helper_id can be used to track progress via helper events.
    """

    success: bool
    helper_id: str = ""  # ID for tracking the helper task
    error: str = ""


@ws_type
@dataclass
class CreateWatcherSessionResult:
    """Result of creating a watcher session to observe another session.

    The watcher session will receive summaries of exchanges from the target
    session. The user can provide instructions to the watcher to guide
    summarization.
    """

    success: bool
    watcher_session_id: str = ""  # The new watcher session ID
    target_session_id: str = ""  # The session being watched
    target_session_name: str = ""  # Display name of the target
    watcher_name: str = ""  # Name of the watcher session (e.g., "watching:target-name")
    error: str = ""


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
    # Parallel tool tracking - multiple tool_use events before any result = parallel
    parallel_group_id: str | None = None  # Current parallel group (set on first tool, cleared on first result)
    pending_tool_count: int = 0  # Tools started but not yet resulted
    # Progress event throttling
    last_progress_emit: float = 0.0  # Timestamp of last progress event emission


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
        queue_state: "QueueState | None" = None,
    ):
        """Initialize service with a SessionManager instance.

        Args:
            session_manager: The SessionManager to expose via WebSocket
            stream_state: Optional StreamState for tracking streaming. Uses global if not provided.
            task_state_service: Optional TaskStateService for emitting streaming events.
                               If provided, the event pump will relay events to frontends.
            session_data_service: Optional SessionDataService for emitting session data events.
                                 If provided, events will be emitted in parallel with TaskStateService.
            queue_state: Optional QueueState for draining queued messages after streaming completes.
                        If provided, queued messages will be automatically submitted when streaming ends.
        """
        self._manager = session_manager
        self._stream_state = stream_state or get_stream_state()
        self._task_service = task_state_service
        self._session_data_service = session_data_service
        self._queue_state = queue_state
        self._event_handlers: list[Callable[[str, dict], None]] = []

        # Register as observer of QueueState to process messages for idle sessions
        if queue_state:
            queue_state.add_observer(self._on_queue_event)

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

        # Watcher mode tracking (MVP internal implementation)
        # Map: target_session_id -> list of watcher_session_ids
        self._watcher_targets: dict[str, list[str]] = {}
        # Map: watcher_session_id -> list of (target_session_id, target_name)
        self._watcher_watching: dict[str, list[tuple[str, str]]] = {}

        # Register SessionDataService as observer if provided
        if session_data_service is not None:
            self.add_observer(session_data_service)

        # Wire up StreamState observer to emit streaming events
        self._stream_state.add_observer(self._on_stream_event)

    async def initialize(self) -> None:
        """Initialize async components of the service.

        Call this after creating the service to:
        - Rebuild watcher relationships from persisted sessions

        This must be called before using watcher-related features.
        """
        await self._rebuild_all_watcher_relationships()

    async def _rebuild_all_watcher_relationships(self) -> None:
        """Load watcher relationships from LMDB storage.

        Called at startup to restore watcher relationships.
        This is now fast because watchers are stored as a proper entity.
        """
        from core.async_storage import get_watcher_storage

        debug_log.info(
            "Loading watcher relationships from storage",
            category=Category.SESSION,
        )

        try:
            watcher_storage = await get_watcher_storage()
            watchers = await watcher_storage.list_watchers()

            for watcher in watchers:
                await self._register_watcher_internal(
                    watcher.watcher_session_id,
                    watcher.target_session_id,
                    watcher.target_session_name,
                    source="startup",
                )

            debug_log.info(
                f"Loaded {len(watchers)} watcher relationships from storage",
                category=Category.SESSION,
            )
        except Exception as e:
            debug_log.error(
                f"Failed to load watcher relationships: {e}",
                category=Category.SESSION,
            )

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
                        category=Category.API,
                    )

    # --- Session Lifecycle Events (Phase 8) ---

    def _emit_session_added(self, session: Any, is_streaming: bool = False) -> None:
        """Emit a session added event to SessionDataService.

        Called when a new session is created (fork, derive, new).
        This is the new event path that will replace TreeState notifications.

        Args:
            session: The Session object that was added
            is_streaming: Whether the session is currently streaming
        """
        if self._session_data_service is None:
            return

        session_info = self._session_data_service.session_to_info(
            session,
            is_pinned=False,  # New sessions are not pinned
            is_streaming=is_streaming,
        )
        self._session_data_service.emit_session_added(session_info)

    def _emit_session_updated(self, session: Any, is_streaming: bool | None = None) -> None:
        """Emit a session updated event to SessionDataService.

        Called when session metadata changes (title, tokens, streaming state).

        Args:
            session: The Session object that was updated
            is_streaming: Override streaming state (None = check _streaming_contexts)
        """
        if self._session_data_service is None:
            return

        # Determine streaming state
        if is_streaming is None:
            is_streaming = session.id in self._streaming_contexts

        session_info = self._session_data_service.session_to_info(
            session,
            is_pinned=False,  # TODO: Check actual pinned state
            is_streaming=is_streaming,
        )
        self._session_data_service.emit_session_updated(session_info)

    def _emit_session_removed(self, session_id: str) -> None:
        """Emit a session removed event to SessionDataService.

        Called when a session is deleted.

        Args:
            session_id: The ID of the removed session
        """
        if self._session_data_service is None:
            return

        self._session_data_service.emit_session_removed(session_id)

    def _get_turns_grouped_by_exchange(self, session: Any) -> list[list[tuple[int, Any]]]:
        """Group session turns by exchange_id, including their indices.

        Returns a list of groups, where each group is a list of (index, Turn) tuples
        sharing the same exchange_id. Turns without an exchange_id are
        placed in their own single-turn group.

        Args:
            session: The Session object with turns

        Returns:
            List of turn groups as (index, turn) tuples, ordered by first turn index
        """
        groups: list[list[tuple[int, Any]]] = []
        exchange_to_group: dict[str, list[tuple[int, Any]]] = {}

        for idx, turn in enumerate(session.turns):
            exchange_id = getattr(turn, 'exchange_id', None)
            entry = (idx, turn)
            if exchange_id:
                if exchange_id in exchange_to_group:
                    exchange_to_group[exchange_id].append(entry)
                else:
                    group = [entry]
                    exchange_to_group[exchange_id] = group
                    groups.append(group)
            else:
                # No exchange_id - own group
                groups.append([entry])

        return groups

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

        SessionDataService receives all session lifecycle and streaming events.
        It provides subscription-based filtering so only subscribed clients
        receive events.

        Args:
            session_data_service: The SessionDataService to emit events through
        """
        self._session_data_service = session_data_service
        # Wire session loader so SessionDataService can load sessions from storage
        session_data_service.set_session_loader(self._manager.load_session)
        # Register as observer for the event pattern
        self.add_observer(session_data_service)

    def set_queue_state(self, queue_state: "QueueState") -> None:
        """Set the QueueState for draining queued messages after streaming.

        When streaming completes or is cancelled, queued messages are automatically
        drained and submitted. This enables the "type while streaming" workflow
        where users can queue messages that will be sent after the current
        response completes.

        Args:
            queue_state: The QueueState to use for queue draining
        """
        self._queue_state = queue_state

    async def _load_session_with_watcher_rebuild(self, session_id: str):
        """Load a session and rebuild watcher relationships if applicable.

        Use this instead of self._manager.load_session() when loading sessions
        that might be watchers.

        Args:
            session_id: Session ID to load

        Returns:
            The loaded session, or None if not found
        """
        session = await self._manager.load_session(session_id)
        if session:
            await self._rebuild_watcher_for_session(session)
        return session

    async def _on_queue_event(
        self,
        event: "QueueEvent",
        snapshot: "QueueSnapshot",
        data: dict,
    ) -> None:
        """Handle QueueState events.

        When a message from a WATCHER is added to a session's queue and that session
        is idle (not streaming), immediately process the queued message. This enables
        watcher-to-target messaging where the watcher queues a message and the
        target processes it right away if it's not busy.

        Regular user input (typed while streaming) should NOT trigger immediate
        processing - it stays in the queue until streaming ends.

        Args:
            event: The queue event type
            snapshot: Current queue state snapshot
            data: Additional event data (e.g., message_id, source)
        """
        if event != QueueEvent.MESSAGE_ADDED:
            return

        # Only process watcher messages immediately
        # Regular user input should wait for streaming to end
        source = data.get("source")
        if not source or not source.startswith("watcher:"):
            return

        session_id = snapshot.session_id
        if not session_id:
            return

        # Check if this session has a runner and if it's idle
        runner = self._manager.get_runner(session_id)
        if not runner:
            # No runner - session not loaded yet
            # Load it so we can process the watcher message
            debug_log.info(
                f"Watcher message for unloaded session {session_id[:8]} - loading session",
                category=Category.SESSION,
            )
            try:
                session = await self._manager.load_session(session_id)
                if session:
                    runner = self._manager.get_runner(session_id)
            except Exception as e:
                debug_log.error(
                    f"Failed to load session for watcher message: {e}",
                    category=Category.SESSION,
                )
                return

            if not runner:
                debug_log.error(
                    f"Session loaded but no runner created for {session_id[:8]}",
                    category=Category.SESSION,
                )
                return

        if runner.is_streaming:
            # Session is busy - message will be processed when streaming ends
            debug_log.debug(
                f"Watcher message for session {session_id[:8]} but streaming - will process on completion",
                category=Category.SESSION,
            )
            return

        # Session is idle - process queued messages immediately
        debug_log.info(
            f"Watcher message for idle session {session_id[:8]} - processing immediately",
            category=Category.SESSION,
            details={"message_id": data.get("message_id"), "source": source},
        )
        await self._process_queued_messages(session_id)

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
        backend_name: str | None = None,
    ) -> None:
        """Start a helper task for background LLM operations.

        Helper tasks are used for operations like context compression, merge summaries,
        archive summaries, etc. They use the session's configured backend by default,
        but can be overridden with a specific backend.

        Args:
            helper_id: Unique ID for this helper task
            helper_type: Type of helper ("compress", "derive", "archive", "merge", "link", "return", "session_review")
            prompt: The prompt to send to the LLM
            session_id: Session this helper is for (determines which backend to use)
            metadata: Type-specific data to pass to completion handlers
            backend_name: Optional explicit backend name (overrides session/default backend)
        """
        from core.runner import HelperRunner
        from config import get_config
        from core.runner_factory import create_runner

        config = get_config()

        # Determine which backend to use with cascade:
        # 1. Explicit backend_name param
        # 2. Session's configured backend
        # 3. Global default backend
        backend = None
        if backend_name:
            backend = config.get_backend(backend_name)
            if not backend:
                debug_log.warning(
                    f"Requested backend '{backend_name}' not found, falling back",
                    category=Category.RUNNER,
                )

        if not backend:
            session = None
            if session_id:
                session = self._manager.get_session(session_id)
            if session:
                backend = self._get_backend_for_session(session)

        if not backend:
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

    @ws_expose
    async def await_helper_result(
        self,
        helper_id: str,
        timeout_seconds: float = 30.0,
    ) -> str:
        """Wait for a helper task to complete and return its result.

        Polls the helper every 100ms until it completes or times out.
        This is a convenience method for frontends that don't want to
        handle helper events.

        Args:
            helper_id: ID of the helper to wait for
            timeout_seconds: Maximum time to wait (default 30s)

        Returns:
            The helper's accumulated text result, or empty string on timeout/error
        """
        import time

        start_time = time.time()
        poll_interval = 0.1  # 100ms

        poll_count = 0
        while time.time() - start_time < timeout_seconds:
            poll_count += 1
            # Check if helper exists
            ctx = self._helper_contexts.get(helper_id)
            if not ctx:
                # Helper not found or already cleaned up
                debug_log.info(
                    f"await_helper_result: ctx not found",
                    category=Category.RUNNER,
                    details={"helper_id": helper_id, "poll_count": poll_count},
                )
                return ""

            # Check if helper runner is done
            runner = self._helper_runners.get(helper_id)
            if not runner:
                debug_log.info(
                    f"await_helper_result: runner not found but ctx exists",
                    category=Category.RUNNER,
                    details={
                        "helper_id": helper_id,
                        "poll_count": poll_count,
                        "ctx_content_len": len(ctx.content),
                    },
                )
                # Runner was cleaned up but ctx still has content
                result = ctx.content.strip()
                self._helper_contexts.pop(helper_id, None)
                return result

            # Drain events from runner to populate ctx.content
            # This is needed because the main event pump may not run between our polls
            events = runner.drain_events()
            for event in events:
                await self._dispatch_helper_event(helper_id, event, ctx)

            if runner.is_done:
                # Done - return accumulated content
                result = ctx.content.strip()
                debug_log.info(
                    f"await_helper_result: returning result",
                    category=Category.RUNNER,
                    details={
                        "helper_id": helper_id,
                        "result_len": len(result),
                        "result_preview": result[:200] if result else "(empty)",
                    },
                )
                # Clean up
                self._helper_contexts.pop(helper_id, None)
                self._helper_runners.pop(helper_id, None)
                return result

            # Wait a bit before polling again
            await asyncio.sleep(poll_interval)

        # Timeout - return whatever we have
        ctx = self._helper_contexts.get(helper_id)
        result = ctx.content.strip() if ctx else ""
        # Clean up
        self._helper_contexts.pop(helper_id, None)
        self._helper_runners.pop(helper_id, None)
        return result

    def start_event_pump(self) -> None:
        """Start the event pump for relaying streaming events.

        The event pump polls all running sessions for events and relays them
        through TaskStateService. This should be called when the service is
        ready to handle WebSocket connections.

        The pump is idempotent - calling multiple times is safe.
        """
        if self._pump_running:
            debug_log.info("start_event_pump: already running", category=Category.RUNNER)
            return

        debug_log.info("start_event_pump: starting pump task", category=Category.RUNNER)
        self._pump_running = True
        self._pump_task = asyncio.create_task(self._event_pump_loop())

    def stop_event_pump(self) -> None:
        """Stop the event pump.

        Call this when shutting down the service.
        """
        self._pump_running = False
        if self._pump_task and not self._pump_task.done():
            self._pump_task.cancel()

    async def _process_queued_messages(self, session_id: str) -> None:
        """Drain and submit queued messages after streaming completes.

        This is called after streaming ends (done, cancelled, or input_required)
        to automatically send any messages the user typed while streaming.

        Messages are combined with newline separators and submitted as a single
        prompt. If no messages are queued, this is a no-op.

        Args:
            session_id: The session to process queued messages for
        """
        if not self._queue_state:
            return

        # Check if queue has messages
        if not self._queue_state.has_messages(session_id):
            return

        # Check if queue is blocked (first message is paused)
        if self._queue_state.is_blocked(session_id):
            debug_log.info(
                "Queue is blocked - first message is paused",
                category=Category.RUNNER,
                session_id=session_id,
            )
            return

        # Drain all non-paused messages
        messages = self._queue_state.drain(session_id)
        if not messages:
            return

        # Combine all messages with double-newline separator
        combined_prompt = "\n\n".join(messages)

        debug_log.info(
            f"Processing {len(messages)} queued messages as single prompt ({len(combined_prompt)} chars)",
            category=Category.RUNNER,
            session_id=session_id,
        )

        # Submit the combined message
        await self.submit_message(session_id, combined_prompt)

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
                category=Category.API,
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
            category=Category.API,
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
                category=Category.API,
                session_id=session_id,
            )
            del self._streaming_contexts[session_id]
            return state
        return None

    async def _event_pump_loop(self) -> None:
        """Main event pump loop - polls sessions and relays events."""
        debug_log.info("Event pump loop started", category=Category.RUNNER)
        while self._pump_running:
            try:
                await self._pump_events()
                await asyncio.sleep(self._pump_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log but don't crash the pump
                debug_log.error(f"Pump error: {e}", category=Category.RUNNER)
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
                category=Category.RUNNER,
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
            debug_log.info(
                f"Helper done: {helper_id}, type={ctx.helper_type}",
                category=Category.SESSION,
                details={
                    "content_len": len(ctx.content),
                    "has_fork_data": bool(ctx.metadata.get("fork_data")),
                    "auto_complete": ctx.metadata.get("auto_complete", False),
                },
            )

            await self._notify_observers(
                "on_helper_done",
                HelperDoneEvent(
                    helper_id=helper_id,
                    helper_type=ctx.helper_type,
                    result=ctx.content,
                    metadata=ctx.metadata,
                ),
            )

            # Auto-complete fork compression if flagged to do so
            # This allows React UI to work without needing to listen for helper events
            # TUI sets auto_complete=False because it handles completion manually
            if (
                ctx.helper_type == "compress"
                and ctx.metadata.get("fork_data")
                and ctx.metadata.get("auto_complete", False)
            ):
                debug_log.info(
                    f"Auto-completing fork compression for helper {helper_id}",
                    category=Category.SESSION,
                )
                try:
                    result = await self.complete_fork_after_compression(
                        helper_id=helper_id,
                        compressed_summary=ctx.content,
                        start_streaming=True,
                    )
                    debug_log.info(
                        f"Auto-complete result: success={result.success}, error={result.error}",
                        category=Category.SESSION,
                    )
                except Exception as e:
                    # Log but don't fail - the manual path is still available
                    debug_log.warning(
                        f"Auto-complete fork compression failed: {e}",
                        category=Category.SESSION
                    )
                    import traceback
                    traceback.print_exc()

            # Auto-complete archive if flagged to do so
            if (
                ctx.helper_type == "archive"
                and ctx.metadata.get("auto_complete", False)
            ):
                debug_log.info(
                    f"Auto-completing archive for helper {helper_id}, content_len={len(ctx.content)}",
                    category=Category.SESSION,
                )
                try:
                    result = await self.complete_archive(
                        helper_id=helper_id,
                        summary=ctx.content,
                    )
                    debug_log.info(
                        f"Archive auto-complete result: success={result.success}, error={result.error}",
                        category=Category.SESSION,
                    )
                    # If complete_archive returned a failure (not exception), emit failure event
                    if not result.success:
                        debug_log.warning(
                            f"Archive auto-complete returned failure: {result.error}",
                            category=Category.SESSION,
                        )
                        archive_error_data = {
                            "session_id": ctx.session_id,
                            "helper_id": helper_id,
                            "success": False,
                            "error": result.error or "Unknown error",
                            "turns_archived": 0,
                        }
                        for handler in self._event_handlers:
                            handler("onArchiveCompleted", archive_error_data)
                except Exception as e:
                    debug_log.warning(
                        f"Auto-complete archive failed with exception: {e}",
                        category=Category.SESSION
                    )
                    import traceback
                    traceback.print_exc()
                    # Emit failure event so UI can clear archiving state
                    archive_error_data = {
                        "session_id": ctx.session_id,
                        "helper_id": helper_id,
                        "success": False,
                        "error": str(e),
                        "turns_archived": 0,
                    }
                    for handler in self._event_handlers:
                        handler("onArchiveCompleted", archive_error_data)

            # Auto-complete session review if flagged to do so
            if (
                ctx.helper_type == "session_review"
                and ctx.metadata.get("auto_complete", False)
            ):
                debug_log.info(
                    f"Auto-completing session review for helper {helper_id}",
                    category=Category.SESSION,
                )
                try:
                    result = await self.complete_session_review(
                        helper_id=helper_id,
                        result_text=ctx.content,
                    )
                    debug_log.info(
                        f"Session review auto-complete result: success={result.success}, error={result.error}",
                        category=Category.SESSION,
                    )
                except Exception as e:
                    debug_log.warning(
                        f"Auto-complete session review failed: {e}",
                        category=Category.SESSION
                    )
                    import traceback
                    traceback.print_exc()

            # Auto-complete watcher summary injection
            if (
                ctx.helper_type == "watch_summary"
                and ctx.metadata.get("auto_complete", False)
            ):
                debug_log.info(
                    f"Auto-completing watcher summary for helper {helper_id}",
                    category=Category.SESSION,
                )
                try:
                    await self._inject_watch_summary(
                        watcher_session_id=ctx.metadata["watcher_session_id"],
                        target_session_id=ctx.metadata["target_session_id"],
                        target_session_name=ctx.metadata["target_session_name"],
                        exchange_index=ctx.metadata["exchange_index"],
                        summary=ctx.content.strip(),
                    )
                    debug_log.info(
                        f"Watcher summary injected successfully for helper {helper_id}",
                        category=Category.SESSION,
                    )
                except Exception as e:
                    debug_log.warning(
                        f"Auto-complete watcher summary failed: {e}",
                        category=Category.SESSION
                    )
                    import traceback
                    traceback.print_exc()

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
            import sys
            print(f"[TURN_ORDER] turn_started: order={ctx.assistant_turn_idx}, id={ctx.assistant_turn_id[:8] if ctx.assistant_turn_id else 'none'}", file=sys.stderr, flush=True)

            # Generate a turn_id if missing (fallback for compatibility)
            if not ctx.assistant_turn_id:
                ctx.assistant_turn_id = str(uuid.uuid4())
                debug_log.warning(
                    f"turn_started event missing turn_id, generated: {ctx.assistant_turn_id[:8]}",
                    category=Category.RUNNER,
                    details={"session_id": session_id, "data": data},
                )

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
                    turn_id=ctx.assistant_turn_id,
                    role="assistant",
                    turn_type="text_turn",
                )

        elif event_type == "text":
            # Text delta - accumulate and emit
            text = data if isinstance(data, str) else str(data)
            ctx.content += text

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
                    turn_id=ctx.assistant_turn_id,
                    delta=text,
                    accumulated=ctx.content,
                )

            # Emit throttled progress event (every 500ms)
            import time
            now = time.monotonic()
            if now - ctx.last_progress_emit >= 0.5:
                ctx.last_progress_emit = now
                stream = self._stream_state.get_stream(ctx.exchange_id)
                if stream:
                    await self._notify_observers(
                        "on_stream_progress",
                        StreamProgressEvent(
                            session_id=session_id,
                            exchange_id=ctx.exchange_id,
                            tokens_streamed=stream.tokens_streamed,
                            current_token_rate=stream.current_token_rate,
                            tool_name=stream.tool_name,
                            tool_count=stream.tool_count,
                            model=stream.model,
                            context_window=stream.context_window,
                            duration_seconds=stream.duration_seconds,
                        ),
                    )

        elif event_type == "text_flush":
            # Text segment complete before tool use
            text = data.get("text", "") if isinstance(data, dict) else ""
            turn_idx = data.get("turn_index", ctx.assistant_turn_idx) if isinstance(data, dict) else ctx.assistant_turn_idx
            turn_id = data.get("turn_id", ctx.assistant_turn_id) if isinstance(data, dict) else ctx.assistant_turn_id
            import sys
            print(f"[TURN_ORDER] text_flush: order={turn_idx}, id={turn_id[:8] if turn_id else 'none'}, len={len(text)}", file=sys.stderr, flush=True)

            # Get cumulative token counts from stream state
            stream = self._stream_state.get_stream(ctx.exchange_id)
            context_tokens = stream.input_tokens if stream else 0
            output_tokens_total = stream.output_tokens if stream else 0

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
                    context_tokens=context_tokens,
                    output_tokens_total=output_tokens_total,
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
                self._task_service.emit_turn_finished(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_index=turn_idx,
                    turn_id=turn_id,
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
            import sys
            print(f"[TURN_ORDER] text_turn_started: order={turn_idx}, id={turn_id[:8] if turn_id else 'none'}", file=sys.stderr, flush=True)

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
                    turn_id=turn_id,
                    role="assistant",
                    turn_type="text_turn",
                )

        elif event_type == "tool_use_start":
            # Tool use started - update context and emit
            # The turnIndex here is the main assistant turn; tool uses are shown there
            tool_use_id = data.get("tool_use_id", "")
            tool_name = data.get("tool_name", "")
            tool_idx = data.get("tool_index", ctx.tool_count)

            ctx.tool_count += 1
            ctx.tool_names[tool_use_id] = tool_name

            # Track parallel tool calls - if this is a new batch, start a group
            # A "batch" is multiple tool_use events before any tool_result
            if ctx.pending_tool_count == 0:
                # First tool in a potential parallel batch - create group ID
                ctx.parallel_group_id = str(uuid.uuid4())
            ctx.pending_tool_count += 1

            debug_log.info(
                f"_dispatch_event: tool_use_start",
                category=Category.RUNNER,
                details={
                    "session_id": session_id[:8],
                    "tool_name": tool_name,
                    "tool_use_id": tool_use_id[:12],
                    "num_observers": len(self._observers),
                    "parallel_group_id": ctx.parallel_group_id[:8] if ctx.parallel_group_id else None,
                    "pending_tool_count": ctx.pending_tool_count,
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
            # Note: turn_id not yet known at tool_use_start - will be set on tool_use_turn_started
            if self._task_service:
                self._task_service.emit_tool_use_started(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_index=ctx.assistant_turn_idx,
                    turn_id="",  # Not yet known - assigned on tool_use_turn_started
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    tool_index=tool_idx,
                    parallel_group_id=ctx.parallel_group_id,
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
            # Get turn_id if available (may not be set yet during streaming)
            turn_id = ctx.tool_turn_ids.get((tool_use_id, "tool_use"), "")
            if self._task_service:
                self._task_service.emit_tool_input_delta(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_id=turn_id,
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
            import sys
            print(f"[TURN_ORDER] tool_use_turn_started: order={turn_idx}, id={turn_id[:8] if turn_id else 'none'}, tool={data.get('tool_name', '?')}, parallel_group={ctx.parallel_group_id[:8] if ctx.parallel_group_id else 'none'}", file=sys.stderr, flush=True)

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
                    parallel_group_id=ctx.parallel_group_id,
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
                self._task_service.emit_turn_started(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_index=turn_idx,
                    turn_id=turn_id,
                    role="assistant",
                    turn_type="tool_use",
                    parallel_group_id=ctx.parallel_group_id,
                )

        elif event_type == "tool_use":
            # Tool input complete - emit tool_use event
            tool_use_id = data.get("tool_use_id", "")
            tool_name = data.get("tool_name", "")
            debug_log.info(
                f"_dispatch_event: tool_use",
                category=Category.RUNNER,
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

            # Intercept propose_fork and propose_merge tools to create proposal turns
            # Only handle balloons-tool calls (id starts with "balloons-"), not native CLI tools
            # Note: We still emit tool_use and turn_finished events below so the frontend
            # can properly transition the tool_use turn from streaming to completed state.
            if tool_name == "propose_fork" and tool_use_id.startswith("balloons-"):
                await self._handle_fork_proposal(
                    session_id=session_id,
                    tool_use_id=tool_use_id,
                    tool_input=tool_input,
                    exchange_id=ctx.exchange_id,
                )

            if tool_name == "propose_merge" and tool_use_id.startswith("balloons-"):
                await self._handle_merge_proposal(
                    session_id=session_id,
                    tool_use_id=tool_use_id,
                    tool_input=tool_input,
                    exchange_id=ctx.exchange_id,
                )

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
            # Get cumulative token counts from stream state
            stream = self._stream_state.get_stream(ctx.exchange_id)
            context_tokens = stream.input_tokens if stream else 0
            output_tokens_total = stream.output_tokens if stream else 0

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
                    context_tokens=context_tokens,
                    output_tokens_total=output_tokens_total,
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
                self._task_service.emit_tool_use(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_index=turn_idx,
                    turn_id=turn_id,
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_index=tool_idx,
                    parallel_group_id=ctx.parallel_group_id,
                )

        elif event_type == "tool_result_turn_started":
            # Tool result turn started - track turn index and ID
            turn_idx = data.get("turn_index", ctx.assistant_turn_idx) if isinstance(data, dict) else ctx.assistant_turn_idx
            turn_id = data.get("turn_id", "") if isinstance(data, dict) else ""
            tool_use_id = data.get("tool_use_id", "")
            ctx.tool_turn_indices[(tool_use_id, "tool_result")] = turn_idx
            ctx.tool_turn_ids[(tool_use_id, "tool_result")] = turn_id
            import sys
            print(f"[TURN_ORDER] tool_result_turn_started: order={turn_idx}, id={turn_id[:8] if turn_id else 'none'}, parallel_group={ctx.parallel_group_id[:8] if ctx.parallel_group_id else 'none'}", file=sys.stderr, flush=True)

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
                    parallel_group_id=ctx.parallel_group_id,
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
                self._task_service.emit_turn_started(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_index=turn_idx,
                    turn_id=turn_id,
                    role="tool",
                    turn_type="tool_result",
                    parallel_group_id=ctx.parallel_group_id,
                )

        elif event_type == "tool_result":
            # Tool execution complete
            tool_use_id = data.get("tool_use_id", "")
            result = data.get("result", "")
            tool_idx = data.get("tool_index", 0)
            turn_idx = data.get("turn_index", ctx.assistant_turn_idx)
            turn_id = data.get("turn_id", ctx.tool_turn_ids.get((tool_use_id, "tool_result"), ""))
            tool_name = ctx.tool_names.get(tool_use_id, "")

            # Track parallel batch completion
            # Decrement pending count and clear group when all results received
            ctx.pending_tool_count = max(0, ctx.pending_tool_count - 1)
            current_parallel_group = ctx.parallel_group_id  # Save for this result's emit
            if ctx.pending_tool_count == 0:
                # All results received - reset for next potential parallel batch
                ctx.parallel_group_id = None

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
            # Get cumulative token counts from stream state
            stream = self._stream_state.get_stream(ctx.exchange_id)
            context_tokens = stream.input_tokens if stream else 0
            output_tokens_total = stream.output_tokens if stream else 0

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
                    context_tokens=context_tokens,
                    output_tokens_total=output_tokens_total,
                ),
            )

            # TaskStateService calls (doesn't use observer pattern)
            if self._task_service:
                self._task_service.emit_tool_result(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_index=turn_idx,
                    turn_id=turn_id,
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    result=result,
                    is_error=False,
                    tool_index=tool_idx,
                    parallel_group_id=current_parallel_group,
                )

            # Emit progress event after tool completion (state change)
            stream = self._stream_state.get_stream(ctx.exchange_id)
            if stream:
                import time
                ctx.last_progress_emit = time.monotonic()
                await self._notify_observers(
                    "on_stream_progress",
                    StreamProgressEvent(
                        session_id=session_id,
                        exchange_id=ctx.exchange_id,
                        tokens_streamed=stream.tokens_streamed,
                        current_token_rate=stream.current_token_rate,
                        tool_name=stream.tool_name,
                        tool_count=stream.tool_count,
                        model=stream.model,
                        context_window=stream.context_window,
                        duration_seconds=stream.duration_seconds,
                    ),
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

        elif event_type == "context_tokens":
            # Context tokens counted via tiktoken BEFORE sending to Claude
            # This is the accurate token count for the context being sent
            context_tokens = data.get("context_tokens", 0)
            self._stream_state.update_stream(
                ctx.exchange_id,
                input_tokens=context_tokens,  # Use as input tokens for display
            )
            # Emit session updated with accurate context token count
            session = self._manager.get_session(session_id)
            if session:
                self._emit_session_updated(session, is_streaming=True)

        elif event_type == "result":
            # Usage stats from API - update stream state
            # Note: We prefer context_tokens event for accurate token count,
            # but still track API-reported values for cost calculation
            input_tokens = data.get("input_tokens", 0)
            output_tokens = data.get("output_tokens", 0)
            self._stream_state.update_stream(
                ctx.exchange_id,
                output_tokens=output_tokens,  # Only update output tokens from API
            )

        elif event_type == "done":
            # Stream complete - emit final turn_finished and clean up
            # Only emit turn_finished if there's unflushed content.
            # If ctx.content is empty, it means text_flush already emitted the content.

            # Get token counts from stream state (may have been updated by result event)
            stream = self._stream_state.get_stream(ctx.exchange_id)
            input_tokens = stream.input_tokens if stream else 0
            output_tokens = stream.output_tokens if stream else 0
            import sys
            print(f"[TURN_ORDER] done: order={ctx.assistant_turn_idx}, id={ctx.assistant_turn_id[:8] if ctx.assistant_turn_id else 'none'}, len={len(ctx.content)}, skipping_turn_finished={len(ctx.content) == 0}", file=sys.stderr, flush=True)

            # Only emit turn_finished if there's unflushed content
            # If content was already flushed via text_flush, ctx.content will be empty
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
                        context_tokens=input_tokens,
                        output_tokens_total=output_tokens,
                    ),
                )

            # Always emit stream_done
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
            if self._task_service and ctx.content:
                self._task_service.emit_turn_finished(
                    session_id=session_id,
                    exchange_id=ctx.exchange_id,
                    turn_index=ctx.assistant_turn_idx,
                    turn_id=ctx.assistant_turn_id,
                    role="assistant",
                    content=ctx.content,
                )
            # Complete the stream
            self._stream_state.complete_stream(ctx.exchange_id)
            # Emit session updated so React frontend hides stop button
            session = self._manager.get_session(session_id)
            if session:
                self._emit_session_updated(session, is_streaming=False)
            # Clean up context
            if session_id in self._streaming_contexts:
                del self._streaming_contexts[session_id]

            # Notify watchers of completed exchange (watcher mode)
            await self._notify_watchers_of_exchange(session_id, ctx.exchange_id)

            # Process any queued messages now that streaming is done
            await self._process_queued_messages(session_id)

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

            self._stream_state.fail_stream(ctx.exchange_id, error_msg)
            # Emit session updated so React frontend hides stop button
            session = self._manager.get_session(session_id)
            if session:
                self._emit_session_updated(session, is_streaming=False)
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
            # Emit session updated so React frontend hides stop button
            session = self._manager.get_session(session_id)
            if session:
                self._emit_session_updated(session, is_streaming=False)
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

            # Add an InterruptionBlock turn to the session
            session = self._manager.get_session(session_id)
            if session:
                # Create and add the interruption turn
                interruption_block = InterruptionBlock(reason="user_cancelled")
                turn = session.add_turn(
                    role="assistant",
                    content_block=interruption_block,
                    tokens=0,
                    exchange_id=ctx.exchange_id,
                )
                turn_idx = len(session.turns) - 1

                # Notify observers about the new turn
                await self._notify_observers(
                    "on_turn_created",
                    TurnCreatedEvent(
                        session_id=session_id,
                        turn_id=turn.id,
                        turn_index=turn_idx,
                        role="assistant",
                        exchange_id=ctx.exchange_id,
                        content_block_type="interruption",
                    ),
                )
                await self._notify_observers(
                    "on_turn_finished",
                    TurnFinishedEvent(
                        session_id=session_id,
                        turn_id=turn.id,
                        turn_index=turn_idx,
                        role="assistant",
                        content="",
                        tokens=0,
                        content_block=interruption_block,
                        context_tokens=0,
                        output_tokens_total=0,
                    ),
                )

                # Emit session updated so React frontend hides stop button
                self._emit_session_updated(session, is_streaming=False)

            if session_id in self._streaming_contexts:
                del self._streaming_contexts[session_id]

            # Process any queued messages now that streaming is cancelled
            await self._process_queued_messages(session_id)

        elif event_type == "input_required":
            # Claude is asking for input - this shouldn't happen for non-interactive frontends
            # Mark as completed since we can't respond

            # Get cumulative token counts from stream state
            stream = self._stream_state.get_stream(ctx.exchange_id)
            context_tokens = stream.input_tokens if stream else 0
            output_tokens_total = stream.output_tokens if stream else 0

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
                        context_tokens=context_tokens,
                        output_tokens_total=output_tokens_total,
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
                    turn_id=ctx.assistant_turn_id,
                    role="assistant",
                    content=ctx.content,
                )
            self._stream_state.complete_stream(ctx.exchange_id)
            # Emit session updated so React frontend hides stop button
            session = self._manager.get_session(session_id)
            if session:
                self._emit_session_updated(session, is_streaming=False)
            if session_id in self._streaming_contexts:
                del self._streaming_contexts[session_id]

            # Notify watchers of completed exchange (watcher mode)
            await self._notify_watchers_of_exchange(session_id, ctx.exchange_id)

            # Process any queued messages now that streaming is done
            await self._process_queued_messages(session_id)

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
            # Emit session updated so React frontend hides stop button
            session = self._manager.get_session(stream.session_id)
            if session:
                self._emit_session_updated(session, is_streaming=False)

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

        # Emit session added event so React UI can display the new session
        self._emit_session_added(session, is_streaming=False)

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
        auto_complete_compression: bool = False,
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
            auto_complete_compression: If True, automatically complete fork when compression
                                       finishes (for clients that don't handle helper events).
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

        # Get context modes from parameter (required when forking via UI)
        from models import ContextMode
        tree_modes: dict[int, ContextMode] = {}
        if context_modes:
            for cm in context_modes:
                turn_idx = cm.get("turn_index")
                mode_str = cm.get("mode", "copy")
                if mode_str == "compress":
                    tree_modes[turn_idx] = ContextMode.COMPRESS
                elif mode_str == "drop":
                    tree_modes[turn_idx] = ContextMode.DROP
                else:
                    tree_modes[turn_idx] = ContextMode.COPY
        # If no context_modes provided, all turns will default to COPY

        # Build indexed messages with context modes
        from models import Message
        indexed_messages = []
        mode_stats = {"copy": 0, "compress": 0, "drop": 0}
        for turn_idx, turn in enumerate(parent_session.turns):
            # Get context mode for this turn
            mode = tree_modes.get(turn_idx, ContextMode.COPY)
            mode_stats[mode.value] = mode_stats.get(mode.value, 0) + 1

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

        debug_log.info(
            f"fork_session: built indexed messages",
            category=Category.SESSION,
            details={
                "parent_turn_count": len(parent_session.turns),
                "indexed_message_count": len(indexed_messages),
                "mode_stats": mode_stats,
            }
        )

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

        debug_log.info(
            f"fork_session: child session created",
            category=Category.SESSION,
            details={
                "child_session_id": child_session.id[:8],
                "child_turn_count": len(child_session.turns),
                "background": background,
            }
        )

        # Emit session added event so React UI can display the new session
        self._emit_session_added(child_session, is_streaming=False)

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
                    "auto_complete": auto_complete_compression,
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

        debug_log.info(
            f"complete_fork_after_compression: session populated with {len(child_session.turns)} turns",
            category=Category.SESSION,
            details={
                "child_session_id": child_session.id[:8],
                "child_turn_count": len(child_session.turns),
            }
        )

        # Emit turnFinished events for each turn so subscribed clients get the data
        # This handles the case where React subscribed before compression completed
        if self._session_data_service:
            for turn_idx, turn in enumerate(child_session.turns):
                content_block = turn.content_block
                # Get text content for backward compat
                final_content = ""
                if content_block:
                    if hasattr(content_block, 'text'):
                        final_content = content_block.text or ""
                    elif hasattr(content_block, 'content'):
                        final_content = content_block.content or ""
                self._session_data_service.emit_turn_finished(
                    session_id=child_session.id,
                    turn_id=turn.id,
                    final_content=final_content,
                    tokens=turn.tokens,
                    order=turn_idx,
                    role=turn.role,
                    content_block=content_block,
                )
            debug_log.info(
                f"complete_fork_after_compression: emitted {len(child_session.turns)} turn events",
                category=Category.SESSION,
            )

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

        # Emit session updated events for React UI
        self._emit_session_updated(fork_session, is_streaming=False)
        self._emit_session_updated(parent_session, is_streaming=False)

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
    async def get_exchange_summaries(
        self,
        session_id: str,
        exclude_current: bool = True,
    ) -> list[ExchangeSummary]:
        """Get summaries of each exchange in a session for proposal UIs.

        Returns short descriptions of each exchange for display in fork/merge
        proposal components, helping the user understand what context each
        exchange contains.

        Args:
            session_id: ID of the session to get exchange summaries for
            exclude_current: If True, exclude the last exchange (the one
                           containing a proposal). Default True since this
                           is typically called when displaying a proposal.

        Returns:
            List of ExchangeSummary objects with index, summary, and default mode
        """
        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return []

        summaries: list[ExchangeSummary] = []

        groups = self._get_turns_grouped_by_exchange(session)

        # Exclude the current (proposal) exchange if requested
        if exclude_current and groups:
            groups = groups[:-1]

        for exchange_idx, group in enumerate(groups):
            if not group:
                continue
            # Get first meaningful content from the group (group is list of (idx, turn) tuples)
            _, first_turn = group[0]
            content = getattr(first_turn, 'content', '') or ""
            # Truncate for display
            if len(content) > 60:
                content = content[:57] + "..."
            # Remove newlines for single-line display
            content = content.replace("\n", " ").strip()
            role = getattr(first_turn, 'role', 'user')
            summary = f"[{role}] {content}"
            summaries.append(ExchangeSummary(
                index=exchange_idx,
                summary=summary,
                mode="compress",  # Default mode
            ))

        return summaries

    # =========================================================================
    # Fork/Merge Proposal Handling (Internal)
    # =========================================================================

    async def _handle_fork_proposal(
        self,
        session_id: str,
        tool_use_id: str,
        tool_input: dict,
        exchange_id: str,
    ) -> None:
        """Handle a propose_fork tool call.

        The proposal UI is rendered directly from the tool_use turn by
        ForkProposalCard in the frontend. This method just logs the proposal
        for debugging - the tool_use turn is already created and emitted
        by the regular event flow.

        Previously this created a separate fork_proposal turn, but that was
        redundant since ForkProposalCard renders from the tool_use block.
        """
        # Parse the tool input for logging
        proposal = parse_fork_proposal(tool_input)
        if not proposal:
            debug_log.error(
                "Failed to parse fork proposal",
                category=Category.SESSION,
                details={"tool_input_keys": list(tool_input.keys())},
            )
            return

        debug_log.info(
            f"Fork proposal received: {proposal.name}",
            category=Category.SESSION,
            details={
                "tool_use_id": tool_use_id,
                "description": proposal.description[:100] if proposal.description else "",
                "context_plan_count": len(proposal.context_plan) if proposal.context_plan else 0,
            },
        )

    async def _handle_merge_proposal(
        self,
        session_id: str,
        tool_use_id: str,
        tool_input: dict,
        exchange_id: str,
    ) -> None:
        """Handle a propose_merge tool call.

        The proposal UI is rendered directly from the tool_use turn by
        MergeProposalCard in the frontend. This method just logs the proposal
        for debugging - the tool_use turn is already created and emitted
        by the regular event flow.

        Previously this created a separate merge_proposal turn, but that was
        redundant since MergeProposalCard renders from the tool_use block.
        """
        # Parse the tool input for logging
        proposal = parse_merge_proposal(tool_input)
        if not proposal:
            debug_log.error(
                "Failed to parse merge proposal",
                category=Category.SESSION,
                details={"tool_input_keys": list(tool_input.keys())},
            )
            return

        debug_log.info(
            f"Merge proposal received",
            category=Category.SESSION,
            details={
                "tool_use_id": tool_use_id,
                "summary": proposal.summary[:100] if proposal.summary else "",
            },
        )

    @ws_expose
    async def respond_to_fork_proposal(
        self,
        session_id: str,
        proposal_id: str,
        accepted: bool,
        context_plan: list[dict] | None = None,
        initial_prompt: str | None = None,
        name: str | None = None,
        description: str | None = None,
        start_streaming: bool = True,
    ) -> RespondToForkProposalResult:
        """Respond to a fork proposal by accepting or rejecting it.

        When accepting, optionally provide modified context_plan and initial_prompt.
        The context_plan uses exchange ranges (like "0-2", "last") rather than
        individual turn indices - this method handles the resolution.

        Args:
            session_id: ID of the session containing the proposal
            proposal_id: ID of the proposal to respond to
            accepted: True to accept, False to reject
            context_plan: Modified context plan (list of {exchange_range, mode, reason})
                         If not provided, uses the original from the proposal
            initial_prompt: Modified initial prompt (if not provided, uses original)
            name: Fork name (if not provided, uses original from proposal)
            description: Fork description (if not provided, uses original from proposal)
            start_streaming: If True and accepted, start streaming after fork creation

        Returns:
            RespondToForkProposalResult with fork session info if accepted
        """
        # Get the session
        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return RespondToForkProposalResult(
                    success=False,
                    error=f"Session {session_id} not found",
                )

        # Validate required data - the frontend (ForkProposalCard) always provides these
        # from the tool_use turn's input
        if not name or not context_plan:
            return RespondToForkProposalResult(
                success=False,
                error="Missing required fork parameters (name and context_plan)",
            )

        if not accepted:
            # Nothing to update - rejection is just a no-op
            # The tool_use turn remains in the session as-is
            return RespondToForkProposalResult(
                success=True,
                accepted=False,
            )

        # Accept the proposal - execute the fork
        from core.fork import ForkProposal, ContextAssignment
        from models import ContextMode

        # Build a ForkProposal to resolve exchange ranges
        fork_proposal = ForkProposal(
            name=name,
            description=description or "",
            context_plan=[
                ContextAssignment(
                    exchange_range=cp.get("exchange_range", ""),
                    mode=cp.get("mode", "compress"),
                    reason=cp.get("reason", ""),
                )
                for cp in context_plan
            ],
            initial_prompt=initial_prompt or "",
        )

        # Get exchange groups to resolve ranges (list of (idx, turn) tuples per group)
        groups = self._get_turns_grouped_by_exchange(session)
        total_exchanges = len(groups)

        # Resolve exchange ranges to turn indices with modes
        # exclude_current=True because the proposal was made during the current exchange
        exchange_modes = fork_proposal.resolve_exchange_indices(total_exchanges, exclude_current=True)

        # Convert exchange modes to turn context modes
        turn_context_modes: list[dict] = []
        for exchange_idx, mode in exchange_modes.items():
            if exchange_idx < len(groups):
                for turn_idx, turn in groups[exchange_idx]:
                    turn_context_modes.append({
                        "turn_index": turn_idx,
                        "mode": mode.value,  # "copy", "compress", "drop"
                    })

        # Also need to drop turns from exchanges not mentioned (default to drop? or compress?)
        # For safety, default un-mentioned exchanges to compress
        mentioned_exchanges = set(exchange_modes.keys())
        for exchange_idx, group in enumerate(groups):
            if exchange_idx not in mentioned_exchanges:
                # Check if it's the last exchange (current proposal) - skip it
                if exchange_idx == total_exchanges - 1:
                    continue
                for turn_idx, turn in group:
                    # Default to compress for un-mentioned exchanges
                    turn_context_modes.append({
                        "turn_index": turn_idx,
                        "mode": "compress",
                    })

        # Mark proposal as being processed (will update with child_session_id after fork succeeds)

        # Build the prompt
        prompt = fork_proposal.initial_prompt or f"Continue with: {fork_proposal.description}"

        # Create the fork using fork_session
        # Set auto_complete_compression=True so React UI works without helper event handling
        debug_log.info(
            f"Creating fork from proposal: name={fork_proposal.name}",
            category=Category.SESSION,
            details={
                "prompt": prompt[:100] + "..." if len(prompt) > 100 else prompt,
                "num_context_modes": len(turn_context_modes),
                "start_streaming": start_streaming,
            },
        )
        fork_result = await self.fork_session(
            parent_session_id=session_id,
            prompt=prompt,
            name=fork_proposal.name,
            background=False,
            context_modes=turn_context_modes,
            allowed_tools=None,  # All tools
            start_streaming=start_streaming,
            auto_complete_compression=True,
        )

        debug_log.info(
            f"Fork result: success={fork_result.success}, needs_compression={fork_result.needs_compression}",
            category=Category.SESSION,
            details={
                "child_session_id": fork_result.child_session_id,
                "helper_id": fork_result.helper_id,
                "error": fork_result.error,
            },
        )

        if not fork_result.success:
            return RespondToForkProposalResult(
                success=False,
                error=fork_result.error or "Fork failed",
            )

        # Update the tool_use turn with the child_session_id
        # so the ForkProposalCard can show the link after page reload
        tool_use_turn = None
        tool_use_turn_idx = None
        for idx, turn in enumerate(session.turns):
            if isinstance(turn.content_block, ToolUseBlock):
                if turn.content_block.id == proposal_id:
                    tool_use_turn = turn
                    tool_use_turn_idx = idx
                    # Add child_session_id and status to the input
                    if turn.content_block.input is None:
                        turn.content_block.input = {}
                    turn.content_block.input["_child_session_id"] = fork_result.child_session_id
                    turn.content_block.input["_status"] = "accepted"
                    break

        await session.save()

        # Emit turn_finished event so frontend gets updated with child_session_id
        if tool_use_turn and tool_use_turn_idx is not None:
            await self._notify_observers(
                "on_turn_finished",
                TurnFinishedEvent(
                    session_id=session_id,
                    turn_id=tool_use_turn.id,
                    turn_index=tool_use_turn_idx,
                    role="assistant",
                    content="",
                    tokens=0,
                    content_block=tool_use_turn.content_block,
                ),
            )

        return RespondToForkProposalResult(
            success=True,
            accepted=True,
            child_session_id=fork_result.child_session_id,
            parent_session_id=fork_result.parent_session_id,
            fork_name=fork_result.fork_name,
            exchange_id=fork_result.exchange_id,
            needs_compression=fork_result.needs_compression,
            helper_id=fork_result.helper_id,
        )

    @ws_expose
    async def respond_to_merge_proposal(
        self,
        session_id: str,
        proposal_id: str,
        accepted: bool,
        summary: str | None = None,
        files_changed: list[str] | None = None,
        key_accomplishments: list[str] | None = None,
        reason: str | None = None,
    ) -> RespondToMergeProposalResult:
        """Respond to a merge proposal by accepting or rejecting it.

        When accepting, optionally provide a modified summary.

        Args:
            session_id: ID of the session containing the proposal (the fork session)
            proposal_id: ID of the proposal to respond to
            accepted: True to accept, False to reject
            summary: Modified merge summary (if not provided, uses original)
            files_changed: Modified list of changed files
            key_accomplishments: Modified list of accomplishments
            reason: Modified reason for merge

        Returns:
            RespondToMergeProposalResult with merge info if accepted
        """
        # Get the session
        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return RespondToMergeProposalResult(
                    success=False,
                    error=f"Session {session_id} not found",
                )

        # Validate we have a summary (required for merge)
        if not summary:
            return RespondToMergeProposalResult(
                success=False,
                error="Missing required merge summary",
            )

        if not accepted:
            # Nothing to update - rejection is just a no-op
            return RespondToMergeProposalResult(
                success=True,
                accepted=False,
            )

        # Accept the proposal - execute the merge
        merge_result = await self.merge_session(
            fork_session_id=session_id,
            merge_summary=summary,
            files_changed=files_changed or [],
            key_accomplishments=key_accomplishments or [],
            reason=reason or "",
        )

        if not merge_result.success:
            return RespondToMergeProposalResult(
                success=False,
                error=merge_result.error or "Merge failed",
            )

        return RespondToMergeProposalResult(
            success=True,
            accepted=True,
            fork_session_id=merge_result.fork_session_id,
            parent_session_id=merge_result.parent_session_id,
            merge_id=merge_result.merge_id,
            merge_point=merge_result.merge_point,
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

        # Get context modes from parameter (required when deriving via UI)
        from models import ContextMode
        tree_modes: dict[int, ContextMode] = {}
        if context_modes:
            for cm in context_modes:
                turn_idx = cm.get("turn_index")
                mode_str = cm.get("mode", "copy")
                if mode_str == "compress":
                    tree_modes[turn_idx] = ContextMode.COMPRESS
                elif mode_str == "drop":
                    tree_modes[turn_idx] = ContextMode.DROP
                else:
                    tree_modes[turn_idx] = ContextMode.COPY
        # If no context_modes provided, all turns will default to COPY

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

        # Emit session added event so React UI can display the new session
        self._emit_session_added(new_session, is_streaming=False)

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

    # --- Link Operations ---

    @ws_expose
    async def link_sessions(
        self,
        source_session_id: str,
        target_session_id: str,
        summary: str = "",
    ) -> LinkSessionsResult:
        """Create a bidirectional link between two sessions.

        Links allow navigation between sessions without a parent/child relationship.
        Both sessions get a LinkBlock turn pointing to the other.

        Args:
            source_session_id: The current session (where user initiated the link)
            target_session_id: The session to link to
            summary: Optional description of why these sessions are linked

        Returns:
            LinkSessionsResult with the shared link_id
        """
        import uuid

        # Validate source session
        source_session = self._manager.get_session(source_session_id)
        if not source_session:
            source_session = await self._manager.load_session(source_session_id)
            if not source_session:
                return LinkSessionsResult(
                    success=False,
                    error=f"Source session {source_session_id} not found",
                )

        # Validate target session
        target_session = self._manager.get_session(target_session_id)
        if not target_session:
            target_session = await self._manager.load_session(target_session_id)
            if not target_session:
                return LinkSessionsResult(
                    success=False,
                    error=f"Target session {target_session_id} not found",
                )

        # Can't link a session to itself
        if source_session_id == target_session_id:
            return LinkSessionsResult(
                success=False,
                error="Cannot link a session to itself",
            )

        # Check if link already exists
        for turn in source_session.turns:
            from models import LinkBlock
            if isinstance(turn.content_block, LinkBlock):
                if turn.content_block.linked_session_id == target_session_id:
                    return LinkSessionsResult(
                        success=False,
                        error="Sessions are already linked",
                    )

        # Generate a shared link ID
        link_id = str(uuid.uuid4())

        # Get display names for the summary
        source_name = source_session.title or source_session.fork_name or source_session.id[:8]
        target_name = target_session.title or target_session.fork_name or target_session.id[:8]

        # Default summary if not provided
        if not summary:
            summary = f"Linked to {target_name}"

        # Add link to source session (pointing to target)
        source_turn = source_session.add_link_turn(
            link_id=link_id,
            linked_session_id=target_session_id,
            summary=summary,
        )
        await source_session.save()

        # Add link to target session (pointing back to source)
        target_turn = target_session.add_link_turn(
            link_id=link_id,
            linked_session_id=source_session_id,
            summary=f"Linked from {source_name}",
        )
        await target_session.save()

        # Emit turn events for the source session
        source_turn_idx = len(source_session.turns) - 1
        source_exchange_id = str(uuid.uuid4())
        await self._notify_observers(
            "on_turn_created",
            TurnCreatedEvent(
                session_id=source_session_id,
                turn_id=source_turn.id,
                turn_index=source_turn_idx,
                role="system",
                exchange_id=source_exchange_id,
                content_block_type="link",
            ),
        )
        await self._notify_observers(
            "on_turn_finished",
            TurnFinishedEvent(
                session_id=source_session_id,
                turn_id=source_turn.id,
                turn_index=source_turn_idx,
                role="system",
                content="[Link created]",
                tokens=0,
                content_block=source_turn.content_block,
            ),
        )

        # Emit turn events for the target session
        target_turn_idx = len(target_session.turns) - 1
        target_exchange_id = str(uuid.uuid4())
        await self._notify_observers(
            "on_turn_created",
            TurnCreatedEvent(
                session_id=target_session_id,
                turn_id=target_turn.id,
                turn_index=target_turn_idx,
                role="system",
                exchange_id=target_exchange_id,
                content_block_type="link",
            ),
        )
        await self._notify_observers(
            "on_turn_finished",
            TurnFinishedEvent(
                session_id=target_session_id,
                turn_id=target_turn.id,
                turn_index=target_turn_idx,
                role="system",
                content="[Link created]",
                tokens=0,
                content_block=target_turn.content_block,
            ),
        )

        debug_log.info(
            f"Linked sessions: {source_session_id[:8]} <-> {target_session_id[:8]}",
            category=Category.SESSION,
            details={"link_id": link_id, "summary": summary},
        )

        return LinkSessionsResult(
            success=True,
            link_id=link_id,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
        )

    # --- Watcher Operations ---

    @ws_expose
    async def create_watcher_session(
        self,
        target_session_id: str,
    ) -> CreateWatcherSessionResult:
        """Create a watcher session to observe another session.

        The watcher session will receive summaries of exchanges from the target
        session. The user can provide instructions to the watcher to guide how
        summaries are generated and how the watcher should respond.

        Args:
            target_session_id: ID of the session to watch

        Returns:
            CreateWatcherSessionResult with the new watcher session info
        """
        from models import WatchStartBlock

        debug_log.info(
            f"create_watcher_session called for target {target_session_id[:8]}",
            category=Category.SESSION,
        )

        # Validate target session exists
        target_session = self._manager.get_session(target_session_id)
        if not target_session:
            target_session = await self._manager.load_session(target_session_id)
            if not target_session:
                return CreateWatcherSessionResult(
                    success=False,
                    error=f"Target session {target_session_id} not found",
                )

        # Get target session name for display
        target_name = target_session.title or target_session.fork_name or target_session.id[:8]

        # Create the watcher session
        watcher_session = await self._manager.create_session(
            working_directory=target_session.working_directory
        )

        # Name the watcher session
        watcher_name = f"watching:{target_name}"
        watcher_session.title = watcher_name

        # Add WatchStartBlock to establish the watching relationship
        watch_turn = watcher_session.add_watch_start_turn(
            target_session_id=target_session_id,
            target_session_name=target_name,
        )

        # Add watcher instructions as a system-like user turn
        # This ensures the LLM knows it's a watcher session and how to behave
        watcher_instructions = self._get_watcher_instructions(target_name)
        instructions_turn = watcher_session.add_turn(
            role="user",
            content_block=TextBlock(text=watcher_instructions),
        )

        # Save the watcher session
        await watcher_session.save()

        # Emit session created event
        self._emit_event(SessionManagerEvent.SESSION_CREATED, watcher_session.id)

        # Emit session added event so React UI can display the new session
        self._emit_session_added(watcher_session, is_streaming=False)

        # Emit turn events for the watch start (turn 0)
        watch_exchange_id = str(uuid.uuid4())
        await self._notify_observers(
            "on_turn_created",
            TurnCreatedEvent(
                session_id=watcher_session.id,
                turn_id=watch_turn.id,
                turn_index=0,
                role="system",
                exchange_id=watch_exchange_id,
                content_block_type="watch_start",
            ),
        )
        await self._notify_observers(
            "on_turn_finished",
            TurnFinishedEvent(
                session_id=watcher_session.id,
                turn_id=watch_turn.id,
                turn_index=0,
                role="system",
                content=f"[Watching {target_name}]",
                tokens=0,
                content_block=watch_turn.content_block,
            ),
        )

        # Emit turn events for the instructions turn (turn 1)
        instructions_exchange_id = str(uuid.uuid4())
        await self._notify_observers(
            "on_turn_created",
            TurnCreatedEvent(
                session_id=watcher_session.id,
                turn_id=instructions_turn.id,
                turn_index=1,
                role="user",
                exchange_id=instructions_exchange_id,
                content_block_type="text",
            ),
        )
        await self._notify_observers(
            "on_turn_finished",
            TurnFinishedEvent(
                session_id=watcher_session.id,
                turn_id=instructions_turn.id,
                turn_index=1,
                role="user",
                content=watcher_instructions[:100] + "...",
                tokens=0,
                content_block=instructions_turn.content_block,
            ),
        )

        # Register watcher relationship for live summarization
        # Uses internal tracking; persists to LMDB for fast startup
        await self._register_watcher_internal(
            watcher_session.id, target_session_id, target_name
        )

        debug_log.info(
            f"Created watcher session: {watcher_session.id[:8]} watching {target_session_id[:8]}",
            category=Category.SESSION,
            details={"target_name": target_name, "watcher_name": watcher_name},
        )

        return CreateWatcherSessionResult(
            success=True,
            watcher_session_id=watcher_session.id,
            target_session_id=target_session_id,
            target_session_name=target_name,
            watcher_name=watcher_name,
        )

    @ws_expose
    async def stop_watching(
        self,
        watcher_session_id: str,
        target_session_id: str | None = None,
        reason: str = "user",
    ) -> bool:
        """Stop a watcher session from watching a target.

        Args:
            watcher_session_id: ID of the watcher session
            target_session_id: ID of the target to stop watching (if None, stops all)
            reason: Why watching stopped ("user", "session_closed", "session_archived")

        Returns:
            True if successfully stopped, False otherwise
        """
        # Load the watcher session
        watcher_session = self._manager.get_session(watcher_session_id)
        if not watcher_session:
            watcher_session = await self._manager.load_session(watcher_session_id)
            if not watcher_session:
                return False

        # Get the target(s) to stop watching
        if target_session_id:
            targets = [target_session_id] if watcher_session.is_watching(target_session_id) else []
        else:
            targets = watcher_session.get_all_watch_targets()

        if not targets:
            return False

        # Add WatchStopBlock for each target
        for target_id in targets:
            stop_turn = watcher_session.add_watch_stop_turn(
                target_session_id=target_id,
                reason=reason,
            )

            # Emit turn events
            stop_turn_idx = len(watcher_session.turns) - 1
            stop_exchange_id = str(uuid.uuid4())
            await self._notify_observers(
                "on_turn_created",
                TurnCreatedEvent(
                    session_id=watcher_session_id,
                    turn_id=stop_turn.id,
                    turn_index=stop_turn_idx,
                    role="system",
                    exchange_id=stop_exchange_id,
                    content_block_type="watch_stop",
                ),
            )
            await self._notify_observers(
                "on_turn_finished",
                TurnFinishedEvent(
                    session_id=watcher_session_id,
                    turn_id=stop_turn.id,
                    turn_index=stop_turn_idx,
                    role="system",
                    content=f"[Stopped watching]",
                    tokens=0,
                    content_block=stop_turn.content_block,
                ),
            )

        await watcher_session.save()

        # Unregister watcher relationships
        for target_id in targets:
            await self._unregister_watcher_internal(watcher_session_id, target_id)

        debug_log.info(
            f"Stopped watching: {watcher_session_id[:8]} no longer watching {targets}",
            category=Category.SESSION,
            details={"reason": reason},
        )

        return True

    # --- Watcher Internal Methods ---

    async def _register_watcher_internal(
        self,
        watcher_session_id: str,
        target_session_id: str,
        target_session_name: str,
        source: str = "creation",
    ) -> None:
        """Register a watcher relationship internally.

        Called when create_watcher_session creates the watching relationship,
        or when loading from storage after server restart.

        Args:
            watcher_session_id: ID of the watcher session
            target_session_id: ID of the target being watched
            target_session_name: Display name of the target
            source: Where this registration came from ("creation", "startup", "load", "rebuild")
        """
        # Add to target -> watchers map (in-memory cache)
        is_new = False
        if target_session_id not in self._watcher_targets:
            self._watcher_targets[target_session_id] = []
        if watcher_session_id not in self._watcher_targets[target_session_id]:
            self._watcher_targets[target_session_id].append(watcher_session_id)
            is_new = True

        # Add to watcher -> targets map (in-memory cache)
        if watcher_session_id not in self._watcher_watching:
            self._watcher_watching[watcher_session_id] = []
        entry = (target_session_id, target_session_name)
        if entry not in self._watcher_watching[watcher_session_id]:
            self._watcher_watching[watcher_session_id].append(entry)

        # Persist to storage (for new relationships, not startup loads)
        # - "creation": new watcher session created
        # - "rebuild": session loaded that has watcher info, now migrating to LMDB
        # - "load": session loaded/switched, may need migration to LMDB
        # Skip "startup" since those are already loaded from LMDB
        if is_new and source in ("creation", "rebuild", "load"):
            from datetime import datetime
            from core.async_storage import get_watcher_storage, WatcherRelationData

            watcher_id = f"{watcher_session_id}:{target_session_id}"
            watcher_data = WatcherRelationData(
                id=watcher_id,
                watcher_session_id=watcher_session_id,
                target_session_id=target_session_id,
                target_session_name=target_session_name,
                created_at=datetime.utcnow().isoformat() + "Z",
            )
            try:
                watcher_storage = await get_watcher_storage()
                await watcher_storage.save_watcher(watcher_data)
            except Exception as e:
                debug_log.error(
                    f"Failed to persist watcher relationship: {e}",
                    category=Category.SESSION,
                )

        debug_log.info(
            f"Registered watcher relationship ({source}): {watcher_session_id[:8]} -> {target_session_id[:8]}",
            category=Category.SESSION,
            details={
                "watcher_id": watcher_session_id,
                "target_id": target_session_id,
                "target_name": target_session_name,
                "source": source,
                "is_new": is_new,
            },
        )

    async def _unregister_watcher_internal(
        self,
        watcher_session_id: str,
        target_session_id: str | None = None,
    ) -> None:
        """Unregister a watcher relationship internally.

        Called when stop_watching is called. Removes from in-memory cache and LMDB.
        """
        from core.async_storage import get_watcher_storage

        targets_to_delete: list[str] = []

        if target_session_id:
            # Remove specific target
            if target_session_id in self._watcher_targets:
                if watcher_session_id in self._watcher_targets[target_session_id]:
                    self._watcher_targets[target_session_id].remove(watcher_session_id)
            if watcher_session_id in self._watcher_watching:
                self._watcher_watching[watcher_session_id] = [
                    (tid, tn) for tid, tn in self._watcher_watching[watcher_session_id]
                    if tid != target_session_id
                ]
            targets_to_delete.append(target_session_id)
        else:
            # Remove all targets for this watcher
            for tid, _ in list(self._watcher_watching.get(watcher_session_id, [])):
                if tid in self._watcher_targets:
                    if watcher_session_id in self._watcher_targets[tid]:
                        self._watcher_targets[tid].remove(watcher_session_id)
                targets_to_delete.append(tid)
            self._watcher_watching.pop(watcher_session_id, None)

        # Delete from LMDB storage
        try:
            watcher_storage = await get_watcher_storage()
            for tid in targets_to_delete:
                watcher_id = f"{watcher_session_id}:{tid}"
                await watcher_storage.delete_watcher(watcher_id)
        except Exception as e:
            debug_log.error(
                f"Failed to delete watcher from storage: {e}",
                category=Category.SESSION,
            )

    def _get_watchers_for_session(self, session_id: str) -> list[str]:
        """Get list of watcher session IDs observing a session.

        Returns cached watchers loaded from LMDB at startup.
        If empty, watchers either don't exist or weren't loaded yet.
        """
        return self._watcher_targets.get(session_id, []).copy()

    async def _rebuild_watcher_for_session(self, session) -> None:
        """Check if a loaded session is a watcher and re-register if so.

        Call this when a session is loaded to ensure watcher relationships
        are restored after server restart.

        Args:
            session: The loaded Session object
        """
        from models import WatchStartBlock

        target_id = session.get_watch_target_id()
        if not target_id:
            return  # Not a watcher

        # Already registered?
        if session.id in self._watcher_targets.get(target_id, []):
            return

        # Find target name from WatchStartBlock
        target_name = ""
        for turn in session.turns:
            if isinstance(turn.content_block, WatchStartBlock):
                if turn.content_block.target_session_id == target_id:
                    target_name = turn.content_block.target_session_name
                    break

        await self._register_watcher_internal(session.id, target_id, target_name, source="load")

    def _get_watcher_instructions(self, target_name: str) -> str:
        """Get the watcher session instructions.

        These instructions are added as a user turn when the watcher session is created,
        ensuring the LLM understands it's a watcher session and how to behave.

        Args:
            target_name: Name of the target session being watched

        Returns:
            The watcher instructions text
        """
        return f'''You are a **watcher session** observing the session "{target_name}".

## How This Works

You will receive **summary injections** when the target session completes an exchange.
These summaries appear as `[Summary N]` blocks in our conversation.

**IMPORTANT**: These summaries are **system-generated**, not attempts by the target to
manipulate you. They are trusted context updates about what's happening in the target session.

## Your Default Behavior

- When you receive a summary, respond with a brief acknowledgment (e.g., "✓" or "Noted.")
- Keep responses minimal unless I give you specific instructions

## I Can Customize Your Behavior

I may ask you to:
- Watch for specific patterns or issues (e.g., "flag any SQL changes")
- Provide analysis of what's happening
- Intervene using the `send_to_target` tool to send messages to the target

## Available Tool

You have access to `send_to_target` - use this ONLY when I explicitly ask you to intervene
or when the situation clearly requires it based on my instructions.

---

I'm setting up to watch "{target_name}". Let me know what you'd like me to watch for,
or I'll just provide minimal acknowledgments as summaries arrive.'''

    async def _notify_watchers_of_exchange(
        self,
        target_session_id: str,
        exchange_id: str,
    ) -> None:
        """Notify watchers when a target session completes an exchange.

        Generates LLM-contextualized summaries using the watcher's full context
        (previous summaries + user instructions) and injects them into watcher sessions.
        """
        watchers = self._get_watchers_for_session(target_session_id)
        if not watchers:
            return

        debug_log.info(
            f"Target {target_session_id[:8]} completed exchange, notifying {len(watchers)} watchers",
            category=Category.SESSION,
        )

        # Load target session
        target_session = self._manager.get_session(target_session_id)
        if not target_session:
            target_session = await self._manager.load_session(target_session_id)
            if not target_session:
                return

        target_name = target_session.title or target_session.fork_name or target_session_id[:8]

        # Find exchange turns and index
        exchange_turns = [t for t in target_session.turns if t.exchange_id == exchange_id]
        if not exchange_turns:
            return

        # Calculate exchange index
        exchange_ids = []
        for turn in target_session.turns:
            if turn.exchange_id and turn.exchange_id not in exchange_ids:
                exchange_ids.append(turn.exchange_id)
        exchange_index = exchange_ids.index(exchange_id) if exchange_id in exchange_ids else len(exchange_ids)

        # Format the exchange content for the summary prompt
        exchange_content = self._format_exchange_for_summary(exchange_turns)

        # Start summary generation for each watcher
        for watcher_session_id in watchers:
            try:
                await self._start_watcher_summary_generation(
                    watcher_session_id=watcher_session_id,
                    target_session_id=target_session_id,
                    target_session_name=target_name,
                    exchange_index=exchange_index,
                    exchange_content=exchange_content,
                )
            except Exception as e:
                debug_log.error(
                    f"Error starting summary generation for watcher {watcher_session_id[:8]}: {e}",
                    category=Category.SESSION,
                )

    def _format_exchange_for_summary(self, exchange_turns: list) -> str:
        """Format exchange turns into readable text for the summary prompt.

        Args:
            exchange_turns: List of Turn objects from the exchange

        Returns:
            Formatted text representation of the exchange
        """
        parts = []
        for turn in exchange_turns:
            role = turn.role.capitalize()
            block = turn.content_block

            if hasattr(block, 'text') and block.text:
                # TextBlock - include full text (will be truncated in prompt if too long)
                content = block.text
                parts.append(f"**{role}**: {content}")
            elif hasattr(block, 'name') and hasattr(block, 'input'):
                # ToolUseBlock
                import json
                tool_input_str = json.dumps(block.input, indent=2)
                # Truncate very long tool inputs
                if len(tool_input_str) > 500:
                    tool_input_str = tool_input_str[:500] + "..."
                parts.append(f"**{role}**: [Tool: {block.name}]\n```json\n{tool_input_str}\n```")
            elif hasattr(block, 'content') and hasattr(block, 'tool_use_id'):
                # ToolResultBlock
                content = block.content
                if len(content) > 500:
                    content = content[:500] + "..."
                parts.append(f"**{role}**: [Tool Result]\n{content}")
            else:
                # Other block types
                parts.append(f"**{role}**: [Content block: {type(block).__name__}]")

        return "\n\n".join(parts) if parts else "Exchange completed."

    def _build_watcher_context(self, watcher_session) -> str:
        """Build context from watcher session's turns for the summary prompt.

        Includes previous summaries, user instructions, and watcher responses
        to give the LLM context for generating new summaries.

        Args:
            watcher_session: The watcher Session object

        Returns:
            Formatted text context from the watcher's conversation
        """
        from models import WatchStartBlock, WatchStopBlock, WatchSummaryBlock, TextBlock

        context_parts = []

        for turn in watcher_session.turns:
            block = turn.content_block
            role = turn.role

            if isinstance(block, WatchStartBlock):
                context_parts.append(f"[Started watching {block.target_session_name}]")
            elif isinstance(block, WatchStopBlock):
                context_parts.append(f"[Stopped watching: {block.reason}]")
            elif isinstance(block, WatchSummaryBlock):
                context_parts.append(f"[Summary {block.exchange_index + 1}]: {block.summary}")
            elif role == "user" and hasattr(block, 'text'):
                # User instructions to the watcher
                context_parts.append(f"**User instruction**: {block.text}")
            elif role == "assistant" and hasattr(block, 'text'):
                # Watcher's previous responses
                context_parts.append(f"**Watcher response**: {block.text}")

        return "\n\n".join(context_parts) if context_parts else ""

    def _build_watcher_summary_prompt(
        self,
        watcher_context: str,
        target_session_name: str,
        exchange_index: int,
        exchange_content: str,
    ) -> str:
        """Build the prompt for generating a watcher summary.

        The prompt includes the watcher's context (previous summaries, user instructions)
        and the target exchange content, asking the LLM to generate a contextualized summary.

        Args:
            watcher_context: Context from the watcher session
            target_session_name: Name of the target session
            exchange_index: Index of the exchange being summarized
            exchange_content: Formatted content of the target exchange

        Returns:
            The complete prompt for summary generation
        """
        prompt_parts = []

        # Add watcher context if available
        if watcher_context:
            prompt_parts.append(f"""## Your Watching Context

You are watching the session "{target_session_name}". Here is your context from previous summaries and user instructions:

{watcher_context}

---""")

        # Add the exchange to summarize
        prompt_parts.append(f"""## Exchange {exchange_index + 1} to Summarize

The target session "{target_session_name}" just completed this exchange:

{exchange_content}

---

## Instructions

Provide a 2-4 sentence summary of this exchange. Focus on:
- What was attempted or asked
- Key outcomes or changes
- Anything the user previously asked you to watch for (if applicable)

Keep the summary concise but informative. If the user gave you specific instructions about what to watch for, prioritize highlighting those aspects.

Summary:""")

        return "\n\n".join(prompt_parts)

    async def _start_watcher_summary_generation(
        self,
        watcher_session_id: str,
        target_session_id: str,
        target_session_name: str,
        exchange_index: int,
        exchange_content: str,
    ) -> None:
        """Start LLM-based summary generation for a watcher.

        Uses a HelperRunner to asynchronously generate the summary using the
        watcher's full context. The summary will be injected when generation completes.

        Args:
            watcher_session_id: ID of the watcher session
            target_session_id: ID of the target session
            target_session_name: Display name of the target session
            exchange_index: Index of the exchange being summarized
            exchange_content: Formatted content of the target exchange
        """
        import uuid

        # Load watcher session
        watcher_session = self._manager.get_session(watcher_session_id)
        if not watcher_session:
            watcher_session = await self._manager.load_session(watcher_session_id)
            if not watcher_session:
                debug_log.warning(
                    f"Could not load watcher session {watcher_session_id[:8]}",
                    category=Category.SESSION,
                )
                return

        # Build context from watcher's previous turns
        watcher_context = self._build_watcher_context(watcher_session)

        # Build the summary prompt
        prompt = self._build_watcher_summary_prompt(
            watcher_context=watcher_context,
            target_session_name=target_session_name,
            exchange_index=exchange_index,
            exchange_content=exchange_content,
        )

        # Start helper with metadata for auto-completion
        helper_id = str(uuid.uuid4())
        metadata = {
            "watcher_session_id": watcher_session_id,
            "target_session_id": target_session_id,
            "target_session_name": target_session_name,
            "exchange_index": exchange_index,
            "auto_complete": True,  # Auto-inject when complete
        }

        debug_log.info(
            f"Starting watcher summary generation: helper={helper_id[:8]}, watcher={watcher_session_id[:8]}",
            category=Category.SESSION,
            details={
                "target_session_id": target_session_id[:8],
                "exchange_index": exchange_index,
                "context_len": len(watcher_context),
            },
        )

        # Use the watcher's backend for summary generation
        self.start_helper(
            helper_id=helper_id,
            helper_type="watch_summary",
            prompt=prompt,
            session_id=watcher_session_id,
            metadata=metadata,
            backend_name=watcher_session.backend_name or None,
        )

    async def _inject_watch_summary(
        self,
        watcher_session_id: str,
        target_session_id: str,
        target_session_name: str,
        exchange_index: int,
        summary: str,
        trigger_response: bool = True,
    ) -> None:
        """Inject a WatchSummaryBlock into a watcher session and optionally trigger LLM response.

        Args:
            watcher_session_id: ID of the watcher session
            target_session_id: ID of the target session
            target_session_name: Display name of the target session
            exchange_index: Index of the exchange being summarized
            summary: The LLM-generated summary content
            trigger_response: If True, trigger the watcher LLM to respond to the summary
        """
        from models import WatchSummaryBlock

        watcher_session = self._manager.get_session(watcher_session_id)
        if not watcher_session:
            watcher_session = await self._manager.load_session(watcher_session_id)
            if not watcher_session:
                return

        # Add the summary turn
        summary_turn = watcher_session.add_watch_summary_turn(
            target_session_id=target_session_id,
            target_session_name=target_session_name,
            exchange_index=exchange_index,
            summary=summary,
        )

        await watcher_session.save()

        # Emit turn events so UI updates
        summary_turn_idx = len(watcher_session.turns) - 1
        summary_exchange_id = str(uuid.uuid4())
        await self._notify_observers(
            "on_turn_created",
            TurnCreatedEvent(
                session_id=watcher_session_id,
                turn_id=summary_turn.id,
                turn_index=summary_turn_idx,
                role="system",
                exchange_id=summary_exchange_id,
                content_block_type="watch_summary",
            ),
        )
        await self._notify_observers(
            "on_turn_finished",
            TurnFinishedEvent(
                session_id=watcher_session_id,
                turn_id=summary_turn.id,
                turn_index=summary_turn_idx,
                role="system",
                content=f"[Summary of exchange {exchange_index + 1}]",
                tokens=0,
                content_block=summary_turn.content_block,
            ),
        )

        debug_log.info(
            f"Injected summary for exchange {exchange_index} into watcher {watcher_session_id[:8]}",
            category=Category.SESSION,
        )

        # Trigger watcher LLM response to the summary
        if trigger_response:
            await self._trigger_watcher_response(
                watcher_session_id=watcher_session_id,
                target_session_name=target_session_name,
                exchange_index=exchange_index,
                summary=summary,
            )

    async def _trigger_watcher_response(
        self,
        watcher_session_id: str,
        target_session_name: str,
        exchange_index: int,
        summary: str,
    ) -> None:
        """Trigger the watcher LLM to respond to an injected summary.

        The watcher's response is guided by any user instructions in its context.
        Default behavior is minimal acknowledgment (e.g., "✓").

        Args:
            watcher_session_id: ID of the watcher session
            target_session_name: Name of the target session
            exchange_index: Index of the exchange that was summarized
            summary: The summary content that was injected
        """
        # Get runner for the watcher session
        runner = self._manager.get_runner(watcher_session_id)
        if not runner:
            debug_log.warning(
                f"No runner for watcher session {watcher_session_id[:8]}, skipping response",
                category=Category.SESSION,
            )
            return

        watcher_session = self._manager.get_session(watcher_session_id)
        if not watcher_session:
            watcher_session = await self._manager.load_session(watcher_session_id)
            if not watcher_session:
                return

        # Build the response prompt - this guides how the watcher responds to summaries
        response_prompt = self._build_watcher_response_prompt(
            target_session_name=target_session_name,
            exchange_index=exchange_index,
            summary=summary,
        )

        # Check if watcher is currently streaming
        if runner.is_streaming:
            # Queue the response for later
            debug_log.info(
                f"Watcher {watcher_session_id[:8]} is busy, queueing response",
                category=Category.SESSION,
            )
            # Use the session's message queue
            watcher_session.message_queue.add(response_prompt)
            await watcher_session.save()
            return

        # Start streaming the watcher's response
        try:
            # Submit as a pseudo-user message (the summary acts as the input)
            result = await self.submit_message(
                session_id=watcher_session_id,
                content=response_prompt,
                queue=True,  # Queue if busy (shouldn't happen given check above)
            )
            debug_log.info(
                f"Triggered watcher response: session={watcher_session_id[:8]}, exchange_id={result.exchange_id}",
                category=Category.SESSION,
            )
        except Exception as e:
            debug_log.error(
                f"Failed to trigger watcher response: {e}",
                category=Category.SESSION,
            )

    def _build_watcher_response_prompt(
        self,
        target_session_name: str,
        exchange_index: int,
        summary: str,
    ) -> str:
        """Build the prompt for the watcher's response to a summary.

        The prompt guides the watcher to respond based on any user instructions.
        Default behavior is minimal acknowledgment.

        Args:
            target_session_name: Name of the target session
            exchange_index: Index of the exchange
            summary: The summary content

        Returns:
            The prompt for the watcher's response
        """
        return f"""A new summary has been injected from the target session "{target_session_name}":

**[Summary {exchange_index + 1}]**: {summary}

Based on the user's instructions (if any), respond appropriately:
- If no specific instructions: Give a brief acknowledgment (e.g., "✓" or "Noted.")
- If user asked for analysis: Provide your analysis
- If user asked to watch for something specific: Note if this relates to that
- If user asked you to intervene: Use send_to_target() if appropriate

Keep your response concise unless the user asked for detailed analysis."""

    # --- Archive Operations ---

    @ws_expose
    async def start_archive(
        self,
        session_id: str,
        turn_indices: list[int],
        auto_complete: bool = True,
    ) -> StartArchiveResult:
        """Start archiving turns with LLM-generated summary.

        This starts a background task to generate a summary of the turns being
        archived. The actual archive is performed after the summary completes.

        Args:
            session_id: ID of the session to archive turns from
            turn_indices: List of turn indices to archive (must be contiguous)
            auto_complete: If True, automatically complete the archive after
                          summary generation. If False, client must call
                          complete_archive() manually.

        Returns:
            StartArchiveResult with helper_id for tracking progress
        """
        from core.summarizer import Summarizer

        # Load the session
        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return StartArchiveResult(success=False, error=f"Session {session_id} not found")

        if not turn_indices:
            return StartArchiveResult(success=False, error="No turns specified")

        # Calculate turn range (must be contiguous)
        turn_start = min(turn_indices)
        turn_end = max(turn_indices) + 1

        # Validate indices
        if turn_start < 0 or turn_end > len(session.turns):
            return StartArchiveResult(
                success=False,
                error=f"Invalid turn range: {turn_start}-{turn_end}, session has {len(session.turns)} turns"
            )

        # Get turns to archive
        turns_to_archive = session.turns[turn_start:turn_end]

        debug_log.info(
            f"Starting archive: session={session_id[:8]}, turns={turn_start}-{turn_end-1}",
            category=Category.SESSION,
        )

        # Build summary prompt
        summarizer = Summarizer(runner=None)  # We don't need the runner for prompt building
        summary_prompt = summarizer.build_archive_summary_prompt(turns_to_archive, "")

        # Generate helper ID
        helper_id = f"archive-{uuid.uuid4().hex[:8]}"

        # Store archive metadata for completion
        archive_metadata = {
            "session_id": session_id,
            "turn_indices": list(turn_indices),
            "turn_start": turn_start,
            "turn_end": turn_end,
            "auto_complete": auto_complete,
        }

        # Start helper task
        self.start_helper(
            helper_id=helper_id,
            helper_type="archive",
            prompt=summary_prompt,
            session_id=session_id,
            metadata=archive_metadata,
        )

        return StartArchiveResult(
            success=True,
            helper_id=helper_id,
            session_id=session_id,
            turn_start=turn_start,
            turn_end=turn_end,
        )

    @ws_expose
    async def complete_archive(
        self,
        helper_id: str,
        summary: str | None = None,
    ) -> CompleteArchiveResult:
        """Complete an archive after summary generation.

        Can be called manually with a custom summary, or automatically
        by the helper completion handler with the generated summary.

        Args:
            helper_id: ID of the archive helper task
            summary: Summary text to use. If None, uses the helper's generated summary.

        Returns:
            CompleteArchiveResult with archive details
        """
        from core.command_executor import CommandExecutor

        # Get helper context
        helper_ctx = self._helper_contexts.get(helper_id)
        if not helper_ctx:
            return CompleteArchiveResult(success=False, error=f"Helper {helper_id} not found")

        if helper_ctx.helper_type != "archive":
            return CompleteArchiveResult(success=False, error=f"Helper {helper_id} is not an archive task")

        # Get archive metadata
        metadata = helper_ctx.metadata
        session_id = metadata.get("session_id", "")
        turn_indices = metadata.get("turn_indices", [])
        turn_start = metadata.get("turn_start", 0)
        turn_end = metadata.get("turn_end", 0)

        # Use provided summary or helper's generated content
        archive_summary = summary if summary is not None else helper_ctx.content.strip()
        if not archive_summary:
            archive_summary = f"Archived turns {turn_start}-{turn_end - 1}"

        debug_log.info(
            f"Completing archive: session={session_id[:8]}, summary={archive_summary[:50]}...",
            category=Category.SESSION,
        )

        # Load session
        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return CompleteArchiveResult(success=False, error=f"Session {session_id} not found")

        # Use command executor to perform archive
        executor = CommandExecutor()
        result = executor.prepare_archive(
            session=session,
            turn_indices=turn_indices,
            summary=archive_summary,
        )

        if not result.success:
            return CompleteArchiveResult(success=False, error=result.error or "Archive failed")

        # Update session with new turns
        session.turns = result.new_turns
        await session.save()

        # Emit session updated event for React UI
        self._emit_session_updated(session, is_streaming=False)

        # Clean up helper context
        self._helper_contexts.pop(helper_id, None)
        self._helper_runners.pop(helper_id, None)

        # Emit session updated event
        self._emit_event(SessionManagerEvent.SESSION_UPDATED, session_id)

        # Build the result
        archive_result = CompleteArchiveResult(
            success=True,
            session_id=session_id,
            archive_id=result.archive_block.archive_id if result.archive_block else "",
            turn_index=turn_start,
            turns_archived=result.archived_count,
            helper_id=helper_id,
        )

        # Emit archive completed event so UI can reload turns
        archive_event_data = {
            "session_id": session_id,
            "archive_id": archive_result.archive_id,
            "turn_index": archive_result.turn_index,
            "turns_archived": archive_result.turns_archived,
            "helper_id": helper_id,
        }
        debug_log.info(
            f"Emitting onArchiveCompleted event to {len(self._event_handlers)} handlers",
            category=Category.SESSION,
            details=archive_event_data,
        )
        for handler in self._event_handlers:
            handler("onArchiveCompleted", archive_event_data)

        return archive_result

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
            # Rebuild watcher relationships for the now-loaded session
            session = self._manager.get_session(session_id)
            if session:
                await self._rebuild_watcher_for_session(session)
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
            session = await self._load_session_with_watcher_rebuild(session_id)
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

        # Emit session updated so React frontend knows we're streaming
        self._emit_session_updated(session, is_streaming=True)

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
                turn_id=user_turn.id,
                role="user",
                turn_type="text_turn",
            )
            self._task_service.emit_turn_finished(
                session_id=session_id,
                exchange_id=exchange_id,
                turn_index=turn_index,
                turn_id=user_turn.id,
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

        # Emit session updated so React frontend knows we're streaming
        self._emit_session_updated(session, is_streaming=True)

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
                turn_id=user_turn.id,
                role="user",
                turn_type="text_turn",
            )
            self._task_service.emit_turn_finished(
                session_id=session_id,
                exchange_id=exchange_id,
                turn_index=turn_index,
                turn_id=user_turn.id,
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

    @ws_expose
    async def submit_markdown_message(
        self,
        session_id: str,
        content: str,
        queue: bool = False,
        allowed_tools: list[str] | None = None,
    ) -> SubmitMessageResult:
        """Submit a markdown message to a session and start streaming the response.

        Similar to submit_message but the user turn is stored and displayed as
        a MarkdownBlock instead of TextBlock, allowing rich formatting (code blocks,
        tables, etc.) in user-submitted content like code reviews.

        Args:
            session_id: ID of the session to submit to
            content: The markdown content (user prompt)
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

        # Add user message to session (persists immediately)
        # Use MarkdownBlock instead of TextBlock for rich rendering
        turn_index = len(session.turns)
        user_blocks = [MarkdownBlock(text=content)]
        user_turn = session.add_message(
            "user", content, content_blocks=user_blocks, exchange_id=exchange_id
        )
        await session.save()

        # Emit session updated so React frontend knows we're streaming
        self._emit_session_updated(session, is_streaming=True)

        # Emit user turn events via observer pattern
        await self._notify_observers(
            "on_turn_created",
            TurnCreatedEvent(
                session_id=session_id,
                turn_id=user_turn.id,
                turn_index=turn_index,
                role="user",
                exchange_id=exchange_id,
                content_block_type="markdown",  # Key difference: markdown instead of text
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
                content_block=MarkdownBlock(type="markdown", text=content),  # Key difference
            ),
        )

        # TaskStateService calls
        if self._task_service:
            self._task_service.emit_turn_started(
                session_id=session_id,
                exchange_id=exchange_id,
                turn_index=turn_index,
                turn_id=user_turn.id,
                role="user",
                turn_type="markdown_turn",  # Different turn type for tracking
            )
            self._task_service.emit_turn_finished(
                session_id=session_id,
                exchange_id=exchange_id,
                turn_index=turn_index,
                turn_id=user_turn.id,
                role="user",
                content=content,
            )

        # Generate assistant turn ID for tracking streaming events
        assistant_turn_id = str(uuid.uuid4())

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
            assistant_turn_id=assistant_turn_id,
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
        self._emit_event(
            SessionManagerEvent.MESSAGE_SUBMITTED,
            session_id,
            {
                "exchange_id": exchange_id,
                "turn_index": turn_index,
                "content": content,
                "content_type": "markdown",
            },
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
                category=Category.LIFECYCLE,
                details={"session_id": session_id},
            )
            return False

        config = get_config()
        executor = CommandExecutor()
        result = executor.set_backend(session, backend_name, config)

        if result.success:
            # Save session to persist the change
            await session.save()

            # Recreate the runner with the new backend configuration
            # This is critical - without this, the old runner continues to use
            # the previous backend until the session is reloaded
            from core.runner import SessionRunner
            from core.runner_factory import create_runner

            backend_config = config.get_backend(backend_name)
            new_runner = SessionRunner(session, runner=create_runner(backend_config))
            self._manager.update_runner(session_id, new_runner)

            # Emit session updated event so React UI sees the backend change
            self._emit_session_updated(session)

            debug_log.info(
                f"Backend changed to {backend_name}",
                category=Category.LIFECYCLE,
                details={"session_id": session_id, "backend": backend_name},
            )
            return True
        else:
            debug_log.warn(
                f"Failed to set backend: {result.error}",
                category=Category.LIFECYCLE,
                details={"session_id": session_id, "error": result.error},
            )
            return False

    @ws_expose
    async def set_session_title(
        self, session_id: str, title: str
    ) -> bool:
        """Set the title for a session.

        Args:
            session_id: ID of the session to update
            title: New title for the session

        Returns:
            True if successful, False if session not found
        """
        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return False

        # Update the title
        session.title = title
        await session.save()

        # Emit session updated event so React UI sees the title change
        self._emit_session_updated(session)

        debug_log.info(
            f"Session title changed to: {title}",
            category=Category.SESSION,
            details={"session_id": session_id, "title": title},
        )
        return True

    @ws_expose
    async def set_session_working_directory(
        self, session_id: str, working_directory: str
    ) -> bool:
        """Set the working directory for a session.

        Args:
            session_id: ID of the session to update
            working_directory: New working directory path

        Returns:
            True if successful, False if session not found or path invalid
        """
        import os

        # Validate the path exists
        if not os.path.isdir(working_directory):
            debug_log.warn(
                f"Invalid working directory: {working_directory}",
                category=Category.SESSION,
                details={"session_id": session_id, "path": working_directory},
            )
            return False

        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return False

        # Update the working directory
        session.set_working_directory(working_directory)
        await session.save()

        # Emit session updated event so React UI sees the change
        self._emit_session_updated(session)

        debug_log.info(
            f"Session working directory changed to: {working_directory}",
            category=Category.SESSION,
            details={"session_id": session_id, "working_directory": working_directory},
        )
        return True

    # --- Session Review Methods ---

    @ws_expose
    async def start_session_review(
        self,
        session_id: str,
        backend_name: str,
    ) -> StartSessionReviewResult:
        """Start a session review using the specified backend.

        This initiates an LLM call to analyze the session and generate a
        structured review. The review runs asynchronously; use helper events
        to track progress and complete_session_review() when done.

        Args:
            session_id: The session to review
            backend_name: Which backend to use for generating the review

        Returns:
            StartSessionReviewResult with helper_id for tracking progress
        """
        from core.summarizer import Summarizer

        # Load the session
        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return StartSessionReviewResult(
                    success=False,
                    error=f"Session {session_id} not found"
                )

        # Validate backend exists
        if backend_name not in self._backend_config:
            available = list(self._backend_config.keys())
            return StartSessionReviewResult(
                success=False,
                error=f"Unknown backend: {backend_name}. Available: {available}"
            )

        debug_log.info(
            f"Starting session review: session={session_id[:8]}, backend={backend_name}",
            category=Category.SESSION,
        )

        # Build review prompt
        summarizer = Summarizer(runner=None, backend_name=backend_name)
        review_prompt = summarizer.build_session_review_prompt(session)

        if review_prompt is None:
            return StartSessionReviewResult(
                success=False,
                error="Session has no conversation content to review"
            )

        # Generate helper ID
        helper_id = f"review-{uuid.uuid4().hex[:8]}"

        # Store review metadata for completion
        review_metadata = {
            "session_id": session_id,
            "backend_name": backend_name,
            "turn_count": len(session.turns),
            "auto_complete": True,  # React UI uses auto-completion
        }

        # Start helper runner for the review
        self.start_helper(
            helper_id=helper_id,
            helper_type="session_review",
            prompt=review_prompt,
            session_id=session_id,
            metadata=review_metadata,
            backend_name=backend_name,
        )

        return StartSessionReviewResult(
            success=True,
            helper_id=helper_id,
            session_id=session_id,
            backend_name=backend_name,
        )

    @ws_expose
    async def complete_session_review(
        self,
        helper_id: str,
        result_text: str,
    ) -> CompleteSessionReviewResult:
        """Complete a session review after LLM summary generation.

        Called by the frontend after the helper runner finishes streaming
        the review content.

        Args:
            helper_id: The helper ID from start_session_review
            result_text: The accumulated LLM response text

        Returns:
            CompleteSessionReviewResult with the parsed review data
        """
        from core.summarizer import Summarizer
        from datetime import datetime

        # Get helper context
        ctx = self._helper_contexts.get(helper_id)
        if not ctx:
            return CompleteSessionReviewResult(
                success=False,
                error=f"No active review helper: {helper_id}"
            )

        session_id = ctx.session_id
        metadata = ctx.metadata or {}
        backend_name = metadata.get("backend_name", "unknown")
        turn_count = metadata.get("turn_count", 0)

        # Load the session
        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return CompleteSessionReviewResult(
                    success=False,
                    error=f"Session {session_id} not found"
                )

        # Parse the LLM response into a SessionSummaryBlock
        summarizer = Summarizer(runner=None, backend_name=backend_name)
        review = summarizer._parse_session_review(result_text, session)

        # Override metadata from our tracked context
        review.turn_count_at_review = turn_count
        review.reviewed_by_backend = backend_name
        review.reviewed_at = datetime.now().isoformat()

        # Add the review as a turn in the session
        turn = Turn(
            role="system",
            content_block=review,
        )
        session.turns.append(turn)
        await session.save()

        turn_index = len(session.turns) - 1

        debug_log.info(
            f"Session review completed: session={session_id[:8]}, "
            f"summary_id={review.summary_id[:8]}, title='{review.proposed_title}'",
            category=Category.SESSION,
        )

        # Clean up helper context
        self._helper_contexts.pop(helper_id, None)
        self._helper_runners.pop(helper_id, None)

        # Emit session updated event
        self._emit_event(SessionManagerEvent.SESSION_UPDATED, session_id)

        return CompleteSessionReviewResult(
            success=True,
            session_id=session_id,
            summary_id=review.summary_id,
            turn_index=turn_index,
            proposed_title=review.proposed_title,
            markdown_content=review.markdown_content,
        )

    @ws_expose
    async def approve_session_review(
        self,
        session_id: str,
        summary_id: str,
        approved_title: str,
        edited_markdown: str | None = None,
    ) -> ApproveSessionReviewResult:
        """Approve a session review and update the session title.

        Args:
            session_id: The session containing the review
            summary_id: The ID of the SessionSummaryBlock to approve
            approved_title: The final title (may differ from proposed)
            edited_markdown: Optional edited markdown content

        Returns:
            ApproveSessionReviewResult with success status
        """
        # Load the session
        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return ApproveSessionReviewResult(
                    success=False,
                    error=f"Session {session_id} not found"
                )

        # Find the review turn
        found = False
        for turn in session.turns:
            if (isinstance(turn.content_block, SessionSummaryBlock)
                and turn.content_block.summary_id == summary_id):
                turn.content_block.status = "approved"
                turn.content_block.approved_title = approved_title
                if edited_markdown is not None:
                    turn.content_block.markdown_content = edited_markdown
                    # Re-parse structured fields from edited markdown
                    self._update_review_from_markdown(turn.content_block, edited_markdown)
                found = True
                break

        if not found:
            return ApproveSessionReviewResult(
                success=False,
                error=f"Review {summary_id} not found in session"
            )

        # Update session title
        session.title = approved_title
        await session.save()

        debug_log.info(
            f"Session review approved: session={session_id[:8]}, "
            f"summary_id={summary_id[:8]}, title='{approved_title}'",
            category=Category.SESSION,
        )

        # Emit session updated event
        self._emit_event(SessionManagerEvent.SESSION_UPDATED, session_id)

        return ApproveSessionReviewResult(
            success=True,
            session_id=session_id,
            summary_id=summary_id,
            approved_title=approved_title,
        )

    def _update_review_from_markdown(
        self,
        review: SessionSummaryBlock,
        markdown: str,
    ) -> None:
        """Update review's structured fields from edited markdown.

        Args:
            review: The SessionSummaryBlock to update
            markdown: The edited markdown content
        """
        # Parse markdown sections back to structured data
        sections = markdown.split("## ")
        for section in sections:
            if not section.strip():
                continue

            lines = section.split("\n")
            header = lines[0].strip().lower()
            body = "\n".join(lines[1:]).strip()

            if "summary" in header:
                review.work_done = body
            elif "files" in header:
                review.files_modified = self._parse_list_items(body)
            elif "decisions" in header:
                review.decisions_made = self._parse_list_items(body)
            elif "next" in header:
                review.next_steps = self._parse_list_items(body)
            elif "questions" in header:
                review.questions_raised = self._parse_list_items(body)

    def _parse_list_items(self, text: str) -> list[str]:
        """Parse markdown list items from text."""
        items = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                item = line[1:].strip()
                if item and item.lower() != "none":
                    items.append(item)
        return items

    @ws_expose
    async def get_session_reviews(
        self,
        session_id: str,
    ) -> list[dict]:
        """Get all reviews for a session.

        Returns a list of review dictionaries with summary info for display
        in the review history sidebar.

        Args:
            session_id: The session to get reviews for

        Returns:
            List of review dictionaries
        """
        # Load the session
        session = self._manager.get_session(session_id)
        if not session:
            session = await self._manager.load_session(session_id)
            if not session:
                return []

        reviews = []
        for i, turn in enumerate(session.turns):
            if isinstance(turn.content_block, SessionSummaryBlock):
                block = turn.content_block
                reviews.append({
                    "summary_id": block.summary_id,
                    "turn_index": i,
                    "proposed_title": block.proposed_title,
                    "approved_title": block.approved_title,
                    "markdown_content": block.markdown_content,
                    "work_done": block.work_done,
                    "files_modified": block.files_modified,
                    "decisions_made": block.decisions_made,
                    "next_steps": block.next_steps,
                    "questions_raised": block.questions_raised,
                    "status": block.status,
                    "reviewed_at": block.reviewed_at,
                    "reviewed_by_backend": block.reviewed_by_backend,
                    "turn_count_at_review": block.turn_count_at_review,
                })

        # Return newest first for history sidebar
        reviews.reverse()

        return reviews

    # --- Git Commit Message Generation ---

    @ws_expose
    async def generate_commit_message(
        self,
        git_root: str,
        staged_diff: str,
    ) -> GenerateCommitMessageResult:
        """Generate a commit message using the LLM.

        Starts a background helper task to generate a commit message based on
        the staged git diff. The helper_id can be used to track progress via
        helper events (helperDelta, helperDone).

        Args:
            git_root: Path to the git repository root
            staged_diff: The staged diff output (from git diff --cached)

        Returns:
            GenerateCommitMessageResult with helper_id for tracking progress
        """
        if not staged_diff.strip():
            return GenerateCommitMessageResult(
                success=False,
                error="No staged changes to generate commit message for"
            )

        # Build the commit message prompt - be very explicit to avoid context confusion
        prompt = f"""You are a commit message generator. Your ONLY task is to generate a git commit message for the code changes shown below.

DO NOT:
- Discuss session management, goals, or todos
- Ask questions or seek clarification
- Provide explanations beyond the commit message
- Use any tools or propose any actions

JUST output a commit message following these conventions:
- Start with a brief summary line (50 chars or less)
- Use imperative mood ("Add feature" not "Added feature")
- Focus on what changed and why, not how
- If there are multiple changes, list the most important ones

Here are the staged changes to commit:

```diff
{staged_diff[:8000]}
```
{"(diff truncated due to size)" if len(staged_diff) > 8000 else ""}

Output ONLY the commit message, nothing else:"""

        # Generate helper ID
        helper_id = f"commit-msg-{uuid.uuid4().hex[:8]}"

        debug_log.info(
            f"Starting commit message generation: helper_id={helper_id}",
            category=Category.RUNNER,
            details={
                "diff_length": len(staged_diff),
                "diff_preview": staged_diff[:500] if staged_diff else "(empty)",
            },
        )

        # Start helper task (no session_id since this isn't tied to a session)
        self.start_helper(
            helper_id=helper_id,
            helper_type="commit_message",
            prompt=prompt,
            session_id=None,
            metadata={"git_root": git_root},
        )

        return GenerateCommitMessageResult(
            success=True,
            helper_id=helper_id,
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

    @ws_event
    async def on_archive_started(self) -> StartArchiveResult:
        """Emitted when an archive operation begins."""
        ...

    @ws_event
    async def on_archive_completed(self) -> CompleteArchiveResult:
        """Emitted when an archive operation completes successfully."""
        ...
