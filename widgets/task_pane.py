"""Task pane showing active LLM tasks and their status."""

from textual.widgets import Static, Tree
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from rich.text import Text
from datetime import datetime

from core.task_state import (
    get_task_state,
    Task,
    TaskStatus,
    TaskType,
    TaskEvent,
)


# Sparkline characters (8 levels of height)
SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"


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
    """Right panel showing active tasks in a tree with details below."""

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

    TaskPane > #task-detail-scroll > #task-detail {
        padding: 1;
    }
    """

    # Reactive to trigger updates
    task_count = reactive(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._selected_task_id: str | None = None
        self._task_state = get_task_state()

    def compose(self):
        tree = Tree("[bold]Tasks[/]", id="task-tree")
        tree.root.expand()
        yield tree
        with VerticalScroll(id="task-detail-scroll"):
            yield Static("Select a task to view details", id="task-detail")

    def on_mount(self) -> None:
        """Start observing task state changes."""
        self._task_state.add_observer(self._on_task_event)
        # Initial render
        self._refresh_task_tree()

    def on_unmount(self) -> None:
        """Stop observing task state changes."""
        self._task_state.remove_observer(self._on_task_event)

    async def _on_task_event(self, event: TaskEvent, task: Task) -> None:
        """Handle task state changes (async observer)."""
        # Skip if not mounted yet
        if not self.is_mounted:
            return

        # Update the reactive to trigger a refresh
        self.task_count = self._task_state.get_active_count()
        self._refresh_task_tree()

        # If viewing this task, refresh detail
        if self._selected_task_id == task.task_id:
            self._show_task_detail(task)

    def _refresh_task_tree(self) -> None:
        """Rebuild the task tree."""
        tree = self.query_one("#task-tree", Tree)

        # Remember expanded state
        was_expanded = tree.root.is_expanded

        # Clear and rebuild
        tree.root.remove_children()

        active_tasks = self._task_state.get_active_tasks()
        recent_completed = [
            t for t in self._task_state.get_all_tasks()
            if not t.is_active
        ][:5]  # Show last 5 completed

        # Update root label
        active_count = len(active_tasks)
        if active_count > 0:
            tree.root.set_label(f"[bold]Tasks[/] [green]({active_count} active)[/]")
        else:
            tree.root.set_label("[bold]Tasks[/] [dim](none active)[/]")

        if active_tasks:
            active_node = tree.root.add("[green bold]Active[/]", expand=True)
            for task in active_tasks:
                label = self._format_task_label(task)
                active_node.add_leaf(label, data={"task_id": task.task_id})

        if recent_completed:
            recent_node = tree.root.add("[dim]Recent[/]", expand=True)
            for task in recent_completed:
                label = self._format_task_label(task)
                recent_node.add_leaf(label, data={"task_id": task.task_id})

        if was_expanded:
            tree.root.expand()

    def _format_task_label(self, task: Task) -> str:
        """Format a single task for the tree as a markup string."""
        status_style = self._get_status_style(task.status)
        status_icon = self._get_status_icon(task.status)
        type_label = self._get_type_label(task.task_type)
        duration = f"{task.duration_seconds:.1f}s"

        # Build markup string
        parts = [
            f"[{status_style}]{status_icon}[/]",
            f" [bold]{type_label}[/]",
            f" [dim]({duration})[/]",
        ]

        if task.backend_name:
            parts.append(f" [cyan dim]\\[{task.backend_name}][/]")

        return "".join(parts)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle task selection in tree."""
        node_data = event.node.data
        if not node_data:
            return

        task_id = node_data.get("task_id")
        if task_id:
            self._selected_task_id = task_id
            task = self._task_state.get_task(task_id)
            if task:
                self._show_task_detail(task)

    def _get_status_style(self, status: TaskStatus) -> str:
        """Get Rich style for a status."""
        return {
            TaskStatus.PENDING: "dim",
            TaskStatus.STREAMING: "green",
            TaskStatus.EXECUTING: "yellow",
            TaskStatus.COMPLETED: "dim green",
            TaskStatus.ERROR: "red",
            TaskStatus.CANCELLED: "dim red",
        }.get(status, "dim")

    def _get_status_icon(self, status: TaskStatus) -> str:
        """Get icon for a status."""
        return {
            TaskStatus.PENDING: "○",
            TaskStatus.STREAMING: "●",
            TaskStatus.EXECUTING: "◐",
            TaskStatus.COMPLETED: "✓",
            TaskStatus.ERROR: "✗",
            TaskStatus.CANCELLED: "⊘",
        }.get(status, "?")

    def _get_type_label(self, task_type: TaskType) -> str:
        """Get human-readable label for task type."""
        return {
            TaskType.CHAT: "Chat",
            TaskType.COMPRESSION: "Compress",
            TaskType.MERGE_SUMMARY: "Merge",
            TaskType.LINK_SUMMARY: "Link",
            TaskType.ARCHIVE_SUMMARY: "Archive",
            TaskType.TITLE: "Title",
        }.get(task_type, str(task_type.value))

    def _show_task_detail(self, task: Task) -> None:
        """Show detailed properties for selected task."""
        detail = self.query_one("#task-detail", Static)

        lines = []

        # Header with status
        status_icon = self._get_status_icon(task.status)
        status_style = self._get_status_style(task.status)
        header = Text()
        header.append(f"{status_icon} ", style=status_style)
        header.append(self._get_type_label(task.task_type), style="bold")
        header.append(f" - {task.status.value}", style=status_style)
        lines.append(header)
        lines.append(Text(""))

        # Properties section
        lines.append(Text("Properties", style="bold underline"))

        # Task ID
        lines.append(Text(f"  Task ID: ", style="dim").append(task.task_id[:16] + ("..." if len(task.task_id) > 16 else "")))

        # Session
        if task.session_id:
            lines.append(Text(f"  Session: ", style="dim").append(task.session_id[:16] + ("..." if len(task.session_id) > 16 else "")))

        # Backend
        if task.backend_name:
            lines.append(Text(f"  Backend: ", style="dim").append(task.backend_name, style="cyan"))

        # Model
        if task.model:
            lines.append(Text(f"  Model: ", style="dim").append(task.model, style="magenta"))

        lines.append(Text(""))

        # Timing section
        lines.append(Text("Timing", style="bold underline"))
        started = task.started_at.strftime("%H:%M:%S.%f")[:-3]
        lines.append(Text(f"  Started: ", style="dim").append(started))
        lines.append(Text(f"  Duration: ", style="dim").append(f"{task.duration_seconds:.2f}s", style="green" if task.is_active else ""))

        if task.finished_at:
            finished = task.finished_at.strftime("%H:%M:%S.%f")[:-3]
            lines.append(Text(f"  Finished: ", style="dim").append(finished))

        lines.append(Text(""))

        # Tokens section
        lines.append(Text("Tokens", style="bold underline"))

        # Get output token count (prefer actual, fall back to estimate)
        output_count = task.output_tokens if task.output_tokens > 0 else task.tokens_streamed
        is_estimated = task.output_tokens == 0 and task.tokens_streamed > 0

        # Context window usage (input tokens = context sent to API)
        if task.context_window > 0 and task.input_tokens > 0:
            usage_pct = (task.input_tokens / task.context_window * 100)
            usage_style = "red" if usage_pct > 80 else ("yellow" if usage_pct > 50 else "green")
            context_line = Text(f"  Context Window: ", style="dim")
            context_line.append(f"{task.input_tokens:,}", style=usage_style)
            context_line.append(f" / {task.context_window:,}", style="dim")
            context_line.append(f" ({usage_pct:.1f}%)", style=usage_style)
            lines.append(context_line)

        # Output tokens (response tokens)
        if output_count > 0:
            output_style = "green"
            output_text = f"~{output_count:,}" if is_estimated else f"{output_count:,}"
            lines.append(Text(f"  Output: ", style="dim").append(output_text, style=output_style))

        # Token rate and sparkline (inference speed)
        token_rate = task.current_token_rate
        if token_rate > 0:
            rate_text = Text(f"  Speed: ", style="dim").append(f"{token_rate:.1f} tok/s", style="cyan")
            lines.append(rate_text)

            # Render sparkline of recent rates
            rates = task.get_token_rates()
            if rates:
                sparkline = render_sparkline(rates, width=30)
                sparkline_text = Text(f"  ", style="dim").append(sparkline, style="cyan")
                lines.append(sparkline_text)

        lines.append(Text(""))

        # Tools section
        lines.append(Text("Tools", style="bold underline"))
        tools_style = "yellow" if task.tool_count > 0 else "dim"
        lines.append(Text(f"  Executed: ", style="dim").append(str(task.tool_count), style=tools_style))

        if task.tool_name:
            lines.append(Text(f"  Current: ", style="dim").append(task.tool_name, style="yellow bold"))

        # Error section
        if task.error:
            lines.append(Text(""))
            lines.append(Text("Error", style="bold underline red"))
            # Wrap error text
            error_text = task.error
            lines.append(Text(f"  {error_text}", style="red"))

        # Prompt section
        if task.prompt:
            lines.append(Text(""))
            lines.append(Text("Prompt", style="bold underline"))
            # Show truncated prompt
            prompt_preview = task.prompt[:300]
            if len(task.prompt) > 300:
                prompt_preview += "..."
            lines.append(Text(f"  {prompt_preview}", style="italic dim"))

        # Combine all lines
        output = Text()
        for i, line in enumerate(lines):
            if i > 0:
                output.append("\n")
            output.append_text(line)

        detail.update(output)

    def refresh_tasks(self) -> None:
        """Manually refresh the task tree."""
        self._refresh_task_tree()
