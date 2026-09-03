"""AI SDK runner using Rust ai-sdk-openai-compatible crate via Python bindings.

This runner uses the high-performance Rust implementation of the OpenAI-compatible
protocol, providing better streaming support and native reasoning/text separation.
"""

from pathlib import Path
from datetime import datetime
import asyncio
import json
from typing import AsyncIterator, TYPE_CHECKING

# Timeout constants
STREAM_READLINE_TIMEOUT = 30.0  # Hard timeout for stream reading
TOOL_EXECUTION_TIMEOUT = 300.0  # Soft timeout for tool execution (warn only)


def dump_failed_context(
    context: str,
    model: str,
    messages: list,
    error: str,
    run_id: str = "",
) -> Path | None:
    """Dump failed context to debug file.
    
    Args:
        context: Context identifier (e.g., "stream_error", "tool_parse_error")
        model: Model identifier
        messages: Messages that were sent
        error: Error description
        run_id: For logging
    
    Returns:
        Path to dump file, or None on failure
    """
    try:
        debug_dir = Path.home() / ".balloons" / "dumps"
        debug_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"ai_sdk_{context}_{timestamp}.json"
        filepath = debug_dir / filename
        
        dump_data = {
            "timestamp": datetime.now().isoformat(),
            "context": context,
            "model": model,
            "run_id": run_id,
            "error": error,
            "messages": [
                {
                    "role": getattr(msg, 'role', 'unknown'),
                    "content_type": "text" if isinstance(getattr(msg, 'content', None), str) else "structured",
                    "content_preview": str(getattr(msg, 'content', ''))[:500] if isinstance(getattr(msg, 'content', None), str) else "structured blocks",
                }
                for msg in messages
            ],
        }
        
        filepath.write_text(json.dumps(dump_data, indent=2))
        
        debug_log.error(
            f"Dumped failed context to {filepath}",
            category=Category.RUNNER,
            run_id=run_id,
        )
        
        return filepath
    except Exception as e:
        debug_log.error(
            f"Failed to write error dump: {e}",
            category=Category.RUNNER,
            run_id=run_id,
        )
        return None

from ai_sdk_openai_compatible_py import (
    create_chat_model_py,
    Message as RustMessage,
    ToolDefinition,
    ImageContent,
    ReasoningContent,
    ToolCallContent,
    StreamPart,
    tool_result_message,
)

from models import (
    Message, TextDelta, ThinkingDelta, ResultEvent, InitEvent, ContextTokensEvent,
    TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, ArchiveBlock, ContextMode,
    ToolUseStartEvent, ToolInputDeltaEvent, ToolUseEvent, ToolResultDeltaEvent, ToolResultEvent, SteeringInjectedEvent,
    RawEvent,
)
from .base_runner import BaseRunner, RunnerEvent, SteeringCapability
from .tools import get_tools_for_request
from .tool_executor import execute_tool
from .tool_result import ToolExecutionResult
from .debug_log import debug_log, Category
from .context import ContextBuilder, OutputFormat
from tokenizer import count_tokens

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
        self._pending_images: list[ImageBlock] = []
        self._error_dumps: list[tuple[str, str]] = []

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
        images: list[ImageBlock] | None = None,
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
                    messages, prompt, tools, working_dir, images
                )

                # Yield all events
                for event in events:
                    yield event

                # Check if we have tool calls to execute
                tool_calls = result.tool_calls if hasattr(result, 'tool_calls') else result.get("tool_calls", [])
                if not tool_calls:
                    # No tool calls, we're done
                    break

                # Execute each tool and add results
                for tc in tool_calls:
                    if self._cancelled:
                        break

                    tool_name = tc.name if hasattr(tc, 'name') else tc["name"]
                    tool_id = tc.id if hasattr(tc, 'id') else tc["id"]
                    tool_args = tc.arguments if hasattr(tc, 'arguments') else tc["arguments"]

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

                    # Add tool result to messages for next model turn
                    from models import ToolResultBlock
                    tool_result_block = ToolResultBlock(
                        tool_use_id=tool_id,
                        content=result_text,
                        is_error=is_error,
                    )
                    # Find or create tool message for this tool result
                    tool_message_found = False
                    for msg in messages:
                        if msg.role == "tool" and msg.content_blocks:
                            for block in msg.content_blocks:
                                if hasattr(block, 'tool_use_id') and block.tool_use_id == tool_id:
                                    block.content = result_text
                                    block.is_error = is_error
                                    tool_message_found = True
                                    break
                        if tool_message_found:
                            break
                    
                    if not tool_message_found:
                        messages.append(Message("tool", "", content_blocks=[tool_result_block]))

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
                            "id": tc.id if hasattr(tc, 'id') else tc["id"],
                            "name": tc.name if hasattr(tc, 'name') else tc["name"],
                            "input": tc.arguments if hasattr(tc, 'arguments') else tc["arguments"],
                        })

                    messages.append(Message("assistant", tool_call_blocks))
                    continue

                # Break from tool loop due to steering or cancellation
                break

             # Yield final result event
            usage = result.usage if hasattr(result, 'usage') else result.get("usage", {})
            finish_reason = result.finish_reason if hasattr(result, 'finish_reason') else result.get("finish_reason", "stop")
            yield ResultEvent(
                input_tokens=usage.input_tokens if hasattr(usage, 'input_tokens') else usage.get("input_tokens", 0),
                output_tokens=usage.output_tokens if hasattr(usage, 'output_tokens') else usage.get("output_tokens", 0),
                total_cost_usd=0.0,
                context_window=self.context_window,
                raw={"finish_reason": finish_reason},
            )

        except Exception as e:
            # Dump failed context for debugging
            dump_path = dump_failed_context(
                context="stream_error",
                model=self.model,
                messages=py_messages if 'py_messages' in locals() else [],
                error=str(e),
                run_id=self._run_id or "",
            )
            if dump_path:
                self._error_dumps.append(("stream_error", str(dump_path)))
            
            yield ErrorBlock(str(e))
        finally:
            self._running = False

    async def _stream_one_response(
        self,
        messages: list[Message],
        prompt: str,
        tools: list[dict] | None,
        working_dir: str | None,
        images: list[ImageBlock] | None = None,
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
        # Build context using ContextBuilder (single source of truth)
        builder = ContextBuilder()
        
        # Add system prompt if configured
        if self.user_prompt:
            builder.add_message(Message("system", self.user_prompt))
        
        # Add conversation history with proper tool result handling
        for msg in messages:
            role = msg.role
            
            # Handle tool result messages (role="tool")
            if role == "tool":
                for block in msg.content_blocks or []:
                    if hasattr(block, 'type') and block.type == "tool_result":
                        builder.add_message(Message("tool", "", content_blocks=[block]))
                continue
            
            # Handle regular messages
            if role in ("system", "user", "assistant"):
                builder.add_message(msg)
        
        # Build structured content for the current prompt
        content = builder.build_message_content(
            messages=[],  # History already added via add_messages
            new_prompt=prompt,
            images=images or [],
        )
        
        # Convert to RustMessage format
        py_messages = [RustMessage("user", content)]

        # Accumulation variables (must be before token counting)
        result = {
            "text": "",
            "reasoning": "",
            "tool_calls": [],
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "finish_reason": "stop",
        }
        events: list[RunnerEvent] = []
        
        # Count tokens using tiktoken (accurate pre-send count)
        context_text = builder.build(OutputFormat.TEXT_UNWRAPPED).as_text()
        context_tokens = count_tokens(context_text)
        
        # Emit ContextTokensEvent for UI
        events.append(ContextTokensEvent(context_tokens=context_tokens))
        
        debug_log.info(
            f"Context tokens: {context_tokens}",
            category=Category.RUNNER,
            run_id=self._run_id or "",
        )

        # Create model instance
        model = create_chat_model_py(self.base_url, self.model, self.api_key)

      # Track current tool call being processed
        current_tool_id: str | None = None
        # Track which tool IDs have had ToolUseStartEvent emitted
        tool_start_emitted: set[str] = set()

        # Convert tools to Rust format
        rust_tools = None
        if tools:
            rust_tools = []
            for tool in tools:
                func = tool.get("function", {})
                params = func.get("parameters", {})
                rust_tools.append(ToolDefinition(
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

        # Track if we're waiting for tool execution (soft timeout applies)
        awaiting_tool_execution = False
        
        async for chunk in stream:
            if self._cancelled:
                break
            
            # Apply timeout based on state
            # Note: This is a soft timeout for tool execution, hard for stream reading
            timeout = TOOL_EXECUTION_TIMEOUT if awaiting_tool_execution else STREAM_READLINE_TIMEOUT
            
            try:
                with asyncio.timeout(timeout):
                    # Handle typed StreamPart objects
                    if isinstance(chunk, StreamPart.Done):
                        break
                    elif isinstance(chunk, StreamPart.TextDelta):
                        delta = chunk.delta
                        result["text"] += delta
                        events.append(TextDelta(delta))
                        events.append(RawEvent(data={"type": "text_delta", "delta": delta}))
                    elif isinstance(chunk, StreamPart.ReasoningDelta):
                        delta = chunk.delta
                        result["reasoning"] += delta
                        # ThinkingDelta so the UI renders a separate thinking block.
                        events.append(ThinkingDelta(delta))
                        events.append(RawEvent(data={"type": "reasoning_delta", "delta": delta}))
                    elif isinstance(chunk, StreamPart.ToolCallStart):
                        tool_id = chunk.id
                        current_tool_id = tool_id
                        
                        # Only emit ToolUseStartEvent if we have a tool name
                        # Some APIs don't send the name in the start event
                        if chunk.tool_name:
                            events.append(ToolUseStartEvent(
                                tool_use_id=tool_id,
                                tool_name=chunk.tool_name,
                            ))
                            tool_start_emitted.add(tool_id)
                        events.append(RawEvent(data={"type": "tool_call_start", "id": tool_id, "tool_name": chunk.tool_name}))
                    elif isinstance(chunk, StreamPart.ToolCallDelta):
                        tool_id = chunk.id
                        delta = chunk.delta  # ← accumulated JSON from Rust
                        
                        # Emit delta for UI
                        events.append(ToolInputDeltaEvent(
                            tool_use_id=tool_id,
                            delta=delta,
                            partial_json=delta,
                        ))
                        events.append(RawEvent(data={"type": "tool_call_delta", "id": tool_id, "delta": delta}))
                    elif isinstance(chunk, StreamPart.ToolCallEnd):
                        tool_id = chunk.id
                        # Just signals end - no action needed
                        awaiting_tool_execution = True  # Set to True after tool call received
                        events.append(RawEvent(data={"type": "tool_call_end", "id": tool_id}))
                        
                    elif isinstance(chunk, StreamPart.ToolCall):
                        tool_id = chunk.id
                        tool_name = chunk.tool_name
                        
                        # If we didn't emit ToolUseStartEvent earlier (because tool_name was empty),
                        # emit it now that we have the name
                        if tool_name and tool_id not in tool_start_emitted:
                            events.append(ToolUseStartEvent(
                                tool_use_id=tool_id,
                                tool_name=tool_name,
                            ))
                            tool_start_emitted.add(tool_id)
                        
                        # Parse accumulated JSON from Rust
                        tool_args = {}
                        if chunk.arguments:
                            try:
                                tool_args = json.loads(chunk.arguments)
                                # Validate structure
                                if not isinstance(tool_args, dict):
                                    raise ValueError(f"Expected dict, got {type(tool_args).__name__}")
                            except json.JSONDecodeError as e:
                                debug_log.error(
                                    f"Invalid tool arguments for {tool_name}",
                                    category=Category.RUNNER,
                                    details={"error": str(e), "tool_id": tool_id},
                                    run_id=self._run_id or "",
                                )
                                events.append(ErrorBlock(f"Invalid tool arguments for {tool_name}: {e}"))
                                continue
                            except ValueError as e:
                                debug_log.error(
                                    f"Malformed tool arguments for {tool_name}",
                                    category=Category.RUNNER,
                                    details={"error": str(e), "tool_id": tool_id},
                                    run_id=self._run_id or "",
                                )
                                events.append(ErrorBlock(f"Malformed tool arguments for {tool_name}: {e}"))
                                continue
                        
                        if tool_name and tool_args:
                            result["tool_calls"].append({
                                "id": tool_id,
                                "name": tool_name,
                                "arguments": tool_args,
                            })
                            events.append(ToolUseEvent(
                                tool_use_id=tool_id,
                                tool_name=tool_name,
                                tool_input=tool_args,
                            ))
                        
                        # Reset for next tool call
                        current_tool_id = None
                        events.append(RawEvent(data={
                            "type": "tool_call",
                            "id": tool_id,
                            "tool_name": tool_name,
                            "arguments": tool_args,
                        }))
                    elif isinstance(chunk, StreamPart.Finish):
                        if chunk.usage:
                            result["usage"]["input_tokens"] = chunk.usage.input_tokens
                            result["usage"]["output_tokens"] = chunk.usage.output_tokens
                            result["usage"]["total_tokens"] = (
                                result["usage"]["input_tokens"] + result["usage"]["output_tokens"]
                            )
                        events.append(RawEvent(data={
                            "type": "finish",
                            "usage": {
                                "input_tokens": result["usage"]["input_tokens"],
                                "output_tokens": result["usage"]["output_tokens"],
                            }
                        }))
            except asyncio.TimeoutError:
                if awaiting_tool_execution:
                    # Soft timeout - warn and continue waiting
                    debug_log.warning(
                        f"Tool execution taking long ({timeout}s)",
                        category=Category.RUNNER,
                        run_id=self._run_id or "",
                    )
                    continue
                else:
                    # Hard timeout - raise error
                    raise
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
