from textual.widgets import Static
from textual.reactive import reactive
from textual.message import Message
from textual.timer import Timer


class StatusBar(Static):
    """Status bar showing model, token usage, and cost."""

    class FollowClicked(Message):
        """Posted when the Follow indicator is clicked."""
        pass

    model: reactive[str] = reactive("")
    input_tokens: reactive[int] = reactive(0)
    output_tokens: reactive[int] = reactive(0)
    context_window: reactive[int] = reactive(200000)
    cost: reactive[float] = reactive(0.0)
    streaming: reactive[bool] = reactive(False)
    status: reactive[str] = reactive("")
    _status_animated: bool = True
    error: reactive[str] = reactive("")
    working_directory: reactive[str] = reactive("")
    following: reactive[bool] = reactive(True)  # Whether chat is following new content
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
        total_tokens = self.input_tokens + self.output_tokens
        if self.context_window > 0:
            percent = (total_tokens / self.context_window) * 100
        else:
            percent = 0

        model_display = self.model.split("-")[0] if self.model else "claude"

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

        # Show working directory (always displayed)
        wd_path = self.working_directory or "."
        parts = wd_path.split("/")
        if len(parts) > 2:
            wd_display = f" [dim]@.../{'/'.join(parts[-2:])}[/]"
        else:
            wd_display = f" [dim]@{wd_path}[/]"

        # Show follow indicator when not following (clickable to jump to bottom)
        follow_indicator = "" if self.following else " [bold yellow]↓ Follow[/]"

        return (
            f"[{model_display}] "
            f"{total_tokens:,} / {self.context_window:,} tokens ({percent:.1f}%) | "
            f"${self.cost:.4f}"
            f"{wd_display}"
            f"{follow_indicator}"
            f"{status_indicator}"
        )

    def update_stats(
        self,
        model: str = None,
        input_tokens: int = None,
        output_tokens: int = None,
        context_window: int = None,
        cost: float = None,
    ):
        if model is not None:
            self.model = model
        if input_tokens is not None:
            self.input_tokens = input_tokens
        if output_tokens is not None:
            self.output_tokens = output_tokens
        if context_window is not None:
            self.context_window = context_window
        if cost is not None:
            self.cost = cost

    def set_streaming(self, streaming: bool):
        self.streaming = streaming
        if streaming:
            self._start_spinner()
        else:
            self._stop_spinner()

    def set_status(self, status: str, animate: bool = True):
        self.status = status
        self._status_animated = animate
        self.error = ""  # Clear error when setting status
        if status and animate:
            self._start_spinner()
        else:
            self._stop_spinner()

    def set_error(self, error: str):
        self.error = error
        self.status = ""  # Clear status when setting error
        self._stop_spinner()  # No animation for errors

    def _start_spinner(self) -> None:
        """Start the spinner animation."""
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.1, self._advance_spinner)

    def _stop_spinner(self) -> None:
        """Stop the spinner animation."""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
            self._spinner_frame = 0

    def _advance_spinner(self) -> None:
        """Advance the spinner to the next frame."""
        self._spinner_frame = (self._spinner_frame + 1) % len(self._spinner_chars)

    def update_working_directory(self, path: str) -> None:
        """Update the displayed working directory."""
        self.working_directory = path

    def on_click(self) -> None:
        """Handle click - if not following, post message to follow."""
        if not self.following:
            self.post_message(self.FollowClicked())
