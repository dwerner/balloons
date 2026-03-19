"""OpenAI-compatible runner for OpenRouter, llamacpp, and similar backends."""

import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, TYPE_CHECKING

from openai import AsyncOpenAI

from models import (
    Message, TextDelta, ResultEvent, InitEvent,
    TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, ArchiveBlock, ContextMode,
    ToolUseStartEvent, ToolInputDeltaEvent, ToolUseEvent, ToolResultEvent, SteeringInjectedEvent,
)
from .base_runner import BaseRunner, RunnerEvent, SteeringCapability
from .debug_log import debug_log, dump_failed_json, perf_marker, Category
from .tools import get_tools_for_request
from .tool_executor import execute_tool
from .tool_result import ToolExecutionResult

if TYPE_CHECKING:
    from session import Session


# Tool argument fields that MUST be strings (for UI rendering safety)
_STRING_FIELDS_BY_TOOL = {
    "Write": ["file_path", "content"],
    "Edit": ["file_path", "old_string", "new_string"],
    "Read": ["file_path"],
    "Bash": ["command", "description"],
    "Grep": ["pattern", "path", "glob", "type", "output_mode"],
    "Glob": ["pattern", "path"],
}


def _normalize_tool_arguments(tool_name: str, arguments: dict) -> dict:
    """Normalize tool arguments to ensure expected types.

    Some models (e.g., Qwen) may send non-string values for fields that
    should be strings. This converts them to prevent UI crashes.
    """
    if not isinstance(arguments, dict):
        return arguments

    string_fields = _STRING_FIELDS_BY_TOOL.get(tool_name, [])
    if not string_fields:
        return arguments

    normalized = arguments.copy()
    for field in string_fields:
        if field in normalized:
            value = normalized[field]
            if not isinstance(value, str):
                # Convert non-strings to JSON representation
                if value is None:
                    normalized[field] = ""
                elif isinstance(value, (list, dict)):
                    normalized[field] = json.dumps(value, indent=2)
                else:
                    normalized[field] = str(value)
                debug_log.warning(
                    f"Normalized non-string tool argument: {tool_name}.{field}",
                    category=Category.RUNNER,
                    details={
                        "original_type": type(value).__name__,
                        "original_preview": str(value)[:100] if value else None,
                    },
                )
    return normalized


def _dump_interaction(
    context: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    chunks: list[dict],
    error: str | None = None,
) -> Path | None:
    """Dump a full interaction to a debug file for analysis.

    Args:
        context: Short identifier (e.g., "tool_call_fail", "stream_error")
        model: Model name
        messages: Messages sent to the API
        tools: Tool definitions sent
        chunks: Raw chunks received
        error: Optional error message

    Returns:
        Path to the created file, or None on failure
    """
    try:
        debug_dir = Path.home() / ".balloons" / "debug" / "interactions"
        debug_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{context}_{timestamp}.json"
        filepath = debug_dir / filename

        interaction = {
            "timestamp": datetime.now().isoformat(),
            "context": context,
            "model": model,
            "error": error,
            "messages": messages,
            "tools": tools,
            "chunks": chunks,
            "chunk_count": len(chunks),
        }

        with open(filepath, "w") as f:
            json.dump(interaction, f, indent=2, default=str)

        debug_log.info(
            f"Dumped interaction to {filepath}",
            category=Category.RUNNER,
            details={"file": str(filepath), "context": context},
        )
        return filepath
    except Exception as e:
        debug_log.warning(
            f"Failed to dump interaction: {e}",
            category=Category.RUNNER,
        )
        return None


class OpenAICompatibleRunner(BaseRunner):
    """Runner for OpenAI-compatible APIs (OpenRouter, llamacpp, etc.)

    Uses the OpenAI Python SDK to stream responses. Supports tool calling
    for models that implement OpenAI's function calling API.

    System prompts are built per-turn to include fresh domain prompts and
    other dynamic context. The user_prompt (from backend config) is stored
    and combined with balloons tools and domain prompts each turn.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        user_prompt: str | None = None,
        context_window: int = 128000,
    ):
        """Initialize the runner.

        Args:
            base_url: API base URL (e.g., https://openrouter.ai/api/v1)
            api_key: API key for authentication
            model: Model identifier to use
            user_prompt: Optional user-provided system prompt (from backend config).
                         This is combined with balloons tools and domain prompts per-turn.
            context_window: Max context tokens for this backend
        """
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self._user_prompt = user_prompt  # Base prompt from backend config
        self.context_window = context_window
        self._running = False
        self._cancelled = False
        self._run_id = ""
        self._session: "Session | None" = None
        self._collected_chunks: list[dict] = []  # Raw chunks for dump on error

    @property
    def steering_capability(self) -> SteeringCapability:
        """OpenAI uses separate messages for tool results and user text."""
        return SteeringCapability.SEPARATE_MESSAGES

    def set_session(self, session: "Session") -> None:
        """Set the session for link tool execution.

        Args:
            session: The session to use for link navigation tools
        """
        self._session = session

    def _get_system_prompt(self) -> str | None:
        """Build the system prompt for this turn.

        Combines user prompt with balloons tools, domain prompts, and
        session-specific prompt files.
        Called per-turn to ensure domain prompts are fresh.

        Returns:
            Complete system prompt, or None if no content
        """
        from .prompt_builder import build_system_prompt
        return build_system_prompt(
            backend_type="openai",
            user_prompt=self._user_prompt,
            session=self._session,
        )

    def build_messages(self, messages: list[Message], new_prompt: str) -> list[dict]:
        """Convert internal Message format to OpenAI chat format.

        Args:
            messages: Message history
            new_prompt: New user prompt

        Returns:
            List of OpenAI chat message dicts
        """
        openai_messages = []

        # Build system prompt fresh for this turn (includes domain prompts)
        system_prompt = self._get_system_prompt()
        if system_prompt:
            openai_messages.append({
                "role": "system",
                "content": system_prompt,
            })

        for msg in messages:
            # Respect context mode
            if msg.context_mode == ContextMode.DROP:
                continue

            # Handle system messages (links, archives, metadata)
            if msg.role == "system":
                if msg.content_blocks:
                    content_parts = []
                    for block in msg.content_blocks:
                        if isinstance(block, ArchiveBlock):
                            archive_info = f"[Archived {block.message_count} turns: {block.summary}]"
                            archive_info += f"\n(Use read_archive tool with archive_id={block.archive_id} to retrieve full content)"
                            content_parts.append(archive_info)
                        elif isinstance(block, TextBlock) and block.text:
                            content_parts.append(block.text)
                    if content_parts:
                        # Include system metadata as a user message for context
                        openai_messages.append({
                            "role": "user",
                            "content": "\n\n".join(content_parts),
                        })
                elif msg.content:
                    openai_messages.append({
                        "role": "user",
                        "content": msg.content,
                    })
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
                image_blocks = []
                tool_use_blocks = []
                tool_result_blocks = []

                for block in msg.content_blocks:
                    if isinstance(block, TextBlock):
                        if block.text:
                            content_parts.append(block.text)
                    elif isinstance(block, ImageBlock):
                        # Collect images for OpenAI format
                        image_blocks.append(block)
                    elif isinstance(block, ToolUseBlock):
                        # Collect tool uses for proper OpenAI format
                        tool_use_blocks.append(block)
                    elif isinstance(block, ToolResultBlock):
                        # Collect tool results for proper OpenAI format
                        tool_result_blocks.append(block)
                    elif isinstance(block, InterruptionBlock):
                        # Mark that the response was interrupted
                        content_parts.append(f"[Interrupted: {block.reason}]")
                    elif isinstance(block, ErrorBlock):
                        # Mark that the response was truncated due to error
                        content_parts.append(f"[Error: {block.reason}]")
                    elif isinstance(block, ArchiveBlock):
                        # Format archive reference with summary
                        archive_info = f"[Archived {block.message_count} turns: {block.summary}]"
                        archive_info += f"\n(Use read_archive tool with archive_id={block.archive_id} to retrieve full content)"
                        content_parts.append(archive_info)

                # Handle assistant messages with tool calls (proper OpenAI format)
                if role == "assistant" and tool_use_blocks:
                    # Build tool_calls array
                    tool_calls = []
                    for block in tool_use_blocks:
                        tool_calls.append({
                            "id": block.id,
                            "type": "function",
                            "function": {
                                "name": block.name,
                                "arguments": json.dumps(block.input),
                            }
                        })

                    # Build assistant message with tool_calls
                    assistant_msg: dict = {
                        "role": "assistant",
                        "tool_calls": tool_calls,
                    }
                    # Include text content if any
                    if content_parts:
                        assistant_msg["content"] = "\n\n".join(content_parts)
                    else:
                        assistant_msg["content"] = None  # OpenAI requires this field

                    openai_messages.append(assistant_msg)

                # Handle tool results (as separate "tool" role messages)
                elif role == "user" and tool_result_blocks:
                    # Each tool result becomes a separate message
                    for block in tool_result_blocks:
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": block.tool_use_id,
                            "content": block.content or "",
                        })
                    # Also include any text content from user
                    if content_parts:
                        openai_messages.append({
                            "role": "user",
                            "content": "\n\n".join(content_parts),
                        })

                # Handle images
                elif image_blocks:
                    content_array = []
                    if content_parts:
                        content_array.append({
                            "type": "text",
                            "text": "\n\n".join(content_parts),
                        })
                    for img in image_blocks:
                        content_array.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"file://{img.file_path}",
                            }
                        })
                    openai_messages.append({
                        "role": role,
                        "content": content_array,
                    })

                # Regular text content
                elif content_parts:
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
            category=Category.RUNNER,
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
            context_window=self.context_window,
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

                # Client-only tools - handled entirely by UI, no backend execution
                # These tools are intercepted at the app/UI layer from the tool_use event
                CLIENT_ONLY_TOOLS = {"play_midi", "propose_fork", "propose_merge"}

                # Execute each tool and add results
                # Check queue after EACH tool for boundary-aware steering
                accumulated_steering: list[str] = []

                for tc in tool_calls:
                    if self._cancelled:
                        break

                    tool_name = tc["name"]

                    # Skip client-only tools - UI handles them from the tool_use event
                    if tool_name in CLIENT_ONLY_TOOLS:
                        debug_log.info(
                            f"Skipping client-only tool: {tool_name}",
                            category=Category.RUNNER,
                            run_id=self._run_id,
                        )
                        # Don't add to openai_messages - no result for LLM
                        continue

                    tool_result = await execute_tool(
                        tool_name,
                        tc["arguments"],
                        working_dir or ".",
                        self._run_id,
                        session=self._session,
                    )

                    # Handle both legacy tuple and new ToolExecutionResult
                    if isinstance(tool_result, ToolExecutionResult):
                        result = tool_result.result
                        is_error = tool_result.is_error
                        # Check if domain tools changed (load_domain/unload_domain)
                        if tool_result.domains_changed:
                            tools = get_tools_for_request(allowed_tools, disable_tools)
                            debug_log.info(
                                f"Domain tools changed, refreshed tool list",
                                category=Category.RUNNER,
                                details={"tool_count": len(tools) if tools else 0},
                                run_id=self._run_id,
                            )
                    else:
                        result, is_error = tool_result

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

                    # Check for steering after EACH tool result
                    # This enables boundary-aware injection (like Claude Code's h2A queue)
                    if self._injection_callback:
                        steering = await self._injection_callback()
                        if steering:
                            accumulated_steering.append(steering)
                            debug_log.info(
                                f"Captured steering after tool {tool_name}",
                                category=Category.RUNNER,
                                details={"steering_len": len(steering)},
                                run_id=self._run_id,
                            )
                            # Yield event so UI can display the injected message
                            yield SteeringInjectedEvent(
                                content=steering,
                                injected_at_tool_id=tc["id"],
                            )

                # Add accumulated steering as a user message after all tool results
                # OpenAI uses SEPARATE_MESSAGES - steering follows tool results
                if accumulated_steering:
                    combined_steering = "\n\n".join(accumulated_steering)
                    debug_log.info(
                        f"Adding accumulated steering as user message",
                        category=Category.RUNNER,
                        details={"num_messages": len(accumulated_steering), "total_len": len(combined_steering)},
                        run_id=self._run_id,
                    )
                    openai_messages.append({
                        "role": "user",
                        "content": combined_steering,
                    })

            debug_log.info(
                f"OpenAI stream complete",
                category=Category.RUNNER,
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
                context_window=self.context_window,
            )

        except Exception as e:
            debug_log.error(
                f"OpenAI stream error: {e}",
                category=Category.RUNNER,
                details={
                    "error_type": type(e).__name__,
                    "error_str": str(e),
                },
                run_id=self._run_id,
            )
            # Dump full interaction for debugging
            _dump_interaction(
                context="stream_error",
                model=self.model,
                messages=openai_messages,
                tools=tools,
                chunks=self._collected_chunks,
                error=f"{type(e).__name__}: {e}",
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
        import time

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

        # Log request payload for debugging
        debug_log.debug(
            f"OpenAI request payload",
            category=Category.RUNNER,
            details={
                "model": self.model,
                "message_count": len(openai_messages),
                "last_messages": [
                    {
                        "role": m.get("role"),
                        "content_preview": str(m.get("content", ""))[:200] if m.get("content") else None,
                        "has_tool_calls": "tool_calls" in m,
                    }
                    for m in openai_messages[-3:]
                ],
                "tools_count": len(tools) if tools else 0,
                "tool_names": [t["function"]["name"] for t in tools] if tools else [],
            },
            run_id=self._run_id,
        )

        # Log full tool definitions at TRACE level (filtered by debug_log.min_level)
        if tools:
            debug_log.trace(
                "Full tool definitions",
                category=Category.RUNNER,
                details={"tools": tools},
                run_id=self._run_id,
            )

        api_start = time.perf_counter()
        first_chunk_time = None
        self._collected_chunks = []  # Reset chunk collection

        stream = await self.client.chat.completions.create(**kwargs)

        async for chunk in stream:
            if self._cancelled:
                break

            # Collect chunks for potential error dumps, and log at TRACE level
            try:
                chunk_dict = chunk.model_dump()
                self._collected_chunks.append(chunk_dict)
                debug_log.trace(
                    "Raw OpenAI chunk",
                    category=Category.RUNNER,
                    details={"chunk": chunk_dict},
                    run_id=self._run_id,
                )
            except Exception as e:
                debug_log.trace(
                    f"Failed to serialize chunk: {e}",
                    category=Category.RUNNER,
                    run_id=self._run_id,
                )

            # Track first chunk timing
            if first_chunk_time is None:
                first_chunk_time = time.perf_counter()
                ttfc_ms = (first_chunk_time - api_start) * 1000
                perf_marker(
                    "openai.first_chunk",
                    model=self.model,
                    ttfc_ms=round(ttfc_ms, 1),
                    run_id=self._run_id,
                )

            # Extract usage from final chunk
            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens

            if not chunk.choices:
                # Log chunks without choices (might indicate issues)
                debug_log.trace(
                    "Chunk without choices",
                    category=Category.RUNNER,
                    details={"has_usage": chunk.usage is not None},
                    run_id=self._run_id,
                )
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
                # Log raw tool_calls delta for debugging
                debug_log.debug(
                    "Raw tool_calls delta",
                    category=Category.RUNNER,
                    details={
                        "tool_calls": [
                            {
                                "index": tc.index,
                                "id": tc.id,
                                "type": tc.type,
                                "function_name": tc.function.name if tc.function else None,
                                "arguments_chunk": tc.function.arguments if tc.function else None,
                                "arguments_len": len(tc.function.arguments) if tc.function and tc.function.arguments else 0,
                            }
                            for tc in delta.tool_calls
                        ],
                    },
                    run_id=self._run_id,
                )
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
            # Log the raw arguments before parsing (useful for debugging weird encodings)
            debug_log.debug(
                f"Finalizing tool call: {tc['name']}",
                category=Category.RUNNER,
                details={
                    "tool_id": tc["id"],
                    "tool_name": tc["name"],
                    "arguments_json_len": len(tc["arguments_json"]),
                    "arguments_json_preview": tc["arguments_json"][:500] if tc["arguments_json"] else "",
                },
                run_id=self._run_id,
            )

            try:
                arguments = json.loads(tc["arguments_json"]) if tc["arguments_json"] else {}
            except json.JSONDecodeError as e:
                raw_args = tc["arguments_json"]
                dump_path = dump_failed_json(raw_args, "tool_input")
                debug_log.warning(
                    f"Tool input JSON decode error: {e}" + (f" (dumped to {dump_path})" if dump_path else ""),
                    category=Category.RUNNER,
                    details={
                        "tool_name": tc["name"],
                        "dump_file": str(dump_path) if dump_path else None,
                        "raw_preview": raw_args[:200] if raw_args else "",
                        "raw_len": len(raw_args) if raw_args else 0,
                    },
                    run_id=self._run_id,
                )

                # Dump full interaction for debugging
                _dump_interaction(
                    context="tool_json_parse_fail",
                    model=self.model,
                    messages=openai_messages,
                    tools=tools,
                    chunks=self._collected_chunks,
                    error=f"JSON decode error for tool {tc['name']}: {e}",
                )

                arguments = {"raw": raw_args, "_dump_file": str(dump_path) if dump_path else None}

            # Normalize arguments to ensure expected types (e.g., strings for Write.content)
            arguments = _normalize_tool_arguments(tc["name"], arguments)

            finalized_tool_calls.append({
                "id": tc["id"],
                "name": tc["name"],
                "arguments": arguments,
            })

            # Log successful parse
            debug_log.debug(
                f"Tool call parsed: {tc['name']}",
                category=Category.RUNNER,
                details={
                    "tool_id": tc["id"],
                    "tool_name": tc["name"],
                    "argument_keys": list(arguments.keys()) if isinstance(arguments, dict) else "not_dict",
                },
                run_id=self._run_id,
            )

            # Emit tool use complete event
            events.append(ToolUseEvent(
                tool_use_id=tc["id"],
                tool_name=tc["name"],
                tool_input=arguments,
            ))

        # Log API call completion timing
        api_elapsed_ms = (time.perf_counter() - api_start) * 1000
        perf_marker(
            "openai.api_complete",
            model=self.model,
            elapsed_ms=round(api_elapsed_ms, 1),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_calls=len(finalized_tool_calls),
            run_id=self._run_id,
        )

        # Detect embedded tool calls in content (common with some models)
        # These patterns indicate the model is trying to call tools but not using the API
        embedded_patterns = [
            (r'<function_call>', "XML function_call tag"),
            (r'<tool_call>', "XML tool_call tag"),
            (r'```json\s*\{\s*"name"\s*:', "JSON tool block in code fence"),
            (r'\{\s*"function"\s*:\s*\{', "function object in content"),
            (r'\{\s*"tool"\s*:\s*"', "tool field in content"),
            (r'Action:\s*\w+\[', "Action pattern (e.g., Action: Search[query])"),
            (r'\b(chess_\w+|supervisor_\w+|Read|Write|Edit|Bash|Glob|Grep)\s*\(\s*\w+\s*=', "Python-style function call"),
        ]

        for pattern, description in embedded_patterns:
            if re.search(pattern, content_buffer):
                debug_log.warning(
                    f"Possible embedded tool call detected: {description}",
                    category=Category.RUNNER,
                    details={
                        "pattern": pattern,
                        "description": description,
                        "content_preview": content_buffer[:500],
                        "content_len": len(content_buffer),
                        "model": self.model,
                        "had_tool_calls": len(finalized_tool_calls) > 0,
                    },
                    run_id=self._run_id,
                )
                # Dump interaction for analysis if no proper tool calls were made
                if len(finalized_tool_calls) == 0:
                    _dump_interaction(
                        context="embedded_tool_call",
                        model=self.model,
                        messages=openai_messages,
                        tools=tools,
                        chunks=self._collected_chunks,
                        error=f"Detected {description} in content",
                    )
                break  # Only warn once per response

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
