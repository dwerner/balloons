from textual.widgets import Static
from textual.containers import VerticalScroll
from rich.markdown import Markdown
from rich.console import RenderableType
from rich.text import Text


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
        """Append text to the current assistant message."""
        if self._current_assistant_message:
            self._current_assistant_message.append_text(text)
            self.scroll_end(animate=False)

    def add_tool_use(self, tool_name: str, content: str) -> ToolUseWidget:
        """Add a tool use widget to the log, before any streaming message."""
        turn_id = self._turn_counter
        widget = ToolUseWidget(tool_name, content, turn_id=turn_id)
        # Insert before streaming message if one exists
        if self._current_assistant_message:
            self.mount(widget, before=self._current_assistant_message)
        else:
            self.mount(widget)
        self.scroll_end(animate=False)
        return widget

    def add_tool_result(self, content: str) -> ToolResultWidget:
        """Add a tool result widget to the log, before any streaming message."""
        turn_id = self._turn_counter
        widget = ToolResultWidget(content, turn_id=turn_id)
        # Insert before streaming message if one exists
        if self._current_assistant_message:
            self.mount(widget, before=self._current_assistant_message)
        else:
            self.mount(widget)
        self.scroll_end(animate=False)
        return widget

    def finish_current_message(self) -> str:
        """Mark the current assistant message as complete and return its content."""
        content = ""
        if self._current_assistant_message:
            self._current_assistant_message.remove_class("streaming")
            self._current_assistant_message.finish_streaming()  # Re-render with markdown
            content = self._current_assistant_message.content
            self._current_assistant_message = None
        return content

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

    def filter_by_turns(self, turn_ids: list[int], show_all: bool = False) -> None:
        """Show only specified turns, or all if show_all is True."""
        for child in self.children:
            if isinstance(child, (MessageWidget, ToolUseWidget, ToolResultWidget)):
                if show_all or child.turn_id in turn_ids:
                    child.remove_class("hidden")
                else:
                    child.add_class("hidden")
        self.scroll_end(animate=False)
