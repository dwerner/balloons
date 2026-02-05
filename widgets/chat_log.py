import json
from pathlib import Path

from textual.widgets import Static
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.message import Message
from textual.events import Click, Key
from rich.markdown import Markdown
from rich.console import RenderableType, Group
from rich.text import Text
from rich.syntax import Syntax
from rich.panel import Panel

from .with_widget import WithWidget
from .with_result_widget import WithResultWidget
from .fork_marker import ForkMarker
from .merge_marker import MergeMarker
from .link_marker import LinkMarker
from .archive_marker import ArchiveMarker
from models import TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, LinkBlock, ForkBlock, MergeBlock, ArchiveBlock
from core.formatter import format_edit_as_diff, guess_language
from core.json_stream import StreamingJsonParser
from core.history_loader import (
    HistoryLoader,
    RenderMessage, RenderToolUse, RenderToolResult,
    RenderInterruption, RenderError, RenderLink, RenderArchive,
    RenderFork, RenderMerge
)
from session import Session

# Re-export for backwards compatibility (used by app.py imports)
_format_edit_as_diff = format_edit_as_diff
_guess_language = guess_language


class ToolUseWidget(Static):
    """A tool use display in the chat log."""

    DEFAULT_CSS = """
    ToolUseWidget {
        padding: 0 1;
        margin: 0 0 1 2;
        background: #2a2a1a;
        border-left: thick $warning;
    }

    ToolUseWidget.hidden {
        display: none;
    }

    ToolUseWidget.highlighted {
        /* Use outline on top/right/bottom only - outline-left conflicts with border-left */
        outline-top: wide $warning;
        outline-right: wide $warning;
        outline-bottom: wide $warning;
    }

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

    /* Hover feedback - background change only, no border changes */
    ToolUseWidget:hover {
        background: #252525;
    }

    ToolUseWidget:focus {
        background: #232323;
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
        """Handle click - expand if collapsed and expandable, otherwise toggle context mode."""
        if self._full_content is not None and not self._expanded:
            # Collapsed expandable widget: expand it
            self.toggle_expand()
        elif self.turn_id > 0:
            # Expanded or non-expandable: toggle context mode
            for ancestor in self.ancestors_with_self:
                if isinstance(ancestor, ChatLogView):
                    ancestor.post_message(ChatLogView.ContextModeToggleRequested(self.turn_id))
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
        background: #2a2a20;
        border-left: thick #d4d422;
        max-height: 15;
        overflow-y: auto;
    }

    ToolResultWidget.hidden {
        display: none;
    }

    ToolResultWidget.highlighted {
        /* Use outline on top/right/bottom only - outline-left conflicts with border-left */
        outline-top: wide $warning;
        outline-right: wide $warning;
        outline-bottom: wide $warning;
    }

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

    /* Hover feedback - background change only, no border changes */
    ToolResultWidget:hover {
        background: #252525;
    }

    ToolResultWidget:focus {
        background: #232323;
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
        """Handle click - expand if collapsed and expandable, otherwise toggle context mode."""
        if self._full_content is not None and not self._expanded:
            # Collapsed expandable widget: expand it
            self.toggle_expand()
        elif self.turn_id > 0:
            # Expanded or non-expandable: toggle context mode
            for ancestor in self.ancestors_with_self:
                if isinstance(ancestor, ChatLogView):
                    ancestor.post_message(ChatLogView.ContextModeToggleRequested(self.turn_id))
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


class MessageWidget(Static):
    """A single message in the chat log."""

    DEFAULT_CSS = """
    MessageWidget {
        padding: 0 1;
        margin: 0 0 1 0;
    }

    MessageWidget.user {
        background: #1a1a3a;
        color: #e0d8b0;  /* Subtle light yellow for user messages */
        border-left: thick $primary;
        margin-left: 2;
        padding: 1 2;
    }

    MessageWidget.assistant {
        background: #2a1a1a;
        color: $text;
        border-left: thick $error;
        margin-left: 2;
    }

    MessageWidget:focus {
        background: #252525;
    }

    MessageWidget.user:focus {
        background: #1f1f2f;
    }

    MessageWidget.assistant:focus {
        background: #2f1f1f;
    }

    MessageWidget.streaming {
        border-left: thick $accent;
    }

    MessageWidget.hidden {
        display: none;
    }

    MessageWidget.highlighted {
        /* Use outline on top/right/bottom only - outline-left conflicts with border-left */
        outline-top: wide $warning;
        outline-right: wide $warning;
        outline-bottom: wide $warning;
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
    """

    def __init__(self, role: str, content: str = "", streaming: bool = False, turn_id: int = 0, block_idx: int = -1, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self._content = content
        self._streaming = streaming
        self.turn_id = turn_id
        self.block_idx = block_idx  # Index within content_blocks, -1 if not set
        self.add_class(role)

    def render(self) -> RenderableType:
        if self._streaming:
            # Plain text during streaming for performance
            return Text(f"{self._content}▌")
        elif self._content:
            # Render markdown with syntax highlighting
            return Markdown(self._content, code_theme="monokai")
        else:
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

    def on_click(self) -> None:
        """Toggle context mode when clicked."""
        if self.turn_id > 0:
            # Find the ChatLog parent and post the toggle message
            chat_log = self.ancestors_with_self
            for ancestor in chat_log:
                if isinstance(ancestor, ChatLogView):
                    ancestor.post_message(ChatLogView.ContextModeToggleRequested(self.turn_id))
                    break

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

    class NewContentWhileNotFollowing(Message):
        """Posted when new content arrives while user is not following."""
        pass

    class ColonPressed(Message):
        """Posted when user types : to jump to text entry."""
        pass

    following: reactive[bool] = reactive(True)  # True when auto-scrolling to new content

    DEFAULT_CSS = """
    ChatLogView {
        height: 1fr;
        background: $background;
        padding: 1;
    }
    """

    # Maximum update rate for streaming text (in seconds)
    # Lower = more responsive but higher CPU, higher = smoother under load
    STREAM_UPDATE_INTERVAL = 0.05  # 50ms = 20 updates/sec max

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_assistant_message: MessageWidget | None = None
        self._turn_counter = 0
        self._header: SessionHeader | None = None
        # Batched streaming text buffer
        self._pending_text: str = ""
        self._stream_update_timer = None

    async def _on_key(self, event: Key) -> None:
        """Handle key events - colon jumps to text entry."""
        if event.key == "colon":
            self.post_message(self.ColonPressed())
            event.prevent_default()
            event.stop()
            return
        await super()._on_key(event)

    def watch_following(self, following: bool) -> None:
        """Post a message when following state changes."""
        from core.debug_log import debug_log
        debug_log.info(f"watch_following: following changed to {following}", category="chat_log")
        if self.is_mounted:
            self.post_message(self.FollowingChanged(following))
            # Clear new messages flag when we start following again
            if following:
                self._has_new_messages = False

    def _notify_new_content(self) -> None:
        """Called when new content is added - posts message if not following."""
        from core.debug_log import debug_log
        if not self.following:
            debug_log.info(f"_notify_new_content: NOT following, posting NewContentWhileNotFollowing", category="chat_log")
            self.post_message(self.NewContentWhileNotFollowing())

    def compose(self):
        self._header = SessionHeader("", id="session-header")
        yield self._header

    def _check_at_bottom(self) -> None:
        """Check if we're at the bottom and update following state."""
        from core.debug_log import debug_log
        if not self.is_mounted:
            return
        # If max_scroll_y is 0 or very small, content fits in viewport - always following
        max_y = self.max_scroll_y
        if max_y <= 1:
            at_bottom = True
        else:
            at_bottom = (max_y - self.scroll_y) < 50
        # Only update if changed to avoid message spam
        if self.following != at_bottom:
            debug_log.info(
                f"_check_at_bottom: following changing from {self.following} to {at_bottom}, "
                f"max_scroll_y={max_y}, scroll_y={self.scroll_y}, gap={max_y - self.scroll_y}",
                category="chat_log"
            )
            self.following = at_bottom

    def on_mouse_scroll_down(self, event) -> None:
        """Track scrolling down (toward bottom)."""
        self._check_at_bottom()

    def on_mouse_scroll_up(self, event) -> None:
        """Track scrolling up (toward top)."""
        self._check_at_bottom()

    def _smart_scroll(self) -> None:
        """Scroll to end only if user hasn't scrolled up."""
        from core.debug_log import debug_log
        if self.following:
            debug_log.debug(f"_smart_scroll: following=True, scheduling scroll_end", category="chat_log")
            # Defer scroll until after layout refresh so scroll_end knows the true max_scroll_y
            self.call_after_refresh(self._scroll_end_and_verify)
        else:
            debug_log.debug(f"_smart_scroll: following=False, NOT scrolling", category="chat_log")

    def _scroll_end_and_verify(self) -> None:
        """Scroll to end and re-check if we're actually at the bottom."""
        from core.debug_log import debug_log
        debug_log.debug(
            f"_scroll_end_and_verify: before scroll_end, scroll_y={self.scroll_y}, max_scroll_y={self.max_scroll_y}",
            category="chat_log"
        )
        self.scroll_end(animate=False)
        debug_log.debug(
            f"_scroll_end_and_verify: after scroll_end, scroll_y={self.scroll_y}, max_scroll_y={self.max_scroll_y}",
            category="chat_log"
        )
        # Re-check after scroll in case content grew during the frame
        self.call_later(self._check_at_bottom)

    def scroll_to_turn(self, turn_id: int, scroll_to_top: bool = False) -> bool:
        """Scroll to a turn by ID and disable follow mode if not at the bottom.

        Args:
            turn_id: The 1-indexed turn ID to scroll to
            scroll_to_top: If True, always scroll so turn is at top of viewport.
                          If False (default), use smart scroll that minimizes movement.

        Returns True if the turn was found and scrolled to, False otherwise.
        """
        from core.debug_log import debug_log
        debug_log.info(f"scroll_to_turn: looking for turn_id={turn_id}, scroll_to_top={scroll_to_top}", category="chat_log")
        for child in self.children:
            if hasattr(child, 'turn_id') and child.turn_id == turn_id:
                debug_log.info(f"scroll_to_turn: found turn_id={turn_id}, scrolling", category="chat_log")
                if scroll_to_top:
                    self.scroll_to_widget_at_top(child)
                else:
                    self.scroll_to_widget_and_check_follow(child)
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
        from core.debug_log import debug_log
        # Reserve space for floating "more below" indicator
        INDICATOR_HEIGHT = 2

        # Use virtual_region which is relative to the container's content, not the viewport
        # widget.region is relative to screen and changes with scroll position
        widget_region = widget.virtual_region
        viewport_height = self.size.height
        effective_viewport = viewport_height - INDICATOR_HEIGHT
        widget_height = widget_region.height
        widget_top = widget_region.y
        widget_bottom = widget_top + widget_height

        debug_log.info(
            f"scroll_to_widget_and_check_follow: widget={widget}, virtual_region={widget_region}, "
            f"viewport_height={viewport_height}, effective_viewport={effective_viewport}, "
            f"current_scroll_y={self.scroll_y}",
            category="chat_log"
        )

        if widget_height <= effective_viewport:
            # Widget fits in viewport - ensure entire widget is visible above indicator
            current_scroll = self.scroll_y
            visible_top = current_scroll
            visible_bottom = current_scroll + effective_viewport

            if widget_top >= visible_top and widget_bottom <= visible_bottom:
                # Already fully visible - no scroll needed
                debug_log.info(f"  -> already visible, no scroll", category="chat_log")
                pass
            elif widget_top < visible_top:
                # Widget is above viewport - scroll up to show it
                debug_log.info(f"  -> widget above viewport, scrolling to y={widget_top}", category="chat_log")
                self.scroll_to(y=widget_top, animate=False)
            else:
                # Widget is below viewport - scroll down so bottom of widget
                # is at bottom of effective viewport (above indicator)
                target_y = widget_bottom - effective_viewport
                debug_log.info(f"  -> widget below viewport, scrolling to y={target_y}", category="chat_log")
                self.scroll_to(y=target_y, animate=False)
        else:
            # Widget doesn't fit - scroll so top of widget is at top of viewport
            debug_log.info(f"  -> widget too tall, scrolling to y={widget_top}", category="chat_log")
            self.scroll_to(y=widget_top, animate=False)

        # After scrolling, check if we're at the bottom
        self.call_later(self._check_at_bottom)

    def scroll_to_widget_at_top(self, widget) -> None:
        """Scroll so the widget is at the top of the viewport.

        Unlike scroll_to_widget_and_check_follow, this always scrolls to put
        the widget at the top, even if it's already partially visible.
        Useful for exchange nodes where we want the first turn at the top.
        """
        from core.debug_log import debug_log
        # Use virtual_region which is relative to the container's content, not the viewport
        # widget.region is relative to screen and changes with scroll position
        widget_top = widget.virtual_region.y
        # Account for container's content offset (padding/border at top)
        # The virtual_region.y includes the content offset, so we subtract it to get
        # the widget to appear at the top of the visible content area
        content_offset_y = self.content_offset.y if hasattr(self, 'content_offset') else 0
        adjusted_y = max(0, widget_top - content_offset_y)
        debug_log.info(
            f"scroll_to_widget_at_top: widget={widget}, virtual_region={widget.virtual_region}, "
            f"content_offset_y={content_offset_y}, current_scroll_y={self.scroll_y}, "
            f"scrolling to y={adjusted_y} (widget_top={widget_top} - offset={content_offset_y})",
            category="chat_log"
        )
        self.scroll_to(y=adjusted_y, animate=False)
        self.call_later(self._check_at_bottom)

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

        # Buffer the text instead of immediately refreshing
        self._pending_text += text

        # Start a timer to flush if not already running
        if self._stream_update_timer is None:
            self._stream_update_timer = self.set_timer(
                self.STREAM_UPDATE_INTERVAL,
                self._flush_pending_text
            )

    def _flush_pending_text(self) -> None:
        """Flush buffered streaming text to the widget in a single batch update."""
        self._stream_update_timer = None

        if not self._pending_text:
            return

        text_to_append = self._pending_text
        self._pending_text = ""

        if self._current_assistant_message:
            # Use batch_update to coalesce all refreshes into one
            with self.app.batch_update():
                self._current_assistant_message.append_text(text_to_append, refresh=True)
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
        if self._stream_update_timer is not None:
            self._stream_update_timer.stop()
            self._stream_update_timer = None
        if self._pending_text and self._current_assistant_message:
            self._current_assistant_message.append_text(self._pending_text, refresh=False)
            self._pending_text = ""

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
        # Cancel any pending stream update
        if self._stream_update_timer is not None:
            self._stream_update_timer.stop()
            self._stream_update_timer = None
        self._pending_text = ""

        for child in list(self.children):
            child.remove()
        self._turn_counter = 0
        self._current_assistant_message = None

    def highlight_tool(self, tool_use_id: str) -> None:
        """Highlight a tool use and its result by tool_use_id, scrolling to it."""
        from core.debug_log import debug_log
        debug_log.info(f"highlight_tool: looking for tool_use_id={tool_use_id}", category="chat_log")

        # First clear any existing highlights
        self.clear_highlights()

        # Find and highlight the matching widgets
        scrolled = False
        found_use = False
        found_result = False
        for child in self.children:
            if isinstance(child, ToolUseWidget):
                debug_log.debug(f"  checking ToolUseWidget: tool_use_id={child.tool_use_id}", category="chat_log")
                if child.tool_use_id == tool_use_id:
                    child.add_class("highlighted")
                    found_use = True
                    if not scrolled:
                        self.scroll_to_widget_and_check_follow(child)
                        scrolled = True
            elif isinstance(child, ToolResultWidget):
                debug_log.debug(f"  checking ToolResultWidget: tool_use_id={child.tool_use_id}", category="chat_log")
                if child.tool_use_id == tool_use_id:
                    child.add_class("highlighted")
                    found_result = True

        if found_use or found_result:
            debug_log.info(f"highlight_tool: found use={found_use} result={found_result}, scrolled={scrolled}", category="chat_log")
        else:
            debug_log.warning(f"highlight_tool: tool_use_id={tool_use_id} NOT FOUND in {len(list(self.children))} children", category="chat_log")

    def highlight_text_block(self, turn_id: int, block_idx: int) -> None:
        """Highlight a text block by turn_id and block_idx, scrolling to it."""
        from core.debug_log import debug_log
        debug_log.info(f"highlight_text_block: looking for turn_id={turn_id}, block_idx={block_idx}", category="chat_log")

        # First clear any existing highlights
        self.clear_highlights()

        # Find and highlight the matching widget
        found = False
        for child in self.children:
            if isinstance(child, MessageWidget):
                debug_log.debug(f"  checking MessageWidget: turn_id={child.turn_id}, block_idx={child.block_idx}", category="chat_log")
                if child.turn_id == turn_id and child.block_idx == block_idx:
                    child.add_class("highlighted")
                    self.scroll_to_widget_and_check_follow(child)
                    found = True
                    debug_log.info(f"  -> FOUND and highlighted!", category="chat_log")
                    break
        if not found:
            debug_log.warning(f"  -> NOT FOUND!", category="chat_log")

    def highlight_turn(self, turn_id: int, scroll_to_top: bool = False) -> None:
        """Highlight a turn by turn_id, scrolling to it.

        Args:
            turn_id: The 1-indexed turn ID to highlight
            scroll_to_top: If True, always scroll so turn is at top of viewport.
                          If False (default), use smart scroll that minimizes movement.
        """
        from core.debug_log import debug_log
        debug_log.info(f"highlight_turn: looking for turn_id={turn_id}, scroll_to_top={scroll_to_top}", category="chat_log")

        self.clear_highlights()

        # Find and highlight the first widget with matching turn_id
        for child in self.children:
            if hasattr(child, 'turn_id') and child.turn_id == turn_id:
                child.add_class("highlighted")
                if scroll_to_top:
                    self.scroll_to_widget_at_top(child)
                else:
                    self.scroll_to_widget_and_check_follow(child)
                debug_log.info(f"highlight_turn: found and highlighted turn_id={turn_id}", category="chat_log")
                return
        debug_log.warning(f"highlight_turn: turn_id={turn_id} NOT FOUND", category="chat_log")

    def clear_highlights(self) -> None:
        """Remove all highlights from tools and messages."""
        for child in self.children:
            if isinstance(child, (ToolUseWidget, ToolResultWidget, MessageWidget)):
                child.remove_class("highlighted")

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

    def load_history(self, messages: list, session: Session | None = None) -> None:
        """Load message history from a list of Message objects.

        If session is provided, also reconstructs fork, merge, and link markers from
        the session's children and links lists.

        Uses HistoryLoader to transform messages into render instructions, then
        interprets those instructions to create and mount widgets.
        """
        loader = HistoryLoader()
        result = loader.load(messages, session=session, start_turn_id=self._turn_counter)

        for instr in result.instructions:
            widget = self._instruction_to_widget(instr)
            if widget:
                self.mount(widget)

        self._turn_counter = result.final_turn_id
        self.scroll_end(animate=False)

    def _instruction_to_widget(self, instr):
        """Convert a render instruction to a widget.

        This method bridges the data layer (instructions) with the UI layer (widgets).
        """
        if isinstance(instr, RenderMessage):
            return MessageWidget(
                instr.role, instr.text, turn_id=instr.turn_id, block_idx=instr.block_idx
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
        for child in self.children:
            if isinstance(child, WithWidget) and child.child_session_id == child_session_id:
                return child
        return None

    def filter_by_turns(self, turn_ids: list[int], show_all: bool = False) -> None:
        """Show only specified turns, or all if show_all is True.

        DEPRECATED: Use set_turn_context_modes instead for visual indication without hiding.
        """
        for child in self.children:
            if isinstance(child, (MessageWidget, ToolUseWidget, ToolResultWidget, InterruptionMarkerWidget, WithWidget, WithResultWidget, ForkMarker, MergeMarker, LinkMarker, ArchiveMarker)):
                if show_all or child.turn_id in turn_ids:
                    child.remove_class("hidden")
                else:
                    child.add_class("hidden")
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
        context_classes = ("context-copy", "context-compress", "context-drop")

        for child in self.children:
            if isinstance(child, (MessageWidget, ToolUseWidget, ToolResultWidget, InterruptionMarkerWidget, WithWidget, WithResultWidget, ForkMarker, MergeMarker, LinkMarker, ArchiveMarker)):
                # Remove any existing context classes
                for cls in context_classes:
                    child.remove_class(cls)
                # Remove hidden class - we show everything now
                child.remove_class("hidden")

                # Get mode for this turn (default to no visual if not specified)
                mode = turn_modes.get(child.turn_id, None)
                if mode == "COPY":
                    child.add_class("context-copy")
                elif mode in ("COMPRESS", "SUMMARIZE"):
                    child.add_class("context-compress")
                elif mode == "DROP":
                    child.add_class("context-drop")
                # If mode is None, no context class is applied (normal appearance)

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
        for child in self.children:
            if isinstance(child, ForkMarker) and child.child_session_id == child_session_id:
                return child
        return None

    def find_merge_marker(self, child_session_id: str) -> MergeMarker | None:
        """Find a MergeMarker by its child session ID."""
        for child in self.children:
            if isinstance(child, MergeMarker) and child.child_session_id == child_session_id:
                return child
        return None

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
        for child in self.children:
            if isinstance(child, LinkMarker) and child.linked_session_id == linked_session_id:
                return child
        return None

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
        for child in self.children:
            if isinstance(child, ArchiveMarker) and child.archive_block.archive_id == archive_id:
                return child
        return None

    def remove_archive_marker(self, archive_id: str) -> bool:
        """Remove an archive marker by its archive ID.

        Returns True if the marker was found and removed, False otherwise.
        """
        marker = self.find_archive_marker(archive_id)
        if marker:
            marker.remove()
            return True
        return False
