"""Debug pane widget for Balloons.

Collapsible bottom drawer showing debug log entries for Claude observability.
Uses RichLog for simple append-only display with strict ordering by sequence number.
"""

from textual.message import Message
from textual.widgets import RichLog
from rich.text import Text

from core.debug_log import debug_log, LogEntry, LogLevel


class DebugPane(RichLog):
    """Collapsible debug pane showing log entries.

    Simple append-only log display. Entries are ordered strictly by their
    monotonic sequence number to prevent UI jumping.
    Toggle with Ctrl+G, auto-expands on errors.
    """

    class NewLogEntry(Message):
        """Message posted when a new log entry arrives.

        Using Textual messages ensures entries are processed in order
        on the main thread, preventing race conditions.
        """

        def __init__(self, entry: LogEntry) -> None:
            super().__init__()
            self.entry = entry

    DEFAULT_CSS = """
    DebugPane {
        height: 0;
        background: $surface;
        border-top: solid $primary;
        scrollbar-size: 1 1;
    }

    DebugPane.expanded {
        height: 14;
    }

    DebugPane.auto-expanded {
        height: 10;
        border-top: solid $error;
    }
    """

    LEVEL_COLORS = {
        LogLevel.ERROR: "red",
        LogLevel.WARNING: "yellow",
        LogLevel.INFO: "white",
        LogLevel.DEBUG: "dim white",
    }

    LEVEL_SYMBOLS = {
        LogLevel.ERROR: "E",
        LogLevel.WARNING: "W",
        LogLevel.INFO: "I",
        LogLevel.DEBUG: "D",
    }

    def __init__(self, **kwargs):
        super().__init__(highlight=False, markup=False, wrap=False, **kwargs)
        self._expanded = False
        self._auto_expanded = False
        self._last_seq = 0  # Track last displayed sequence number

    def on_mount(self) -> None:
        """Subscribe to debug log updates."""
        # Load existing entries FIRST (before adding listener)
        # get_entries returns newest-first, so reverse to add oldest-first
        for entry in reversed(debug_log.get_entries(limit=100)):
            self._add_entry(entry)
        # Now subscribe to new entries - they'll arrive after existing ones
        debug_log.add_listener(self._on_log_entry)

    def on_unmount(self) -> None:
        """Unsubscribe from debug log updates."""
        debug_log.remove_listener(self._on_log_entry)

    def _on_log_entry(self, entry: LogEntry) -> None:
        """Handle new log entry from debug_log listener.

        Posts a message to ensure processing happens on Textual's main thread,
        maintaining correct ordering even when entries arrive from async tasks.
        """
        # Post message to process on main thread - this ensures ordering
        self.post_message(self.NewLogEntry(entry))

    def on_debug_pane_new_log_entry(self, message: NewLogEntry) -> None:
        """Process log entry on the main thread."""
        entry = message.entry
        self._add_entry(entry)

        # Auto-expand on errors
        if entry.level == LogLevel.ERROR and not self._expanded:
            self._auto_expanded = True
            self.add_class("auto-expanded")

    def _add_entry(self, entry: LogEntry) -> None:
        """Add an entry to the log, enforcing strict sequence ordering."""
        # Skip entries we've already displayed (prevents duplicates)
        if entry.seq <= self._last_seq:
            return

        self._last_seq = entry.seq

        # Format and write the entry
        label = self._format_entry(entry)
        self.write(label)

    def _format_entry(self, entry: LogEntry) -> Text:
        """Format a log entry for display."""
        color = self.LEVEL_COLORS.get(entry.level, "white")
        symbol = self.LEVEL_SYMBOLS.get(entry.level, "?")

        text = Text()
        text.append(f"[{entry.timestamp}] ", style="dim")
        text.append(f"[{symbol}] ", style=color)

        if entry.run_id:
            text.append(f"pid:{entry.run_id} ", style="cyan dim")

        if entry.category:
            text.append(f"{entry.category}: ", style="cyan")

        # Truncate long messages
        message = entry.message
        if len(message) > 100:
            message = message[:97] + "..."
        text.append(message, style=color if entry.level in (LogLevel.ERROR, LogLevel.WARNING) else "")

        # Show key details inline (compact)
        if entry.details:
            details_parts = []
            for k, v in entry.details.items():
                if k == "stderr" and v:
                    first_line = str(v).split('\n')[0][:40]
                    details_parts.append(f"stderr={first_line}...")
                elif k == "text" and v:
                    content = str(v).replace("\n", "\\n")
                    if len(content) > 40:
                        content = content[:37] + "..."
                    details_parts.append(f'text="{content}"')
                elif k not in ("prompt_len", "json"):
                    str_v = str(v)
                    if len(str_v) > 30:
                        str_v = str_v[:27] + "..."
                    details_parts.append(f"{k}={str_v}")
            if details_parts:
                text.append(f" ({', '.join(details_parts)})", style="dim")

        return text

    def toggle(self) -> None:
        """Toggle the debug pane visibility."""
        if self._expanded or self._auto_expanded:
            self._expanded = False
            self._auto_expanded = False
            self.remove_class("expanded")
            self.remove_class("auto-expanded")
        else:
            self._expanded = True
            self._auto_expanded = False
            self.add_class("expanded")
            self.remove_class("auto-expanded")

    def clear_entries(self) -> None:
        """Clear all displayed entries."""
        self.clear()
        self._last_seq = 0
        debug_log.clear()

    @property
    def is_expanded(self) -> bool:
        """Check if pane is expanded (manually or auto)."""
        return self._expanded or self._auto_expanded
