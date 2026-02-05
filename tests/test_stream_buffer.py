"""Tests for stream_buffer module."""

import pytest
from typing import Callable
from core.stream_buffer import StreamBuffer, Timer, TimerFactory


class MockTimer:
    """Mock timer for testing."""

    def __init__(self, callback: Callable[[], None]):
        self.callback = callback
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def fire(self) -> None:
        """Simulate timer firing (test helper)."""
        if not self.stopped:
            self.callback()


class MockTimerFactory:
    """Mock timer factory for testing."""

    def __init__(self):
        self.timers: list[MockTimer] = []
        self.last_delay: float | None = None

    def set_timer(self, delay: float, callback: Callable[[], None]) -> MockTimer:
        self.last_delay = delay
        timer = MockTimer(callback)
        self.timers.append(timer)
        return timer

    @property
    def active_timers(self) -> list[MockTimer]:
        """Return timers that haven't been stopped."""
        return [t for t in self.timers if not t.stopped]

    def fire_all(self) -> None:
        """Fire all active timers (test helper)."""
        for timer in self.active_timers:
            timer.fire()


class TestStreamBufferBasics:
    """Test basic stream buffer functionality."""

    def test_initial_state_empty(self):
        """Buffer starts empty with no timer."""
        factory = MockTimerFactory()
        flushed = []
        buffer = StreamBuffer(
            flush_callback=lambda t: flushed.append(t),
            timer_factory=factory,
        )

        assert buffer.pending_text == ""
        assert buffer.has_pending is False
        assert buffer.timer_active is False
        assert flushed == []

    def test_append_buffers_text(self):
        """Append accumulates text in buffer."""
        factory = MockTimerFactory()
        flushed = []
        buffer = StreamBuffer(
            flush_callback=lambda t: flushed.append(t),
            timer_factory=factory,
        )

        buffer.append("Hello ")
        assert buffer.pending_text == "Hello "
        assert buffer.has_pending is True

        buffer.append("world!")
        assert buffer.pending_text == "Hello world!"

    def test_append_starts_timer(self):
        """First append starts the flush timer."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        assert buffer.timer_active is False
        buffer.append("text")
        assert buffer.timer_active is True
        assert len(factory.timers) == 1

    def test_multiple_appends_single_timer(self):
        """Multiple appends don't create multiple timers."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        buffer.append("one ")
        buffer.append("two ")
        buffer.append("three")

        assert len(factory.timers) == 1
        assert buffer.pending_text == "one two three"

    def test_timer_uses_configured_interval(self):
        """Timer is created with the configured interval."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
            interval=0.1,
        )

        buffer.append("text")
        assert factory.last_delay == 0.1

    def test_default_interval(self):
        """Default interval is 50ms."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        buffer.append("text")
        assert factory.last_delay == 0.05


class TestStreamBufferFlushOnTimer:
    """Test automatic flushing when timer fires."""

    def test_timer_flushes_to_callback(self):
        """Timer firing calls flush_callback with accumulated text."""
        factory = MockTimerFactory()
        flushed = []
        buffer = StreamBuffer(
            flush_callback=lambda t: flushed.append(t),
            timer_factory=factory,
        )

        buffer.append("Hello ")
        buffer.append("world!")
        assert flushed == []

        factory.fire_all()
        assert flushed == ["Hello world!"]
        assert buffer.pending_text == ""
        assert buffer.has_pending is False

    def test_timer_clears_after_firing(self):
        """Timer reference is cleared after firing."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        buffer.append("text")
        assert buffer.timer_active is True

        factory.fire_all()
        assert buffer.timer_active is False

    def test_timer_with_empty_buffer_no_callback(self):
        """Timer firing with empty buffer doesn't call callback."""
        factory = MockTimerFactory()
        flushed = []
        buffer = StreamBuffer(
            flush_callback=lambda t: flushed.append(t),
            timer_factory=factory,
        )

        # Start timer then manually clear buffer
        buffer.append("text")
        buffer._pending_text = ""  # Simulate external clear

        factory.fire_all()
        assert flushed == []

    def test_append_after_timer_fires_starts_new_timer(self):
        """Appending after timer fires starts a new timer."""
        factory = MockTimerFactory()
        flushed = []
        buffer = StreamBuffer(
            flush_callback=lambda t: flushed.append(t),
            timer_factory=factory,
        )

        buffer.append("first ")
        factory.fire_all()
        assert flushed == ["first "]
        assert len(factory.timers) == 1

        buffer.append("second")
        assert buffer.timer_active is True
        assert len(factory.timers) == 2

        factory.fire_all()
        assert flushed == ["first ", "second"]


class TestStreamBufferManualFlush:
    """Test manual flush() method."""

    def test_flush_returns_pending_text(self):
        """flush() returns accumulated text."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        buffer.append("Hello ")
        buffer.append("world!")

        result = buffer.flush()
        assert result == "Hello world!"

    def test_flush_clears_buffer(self):
        """flush() clears the buffer."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        buffer.append("text")
        buffer.flush()

        assert buffer.pending_text == ""
        assert buffer.has_pending is False

    def test_flush_stops_timer(self):
        """flush() cancels the pending timer."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        buffer.append("text")
        assert buffer.timer_active is True

        buffer.flush()
        assert buffer.timer_active is False
        assert factory.timers[0].stopped is True

    def test_flush_does_not_call_callback(self):
        """flush() returns text directly, doesn't call callback."""
        factory = MockTimerFactory()
        flushed = []
        buffer = StreamBuffer(
            flush_callback=lambda t: flushed.append(t),
            timer_factory=factory,
        )

        buffer.append("text")
        result = buffer.flush()

        assert result == "text"
        assert flushed == []  # Callback not called

    def test_flush_empty_buffer(self):
        """flush() on empty buffer returns empty string."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        result = buffer.flush()
        assert result == ""

    def test_flush_without_timer(self):
        """flush() works even if no timer was started."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        # Manually set pending text without starting timer
        buffer._pending_text = "manual"

        result = buffer.flush()
        assert result == "manual"


class TestStreamBufferCancel:
    """Test cancel() method."""

    def test_cancel_stops_timer(self):
        """cancel() stops the pending timer."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        buffer.append("text")
        buffer.cancel()

        assert buffer.timer_active is False
        assert factory.timers[0].stopped is True

    def test_cancel_clears_buffer(self):
        """cancel() discards pending text."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        buffer.append("text")
        buffer.cancel()

        assert buffer.pending_text == ""
        assert buffer.has_pending is False

    def test_cancel_without_timer(self):
        """cancel() works even without active timer."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        buffer._pending_text = "text"  # Text without timer

        buffer.cancel()  # Should not raise
        assert buffer.pending_text == ""

    def test_cancel_idempotent(self):
        """Calling cancel() multiple times is safe."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        buffer.append("text")
        buffer.cancel()
        buffer.cancel()  # Should not raise

        assert buffer.pending_text == ""


class TestStreamBufferIntegration:
    """Integration-style tests for realistic usage patterns."""

    def test_streaming_scenario(self):
        """Simulate typical streaming text scenario."""
        factory = MockTimerFactory()
        flushed = []
        buffer = StreamBuffer(
            flush_callback=lambda t: flushed.append(t),
            timer_factory=factory,
            interval=0.05,
        )

        # Rapid text arrival
        buffer.append("The ")
        buffer.append("quick ")
        buffer.append("brown ")
        # Timer fires
        factory.fire_all()
        assert flushed == ["The quick brown "]

        # More text
        buffer.append("fox ")
        buffer.append("jumps")
        # Timer fires again
        factory.fire_all()
        assert flushed == ["The quick brown ", "fox jumps"]

        # Final flush on completion
        buffer.append(" over")
        remaining = buffer.flush()
        assert remaining == " over"
        # Total: "The quick brown " + "fox jumps" + " over" = full text

    def test_finish_streaming_flushes_remaining(self):
        """Finishing streaming flushes any remaining text."""
        factory = MockTimerFactory()
        flushed_via_callback = []
        buffer = StreamBuffer(
            flush_callback=lambda t: flushed_via_callback.append(t),
            timer_factory=factory,
        )

        buffer.append("partial")
        # Streaming ends before timer fires
        remaining = buffer.flush()

        assert remaining == "partial"
        assert flushed_via_callback == []  # Didn't go through callback

    def test_clear_during_streaming(self):
        """Clearing during streaming cancels and discards."""
        factory = MockTimerFactory()
        flushed = []
        buffer = StreamBuffer(
            flush_callback=lambda t: flushed.append(t),
            timer_factory=factory,
        )

        buffer.append("should be discarded")
        buffer.cancel()

        # Timer should not fire (it's stopped)
        factory.fire_all()  # Fires but timer was stopped

        assert flushed == []
        assert buffer.pending_text == ""

    def test_empty_text_append(self):
        """Appending empty string still works."""
        factory = MockTimerFactory()
        buffer = StreamBuffer(
            flush_callback=lambda t: None,
            timer_factory=factory,
        )

        buffer.append("")
        # Empty string starts timer but buffer is still ""
        assert buffer.timer_active is True
        assert buffer.pending_text == ""

        buffer.append("text")
        assert buffer.pending_text == "text"
