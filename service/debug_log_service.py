"""WebSocket-exposed service for debug logging.

This service allows web clients to send debug log entries that appear in the
TUI's debug pane alongside native Python logs. This provides a unified logging
experience across all frontends.

Usage (from web client):
    await client.debugLog.log({
        level: 'info',
        message: 'Creating new session',
        category: 'web',
        details: { sessionId: '...' }
    });
"""

from dataclasses import dataclass
from typing import Literal

from codegen import ws_service, ws_expose, ws_type
from core.debug_log import debug_log, LogLevel, Category
from core.server_identity import get_identity, identity_to_dict


LogLevelStr = Literal["error", "warning", "info", "debug", "trace", "perf"]


@ws_type
@dataclass
class LogEntryInput:
    """Input for logging from web client."""

    level: str  # One of: error, warning, info, debug, trace, perf
    message: str
    category: str = "web"  # Default category for web logs
    session_id: str = ""
    details: dict | None = None


@ws_type
@dataclass
class LogResult:
    """Result of logging operation."""

    success: bool
    seq: int = 0  # Sequence number of the logged entry


@ws_type
@dataclass
class LogEntryOutput:
    """A log entry for output to clients."""

    seq: int
    timestamp: str
    level: str
    message: str
    category: str
    session_id: str
    run_id: str
    details: dict


@ws_type
@dataclass
class QueryResult:
    """Result of a log query."""

    entries: list[LogEntryOutput]
    total: int  # Total entries in buffer (before filtering)


@ws_type
@dataclass
class BufferStats:
    """Statistics for a category buffer."""

    category: str
    count: int
    maxsize: int


@ws_type
@dataclass
class ServerIdentityInfo:
    """Server identity and git state."""

    git_commit: str
    git_commit_short: str
    git_branch: str
    git_dirty: bool
    git_diff_hash: str
    slot: str
    port: int
    pid: int
    start_time: str


@ws_service
class DebugLogService:
    """WebSocket-exposed service for debug logging.

    Provides a way for web clients to send log entries to the shared
    debug log, making them visible in the TUI's debug pane.
    """

    def __init__(self) -> None:
        """Initialize the debug log service."""
        pass

    @ws_expose(fire_and_forget=True)
    def log(self, entry: LogEntryInput) -> LogResult:
        """Log a message from a web client.

        The log entry will appear in the TUI's debug pane with the specified
        level, message, and category. Category defaults to "web" for web
        client logs.

        Exposed as a fire-and-forget call (a JSON-RPC notification): the client
        sends it without an "id" and the server never replies. The returned
        LogResult is discarded on the wire; the entry is still recorded in the
        shared debug log exactly as before. (log_batch, which loops over this
        method, is unaffected - it calls self.log() directly in Python.)

        Args:
            entry: The log entry to add

        Returns:
            LogResult with success status and sequence number (discarded on
            the wire for fire-and-forget callers)
        """
        # Map string level to LogLevel enum
        level_map = {
            "error": LogLevel.ERROR,
            "warning": LogLevel.WARNING,
            "info": LogLevel.INFO,
            "debug": LogLevel.DEBUG,
            "trace": LogLevel.TRACE,
            "perf": LogLevel.PERF,
        }

        level = level_map.get(entry.level.lower(), LogLevel.INFO)
        details = entry.details or {}

        # Add source indicator to details
        details["source"] = "web"

        # Create and add the log entry
        log_entry = debug_log._make_entry(
            level=level,
            message=entry.message,
            session_id=entry.session_id,
            category=entry.category or "web",
            details=details,
        )
        debug_log._add_entry(log_entry)

        return LogResult(success=True, seq=log_entry.seq)

    @ws_expose
    def log_batch(self, entries: list[LogEntryInput]) -> LogResult:
        """Log multiple messages at once.

        Useful for flushing buffered logs from the web client.

        Args:
            entries: List of log entries to add

        Returns:
            LogResult with success status and last sequence number
        """
        last_seq = 0
        for entry in entries:
            result = self.log(entry)
            last_seq = result.seq

        return LogResult(success=True, seq=last_seq)

    @ws_expose(fire_and_forget=True)
    def error(
        self,
        message: str,
        category: str = "web",
        session_id: str = "",
        details: dict | None = None,
    ) -> LogResult:
        """Convenience method to log an error.

        Fire-and-forget (see log): no response, return value discarded on the
        wire. This also means an error log can never reject the caller's
        promise the way the old request/response form could.
        """
        return self.log(
            LogEntryInput(
                level="error",
                message=message,
                category=category,
                session_id=session_id,
                details=details,
            )
        )

    @ws_expose(fire_and_forget=True)
    def warning(
        self,
        message: str,
        category: str = "web",
        session_id: str = "",
        details: dict | None = None,
    ) -> LogResult:
        """Convenience method to log a warning.

        Fire-and-forget (see log): no response, return value discarded on the
        wire.
        """
        return self.log(
            LogEntryInput(
                level="warning",
                message=message,
                category=category,
                session_id=session_id,
                details=details,
            )
        )

    @ws_expose(fire_and_forget=True)
    def info(
        self,
        message: str,
        category: str = "web",
        session_id: str = "",
        details: dict | None = None,
    ) -> LogResult:
        """Convenience method to log an info message.

        Exposed as a fire-and-forget call (a JSON-RPC notification): the
        client sends it without an "id" and the server never replies. This is
        intentional — info logs are high-volume and best-effort, and a
        request/response round-trip per log line dominated UI traffic (see
        tools/wslog analysis). The returned LogResult is discarded on the wire;
        the entry is still recorded in the shared debug log exactly as before.
        """
        return self.log(
            LogEntryInput(
                level="info",
                message=message,
                category=category,
                session_id=session_id,
                details=details,
            )
        )

    @ws_expose(fire_and_forget=True)
    def debug(
        self,
        message: str,
        category: str = "web",
        session_id: str = "",
        details: dict | None = None,
    ) -> LogResult:
        """Convenience method to log a debug message.

        Fire-and-forget (see log): no response, return value discarded on the
        wire.
        """
        return self.log(
            LogEntryInput(
                level="debug",
                message=message,
                category=category,
                session_id=session_id,
                details=details,
            )
        )

    @ws_expose
    def set_enabled(self, enabled: bool) -> LogResult:
        """Enable or disable debug logging globally.

        When disabled, no entries are added to buffers or files.
        This is the main on/off switch for all debug logging.

        Args:
            enabled: True to enable, False to disable

        Returns:
            LogResult with success status
        """
        debug_log.enabled = enabled
        # This log entry will only be recorded if we just enabled
        if enabled:
            debug_log.info(
                "Debug logging enabled",
                category=Category.LIFECYCLE,
            )
        return LogResult(success=True, seq=0)

    @ws_expose
    def is_enabled(self) -> bool:
        """Check if debug logging is enabled.

        Returns:
            True if debug logging is enabled
        """
        return debug_log.enabled

    @ws_expose
    def set_level(self, level: str) -> LogResult:
        """Set the minimum log level for the debug log.

        This controls what gets logged on the server side. Use 'trace' for
        maximum verbosity when debugging API issues.

        Args:
            level: One of 'error', 'warning', 'info', 'perf', 'debug', 'trace'

        Returns:
            LogResult with success status
        """
        level_map = {
            "error": LogLevel.ERROR,
            "warning": LogLevel.WARNING,
            "info": LogLevel.INFO,
            "perf": LogLevel.PERF,
            "debug": LogLevel.DEBUG,
            "trace": LogLevel.TRACE,
        }
        log_level = level_map.get(level.lower())
        if log_level is None:
            return LogResult(success=False, seq=0)

        debug_log.min_level = log_level
        debug_log.info(
            f"Log level set to {level.upper()}",
            category=Category.LIFECYCLE,
        )
        return LogResult(success=True, seq=0)

    @ws_expose
    def get_level(self) -> str:
        """Get the current minimum log level.

        Returns:
            Current log level as string (e.g., 'debug', 'trace')
        """
        return debug_log.min_level.value

    @ws_expose
    def enable_category(self, category: str) -> LogResult:
        """Enable logging for a specific category.

        When any categories are enabled, only those categories will be logged.
        Useful for targeted debugging.

        Categories for API debugging:
        - 'api': API requests, responses, chunks
        - 'tool': Tool execution
        - 'json': JSON parsing errors
        - 'process': Process lifecycle

        Args:
            category: Category to enable

        Returns:
            LogResult with success status
        """
        debug_log.enable_category(category)
        debug_log.info(
            f"Enabled category: {category}",
            category=Category.LIFECYCLE,
        )
        return LogResult(success=True, seq=0)

    @ws_expose
    def disable_category(self, category: str) -> LogResult:
        """Disable logging for a specific category.

        Args:
            category: Category to disable

        Returns:
            LogResult with success status
        """
        debug_log.disable_category(category)
        debug_log.info(
            f"Disabled category: {category}",
            category=Category.LIFECYCLE,
        )
        return LogResult(success=True, seq=0)

    @ws_expose
    def set_categories(self, categories: list[str]) -> LogResult:
        """Set the list of enabled categories.

        Pass an empty list to log all categories (default behavior).

        Args:
            categories: List of category names to enable

        Returns:
            LogResult with success status
        """
        debug_log.set_categories(categories)
        if categories:
            debug_log.info(
                f"Set categories: {', '.join(categories)}",
                category=Category.LIFECYCLE,
            )
        else:
            debug_log.info(
                "Cleared category filter (logging all)",
                category=Category.LIFECYCLE,
            )
        return LogResult(success=True, seq=0)

    @ws_expose
    def get_categories(self) -> list[str]:
        """Get the list of currently enabled categories.

        Returns:
            List of enabled category names, or empty list if all are enabled
        """
        return debug_log.get_categories()

    @ws_expose
    def clear_categories(self) -> LogResult:
        """Clear category filter to log all categories.

        Returns:
            LogResult with success status
        """
        debug_log.clear_categories()
        debug_log.info(
            "Cleared category filter (logging all)",
            category=Category.LIFECYCLE,
        )
        return LogResult(success=True, seq=0)

    # =========================================================================
    # v2 APIs: Per-category querying and buffer management
    # =========================================================================

    @ws_expose
    def get_all_categories(self) -> list[str]:
        """Get all valid category names.

        Returns:
            List of all category names that have dedicated buffers
        """
        return Category.all()

    @ws_expose
    def query(
        self,
        category: str,
        limit: int = 50,
        level: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> QueryResult:
        """Query log entries from a specific category's buffer.

        This is the primary query method for v2. Use this to efficiently
        query entries from a single category's ring buffer.

        Args:
            category: Category to query (e.g., 'api', 'runner')
            limit: Max entries to return (newest first)
            level: Filter by log level (optional)
            session_id: Filter by session (optional)
            run_id: Filter by run (optional)

        Returns:
            QueryResult with matching entries and total buffer count
        """
        # Convert level string to enum if provided
        level_enum = None
        if level:
            level_map = {
                "error": LogLevel.ERROR,
                "warning": LogLevel.WARNING,
                "info": LogLevel.INFO,
                "perf": LogLevel.PERF,
                "debug": LogLevel.DEBUG,
                "trace": LogLevel.TRACE,
            }
            level_enum = level_map.get(level.lower())

        entries = debug_log.query(
            category=category,
            limit=limit,
            level=level_enum,
            session_id=session_id,
            run_id=run_id,
        )

        # Get total buffer count for this category
        stats = debug_log.get_buffer_stats()
        total = stats.get(category, stats.get("_default", {})).get("count", 0)

        # Convert to output format
        output_entries = [
            LogEntryOutput(
                seq=e.seq,
                timestamp=e.timestamp,
                level=e.level.value,
                message=e.message,
                category=e.category,
                session_id=e.session_id,
                run_id=e.run_id,
                details=e.details,
            )
            for e in entries
        ]

        return QueryResult(entries=output_entries, total=total)

    @ws_expose
    def get_buffer_stats(self) -> list[BufferStats]:
        """Get statistics for all category buffers.

        Returns:
            List of BufferStats for each category
        """
        stats = debug_log.get_buffer_stats()
        return [
            BufferStats(category=cat, count=s["count"], maxsize=s["maxsize"])
            for cat, s in stats.items()
        ]

    @ws_expose
    def set_buffer_size(self, category: str, size: int) -> LogResult:
        """Set the buffer size for a category.

        Args:
            category: Category name
            size: New max size (must be > 0)

        Returns:
            LogResult with success status
        """
        success = debug_log.set_buffer_size(category, size)
        if success:
            debug_log.info(
                f"Set buffer size for {category} to {size}",
                category=Category.LIFECYCLE,
            )
        return LogResult(success=success, seq=0)

    @ws_expose
    def clear_buffer(self, category: str | None = None) -> LogResult:
        """Clear log entries from a buffer.

        Args:
            category: Category to clear, or None to clear all

        Returns:
            LogResult with success status
        """
        debug_log.clear(category)
        if category:
            debug_log.info(
                f"Cleared buffer for {category}",
                category=Category.LIFECYCLE,
            )
        else:
            debug_log.info(
                "Cleared all buffers",
                category=Category.LIFECYCLE,
            )
        return LogResult(success=True, seq=0)

    @ws_expose
    def get_server_identity(self) -> ServerIdentityInfo | None:
        """Get server identity (git state, metadata).

        Returns the server's git commit, branch, dirty status, and
        diff hash (fingerprint of local changes). Useful for debugging
        to confirm what code version is running.

        Returns:
            ServerIdentityInfo or None if not captured
        """
        identity = get_identity()
        if identity is None:
            return None
        return ServerIdentityInfo(
            git_commit=identity.git_commit,
            git_commit_short=identity.git_commit_short,
            git_branch=identity.git_branch,
            git_dirty=identity.git_dirty,
            git_diff_hash=identity.git_diff_hash,
            slot=identity.slot,
            port=identity.port,
            pid=identity.pid,
            start_time=identity.start_time,
        )
