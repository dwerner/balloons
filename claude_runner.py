import asyncio
import json
import os
import re
import signal
import uuid
from typing import AsyncIterator, TYPE_CHECKING

from models import (
    Message, TextDelta, ResultEvent, InitEvent, RawEvent,
    ToolUseStartEvent, ToolUseEvent, ToolResultEvent,
    TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, LinkBlock, ArchiveBlock, ContextMode,
)
from core.debug_log import debug_log, dump_failed_json
from core.base_runner import BaseRunner, RunnerEvent
from core.exceptions import RateLimitError, StreamTimeoutError

# Timeout for reading lines from Claude stream (3 minutes)
# This is a hard timeout when waiting for Claude to stream text.
# When waiting for tool execution, we use a soft timeout (warning only).
STREAM_READLINE_TIMEOUT = 180.0
from core.tool_executor import execute_tool
from core.link_tools import LINK_TOOL_NAMES
from core.tools import REVIEW_TOOL_NAMES

# Regex to match <balloons-tool>...</balloons-tool> blocks
# Use non-greedy .*? to allow matching multiple blocks, but consume up to the matching closing tag
# We use a regex that stops at the first </balloons-tool> after each opening tag
BALLOONS_TOOL_RE = re.compile(
    r'<balloons-tool>\s*(\{[^<]*(?:<(?!/balloons-tool>)[^<]*)*\})\s*</balloons-tool>',
    re.DOTALL
)

if TYPE_CHECKING:
    from session import Session


async def readline_unlimited(
    stream: asyncio.StreamReader,
    timeout: float = STREAM_READLINE_TIMEOUT,
    run_id: str = "",
    hard_timeout: bool = True,
    session_name: str = "",
) -> bytes:
    """Read a line from stream without size limit, with timeout.

    Args:
        stream: The stream to read from
        timeout: Max seconds to wait (default 3 minutes)
        run_id: Process ID for logging
        hard_timeout: If True, raise StreamTimeoutError. If False, just warn and keep waiting.
        session_name: Session name for logging (used in soft timeout warnings)

    Returns:
        The line read (including newline), or partial data on EOF

    Raises:
        StreamTimeoutError: If hard_timeout=True and no data received within timeout
    """
    chunks = []
    wait_count = 0
    while True:
        try:
            # Read up to separator, with timeout
            chunk = await asyncio.wait_for(
                stream.readuntil(b'\n'),
                timeout=timeout,
            )
            chunks.append(chunk)
            break
        except asyncio.TimeoutError:
            wait_count += 1
            total_wait = wait_count * timeout
            if hard_timeout:
                # Hard timeout - raise error
                raise StreamTimeoutError(total_wait)
            else:
                # Soft timeout - log warning and keep waiting
                session_info = f" [{session_name}]" if session_name else ""
                debug_log.warning(
                    f"Tool execution taking {total_wait:.0f}s{session_info}",
                    category="stream",
                    run_id=run_id,
                )
                # TODO: Could emit a notification event here for UI
                continue
        except asyncio.IncompleteReadError as e:
            # EOF reached
            chunks.append(e.partial)
            break
        except asyncio.LimitOverrunError as e:
            # Line too long, read what we can and continue
            chunk = await stream.read(e.consumed)
            chunks.append(chunk)
    return b''.join(chunks)


class ClaudeRunner(BaseRunner):
    """Runner that uses Claude CLI with bidirectional JSON streaming.

    Uses --input-format stream-json and --output-format stream-json for
    proper message passing. Executes tools ourselves and sends results
    back via the bidirectional stream.
    """

    def __init__(
        self,
        backend_env: dict[str, str] | None = None,
        system_prompt: str | None = None,
        context_window: int = 150000,
    ):
        self.process: asyncio.subprocess.Process | None = None
        self._terminated = False
        self._current_tool_use: dict | None = None  # Track tool use being built
        self._run_id: str = ""  # Current process PID for debug logging
        self._backend_env = backend_env or {}  # Environment overrides for LLM backend
        self.system_prompt = system_prompt  # Additional system context to prepend
        self.context_window = context_window  # Max context tokens
        self._json_errors: list[tuple[str, str | None]] = []  # Track (error_detail, dump_path) tuples
        self._current_session: "Session | None" = None  # Session for tool execution
        self._text_buffer: str = ""  # Buffer for detecting balloons-tool blocks

    def _parse_balloons_tools(self, text: str) -> list[tuple[str, str, dict]]:
        """Parse all <balloons-tool> blocks from text.

        Args:
            text: Text that may contain one or more balloons-tool blocks

        Returns:
            List of (tool_name, tool_id, args) tuples for each valid tool call found
        """
        matches = BALLOONS_TOOL_RE.findall(text)
        if not matches:
            return []

        results = []
        for captured in matches:
            try:
                debug_log.info(
                    f"Parsing balloons-tool JSON",
                    category="tool",
                    details={"captured_len": len(captured), "captured_preview": captured[:200]},
                    run_id=self._run_id,
                )
                tool_call = json.loads(captured)
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})
                if tool_name == "propose_fork":
                    debug_log.info(
                        f"propose_fork parsed",
                        category="tool",
                        details={"context_plan_len": len(tool_args.get("context_plan", []))},
                        run_id=self._run_id,
                    )
                tool_id = f"balloons-{uuid.uuid4().hex[:12]}"
                results.append((tool_name, tool_id, tool_args))
            except json.JSONDecodeError as e:
                debug_log.warning(
                    f"Failed to parse balloons-tool JSON: {e}",
                    category="tool",
                    details={"captured": captured[:500]},
                    run_id=self._run_id,
                )
                # Continue to try other matches

        return results

    async def _handle_balloons_tools(
        self, text: str, working_dir: str
    ) -> AsyncIterator[RunnerEvent]:
        """Check for and handle <balloons-tool> blocks in text.

        If balloons-tool blocks are found, executes each tool and sends all results
        back to Claude as a continuation message.

        Args:
            text: Text that may contain one or more balloons-tool blocks
            working_dir: Working directory for tool execution

        Yields:
            Tool use/result events for each tool called
        """
        tool_calls = self._parse_balloons_tools(text)
        if not tool_calls:
            return

        debug_log.info(
            f"Detected {len(tool_calls)} balloons-tool(s)",
            category="tool",
            details={"tools": [tc[0] for tc in tool_calls]},
            run_id=self._run_id,
        )

        # Process all tool calls and collect results
        all_results = []
        for tool_name, tool_id, tool_args in tool_calls:
            # Yield tool use events so UI can display them
            yield ToolUseStartEvent(tool_use_id=tool_id, tool_name=tool_name)
            yield ToolUseEvent(
                tool_use_id=tool_id,
                tool_name=tool_name,
                tool_input=tool_args,
            )

            # Execute the tool
            result, is_error = await execute_tool(
                tool_name,
                tool_args,
                working_dir,
                self._run_id,
                session=self._current_session,
            )

            # Yield result event
            yield ToolResultEvent(tool_use_id=tool_id, result=result)

            # Collect result for batch continuation
            all_results.append((tool_name, tool_id, result))

        # Send all results back to Claude as a single continuation message
        result_blocks = []
        for tool_name, tool_id, result in all_results:
            result_blocks.append(f"<balloons-tool-result tool=\"{tool_name}\" id=\"{tool_id}\">\n{result}\n</balloons-tool-result>")

        continuation_text = "\n\n".join(result_blocks)
        continuation_msg = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": continuation_text}],
            }
        }
        await self._send_message(continuation_msg)

    def build_message_content(self, messages: list[Message], new_prompt: str) -> list[dict]:
        """Build content blocks for the user message.

        Converts message history into a content array that Claude can understand.
        Each message becomes a text block with role prefix, tool uses become
        proper tool_use references, and tool results become tool_result blocks.

        Args:
            messages: Message history
            new_prompt: New user prompt to append

        Returns:
            List of content blocks for the user message
        """
        content = []

        # Build conversation history as text blocks
        history_parts = []
        for msg in messages:
            if msg.context_mode == ContextMode.DROP:
                continue

            # Handle system messages
            if msg.role == "system":
                if msg.content_blocks:
                    for block in msg.content_blocks:
                        if isinstance(block, LinkBlock):
                            link_info = f"[Link: {block.linked_session_id[:8]}]"
                            if block.summary:
                                link_info += f" - {block.summary}"
                            history_parts.append(link_info)
                        elif isinstance(block, ArchiveBlock):
                            archive_info = f"[Archived {block.message_count} turns: {block.summary}]"
                            archive_info += f"\n(Archive JSON path: {block.file_path})"
                            history_parts.append(archive_info)
                        elif isinstance(block, TextBlock) and block.text:
                            history_parts.append(block.text)
                elif msg.content:
                    history_parts.append(msg.content)
                continue

            # Use summary if in SUMMARIZE mode
            if msg.context_mode == ContextMode.SUMMARIZE and msg.summary:
                role_name = "User" if msg.role == "user" else "Assistant"
                history_parts.append(f"<{role_name.lower()}>\n[Summary] {msg.summary}\n</{role_name.lower()}>")
                continue

            # Build content from blocks
            if msg.content_blocks:
                role_name = "user" if msg.role == "user" else "assistant"
                block_texts = []

                for block in msg.content_blocks:
                    if isinstance(block, TextBlock) and block.text:
                        block_texts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_info = f"<tool_use name=\"{block.name}\" id=\"{block.id}\">\n{json.dumps(block.input, indent=2)}\n</tool_use>"
                        block_texts.append(tool_info)
                    elif isinstance(block, ToolResultBlock):
                        error_attr = ' error="true"' if block.is_error else ''
                        result_info = f"<tool_result id=\"{block.tool_use_id}\"{error_attr}>\n{block.content}\n</tool_result>"
                        block_texts.append(result_info)
                    elif isinstance(block, InterruptionBlock):
                        block_texts.append(f"[Response interrupted: {block.reason}]")
                    elif isinstance(block, ErrorBlock):
                        error_info = f"[Response truncated: {block.reason}]"
                        if block.partial_tool_name:
                            error_info += f" (incomplete tool: {block.partial_tool_name})"
                        block_texts.append(error_info)
                    elif isinstance(block, LinkBlock):
                        link_info = f"[Link: {block.linked_session_id[:8]}]"
                        if block.summary:
                            link_info += f" - {block.summary}"
                        block_texts.append(link_info)
                    elif isinstance(block, ArchiveBlock):
                        archive_info = f"[Archived {block.message_count} turns: {block.summary}]"
                        archive_info += f"\n(Archive ID: {block.archive_id}, JSON path: {block.file_path})"
                        block_texts.append(archive_info)

                if block_texts:
                    history_parts.append(f"<{role_name}>\n" + "\n\n".join(block_texts) + f"\n</{role_name}>")
            elif msg.content:
                role_name = "user" if msg.role == "user" else "assistant"
                history_parts.append(f"<{role_name}>\n{msg.content}\n</{role_name}>")

        # Add history as a single text block if we have any
        if history_parts:
            history_text = "<conversation_history>\n" + "\n\n".join(history_parts) + "\n</conversation_history>"
            content.append({"type": "text", "text": history_text})

        # Add the new prompt
        content.append({"type": "text", "text": new_prompt})

        return content

    async def stream_response(
        self, messages: list[Message], prompt: str, allowed_tools: list[str] | None = None,
        working_dir: str | None = None, disable_tools: bool = False
    ) -> AsyncIterator[RunnerEvent]:
        """Stream a response from Claude using bidirectional JSON streaming.

        Uses --input-format stream-json for proper message passing. When Claude
        calls a tool, we execute it ourselves and send the result back via the
        bidirectional stream, continuing until Claude stops calling tools.

        Args:
            messages: Message history for context
            prompt: The new prompt to send
            allowed_tools: List of tool names to allow, or None for all
            working_dir: Working directory for the Claude process
            disable_tools: If True, disable all tools (for simple text responses)

        Yields:
            RunnerEvent objects (TextDelta, ToolUseEvent, ToolResultEvent, etc.)
        """
        self._terminated = False
        self._json_errors = []
        self._current_tool_use = None
        self._text_buffer = ""  # Reset text buffer for balloons-tool detection

        # Build command with bidirectional JSON streaming
        cmd = [
            "claude",
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--no-session-persistence",
            "--disallowedTools", "Task,TodoWrite,NotebookEdit,AskUserQuestion,EnterPlanMode,ExitPlanMode",
        ]

        if self.system_prompt:
            cmd.extend(["--system-prompt", self.system_prompt])

        if disable_tools:
            cmd.extend(["--tools", ""])
        elif allowed_tools:
            cmd.extend(["--allowedTools", ",".join(allowed_tools)])

        # Build environment with backend overrides
        env = None
        if self._backend_env:
            env = os.environ.copy()
            env.update(self._backend_env)

        # Use working_dir if it exists, otherwise fall back to current directory
        effective_cwd = working_dir
        if working_dir and not os.path.isdir(working_dir):
            debug_log.warning(
                f"Working directory does not exist: {working_dir}, falling back to cwd",
                category="process",
            )
            effective_cwd = None

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=effective_cwd,
            env=env,
        )

        self._run_id = str(self.process.pid)

        debug_log.info(
            f"Claude started (pid {self.process.pid})",
            category="process",
            details={"cwd": working_dir or "default", "mode": "stream-json"},
            run_id=self._run_id,
        )

        try:
            # Build and send initial message with conversation history
            content = self.build_message_content(messages, prompt)
            initial_msg = {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": content,
                }
            }
            await self._send_message(initial_msg)

            # Process responses, handling tool calls
            async for event in self._process_stream(working_dir or "."):
                yield event

        finally:
            await self._cleanup()

    async def _send_message(self, msg: dict) -> None:
        """Send a JSON message to the Claude process."""
        if not self.process or not self.process.stdin:
            return

        line = json.dumps(msg) + "\n"
        self.process.stdin.write(line.encode("utf-8"))
        await self.process.stdin.drain()

        debug_log.debug(
            f"Sent {msg.get('type')} message",
            category="claude",
            run_id=self._run_id,
        )

    async def _send_tool_result(self, tool_use_id: str, result: str, is_error: bool = False) -> None:
        """Send a tool result back to Claude."""
        msg = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                    "is_error": is_error,
                }]
            }
        }
        await self._send_message(msg)

    async def _process_stream(self, working_dir: str) -> AsyncIterator[RunnerEvent]:
        """Process the JSON stream from Claude, handling tool calls.

        Yields events and automatically executes tools, sending results back.
        """
        pending_tool_calls: list[dict] = []  # Collect tool calls from current response
        awaiting_balloons_tool_response = False  # True after we send a balloons-tool result
        awaiting_tool_execution = False  # True when CLI is executing a tool

        # Get session name for logging
        session_name = ""
        if self._current_session:
            session_name = self._current_session.title or self._current_session.fork_name or self._current_session.id[:8]

        while True:
            if self._terminated:
                break

            # Use soft timeout when waiting for tool execution, hard timeout when waiting for Claude
            line = await readline_unlimited(
                self.process.stdout,
                run_id=self._run_id,
                hard_timeout=not awaiting_tool_execution,
                session_name=session_name,
            )
            if not line:
                break

            line = line.decode("utf-8").strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                dump_path = dump_failed_json(line, "sse_line")
                self._json_errors.append((str(e), str(dump_path) if dump_path else None))
                debug_log.warning(
                    f"JSON decode error: {e}",
                    category="json",
                    run_id=self._run_id,
                )
                continue

            # Always yield raw event
            yield RawEvent(data=data)

            msg_type = data.get("type")

            # Handle init event
            if msg_type == "system" and data.get("subtype") == "init":
                yield InitEvent(
                    model=data.get("model", ""),
                    session_id=data.get("session_id", ""),
                    context_window=self.context_window,
                )
                continue

            # Handle assistant message (contains text and/or tool_use)
            if msg_type == "assistant":
                message = data.get("message", {})
                for block in message.get("content", []):
                    block_type = block.get("type")

                    if block_type == "text":
                        text = block.get("text", "")
                        if text:
                            yield TextDelta(text=text)

                            # Check for balloons-tool blocks in text
                            self._text_buffer += text
                            if "<balloons-tool>" in self._text_buffer and "</balloons-tool>" in self._text_buffer:
                                # Count opening and closing tags to ensure all blocks are complete
                                opening_count = self._text_buffer.count("<balloons-tool>")
                                closing_count = self._text_buffer.count("</balloons-tool>")

                                if opening_count == closing_count:
                                    debug_log.info(
                                        f"Found {opening_count} complete balloons-tool block(s)",
                                        category="tool",
                                        details={"buffer_len": len(self._text_buffer), "buffer_preview": self._text_buffer[:500]},
                                        run_id=self._run_id,
                                    )
                                    async for event in self._handle_balloons_tools(self._text_buffer, working_dir):
                                        yield event
                                    self._text_buffer = ""
                                    # Mark that we're waiting for Claude to respond to the tool result
                                    awaiting_balloons_tool_response = True

                    elif block_type == "tool_use":
                        tool_use_id = block.get("id", "")
                        tool_name = block.get("name", "")
                        tool_input = block.get("input", {})

                        # Yield tool use events
                        yield ToolUseStartEvent(
                            tool_use_id=tool_use_id,
                            tool_name=tool_name,
                        )
                        yield ToolUseEvent(
                            tool_use_id=tool_use_id,
                            tool_name=tool_name,
                            tool_input=tool_input,
                        )

                        # Queue for execution
                        pending_tool_calls.append({
                            "id": tool_use_id,
                            "name": tool_name,
                            "input": tool_input,
                        })
                        # CLI will execute this tool - use soft timeout for next read
                        awaiting_tool_execution = True
                continue

            # Handle user message (tool results from CLI)
            if msg_type == "user":
                # CLI executed tools and is sending results back
                # Parse and yield the results, remove from pending_tool_calls
                message = data.get("message", {})
                for block in message.get("content", []):
                    if block.get("type") == "tool_result":
                        tool_use_id = block.get("tool_use_id", "")
                        result_content = block.get("content", "")

                        # Yield the tool result event
                        yield ToolResultEvent(
                            tool_use_id=tool_use_id,
                            result=result_content,
                        )

                        # Remove from pending_tool_calls (CLI already handled it)
                        pending_tool_calls = [
                            tc for tc in pending_tool_calls
                            if tc["id"] != tool_use_id
                        ]

                        debug_log.debug(
                            f"CLI tool result received: {tool_use_id[:8]}...",
                            category="claude",
                            run_id=self._run_id,
                        )

                # Tool results received - back to hard timeout for Claude's response
                if not pending_tool_calls:
                    awaiting_tool_execution = False
                continue

            # Handle result event (turn complete)
            if msg_type == "result":
                usage = data.get("usage", {})

                # Only execute custom tools (link/review tools) that CLI doesn't know about
                # Standard tools (Read, Bash, etc.) are handled by CLI
                custom_tool_names = LINK_TOOL_NAMES | REVIEW_TOOL_NAMES
                custom_tool_calls = [
                    tc for tc in pending_tool_calls
                    if tc["name"] in custom_tool_names
                ]

                if custom_tool_calls:
                    for tc in custom_tool_calls:
                        result, is_error = await execute_tool(
                            tc["name"],
                            tc["input"],
                            working_dir,
                            self._run_id,
                            session=self._current_session,
                        )

                        yield ToolResultEvent(
                            tool_use_id=tc["id"],
                            result=result,
                        )

                        # Send result back to Claude
                        await self._send_tool_result(tc["id"], result, is_error)

                    pending_tool_calls.clear()
                    # Continue processing - Claude will respond to the tool results
                    continue

                # Check if we're waiting for Claude to respond to a balloons-tool result
                if awaiting_balloons_tool_response:
                    debug_log.debug(
                        "Awaiting balloons-tool response, continuing stream",
                        category="tool",
                        run_id=self._run_id,
                    )
                    awaiting_balloons_tool_response = False
                    continue

                # No custom tool calls pending - we're done
                pending_tool_calls.clear()
                yield ResultEvent(
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    total_cost_usd=data.get("total_cost_usd", 0.0),
                    context_window=self.context_window,
                )
                break

    async def _cleanup(self) -> None:
        """Clean up the Claude process."""
        if not self.process:
            return

        # Close stdin to signal we're done
        if self.process.stdin and not self.process.stdin.is_closing():
            self.process.stdin.close()
            try:
                await self.process.stdin.wait_closed()
            except Exception:
                pass

        # Read any remaining stderr
        stderr_output = b""
        try:
            stderr_output = await asyncio.wait_for(
                self.process.stderr.read(),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            pass

        # Wait for process to exit
        try:
            await asyncio.wait_for(self.process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()

        exit_code = self.process.returncode
        stderr_text = stderr_output.decode("utf-8", errors="replace") if stderr_output else ""

        if exit_code != 0:
            debug_log.error(
                f"Claude exited (code {exit_code})",
                category="process",
                details={"stderr": stderr_text[:500]},
                run_id=self._run_id,
            )
            if "hit your limit" in stderr_text.lower():
                raise RateLimitError(stderr_text.strip())
        else:
            debug_log.info(f"Claude exited (code 0)", category="process", run_id=self._run_id)

        self._run_id = ""
        self.process = None

    def terminate(self) -> None:
        """Terminate the running Claude process."""
        self._terminated = True
        if self.process and self.process.returncode is None:
            try:
                self.process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    def get_stream_errors(self) -> tuple[list[tuple[str, str | None]], dict | None]:
        """Get any errors that occurred during streaming.

        Returns:
            Tuple of (json_errors, partial_tool_use)
        """
        return self._json_errors, self._current_tool_use

    def set_session(self, session: "Session") -> None:
        """Set the current session for tool execution.

        Args:
            session: The current Session object
        """
        self._current_session = session

    @staticmethod
    def build_context(messages: list[Message], new_prompt: str) -> str:
        """Build a human-readable context string for display purposes.

        This is used by the UI to show what context will be sent. The actual
        API uses build_message_content() which returns structured content blocks.

        Args:
            messages: Message history
            new_prompt: New user prompt

        Returns:
            Human-readable string representation of the context
        """
        parts = []

        for msg in messages:
            if msg.context_mode == ContextMode.DROP:
                continue

            if msg.role == "system":
                if msg.content_blocks:
                    for block in msg.content_blocks:
                        if isinstance(block, LinkBlock):
                            link_info = f"[Link: {block.linked_session_id[:8]}]"
                            if block.summary:
                                link_info += f" - {block.summary}"
                            parts.append(link_info)
                        elif isinstance(block, ArchiveBlock):
                            archive_info = f"[Archived {block.message_count} turns: {block.summary}]"
                            archive_info += f"\n(Archive ID: {block.archive_id}, JSON path: {block.file_path})"
                            parts.append(archive_info)
                        elif isinstance(block, TextBlock) and block.text:
                            parts.append(block.text)
                elif msg.content:
                    parts.append(msg.content)
                continue

            role_name = "User" if msg.role == "user" else "Assistant"

            if msg.context_mode == ContextMode.SUMMARIZE and msg.summary:
                parts.append(f"{role_name}: [Summary] {msg.summary}")
                continue

            if msg.content_blocks:
                block_texts = []
                for block in msg.content_blocks:
                    if isinstance(block, TextBlock) and block.text:
                        block_texts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        block_texts.append(f"[Tool: {block.name}]\n{json.dumps(block.input, indent=2)}")
                    elif isinstance(block, ToolResultBlock):
                        error_mark = " (error)" if block.is_error else ""
                        block_texts.append(f"[Result{error_mark}]\n{block.content}")
                    elif isinstance(block, InterruptionBlock):
                        block_texts.append(f"[Interrupted: {block.reason}]")
                    elif isinstance(block, ErrorBlock):
                        block_texts.append(f"[Error: {block.reason}]")
                    elif isinstance(block, LinkBlock):
                        link_info = f"[Link: {block.linked_session_id[:8]}]"
                        if block.summary:
                            link_info += f" - {block.summary}"
                        block_texts.append(link_info)
                    elif isinstance(block, ArchiveBlock):
                        archive_info = f"[Archived {block.message_count} turns: {block.summary}]"
                        archive_info += f"\n(Archive ID: {block.archive_id}, JSON path: {block.file_path})"
                        block_texts.append(archive_info)

                if block_texts:
                    parts.append(f"{role_name}: " + "\n".join(block_texts))
            elif msg.content:
                parts.append(f"{role_name}: {msg.content}")

        if new_prompt:
            parts.append(f"User: {new_prompt}")

        return "\n\n".join(parts)
