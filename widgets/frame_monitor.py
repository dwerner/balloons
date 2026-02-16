"""Frame rate monitoring widget for Balloons TUI.

Provides real-time FPS display, dropped frame detection, and render timing.
Enable with :debug-fps toggle command.

The widget uses a high-frequency timer to measure event loop responsiveness.
When the event loop is blocked (UI jank), the timer callbacks are delayed,
which we detect as "slow frames" or "dropped frames".
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from textual.widgets import Static
from textual.containers import Container
from textual.reactive import reactive
from textual.timer import Timer
from rich.text import Text

from core.debug_log import debug_log


# Target frame time for 60 FPS (in seconds)
TARGET_FRAME_TIME = 1.0 / 60.0  # ~16.67ms

# Threshold for "slow frame" warning (ms)
SLOW_FRAME_THRESHOLD_MS = 50.0

# Threshold for logging slow frames to debug log (ms)
LOG_SLOW_FRAME_THRESHOLD_MS = 1000.0  # 1 second - only log really bad jank

# Threshold for "dropped frame" (missed 2+ frame intervals)
DROPPED_FRAME_THRESHOLD = TARGET_FRAME_TIME * 2

# Timer interval for frame sampling (seconds)
# Using 1/60 = ~16.67ms for 60fps target
SAMPLE_INTERVAL = 1.0 / 60.0


@dataclass
class FrameSample:
    """Statistics for a single frame sample."""
    timestamp: float  # When the sample was taken
    interval_ms: float  # Time since last sample


class FrameMonitor:
    """Singleton frame rate monitor.

    Uses timer-based sampling to measure event loop responsiveness.
    When the event loop is blocked, timer callbacks are delayed,
    which we detect as jank.
    """

    _instance: "FrameMonitor | None" = None

    # Keep last N samples for FPS calculation
    HISTORY_SIZE = 120  # 2 seconds at 60fps for short-term stats

    # Keep 1 minute of history for histogram (60fps * 60 seconds = 3600)
    HISTOGRAM_HISTORY_SIZE = 3600

    def __new__(cls) -> "FrameMonitor":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        """Initialize the monitor state."""
        self._sample_history: deque[FrameSample] = deque(maxlen=self.HISTORY_SIZE)
        # Longer history for 1-minute histogram
        self._histogram_history: deque[FrameSample] = deque(maxlen=self.HISTOGRAM_HISTORY_SIZE)
        self._last_sample_time: float = 0.0
        self._dropped_frames: int = 0
        self._total_samples: int = 0
        self._enabled: bool = False
        self._listeners: list[Callable[[], None]] = []
        self._slow_frame_logged_at: float = 0.0  # Debounce slow frame logging

    @property
    def enabled(self) -> bool:
        """Whether frame monitoring is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Enable or disable frame monitoring."""
        if value and not self._enabled:
            # Reset stats when enabling
            self._sample_history.clear()
            self._histogram_history.clear()
            self._dropped_frames = 0
            self._total_samples = 0
            self._last_sample_time = 0.0
        self._enabled = value

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Add a listener to be notified after each sample."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[], None]) -> None:
        """Remove a listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def record_sample(self) -> None:
        """Record a frame sample (called by timer).

        Measures the interval since the last sample. If the interval
        is longer than expected, it indicates the event loop was blocked.
        """
        if not self._enabled:
            return

        now = time.perf_counter()

        if self._last_sample_time > 0:
            interval_ms = (now - self._last_sample_time) * 1000

            # Record the sample
            sample = FrameSample(
                timestamp=now,
                interval_ms=interval_ms,
            )
            self._sample_history.append(sample)
            self._histogram_history.append(sample)
            self._total_samples += 1

            # Check for dropped frames (interval > 2x expected)
            expected_ms = SAMPLE_INTERVAL * 1000
            if interval_ms > expected_ms * 2:
                # Estimate how many frames were "dropped"
                dropped = int(interval_ms / expected_ms) - 1
                self._dropped_frames += dropped

            # Log very slow frames (debounced)
            if interval_ms > LOG_SLOW_FRAME_THRESHOLD_MS:
                if now - self._slow_frame_logged_at > 5.0:  # Max once per 5 seconds
                    self._slow_frame_logged_at = now
                    debug_log.warning(
                        f"UI jank detected: {interval_ms:.0f}ms gap in event loop",
                        category="perf",
                        details={
                            "interval_ms": interval_ms,
                            "expected_ms": expected_ms,
                            "fps": self.current_fps,
                        },
                    )

        self._last_sample_time = now

        # Notify listeners
        for listener in self._listeners:
            try:
                listener()
            except Exception:
                pass

    @property
    def current_fps(self) -> float:
        """Calculate current FPS from recent sample history.

        FPS is calculated as the inverse of average frame interval.
        """
        if len(self._sample_history) < 2:
            return 0.0

        # Calculate average interval from recent samples
        samples = list(self._sample_history)[-30:]  # Use last 30 samples (~0.5s)
        if len(samples) < 2:
            return 0.0

        avg_interval_ms = sum(s.interval_ms for s in samples) / len(samples)
        if avg_interval_ms <= 0:
            return 0.0

        return 1000.0 / avg_interval_ms

    @property
    def average_frame_time_ms(self) -> float:
        """Average frame time (interval) in milliseconds."""
        if not self._sample_history:
            return 0.0
        samples = list(self._sample_history)[-30:]
        return sum(s.interval_ms for s in samples) / len(samples)

    @property
    def max_frame_time_ms(self) -> float:
        """Maximum frame interval in recent history."""
        if not self._sample_history:
            return 0.0
        samples = list(self._sample_history)[-30:]
        return max(s.interval_ms for s in samples)

    @property
    def dropped_frames(self) -> int:
        """Number of dropped frames detected."""
        return self._dropped_frames

    @property
    def total_samples(self) -> int:
        """Total samples recorded since monitoring started."""
        return self._total_samples

    def get_sparkline_data(self, width: int = 20) -> list[float]:
        """Get frame intervals normalized for sparkline display.

        Returns list of values from 0.0 to 1.0 representing frame intervals
        relative to SLOW_FRAME_THRESHOLD_MS.
        """
        if not self._sample_history:
            return []

        # Get last `width` samples
        samples = list(self._sample_history)[-width:]

        # Normalize to 0-1 range (capped at slow threshold)
        return [min(1.0, s.interval_ms / SLOW_FRAME_THRESHOLD_MS) for s in samples]

    def get_histogram_data(self, buckets: int = 20, max_seconds: float = 60.0) -> tuple[list[int], list[str]]:
        """Get histogram of frame times over the last minute.

        Buckets frame times into ranges and counts how many fall into each.
        Returns (counts, labels) where counts[i] is the count for bucket i
        and labels[i] is the bucket label (e.g., "0-16ms").

        Args:
            buckets: Number of histogram buckets
            max_seconds: Only include samples from the last N seconds

        Returns:
            Tuple of (counts list, labels list)
        """
        if not self._histogram_history:
            return [], []

        now = time.perf_counter()
        cutoff = now - max_seconds

        # Filter to last N seconds
        samples = [s for s in self._histogram_history if s.timestamp >= cutoff]
        if not samples:
            return [], []

        # Define bucket boundaries (ms)
        # Logarithmic-ish buckets: 0-16, 16-33, 33-50, 50-100, 100-200, 200-500, 500-1000, 1000+
        bucket_boundaries = [0, 16, 33, 50, 100, 200, 500, 1000, float('inf')]
        bucket_labels = ["<16", "16-33", "33-50", "50-100", "100-200", "200-500", "500-1k", ">1k"]

        # Count samples in each bucket
        counts = [0] * len(bucket_labels)
        for sample in samples:
            ms = sample.interval_ms
            for i in range(len(bucket_boundaries) - 1):
                if bucket_boundaries[i] <= ms < bucket_boundaries[i + 1]:
                    counts[i] += 1
                    break

        return counts, bucket_labels

    def get_histogram_sparkline(self, width: int = 20, max_seconds: float = 60.0) -> list[float]:
        """Get histogram data as normalized values for sparkline rendering.

        Groups the last minute of samples into `width` time buckets,
        and returns the max frame time in each bucket normalized 0-1.

        This shows a "worst case" view over time - where were the spikes?

        Args:
            width: Number of time buckets
            max_seconds: Time window in seconds

        Returns:
            List of normalized values (0.0 to 1.0), one per time bucket
        """
        if not self._histogram_history:
            return []

        now = time.perf_counter()
        cutoff = now - max_seconds

        # Filter to last N seconds
        samples = [s for s in self._histogram_history if s.timestamp >= cutoff]
        if not samples:
            return []

        # Divide time window into buckets
        bucket_duration = max_seconds / width
        buckets: list[list[float]] = [[] for _ in range(width)]

        for sample in samples:
            # Which bucket does this sample fall into?
            age = now - sample.timestamp  # seconds ago
            bucket_idx = int((max_seconds - age) / bucket_duration)
            bucket_idx = max(0, min(width - 1, bucket_idx))
            buckets[bucket_idx].append(sample.interval_ms)

        # Get max frame time per bucket, normalized
        result = []
        for bucket in buckets:
            if bucket:
                max_ms = max(bucket)
                # Normalize: 16ms = 0.0 (ideal), 100ms+ = 1.0 (bad)
                normalized = min(1.0, (max_ms - 16) / 84)  # 16ms to 100ms range
                normalized = max(0.0, normalized)
            else:
                normalized = 0.0  # No samples = assume good
            result.append(normalized)

        return result


# Module-level singleton access
_frame_monitor: FrameMonitor | None = None


def get_frame_monitor() -> FrameMonitor:
    """Get the global frame monitor instance."""
    global _frame_monitor
    if _frame_monitor is None:
        _frame_monitor = FrameMonitor()
    return _frame_monitor


# Sparkline characters (from empty to full)
SPARKLINE_CHARS = " ▁▂▃▄▅▆▇█"


def render_sparkline(values: list[float], width: int = 20) -> Text:
    """Render a sparkline from normalized values (0.0-1.0).

    Colors: green (good), yellow (warning), red (slow)
    """
    text = Text()

    for value in values[-width:]:
        # Clamp to 0-1
        value = max(0.0, min(1.0, value))

        # Select character based on value
        char_idx = int(value * (len(SPARKLINE_CHARS) - 1))
        char = SPARKLINE_CHARS[char_idx]

        # Color based on value
        if value < 0.3:
            style = "green"
        elif value < 0.6:
            style = "yellow"
        else:
            style = "red"

        text.append(char, style=style)

    # Pad to width if needed
    if len(values) < width:
        text = Text(" " * (width - len(values))) + text

    return text


class _FrameMonitorDisplay(Static):
    """The actual frame monitor display widget."""

    DEFAULT_CSS = """
    _FrameMonitorDisplay {
        background: $surface 90%;
        border: solid $primary-darken-2;
        padding: 0 1;
        width: auto;
        height: auto;
    }
    """

    # Reactive to trigger re-render on stats update
    fps: reactive[float] = reactive(0.0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._monitor = get_frame_monitor()
        self._sample_timer: Timer | None = None
        self._display_timer: Timer | None = None
        self._sample_count: int = 0

    def on_mount(self) -> None:
        """Start frame sampling when mounted."""
        pass  # Timer started by toggle()

    def on_unmount(self) -> None:
        """Stop frame sampling when unmounted."""
        self._stop_timer()

    def _start_timer(self) -> None:
        """Start the high-frequency sampling timer and slower display timer."""
        if self._sample_timer is None:
            # Sample at 60fps for accurate measurements
            self._sample_timer = self.set_interval(
                SAMPLE_INTERVAL,
                self._on_sample,
                name="frame_sample",
            )
        if self._display_timer is None:
            # Update display at 4Hz (every 250ms) for stable readout
            self._display_timer = self.set_interval(
                0.25,
                self._update_display,
                name="frame_display",
            )

    def _stop_timer(self) -> None:
        """Stop the sampling and display timers."""
        if self._sample_timer is not None:
            self._sample_timer.stop()
            self._sample_timer = None
        if self._display_timer is not None:
            self._display_timer.stop()
            self._display_timer = None

    def _on_sample(self) -> None:
        """Called at 60fps - record sample."""
        self._monitor.record_sample()

    def _update_display(self) -> None:
        """Called at 4Hz - update the display."""
        # Trigger re-render by updating reactive
        self.fps = self._monitor.current_fps

    def render(self) -> Text:
        """Render the frame statistics display."""
        text = Text()

        # FPS with color coding
        fps = self._monitor.current_fps
        if fps >= 50:
            fps_style = "green"
        elif fps >= 30:
            fps_style = "yellow"
        else:
            fps_style = "red"

        text.append(f"{fps:5.1f}", style=f"bold {fps_style}")
        text.append(" fps ", style="dim")

        # Average frame time
        avg_ms = self._monitor.average_frame_time_ms
        text.append(f"{avg_ms:5.1f}", style="cyan")
        text.append("ms ", style="dim")

        # Dropped frames
        dropped = self._monitor.dropped_frames
        if dropped > 0:
            text.append(f"↓{dropped}", style="red")
            text.append(" ", style="dim")

        # Recent sparkline (last ~3 seconds, 20 chars)
        text.append("now:", style="dim")
        sparkline = render_sparkline(self._monitor.get_sparkline_data(20), width=20)
        text.append(sparkline)

        # 1-minute histogram sparkline (40 chars)
        text.append(" 1m:", style="dim")
        hist_sparkline = render_sparkline(self._monitor.get_histogram_sparkline(40, max_seconds=60.0), width=40)
        text.append(hist_sparkline)

        return text


class FrameMonitorWidget(Container):
    """Floating overlay container for frame rate statistics.

    Displays:
    - Current FPS (with color coding)
    - Average frame time
    - Dropped frame count
    - Sparkline of recent frame times + 1-minute histogram

    The widget runs a high-frequency timer to sample the event loop.
    When the event loop is blocked (UI jank), timer callbacks are delayed,
    which shows up as low FPS and long frame times in the display.

    Toggle visibility with :debug-fps command.
    """

    DEFAULT_CSS = """
    FrameMonitorWidget {
        /* Floating overlay at top-right */
        layer: _fps_overlay;
        width: 100%;
        height: auto;
        align: right top;
        display: none;
    }

    FrameMonitorWidget.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._display: _FrameMonitorDisplay | None = None

    def compose(self):
        """Create the display widget."""
        self._display = _FrameMonitorDisplay()
        yield self._display

    def toggle(self) -> None:
        """Toggle visibility and enable/disable monitoring."""
        if self.has_class("visible"):
            self.remove_class("visible")
            if self._display:
                self._display._monitor.enabled = False
                self._display._stop_timer()
        else:
            self.add_class("visible")
            if self._display:
                self._display._monitor.enabled = True
                self._display._start_timer()
