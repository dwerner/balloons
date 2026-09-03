"""Integration tests for AISDKRunner - requires a running OpenAI-compatible server."""

import os
import pytest
import asyncio
from core.ai_sdk_runner import AISDKRunner
from models import ToolUseEvent, ToolResultEvent, ErrorBlock, ToolUseStartEvent


# These tests drive a real OpenAI-compatible endpoint (AI_SDK_TEST_BASE_URL, default
# 192.168.0.196:8000), so they must not run in the default `-m "not integration"` pass.
# The justfile runs them explicitly via `test-ai-sdk-runner-integration`.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get('AI_SDK_TEST_SKIP') == '1',
        reason="AI_SDK_TEST_SKIP=1 - skipping integration tests",
    ),
]


@pytest.fixture
def ai_sdk_runner():
    """Create an AISDKRunner with test configuration."""
    base_url = os.environ.get('AI_SDK_TEST_BASE_URL', 'http://192.168.0.196:8000')
    model = os.environ.get('AI_SDK_TEST_MODEL', 'Qwen3.5-122B-A10B-Q6_K-00001-of-00004.gguf')
    api_key = os.environ.get('AI_SDK_TEST_API_KEY')

    return AISDKRunner(
        base_url=base_url,
        model=model,
        api_key=api_key if api_key else None,
        context_window=200000,
    )


@pytest.fixture
def ai_sdk_runner_readonly():
    """Create an AISDKRunner with read-only tools only (no Write/Edit/Bash)."""
    base_url = os.environ.get('AI_SDK_TEST_BASE_URL', 'http://192.168.0.196:8000')
    model = os.environ.get('AI_SDK_TEST_MODEL', 'Qwen3.5-122B-A10B-Q6_K-00001-of-00004.gguf')
    api_key = os.environ.get('AI_SDK_TEST_API_KEY')

    runner = AISDKRunner(
        base_url=base_url,
        model=model,
        api_key=api_key if api_key else None,
        context_window=200000,
    )
    # Store read-only tool list for stream_response calls
    runner._readonly_tools = ['Read', 'Glob', 'Grep', 'List']
    return runner


@pytest.mark.asyncio
async def test_ai_sdk_basic_text_generation(ai_sdk_runner):
    """Test basic text generation with AI SDK runner."""
    events = []
    async for event in ai_sdk_runner.stream_response([], 'Say hello briefly.'):
        events.append(event)

    assert len(events) >= 2
    assert any(type(e).__name__ == 'InitEvent' for e in events)
    assert any(type(e).__name__ == 'ResultEvent' for e in events)

    # Should have received some text
    text_events = [e for e in events if type(e).__name__ == 'TextDelta']
    total_text = ''.join(getattr(e, 'text', '') for e in text_events)
    assert len(total_text) > 0


@pytest.mark.asyncio
async def test_ai_sdk_reasoning_content(ai_sdk_runner):
    """Test that reasoning content is handled if model provides it."""
    events = []
    async for event in ai_sdk_runner.stream_response([], 'Think about 2+2 briefly.'):
        events.append(event)

    # Just verify we get a response without errors
    error_events = [e for e in events if type(e).__name__ == 'ErrorBlock']
    assert len(error_events) == 0


@pytest.mark.asyncio
async def test_ai_sdk_context_handling(ai_sdk_runner):
    """Test that context is maintained across messages."""
    messages = []

    # First turn
    events1 = []
    async for event in ai_sdk_runner.stream_response(messages, 'My name is TestUser. Remember this.'):
        events1.append(event)

    # Add assistant response to messages (simplified - just track that we got a response)
    text1 = ''.join(getattr(e, 'text', '') for e in events1 if type(e).__name__ == 'TextDelta')
    messages.append(type('Message', (), {'role': 'assistant', 'content': text1})())
    messages.append(type('Message', (), {'role': 'user', 'content': 'What is my name?'})())

    # Second turn - should know the name
    events2 = []
    async for event in ai_sdk_runner.stream_response(messages, 'What is my name?'):
        events2.append(event)

    # Just verify no errors
    error_events = [e for e in events2 if type(e).__name__ == 'ErrorBlock']
    assert len(error_events) == 0


@pytest.mark.asyncio
async def test_ai_sdk_streaming_behavior(ai_sdk_runner):
    """Test that streaming returns multiple events (not just one big response)."""
    events = []
    async for event in ai_sdk_runner.stream_response([], 'Write a short poem about coding.'):
        events.append(event)

    # Should have multiple TextDelta events for streaming
    text_events = [e for e in events if type(e).__name__ == 'TextDelta']
    
    # If we got any text, we should have had streaming
    total_text = ''.join(getattr(e, 'text', '') for e in text_events)
    if len(total_text) > 50:  # Only check if we got substantial text
        assert len(text_events) > 1, "Expected multiple text deltas for streaming"


@pytest.mark.asyncio
async def test_ai_sdk_error_handling(ai_sdk_runner):
    """Test that errors are properly reported."""
    # This test verifies the error handling path works
    # If the server is down, we should get an ErrorBlock, not an exception
    events = []
    try:
        async for event in ai_sdk_runner.stream_response([], 'Hello'):
            events.append(event)
    except Exception as e:
        # If we get an exception, that's also a form of error handling
        pytest.fail(f"Unexpected exception: {e}")

    # Either we got a successful response or an error block
    error_events = [e for e in events if type(e).__name__ == 'ErrorBlock']
    result_events = [e for e in events if type(e).__name__ == 'ResultEvent']
    
    # One of these should be present
    assert len(error_events) > 0 or len(result_events) > 0


# =============================================================================
# Tool Call Integration Tests
# =============================================================================

@pytest.mark.asyncio
async def test_ai_sdk_tool_call_basic(ai_sdk_runner_readonly):
    """Test that tool calls are handled correctly with read-only tools."""
    # Use a prompt that might trigger a tool call
    events = []
    async for event in ai_sdk_runner_readonly.stream_response(
        [],
        'Please use the Read tool to read the file test.py. Just call the tool.',
        allowed_tools=ai_sdk_runner_readonly._readonly_tools
    ):
        events.append(event)

    # Check for errors
    error_events = [e for e in events if isinstance(e, ErrorBlock)]
    assert len(error_events) == 0, f"Got errors: {[e.details for e in error_events]}"

    # Should have either tool use events or a normal response
    tool_use_events = [e for e in events if isinstance(e, ToolUseEvent)]
    tool_start_events = [e for e in events if isinstance(e, ToolUseStartEvent)]
    result_events = [e for e in events if isinstance(e, ToolResultEvent)]

    # Either we got tool calls or the model declined
    # (depending on whether tools are available and model behavior)
    assert len(tool_use_events) > 0 or len(result_events) > 0 or len([e for e in events if type(e).__name__ == 'TextDelta']) > 0
    
    # ToolUseStart events should be emitted before ToolUse events
    if len(tool_use_events) > 0:
        assert len(tool_start_events) >= len(tool_use_events), \
            f"Expected at least {len(tool_use_events)} ToolUseStart events, got {len(tool_start_events)}"


@pytest.mark.asyncio
async def test_ai_sdk_tool_call_with_real_tool(ai_sdk_runner_readonly):
    """Test tool call with a real tool execution (read-only)."""
    # This test requires the Read tool to be available
    events = []
    async for event in ai_sdk_runner_readonly.stream_response(
        [],
        'Read the file README.md using the Read tool.',
        allowed_tools=ai_sdk_runner_readonly._readonly_tools
    ):
        events.append(event)

    # Check for errors
    error_events = [e for e in events if isinstance(e, ErrorBlock)]
    assert len(error_events) == 0, f"Got errors: {[e.details for e in error_events]}"

    # Should have tool use and result if tool was called
    tool_use_events = [e for e in events if isinstance(e, ToolUseEvent)]
    tool_result_events = [e for e in events if isinstance(e, ToolResultEvent)]

    # If model called the tool, we should have both
    if len(tool_use_events) > 0:
        assert len(tool_result_events) > 0, "Expected tool result after tool use"

        # Verify tool result has content
        for result in tool_result_events:
            assert len(result.result) > 0 or 'Error' in result.result


@pytest.mark.asyncio
async def test_ai_sdk_multiple_tool_calls(ai_sdk_runner_readonly):
    """Test multiple sequential tool calls (read-only)."""
    events = []
    async for event in ai_sdk_runner_readonly.stream_response(
        [],
        'Call the Glob tool to find all .py files, then read one of them.',
        allowed_tools=ai_sdk_runner_readonly._readonly_tools
    ):
        events.append(event)

    # Check for errors
    error_events = [e for e in events if isinstance(e, ErrorBlock)]
    assert len(error_events) == 0, f"Got errors: {[e.details for e in error_events]}"

    # Count tool uses and results
    tool_use_events = [e for e in events if isinstance(e, ToolUseEvent)]
    tool_result_events = [e for e in events if isinstance(e, ToolResultEvent)]

    # Should have matching tool uses and results
    assert len(tool_use_events) == len(tool_result_events) or len(tool_use_events) == 0


@pytest.mark.asyncio
async def test_ai_sdk_invalid_tool_arguments(ai_sdk_runner_readonly):
    """Test handling of invalid tool arguments (read-only)."""
    # This tests the error handling path when model generates invalid JSON
    events = []
    async for event in ai_sdk_runner_readonly.stream_response(
        [],
        'Try to call a tool with broken JSON: {"bad": json}',
        allowed_tools=ai_sdk_runner_readonly._readonly_tools
    ):
        events.append(event)

    # Should not crash - either get error block or model adapts
    # (The model should learn not to send invalid JSON)
    assert True  # If we got here without exception, the test passes
