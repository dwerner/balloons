"""Tests for StreamState management."""

import pytest
import asyncio
from datetime import datetime, timedelta

from core.stream_state import (
    StreamState,
    Stream,
    StreamStatus,
    StreamType,
    StreamEvent,
    SessionStreamInfo,
    get_stream_state,
)


@pytest.fixture
def stream_state():
    """Get a fresh StreamState for each test."""
    state = StreamState()
    state.clear_all()  # Reset singleton state between tests
    # Reset observers too
    state._observers.clear()
    return state


class TestStreamRegistration:
    """Tests for registering streams."""

    def test_register_session_stream(self, stream_state):
        """Test registering a chat stream for a session."""
        stream = stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Hello, Claude!",
            backend_name="claude",
        )

        assert stream.stream_id == "exchange-1"
        assert stream.stream_type == StreamType.CHAT
        assert stream.status == StreamStatus.STREAMING
        assert stream.session_id == "session-1"
        assert stream.backend_name == "claude"
        assert stream.prompt == "Hello, Claude!"
        assert stream.is_active

    def test_register_helper_stream(self, stream_state):
        """Test registering a helper stream."""
        stream = stream_state.register_helper_stream(
            stream_id="helper-1",
            stream_type=StreamType.COMPRESSION,
            prompt="Compressing context...",
            session_id="session-1",
            backend_name="claude",
        )

        assert stream.stream_id == "helper-1"
        assert stream.stream_type == StreamType.COMPRESSION
        assert stream.status == StreamStatus.STREAMING
        assert stream.is_active

    def test_register_multiple_streams(self, stream_state):
        """Test registering multiple streams."""
        stream1 = stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="First prompt",
            backend_name="claude",
        )
        stream2 = stream_state.register_session_stream(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Second prompt",
            backend_name="openrouter",
        )

        all_streams = stream_state.get_all_streams()
        assert len(all_streams) == 2

        streaming = stream_state.get_streaming_streams()
        assert len(streaming) == 2


class TestStreamUpdates:
    """Tests for updating stream state."""

    def test_update_tokens_streamed(self, stream_state):
        """Test updating token count."""
        stream = stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        stream_state.update_stream("exchange-1", tokens_streamed=150)

        updated = stream_state.get_stream("exchange-1")
        assert updated.tokens_streamed == 150

    def test_update_tool_execution(self, stream_state):
        """Test updating tool execution state."""
        stream = stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        stream_state.update_stream(
            "exchange-1",
            status=StreamStatus.EXECUTING,
            tool_name="Read",
            tool_count=1,
        )

        updated = stream_state.get_stream("exchange-1")
        assert updated.status == StreamStatus.EXECUTING
        assert updated.tool_name == "Read"
        assert updated.tool_count == 1
        assert updated.is_active  # Still active during tool execution

    def test_complete_stream(self, stream_state):
        """Test completing a stream."""
        stream = stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        completed = stream_state.complete_stream("exchange-1")

        assert completed.status == StreamStatus.COMPLETED
        assert completed.finished_at is not None
        assert not completed.is_active

    def test_fail_stream(self, stream_state):
        """Test marking a stream as failed."""
        stream = stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        failed = stream_state.fail_stream("exchange-1", "Rate limit exceeded")

        assert failed.status == StreamStatus.ERROR
        assert failed.error == "Rate limit exceeded"
        assert not failed.is_active

    def test_cancel_stream(self, stream_state):
        """Test cancelling a stream."""
        stream = stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        cancelled = stream_state.cancel_stream("exchange-1")

        assert cancelled.status == StreamStatus.CANCELLED
        assert not cancelled.is_active


class TestStreamQueries:
    """Tests for querying streams."""

    def test_get_session_stream(self, stream_state):
        """Test getting the active stream for a session."""
        stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        active = stream_state.get_session_stream("session-1")
        assert active is not None
        assert active.stream_id == "exchange-1"

        # After completion, should return None
        stream_state.complete_stream("exchange-1")
        active = stream_state.get_session_stream("session-1")
        assert active is None

    def test_get_active_streams(self, stream_state):
        """Test getting all active streams."""
        stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test 1",
            backend_name="claude",
        )
        stream_state.register_session_stream(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Test 2",
            backend_name="claude",
        )

        # Complete one
        stream_state.complete_stream("exchange-1")

        active = stream_state.get_active_streams()
        assert len(active) == 1
        assert active[0].stream_id == "exchange-2"

    def test_get_streams_by_type(self, stream_state):
        """Test filtering streams by type."""
        stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Chat",
            backend_name="claude",
        )
        stream_state.register_helper_stream(
            stream_id="helper-1",
            stream_type=StreamType.COMPRESSION,
            prompt="Compress",
        )

        chat_streams = stream_state.get_streams_by_type(StreamType.CHAT)
        assert len(chat_streams) == 1

        compression_streams = stream_state.get_streams_by_type(StreamType.COMPRESSION)
        assert len(compression_streams) == 1

    def test_get_streams_by_backend(self, stream_state):
        """Test filtering streams by backend."""
        stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test 1",
            backend_name="claude",
        )
        stream_state.register_session_stream(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Test 2",
            backend_name="openrouter",
        )

        claude_streams = stream_state.get_streams_by_backend("claude")
        assert len(claude_streams) == 1
        assert claude_streams[0].stream_id == "exchange-1"


class TestSummaryMethods:
    """Tests for summary and count methods."""

    def test_get_streaming_count(self, stream_state):
        """Test counting streaming streams."""
        stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test 1",
            backend_name="claude",
        )
        stream_state.register_session_stream(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Test 2",
            backend_name="claude",
        )

        assert stream_state.get_streaming_count() == 2

        stream_state.complete_stream("exchange-1")
        assert stream_state.get_streaming_count() == 1

    def test_get_backend_summary(self, stream_state):
        """Test getting backend usage summary."""
        stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test 1",
            backend_name="claude",
        )
        stream_state.register_session_stream(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Test 2",
            backend_name="claude",
        )
        stream_state.register_session_stream(
            session_id="session-3",
            exchange_id="exchange-3",
            prompt="Test 3",
            backend_name="openrouter",
        )

        summary = stream_state.get_backend_summary()
        assert summary["claude"] == 2
        assert summary["openrouter"] == 1

    def test_get_session_summary(self, stream_state):
        """Test getting session stream summary."""
        stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="First prompt",
            backend_name="claude",
        )

        summary = stream_state.get_session_summary("session-1")

        assert summary.session_id == "session-1"
        assert summary.is_streaming
        assert summary.current_stream is not None
        assert summary.backend_name == "claude"

        # Complete the stream
        stream_state.complete_stream("exchange-1")

        summary = stream_state.get_session_summary("session-1")
        assert not summary.is_streaming
        assert summary.current_stream is None
        assert summary.total_exchanges == 1


class TestObservers:
    """Tests for the observer pattern."""

    async def test_async_observer_receives_events(self, stream_state):
        """Test that async observers receive stream events."""
        events_received = []

        async def observer(event: StreamEvent, stream: Stream):
            events_received.append((event, stream.stream_id))

        stream_state.add_observer(observer)

        stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )

        # Give event loop time to process
        await asyncio.sleep(0.01)

        assert len(events_received) == 1
        assert events_received[0][0] == StreamEvent.STREAM_STARTED
        assert events_received[0][1] == "exchange-1"

        stream_state.complete_stream("exchange-1")
        await asyncio.sleep(0.01)

        assert len(events_received) == 2
        assert events_received[1][0] == StreamEvent.STREAM_COMPLETED

    async def test_remove_observer(self, stream_state):
        """Test removing an observer."""
        events_received = []

        async def observer(event: StreamEvent, stream: Stream):
            events_received.append(event)

        stream_state.add_observer(observer)
        stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )
        await asyncio.sleep(0.01)
        assert len(events_received) == 1

        stream_state.remove_observer(observer)
        stream_state.complete_stream("exchange-1")
        await asyncio.sleep(0.01)
        assert len(events_received) == 1  # No new events


class TestCleanup:
    """Tests for cleanup methods."""

    def test_clear_completed_old_streams(self, stream_state):
        """Test clearing old completed streams."""
        stream = stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test",
            backend_name="claude",
        )
        stream_state.complete_stream("exchange-1")

        # Manually set finished_at to simulate old stream
        stream = stream_state.get_stream("exchange-1")
        stream.finished_at = datetime.now() - timedelta(seconds=400)

        # Clear streams older than 300 seconds
        removed = stream_state.clear_completed(max_age_seconds=300)

        assert removed == 1
        assert stream_state.get_stream("exchange-1") is None

    def test_clear_all(self, stream_state):
        """Test clearing all streams."""
        stream_state.register_session_stream(
            session_id="session-1",
            exchange_id="exchange-1",
            prompt="Test 1",
            backend_name="claude",
        )
        stream_state.register_session_stream(
            session_id="session-2",
            exchange_id="exchange-2",
            prompt="Test 2",
            backend_name="claude",
        )

        stream_state.clear_all()

        assert len(stream_state.get_all_streams()) == 0


class TestStreamProperties:
    """Tests for Stream dataclass properties."""

    def test_short_prompt(self):
        """Test prompt truncation."""
        short_stream = Stream(
            stream_id="1",
            stream_type=StreamType.CHAT,
            prompt="Short prompt",
        )
        assert short_stream.short_prompt == "Short prompt"

        long_prompt = "A" * 100
        long_stream = Stream(
            stream_id="2",
            stream_type=StreamType.CHAT,
            prompt=long_prompt,
        )
        assert len(long_stream.short_prompt) == 60
        assert long_stream.short_prompt.endswith("...")

    def test_duration_seconds(self):
        """Test duration calculation."""
        stream = Stream(
            stream_id="1",
            stream_type=StreamType.CHAT,
            started_at=datetime.now() - timedelta(seconds=10),
        )

        # Should be approximately 10 seconds (allow for test execution time)
        assert 9 <= stream.duration_seconds <= 12


class TestSingleton:
    """Tests for singleton behavior."""

    def test_get_stream_state_returns_singleton(self):
        """Test that get_stream_state returns the same instance."""
        state1 = get_stream_state()
        state2 = get_stream_state()
        assert state1 is state2

    def test_streamstate_is_singleton(self):
        """Test that StreamState() returns the same instance."""
        state1 = StreamState()
        state2 = StreamState()
        assert state1 is state2
