from textual.widgets import Static
from textual.reactive import reactive
from textual.message import Message
from textual.timer import Timer
from textual.events import Click


class StatusBar(Static):
    """Status bar showing model, context usage, and cost."""

    class FollowClicked(Message):
        """Posted when the Follow indicator is clicked."""
        pass

    class PriorityClicked(Message):
        """Posted when the priority divergence indicator is clicked."""
        def __init__(self, todo_id: str) -> None:
            self.todo_id = todo_id
            super().__init__()

    model: reactive[str] = reactive("")
    backend: reactive[str] = reactive("")  # Backend name (e.g., "openrouter", "claude")
    overhead_tokens: reactive[int] = reactive(0)  # System overhead (Claude prompt, etc.)
    context_tokens: reactive[int] = reactive(0)  # Actual conversation context tokens
    context_window: reactive[int] = reactive(200000)
    cost: reactive[float] = reactive(0.0)
    streaming: reactive[bool] = reactive(False)
    streaming_count: reactive[int] = reactive(0)  # Total sessions streaming (including background)
    status: reactive[str] = reactive("")
    _status_animated: bool = True
    error: reactive[str] = reactive("")
    working_directory: reactive[str] = reactive("")
    following: reactive[bool] = reactive(True)  # Whether chat is following new content
    priority_divergence: reactive[str] = reactive("")  # Priority divergence warning
    _priority_todo_id: str = ""  # Todo ID for priority divergence click navigation
    _spinner_frame: reactive[int] = reactive(0)
    _spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    _spinner_timer: Timer | None = None

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def render(self) -> str:
        total_tokens = self.overhead_tokens + self.context_tokens
        if self.context_window > 0:
            percent = (total_tokens / self.context_window) * 100
        else:
            percent = 0

        # Extract meaningful model name
        # Claude models: "claude-opus-4-5-20251101" -> "opus-4.5"
        # Other models: "Qwen3-Coder-30B" -> "Qwen3"
        if self.model:
            if self.model.startswith("claude-"):
                # Extract the model variant (opus, sonnet, haiku) and version
                parts = self.model.split("-")
                if len(parts) >= 3:
                    variant = parts[1]  # e.g., "opus"
                    # Try to get version like "4.5" from "4-5"
                    if len(parts) >= 4 and parts[2].isdigit() and parts[3].isdigit():
                        model_display = f"{variant}-{parts[2]}.{parts[3]}"
                    else:
                        model_display = variant
                else:
                    model_display = self.model.split("-")[0]
            else:
                model_display = self.model.split("-")[0]
        else:
            model_display = "?"
        backend_display = f"{self.backend}:" if self.backend else ""

        # Show error, status, or streaming indicator
        if self.error:
            status_indicator = f" [bold orange1]{self.error}[/]"
        elif self.status:
            if self._status_animated:
                spinner = self._spinner_chars[self._spinner_frame]
                status_indicator = f" [bold cyan]{spinner} {self.status}[/]"
            else:
                status_indicator = f" [bold cyan]{self.status}[/]"
        elif self.streaming:
            spinner = self._spinner_chars[self._spinner_frame]
            status_indicator = f" [bold green]{spinner} streaming[/]"
        else:
            status_indicator = ""

        # Show background streaming count (excluding focused session)
        background_count = self.streaming_count - (1 if self.streaming else 0)
        if background_count > 0:
            spinner = self._spinner_chars[self._spinner_frame]
            bg_indicator = f" [yellow]{spinner} {background_count} bg[/]"
        else:
            bg_indicator = ""

        # Show working directory (always displayed)
        wd_path = self.working_directory or "."
        parts = wd_path.split("/")
        if len(parts) > 2:
            wd_display = f" [dim]@.../{'/'.join(parts[-2:])}[/]"
        else:
            wd_display = f" [dim]@{wd_path}[/]"

        # Show follow indicator when not following (clickable to jump to bottom)
        follow_indicator = "" if self.following else " [bold yellow]↓ Follow[/]"

        # Show priority divergence warning if working on non-highest-priority todo
        priority_indicator = f" [bold orange1]⚠ {self.priority_divergence}[/]" if self.priority_divergence else ""

        # Format tokens with 'k' suffix for readability
        def fmt_k(n: int) -> str:
            if n >= 1000:
                return f"{n / 1000:.1f}k"
            return str(n)

        overhead_str = fmt_k(self.overhead_tokens)
        context_str = fmt_k(self.context_tokens)
        window_str = fmt_k(self.context_window)

        return (
            f"[{backend_display}{model_display}] "
            f"ctx: {overhead_str} + {context_str} / {window_str} ({percent:.1f}%) | "
            f"${self.cost:.4f}"
            f"{wd_display}"
            f"{priority_indicator}"
            f"{follow_indicator}"
            f"{bg_indicator}"
            f"{status_indicator}"
        )

    def update_stats(
        self,
        model: str = None,
        backend: str = None,
        overhead_tokens: int = None,
        context_tokens: int = None,
        context_window: int = None,
        cost: float = None,
    ):
        if model is not None:
            self.model = model
        if backend is not None:
            self.backend = backend
        if overhead_tokens is not None:
            self.overhead_tokens = overhead_tokens
        if context_tokens is not None:
            self.context_tokens = context_tokens
        if context_window is not None:
            self.context_window = context_window
        if cost is not None:
            self.cost = cost

    def set_streaming(self, streaming: bool):
        self.streaming = streaming
        if streaming:
            self._start_spinner()
        else:
            self._maybe_stop_spinner()

    def set_streaming_count(self, count: int):
        """Set total number of streaming sessions (foreground + background)."""
        self.streaming_count = count
        # Start spinner if any sessions streaming
        if count > 0:
            self._start_spinner()
        else:
            self._maybe_stop_spinner()

    def set_status(self, status: str, animate: bool = True):
        self.status = status
        self._status_animated = animate
        self.error = ""  # Clear error when setting status
        if status and animate:
            self._start_spinner()
        else:
            self._maybe_stop_spinner()

    def set_error(self, error: str):
        self.error = error
        self.status = ""  # Clear status when setting error
        self._maybe_stop_spinner()  # Only stop if nothing else needs animation

    def _start_spinner(self) -> None:
        """Start the spinner animation."""
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.1, self._advance_spinner)

    def _stop_spinner(self) -> None:
        """Stop the spinner animation unconditionally."""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
            self._spinner_frame = 0

    def _maybe_stop_spinner(self) -> None:
        """Stop the spinner only if nothing needs animation.

        The spinner should keep running if any of:
        - Foreground session is streaming
        - Background sessions are streaming (streaming_count > 0)
        - An animated status message is shown
        """
        needs_animation = (
            self.streaming or
            self.streaming_count > 0 or
            (self.status and self._status_animated)
        )
        if not needs_animation:
            self._stop_spinner()

    def _advance_spinner(self) -> None:
        """Advance the spinner to the next frame."""
        self._spinner_frame = (self._spinner_frame + 1) % len(self._spinner_chars)

    def update_working_directory(self, path: str) -> None:
        """Update the displayed working directory."""
        self.working_directory = path

    def set_priority_divergence(self, message: str = "", todo_id: str = "") -> None:
        """Set or clear the priority divergence warning.

        Args:
            message: Warning message (e.g., "Higher priority: fix-auth-bug")
                    Pass empty string to clear.
            todo_id: The ID of the higher-priority todo to navigate to when clicked.
        """
        self.priority_divergence = message
        self._priority_todo_id = todo_id

    def on_click(self, event: Click) -> None:
        """Handle click on status bar indicators.

        Priority (left to right):
        1. If priority divergence is shown and clicked, navigate to todo
        2. If Follow is shown and clicked, scroll to bottom

        We use click position to determine which indicator was clicked.
        """
        # Get the rendered text to estimate indicator positions
        # The priority indicator appears before the follow indicator
        rendered = self.render()

        # Find approximate positions of clickable indicators
        # Priority indicator: "⚠ Higher priority: ..."
        # Follow indicator: "↓ Follow"
        has_priority = self.priority_divergence and self._priority_todo_id
        has_follow = not self.following

        if has_priority:
            # If there's a priority warning, clicking anywhere on the status bar
            # should navigate to the todo (it's the primary call to action)
            self.post_message(self.PriorityClicked(self._priority_todo_id))
        elif has_follow:
            self.post_message(self.FollowClicked())
