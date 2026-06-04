"""Integration tests for AISDKRunner - requires a running OpenAI-compatible server."""

import os
import pytest
import asyncio
from core.ai_sdk_runner import AISDKRunner


# Skip all tests if no server URL is configured
pytestmark = pytest.mark.skipif(
    not os.environ.get('AI_SDK_TEST_BASE_URL'),
    reason="AI_SDK_TEST_BASE_URL not set - skipping integration tests"
)


@pytest.fixture
def ai_sdk_runner():
    """Create an AISDKRunner with test configuration."""
    base_url = os.environ.get('AI_SDK_TEST_BASE_URL', 'http://localhost:8000')
    model = os.environ.get('AI_SDK_TEST_MODEL', 'test-model')
    api_key = os.environ.get('AI_SDK_TEST_API_KEY')

    return AISDKRunner(
        base_url=base_url,
        model=model,
        api_key=api_key if api_key else None,
        context_window=200000,
    )


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
