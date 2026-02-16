"""Tests for frame rate monitoring widget."""

import time
import pytest

from widgets.frame_monitor import (
    FrameMonitor,
    get_frame_monitor,
    render_sparkline,
    SLOW_FRAME_THRESHOLD_MS,
)


class TestFrameMonitor:
    """Tests for FrameMonitor class."""

    def setup_method(self):
        """Reset the monitor singleton before each test."""
        monitor = get_frame_monitor()
        monitor._init()  # Reset state
        monitor.enabled = False

    def test_singleton_pattern(self):
        """Test that get_frame_monitor returns singleton."""
        m1 = get_frame_monitor()
        m2 = get_frame_monitor()
        assert m1 is m2

    def test_disabled_by_default(self):
        """Test that monitoring is disabled by default."""
        monitor = get_frame_monitor()
        assert not monitor.enabled

    def test_enable_resets_stats(self):
        """Test that enabling monitoring resets statistics."""
        monitor = get_frame_monitor()
        monitor.enabled = True

        # Record some samples
        for _ in range(5):
            monitor.record_sample()
            time.sleep(0.01)

        assert monitor.total_samples > 0

        # Disable and re-enable
        monitor.enabled = False
        monitor.enabled = True

        assert monitor.total_samples == 0
        assert monitor.dropped_frames == 0

    def test_record_sample_tracks_count(self):
        """Test that samples are counted."""
        monitor = get_frame_monitor()
        monitor.enabled = True

        for _ in range(10):
            monitor.record_sample()
            time.sleep(0.01)

        # First sample doesn't count (no previous time)
        assert monitor.total_samples == 9

    def test_fps_calculation(self):
        """Test FPS is calculated from sample intervals."""
        monitor = get_frame_monitor()
        monitor.enabled = True

        # Record samples at ~60fps (16.67ms intervals)
        for _ in range(30):
            monitor.record_sample()
            time.sleep(0.0167)

        # FPS should be roughly 60 (allow some variance)
        fps = monitor.current_fps
        assert 50 < fps < 70, f"Expected ~60 fps, got {fps}"

    def test_dropped_frame_detection(self):
        """Test that long gaps are detected as dropped frames."""
        monitor = get_frame_monitor()
        monitor.enabled = True

        # Record normal samples
        for _ in range(5):
            monitor.record_sample()
            time.sleep(0.016)

        # Simulate jank (100ms gap = ~6 frames at 60fps)
        time.sleep(0.1)
        monitor.record_sample()

        # Should detect dropped frames
        assert monitor.dropped_frames > 0

    def test_max_frame_time(self):
        """Test that max frame time tracks the worst interval."""
        monitor = get_frame_monitor()
        monitor.enabled = True

        # Record normal samples
        for _ in range(5):
            monitor.record_sample()
            time.sleep(0.016)

        # Record one slow sample (50ms gap)
        time.sleep(0.05)
        monitor.record_sample()

        # Max should be around 50ms
        assert monitor.max_frame_time_ms > 40

    def test_sparkline_data_length(self):
        """Test sparkline data respects width parameter."""
        monitor = get_frame_monitor()
        monitor.enabled = True

        # Record many samples
        for _ in range(50):
            monitor.record_sample()
            time.sleep(0.01)

        # Request specific width
        data = monitor.get_sparkline_data(width=10)
        assert len(data) == 10

    def test_sparkline_data_normalization(self):
        """Test sparkline values are normalized 0-1."""
        monitor = get_frame_monitor()
        monitor.enabled = True

        for _ in range(20):
            monitor.record_sample()
            time.sleep(0.01)

        data = monitor.get_sparkline_data()
        for value in data:
            assert 0.0 <= value <= 1.0

    def test_disabled_monitor_ignores_samples(self):
        """Test that disabled monitor doesn't record samples."""
        monitor = get_frame_monitor()
        monitor.enabled = False

        for _ in range(10):
            monitor.record_sample()
            time.sleep(0.01)

        assert monitor.total_samples == 0
        assert monitor.current_fps == 0.0


class TestRenderSparkline:
    """Tests for sparkline rendering."""

    def test_empty_values(self):
        """Test rendering empty sparkline pads to width."""
        result = render_sparkline([], width=5)
        assert result.plain == "     "  # Padded to width

    def test_renders_correct_width(self):
        """Test sparkline renders to specified width."""
        values = [0.5] * 10
        result = render_sparkline(values, width=10)
        # Should be exactly 10 characters
        assert len(result.plain) == 10

    def test_padding_for_short_data(self):
        """Test sparkline is padded when data is shorter than width."""
        values = [0.5] * 5
        result = render_sparkline(values, width=10)
        # Should pad to 10 characters
        assert len(result.plain) == 10

    def test_values_clamped_to_range(self):
        """Test values outside 0-1 are clamped."""
        values = [-0.5, 0.5, 1.5]  # Invalid, valid, invalid
        result = render_sparkline(values, width=3)
        # Should not raise and should produce valid output
        assert len(result.plain) == 3
        # -0.5 should clamp to 0.0 (space), 0.5 is valid, 1.5 clamps to 1.0 (full block)
        assert result.plain[0] == " "  # -0.5 -> 0.0
        assert result.plain[2] == "█"  # 1.5 -> 1.0

    def test_color_coding(self):
        """Test that sparkline uses color coding."""
        # Low values (green)
        low_result = render_sparkline([0.1])
        # High values (red)
        high_result = render_sparkline([0.9])

        # Both should produce non-empty output
        assert low_result.plain
        assert high_result.plain


class TestFrameMonitorListeners:
    """Tests for listener functionality."""

    def setup_method(self):
        """Reset the monitor singleton before each test."""
        monitor = get_frame_monitor()
        monitor._init()

    def test_add_listener(self):
        """Test adding a listener."""
        monitor = get_frame_monitor()
        calls = []
        monitor.add_listener(lambda: calls.append(1))
        monitor.enabled = True

        monitor.record_sample()
        time.sleep(0.01)
        monitor.record_sample()

        # Listener should have been called
        assert len(calls) > 0

    def test_remove_listener(self):
        """Test removing a listener."""
        monitor = get_frame_monitor()
        calls = []
        callback = lambda: calls.append(1)

        monitor.add_listener(callback)
        monitor.enabled = True

        monitor.record_sample()
        time.sleep(0.01)
        monitor.record_sample()

        initial_calls = len(calls)

        monitor.remove_listener(callback)

        monitor.record_sample()
        time.sleep(0.01)
        monitor.record_sample()

        # Should not have any new calls after removal
        assert len(calls) == initial_calls

    def test_listener_exception_doesnt_crash(self):
        """Test that listener exceptions don't crash sampling."""
        monitor = get_frame_monitor()

        def bad_listener():
            raise RuntimeError("Test error")

        monitor.add_listener(bad_listener)
        monitor.enabled = True

        # Should not raise
        monitor.record_sample()
        time.sleep(0.01)
        monitor.record_sample()

        assert monitor.total_samples > 0


class TestHistogram:
    """Tests for histogram functionality."""

    def setup_method(self):
        """Reset the monitor singleton before each test."""
        monitor = get_frame_monitor()
        monitor._init()

    def test_histogram_data_empty_when_no_samples(self):
        """Test histogram returns empty when no samples."""
        monitor = get_frame_monitor()
        monitor.enabled = True

        counts, labels = monitor.get_histogram_data()
        assert counts == []
        assert labels == []

    def test_histogram_data_has_correct_buckets(self):
        """Test histogram returns expected bucket labels."""
        monitor = get_frame_monitor()
        monitor.enabled = True

        # Record some samples
        for _ in range(20):
            monitor.record_sample()
            time.sleep(0.016)

        counts, labels = monitor.get_histogram_data()
        assert len(counts) == 8  # 8 predefined buckets
        assert len(labels) == 8
        assert labels[0] == "<16"
        assert labels[-1] == ">1k"

    def test_histogram_sparkline_length(self):
        """Test histogram sparkline has correct length."""
        monitor = get_frame_monitor()
        monitor.enabled = True

        for _ in range(30):
            monitor.record_sample()
            time.sleep(0.01)

        data = monitor.get_histogram_sparkline(width=15, max_seconds=60.0)
        assert len(data) == 15

    def test_histogram_sparkline_normalized(self):
        """Test histogram sparkline values are 0-1."""
        monitor = get_frame_monitor()
        monitor.enabled = True

        for _ in range(30):
            monitor.record_sample()
            time.sleep(0.01)

        data = monitor.get_histogram_sparkline(width=10)
        for value in data:
            assert 0.0 <= value <= 1.0

    def test_histogram_detects_jank_spikes(self):
        """Test histogram captures jank spikes."""
        monitor = get_frame_monitor()
        monitor.enabled = True

        # Normal samples
        for _ in range(20):
            monitor.record_sample()
            time.sleep(0.016)

        # Jank spike
        time.sleep(0.1)
        monitor.record_sample()

        # More normal samples
        for _ in range(10):
            monitor.record_sample()
            time.sleep(0.016)

        # Histogram should show the spike
        data = monitor.get_histogram_sparkline(width=10)
        assert max(data) > 0.5  # At least one bucket should show the spike
