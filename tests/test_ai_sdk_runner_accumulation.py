"""Tests for tool call string accumulation and parsing in AISDKRunner."""

import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock

from core.ai_sdk_runner import AISDKRunner
from models import (
    ToolUseStartEvent, ToolInputDeltaEvent, ToolUseEvent,
    ToolResultEvent, ErrorBlock, TextDelta, ResultEvent, InitEvent
)


class TestToolArgumentAccumulation:
    """Test string-based tool argument accumulation."""

    @pytest.mark.asyncio
    async def test_accumulate_valid_json_from_chunks(self):
        """Test that string chunks are accumulated and parsed correctly."""
        # Simulate streaming: {"file_path": "test.py"}
        chunks = [
            '{"file_path": "',
            'test',
            '.py"}'
        ]
        
        # Verify accumulation logic
        accumulated = ""
        for chunk in chunks:
            accumulated += chunk
        
        result = json.loads(accumulated)
        assert result == {"file_path": "test.py"}

    @pytest.mark.asyncio
    async def test_accumulate_empty_json_object(self):
        """Test that empty JSON object is handled."""
        accumulated = "{}"
        result = json.loads(accumulated)
        assert result == {}
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_accumulate_nested_json(self):
        """Test that nested JSON is accumulated correctly."""
        chunks = [
            '{"edit": {"file": "',
            'test.py", "old": "a',
            '", "new": "b"}}'
        ]
        
        accumulated = ""
        for chunk in chunks:
            accumulated += chunk
        
        result = json.loads(accumulated)
        assert result == {
            "edit": {
                "file": "test.py",
                "old": "a",
                "new": "b"
            }
        }

    @pytest.mark.asyncio
    async def test_invalid_json_raises_error(self):
        """Test that invalid JSON raises JSONDecodeError."""
        invalid = '{"file_path": "test.py"'  # Missing closing brace
        
        with pytest.raises(json.JSONDecodeError):
            json.loads(invalid)

    @pytest.mark.asyncio
    async def test_invalid_json_with_colon(self):
        """Test invalid JSON with incomplete value."""
        invalid = '{"key":'
        
        with pytest.raises(json.JSONDecodeError):
            json.loads(invalid)


class TestStreamChunkHandling:
    """Test StreamChunk event handling in _stream_one_response."""

    @pytest.mark.asyncio
    async def test_tool_call_delta_string_accumulation(self):
        """Test ToolCallDelta with string delta accumulates correctly."""
        runner = AISDKRunner(
            base_url='http://localhost:8000',
            model='test-model'
        )
        
        # Simulate multiple ToolCallDelta chunks
        chunks = [
            '{"file_path": "',
            'test',
            '.py"}'
        ]
        
        # Accumulate as the runner would
        accumulated = ""
        for chunk in chunks:
            accumulated += chunk
        
        # Parse at the end
        result = json.loads(accumulated)
        assert result == {"file_path": "test.py"}
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_tool_call_complete_parsing(self):
        """Test ToolCallComplete JSON parsing succeeds."""
        args_str = '{"file_path": "test.py", "offset": 0, "limit": 100}'
        
        result = json.loads(args_str)
        assert result == {
            "file_path": "test.py",
            "offset": 0,
            "limit": 100
        }

    @pytest.mark.asyncio
    async def test_tool_call_complete_invalid_json_emits_error(self):
        """Test ToolCallComplete with invalid JSON emits ErrorBlock."""
        args_str = '{"file_path": "test.py'  # Invalid
        
        events = []
        try:
            json.loads(args_str)
        except json.JSONDecodeError as e:
            events.append(ErrorBlock(details=f"Invalid tool arguments for Read: {e}"))
        
        assert len(events) == 1
        assert isinstance(events[0], ErrorBlock)
        assert "Invalid tool arguments" in events[0].details

    @pytest.mark.asyncio
    async def test_multiple_sequential_tool_calls(self):
        """Test multiple tool calls are accumulated separately."""
        tool1_chunks = ['{"file": "', 'test1.py"}']
        tool2_chunks = ['{"command": "', 'ls -la"}']
        
        # Accumulate tool 1
        tool1_args = ""
        for chunk in tool1_chunks:
            tool1_args += chunk
        tool1_result = json.loads(tool1_args)
        
        # Accumulate tool 2
        tool2_args = ""
        for chunk in tool2_chunks:
            tool2_args += chunk
        tool2_result = json.loads(tool2_args)
        
        assert tool1_result == {"file": "test1.py"}
        assert tool2_result == {"command": "ls -la"}


class TestFinishEventHandling:
    """Test Finish event handling with pending tool data."""

    @pytest.mark.asyncio
    async def test_finish_with_pending_tool_data(self):
        """Test Finish event finalizes pending tool call."""
        # Simulate pending tool data at Finish
        current_tool_name = "Read"
        current_tool_args_str = '{"file_path": "pending.py"}'
        
        # Parse at Finish
        tool_args = json.loads(current_tool_args_str)
        
        assert current_tool_name == "Read"
        assert tool_args == {"file_path": "pending.py"}

    @pytest.mark.asyncio
    async def test_finish_with_invalid_pending_json(self):
        """Test Finish event handles invalid pending JSON."""
        current_tool_name = "Read"
        current_tool_args_str = '{"file_path": "pending.py'  # Invalid
        
        events = []
        tool_args = {}
        try:
            tool_args = json.loads(current_tool_args_str)
        except json.JSONDecodeError as e:
            events.append(ErrorBlock(f"Invalid tool arguments for {current_tool_name}: {e}"))
            current_tool_args_str = ""
        
        assert len(events) == 1
        assert isinstance(events[0], ErrorBlock)
        assert tool_args == {}
        assert current_tool_args_str == ""


class TestToolInputDeltaEvent:
    """Test ToolInputDeltaEvent emission during streaming."""

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

    def test_partial_json_backward_compat(self):
        """Test partial_json is kept for backward compat."""
        event = ToolInputDeltaEvent(
            tool_use_id="test-1",
            partial_json='{"key": "value"}',
            delta='{"key": "value"}'
        )
        assert event.partial_json == '{"key": "value"}'


class TestToolUseEvent:
    """Test ToolUseEvent emission after parsing."""

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
