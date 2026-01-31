"""Tests for the debug logging module."""

import pytest
from core.debug_log import DebugLog, LogLevel, LogEntry, debug_log


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
            category="process",
            details={"key": "value"},
        )
        assert entry.level == LogLevel.ERROR
        assert entry.session_id == "abc123"
        assert entry.category == "process"
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
        debug_log.error("Test error", category="test")
        entries = debug_log.get_entries()
        assert len(entries) == 1
        assert entries[0].level == LogLevel.ERROR
        assert entries[0].category == "test"

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
        debug_log.info("Process started", category="process")
        debug_log.info("JSON parsed", category="json")
        debug_log.info("Stream started", category="stream")

        process_entries = debug_log.get_entries(category="process")
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
