"""Google Gemini runner using the google-genai SDK.

Uses the stateless generate_content API with manual function calling control.
History is managed externally by Balloons (not the SDK's Chat abstraction).
"""

import asyncio
from typing import AsyncIterator, TYPE_CHECKING

from models import (
    Message, TextDelta, ResultEvent, InitEvent,
    TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock,
    ErrorBlock, ArchiveBlock, ContextMode,
    ToolUseStartEvent, ToolUseEvent, ToolResultDeltaEvent, ToolResultEvent, SteeringInjectedEvent,
)
from .base_runner import BaseRunner, RunnerEvent, SteeringCapability
from .debug_log import debug_log, Category
from .exceptions import InputRequiredError
from .tools import get_tools_for_gemini
from .tool_executor import execute_tool
from .tool_result import ToolExecutionResult

if TYPE_CHECKING:
    from session import Session


class GeminiRunner(BaseRunner):
    """Runner for Google Gemini API.

    Uses the google-genai SDK with manual function calling control.
    We disable automatic function calling so we can:
    - Yield events for UI display
    - Execute tools via our tool_executor with session context
    - Handle steering injection
    - Track for persistence

    History is managed externally - we build the contents list from
    the Message history passed to stream_response().
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        user_prompt: str | None = None,
        context_window: int = 200000,
    ):
        """Initialize the Gemini runner.

        Args:
            api_key: Google AI API key
            model: Model identifier (e.g., gemini-2.5-flash, gemini-2.5-pro)
            user_prompt: Optional user-provided system prompt from backend config
            context_window: Max context tokens for this backend
        """
        # Lazy import to avoid requiring google-genai if not using Gemini
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model
        self._user_prompt = user_prompt
        self.context_window = context_window
        self._running = False
        self._cancelled = False
        self._run_id = ""
        self._session: "Session | None" = None

    @property
    def steering_capability(self) -> SteeringCapability:
        """Gemini uses separate messages for tool results and user text."""
        return SteeringCapability.SEPARATE_MESSAGES

    def set_session(self, session: "Session") -> None:
        """Set the session for tool execution context.

        Args:
            session: The session to use for link navigation tools, domains, etc.
        """
        self._session = session

    def _get_system_prompt(self) -> str | None:
        """Build the system prompt for this turn.

        Combines user prompt with balloons tools, domain prompts, and
        session-specific prompt files.

        Returns:
            Complete system prompt, or None if no content
        """
        from .prompt_builder import build_system_prompt

        enabled_tools = None
        if self._session:
            enabled_tools = self._session.get_enabled_tools_list()

        return build_system_prompt(
            backend_type="gemini",
            user_prompt=self._user_prompt,
            session=self._session,
            enabled_tools=enabled_tools,
        )

    def build_contents(
        self,
        messages: list[Message],
        new_prompt: str,
    ) -> list:
        """Convert internal Message format to Gemini Content format.

        Args:
            messages: Message history
            new_prompt: New user prompt to append

        Returns:
            List of google.genai.types.Content objects
        """
        from google.genai import types

        contents = []

        # Track tool names for function responses (Gemini needs the name)
        tool_names_by_id: dict[str, str] = {}

        for msg in messages:
            # Respect context mode
            if msg.context_mode == ContextMode.DROP:
                continue

            # Determine role
            if msg.role == "user":
                role = "user"
            elif msg.role == "assistant":
                role = "model"
            elif msg.role == "tool":
                # Tool results go as user role with function_response parts
                role = "user"
            elif msg.role == "system":
                # System messages get converted to user messages
                role = "user"
            else:
                role = "user"

            # Use summary if in SUMMARIZE mode and summary exists
            if msg.context_mode == ContextMode.SUMMARIZE and msg.summary:
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=f"[Summary] {msg.summary}")]
                ))
                continue

            # Build parts from content blocks
            parts = []

            if msg.content_blocks:
                for block in msg.content_blocks:
                    if isinstance(block, TextBlock):
                        if block.text:
                            parts.append(types.Part.from_text(text=block.text))

                    elif isinstance(block, ImageBlock):
                        # Load image and add as inline data
                        image_part = self._load_image_part(block)
                        if image_part:
                            parts.append(image_part)

                    elif isinstance(block, ToolUseBlock):
                        # Model's function call - record name for later
                        tool_names_by_id[block.id] = block.name
                        parts.append(types.Part(
                            function_call=types.FunctionCall(
                                name=block.name,
                                args=block.input,
                                id=block.id,
                            )
                        ))

                    elif isinstance(block, ToolResultBlock):
                        # Tool result - need to look up the tool name
                        tool_name = tool_names_by_id.get(
                            block.tool_use_id, "unknown_tool"
                        )
                        parts.append(types.Part.from_function_response(
                            name=tool_name,
                            response={"result": block.content or ""},
                        ))

                    elif isinstance(block, InterruptionBlock):
                        parts.append(types.Part.from_text(text=
                            f"[Interrupted: {block.reason}]"
                        ))

                    elif isinstance(block, ErrorBlock):
                        parts.append(types.Part.from_text(text=
                            f"[Error: {block.reason}]"
                        ))

                    elif isinstance(block, ArchiveBlock):
                        archive_info = f"[Archived {block.message_count} turns: {block.summary}]"
                        archive_info += f"\n(Use read_archive tool with archive_id={block.archive_id} to retrieve full content)"
                        parts.append(types.Part.from_text(text=archive_info))

            elif msg.content:
                # Fallback to plain content
                parts.append(types.Part.from_text(text=msg.content))

            if parts:
                contents.append(types.Content(role=role, parts=parts))

        # Add the new user prompt
        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=new_prompt)]
        ))

        return contents

    def _load_image_part(self, block: ImageBlock):
        """Load an image block as a Gemini Part.

        Args:
            block: ImageBlock with file_path and media_type

        Returns:
            google.genai.types.Part with inline_data, or None if failed
        """
        from pathlib import Path
        import base64
        from google.genai import types

        path = Path(block.file_path)
        if not path.exists():
            debug_log.warning(
                f"Image file not found: {block.file_path}",
                category=Category.RUNNER,
                run_id=self._run_id,
            )
            return None

        try:
            data = path.read_bytes()
            # Gemini expects base64-encoded data
            b64_data = base64.standard_b64encode(data).decode("ascii")

            return types.Part(
                inline_data=types.Blob(
                    mime_type=block.media_type or "image/png",
                    data=b64_data,
                )
            )
        except Exception as e:
            debug_log.error(
                f"Failed to load image: {e}",
                category=Category.RUNNER,
                run_id=self._run_id,
            )
            return None

    async def stream_response(
        self,
        messages: list[Message],
        prompt: str,
        allowed_tools: list[str] | None = None,
        working_dir: str | None = None,
        disable_tools: bool = False,
    ) -> AsyncIterator[RunnerEvent]:
        """Stream a response from the Gemini API.

        Args:
            messages: Message history for context
            prompt: The new prompt to send
            allowed_tools: List of tool names to allow, or None for all
            working_dir: Working directory for tool execution
            disable_tools: If True, disable all tools

        Yields:
            TextDelta, ToolUseEvent, ToolResultEvent, InitEvent, and ResultEvent
        """
        from google.genai import types

        self._running = True
        self._cancelled = False
        self._run_id = f"gemini-{id(self)}"

        # Build contents from message history
        contents = self.build_contents(messages, prompt)

        # Get enabled tools from session if available
        effective_allowed_tools = allowed_tools
        if effective_allowed_tools is None and self._session:
            enabled = self._session.get_enabled_tools_list()
            if enabled:
                effective_allowed_tools = enabled

        # Get tools in Gemini format
        tools = get_tools_for_gemini(
            effective_allowed_tools,
            disable_tools,
            include_browser_tools=True,
        )

        # Build config
        config = types.GenerateContentConfig(
            system_instruction=self._get_system_prompt(),
            tools=tools,
            # Disable automatic function calling - we handle it ourselves
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        debug_log.info(
            f"Gemini request to {self.model}",
            category=Category.RUNNER,
            details={
                "content_count": len(contents),
                "prompt_len": len(prompt),
                "tools_enabled": tools is not None,
            },
            run_id=self._run_id,
        )

        # Emit init event
        yield InitEvent(
            model=self.model,
            session_id="",
            context_window=self.context_window,
        )

        total_input_tokens = 0
        total_output_tokens = 0

        # Track tool names for this run (for function responses)
        tool_names_by_id: dict[str, str] = {}

        try:
            # Tool execution loop - continue until model stops calling tools
            while True:
                if self._cancelled:
                    break

                # Stream one response and collect events/tool calls
                tool_calls = []
                text_buffer = ""

                debug_log.debug(
                    f"Gemini API call",
                    category=Category.RUNNER,
                    details={
                        "content_count": len(contents),
                        "model": self.model,
                    },
                    run_id=self._run_id,
                )

                # Use async streaming
                async for chunk in await self.client.aio.models.generate_content_stream(
                    model=self.model,
                    contents=contents,
                    config=config,
                ):
                    if self._cancelled:
                        break

                    # Extract usage from chunk if available
                    if chunk.usage_metadata:
                        total_input_tokens = chunk.usage_metadata.prompt_token_count or 0
                        total_output_tokens = chunk.usage_metadata.candidates_token_count or 0

                    # Process candidates
                    if not chunk.candidates:
                        continue

                    for candidate in chunk.candidates:
                        if not candidate.content or not candidate.content.parts:
                            continue

                        for part in candidate.content.parts:
                            # Handle text content
                            if hasattr(part, 'text') and part.text:
                                text_buffer += part.text
                                yield TextDelta(text=part.text)
                                await asyncio.sleep(0)  # Yield to event loop

                            # Handle function calls
                            if hasattr(part, 'function_call') and part.function_call:
                                fc = part.function_call
                                tool_call = {
                                    "id": fc.id or f"call_{len(tool_calls)}",
                                    "name": fc.name,
                                    "arguments": dict(fc.args) if fc.args else {},
                                }
                                tool_calls.append(tool_call)

                                # Yield tool use events
                                yield ToolUseStartEvent(
                                    tool_use_id=tool_call["id"],
                                    tool_name=tool_call["name"],
                                )
                                yield ToolUseEvent(
                                    tool_use_id=tool_call["id"],
                                    tool_name=tool_call["name"],
                                    tool_input=tool_call["arguments"],
                                )

                # Check if we have tool calls to execute
                if not tool_calls:
                    # No tool calls, we're done
                    break

                # Add model's response to contents for next iteration
                model_parts = []
                if text_buffer:
                    model_parts.append(types.Part.from_text(text=text_buffer))
                for tc in tool_calls:
                    tool_names_by_id[tc["id"]] = tc["name"]
                    model_parts.append(types.Part(
                        function_call=types.FunctionCall(
                            name=tc["name"],
                            args=tc["arguments"],
                            id=tc["id"],
                        )
                    ))
                contents.append(types.Content(role="model", parts=model_parts))

                # Client-only tools - handled by UI
                CLIENT_ONLY_TOOLS = {"play_midi", "propose_fork", "propose_merge"}

                # Execute each tool and collect results
                accumulated_steering: list[str] = []
                tool_response_parts = []

                for tc in tool_calls:
                    if self._cancelled:
                        break

                    tool_name = tc["name"]

                    # Client-only tools
                    if tool_name in CLIENT_ONLY_TOOLS:
                        debug_log.info(
                            f"Client-only tool: {tool_name}",
                            category=Category.RUNNER,
                            run_id=self._run_id,
                        )
                        yield ToolResultEvent(
                            tool_use_id=tc["id"],
                            result=f"[{tool_name}] Handled by UI",
                        )
                        tool_response_parts.append(
                            types.Part.from_function_response(
                                name=tool_name,
                                response={"result": f"[{tool_name}] Handled by UI"},
                            )
                        )
                        continue

                    async def emit_tool_output(stream_name: str, delta: str) -> None:
                        if not delta or self._tool_event_callback is None:
                            return
                        await self._tool_event_callback(
                            ToolResultDeltaEvent(
                                session_id=self._session.id if self._session else "",
                                exchange_id="",
                                turn_id="",
                                tool_use_id=tc["id"],
                                tool_name=tool_name,
                                delta=delta,
                                stream=stream_name,
                            )
                        )

                    # Execute the tool
                    tool_result = await execute_tool(
                        tool_name,
                        tc["arguments"],
                        working_dir or ".",
                        self._run_id,
                        session=self._session,
                        output_callback=emit_tool_output,
                    )

                    # Handle both legacy tuple and new ToolExecutionResult
                    input_required = False
                    if isinstance(tool_result, ToolExecutionResult):
                        result = tool_result.result
                        is_error = tool_result.is_error
                        input_required = tool_result.input_required
                        if tool_result.domains_changed:
                            tools = get_tools_for_gemini(
                                allowed_tools,
                                disable_tools,
                                include_browser_tools=True,
                            )
                            config = types.GenerateContentConfig(
                                system_instruction=self._get_system_prompt(),
                                tools=tools,
                                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                                    disable=True
                                ),
                            )
                            debug_log.info(
                                f"Domain tools changed, refreshed tool list",
                                category=Category.RUNNER,
                                run_id=self._run_id,
                            )
                    else:
                        result, is_error = tool_result

                    # Yield tool result event
                    yield ToolResultEvent(
                        tool_use_id=tc["id"],
                        result=result,
                    )

                    # Add to response parts
                    tool_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": result},
                        )
                    )

                    # Check if tool requested user input
                    if input_required:
                        debug_log.info(
                            f"Tool {tool_name} requested user input, stopping agentic loop",
                            category=Category.RUNNER,
                            run_id=self._run_id,
                        )
                        raise InputRequiredError(result)

                    # Check for steering after each tool
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
                            yield SteeringInjectedEvent(
                                content=steering,
                                injected_at_tool_id=tc["id"],
                            )

                # Add tool responses to contents
                contents.append(types.Content(role="user", parts=tool_response_parts))

                # Add accumulated steering as a separate user message
                if accumulated_steering:
                    combined_steering = "\n\n".join(accumulated_steering)
                    debug_log.info(
                        f"Adding accumulated steering as user message",
                        category=Category.RUNNER,
                        details={"num_messages": len(accumulated_steering)},
                        run_id=self._run_id,
                    )
                    contents.append(types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=combined_steering)]
                    ))

            debug_log.info(
                f"Gemini stream complete",
                category=Category.RUNNER,
                details={
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                },
                run_id=self._run_id,
            )

            yield ResultEvent(
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                total_cost_usd=0.0,  # TODO: Calculate based on model pricing
                context_window=self.context_window,
            )

        except Exception as e:
            debug_log.error(
                f"Gemini stream error: {e}",
                category=Category.RUNNER,
                details={
                    "error_type": type(e).__name__,
                    "error_str": str(e),
                },
                run_id=self._run_id,
            )
            raise

        finally:
            self._running = False
            self._run_id = ""

    def terminate(self) -> None:
        """Terminate any running request."""
        self._cancelled = True
        self._running = False

    @property
    def is_running(self) -> bool:
        """Whether the runner is currently processing a request."""
        return self._running
