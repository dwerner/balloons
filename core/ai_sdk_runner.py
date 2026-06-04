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
from .tools import get_tools_for_request
from .tool_executor import execute_tool
from .tool_result import ToolExecutionResult
from .debug_log import debug_log, Category

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
        self._cancelled = False
        self._run_id: str | None = None
        self._session: "Session | None" = None
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

    def set_session(self, session: "Session | None") -> None:
        """Set the session for accessing enabled tools and other session state."""
        self._session = session

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
            allowed_tools: List of tool names to allow, or None for all
            working_dir: Working directory for tool execution
            disable_tools: If True, disable all tools

        Yields:
            Events from the model (text deltas, reasoning, tool use, results)
        """
        self._running = True
        self._cancelled = False
        self._run_id = f"ai-sdk-{id(self)}-{asyncio.get_event_loop().time()}"

        try:
            # Get tools for this request
            tools = get_tools_for_request(
                allowed_tools=allowed_tools,
                disable_tools=disable_tools,
                include_balloon_tools=True,
                include_supervisor_tools=True,
                include_goal_tools=True,
                include_midi_tools=True,
                include_debug_tools=True,
                include_lsp_tools=True,
                include_domain_tools=True,
                include_browser_tools=True,
            )

            debug_log.info(
                f"AI SDK request to {self.model}",
                category=Category.RUNNER,
                details={
                    "message_count": len(messages) + 1,
                    "prompt_len": len(prompt),
                    "tools_enabled": tools is not None,
                    "tool_count": len(tools) if tools else 0,
                },
                run_id=self._run_id,
            )

            # Emit init event
            yield InitEvent(
                model=self.model,
                session_id=self._session.id if self._session else "",
                context_window=self.context_window,
                raw={},
            )

              # Tool execution loop - continue until model stops calling tools
            while True:
                if self._cancelled:
                    break

                # Stream one response
                result, events = await self._stream_one_response(
                    messages, prompt, tools, working_dir
                )

                # Yield all events
                for event in events:
                    yield event

                # Check if we have tool calls to execute
                tool_calls = result.get("tool_calls", [])
                if not tool_calls:
                    # No tool calls, we're done
                    break

                # Execute each tool and add results
                for tc in tool_calls:
                    if self._cancelled:
                        break

                    tool_name = tc["name"]
                    tool_id = tc["id"]
                    tool_args = tc["arguments"]

                    # Client-only tools - UI handles them from the tool_use event
                    CLIENT_ONLY_TOOLS = {"play_midi", "propose_fork", "propose_merge"}

                    if tool_name in CLIENT_ONLY_TOOLS:
                        # Yield a tool result event for UI
                        yield ToolResultEvent(
                            tool_use_id=tool_id,
                            result=f"[{tool_name}] Handled by UI",
                        )
                        continue

                    async def emit_tool_output(stream_name: str, delta: str) -> None:
                        if not delta or self._tool_event_callback is None:
                            return
                        await self._tool_event_callback(
                            ToolResultDeltaEvent(
                                tool_use_id=tool_id,
                                delta=delta,
                                stream=stream_name,
                                session_id=self._session.id if self._session else "",
                                exchange_id="",
                                turn_id="",
                                tool_name=tool_name,
                            )
                        )

                    tool_result = await execute_tool(
                        tool_name,
                        tool_args,
                        working_dir or ".",
                        self._run_id,
                        session=self._session,
                        output_callback=emit_tool_output,
                    )

                    # Handle both legacy tuple and new ToolExecutionResult
                    if isinstance(tool_result, ToolExecutionResult):
                        result_text = tool_result.result
                        is_error = tool_result.is_error
                        # Check if domain tools changed (load_domain/unload_domain)
                        if tool_result.domains_changed:
                            tools = get_tools_for_request(
                                allowed_tools=allowed_tools,
                                disable_tools=disable_tools,
                                include_balloon_tools=True,
                                include_supervisor_tools=True,
                                include_goal_tools=True,
                                include_midi_tools=True,
                                include_debug_tools=True,
                                include_lsp_tools=True,
                                include_domain_tools=True,
                                include_browser_tools=True,
                            )
                    else:
                        result_text, is_error = tool_result

                    # Yield tool result event
                    yield ToolResultEvent(
                        tool_use_id=tool_id,
                        result=result_text,
                    )

                    # Check for steering after tool execution
                    if self._injection_callback:
                        steering_msg = await self._injection_callback()
                        if steering_msg:
                            yield SteeringInjectedEvent(steering_msg)
                            # Add steering message to conversation
                            messages.append(Message("user", steering_msg))
                            # Break to restart generation with steering
                            break

                else:
                    # No break from tool loop, continue with next generation
                    # Add tool calls to messages
                    tool_call_blocks = []
                    for tc in tool_calls:
                        tool_call_blocks.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": tc["arguments"],
                        })

                    messages.append(Message("assistant", tool_call_blocks))
                    continue

                # Break from tool loop due to steering or cancellation
                break

            # Yield final result event
            usage = result.get("usage", {})
            yield ResultEvent(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                total_cost_usd=0.0,
                context_window=self.context_window,
                raw={"finish_reason": result.get("finish_reason", "stop")},
            )

        except Exception as e:
            yield ErrorBlock(str(e))
        finally:
            self._running = False

    async def _stream_one_response(
        self,
        messages: list[Message],
        prompt: str,
        tools: list[dict] | None,
        working_dir: str | None,
    ) -> tuple[dict, list[RunnerEvent]]:
        """Stream a single response from the model.

        Args:
            messages: Message history for context
            prompt: The new prompt to send
            tools: List of tool definitions, or None
            working_dir: Working directory (not used)

        Returns:
            Tuple of (result_dict, events_list) where result_dict contains
            'text', 'reasoning', 'tool_calls', 'usage', 'finish_reason'
            and events_list contains all events for streaming.
        """
        # Build message list
        py_messages = []

        # Add system prompt if configured
        if self.user_prompt:
            py_messages.append(self._PyMessage("system", self.user_prompt))

           # Add conversation history
        for msg in messages:
            role = msg.role
            if role in ("system", "user", "assistant"):
                if isinstance(msg.content, str):
                    py_messages.append(self._PyMessage(role, msg.content))
                elif isinstance(msg.content, list):
                    # Handle content blocks - convert to complex message format
                    from ai_sdk_openai_compatible_py import PyImageContent, PyReasoningContent, PyToolCallContent
                    
                    content_parts = []
                    for block in msg.content:
                        if hasattr(block, 'type'):
                            if block.type == "text":
                                content_parts.append({
                                    "type": "text",
                                    "text": block.text,
                                })
                            elif block.type == "image":
                                # Convert image to base64 if needed
                                image_data = block.source.get("data", "") if hasattr(block, 'source') else ""
                                media_type = block.source.get("media_type", "image/png") if hasattr(block, 'source') else "image/png"
                                content_parts.append({
                                    "type": "image",
                                    "data": image_data,
                                    "media_type": media_type,
                                })
                            elif block.type == "tool_use":
                                import json
                                content_parts.append({
                                    "type": "tool_call",
                                    "tool_call_id": block.id,
                                    "tool_name": block.name,
                                    "input": json.dumps(block.input) if hasattr(block, 'input') else "{}",
                                })
                            elif block.type == "reasoning":
                                content_parts.append({
                                    "type": "reasoning",
                                    "text": block.text if hasattr(block, 'text') else "",
                                })
                    
                    if content_parts:
                        py_messages.append(self._PyMessage(role, content_parts))

        # Add current prompt
        py_messages.append(self._PyMessage("user", prompt))

        # Create model instance
        model = self._create_chat_model(self.base_url, self.model, self.api_key)

        # Accumulation variables
        result = {
            "text": "",
            "reasoning": "",
            "tool_calls": [],
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "finish_reason": "stop",
        }
        events: list[RunnerEvent] = []
        
        # Track current tool call being accumulated
        current_tool_id: str | None = None
        current_tool_name: str | None = None
        current_tool_args: dict = {}

        try:
            # Convert tools to Rust format
            from ai_sdk_openai_compatible_py import PyToolDefinition
            rust_tools = None
            if tools:
                rust_tools = []
                for tool in tools:
                    func = tool.get("function", {})
                    params = func.get("parameters", {})
                    rust_tools.append(PyToolDefinition(
                        name=func.get("name", ""),
                        description=func.get("description"),
                        parameters=json.dumps(params),
                    ))
 

            stream = await model.stream(
                messages=py_messages,
                max_tokens=min(4000, self.context_window // 4),
                temperature=0.7,
                tools=rust_tools,
                tool_choice="auto",
            )

            async for chunk in stream:
                if self._cancelled:
                    break

                if chunk == "[DONE]":
                    break

                try:
                    data = json.loads(chunk)
                    chunk_type = data.get("type", "")
                    
  

                    if chunk_type == "text":
                        delta = data.get("delta", "")
                        result["text"] += delta
                        events.append(TextDelta(delta))

                    elif chunk_type == "reasoning":
                        delta = data.get("delta", "")
                        result["reasoning"] += delta
                        events.append(TextDelta(delta))

                    elif chunk_type == "tool_call_start":
                        tool_id = data.get("tool_id", "")
                        current_tool_id = tool_id
                        current_tool_name = None
                        current_tool_args_str = ""
                        events.append(ToolUseStartEvent(tool_id=tool_id))

                    elif chunk_type == "tool_call_delta":
                        # Accumulate tool call data
                        # Name might come in the first delta or separately
                        name = data.get("name")
                        if name:
                            current_tool_name = name
                        
                        # Arguments come as incremental JSON strings
                        arguments = data.get("arguments", "")
                        if arguments:
                            current_tool_args_str += arguments
                        
                        # If we have tool_id in this delta, update current_tool_id
                        tool_id = data.get("tool_id", "")
                        if tool_id:
                            current_tool_id = tool_id

                    elif chunk_type == "tool_call_end":
                        tool_id = data.get("tool_id", "")
                        # Use accumulated data from tool_call_delta
                        tool_name = current_tool_name
                        tool_args_str = current_tool_args_str
                        
                        # Parse the accumulated arguments JSON
                        tool_args = {}
                        if tool_args_str:
                            try:
                                tool_args = json.loads(tool_args_str)
                            except json.JSONDecodeError:
                                # If parsing fails, use the raw string
                                tool_args = {"raw": tool_args_str}
                        
                        if tool_name:
                            result["tool_calls"].append({
                                "id": current_tool_id,
                                "name": tool_name,
                                "arguments": tool_args,
                            })
                            events.append(ToolUseEvent(
                                tool_use_id=current_tool_id,
                                name=tool_name,
                                input=tool_args,
                            ))
                        
                        # Reset for next tool call
                        current_tool_id = None
                        current_tool_name = None
                        current_tool_args_str = ""

                    elif chunk_type == "finish":
                        # If we have pending tool call data, finalize it
                        if current_tool_name and current_tool_args_str:
                            tool_args = {}
                            try:
                                tool_args = json.loads(current_tool_args_str)
                            except json.JSONDecodeError:
                                tool_args = {"raw": current_tool_args_str}
                            
                            if current_tool_name:
                                result["tool_calls"].append({
                                    "id": current_tool_id,
                                    "name": current_tool_name,
                                    "arguments": tool_args,
                                })
                                events.append(ToolUseEvent(
                                    tool_use_id=current_tool_id,
                                    name=current_tool_name,
                                    input=tool_args,
                                ))
                            
                            # Reset for next tool call
                            current_tool_id = None
                            current_tool_name = None
                            current_tool_args_str = ""
                        
                        usage = data.get("usage", {})
                        result["usage"]["input_tokens"] = usage.get("input_tokens", 0)
                        result["usage"]["output_tokens"] = usage.get("output_tokens", 0)
                        result["usage"]["total_tokens"] = (
                            result["usage"]["input_tokens"] + result["usage"]["output_tokens"]
                        )

                except json.JSONDecodeError:
                    # Skip malformed chunks
                    continue

        except Exception as e:
            # Handle streaming errors
            events.append(ErrorBlock(f"Stream error: {str(e)}"))

        return result, events

    def terminate(self) -> None:
        """Terminate the current request."""
        self._cancelled = True
        self._running = False

    @property
    def is_running(self) -> bool:
        """Whether the runner is currently processing a request."""
        return self._running
