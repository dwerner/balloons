"""Tests for the debug logging module."""

import asyncio
import json
import time
import pytest
from core.debug_log import DebugLog, LogLevel, LogEntry, debug_log, dump_failed_json, perf_timed, perf_marker


class TestLogEntry:
    """Tests for LogEntry dataclass."""

    def test_create_entry(self):
        entry = LogEntry(
            level=LogLevel.INFO,
            message="Test message",
            timestamp="12:00:00.000",
        )
        assert entry.level == LogLevel.INFO
        assert entry.message == "Test message"
        assert entry.session_id == ""
        assert entry.category == ""
        assert entry.details == {}

    def test_create_entry_with_all_fields(self):
        entry = LogEntry(
            level=LogLevel.ERROR,
            message="Error occurred",
            timestamp="12:00:00.000",
            session_id="abc123",
            category="runner",
            details={"key": "value"},
        )
        assert entry.level == LogLevel.ERROR
        assert entry.session_id == "abc123"
        assert entry.category == "runner"
        assert entry.details == {"key": "value"}


class TestDebugLog:
    """Tests for DebugLog singleton."""

    def setup_method(self):
        """Clear the debug log before each test."""
        debug_log.clear()
        # Remove any test listeners
        debug_log._listeners = []

    def test_singleton(self):
        log1 = DebugLog()
        log2 = DebugLog()
        assert log1 is log2

    def test_info_creates_entry(self):
        debug_log.info("Test info")
        entries = debug_log.get_entries()
        assert len(entries) == 1
        assert entries[0].level == LogLevel.INFO
        assert entries[0].message == "Test info"

    def test_error_creates_entry(self):
        debug_log.error("Test error", category="runner")
        entries = debug_log.get_entries()
        assert len(entries) == 1
        assert entries[0].level == LogLevel.ERROR
        assert entries[0].category == "runner"

    def test_warning_creates_entry(self):
        debug_log.warning("Test warning", session_id="sess123")
        entries = debug_log.get_entries()
        assert len(entries) == 1
        assert entries[0].level == LogLevel.WARNING
        assert entries[0].session_id == "sess123"

    def test_debug_creates_entry(self):
        debug_log.debug("Test debug", details={"foo": "bar"})
        entries = debug_log.get_entries()
        assert len(entries) == 1
        assert entries[0].level == LogLevel.DEBUG
        assert entries[0].details == {"foo": "bar"}

    def test_trace_creates_entry_when_enabled(self):
        """Test that trace messages are logged when min_level is TRACE."""
        original_level = debug_log.min_level
        try:
            debug_log.min_level = LogLevel.TRACE
            debug_log.trace("Test trace", category="client")
            entries = debug_log.get_entries()
            assert len(entries) == 1
            assert entries[0].level == LogLevel.TRACE
            assert entries[0].message == "Test trace"
            assert entries[0].category == "client"
        finally:
            debug_log.min_level = original_level

    def test_trace_filtered_when_min_level_is_debug(self):
        """Test that trace messages are filtered when min_level is DEBUG."""
        original_level = debug_log.min_level
        try:
            debug_log.min_level = LogLevel.DEBUG
            debug_log.trace("This should be filtered")
            debug_log.debug("This should appear")
            entries = debug_log.get_entries()
            assert len(entries) == 1
            assert entries[0].level == LogLevel.DEBUG
        finally:
            debug_log.min_level = original_level

    def test_min_level_filtering(self):
        """Test that min_level filters messages below the threshold."""
        original_level = debug_log.min_level
        try:
            debug_log.min_level = LogLevel.WARNING
            debug_log.trace("Filtered")
            debug_log.debug("Filtered")
            debug_log.info("Filtered")
            debug_log.warning("Should appear")
            debug_log.error("Should appear")
            entries = debug_log.get_entries()
            assert len(entries) == 2
            levels = {e.level for e in entries}
            assert LogLevel.WARNING in levels
            assert LogLevel.ERROR in levels
        finally:
            debug_log.min_level = original_level

    def test_level_severity(self):
        """Test that log levels have correct severity ordering."""
        assert LogLevel.severity(LogLevel.TRACE) < LogLevel.severity(LogLevel.DEBUG)
        assert LogLevel.severity(LogLevel.DEBUG) < LogLevel.severity(LogLevel.PERF)
        assert LogLevel.severity(LogLevel.PERF) < LogLevel.severity(LogLevel.INFO)
        assert LogLevel.severity(LogLevel.INFO) < LogLevel.severity(LogLevel.WARNING)
        assert LogLevel.severity(LogLevel.WARNING) < LogLevel.severity(LogLevel.ERROR)

    def test_perf_creates_entry(self):
        """Test that perf messages are logged at PERF level."""
        debug_log.perf("Performance marker", details={"elapsed_ms": 42.5})
        entries = debug_log.get_entries()
        assert len(entries) == 1
        assert entries[0].level == LogLevel.PERF
        assert entries[0].message == "Performance marker"
        assert entries[0].category == "perf"
        assert entries[0].details == {"elapsed_ms": 42.5}

    def test_perf_mode_filters_non_perf_messages(self):
        """Test that perf mode only shows PERF and higher severity."""
        original_perf_mode = debug_log.perf_mode
        try:
            debug_log.perf_mode = True
            debug_log.trace("Trace message")
            debug_log.debug("Debug message")
            debug_log.info("Info message")
            debug_log.perf("Perf marker")
            debug_log.warning("Warning message")
            debug_log.error("Error message")

            entries = debug_log.get_entries()
            levels = [e.level for e in entries]

            # Only PERF, WARNING, and ERROR should be present
            assert LogLevel.TRACE not in levels
            assert LogLevel.DEBUG not in levels
            assert LogLevel.INFO not in levels
            assert LogLevel.PERF in levels
            assert LogLevel.WARNING in levels
            assert LogLevel.ERROR in levels
            assert len(entries) == 3
        finally:
            debug_log.perf_mode = original_perf_mode

    def test_entries_in_order(self):
        debug_log.info("First")
        debug_log.info("Second")
        debug_log.info("Third")
        entries = debug_log.get_entries()
        # Newest first
        assert entries[0].message == "Third"
        assert entries[1].message == "Second"
        assert entries[2].message == "First"

    def test_get_entries_with_limit(self):
        for i in range(10):
            debug_log.info(f"Message {i}")
        entries = debug_log.get_entries(limit=3)
        assert len(entries) == 3
        assert entries[0].message == "Message 9"

    def test_get_entries_filter_by_level(self):
        debug_log.info("Info message")
        debug_log.error("Error message")
        debug_log.warning("Warning message")

        errors = debug_log.get_entries(level=LogLevel.ERROR)
        assert len(errors) == 1
        assert errors[0].message == "Error message"

    def test_get_entries_filter_by_category(self):
        debug_log.info("Process started", category="runner")
        debug_log.info("JSON parsed", category="runner")
        debug_log.info("Stream started", category="runner")

        process_entries = debug_log.get_entries(category="runner")
        assert len(process_entries) == 1
        assert process_entries[0].message == "Process started"

    def test_get_entries_filter_by_session(self):
        debug_log.info("Session A", session_id="aaa")
        debug_log.info("Session B", session_id="bbb")
        debug_log.info("Session A again", session_id="aaa")

        session_a = debug_log.get_entries(session_id="aaa")
        assert len(session_a) == 2

    def test_clear(self):
        debug_log.info("Message 1")
        debug_log.info("Message 2")
        assert len(debug_log.get_entries()) == 2

        debug_log.clear()
        assert len(debug_log.get_entries()) == 0

    def test_max_entries_pruning(self):
        # Add more than MAX_ENTRIES
        for i in range(DebugLog.MAX_ENTRIES + 100):
            debug_log.info(f"Message {i}")

        entries = debug_log.get_entries()
        assert len(entries) == DebugLog.MAX_ENTRIES
        # Should have newest entries
        assert "Message 599" in entries[0].message  # Last one added

    def test_listener_notified(self):
        received = []

        def listener(entry: LogEntry):
            received.append(entry)

        debug_log.add_listener(listener)
        debug_log.info("Test message")

        assert len(received) == 1
        assert received[0].message == "Test message"

    def test_remove_listener(self):
        received = []

        def listener(entry: LogEntry):
            received.append(entry)

        debug_log.add_listener(listener)
        debug_log.info("Message 1")
        debug_log.remove_listener(listener)
        debug_log.info("Message 2")

        assert len(received) == 1
        assert received[0].message == "Message 1"

    def test_listener_error_does_not_crash(self):
        def bad_listener(entry: LogEntry):
            raise RuntimeError("Listener error")

        debug_log.add_listener(bad_listener)
        # Should not raise
        debug_log.info("Test message")

        # Entry should still be recorded
        entries = debug_log.get_entries()
        assert len(entries) == 1

    def test_timestamp_format(self):
        debug_log.info("Test")
        entry = debug_log.get_entries()[0]
        # Should be HH:MM:SS.mmm format
        assert len(entry.timestamp) == 12
        assert entry.timestamp[2] == ":"
        assert entry.timestamp[5] == ":"
        assert entry.timestamp[8] == "."


class TestAsyncFileLogging:
    """Tests for async fire-and-forget file logging."""

    def setup_method(self):
        """Clear the debug log before each test."""
        debug_log.clear()
        debug_log._listeners = []
        debug_log._log_file = None

    @pytest.mark.asyncio
    async def test_write_to_file_async(self, tmp_path):
        """Test that log entries are written to file asynchronously."""
        log_file = tmp_path / "test.log"
        debug_log.set_log_file(log_file)

        debug_log.info("Test async write", category="runner")

        # Allow the fire-and-forget task to complete
        await asyncio.sleep(0.1)

        assert log_file.exists()
        content = log_file.read_text()
        assert "Test async write" in content
        assert "test" in content  # category

        # Cleanup
        debug_log._log_file = None

    @pytest.mark.asyncio
    async def test_write_multiple_entries_async(self, tmp_path):
        """Test that multiple entries are written asynchronously."""
        log_file = tmp_path / "test.log"
        debug_log.set_log_file(log_file)

        debug_log.info("Entry 1")
        debug_log.warning("Entry 2")
        debug_log.error("Entry 3")

        # Allow tasks to complete
        await asyncio.sleep(0.1)

        content = log_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 3

        # Verify JSON format
        for line in lines:
            parsed = json.loads(line)
            assert "timestamp" in parsed
            assert "level" in parsed
            assert "message" in parsed

        # Cleanup
        debug_log._log_file = None

    @pytest.mark.asyncio
    async def test_dump_failed_json_async(self, tmp_path, monkeypatch):
        """Test that dump_failed_json writes asynchronously."""
        from pathlib import Path

        # Monkeypatch Path.home to return tmp_path
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        content = '{"invalid": json content}'
        result = dump_failed_json(content, context="test_error")

        # Allow task to complete
        await asyncio.sleep(0.1)

        assert result is not None
        assert "test_error" in str(result)
        # File should exist after async write completes
        assert result.exists()
        assert result.read_text() == content

    # Removed test_no_event_loop_graceful_fallback - we no longer support
    # sync fallback behavior. All code must run in async context.


class TestPerfTiming:
    """Tests for performance timing utilities."""

    def setup_method(self):
        """Clear the debug log before each test."""
        debug_log.clear()
        debug_log._listeners = []

    def test_perf_marker_logs_event(self):
        """Test that perf_marker creates a PERF level entry."""
        perf_marker("test.operation", elapsed_ms=42.5, session_id="abc123")

        entries = debug_log.get_entries()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.level == LogLevel.PERF
        assert "[test.operation]" in entry.message
        assert entry.details["marker"] == "test.operation"
        assert entry.details["elapsed_ms"] == 42.5
        assert entry.details["session_id"] == "abc123"

    def test_perf_marker_with_multiple_kwargs(self):
        """Test that perf_marker accepts arbitrary keyword args."""
        perf_marker(
            "storage.save",
            session_id="sess123",
            turn_count=5,
            elapsed_ms=15.3,
        )

        entries = debug_log.get_entries()
        assert len(entries) == 1
        details = entries[0].details
        assert details["marker"] == "storage.save"
        assert details["session_id"] == "sess123"
        assert details["turn_count"] == 5
        assert details["elapsed_ms"] == 15.3

    def test_perf_timed_logs_duration(self):
        """Test that perf_timed context manager logs operation duration."""
        with perf_timed("test.sleep"):
            time.sleep(0.01)  # 10ms

        entries = debug_log.get_entries()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.level == LogLevel.PERF
        assert "test.sleep:" in entry.message
        assert entry.details["operation"] == "test.sleep"
        assert entry.details["elapsed_ms"] >= 10  # At least 10ms

    def test_perf_timed_with_threshold_warning(self):
        """Test that perf_timed logs WARNING when threshold exceeded."""
        with perf_timed("test.slow", threshold_ms=5):
            time.sleep(0.02)  # 20ms - exceeds 5ms threshold

        entries = debug_log.get_entries()
        # Should have both PERF (always) and WARNING (threshold exceeded)
        assert len(entries) == 2

        perf_entry = [e for e in entries if e.level == LogLevel.PERF][0]
        warning_entry = [e for e in entries if e.level == LogLevel.WARNING][0]

        assert "test.slow:" in perf_entry.message
        assert "SLOW" in warning_entry.message
        assert warning_entry.details["threshold_ms"] == 5

    def test_perf_timed_no_warning_under_threshold(self):
        """Test that perf_timed doesn't warn when under threshold."""
        with perf_timed("test.fast", threshold_ms=100):
            time.sleep(0.005)  # 5ms - under 100ms threshold

        entries = debug_log.get_entries()
        # Should only have PERF, no WARNING
        assert len(entries) == 1
        assert entries[0].level == LogLevel.PERF

    def test_perf_marker_visible_in_perf_mode(self):
        """Test that perf_marker entries are visible when perf_mode is enabled."""
        original_perf_mode = debug_log.perf_mode
        try:
            debug_log.perf_mode = True

            perf_marker("test.marker", value=123)
            debug_log.info("This should be filtered")  # Should NOT appear

            entries = debug_log.get_entries()
            assert len(entries) == 1
            assert entries[0].level == LogLevel.PERF
        finally:
            debug_log.perf_mode = original_perf_mode
