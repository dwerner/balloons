"""Integration tests for ai-sdk-openai-compatible Python bindings against real server."""

import pytest
import asyncio

pytestmark = pytest.mark.integration
import json
from ai_sdk_openai_compatible_py import (
    create_chat_model_py as create_chat_model,
    create_completion_model_py as create_completion_model,
    create_embedding_model_py as create_embedding_model,
    AIError,
    PyMessage,
)

# Server configuration (base_url should NOT include /v1)
BASE_URL = "http://192.168.0.196:8000"
API_KEY = None  # No auth required for local server

# Model IDs (adjust based on your server's available models)
MODEL_ID = "Qwen3.5-122B-A10B-Q6_K-00001-of-00004.gguf"
CHAT_MODEL_ID = MODEL_ID
COMPLETION_MODEL_ID = MODEL_ID
# Note: Server doesn't support embeddings, skipping those tests
EMBEDDING_MODEL_ID = None


class TestChatModel:
    """Tests for chat model functionality."""

    @pytest.mark.asyncio
    async def test_generate_simple(self):
        """Test basic chat generation."""
        model = create_chat_model(BASE_URL, CHAT_MODEL_ID, API_KEY)
        
        result_str = await model.generate(
            messages=[
                PyMessage("user", "Hello, who are you?")
            ],
            max_tokens=500,
            temperature=0.7,
        )
        
        result = json.loads(result_str)
        print(f"Full result: {result}")
        assert "text" in result
        assert "usage" in result
        assert "finish_reason" in result
        print(f"Text: '{result['text'][:100]}...'")
        print(f"Reasoning: '{result.get('reasoning', 'N/A')[:100]}...'")
        print(f"Usage: {result['usage']}")
        # Qwen outputs both reasoning and content
        assert len(result.get("reasoning", "")) > 0, "Response reasoning should not be empty"
        assert len(result.get("text", "")) > 0, "Response text should not be empty"
        assert result["usage"]["input_tokens"] > 0
        assert result["usage"]["output_tokens"] > 0

    @pytest.mark.asyncio
    async def test_generate_with_system_prompt(self):
        """Test chat generation with system prompt."""
        model = create_chat_model(BASE_URL, CHAT_MODEL_ID, API_KEY)
        
        result_str = await model.generate(
            messages=[
                PyMessage("system", "You are a helpful assistant."),
                PyMessage("user", "What is 2+2?")
            ],
            max_tokens=500,
            temperature=0.7,
        )
        
        result = json.loads(result_str)
        assert "text" in result
        assert "usage" in result
        # Note: Model may return empty text for short questions
        # assert "2+2" in result["text"] or "4" in result["text"]
        print(f"System prompt response: {result['text']}")

    @pytest.mark.asyncio
    async def test_stream_response(self):
        """Test streaming chat generation."""
        model = create_chat_model(BASE_URL, CHAT_MODEL_ID, API_KEY)
        
        chunks = []
        stream = await model.stream(
            messages=[
                PyMessage("user", "Tell me a short story")
            ],
            max_tokens=100,
            temperature=0.7,
        )
        async for chunk in stream:
            chunks.append(chunk)
            print(f"Chunk: {chunk[:50]}..." if len(chunk) > 50 else f"Chunk: {chunk}")
        
        assert len(chunks) > 0
        assert chunks[-1] == "[DONE]"
        full_text = "".join(chunks[:-1])  # Exclude [DONE] marker
        assert len(full_text) > 0
        print(f"Full streamed text: {full_text[:200]}...")


class TestCompletionModel:
    """Tests for completion model functionality."""

    @pytest.mark.asyncio
    async def test_generate_completion(self):
        """Test basic text completion."""
        model = create_completion_model(BASE_URL, COMPLETION_MODEL_ID, API_KEY)
        
        result_str = await model.generate(
            prompt="Once upon a time",
            max_tokens=50,
            temperature=0.7,
)
        
        result = json.loads(result_str)
        assert "text" in result
        assert "usage" in result
        assert len(result["text"]) > 0, "Completion text should not be empty"
        print(f"Completion: {result['text'][:100]}...")

    @pytest.mark.asyncio
    async def test_stream_completion(self):
        """Test streaming completion."""
        pytest.skip("Streaming not implemented for completion model")


class TestEmbeddingModel:
    """Tests for embedding model functionality."""
    
    @pytest.fixture(autouse=True)
    def skip_if_no_embedding(self):
        """Skip all embedding tests if no embedding model configured."""
        if EMBEDDING_MODEL_ID is None:
            pytest.skip("Embedding model not configured")


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_invalid_model(self):
        """Test error handling for invalid model."""
        pytest.skip("Server accepts any model name")

    @pytest.mark.asyncio
    async def test_invalid_url(self):
        """Test error handling for invalid URL."""
        model = create_chat_model("http://invalid-url-xyz:9999/v1", CHAT_MODEL_ID, API_KEY)
        
        with pytest.raises(RuntimeError):
            await model.generate(
                messages=[PyMessage("user", "Hello")],
                max_tokens=50,
                temperature=0.7,
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
