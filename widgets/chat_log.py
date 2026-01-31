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
from models import TextBlock, ToolUseBlock, ToolResultBlock
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
        background: #1a2a1a;
        border-left: thick $success;
    }

    ToolUseWidget.hidden {
        display: none;
    }

    ToolUseWidget.highlighted {
        background: #2a4a2a;
        border: wide $warning;
    }

    ToolUseWidget.expandable {
        border-left: thick $success;
    }

    ToolUseWidget.expanded {
        max-height: 10000;
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
        background: #2a3a2a;
    }
    """

    def __init__(
        self,
        tool_name: str,
        content: RenderableType,
        turn_id: int = 0,
        tool_use_id: str = "",
        full_content: RenderableType | None = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.tool_name = tool_name
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


class ToolResultWidget(Static):
    """A tool result display in the chat log."""

    DEFAULT_CSS = """
    ToolResultWidget {
        padding: 0 1;
        margin: 0 0 1 4;
        background: #1a1a2a;
        border-left: thick $primary;
        max-height: 15;
        overflow-y: auto;
    }

    ToolResultWidget.hidden {
        display: none;
    }

    ToolResultWidget.highlighted {
        background: #2a2a4a;
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
        background: #2a2a3a;
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


class MessageWidget(Static):
    """A single message in the chat log."""

    DEFAULT_CSS = """
    MessageWidget {
        padding: 0 1;
        margin: 0 0 1 0;
    }

    MessageWidget.user {
        background: $surface;
        color: $text-muted;
    }

    MessageWidget.assistant {
        background: $panel;
        color: $text;
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
        background: #2a3a3a;
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
            self.scroll_end(animate=False)

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
        return widget

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
        for child in self.children:
            if isinstance(child, ToolUseWidget) and child.tool_use_id == tool_use_id:
                child.add_class("highlighted")
                child.scroll_visible(animate=True)
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
                    child.scroll_visible(animate=True)
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

        If session is provided, also reconstructs merge markers from the
        session's children list.
        """
        # Build merge points map: turn_index -> child info
        merge_points: dict[int, dict] = {}
        if session:
            for child in session.children:
                if child.get("status") == "merged":
                    merge_point = child.get("merge_point", -1)
                    if merge_point >= 0:
                        merge_points[merge_point] = child

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
            else:
                # Fallback: just use msg.content
                widget = MessageWidget(msg.role, msg.content, turn_id=turn_id)
                self.mount(widget)

            # Check if there's a merge marker after this turn
            if turn_idx in merge_points:
                child_info = merge_points[turn_idx]
                child_session = Session.load(child_info["session_id"])
                if child_session:
                    self.mount(MergeMarker(
                        message=child_session.merge_message,
                        child_session_id=child_session.id,
                        fork_name=child_info.get("name") or child_session.get_fork_display_name(),
                        turn_id=turn_id,
                    ))

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
            if isinstance(child, (MessageWidget, ToolUseWidget, ToolResultWidget, WithWidget, WithResultWidget, ForkMarker, MergeMarker)):
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
            if isinstance(child, (MessageWidget, ToolUseWidget, ToolResultWidget, WithWidget, WithResultWidget, ForkMarker, MergeMarker)):
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
