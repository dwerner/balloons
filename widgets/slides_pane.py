"""Slides pane showing presentation slides from the session."""

from textual.widgets import Static, Button, ListView, ListItem
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text
from rich.markdown import Markdown
from rich.panel import Panel
from rich.console import Group

from models import SlideBlock
from session import Session


class SlideCard(ListItem):
    """A card displaying a slide preview in the slides list."""

    DEFAULT_CSS = """
    SlideCard {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: $surface;
        border: solid $primary-darken-2;
    }

    SlideCard:hover {
        background: $surface-lighten-1;
        border: solid $primary;
    }

    SlideCard.--highlight {
        background: $primary-darken-3;
        border: solid $primary;
    }

    SlideCard > #slide-header {
        width: 100%;
        height: auto;
    }

    SlideCard > #slide-preview {
        width: 100%;
        height: auto;
        max-height: 6;
        overflow: hidden;
    }

    SlideCard Static {
        width: 100%;
    }
    """

    def __init__(
        self,
        slide_index: int,
        turn_index: int,
        slide: SlideBlock,
        **kwargs,
    ):
        """Initialize a slide card.

        Args:
            slide_index: 0-based index in the slide deck (1, 2, 3...)
            turn_index: Index of the turn in the session
            slide: The SlideBlock data
        """
        super().__init__(**kwargs)
        self.slide_index = slide_index
        self.turn_index = turn_index
        self.slide = slide

    def compose(self):
        # Header with slide number and title
        header = Text()
        header.append(f"#{self.slide_index + 1}", style="bold cyan")
        header.append("  ", style="")
        title = self.slide.title or "(Untitled)"
        # Truncate title if too long
        if len(title) > 40:
            title = title[:37] + "..."
        header.append(title, style="bold")
        yield Static(header, id="slide-header")

        # Preview of content (truncated)
        if self.slide.content:
            # Show first few lines as plain text preview
            preview_lines = self.slide.content.split("\n")[:3]
            preview_text = "\n".join(preview_lines)
            if len(self.slide.content.split("\n")) > 3:
                preview_text += "\n..."
            yield Static(preview_text, id="slide-preview", classes="dim")


class SlidesPane(Vertical):
    """Right panel showing presentation slides in the current session.

    Features:
    - Lists all slides from session.turns where role='slide'
    - Each slide shown as a card with title and content preview
    - Click to select/expand
    - Present button to enter presentation mode
    """

    DEFAULT_CSS = """
    SlidesPane {
        width: 100%;
        height: 100%;
        background: $background;
    }

    SlidesPane > #slides-header {
        dock: top;
        height: auto;
        padding: 1;
        background: $surface;
        border-bottom: solid $primary;
    }

    SlidesPane > #slides-header > #header-title {
        width: 1fr;
    }

    SlidesPane > #slides-header > Button {
        margin-left: 1;
    }

    SlidesPane > #slides-list {
        height: 1fr;
        padding: 1;
    }

    SlidesPane > #no-slides {
        height: 1fr;
        content-align: center middle;
        text-style: italic;
        color: $text-muted;
    }

    SlidesPane > #slide-detail {
        height: 1fr;
        padding: 1;
        border-top: solid $primary;
        display: none;
    }

    SlidesPane > #slide-detail.visible {
        display: block;
    }
    """

    # Currently selected slide turn index
    selected_turn_index = reactive(-1)

    class SlideSelected(Message):
        """Emitted when a slide is selected."""
        def __init__(self, turn_index: int, slide: SlideBlock):
            super().__init__()
            self.turn_index = turn_index
            self.slide = slide

    class PresentRequested(Message):
        """Emitted when user clicks the Present button."""
        pass

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._session: Session | None = None

    def compose(self):
        with Horizontal(id="slides-header"):
            yield Static("📊 Slides", id="header-title")
            yield Button("▶ Present", id="present-btn", variant="primary")

        yield Static("No slides yet.\n\nUse :new-slide to create one,\nor ask Claude to create slides.", id="no-slides")
        yield ListView(id="slides-list")
        yield VerticalScroll(id="slide-detail")

    def on_mount(self) -> None:
        """Initial setup."""
        self._update_slides_list()

    def set_session(self, session: Session | None) -> None:
        """Set the session to display slides from."""
        self._session = session
        self._update_slides_list()

    def refresh_slides(self) -> None:
        """Refresh the slides list from the current session."""
        self._update_slides_list()

    def _update_slides_list(self) -> None:
        """Rebuild the slides list from the session."""
        slides_list = self.query_one("#slides-list", ListView)
        no_slides = self.query_one("#no-slides", Static)
        present_btn = self.query_one("#present-btn", Button)
        header_title = self.query_one("#header-title", Static)

        # Clear existing
        slides_list.clear()

        if not self._session:
            no_slides.display = True
            slides_list.display = False
            present_btn.disabled = True
            header_title.update("📊 Slides")
            return

        slides = self._session.get_all_slides()

        if not slides:
            no_slides.display = True
            slides_list.display = False
            present_btn.disabled = True
            header_title.update("📊 Slides")
            return

        # Hide "no slides" message, show list
        no_slides.display = False
        slides_list.display = True
        present_btn.disabled = False
        header_title.update(f"📊 Slides ({len(slides)})")

        # Add slide cards
        for slide_idx, (turn_idx, slide_block) in enumerate(slides):
            card = SlideCard(
                slide_index=slide_idx,
                turn_index=turn_idx,
                slide=slide_block,
                id=f"slide-card-{turn_idx}",
            )
            slides_list.append(card)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle slide selection."""
        if isinstance(event.item, SlideCard):
            self.selected_turn_index = event.item.turn_index
            self.post_message(self.SlideSelected(
                turn_index=event.item.turn_index,
                slide=event.item.slide,
            ))
            self._show_slide_detail(event.item.slide)

    def _show_slide_detail(self, slide: SlideBlock) -> None:
        """Show detailed view of selected slide."""
        detail = self.query_one("#slide-detail", VerticalScroll)
        detail.remove_children()

        # Title
        if slide.title:
            detail.mount(Static(Text(slide.title, style="bold underline cyan")))
            detail.mount(Static(""))

        # Content as markdown
        if slide.content:
            try:
                detail.mount(Static(Markdown(slide.content)))
            except Exception:
                # Fallback to plain text
                detail.mount(Static(slide.content))

        # Notes
        if slide.notes:
            detail.mount(Static(""))
            detail.mount(Static(Text("Speaker Notes:", style="bold dim")))
            detail.mount(Static(Text(slide.notes, style="italic dim")))

        detail.add_class("visible")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "present-btn":
            self.post_message(self.PresentRequested())

    def watch_selected_turn_index(self, value: int) -> None:
        """Update UI when selection changes."""
        if value < 0:
            detail = self.query_one("#slide-detail", VerticalScroll)
            detail.remove_class("visible")
