"""Tests for StreamChunk Rust bindings."""

import pytest
from ai_sdk_openai_compatible_py import StreamChunk


class TestStreamChunk:
    """Test StreamChunk enum variants."""

    def test_tool_call_delta_with_string(self):
        """Test ToolCallDelta with string delta."""
        chunk = StreamChunk.ToolCallDelta(
            tool_id='test-1',
            delta='{"key": "value"}'
        )
        assert chunk.tool_id == 'test-1'
        assert chunk.delta == '{"key": "value"}'
        assert isinstance(chunk.delta, str)

    def test_tool_call_complete_with_string(self):
        """Test ToolCallComplete with string arguments."""
        chunk = StreamChunk.ToolCallComplete(
            tool_id='test-1',
            tool_name='Read',
            arguments='{"file_path": "test.py"}'
        )
        assert chunk.tool_id == 'test-1'
        assert chunk.tool_name == 'Read'
        assert chunk.arguments == '{"file_path": "test.py"}'
        assert isinstance(chunk.arguments, str)

    def test_tool_call_start(self):
        """Test ToolCallStart variant."""
        chunk = StreamChunk.ToolCallStart(
            tool_id='test-1',
            tool_name='Read'
        )
        assert chunk.tool_id == 'test-1'
        assert chunk.tool_name == 'Read'

    def test_tool_call_start_with_none_name(self):
        """Test ToolCallStart with None tool name."""
        chunk = StreamChunk.ToolCallStart(
            tool_id='test-1',
            tool_name=None
        )
        assert chunk.tool_id == 'test-1'
        assert chunk.tool_name is None

    def test_text_delta(self):
        """Test TextDelta variant."""
        chunk = StreamChunk.TextDelta(
            delta='Hello '
        )
        assert chunk.delta == 'Hello '
        assert isinstance(chunk.delta, str)

    def test_reasoning_delta(self):
        """Test ReasoningDelta variant."""
        chunk = StreamChunk.ReasoningDelta(
            delta='Let me think about this...'
        )
        assert chunk.delta == 'Let me think about this...'
        assert isinstance(chunk.delta, str)

    def test_finish_with_usage(self):
        """Test Finish variant with usage."""
        # Usage is created internally by the Rust code, not directly from Python
        # Just test that Finish can be created with None usage
        chunk = StreamChunk.Finish(usage=None)
        assert chunk.usage is None

    def test_finish_without_usage(self):
        """Test Finish variant without usage."""
        chunk = StreamChunk.Finish(usage=None)
        assert chunk.usage is None

    def test_done(self):
        """Test Done variant."""
        chunk = StreamChunk.Done()
        # Done is a unit variant, just check it exists
        assert chunk is not None

    def test_tool_call_delta_empty_string(self):
        """Test ToolCallDelta with empty string."""
        chunk = StreamChunk.ToolCallDelta(
            tool_id='test-1',
            delta=''
        )
        assert chunk.delta == ''

    def test_tool_call_complete_empty_arguments(self):
        """Test ToolCallComplete with empty arguments."""
        chunk = StreamChunk.ToolCallComplete(
            tool_id='test-1',
            tool_name='Test',
            arguments=''
        )
        assert chunk.arguments == ''

    def test_tool_call_complete_nested_json(self):
        """Test ToolCallComplete with nested JSON."""
        chunk = StreamChunk.ToolCallComplete(
            tool_id='test-1',
            tool_name='Edit',
            arguments='{"edit": {"file": "test.py", "old": "a", "new": "b"}}'
        )
        assert isinstance(chunk.arguments, str)
        import json
        parsed = json.loads(chunk.arguments)
        assert parsed == {"edit": {"file": "test.py", "old": "a", "new": "b"}}

    def test_tool_call_delta_special_chars(self):
        """Test ToolCallDelta with special characters."""
        chunk = StreamChunk.ToolCallDelta(
            tool_id='test-1',
            delta='{"code": "print(\\"hello\\")"}'
        )
        assert isinstance(chunk.delta, str)
        import json
        parsed = json.loads(chunk.delta)
        assert parsed == {"code": 'print("hello")'}

    def test_tool_call_delta_unicode(self):
        """Test ToolCallDelta with unicode."""
        chunk = StreamChunk.ToolCallDelta(
            tool_id='test-1',
            delta='{"message": "こんにちは"}'
        )
        assert isinstance(chunk.delta, str)
        import json
        parsed = json.loads(chunk.delta)
        assert parsed == {"message": "こんにちは"}
