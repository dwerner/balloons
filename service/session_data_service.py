"""WebSocket-exposed service for session data streaming.

This service provides real-time session data subscriptions, allowing clients
to subscribe to specific sessions and receive turn updates as they happen.

Unlike TreeStateService which exposes the full tree structure, this service
focuses on efficient streaming of session content:
- Clients subscribe to specific sessions by ID
- Turn deltas stream as content is generated
- Snapshots provide full state for late-joining clients

Example usage:
    service = SessionDataService()

    # Subscribe to a session:
    # {"id": "1", "method": "subscribeSession", "params": {"sessionId": "abc"}}
    # -> {"id": "1", "result": {"sessionId": "abc", "subscribed": true}}

    # Receive streaming events:
    # {"event": "turnDelta", "data": {"sessionId": "abc", "turnId": "uuid-123", "delta": "Hello"}}
"""

from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING, Any, Awaitable

from codegen import ws_service, ws_expose, ws_event, ws_type

if TYPE_CHECKING:
    from core.tree_state import TreeState

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
    """

    turn_id: str  # Stable UUID for the turn
    idx: int
    role: str  # "user", "assistant", "tool"
    content: str
    streaming: bool
    viewed: bool
    tokens: int
    context_mode: str  # "copy", "compress", "drop"
    content_block_type: str = "text"
    exchange_id: str | None = None


@ws_type
@dataclass
class SessionSnapshot:
    """Complete snapshot of a session's current state.

    Sent when a client subscribes to provide full initial state.
    After receiving a snapshot, clients receive incremental TurnDeltas.
    """

    session_id: str
    title: str
    model: str
    is_streaming: bool
    turns: list[TurnSnapshot] = field(default_factory=list)
    current_turn_idx: int | None = None  # Index of currently streaming turn
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
    final_content: str
    tokens: int


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

    def __init__(
        self,
        tree_state: "TreeState | None" = None,
        session_loader: SessionLoaderCallback | None = None,
    ) -> None:
        """Initialize the session data service.

        Args:
            tree_state: Optional TreeState for loading session snapshots.
                       Can also be set later via set_tree_state().
            session_loader: Optional async callback to load sessions from storage.
                           Used when a session isn't already loaded in TreeState.
        """
        # Event handlers receive: (event_name, data, target_clients)
        # target_clients is a set of client_ids that should receive the event
        self._event_handlers: list[Callable[[str, dict, set[str] | None], None]] = []
        # Track subscriptions: client_id -> set of session_ids
        self._subscriptions: dict[str, set[str]] = {}
        # Track reverse mapping: session_id -> set of client_ids
        self._session_subscribers: dict[str, set[str]] = {}
        # TreeState for loading session data
        self._tree_state: "TreeState | None" = tree_state
        # Session loader callback for loading sessions not in TreeState
        self._session_loader: SessionLoaderCallback | None = session_loader

    def set_tree_state(self, tree_state: "TreeState") -> None:
        """Set the TreeState for loading session snapshots.

        Args:
            tree_state: The TreeState instance to use for loading session data
        """
        self._tree_state = tree_state

    def set_session_loader(self, loader: SessionLoaderCallback) -> None:
        """Set the session loader callback.

        The callback should be an async function that takes a session_id
        and returns the Session object, or None if not found.

        Args:
            loader: Async callback (session_id) -> Session | None
        """
        self._session_loader = loader

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

        Returns the full session snapshot atomically with the subscription,
        ensuring the client has complete initial state before receiving any
        incremental events.

        When subscribed, the client will receive:
        - turnCreated: When a new turn starts
        - turnDelta: As content streams in
        - turnFinished: When a turn completes

        Args:
            session_id: The session to subscribe to
            client_id: Unique identifier for the subscribing client

        Returns:
            SubscribeSessionResult with snapshot if session found
        """
        if not client_id:
            return SubscribeSessionResult(
                session_id=session_id,
                subscribed=False,
                error="client_id is required",
            )

        # Get snapshot BEFORE adding subscription to ensure atomicity
        # (client won't miss events that happen after snapshot but before subscription)
        snapshot = await self.get_session_snapshot(session_id)

        # Add to client's subscriptions
        if client_id not in self._subscriptions:
            self._subscriptions[client_id] = set()
        self._subscriptions[client_id].add(session_id)

        # Add to session's subscribers
        if session_id not in self._session_subscribers:
            self._session_subscribers[session_id] = set()
        self._session_subscribers[session_id].add(client_id)

        from core.debug_log import debug_log
        debug_log.info(
            f"subscribe_session: session={session_id[:8]}, client={client_id}, "
            f"total_subscribers={len(self._session_subscribers.get(session_id, set()))}",
            category="websocket",
        )

        return SubscribeSessionResult(
            session_id=session_id,
            subscribed=True,
            snapshot=snapshot,
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
        if not self._tree_state:
            return None

        session_data = self._tree_state.get_session(session_id)

        # If session not in TreeState or turns not loaded, try to load it
        if session_data is None or session_data.turns is None:
            if self._session_loader:
                # Load session from storage
                session = await self._session_loader(session_id)
                if session:
                    # Add/update in TreeState and load turns
                    self._tree_state.add_session(session, is_current=False)
                    self._tree_state.load_session(session_id, session)
                    session_data = self._tree_state.get_session(session_id)

        if not session_data:
            return None

        # Convert TreeState turns to TurnSnapshot format
        turn_snapshots: list[TurnSnapshot] = []
        streaming_turn_ids: list[str] = []
        current_turn_idx: int | None = None

        if session_data.turns is not None:
            for turn in session_data.turns:
                # Determine content_block_type from content_block
                content_block_type = "text"
                if turn.content_block is not None:
                    content_block_type = turn.content_block.type

                # Get context mode for this turn
                context_mode = self._tree_state.get_context_mode(session_id, turn.idx)

                # Get turn_id from the session_ref if available (Turn has .id field)
                turn_id = ""
                if session_data.session_ref and hasattr(session_data.session_ref, 'turns'):
                    session_turns = session_data.session_ref.turns
                    if turn.idx < len(session_turns):
                        session_turn = session_turns[turn.idx]
                        if hasattr(session_turn, 'id'):
                            turn_id = session_turn.id

                turn_snapshot = TurnSnapshot(
                    turn_id=turn_id,
                    idx=turn.idx,
                    role=turn.role,
                    content=turn.content,
                    streaming=turn.streaming,
                    viewed=turn.viewed,
                    tokens=turn.tokens,
                    context_mode=context_mode.value,
                    content_block_type=content_block_type,
                    exchange_id=turn.exchange_id,
                )
                turn_snapshots.append(turn_snapshot)

                # Track streaming turns
                if turn.streaming:
                    streaming_turn_ids.append(turn_id)
                    current_turn_idx = turn.idx

        return SessionSnapshot(
            session_id=session_id,
            title=session_data.title,
            model=session_data.model,
            is_streaming=session_data.is_streaming,
            turns=turn_snapshots,
            current_turn_idx=current_turn_idx,
            streaming_turn_ids=streaming_turn_ids,
        )

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
        exchange_id: str | None = None,
        content_block_type: str = "text",
    ) -> None:
        """Emit a turn created event to subscribed clients.

        Called when a new turn begins in a session.

        Args:
            session_id: The session where the turn was created
            turn_id: Stable UUID for the turn
            role: Turn role ("user", "assistant", "tool")
            exchange_id: Exchange ID grouping related turns
            content_block_type: Type of content block
        """
        from core.debug_log import debug_log
        subscribers = self._session_subscribers.get(session_id)
        debug_log.debug(
            f"emit_turn_created: session={session_id[:8]}, turn={turn_id[:8] if turn_id else 'none'}, "
            f"role={role}, subscribers={len(subscribers) if subscribers else 0}",
            category="websocket",
        )
        if not subscribers:
            return

        event_data = SessionTurnCreatedEvent(
            session_id=session_id,
            turn_id=turn_id,
            role=role,
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
    ) -> None:
        """Emit a turn finished event to subscribed clients.

        Called when a turn completes streaming.

        Args:
            session_id: The session containing the turn
            turn_id: Stable UUID for the turn
            final_content: Complete content of the turn
            tokens: Token count for the turn
        """
        subscribers = self._session_subscribers.get(session_id)
        if not subscribers:
            return

        event_data = SessionTurnFinishedEvent(
            session_id=session_id,
            turn_id=turn_id,
            final_content=final_content,
            tokens=tokens,
        )
        from core.debug_log import debug_log
        debug_log.debug(
            f"emit_turn_finished: turn_id={turn_id}, final_content_len={len(final_content)}, "
            f"tokens={tokens}, subscribers={len(subscribers)}",
            category="websocket",
        )
        self._emit_event("sessionDataTurnFinished", event_data.__dict__, subscribers)

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
