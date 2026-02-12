"""Debug pane widget for Balloons.

Collapsible bottom drawer showing debug log entries for Claude observability.
Uses RichLog for simple append-only display with strict ordering by sequence number.
Includes a log level selector to filter by severity.
"""

from textual.events import Click
from textual.message import Message
from textual.widgets import RichLog, Static
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from rich.text import Text

from core.debug_log import debug_log, LogEntry, LogLevel


class LogLevelSelector(Static):
    """Clickable log level selector widget.

    Shows buttons for each log level. Clicking a level sets the minimum
    display level (e.g., clicking INFO shows INFO, WARNING, ERROR).
    """

    DEFAULT_CSS = """
    LogLevelSelector {
        height: 1;
        width: auto;
        padding: 0 1;
        background: $surface-darken-1;
    }

    LogLevelSelector .level-btn {
        padding: 0 1;
    }

    LogLevelSelector .level-btn.active {
        text-style: bold reverse;
    }
    """

    class LevelChanged(Message):
        """Posted when user clicks a log level button."""

        def __init__(self, level: LogLevel) -> None:
            super().__init__()
            self.level = level

    # Level order from most verbose to most severe
    LEVELS = [LogLevel.TRACE, LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR]

    LEVEL_LABELS = {
        LogLevel.ERROR: "E",
        LogLevel.WARNING: "W",
        LogLevel.INFO: "I",
        LogLevel.DEBUG: "D",
        LogLevel.TRACE: "T",
    }

    LEVEL_COLORS = {
        LogLevel.ERROR: "red",
        LogLevel.WARNING: "yellow",
        LogLevel.INFO: "white",
        LogLevel.DEBUG: "dim white",
        LogLevel.TRACE: "dim cyan",
    }

    current_level: reactive[LogLevel] = reactive(LogLevel.DEBUG)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_level = debug_log.min_level

    def render(self) -> Text:
        """Render the level selector as clickable buttons."""
        text = Text()
        text.append("Level: ", style="dim")

        for i, level in enumerate(self.LEVELS):
            color = self.LEVEL_COLORS[level]
            label = self.LEVEL_LABELS[level]

            # Check if this level is active (at or above min_level)
            is_active = LogLevel.severity(level) >= LogLevel.severity(self.current_level)

            if is_active:
                text.append(f"[{label}]", style=f"bold {color} reverse")
            else:
                text.append(f"[{label}]", style=f"dim {color}")

            if i < len(self.LEVELS) - 1:
                text.append(" ")

        return text

    def on_click(self, event: Click) -> None:
        """Handle click on level buttons."""
        # Calculate which button was clicked based on x position
        # Format: "Level: [T] [D] [I] [W] [E]"
        # "Level: " = 7 chars, each button = 3 chars + 1 space
        content_offset = event.get_content_offset(self)
        if content_offset is None:
            return

        x = content_offset.x
        # Subtract padding and "Level: " prefix
        x_adjusted = x - 7  # "Level: " = 7 chars

        if x_adjusted < 0:
            return

        # Each level button is 3 chars + 1 space = 4 chars (except last)
        button_idx = x_adjusted // 4
        if 0 <= button_idx < len(self.LEVELS):
            level = self.LEVELS[button_idx]
            self.current_level = level
            debug_log.min_level = level
            self.post_message(self.LevelChanged(level))
            self.refresh()


class DebugLogView(RichLog):
    """The actual log display (RichLog-based)."""

    DEFAULT_CSS = """
    DebugLogView {
        height: 1fr;
        scrollbar-size: 1 1;
    }
    """

    LEVEL_COLORS = {
        LogLevel.ERROR: "red",
        LogLevel.WARNING: "yellow",
        LogLevel.INFO: "white",
        LogLevel.DEBUG: "dim white",
        LogLevel.TRACE: "dim cyan",
    }

    LEVEL_SYMBOLS = {
        LogLevel.ERROR: "E",
        LogLevel.WARNING: "W",
        LogLevel.INFO: "I",
        LogLevel.DEBUG: "D",
        LogLevel.TRACE: "T",
    }

    class LogLineSelected(Message):
        """Message posted when user Ctrl+clicks a log line."""

        def __init__(self, text: str, line_idx: int) -> None:
            super().__init__()
            self.text = text
            self.line_idx = line_idx

    def __init__(self, **kwargs):
        super().__init__(highlight=False, markup=False, wrap=False, **kwargs)
        self._last_seq = 0
        self._line_entries: list[LogEntry] = []
        self._highlighted_line: int | None = None

    def _format_entry(self, entry: LogEntry, highlighted: bool = False) -> Text:
        """Format a log entry for display."""
        color = self.LEVEL_COLORS.get(entry.level, "white")
        symbol = self.LEVEL_SYMBOLS.get(entry.level, "?")

        text = Text()

        # Add highlight background if this line is highlighted
        base_style = "on #333366" if highlighted else ""

        text.append(f"[{entry.timestamp}] ", style=f"dim {base_style}")
        text.append(f"[{symbol}] ", style=f"{color} {base_style}")

        if entry.run_id:
            text.append(f"pid:{entry.run_id} ", style=f"cyan dim {base_style}")

        if entry.category:
            text.append(f"{entry.category}: ", style=f"cyan {base_style}")

        # Truncate long messages
        message = entry.message
        if len(message) > 100:
            message = message[:97] + "..."

        msg_style = color if entry.level in (LogLevel.ERROR, LogLevel.WARNING) else ""
        text.append(message, style=f"{msg_style} {base_style}")

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
                text.append(f" ({', '.join(details_parts)})", style=f"dim {base_style}")

        return text

    def _format_entry_full(self, entry: LogEntry) -> str:
        """Format a log entry as full text for insertion into input."""
        parts = [f"[{entry.timestamp}]"]
        symbol = self.LEVEL_SYMBOLS.get(entry.level, "?")
        parts.append(f"[{symbol}]")

        if entry.run_id:
            parts.append(f"pid:{entry.run_id}")

        if entry.category:
            parts.append(f"{entry.category}:")

        parts.append(entry.message)

        # Include full details for context
        if entry.details:
            details_parts = []
            for k, v in entry.details.items():
                str_v = str(v)
                details_parts.append(f"{k}={str_v}")
            if details_parts:
                parts.append(f"({', '.join(details_parts)})")

        return " ".join(parts)

    def add_entry(self, entry: LogEntry) -> None:
        """Add an entry to the log, enforcing strict sequence ordering."""
        if entry.seq <= self._last_seq:
            return

        self._last_seq = entry.seq
        self._line_entries.append(entry)

        label = self._format_entry(entry)
        self.write(label)

    def highlight_line(self, line_idx: int) -> None:
        """Highlight a specific line visually."""
        if self._highlighted_line is not None:
            # Clear previous highlight by re-rendering that line
            self._rerender_line(self._highlighted_line, highlighted=False)

        self._highlighted_line = line_idx
        self._rerender_line(line_idx, highlighted=True)

    def _rerender_line(self, line_idx: int, highlighted: bool) -> None:
        """Re-render a specific line with or without highlight."""
        if 0 <= line_idx < len(self._line_entries):
            # RichLog doesn't support in-place updates, so we can't truly
            # re-render. Instead, we'll just track the highlight state for
            # visual feedback via border color change on the parent.
            pass

    def clear_entries(self) -> None:
        """Clear all displayed entries."""
        self.clear()
        self._last_seq = 0
        self._line_entries.clear()
        self._highlighted_line = None

    def on_click(self, event: Click) -> None:
        """Handle click on log lines. Ctrl+click inserts into input."""
        if event.ctrl:
            content_offset = event.get_content_offset(self)
            if content_offset is None:
                return

            # RichLog uses scroll_y for vertical scroll position
            # content_offset.y is the y within the visible area
            # We need to add scroll_y to get the actual line index
            line_idx = int(content_offset.y + self.scroll_y)

            if 0 <= line_idx < len(self._line_entries):
                entry = self._line_entries[line_idx]
                full_text = self._format_entry_full(entry)
                self.post_message(self.LogLineSelected(full_text, line_idx))
                event.stop()


class DebugPane(Vertical):
    """Collapsible debug pane showing log entries.

    Contains a log level selector and the actual log view.
    Toggle with Ctrl+G, auto-expands on errors.
    """

    class NewLogEntry(Message):
        """Message posted when a new log entry arrives."""

        def __init__(self, entry: LogEntry) -> None:
            super().__init__()
            self.entry = entry

    class LogLineSelected(Message):
        """Message posted when user Ctrl+clicks a log line."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    DEFAULT_CSS = """
    DebugPane {
        height: 0;
        background: $surface;
        border-top: solid $primary;
    }

    DebugPane.expanded {
        height: 14;
    }

    DebugPane.auto-expanded {
        height: 10;
        border-top: solid $error;
    }

    DebugPane.line-selected {
        border-top: solid $accent;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._expanded = False
        self._auto_expanded = False
        self._log_view: DebugLogView | None = None
        self._level_selector: LogLevelSelector | None = None

    def compose(self):
        self._level_selector = LogLevelSelector(id="log-level-selector")
        self._log_view = DebugLogView(id="debug-log-view")
        yield self._level_selector
        yield self._log_view

    def on_mount(self) -> None:
        """Subscribe to debug log updates."""
        # Load existing entries
        for entry in reversed(debug_log.get_entries(limit=100)):
            if self._log_view:
                self._log_view.add_entry(entry)
        # Subscribe to new entries
        debug_log.add_listener(self._on_log_entry)

    def on_unmount(self) -> None:
        """Unsubscribe from debug log updates."""
        debug_log.remove_listener(self._on_log_entry)

    def _on_log_entry(self, entry: LogEntry) -> None:
        """Handle new log entry from debug_log listener."""
        self.post_message(self.NewLogEntry(entry))

    def on_debug_pane_new_log_entry(self, message: NewLogEntry) -> None:
        """Process log entry on the main thread."""
        entry = message.entry
        if self._log_view:
            self._log_view.add_entry(entry)

        # Auto-expand on errors
        if entry.level == LogLevel.ERROR and not self._expanded:
            self._auto_expanded = True
            self.add_class("auto-expanded")

    def on_debug_log_view_log_line_selected(self, event: DebugLogView.LogLineSelected) -> None:
        """Handle log line selection from the log view."""
        # Show visual feedback
        self.add_class("line-selected")
        # Schedule removal of the visual feedback
        self.set_timer(0.5, lambda: self.remove_class("line-selected"))
        # Bubble up the message
        self.post_message(self.LogLineSelected(event.text))

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
        if self._log_view:
            self._log_view.clear_entries()
        debug_log.clear()

    @property
    def is_expanded(self) -> bool:
        """Check if pane is expanded (manually or auto)."""
        return self._expanded or self._auto_expanded
