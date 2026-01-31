from textual.widgets import Static
from textual.containers import VerticalScroll
from rich.markdown import Markdown
from rich.console import RenderableType
from rich.text import Text

from .with_widget import WithWidget
from .with_result_widget import WithResultWidget


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
    """

    def __init__(self, tool_name: str, content: str, turn_id: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self._content = content
        self.turn_id = turn_id

    def render(self) -> RenderableType:
        return Markdown(self._content, code_theme="monokai")


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
    """

    def __init__(self, content: str, turn_id: int = 0, **kwargs):
        super().__init__(**kwargs)
        self._content = content
        self.turn_id = turn_id

    def render(self) -> RenderableType:
        return Markdown(self._content, code_theme="monokai")


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
    """

    def __init__(self, role: str, content: str = "", streaming: bool = False, turn_id: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self._content = content
        self._streaming = streaming
        self.turn_id = turn_id
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

    @property
    def content(self) -> str:
        return self._content


class ChatLog(VerticalScroll):
    """Scrolling container for chat messages."""

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

    def add_user_message(self, content: str) -> MessageWidget:
        """Add a user message to the log."""
        self._turn_counter += 1
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
        self.scroll_end(animate=False)
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
        self.scroll_end(animate=False)

    def add_tool_use(self, tool_name: str, content: str) -> ToolUseWidget:
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

        widget = ToolUseWidget(tool_name, content, turn_id=turn_id)
        self.mount(widget)
        self.scroll_end(animate=False)
        return widget

    def add_tool_result(self, content: str) -> ToolResultWidget:
        """Add a tool result widget to the log."""
        turn_id = self._turn_counter
        widget = ToolResultWidget(content, turn_id=turn_id)
        self.mount(widget)
        self.scroll_end(animate=False)
        return widget

    def finish_current_message(self) -> str:
        """Mark streaming complete and return combined text from all assistant messages in this turn.

        Since text may be split across multiple MessageWidgets (due to tool uses
        in between), we collect content from all assistant messages in the current turn.
        """
        # Finish any active streaming message
        if self._current_assistant_message:
            self._current_assistant_message.remove_class("streaming")
            self._current_assistant_message.finish_streaming()
            self._current_assistant_message = None

        # Collect text from all assistant messages in current turn
        turn_id = self._turn_counter
        content_parts = []
        for child in self.children:
            if isinstance(child, MessageWidget) and child.role == "assistant" and child.turn_id == turn_id:
                if child.content.strip():
                    content_parts.append(child.content)

        return "\n\n".join(content_parts)

    def clear(self) -> None:
        """Clear all messages and reset counter."""
        for child in list(self.children):
            child.remove()
        self._turn_counter = 0
        self._current_assistant_message = None

    def load_history(self, messages: list) -> None:
        """Load message history from a list of Message objects."""
        for msg in messages:
            self._turn_counter += 1
            widget = MessageWidget(msg.role, msg.content, turn_id=self._turn_counter)
            self.mount(widget)
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
        self.scroll_end(animate=False)
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
        self.scroll_end(animate=False)
        return widget

    def find_with_widget(self, child_session_id: str) -> WithWidget | None:
        """Find a WithWidget by its child session ID."""
        for child in self.children:
            if isinstance(child, WithWidget) and child.child_session_id == child_session_id:
                return child
        return None

    def filter_by_turns(self, turn_ids: list[int], show_all: bool = False) -> None:
        """Show only specified turns, or all if show_all is True."""
        for child in self.children:
            if isinstance(child, (MessageWidget, ToolUseWidget, ToolResultWidget, WithWidget, WithResultWidget)):
                if show_all or child.turn_id in turn_ids:
                    child.remove_class("hidden")
                else:
                    child.add_class("hidden")
        self.scroll_end(animate=False)
