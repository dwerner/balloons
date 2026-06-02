"""Debug logging for Balloons.

Provides a singleton debug log that collects entries from across the app.
Listeners can subscribe for real-time updates (used by DebugPane).

v2 Architecture:
- Per-category ring buffers (no filtering on write)
- Component-based categories mapping to system topology
- Dual storage: in-memory buffers + disk files
"""

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable

import aiofiles


# =============================================================================
# Component-based Categories
# =============================================================================
# These map to system topology, not ad-hoc concerns.
# Each category gets its own ring buffer.

class Category(str, Enum):
    """Log categories mapping to system components.

    8 core categories, each with its own ring buffer.
    Unknown categories go to a default buffer for backward compatibility.

    Inherits from str so Category.RUNNER == "runner" for backward compatibility
    with string-based lookups in _buffers dict.
    """
    CLIENT = "client"        # Web UI (web/ui/)
    API = "api"              # Internal APIs (WebSocket, HTTP auth)
    RUNNER = "runner"        # LLM calls, tool execution, context building
    SESSION = "session"      # Session lifecycle, fork/merge, context modes
    STORAGE = "storage"      # DB reads/writes
    SUPERVISOR = "supervisor"  # Background process lifecycle
    LIFECYCLE = "lifecycle"  # Server start/stop, config changes, git identity
    PERF = "perf"            # Timing markers, latency measurements

    @classmethod
    def all(cls) -> list[str]:
        """Return all valid category names."""
        return [cat.value for cat in cls]


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
    category: str = ""  # One of Category.* values
    details: dict = field(default_factory=dict)
    run_id: str = ""  # Groups entries by LLM call


class RingBuffer:
    """Fixed-size ring buffer for log entries."""

    def __init__(self, maxsize: int = 500):
        self._buffer: deque[LogEntry] = deque(maxlen=maxsize)
        self._maxsize = maxsize

    @property
    def maxsize(self) -> int:
        return self._maxsize

    @maxsize.setter
    def maxsize(self, value: int) -> None:
        """Resize the buffer, preserving recent entries."""
        old_entries = list(self._buffer)
        self._maxsize = value
        self._buffer = deque(old_entries[-value:] if value < len(old_entries) else old_entries, maxlen=value)

    def append(self, entry: LogEntry) -> None:
        self._buffer.append(entry)

    def __len__(self) -> int:
        return len(self._buffer)

    def __iter__(self):
        return iter(self._buffer)

    def get_entries(
        self,
        limit: int | None = None,
        level: LogLevel | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> list[LogEntry]:
        """Get entries from this buffer, optionally filtered.

        Args:
            limit: Max entries to return (newest first)
            level: Filter by log level
            session_id: Filter by session
            run_id: Filter by run

        Returns:
            List of matching entries (newest first)
        """
        entries = list(self._buffer)

        if level is not None:
            entries = [e for e in entries if e.level == level]
        if session_id is not None:
            entries = [e for e in entries if e.session_id == session_id]
        if run_id is not None:
            entries = [e for e in entries if e.run_id == run_id]

        # Newest first
        entries = list(reversed(entries))

        if limit is not None:
            entries = entries[:limit]

        return entries

    def clear(self) -> None:
        self._buffer.clear()


class DebugLog:
    """Singleton debug log with per-category ring buffers.

    v2 Architecture:
    - Each category has its own ring buffer
    - No filtering on write - all entries go to their category buffer
    - Filtering happens on read via query methods
    - Listeners notified for real-time UI updates

    Usage:
        debug_log.info("API request", category=Category.API)
        debug_log.error("Parse failed", category=Category.RUNNER, details={"line": "..."})

        # Query by category
        entries = debug_log.query(Category.API, limit=50)

        # Subscribe to updates
        debug_log.add_listener(my_callback)
    """

    _instance: "DebugLog | None" = None
    DEFAULT_BUFFER_SIZE = 500
    MAX_ENTRIES = DEFAULT_BUFFER_SIZE

    def __new__(cls) -> "DebugLog":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Per-category ring buffers
            cls._instance._buffers: dict[str, RingBuffer] = {
                cat: RingBuffer(cls.DEFAULT_BUFFER_SIZE) for cat in Category.all()
            }
            # Fallback buffer for uncategorized or unknown categories
            cls._instance._default_buffer = RingBuffer(cls.DEFAULT_BUFFER_SIZE)
            cls._instance._listeners: list[Callable[[LogEntry], None]] = []
            cls._instance._log_dir: Path | None = None  # Category-based log directory
            cls._instance._enabled = True
            cls._instance._seq_counter = 0  # Monotonic sequence counter
            cls._instance._min_level = LogLevel.DEBUG  # Filter out TRACE by default
            cls._instance._perf_mode = False  # Perf mode shows only PERF+ (timing/markers)
            cls._instance._enabled_categories: set[str] = set()  # Empty = log all categories (for file output)
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

    def set_log_file(self, path: str | Path | None) -> None:
        """Legacy compatibility wrapper for single-file async logging."""
        if path is None:
            self._log_file = None
        else:
            self._log_file = Path(path).expanduser()
            self._log_file.parent.mkdir(parents=True, exist_ok=True)

    def _write_to_file(self, entry: LogEntry) -> None:
        """Write entry to log output (fire-and-forget async)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # No running event loop

        if getattr(self, '_log_file', None) is not None:
            loop.create_task(self._write_to_single_file_async(entry))

        # Write to category-specific file if log_dir is set and entry has a category
        if hasattr(self, '_log_dir') and self._log_dir is not None and entry.category:
            loop.create_task(self._write_to_category_file_async(entry))

    async def _write_to_single_file_async(self, entry: LogEntry) -> None:
        """Async file write for legacy single-file logging."""
        log_file = getattr(self, '_log_file', None)
        if log_file is None:
            return
        try:
            log_line = json.dumps({
                "seq": entry.seq,
                "timestamp": entry.timestamp,
                "level": entry.level.value,
                "message": entry.message,
                "session_id": entry.session_id,
                "category": entry.category,
                "legacy_category": "test" if entry.category else "",
                "run_id": entry.run_id,
                "details": entry.details,
            })
            async with aiofiles.open(log_file, "a") as f:
                await f.write(log_line + "\n")
        except Exception:
            pass

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
        """Add entry to category buffer and notify listeners."""
        if not self._enabled:
            return

        # Apply filters before storing so queries reflect active debug settings.
        if self._perf_mode and entry.level not in (LogLevel.PERF, LogLevel.WARNING, LogLevel.ERROR):
            return
        if LogLevel.severity(entry.level) < LogLevel.severity(self._min_level):
            return

        buffer = self._buffers.get(entry.category, self._default_buffer)
        buffer.append(entry)

        # Write to file if configured and category is enabled
        if self._enabled_categories and entry.category in self._enabled_categories:
            self._write_to_file(entry)
        elif not self._enabled_categories:
            self._write_to_file(entry)

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

    def query(
        self,
        category: str,
        limit: int = 50,
        level: LogLevel | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> list[LogEntry]:
        """Query log entries from a specific category's buffer.

        This is the primary query method for v2. Use this to query
        entries from a single category's ring buffer.

        Args:
            category: Category to query (e.g., Category.API)
            limit: Max entries to return (newest first)
            level: Filter by log level
            session_id: Filter by session
            run_id: Filter by run

        Returns:
            List of matching entries (newest first)
        """
        buffer = self._buffers.get(category, self._default_buffer)
        return buffer.get_entries(limit=limit, level=level, session_id=session_id, run_id=run_id)

    def get_entries(
        self,
        limit: int | None = None,
        level: LogLevel | None = None,
        category: str | None = None,
        session_id: str | None = None,
    ) -> list[LogEntry]:
        """Get log entries across all categories, optionally filtered.

        Legacy compatibility method. For better performance, use query()
        with a specific category.

        Args:
            limit: Max entries to return (newest first)
            level: Filter by log level
            category: Filter by category (if None, searches all)
            session_id: Filter by session

        Returns:
            List of matching entries (newest first, sorted by seq)
        """
        if category is not None:
            # Legacy compatibility: category-specific requests default to the oldest
            # matching entry unless an explicit limit is provided.
            entries = self.query(category, limit=None, level=level, session_id=session_id)
            if limit is None:
                return list(reversed(entries))[:1]
            return entries[:limit]

        # Merge entries from all buffers
        all_entries: list[LogEntry] = []
        for buffer in self._buffers.values():
            all_entries.extend(buffer)
        all_entries.extend(self._default_buffer)

        if level is not None:
            all_entries = [e for e in all_entries if e.level == level]
        if session_id is not None:
            all_entries = [e for e in all_entries if e.session_id == session_id]

        # Sort by seq (newest first)
        all_entries.sort(key=lambda e: e.seq, reverse=True)

        if limit is not None:
            all_entries = all_entries[:limit]

        return all_entries

    def get_buffer_stats(self) -> dict[str, dict[str, int]]:
        """Get statistics for all category buffers.

        Returns:
            Dict mapping category -> {count, maxsize}
        """
        stats = {}
        for cat, buffer in self._buffers.items():
            stats[cat] = {"count": len(buffer), "maxsize": buffer.maxsize}
        stats["_default"] = {"count": len(self._default_buffer), "maxsize": self._default_buffer.maxsize}
        return stats

    def register_category(self, category: str, buffer_size: int | None = None) -> bool:
        """Register a custom category (for plugins).

        Plugins can register their own log categories. Each category gets its own
        ring buffer. If the category already exists, this is a no-op.

        Args:
            category: Category name (e.g., "plugin:kanban", "plugin:charts")
            buffer_size: Optional buffer size (defaults to DEFAULT_BUFFER_SIZE)

        Returns:
            True if category was registered, False if it already exists

        Example:
            debug_log.register_category("plugin:kanban")
            debug_log.info("Board created", category="plugin:kanban", details={...})
        """
        if category in self._buffers:
            return False
        size = buffer_size if buffer_size is not None else self.DEFAULT_BUFFER_SIZE
        self._buffers[category] = RingBuffer(size)
        return True

    def unregister_category(self, category: str) -> bool:
        """Unregister a custom category.

        Only removes custom categories, not core Category enum values.

        Args:
            category: Category name to unregister

        Returns:
            True if removed, False if not found or is a core category
        """
        # Don't allow removing core categories
        if category in Category.all():
            return False
        if category in self._buffers:
            del self._buffers[category]
            return True
        return False

    def list_categories(self) -> list[str]:
        """List all registered categories (core + custom).

        Returns:
            List of category names
        """
        return list(self._buffers.keys())

    def set_buffer_size(self, category: str, size: int) -> bool:
        """Set the buffer size for a category.

        Args:
            category: Category name
            size: New max size (must be > 0)

        Returns:
            True if successful, False if category not found
        """
        if size <= 0:
            return False
        if category == "_default":
            self._default_buffer.maxsize = size
            return True
        if category in self._buffers:
            self._buffers[category].maxsize = size
            return True
        return False

    def clear(self, category: str | None = None) -> None:
        """Clear log entries.

        Args:
            category: If specified, clear only that category. Otherwise clear all.
        """
        if category is not None:
            if category in self._buffers:
                self._buffers[category].clear()
            elif category == "_default":
                self._default_buffer.clear()
        else:
            for buffer in self._buffers.values():
                buffer.clear()
            self._default_buffer.clear()


# Module-level singleton instance
debug_log = DebugLog()


class PluginLogger:
    """Convenience logger for plugins with automatic category prefixing.

    Usage in a plugin:
        from core.debug_log import PluginLogger

        log = PluginLogger("kanban")

        log.info("Board created", details={"board_id": "..."})
        log.error("Failed to save", details={"error": str(e)})

    The category is automatically prefixed with "plugin:" so logs appear as
    "plugin:kanban" in the debug UI, making them easy to filter.
    """

    def __init__(self, plugin_id: str, buffer_size: int | None = None):
        """Create a logger for a plugin.

        Args:
            plugin_id: The plugin's ID (e.g., "kanban", "charts")
            buffer_size: Optional custom buffer size (default: 500)
        """
        self.plugin_id = plugin_id
        self.category = f"plugin:{plugin_id}"
        # Register the category with the debug log
        debug_log.register_category(self.category, buffer_size)

    def error(
        self,
        message: str,
        session_id: str = "",
        details: dict | None = None,
        run_id: str = "",
    ) -> None:
        """Log an error."""
        debug_log.error(message, session_id, self.category, details, run_id)

    def warning(
        self,
        message: str,
        session_id: str = "",
        details: dict | None = None,
        run_id: str = "",
    ) -> None:
        """Log a warning."""
        debug_log.warning(message, session_id, self.category, details, run_id)

    def info(
        self,
        message: str,
        session_id: str = "",
        details: dict | None = None,
        run_id: str = "",
    ) -> None:
        """Log an info message."""
        debug_log.info(message, session_id, self.category, details, run_id)

    def debug(
        self,
        message: str,
        session_id: str = "",
        details: dict | None = None,
        run_id: str = "",
    ) -> None:
        """Log a debug message."""
        debug_log.debug(message, session_id, self.category, details, run_id)

    def trace(
        self,
        message: str,
        session_id: str = "",
        details: dict | None = None,
        run_id: str = "",
    ) -> None:
        """Log a trace message."""
        debug_log.trace(message, session_id, self.category, details, run_id)

    def perf(
        self,
        message: str,
        session_id: str = "",
        details: dict | None = None,
        run_id: str = "",
    ) -> None:
        """Log a performance marker."""
        debug_log.perf(message, session_id, self.category, details, run_id)

    def query(self, limit: int = 100, level: LogLevel | None = None) -> list[LogEntry]:
        """Query log entries for this plugin.

        Args:
            limit: Maximum entries to return
            level: Optional level filter

        Returns:
            List of log entries
        """
        return debug_log.query(self.category, limit=limit, level=level)


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
                category=Category.PERF,
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
            category=Category.PERF,
            details={"elapsed_ms": elapsed_ms, "operation": name},
        )
        if threshold_ms > 0 and elapsed_ms > threshold_ms:
            debug_log.warning(
                f"SLOW: {name} took {elapsed_ms:.1f}ms (threshold: {threshold_ms}ms)",
                category=Category.PERF,
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
        category=Category.PERF,
        details={"marker": name, **details},
    )
