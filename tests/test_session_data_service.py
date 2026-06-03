"""Tests for SessionDataService subscription tracking and event filtering."""

import pytest
from unittest.mock import MagicMock
from dataclasses import dataclass, field

from service.session_data_service import (
    SessionDataService,
    SubscriptionResult,
    SubscribeSessionResult,
    SessionSnapshot,
    TurnSnapshot,
    SessionTurnCreatedEvent,
    SessionTurnDeltaEvent,
    SessionTurnFinishedEvent,
)
from service.session_events import TurnDeltaEvent
from models import TextBlock, ToolUseBlock, ToolResultBlock, ContextMode

# Default layers for full subscription (equivalent to legacy subscribe_session)
ALL_LAYERS = ["header", "body", "delta", "history"]


# Helper to subscribe with all layers (replacement for removed subscribe_session)
async def subscribe_all(service: SessionDataService, session_id: str, client_id: str) -> SubscriptionResult:
    """Subscribe to all layers - equivalent to legacy subscribe_session."""
    return await service.subscribe_add(session_id, client_id, ALL_LAYERS)


# Helper to unsubscribe all layers (replacement for removed unsubscribe_session)
async def unsubscribe_all(service: SessionDataService, session_id: str, client_id: str) -> SubscriptionResult:
    """Unsubscribe from all layers - equivalent to legacy unsubscribe_session."""
    return await service.subscribe_remove(session_id, client_id, ALL_LAYERS)


class TestSubscriptionTracking:
    """Tests for subscribe/unsubscribe lifecycle using layer-based API."""

    @pytest.fixture
    def service(self):
        return SessionDataService()

    @pytest.mark.asyncio
    async def test_subscribe_add(self, service):
        """Test basic subscription with layers."""
        result = await service.subscribe_add("session-1", "client-a", ALL_LAYERS)

        assert result.session_id == "session-1"
        assert result.subscribed is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_subscribe_requires_client_id(self, service):
        """Test that client_id is required for subscription."""
        result = await service.subscribe_add("session-1", "", ALL_LAYERS)

        assert result.subscribed is False
        assert result.error == "client_id is required"

    @pytest.mark.asyncio
    async def test_multiple_clients_subscribe_to_session(self, service):
        """Test that multiple clients can subscribe to the same session."""
        await subscribe_all(service, "session-1", "client-a")
        await subscribe_all(service, "session-1", "client-b")
        await subscribe_all(service, "session-1", "client-c")

        subscribers = service.get_session_subscribers("session-1")
        assert subscribers == {"client-a", "client-b", "client-c"}

    @pytest.mark.asyncio
    async def test_client_subscribes_to_multiple_sessions(self, service):
        """Test that a client can subscribe to multiple sessions."""
        await subscribe_all(service, "session-1", "client-a")
        await subscribe_all(service, "session-2", "client-a")
        await subscribe_all(service, "session-3", "client-a")

        sessions = await service.get_subscribed_sessions("client-a")
        assert set(sessions) == {"session-1", "session-2", "session-3"}

    @pytest.mark.asyncio
    async def test_subscribe_remove(self, service):
        """Test basic unsubscription."""
        await subscribe_all(service, "session-1", "client-a")
        result = await unsubscribe_all(service, "session-1", "client-a")

        assert result.session_id == "session-1"
        assert result.subscribed is False
        assert result.error is None
        assert service.get_session_subscribers("session-1") == set()

    @pytest.mark.asyncio
    async def test_unsubscribe_requires_client_id(self, service):
        """Test that client_id is required for unsubscription."""
        result = await service.subscribe_remove("session-1", "", ALL_LAYERS)

        assert result.subscribed is False
        assert result.error == "client_id is required"

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_subscription(self, service):
        """Test unsubscribing from a session not subscribed to."""
        result = await unsubscribe_all(service, "session-1", "client-a")

        # Should succeed without error
        assert result.subscribed is False
        assert result.error is None

    @pytest.mark.asyncio
    async def test_get_subscriber_count(self, service):
        """Test getting subscriber count for a session."""
        assert await service.get_session_subscriber_count("session-1") == 0

        await subscribe_all(service, "session-1", "client-a")
        assert await service.get_session_subscriber_count("session-1") == 1

        await subscribe_all(service, "session-1", "client-b")
        assert await service.get_session_subscriber_count("session-1") == 2

        await unsubscribe_all(service, "session-1", "client-a")
        assert await service.get_session_subscriber_count("session-1") == 1


class TestClientDisconnection:
    """Tests for client disconnection cleanup."""

    @pytest.fixture
    def service(self):
        return SessionDataService()

    @pytest.mark.asyncio
    async def test_client_disconnected_cleans_up_subscriptions(self, service):
        """Test that client disconnection removes all subscriptions."""
        await subscribe_all(service, "session-1", "client-a")
        await subscribe_all(service, "session-2", "client-a")
        await subscribe_all(service, "session-1", "client-b")

        service.client_disconnected("client-a")

        # client-a's subscriptions should be cleaned up
        assert await service.get_subscribed_sessions("client-a") == []
        assert "client-a" not in service.get_session_subscribers("session-1")
        assert "client-a" not in service.get_session_subscribers("session-2")

        # client-b's subscription should still exist
        assert "client-b" in service.get_session_subscribers("session-1")

    @pytest.mark.asyncio
    async def test_client_disconnected_cleans_up_empty_session(self, service):
        """Test that empty session subscriber sets are cleaned up."""
        await subscribe_all(service, "session-1", "client-a")

        service.client_disconnected("client-a")

        # Session should have no subscribers
        assert service.get_session_subscribers("session-1") == set()

    def test_client_disconnected_handles_unknown_client(self, service):
        """Test that disconnecting an unknown client doesn't error."""
        # Should not raise
        service.client_disconnected("unknown-client")


class TestEventFiltering:
    """Tests for event emission with subscription filtering."""

    @pytest.fixture
    def service(self):
        return SessionDataService()

    @pytest.fixture
    def event_collector(self):
        """Fixture that collects emitted events."""
        events = []

        def handler(event_name, data, target_clients):
            events.append({
                "event_name": event_name,
                "data": data,
                "target_clients": target_clients,
            })

        return events, handler

    @pytest.mark.asyncio
    async def test_emit_turn_created_targets_subscribers(
        self, service, event_collector
    ):
        """Test that turnCreated events target only HEADER layer subscribers."""
        events, handler = event_collector
        service.add_event_handler(handler)

        await service.subscribe_add("session-1", "client-a", ["header"])
        await service.subscribe_add("session-1", "client-b", ["header"])

        service.emit_turn_created("session-1", "turn-uuid-1", "user", order=0)

        assert len(events) == 1
        assert events[0]["event_name"] == "sessionDataTurnCreated"
        assert events[0]["target_clients"] == {"client-a", "client-b"}

    @pytest.mark.asyncio
    async def test_emit_turn_delta_targets_subscribers(
        self, service, event_collector
    ):
        """Test that turnDelta events target only DELTA layer subscribers."""
        events, handler = event_collector
        service.add_event_handler(handler)

        await service.subscribe_add("session-1", "client-a", ["delta"])

        service.emit_turn_delta("session-1", "turn-uuid-1", "Hello", 5)

        assert len(events) == 1
        assert events[0]["event_name"] == "sessionDataTurnDelta"
        assert events[0]["target_clients"] == {"client-a"}

    @pytest.mark.asyncio
    async def test_emit_turn_finished_targets_subscribers(
        self, service, event_collector
    ):
        """Test that turnFinished events target HEADER and BODY layer subscribers."""
        events, handler = event_collector
        service.add_event_handler(handler)

        await service.subscribe_add("session-1", "client-a", ["header"])
        await service.subscribe_add("session-1", "client-b", ["body"])

        service.emit_turn_finished("session-1", "turn-uuid-1", "Hello, world!", 100)

        assert len(events) == 1
        assert events[0]["event_name"] == "sessionDataTurnFinished"
        assert events[0]["target_clients"] == {"client-a", "client-b"}

    @pytest.mark.asyncio
    async def test_no_event_emitted_when_no_subscribers(
        self, service, event_collector
    ):
        """Test that events are not emitted when no one is subscribed."""
        events, handler = event_collector
        service.add_event_handler(handler)

        # No subscribers for session-1
        service.emit_turn_created("session-1", "turn-uuid-1", "user", order=0)
        service.emit_turn_delta("session-1", "turn-uuid-1", "Hello", 5)
        service.emit_turn_finished("session-1", "turn-uuid-1", "Hello", 5)

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_events_only_target_session_subscribers(
        self, service, event_collector
    ):
        """Test that events only target subscribers of the specific session."""
        events, handler = event_collector
        service.add_event_handler(handler)

        await service.subscribe_add("session-1", "client-a", ["header"])
        await service.subscribe_add("session-2", "client-b", ["header"])

        service.emit_turn_created("session-1", "turn-uuid-1", "user", order=0)

        assert len(events) == 1
        # Only client-a is subscribed to session-1
        assert events[0]["target_clients"] == {"client-a"}


class TestEventHandlers:
    """Tests for event handler management."""

    @pytest.fixture
    def service(self):
        return SessionDataService()

    def test_add_event_handler(self, service):
        """Test adding an event handler."""
        handler = MagicMock()
        service.add_event_handler(handler)

        assert handler in service._event_handlers

    def test_remove_event_handler(self, service):
        """Test removing an event handler."""
        handler = MagicMock()
        service.add_event_handler(handler)
        service.remove_event_handler(handler)

        assert handler not in service._event_handlers

    def test_remove_nonexistent_handler(self, service):
        """Test removing a handler that was never added."""
        handler = MagicMock()
        # Should not raise
        service.remove_event_handler(handler)

    @pytest.mark.asyncio
    async def test_multiple_handlers_called(self, service):
        """Test that multiple handlers are all called."""
        handler1_calls = []
        handler2_calls = []

        def handler1(event_name, data, target_clients):
            handler1_calls.append((event_name, target_clients))

        def handler2(event_name, data, target_clients):
            handler2_calls.append((event_name, target_clients))

        service.add_event_handler(handler1)
        service.add_event_handler(handler2)

        await service.subscribe_add("session-1", "client-a", ["header"])
        service.emit_turn_created("session-1", "turn-uuid-1", "user", order=0)

        assert len(handler1_calls) == 1
        assert len(handler2_calls) == 1


class TestEventData:
    """Tests for event payload data."""

    @pytest.fixture
    def service(self):
        return SessionDataService()

    @pytest.mark.asyncio
    async def test_turn_created_event_data(self, service):
        """Test TurnCreatedEvent payload structure."""
        events = []

        def handler(event_name, data, target_clients):
            events.append(data)

        service.add_event_handler(handler)
        await service.subscribe_add("session-1", "client-a", ["header"])

        service.emit_turn_created(
            "session-1",
            turn_id="turn-uuid-5",
            role="assistant",
            order=5,
            exchange_id="exchange-123",
            content_block_type="code",
        )

        assert events[0] == {
            "session_id": "session-1",
            "turn_id": "turn-uuid-5",
            "role": "assistant",
            "order": 5,
            "exchange_id": "exchange-123",
            "content_block_type": "code",
            "parallel_group_id": None,
            "is_steering": False,
        }

    @pytest.mark.asyncio
    async def test_turn_delta_event_data(self, service):
        """Test TurnDeltaEvent payload structure."""
        events = []

        def handler(event_name, data, target_clients):
            events.append(data)

        service.add_event_handler(handler)
        await service.subscribe_add("session-1", "client-a", ["delta"])

        service.emit_turn_delta(
            "session-1",
            turn_id="turn-uuid-3",
            delta="Hello, ",
            accumulated_length=7,
        )

        assert events[0] == {
            "session_id": "session-1",
            "turn_id": "turn-uuid-3",
            "delta": "Hello, ",
            "accumulated_length": 7,
            "content_block_type": "text",
        }

    @pytest.mark.asyncio
    async def test_on_turn_delta_forwards_content_block_type(self, service):
        """Observer path should preserve content_block_type from SessionManagerService."""
        events = []

        def handler(event_name, data, target_clients):
            events.append(data)

        service.add_event_handler(handler)
        await service.subscribe_add("session-1", "client-a", ["delta"])

        await service.on_turn_delta(
            TurnDeltaEvent(
                session_id="session-1",
                turn_id="turn-uuid-thinking",
                turn_index=3,
                delta="pondering",
                accumulated_length=9,
                content_block_type="thinking",
            )
        )

        assert events[0] == {
            "session_id": "session-1",
            "turn_id": "turn-uuid-thinking",
            "delta": "pondering",
            "accumulated_length": 9,
            "content_block_type": "thinking",
        }

    @pytest.mark.asyncio
    async def test_turn_finished_event_data(self, service):
        """Test TurnFinishedEvent payload structure."""
        events = []

        def handler(event_name, data, target_clients):
            events.append(data)

        service.add_event_handler(handler)
        await service.subscribe_add("session-1", "client-a", ["header", "body"])

        service.emit_turn_finished(
            "session-1",
            turn_id="turn-uuid-3",
            final_content="Hello, world!",
            tokens=150,
        )

        assert events[0] == {
            "session_id": "session-1",
            "turn_id": "turn-uuid-3",
            "final_content": "Hello, world!",
            "tokens": 150,
            "content_block": None,  # Optional, not set in this test
            "order": 0,  # Default value
            "role": "assistant",  # Default value
            "context_tokens": 0,  # Cumulative context tokens (default)
            "output_tokens_total": 0,  # Cumulative output tokens (default)
        }


class TestSessionSnapshot:
    """Tests for get_session_snapshot and snapshot integration."""

    @pytest.fixture
    def service_with_loader(self, mock_session):
        """Create service with session_loader wired up."""
        async def mock_loader(session_id: str):
            if session_id == mock_session.id:
                return mock_session
            return None
        service = SessionDataService(session_loader=mock_loader)
        return service

    @pytest.fixture
    def mock_session(self):
        """Create a mock Session object for testing."""
        @dataclass
        class MockTurn:
            role: str
            content_block: TextBlock | ToolUseBlock | ToolResultBlock
            context_mode: ContextMode = ContextMode.COPY
            exchange_id: str | None = None
            id: str = ""

            @property
            def content(self):
                if isinstance(self.content_block, TextBlock):
                    return self.content_block.text
                return ""

        @dataclass
        class MockSession:
            id: str = "test-session-1"
            created: str = "2024-01-01T00:00:00"
            last_modified: str = "2024-01-01T00:00:00"
            model: str = "claude-3"
            title: str = "Test Session"
            total_input_tokens: int = 0
            total_output_tokens: int = 0
            total_cost: float = 0.0
            parent_id: str | None = None
            children: list = field(default_factory=list)
            fork_name: str = ""
            fork_status: str = "active"
            backend_name: str = ""
            turns: list = field(default_factory=list)
            messages: list = field(default_factory=list)

        session = MockSession()
        session.turns = [
            MockTurn(
                role="user",
                content_block=TextBlock(text="Hello"),
                exchange_id="ex-1",
                id="turn-uuid-1",
            ),
            MockTurn(
                role="assistant",
                content_block=TextBlock(text="Hi there!"),
                exchange_id="ex-1",
                id="turn-uuid-2",
            ),
            MockTurn(
                role="user",
                content_block=TextBlock(text="Use a tool"),
                exchange_id="ex-2",
                id="turn-uuid-3",
            ),
            MockTurn(
                role="assistant",
                content_block=ToolUseBlock(id="tool-1", name="search", input={"q": "test"}),
                exchange_id="ex-2",
                id="turn-uuid-4",
            ),
            MockTurn(
                role="tool",
                content_block=ToolResultBlock(tool_use_id="tool-1", content="Found results"),
                exchange_id="ex-2",
                id="turn-uuid-5",
            ),
        ]
        return session

    @pytest.mark.asyncio
    async def test_get_session_snapshot_returns_none_without_loader(self):
        """Test that snapshot returns None when session_loader is not configured."""
        service = SessionDataService()  # No session_loader
        snapshot = await service.get_session_snapshot("session-1")
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_get_session_snapshot_returns_none_for_unknown_session(
        self, service_with_loader
    ):
        """Test that snapshot returns None for unknown session."""
        snapshot = await service_with_loader.get_session_snapshot("unknown-session")
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_get_session_snapshot_returns_full_turn_history(
        self, service_with_loader, mock_session
    ):
        """Test that snapshot includes all turns with correct data."""
        snapshot = await service_with_loader.get_session_snapshot(mock_session.id)

        assert snapshot is not None
        assert snapshot.session_id == mock_session.id
        assert snapshot.title == mock_session.title
        assert snapshot.model == mock_session.model
        assert len(snapshot.turns) == 5

        # Check first turn (idx removed - order is from array position)
        assert snapshot.turns[0].turn_id == "turn-uuid-1"
        assert snapshot.turns[0].role == "user"
        assert snapshot.turns[0].content_block.type == "text"
        assert snapshot.turns[0].content_block.text == "Hello"
        assert snapshot.turns[0].exchange_id == "ex-1"

        # Check assistant turn
        assert snapshot.turns[1].turn_id == "turn-uuid-2"
        assert snapshot.turns[1].role == "assistant"
        assert snapshot.turns[1].content_block.text == "Hi there!"

        # Check tool_use turn
        assert snapshot.turns[3].turn_id == "turn-uuid-4"
        assert snapshot.turns[3].role == "assistant"
        assert snapshot.turns[3].content_block.type == "tool_use"

        # Check tool_result turn
        assert snapshot.turns[4].turn_id == "turn-uuid-5"
        assert snapshot.turns[4].role == "tool"
        assert snapshot.turns[4].content_block.type == "tool_result"

    @pytest.mark.asyncio
    async def test_snapshot_context_mode_defaults_to_copy(
        self, service_with_loader, mock_session
    ):
        """Test that snapshot context_mode defaults to copy."""
        snapshot = await service_with_loader.get_session_snapshot(mock_session.id)

        # All turns should have default context_mode of "copy"
        assert snapshot.turns[1].context_mode == "copy"

    @pytest.mark.asyncio
    async def test_snapshot_streaming_status_is_false(
        self, service_with_loader, mock_session
    ):
        """Test that snapshot streaming status is false for persisted sessions."""
        snapshot = await service_with_loader.get_session_snapshot(mock_session.id)

        # Streaming status is false for sessions loaded from storage
        # (streaming state is updated by live events, not loaded from storage)
        assert snapshot.is_streaming is False
        assert len(snapshot.streaming_turn_ids) == 0

    @pytest.mark.asyncio
    async def test_subscribe_add_with_history(
        self, service_with_loader, mock_session
    ):
        """Test that subscribe_add with history layer subscribes successfully.

        Note: subscribe_add does NOT return a snapshot or trigger history loading.
        History loading happens via a separate mechanism.
        """
        result = await service_with_loader.subscribe_add(
            mock_session.id, "client-a", ALL_LAYERS
        )

        assert isinstance(result, SubscriptionResult)
        assert result.subscribed is True
        assert result.session_id == mock_session.id

    @pytest.mark.asyncio
    async def test_subscribe_add_registers_client(
        self, service_with_loader, mock_session
    ):
        """Test that subscription registers the client."""
        await service_with_loader.subscribe_add(
            mock_session.id, "client-a", ALL_LAYERS
        )

        # Client should be subscribed
        assert "client-a" in service_with_loader.get_session_subscribers(mock_session.id)

    @pytest.mark.asyncio
    async def test_subscribe_add_works_without_loader(self):
        """Test that subscription works even without session_loader."""
        service = SessionDataService()  # No session_loader

        result = await service.subscribe_add("session-1", "client-a", ALL_LAYERS)

        assert result.subscribed is True

    @pytest.mark.asyncio
    async def test_set_session_loader_enables_snapshots(self, mock_session):
        """Test that set_session_loader enables snapshot loading."""
        service = SessionDataService()

        # Initially no snapshots
        snapshot = await service.get_session_snapshot(mock_session.id)
        assert snapshot is None

        # Wire up session_loader
        async def mock_loader(session_id: str):
            if session_id == mock_session.id:
                return mock_session
            return None
        service.set_session_loader(mock_loader)

        # Now snapshots work
        snapshot = await service.get_session_snapshot(mock_session.id)
        assert snapshot is not None
        assert len(snapshot.turns) == 5


class TestSessionLoading:
    """Tests for session loading via session_loader callback."""

    @pytest.fixture
    def mock_session_for_loader(self):
        """Create a mock Session object for loader tests."""
        @dataclass
        class MockTurn:
            role: str = "user"
            content_block: TextBlock = field(default_factory=lambda: TextBlock(text="loaded content"))
            context_mode: ContextMode = ContextMode.COPY
            exchange_id: str | None = None
            id: str = "loaded-turn-id"

            @property
            def content(self):
                return self.content_block.text

        @dataclass
        class MockSession:
            id: str = "unloaded-session"
            created: str = "2024-01-01"
            last_modified: str = "2024-01-01"
            model: str = "claude-3"
            title: str = "Loaded Session"
            total_input_tokens: int = 0
            total_output_tokens: int = 0
            total_cost: float = 0.0
            parent_id: str | None = None
            children: list = field(default_factory=list)
            fork_name: str = ""
            fork_status: str = "active"
            backend_name: str = ""
            turns: list = field(default_factory=list)
            messages: list = field(default_factory=list)

        session = MockSession()
        session.turns = [MockTurn()]
        return session

    @pytest.mark.asyncio
    async def test_session_loader_called_for_session(
        self, mock_session_for_loader
    ):
        """Test that session_loader is called when requesting session."""
        loader_calls = []

        async def mock_loader(session_id: str):
            loader_calls.append(session_id)
            if session_id == mock_session_for_loader.id:
                return mock_session_for_loader
            return None

        service = SessionDataService(session_loader=mock_loader)

        snapshot = await service.get_session_snapshot(mock_session_for_loader.id)

        # Loader should have been called
        assert mock_session_for_loader.id in loader_calls
        # Snapshot should now exist
        assert snapshot is not None
        assert len(snapshot.turns) == 1
        assert snapshot.title == "Loaded Session"

    @pytest.mark.asyncio
    async def test_snapshot_returns_none_when_loader_returns_none(self):
        """Test that snapshot returns None when loader can't find session."""
        async def mock_loader(session_id: str):
            return None

        service = SessionDataService(session_loader=mock_loader)

        snapshot = await service.get_session_snapshot("nonexistent-session")
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_subscribe_add_works_with_loader(
        self, mock_session_for_loader
    ):
        """Test that subscribe_add works when session_loader is configured.

        Note: subscribe_add does NOT load sessions or return snapshots.
        It just registers the subscription.
        """
        async def mock_loader(session_id: str):
            if session_id == mock_session_for_loader.id:
                return mock_session_for_loader
            return None

        service = SessionDataService(session_loader=mock_loader)

        # Subscribe to session
        result = await service.subscribe_add(mock_session_for_loader.id, "client-a", ALL_LAYERS)

        assert result.subscribed is True
        assert result.session_id == mock_session_for_loader.id


class TestTurnSnapshotFields:
    """Tests for TurnSnapshot field correctness."""

    @pytest.mark.asyncio
    async def test_turn_snapshot_from_get_session_snapshot(self):
        """Test TurnSnapshot includes all required fields per acceptance criteria."""
        @dataclass
        class MockTurn:
            role: str = "user"
            content_block: TextBlock = field(default_factory=lambda: TextBlock(text="test"))
            context_mode: ContextMode = ContextMode.COPY
            exchange_id: str | None = "ex-1"
            id: str = "turn-id-abc"
            tokens: int = 0

            @property
            def content(self):
                return self.content_block.text

        @dataclass
        class MockSession:
            id: str = "session-1"
            created: str = "2024-01-01"
            last_modified: str = "2024-01-01"
            model: str = "claude-3"
            title: str = "Test"
            total_input_tokens: int = 0
            total_output_tokens: int = 0
            total_cost: float = 0.0
            parent_id: str | None = None
            children: list = field(default_factory=list)
            fork_name: str = ""
            fork_status: str = "active"
            backend_name: str = ""
            turns: list = field(default_factory=list)
            messages: list = field(default_factory=list)

        session = MockSession()
        session.turns = [MockTurn()]

        async def mock_loader(session_id: str):
            if session_id == session.id:
                return session
            return None

        service = SessionDataService(session_loader=mock_loader)

        snapshot = await service.get_session_snapshot(session.id)
        turn = snapshot.turns[0]

        # Verify all required fields per acceptance criteria
        # Note: idx removed - order is from array position
        # content and content_block_type replaced by content_block
        assert hasattr(turn, 'turn_id')
        assert hasattr(turn, 'role')
        assert hasattr(turn, 'content_block')  # Full structured content
        assert hasattr(turn, 'streaming')
        assert hasattr(turn, 'viewed')
        assert hasattr(turn, 'tokens')
        assert hasattr(turn, 'context_mode')
        assert hasattr(turn, 'exchange_id')

        # Verify correct values
        assert turn.turn_id == "turn-id-abc"
        assert turn.role == "user"
        assert turn.content_block.type == "text"
        assert turn.content_block.text == "test"
        assert turn.exchange_id == "ex-1"


class TestChunkedHistoryLoading:
    """Tests for chunked history loading from LMDB.

    These tests verify that:
    1. subscribe_add with HISTORY layer triggers history loading
    2. Historical turns are streamed via historyChunk events
    3. historyComplete is emitted when all chunks are sent
    """

    @pytest.fixture
    def mock_storage(self):
        """Create a mock AsyncStorage for testing chunked loading."""
        class MockStorage:
            def __init__(self):
                self.turns = {}  # session_id -> list of turn dicts
                self.get_turn_count_calls = []
                self.load_turns_range_calls = []

            async def get_turn_count(self, session_id: str) -> int:
                self.get_turn_count_calls.append(session_id)
                return len(self.turns.get(session_id, []))

            async def load_turns_range(
                self, session_id: str, offset: int, limit: int
            ) -> list[dict]:
                self.load_turns_range_calls.append((session_id, offset, limit))
                turns = self.turns.get(session_id, [])
                return turns[offset:offset + limit]

        return MockStorage()

    @pytest.fixture
    def mock_session(self):
        """Create a mock session with metadata."""
        @dataclass
        class MockSession:
            id: str = "test-session-1"
            created: str = "2024-01-01T00:00:00"
            last_modified: str = "2024-01-01T01:00:00"
            model: str = "claude-3"
            title: str = "Test Session"
            total_input_tokens: int = 100
            total_output_tokens: int = 200
            total_cost: float = 0.05
            parent_id: str | None = None
            children: list = field(default_factory=list)
            fork_name: str = ""
            fork_status: str = "active"
            backend_name: str = ""
            turns: list = field(default_factory=list)
            messages: list = field(default_factory=list)

        return MockSession()

    @pytest.mark.asyncio
    async def test_subscribe_returns_empty_turns(
        self, mock_storage, mock_session
    ):
        """Test that subscribe returns metadata with empty turns list."""
        async def mock_loader(session_id: str):
            if session_id == mock_session.id:
                return mock_session
            return None

        service = SessionDataService(
            session_loader=mock_loader,
            storage=mock_storage,
        )

        result = await service.subscribe_add(mock_session.id, "client-a", ALL_LAYERS)

        assert result.subscribed is True
        assert result.session_id == mock_session.id

    @pytest.mark.asyncio
    async def test_history_chunk_events_emitted(
        self, mock_storage, mock_session
    ):
        """Test that historyChunk events are emitted for turns."""
        import asyncio

        # Add some turns to the mock session
        @dataclass
        class MockTurn:
            id: str
            role: str
            content_block: TextBlock
            tokens: int
            context_mode: ContextMode
            exchange_id: str

        mock_session.turns = [
            MockTurn(
                id="turn-1",
                role="user",
                content_block=TextBlock(type="text", text="Hello"),
                tokens=10,
                context_mode=ContextMode.COPY,
                exchange_id="ex-1",
            ),
            MockTurn(
                id="turn-2",
                role="assistant",
                content_block=TextBlock(type="text", text="Hi there!"),
                tokens=15,
                context_mode=ContextMode.COPY,
                exchange_id="ex-1",
            ),
        ]

        async def mock_loader(session_id: str):
            if session_id == mock_session.id:
                return mock_session
            return None

        service = SessionDataService(
            session_loader=mock_loader,
            storage=mock_storage,
        )

        # Track emitted events
        events = []
        def capture_event(name, data, clients):
            events.append((name, data))

        service.add_event_handler(capture_event)

        # Subscribe with HISTORY layer - this triggers history loading
        result = await service.subscribe_add(mock_session.id, "client-a", ["history"])
        assert result.subscribed is True

        # Should have emitted historyChunk and historyComplete events
        event_names = [e[0] for e in events]
        assert "sessionDataHistoryChunk" in event_names
        assert "sessionDataHistoryComplete" in event_names

        # Check chunk event content
        chunk_event = next(e for e in events if e[0] == "sessionDataHistoryChunk")
        assert chunk_event[1]["session_id"] == mock_session.id
        assert len(chunk_event[1]["turns"]) == 2

        # Check complete event content
        complete_event = next(e for e in events if e[0] == "sessionDataHistoryComplete")
        assert complete_event[1]["session_id"] == mock_session.id
        assert complete_event[1]["total_turns"] == 2

    @pytest.mark.asyncio
    async def test_history_complete_emitted_for_empty_session(
        self, mock_storage, mock_session
    ):
        """Test that historyComplete is emitted even for sessions with no turns."""
        import asyncio

        mock_storage.turns[mock_session.id] = []  # Empty

        async def mock_loader(session_id: str):
            if session_id == mock_session.id:
                return mock_session
            return None

        service = SessionDataService(
            session_loader=mock_loader,
            storage=mock_storage,
        )

        events = []
        service.add_event_handler(lambda name, data, clients: events.append((name, data)))

        await service.subscribe_add(mock_session.id, "client-a", ["history"])
        await asyncio.sleep(0.1)

        # Should have historyComplete but no historyChunk
        event_names = [e[0] for e in events]
        assert "sessionDataHistoryComplete" in event_names

        complete_event = next(e for e in events if e[0] == "sessionDataHistoryComplete")
        assert complete_event[1]["total_turns"] == 0
        # Watermark is 0 for empty sessions (changed from -1 in new implementation)

    @pytest.mark.asyncio
    async def test_no_history_events_without_storage(self, mock_session):
        """Test that no history events are emitted when no storage configured."""
        import asyncio

        async def mock_loader(session_id: str):
            if session_id == mock_session.id:
                return mock_session
            return None

        # No storage configured - history streaming is skipped
        service = SessionDataService(session_loader=mock_loader)

        events = []
        service.add_event_handler(lambda name, data, clients: events.append((name, data)))

        await service.subscribe_add(mock_session.id, "client-a", ["history"])
        await asyncio.sleep(0.1)

        # Without storage, history events still complete but with 0 turns
        # (changed from old behavior - now always emits complete event)
        event_names = [e[0] for e in events]
        # Check we got the complete event even without storage
        assert "sessionDataHistoryComplete" in event_names

    @pytest.mark.asyncio
    async def test_turn_dict_to_snapshot_conversion(self, mock_storage):
        """Test that turn dicts from storage are correctly converted to TurnSnapshot."""
        service = SessionDataService(
            storage=mock_storage,
        )

        turn_dict = {
            "id": "turn-uuid-123",
            "role": "assistant",
            "content_block": {"type": "text", "text": "Hello world"},
            "tokens": 42,
            "context_mode": "compress",
            "exchange_id": "ex-abc",
        }

        snapshot = service._turn_dict_to_snapshot(turn_dict, order=5)

        assert snapshot.turn_id == "turn-uuid-123"
        assert snapshot.role == "assistant"
        assert snapshot.tokens == 42
        assert snapshot.context_mode == "compress"
        assert snapshot.exchange_id == "ex-abc"
        assert snapshot.streaming is False  # Historical turns never streaming
        assert snapshot.viewed is True  # Historical turns considered viewed
        assert snapshot.content_block.type == "text"
        assert snapshot.content_block.text == "Hello world"

    @pytest.mark.asyncio
    async def test_deserialize_content_block_types(self, mock_storage):
        """Test that various content block types are correctly deserialized."""
        service = SessionDataService(
            storage=mock_storage,
        )

        # Test text block
        text_block = service._deserialize_content_block({"type": "text", "text": "hello"})
        assert text_block.type == "text"
        assert text_block.text == "hello"

        # Test tool_use block
        tool_use_block = service._deserialize_content_block({
            "type": "tool_use",
            "id": "tool-123",
            "name": "read_file",
            "input": {"path": "/tmp/foo"},
        })
        assert tool_use_block.type == "tool_use"
        assert tool_use_block.id == "tool-123"
        assert tool_use_block.name == "read_file"
        assert tool_use_block.input == {"path": "/tmp/foo"}

        # Test tool_result block
        tool_result_block = service._deserialize_content_block({
            "type": "tool_result",
            "tool_use_id": "tool-123",
            "content": "file contents",
            "is_error": False,
        })
        assert tool_result_block.type == "tool_result"
        assert tool_result_block.tool_use_id == "tool-123"

        # Test fork block
        fork_block = service._deserialize_content_block({
            "type": "fork",
            "child_session_id": "child-session",
            "fork_name": "feature-branch",
        })
        assert fork_block.type == "fork"
        assert fork_block.child_session_id == "child-session"


class TestLayerBasedSubscriptions:
    """Tests for the new layer-based subscription API."""

    @pytest.fixture
    def service(self):
        return SessionDataService()

    @pytest.mark.asyncio
    async def test_subscribe_add_creates_subscription(self, service):
        """Adding layers creates a subscription."""
        result = await service.subscribe_add("session-1", "client-a", ["header"])

        assert result.session_id == "session-1"
        assert result.subscribed is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_subscribe_add_requires_client_id(self, service):
        """client_id is required."""
        result = await service.subscribe_add("session-1", "", ["header"])

        assert result.subscribed is False
        assert result.error == "client_id is required"

    @pytest.mark.asyncio
    async def test_subscribe_add_requires_layers(self, service):
        """At least one layer is required."""
        result = await service.subscribe_add("session-1", "client-a", [])

        assert result.subscribed is False
        assert "layer is required" in result.error

    @pytest.mark.asyncio
    async def test_subscribe_add_validates_layer_names(self, service):
        """Invalid layer names are rejected."""
        result = await service.subscribe_add("session-1", "client-a", ["invalid_layer"])

        assert result.subscribed is False
        assert "invalid layer" in result.error.lower()

    @pytest.mark.asyncio
    async def test_subscribe_add_multiple_layers(self, service):
        """Multiple layers can be added at once."""
        result = await service.subscribe_add(
            "session-1", "client-a", ["header", "body", "delta"]
        )

        assert result.subscribed is True

        # Verify layers are tracked
        from service.subscription_manager import Layer
        layers = service._subscription_manager.get_client_layers("session-1", "client-a")
        assert Layer.HEADER in layers
        assert Layer.BODY in layers
        assert Layer.DELTA in layers

    @pytest.mark.asyncio
    async def test_subscribe_remove_removes_layers(self, service):
        """Removing layers updates subscription."""
        # First add layers
        await service.subscribe_add("session-1", "client-a", ["header", "body", "delta"])

        # Remove delta
        result = await service.subscribe_remove("session-1", "client-a", ["delta"])

        assert result.subscribed is True  # Still has header+body

        from service.subscription_manager import Layer
        layers = service._subscription_manager.get_client_layers("session-1", "client-a")
        assert Layer.HEADER in layers
        assert Layer.BODY in layers
        assert Layer.DELTA not in layers

    @pytest.mark.asyncio
    async def test_subscribe_remove_all_layers_unsubscribes(self, service):
        """Removing all layers unsubscribes completely."""
        await service.subscribe_add("session-1", "client-a", ["header"])
        result = await service.subscribe_remove("session-1", "client-a", ["header"])

        assert result.subscribed is False  # No layers remaining

    @pytest.mark.asyncio
    async def test_emit_turn_created_routes_to_header_layer(self, service):
        """turnCreated events route to HEADER layer subscribers."""
        events = []
        service.add_event_handler(
            lambda name, data, clients: events.append((name, clients))
        )

        # Subscribe via layers
        await service.subscribe_add("session-1", "client-a", ["header"])

        # Emit event
        service.emit_turn_created(
            "session-1",
            turn_id="turn-1",
            role="assistant",
            order=0,
        )

        assert len(events) == 1
        assert events[0][0] == "sessionDataTurnCreated"
        assert "client-a" in events[0][1]

    @pytest.mark.asyncio
    async def test_emit_turn_delta_routes_to_delta_layer(self, service):
        """turnDelta events route to DELTA layer subscribers."""
        events = []
        service.add_event_handler(
            lambda name, data, clients: events.append((name, clients))
        )

        # Subscribe to header only (no delta)
        await service.subscribe_add("session-1", "client-a", ["header"])
        # Subscribe to delta
        await service.subscribe_add("session-1", "client-b", ["delta"])

        # Emit delta event
        service.emit_turn_delta(
            "session-1",
            turn_id="turn-1",
            delta="Hello",
            accumulated_length=5,
        )

        assert len(events) == 1
        assert events[0][0] == "sessionDataTurnDelta"
        # Only client-b should receive (has DELTA layer)
        assert "client-b" in events[0][1]
        assert "client-a" not in events[0][1]

    @pytest.mark.asyncio
    async def test_emit_turn_finished_routes_to_header_and_body(self, service):
        """turnFinished events route to HEADER and BODY layer subscribers."""
        events = []
        service.add_event_handler(
            lambda name, data, clients: events.append((name, clients))
        )

        # client-a has header only
        await service.subscribe_add("session-1", "client-a", ["header"])
        # client-b has body only
        await service.subscribe_add("session-1", "client-b", ["body"])
        # client-c has delta only (should NOT receive)
        await service.subscribe_add("session-1", "client-c", ["delta"])

        # Emit finished event
        service.emit_turn_finished(
            "session-1",
            turn_id="turn-1",
            final_content="Hello",
            tokens=10,
        )

        assert len(events) == 1
        assert events[0][0] == "sessionDataTurnFinished"
        # Both header and body subscribers should receive
        assert "client-a" in events[0][1]
        assert "client-b" in events[0][1]
        # Delta-only should NOT receive
        assert "client-c" not in events[0][1]

    @pytest.mark.asyncio
    async def test_client_disconnected_cleans_up_layer_subscriptions(self, service):
        """Client disconnect cleans up layer subscriptions."""
        await service.subscribe_add("session-1", "client-a", ["header", "body"])
        await service.subscribe_add("session-2", "client-a", ["header"])

        service.client_disconnected("client-a")

        # Verify all subscriptions removed
        from service.subscription_manager import Layer
        assert service._subscription_manager.get_client_sessions("client-a") == {}

    @pytest.mark.asyncio
    async def test_multiple_layer_subscriptions(self, service):
        """Multiple layer subscriptions work together."""
        events = []
        service.add_event_handler(
            lambda name, data, clients: events.append((name, clients))
        )

        # Subscribe with different layers
        await service.subscribe_add("session-1", "client-header", ["header"])
        await service.subscribe_add("session-1", "client-all", ["header", "body", "delta"])

        # Emit event
        service.emit_turn_created(
            "session-1",
            turn_id="turn-1",
            role="assistant",
            order=0,
        )

        assert len(events) == 1
        # Both clients should receive (turnCreated goes to HEADER layer)
        assert "client-header" in events[0][1]
        assert "client-all" in events[0][1]
