"""Debug logging for Balloons.

Provides a singleton debug log that collects entries from across the app.
Listeners can subscribe for real-time updates (used by DebugPane).
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable

import aiofiles


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
    seq: int = 0  # Monotonic sequence number for strict ordering
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
            cls._instance._log_file: Path | None = None
            cls._instance._enabled = True
            cls._instance._seq_counter = 0  # Monotonic sequence counter
        return cls._instance

    @property
    def enabled(self) -> bool:
        """Whether logging is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Enable or disable logging."""
        self._enabled = value

    def set_log_file(self, path: str | Path | None) -> None:
        """Enable file persistence for debug logs.

        Args:
            path: File path to write logs to, or None to disable.
        """
        if path is None:
            self._log_file = None
        else:
            self._log_file = Path(path).expanduser()
            self._log_file.parent.mkdir(parents=True, exist_ok=True)

    def _write_to_file(self, entry: LogEntry) -> None:
        """Write entry to log file if configured (fire-and-forget async)."""
        if self._log_file is None:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._write_to_file_async(entry))
        except RuntimeError:
            # No event loop running - skip file write (in-memory log still works)
            pass

    async def _write_to_file_async(self, entry: LogEntry) -> None:
        """Async file write for log entry."""
        if self._log_file is None:
            return
        try:
            log_line = json.dumps({
                "seq": entry.seq,
                "timestamp": entry.timestamp,
                "level": entry.level.value,
                "message": entry.message,
                "category": entry.category,
                "session_id": entry.session_id,
                "run_id": entry.run_id,
                "details": entry.details,
            })
            async with aiofiles.open(self._log_file, "a") as f:
                await f.write(log_line + "\n")
        except Exception:
            pass  # Don't let file errors crash logging

    def _add_entry(self, entry: LogEntry) -> None:
        """Add entry and notify listeners."""
        if not self._enabled:
            return
        self._entries.append(entry)
        # Write to file if configured
        self._write_to_file(entry)
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
        """Create a log entry with current timestamp and sequence number."""
        self._seq_counter += 1
        return LogEntry(
            level=level,
            message=message,
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
            seq=self._seq_counter,
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


def dump_failed_json(content: str, context: str = "json_error") -> Path | None:
    """Write failed JSON content to a debug file (fire-and-forget async).

    Args:
        content: The JSON content that failed to parse
        context: A short identifier for the error context (e.g., "tool_input", "sse_line")

    Returns:
        Path to the created file, or None if no event loop running
    """
    try:
        debug_dir = Path.home() / ".cache" / "balloons" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{context}_{timestamp}.json"
        filepath = debug_dir / filename

        # Fire-and-forget async write
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_dump_failed_json_async(filepath, content))
            return filepath
        except RuntimeError:
            # No event loop running - skip file write
            return None
    except Exception:
        return None


async def _dump_failed_json_async(filepath: Path, content: str) -> None:
    """Async file write for dump_failed_json."""
    try:
        async with aiofiles.open(filepath, "w") as f:
            await f.write(content)
    except Exception:
        pass  # Don't let file errors crash
