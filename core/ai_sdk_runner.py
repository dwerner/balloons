"""AI SDK runner using Rust ai-sdk-openai-compatible crate via Python bindings.

This runner uses the high-performance Rust implementation of the OpenAI-compatible
protocol, providing better streaming support and native reasoning/text separation.
"""

import asyncio
import json
from typing import AsyncIterator, TYPE_CHECKING

from models import (
    Message, TextDelta, ResultEvent, InitEvent,
    TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, ArchiveBlock, ContextMode,
    ToolUseStartEvent, ToolInputDeltaEvent, ToolUseEvent, ToolResultDeltaEvent, ToolResultEvent, SteeringInjectedEvent,
)
from .base_runner import BaseRunner, RunnerEvent, SteeringCapability

if TYPE_CHECKING:
    from session import Session


class AISDKRunner(BaseRunner):
    """Runner using ai-sdk-openai-compatible Rust crate via Python bindings."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        user_prompt: str | None = None,
        context_window: int = 200000,
    ):
        """Initialize the AI SDK runner.

        Args:
            base_url: Base URL for the OpenAI-compatible API (e.g., http://localhost:8000)
            model: Model identifier (e.g., Qwen3.5-122B-A10B-Q6_K-00001-of-00004.gguf)
            api_key: Optional API key (None for local servers)
            user_prompt: Optional custom system prompt
            context_window: Maximum context window size in tokens
        """
        self.base_url = base_url.rstrip("/v1")  # Remove /v1 if present
        self.model = model
        self.api_key = api_key
        self.user_prompt = user_prompt
        self.context_window = context_window

        self._running = False
        self._current_task: asyncio.Task | None = None
        self._injection_callback = None
        self._tool_event_callback = None

        # Import Python bindings lazily
        try:
            from ai_sdk_openai_compatible_py import (
                create_chat_model_py,
                PyMessage,
            )
            self._create_chat_model = create_chat_model_py
            self._PyMessage = PyMessage
        except ImportError as e:
            raise RuntimeError(
                "ai-sdk-openai-compatible-py not installed. "
                "Install with: cd balloons-rs/crates/ai-sdk-openai-compatible-py && maturin develop"
            ) from e

    @property
    def steering_capability(self) -> SteeringCapability:
        """AI SDK runner supports separate messages for steering."""
        return SteeringCapability.SEPARATE_MESSAGES

    async def stream_response(
        self,
        messages: list[Message],
        prompt: str,
        allowed_tools: list[str] | None = None,
        working_dir: str | None = None,
        disable_tools: bool = False,
    ) -> AsyncIterator[RunnerEvent]:
        """Stream a response from the AI SDK model.

        Args:
            messages: Message history for context
            prompt: The new prompt to send
            allowed_tools: List of tool names to allow (not yet supported)
            working_dir: Working directory for file operations (not used)
            disable_tools: If True, disable all tools

        Yields:
            Events from the model (text deltas, reasoning, results)
        """
        self._running = True

        try:
            # Build message list
            py_messages = []

            # Add system prompt if configured
            if self.user_prompt:
                py_messages.append(self._PyMessage("system", self.user_prompt))

            # Add conversation history
            for msg in messages:
                role = msg.role
                if role in ("system", "user", "assistant"):
                    # For simplicity, we're only handling text content
                    # Image content and tool results would need more work
                    if isinstance(msg.content, str):
                        py_messages.append(self._PyMessage(role, msg.content))
                    elif isinstance(msg.content, list):
                        # Extract text from content blocks
                        text_parts = []
                        for block in msg.content:
                            if hasattr(block, 'type'):
                                if block.type == "text":
                                    text_parts.append(block.text)
                                elif block.type == "tool_use":
                                    text_parts.append(f"[Tool: {block.name}]")
                                elif block.type == "tool_result":
                                    text_parts.append(f"[Tool Result: {block.content}]")
                        if text_parts:
                            py_messages.append(self._PyMessage(role, " ".join(text_parts)))

            # Add current prompt
            py_messages.append(self._PyMessage("user", prompt))

            # Create model instance
            model = self._create_chat_model(self.base_url, self.model, self.api_key)

            # Generate response
            yield InitEvent()

            # Use generate for now (streaming can be added later)
            result_str = await model.generate(
                messages=py_messages,
                max_tokens=min(4000, self.context_window // 4),  # Conservative default
                temperature=0.7,
            )

            result = json.loads(result_str)

            # Yield text
            if result.get("reasoning"):
                yield TextDelta(result["reasoning"])

            if result.get("text"):
                yield TextDelta(result["text"])

            # Yield result event
            yield ResultEvent(
                finish_reason=result.get("finish_reason", "stop"),
                usage=result.get("usage", {}),
            )

        except Exception as e:
            yield ErrorBlock(str(e))
        finally:
            self._running = False

    def terminate(self) -> None:
        """Terminate the current request."""
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
        self._running = False

    @property
    def is_running(self) -> bool:
        """Whether the runner is currently processing a request."""
        return self._running
