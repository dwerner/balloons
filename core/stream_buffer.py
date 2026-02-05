"""Stream buffer - manages rate-limited text streaming.

This module separates text buffering and rate-limiting from the ChatLogView widget,
enabling:
- Unit testing without Textual timers
- Clear separation of buffering logic from UI updates
- Reusable rate-limiting for other streaming scenarios
"""

from typing import Protocol, Callable, Any


class Timer(Protocol):
    """Protocol for a timer that can be stopped."""

    def stop(self) -> None:
        """Cancel the timer."""
        ...


class TimerFactory(Protocol):
    """Protocol for creating timers.

    This abstraction allows testing without Textual's set_timer.
    """

    def set_timer(self, delay: float, callback: Callable[[], None]) -> Timer:
        """Create a timer that calls callback after delay seconds."""
        ...


class StreamBuffer:
    """Manages rate-limited text buffering for streaming content.

    Text is accumulated in a buffer and flushed at a controlled rate to reduce
    UI refresh overhead during fast streaming.

    Usage:
        buffer = StreamBuffer(
            flush_callback=lambda text: widget.append_text(text),
            timer_factory=my_timer_factory,
            interval=0.05,  # 50ms = 20 flushes/sec max
        )

        # When text arrives (may be called rapidly):
        buffer.append("Hello ")
        buffer.append("world!")

        # Timer fires and calls flush_callback with accumulated text

        # When done streaming:
        remaining = buffer.flush()  # Immediate flush, returns any remaining text

        # On cleanup:
        buffer.cancel()  # Cancel timer and clear buffer
    """

    # Default update interval: 50ms = 20 updates/sec max
    DEFAULT_INTERVAL = 0.05

    def __init__(
        self,
        flush_callback: Callable[[str], None],
        timer_factory: TimerFactory,
        interval: float = DEFAULT_INTERVAL,
    ):
        """Initialize the stream buffer.

        Args:
            flush_callback: Called with accumulated text when timer fires.
                           Should handle the actual UI update.
            timer_factory: Factory for creating timers (typically the Textual widget).
            interval: Minimum time between flushes in seconds.
        """
        self._flush_callback = flush_callback
        self._timer_factory = timer_factory
        self._interval = interval

        self._pending_text: str = ""
        self._timer: Timer | None = None

    @property
    def pending_text(self) -> str:
        """The currently buffered text (read-only for testing)."""
        return self._pending_text

    @property
    def has_pending(self) -> bool:
        """Whether there is text waiting to be flushed."""
        return bool(self._pending_text)

    @property
    def timer_active(self) -> bool:
        """Whether a flush timer is currently running."""
        return self._timer is not None

    def append(self, text: str) -> None:
        """Buffer text for rate-limited flushing.

        Text is accumulated and will be flushed when the timer fires.
        If no timer is running, one is started.

        Args:
            text: Text to buffer.
        """
        self._pending_text += text

        # Start timer if not already running
        if self._timer is None:
            self._timer = self._timer_factory.set_timer(
                self._interval,
                self._on_timer,
            )

    def _on_timer(self) -> None:
        """Internal callback when flush timer fires."""
        self._timer = None

        if not self._pending_text:
            return

        text_to_flush = self._pending_text
        self._pending_text = ""

        self._flush_callback(text_to_flush)

    def flush(self) -> str:
        """Immediately flush and return buffered text.

        Cancels any pending timer. Returns the buffered text (may be empty).
        The flush_callback is NOT called - caller receives the text directly.

        Returns:
            The buffered text that was waiting to be flushed.
        """
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

        text = self._pending_text
        self._pending_text = ""
        return text

    def cancel(self) -> None:
        """Cancel pending timer and discard buffered text.

        Use this for cleanup when the buffer is no longer needed.
        """
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._pending_text = ""
