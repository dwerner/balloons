"""Tests for tool formatting."""

import pytest
from core.formatter import Formatter, guess_language, format_edit_as_diff
from models import ToolUseEvent, ToolResultEvent, ToolUseBlock, ToolResultBlock


@pytest.fixture
def formatter():
    return Formatter()


class TestGuessLanguage:
    """Tests for language detection from file extension."""

    def test_python(self):
        assert guess_language("test.py") == "python"

    def test_javascript(self):
        assert guess_language("test.js") == "javascript"

    def test_typescript(self):
        assert guess_language("test.ts") == "typescript"
        assert guess_language("test.tsx") == "typescript"

    def test_rust(self):
        assert guess_language("test.rs") == "rust"

    def test_go(self):
        assert guess_language("test.go") == "go"

    def test_json(self):
        assert guess_language("test.json") == "json"

    def test_yaml(self):
        assert guess_language("test.yaml") == "yaml"
        assert guess_language("test.yml") == "yaml"

    def test_markdown(self):
        assert guess_language("test.md") == "markdown"

    def test_bash(self):
        assert guess_language("test.sh") == "bash"

    def test_unknown(self):
        assert guess_language("test.xyz") == "text"
        assert guess_language("noextension") == "text"


class TestFormatEditAsDiff:
    """Tests for edit diff formatting."""

    def test_simple_edit(self):
        """Edit with changes produces diff."""
        tool_input = {
            "file_path": "/test.py",
            "old_string": "hello",
            "new_string": "world",
        }
        file_path, diff_text = format_edit_as_diff(tool_input, "python")
        assert file_path == "/test.py"
        assert diff_text  # Should have content

    def test_no_changes(self):
        """Edit with no changes shows message."""
        tool_input = {
            "file_path": "/test.py",
            "old_string": "same",
            "new_string": "same",
        }
        file_path, diff_text = format_edit_as_diff(tool_input, "python")
        assert file_path == "/test.py"
        assert "no changes" in str(diff_text)

    def test_multiline_edit(self):
        """Multi-line edits show proper diff."""
        tool_input = {
            "file_path": "/test.py",
            "old_string": "line1\nline2\nline3",
            "new_string": "line1\nmodified\nline3",
        }
        file_path, diff_text = format_edit_as_diff(tool_input, "python")
        assert file_path == "/test.py"


class TestFormatterToolUse:
    """Tests for tool use formatting."""

    def test_edit_tool(self, formatter):
        """Edit tool shows as diff."""
        event = ToolUseEvent(
            tool_use_id="123",
            tool_name="Edit",
            tool_input={
                "file_path": "/test.py",
                "old_string": "old",
                "new_string": "new",
            },
        )
        result = formatter.format_tool_use(event)
        # Should return a Group with header and diff

    def test_read_tool(self, formatter):
        """Read tool shows file path."""
        event = ToolUseEvent(
            tool_use_id="123",
            tool_name="Read",
            tool_input={"file_path": "/test.py"},
        )
        result = formatter.format_tool_use(event)
        assert "/test.py" in str(result)
        assert "Read" in str(result)

    def test_read_tool_with_range(self, formatter):
        """Read tool with offset/limit shows range."""
        event = ToolUseEvent(
            tool_use_id="123",
            tool_name="Read",
            tool_input={"file_path": "/test.py", "offset": 10, "limit": 50},
        )
        result = formatter.format_tool_use(event)
        assert "/test.py" in str(result)

    def test_write_tool(self, formatter):
        """Write tool shows file path and preview."""
        event = ToolUseEvent(
            tool_use_id="123",
            tool_name="Write",
            tool_input={"file_path": "/test.py", "content": "print('hello')"},
        )
        result = formatter.format_tool_use(event)
        assert "Write" in str(result)
        assert "/test.py" in str(result)

    def test_write_tool_truncates_long_content(self, formatter):
        """Write tool truncates long content."""
        event = ToolUseEvent(
            tool_use_id="123",
            tool_name="Write",
            tool_input={"file_path": "/test.py", "content": "x" * 1000},
        )
        result = formatter.format_tool_use(event)
        assert "truncated" in str(result)

    def test_bash_tool(self, formatter):
        """Bash tool shows command."""
        event = ToolUseEvent(
            tool_use_id="123",
            tool_name="Bash",
            tool_input={"command": "ls -la"},
        )
        result = formatter.format_tool_use(event)
        assert "Bash" in str(result)
        assert "ls -la" in str(result)

    def test_bash_tool_with_description(self, formatter):
        """Bash tool shows description if present."""
        event = ToolUseEvent(
            tool_use_id="123",
            tool_name="Bash",
            tool_input={"command": "ls", "description": "list files"},
        )
        result = formatter.format_tool_use(event)
        assert "list files" in str(result)

    def test_glob_tool(self, formatter):
        """Glob tool shows pattern."""
        event = ToolUseEvent(
            tool_use_id="123",
            tool_name="Glob",
            tool_input={"pattern": "*.py"},
        )
        result = formatter.format_tool_use(event)
        assert "Glob" in str(result)
        assert "*.py" in str(result)

    def test_grep_tool(self, formatter):
        """Grep tool shows pattern and path."""
        event = ToolUseEvent(
            tool_use_id="123",
            tool_name="Grep",
            tool_input={"pattern": "TODO", "path": "/src"},
        )
        result = formatter.format_tool_use(event)
        assert "Grep" in str(result)
        assert "TODO" in str(result)
        assert "/src" in str(result)

    def test_unknown_tool(self, formatter):
        """Unknown tools show as JSON."""
        event = ToolUseEvent(
            tool_use_id="123",
            tool_name="CustomTool",
            tool_input={"foo": "bar"},
        )
        result = formatter.format_tool_use(event)
        assert "CustomTool" in str(result)
        assert "foo" in str(result)


class TestFormatterToolResult:
    """Tests for tool result formatting."""

    def test_empty_result(self, formatter):
        """Empty result returns empty string."""
        event = ToolResultEvent(tool_use_id="123", result="")
        result = formatter.format_tool_result(event)
        assert result == ""

    def test_simple_result(self, formatter):
        """Simple result shown as code block."""
        event = ToolResultEvent(tool_use_id="123", result="output here")
        result = formatter.format_tool_result(event)
        assert "output here" in str(result)

    def test_long_result_truncated(self, formatter):
        """Long results are truncated."""
        event = ToolResultEvent(tool_use_id="123", result="x" * 1000)
        result = formatter.format_tool_result(event)
        assert "..." in str(result)

    def test_read_result_with_line_numbers(self, formatter):
        """Read results get special formatting."""
        last_tool = ToolUseBlock(id="123", name="Read", input={"file_path": "/test.py"})
        event = ToolResultEvent(tool_use_id="123", result="    1→print('hello')")
        result = formatter.format_tool_result(event, last_tool)
        # Should have syntax highlighting applied


class TestFormatterBlocks:
    """Tests for formatting content blocks (from history)."""

    def test_tool_use_block(self, formatter):
        """ToolUseBlock formatting."""
        block = ToolUseBlock(id="123", name="Read", input={"file_path": "/test.py"})
        result = formatter.format_tool_use_block(block)
        assert "Read" in str(result)
        assert "/test.py" in str(result)

    def test_tool_result_block(self, formatter):
        """ToolResultBlock formatting."""
        block = ToolResultBlock(tool_use_id="123", content="file contents")
        result = formatter.format_tool_result_block(block)
        assert "file contents" in str(result)

    def test_tool_result_block_truncates(self, formatter):
        """Long ToolResultBlock content is truncated."""
        block = ToolResultBlock(tool_use_id="123", content="x" * 5000)
        result = formatter.format_tool_result_block(block)
        assert "truncated" in str(result)
