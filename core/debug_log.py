"""Debug logging for Balloons.

Provides a singleton debug log that collects entries from across the app.
Listeners can subscribe for real-time updates (used by DebugPane).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable


class LogLevel(Enum):
    """Log level for debug entries."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"


@dataclass
class LogEntry:
    """A single debug log entry."""
    level: LogLevel
    message: str
    timestamp: str
    session_id: str = ""
    category: str = ""  # "process", "stderr", "json", "event", "stream"
    details: dict = field(default_factory=dict)
    run_id: str = ""  # Groups entries by Claude process run (PID)


class DebugLog:
    """Singleton debug log with listener pattern.

    Collects log entries from across the application.
    Listeners are notified on each new entry for real-time UI updates.

    Usage:
        debug_log.info("Process started", category="process")
        debug_log.error("JSON decode failed", category="json", details={"line": "..."})

        # Subscribe to updates
        debug_log.add_listener(my_callback)
    """

    _instance: "DebugLog | None" = None
    MAX_ENTRIES = 500

    def __new__(cls) -> "DebugLog":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._entries = []
            cls._instance._listeners = []
        return cls._instance

    def _add_entry(self, entry: LogEntry) -> None:
        """Add entry and notify listeners."""
        self._entries.append(entry)
        # Prune oldest if over limit
        if len(self._entries) > self.MAX_ENTRIES:
            self._entries = self._entries[-self.MAX_ENTRIES:]
        # Notify listeners
        for listener in self._listeners:
            try:
                listener(entry)
            except Exception:
                pass  # Don't let listener errors crash logging

    def _make_entry(
        self,
        level: LogLevel,
        message: str,
        session_id: str = "",
        category: str = "",
        details: dict | None = None,
        run_id: str = "",
    ) -> LogEntry:
        """Create a log entry with current timestamp."""
        return LogEntry(
            level=level,
            message=message,
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
            session_id=session_id,
            category=category,
            details=details or {},
            run_id=run_id,
        )

    def error(
        self,
        message: str,
        session_id: str = "",
        category: str = "",
        details: dict | None = None,
        run_id: str = "",
    ) -> None:
        """Log an error."""
        entry = self._make_entry(LogLevel.ERROR, message, session_id, category, details, run_id)
        self._add_entry(entry)

    def warning(
        self,
        message: str,
        session_id: str = "",
        category: str = "",
        details: dict | None = None,
        run_id: str = "",
    ) -> None:
        """Log a warning."""
        entry = self._make_entry(LogLevel.WARNING, message, session_id, category, details, run_id)
        self._add_entry(entry)

    def info(
        self,
        message: str,
        session_id: str = "",
        category: str = "",
        details: dict | None = None,
        run_id: str = "",
    ) -> None:
        """Log an info message."""
        entry = self._make_entry(LogLevel.INFO, message, session_id, category, details, run_id)
        self._add_entry(entry)

    def debug(
        self,
        message: str,
        session_id: str = "",
        category: str = "",
        details: dict | None = None,
        run_id: str = "",
    ) -> None:
        """Log a debug message."""
        entry = self._make_entry(LogLevel.DEBUG, message, session_id, category, details, run_id)
        self._add_entry(entry)

    def add_listener(self, callback: Callable[[LogEntry], None]) -> None:
        """Subscribe to log updates. Callback called for each new entry."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[LogEntry], None]) -> None:
        """Unsubscribe from log updates."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def get_entries(
        self,
        limit: int | None = None,
        level: LogLevel | None = None,
        category: str | None = None,
        session_id: str | None = None,
    ) -> list[LogEntry]:
        """Get log entries, optionally filtered.

        Args:
            limit: Max entries to return (newest first)
            level: Filter by log level
            category: Filter by category
            session_id: Filter by session

        Returns:
            List of matching entries (newest first)
        """
        entries = self._entries

        if level is not None:
            entries = [e for e in entries if e.level == level]
        if category is not None:
            entries = [e for e in entries if e.category == category]
        if session_id is not None:
            entries = [e for e in entries if e.session_id == session_id]

        # Newest first
        entries = list(reversed(entries))

        if limit is not None:
            entries = entries[:limit]

        return entries

    def clear(self) -> None:
        """Clear all log entries."""
        self._entries = []


# Module-level singleton instance
debug_log = DebugLog()
