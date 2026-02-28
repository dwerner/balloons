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
    PERF = "perf"  # Performance markers and timing (visible in perf mode)
    DEBUG = "debug"
    TRACE = "trace"  # Very verbose, for scroll events etc.

    @classmethod
    def severity(cls, level: "LogLevel") -> int:
        """Return numeric severity (higher = more severe)."""
        return {
            cls.ERROR: 50,
            cls.WARNING: 40,
            cls.INFO: 30,
            cls.PERF: 25,  # Between INFO and DEBUG
            cls.DEBUG: 20,
            cls.TRACE: 10,
        }[level]


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
            cls._instance._log_dir: Path | None = None  # Category-based log directory
            cls._instance._enabled = True
            cls._instance._seq_counter = 0  # Monotonic sequence counter
            cls._instance._min_level = LogLevel.DEBUG  # Filter out TRACE by default
            cls._instance._perf_mode = False  # Perf mode shows only PERF+ (timing/markers)
            cls._instance._enabled_categories: set[str] = set()  # Empty = log all categories
        return cls._instance

    @property
    def enabled(self) -> bool:
        """Whether logging is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Enable or disable logging."""
        self._enabled = value

    @property
    def min_level(self) -> LogLevel:
        """Minimum log level to display (filters out lower severity)."""
        return self._min_level

    @min_level.setter
    def min_level(self, value: LogLevel) -> None:
        """Set minimum log level to display."""
        self._min_level = value
        # Notify listeners that filter changed
        for listener in self._listeners:
            try:
                if hasattr(listener, '__self__') and hasattr(listener.__self__, 'on_level_changed'):
                    listener.__self__.on_level_changed(value)
            except Exception:
                pass

    @property
    def perf_mode(self) -> bool:
        """Whether perf mode is enabled (shows only PERF level and above)."""
        return self._perf_mode

    @perf_mode.setter
    def perf_mode(self, value: bool) -> None:
        """Enable or disable perf mode.

        When enabled, only PERF, WARNING, and ERROR level messages are shown.
        This filters out the noise and shows only timing/performance markers.
        """
        self._perf_mode = value
        # Notify listeners that filter changed
        for listener in self._listeners:
            try:
                if hasattr(listener, '__self__') and hasattr(listener.__self__, 'on_perf_mode_changed'):
                    listener.__self__.on_perf_mode_changed(value)
            except Exception:
                pass

    def enable_category(self, category: str) -> None:
        """Enable logging for a specific category.

        When any categories are enabled, only those categories will be logged.
        Use this for targeted debugging (e.g., 'api' for API issues).

        Args:
            category: Category to enable (e.g., 'api', 'tool', 'process')
        """
        self._enabled_categories.add(category)

    def disable_category(self, category: str) -> None:
        """Disable logging for a specific category.

        Args:
            category: Category to disable
        """
        self._enabled_categories.discard(category)

    def set_categories(self, categories: list[str]) -> None:
        """Set the list of enabled categories.

        Pass an empty list to log all categories (default behavior).

        Args:
            categories: List of category names to enable
        """
        self._enabled_categories = set(categories)

    def get_categories(self) -> list[str]:
        """Get the list of currently enabled categories.

        Returns:
            List of enabled category names, or empty list if all are enabled
        """
        return sorted(self._enabled_categories)

    def clear_categories(self) -> None:
        """Clear category filter to log all categories."""
        self._enabled_categories.clear()

    def set_log_dir(self, path: str | Path | None) -> None:
        """Enable category-based file logging.

        When set, logs are written to {path}/{category}.log files.
        Only logs for enabled categories are written.

        Args:
            path: Directory path for log files, or None to disable.
        """
        if path is None:
            self._log_dir: Path | None = None
        else:
            self._log_dir = Path(path).expanduser()
            self._log_dir.mkdir(parents=True, exist_ok=True)

    def _write_to_file(self, entry: LogEntry) -> None:
        """Write entry to category-specific log file (fire-and-forget async)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # No running event loop

        # Write to category-specific file if log_dir is set and entry has a category
        if hasattr(self, '_log_dir') and self._log_dir is not None and entry.category:
            loop.create_task(self._write_to_category_file_async(entry))

    async def _write_to_category_file_async(self, entry: LogEntry) -> None:
        """Async file write for category-specific log."""
        if not hasattr(self, '_log_dir') or self._log_dir is None:
            return
        if not entry.category:
            return
        try:
            # Sanitize category name for filename
            safe_category = entry.category.replace("/", "_").replace("\\", "_").replace("..", "_")
            log_path = self._log_dir / f"{safe_category}.log"

            log_line = json.dumps({
                "seq": entry.seq,
                "timestamp": entry.timestamp,
                "level": entry.level.value,
                "message": entry.message,
                "session_id": entry.session_id,
                "run_id": entry.run_id,
                "details": entry.details,
            })
            async with aiofiles.open(log_path, "a") as f:
                await f.write(log_line + "\n")
        except Exception:
            pass  # Don't let file errors crash logging

    def _add_entry(self, entry: LogEntry) -> None:
        """Add entry and notify listeners."""
        if not self._enabled:
            return
        # In perf mode, only show PERF, WARNING, and ERROR
        # This filters out all the chatty INFO/DEBUG/TRACE logs
        if self._perf_mode:
            if entry.level not in (LogLevel.PERF, LogLevel.WARNING, LogLevel.ERROR):
                return
        # Filter by minimum level
        if LogLevel.severity(entry.level) < LogLevel.severity(self._min_level):
            return
        # Filter by enabled categories (if any are set)
        if self._enabled_categories and entry.category not in self._enabled_categories:
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

    def trace(
        self,
        message: str,
        session_id: str = "",
        category: str = "",
        details: dict | None = None,
        run_id: str = "",
    ) -> None:
        """Log a trace message (very verbose, for scroll events etc.)."""
        entry = self._make_entry(LogLevel.TRACE, message, session_id, category, details, run_id)
        self._add_entry(entry)

    def perf(
        self,
        message: str,
        session_id: str = "",
        category: str = "perf",
        details: dict | None = None,
        run_id: str = "",
    ) -> None:
        """Log a performance marker or timing event.

        These messages are visible even in perf mode, which filters out
        lower-level messages. Use for:
        - Operation start/end timing
        - Performance counters
        - Key milestones in expensive operations
        """
        entry = self._make_entry(LogLevel.PERF, message, session_id, category, details, run_id)
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
        loop = asyncio.get_running_loop()
        loop.create_task(_dump_failed_json_async(filepath, content))
        return filepath
    except Exception:
        return None


async def _dump_failed_json_async(filepath: Path, content: str) -> None:
    """Async file write for dump_failed_json."""
    try:
        async with aiofiles.open(filepath, "w") as f:
            await f.write(content)
    except Exception:
        pass  # Don't let file errors crash


import time
from contextlib import contextmanager


@contextmanager
def timed(name: str, threshold_ms: float = 50.0):
    """Context manager that logs a warning if the block takes too long.

    Usage:
        with timed("session.save"):
            session.save()

    If the operation takes longer than threshold_ms, logs a warning.

    Args:
        name: Name to identify the operation in logs
        threshold_ms: Log warning if operation takes longer than this (default 50ms)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms > threshold_ms:
            debug_log.warning(
                f"SLOW: {name} took {elapsed_ms:.1f}ms (threshold: {threshold_ms}ms)",
                category="perf",
                details={"elapsed_ms": elapsed_ms, "threshold_ms": threshold_ms},
            )


@contextmanager
def perf_timed(name: str, threshold_ms: float = 0.0):
    """Context manager that always logs timing at PERF level.

    Unlike timed(), this always logs the duration (useful in perf mode).
    If threshold_ms is set and exceeded, also logs a WARNING.

    Usage:
        with perf_timed("render_chat_log"):
            render()

    Args:
        name: Name to identify the operation in logs
        threshold_ms: If > 0, also log WARNING when exceeded
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        debug_log.perf(
            f"{name}: {elapsed_ms:.1f}ms",
            category="perf",
            details={"elapsed_ms": elapsed_ms, "operation": name},
        )
        if threshold_ms > 0 and elapsed_ms > threshold_ms:
            debug_log.warning(
                f"SLOW: {name} took {elapsed_ms:.1f}ms (threshold: {threshold_ms}ms)",
                category="perf",
                details={"elapsed_ms": elapsed_ms, "threshold_ms": threshold_ms},
            )


def perf_marker(name: str, **details) -> None:
    """Log a performance marker/checkpoint.

    Use this for key milestones like:
    - "stream_start", "first_token", "stream_end"
    - "render_begin", "render_complete"
    - "storage_read", "storage_write"

    Args:
        name: Marker name
        **details: Additional details to include
    """
    debug_log.perf(
        f"[{name}]",
        category="perf",
        details={"marker": name, **details},
    )
