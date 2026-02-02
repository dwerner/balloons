import json
from pathlib import Path

from textual.widgets import Static
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.message import Message
from textual.events import Click
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
from models import TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, LinkBlock
from core.formatter import format_edit_as_diff, guess_language
from session import Session

# Re-export for backwards compatibility (used by app.py imports)
_format_edit_as_diff = format_edit_as_diff
_guess_language = guess_language


class ToolUseWidget(Static):
    """A tool use display in the chat log."""

    DEFAULT_CSS = """
    ToolUseWidget {
        padding: 0 1;
        margin: 0 0 0 2;
        background: #1e1e1e;
        border-left: thick $success;
    }

    ToolUseWidget.hidden {
        display: none;
    }

    ToolUseWidget.highlighted {
        background: #2a2a2a;
        border: wide $warning;
    }

    ToolUseWidget.expandable {
        border-left: thick $success;
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
        if full_content is not None:
            self.add_class("expandable")
        if streaming:
            self.add_class("streaming")

    def render(self) -> RenderableType:
        if self._streaming:
            # Show tool name + partial JSON with cursor
            text = Text()
            text.append(f"[{self.tool_name}] ", style="bold cyan")
            text.append(self._partial_json, style="dim")
            text.append("▌", style="bold")
            return text

        content = self._full_content if self._expanded and self._full_content else self._content
        # Content can be Markdown, Text, or other Rich renderables
        if isinstance(content, str):
            return Markdown(content, code_theme="monokai")
        return content

    def append_input(self, partial_json: str) -> None:
        """Append partial JSON to streaming tool use."""
        self._partial_json += partial_json
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
                if isinstance(ancestor, ChatLog):
                    ancestor.post_message(ChatLog.ContextModeToggleRequested(self.turn_id))
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
        margin: 0 0 1 4;
        background: #1a1a1a;
        border-left: thick $primary;
        max-height: 15;
        overflow-y: auto;
    }

    ToolResultWidget.hidden {
        display: none;
    }

    ToolResultWidget.highlighted {
        background: #2a2a2a;
        border: wide $warning;
    }

    ToolResultWidget.expandable {
        border-left: thick $primary;
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
                if isinstance(ancestor, ChatLog):
                    ancestor.post_message(ChatLog.ContextModeToggleRequested(self.turn_id))
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
        turn_id: int = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.reason = reason
        self.partial_tool_name = partial_tool_name
        self.details = details
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

        return Text(msg, style="italic dim")


class MessageWidget(Static):
    """A single message in the chat log."""

    DEFAULT_CSS = """
    MessageWidget {
        padding: 0 1;
        margin: 0 0 1 0;
    }

    MessageWidget.user {
        background: #1a1a1a;
        color: $text-muted;
    }

    MessageWidget.assistant {
        background: #1e1e1e;
        color: $text;
    }

    MessageWidget:focus {
        background: #252525;
    }

    MessageWidget.user:focus {
        background: #1f1f1f;
    }

    MessageWidget.assistant:focus {
        background: #232323;
    }

    MessageWidget.streaming {
        border-left: thick $accent;
    }

    MessageWidget.hidden {
        display: none;
    }

    MessageWidget.highlighted {
        background: #2a3a2a;
        border: wide $warning;
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
        background: #222222;
    }

    MessageWidget.assistant:hover {
        background: #262626;
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

    def append_text(self, text: str) -> None:
        """Append text to the message content."""
        self._content += text
        self.refresh()

    def finish_streaming(self) -> None:
        """Mark streaming as complete and re-render with markdown."""
        self._streaming = False
        self.refresh()

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
                if isinstance(ancestor, ChatLog):
                    ancestor.post_message(ChatLog.ContextModeToggleRequested(self.turn_id))
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
        if self._new_message_count == 0:
            self.update("↓ More below ↓")
            self.remove_class("new-messages")
        self.add_class("visible")

    def show_new_messages(self) -> None:
        """Show with new message styling."""
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


class ChatLog(VerticalScroll):
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

    following: reactive[bool] = reactive(True)  # True when auto-scrolling to new content

    DEFAULT_CSS = """
    ChatLog {
        height: 1fr;
        background: $background;
        padding: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_assistant_message: MessageWidget | None = None
        self._turn_counter = 0
        self._header: SessionHeader | None = None

    def watch_following(self, following: bool) -> None:
        """Post a message when following state changes."""
        if self.is_mounted:
            self.post_message(self.FollowingChanged(following))
            # Clear new messages flag when we start following again
            if following:
                self._has_new_messages = False

    def _notify_new_content(self) -> None:
        """Called when new content is added - posts message if not following."""
        if not self.following:
            self.post_message(self.NewContentWhileNotFollowing())

    def compose(self):
        self._header = SessionHeader("", id="session-header")
        yield self._header

    def _check_at_bottom(self) -> None:
        """Check if we're at the bottom and update following state."""
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
            self.following = at_bottom

    def on_mouse_scroll_down(self, event) -> None:
        """Track scrolling down (toward bottom)."""
        self._check_at_bottom()

    def on_mouse_scroll_up(self, event) -> None:
        """Track scrolling up (toward top)."""
        self._check_at_bottom()

    def _smart_scroll(self) -> None:
        """Scroll to end only if user hasn't scrolled up."""
        if self.following:
            # Defer scroll until after layout refresh so scroll_end knows the true max_scroll_y
            self.call_after_refresh(self._scroll_end_and_verify)

    def _scroll_end_and_verify(self) -> None:
        """Scroll to end and re-check if we're actually at the bottom."""
        self.scroll_end(animate=False)
        # Re-check after scroll in case content grew during the frame
        self.call_later(self._check_at_bottom)

    def scroll_to_turn(self, turn_id: int) -> bool:
        """Scroll to a turn by ID and disable follow mode if not at the bottom.

        Returns True if the turn was found and scrolled to, False otherwise.
        """
        for child in self.children:
            if hasattr(child, 'turn_id') and child.turn_id == turn_id:
                child.scroll_visible(animate=True)
                # After scrolling, check if we're at the bottom
                # Use call_later to check after scroll animation starts
                self.call_later(self._check_at_bottom)
                return True
        return False

    def scroll_to_widget_and_check_follow(self, widget) -> None:
        """Scroll to a specific widget and disable follow mode if not at the bottom."""
        widget.scroll_visible(animate=True)
        # After scrolling, check if we're at the bottom
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
        """
        if not self._current_assistant_message:
            # Create a new streaming message for text after tool use
            widget = MessageWidget("assistant", "", streaming=True, turn_id=self._turn_counter)
            widget.add_class("streaming")
            self._current_assistant_message = widget
            self.mount(widget)

        self._current_assistant_message.append_text(text)
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
    ) -> ErrorMarkerWidget:
        """Add an error marker to the log (truncated response, etc.)."""
        turn_id = self._turn_counter
        widget = ErrorMarkerWidget(
            reason=reason,
            partial_tool_name=partial_tool_name,
            details=details,
            turn_id=turn_id,
        )
        self.mount(widget)
        self._smart_scroll()
        return widget

    def clear(self) -> None:
        """Clear all messages and reset counter."""
        for child in list(self.children):
            child.remove()
        self._turn_counter = 0
        self._current_assistant_message = None

    def highlight_tool(self, tool_use_id: str) -> None:
        """Highlight a tool use and its result by tool_use_id, scrolling to it."""
        # First clear any existing highlights
        self.clear_highlights()

        # Find and highlight the matching widgets
        scrolled = False
        for child in self.children:
            if isinstance(child, ToolUseWidget) and child.tool_use_id == tool_use_id:
                child.add_class("highlighted")
                if not scrolled:
                    self.scroll_to_widget_and_check_follow(child)
                    scrolled = True
            elif isinstance(child, ToolResultWidget) and child.tool_use_id == tool_use_id:
                child.add_class("highlighted")

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
        """
        # Build fork and merge points maps: turn_index -> list of child infos
        fork_points: dict[int, list[dict]] = {}
        merge_points: dict[int, list[dict]] = {}
        link_points: dict[int, list[dict]] = {}
        if session:
            for child in session.children:
                # Fork markers: all children have fork points
                fork_point = child.get("fork_point", -1)
                if fork_point >= 0:
                    fork_points.setdefault(fork_point, []).append(child)
                # Merge markers: only merged children
                if child.get("status") == "merged":
                    merge_point = child.get("merge_point", -1)
                    if merge_point >= 0:
                        merge_points.setdefault(merge_point, []).append(child)
            # Link markers
            for link in session.links:
                link_point = link.get("link_point", -1)
                if link_point >= 0:
                    link_points.setdefault(link_point, []).append(link)

        def mount_forks(fork_point_idx: int, turn_id: int) -> None:
            """Mount fork markers for a given fork point."""
            for child_info in fork_points.get(fork_point_idx, []):
                child_session = Session.load(child_info["session_id"])
                if child_session:
                    self.mount(ForkMarker(
                        prompt=child_info.get("prompt", ""),
                        child_session_id=child_session.id,
                        fork_name=child_info.get("name") or child_session.get_fork_display_name(),
                        status=child_info.get("status", "active"),
                        turn_id=turn_id,
                    ))

        def mount_merges(merge_point_idx: int, turn_id: int) -> None:
            """Mount merge markers for a given merge point."""
            for child_info in merge_points.get(merge_point_idx, []):
                child_session = Session.load(child_info["session_id"])
                if child_session:
                    self.mount(MergeMarker(
                        message=child_session.merge_message,
                        child_session_id=child_session.id,
                        fork_name=child_info.get("name") or child_session.get_fork_display_name(),
                        turn_id=turn_id,
                    ))

        def mount_links(link_point_idx: int, turn_id: int) -> None:
            """Mount link markers for a given link point."""
            for link_info in link_points.get(link_point_idx, []):
                linked_session_id = link_info.get("linked_session_id", "")
                linked_session = Session.load(linked_session_id)
                is_orphaned = link_info.get("is_orphaned", False)
                # Check if linked session exists
                if linked_session:
                    linked_name = linked_session.title or linked_session.fork_name or linked_session_id[:8]
                else:
                    linked_name = linked_session_id[:8] if linked_session_id else "[unknown]"
                    is_orphaned = True  # Session doesn't exist anymore
                self.mount(LinkMarker(
                    summary=link_info.get("summary", ""),
                    linked_session_id=linked_session_id,
                    linked_session_name=linked_name,
                    link_point=link_info.get("link_point", 0),
                    turn_id=turn_id,
                    is_orphaned=is_orphaned,
                ))

        for turn_idx, msg in enumerate(messages):
            self._turn_counter += 1
            turn_id = self._turn_counter

            # Render content blocks properly if available
            if msg.content_blocks:
                for block_idx, block in enumerate(msg.content_blocks):
                    if isinstance(block, TextBlock):
                        if block.text.strip():
                            widget = MessageWidget(
                                msg.role, block.text, turn_id=turn_id, block_idx=block_idx
                            )
                            self.mount(widget)
                    elif isinstance(block, ToolUseBlock):
                        formatted = self._format_tool_use(block)
                        if isinstance(formatted, tuple):
                            content, full_content = formatted
                        else:
                            content, full_content = formatted, None
                        widget = ToolUseWidget(
                            block.name, content, turn_id=turn_id,
                            tool_use_id=block.id, full_content=full_content
                        )
                        self.mount(widget)
                    elif isinstance(block, ToolResultBlock):
                        formatted = self._format_tool_result(block)
                        if isinstance(formatted, tuple):
                            content, full_content = formatted
                        else:
                            content, full_content = formatted, None
                        widget = ToolResultWidget(
                            content, turn_id=turn_id,
                            tool_use_id=block.tool_use_id, full_content=full_content
                        )
                        self.mount(widget)
                    elif isinstance(block, InterruptionBlock):
                        widget = InterruptionMarkerWidget(
                            reason=block.reason, turn_id=turn_id
                        )
                        self.mount(widget)
                    elif isinstance(block, ErrorBlock):
                        widget = ErrorMarkerWidget(
                            reason=block.reason,
                            partial_tool_name=block.partial_tool_name,
                            details=block.details,
                            turn_id=turn_id,
                        )
                        self.mount(widget)
                    elif isinstance(block, LinkBlock):
                        # Render LinkBlock as LinkMarker
                        linked_session = Session.load(block.linked_session_id)
                        is_orphaned = block.is_orphaned
                        if linked_session:
                            linked_name = linked_session.title or linked_session.fork_name or block.linked_session_id[:8]
                        else:
                            linked_name = block.linked_session_id[:8] if block.linked_session_id else "[unknown]"
                            is_orphaned = True
                        widget = LinkMarker(
                            summary=block.summary,
                            linked_session_id=block.linked_session_id,
                            linked_session_name=linked_name,
                            link_point=turn_idx,  # The turn index where this link exists
                            turn_id=turn_id,
                            is_orphaned=is_orphaned,
                        )
                        self.mount(widget)
            else:
                # Fallback: just use msg.content
                widget = MessageWidget(msg.role, msg.content, turn_id=turn_id)
                self.mount(widget)

            # Add any fork markers after this turn (forks start after the turn)
            mount_forks(turn_idx, turn_id)
            # Add any merge markers after this turn
            mount_merges(turn_idx, turn_id)
            # Add any link markers after this turn
            mount_links(turn_idx, turn_id)

        # Add any markers at the end (point == len(messages))
        mount_forks(len(messages), self._turn_counter)
        mount_merges(len(messages), self._turn_counter)
        mount_links(len(messages), self._turn_counter)

        self.scroll_end(animate=False)

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
            if isinstance(child, (MessageWidget, ToolUseWidget, ToolResultWidget, InterruptionMarkerWidget, WithWidget, WithResultWidget, ForkMarker, MergeMarker, LinkMarker)):
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
            if isinstance(child, (MessageWidget, ToolUseWidget, ToolResultWidget, InterruptionMarkerWidget, WithWidget, WithResultWidget, ForkMarker, MergeMarker, LinkMarker)):
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
