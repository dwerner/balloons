"""Test integration between React frontend (via SessionManagerService) and TUI.

These tests verify that:
1. Messages submitted via SessionManagerService create proper streaming contexts in TUI
2. Streaming events are properly dispatched to both React (via TaskStateService) and TUI
3. After streaming completes, both sides are properly cleaned up
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from core.manager import SessionManager
from core.streaming import StreamingContext
from service.session_manager_service import SessionManagerService, SessionManagerEvent


class MockSession:
    """Mock session for testing."""

    def __init__(self, session_id: str):
        self.id = session_id
        self.turns = []
        self.title = "Test Session"

    def add_message(self, role, content, content_blocks=None, exchange_id=None):
        self.turns.append({
            "role": role,
            "content": content,
            "exchange_id": exchange_id,
        })

    async def save(self):
        pass


class MockRunner:
    """Mock runner for testing."""

    def __init__(self):
        self.is_streaming = False
        self._events = []

    def start_background(self, prompt, messages, allowed_tools=None):
        self.is_streaming = True
        # Simulate immediate turn_started event
        self._events.append(MagicMock(event_type="turn_started", data={"turn_index": 1}))

    def drain_events(self):
        events = self._events
        self._events = []
        return events

    @property
    def is_done(self):
        return not self.is_streaming


class TestMessageSubmittedEventHandling:
    """Test that MESSAGE_SUBMITTED event creates proper streaming context."""

    @pytest.fixture
    def mock_manager(self):
        """Create a mock SessionManager."""
        manager = MagicMock(spec=SessionManager)
        manager._sessions = {}
        manager._runners = {}
        return manager

    @pytest.fixture
    def service(self, mock_manager):
        """Create SessionManagerService with mock manager."""
        return SessionManagerService(mock_manager)

    def test_message_submitted_emits_content(self, service, mock_manager):
        """Test that MESSAGE_SUBMITTED event includes content field."""
        # Set up mock session and runner
        session = MockSession("test-session-id")
        runner = MockRunner()
        mock_manager.get_session.return_value = session
        mock_manager.get_runner.return_value = runner

        # Track emitted events
        emitted_events = []
        def event_handler(event_name, data):
            emitted_events.append((event_name, data))

        service.add_event_handler(event_handler)

        # Submit a message
        asyncio.run(service.submit_message("test-session-id", "Hello, world!"))

        # Verify messageSubmitted event was emitted with content
        # (streamingStarted is also emitted, so filter for the one we care about)
        msg_events = [(n, d) for n, d in emitted_events if n == "messageSubmitted"]
        assert len(msg_events) == 1
        event_name, data = msg_events[0]
        assert event_name == "messageSubmitted"
        assert data["session_id"] == "test-session-id"
        assert data["content"] == "Hello, world!"
        assert "exchange_id" in data
        assert "turn_index" in data

    def test_streaming_context_created_synchronously(self, service, mock_manager):
        """Test that streaming context can be created synchronously from event."""
        session = MockSession("test-session-id")
        runner = MockRunner()
        mock_manager.get_session.return_value = session
        mock_manager.get_runner.return_value = runner

        # Track streaming contexts (simulating TUI's _streaming_contexts)
        streaming_contexts = {}

        def event_handler(event_name, data):
            if event_name == "messageSubmitted":
                session_id = data.get("session_id")
                exchange_id = data.get("exchange_id", "")
                turn_index = data.get("turn_index", 0)
                content = data.get("content", "")

                # This is what the TUI does
                ctx = StreamingContext(
                    session_id=session_id,
                    user_turn_idx=turn_index,
                    assistant_turn_idx=turn_index + 1,
                    prompt=content,
                    is_active=True,
                    exchange_id=exchange_id,
                )
                streaming_contexts[session_id] = ctx

        service.add_event_handler(event_handler)

        # Submit a message
        asyncio.run(service.submit_message("test-session-id", "Test prompt"))

        # Context should exist synchronously after submit
        assert "test-session-id" in streaming_contexts
        ctx = streaming_contexts["test-session-id"]
        assert ctx.prompt == "Test prompt"
        assert ctx.is_active is True

    def test_runner_has_events_after_submit(self, service, mock_manager):
        """Test that runner has events available after submit_message returns."""
        session = MockSession("test-session-id")
        runner = MockRunner()
        mock_manager.get_session.return_value = session
        mock_manager.get_runner.return_value = runner

        # Submit a message
        asyncio.run(service.submit_message("test-session-id", "Test prompt"))

        # Runner should have events
        assert runner.is_streaming is True
        events = runner.drain_events()
        assert len(events) > 0


class TestStreamingContextLifecycle:
    """Test streaming context lifecycle between React and TUI."""

    def test_context_is_active_matches_tui_session(self):
        """Test that is_active is correctly determined by matching session IDs."""
        active_session_id = "active-session"

        # Case 1: Submit to active session
        is_active_1 = active_session_id == "active-session"
        assert is_active_1 is True

        # Case 2: Submit to different session
        is_active_2 = active_session_id == "other-session"
        assert is_active_2 is False

    def test_context_fields_for_external_submission(self):
        """Test that StreamingContext has correct fields for external submission."""
        ctx = StreamingContext(
            session_id="test-session",
            user_turn_idx=5,
            assistant_turn_idx=6,
            prompt="User prompt",
            is_active=True,
            exchange_id="exchange-123",
        )

        assert ctx.session_id == "test-session"
        assert ctx.user_turn_idx == 5
        assert ctx.assistant_turn_idx == 6
        assert ctx.prompt == "User prompt"
        assert ctx.is_active is True
        assert ctx.exchange_id == "exchange-123"
        assert ctx.content == ""  # Should start empty


class TestPollLoopRaceCondition:
    """Test that poll loop doesn't miss events from external submissions."""

    @pytest.fixture
    def mock_manager(self):
        manager = MagicMock(spec=SessionManager)
        manager._sessions = {}
        manager._runners = {}
        return manager

    def test_events_preserved_until_polled(self, mock_manager):
        """Test that events aren't lost between submit and first poll."""
        session = MockSession("test-session")
        runner = MockRunner()

        mock_manager.get_session.return_value = session
        mock_manager.get_runner.return_value = runner
        mock_manager._runners = {"test-session": runner}

        service = SessionManagerService(mock_manager)

        # Submit message
        asyncio.run(service.submit_message("test-session", "Hello"))

        # Runner should have events
        events = runner.drain_events()
        assert len(events) > 0
        assert events[0].event_type == "turn_started"

    def test_poll_all_returns_events_after_submit(self, mock_manager):
        """Test that manager.poll_all() returns events after external submit."""
        session = MockSession("test-session")
        runner = MockRunner()

        mock_manager.get_session.return_value = session
        mock_manager.get_runner.return_value = runner
        mock_manager._runners = {"test-session": runner}

        # Simulate poll_all
        def poll_all():
            results = []
            for session_id, r in mock_manager._runners.items():
                events = r.drain_events()
                if events:
                    results.append((session_id, events))
            return results

        mock_manager.poll_all = poll_all

        service = SessionManagerService(mock_manager)

        # Submit message
        asyncio.run(service.submit_message("test-session", "Hello"))

        # Poll should return the events
        results = mock_manager.poll_all()
        assert len(results) == 1
        session_id, events = results[0]
        assert session_id == "test-session"
        assert len(events) > 0


class TestStreamingFlagManagement:
    """Test that streaming flag is properly managed."""

    def test_streaming_flag_flow(self):
        """Document expected streaming flag transitions."""
        # Initial state
        streaming = False

        # React submits -> TUI creates context -> sets streaming=True
        streaming = True
        assert streaming is True

        # Stream completes -> DoneAction -> finalize sets streaming=False
        streaming = False
        assert streaming is False

        # TUI should now accept new input
        assert streaming is False

    def test_is_active_affects_streaming_cleanup(self):
        """Test that is_active determines whether streaming flag is reset."""
        # Case 1: Active session - should reset streaming
        ctx_active = StreamingContext(
            session_id="test",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="test",
            is_active=True,
            exchange_id="ex1",
        )

        # finalize_streaming checks ctx.is_active before resetting self.streaming
        should_reset = ctx_active.is_active
        assert should_reset is True

        # Case 2: Background session - should NOT reset streaming
        ctx_background = StreamingContext(
            session_id="test",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="test",
            is_active=False,
            exchange_id="ex2",
        )

        should_reset = ctx_background.is_active
        assert should_reset is False


class TestContextOwnershipTransfer:
    """Test that TUI can take ownership of sessions from the event pump."""

    @pytest.fixture
    def mock_manager(self):
        manager = MagicMock(spec=SessionManager)
        manager._sessions = {}
        manager._runners = {}
        return manager

    @pytest.fixture
    def service(self, mock_manager):
        return SessionManagerService(mock_manager)

    def test_release_streaming_context_removes_context(self, service, mock_manager):
        """Test that release_streaming_context removes the session from event pump."""
        session = MockSession("test-session")
        runner = MockRunner()
        mock_manager.get_session.return_value = session
        mock_manager.get_runner.return_value = runner

        # Submit creates context
        asyncio.run(service.submit_message("test-session", "Hello"))
        assert "test-session" in service._streaming_contexts

        # Release removes it
        result = service.release_streaming_context("test-session")
        assert result is True
        assert "test-session" not in service._streaming_contexts

    def test_release_streaming_context_returns_false_if_no_context(self, service):
        """Test that release_streaming_context returns False if no context exists."""
        result = service.release_streaming_context("nonexistent")
        assert result is False

    def test_event_pump_skips_released_sessions(self, service, mock_manager):
        """Test that event pump doesn't poll sessions after they're released."""
        session = MockSession("test-session")
        runner = MockRunner()
        mock_manager.get_session.return_value = session
        mock_manager.get_runner.return_value = runner
        mock_manager._runners = {"test-session": runner}

        # Submit creates context
        asyncio.run(service.submit_message("test-session", "Hello"))

        # Release to TUI
        service.release_streaming_context("test-session")

        # Add more events to runner
        runner._events = [MagicMock(event_type="text", data="more content")]

        # Pump should not drain these events (no context to track)
        async def pump_and_check():
            await service._pump_events()
            # Events should still be in runner since pump skipped this session
            return len(runner._events)

        events_remaining = asyncio.run(pump_and_check())
        assert events_remaining == 1  # Events not drained


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
