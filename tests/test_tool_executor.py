"""Tests for tool_executor module."""

import pytest
from pathlib import Path

from core.tool_executor import (
    execute_read,
    execute_write,
    execute_glob,
    execute_bash,
    execute_tool,
    resolve_path,
    truncate_output,
)


class TestResolvePath:
    """Tests for path resolution."""

    def test_absolute_path_unchanged(self):
        result = resolve_path("/home/user/file.txt", "/working/dir")
        assert result == Path("/home/user/file.txt")

    def test_relative_path_resolved(self):
        result = resolve_path("subdir/file.txt", "/working/dir")
        assert result == Path("/working/dir/subdir/file.txt")

    def test_dot_path_resolved(self):
        result = resolve_path("./file.txt", "/working/dir")
        assert result == Path("/working/dir/file.txt")


class TestTruncateOutput:
    """Tests for output truncation."""

    def test_small_output_unchanged(self):
        text = "small text"
        assert truncate_output(text) == text

    def test_large_output_truncated(self):
        text = "x" * 100000
        result = truncate_output(text, max_size=1000)
        assert len(result) < len(text)
        assert "truncated" in result


class TestExecuteRead:
    """Tests for async file reading."""

    @pytest.fixture
    def temp_file(self, tmp_path):
        """Create a temporary file for testing."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line one\nline two\nline three\n")
        return test_file

    @pytest.mark.asyncio
    async def test_read_file(self, temp_file):
        result, is_error = await execute_read(
            {"file_path": str(temp_file)},
            str(temp_file.parent)
        )
        assert not is_error
        assert "line one" in result
        assert "line two" in result

    @pytest.mark.asyncio
    async def test_read_file_with_line_numbers(self, temp_file):
        result, is_error = await execute_read(
            {"file_path": str(temp_file)},
            str(temp_file.parent)
        )
        assert not is_error
        # Line numbers should be included (cat -n format)
        assert "1\t" in result

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tmp_path):
        result, is_error = await execute_read(
            {"file_path": str(tmp_path / "nonexistent.txt")},
            str(tmp_path)
        )
        assert is_error
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_read_directory_fails(self, tmp_path):
        result, is_error = await execute_read(
            {"file_path": str(tmp_path)},
            str(tmp_path)
        )
        assert is_error
        assert "directory" in result.lower()

    @pytest.mark.asyncio
    async def test_read_missing_path_param(self, tmp_path):
        result, is_error = await execute_read({}, str(tmp_path))
        assert is_error
        assert "required" in result.lower()

    @pytest.mark.asyncio
    async def test_read_with_offset(self, temp_file):
        result, is_error = await execute_read(
            {"file_path": str(temp_file), "offset": 2},
            str(temp_file.parent)
        )
        assert not is_error
        # Should start from line 2
        assert "line one" not in result
        assert "line two" in result

    @pytest.mark.asyncio
    async def test_read_with_limit(self, temp_file):
        result, is_error = await execute_read(
            {"file_path": str(temp_file), "limit": 1},
            str(temp_file.parent)
        )
        assert not is_error
        assert "line one" in result
        assert "line two" not in result


class TestExecuteWrite:
    """Tests for async file writing."""

    @pytest.mark.asyncio
    async def test_write_new_file(self, tmp_path):
        test_file = tmp_path / "new_file.txt"
        content = "test content"

        result, is_error = await execute_write(
            {"file_path": str(test_file), "content": content},
            str(tmp_path)
        )

        assert not is_error
        assert "Successfully wrote" in result
        assert test_file.read_text() == content

    @pytest.mark.asyncio
    async def test_write_overwrites_existing(self, tmp_path):
        test_file = tmp_path / "existing.txt"
        test_file.write_text("old content")

        result, is_error = await execute_write(
            {"file_path": str(test_file), "content": "new content"},
            str(tmp_path)
        )

        assert not is_error
        assert test_file.read_text() == "new content"

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self, tmp_path):
        test_file = tmp_path / "subdir" / "nested" / "file.txt"
        content = "nested content"

        result, is_error = await execute_write(
            {"file_path": str(test_file), "content": content},
            str(tmp_path)
        )

        assert not is_error
        assert test_file.exists()
        assert test_file.read_text() == content

    @pytest.mark.asyncio
    async def test_write_missing_path_param(self, tmp_path):
        result, is_error = await execute_write(
            {"content": "test"},
            str(tmp_path)
        )
        assert is_error
        assert "required" in result.lower()

    @pytest.mark.asyncio
    async def test_write_missing_content_param(self, tmp_path):
        result, is_error = await execute_write(
            {"file_path": str(tmp_path / "test.txt")},
            str(tmp_path)
        )
        assert is_error
        assert "required" in result.lower()

    @pytest.mark.asyncio
    async def test_write_empty_content(self, tmp_path):
        test_file = tmp_path / "empty.txt"

        result, is_error = await execute_write(
            {"file_path": str(test_file), "content": ""},
            str(tmp_path)
        )

        assert not is_error
        assert test_file.read_text() == ""


class TestExecuteTool:
    """Tests for the execute_tool dispatcher."""

    @pytest.mark.asyncio
    async def test_dispatch_read(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")

        result, is_error = await execute_tool(
            "Read",
            {"file_path": str(test_file)},
            str(tmp_path)
        )

        assert not is_error
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_dispatch_write(self, tmp_path):
        test_file = tmp_path / "test.txt"

        result, is_error = await execute_tool(
            "Write",
            {"file_path": str(test_file), "content": "written"},
            str(tmp_path)
        )

        assert not is_error
        assert test_file.read_text() == "written"

    @pytest.mark.asyncio
    async def test_unknown_tool(self, tmp_path):
        result, is_error = await execute_tool(
            "UnknownTool",
            {},
            str(tmp_path)
        )

        assert is_error
        assert "Unknown tool" in result


class TestExecuteBash:
    """Tests for bash command execution."""

    @pytest.mark.asyncio
    async def test_simple_command(self, tmp_path):
        result, is_error = await execute_bash(
            {"command": "echo hello"},
            str(tmp_path)
        )
        assert not is_error
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_command_with_exit_code(self, tmp_path):
        result, is_error = await execute_bash(
            {"command": "exit 1"},
            str(tmp_path)
        )
        assert is_error
        assert "exit code: 1" in result

    @pytest.mark.asyncio
    async def test_missing_command_param(self, tmp_path):
        result, is_error = await execute_bash({}, str(tmp_path))
        assert is_error
        assert "required" in result.lower()


class TestExecuteGlob:
    """Tests for glob pattern matching."""

    @pytest.mark.asyncio
    async def test_find_files(self, tmp_path):
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.txt").write_text("b")
        (tmp_path / "other.py").write_text("c")

        result, is_error = await execute_glob(
            {"pattern": "*.txt"},
            str(tmp_path)
        )

        assert not is_error
        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "other.py" not in result

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_path):
        result, is_error = await execute_glob(
            {"pattern": "*.nonexistent"},
            str(tmp_path)
        )

        assert not is_error
        assert "No files found" in result

    @pytest.mark.asyncio
    async def test_missing_pattern_param(self, tmp_path):
        result, is_error = await execute_glob({}, str(tmp_path))
        assert is_error
        assert "required" in result.lower()
