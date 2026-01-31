import asyncio
import json
import signal
from typing import AsyncIterator, Union

from models import (
    Message, TextDelta, ResultEvent, InitEvent, RawEvent, ToolUseEvent, ToolResultEvent,
    TextBlock, ToolUseBlock, ToolResultBlock, ContextMode,
)
from core.debug_log import debug_log


class RateLimitError(Exception):
    """Raised when Claude CLI reports hitting the rate limit."""
    pass


class InputRequiredError(Exception):
    """Raised when Claude CLI is waiting for user input (question asked)."""
    pass


async def readline_unlimited(stream: asyncio.StreamReader) -> bytes:
    """Read a line from stream without size limit."""
    chunks = []
    while True:
        try:
            # Read up to separator
            chunk = await stream.readuntil(b'\n')
            chunks.append(chunk)
            break
        except asyncio.IncompleteReadError as e:
            # EOF reached
            chunks.append(e.partial)
            break
        except asyncio.LimitOverrunError as e:
            # Line too long, read what we can and continue
            chunk = await stream.read(e.consumed)
            chunks.append(chunk)
    return b''.join(chunks)


class ClaudeRunner:
    def __init__(self, backend_env: dict[str, str] | None = None):
        self.process: asyncio.subprocess.Process | None = None
        self._terminated = False
        self._current_tool_use: dict | None = None  # Track tool use being built
        self._run_id: str = ""  # Current process PID for debug logging
        self._backend_env = backend_env or {}  # Environment overrides for LLM backend

    @staticmethod
    def build_context(messages: list[Message], new_prompt: str) -> str:
        """Build the full context string from message history + new prompt.

        Reconstructs tool calls and results so Claude has proper context.
        Respects ContextMode for each message (copy, summarize, drop).
        """
        parts = []
        for msg in messages:
            # Respect context mode
            if msg.context_mode == ContextMode.DROP:
                continue

            prefix = "User" if msg.role == "user" else "Assistant"

            # Use summary if in SUMMARIZE mode and summary exists
            if msg.context_mode == ContextMode.SUMMARIZE and msg.summary:
                parts.append(f"{prefix}: [Summary] {msg.summary}")
                continue

            # Build content from blocks if available
            if msg.content_blocks:
                block_parts = []
                for block in msg.content_blocks:
                    if isinstance(block, TextBlock):
                        if block.text:
                            block_parts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        # Format tool use so Claude knows what it did
                        import json
                        input_str = json.dumps(block.input, indent=2)
                        block_parts.append(f"[Tool Use: {block.name}]\n{input_str}")
                    elif isinstance(block, ToolResultBlock):
                        # Format tool result so Claude sees what the tool returned
                        error_prefix = "[Error] " if block.is_error else ""
                        # Truncate very long results
                        content = block.content
                        if len(content) > 10000:
                            content = content[:10000] + "\n... [truncated]"
                        block_parts.append(f"[Tool Result]{error_prefix}\n{content}")

                if block_parts:
                    parts.append(f"{prefix}: " + "\n\n".join(block_parts))
            else:
                # Fallback to plain content
                parts.append(f"{prefix}: {msg.content}")

        parts.append(f"User: {new_prompt}")
        return "\n\n".join(parts)

    async def stream_response(
        self, messages: list[Message], prompt: str, allowed_tools: list[str] | None = None,
        working_dir: str | None = None
    ) -> AsyncIterator[Union[TextDelta, ResultEvent, InitEvent, RawEvent]]:
        """
        Stream a response from Claude.

        Sends full conversation history + new prompt each time.
        Yields both parsed events and RawEvent for all JSON lines.
        """
        self._terminated = False

        # Build full context from history
        if messages:
            full_prompt = self.build_context(messages, prompt)
        else:
            full_prompt = prompt

        cmd = [
            "claude",
            "-p",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--no-session-persistence",  # Don't save sessions in Claude - we manage our own
            "--disallowedTools", "Task,TodoWrite,NotebookEdit,AskUserQuestion",  # Prevent task spawning, todo lists, notebook, questions - we manage our own sessions
        ]

        if allowed_tools:
            cmd.extend(["--allowedTools", ",".join(allowed_tools)])

        # Build environment with backend overrides
        env = None
        if self._backend_env:
            import os
            env = os.environ.copy()
            env.update(self._backend_env)

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            env=env,
        )

        # Track run_id for debug logging
        self._run_id = str(self.process.pid)

        # Log process start
        debug_log.info(
            f"Claude started (pid {self.process.pid})",
            category="process",
            details={"cwd": working_dir or "default", "prompt_len": len(full_prompt)},
            run_id=self._run_id,
        )

        # Send prompt via stdin
        self.process.stdin.write(full_prompt.encode("utf-8"))
        await self.process.stdin.drain()
        self.process.stdin.close()

        # Read and parse NDJSON lines using readline() for immediate reads
        while True:
            if self._terminated:
                break

            line = await readline_unlimited(self.process.stdout)
            if not line:  # EOF
                break

            line = line.decode("utf-8").strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                debug_log.warning(
                    f"JSON decode error: {e}",
                    category="json",
                    details={"line": line[:100] if len(line) > 100 else line},
                    run_id=self._run_id,
                )
                continue

            # Log raw event type for debugging
            event_type = data.get("type", "unknown")
            event_subtype = ""
            event_details = {}

            if event_type == "stream_event":
                event_obj = data.get("event", {})
                event_subtype = event_obj.get("type", "")

                # Capture delta content for debugging
                if event_subtype == "content_block_delta":
                    delta = event_obj.get("delta", {})
                    delta_type = delta.get("type", "")
                    if delta_type == "text_delta":
                        text = delta.get("text", "")
                        event_details["text"] = text[:100] if len(text) > 100 else text
                    elif delta_type == "input_json_delta":
                        partial = delta.get("partial_json", "")
                        event_details["json"] = partial[:50] if len(partial) > 50 else partial

            elif event_type == "system":
                event_subtype = data.get("subtype", "")

            debug_log.debug(
                f"{event_type}" + (f"/{event_subtype}" if event_subtype else ""),
                category="llm",
                run_id=self._run_id,
                details=event_details if event_details else None,
            )

            # Always yield raw event for inspection
            yield RawEvent(data=data)

            # Also yield parsed event if recognized
            try:
                event = self._parse_event(data)
                if event:
                    yield event
                    # Give event loop a chance to process UI updates
                    await asyncio.sleep(0)
            except InputRequiredError:
                # Claude is asking a question - terminate the process
                debug_log.info(
                    "Terminating: Claude is asking a question",
                    category="process",
                    run_id=self._run_id,
                )
                self.terminate()
                raise

        # Check for rate limit error before waiting
        stderr_output = await self.process.stderr.read()
        await self.process.wait()

        # Log process exit
        exit_code = self.process.returncode
        stderr_text = stderr_output.decode("utf-8", errors="replace") if stderr_output else ""

        if exit_code != 0:
            debug_log.error(
                f"Claude exited (code {exit_code})",
                category="process",
                details={"stderr": stderr_text[:500] if len(stderr_text) > 500 else stderr_text},
                run_id=self._run_id,
            )
            # Check for rate limit
            if "hit your limit" in stderr_text.lower() or "resets" in stderr_text.lower():
                raise RateLimitError(stderr_text.strip())
        else:
            debug_log.info(f"Claude exited (code 0)", category="process", run_id=self._run_id)

        self._run_id = ""
        self.process = None

    def _parse_event(self, data: dict) -> Union[TextDelta, ResultEvent, InitEvent, ToolUseEvent, ToolResultEvent, None]:
        """Parse a JSON event from Claude's stream output."""
        msg_type = data.get("type")

        if msg_type == "system" and data.get("subtype") == "init":
            return InitEvent(
                model=data.get("model", ""),
                session_id=data.get("session_id", ""),
                context_window=data.get("contextWindow", {}).get("maxTokens", 200000),
            )

        if msg_type == "stream_event":
            event = data.get("event", {})
            event_type = event.get("type")

            if event_type == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    return TextDelta(text=delta.get("text", ""))
                # Accumulate tool input JSON
                if delta.get("type") == "input_json_delta":
                    if self._current_tool_use:
                        self._current_tool_use["input_json"] += delta.get("partial_json", "")

            if event_type == "content_block_start":
                content_block = event.get("content_block", {})
                if content_block.get("type") == "tool_use":
                    # Start tracking a new tool use (capture Claude's tool_use_id)
                    self._current_tool_use = {
                        "id": content_block.get("id", ""),
                        "name": content_block.get("name", ""),
                        "input_json": "",
                    }

            if event_type == "content_block_stop":
                # Tool use complete - emit event
                if self._current_tool_use:
                    import json
                    try:
                        tool_input = json.loads(self._current_tool_use["input_json"]) if self._current_tool_use["input_json"] else {}
                    except json.JSONDecodeError:
                        tool_input = {"raw": self._current_tool_use["input_json"]}

                    event = ToolUseEvent(
                        tool_use_id=self._current_tool_use["id"],
                        tool_name=self._current_tool_use["name"],
                        tool_input=tool_input,
                    )
                    self._current_tool_use = None
                    return event

        # Tool result from user message (Claude CLI returns tool results as user messages)
        # A "user" event without tool_result content means Claude is asking a question
        if msg_type == "user" and data.get("message"):
            message = data.get("message", {})
            has_tool_result = False
            for content in message.get("content", []):
                if content.get("type") == "tool_result":
                    has_tool_result = True
                    return ToolResultEvent(
                        tool_use_id=content.get("tool_use_id", ""),
                        result=content.get("content", ""),
                    )
            # If we got a user message but no tool_result, Claude is asking a question
            if not has_tool_result:
                debug_log.warning(
                    "Received user event without tool_result - Claude may be asking a question",
                    category="llm",
                    run_id=self._run_id,
                    details={"content_types": [c.get("type") for c in message.get("content", [])]},
                )
                raise InputRequiredError("Claude is asking a question (user event without tool_result)")

        if msg_type == "result":
            usage = data.get("usage", {})
            return ResultEvent(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                total_cost_usd=data.get("total_cost_usd", 0.0),
                context_window=200000,  # Could extract from earlier init event
            )

        return None

    def terminate(self):
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
