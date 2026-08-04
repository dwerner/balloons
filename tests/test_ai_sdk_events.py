"""Tests for AI SDK event models with string/dict types."""

import pytest
import json
from models import (
    ToolInputDeltaEvent, ToolUseEvent, ToolResultEvent,
    ToolResultDeltaEvent, ToolUseStartEvent, ErrorBlock
)


class TestToolInputDeltaEvent:
    """Test ToolInputDeltaEvent with string delta."""

    def test_delta_is_string(self):
        """Test that delta is string type."""
        event = ToolInputDeltaEvent(
            tool_use_id="test-1",
            partial_json='{"key":',
            delta='{"key":'
        )
        assert isinstance(event.delta, str)
        assert event.delta == '{"key":'

    def test_delta_can_be_none(self):
        """Test that delta can be None."""
        event = ToolInputDeltaEvent(
            tool_use_id="test-1",
            partial_json='{"key":'
        )
        assert event.delta is None

    def test_delta_empty_string(self):
        """Test that delta can be empty string."""
        event = ToolInputDeltaEvent(
            tool_use_id="test-1",
            partial_json='',
            delta=''
        )
        assert event.delta == ''

    def test_partial_json_backward_compat(self):
        """Test partial_json is kept for backward compat."""
        event = ToolInputDeltaEvent(
            tool_use_id="test-1",
            partial_json='{"key": "value"}',
            delta='{"key": "value"}'
        )
        assert event.partial_json == '{"key": "value"}'

    def test_delta_with_nested_json(self):
        """Test delta with nested JSON structure."""
        event = ToolInputDeltaEvent(
            tool_use_id="test-1",
            partial_json='{"edit": {"file": "test.py"}}',
            delta='{"edit": {"file": "test.py"}}'
        )
        assert isinstance(event.delta, str)
        # Verify it's valid JSON
        parsed = json.loads(event.delta)
        assert parsed == {"edit": {"file": "test.py"}}

    def test_delta_with_special_chars(self):
        """Test delta with special characters."""
        event = ToolInputDeltaEvent(
            tool_use_id="test-1",
            partial_json='{"code": "print(\\"hello\\")"}',
            delta='{"code": "print(\\"hello\\")"}'
        )
        assert isinstance(event.delta, str)
        parsed = json.loads(event.delta)
        assert parsed == {"code": 'print("hello")'}


class TestToolUseEvent:
    """Test ToolUseEvent with dict tool_input."""

    def test_tool_input_is_dict(self):
        """Test that tool_input is dict type."""
        event = ToolUseEvent(
            tool_use_id="test-1",
            tool_name="Read",
            tool_input={"file_path": "test.py"}
        )
        assert isinstance(event.tool_input, dict)
        assert event.tool_input == {"file_path": "test.py"}

    def test_tool_input_nested_dict(self):
        """Test that tool_input can have nested dicts."""
        event = ToolUseEvent(
            tool_use_id="test-1",
            tool_name="Edit",
            tool_input={
                "file_path": "test.py",
                "old_string": "old",
                "new_string": "new"
            }
        )
        assert event.tool_input["old_string"] == "old"
        assert event.tool_input["new_string"] == "new"

    def test_tool_input_empty_dict(self):
        """Test that tool_input can be empty dict."""
        event = ToolUseEvent(
            tool_use_id="test-1",
            tool_name="Test",
            tool_input={}
        )
        assert event.tool_input == {}

    def test_tool_input_with_arrays(self):
        """Test that tool_input can have arrays."""
        event = ToolUseEvent(
            tool_use_id="test-1",
            tool_name="Bash",
            tool_input={
                "command": "echo $PATH",
                "env": ["PATH", "HOME"]
            }
        )
        assert isinstance(event.tool_input["env"], list)
        assert event.tool_input["env"] == ["PATH", "HOME"]

    def test_tool_input_with_numbers(self):
        """Test that tool_input can have numbers."""
        event = ToolUseEvent(
            tool_use_id="test-1",
            tool_name="Read",
            tool_input={
                "file_path": "test.py",
                "offset": 100,
                "limit": 50
            }
        )
        assert event.tool_input["offset"] == 100
        assert event.tool_input["limit"] == 50

    def test_tool_input_with_booleans(self):
        """Test that tool_input can have booleans."""
        event = ToolUseEvent(
            tool_use_id="test-1",
            tool_name="Glob",
            tool_input={
                "pattern": "*.py",
                "recursive": True
            }
        )
        assert event.tool_input["recursive"] is True

    def test_tool_input_serialization(self):
        """Test that tool_input can be serialized to JSON."""
        event = ToolUseEvent(
            tool_use_id="test-1",
            tool_name="Edit",
            tool_input={
                "file_path": "test.py",
                "old_string": "old",
                "new_string": "new"
            }
        )
        serialized = json.dumps(event.tool_input)
        parsed = json.loads(serialized)
        assert parsed == event.tool_input


class TestToolResultEvent:
    """Test ToolResultEvent."""

    def test_result_is_string(self):
        """Test that result is string type."""
        event = ToolResultEvent(
            tool_use_id="test-1",
            result="File contents here"
        )
        assert isinstance(event.result, str)
        assert event.result == "File contents here"

    def test_result_with_multiline(self):
        """Test result with multiline content."""
        event = ToolResultEvent(
            tool_use_id="test-1",
            result="line1\nline2\nline3"
        )
        assert "\n" in event.result

    def test_result_with_json(self):
        """Test result containing JSON."""
        json_result = '{"status": "ok", "data": [1, 2, 3]}'
        event = ToolResultEvent(
            tool_use_id="test-1",
            result=json_result
        )
        assert isinstance(event.result, str)
        # Should be able to parse
        parsed = json.loads(event.result)
        assert parsed["status"] == "ok"

    def test_result_empty(self):
        """Test empty result."""
        event = ToolResultEvent(
            tool_use_id="test-1",
            result=""
        )
        assert event.result == ""

    def test_result_with_error(self):
        """Test error result."""
        event = ToolResultEvent(
            tool_use_id="test-1",
            result="Error: file not found"
        )
        assert "Error" in event.result


class TestToolResultDeltaEvent:
    """Test ToolResultDeltaEvent for streaming tool output."""

    def test_delta_is_string(self):
        """Test that delta is string type."""
        event = ToolResultDeltaEvent(
            tool_use_id="test-1",
            delta="Processing...",
            stream="stdout"
        )
        assert isinstance(event.delta, str)
        assert event.delta == "Processing..."

    def test_with_session_context(self):
        """Test with session context fields."""
        event = ToolResultDeltaEvent(
            tool_use_id="test-1",
            delta="Output chunk 1",
            stream="stdout",
            session_id="session-123",
            exchange_id="exchange-456",
            turn_id="turn-789",
            tool_name="Read"
        )
        assert event.session_id == "session-123"
        assert event.exchange_id == "exchange-456"
        assert event.turn_id == "turn-789"
        assert event.tool_name == "Read"

    def test_default_stream(self):
        """Test default stream value."""
        event = ToolResultDeltaEvent(
            tool_use_id="test-1",
            delta="Output"
        )
        assert event.stream == "stdout"


class TestToolUseStartEvent:
    """Test ToolUseStartEvent."""

    def test_basic(self):
        """Test basic ToolUseStartEvent."""
        event = ToolUseStartEvent(
            tool_use_id="test-1",
            tool_name="Read"
        )
        assert event.tool_use_id == "test-1"
        assert event.tool_name == "Read"

    def test_with_empty_name(self):
        """Test with empty tool name."""
        event = ToolUseStartEvent(
            tool_use_id="test-1",
            tool_name=""
        )
        assert event.tool_name == ""


class TestErrorBlock:
    """Test ErrorBlock for error handling."""

    def test_basic(self):
        """Test basic ErrorBlock."""
        error = ErrorBlock(details="Something went wrong")
        assert error.details == "Something went wrong"

    def test_with_tool_error(self):
        """Test ErrorBlock with tool error."""
        error = ErrorBlock(details="Invalid tool arguments for Read: Expecting '}': line 1 column 20")
        assert "Invalid tool arguments" in error.details
        assert "Read" in error.details

    def test_with_stream_error(self):
        """Test ErrorBlock with stream error."""
        error = ErrorBlock(details="Stream error: Connection lost")
        assert "Stream error" in error.details
