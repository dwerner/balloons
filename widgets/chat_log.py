import json
import difflib
from pathlib import Path

from textual.widgets import Static
from textual.containers import VerticalScroll
from rich.markdown import Markdown
from rich.console import RenderableType, Group
from rich.text import Text
from rich.syntax import Syntax
from rich.panel import Panel

from .with_widget import WithWidget
from .with_result_widget import WithResultWidget
from models import TextBlock, ToolUseBlock, ToolResultBlock


def _format_edit_as_diff(tool_input: dict, language: str = "python") -> tuple[str, Text]:
    """Format an Edit tool use as a unified diff with syntax highlighting and colored backgrounds.

    Returns (file_path, rich_text) for display.
    """
    file_path = tool_input.get("file_path", "unknown")
    old_string = tool_input.get("old_string", "")
    new_string = tool_input.get("new_string", "")

    # Generate unified diff with keepends to preserve line structure
    old_lines = old_string.splitlines(keepends=True)
    new_lines = new_string.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{Path(file_path).name}",
        tofile=f"b/{Path(file_path).name}",
    ))

    if not diff:
        # If no diff (strings are equal), show simple message
        return file_path, Text("(no changes)")

    # Build rich text with syntax highlighting and colored backgrounds
    result = Text()

    for line in diff:
        line_text = line.rstrip("\n\r")

        if line.startswith("+++") or line.startswith("---"):
            # Header lines - bold cyan
            result.append(line_text + "\n", style="bold cyan")
        elif line.startswith("@@"):
            # Hunk headers - magenta
            result.append(line_text + "\n", style="magenta")
        elif line.startswith("+"):
            # Added lines - syntax highlight with green background
            code = line_text[1:]  # Strip the + prefix
            result.append("+", style="bold green on #1a3a1a")
            # Get syntax-highlighted text and append it
            syntax = Syntax(code, language, theme="monokai", background_color="#1a3a1a")
            highlighted = syntax.highlight(code)
            # Remove trailing newline from highlight output
            highlighted.rstrip()
            result.append_text(highlighted)
            result.append("\n")
        elif line.startswith("-"):
            # Removed lines - syntax highlight with red background
            code = line_text[1:]  # Strip the - prefix
            result.append("-", style="bold red on #3a1a1a")
            syntax = Syntax(code, language, theme="monokai", background_color="#3a1a1a")
            highlighted = syntax.highlight(code)
            highlighted.rstrip()
            result.append_text(highlighted)
            result.append("\n")
        else:
            # Context lines - syntax highlight with no special background
            code = line_text[1:] if line_text.startswith(" ") else line_text
            result.append(" ", style="dim")
            syntax = Syntax(code, language, theme="monokai")
            highlighted = syntax.highlight(code)
            highlighted.rstrip()
            result.append_text(highlighted)
            result.append("\n")

    return file_path, result


def _guess_language(file_path: str) -> str:
    """Guess language from file extension for syntax highlighting."""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".go": "go",
        ".rb": "ruby",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".css": "css",
        ".html": "html",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".sh": "bash",
        ".bash": "bash",
        ".sql": "sql",
    }
    ext = Path(file_path).suffix.lower()
    return ext_map.get(ext, "text")


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
    """

    def __init__(self, tool_name: str, content: RenderableType, turn_id: int = 0, tool_use_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self._content = content
        self.turn_id = turn_id
        self.tool_use_id = tool_use_id

    def render(self) -> RenderableType:
        # Content can be Markdown, Text, or other Rich renderables
        if isinstance(self._content, str):
            return Markdown(self._content, code_theme="monokai")
        return self._content


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
    """

    def __init__(self, content: RenderableType, turn_id: int = 0, tool_use_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self._content = content
        self.turn_id = turn_id
        self.tool_use_id = tool_use_id

    def render(self) -> RenderableType:
        # Content can be Markdown, Text, or other Rich renderables
        if isinstance(self._content, str):
            return Markdown(self._content, code_theme="monokai")
        return self._content


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

    def compose(self):
        self._header = SessionHeader("", id="session-header")
        yield self._header

    def set_session_title(self, title: str) -> None:
        """Set the session title displayed in the header."""
        if self._header:
            self._header.set_title(title)

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

    def add_tool_use(self, tool_name: str, content: RenderableType, tool_use_id: str = "") -> ToolUseWidget:
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

        widget = ToolUseWidget(tool_name, content, turn_id=turn_id, tool_use_id=tool_use_id)
        self.mount(widget)
        self.scroll_end(animate=False)
        return widget

    def add_tool_result(self, content: RenderableType, tool_use_id: str = "") -> ToolResultWidget:
        """Add a tool result widget to the log."""
        turn_id = self._turn_counter
        widget = ToolResultWidget(content, turn_id=turn_id, tool_use_id=tool_use_id)
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

    def highlight_tool(self, tool_use_id: str) -> None:
        """Highlight a tool use and its result by tool_use_id, scrolling to it."""
        # First clear any existing highlights
        for child in self.children:
            if isinstance(child, (ToolUseWidget, ToolResultWidget)):
                child.remove_class("highlighted")

        # Find and highlight the matching widgets
        for child in self.children:
            if isinstance(child, ToolUseWidget) and child.tool_use_id == tool_use_id:
                child.add_class("highlighted")
                child.scroll_visible(animate=True)
            elif isinstance(child, ToolResultWidget) and child.tool_use_id == tool_use_id:
                child.add_class("highlighted")

    def clear_highlights(self) -> None:
        """Remove all tool highlights."""
        for child in self.children:
            if isinstance(child, (ToolUseWidget, ToolResultWidget)):
                child.remove_class("highlighted")

    def _format_tool_use(self, block: ToolUseBlock) -> RenderableType:
        """Format a tool use block for display."""
        tool_name = block.name
        tool_input = block.input

        if tool_name == "Edit":
            # Show as diff with colored backgrounds
            file_path = tool_input.get("file_path", "unknown")
            _, diff_text = _format_edit_as_diff(tool_input, _guess_language(file_path))
            header = Text()
            header.append("Edit ", style="bold")
            header.append(file_path, style="cyan")
            header.append("\n")
            return Group(header, diff_text)

        elif tool_name == "Read":
            file_path = tool_input.get("file_path", "unknown")
            offset = tool_input.get("offset", "")
            limit = tool_input.get("limit", "")
            range_info = ""
            if offset or limit:
                range_info = f" (lines {offset or 1}-{(offset or 0) + (limit or 'end')})"
            return f"**Read** `{file_path}`{range_info}"

        elif tool_name == "Write":
            file_path = tool_input.get("file_path", "unknown")
            content = tool_input.get("content", "")
            lang = _guess_language(file_path)
            preview = content[:500]
            if len(content) > 500:
                preview += "\n... [truncated]"
            return f"**Write** `{file_path}`\n```{lang}\n{preview}\n```"

        elif tool_name == "Bash":
            cmd = tool_input.get("command", "")
            desc = tool_input.get("description", "")
            header = f"**Bash**"
            if desc:
                header += f" - {desc}"
            return f"{header}\n```bash\n{cmd}\n```"

        elif tool_name == "Grep":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", ".")
            return f"**Grep** `{pattern}` in `{path}`"

        elif tool_name == "Glob":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", ".")
            return f"**Glob** `{pattern}` in `{path}`"

        else:
            # Default: show as JSON
            input_str = json.dumps(tool_input, indent=2)
            return f"**{tool_name}**\n```json\n{input_str}\n```"

    def load_history(self, messages: list) -> None:
        """Load message history from a list of Message objects."""
        for msg in messages:
            self._turn_counter += 1
            turn_id = self._turn_counter

            # Render content blocks properly if available
            if msg.content_blocks:
                # Collect consecutive text blocks, flush when hitting tool use/result
                text_buffer = []

                def flush_text():
                    if text_buffer:
                        combined = "\n\n".join(text_buffer)
                        widget = MessageWidget(msg.role, combined, turn_id=turn_id)
                        self.mount(widget)
                        text_buffer.clear()

                for block in msg.content_blocks:
                    if isinstance(block, TextBlock):
                        if block.text.strip():
                            text_buffer.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        flush_text()
                        content = self._format_tool_use(block)
                        widget = ToolUseWidget(block.name, content, turn_id=turn_id, tool_use_id=block.id)
                        self.mount(widget)
                    elif isinstance(block, ToolResultBlock):
                        # Truncate long results for display
                        result = block.content
                        if len(result) > 2000:
                            result = result[:2000] + "\n... [truncated]"
                        content = f"```\n{result}\n```"
                        widget = ToolResultWidget(content, turn_id=turn_id, tool_use_id=block.tool_use_id)
                        self.mount(widget)

                # Flush any remaining text
                flush_text()
            else:
                # Fallback: just use msg.content
                widget = MessageWidget(msg.role, msg.content, turn_id=turn_id)
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
