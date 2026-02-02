"""OpenAI-compatible runner for OpenRouter, llamacpp, and similar backends."""

import asyncio
import json
import uuid
from typing import AsyncIterator

from openai import AsyncOpenAI

from models import (
    Message, TextDelta, ResultEvent, InitEvent,
    TextBlock, ToolUseBlock, ToolResultBlock, ContextMode,
    ToolUseStartEvent, ToolInputDeltaEvent, ToolUseEvent, ToolResultEvent,
)
from .base_runner import BaseRunner, RunnerEvent
from .debug_log import debug_log
from .tools import get_tools_for_request
from .tool_executor import execute_tool


class OpenAICompatibleRunner(BaseRunner):
    """Runner for OpenAI-compatible APIs (OpenRouter, llamacpp, etc.)

    Uses the OpenAI Python SDK to stream responses. Supports tool calling
    for models that implement OpenAI's function calling API.
    """

    def __init__(self, base_url: str, api_key: str, model: str, system_prompt: str | None = None):
        """Initialize the runner.

        Args:
            base_url: API base URL (e.g., https://openrouter.ai/api/v1)
            api_key: API key for authentication
            model: Model identifier to use
            system_prompt: Optional system prompt content to prepend to conversations
        """
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt
        self._running = False
        self._cancelled = False
        self._run_id = ""

    def build_messages(self, messages: list[Message], new_prompt: str) -> list[dict]:
        """Convert internal Message format to OpenAI chat format.

        Args:
            messages: Message history
            new_prompt: New user prompt

        Returns:
            List of OpenAI chat message dicts
        """
        openai_messages = []

        # Add system prompt if configured
        if self.system_prompt:
            openai_messages.append({
                "role": "system",
                "content": self.system_prompt,
            })

        for msg in messages:
            # Respect context mode
            if msg.context_mode == ContextMode.DROP:
                continue

            role = "user" if msg.role == "user" else "assistant"

            # Use summary if in SUMMARIZE mode and summary exists
            if msg.context_mode == ContextMode.SUMMARIZE and msg.summary:
                openai_messages.append({
                    "role": role,
                    "content": f"[Summary] {msg.summary}",
                })
                continue

            # Build content from blocks if available
            if msg.content_blocks:
                content_parts = []
                for block in msg.content_blocks:
                    if isinstance(block, TextBlock):
                        if block.text:
                            content_parts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        # Format tool use so the model knows what was done
                        input_str = json.dumps(block.input, indent=2)
                        content_parts.append(f"[Tool Use: {block.name}]\n{input_str}")
                    elif isinstance(block, ToolResultBlock):
                        # Format tool result
                        error_prefix = "[Error] " if block.is_error else ""
                        content_parts.append(f"[Tool Result]{error_prefix}\n{block.content}")

                if content_parts:
                    openai_messages.append({
                        "role": role,
                        "content": "\n\n".join(content_parts),
                    })
            else:
                # Fallback to plain content
                openai_messages.append({
                    "role": role,
                    "content": msg.content,
                })

        # Add the new user prompt
        openai_messages.append({
            "role": "user",
            "content": new_prompt,
        })

        return openai_messages

    async def stream_response(
        self,
        messages: list[Message],
        prompt: str,
        allowed_tools: list[str] | None = None,
        working_dir: str | None = None,
        disable_tools: bool = False,
    ) -> AsyncIterator[RunnerEvent]:
        """Stream a response from the OpenAI-compatible API.

        Args:
            messages: Message history for context
            prompt: The new prompt to send
            allowed_tools: List of tool names to allow, or None for all
            working_dir: Working directory for tool execution
            disable_tools: If True, disable all tools

        Yields:
            TextDelta, ToolUseEvent, ToolResultEvent, InitEvent, and ResultEvent
        """
        self._running = True
        self._cancelled = False
        self._run_id = f"openai-{id(self)}"

        # Convert messages to OpenAI format
        openai_messages = self.build_messages(messages, prompt)

        # Get tools for this request
        tools = get_tools_for_request(allowed_tools, disable_tools)

        debug_log.info(
            f"OpenAI request to {self.model}",
            category="process",
            details={
                "message_count": len(openai_messages),
                "prompt_len": len(prompt),
                "tools_enabled": tools is not None,
            },
            run_id=self._run_id,
        )

        # Emit init event
        yield InitEvent(
            model=self.model,
            session_id="",  # No session concept for OpenAI
            context_window=128000,  # Default assumption, varies by model
        )

        total_input_tokens = 0
        total_output_tokens = 0

        try:
            # Tool execution loop - continue until model stops calling tools
            while True:
                if self._cancelled:
                    break

                # Stream one response
                tool_calls_data, input_tokens, output_tokens = await self._stream_one_response(
                    openai_messages, tools
                )

                total_input_tokens += input_tokens
                total_output_tokens += output_tokens

                # Yield all events from the stream
                for event in tool_calls_data.get("events", []):
                    yield event

                # Check if we have tool calls to execute
                tool_calls = tool_calls_data.get("tool_calls", [])
                if not tool_calls:
                    # No tool calls, we're done
                    break

                # Execute tools and continue the loop
                assistant_content = tool_calls_data.get("content", "")

                # Add assistant message with tool calls
                assistant_msg = {
                    "role": "assistant",
                    "content": assistant_content or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"]),
                            }
                        }
                        for tc in tool_calls
                    ]
                }
                openai_messages.append(assistant_msg)

                # Execute each tool and add results
                for tc in tool_calls:
                    if self._cancelled:
                        break

                    result, is_error = await execute_tool(
                        tc["name"],
                        tc["arguments"],
                        working_dir or ".",
                        self._run_id,
                    )

                    # Yield tool result event
                    yield ToolResultEvent(
                        tool_use_id=tc["id"],
                        result=result,
                    )

                    # Add tool result to messages for next API call
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })

            debug_log.info(
                f"OpenAI stream complete",
                category="process",
                details={
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                },
                run_id=self._run_id,
            )

            # Emit result event (cost tracking not available for non-Claude)
            yield ResultEvent(
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                total_cost_usd=0.0,  # Unknown for non-Claude backends
                context_window=128000,
            )

        except Exception as e:
            debug_log.error(
                f"OpenAI stream error: {e}",
                category="process",
                run_id=self._run_id,
            )
            raise

        finally:
            self._running = False
            self._run_id = ""

    async def _stream_one_response(
        self,
        openai_messages: list[dict],
        tools: list[dict] | None,
    ) -> tuple[dict, int, int]:
        """Stream a single response from the API.

        Returns:
            Tuple of (data_dict, input_tokens, output_tokens)
            data_dict contains:
                - events: list of events to yield
                - tool_calls: list of tool calls (if any)
                - content: text content (if any)
        """
        events = []
        tool_calls = {}  # id -> {id, name, arguments_json}
        content_buffer = ""
        input_tokens = 0
        output_tokens = 0

        # Build API call kwargs
        kwargs = {
            "model": self.model,
            "messages": openai_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools

        stream = await self.client.chat.completions.create(**kwargs)

        async for chunk in stream:
            if self._cancelled:
                break

            # Extract usage from final chunk
            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens

            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            if not delta:
                continue

            # Handle text content
            if delta.content:
                content_buffer += delta.content
                events.append(TextDelta(text=delta.content))
                await asyncio.sleep(0)  # Yield to event loop

            # Handle tool calls
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    tc_id = tc_delta.id
                    tc_index = tc_delta.index

                    # Use index as key since id might not be in every delta
                    if tc_index not in tool_calls:
                        # New tool call starting
                        tool_calls[tc_index] = {
                            "id": tc_id or f"call_{uuid.uuid4().hex[:8]}",
                            "name": "",
                            "arguments_json": "",
                        }

                    tc = tool_calls[tc_index]

                    # Update id if provided
                    if tc_delta.id:
                        tc["id"] = tc_delta.id

                    # Update function name if provided
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc["name"] = tc_delta.function.name
                            # Emit tool use start event
                            events.append(ToolUseStartEvent(
                                tool_use_id=tc["id"],
                                tool_name=tc["name"],
                            ))

                        # Accumulate arguments JSON
                        if tc_delta.function.arguments:
                            tc["arguments_json"] += tc_delta.function.arguments
                            # Emit input delta event
                            events.append(ToolInputDeltaEvent(
                                tool_use_id=tc["id"],
                                partial_json=tc_delta.function.arguments,
                            ))

        # Finalize tool calls - parse arguments JSON
        finalized_tool_calls = []
        for tc in tool_calls.values():
            try:
                arguments = json.loads(tc["arguments_json"]) if tc["arguments_json"] else {}
            except json.JSONDecodeError:
                arguments = {"raw": tc["arguments_json"]}

            finalized_tool_calls.append({
                "id": tc["id"],
                "name": tc["name"],
                "arguments": arguments,
            })

            # Emit tool use complete event
            events.append(ToolUseEvent(
                tool_use_id=tc["id"],
                tool_name=tc["name"],
                tool_input=arguments,
            ))

        return {
            "events": events,
            "tool_calls": finalized_tool_calls,
            "content": content_buffer,
        }, input_tokens, output_tokens

    def terminate(self) -> None:
        """Terminate the running request."""
        self._cancelled = True
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running
