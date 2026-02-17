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
from core.tree_state import TreeState, TurnData, SessionData
from models import TextBlock, ToolUseBlock, ToolResultBlock, ContextMode


class TestSubscriptionTracking:
    """Tests for subscribe/unsubscribe lifecycle."""

    @pytest.fixture
    def service(self):
        return SessionDataService()

    @pytest.mark.asyncio
    async def test_subscribe_session(self, service):
        """Test basic subscription."""
        result = await service.subscribe_session("session-1", "client-a")

        assert result.session_id == "session-1"
        assert result.subscribed is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_subscribe_requires_client_id(self, service):
        """Test that client_id is required for subscription."""
        result = await service.subscribe_session("session-1", "")

        assert result.subscribed is False
        assert result.error == "client_id is required"

    @pytest.mark.asyncio
    async def test_multiple_clients_subscribe_to_session(self, service):
        """Test that multiple clients can subscribe to the same session."""
        await service.subscribe_session("session-1", "client-a")
        await service.subscribe_session("session-1", "client-b")
        await service.subscribe_session("session-1", "client-c")

        subscribers = service.get_session_subscribers("session-1")
        assert subscribers == {"client-a", "client-b", "client-c"}

    @pytest.mark.asyncio
    async def test_client_subscribes_to_multiple_sessions(self, service):
        """Test that a client can subscribe to multiple sessions."""
        await service.subscribe_session("session-1", "client-a")
        await service.subscribe_session("session-2", "client-a")
        await service.subscribe_session("session-3", "client-a")

        sessions = await service.get_subscribed_sessions("client-a")
        assert set(sessions) == {"session-1", "session-2", "session-3"}

    @pytest.mark.asyncio
    async def test_unsubscribe_session(self, service):
        """Test basic unsubscription."""
        await service.subscribe_session("session-1", "client-a")
        result = await service.unsubscribe_session("session-1", "client-a")

        assert result.session_id == "session-1"
        assert result.subscribed is False
        assert result.error is None
        assert service.get_session_subscribers("session-1") == set()

    @pytest.mark.asyncio
    async def test_unsubscribe_requires_client_id(self, service):
        """Test that client_id is required for unsubscription."""
        result = await service.unsubscribe_session("session-1", "")

        assert result.subscribed is False
        assert result.error == "client_id is required"

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_subscription(self, service):
        """Test unsubscribing from a session not subscribed to."""
        result = await service.unsubscribe_session("session-1", "client-a")

        # Should succeed without error
        assert result.subscribed is False
        assert result.error is None

    @pytest.mark.asyncio
    async def test_get_subscriber_count(self, service):
        """Test getting subscriber count for a session."""
        assert await service.get_session_subscriber_count("session-1") == 0

        await service.subscribe_session("session-1", "client-a")
        assert await service.get_session_subscriber_count("session-1") == 1

        await service.subscribe_session("session-1", "client-b")
        assert await service.get_session_subscriber_count("session-1") == 2

        await service.unsubscribe_session("session-1", "client-a")
        assert await service.get_session_subscriber_count("session-1") == 1


class TestClientDisconnection:
    """Tests for client disconnection cleanup."""

    @pytest.fixture
    def service(self):
        return SessionDataService()

    @pytest.mark.asyncio
    async def test_client_disconnected_cleans_up_subscriptions(self, service):
        """Test that client disconnection removes all subscriptions."""
        await service.subscribe_session("session-1", "client-a")
        await service.subscribe_session("session-2", "client-a")
        await service.subscribe_session("session-1", "client-b")

        service.client_disconnected("client-a")

        # client-a's subscriptions should be cleaned up
        assert await service.get_subscribed_sessions("client-a") == []
        assert "client-a" not in service.get_session_subscribers("session-1")
        assert "client-a" not in service.get_session_subscribers("session-2")

        # client-b's subscription should still exist
        assert "client-b" in service.get_session_subscribers("session-1")

    @pytest.mark.asyncio
    async def test_client_disconnected_cleans_up_empty_session_sets(self, service):
        """Test that empty session subscriber sets are cleaned up."""
        await service.subscribe_session("session-1", "client-a")

        service.client_disconnected("client-a")

        # The session should no longer have an entry in _session_subscribers
        assert "session-1" not in service._session_subscribers

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
        """Test that turnCreated events target only subscribers."""
        events, handler = event_collector
        service.add_event_handler(handler)

        await service.subscribe_session("session-1", "client-a")
        await service.subscribe_session("session-1", "client-b")

        service.emit_turn_created("session-1", "turn-uuid-1", "user")

        assert len(events) == 1
        assert events[0]["event_name"] == "turnCreated"
        assert events[0]["target_clients"] == {"client-a", "client-b"}

    @pytest.mark.asyncio
    async def test_emit_turn_delta_targets_subscribers(
        self, service, event_collector
    ):
        """Test that turnDelta events target only subscribers."""
        events, handler = event_collector
        service.add_event_handler(handler)

        await service.subscribe_session("session-1", "client-a")

        service.emit_turn_delta("session-1", "turn-uuid-1", "Hello", 5)

        assert len(events) == 1
        assert events[0]["event_name"] == "turnDelta"
        assert events[0]["target_clients"] == {"client-a"}

    @pytest.mark.asyncio
    async def test_emit_turn_finished_targets_subscribers(
        self, service, event_collector
    ):
        """Test that turnFinished events target only subscribers."""
        events, handler = event_collector
        service.add_event_handler(handler)

        await service.subscribe_session("session-1", "client-a")
        await service.subscribe_session("session-1", "client-b")

        service.emit_turn_finished("session-1", "turn-uuid-1", "Hello, world!", 100)

        assert len(events) == 1
        assert events[0]["event_name"] == "turnFinished"
        assert events[0]["target_clients"] == {"client-a", "client-b"}

    @pytest.mark.asyncio
    async def test_no_event_emitted_when_no_subscribers(
        self, service, event_collector
    ):
        """Test that events are not emitted when no one is subscribed."""
        events, handler = event_collector
        service.add_event_handler(handler)

        # No subscribers for session-1
        service.emit_turn_created("session-1", "turn-uuid-1", "user")
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

        await service.subscribe_session("session-1", "client-a")
        await service.subscribe_session("session-2", "client-b")

        service.emit_turn_created("session-1", "turn-uuid-1", "user")

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

        await service.subscribe_session("session-1", "client-a")
        service.emit_turn_created("session-1", "turn-uuid-1", "user")

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
        await service.subscribe_session("session-1", "client-a")

        service.emit_turn_created(
            "session-1",
            turn_id="turn-uuid-5",
            role="assistant",
            exchange_id="exchange-123",
            content_block_type="code",
        )

        assert events[0] == {
            "session_id": "session-1",
            "turn_id": "turn-uuid-5",
            "role": "assistant",
            "exchange_id": "exchange-123",
            "content_block_type": "code",
        }

    @pytest.mark.asyncio
    async def test_turn_delta_event_data(self, service):
        """Test TurnDeltaEvent payload structure."""
        events = []

        def handler(event_name, data, target_clients):
            events.append(data)

        service.add_event_handler(handler)
        await service.subscribe_session("session-1", "client-a")

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
        }

    @pytest.mark.asyncio
    async def test_turn_finished_event_data(self, service):
        """Test TurnFinishedEvent payload structure."""
        events = []

        def handler(event_name, data, target_clients):
            events.append(data)

        service.add_event_handler(handler)
        await service.subscribe_session("session-1", "client-a")

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
        }


class TestSessionSnapshot:
    """Tests for get_session_snapshot and snapshot integration."""

    @pytest.fixture
    def tree_state(self):
        """Create a TreeState with test sessions."""
        return TreeState()

    @pytest.fixture
    def service_with_tree_state(self, tree_state):
        """Create service with TreeState wired up."""
        service = SessionDataService(tree_state=tree_state)
        return service

    @pytest.fixture
    def mock_session(self):
        """Create a mock Session object for TreeState."""
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
    async def test_get_session_snapshot_returns_none_without_tree_state(self):
        """Test that snapshot returns None when TreeState is not configured."""
        service = SessionDataService()  # No tree_state
        snapshot = await service.get_session_snapshot("session-1")
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_get_session_snapshot_returns_none_for_unknown_session(
        self, service_with_tree_state
    ):
        """Test that snapshot returns None for session not in TreeState."""
        snapshot = await service_with_tree_state.get_session_snapshot("unknown-session")
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_get_session_snapshot_returns_full_turn_history(
        self, service_with_tree_state, tree_state, mock_session
    ):
        """Test that snapshot includes all turns with correct data."""
        # Load session into TreeState
        tree_state.add_session(mock_session, is_current=True)
        tree_state.load_session(mock_session.id, mock_session)

        snapshot = await service_with_tree_state.get_session_snapshot(mock_session.id)

        assert snapshot is not None
        assert snapshot.session_id == mock_session.id
        assert snapshot.title == mock_session.title
        assert snapshot.model == mock_session.model
        assert len(snapshot.turns) == 5

        # Check first turn
        assert snapshot.turns[0].turn_id == "turn-uuid-1"
        assert snapshot.turns[0].idx == 0
        assert snapshot.turns[0].role == "user"
        assert snapshot.turns[0].content == "Hello"
        assert snapshot.turns[0].content_block_type == "text"
        assert snapshot.turns[0].exchange_id == "ex-1"

        # Check assistant turn
        assert snapshot.turns[1].turn_id == "turn-uuid-2"
        assert snapshot.turns[1].role == "assistant"
        assert snapshot.turns[1].content == "Hi there!"

        # Check tool_use turn
        assert snapshot.turns[3].turn_id == "turn-uuid-4"
        assert snapshot.turns[3].role == "assistant"
        assert snapshot.turns[3].content_block_type == "tool_use"

        # Check tool_result turn
        assert snapshot.turns[4].turn_id == "turn-uuid-5"
        assert snapshot.turns[4].role == "tool"
        assert snapshot.turns[4].content_block_type == "tool_result"

    @pytest.mark.asyncio
    async def test_snapshot_includes_context_mode(
        self, service_with_tree_state, tree_state, mock_session
    ):
        """Test that snapshot includes correct context modes."""
        tree_state.add_session(mock_session, is_current=True)
        tree_state.load_session(mock_session.id, mock_session)

        # Set a specific context mode
        tree_state.set_context_mode(mock_session.id, 1, ContextMode.DROP)

        snapshot = await service_with_tree_state.get_session_snapshot(mock_session.id)

        assert snapshot.turns[1].context_mode == "drop"

    @pytest.mark.asyncio
    async def test_snapshot_tracks_streaming_turns(
        self, service_with_tree_state, tree_state, mock_session
    ):
        """Test that snapshot identifies streaming turns."""
        tree_state.add_session(mock_session, is_current=True)
        tree_state.load_session(mock_session.id, mock_session)

        # Mark session as streaming and mark a turn as streaming
        tree_state.start_streaming(mock_session.id)
        session_data = tree_state.get_session(mock_session.id)
        session_data.turns[4].streaming = True

        snapshot = await service_with_tree_state.get_session_snapshot(mock_session.id)

        assert snapshot.is_streaming is True
        assert snapshot.current_turn_idx == 4
        assert "turn-uuid-5" in snapshot.streaming_turn_ids

    @pytest.mark.asyncio
    async def test_subscribe_session_returns_snapshot(
        self, service_with_tree_state, tree_state, mock_session
    ):
        """Test that subscribe_session returns snapshot with subscription."""
        tree_state.add_session(mock_session, is_current=True)
        tree_state.load_session(mock_session.id, mock_session)

        result = await service_with_tree_state.subscribe_session(
            mock_session.id, "client-a"
        )

        assert isinstance(result, SubscribeSessionResult)
        assert result.subscribed is True
        assert result.session_id == mock_session.id
        assert result.snapshot is not None
        assert len(result.snapshot.turns) == 5

    @pytest.mark.asyncio
    async def test_subscribe_session_snapshot_is_atomic(
        self, service_with_tree_state, tree_state, mock_session
    ):
        """Test that subscription and snapshot are atomic."""
        tree_state.add_session(mock_session, is_current=True)
        tree_state.load_session(mock_session.id, mock_session)

        result = await service_with_tree_state.subscribe_session(
            mock_session.id, "client-a"
        )

        # Client should be subscribed
        assert "client-a" in service_with_tree_state.get_session_subscribers(mock_session.id)
        # And have the snapshot
        assert result.snapshot is not None

    @pytest.mark.asyncio
    async def test_subscribe_session_still_works_without_tree_state(self):
        """Test that subscription works even without TreeState (no snapshot)."""
        service = SessionDataService()  # No tree_state

        result = await service.subscribe_session("session-1", "client-a")

        assert result.subscribed is True
        assert result.snapshot is None  # No snapshot without TreeState

    @pytest.mark.asyncio
    async def test_set_tree_state_enables_snapshots(self, tree_state, mock_session):
        """Test that set_tree_state enables snapshot loading."""
        service = SessionDataService()

        # Initially no snapshots
        snapshot = await service.get_session_snapshot(mock_session.id)
        assert snapshot is None

        # Wire up TreeState
        tree_state.add_session(mock_session, is_current=True)
        tree_state.load_session(mock_session.id, mock_session)
        service.set_tree_state(tree_state)

        # Now snapshots work
        snapshot = await service.get_session_snapshot(mock_session.id)
        assert snapshot is not None
        assert len(snapshot.turns) == 5


class TestSessionLoading:
    """Tests for session loading via session_loader callback."""

    @pytest.fixture
    def tree_state(self):
        return TreeState()

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
    async def test_session_loader_called_for_unloaded_session(
        self, tree_state, mock_session_for_loader
    ):
        """Test that session_loader is called when session not in TreeState."""
        loader_calls = []

        async def mock_loader(session_id: str):
            loader_calls.append(session_id)
            if session_id == mock_session_for_loader.id:
                return mock_session_for_loader
            return None

        service = SessionDataService(tree_state=tree_state, session_loader=mock_loader)

        # Session is not in TreeState yet
        snapshot = await service.get_session_snapshot(mock_session_for_loader.id)

        # Loader should have been called
        assert mock_session_for_loader.id in loader_calls
        # Snapshot should now exist
        assert snapshot is not None
        assert len(snapshot.turns) == 1
        assert snapshot.title == "Loaded Session"

    @pytest.mark.asyncio
    async def test_session_loader_not_called_for_loaded_session(
        self, tree_state, mock_session_for_loader
    ):
        """Test that session_loader is NOT called when session already loaded."""
        loader_calls = []

        async def mock_loader(session_id: str):
            loader_calls.append(session_id)
            return mock_session_for_loader

        # Pre-load the session
        tree_state.add_session(mock_session_for_loader, is_current=True)
        tree_state.load_session(mock_session_for_loader.id, mock_session_for_loader)

        service = SessionDataService(tree_state=tree_state, session_loader=mock_loader)

        # Session is already in TreeState
        snapshot = await service.get_session_snapshot(mock_session_for_loader.id)

        # Loader should NOT have been called
        assert len(loader_calls) == 0
        assert snapshot is not None

    @pytest.mark.asyncio
    async def test_snapshot_returns_none_when_loader_returns_none(self, tree_state):
        """Test that snapshot returns None when loader can't find session."""
        async def mock_loader(session_id: str):
            return None

        service = SessionDataService(tree_state=tree_state, session_loader=mock_loader)

        snapshot = await service.get_session_snapshot("nonexistent-session")
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_subscribe_loads_session_via_loader(
        self, tree_state, mock_session_for_loader
    ):
        """Test that subscribe_session uses loader when session not loaded."""
        async def mock_loader(session_id: str):
            if session_id == mock_session_for_loader.id:
                return mock_session_for_loader
            return None

        service = SessionDataService(tree_state=tree_state, session_loader=mock_loader)

        # Subscribe to unloaded session - should load via loader
        result = await service.subscribe_session(mock_session_for_loader.id, "client-a")

        assert result.subscribed is True
        assert result.snapshot is not None
        assert len(result.snapshot.turns) == 1


class TestTurnSnapshotFields:
    """Tests for TurnSnapshot field correctness."""

    @pytest.fixture
    def tree_state(self):
        return TreeState()

    @pytest.fixture
    def service(self, tree_state):
        return SessionDataService(tree_state=tree_state)

    @pytest.mark.asyncio
    async def test_turn_snapshot_has_all_required_fields(self, service, tree_state):
        """Test TurnSnapshot includes all required fields per acceptance criteria."""
        @dataclass
        class MockTurn:
            role: str = "user"
            content_block: TextBlock = field(default_factory=lambda: TextBlock(text="test"))
            context_mode: ContextMode = ContextMode.COPY
            exchange_id: str | None = "ex-1"
            id: str = "turn-id-abc"

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

        tree_state.add_session(session, is_current=True)
        tree_state.load_session(session.id, session)

        snapshot = await service.get_session_snapshot(session.id)
        turn = snapshot.turns[0]

        # Verify all required fields per acceptance criteria
        assert hasattr(turn, 'turn_id')
        assert hasattr(turn, 'idx')
        assert hasattr(turn, 'role')
        assert hasattr(turn, 'content')
        assert hasattr(turn, 'streaming')
        assert hasattr(turn, 'viewed')
        assert hasattr(turn, 'tokens')
        assert hasattr(turn, 'context_mode')
        assert hasattr(turn, 'content_block_type')
        assert hasattr(turn, 'exchange_id')

        # Verify correct values
        assert turn.turn_id == "turn-id-abc"
        assert turn.idx == 0
        assert turn.role == "user"
        assert turn.content == "test"
        assert turn.content_block_type == "text"
        assert turn.exchange_id == "ex-1"
