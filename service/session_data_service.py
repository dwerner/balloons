"""WebSocket-exposed service for session data streaming.

This service provides real-time session data subscriptions, allowing clients
to subscribe to specific sessions and receive turn updates as they happen.

Unlike TreeStateService which exposes the full tree structure, this service
focuses on efficient streaming of session content:
- Clients subscribe to specific sessions by ID
- Turn deltas stream as content is generated
- Snapshots provide full state for late-joining clients

This service implements SessionEventObserver to receive events from
SessionManagerService and forward them to subscribed WebSocket clients.

Example usage:
    service = SessionDataService()

    # Subscribe to a session:
    # {"id": "1", "method": "subscribeSession", "params": {"sessionId": "abc"}}
    # -> {"id": "1", "result": {"sessionId": "abc", "subscribed": true}}

    # Receive streaming events:
    # {"event": "turnDelta", "data": {"sessionId": "abc", "turnId": "uuid-123", "delta": "Hello"}}
"""

import asyncio
from dataclasses import dataclass, field, asdict
from typing import Callable, TYPE_CHECKING, Any, Awaitable, Union

from codegen import ws_service, ws_expose, ws_event, ws_type
from service.subscription_manager import SubscriptionManager, Layer
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
    DomainEventWrapper,
)
from models import (
    TextBlock, MarkdownBlock, ImageBlock, ToolUseBlock, ToolResultBlock,
    InterruptionBlock, ErrorBlock, LinkBlock, ForkBlock, ForkedFromBlock,
    MergeBlock, MergedToBlock, ArchiveBlock, SlideBlock, ReviewBlock,
    ForkProposalBlock, MergeProposalBlock,
    WatchStartBlock, WatchStopBlock, WatchSummaryBlock
)
from core.debug_log import debug_log, Category

if TYPE_CHECKING:
    from core.async_storage import AsyncStorage
    from core.stream_state import StreamState

# ContentBlock union for type annotations
ContentBlock = Union[
    TextBlock, MarkdownBlock, ImageBlock, ToolUseBlock, ToolResultBlock,
    InterruptionBlock, ErrorBlock, LinkBlock, ForkBlock, ForkedFromBlock,
    MergeBlock, MergedToBlock, ArchiveBlock, SlideBlock, ReviewBlock,
    ForkProposalBlock, MergeProposalBlock,
    WatchStartBlock, WatchStopBlock, WatchSummaryBlock
]

# Type for session loader callback: async (session_id) -> Session | None
SessionLoaderCallback = Callable[[str], Awaitable[Any]]


@ws_type
@dataclass
class TurnDelta:
    """Delta update for streaming turn content.

    Sent when new content is added to a turn during streaming.
    Clients accumulate deltas to build the full turn content.
    """

    session_id: str
    turn_id: str  # Stable UUID for the turn
    delta: str  # New text chunk
    accumulated_length: int  # Total length so far (for validation)
    exchange_id: str | None = None


@ws_type
@dataclass
class TurnSnapshot:
    """Complete snapshot of a single turn.

    Used in SessionSnapshot to provide full turn state.
    turn_id is the stable identifier for targeting updates.

    content_block contains the full structured data for the turn,
    discriminated by the 'type' field (e.g., "text", "tool_use", "fork").

    order is the turn's position in the session (0-indexed), used by clients
    to sort turns correctly when history chunks arrive out of order with
    streaming events.
    """

    turn_id: str  # Stable UUID for the turn (primary identifier)
    role: str  # "user", "assistant", "tool"
    streaming: bool
    viewed: bool
    tokens: int
    context_mode: str  # "copy", "compress", "drop"
    content_block: ContentBlock  # Full structured content block
    order: int = 0  # Turn position in session (for sorting)
    exchange_id: str | None = None
    timestamp: str | None = None  # ISO 8601 format, when turn was created
    parallel_group_id: str | None = None  # Groups parallel tool calls from same LLM response
    is_steering: bool = False  # True if this user turn was injected mid-stream as steering
    responds_to_steering: bool = False  # True if this assistant turn follows a steering message


@ws_type
@dataclass
class SessionSnapshot:
    """Complete snapshot of a session's current state.

    Sent when a client subscribes to provide full initial state.
    After receiving a snapshot, clients receive incremental TurnDeltas.

    Turns are ordered by array position (storage order).
    streaming_turn_ids identifies which turns are actively streaming.
    """

    session_id: str
    title: str
    model: str
    is_streaming: bool
    turns: list[TurnSnapshot] = field(default_factory=list)
    streaming_turn_ids: list[str] = field(default_factory=list)  # Turn IDs currently streaming


@ws_type
@dataclass
class SubscriptionResult:
    """Result of a subscribe/unsubscribe operation.

    When subscribing with history_lazy layer, includes metadata about
    available turns so the client knows what range to request.
    """

    session_id: str
    subscribed: bool
    error: str | None = None
    # Metadata for lazy loading - tells client what's available
    total_turns: int | None = None  # Total turns in session (for lazy loading)
    is_streaming: bool | None = None  # Whether session is currently streaming


@ws_type
@dataclass
class SubscribeSessionResult:
    """Result of subscribing to a session with initial snapshot.

    Provides atomic subscription: the snapshot represents state at the moment
    of subscription, so clients can be sure they won't miss any events.
    """

    session_id: str
    subscribed: bool
    snapshot: SessionSnapshot | None = None  # Full state at subscription time
    error: str | None = None


@ws_type
@dataclass
class SessionTurnCreatedEvent:
    """Event payload when a new turn is created in a subscribed session."""

    session_id: str
    turn_id: str  # Stable UUID for the turn
    role: str
    order: int  # Position in turn list (for display ordering)
    exchange_id: str | None = None
    content_block_type: str = "text"
    parallel_group_id: str | None = None  # For grouping parallel tool calls
    is_steering: bool = False  # True if this user turn was injected mid-stream as steering


@ws_type
@dataclass
class SessionTurnDeltaEvent:
    """Event payload for streaming content updates."""

    session_id: str
    turn_id: str  # Stable UUID for the turn
    delta: str
    accumulated_length: int


@ws_type
@dataclass
class SessionTurnFinishedEvent:
    """Event payload when a turn finishes streaming."""

    session_id: str
    turn_id: str  # Stable UUID for the turn
    tokens: int  # Token count for this turn
    order: int = 0  # Turn index for ordering (critical for tool_result turns)
    role: str = "assistant"  # Turn role
    content_block: ContentBlock | None = None  # Full structured content block (optional for backwards compat)
    final_content: str = ""  # Deprecated: use content_block instead
    # Cumulative token counts for the exchange
    context_tokens: int = 0  # Total context/input tokens sent to LLM
    output_tokens_total: int = 0  # Total output tokens generated so far in this exchange


@ws_type
@dataclass
class SessionTurnsDeletedEvent:
    """Event payload when turns are deleted (e.g., during archive)."""

    session_id: str
    turn_indices: list[int]  # Indices of deleted turns
    turn_ids: list[str]  # IDs of deleted turns


@ws_type
@dataclass
class TurnOrderMapping:
    """Mapping of a turn ID to its new order."""

    turn_id: str
    new_order: int


@ws_type
@dataclass
class SessionTurnsReorderedEvent:
    """Event payload when turn orders are recomputed (e.g., after archive).

    After archiving turns, the remaining turns' `order` fields may have gaps.
    This event provides the new order for each turn so clients can update
    their local state without refetching the entire session.
    """

    session_id: str
    mappings: list[TurnOrderMapping]  # List of (turn_id, new_order) mappings


@ws_type
@dataclass
class SessionStreamStartedEvent:
    """Event payload when streaming starts for a session."""

    session_id: str
    exchange_id: str


@ws_type
@dataclass
class SessionStreamDoneEvent:
    """Event payload when streaming completes successfully."""

    session_id: str
    exchange_id: str
    input_tokens: int
    output_tokens: int


@ws_type
@dataclass
class SessionStreamProgressEvent:
    """Event payload for streaming progress updates.

    Emitted periodically during streaming (throttled, not on every delta).
    Provides real-time status for the status bar.
    """

    session_id: str
    exchange_id: str
    tokens_streamed: int  # Estimated output tokens so far
    current_token_rate: float  # Tokens/sec
    tool_name: str | None  # Currently executing tool, if any
    tool_count: int  # Tools executed so far
    model: str  # Model name
    context_window: int  # Model's context window
    duration_seconds: float  # Time since stream started


@ws_type
@dataclass
class SessionStreamErrorEvent:
    """Event payload when streaming fails or is cancelled."""

    session_id: str
    exchange_id: str
    error: str
    error_type: str  # "error", "rate_limit", "cancelled"


@ws_type
@dataclass
class SessionToolUseStartedEvent:
    """Event payload when a tool begins execution."""

    session_id: str
    exchange_id: str
    turn_index: int
    tool_use_id: str
    tool_name: str
    tool_index: int


@ws_type
@dataclass
class SessionToolInputDeltaEvent:
    """Event payload for streaming tool input JSON."""

    session_id: str
    exchange_id: str
    tool_use_id: str
    partial_json: str


@ws_type
@dataclass
class SessionToolUseEvent:
    """Event payload when tool input is complete."""

    session_id: str
    exchange_id: str
    turn_index: int
    tool_use_id: str
    tool_name: str
    tool_input: dict
    tool_index: int


@ws_type
@dataclass
class SessionToolResultEvent:
    """Event payload when a tool finishes execution."""

    session_id: str
    exchange_id: str
    turn_index: int
    tool_use_id: str
    tool_name: str
    result: str
    is_error: bool
    tool_index: int


@ws_type
@dataclass
class SessionDomainEvent:
    """Event payload when a domain plugin emits an event.

    This bridges domain state changes (chess moves, game over, etc.) to the UI.
    Clients can subscribe to specific domains/event_types as needed.
    """

    session_id: str
    domain_id: str  # e.g., "chess"
    event_type: str  # e.g., "move_made", "game_over"
    data: dict[str, Any]  # Event-specific payload


@ws_type
@dataclass
class SessionHistoryChunkEvent:
    """Event payload for a chunk of historical turns.

    Sent incrementally when a client subscribes to a session with history.
    Chunks may arrive out of order; clients should merge by turn_id and
    sort by the order field in TurnSnapshot.

    The watermark indicates the highest turn order in this chunk, useful
    for tracking loading progress and detecting gaps.

    When reversed=True, chunks arrive newest-first (highest orders first).
    This allows clients to show the bottom of conversation immediately
    while older history loads progressively.
    """

    session_id: str
    chunk_id: str  # Unique ID for this chunk (for deduplication)
    turns: list[TurnSnapshot]  # Historical turns in this chunk
    chunk_index: int  # 0-based index of this chunk (0 = first chunk sent, even if it's the last chronologically)
    total_chunks: int  # Total number of chunks expected
    watermark: int  # Highest turn order in this chunk
    reversed: bool = False  # True if chunks sent newest-first


@ws_type
@dataclass
class SessionHistoryCompleteEvent:
    """Event payload when all historical turns have been sent.

    Signals that the client has received all historical data and can
    finalize the initial render. Any streaming events received after
    subscription started should already be merged.
    """

    session_id: str
    total_turns: int  # Total number of historical turns sent
    final_watermark: int  # Highest turn order across all chunks


# --- Session Lifecycle Events (Phase 8: replaces TreeStateService events) ---


@ws_type
@dataclass
class ForkChild:
    """Information about a fork child session.

    Used in SessionInfo.children to list forks created from a session.
    """

    session_id: str
    name: str  # forkName or title
    status: str  # "active", "merged", "abandoned"
    fork_point: int  # Turn index where fork was created (-1 if unknown)


@ws_type
@dataclass
class ForkTreeNode:
    """A node in the fork tree structure.

    Used by get_session_fork_tree() to return the full tree of related sessions.
    The tree is rooted at the original ancestor session.
    """

    session_id: str
    name: str  # forkName or title
    status: str  # "active", "merged", "abandoned"
    is_current: bool  # True if this is the session we're viewing the tree from
    children: list["ForkTreeNode"] = field(default_factory=list)
    watch_targets: list[str] = field(default_factory=list)  # Session IDs this session is watching
    watched_by: list[str] = field(default_factory=list)  # Session IDs of watchers watching this session


@ws_type
@dataclass
class SessionInfo:
    """Session metadata for listing and display.

    This is the primary session info type used by SessionDataService.
    Replaces TreeStateService.SessionInfo.
    """

    id: str
    title: str
    created: str
    last_modified: str
    model: str
    message_count: int
    total_cost: float
    is_streaming: bool
    fork_name: str
    fork_status: str
    concluded: bool = False
    concluded_at: str | None = None
    parent_id: str | None = None
    cached_context_tokens: int = 0
    context_window: int = 150000
    binding_indicator: str = ""
    backend_name: str = ""
    is_pinned: bool = False
    working_directory: str = ""
    children: list[ForkChild] = field(default_factory=list)  # Fork children from this session
    watch_targets: list[str] = field(default_factory=list)  # Session IDs this session is watching
    watched_by: list[str] = field(default_factory=list)  # Session IDs of watchers watching this session


@ws_type
@dataclass
class SessionWatcherInfo:
    """Watcher relationship info for a session (lazy-loaded).

    Used by get_session_watcher_info() to return watch relationships
    without including them in every SessionInfo response.
    """

    session_id: str
    watch_targets: list[str] = field(default_factory=list)  # Sessions this session is watching
    watched_by: list[str] = field(default_factory=list)  # Sessions watching this session


@ws_type
@dataclass
class SessionAddedEvent:
    """Event payload when a new session is created."""

    session_id: str
    session: SessionInfo


@ws_type
@dataclass
class SessionUpdatedEvent:
    """Event payload when session metadata changes."""

    session_id: str
    session: SessionInfo


@ws_type
@dataclass
class SessionRemovedEvent:
    """Event payload when a session is deleted."""

    session_id: str


@ws_type
@dataclass
class SessionPinnedEvent:
    """Event payload when a session is pinned."""

    session_id: str
    is_pinned: bool


@ws_type
@dataclass
class PinnedSessionsChangedEvent:
    """Event payload when the pinned sessions list changes."""

    pinned_session_ids: list[str]


@ws_type
@dataclass
class ToolUseInfo:
    """Tool use information for TurnInfo backwards compatibility."""

    tool_use_id: str
    name: str
    input_json: str  # JSON string of tool input


@ws_type
@dataclass
class ToolResultInfo:
    """Tool result information for TurnInfo backwards compatibility."""

    tool_use_id: str
    content: str
    is_error: bool = False


@ws_type
@dataclass
class TurnImageInfo:
    """Image information for TurnInfo backwards compatibility."""

    source_type: str
    media_type: str
    data: str  # base64 or path


@ws_type
@dataclass
class TurnInfo:
    """Turn information for backwards compatibility with TreeStateService.

    This type maintains compatibility with the existing frontend which
    expects getTurns() to return TurnInfo[] objects.

    DEPRECATED: New code should use TurnSnapshot and the subscription API.
    """

    idx: int
    role: str
    content: str
    streaming: bool
    viewed: bool
    tokens: int
    context_mode: str
    content_block_type: str = "text"
    exchange_id: str | None = None
    images: list[TurnImageInfo] = field(default_factory=list)
    tool_use: ToolUseInfo | None = None
    tool_result: ToolResultInfo | None = None


@ws_service
class SessionDataService:
    """WebSocket-exposed service for session data streaming.

    Provides subscription-based access to session content with efficient
    delta streaming. Clients subscribe to sessions they want to observe
    and receive real-time updates.

    Key features:
    - Per-session subscriptions (only receive events for subscribed sessions)
    - Delta streaming for efficient bandwidth usage
    - Snapshots for late-joining clients
    - Turn lifecycle events (created, delta, finished)
    """

    # Configuration for chunked history loading
    HISTORY_CHUNK_SIZE = 50  # Number of turns per chunk

    def __init__(
        self,
        session_loader: SessionLoaderCallback | None = None,
        storage: "AsyncStorage | None" = None,
        stream_state: "StreamState | None" = None,
    ) -> None:
        """Initialize the session data service.

        Args:
            session_loader: Optional async callback to load sessions from storage.
                           Can also be set later via set_session_loader().
            storage: Optional AsyncStorage for direct LMDB access (used for chunked
                    history loading). Can also be set later via set_storage().
            stream_state: Optional StreamState for checking streaming status.
                         Can also be set later via set_stream_state().
        """
        # Event handlers receive: (event_name, data, target_clients)
        # target_clients is a set of client_ids that should receive the event
        self._event_handlers: list[Callable[[str, dict, set[str] | None], None]] = []
        # Layer-based subscription manager
        self._subscription_manager = SubscriptionManager()
        # Session loader callback for loading sessions from storage
        self._session_loader: SessionLoaderCallback | None = session_loader
        # AsyncStorage for direct LMDB access (chunked history loading)
        self._storage: "AsyncStorage | None" = storage
        # StreamState for checking which sessions are streaming
        self._stream_state: "StreamState | None" = stream_state
        # Track background history loading tasks: session_id -> task
        self._history_tasks: dict[str, asyncio.Task] = {}
        # Reference to SessionManagerService for getting sessions and emitting events
        # This creates a bidirectional relationship: SessionManagerService calls us via
        # observer pattern, and we call it back for session lookup and event emission.
        self._manager: Any = None  # SessionManagerService - set via set_manager()
        self._session_manager: Any = None  # Alias for _manager, used for event emission

    def set_manager(self, manager: Any) -> None:
        """Set the SessionManagerService reference.

        This creates a bidirectional relationship:
        - SessionManagerService calls SessionDataService via observer pattern
        - SessionDataService calls back for session lookup and event emission

        Args:
            manager: The SessionManagerService instance
        """
        self._manager = manager
        self._session_manager = manager  # Alias for event emission

    def set_session_loader(self, loader: SessionLoaderCallback) -> None:
        """Set the session loader callback.

        The callback should be an async function that takes a session_id
        and returns the Session object, or None if not found.

        Args:
            loader: Async callback (session_id) -> Session | None
        """
        self._session_loader = loader

    def set_storage(self, storage: "AsyncStorage") -> None:
        """Set the AsyncStorage for direct LMDB access.

        Enables chunked history loading for large sessions.

        Args:
            storage: The AsyncStorage instance for LMDB access
        """
        self._storage = storage

    def set_stream_state(self, stream_state: "StreamState") -> None:
        """Set the StreamState for checking streaming status.

        Required for accurate isStreaming field in session lists.

        Args:
            stream_state: The StreamState singleton for streaming status
        """
        self._stream_state = stream_state

    def _get_default_backend_name(self) -> str:
        """Get the default backend name from config.

        Returns:
            The default backend name, or 'claude' if config is unavailable.
        """
        try:
            from config import get_config
            config = get_config()
            return config.default_backend
        except Exception:
            return "claude"

    def add_event_handler(
        self, handler: Callable[[str, dict, set[str] | None], None]
    ) -> None:
        """Register a handler for WebSocket events.

        The handler will be called with (event_name, data, target_clients) for each event.
        target_clients is a set of client_ids that should receive the event, or None
        to broadcast to all clients.
        """
        self._event_handlers.append(handler)

    def remove_event_handler(
        self, handler: Callable[[str, dict, set[str] | None], None]
    ) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def _emit_event(
        self, event_name: str, data: dict, target_clients: set[str] | None = None
    ) -> None:
        """Emit an event to registered handlers.

        Args:
            event_name: The name of the event (e.g., "turnCreated")
            data: The event payload data
            target_clients: Optional set of client_ids to target. If provided,
                handlers can use this to filter which clients receive the event.
                If None, the event is broadcast to all clients.
        """
        for handler in self._event_handlers:
            handler(event_name, data, target_clients)

    # --- Subscription Management (Layer-Based) ---

    @ws_expose
    async def subscribe_add(
        self,
        session_id: str,
        client_id: str,
        layers: list[str],
    ) -> SubscriptionResult:
        """Add subscription layers for a session.

        Layer-based subscriptions allow fine-grained control over which events
        a client receives. Layers are additive - call multiple times to add more.

        Layers:
        - "header": Turn lifecycle events (created, completed, deleted) + stream status
        - "body": Full turn content blocks on completion
        - "delta": Live streaming events (text deltas, tool input deltas)
        - "history": One-time historical turn loading (oldest-first, triggers historyChunk events)
        - "history_reverse": One-time historical turn loading (newest-first for fast time-to-bottom)
        - "history_lazy": Register for history but don't auto-load (use load_history_range on-demand)

        Args:
            session_id: The session to subscribe to
            client_id: Unique identifier for the client
            layers: List of layer names to add (e.g., ["header", "body"])

        Returns:
            SubscriptionResult with success/failure info
        """
        from core.debug_log import debug_log

        if not client_id:
            return SubscriptionResult(
                session_id=session_id,
                subscribed=False,
                error="client_id is required",
            )

        if not layers:
            return SubscriptionResult(
                session_id=session_id,
                subscribed=False,
                error="at least one layer is required",
            )

        # Convert string layer names to Layer enum
        try:
            layer_set = {Layer(layer_name) for layer_name in layers}
        except ValueError as e:
            return SubscriptionResult(
                session_id=session_id,
                subscribed=False,
                error=f"invalid layer: {e}",
            )

        # Add layers to subscription
        added = self._subscription_manager.add_layers(session_id, client_id, layer_set)

        debug_log.info(
            f"subscribe_add: session={session_id[:8]}, client={client_id}, "
            f"layers={[l.value for l in layer_set]}, added={added}",
            category=Category.API,
        )

        # Metadata for lazy loading response
        total_turns: int | None = None
        is_streaming: bool | None = None

        # Trigger history loading based on which history layer was added
        if added:
            if Layer.HISTORY in layer_set:
                debug_log.info(
                    f"subscribe_add: triggering history load (forward) for session={session_id[:8]}, client={client_id}",
                    category=Category.API,
                )
                await self._load_and_emit_history(session_id, client_id, reverse=False)
            elif Layer.HISTORY_REVERSE in layer_set:
                debug_log.info(
                    f"subscribe_add: triggering history load (reverse) for session={session_id[:8]}, client={client_id}",
                    category=Category.API,
                )
                await self._load_and_emit_history(session_id, client_id, reverse=True)
            elif Layer.HISTORY_LAZY in layer_set:
                debug_log.info(
                    f"subscribe_add: lazy history mode for session={session_id[:8]}, client={client_id}",
                    category=Category.API,
                )
                # For lazy loading, load the newest chunk first so user has something to see,
                # then they scroll up to load more
                if self._session_loader:
                    session = await self._session_loader(session_id)
                    if session:
                        total_turns = len(session.turns)
                        # Check if session is streaming
                        if self._stream_state:
                            stream = self._stream_state.get_session_stream(session_id)
                            is_streaming = stream is not None and stream.is_active
                        debug_log.info(
                            f"subscribe_add: lazy mode - loading newest chunk, total_turns={total_turns}, is_streaming={is_streaming}",
                            category=Category.API,
                        )
                        # Load the newest chunk to give user something to start with
                        if total_turns > 0:
                            chunk_size = self.HISTORY_CHUNK_SIZE
                            start_order = max(0, total_turns - chunk_size)
                            # Use load_history_range to emit the newest chunk
                            await self.load_history_range(session_id, client_id, start_order, total_turns)
        else:
            # Check if any history layer was requested but already existed
            history_layers = {Layer.HISTORY, Layer.HISTORY_REVERSE, Layer.HISTORY_LAZY}
            if layer_set & history_layers:
                debug_log.info(
                    f"subscribe_add: history layer already existed, skipping load for session={session_id[:8]}",
                    category=Category.API,
                )

        return SubscriptionResult(
            session_id=session_id,
            subscribed=True,
            total_turns=total_turns,
            is_streaming=is_streaming,
        )

    @ws_expose
    async def subscribe_remove(
        self,
        session_id: str,
        client_id: str,
        layers: list[str],
    ) -> SubscriptionResult:
        """Remove subscription layers for a session.

        Removes specific layers from a subscription. If all layers are removed,
        the subscription is deleted entirely.

        Args:
            session_id: The session to modify
            client_id: The client's identifier
            layers: List of layer names to remove

        Returns:
            SubscriptionResult with success/failure info
        """
        from core.debug_log import debug_log

        if not client_id:
            return SubscriptionResult(
                session_id=session_id,
                subscribed=False,
                error="client_id is required",
            )

        # Convert string layer names to Layer enum
        try:
            layer_set = {Layer(layer_name) for layer_name in layers}
        except ValueError as e:
            return SubscriptionResult(
                session_id=session_id,
                subscribed=False,
                error=f"invalid layer: {e}",
            )

        # Remove layers
        removed = self._subscription_manager.remove_layers(session_id, client_id, layer_set)

        # Check if any layers remain
        remaining = self._subscription_manager.get_client_layers(session_id, client_id)

        debug_log.info(
            f"subscribe_remove: session={session_id[:8]}, client={client_id}, "
            f"layers={[l.value for l in layer_set]}, removed={removed}, "
            f"remaining={[l.value for l in remaining]}",
            category=Category.API,
        )

        return SubscriptionResult(
            session_id=session_id,
            subscribed=bool(remaining),
        )

    @ws_expose
    async def load_history_range(
        self,
        session_id: str,
        client_id: str,
        start_order: int,
        end_order: int,
    ) -> SubscriptionResult:
        """Load a specific range of historical turns.

        Used with lazy loading to request history on-demand, typically
        when the user scrolls up to view older content.

        Args:
            session_id: The session to load from
            client_id: The requesting client
            start_order: First turn order to load (inclusive)
            end_order: Last turn order to load (exclusive)

        Returns:
            SubscriptionResult indicating success/failure
        """
        from core.debug_log import debug_log
        import uuid

        debug_log.info(
            f"load_history_range: session={session_id[:8]}, client={client_id}, "
            f"range=[{start_order}, {end_order})",
            category=Category.API,
        )

        if not self._session_loader:
            return SubscriptionResult(
                session_id=session_id,
                subscribed=False,
                error="session_loader not configured",
            )

        # Load session
        session = await self._session_loader(session_id)
        if not session:
            return SubscriptionResult(
                session_id=session_id,
                subscribed=False,
                error="session not found",
            )

        # Extract the requested range
        turns = session.turns
        total_turns = len(turns)

        # Clamp range to valid bounds
        start = max(0, start_order)
        end = min(total_turns, end_order)

        if start >= end:
            # Empty range
            return SubscriptionResult(
                session_id=session_id,
                subscribed=True,
            )

        # Build snapshots for the range
        turn_snapshots = []
        for idx in range(start, end):
            turn = turns[idx]
            raw_mode = getattr(turn, 'context_mode', 'copy')
            if hasattr(raw_mode, 'value'):
                context_mode_str = raw_mode.value
            else:
                context_mode_str = str(raw_mode).lower()

            turn_tokens = getattr(turn, 'tokens', 0)
            snapshot = TurnSnapshot(
                turn_id=turn.id,
                order=idx,
                role=turn.role,
                streaming=False,
                viewed=getattr(turn, 'viewed', False),
                tokens=turn_tokens,
                context_mode=context_mode_str,
                content_block=turn.content_block if hasattr(turn, 'content_block') else None,
                exchange_id=getattr(turn, 'exchange_id', None),
                timestamp=getattr(turn, 'timestamp', None),
                parallel_group_id=getattr(turn, 'parallel_group_id', None),
                is_steering=getattr(turn, 'is_steering', False),
                responds_to_steering=getattr(turn, 'responds_to_steering', False),
            )
            turn_snapshots.append(snapshot)

        # Emit as a single chunk
        chunk_id = str(uuid.uuid4())
        event_data = SessionHistoryChunkEvent(
            session_id=session_id,
            chunk_id=chunk_id,
            turns=turn_snapshots,
            chunk_index=0,  # Single chunk
            total_chunks=1,
            watermark=end - 1,
            reversed=False,  # Range loads are always in order
        )
        self._emit_event(
            "sessionDataHistoryChunk",
            asdict(event_data),
            target_clients={client_id},
        )

        debug_log.info(
            f"load_history_range: emitted {len(turn_snapshots)} turns for range [{start}, {end})",
            category=Category.API,
        )

        return SubscriptionResult(
            session_id=session_id,
            subscribed=True,
        )

    async def _load_and_emit_history(
        self,
        session_id: str,
        client_id: str,
        reverse: bool = False,
    ) -> None:
        """Load session history and emit chunks to a specific client.

        Called when HISTORY layer is added to a subscription.
        Emits historyChunk events followed by historyComplete.

        Args:
            session_id: The session to load history for
            client_id: The client to send history to
            reverse: If True, send newest chunks first (for faster time-to-bottom).
                     If False (default), send oldest chunks first (chronological).
        """
        from core.debug_log import debug_log
        import uuid

        debug_log.info(
            f"_load_and_emit_history: STARTING for session={session_id[:8]}, client={client_id}, reverse={reverse}",
            category=Category.API,
        )

        if not self._session_loader:
            debug_log.warning(
                f"_load_and_emit_history: no session_loader configured",
                category=Category.API,
            )
            return

        # Load session
        session = await self._session_loader(session_id)
        if not session:
            debug_log.warning(
                f"_load_and_emit_history: session {session_id[:8]} not found",
                category=Category.API,
            )
            return

        # Convert turns to snapshots and chunk them
        turns = session.turns
        total_turns = len(turns)
        chunk_size = self.HISTORY_CHUNK_SIZE
        total_chunks = (total_turns + chunk_size - 1) // chunk_size if total_turns > 0 else 1

        # Build all chunks
        all_chunks: list[tuple[list[TurnSnapshot], int]] = []  # (snapshots, watermark)

        for chunk_idx in range(total_chunks):
            start = chunk_idx * chunk_size
            end = min(start + chunk_size, total_turns)
            chunk_turns = turns[start:end]

            # Convert to TurnSnapshot format
            turn_snapshots = []
            for idx, turn in enumerate(chunk_turns, start=start):
                # Get context_mode as string (handle both enum and string values)
                raw_mode = getattr(turn, 'context_mode', 'copy')
                if hasattr(raw_mode, 'value'):
                    # It's an enum - get string value
                    context_mode_str = raw_mode.value
                else:
                    # It's already a string
                    context_mode_str = str(raw_mode).lower()

                turn_tokens = getattr(turn, 'tokens', 0)
                snapshot = TurnSnapshot(
                    turn_id=turn.id,
                    order=idx,
                    role=turn.role,
                    streaming=False,
                    viewed=getattr(turn, 'viewed', False),
                    tokens=turn_tokens,
                    context_mode=context_mode_str,
                    content_block=turn.content_block if hasattr(turn, 'content_block') else None,
                    exchange_id=getattr(turn, 'exchange_id', None),
                    timestamp=getattr(turn, 'timestamp', None),
                    parallel_group_id=getattr(turn, 'parallel_group_id', None),
                    is_steering=getattr(turn, 'is_steering', False),
                responds_to_steering=getattr(turn, 'responds_to_steering', False),
                )
                turn_snapshots.append(snapshot)

            all_chunks.append((turn_snapshots, end - 1 if chunk_turns else 0))

        # Determine emit order based on reverse flag
        if reverse:
            # Emit newest chunks first - clients can show bottom immediately
            emit_order = list(reversed(range(total_chunks)))
        else:
            # Emit oldest chunks first (chronological order)
            emit_order = list(range(total_chunks))

        for emit_idx, chunk_idx_original in enumerate(emit_order):
            turn_snapshots, watermark = all_chunks[chunk_idx_original]
            chunk_id = str(uuid.uuid4())

            debug_log.info(
                f"_load_and_emit_history: emitting chunk {emit_idx}/{total_chunks} "
                f"(original {chunk_idx_original}) with {len(turn_snapshots)} turns to client={client_id}",
                category=Category.API,
            )
            event_data = SessionHistoryChunkEvent(
                session_id=session_id,
                chunk_id=chunk_id,
                turns=turn_snapshots,
                chunk_index=emit_idx,  # Emit order (0 = first sent)
                total_chunks=total_chunks,
                watermark=watermark,
                reversed=reverse,  # Signal which order chunks arrive
            )
            self._emit_event(
                "sessionDataHistoryChunk",
                asdict(event_data),
                target_clients={client_id},
            )

        # Emit history complete
        complete_event = SessionHistoryCompleteEvent(
            session_id=session_id,
            total_turns=total_turns,
            final_watermark=total_turns - 1 if total_turns > 0 else 0,
        )
        self._emit_event(
            "sessionDataHistoryComplete",
            asdict(complete_event),
            target_clients={client_id},
        )

        debug_log.info(
            f"_load_and_emit_history: session={session_id[:8]}, client={client_id}, "
            f"turns={total_turns}, chunks={total_chunks}, reverse={reverse}",
            category=Category.API,
        )

    def _get_turn_content_text(self, turn) -> str:
        """Extract text content from a turn for history loading."""
        if hasattr(turn, 'content_block') and turn.content_block:
            block = turn.content_block
            if hasattr(block, 'text'):
                return block.text
            elif hasattr(block, 'content'):
                return str(block.content)
        return ""

    @ws_expose
    async def get_session_snapshot(self, session_id: str) -> SessionSnapshot | None:
        """Get a complete snapshot of the session's current state.

        Use this when subscribing to get the initial state before
        receiving incremental deltas.

        Args:
            session_id: The session to snapshot

        Returns:
            SessionSnapshot with full turn history, or None if session not found
        """
        from core.debug_log import debug_log

        if not self._session_loader:
            debug_log.info("get_session_snapshot: no session_loader", category=Category.SESSION)
            return None

        # Load session from storage
        session = await self._session_loader(session_id)
        if not session:
            debug_log.info(
                f"get_session_snapshot: session {session_id[:8]} not found",
                category=Category.SESSION,
            )
            return None

        debug_log.info(
            f"get_session_snapshot: session_id={session_id[:8]}, turns={len(session.turns)}",
            category=Category.SESSION,
        )

        # Convert Session turns to TurnSnapshot format
        turn_snapshots: list[TurnSnapshot] = []
        streaming_turn_ids: list[str] = []

        for idx, turn in enumerate(session.turns):
            # Use content_block if available, otherwise create TextBlock from content
            content_block = turn.content_block
            if content_block is None:
                content = getattr(turn, 'content', '') or ""
                content_block = TextBlock(type="text", text=content)

            turn_tokens = getattr(turn, 'tokens', 0)

            turn_snapshot = TurnSnapshot(
                turn_id=turn.id if hasattr(turn, 'id') else "",
                role=turn.role,
                streaming=False,  # Not streaming when loading from storage
                viewed=True,
                tokens=turn_tokens,
                context_mode="copy",  # Default to copy
                content_block=content_block,
                exchange_id=getattr(turn, 'exchange_id', None),
                timestamp=getattr(turn, 'timestamp', None),
                parallel_group_id=getattr(turn, 'parallel_group_id', None),
                is_steering=getattr(turn, 'is_steering', False),
                responds_to_steering=getattr(turn, 'responds_to_steering', False),
            )
            turn_snapshots.append(turn_snapshot)

        return SessionSnapshot(
            session_id=session_id,
            title=session.title or "",
            model=session.model or "",
            is_streaming=False,  # Will be updated by streaming events
            turns=turn_snapshots,
            streaming_turn_ids=[],
        )

    async def _get_session_metadata_snapshot(self, session_id: str) -> SessionSnapshot | None:
        """Get session metadata without loading turns.

        This is a fast operation that returns only the session's metadata,
        suitable for immediate response when subscribing. Historical turns
        are streamed separately via _stream_history_from_storage.

        Args:
            session_id: The session to get metadata for

        Returns:
            SessionSnapshot with empty turns list, or None if session not found
        """
        from core.debug_log import debug_log

        if not self._session_loader:
            debug_log.info("_get_session_metadata_snapshot: no session_loader", category=Category.SESSION)
            return None

        # Load session from storage
        session = await self._session_loader(session_id)
        if not session:
            debug_log.info(
                f"_get_session_metadata_snapshot: session {session_id[:8]} not found",
                category=Category.SESSION,
            )
            return None

        # Return metadata-only snapshot (empty turns, history streams separately)
        return SessionSnapshot(
            session_id=session_id,
            title=session.title or "",
            model=session.model or "",
            is_streaming=False,  # Will be updated by streaming events
            turns=[],  # Empty - history will stream via chunk events
            streaming_turn_ids=[],
        )

    async def _stream_history_from_storage(self, session_id: str) -> None:
        """Stream historical turns from LMDB storage in chunks.

        Loads turns directly from LMDB using load_turns_range() and emits
        sessionDataHistoryChunk events for each batch. When all chunks are
        sent, emits sessionDataHistoryComplete.

        This runs as a background task after subscribe_session returns,
        allowing clients to render progressively and receive streaming
        events concurrently.

        Args:
            session_id: The session to load history for
        """
        from core.debug_log import debug_log

        if not self._storage:
            debug_log.warning(
                f"_stream_history_from_storage: no storage configured for session {session_id[:8]}",
                category=Category.SESSION,
            )
            # Emit empty completion to signal no history available
            self.emit_history_complete(session_id, total_turns=0, final_watermark=-1)
            return

        try:
            # Get total turn count
            total_turns = await self._storage.get_turn_count(session_id)

            debug_log.info(
                f"_stream_history_from_storage: session={session_id[:8]}, total_turns={total_turns}",
                category=Category.SESSION,
            )

            if total_turns == 0:
                self.emit_history_complete(session_id, total_turns=0, final_watermark=-1)
                return

            # Calculate chunk count
            chunk_size = self.HISTORY_CHUNK_SIZE
            total_chunks = (total_turns + chunk_size - 1) // chunk_size  # ceil division

            final_watermark = -1
            turns_sent = 0

            # Load and emit chunks
            for chunk_index in range(total_chunks):
                offset = chunk_index * chunk_size
                limit = min(chunk_size, total_turns - offset)

                # Load chunk from LMDB
                turn_dicts = await self._storage.load_turns_range(session_id, offset, limit)

                # Convert to TurnSnapshot objects
                turn_snapshots = []
                chunk_watermark = -1

                for order, turn_dict in enumerate(turn_dicts, start=offset):
                    snapshot = self._turn_dict_to_snapshot(turn_dict, order)
                    turn_snapshots.append(snapshot)
                    chunk_watermark = max(chunk_watermark, order)

                # Update final watermark
                final_watermark = max(final_watermark, chunk_watermark)
                turns_sent += len(turn_snapshots)

                # Generate unique chunk ID for deduplication
                chunk_id = f"{session_id[:8]}-chunk-{chunk_index}"

                # Emit chunk event
                self.emit_history_chunk(
                    session_id=session_id,
                    chunk_id=chunk_id,
                    turns=turn_snapshots,
                    chunk_index=chunk_index,
                    total_chunks=total_chunks,
                    watermark=chunk_watermark,
                )

                # Yield to allow other tasks to run (especially streaming events)
                await asyncio.sleep(0)

            # Emit completion event
            self.emit_history_complete(
                session_id=session_id,
                total_turns=turns_sent,
                final_watermark=final_watermark,
            )

            debug_log.info(
                f"_stream_history_from_storage: completed session={session_id[:8]}, "
                f"turns_sent={turns_sent}, chunks={total_chunks}",
                category=Category.API,
            )

        except asyncio.CancelledError:
            debug_log.info(
                f"_stream_history_from_storage: cancelled for session {session_id[:8]}",
                category=Category.API,
            )
            raise
        except Exception as e:
            debug_log.error(
                f"_stream_history_from_storage: error for session {session_id[:8]}: {e}",
                category=Category.API,
            )
            # Emit completion with error state (0 turns signals incomplete load)
            self.emit_history_complete(session_id, total_turns=0, final_watermark=-1)

    def _turn_dict_to_snapshot(self, turn_dict: dict, order: int) -> TurnSnapshot:
        """Convert a turn dict from LMDB to a TurnSnapshot.

        Args:
            turn_dict: Turn data dict from storage (matches Rust TurnData schema)
            order: Turn position in the session (0-indexed)

        Returns:
            TurnSnapshot suitable for sending to clients
        """
        # Extract fields from the storage dict
        turn_id = turn_dict.get("id", "")
        role = turn_dict.get("role", "assistant")
        tokens = turn_dict.get("tokens", 0)
        context_mode = turn_dict.get("context_mode", "copy")
        exchange_id = turn_dict.get("exchange_id")

        # Handle content_block - it's stored as a JSON value
        content_block_data = turn_dict.get("content_block", {"type": "text", "text": ""})

        # Convert to the appropriate ContentBlock type
        content_block = self._deserialize_content_block(content_block_data)

        return TurnSnapshot(
            turn_id=turn_id,
            role=role,
            streaming=False,  # Historical turns are never streaming
            viewed=True,  # Historical turns are considered viewed
            tokens=tokens,
            context_mode=context_mode,
            content_block=content_block,
            order=order,  # Turn position for client-side sorting
            exchange_id=exchange_id,
            timestamp=turn_dict.get("timestamp"),
            parallel_group_id=turn_dict.get("parallel_group_id"),
            is_steering=turn_dict.get("is_steering", False),
            responds_to_steering=turn_dict.get("responds_to_steering", False),
        )

    def _deserialize_content_block(self, data: dict) -> ContentBlock:
        """Deserialize a content block dict to the appropriate type.

        Args:
            data: Dict with 'type' field indicating block type

        Returns:
            Appropriate ContentBlock instance
        """
        block_type = data.get("type", "text")

        if block_type == "text":
            return TextBlock(type="text", text=data.get("text", ""))
        elif block_type == "markdown":
            return MarkdownBlock(type="markdown", text=data.get("text", ""))
        elif block_type == "image":
            return ImageBlock(
                type="image",
                file_path=data.get("file_path", ""),
                media_type=data.get("media_type", ""),
                filename=data.get("filename", ""),
                width=data.get("width", 0),
                height=data.get("height", 0),
            )
        elif block_type == "tool_use":
            return ToolUseBlock(
                type="tool_use",
                id=data.get("id", ""),
                name=data.get("name", ""),
                input=data.get("input", {}),
            )
        elif block_type == "tool_result":
            return ToolResultBlock(
                type="tool_result",
                tool_use_id=data.get("tool_use_id", ""),
                content=data.get("content", ""),
                is_error=data.get("is_error", False),
            )
        elif block_type == "interruption":
            return InterruptionBlock(
                type="interruption",
                reason=data.get("reason", "user_cancelled"),
            )
        elif block_type == "error":
            return ErrorBlock(
                type="error",
                reason=data.get("reason", "stream_error"),
                partial_tool_name=data.get("partial_tool_name", ""),
                partial_tool_input=data.get("partial_tool_input", ""),
                details=data.get("details", ""),
                dump_file=data.get("dump_file", ""),
            )
        elif block_type == "link":
            return LinkBlock(
                type="link",
                link_id=data.get("link_id", ""),
                linked_session_id=data.get("linked_session_id", ""),
                summary=data.get("summary", ""),
                is_orphaned=data.get("is_orphaned", False),
            )
        elif block_type == "fork":
            return ForkBlock(
                type="fork",
                fork_id=data.get("fork_id", ""),
                child_session_id=data.get("child_session_id", ""),
                fork_name=data.get("fork_name", ""),
                prompt=data.get("prompt", ""),
                status=data.get("status", "active"),
            )
        elif block_type == "merge":
            return MergeBlock(
                type="merge",
                merge_id=data.get("merge_id", ""),
                child_session_id=data.get("child_session_id", ""),
                fork_name=data.get("fork_name", ""),
                message=data.get("message", ""),
                files_changed=data.get("files_changed", []),
                key_accomplishments=data.get("key_accomplishments", []),
                reason=data.get("reason", ""),
            )
        elif block_type == "merged_to":
            return MergedToBlock(
                type="merged_to",
                merge_id=data.get("merge_id", ""),
                parent_session_id=data.get("parent_session_id", ""),
                parent_name=data.get("parent_name", ""),
                parent_turn=data.get("parent_turn", 0),
                message=data.get("message", ""),
                files_changed=data.get("files_changed", []),
                key_accomplishments=data.get("key_accomplishments", []),
            )
        elif block_type == "forked_from":
            return ForkedFromBlock(
                type="forked_from",
                fork_id=data.get("fork_id", ""),
                parent_session_id=data.get("parent_session_id", ""),
                parent_name=data.get("parent_name", ""),
                parent_turn=data.get("parent_turn", 0),
                fork_name=data.get("fork_name", ""),
                prompt=data.get("prompt", ""),
            )
        elif block_type == "archive":
            return ArchiveBlock(
                type="archive",
                archive_id=data.get("archive_id", ""),
                file_path=data.get("file_path", ""),
                summary=data.get("summary", ""),
                turn_start=data.get("turn_start", 0),
                turn_end=data.get("turn_end", 0),
                message_count=data.get("message_count", 0),
                token_estimate=data.get("token_estimate", 0),
            )
        elif block_type == "slide":
            return SlideBlock(
                type="slide",
                slide_index=data.get("slide_index", 0),
                title=data.get("title", ""),
                content=data.get("content", ""),
                notes=data.get("notes", ""),
            )
        elif block_type == "review":
            return ReviewBlock(
                type="review",
                review_type=data.get("review_type", "thought"),
                content=data.get("content", ""),
                rating=data.get("rating"),
            )
        elif block_type == "fork_proposal":
            return ForkProposalBlock(
                type="fork_proposal",
                proposal_id=data.get("proposal_id", ""),
                name=data.get("name", ""),
                description=data.get("description", ""),
                context_plan=data.get("context_plan", []),
                initial_prompt=data.get("initial_prompt", ""),
                status=data.get("status", "pending"),
            )
        elif block_type == "merge_proposal":
            return MergeProposalBlock(
                type="merge_proposal",
                proposal_id=data.get("proposal_id", ""),
                summary=data.get("summary", ""),
                reason=data.get("reason", ""),
                files_changed=data.get("files_changed", []),
                key_accomplishments=data.get("key_accomplishments", []),
                status=data.get("status", "pending"),
            )
        # Watcher mode blocks
        elif block_type == "watch_start":
            return WatchStartBlock(
                type="watch_start",
                target_session_id=data.get("target_session_id", ""),
                target_session_name=data.get("target_session_name", ""),
            )
        elif block_type == "watch_stop":
            return WatchStopBlock(
                type="watch_stop",
                target_session_id=data.get("target_session_id", ""),
                reason=data.get("reason", ""),
            )
        elif block_type == "watch_summary":
            return WatchSummaryBlock(
                type="watch_summary",
                target_session_id=data.get("target_session_id", ""),
                target_session_name=data.get("target_session_name", ""),
                exchange_index=data.get("exchange_index", 0),
                summary=data.get("summary", ""),
            )
        else:
            # Unknown type - return as text block with JSON dump
            import json
            return TextBlock(type="text", text=json.dumps(data))

    @ws_expose
    async def get_subscribed_sessions(self, client_id: str) -> list[str]:
        """Get list of sessions a client is subscribed to.

        Args:
            client_id: The client's unique identifier

        Returns:
            List of session IDs the client is subscribed to
        """
        return list(self._subscription_manager.get_client_sessions(client_id).keys())

    @ws_expose
    async def get_session_subscriber_count(self, session_id: str) -> int:
        """Get the number of clients subscribed to a session.

        Args:
            session_id: The session to check

        Returns:
            Number of subscribed clients
        """
        return self._subscription_manager.get_subscriber_count(session_id)

    def get_session_subscribers(self, session_id: str) -> set[str]:
        """Get the set of client_ids subscribed to a session (any layer).

        This is an internal method for testing and debugging.

        Args:
            session_id: The session to check

        Returns:
            Set of client_ids subscribed to the session
        """
        # Return all clients subscribed to any layer of this session
        result: set[str] = set()
        for layer in Layer:
            result |= self._subscription_manager.get_clients_for_layer(session_id, layer)
        return result

    # --- Session Listing (Phase 8: replaces TreeStateService) ---

    async def _load_pinned_session_ids(self) -> set[str]:
        """Load pinned session IDs from UserPrefs storage."""
        from core.async_storage import get_user_prefs_storage

        try:
            storage = await get_user_prefs_storage()
            prefs = await storage.load_prefs()
            return set(prefs.pinned_session_ids)
        except Exception:
            return set()

    def session_to_info(
        self,
        session: Any,
        is_pinned: bool = False,
        is_streaming: bool = False,
    ) -> SessionInfo:
        """Convert a Session object to SessionInfo.

        This is a synchronous method for use by SessionManagerService when
        emitting session events. For async usage, use get_session() instead.

        Args:
            session: The Session object to convert
            is_pinned: Whether the session is pinned
            is_streaming: Whether the session is currently streaming

        Returns:
            SessionInfo with all fields populated
        """
        # Convert children list to ForkChild objects
        children = [
            ForkChild(
                session_id=child.get("session_id", ""),
                name=child.get("name", "") or child.get("prompt", "")[:50],
                status=child.get("status", "active"),
                fork_point=child.get("fork_point", -1),
            )
            for child in getattr(session, "children", [])
            if child.get("session_id")
        ]

        # Note: watch_targets and watched_by are NOT populated here.
        # They are lazily loaded from the watcher relationship table
        # in async contexts (e.g., get_session_fork_tree, get_session_watcher_info)

        return SessionInfo(
            id=session.id,
            title=session.title,
            created=session.created,
            last_modified=session.last_modified,
            model=session.model,
            message_count=len(session.turns),
            total_cost=session.total_cost,
            is_streaming=is_streaming,
            fork_name=session.fork_name,
            fork_status=session.fork_status,
            concluded=session.concluded,
            concluded_at=session.concluded_at,
            parent_id=session.parent_id,
            cached_context_tokens=session.ensure_context_tokens() if hasattr(session, 'ensure_context_tokens') else getattr(session, "cached_context_tokens", 0),
            context_window=getattr(session, "context_window", 150000),
            binding_indicator=getattr(session, "binding_indicator", ""),
            backend_name=getattr(session, "backend_name", "") or self._get_default_backend_name(),
            is_pinned=is_pinned,
            working_directory=session.working_directory or "",
            children=children,
            # watch_targets and watched_by left empty - load lazily via get_session_watcher_info()
        )

    async def _session_dict_to_info(
        self, data: dict, pinned_ids: set[str], streaming_ids: set[str]
    ) -> SessionInfo:
        """Convert a session metadata dict from LMDB to SessionInfo.

        Args:
            data: Session metadata dict from storage
            pinned_ids: Set of pinned session IDs
            streaming_ids: Set of currently streaming session IDs

        Returns:
            SessionInfo with all fields populated
        """
        from datetime import datetime, timezone

        # Convert Unix timestamps to ISO format
        created = data.get("created") or data.get("created_at", "")
        last_modified = data.get("last_modified") or data.get("updated_at", "")

        if isinstance(created, (int, float)) and created > 0:
            created = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
        if isinstance(last_modified, (int, float)) and last_modified > 0:
            last_modified = datetime.fromtimestamp(last_modified, tz=timezone.utc).isoformat()

        session_id = data.get("id", "")
        # Get working directory - handle both old format (single) and new format (list)
        working_dirs = data.get("working_directories", [])
        if not working_dirs:
            working_dirs = [data.get("working_directory", "")] if data.get("working_directory") else []
        working_dir = working_dirs[0] if working_dirs else ""

        # Convert children list to ForkChild objects
        children = [
            ForkChild(
                session_id=child.get("session_id", ""),
                name=child.get("name", "") or child.get("prompt", "")[:50] if child.get("prompt") else "",
                status=child.get("status", "active"),
                fork_point=child.get("fork_point", -1),
            )
            for child in data.get("children", [])
            if child.get("session_id")
        ]

        return SessionInfo(
            id=session_id,
            title=data.get("title") or data.get("name", ""),
            created=created if isinstance(created, str) else "",
            last_modified=last_modified if isinstance(last_modified, str) else "",
            model=data.get("model", ""),
            message_count=data.get("message_count") or data.get("turn_count", 0),
            total_cost=data.get("total_cost", 0.0),
            is_streaming=session_id in streaming_ids,
            fork_name=data.get("fork_name", ""),
            fork_status=data.get("fork_status", "active"),
            concluded=data.get("concluded", False),
            concluded_at=data.get("concluded_at"),
            parent_id=data.get("parent_id"),
            cached_context_tokens=data.get("cached_context_tokens", 0),
            context_window=data.get("context_window", 150000),
            binding_indicator=data.get("binding_indicator", ""),
            backend_name=data.get("backend_name", "") or self._get_default_backend_name(),
            is_pinned=session_id in pinned_ids,
            working_directory=working_dir,
            children=children,
        )

    @ws_expose
    async def get_all_sessions(self) -> list[SessionInfo]:
        """Get all sessions with metadata.

        Returns session list directly from LMDB storage, with pinning and
        streaming state merged in.

        Returns:
            List of all sessions sorted by last_modified (most recent first)
        """
        from core.debug_log import debug_log

        if not self._storage:
            debug_log.warning(
                "get_all_sessions called without storage configured",
                category=Category.API,
            )
            return []

        # Load data in parallel
        sessions_data = await self._storage.list_sessions()
        pinned_ids = await self._load_pinned_session_ids()

        # Get streaming session IDs from StreamState if available
        streaming_ids: set[str] = set()
        if self._stream_state:
            for stream in self._stream_state.get_active_streams():
                if stream.session_id:
                    streaming_ids.add(stream.session_id)

        result = []
        for data in sessions_data:
            info = await self._session_dict_to_info(data, pinned_ids, streaming_ids)
            result.append(info)

        return result

    @ws_expose
    async def get_session(self, session_id: str) -> SessionInfo | None:
        """Get session metadata by ID.

        Args:
            session_id: The session ID to look up

        Returns:
            SessionInfo if found, None otherwise
        """
        from core.debug_log import debug_log

        if not self._storage:
            debug_log.warning(
                "get_session called without storage configured",
                category=Category.API,
            )
            return None

        # Load the session
        session = await self._storage.load_session(session_id)
        if not session:
            return None

        pinned_ids = await self._load_pinned_session_ids()

        # Check streaming status from StreamState
        streaming_ids: set[str] = set()
        if self._stream_state:
            stream = self._stream_state.get_session_stream(session_id)
            if stream and stream.is_active:
                streaming_ids.add(session_id)

        # Convert Session to dict format expected by _session_dict_to_info
        data = {
            "id": session.id,
            "title": session.title,
            "created": session.created,
            "last_modified": session.last_modified,
            "model": session.model,
            "message_count": len(session.turns),
            "total_cost": session.total_cost,
            "fork_name": session.fork_name,
            "fork_status": session.fork_status,
            "parent_id": session.parent_id,
            "cached_context_tokens": getattr(session, "cached_context_tokens", 0),
            "context_window": getattr(session, "context_window", 150000),
            "binding_indicator": getattr(session, "binding_indicator", ""),
            "backend_name": getattr(session, "backend_name", ""),
        }

        return await self._session_dict_to_info(data, pinned_ids, streaming_ids)

    @ws_expose
    async def get_session_parent_chain(self, session_id: str) -> list[SessionInfo]:
        """Get the parent chain for a session (ancestors from immediate parent to root).

        This traverses the fork tree upward, returning all ancestor sessions
        in order from immediate parent to the root session.

        Args:
            session_id: The session ID to get parents for

        Returns:
            List of SessionInfo for each parent, ordered from immediate parent to root.
            Empty list if the session has no parent (is a root session).
        """
        from core.debug_log import debug_log

        if not self._storage:
            debug_log.warning(
                "get_session_parent_chain called without storage configured",
                category=Category.API,
            )
            return []

        parents: list[SessionInfo] = []
        current_id = session_id
        visited: set[str] = {session_id}  # Prevent infinite loops

        # Load pinned and streaming state once
        pinned_ids = await self._load_pinned_session_ids()
        streaming_ids: set[str] = set()
        if self._stream_state:
            for stream in self._stream_state.get_active_streams():
                streaming_ids.add(stream.session_id)

        while True:
            # Load the current session to get its parent_id
            session = await self._storage.load_session(current_id)
            if not session:
                break

            parent_id = session.parent_id
            if not parent_id:
                break  # Reached root

            if parent_id in visited:
                debug_log.warning(
                    f"Cycle detected in parent chain at {parent_id}",
                    category=Category.API,
                )
                break

            visited.add(parent_id)

            # Load the parent session
            parent_session = await self._storage.load_session(parent_id)
            if not parent_session:
                debug_log.warning(
                    f"Parent session {parent_id[:8]} not found",
                    category=Category.API,
                )
                break

            # Convert to SessionInfo
            data = {
                "id": parent_session.id,
                "title": parent_session.title,
                "created": parent_session.created,
                "last_modified": parent_session.last_modified,
                "model": parent_session.model,
                "message_count": len(parent_session.turns),
                "total_cost": parent_session.total_cost,
                "fork_name": parent_session.fork_name,
                "fork_status": parent_session.fork_status,
                "parent_id": parent_session.parent_id,
                "cached_context_tokens": getattr(parent_session, "cached_context_tokens", 0),
                "context_window": getattr(parent_session, "context_window", 150000),
                "binding_indicator": getattr(parent_session, "binding_indicator", ""),
                "backend_name": getattr(parent_session, "backend_name", ""),
            }

            parent_info = await self._session_dict_to_info(data, pinned_ids, streaming_ids)
            parents.append(parent_info)

            current_id = parent_id

        return parents

    @ws_expose
    async def get_session_fork_tree(self, session_id: str) -> "ForkTreeNode | None":
        """Get the full fork tree containing this session.

        Finds the root ancestor and builds a tree of all related sessions,
        including siblings, cousins, etc.

        Args:
            session_id: Any session ID in the tree

        Returns:
            ForkTreeNode representing the root, with nested children.
            The target session is marked with is_current=True.
            Returns None if session not found.
        """
        from core.debug_log import debug_log

        if not self._storage:
            debug_log.warning(
                "get_session_fork_tree called without storage configured",
                category=Category.API,
            )
            return None

        # Step 1: Walk up to find the root session
        root_id = session_id
        visited: set[str] = {session_id}

        while True:
            session = await self._storage.load_session(root_id)
            if not session:
                debug_log.warning(
                    f"get_session_fork_tree: session {root_id[:8]} not found",
                    category=Category.API,
                )
                return None

            parent_id = session.parent_id
            if not parent_id:
                break  # Found root

            if parent_id in visited:
                debug_log.warning(
                    f"Cycle detected in fork tree at {parent_id}",
                    category=Category.API,
                )
                break

            visited.add(parent_id)
            root_id = parent_id

        # Step 2: Build tree recursively from root
        async def build_tree(sid: str, depth: int = 0) -> "ForkTreeNode | None":
            if depth > 20:  # Prevent infinite recursion
                return None

            sess = await self._storage.load_session(sid)
            if not sess:
                return None

            # Build children recursively
            child_nodes: list[ForkTreeNode] = []
            for child in sess.children:
                child_id = child.get("session_id")
                if child_id:
                    child_node = await build_tree(child_id, depth + 1)
                    if child_node:
                        child_nodes.append(child_node)

            # Get watcher relationships from storage (both directions)
            watch_targets: list[str] = []
            watched_by: list[str] = []
            if self._storage:
                try:
                    # Who is this session watching?
                    targets = await self._storage.get_targets_for_watcher(sess.id)
                    watch_targets = [t.target_session_id for t in targets]
                    # Who is watching this session?
                    watchers = await self._storage.get_watchers_for_target(sess.id)
                    watched_by = [w.watcher_session_id for w in watchers]
                except Exception:
                    pass  # Ignore errors, leave empty

            return ForkTreeNode(
                session_id=sess.id,
                name=sess.fork_name or sess.title or f"Session {sess.id[:8]}",
                status=sess.fork_status or "active",
                is_current=(sess.id == session_id),
                children=child_nodes,
                watch_targets=watch_targets,
                watched_by=watched_by,
            )

        return await build_tree(root_id)

    @ws_expose
    async def get_session_watcher_info(self, session_id: str) -> "SessionWatcherInfo":
        """Get watcher relationships for a session (lazy loading).

        Returns both:
        - watch_targets: sessions this session is watching
        - watched_by: sessions that are watching this session

        Args:
            session_id: The session ID to get watcher info for

        Returns:
            SessionWatcherInfo with watch_targets and watched_by lists
        """
        from core.debug_log import debug_log

        watch_targets: list[str] = []
        watched_by: list[str] = []

        if not self._storage:
            debug_log.warning(
                "get_session_watcher_info called without storage configured",
                category=Category.API,
            )
            return SessionWatcherInfo(
                session_id=session_id,
                watch_targets=watch_targets,
                watched_by=watched_by,
            )

        try:
            # Who is this session watching?
            targets = await self._storage.get_targets_for_watcher(session_id)
            watch_targets = [t.target_session_id for t in targets]
            # Who is watching this session?
            watchers = await self._storage.get_watchers_for_target(session_id)
            watched_by = [w.watcher_session_id for w in watchers]
        except Exception as e:
            debug_log.error(
                f"Failed to get watcher info for {session_id[:8]}: {e}",
                category=Category.API,
            )

        return SessionWatcherInfo(
            session_id=session_id,
            watch_targets=watch_targets,
            watched_by=watched_by,
        )

    # --- Turn Access ---
    # NOTE: get_turns() and get_turn() have been removed.
    # History is loaded via the subscription API (historyChunk events).
    # Turn updates are sent in the turnFinished event's contentBlock field.

    @ws_expose
    async def set_context_mode(
        self, session_id: str, turn_idx: int, mode: str
    ) -> None:
        """Set the context mode for a turn.

        Args:
            session_id: The session ID
            turn_idx: The turn index
            mode: The mode to set ("copy", "compress", or "drop")
        """
        from core.debug_log import debug_log
        from session import ContextMode

        if not self._session_loader:
            debug_log.warning(
                "set_context_mode called without session_loader configured",
                category=Category.API,
            )
            return

        session = await self._session_loader(session_id)
        if not session:
            debug_log.warning(
                f"set_context_mode: session {session_id[:8]} not found",
                category=Category.API,
            )
            return

        if turn_idx < 0 or turn_idx >= len(session.turns):
            debug_log.warning(
                f"set_context_mode: turn index {turn_idx} out of range",
                category=Category.API,
            )
            return

        # Parse the mode string to enum
        try:
            context_mode = ContextMode(mode.lower())
        except ValueError:
            debug_log.warning(
                f"set_context_mode: invalid mode '{mode}'",
                category=Category.API,
            )
            return

        # Update the turn's context mode
        session.turns[turn_idx].context_mode = context_mode
        await session.save()

        debug_log.info(
            f"set_context_mode: session {session_id[:8]} turn {turn_idx} -> {mode}",
            category=Category.API,
        )

        # Emit session updated event
        session_info = self.session_to_info(session)
        self.emit_session_updated(session_info)

    @ws_expose
    async def delete_turns(self, session_id: str, turn_indices: list[int]) -> int:
        """Delete multiple turns from a session.

        Args:
            session_id: The session ID
            turn_indices: List of turn indices to delete

        Returns:
            Number of turns actually deleted
        """
        from core.debug_log import debug_log

        if not self._session_loader:
            debug_log.warning(
                "delete_turns called without session_loader configured",
                category=Category.API,
            )
            return 0

        session = await self._session_loader(session_id)
        if not session:
            debug_log.warning(
                f"delete_turns: session {session_id[:8]} not found",
                category=Category.API,
            )
            return 0

        # Sort indices in reverse order to delete from end first
        # This prevents index shifting during deletion
        sorted_indices = sorted(set(turn_indices), reverse=True)

        # Collect turn IDs before deletion for event emission
        deleted_turn_ids: list[str] = []
        deleted_turn_indices: list[int] = []
        for idx in sorted_indices:
            if 0 <= idx < len(session.turns):
                deleted_turn_ids.append(session.turns[idx].id)
                deleted_turn_indices.append(idx)

        # Use session.delete_turns() to properly track deletions for incremental save
        deleted_count = session.delete_turns(turn_indices)

        if deleted_count > 0:
            await session.save()
            debug_log.info(
                f"delete_turns: session {session_id[:8]} deleted {deleted_count} turns",
                category=Category.API,
                details={"turn_indices": deleted_turn_indices, "turn_ids": deleted_turn_ids},
            )

            # Emit turns deleted event for incremental UI update
            self.emit_turns_deleted(session_id, deleted_turn_indices, deleted_turn_ids)

            # Emit session updated event
            session_info = self.session_to_info(session)
            self.emit_session_updated(session_info)

        return deleted_count

    # --- Pinning Operations ---

    @ws_expose
    async def pin_session(self, session_id: str) -> bool:
        """Pin a session to appear at top of lists.

        Args:
            session_id: The session to pin

        Returns:
            True if newly pinned, False if already pinned or session doesn't exist
        """
        from core.async_storage import get_user_prefs_storage
        from core.debug_log import debug_log

        try:
            storage = await get_user_prefs_storage()
            prefs = await storage.load_prefs()

            if session_id in prefs.pinned_session_ids:
                return False  # Already pinned

            prefs.pinned_session_ids.append(session_id)
            await storage.save_prefs(prefs)

            debug_log.info(
                f"Session pinned: {session_id[:8]}",
                category=Category.API,
            )

            # Emit events to all clients
            self._emit_event(
                "sessionDataSessionPinned",
                SessionPinnedEvent(session_id=session_id, is_pinned=True).__dict__,
            )
            self._emit_event(
                "sessionDataPinnedSessionsChanged",
                PinnedSessionsChangedEvent(pinned_session_ids=prefs.pinned_session_ids).__dict__,
            )

            return True
        except Exception as e:
            debug_log.error(f"Failed to pin session: {e}", category=Category.API)
            return False

    @ws_expose
    async def unpin_session(self, session_id: str) -> bool:
        """Unpin a session.

        Args:
            session_id: The session to unpin

        Returns:
            True if unpinned, False if wasn't pinned
        """
        from core.async_storage import get_user_prefs_storage
        from core.debug_log import debug_log

        try:
            storage = await get_user_prefs_storage()
            prefs = await storage.load_prefs()

            if session_id not in prefs.pinned_session_ids:
                return False  # Not pinned

            prefs.pinned_session_ids.remove(session_id)
            await storage.save_prefs(prefs)

            debug_log.info(
                f"Session unpinned: {session_id[:8]}",
                category=Category.API,
            )

            # Emit events to all clients
            self._emit_event(
                "sessionDataSessionPinned",
                SessionPinnedEvent(session_id=session_id, is_pinned=False).__dict__,
            )
            self._emit_event(
                "sessionDataPinnedSessionsChanged",
                PinnedSessionsChangedEvent(pinned_session_ids=prefs.pinned_session_ids).__dict__,
            )

            return True
        except Exception as e:
            debug_log.error(f"Failed to unpin session: {e}", category=Category.API)
            return False

    @ws_expose
    async def toggle_pin(self, session_id: str) -> bool:
        """Toggle pin state for a session.

        Args:
            session_id: The session to toggle

        Returns:
            True if now pinned, False if now unpinned
        """
        pinned_ids = await self._load_pinned_session_ids()
        if session_id in pinned_ids:
            await self.unpin_session(session_id)
            return False
        else:
            await self.pin_session(session_id)
            return True

    @ws_expose
    async def is_pinned(self, session_id: str) -> bool:
        """Check if a session is pinned.

        Args:
            session_id: The session to check

        Returns:
            True if session is pinned
        """
        pinned_ids = await self._load_pinned_session_ids()
        return session_id in pinned_ids

    @ws_expose
    async def is_session_streaming(self, session_id: str) -> bool:
        """Check if a session is currently streaming.

        This is useful for refreshing client state after reconnection
        or when the page becomes visible after being backgrounded.

        Args:
            session_id: The session to check

        Returns:
            True if the session has an active stream
        """
        if not self._stream_state:
            return False

        stream = self._stream_state.get_session_stream(session_id)
        return stream is not None and stream.is_active

    @ws_expose
    async def get_pinned_sessions(self) -> list[str]:
        """Get all pinned session IDs.

        Returns:
            List of pinned session IDs
        """
        pinned_ids = await self._load_pinned_session_ids()
        return list(pinned_ids)

    @ws_expose
    async def request_domain_state(self, session_id: str, domain_id: str) -> bool:
        """Request a domain to emit its current state.

        This triggers the domain to emit a state sync event for the specified session.
        The client should already be subscribed to receive domain events.

        Gets raw state from the domain and wraps it in a state_sync event.

        Args:
            session_id: The session ID
            domain_id: The domain ID (e.g., "chess")

        Returns:
            True if state was emitted, False if no state available
        """
        from plugins.registry import get_registry
        from plugins.events import _convert_keys_to_camel

        debug_log.info(
            f"request_domain_state: domain={domain_id}, session={session_id[:8]}",
            category=Category.API,
        )

        # Get the session (needed for the registry call)
        if self._manager is None:
            debug_log.warning("request_domain_state: no manager", category=Category.API)
            return False

        # Use _manager's internal session manager to get the session
        session = self._manager._manager.get_session(session_id)
        if session is None:
            debug_log.warning(f"request_domain_state: session not found: {session_id[:8]}", category=Category.API)
            return False

        # Get raw state from the registry
        registry = get_registry()

        # Auto-load the domain if not loaded
        if domain_id not in registry.loaded_domains:
            debug_log.info(f"request_domain_state: auto-loading domain {domain_id}", category=Category.API)
            try:
                registry.load_domain(domain_id)
            except Exception as e:
                debug_log.error(f"request_domain_state: failed to load domain {domain_id}: {e}", category=Category.API)
                return False  # Domain doesn't exist or failed to load

        state = await registry.get_state(domain_id, session)
        debug_log.info(
            f"request_domain_state: got state for {domain_id}, has_state={state is not None}",
            category=Category.API,
            details={"state_keys": list(state.keys()) if state else None},
        )

        if state is None:
            return False

        # Emit via session manager, wrapping state in a state_sync event
        if self._session_manager:
            event_type = f"{domain_id}_state_sync"
            camel_state = _convert_keys_to_camel(state)
            debug_log.info(
                f"request_domain_state: emitting {event_type}",
                category=Category.API,
                details={"data_keys": list(camel_state.keys()) if camel_state else None},
            )
            await self._session_manager.emit_domain_event(
                domain_id=domain_id,
                event_type=event_type,
                session_id=session_id,
                data=camel_state,
            )
            return True

        return False

    @ws_expose
    async def reload_domain(self, domain_id: str) -> dict:
        """Reload a domain plugin, picking up code changes.

        This is useful for development - when you modify domain code (like adding
        @ws_expose decorators), call this to reload without restarting the server.

        Args:
            domain_id: The domain ID (e.g., "grocery")

        Returns:
            {"success": True, "methods": [...]} on success, {"error": "..."} on failure
        """
        from plugins.registry import get_registry

        debug_log.info(
            f"reload_domain: {domain_id}",
            category=Category.API,
        )

        registry = get_registry()

        try:
            domain = registry.reload_domain(domain_id)
            # Return list of registered methods
            methods = [m.wire_name for m in type(domain)._ws_service_spec.methods] if hasattr(type(domain), '_ws_service_spec') else []
            return {"success": True, "domain": domain_id, "methods": methods}
        except Exception as e:
            debug_log.error(f"reload_domain failed: {domain_id}: {e}", category=Category.API)
            return {"error": str(e)}

    # --- Client Lifecycle ---

    def client_disconnected(self, client_id: str) -> None:
        """Handle client disconnection by cleaning up subscriptions.

        Called by the WebSocket server when a client disconnects.
        Cleans up both legacy and layer-based subscriptions.

        Args:
            client_id: The disconnected client's identifier
        """
        from core.debug_log import debug_log

        # Clean up all subscriptions for this client
        session_count = self._subscription_manager.unsubscribe_client(client_id)

        if session_count > 0:
            debug_log.info(
                f"client_disconnected: client={client_id}, sessions={session_count}",
                category=Category.API,
            )

    # --- Event Emission (called by session infrastructure) ---

    def emit_turn_created(
        self,
        session_id: str,
        turn_id: str,
        role: str,
        order: int,
        exchange_id: str | None = None,
        content_block_type: str = "text",
        parallel_group_id: str | None = None,
        is_steering: bool = False,
    ) -> None:
        """Emit a turn created event to subscribed clients.

        Called when a new turn begins in a session.
        Routes to clients with HEADER layer subscription.

        Args:
            session_id: The session where the turn was created
            turn_id: Stable UUID for the turn
            role: Turn role ("user", "assistant", "tool")
            order: Position in turn list (for display ordering)
            exchange_id: Exchange ID grouping related turns
            content_block_type: Type of content block
            parallel_group_id: Group ID for parallel tool calls
            is_steering: True if this user turn was injected mid-stream as steering
        """
        from core.debug_log import debug_log

        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.HEADER)

        debug_log.debug(
            f"emit_turn_created: session={session_id[:8]}, turn={turn_id[:8] if turn_id else 'none'}, "
            f"role={role}, order={order}, parallel_group={parallel_group_id[:8] if parallel_group_id else 'none'}, "
            f"is_steering={is_steering}, subscribers={len(subscribers)}",
            category=Category.API,
        )
        if not subscribers:
            return

        event_data = SessionTurnCreatedEvent(
            session_id=session_id,
            turn_id=turn_id,
            role=role,
            order=order,
            exchange_id=exchange_id,
            content_block_type=content_block_type,
            parallel_group_id=parallel_group_id,
            is_steering=is_steering,
        )
        self._emit_event("sessionDataTurnCreated", event_data.__dict__, subscribers)

    def emit_turn_delta(
        self,
        session_id: str,
        turn_id: str,
        delta: str,
        accumulated_length: int,
    ) -> None:
        """Emit a turn delta event to subscribed clients.

        Called when new content is streamed to a turn.
        Routes to clients with DELTA layer subscription.

        Args:
            session_id: The session containing the turn
            turn_id: Stable UUID for the turn
            delta: New text chunk
            accumulated_length: Total content length so far
        """
        from core.debug_log import debug_log

        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.DELTA)

        debug_log.debug(
            f"emit_turn_delta: session={session_id[:8]}, turn={turn_id[:8] if turn_id else 'none'}, "
            f"delta_len={len(delta)}, subscribers={len(subscribers)}",
            category=Category.API,
        )
        if not subscribers:
            return

        event_data = SessionTurnDeltaEvent(
            session_id=session_id,
            turn_id=turn_id,
            delta=delta,
            accumulated_length=accumulated_length,
        )
        self._emit_event("sessionDataTurnDelta", event_data.__dict__, subscribers)

    def emit_turn_finished(
        self,
        session_id: str,
        turn_id: str,
        final_content: str,
        tokens: int,
        order: int = 0,
        role: str = "assistant",
        content_block: ContentBlock | None = None,
        context_tokens: int = 0,
        output_tokens_total: int = 0,
    ) -> None:
        """Emit a turn finished event to subscribed clients.

        Called when a turn completes streaming.
        Routes to clients with HEADER layer (metadata) and BODY layer (full content).

        For backward compatibility, emits the full event to all subscribers.
        In the future, we may split into separate turnCompleted (HEADER) and
        turnBody (BODY) events.

        Args:
            session_id: The session containing the turn
            turn_id: Stable UUID for the turn
            final_content: Complete content of the turn (deprecated, use content_block)
            tokens: Token count for the turn
            order: Turn index for ordering
            role: Turn role ("user", "assistant", "tool")
            content_block: Full structured content block (optional, preferred over final_content)
            context_tokens: Cumulative context/input tokens sent to LLM
            output_tokens_total: Cumulative output tokens generated so far in this exchange
        """
        from core.debug_log import debug_log

        # turnFinished goes to both HEADER (for completion notification) and BODY (for content)
        header_subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.HEADER)
        body_subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.BODY)
        subscribers = header_subscribers | body_subscribers

        if not subscribers:
            return

        event_data = SessionTurnFinishedEvent(
            session_id=session_id,
            turn_id=turn_id,
            tokens=tokens,
            order=order,
            role=role,
            content_block=content_block,
            final_content=final_content,
            context_tokens=context_tokens,
            output_tokens_total=output_tokens_total,
        )
        # Convert to dict for JSON serialization
        event_dict = event_data.__dict__.copy()
        if content_block is not None and hasattr(content_block, '__dict__'):
            event_dict['content_block'] = asdict(content_block)

        block_info = f"block_type={content_block.type}" if content_block else f"final_content_len={len(final_content)}"
        debug_log.debug(
            f"emit_turn_finished: turn_id={turn_id}, {block_info}, "
            f"tokens={tokens}, subscribers={len(subscribers)} "
            f"(header={len(header_subscribers)}, body={len(body_subscribers)})",
            category=Category.API,
        )
        self._emit_event("sessionDataTurnFinished", event_dict, subscribers)

    def emit_history_chunk(
        self,
        session_id: str,
        chunk_id: str,
        turns: list[TurnSnapshot],
        chunk_index: int,
        total_chunks: int,
        watermark: int,
    ) -> None:
        """Emit a history chunk event to subscribed clients.

        Called during chunked history loading to send batches of historical turns.

        Args:
            session_id: The session being loaded
            chunk_id: Unique identifier for this chunk (for deduplication)
            turns: List of TurnSnapshot objects in this chunk
            chunk_index: 0-based index of this chunk
            total_chunks: Total number of chunks expected
            watermark: Highest turn order in this chunk
        """
        from core.debug_log import debug_log

        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.HISTORY)
        if not subscribers:
            return

        debug_log.debug(
            f"emit_history_chunk: session={session_id[:8]}, chunk={chunk_index}/{total_chunks}, "
            f"turns={len(turns)}, watermark={watermark}, subscribers={len(subscribers)}",
            category=Category.API,
        )

        # Convert TurnSnapshot list to dicts for serialization
        turn_dicts = []
        for turn in turns:
            turn_dict = turn.__dict__.copy()
            if turn.content_block is not None and hasattr(turn.content_block, '__dict__'):
                turn_dict['content_block'] = asdict(turn.content_block)
            turn_dicts.append(turn_dict)

        event_data = {
            "session_id": session_id,
            "chunk_id": chunk_id,
            "turns": turn_dicts,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "watermark": watermark,
        }
        self._emit_event("sessionDataHistoryChunk", event_data, subscribers)

    def emit_history_complete(
        self,
        session_id: str,
        total_turns: int,
        final_watermark: int,
    ) -> None:
        """Emit a history complete event to subscribed clients.

        Called when all historical chunks have been sent.

        Args:
            session_id: The session that finished loading
            total_turns: Total number of historical turns sent
            final_watermark: Highest turn order across all chunks
        """
        from core.debug_log import debug_log

        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.HISTORY)
        if not subscribers:
            return

        debug_log.info(
            f"emit_history_complete: session={session_id[:8]}, total_turns={total_turns}, "
            f"watermark={final_watermark}, subscribers={len(subscribers)}",
            category=Category.API,
        )

        event_data = SessionHistoryCompleteEvent(
            session_id=session_id,
            total_turns=total_turns,
            final_watermark=final_watermark,
        )
        self._emit_event("sessionDataHistoryComplete", event_data.__dict__, subscribers)

    # --- Session Lifecycle Emission (Phase 8) ---

    def emit_session_added(self, session: SessionInfo) -> None:
        """Emit a session added event to all clients.

        Called when a new session is created (fork, derive, new).

        Args:
            session: The session info for the new session
        """
        from core.debug_log import debug_log
        debug_log.info(
            f"emit_session_added: session={session.id[:8]}, title={session.title[:20]}",
            category=Category.API,
        )
        event_data = SessionAddedEvent(
            session_id=session.id,
            session=session,
        )
        # Broadcast to all clients (no target filtering)
        self._emit_event("sessionDataSessionAdded", asdict(event_data))

    def emit_session_updated(self, session: SessionInfo) -> None:
        """Emit a session updated event to all clients.

        Called when session metadata changes (title, tokens, streaming state).

        Args:
            session: The updated session info
        """
        event_data = SessionUpdatedEvent(
            session_id=session.id,
            session=session,
        )
        self._emit_event("sessionDataSessionUpdated", asdict(event_data))

    def emit_session_removed(self, session_id: str) -> None:
        """Emit a session removed event to all clients.

        Called when a session is deleted.

        Args:
            session_id: The ID of the removed session
        """
        from core.debug_log import debug_log
        debug_log.info(
            f"emit_session_removed: session={session_id[:8]}",
            category=Category.API,
        )
        event_data = SessionRemovedEvent(session_id=session_id)
        self._emit_event("sessionDataSessionRemoved", event_data.__dict__)

    def emit_turns_deleted(
        self,
        session_id: str,
        turn_indices: list[int],
        turn_ids: list[str],
    ) -> None:
        """Emit a turns deleted event to subscribed clients.

        Called when turns are deleted from a session (e.g., during archive).
        Clients should remove these turns from their local state.

        Args:
            session_id: The session ID
            turn_indices: Indices of the deleted turns
            turn_ids: IDs of the deleted turns
        """
        from core.debug_log import debug_log
        debug_log.info(
            f"emit_turns_deleted: session={session_id[:8]}, count={len(turn_ids)}",
            category=Category.API,
            details={"turn_indices": turn_indices},
        )
        event_data = SessionTurnsDeletedEvent(
            session_id=session_id,
            turn_indices=turn_indices,
            turn_ids=turn_ids,
        )
        self._emit_event("sessionDataTurnsDeleted", event_data.__dict__)

    def emit_turns_reordered(
        self,
        session_id: str,
        mappings: list[tuple[str, int]],
    ) -> None:
        """Emit a turns reordered event to subscribed clients.

        Called after archive/rehydrate when turn orders have been recomputed.
        Clients should update their local turn order fields.

        Args:
            session_id: The session ID
            mappings: List of (turn_id, new_order) tuples
        """
        from core.debug_log import debug_log
        debug_log.info(
            f"emit_turns_reordered: session={session_id[:8]}, count={len(mappings)}",
            category=Category.API,
        )
        # Convert tuples to TurnOrderMapping dataclass instances
        mapping_objects = [
            TurnOrderMapping(turn_id=turn_id, new_order=new_order)
            for turn_id, new_order in mappings
        ]
        event_data = SessionTurnsReorderedEvent(
            session_id=session_id,
            mappings=mapping_objects,
        )
        # Convert to dict with proper nested structure
        event_dict = {
            "session_id": event_data.session_id,
            "mappings": [{"turn_id": m.turn_id, "new_order": m.new_order} for m in event_data.mappings],
        }
        self._emit_event("sessionDataTurnsReordered", event_dict)

    # --- Events (for TypeScript generation) ---
    # Event names are prefixed with "sessionData" to avoid collisions with
    # TaskStateService and TreeStateService which also have turn events.

    @ws_event(name="sessionDataTurnCreated")
    async def on_session_data_turn_created(self) -> SessionTurnCreatedEvent:
        """Emitted when a new turn is created in a subscribed session.

        Clients should create UI elements for the new turn.
        """
        ...

    @ws_event(name="sessionDataTurnDelta")
    async def on_session_data_turn_delta(self) -> SessionTurnDeltaEvent:
        """Emitted when content is added to a streaming turn.

        Clients should append the delta to their accumulated content.
        Use accumulated_length to verify sync.
        """
        ...

    @ws_event(name="sessionDataTurnsDeleted")
    async def on_session_data_turns_deleted(self) -> SessionTurnsDeletedEvent:
        """Emitted when turns are deleted from a session (e.g., during archive).

        Clients should remove the deleted turns from their local state.
        """
        ...

    @ws_event(name="sessionDataTurnsReordered")
    async def on_session_data_turns_reordered(self) -> SessionTurnsReorderedEvent:
        """Emitted when turn orders are recomputed (e.g., after archive/rehydrate).

        Clients should update the order field for each turn in the mapping.
        This fixes visual gaps in turn numbering after archive operations.
        """
        ...

    @ws_event(name="sessionDataTurnFinished")
    async def on_session_data_turn_finished(self) -> SessionTurnFinishedEvent:
        """Emitted when a turn finishes streaming.

        Clients should finalize the turn display and update token counts.
        """
        ...

    @ws_event(name="sessionDataStreamStarted")
    async def on_session_data_stream_started(self) -> SessionStreamStartedEvent:
        """Emitted when streaming starts for a session."""
        ...

    @ws_event(name="sessionDataStreamDone")
    async def on_session_data_stream_done(self) -> SessionStreamDoneEvent:
        """Emitted when streaming completes successfully."""
        ...

    @ws_event(name="sessionDataStreamProgress")
    async def on_session_data_stream_progress(self) -> SessionStreamProgressEvent:
        """Emitted periodically during streaming with progress info.

        Throttled to avoid flooding - provides status bar updates.
        """
        ...

    @ws_event(name="sessionDataStreamError")
    async def on_session_data_stream_error(self) -> SessionStreamErrorEvent:
        """Emitted when streaming fails or is cancelled."""
        ...

    @ws_event(name="sessionDataToolUseStarted")
    async def on_session_data_tool_use_started(self) -> SessionToolUseStartedEvent:
        """Emitted when a tool begins execution."""
        ...

    @ws_event(name="sessionDataToolInputDelta")
    async def on_session_data_tool_input_delta(self) -> SessionToolInputDeltaEvent:
        """Emitted while tool input JSON streams in."""
        ...

    @ws_event(name="sessionDataToolUse")
    async def on_session_data_tool_use(self) -> SessionToolUseEvent:
        """Emitted when tool input is complete and execution begins."""
        ...

    @ws_event(name="sessionDataToolResult")
    async def on_session_data_tool_result(self) -> SessionToolResultEvent:
        """Emitted when a tool finishes execution."""
        ...

    @ws_event(name="sessionDataDomainEvent")
    async def on_session_data_domain_event(self) -> SessionDomainEvent:
        """Emitted when a domain plugin sends an event.

        This bridges domain plugins (chess, etc.) to the frontend.
        Contains domain_id, event_type, and event-specific data.
        """
        ...

    @ws_event(name="sessionDataHistoryChunk")
    async def on_session_data_history_chunk(self) -> SessionHistoryChunkEvent:
        """Emitted when a chunk of historical turns is ready.

        Sent incrementally during session subscription when the session
        has historical turns. Clients should merge chunks by turn_id
        and use the order field for sorting.
        """
        ...

    @ws_event(name="sessionDataHistoryComplete")
    async def on_session_data_history_complete(self) -> SessionHistoryCompleteEvent:
        """Emitted when all historical turns have been sent.

        After receiving this event, clients can be confident they have
        all historical data and can finalize the initial render.
        """
        ...

    # --- Session Lifecycle Events (Phase 8) ---

    @ws_event(name="sessionDataSessionAdded")
    async def on_session_data_session_added(self) -> SessionAddedEvent:
        """Emitted when a new session is created.

        Clients should add the session to their session list.
        """
        ...

    @ws_event(name="sessionDataSessionUpdated")
    async def on_session_data_session_updated(self) -> SessionUpdatedEvent:
        """Emitted when session metadata changes.

        Clients should update their session list display.
        """
        ...

    @ws_event(name="sessionDataSessionRemoved")
    async def on_session_data_session_removed(self) -> SessionRemovedEvent:
        """Emitted when a session is deleted.

        Clients should remove the session from their list.
        """
        ...

    @ws_event(name="sessionDataSessionPinned")
    async def on_session_data_session_pinned(self) -> SessionPinnedEvent:
        """Emitted when a session's pin state changes."""
        ...

    @ws_event(name="sessionDataPinnedSessionsChanged")
    async def on_session_data_pinned_sessions_changed(self) -> PinnedSessionsChangedEvent:
        """Emitted when the pinned sessions list changes."""
        ...

    # --- SessionEventObserver Implementation ---
    # These methods are called by SessionManagerService when it has events.
    # They forward events to subscribed WebSocket clients.

    async def on_turn_created(self, event: TurnCreatedEvent) -> None:
        """Handle turn created event from SessionManagerService.

        Forwards the event to all WebSocket clients subscribed to this session.
        """
        self.emit_turn_created(
            session_id=event.session_id,
            turn_id=event.turn_id,
            role=event.role,
            order=event.turn_index,
            exchange_id=event.exchange_id,
            content_block_type=event.content_block_type,
            parallel_group_id=event.parallel_group_id,
            is_steering=event.is_steering,
        )

    async def on_turn_delta(self, event: TurnDeltaEvent) -> None:
        """Handle turn delta event from SessionManagerService.

        Forwards the streaming content to subscribed WebSocket clients.
        """
        self.emit_turn_delta(
            session_id=event.session_id,
            turn_id=event.turn_id,
            delta=event.delta,
            accumulated_length=event.accumulated_length,
        )

    async def on_turn_finished(self, event: TurnFinishedEvent) -> None:
        """Handle turn finished event from SessionManagerService.

        Forwards the completion event to subscribed WebSocket clients.
        """
        self.emit_turn_finished(
            session_id=event.session_id,
            turn_id=event.turn_id,
            final_content=event.content,
            tokens=event.tokens,
            order=event.turn_index,
            role=event.role,
            content_block=event.content_block,
            context_tokens=event.context_tokens,
            output_tokens_total=event.output_tokens_total,
        )

    async def on_stream_started(self, event: StreamStartedEvent) -> None:
        """Handle stream started event from SessionManagerService.

        Emits streamStarted WebSocket event to HEADER layer subscribers.
        """
        session_id = event.session_id
        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.HEADER)
        if not subscribers:
            return

        event_data = {
            "session_id": session_id,
            "exchange_id": event.exchange_id,
        }
        self._emit_event("sessionDataStreamStarted", event_data, subscribers)

    async def on_stream_done(self, event: StreamDoneEvent) -> None:
        """Handle stream done event from SessionManagerService.

        Emits streamDone WebSocket event to HEADER layer subscribers.
        """
        session_id = event.session_id
        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.HEADER)
        if not subscribers:
            return

        event_data = {
            "session_id": session_id,
            "exchange_id": event.exchange_id,
            "input_tokens": event.input_tokens,
            "output_tokens": event.output_tokens,
        }
        self._emit_event("sessionDataStreamDone", event_data, subscribers)

    async def on_stream_progress(self, event: StreamProgressEvent) -> None:
        """Handle stream progress event from SessionManagerService.

        Emits streamProgress WebSocket event to DELTA layer subscribers.
        This event is throttled (not sent on every delta).
        """
        session_id = event.session_id
        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.DELTA)
        if not subscribers:
            return

        event_data = {
            "session_id": session_id,
            "exchange_id": event.exchange_id,
            "tokens_streamed": event.tokens_streamed,
            "current_token_rate": event.current_token_rate,
            "tool_name": event.tool_name,
            "tool_count": event.tool_count,
            "model": event.model,
            "context_window": event.context_window,
            "duration_seconds": event.duration_seconds,
        }
        self._emit_event("sessionDataStreamProgress", event_data, subscribers)

    async def on_stream_error(self, event: StreamErrorEvent) -> None:
        """Handle stream error event from SessionManagerService.

        Emits streamError WebSocket event to HEADER layer subscribers.
        """
        session_id = event.session_id
        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.HEADER)
        if not subscribers:
            return

        event_data = {
            "session_id": session_id,
            "exchange_id": event.exchange_id,
            "error": event.error,
            "error_type": event.error_type,  # "error", "rate_limit", "cancelled"
        }
        self._emit_event("sessionDataStreamError", event_data, subscribers)

    async def on_tool_use_started(self, event: ToolUseStartedEvent) -> None:
        """Handle tool use started event from SessionManagerService.

        Emits toolUseStarted WebSocket event to DELTA layer subscribers.
        """
        session_id = event.session_id
        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.DELTA)
        if not subscribers:
            return

        event_data = {
            "session_id": session_id,
            "exchange_id": event.exchange_id,
            "turn_index": event.turn_index,
            "tool_use_id": event.tool_use_id,
            "tool_name": event.tool_name,
            "tool_index": event.tool_index,
        }
        self._emit_event("sessionDataToolUseStarted", event_data, subscribers)

    async def on_tool_input_delta(self, event: ToolInputDeltaEvent) -> None:
        """Handle tool input delta event from SessionManagerService.

        Emits toolInputDelta WebSocket event to DELTA layer subscribers.
        """
        session_id = event.session_id
        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.DELTA)
        if not subscribers:
            return

        event_data = {
            "session_id": session_id,
            "exchange_id": event.exchange_id,
            "tool_use_id": event.tool_use_id,
            "partial_json": event.partial_json,
        }
        self._emit_event("sessionDataToolInputDelta", event_data, subscribers)

    async def on_tool_use(self, event: ToolUseEvent) -> None:
        """Handle tool use event from SessionManagerService.

        Emits toolUse WebSocket event (tool input complete) to DELTA layer subscribers.
        """
        session_id = event.session_id
        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.DELTA)
        if not subscribers:
            return

        event_data = {
            "session_id": session_id,
            "exchange_id": event.exchange_id,
            "turn_index": event.turn_index,
            "tool_use_id": event.tool_use_id,
            "tool_name": event.tool_name,
            "tool_input": event.tool_input,
            "tool_index": event.tool_index,
        }

        # DEBUG: Log Edit tool inputs to help diagnose missing diff data
        if event.tool_name == "Edit":
            from core.debug_log import debug_log
            tool_input = event.tool_input or {}
            debug_log.info(
                f"[SessionDataService] Edit tool_input: file_path={tool_input.get('file_path', 'N/A')}, "
                f"old_string_len={len(tool_input.get('old_string', ''))}, "
                f"new_string_len={len(tool_input.get('new_string', ''))}, "
                f"keys={list(tool_input.keys())}",
                category=Category.API,
            )

        self._emit_event("sessionDataToolUse", event_data, subscribers)

    async def on_tool_result(self, event: ToolResultEvent) -> None:
        """Handle tool result event from SessionManagerService.

        Emits toolResult WebSocket event to DELTA layer subscribers.
        """
        session_id = event.session_id
        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.DELTA)
        if not subscribers:
            return

        event_data = {
            "session_id": session_id,
            "exchange_id": event.exchange_id,
            "turn_index": event.turn_index,
            "tool_use_id": event.tool_use_id,
            "tool_name": event.tool_name,
            "result": event.result if isinstance(event.result, str) else str(event.result),
            "is_error": event.is_error,
            "tool_index": event.tool_index,
        }
        self._emit_event("sessionDataToolResult", event_data, subscribers)

    async def on_domain_event(self, event: DomainEventWrapper) -> None:
        """Handle domain plugin event from SessionManagerService.

        Emits domainEvent WebSocket event to DELTA layer subscribers.
        This bridges domain plugins (like chess) to the frontend.
        """
        session_id = event.session_id
        subscribers = self._subscription_manager.get_clients_for_layer(session_id, Layer.DELTA)

        debug_log.info(
            f"on_domain_event: {event.domain_id}/{event.event_type} for session {session_id[:8]}, subscribers={len(subscribers)}",
            category=Category.API,
            details={"data_keys": list(event.data.keys()) if event.data else None},
        )

        if not subscribers:
            debug_log.warning(
                f"on_domain_event: no DELTA subscribers for session {session_id[:8]}",
                category=Category.API,
            )
            return

        event_data = {
            "session_id": session_id,
            "domain_id": event.domain_id,
            "event_type": event.event_type,
            "data": event.data,
        }
        self._emit_event("sessionDataDomainEvent", event_data, subscribers)
