import json
from math import ceil
from pathlib import Path
from typing import ClassVar

from textual.widgets import Static, LoadingIndicator
from textual.containers import VerticalScroll, Center
from textual.reactive import reactive
from textual.message import Message
from textual.events import Click, Key
from textual.scrollbar import ScrollBarRender, ScrollBar
from rich.markdown import Markdown
from rich.color import Color
from rich.console import RenderableType, Group
from rich.segment import Segment, Segments
from rich.text import Text
from rich.style import Style
from rich.syntax import Syntax
from rich.panel import Panel

from .with_widget import WithWidget
from .with_result_widget import WithResultWidget
from .fork_marker import ForkMarker
from .merge_marker import MergeMarker
from .merged_to_marker import MergedToMarker
from .link_marker import LinkMarker
from .archive_marker import ArchiveMarker
from .review_marker import ReviewMarker
from .fork_proposal_marker import ForkProposalMarker
from .merge_proposal_marker import MergeProposalMarker
from models import TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, LinkBlock, ForkBlock, MergeBlock, MergedToBlock, ArchiveBlock, Sentiment
from core.formatter import format_edit_as_diff, guess_language
from core.json_stream import StreamingJsonParser
from core.history_loader import (
    HistoryLoader,
    RenderMessage, RenderToolUse, RenderToolResult,
    RenderInterruption, RenderError, RenderLink, RenderArchive,
    RenderFork, RenderMerge, RenderMergedTo, RenderReview,
    RenderForkProposal, RenderMergeProposal
)
from .scroll_controller import ScrollController, WidgetRegion
from .widget_registry import WidgetRegistry
from core.stream_buffer import StreamBuffer
from session import Session

# Re-export for backwards compatibility (used by app.py imports)
_format_edit_as_diff = format_edit_as_diff
_guess_language = guess_language


class MarkedScrollBarRender(ScrollBarRender):
    """ScrollBar renderer that can display markers at specific positions.

    Markers are shown as colored segments in the scrollbar gutter,
    useful for indicating unviewed turns, search results, errors, etc.
    """

    # Marker positions as fractions (0.0 to 1.0) of total content
    markers: ClassVar[list[float]] = []
    # Color for the markers (bright blue for unviewed)
    marker_color: ClassVar[Color] = Color.parse("#5588ff")

    @classmethod
    def render_bar(
        cls,
        size: int = 25,
        virtual_size: float = 50,
        window_size: float = 20,
        position: float = 0,
        thickness: int = 1,
        vertical: bool = True,
        back_color: Color = Color.parse("#555555"),
        bar_color: Color = Color.parse("bright_magenta"),
    ) -> Segments:
        """Render the scrollbar with optional markers."""
        # First, get the standard scrollbar rendering
        segments_obj = super().render_bar(
            size=size,
            virtual_size=virtual_size,
            window_size=window_size,
            position=position,
            thickness=thickness,
            vertical=vertical,
            back_color=back_color,
            bar_color=bar_color,
        )

        # If no markers or not vertical, return as-is
        if not cls.markers or not vertical:
            return segments_obj

        # Convert Segments to a mutable list
        # Segments stores segments in the 'segments' attribute
        segments = list(segments_obj.segments)

        # Filter out newline segments for marker placement
        # In vertical mode, segments alternate: [content, newline, content, newline, ...]
        content_indices = []
        for i, seg in enumerate(segments):
            if seg.text and seg.text != "\n":
                content_indices.append(i)

        if not content_indices:
            return segments_obj

        # Add markers at the appropriate positions
        width_thickness = thickness
        # Use a full block character for visibility
        marker_char = "█" * width_thickness

        for marker_pos in cls.markers:
            # Convert marker position (0.0-1.0) to segment index
            segment_idx = int(marker_pos * len(content_indices))
            segment_idx = max(0, min(segment_idx, len(content_indices) - 1))

            actual_idx = content_indices[segment_idx]

            # Replace the segment with a marker
            # Keep the original meta for click handling
            original_seg = segments[actual_idx]
            original_meta = original_seg.style.meta if original_seg.style else {}
            marker_style = Style(
                color=cls.marker_color,
                bgcolor=cls.marker_color,
                meta=original_meta,
            )
            segments[actual_idx] = Segment(marker_char, marker_style)

        # Preserve new_lines=True for vertical scrollbars (matches parent behavior)
        return Segments(segments, new_lines=True)


class ToolUseWidget(Static):
    """A tool use display in the chat log."""

    DEFAULT_CSS = """
    ToolUseWidget {
        padding: 0 1;
        margin: 0 0 1 2;
        background: #1a1a1a;
        border-left: thick $warning;
    }

    ToolUseWidget.hidden {
        display: none;
    }

    /* Focus/highlight styles removed for debugging zero-height issue */

    ToolUseWidget.expandable {
        border-left: thick $warning;
    }

    ToolUseWidget.expanded {
        max-height: 10000;
    }

    ToolUseWidget.streaming {
        border-left: thick $accent;
    }

    /* Context mode visual indicators - use background color to avoid layout shifts */
    /* COPY is the default - no special styling needed */
    ToolUseWidget.context-copy {
    }

    ToolUseWidget.context-compress {
        background: #2d2a1a;  /* Yellow/orange tint for summarize */
    }

    ToolUseWidget.context-drop {
        opacity: 0.4;
    }
    """

    def __init__(
        self,
        tool_name: str,
        content: RenderableType = None,
        turn_id: int = 0,
        tool_use_id: str = "",
        full_content: RenderableType | None = None,
        streaming: bool = False,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self._content = content
        self._full_content = full_content  # Store full content if truncated
        self._expanded = False
        self.turn_id = turn_id
        self.tool_use_id = tool_use_id
        self._streaming = streaming
        self._partial_json = ""  # Accumulated JSON during streaming
        self._json_parser = StreamingJsonParser()  # Parser for streaming JSON
        if full_content is not None:
            self.add_class("expandable")
        if streaming:
            self.add_class("streaming")

    def render(self) -> RenderableType:
        if self._streaming:
            # Show tool name + parsed partial JSON
            text = Text()
            text.append(f"[{self.tool_name}] ", style="bold cyan")

            # Try to parse and format the partial JSON
            parsed = self._json_parser.get_partial()
            if parsed:
                self._render_parsed_input(text, parsed)
            else:
                # Fallback to raw JSON if parsing fails
                text.append(self._partial_json[:100], style="dim")
                if len(self._partial_json) > 100:
                    text.append("...", style="dim")

            text.append(" ▌", style="bold")
            return text

        content = self._full_content if self._expanded and self._full_content else self._content
        # Content can be Markdown, Text, or other Rich renderables
        if isinstance(content, str):
            return Markdown(content, code_theme="monokai")
        return content

    def _render_parsed_input(self, text: Text, parsed: dict | list) -> None:
        """Render parsed JSON input in a readable format."""
        if isinstance(parsed, dict):
            # Show key-value pairs in a compact format
            items = []
            for key, value in parsed.items():
                if isinstance(value, str):
                    # Truncate long strings
                    if len(value) > 40:
                        display_val = value[:37] + "..."
                    else:
                        display_val = value
                    items.append(f'{key}="{display_val}"')
                elif isinstance(value, (dict, list)):
                    items.append(f"{key}={{...}}")
                else:
                    items.append(f"{key}={value}")
            text.append(", ".join(items), style="dim")
        elif isinstance(parsed, list):
            text.append(f"[{len(parsed)} items]", style="dim")
        else:
            text.append(str(parsed)[:100], style="dim")

    def append_input(self, partial_json: str) -> None:
        """Append partial JSON to streaming tool use."""
        self._partial_json += partial_json
        self._json_parser.feed(partial_json)
        self.refresh()

    def finish_streaming(self, content: RenderableType, full_content: RenderableType | None = None) -> None:
        """Complete streaming with final formatted content."""
        self._streaming = False
        self._content = content
        self._full_content = full_content
        self.remove_class("streaming")
        if full_content is not None:
            self.add_class("expandable")
        self.refresh()

    def toggle_expand(self) -> None:
        """Toggle between expanded and collapsed state."""
        if self._full_content is not None:
            self._expanded = not self._expanded
            if self._expanded:
                self.add_class("expanded")
            else:
                self.remove_class("expanded")
            self.refresh()

    def on_click(self) -> None:
        """Handle click - expand if collapsed and expandable, otherwise highlight tree node."""
        if self._full_content is not None and not self._expanded:
            # Collapsed expandable widget: expand it
            self.toggle_expand()
        elif self.turn_id > 0:
            # Expanded or non-expandable: highlight in tree
            for ancestor in self.ancestors_with_self:
                if isinstance(ancestor, ChatLogView):
                    ancestor.post_message(ChatLogView.TurnClicked(self.turn_id))
                    break

    @property
    def is_expandable(self) -> bool:
        return self._full_content is not None

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    @property
    def is_streaming(self) -> bool:
        return self._streaming


class ToolResultWidget(Static):
    """A tool result display in the chat log."""

    DEFAULT_CSS = """
    ToolResultWidget {
        padding: 0 1;
        margin: 0 0 1 2;
        background: #1a1a1a;
        border-left: thick #d4d422;
        max-height: 15;
        overflow-y: auto;
        scrollbar-gutter: stable;
    }

    ToolResultWidget.hidden {
        display: none;
    }

    /* Focus/highlight styles removed for debugging zero-height issue */

    ToolResultWidget.expandable {
        border-left: thick #d4d422;
    }

    /* Context mode visual indicators - use background color to avoid layout shifts */
    /* COPY is the default - no special styling needed */
    ToolResultWidget.context-copy {
    }

    ToolResultWidget.context-compress {
        background: #2d2a1a;  /* Yellow/orange tint for summarize */
    }

    ToolResultWidget.context-drop {
        opacity: 0.4;
    }

    ToolResultWidget.expanded {
        max-height: 10000;
    }
    """

    def __init__(
        self,
        content: RenderableType,
        turn_id: int = 0,
        tool_use_id: str = "",
        full_content: RenderableType | None = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._content = content
        self._full_content = full_content  # Store full content if truncated
        self._expanded = False
        self.turn_id = turn_id
        self.tool_use_id = tool_use_id
        if full_content is not None:
            self.add_class("expandable")

    def render(self) -> RenderableType:
        content = self._full_content if self._expanded and self._full_content else self._content
        # Content can be Markdown, Text, or other Rich renderables
        if isinstance(content, str):
            return Markdown(content, code_theme="monokai")
        return content

    def toggle_expand(self) -> None:
        """Toggle between expanded and collapsed state."""
        if self._full_content is not None:
            self._expanded = not self._expanded
            if self._expanded:
                self.add_class("expanded")
            else:
                self.remove_class("expanded")
            self.refresh()

    def on_click(self) -> None:
        """Handle click - expand if collapsed and expandable, otherwise highlight tree node."""
        if self._full_content is not None and not self._expanded:
            # Collapsed expandable widget: expand it
            self.toggle_expand()
        elif self.turn_id > 0:
            # Expanded or non-expandable: highlight in tree
            for ancestor in self.ancestors_with_self:
                if isinstance(ancestor, ChatLogView):
                    ancestor.post_message(ChatLogView.TurnClicked(self.turn_id))
                    break

    @property
    def is_expandable(self) -> bool:
        return self._full_content is not None

    @property
    def is_expanded(self) -> bool:
        return self._expanded


class InterruptionMarkerWidget(Static):
    """A marker showing that the response was interrupted."""

    DEFAULT_CSS = """
    InterruptionMarkerWidget {
        padding: 0 1;
        margin: 0 0 1 2;
        background: #2a1a1a;
        border-left: thick $error;
        color: $error;
        text-style: italic;
    }
    """

    def __init__(self, reason: str = "user_cancelled", turn_id: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.reason = reason
        self.turn_id = turn_id

    def render(self) -> RenderableType:
        if self.reason == "user_cancelled":
            return Text("[Response interrupted by user]", style="italic dim")
        elif self.reason == "timeout":
            return Text("[Response timed out]", style="italic dim")
        else:
            return Text(f"[Response interrupted: {self.reason}]", style="italic dim")


class ErrorMarkerWidget(Static):
    """A marker showing that the response ended with an error (truncated, etc.)."""

    DEFAULT_CSS = """
    ErrorMarkerWidget {
        padding: 0 1;
        margin: 0 0 1 2;
        background: #2a1a1a;
        border-left: thick $warning;
        color: $warning;
        text-style: italic;
    }
    """

    def __init__(
        self,
        reason: str = "stream_error",
        partial_tool_name: str = "",
        details: str = "",
        dump_file: str = "",
        turn_id: int = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.reason = reason
        self.partial_tool_name = partial_tool_name
        self.details = details
        self.dump_file = dump_file
        self.turn_id = turn_id

    def render(self) -> RenderableType:
        if self.reason == "truncated" and self.partial_tool_name:
            msg = f"[Response truncated during {self.partial_tool_name} tool call]"
        elif self.reason == "truncated":
            msg = "[Response truncated]"
        elif self.reason == "json_decode_error":
            msg = "[Response ended with parse error]"
        else:
            msg = f"[Response error: {self.reason}]"

        if self.details:
            msg += f"\n{self.details[:200]}"  # Truncate long details

        if self.dump_file:
            msg += f"\nDump: {self.dump_file}"

        return Text(msg, style="italic dim")


class InfoWidget(Static):
    """An informational message in the chat log (for command output like :goals, :todos).

    Unlike MessageWidget, this is not a conversation turn - it's ephemeral info
    that doesn't get saved to the session. Uses Rich markup for formatting.
    """

    DEFAULT_CSS = """
    InfoWidget {
        padding: 1 2;
        margin: 0 0 1 2;
        background: #1a2a1a;
        border-left: thick #22d422;
        color: $text;
    }

    InfoWidget.hidden {
        display: none;
    }
    """

    def __init__(
        self,
        content: str,
        title: str = "",
        turn_id: int = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._content = content
        self._title = title
        self.turn_id = turn_id

    def render(self) -> RenderableType:
        from rich.console import Group
        from rich.text import Text
        from rich.markdown import Markdown

        parts = []
        if self._title:
            parts.append(Text(f"📋 {self._title}", style="bold cyan"))
            parts.append(Text(""))

        # Parse Rich markup
        parts.append(Text.from_markup(self._content))

        return Group(*parts)


class MessageWidget(Static):
    """A single message in the chat log."""

    # Sentiment emoji mapping
    SENTIMENT_EMOJI = {
        Sentiment.EXCELLENT: "\u2764\ufe0f",    # ❤️
        Sentiment.GOOD: "\U0001F44D",          # 👍
        Sentiment.REVIEW: "\U0001F50D",        # 🔍
        Sentiment.POOR: "\U0001F44E",          # 👎
        Sentiment.TERRIBLE: "\u2620\ufe0f",    # ☠️
    }
    SENTIMENT_ORDER = [
        Sentiment.EXCELLENT,
        Sentiment.GOOD,
        Sentiment.REVIEW,
        Sentiment.POOR,
        Sentiment.TERRIBLE,
    ]

    DEFAULT_CSS = """
    MessageWidget {
        padding: 0 1;
        margin: 0 0 1 0;
    }

    MessageWidget.user {
        background: #1a1a3a;
        color: #e0d8b0;  /* Subtle light yellow for user messages */
        border-left: thick $primary;
        margin: 0 0 1 2;
        padding: 1 2 0 2;
    }

    MessageWidget.assistant {
        background: #2a1a1a;
        color: $text;
        border-left: thick $error;
        margin: 0 0 1 2;
        padding: 1 2 0 2;
    }

    /* Focus/highlight styles removed for debugging zero-height issue */

    MessageWidget.streaming {
        border-left: thick $accent;
    }

    MessageWidget.hidden {
        display: none;
    }

    /* Context mode visual indicators - use background color to avoid layout shifts */
    /* COPY is the default - no special styling needed */
    MessageWidget.context-copy {
    }

    MessageWidget.context-compress {
        background: #2d2a1a;  /* Yellow/orange tint for summarize */
    }

    MessageWidget.context-drop {
        opacity: 0.4;
    }

    /* Hover feedback - background change only, no border changes */
    MessageWidget:hover {
        background: #252525;
    }

    MessageWidget.user:hover {
        background: #222232;
    }

    MessageWidget.assistant:hover {
        background: #322222;
    }

    /* Sentiment display */
    MessageWidget.has-sentiment {
        /* Subtle indicator that sentiment is set */
    }
    """

    class SentimentChanged(Message):
        """Posted when the user changes the sentiment rating."""

        def __init__(self, turn_id: int, sentiment: Sentiment | None) -> None:
            super().__init__()
            self.turn_id = turn_id
            self.sentiment = sentiment

    def __init__(
        self,
        role: str,
        content: str = "",
        streaming: bool = False,
        turn_id: int = 0,
        block_idx: int = -1,
        sentiment: Sentiment | None = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.role = role
        self._content = content
        self._streaming = streaming
        self.turn_id = turn_id
        self.block_idx = block_idx  # Index within content_blocks, -1 if not set
        self._sentiment = sentiment
        self.add_class(role)
        if sentiment:
            self.add_class("has-sentiment")

    def _render_sentiment_bar(self, justify: str = "left") -> Text:
        """Render the sentiment buttons as a Text.

        Args:
            justify: Text justification ("left" or "right")
        """
        text = Text(justify=justify)
        for i, sentiment in enumerate(self.SENTIMENT_ORDER):
            emoji = self.SENTIMENT_EMOJI[sentiment]
            is_active = self._sentiment == sentiment
            # Tighter spacing: just emoji with minimal padding
            if is_active:
                # Subtle highlight: muted background, not too bright
                text.append(emoji, style="bold on #444444")
            else:
                text.append(emoji, style="dim")
            # Add small space between emojis (except after last)
            if i < len(self.SENTIMENT_ORDER) - 1:
                text.append(" ")
        return text

    def render(self) -> RenderableType:
        if self._streaming:
            # Plain text during streaming for performance
            return Text(f"{self._content}▌")
        elif self._content:
            # For assistant messages, include sentiment bar on the right
            if self.role == "assistant":
                sentiment_bar = self._render_sentiment_bar(justify="right")
                md = Markdown(self._content, code_theme="monokai")
                return Group(sentiment_bar, md)
            else:
                # Render markdown with syntax highlighting
                return Markdown(self._content, code_theme="monokai")
        else:
            if self.role == "assistant":
                return self._render_sentiment_bar(justify="right")
            return Text("")

    def append_text(self, text: str, refresh: bool = True) -> None:
        """Append text to the message content.

        Args:
            text: Text to append
            refresh: Whether to refresh immediately (set False for batched updates)
        """
        self._content += text
        if refresh:
            self.refresh()

    def finish_streaming(self) -> None:
        """Mark streaming as complete and re-render with markdown."""
        self._streaming = False
        # layout=True forces parent to recalculate this widget's size after
        # switching from plain text to Markdown (which is often much taller)
        self.refresh(layout=True)

    def set_content(self, content: str) -> None:
        """Set the full message content."""
        self._content = content
        self.refresh()

    def on_click(self, event: Click) -> None:
        """Handle click - check if sentiment bar was clicked, otherwise highlight tree node."""
        # Check if click is in the sentiment bar area (first content line, for assistant messages)
        # Note: assistant messages have padding: 1 2 0 2 (top=1, right=2, bottom=0, left=2)
        # So the first content line is at y=1 (after top padding)
        # And the right side has 2 chars of padding
        if self.role == "assistant" and not self._streaming and event.y == 1:
            # Sentiment bar is right-justified on the first content line
            # Layout: "emoji space emoji space emoji space emoji space emoji"
            # Each emoji is ~2 chars, space is 1 char = 3 chars per button (except last = 2)
            # Total width: 5 emojis * 2 + 4 spaces = 14 chars
            sentiment_bar_width = 14
            # Account for right padding (2 chars) when calculating content width
            content_width = self.size.width - 2 - 2  # subtract left and right padding

            # Check if click is in the right-side sentiment area (within content area)
            # Adjust event.x for left padding
            content_x = event.x - 2  # subtract left padding
            sentiment_start_x = content_width - sentiment_bar_width
            if content_x >= sentiment_start_x and content_x < content_width:
                # Calculate which button was clicked
                # Shift by 3 to align click area with visual position (emoji width variation)
                relative_x = content_x - sentiment_start_x - 3
                # Each button takes 3 chars (emoji=2 + space=1), except last (emoji=2)
                button_width = 3
                button_index = max(0, relative_x // button_width)
                # Clamp to valid range
                button_index = min(button_index, len(self.SENTIMENT_ORDER) - 1)

                if 0 <= button_index < len(self.SENTIMENT_ORDER):
                    clicked_sentiment = self.SENTIMENT_ORDER[button_index]

                    # Toggle behavior: clicking same button clears it
                    if self._sentiment == clicked_sentiment:
                        self._sentiment = None
                        self.remove_class("has-sentiment")
                    else:
                        self._sentiment = clicked_sentiment
                        self.add_class("has-sentiment")

                    self.refresh()
                    self.post_message(self.SentimentChanged(self.turn_id, self._sentiment))
                    return

        # Regular click behavior - highlight tree node
        if self.turn_id > 0:
            # Find the ChatLog parent and post the click message
            for ancestor in self.ancestors_with_self:
                if isinstance(ancestor, ChatLogView):
                    ancestor.post_message(ChatLogView.TurnClicked(self.turn_id))
                    break

    def set_sentiment(self, sentiment: Sentiment | None) -> None:
        """Set the sentiment (for external updates)."""
        self._sentiment = sentiment
        if sentiment:
            self.add_class("has-sentiment")
        else:
            self.remove_class("has-sentiment")
        self.refresh()

    @property
    def sentiment(self) -> Sentiment | None:
        """Get the current sentiment."""
        return self._sentiment

    @property
    def content(self) -> str:
        return self._content


class SessionHeader(Static):
    """Header showing session title."""

    DEFAULT_CSS = """
    SessionHeader {
        height: auto;
        padding: 0 1;
        background: $surface;
        color: $text;
        text-style: bold;
        border-bottom: solid $primary;
    }

    SessionHeader.hidden {
        display: none;
    }
    """

    def __init__(self, title: str = "", **kwargs):
        super().__init__(**kwargs)
        self._title = title
        if not title:
            self.add_class("hidden")

    def render(self) -> RenderableType:
        return Text(self._title) if self._title else Text("")

    def set_title(self, title: str) -> None:
        self._title = title
        if title:
            self.remove_class("hidden")
        else:
            self.add_class("hidden")
        self.refresh()


class MoreBelowIndicator(Static):
    """Floating indicator shown when there's more content below the viewport."""

    DEFAULT_CSS = """
    MoreBelowIndicator {
        dock: bottom;
        height: 1;
        width: auto;
        margin: 0 2 1 2;
        padding: 0 2;
        background: $primary-darken-2;
        color: $text;
        text-style: bold;
        text-align: center;
        display: none;
    }

    MoreBelowIndicator.visible {
        display: block;
    }

    MoreBelowIndicator.new-messages {
        background: $warning;
    }
    """

    class Clicked(Message):
        """Posted when the indicator is clicked."""
        pass

    def __init__(self, **kwargs):
        super().__init__("↓ More below ↓", **kwargs)
        self._new_message_count = 0

    def show_more_below(self) -> None:
        """Show the indicator for content below viewport."""
        # TEMPORARILY DISABLED for debugging scroll issues
        return
        if self._new_message_count == 0:
            self.update("↓ More below ↓")
            self.remove_class("new-messages")
        self.add_class("visible")

    def show_new_messages(self) -> None:
        """Show with new message styling."""
        # TEMPORARILY DISABLED for debugging scroll issues
        return
        self._new_message_count += 1
        self.add_class("new-messages")
        if self._new_message_count == 1:
            self.update("↓ New messages below ↓")
        else:
            self.update(f"↓ {self._new_message_count} new messages below ↓")
        self.add_class("visible")

    def hide(self) -> None:
        """Hide the indicator and reset count."""
        self.remove_class("visible")
        self.remove_class("new-messages")
        self._new_message_count = 0

    def on_click(self) -> None:
        """Handle click to scroll to bottom."""
        self.post_message(self.Clicked())


# Keep old name for backwards compatibility
NewMessagesIndicator = MoreBelowIndicator


class ChatLogView(VerticalScroll):
    """Scrolling container for chat messages."""

    class FollowingChanged(Message):
        """Posted when the following state changes."""

        def __init__(self, following: bool) -> None:
            super().__init__()
            self.following = following

    class ContextModeToggleRequested(Message):
        """Posted when user clicks a widget to toggle its context mode."""

        def __init__(self, turn_id: int) -> None:
            super().__init__()
            self.turn_id = turn_id

    class TurnClicked(Message):
        """Posted when user clicks a turn widget to highlight it in the tree."""

        def __init__(self, turn_id: int) -> None:
            super().__init__()
            self.turn_id = turn_id

    class NewContentWhileNotFollowing(Message):
        """Posted when new content arrives while user is not following."""
        pass

    class ColonPressed(Message):
        """Posted when user types : to jump to text entry."""
        pass

    class TurnViewed(Message):
        """Posted when a turn is scrolled into view and should be marked as viewed."""
        def __init__(self, turn_id: int) -> None:
            super().__init__()
            self.turn_id = turn_id

    class SentimentChanged(Message):
        """Posted when a user changes the sentiment rating on a turn."""
        def __init__(self, turn_id: int, sentiment: Sentiment | None) -> None:
            super().__init__()
            self.turn_id = turn_id
            self.sentiment = sentiment

    following: reactive[bool] = reactive(True)  # True when auto-scrolling to new content

    DEFAULT_CSS = """
    ChatLogView {
        height: 1fr;
        background: $background;
        padding: 1;
        scrollbar-gutter: stable;
    }

    ChatLogView #chat-loading {
        height: 100%;
        align: center middle;
    }

    ChatLogView .loading-message {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_assistant_message: MessageWidget | None = None
        self._turn_counter = 0
        self._header: SessionHeader | None = None
        # Unviewed turn IDs for scrollbar markers
        self._unviewed_turn_ids: set[int] = set()
        # Stream buffer - manages rate-limited text buffering
        self._stream_buffer = StreamBuffer(
            flush_callback=self._on_stream_buffer_flush,
            timer_factory=self,  # ChatLogView (via Textual's Widget) has set_timer
        )
        # Scroll controller - manages scroll state and smart scrolling
        # Note: We pass `self` as the container since ChatLogView IS a VerticalScroll
        from core.debug_log import debug_log
        self._scroll_controller = ScrollController(
            container=self,
            on_following_changed=self._on_scroll_following_changed,
            on_new_content_while_not_following=self._on_new_content_while_not_following,
            debug_log=debug_log,
        )
        # Widget registry - provides lookup and highlight operations
        self._widget_registry = WidgetRegistry(
            get_children=lambda: iter(self.children),
            debug_log=debug_log,
        )

    async def _on_key(self, event: Key) -> None:
        """Handle key events - colon jumps to text entry."""
        if event.key == "colon":
            self.post_message(self.ColonPressed())
            event.prevent_default()
            event.stop()
            return
        await super()._on_key(event)

    def watch_following(self, following: bool) -> None:
        """Post a message when following state changes.

        This is called by Textual's reactive system when `self.following` changes.
        We sync the controller's state to match.
        """
        from core.debug_log import debug_log
        debug_log.trace(f"watch_following: following changed to {following}", category="chat_log")
        # Sync controller state (avoid re-triggering if already in sync)
        if self._scroll_controller.following != following:
            self._scroll_controller._following = following  # Direct set to avoid callback loop
        if self.is_mounted:
            self.post_message(self.FollowingChanged(following))

    def _on_scroll_following_changed(self, following: bool) -> None:
        """Callback from ScrollController when following state changes.

        Updates the reactive property, which triggers watch_following.
        """
        if self.following != following:
            self.following = following

    def _on_new_content_while_not_following(self) -> None:
        """Callback from ScrollController when new content arrives while not following."""
        self.post_message(self.NewContentWhileNotFollowing())

    def _notify_new_content(self) -> None:
        """Called when new content is added - notifies via scroll controller."""
        self._scroll_controller.notify_new_content()

    def compose(self):
        self._header = SessionHeader("", id="session-header")
        yield self._header

    def on_mount(self) -> None:
        """Set up the custom scrollbar renderer when mounted."""
        # Use the marked scrollbar renderer for the vertical scrollbar
        self.vertical_scrollbar.renderer = MarkedScrollBarRender

    def on_message_widget_sentiment_changed(self, event: MessageWidget.SentimentChanged) -> None:
        """Handle sentiment changes from MessageWidget and bubble up as ChatLogView message."""
        # Re-post as a ChatLogView message so the app can handle it
        self.post_message(self.SentimentChanged(event.turn_id, event.sentiment))

    def set_unviewed_markers(self, unviewed_turn_ids: list[int]) -> None:
        """Update the scrollbar markers to show unviewed turn positions.

        Args:
            unviewed_turn_ids: List of 1-indexed turn IDs that are unviewed

        Note: Markers are currently disabled (hidden) while tracking logic is preserved.
        """
        self._unviewed_turn_ids = set(unviewed_turn_ids)
        # Markers disabled for now - just clear them
        MarkedScrollBarRender.markers = []
        self.vertical_scrollbar.refresh()

    def _update_scrollbar_markers(self) -> None:
        """Recalculate and apply scrollbar markers based on unviewed turns."""
        if not self._unviewed_turn_ids:
            MarkedScrollBarRender.markers = []
            self.vertical_scrollbar.refresh()
            return

        # Calculate marker positions as fractions of total content height
        markers = []
        total_height = self.virtual_size.height
        if total_height <= 0:
            MarkedScrollBarRender.markers = []
            return

        # Find widgets for each unviewed turn and calculate their position
        for child in self.children:
            if hasattr(child, 'turn_id') and child.turn_id in self._unviewed_turn_ids:
                # Get the widget's position in the virtual content
                region = child.virtual_region
                # Calculate position as fraction (center of the widget)
                center_y = region.y + region.height / 2
                fraction = center_y / total_height
                fraction = max(0.0, min(1.0, fraction))
                markers.append(fraction)

        MarkedScrollBarRender.markers = sorted(markers)
        self.vertical_scrollbar.refresh()

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Called by Textual whenever scroll_y changes.

        This catches ALL scroll changes: mouse wheel, keyboard (PageUp/Down, arrows),
        and programmatic scrolls. The scroll controller distinguishes between
        user and programmatic scrolls using a flag.
        """
        from core.debug_log import debug_log
        debug_log.trace(
            f"watch_scroll_y: {old_value:.0f} -> {new_value:.0f}, "
            f"max={self.max_scroll_y:.0f}, "
            f"programmatic={self._scroll_controller.is_programmatic_scroll}, "
            f"following_before={self._scroll_controller.following}",
            category="scroll"
        )
        super().watch_scroll_y(old_value, new_value)
        self._scroll_controller.on_scroll_changed(old_scroll_y=old_value)
        debug_log.trace(
            f"watch_scroll_y after: following={self._scroll_controller.following}",
            category="scroll"
        )

    def _smart_scroll(self) -> None:
        """Scroll to end only if user hasn't scrolled up."""
        self._scroll_controller.smart_scroll()

    def scroll_to_turn(self, turn_id: int, scroll_to_top: bool = False) -> bool:
        """Scroll to a turn by ID and disable follow mode if not at the bottom.

        Args:
            turn_id: The 1-indexed turn ID to scroll to
            scroll_to_top: If True, always scroll so turn is at top of viewport.
                          If False (default), use smart scroll that minimizes movement.

        Returns True if the turn was found and scrolled to, False otherwise.
        """
        from core.debug_log import debug_log
        debug_log.trace(f"scroll_to_turn: looking for turn_id={turn_id}, scroll_to_top={scroll_to_top}", category="chat_log")
        for child in self.children:
            if hasattr(child, 'turn_id') and child.turn_id == turn_id:
                debug_log.trace(f"scroll_to_turn: found turn_id={turn_id}, scrolling", category="chat_log")
                if scroll_to_top:
                    self.scroll_to_widget_at_top(child)
                else:
                    self.scroll_to_widget_and_check_follow(child)
                # Mark turn as viewed since user explicitly scrolled to it
                self.post_message(self.TurnViewed(turn_id))
                return True
        debug_log.warning(f"scroll_to_turn: turn_id={turn_id} NOT FOUND", category="chat_log")
        return False

    def scroll_to_widget_and_check_follow(self, widget) -> None:
        """Scroll to a widget smartly: show entire widget if it fits, else scroll to top.

        If the widget is shorter than the viewport, scroll so the entire widget is visible.
        If the widget is taller than the viewport, scroll so the top of the widget is at the
        top of the viewport (so the user can start reading from the beginning).

        Accounts for the floating "more below" indicator (2 lines) at the bottom.
        """
        region = widget.virtual_region
        self._scroll_controller.scroll_to_widget(
            WidgetRegion(y=region.y, height=region.height),
            at_top=False,
        )

    def scroll_to_widget_at_top(self, widget) -> None:
        """Scroll so the widget is at the top of the viewport.

        Unlike scroll_to_widget_and_check_follow, this always scrolls to put
        the widget at the top, even if it's already partially visible.
        Useful for exchange nodes where we want the first turn at the top.
        """
        from core.debug_log import debug_log
        region = widget.virtual_region
        content_offset_y = self.content_offset.y if hasattr(self, 'content_offset') else 0
        turn_id = getattr(widget, 'turn_id', '?')
        debug_log.trace(
            f"scroll_to_widget_at_top: turn_id={turn_id}, "
            f"region.y={region.y}, region.height={region.height}, "
            f"widget.size={widget.size}, widget._content_width={getattr(widget, '_content', '?')[:30] if hasattr(widget, '_content') else '?'}",
            category="chat_log"
        )
        self._scroll_controller.scroll_to_widget(
            WidgetRegion(y=region.y, height=region.height),
            at_top=True,
            content_offset_y=content_offset_y,
        )

    def set_session_title(self, title: str) -> None:
        """Set the session title displayed in the header."""
        if self._header:
            self._header.set_title(title)

    def add_user_message(self, content: str) -> MessageWidget:
        """Add a user message to the log."""
        self._turn_counter += 1
        # User sending message means they want to see response - reset scroll state
        self.following = True
        widget = MessageWidget("user", content, turn_id=self._turn_counter)
        self.mount(widget)
        self.scroll_end(animate=False)
        return widget

    def add_info_message(self, content: str, title: str = "") -> InfoWidget:
        """Add an informational message to the log (for command output).

        Unlike user/assistant messages, info messages are not saved to the session.
        They're ephemeral displays for command output like :goals, :todos, etc.

        Args:
            content: Rich markup content to display
            title: Optional title for the info panel

        Returns:
            The InfoWidget that was added
        """
        self._turn_counter += 1
        widget = InfoWidget(content, title=title, turn_id=self._turn_counter)
        self.mount(widget)
        self._smart_scroll()
        return widget

    def add_assistant_message(self, content: str = "") -> MessageWidget:
        """Add an assistant message to the log."""
        self._turn_counter += 1
        widget = MessageWidget("assistant", content, streaming=True, turn_id=self._turn_counter)
        widget.add_class("streaming")
        self._current_assistant_message = widget
        self.mount(widget)
        self._smart_scroll()
        self._notify_new_content()
        return widget

    def append_to_current(self, text: str) -> None:
        """Append text to the current assistant message.

        If there's no current streaming message (e.g., after a tool use finalized it),
        create a new one to receive text that comes after tools.

        Text is buffered and flushed at a rate-limited interval to reduce UI
        refresh overhead during fast streaming (especially under high CPU load).
        """
        if not self._current_assistant_message:
            # Create a new streaming message for text after tool use
            widget = MessageWidget("assistant", "", streaming=True, turn_id=self._turn_counter)
            widget.add_class("streaming")
            self._current_assistant_message = widget
            self.mount(widget)

        # Buffer the text via StreamBuffer (handles rate limiting)
        self._stream_buffer.append(text)

    def _on_stream_buffer_flush(self, text: str) -> None:
        """Callback from StreamBuffer when buffered text is ready to flush."""
        if self._current_assistant_message:
            # Use batch_update to coalesce all refreshes into one
            with self.app.batch_update():
                self._current_assistant_message.append_text(text, refresh=True)
                self._smart_scroll()
                self._notify_new_content()

    def resume_streaming(
        self,
        user_prompt: str,
        accumulated_content: str,
        tool_events: dict | None = None,
        format_tool_use_fn=None,
        format_tool_result_fn=None,
    ) -> None:
        """Resume streaming display when switching to a mid-stream session.

        This is called when switching to a session that is currently streaming.
        It shows the user message that started the turn, replays any tool events,
        then creates a new assistant message with the accumulated content so far,
        so subsequent `append_to_current` calls continue from where it left off.

        Args:
            user_prompt: The user's message that started this turn (empty for query_with)
            accumulated_content: Text accumulated so far in the assistant response
            tool_events: Dict of tool_use_id -> {name, input, result, index} for replay
            format_tool_use_fn: Function to format tool use for display
            format_tool_result_fn: Function to format tool result for display
        """
        # Add user message if present (not for query_with)
        if user_prompt:
            self._turn_counter += 1
            user_widget = MessageWidget("user", user_prompt, turn_id=self._turn_counter)
            self.mount(user_widget)

        # Replay tool events in order (sorted by index)
        if tool_events and format_tool_use_fn:
            # Sort by index to preserve order
            sorted_tools = sorted(tool_events.items(), key=lambda x: x[1].get("index", 0))
            for tool_use_id, tool_data in sorted_tools:
                # Add tool use
                formatted = format_tool_use_fn(tool_data["name"], tool_data["input"])
                if isinstance(formatted, tuple):
                    tool_content, full_content = formatted
                else:
                    tool_content, full_content = formatted, None
                self.add_tool_use(
                    tool_data["name"], tool_content,
                    tool_use_id=tool_use_id, full_content=full_content
                )
                # Add tool result if available
                if tool_data.get("result") is not None and format_tool_result_fn:
                    result_formatted = format_tool_result_fn(tool_data["result"])
                    if isinstance(result_formatted, tuple):
                        result_content, result_full = result_formatted
                    else:
                        result_content, result_full = result_formatted, None
                    self.add_tool_result(
                        result_content, tool_use_id=tool_use_id, full_content=result_full
                    )

        # Add partial assistant message with any accumulated text
        self._turn_counter += 1
        widget = MessageWidget(
            "assistant", accumulated_content, streaming=True, turn_id=self._turn_counter
        )
        widget.add_class("streaming")
        self._current_assistant_message = widget
        self.mount(widget)
        self._smart_scroll()

    def add_tool_use(
        self,
        tool_name: str,
        content: RenderableType,
        tool_use_id: str = "",
        full_content: RenderableType | None = None,
    ) -> ToolUseWidget:
        """Add a tool use widget to the log.

        When there's a streaming message with content, we finalize it first
        so that text appears before the tool, then create a new streaming
        message for any text that comes after.
        """
        turn_id = self._turn_counter

        # Handle current streaming message
        if self._current_assistant_message:
            if self._current_assistant_message._content.strip():
                # Has content - finalize it so text stays above tool widget
                self._current_assistant_message.remove_class("streaming")
                self._current_assistant_message.finish_streaming()
            else:
                # Empty message - remove it
                self._current_assistant_message.remove()
            self._current_assistant_message = None

        widget = ToolUseWidget(
            tool_name, content, turn_id=turn_id, tool_use_id=tool_use_id, full_content=full_content
        )
        self.mount(widget)
        self._smart_scroll()
        self._notify_new_content()
        return widget

    def add_tool_result(
        self,
        content: RenderableType,
        tool_use_id: str = "",
        full_content: RenderableType | None = None,
    ) -> ToolResultWidget:
        """Add a tool result widget to the log."""
        turn_id = self._turn_counter
        widget = ToolResultWidget(
            content, turn_id=turn_id, tool_use_id=tool_use_id, full_content=full_content
        )
        self.mount(widget)
        self._smart_scroll()
        self._notify_new_content()
        return widget

    def add_streaming_tool_use(
        self,
        tool_name: str,
        tool_use_id: str,
    ) -> ToolUseWidget:
        """Add a streaming tool use widget (input still being received).

        When there's a streaming message with content, we finalize it first
        so that text appears before the tool.
        """
        turn_id = self._turn_counter

        # Handle current streaming message (same as add_tool_use)
        if self._current_assistant_message:
            if self._current_assistant_message._content.strip():
                self._current_assistant_message.remove_class("streaming")
                self._current_assistant_message.finish_streaming()
            else:
                self._current_assistant_message.remove()
            self._current_assistant_message = None

        widget = ToolUseWidget(
            tool_name=tool_name,
            turn_id=turn_id,
            tool_use_id=tool_use_id,
            streaming=True,
        )
        self.mount(widget)
        self._smart_scroll()
        self._notify_new_content()
        return widget

    def update_streaming_tool(self, tool_use_id: str, partial_json: str) -> None:
        """Append partial JSON to a streaming tool use widget."""
        for child in self.children:
            if isinstance(child, ToolUseWidget) and child.tool_use_id == tool_use_id:
                child.append_input(partial_json)
                self._smart_scroll()
                return

    def remove_streaming_tool(self, tool_use_id: str) -> None:
        """Remove a streaming tool widget (used when tool is intercepted and handled separately).

        Called when tools like propose_fork/propose_merge are handled with custom UI
        instead of the standard tool widget.
        """
        for child in self.children:
            if isinstance(child, ToolUseWidget) and child.tool_use_id == tool_use_id:
                child.remove()
                return

    def finish_streaming_tool(
        self,
        tool_use_id: str,
        content: RenderableType,
        full_content: RenderableType | None = None,
        tool_name: str = "",
    ) -> None:
        """Complete a streaming tool use with final formatted content.

        If no streaming widget exists for this tool_use_id, creates one with the
        final content (fallback for when tool_use_start wasn't received).
        """
        for child in self.children:
            if isinstance(child, ToolUseWidget) and child.tool_use_id == tool_use_id:
                child.finish_streaming(content, full_content)
                return

        # Fallback: widget doesn't exist, create it with final content
        # This happens if tool_use_start event wasn't processed
        if tool_name:
            self.add_tool_use(tool_name, content, tool_use_id=tool_use_id, full_content=full_content)

    def finish_current_message(self) -> str:
        """Mark streaming complete and return combined text from all assistant messages in this turn.

        Since text may be split across multiple MessageWidgets (due to tool uses
        in between), we collect content from all assistant messages in the current turn.
        Finishes ALL streaming messages in the turn, not just _current_assistant_message.
        """
        # Flush any pending buffered text first
        remaining_text = self._stream_buffer.flush()
        if remaining_text and self._current_assistant_message:
            self._current_assistant_message.append_text(remaining_text, refresh=False)

        turn_id = self._turn_counter
        content_parts = []

        # Finish ALL streaming assistant messages in this turn
        for child in self.children:
            if isinstance(child, MessageWidget) and child.role == "assistant" and child.turn_id == turn_id:
                if child._streaming:
                    child.remove_class("streaming")
                    child.finish_streaming()
                if child.content.strip():
                    content_parts.append(child.content)

        self._current_assistant_message = None

        # Scroll after finishing - the Markdown re-render changes widget height significantly,
        # so we need to scroll after the layout recalculates
        self._smart_scroll()

        # If user is following (watching the stream), mark the turn as viewed
        if self.following:
            self.post_message(self.TurnViewed(turn_id))

        return "\n\n".join(content_parts)

    def add_interruption_marker(self, reason: str = "user_cancelled") -> InterruptionMarkerWidget:
        """Add an interruption marker to the log."""
        turn_id = self._turn_counter
        widget = InterruptionMarkerWidget(reason=reason, turn_id=turn_id)
        self.mount(widget)
        self._smart_scroll()
        return widget

    def add_error_marker(
        self,
        reason: str = "stream_error",
        partial_tool_name: str = "",
        details: str = "",
        dump_file: str = "",
    ) -> ErrorMarkerWidget:
        """Add an error marker to the log (truncated response, etc.)."""
        turn_id = self._turn_counter
        widget = ErrorMarkerWidget(
            reason=reason,
            partial_tool_name=partial_tool_name,
            details=details,
            dump_file=dump_file,
            turn_id=turn_id,
        )
        self.mount(widget)
        self._smart_scroll()
        return widget

    def clear(self) -> None:
        """Clear all messages and reset counter."""
        # Cancel any pending stream buffer
        self._stream_buffer.cancel()

        for child in list(self.children):
            child.remove()
        self._turn_counter = 0
        self._current_assistant_message = None
        # Clear scrollbar markers
        self._unviewed_turn_ids.clear()
        MarkedScrollBarRender.markers = []

    def show_loading(self, message: str = "Switching session...") -> None:
        """Show a loading indicator in the chat log.

        Call this before clearing/loading to provide visual feedback during session switches.
        The loading indicator is automatically removed when load_history is called.
        """
        self.clear()
        # Mount a centered loading indicator
        loading_container = Center(
            LoadingIndicator(),
            Static(message, classes="loading-message"),
            id="chat-loading",
        )
        self.mount(loading_container)

    def hide_loading(self) -> None:
        """Hide the loading indicator if present."""
        try:
            loading = self.query_one("#chat-loading")
            loading.remove()
        except Exception:
            pass  # No loading indicator to remove

    def highlight_tool(self, tool_use_id: str) -> None:
        """Highlight a tool use and its result by tool_use_id, scrolling to it."""
        scroll_target = self._widget_registry.highlight_tool(tool_use_id)
        if scroll_target:
            self.scroll_to_widget_and_check_follow(scroll_target)

    def highlight_text_block(self, turn_id: int, block_idx: int) -> None:
        """Highlight a text block by turn_id and block_idx, scrolling to it."""
        scroll_target = self._widget_registry.highlight_text_block(turn_id, block_idx)
        if scroll_target:
            self.scroll_to_widget_and_check_follow(scroll_target)

    def highlight_turn(self, turn_id: int, scroll_to_top: bool = False) -> None:
        """Highlight a turn by turn_id, scrolling to it.

        Args:
            turn_id: The 1-indexed turn ID to highlight
            scroll_to_top: If True, always scroll so turn is at top of viewport.
                          If False (default), use smart scroll that minimizes movement.
        """
        from core.debug_log import debug_log
        debug_log.trace(f"highlight_turn: turn_id={turn_id}, scroll_to_top={scroll_to_top}", category="chat_log")
        scroll_target = self._widget_registry.highlight_turn(turn_id)
        debug_log.trace(f"highlight_turn: scroll_target={scroll_target}, type={type(scroll_target).__name__ if scroll_target else None}", category="chat_log")
        if scroll_target:
            if scroll_to_top:
                self.scroll_to_widget_at_top(scroll_target)
            else:
                self.scroll_to_widget_and_check_follow(scroll_target)

    def clear_highlights(self) -> None:
        """Remove all highlights from tools and messages."""
        self._widget_registry.clear_highlights()

    def _format_tool_use(
        self, block: ToolUseBlock
    ) -> RenderableType | tuple[RenderableType, RenderableType]:
        """Format a tool use block for display.

        Returns either a single renderable, or tuple of (truncated, full) if content was truncated.
        """
        from core.formatter import Formatter
        formatter = Formatter()
        return formatter.format_tool_use_block(block)

    def _format_tool_result(
        self, block: ToolResultBlock
    ) -> RenderableType | tuple[RenderableType, RenderableType]:
        """Format a tool result block for display.

        Returns either a single renderable, or tuple of (truncated, full) if content was truncated.
        """
        from core.formatter import Formatter
        formatter = Formatter()
        return formatter.format_tool_result_block(block)

    async def load_history(self, messages: list, session: Session | None = None) -> None:
        """Load message history from a list of Message objects.

        If session is provided, also reconstructs fork, merge, and link markers from
        the session's children and links lists.

        Uses HistoryLoader to transform messages into render instructions, then
        interprets those instructions to create and mount widgets.
        """
        import time
        from core.debug_log import perf_marker

        start = time.perf_counter()

        # Hide loading indicator if present
        self.hide_loading()

        loader = HistoryLoader()
        result = await loader.load(messages, session=session, start_turn_id=self._turn_counter)

        mount_start = time.perf_counter()
        widget_count = 0
        for instr in result.instructions:
            widget = self._instruction_to_widget(instr)
            if widget:
                self.mount(widget)
                widget_count += 1

        self._turn_counter = result.final_turn_id
        self.scroll_end(animate=False)

        elapsed_ms = (time.perf_counter() - start) * 1000
        mount_ms = (time.perf_counter() - mount_start) * 1000
        session_id = session.id[:8] if session else "unknown"
        perf_marker(
            "chat_log.load_history",
            session_id=session_id,
            message_count=len(messages),
            widget_count=widget_count,
            elapsed_ms=round(elapsed_ms, 1),
            mount_ms=round(mount_ms, 1),
        )

    def _instruction_to_widget(self, instr):
        """Convert a render instruction to a widget.

        This method bridges the data layer (instructions) with the UI layer (widgets).
        """
        if isinstance(instr, RenderMessage):
            return MessageWidget(
                instr.role, instr.text, turn_id=instr.turn_id, block_idx=instr.block_idx,
                sentiment=instr.sentiment
            )

        elif isinstance(instr, RenderToolUse):
            # Format using Formatter for display
            block = ToolUseBlock(id=instr.tool_use_id, name=instr.tool_name, input=instr.tool_input)
            formatted = self._format_tool_use(block)
            if isinstance(formatted, tuple):
                content, full_content = formatted
            else:
                content, full_content = formatted, None
            return ToolUseWidget(
                instr.tool_name, content, turn_id=instr.turn_id,
                tool_use_id=instr.tool_use_id, full_content=full_content
            )

        elif isinstance(instr, RenderToolResult):
            # Format using Formatter for display
            block = ToolResultBlock(
                tool_use_id=instr.tool_use_id,
                content=instr.content,
                is_error=instr.is_error
            )
            formatted = self._format_tool_result(block)
            if isinstance(formatted, tuple):
                content, full_content = formatted
            else:
                content, full_content = formatted, None
            return ToolResultWidget(
                content, turn_id=instr.turn_id,
                tool_use_id=instr.tool_use_id, full_content=full_content
            )

        elif isinstance(instr, RenderInterruption):
            return InterruptionMarkerWidget(
                reason=instr.reason, turn_id=instr.turn_id
            )

        elif isinstance(instr, RenderError):
            return ErrorMarkerWidget(
                reason=instr.reason,
                partial_tool_name=instr.partial_tool_name,
                details=instr.details,
                dump_file=instr.dump_file,
                turn_id=instr.turn_id,
            )

        elif isinstance(instr, RenderLink):
            return LinkMarker(
                summary=instr.summary,
                linked_session_id=instr.linked_session_id,
                linked_session_name=instr.linked_session_name,
                link_point=instr.link_point,
                turn_id=instr.turn_id,
                is_orphaned=instr.is_orphaned,
            )

        elif isinstance(instr, RenderArchive):
            return ArchiveMarker(
                archive_block=instr.archive_block,
                turn_id=instr.turn_id,
                turn_index=instr.turn_index,
            )

        elif isinstance(instr, RenderFork):
            return ForkMarker(
                prompt=instr.prompt,
                child_session_id=instr.child_session_id,
                fork_name=instr.fork_name,
                status=instr.status,
                turn_id=instr.turn_id,
            )

        elif isinstance(instr, RenderMerge):
            return MergeMarker(
                message=instr.message,
                child_session_id=instr.child_session_id,
                fork_name=instr.fork_name,
                files_changed=instr.files_changed,
                key_accomplishments=instr.key_accomplishments,
                reason=instr.reason,
                turn_id=instr.turn_id,
            )

        elif isinstance(instr, RenderMergedTo):
            return MergedToMarker(
                message=instr.message,
                parent_session_id=instr.parent_session_id,
                parent_name=instr.parent_name,
                parent_turn=instr.parent_turn,
                merge_id=instr.merge_id,
                files_changed=instr.files_changed,
                key_accomplishments=instr.key_accomplishments,
                reason=instr.reason,
                turn_id=instr.turn_id,
            )

        elif isinstance(instr, RenderReview):
            return ReviewMarker(
                child_session_id=instr.child_session_id,
                model_under_review=instr.model_under_review,
                status=instr.status,
                overall_score=instr.overall_score,
                task_category=instr.task_category,
                task_description=instr.task_description,
                turn_id=instr.turn_id,
            )

        elif isinstance(instr, RenderForkProposal):
            return ForkProposalMarker(
                proposal_id=instr.proposal_id,
                name=instr.name,
                description=instr.description,
                context_plan=instr.context_plan,
                initial_prompt=instr.initial_prompt,
                bind_to=instr.bind_to,
                bind_to_inherit=instr.bind_to_inherit,
                status=instr.status,
                turn_id=instr.turn_id,
                all_exchanges=instr.all_exchanges,
            )

        elif isinstance(instr, RenderMergeProposal):
            return MergeProposalMarker(
                proposal_id=instr.proposal_id,
                summary=instr.summary,
                reason=instr.reason,
                files_changed=instr.files_changed,
                key_accomplishments=instr.key_accomplishments,
                status=instr.status,
                turn_id=instr.turn_id,
            )

        return None

    def add_with_widget(
        self,
        prompt: str,
        child_session_id: str,
        status: str = "active",
        return_condition: str = "manual",
    ) -> WithWidget:
        """Add a with widget to the log (fork point marker)."""
        turn_id = self._turn_counter
        widget = WithWidget(
            prompt=prompt,
            child_session_id=child_session_id,
            status=status,
            return_condition=return_condition,
            turn_id=turn_id,
        )
        self.mount(widget)
        self._smart_scroll()
        return widget

    def add_with_result_widget(
        self,
        content: str,
        child_session_id: str,
        return_prompt: str = "",
    ) -> WithResultWidget:
        """Add a with result widget to the log (returned content)."""
        turn_id = self._turn_counter
        widget = WithResultWidget(
            content=content,
            child_session_id=child_session_id,
            return_prompt=return_prompt,
            turn_id=turn_id,
        )
        self.mount(widget)
        self._smart_scroll()
        return widget

    def find_with_widget(self, child_session_id: str) -> WithWidget | None:
        """Find a WithWidget by its child session ID."""
        return self._widget_registry.find_with_widget(child_session_id)

    def filter_by_turns(self, turn_ids: list[int], show_all: bool = False) -> None:
        """Show only specified turns, or all if show_all is True.

        DEPRECATED: Use set_turn_context_modes instead for visual indication without hiding.
        """
        self._widget_registry.filter_by_turns(turn_ids, show_all)
        self._smart_scroll()

    def set_turn_context_modes(self, turn_modes: dict[int, str]) -> None:
        """Apply visual context mode indicators to turns.

        Instead of hiding turns, this shows all turns but with visual indication
        of their context state:
        - COPY: green border (included in full)
        - COMPRESS: yellow border, slightly faded (will be summarized)
        - DROP: very faded (not included in context)

        Args:
            turn_modes: Dict mapping turn_id (1-indexed) to mode name ("COPY", "COMPRESS", "DROP")
        """
        self._widget_registry.set_turn_context_modes(turn_modes)

    def add_fork_marker(
        self,
        prompt: str,
        child_session_id: str,
        fork_name: str,
        status: str = "active",
    ) -> ForkMarker:
        """Add a fork marker to the log (shows where a fork started)."""
        turn_id = self._turn_counter
        widget = ForkMarker(
            prompt=prompt,
            child_session_id=child_session_id,
            fork_name=fork_name,
            status=status,
            turn_id=turn_id,
        )
        self.mount(widget)
        self._smart_scroll()
        return widget

    def add_merge_marker(
        self,
        message: str,
        child_session_id: str,
        fork_name: str,
    ) -> MergeMarker:
        """Add a merge marker to the log (shows where a fork merged back)."""
        turn_id = self._turn_counter
        widget = MergeMarker(
            message=message,
            child_session_id=child_session_id,
            fork_name=fork_name,
            turn_id=turn_id,
        )
        self.mount(widget)
        self._smart_scroll()
        return widget

    def find_fork_marker(self, child_session_id: str) -> ForkMarker | None:
        """Find a ForkMarker by its child session ID."""
        return self._widget_registry.find_fork_marker(child_session_id)

    def find_merge_marker(self, child_session_id: str) -> MergeMarker | None:
        """Find a MergeMarker by its child session ID."""
        return self._widget_registry.find_merge_marker(child_session_id)

    def add_review_marker(
        self,
        child_session_id: str,
        model_under_review: str,
        status: str = "active",
    ) -> ReviewMarker:
        """Add a review marker to the log (shows where a quality review was initiated)."""
        turn_id = self._turn_counter
        widget = ReviewMarker(
            child_session_id=child_session_id,
            model_under_review=model_under_review,
            status=status,
            turn_id=turn_id,
        )
        self.mount(widget)
        self._smart_scroll()
        return widget

    def find_review_marker(self, child_session_id: str) -> ReviewMarker | None:
        """Find a ReviewMarker by its child session ID."""
        return self._widget_registry.find_review_marker(child_session_id)

    def scroll_to_merge_marker(self, child_session_id: str) -> bool:
        """Scroll to a merge marker by its child session ID.

        Returns True if the marker was found and scrolled to, False otherwise.
        """
        marker = self.find_merge_marker(child_session_id)
        if marker:
            self.scroll_to_widget_and_check_follow(marker)
            return True
        return False

    def add_link_marker(
        self,
        summary: str,
        linked_session_id: str,
        linked_session_name: str,
        link_point: int,
        is_orphaned: bool = False,
    ) -> LinkMarker:
        """Add a link marker to the log (shows bidirectional link to another session)."""
        turn_id = self._turn_counter
        widget = LinkMarker(
            summary=summary,
            linked_session_id=linked_session_id,
            linked_session_name=linked_session_name,
            link_point=link_point,
            turn_id=turn_id,
            is_orphaned=is_orphaned,
        )
        self.mount(widget)
        self._smart_scroll()
        return widget

    def find_link_marker(self, linked_session_id: str) -> LinkMarker | None:
        """Find a LinkMarker by its linked session ID."""
        return self._widget_registry.find_link_marker(linked_session_id)

    def scroll_to_link_marker(self, linked_session_id: str) -> bool:
        """Scroll to a link marker by its linked session ID.

        Returns True if the marker was found and scrolled to, False otherwise.
        """
        marker = self.find_link_marker(linked_session_id)
        if marker:
            self.scroll_to_widget_and_check_follow(marker)
            return True
        return False

    def add_archive_marker(
        self,
        archive_block: ArchiveBlock,
        turn_index: int,
    ) -> ArchiveMarker:
        """Add an archive marker to the log (shows archived turns)."""
        turn_id = self._turn_counter
        widget = ArchiveMarker(
            archive_block=archive_block,
            turn_id=turn_id,
            turn_index=turn_index,
        )
        self.mount(widget)
        self._smart_scroll()
        return widget

    def find_archive_marker(self, archive_id: str) -> ArchiveMarker | None:
        """Find an ArchiveMarker by its archive ID."""
        return self._widget_registry.find_archive_marker(archive_id)

    def remove_archive_marker(self, archive_id: str) -> bool:
        """Remove an archive marker by its archive ID.

        Returns True if the marker was found and removed, False otherwise.
        """
        marker = self.find_archive_marker(archive_id)
        if marker:
            marker.remove()
            return True
        return False
