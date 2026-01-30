import asyncio
import json
import signal
from typing import AsyncIterator, Union

from models import Message, TextDelta, ResultEvent, InitEvent, RawEvent, ToolUseEvent, ToolResultEvent


class ClaudeRunner:
    def __init__(self):
        self.process: asyncio.subprocess.Process | None = None
        self._terminated = False
        self._current_tool_use: dict | None = None  # Track tool use being built

    @staticmethod
    def build_context(messages: list[Message], new_prompt: str) -> str:
        """Build the full context string from message history + new prompt."""
        parts = []
        for msg in messages:
            prefix = "User" if msg.role == "user" else "Assistant"
            parts.append(f"{prefix}: {msg.content}")
        parts.append(f"User: {new_prompt}")
        return "\n\n".join(parts)

    async def stream_response(
        self, messages: list[Message], prompt: str, allowed_tools: list[str] | None = None
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
        ]

        if allowed_tools:
            cmd.extend(["--allowedTools", ",".join(allowed_tools)])

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Send prompt via stdin
        self.process.stdin.write(full_prompt.encode("utf-8"))
        await self.process.stdin.drain()
        self.process.stdin.close()

        # Read and parse NDJSON lines using readline() for immediate reads
        while True:
            if self._terminated:
                break

            line = await self.process.stdout.readline()
            if not line:  # EOF
                break

            line = line.decode("utf-8").strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Always yield raw event for inspection
            yield RawEvent(data=data)

            # Also yield parsed event if recognized
            event = self._parse_event(data)
            if event:
                yield event
                # Give event loop a chance to process UI updates
                await asyncio.sleep(0)

        await self.process.wait()
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
                    # Start tracking a new tool use
                    self._current_tool_use = {
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
                        tool_name=self._current_tool_use["name"],
                        tool_input=tool_input,
                    )
                    self._current_tool_use = None
                    return event

        # Tool result from assistant message
        if msg_type == "assistant" and data.get("message"):
            message = data.get("message", {})
            for content in message.get("content", []):
                if content.get("type") == "tool_result":
                    return ToolResultEvent(
                        tool_name=content.get("tool_use_id", ""),
                        result=content.get("content", ""),
                    )

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
