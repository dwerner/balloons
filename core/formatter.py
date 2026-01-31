"""Tool formatting for Balloons.

Extracts tool use and result formatting from app.py and chat_log.py
into a GUI-independent module. Returns Rich renderables.
"""

import difflib
import json
from pathlib import Path
from typing import Any

from rich.console import RenderableType, Group
from rich.text import Text
from rich.syntax import Syntax
from rich.markdown import Markdown

from models import ToolUseEvent, ToolResultEvent, ToolUseBlock, ToolResultBlock


def guess_language(file_path: str) -> str:
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


def format_edit_as_diff(tool_input: dict, language: str = "python") -> tuple[str, Text]:
    """Format an Edit tool use as a unified diff with syntax highlighting.

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
            syntax = Syntax(code, language, theme="monokai", background_color="#1a3a1a")
            highlighted = syntax.highlight(code)
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


class Formatter:
    """Format tool uses and results for display.

    Usage:
        formatter = Formatter()
        content = formatter.format_tool_use(event)
        result = formatter.format_tool_result(event, last_tool_use)
    """

    def format_tool_use(self, event: ToolUseEvent) -> RenderableType:
        """Format a tool use event for display.

        Args:
            event: ToolUseEvent from stream

        Returns:
            Rich renderable for display
        """
        tool = event.tool_name
        inp = event.tool_input
        return self._format_tool_input(tool, inp)

    def format_tool_use_block(self, block: ToolUseBlock) -> RenderableType:
        """Format a tool use block for display (from session history).

        Args:
            block: ToolUseBlock from message content

        Returns:
            Rich renderable for display
        """
        return self._format_tool_input(block.name, block.input)

    def _format_tool_input(self, tool_name: str, tool_input: dict) -> RenderableType:
        """Internal: format tool name and input."""
        if tool_name == "Edit":
            file_path = tool_input.get("file_path", "")
            _, diff_text = format_edit_as_diff(tool_input, guess_language(file_path))
            header = Text()
            header.append("Edit ", style="bold")
            header.append(file_path, style="cyan")
            header.append("\n")
            return Group(header, diff_text)

        elif tool_name == "Write":
            file_path = tool_input.get("file_path", "")
            content = tool_input.get("content", "")
            lang = guess_language(file_path)
            if len(content) > 500:
                preview = content[:500] + "\n... [truncated - click to expand]"
                truncated = f"**Write** `{file_path}`\n```{lang}\n{preview}\n```"
                full = f"**Write** `{file_path}`\n```{lang}\n{content}\n```"
                return (truncated, full)  # Return tuple when truncated
            return f"**Write** `{file_path}`\n```{lang}\n{content}\n```"

        elif tool_name == "Read":
            file_path = tool_input.get("file_path", "")
            offset = tool_input.get("offset", "")
            limit = tool_input.get("limit", "")
            range_info = ""
            if offset or limit:
                range_info = f" (lines {offset or 1}-{(offset or 0) + (limit or 'end')})"
            return f"**Read** `{file_path}`{range_info}"

        elif tool_name == "Bash":
            cmd = tool_input.get("command", "")
            desc = tool_input.get("description", "")
            header = "**Bash**"
            if desc:
                header += f" - {desc}"
            return f"{header}\n```bash\n{cmd}\n```"

        elif tool_name == "Glob":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", ".")
            return f"**Glob** `{pattern}` in `{path}`"

        elif tool_name == "Grep":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", ".")
            return f"**Grep** `{pattern}` in `{path}`"

        else:
            input_str = json.dumps(tool_input, indent=2)[:300]
            return f"**{tool_name}**\n```json\n{input_str}\n```"

    def format_tool_result(
        self,
        event: ToolResultEvent,
        last_tool_use: ToolUseBlock | None = None,
    ) -> RenderableType:
        """Format a tool result for display.

        Args:
            event: ToolResultEvent from stream
            last_tool_use: The preceding tool use block (for context)

        Returns:
            Rich renderable for display, or empty string if nothing to show
        """
        result = event.result
        if not result:
            return ""

        # Special handling for Read results
        if last_tool_use and last_tool_use.name == "Read":
            return self._format_read_result(result, last_tool_use.input)

        # Default: truncate and show as code block
        if len(result) > 500:
            truncated = f"```\n{result[:500]}... [truncated - click to expand]\n```"
            full = f"```\n{result}\n```"
            return (truncated, full)  # Return tuple when truncated
        return f"```\n{result}\n```"

    def format_tool_result_block(
        self, block: ToolResultBlock
    ) -> RenderableType | tuple[RenderableType, RenderableType]:
        """Format a tool result block for display (from session history).

        Args:
            block: ToolResultBlock from message content

        Returns:
            Rich renderable for display, or tuple of (truncated, full) if truncated
        """
        result = block.content
        if len(result) > 2000:
            truncated = f"```\n{result[:2000]}\n... [truncated - click to expand]\n```"
            full = f"```\n{result}\n```"
            return (truncated, full)
        return f"```\n{result}\n```"

    def _format_read_result(self, result: str, tool_input: dict) -> RenderableType:
        """Format Read tool result with syntax highlighting.

        Args:
            result: Raw Read output (with line numbers)
            tool_input: The Read tool input dict

        Returns:
            Rich Text with syntax highlighting
        """
        file_path = tool_input.get("file_path", "")
        language = guess_language(file_path)

        lines = result.split("\n")
        formatted = Text()

        for line in lines[:100]:  # Limit to first 100 lines
            # Parse line number prefix: spaces + number + tab + content
            if "→" in line:
                prefix, content = line.split("→", 1)
                line_num = prefix.strip()
                # Format line number in dim style
                formatted.append(f"{line_num:>5} ", style="dim")
                # Apply syntax highlighting to content
                syntax = Syntax(content, language, theme="monokai")
                highlighted = syntax.highlight(content)
                highlighted.rstrip()
                formatted.append_text(highlighted)
                formatted.append("\n")
            else:
                formatted.append(line + "\n", style="dim")

        if len(lines) > 100:
            formatted.append(f"... ({len(lines) - 100} more lines)", style="dim italic")

        return formatted
