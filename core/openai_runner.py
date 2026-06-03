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
    ToolUseStartEvent, ToolInputDeltaEvent, ToolUseEvent, ToolResultDeltaEvent, ToolResultEvent, SteeringInjectedEvent,
)
from .base_runner import BaseRunner, RunnerEvent, SteeringCapability
from .debug_log import debug_log, dump_failed_json, perf_marker, Category
from .exceptions import InputRequiredError
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


def _parse_embedded_tool_calls(content: str) -> list[dict]:
    """Parse embedded tool calls from content text.

    Some models output tool calls as formatted text instead of using native
    function calling. This function attempts to parse common formats:

    1. XML format: <tool_call><function=Name><parameter=arg>value</parameter></function></tool_call>
    2. JSON format: {"name": "tool", "arguments": {...}}

    Args:
        content: Text content that may contain embedded tool calls

    Returns:
        List of parsed tool calls in the format:
        [{"id": "...", "name": "...", "arguments": {...}}, ...]
    """
    parsed_calls = []

    # Pattern 1: XML-style <tool_call><function=Name>...</function></tool_call>
    # Example: <tool_call><function=Edit><parameter=file_path>/path/to/file</parameter>...</function></tool_call>
    xml_pattern = re.compile(
        r'<tool_call>\s*<function=(\w+)>(.*?)</function>\s*</tool_call>',
        re.DOTALL
    )

    for match in xml_pattern.finditer(content):
        tool_name = match.group(1)
        params_content = match.group(2)

        # Parse parameters from <parameter=name>value</parameter>
        param_pattern = re.compile(
            r'<parameter=(\w+)>(.*?)</parameter>',
            re.DOTALL
        )

        arguments = {}
        for param_match in param_pattern.finditer(params_content):
            param_name = param_match.group(1)
            param_value = param_match.group(2)
            arguments[param_name] = param_value

        if tool_name and arguments:
            parsed_calls.append({
                "id": f"embedded_{uuid.uuid4().hex[:8]}",
                "name": tool_name,
                "arguments": arguments,
            })
            debug_log.info(
                f"Parsed embedded XML tool call: {tool_name}",
                category=Category.RUNNER,
                details={"argument_keys": list(arguments.keys())},
            )

    # Pattern 2: Simpler XML without closing function tag (some models do this)
    # <tool_call>\n<function=Edit>\n<parameter=file_path>...</parameter>\n
    if not parsed_calls:
        simple_xml_pattern = re.compile(
            r'<tool_call>\s*\n?\s*<function=(\w+)>\s*\n?((?:<parameter=\w+>.*?</parameter>\s*\n?)+)',
            re.DOTALL
        )

        for match in simple_xml_pattern.finditer(content):
            tool_name = match.group(1)
            params_content = match.group(2)

            param_pattern = re.compile(
                r'<parameter=(\w+)>(.*?)</parameter>',
                re.DOTALL
            )

            arguments = {}
            for param_match in param_pattern.finditer(params_content):
                param_name = param_match.group(1)
                param_value = param_match.group(2)
                arguments[param_name] = param_value

            if tool_name and arguments:
                parsed_calls.append({
                    "id": f"embedded_{uuid.uuid4().hex[:8]}",
                    "name": tool_name,
                    "arguments": arguments,
                })
                debug_log.info(
                    f"Parsed embedded simple XML tool call: {tool_name}",
                    category=Category.RUNNER,
                    details={"argument_keys": list(arguments.keys())},
                )

    return parsed_calls


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
        debug_dir = Path.home() / ".balloons" / "dumps"
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
        # llama.cpp and other local servers can spend a long time generating
        # before the first streamed token arrives, so disable SDK timeouts here.
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=None)
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
        # Get enabled tools from session (or None for defaults)
        # Use list to preserve order (order determines prompt order)
        enabled_tools = None
        if self._session:
            enabled_tools = self._session.get_enabled_tools_list()
        return build_system_prompt(
            backend_type="openai",
            user_prompt=self._user_prompt,
            session=self._session,
            enabled_tools=enabled_tools,
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
        
        # Always include system prompt at the start of every request.
        # Each API call is stateless - the server doesn't cache anything.
        # The FULL chat history (including system) must be sent every time.
        if system_prompt:
            openai_messages.append({
                "role": "system",
                "content": system_prompt,
            })

        for msg in messages:
            # Respect context mode
            if msg.context_mode == ContextMode.DROP:
                continue

            # Handle internal system messages (links, archives, metadata)
            # Do not convert them into user turns: strict Jinja templates like
            # Mistral's require user/assistant alternation and will reject
            # synthetic user messages inserted from system metadata.
            if msg.role == "system" and not msg.content_blocks:
                continue

            # Handle tool results specially - they use role="tool" in OpenAI format
            # Tool results are stored with msg.role="tool" or msg.role="user" (legacy)
            if msg.role == "tool":
                # Extract tool result blocks and convert to OpenAI tool messages
                for block in msg.content_blocks or []:
                    if isinstance(block, ToolResultBlock):
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": block.tool_use_id,
                            "content": block.content or "",
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
            if msg.content_blocks or (role == "assistant" and msg.role == "system"):
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
                        summary = block.summary or f"Archived {block.message_count} turns"
                        archive_info = f"[Archived {block.message_count} turns: {summary}]"
                        archive_info += f"\n(Use read_archive tool with archive_id={block.archive_id} to retrieve full content)"
                        content_parts.append(archive_info)

                # Handle assistant messages with tool calls (proper OpenAI format)
                if role == "assistant" and tool_use_blocks:
                    # Client-only tools that don't have stored tool results
                    # These are handled by the UI and don't execute on the backend
                    CLIENT_ONLY_TOOLS = {"play_midi", "propose_fork", "propose_merge"}

                    # Build tool_calls array
                    tool_calls = []
                    client_only_tool_ids = []  # Track which need synthetic results
                    for block in tool_use_blocks:
                        tool_calls.append({
                            "id": block.id,
                            "type": "function",
                            "function": {
                                "name": block.name,
                                "arguments": json.dumps(block.input),
                            }
                        })
                        if block.name in CLIENT_ONLY_TOOLS:
                            client_only_tool_ids.append((block.id, block.name))

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

                    # Add synthetic tool results for client-only tools
                    # These tools don't have stored ToolResultBlocks because they're
                    # handled entirely by the UI (fork/merge proposals, MIDI playback)
                    for tool_id, tool_name in client_only_tool_ids:
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "content": f"[{tool_name}] Handled by UI",
                        })

                # Handle tool results from user messages (legacy format)
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

        # Add the new user prompt unless the previous message is already a user turn.
        # Strict Jinja chat templates (e.g. Mistral) require alternation after the
        # optional system prompt, so merge consecutive user content when needed.
        if openai_messages and openai_messages[-1].get("role") == "user":
            prev = openai_messages[-1].get("content")
            if prev is None:
                openai_messages[-1]["content"] = new_prompt
            elif isinstance(prev, str):
                openai_messages[-1]["content"] = f"{prev}\n\n{new_prompt}" if new_prompt else prev
            else:
                openai_messages.append({
                    "role": "user",
                    "content": new_prompt,
                })
        else:
            openai_messages.append({
                "role": "user",
                "content": new_prompt,
            })

        # Legacy post-processing kept for the default OpenAI-compatible runner.
        # Strict Jinja backends should use StrictOpenAICompatibleRunner, which
        # applies an isolated conservative packaging model.
        openai_messages = self._reorder_tool_messages(openai_messages)
        openai_messages = self._normalize_strict_alternation(openai_messages)

        return openai_messages

    def _is_placeholder_assistant_error(self, msg: dict) -> bool:
        if msg.get("role") != "assistant" or msg.get("tool_calls") or not isinstance(msg.get("content"), str):
            return False
        content = msg.get("content", "").strip()
        return content in {
            "[Error: api_error]",
            "[Interrupted: user_cancelled]",
            "[Interrupted: user_cancelled]\n\n[Interrupted: user_cancelled]",
        }

    def _normalize_strict_alternation(self, messages: list[dict]) -> list[dict]:
        """Normalize history to system? then strict user/assistant alternation.

        Preserves tool-call blocks (assistant with tool_calls followed by tool results),
        drops placeholder assistant error turns, and merges adjacent same-role text turns.
        """
        if not messages:
            return messages

        # First remove placeholder assistant errors from outbound history.
        filtered = [m for m in messages if not self._is_placeholder_assistant_error(m)]

        # Then merge remaining adjacent user/user or assistant/assistant plain text turns.
        return self._merge_consecutive_messages(filtered)

    def _merge_consecutive_messages(self, messages: list[dict]) -> list[dict]:
        """Merge consecutive user/user or assistant/assistant text messages.

        Keeps tool call and tool result structure intact while normalizing plain
        text history into strict alternation for backends with validating chat
        templates. Only merges messages that do not contain tool_calls and are
        not role=tool.
        """
        if not messages:
            return messages

        merged: list[dict] = []
        for msg in messages:
            role = msg.get("role")
            if not merged:
                merged.append(msg)
                continue

            prev = merged[-1]
            prev_role = prev.get("role")

            can_merge = (
                role in {"user", "assistant"}
                and prev_role == role
                and role != "tool"
                and not prev.get("tool_calls")
                and not msg.get("tool_calls")
                and isinstance(prev.get("content"), str)
                and isinstance(msg.get("content"), str)
            )

            if can_merge:
                if msg.get("content"):
                    prev["content"] = f"{prev['content']}\n\n{msg['content']}" if prev.get("content") else msg["content"]
            else:
                merged.append(msg)

        return merged

    def _reorder_tool_messages(self, messages: list[dict]) -> list[dict]:
        """Reorder messages to ensure tool results immediately follow their tool calls.

        OpenAI requires that an assistant message with tool_calls must be immediately
        followed by tool role messages for ALL those tool_call_ids before any other
        message type.

        This method uses a two-pass approach:
        1. First pass: Build a map of tool_call_id -> tool result message
        2. Second pass: When encountering assistant messages with tool_calls,
           merge consecutive ones and pull in their results immediately after

        Args:
            messages: List of OpenAI message dicts

        Returns:
            Reordered message list with proper tool call/result ordering
        """
        if not messages:
            return messages

        # First pass: collect all tool results by their tool_call_id
        tool_results_by_id: dict[str, dict] = {}
        for msg in messages:
            if msg.get("role") == "tool":
                tool_call_id = msg.get("tool_call_id")
                if tool_call_id:
                    tool_results_by_id[tool_call_id] = msg

        # Track which tool_call_ids have been consumed
        consumed_tool_ids: set[str] = set()

        # Second pass: build output with proper ordering
        result = []
        i = 0

        while i < len(messages):
            msg = messages[i]

            # Skip tool messages - they'll be pulled in by their assistant message
            if msg.get("role") == "tool":
                i += 1
                continue

            # Check if this is an assistant message with tool_calls
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                # Collect all consecutive assistant tool_calls messages, and also
                # absorb an immediately preceding assistant text-only message.
                merged_tool_calls = list(msg.get("tool_calls", []))
                merged_content_parts = []

                if result:
                    prev_msg = result[-1]
                    if (
                        prev_msg.get("role") == "assistant"
                        and not prev_msg.get("tool_calls")
                        and isinstance(prev_msg.get("content"), str)
                    ):
                        merged_content_parts.append(prev_msg["content"])
                        result.pop()

                if msg.get("content"):
                    merged_content_parts.append(msg["content"])

                # Look ahead for more consecutive assistant tool_calls messages
                j = i + 1
                while j < len(messages):
                    next_msg = messages[j]
                    # Skip tool messages when looking for consecutive assistant tool_calls
                    if next_msg.get("role") == "tool":
                        j += 1
                        continue
                    # Also skip intervening user messages here: if the stored history
                    # captured a failed/aborted tool phase, the next real user prompt may
                    # already be merged into the current request prompt. Strict Jinja
                    # backends care about the final normalized turn sequence, not these
                    # internal fragments.
                    if next_msg.get("role") == "user":
                        j += 1
                        continue
                    if next_msg.get("role") == "assistant" and next_msg.get("tool_calls"):
                        # Merge this into the current assistant message
                        merged_tool_calls.extend(next_msg.get("tool_calls", []))
                        if next_msg.get("content"):
                            merged_content_parts.append(next_msg["content"])
                        j += 1
                    elif next_msg.get("role") == "assistant" and not next_msg.get("tool_calls") and isinstance(next_msg.get("content"), str) and next_msg.get("content", "").strip() in {
                        "[Interrupted: user_cancelled]",
                        "[Interrupted: user_cancelled]\n\n[Interrupted: user_cancelled]",
                        "[Error: api_error]",
                    }:
                        # Skip placeholder assistant artifacts between tool phases.
                        j += 1
                    else:
                        break

                # Create the merged assistant message
                merged_assistant: dict = {
                    "role": "assistant",
                    "tool_calls": merged_tool_calls,
                }
                if merged_content_parts:
                    merged_assistant["content"] = "\n\n".join(merged_content_parts)
                else:
                    merged_assistant["content"] = None

                result.append(merged_assistant)

                # Collect tool results for all tool_call_ids in this merged message
                for tc in merged_tool_calls:
                    tc_id = tc["id"]
                    if tc_id in tool_results_by_id and tc_id not in consumed_tool_ids:
                        result.append(tool_results_by_id[tc_id])
                        consumed_tool_ids.add(tc_id)
                    elif tc_id not in consumed_tool_ids:
                        # No tool result found - add synthetic one
                        result.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": "[Tool result not available]",
                        })
                        consumed_tool_ids.add(tc_id)

                i = j
            else:
                result.append(msg)
                i += 1

        return result

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

        # Get enabled tools from session if available, otherwise use allowed_tools param
        effective_allowed_tools = allowed_tools
        if effective_allowed_tools is None and self._session:
            # get_enabled_tools_list preserves order, but for tool filtering order doesn't matter
            enabled = self._session.get_enabled_tools_list()
            if enabled:
                effective_allowed_tools = enabled

        # Get tools for this request
        tools = get_tools_for_request(
            effective_allowed_tools,
            disable_tools,
            include_browser_tools=True,
        )

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

                    # Client-only tools - UI handles them from the tool_use event
                    # We still need to add a tool result message for OpenAI's format
                    if tool_name in CLIENT_ONLY_TOOLS:
                        debug_log.info(
                            f"Client-only tool: {tool_name}",
                            category=Category.RUNNER,
                            run_id=self._run_id,
                        )
                        # Yield a tool result event for UI
                        yield ToolResultEvent(
                            tool_use_id=tc["id"],
                            result=f"[{tool_name}] Handled by UI",
                        )
                        # Add placeholder result to messages (OpenAI requires this)
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": f"[{tool_name}] Handled by UI",
                        })
                        continue

                    async def emit_tool_output(stream_name: str, delta: str) -> None:
                        if not delta or self._tool_event_callback is None:
                            return
                        await self._tool_event_callback(
                            ToolResultDeltaEvent(
                                tool_use_id=tc["id"],
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
                        # Check if domain tools changed (load_domain/unload_domain)
                        if tool_result.domains_changed:
                            tools = get_tools_for_request(
                                allowed_tools=allowed_tools,
                                disable_tools=disable_tools,
                                include_domain_tools=True,
                            )
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

                    # Check if the tool requested user input (ask_user tool)
                    if input_required:
                        debug_log.info(
                            f"Tool {tool_name} requested user input, stopping agentic loop",
                            category=Category.RUNNER,
                            run_id=self._run_id,
                        )
                        raise InputRequiredError(result)

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

                # Add accumulated steering after all tool results.
                # For strict Jinja templates (e.g. Mistral), avoid creating a
                # fresh user turn immediately after a user turn. Merge steering
                # into the previous user message when possible.
                if accumulated_steering:
                    combined_steering = "\n\n".join(accumulated_steering)
                    debug_log.info(
                        f"Adding accumulated steering as user message",
                        category=Category.RUNNER,
                        details={"num_messages": len(accumulated_steering), "total_len": len(combined_steering)},
                        run_id=self._run_id,
                    )
                    if openai_messages and openai_messages[-1].get("role") == "user" and isinstance(openai_messages[-1].get("content"), str):
                        prev = openai_messages[-1]["content"]
                        openai_messages[-1]["content"] = f"{prev}\n\n{combined_steering}" if prev else combined_steering
                    else:
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
            error_str = str(e)
            details = {
                "error_type": type(e).__name__,
                "error_str": error_str,
            }

            # Add compact message-role diagnostics for strict-template failures.
            if "conversation roles must alternate user and assistant roles" in error_str:
                details["message_roles"] = [
                    {
                        "idx": i,
                        "role": m.get("role"),
                        "has_tool_calls": bool(m.get("tool_calls")),
                        "tool_call_id": m.get("tool_call_id"),
                        "content_type": type(m.get("content")).__name__ if "content" in m else None,
                        "content_preview": (m.get("content")[:120] if isinstance(m.get("content"), str) else None),
                    }
                    for i, m in enumerate(openai_messages)
                ]

            debug_log.error(
                f"OpenAI stream error: {e}",
                category=Category.RUNNER,
                details=details,
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
                debug_log.trace(
                    "Chunk with empty delta",
                    category=Category.RUNNER,
                    details={"choice_index": getattr(choice, 'index', None), "finish_reason": choice.finish_reason},
                    run_id=self._run_id,
                )
                continue

            # Handle text content
            if delta.content:
                content_buffer += delta.content
                events.append(TextDelta(text=delta.content))
                await asyncio.sleep(0)  # Yield to event loop
            elif getattr(delta, "refusal", None):
                refusal_text = delta.refusal
                content_buffer += refusal_text
                events.append(TextDelta(text=refusal_text))
                await asyncio.sleep(0)
            elif getattr(delta, "reasoning_content", None):
                reasoning_text = delta.reasoning_content
                content_buffer += reasoning_text
                events.append(TextDelta(text=reasoning_text))
                await asyncio.sleep(0)

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

        # Detect and parse embedded tool calls in content (common with some models)
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

        embedded_detected = False
        for pattern, description in embedded_patterns:
            if re.search(pattern, content_buffer):
                embedded_detected = True
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
                break  # Only detect once

        # If we detected embedded tool calls AND didn't get any native tool calls,
        # try to parse the embedded ones
        if embedded_detected and len(finalized_tool_calls) == 0:
            parsed_embedded = _parse_embedded_tool_calls(content_buffer)
            if parsed_embedded:
                debug_log.info(
                    f"Successfully parsed {len(parsed_embedded)} embedded tool calls",
                    category=Category.RUNNER,
                    details={
                        "tools": [tc["name"] for tc in parsed_embedded],
                    },
                    run_id=self._run_id,
                )
                # Emit tool use events for parsed embedded calls
                for tc in parsed_embedded:
                    # Normalize arguments
                    tc["arguments"] = _normalize_tool_arguments(tc["name"], tc["arguments"])
                    events.append(ToolUseStartEvent(
                        tool_use_id=tc["id"],
                        tool_name=tc["name"],
                    ))
                    events.append(ToolUseEvent(
                        tool_use_id=tc["id"],
                        tool_name=tc["name"],
                        tool_input=tc["arguments"],
                    ))
                # Add parsed calls to finalized list
                finalized_tool_calls.extend(parsed_embedded)
            else:
                # Failed to parse - dump for analysis
                _dump_interaction(
                    context="embedded_tool_call",
                    model=self.model,
                    messages=openai_messages,
                    tools=tools,
                    chunks=self._collected_chunks,
                    error=f"Detected embedded tool call but failed to parse",
                )

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
