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
from core.debug_log import debug_log, LogLevel


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


@ws_service
class DebugLogService:
    """WebSocket-exposed service for debug logging.

    Provides a way for web clients to send log entries to the shared
    debug log, making them visible in the TUI's debug pane.
    """

    def __init__(self) -> None:
        """Initialize the debug log service."""
        pass

    @ws_expose
    def log(self, entry: LogEntryInput) -> LogResult:
        """Log a message from a web client.

        The log entry will appear in the TUI's debug pane with the specified
        level, message, and category. Category defaults to "web" for web
        client logs.

        Args:
            entry: The log entry to add

        Returns:
            LogResult with success status and sequence number
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

    @ws_expose
    def error(
        self,
        message: str,
        category: str = "web",
        session_id: str = "",
        details: dict | None = None,
    ) -> LogResult:
        """Convenience method to log an error."""
        return self.log(
            LogEntryInput(
                level="error",
                message=message,
                category=category,
                session_id=session_id,
                details=details,
            )
        )

    @ws_expose
    def warning(
        self,
        message: str,
        category: str = "web",
        session_id: str = "",
        details: dict | None = None,
    ) -> LogResult:
        """Convenience method to log a warning."""
        return self.log(
            LogEntryInput(
                level="warning",
                message=message,
                category=category,
                session_id=session_id,
                details=details,
            )
        )

    @ws_expose
    def info(
        self,
        message: str,
        category: str = "web",
        session_id: str = "",
        details: dict | None = None,
    ) -> LogResult:
        """Convenience method to log an info message."""
        return self.log(
            LogEntryInput(
                level="info",
                message=message,
                category=category,
                session_id=session_id,
                details=details,
            )
        )

    @ws_expose
    def debug(
        self,
        message: str,
        category: str = "web",
        session_id: str = "",
        details: dict | None = None,
    ) -> LogResult:
        """Convenience method to log a debug message."""
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
            category="debug",
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
            category="debug",
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
            category="debug",
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
                category="debug",
            )
        else:
            debug_log.info(
                "Cleared category filter (logging all)",
                category="debug",
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
            category="debug",
        )
        return LogResult(success=True, seq=0)
