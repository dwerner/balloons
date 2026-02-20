"""Stream pane showing active LLM streams and their status."""

from textual.widgets import Static, Tree
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.timer import Timer
from textual.message import Message
from rich.text import Text
from datetime import datetime

from core.stream_state import (
    get_stream_state,
    Stream,
    StreamStatus,
    StreamType,
    StreamEvent,
)


# Sparkline characters (8 levels of height)
SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"


class ClickableSessionLink(Static):
    """A clickable session link that posts a message when clicked."""

    DEFAULT_CSS = """
    ClickableSessionLink {
        width: auto;
        height: auto;
    }

    ClickableSessionLink:hover {
        background: $primary 20%;
    }
    """

    class Clicked(Message):
        """Posted when user clicks the session link."""

        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    def __init__(self, session_id: str, display_text: str, **kwargs):
        super().__init__(**kwargs)
        self.session_id = session_id
        self._display_text = display_text

    def render(self) -> Text:
        text = Text()
        text.append("  Session: ", style="dim")
        text.append(self._display_text, style="cyan underline")
        text.append(" ", style="dim")
        text.append("→", style="cyan dim")
        return text

    def on_click(self) -> None:
        """Navigate to the session when clicked."""
        self.post_message(self.Clicked(self.session_id))


def render_sparkline(values: list[float], width: int = 20) -> str:
    """Render a sparkline from values.

    Args:
        values: List of numeric values
        width: Max width of sparkline

    Returns:
        String of sparkline characters
    """
    if not values:
        return ""

    # Take last `width` values
    values = values[-width:]

    if not values:
        return ""

    min_val = min(values)
    max_val = max(values)
    val_range = max_val - min_val

    if val_range == 0:
        # All values the same - show middle height
        return SPARKLINE_CHARS[3] * len(values)

    result = []
    for val in values:
        # Normalize to 0-1, then map to character index
        normalized = (val - min_val) / val_range
        char_idx = int(normalized * (len(SPARKLINE_CHARS) - 1))
        char_idx = max(0, min(char_idx, len(SPARKLINE_CHARS) - 1))
        result.append(SPARKLINE_CHARS[char_idx])

    return "".join(result)


class TaskPane(Vertical):
    """Right panel showing active streams in a tree with details below."""

    DEFAULT_CSS = """
    TaskPane {
        width: 60;
        height: 100%;
        border-left: solid $primary;
    }

    TaskPane.hidden {
        display: none;
    }

    TaskPane > #task-tree {
        height: 1fr;
        min-height: 8;
        background: $background;
    }

    TaskPane > #task-detail-scroll {
        height: 1fr;
        border-top: solid $primary;
    }

    TaskPane > #task-detail-scroll > #task-detail-header {
        padding: 1 1 0 1;
    }

    TaskPane > #task-detail-scroll > #task-detail-body {
        padding: 0 1 1 1;
    }

    TaskPane > #task-detail-scroll > ClickableSessionLink {
        padding: 0 1;
    }
    """

    # Reactive to trigger updates
    task_count = reactive(0)

    # Spinner animation for active tasks
    _spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._selected_stream_id: str | None = None
        self._stream_state = get_stream_state()

        # Spinner animation state
        self._spinner_frame: int = 0
        self._spinner_timer: Timer | None = None

    def compose(self):
        tree = Tree("[bold]Streams[/]", id="task-tree")
        tree.root.expand()
        yield tree
        with VerticalScroll(id="task-detail-scroll"):
            yield Static("Select a stream to view details", id="task-detail-header")
            # Session link is dynamically added/removed
            yield Static("", id="task-detail-body")

    def on_mount(self) -> None:
        """Start observing task state changes."""
        self._stream_state.add_observer(self._on_task_event)
        # Initial render
        self._refresh_task_tree()
        # Start spinner if any tasks are already active
        if self._stream_state.get_active_count() > 0:
            self._start_spinner()

    def on_unmount(self) -> None:
        """Stop observing task state changes."""
        self._stream_state.remove_observer(self._on_task_event)
        self._stop_spinner()

    def on_show(self) -> None:
        """When pane becomes visible, ensure spinner is running if needed.

        Textual may pause timers for hidden widgets, so we restart the spinner
        whenever the pane becomes visible to ensure the display stays updated.
        """
        # Stop any existing timer that might be stale
        self._stop_spinner()
        # Restart spinner if there are active streams
        if self._stream_state.get_active_count() > 0:
            self._start_spinner()
        self._refresh_task_tree()

    async def _on_task_event(self, event: StreamEvent, stream: Stream) -> None:
        """Handle task state changes (async observer)."""
        # Skip if not mounted yet
        if not self.is_mounted:
            return

        # Update the reactive to trigger a refresh
        active_count = self._stream_state.get_active_count()
        self.task_count = active_count

        # Only do expensive refreshes if visible
        if self.display:
            self._refresh_task_tree()

        # Start/stop spinner based on active task count
        if active_count > 0:
            self._start_spinner()
        else:
            self._stop_spinner()

        # If viewing this stream, refresh detail (only if visible)
        if self.display and self._selected_stream_id == stream.stream_id:
            self._show_stream_detail(stream)

    def _refresh_task_tree(self) -> None:
        """Rebuild the task tree."""
        tree = self.query_one("#task-tree", Tree)

        # Remember expanded state
        was_expanded = tree.root.is_expanded

        # Clear and rebuild
        tree.root.remove_children()

        active_streams = self._stream_state.get_active_streams()
        recent_completed = [
            s for s in self._stream_state.get_all_streams()
            if not s.is_active
        ][:5]  # Show last 5 completed

        # Ensure spinner is running if we have active streams
        active_count = len(active_streams)
        if active_count > 0 and self._spinner_timer is None:
            self._start_spinner()

        # Update root label
        if active_count > 0:
            tree.root.set_label(f"[bold]Streams[/] [green]({active_count} active)[/]")
        else:
            tree.root.set_label("[bold]Streams[/] [dim](none active)[/]")

        if active_streams:
            active_node = tree.root.add("[green bold]Active[/]", expand=True)
            for stream in active_streams:
                label = self._format_stream_label(stream)
                active_node.add_leaf(label, data={"stream_id": stream.stream_id})

        if recent_completed:
            recent_node = tree.root.add("[dim]Recent[/]", expand=True)
            for stream in recent_completed:
                label = self._format_stream_label(stream)
                recent_node.add_leaf(label, data={"stream_id": stream.stream_id})

        if was_expanded:
            tree.root.expand()

        # Force the tree widget to refresh and re-render
        tree.refresh()

    def _format_stream_label(self, stream: Stream) -> str:
        """Format a single stream for the tree as a markup string."""
        status_style = self._get_status_style(stream.status)
        status_icon = self._get_status_icon(stream.status)
        type_label = self._get_type_label(stream.stream_type)
        duration = f"{stream.duration_seconds:.1f}s"

        # Build markup string
        parts = [
            f"[{status_style}]{status_icon}[/]",
            f" [bold]{type_label}[/]",
            f" [dim]({duration})[/]",
        ]

        if stream.backend_name:
            parts.append(f" [cyan dim]\\[{stream.backend_name}][/]")

        return "".join(parts)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle stream selection in tree."""
        node_data = event.node.data
        if not node_data:
            return

        stream_id = node_data.get("stream_id")
        if stream_id:
            self._selected_stream_id = stream_id
            stream = self._stream_state.get_stream(stream_id)
            if stream:
                self._show_stream_detail(stream)

    def _get_status_style(self, status: StreamStatus) -> str:
        """Get Rich style for a status."""
        return {
            StreamStatus.PENDING: "dim",
            StreamStatus.STREAMING: "green",
            StreamStatus.EXECUTING: "yellow",
            StreamStatus.COMPLETED: "dim green",
            StreamStatus.ERROR: "red",
            StreamStatus.CANCELLED: "dim red",
        }.get(status, "dim")

    def _get_status_icon(self, status: StreamStatus) -> str:
        """Get icon for a status.

        Active statuses (PENDING, STREAMING, EXECUTING) get animated spinner.
        Completed statuses get static icons.
        """
        if status in (StreamStatus.STREAMING, StreamStatus.EXECUTING, StreamStatus.PENDING):
            # Use animated spinner for active tasks
            return self._spinner_chars[self._spinner_frame]
        return {
            StreamStatus.COMPLETED: "✓",
            StreamStatus.ERROR: "✗",
            StreamStatus.CANCELLED: "⊘",
        }.get(status, "?")

    def _get_type_label(self, stream_type: StreamType) -> str:
        """Get human-readable label for stream type."""
        return {
            StreamType.CHAT: "Chat",
            StreamType.COMPRESSION: "Compress",
            StreamType.MERGE_SUMMARY: "Merge",
            StreamType.LINK_SUMMARY: "Link",
            StreamType.ARCHIVE_SUMMARY: "Archive",
            StreamType.TITLE: "Title",
        }.get(stream_type, str(stream_type.value))

    # --- Spinner Animation ---

    def _start_spinner(self) -> None:
        """Start the spinner animation for active tasks."""
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.1, self._advance_spinner)

    def _stop_spinner(self) -> None:
        """Stop the spinner animation."""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
            self._spinner_frame = 0

    def _advance_spinner(self) -> None:
        """Advance the spinner to the next frame and update active stream labels."""
        try:
            self._spinner_frame = (self._spinner_frame + 1) % len(self._spinner_chars)

            # Only do expensive refreshes if visible
            if not self.display:
                return

            # Refresh tree to show updated spinner and durations
            self._refresh_task_tree()
            # Also refresh detail pane if showing an active stream
            if self._selected_stream_id:
                stream = self._stream_state.get_stream(self._selected_stream_id)
                if stream and stream.is_active:
                    self._show_stream_detail(stream)
        except Exception:
            # Don't let errors stop the timer
            pass

    def _show_stream_detail(self, stream: Stream) -> None:
        """Show detailed properties for selected stream."""
        header_widget = self.query_one("#task-detail-header", Static)
        body_widget = self.query_one("#task-detail-body", Static)
        scroll_container = self.query_one("#task-detail-scroll", VerticalScroll)

        # Build header lines (status, properties section start)
        header_lines = []

        # Header with status
        status_icon = self._get_status_icon(stream.status)
        status_style = self._get_status_style(stream.status)
        header = Text()
        header.append(f"{status_icon} ", style=status_style)
        header.append(self._get_type_label(stream.stream_type), style="bold")
        header.append(f" - {stream.status.value}", style=status_style)
        header_lines.append(header)
        header_lines.append(Text(""))

        # Properties section
        header_lines.append(Text("Properties", style="bold underline"))

        # Stream ID
        header_lines.append(Text(f"  Stream ID: ", style="dim").append(stream.stream_id[:16] + ("..." if len(stream.stream_id) > 16 else "")))

        # Update header widget
        header_output = Text()
        for i, line in enumerate(header_lines):
            if i > 0:
                header_output.append("\n")
            header_output.append_text(line)
        header_widget.update(header_output)

        # Handle clickable session link
        # Only update if session_id changed to avoid flicker during spinner updates
        existing_links = list(scroll_container.query(ClickableSessionLink))
        existing_session_id = existing_links[0].session_id if existing_links else None

        if existing_session_id != stream.session_id:
            # Remove existing links
            for link in existing_links:
                link.remove()

            # Add new link if stream has a session
            if stream.session_id:
                display_text = stream.session_id[:16] + ("..." if len(stream.session_id) > 16 else "")
                session_link = ClickableSessionLink(
                    stream.session_id,
                    display_text,
                )
                # Mount after header, before body
                scroll_container.mount(session_link, after=header_widget)

        # Build body lines (everything after session)
        body_lines = []

        # Backend
        if stream.backend_name:
            body_lines.append(Text(f"  Backend: ", style="dim").append(stream.backend_name, style="cyan"))

        # Model
        if stream.model:
            body_lines.append(Text(f"  Model: ", style="dim").append(stream.model, style="magenta"))

        body_lines.append(Text(""))

        # Timing section
        body_lines.append(Text("Timing", style="bold underline"))
        started = stream.started_at.strftime("%H:%M:%S.%f")[:-3]
        body_lines.append(Text(f"  Started: ", style="dim").append(started))
        body_lines.append(Text(f"  Duration: ", style="dim").append(f"{stream.duration_seconds:.2f}s", style="green" if stream.is_active else ""))

        if stream.finished_at:
            finished = stream.finished_at.strftime("%H:%M:%S.%f")[:-3]
            body_lines.append(Text(f"  Finished: ", style="dim").append(finished))

        body_lines.append(Text(""))

        # Tokens section
        body_lines.append(Text("Tokens", style="bold underline"))

        # Get output token count (prefer actual, fall back to estimate)
        output_count = stream.output_tokens if stream.output_tokens > 0 else stream.tokens_streamed
        is_estimated = stream.output_tokens == 0 and stream.tokens_streamed > 0

        # Context window usage (input tokens = context sent to API)
        if stream.context_window > 0 and stream.input_tokens > 0:
            usage_pct = (stream.input_tokens / stream.context_window * 100)
            usage_style = "red" if usage_pct > 80 else ("yellow" if usage_pct > 50 else "green")
            context_line = Text(f"  Context Window: ", style="dim")
            context_line.append(f"{stream.input_tokens:,}", style=usage_style)
            context_line.append(f" / {stream.context_window:,}", style="dim")
            context_line.append(f" ({usage_pct:.1f}%)", style=usage_style)
            body_lines.append(context_line)

        # Output tokens (response tokens)
        if output_count > 0:
            output_style = "green"
            output_text = f"~{output_count:,}" if is_estimated else f"{output_count:,}"
            body_lines.append(Text(f"  Output: ", style="dim").append(output_text, style=output_style))

        # Token rate and sparkline (inference speed)
        token_rate = stream.current_token_rate
        if token_rate > 0:
            rate_text = Text(f"  Speed: ", style="dim").append(f"{token_rate:.1f} tok/s", style="cyan")
            body_lines.append(rate_text)

            # Render sparkline of recent rates
            rates = stream.get_token_rates()
            if rates:
                sparkline = render_sparkline(rates, width=30)
                sparkline_text = Text(f"  ", style="dim").append(sparkline, style="cyan")
                body_lines.append(sparkline_text)

        body_lines.append(Text(""))

        # Tools section
        body_lines.append(Text("Tools", style="bold underline"))
        tools_style = "yellow" if stream.tool_count > 0 else "dim"
        body_lines.append(Text(f"  Executed: ", style="dim").append(str(stream.tool_count), style=tools_style))

        if stream.tool_name:
            body_lines.append(Text(f"  Current: ", style="dim").append(stream.tool_name, style="yellow bold"))

        # Error section
        if stream.error:
            body_lines.append(Text(""))
            body_lines.append(Text("Error", style="bold underline red"))
            # Wrap error text
            error_text = stream.error
            body_lines.append(Text(f"  {error_text}", style="red"))

        # Prompt section
        if stream.prompt:
            body_lines.append(Text(""))
            body_lines.append(Text("Prompt", style="bold underline"))
            # Show truncated prompt
            prompt_preview = stream.prompt[:300]
            if len(stream.prompt) > 300:
                prompt_preview += "..."
            body_lines.append(Text(f"  {prompt_preview}", style="italic dim"))

        # Combine body lines
        body_output = Text()
        for i, line in enumerate(body_lines):
            if i > 0:
                body_output.append("\n")
            body_output.append_text(line)

        body_widget.update(body_output)

    def refresh_tasks(self) -> None:
        """Manually refresh the task tree."""
        self._refresh_task_tree()
