"""Tests for JSON repair utilities."""

import pytest
from core.json_repair import (
    repair_json,
    repair_tool_input,
    parse_tool_use_blocks,
    find_malformed_tool_uses,
)


class TestRepairNestedQuotes:
    """Test repair of unescaped nested quotes."""

    def test_valid_json_unchanged(self):
        """Valid JSON should pass through unchanged."""
        valid = '{"command": "echo hello"}'
        result = repair_json(valid)
        assert result.success
        assert result.repair_description == "no repair needed"
        assert result.parsed_value == {"command": "echo hello"}

    def test_nested_quotes_in_ssh_command(self):
        """The classic case: ssh with nested command quotes."""
        malformed = '{ "command": "ssh host \"echo hello\"" }'
        # This is actually valid JSON (escaped quotes)
        result = repair_json(malformed)
        assert result.success

    def test_unescaped_nested_quotes(self):
        """Unescaped quotes inside string value."""
        malformed = '{ "command": "ssh host "echo hello"" }'
        result = repair_json(malformed)
        assert result.success
        assert "nested quote" in result.repair_description.lower()
        assert result.parsed_value["command"] == 'ssh host "echo hello"'

    def test_multiple_nested_quotes(self):
        """Multiple unescaped quotes."""
        malformed = '{ "cmd": "ssh "host" "cmd arg"" }'
        result = repair_json(malformed)
        assert result.success
        assert result.parsed_value["cmd"] == 'ssh "host" "cmd arg"'


class TestRepairSingleQuotes:
    """Test repair of single-quoted JSON (Python style)."""

    def test_single_quoted_json(self):
        """Convert single quotes to double."""
        malformed = "{'key': 'value'}"
        result = repair_json(malformed)
        assert result.success
        assert result.parsed_value == {"key": "value"}


class TestRepairTrailingComma:
    """Test repair of trailing commas."""

    def test_trailing_comma_in_object(self):
        """Remove trailing comma before }."""
        malformed = '{"key": "value",}'
        result = repair_json(malformed)
        assert result.success
        assert result.parsed_value == {"key": "value"}

    def test_trailing_comma_in_array(self):
        """Remove trailing comma before ]."""
        malformed = '{"arr": [1, 2, 3,]}'
        result = repair_json(malformed)
        assert result.success
        assert result.parsed_value == {"arr": [1, 2, 3]}


class TestRepairToolInput:
    """Test tool-specific repair heuristics."""

    def test_bash_nested_quotes(self):
        """Bash tool with nested quotes in command."""
        malformed = '{ "command": "ssh server "tail -f log"", "description": "Check logs" }'
        result = repair_tool_input("Bash", malformed)
        assert result.success
        assert result.parsed_value["command"] == 'ssh server "tail -f log"'
        assert result.parsed_value["description"] == "Check logs"


class TestParseToolUseBlocks:
    """Test parsing <tool_use> blocks from text."""

    def test_valid_tool_use_block(self):
        """Parse a valid tool_use block."""
        text = '''
        <tool_use name="Bash" id="tool-123">
        {"command": "ls -la"}
        </tool_use>
        '''
        tools = parse_tool_use_blocks(text)
        assert len(tools) == 1
        assert tools[0].name == "Bash"
        assert tools[0].id == "tool-123"
        assert tools[0].input == {"command": "ls -la"}
        assert not tools[0].was_repaired

    def test_malformed_tool_use_block(self):
        """Parse and repair a malformed tool_use block."""
        text = '''
        <tool_use name="Bash" id="tool-456">
        { "command": "ssh host "tail -f log"" }
        </tool_use>
        '''
        tools = parse_tool_use_blocks(text)
        assert len(tools) == 1
        assert tools[0].name == "Bash"
        assert tools[0].is_valid  # Repair succeeded
        assert tools[0].was_repaired
        assert tools[0].input["command"] == 'ssh host "tail -f log"'

    def test_multiple_tool_use_blocks(self):
        """Parse multiple tool_use blocks."""
        text = '''
        <tool_use name="Read" id="read-1">
        {"file_path": "/etc/hosts"}
        </tool_use>
        Some text in between
        <tool_use name="Bash" id="bash-1">
        {"command": "echo hello"}
        </tool_use>
        '''
        tools = parse_tool_use_blocks(text)
        assert len(tools) == 2
        assert tools[0].name == "Read"
        assert tools[1].name == "Bash"


class TestFindMalformedToolUses:
    """Test finding only malformed tool_use blocks."""

    def test_finds_only_malformed(self):
        """Should return only blocks that needed repair."""
        text = '''
        <tool_use name="Read" id="read-1">
        {"file_path": "/etc/hosts"}
        </tool_use>
        <tool_use name="Bash" id="bash-1">
        { "command": "ssh "cmd"" }
        </tool_use>
        '''
        malformed = find_malformed_tool_uses(text)
        assert len(malformed) == 1
        assert malformed[0].name == "Bash"
        assert malformed[0].was_repaired

    def test_no_malformed(self):
        """Should return empty list if all blocks are valid."""
        text = '''
        <tool_use name="Read" id="read-1">
        {"file_path": "/etc/hosts"}
        </tool_use>
        '''
        malformed = find_malformed_tool_uses(text)
        assert len(malformed) == 0
