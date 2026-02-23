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
)
from models import (
    TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock,
    InterruptionBlock, ErrorBlock, LinkBlock, ForkBlock, MergeBlock,
    MergedToBlock, ArchiveBlock, SlideBlock, ReviewBlock,
    ForkProposalBlock, MergeProposalBlock
)

if TYPE_CHECKING:
    from core.async_storage import AsyncStorage

# ContentBlock union for type annotations
ContentBlock = Union[
    TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock,
    InterruptionBlock, ErrorBlock, LinkBlock, ForkBlock, MergeBlock,
    MergedToBlock, ArchiveBlock, SlideBlock, ReviewBlock,
    ForkProposalBlock, MergeProposalBlock
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
    """Result of a subscribe/unsubscribe operation."""

    session_id: str
    subscribed: bool
    error: str | None = None


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
    tokens: int
    order: int = 0  # Turn index for ordering (critical for tool_result turns)
    role: str = "assistant"  # Turn role
    content_block: ContentBlock | None = None  # Full structured content block (optional for backwards compat)
    final_content: str = ""  # Deprecated: use content_block instead


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
class SessionHistoryChunkEvent:
    """Event payload for a chunk of historical turns.

    Sent incrementally when a client subscribes to a session with history.
    Chunks may arrive out of order; clients should merge by turn_id and
    sort by the order field in TurnSnapshot.

    The watermark indicates the highest turn order in this chunk, useful
    for tracking loading progress and detecting gaps.
    """

    session_id: str
    chunk_id: str  # Unique ID for this chunk (for deduplication)
    turns: list[TurnSnapshot]  # Historical turns in this chunk
    chunk_index: int  # 0-based index of this chunk
    total_chunks: int  # Total number of chunks expected
    watermark: int  # Highest turn order in this chunk


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
    parent_id: str | None = None
    cached_context_tokens: int = 0
    context_window: int = 200000
    binding_indicator: str = ""
    backend_name: str = ""
    is_pinned: bool = False


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
    ) -> None:
        """Initialize the session data service.

        Args:
            session_loader: Optional async callback to load sessions from storage.
                           Can also be set later via set_session_loader().
            storage: Optional AsyncStorage for direct LMDB access (used for chunked
                    history loading). Can also be set later via set_storage().
        """
        # Event handlers receive: (event_name, data, target_clients)
        # target_clients is a set of client_ids that should receive the event
        self._event_handlers: list[Callable[[str, dict, set[str] | None], None]] = []
        # Track subscriptions: client_id -> set of session_ids
        self._subscriptions: dict[str, set[str]] = {}
        # Track reverse mapping: session_id -> set of client_ids
        self._session_subscribers: dict[str, set[str]] = {}
        # Session loader callback for loading sessions from storage
        self._session_loader: SessionLoaderCallback | None = session_loader
        # AsyncStorage for direct LMDB access (chunked history loading)
        self._storage: "AsyncStorage | None" = storage
        # Track background history loading tasks: session_id -> task
        self._history_tasks: dict[str, asyncio.Task] = {}

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

    # --- Subscription Management ---

    @ws_expose
    async def subscribe_session(
        self, session_id: str, client_id: str = ""
    ) -> SubscribeSessionResult:
        """Subscribe to receive updates for a session.

        Returns session metadata immediately, then streams historical turns
        via sessionDataHistoryChunk events. This ensures:
        1. Subscription is registered FIRST (capturing concurrent streaming events)
        2. Client gets metadata without waiting for full history load
        3. History arrives progressively, enabling incremental rendering

        When subscribed, the client will receive:
        - historyChunk: Batches of historical turns during initial load
        - historyComplete: Signals all history has been sent
        - turnCreated: When a new turn starts (may interleave with history)
        - turnDelta: As content streams in
        - turnFinished: When a turn completes

        Args:
            session_id: The session to subscribe to
            client_id: Unique identifier for the subscribing client

        Returns:
            SubscribeSessionResult with metadata-only snapshot (no turns)
        """
        from core.debug_log import debug_log

        if not client_id:
            return SubscribeSessionResult(
                session_id=session_id,
                subscribed=False,
                error="client_id is required",
            )

        # PHASE 3 CHANGE: Register subscription FIRST to capture concurrent events
        # Add to client's subscriptions
        if client_id not in self._subscriptions:
            self._subscriptions[client_id] = set()
        self._subscriptions[client_id].add(session_id)

        # Add to session's subscribers
        if session_id not in self._session_subscribers:
            self._session_subscribers[session_id] = set()
        self._session_subscribers[session_id].add(client_id)

        debug_log.info(
            f"subscribe_session: session={session_id[:8]}, client={client_id}, "
            f"total_subscribers={len(self._session_subscribers.get(session_id, set()))}",
            category="websocket",
        )

        # Get metadata-only snapshot (no turns) - fast operation
        snapshot = await self._get_session_metadata_snapshot(session_id)

        debug_log.info(
            f"subscribe_session: snapshot_exists={snapshot is not None}, storage_exists={self._storage is not None}",
            category="fork",
            details={"session_id": session_id[:8]},
        )

        # PHASE 3 CHANGE: Spawn background task to stream history from LMDB
        # Only if session exists and we have storage configured
        if snapshot is not None and self._storage is not None:
            # Cancel any existing history task for this session (e.g., from reconnect)
            if session_id in self._history_tasks:
                self._history_tasks[session_id].cancel()

            # Start streaming history in background with a small delay
            # This ensures the client has time to set up event handlers before
            # history chunks arrive. Without this delay, events can be lost if
            # they're emitted before the client's handlers are registered.
            async def delayed_stream_history():
                await asyncio.sleep(0.05)  # 50ms delay for handler setup
                await self._stream_history_from_storage(session_id)

            task = asyncio.create_task(
                delayed_stream_history(),
                name=f"history-{session_id[:8]}",
            )
            self._history_tasks[session_id] = task

            # Clean up task reference when done
            def cleanup_task(t: asyncio.Task) -> None:
                if session_id in self._history_tasks and self._history_tasks[session_id] is t:
                    del self._history_tasks[session_id]
            task.add_done_callback(cleanup_task)

        # Subscription succeeds even if session not found (client may be waiting for it)
        # snapshot will be None in that case
        return SubscribeSessionResult(
            session_id=session_id,
            subscribed=True,
            snapshot=snapshot,  # Metadata only (no turns), or None if session not found
        )

    @ws_expose
    async def unsubscribe_session(
        self, session_id: str, client_id: str = ""
    ) -> SubscriptionResult:
        """Unsubscribe from session updates.

        Args:
            session_id: The session to unsubscribe from
            client_id: The client's unique identifier

        Returns:
            SubscriptionResult indicating the unsubscription
        """
        if not client_id:
            return SubscriptionResult(
                session_id=session_id,
                subscribed=False,
                error="client_id is required",
            )

        # Remove from client's subscriptions
        if client_id in self._subscriptions:
            self._subscriptions[client_id].discard(session_id)
            if not self._subscriptions[client_id]:
                del self._subscriptions[client_id]

        # Remove from session's subscribers
        if session_id in self._session_subscribers:
            self._session_subscribers[session_id].discard(client_id)
            if not self._session_subscribers[session_id]:
                del self._session_subscribers[session_id]

        return SubscriptionResult(
            session_id=session_id,
            subscribed=False,
        )

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
            debug_log.info("get_session_snapshot: no session_loader", category="fork")
            return None

        # Load session from storage
        session = await self._session_loader(session_id)
        if not session:
            debug_log.info(
                f"get_session_snapshot: session {session_id[:8]} not found",
                category="fork",
            )
            return None

        debug_log.info(
            f"get_session_snapshot: session_id={session_id[:8]}, turns={len(session.turns)}",
            category="fork",
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

            turn_snapshot = TurnSnapshot(
                turn_id=turn.id if hasattr(turn, 'id') else "",
                role=turn.role,
                streaming=False,  # Not streaming when loading from storage
                viewed=True,
                tokens=getattr(turn, 'tokens', 0),
                context_mode="copy",  # Default to copy
                content_block=content_block,
                exchange_id=getattr(turn, 'exchange_id', None),
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
            debug_log.info("_get_session_metadata_snapshot: no session_loader", category="fork")
            return None

        # Load session from storage
        session = await self._session_loader(session_id)
        if not session:
            debug_log.info(
                f"_get_session_metadata_snapshot: session {session_id[:8]} not found",
                category="fork",
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
                category="fork",
            )
            # Emit empty completion to signal no history available
            self.emit_history_complete(session_id, total_turns=0, final_watermark=-1)
            return

        try:
            # Get total turn count
            total_turns = await self._storage.get_turn_count(session_id)

            debug_log.info(
                f"_stream_history_from_storage: session={session_id[:8]}, total_turns={total_turns}",
                category="fork",
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
                category="websocket",
            )

        except asyncio.CancelledError:
            debug_log.info(
                f"_stream_history_from_storage: cancelled for session {session_id[:8]}",
                category="websocket",
            )
            raise
        except Exception as e:
            debug_log.error(
                f"_stream_history_from_storage: error for session {session_id[:8]}: {e}",
                category="websocket",
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
        elif block_type == "archive":
            return ArchiveBlock(
                type="archive",
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
        return list(self._subscriptions.get(client_id, set()))

    @ws_expose
    async def get_session_subscriber_count(self, session_id: str) -> int:
        """Get the number of clients subscribed to a session.

        Args:
            session_id: The session to check

        Returns:
            Number of subscribed clients
        """
        return len(self._session_subscribers.get(session_id, set()))

    def get_session_subscribers(self, session_id: str) -> set[str]:
        """Get the set of client_ids subscribed to a session.

        This is an internal method for testing and debugging.

        Args:
            session_id: The session to check

        Returns:
            Set of client_ids subscribed to the session
        """
        return self._session_subscribers.get(session_id, set()).copy()

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
            parent_id=session.parent_id,
            cached_context_tokens=getattr(session, "cached_context_tokens", 0),
            context_window=getattr(session, "context_window", 200000),
            binding_indicator=getattr(session, "binding_indicator", ""),
            backend_name=getattr(session, "backend_name", ""),
            is_pinned=is_pinned,
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
            parent_id=data.get("parent_id"),
            cached_context_tokens=data.get("cached_context_tokens", 0),
            context_window=data.get("context_window", 200000),
            binding_indicator=data.get("binding_indicator", ""),
            backend_name=data.get("backend_name", ""),
            is_pinned=session_id in pinned_ids,
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
                category="websocket",
            )
            return []

        # Load data in parallel
        sessions_data = await self._storage.list_sessions()
        pinned_ids = await self._load_pinned_session_ids()

        # Get streaming session IDs from SessionManagerService if available
        streaming_ids: set[str] = set()
        # Note: We'll need to wire this up from SessionManagerService

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
                category="websocket",
            )
            return None

        # Load the session
        session = await self._storage.load_session(session_id)
        if not session:
            return None

        pinned_ids = await self._load_pinned_session_ids()
        streaming_ids: set[str] = set()  # TODO: wire from SessionManagerService

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
            "context_window": getattr(session, "context_window", 200000),
            "binding_indicator": getattr(session, "binding_indicator", ""),
            "backend_name": getattr(session, "backend_name", ""),
        }

        return await self._session_dict_to_info(data, pinned_ids, streaming_ids)

    # --- Turn Access (backwards compatibility with TreeStateService) ---

    @ws_expose
    async def get_turns(self, session_id: str) -> list[TurnInfo]:
        """Get all turns for a session.

        DEPRECATED: This method exists for backwards compatibility with the
        existing frontend. New code should use subscribe_session() and
        receive turns via the historyChunk event.

        Args:
            session_id: The session ID to get turns for

        Returns:
            List of TurnInfo objects for all turns in the session
        """
        import json
        from core.debug_log import debug_log

        if not self._session_loader:
            debug_log.warning(
                "get_turns called without session_loader configured",
                category="websocket",
            )
            return []

        session = await self._session_loader(session_id)
        if not session:
            debug_log.warning(
                f"get_turns: session {session_id[:8]} not found",
                category="websocket",
            )
            return []

        result: list[TurnInfo] = []
        for idx, turn in enumerate(session.turns):
            # Get content from content_block or fallback to content attribute
            content_block = turn.content_block
            content = ""
            content_block_type = "text"
            tool_use: ToolUseInfo | None = None
            tool_result: ToolResultInfo | None = None
            images: list[TurnImageInfo] = []

            if content_block is not None:
                content_block_type = getattr(content_block, "type", "text")

                if isinstance(content_block, TextBlock):
                    content = content_block.text
                elif isinstance(content_block, ToolUseBlock):
                    content = json.dumps(content_block.input) if content_block.input else ""
                    tool_use = ToolUseInfo(
                        tool_use_id=content_block.id,
                        name=content_block.name,
                        input_json=content,
                    )
                elif isinstance(content_block, ToolResultBlock):
                    content = str(content_block.content) if content_block.content else ""
                    tool_result = ToolResultInfo(
                        tool_use_id=content_block.tool_use_id,
                        content=content,
                        is_error=getattr(content_block, "is_error", False),
                    )
                elif isinstance(content_block, ImageBlock):
                    content = "[Image]"
                    source = content_block.source
                    if source:
                        images.append(TurnImageInfo(
                            source_type=source.type,
                            media_type=source.media_type,
                            data=source.data if hasattr(source, 'data') else "",
                        ))
                else:
                    # For other block types, try to get a string representation
                    content = str(getattr(content_block, "text", "")) or str(content_block)
            else:
                # Fallback to content attribute if available
                content = getattr(turn, 'content', '') or ""

            # Get context_mode as string (could be ContextMode enum or string)
            raw_context_mode = getattr(turn, 'context_mode', None)
            if raw_context_mode is None:
                context_mode_str = "copy"
            elif hasattr(raw_context_mode, 'value'):
                # It's an enum
                context_mode_str = raw_context_mode.value
            else:
                context_mode_str = str(raw_context_mode)

            turn_info = TurnInfo(
                idx=idx,
                role=turn.role,
                content=content,
                streaming=False,  # Historical turns are not streaming
                viewed=True,
                tokens=getattr(turn, 'tokens', 0),
                context_mode=context_mode_str,
                content_block_type=content_block_type,
                exchange_id=getattr(turn, 'exchange_id', None),
                images=images,
                tool_use=tool_use,
                tool_result=tool_result,
            )
            result.append(turn_info)

        debug_log.info(
            f"get_turns: session {session_id[:8]} returned {len(result)} turns",
            category="websocket",
        )
        return result

    @ws_expose
    async def get_turn(self, session_id: str, turn_idx: int) -> TurnInfo | None:
        """Get a specific turn from a session.

        Args:
            session_id: The session ID
            turn_idx: The turn index

        Returns:
            TurnInfo if found, None otherwise
        """
        turns = await self.get_turns(session_id)
        for turn in turns:
            if turn.idx == turn_idx:
                return turn
        return None

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
                category="websocket",
            )
            return

        session = await self._session_loader(session_id)
        if not session:
            debug_log.warning(
                f"set_context_mode: session {session_id[:8]} not found",
                category="websocket",
            )
            return

        if turn_idx < 0 or turn_idx >= len(session.turns):
            debug_log.warning(
                f"set_context_mode: turn index {turn_idx} out of range",
                category="websocket",
            )
            return

        # Parse the mode string to enum
        try:
            context_mode = ContextMode(mode.lower())
        except ValueError:
            debug_log.warning(
                f"set_context_mode: invalid mode '{mode}'",
                category="websocket",
            )
            return

        # Update the turn's context mode
        session.turns[turn_idx].context_mode = context_mode
        await session.save()

        debug_log.info(
            f"set_context_mode: session {session_id[:8]} turn {turn_idx} -> {mode}",
            category="websocket",
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
                category="websocket",
            )
            return 0

        session = await self._session_loader(session_id)
        if not session:
            debug_log.warning(
                f"delete_turns: session {session_id[:8]} not found",
                category="websocket",
            )
            return 0

        # Sort indices in reverse order to delete from end first
        # This prevents index shifting during deletion
        sorted_indices = sorted(turn_indices, reverse=True)

        deleted_count = 0
        for idx in sorted_indices:
            if 0 <= idx < len(session.turns):
                del session.turns[idx]
                deleted_count += 1

        if deleted_count > 0:
            await session.save()
            debug_log.info(
                f"delete_turns: session {session_id[:8]} deleted {deleted_count} turns",
                category="websocket",
            )

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
                category="websocket",
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
            debug_log.error(f"Failed to pin session: {e}", category="websocket")
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
                category="websocket",
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
            debug_log.error(f"Failed to unpin session: {e}", category="websocket")
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
    async def get_pinned_sessions(self) -> list[str]:
        """Get all pinned session IDs.

        Returns:
            List of pinned session IDs
        """
        pinned_ids = await self._load_pinned_session_ids()
        return list(pinned_ids)

    # --- Client Lifecycle ---

    def client_disconnected(self, client_id: str) -> None:
        """Handle client disconnection by cleaning up subscriptions.

        Called by the WebSocket server when a client disconnects.

        Args:
            client_id: The disconnected client's identifier
        """
        if client_id not in self._subscriptions:
            return

        # Remove client from all session subscriber lists
        for session_id in self._subscriptions[client_id]:
            if session_id in self._session_subscribers:
                self._session_subscribers[session_id].discard(client_id)
                if not self._session_subscribers[session_id]:
                    del self._session_subscribers[session_id]

        # Remove client's subscription record
        del self._subscriptions[client_id]

    # --- Event Emission (called by session infrastructure) ---

    def emit_turn_created(
        self,
        session_id: str,
        turn_id: str,
        role: str,
        order: int,
        exchange_id: str | None = None,
        content_block_type: str = "text",
    ) -> None:
        """Emit a turn created event to subscribed clients.

        Called when a new turn begins in a session.

        Args:
            session_id: The session where the turn was created
            turn_id: Stable UUID for the turn
            role: Turn role ("user", "assistant", "tool")
            order: Position in turn list (for display ordering)
            exchange_id: Exchange ID grouping related turns
            content_block_type: Type of content block
        """
        from core.debug_log import debug_log
        subscribers = self._session_subscribers.get(session_id)
        debug_log.debug(
            f"emit_turn_created: session={session_id[:8]}, turn={turn_id[:8] if turn_id else 'none'}, "
            f"role={role}, order={order}, subscribers={len(subscribers) if subscribers else 0}",
            category="websocket",
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

        Args:
            session_id: The session containing the turn
            turn_id: Stable UUID for the turn
            delta: New text chunk
            accumulated_length: Total content length so far
        """
        from core.debug_log import debug_log
        subscribers = self._session_subscribers.get(session_id)
        debug_log.debug(
            f"emit_turn_delta: session={session_id[:8]}, turn={turn_id[:8] if turn_id else 'none'}, "
            f"delta_len={len(delta)}, subscribers={len(subscribers) if subscribers else 0}",
            category="websocket",
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
    ) -> None:
        """Emit a turn finished event to subscribed clients.

        Called when a turn completes streaming.

        Args:
            session_id: The session containing the turn
            turn_id: Stable UUID for the turn
            final_content: Complete content of the turn (deprecated, use content_block)
            tokens: Token count for the turn
            order: Turn index for ordering
            role: Turn role ("user", "assistant", "tool")
            content_block: Full structured content block (optional, preferred over final_content)
        """
        subscribers = self._session_subscribers.get(session_id)
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
        )
        # Convert to dict for JSON serialization
        event_dict = event_data.__dict__.copy()
        if content_block is not None and hasattr(content_block, '__dict__'):
            event_dict['content_block'] = asdict(content_block)

        from core.debug_log import debug_log
        block_info = f"block_type={content_block.type}" if content_block else f"final_content_len={len(final_content)}"
        debug_log.debug(
            f"emit_turn_finished: turn_id={turn_id}, {block_info}, "
            f"tokens={tokens}, subscribers={len(subscribers)}",
            category="websocket",
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
        subscribers = self._session_subscribers.get(session_id)
        if not subscribers:
            return

        from core.debug_log import debug_log
        debug_log.debug(
            f"emit_history_chunk: session={session_id[:8]}, chunk={chunk_index}/{total_chunks}, "
            f"turns={len(turns)}, watermark={watermark}, subscribers={len(subscribers)}",
            category="websocket",
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
        subscribers = self._session_subscribers.get(session_id)
        if not subscribers:
            return

        from core.debug_log import debug_log
        debug_log.info(
            f"emit_history_complete: session={session_id[:8]}, total_turns={total_turns}, "
            f"watermark={final_watermark}, subscribers={len(subscribers)}",
            category="websocket",
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
            category="websocket",
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
            category="websocket",
        )
        event_data = SessionRemovedEvent(session_id=session_id)
        self._emit_event("sessionDataSessionRemoved", event_data.__dict__)

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
        )

    async def on_stream_started(self, event: StreamStartedEvent) -> None:
        """Handle stream started event from SessionManagerService.

        Emits streamStarted WebSocket event to subscribed clients.
        """
        session_id = event.session_id
        subscribers = self._session_subscribers.get(session_id, set())
        if not subscribers:
            return

        event_data = {
            "session_id": session_id,
            "exchange_id": event.exchange_id,
        }
        self._emit_event("sessionDataStreamStarted", event_data, subscribers)

    async def on_stream_done(self, event: StreamDoneEvent) -> None:
        """Handle stream done event from SessionManagerService.

        Emits streamDone WebSocket event to subscribed clients.
        """
        session_id = event.session_id
        subscribers = self._session_subscribers.get(session_id, set())
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

        Emits streamProgress WebSocket event to subscribed clients.
        This event is throttled (not sent on every delta).
        """
        session_id = event.session_id
        subscribers = self._session_subscribers.get(session_id, set())
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

        Emits streamError WebSocket event to subscribed clients.
        """
        session_id = event.session_id
        subscribers = self._session_subscribers.get(session_id, set())
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

        Emits toolUseStarted WebSocket event to subscribed clients.
        """
        session_id = event.session_id
        subscribers = self._session_subscribers.get(session_id, set())
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

        Emits toolInputDelta WebSocket event to subscribed clients.
        """
        session_id = event.session_id
        subscribers = self._session_subscribers.get(session_id, set())
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

        Emits toolUse WebSocket event (tool input complete) to subscribed clients.
        """
        session_id = event.session_id
        subscribers = self._session_subscribers.get(session_id, set())
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
                category="websocket",
            )

        self._emit_event("sessionDataToolUse", event_data, subscribers)

    async def on_tool_result(self, event: ToolResultEvent) -> None:
        """Handle tool result event from SessionManagerService.

        Emits toolResult WebSocket event to subscribed clients.
        """
        session_id = event.session_id
        subscribers = self._session_subscribers.get(session_id, set())
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
