"""Fullscreen presentation mode for slides."""

import asyncio
from textual.screen import Screen
from textual.widgets import Static
from textual.containers import Vertical, Horizontal, Center
from textual.binding import Binding
from rich.markdown import Markdown
from rich.text import Text
from rich.panel import Panel
from rich.console import Group

from models import SlideBlock
from core.tts import get_tts_runner, TTSConfig


class PresentationScreen(Screen[None]):
    """Fullscreen presentation mode for viewing slides.

    Features:
    - One slide at a time, centered and 1080p-optimized
    - Keyboard navigation: ← → j k Space Backspace
    - Exit: Esc or q
    - Progress indicator at bottom
    - Slide content rendered as markdown
    - Speaker notes hidden by default, toggle with 'n'
    """

    DEFAULT_CSS = """
    PresentationScreen {
        background: $background;
        layout: vertical;
    }

    #slide-container {
        width: 100%;
        height: 1fr;
        align: center middle;
    }

    #slide-content {
        width: 100%;
        height: 100%;
        padding: 2 4;
        background: $surface;
    }

    #slide-title {
        width: 100%;
        height: auto;
        text-align: center;
        text-style: bold;
        color: $text;
        padding: 1 2;
        border-bottom: solid $primary-darken-2;
        margin-bottom: 1;
    }

    #slide-body {
        width: 100%;
        height: 1fr;
        padding: 2 4;
    }

    #slide-notes {
        width: 100%;
        height: auto;
        max-height: 8;
        padding: 1 2;
        background: $surface-darken-1;
        border-top: dashed $primary-darken-2;
        display: none;
    }

    #slide-notes.visible {
        display: block;
    }

    #progress-bar {
        dock: bottom;
        width: 100%;
        height: 3;
        padding: 0 2;
        content-align: center middle;
        background: $surface-darken-1;
    }

    #progress-indicator {
        text-align: center;
    }

    #navigation-hint {
        text-align: center;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "exit", "Exit", show=True),
        Binding("q", "exit", "Exit"),
        Binding("left", "previous", "Previous", show=True),
        Binding("right", "next", "Next", show=True),
        Binding("j", "next", "Next"),
        Binding("k", "previous", "Previous"),
        Binding("space", "next", "Next"),
        Binding("backspace", "previous", "Previous"),
        Binding("n", "toggle_notes", "Toggle Notes", show=True),
        Binding("home", "first", "First"),
        Binding("end", "last", "Last"),
        Binding("r", "read_slide", "Read Aloud", show=True),
        Binding("a", "toggle_auto_read", "Auto-Read", show=True),
        Binding("s", "stop_speech", "Stop Speech"),
    ]

    def __init__(
        self,
        slides: list[tuple[int, SlideBlock]],
        start_index: int = 0,
        **kwargs,
    ):
        """Initialize presentation screen.

        Args:
            slides: List of (turn_index, SlideBlock) tuples
            start_index: Which slide to start on (0-based)
        """
        super().__init__(**kwargs)
        self._slides = slides
        self._current_index = max(0, min(start_index, len(slides) - 1))
        self._show_notes = False
        self._auto_read = False
        self._tts_runner = get_tts_runner()

    def compose(self):
        # Progress bar docks to bottom - must be yielded first for docking to work
        with Vertical(id="progress-bar"):
            yield Static("", id="progress-indicator")
            yield Static("← → navigate  |  r read  |  a auto  |  n notes  |  q exit", id="navigation-hint")
        # Slide container takes remaining space
        with Vertical(id="slide-container"):
            with Vertical(id="slide-content"):
                yield Static("", id="slide-title")
                yield Static("", id="slide-body")
                yield Static("", id="slide-notes")

    def on_mount(self) -> None:
        """Display the initial slide."""
        self._render_current_slide()

    def _render_current_slide(self) -> None:
        """Render the current slide."""
        if not self._slides:
            return

        _, slide = self._slides[self._current_index]

        # Update title
        title_widget = self.query_one("#slide-title", Static)
        if slide.title:
            title_widget.update(Text(slide.title, style="bold"))
        else:
            title_widget.update(Text("(Untitled)", style="dim italic"))

        # Update body
        body_widget = self.query_one("#slide-body", Static)
        if slide.content:
            try:
                body_widget.update(Markdown(slide.content))
            except Exception:
                # Fallback to plain text
                body_widget.update(slide.content)
        else:
            body_widget.update(Text("(No content)", style="dim italic"))

        # Update notes
        notes_widget = self.query_one("#slide-notes", Static)
        if slide.notes:
            notes_widget.update(
                Group(
                    Text("Speaker Notes:", style="bold dim"),
                    Text(slide.notes, style="italic"),
                )
            )
        else:
            notes_widget.update(Text("(No notes)", style="dim italic"))

        # Update progress indicator
        self._update_progress()

    def _update_progress(self) -> None:
        """Update the progress indicator."""
        progress_widget = self.query_one("#progress-indicator", Static)

        total = len(self._slides)
        current = self._current_index + 1

        # Create dot indicator: ● ○ ○ ○ ○
        dots = []
        for i in range(total):
            if i == self._current_index:
                dots.append("●")
            else:
                dots.append("○")

        # For many slides, show numeric instead
        if total > 10:
            progress_text = f"Slide {current} / {total}"
        else:
            progress_text = f"{' '.join(dots)}  ({current}/{total})"

        progress_widget.update(Text(progress_text, style="bold"))

    def action_exit(self) -> None:
        """Exit presentation mode."""
        self.dismiss(None)

    def action_next(self) -> None:
        """Go to next slide."""
        if self._current_index < len(self._slides) - 1:
            self._current_index += 1
            self._render_current_slide()

    def action_previous(self) -> None:
        """Go to previous slide."""
        if self._current_index > 0:
            self._current_index -= 1
            self._render_current_slide()

    def action_first(self) -> None:
        """Go to first slide."""
        self._current_index = 0
        self._render_current_slide()

    def action_last(self) -> None:
        """Go to last slide."""
        self._current_index = len(self._slides) - 1
        self._render_current_slide()

    def action_toggle_notes(self) -> None:
        """Toggle speaker notes visibility."""
        self._show_notes = not self._show_notes
        if self.is_mounted:
            notes_widget = self.query_one("#slide-notes", Static)
            if self._show_notes:
                notes_widget.add_class("visible")
            else:
                notes_widget.remove_class("visible")

    def _get_slide_text(self) -> str:
        """Get the text content of the current slide for TTS."""
        if not self._slides:
            return ""

        _, slide = self._slides[self._current_index]
        parts = []

        if slide.title:
            parts.append(slide.title)

        if slide.content:
            # Strip markdown formatting for cleaner speech
            # Remove headers, bullets, and code blocks
            content = slide.content
            # Remove markdown headers
            import re
            content = re.sub(r'^#+\s*', '', content, flags=re.MULTILINE)
            # Remove bullet points
            content = re.sub(r'^[\*\-]\s*', '', content, flags=re.MULTILINE)
            # Remove code block markers
            content = re.sub(r'```\w*\n?', '', content)
            # Remove inline code backticks
            content = re.sub(r'`([^`]+)`', r'\1', content)
            parts.append(content.strip())

        return ". ".join(parts)

    async def action_read_slide(self) -> None:
        """Read the current slide aloud using TTS."""
        text = self._get_slide_text()
        if text:
            await self._tts_runner.speak(text)

    async def action_toggle_auto_read(self) -> None:
        """Toggle auto-read mode (read each slide then advance)."""
        self._auto_read = not self._auto_read

        # Update the hint to show auto mode status
        hint_widget = self.query_one("#navigation-hint", Static)
        if self._auto_read:
            hint_widget.update("← → navigate  |  r read  |  [AUTO ON]  |  n notes  |  q exit")
            # Start reading current slide
            await self._auto_read_current()
        else:
            hint_widget.update("← → navigate  |  r read  |  a auto  |  n notes  |  q exit")
            # Stop any current speech
            await self._tts_runner.cancel()

    async def _auto_read_current(self) -> None:
        """Read current slide and advance when done (if auto-read is on)."""
        if not self._auto_read:
            return

        text = self._get_slide_text()
        if text:
            def on_complete():
                # Schedule next slide advance on the main thread
                if self._auto_read and self._current_index < len(self._slides) - 1:
                    self.call_later(self._advance_and_read)

            await self._tts_runner.speak(text, on_complete)

    def _advance_and_read(self) -> None:
        """Advance to next slide and read it (called from TTS completion callback)."""
        if self._current_index < len(self._slides) - 1:
            self._current_index += 1
            self._render_current_slide()
            # Schedule the async read
            asyncio.create_task(self._auto_read_current())

    async def action_stop_speech(self) -> None:
        """Stop any current speech."""
        self._auto_read = False
        await self._tts_runner.cancel()
        # Update hint
        hint_widget = self.query_one("#navigation-hint", Static)
        hint_widget.update("← → navigate  |  r read  |  a auto  |  n notes  |  q exit")
