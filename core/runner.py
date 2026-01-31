"""Session runner for Balloons.

Manages async streaming for individual sessions, enabling background execution.
Each SessionRunner wraps a ClaudeRunner and maintains an event queue.
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Any, Optional

from models import (
    Message, TextDelta, ResultEvent, InitEvent, RawEvent,
    ToolUseEvent, ToolResultEvent, TextBlock, ToolUseBlock, ToolResultBlock,
)
from claude_runner import ClaudeRunner, RateLimitError, InputRequiredError
from session import Session
from .debug_log import debug_log


class RunnerStatus(Enum):
    """Status of a session runner."""
    IDLE = "idle"
    STREAMING = "streaming"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class StreamEvent:
    """Wrapper for events emitted during streaming.

    Event types:
        - "turn_started": Stream began, data has session_id and turn_index
        - "text": Text delta, data is the text string
        - "tool_use": Tool invocation, data has tool_use_id, tool_name, tool_input, tool_index
        - "tool_result": Tool completed, data has tool_use_id, result, tool_index
        - "init": Init event, data has model, context_window
        - "result": Usage stats, data has input_tokens, output_tokens, total_cost
        - "raw": Raw JSON event
        - "done": Stream complete, data is StreamResult
        - "error": Error occurred, data is error message
        - "rate_limit": Rate limit hit, data is error message with reset time
        - "cancelled": Stream was cancelled
        - "input_required": Claude is asking a question (non-interactive mode), data is message
    """
    event_type: str
    data: Any = None
    session_id: str = ""  # Which session this event belongs to


@dataclass
class StreamResult:
    """Result of a completed stream operation."""
    content: str  # Full text content
    content_blocks: list  # Rich content blocks (TextBlock, ToolUseBlock, etc.)
    raw_events: list[dict]  # Raw JSON events
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    error: Optional[str] = None


class SessionRunner:
    """Manages streaming for a single session.

    Can run in foreground (blocking) or background (async with event queue).

    Usage (foreground):
        runner = SessionRunner(session)
        async for event in runner.stream(prompt, messages):
            # Handle event

    Usage (background):
        runner = SessionRunner(session)
        runner.start_background(prompt, messages)
        # Later...
        events = runner.drain_events()
        if runner.is_done:
            result = runner.get_result()
    """

    def __init__(self, session: Session):
        self.session = session
        self._claude_runner = ClaudeRunner()
        self._status = RunnerStatus.IDLE
        self._event_queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        self._background_task: Optional[asyncio.Task] = None
        self._result: Optional[StreamResult] = None

        # Accumulation state during streaming
        self._raw_events: list[dict] = []
        self._content_blocks: list = []
        self._text_buffer: str = ""
        self._current_tool_use_id: str = ""
        self._tool_index: int = 0  # Track tool order within turn
        self._turn_index: int = 0  # Track current turn in session

    @property
    def status(self) -> RunnerStatus:
        return self._status

    @property
    def is_streaming(self) -> bool:
        return self._status == RunnerStatus.STREAMING

    @property
    def is_done(self) -> bool:
        return self._status in (RunnerStatus.IDLE, RunnerStatus.ERROR, RunnerStatus.CANCELLED)

    def _make_event(self, event_type: str, data: Any = None) -> StreamEvent:
        """Create an event tagged with this session's ID."""
        return StreamEvent(event_type, data, session_id=self.session.id)

    async def stream(
        self,
        prompt: str,
        messages: list[Message],
        allowed_tools: list[str] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a response, yielding events as they arrive.

        This is the foreground streaming mode - blocks until complete.

        Args:
            prompt: The user prompt
            messages: Context messages
            allowed_tools: List of allowed tool names, or None for all

        Yields:
            StreamEvent for each event from Claude
        """
        self._reset_state()
        self._status = RunnerStatus.STREAMING
        self._turn_index = len(self.session.messages)  # Next turn index

        # Emit turn_started event
        yield self._make_event("turn_started", {
            "turn_index": self._turn_index,
            "prompt": prompt,
        })

        try:
            async for event in self._claude_runner.stream_response(
                messages, prompt, allowed_tools,
                working_dir=self.session.working_directory
            ):
                stream_event = self._process_event(event)
                if stream_event:
                    yield stream_event

            # Finalize
            self._finalize_stream()
            yield self._make_event("done", self._result)

        except asyncio.CancelledError:
            self._status = RunnerStatus.CANCELLED
            raise
        except RateLimitError as e:
            self._status = RunnerStatus.ERROR
            debug_log.warning(f"Rate limit: {e}", session_id=self.session.id, category="stream")
            self._result = StreamResult(
                content=self._text_buffer,
                content_blocks=self._content_blocks,
                raw_events=self._raw_events,
                error=str(e),
            )
            yield self._make_event("rate_limit", str(e))
        except InputRequiredError as e:
            self._status = RunnerStatus.IDLE  # Not an error - just needs input
            debug_log.info(f"Input required: {e}", session_id=self.session.id, category="stream")
            self._finalize_stream()
            self._result.error = "Claude is asking a question"
            yield self._make_event("input_required", str(e))
        except Exception as e:
            self._status = RunnerStatus.ERROR
            debug_log.error(f"Stream error: {e}", session_id=self.session.id, category="stream")
            self._result = StreamResult(
                content=self._text_buffer,
                content_blocks=self._content_blocks,
                raw_events=self._raw_events,
                error=str(e),
            )
            yield self._make_event("error", str(e))

    def start_background(
        self,
        prompt: str,
        messages: list[Message],
        allowed_tools: list[str] | None = None,
    ) -> None:
        """Start streaming in background, queueing events.

        Events can be retrieved via drain_events().
        When done, is_done will be True and get_result() returns the result.

        Args:
            prompt: The user prompt
            messages: Context messages
            allowed_tools: List of allowed tool names, or None for all
        """
        if self._status == RunnerStatus.STREAMING:
            raise RuntimeError("Runner is already streaming")

        self._reset_state()
        self._status = RunnerStatus.STREAMING
        self._turn_index = len(self.session.messages)  # Next turn index
        self._background_task = asyncio.create_task(
            self._background_stream(prompt, messages, allowed_tools)
        )

    async def _background_stream(
        self,
        prompt: str,
        messages: list[Message],
        allowed_tools: list[str] | None,
    ) -> None:
        """Internal: background streaming task."""
        # Emit turn_started event
        await self._event_queue.put(self._make_event("turn_started", {
            "turn_index": self._turn_index,
            "prompt": prompt,
        }))

        try:
            async for event in self._claude_runner.stream_response(
                messages, prompt, allowed_tools,
                working_dir=self.session.working_directory
            ):
                stream_event = self._process_event(event)
                if stream_event:
                    await self._event_queue.put(stream_event)

            # Finalize
            self._finalize_stream()
            debug_log.info("Emitting done event", category="stream", session_id=self.session.id)
            await self._event_queue.put(self._make_event("done", self._result))
            self._status = RunnerStatus.IDLE

        except asyncio.CancelledError:
            self._status = RunnerStatus.CANCELLED
            await self._event_queue.put(self._make_event("cancelled", None))
        except RateLimitError as e:
            self._status = RunnerStatus.ERROR
            debug_log.warning(f"Rate limit: {e}", session_id=self.session.id, category="stream")
            self._result = StreamResult(
                content=self._text_buffer,
                content_blocks=self._content_blocks,
                raw_events=self._raw_events,
                error=str(e),
            )
            await self._event_queue.put(self._make_event("rate_limit", str(e)))
        except InputRequiredError as e:
            self._status = RunnerStatus.IDLE  # Not an error - just needs input
            debug_log.info(f"Input required: {e}", session_id=self.session.id, category="stream")
            self._finalize_stream()
            self._result.error = "Claude is asking a question"
            await self._event_queue.put(self._make_event("input_required", str(e)))
        except Exception as e:
            self._status = RunnerStatus.ERROR
            debug_log.error(f"Stream error: {e}", session_id=self.session.id, category="stream")
            self._result = StreamResult(
                content=self._text_buffer,
                content_blocks=self._content_blocks,
                raw_events=self._raw_events,
                error=str(e),
            )
            await self._event_queue.put(self._make_event("error", str(e)))

    def drain_events(self) -> list[StreamEvent]:
        """Get all queued events without blocking.

        Returns:
            List of events queued since last drain
        """
        events = []
        while not self._event_queue.empty():
            try:
                events.append(self._event_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    async def wait_for_event(self, timeout: float = None) -> Optional[StreamEvent]:
        """Wait for the next event.

        Args:
            timeout: Max seconds to wait, or None to wait forever

        Returns:
            Next event, or None if timeout
        """
        try:
            if timeout:
                return await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=timeout
                )
            else:
                return await self._event_queue.get()
        except asyncio.TimeoutError:
            return None

    def get_result(self) -> Optional[StreamResult]:
        """Get the result of a completed stream.

        Returns:
            StreamResult if stream is done, None otherwise
        """
        return self._result if self.is_done else None

    def cancel(self) -> None:
        """Cancel an ongoing stream."""
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
        self._claude_runner.terminate()
        self._status = RunnerStatus.CANCELLED

    def _reset_state(self) -> None:
        """Reset accumulation state for a new stream."""
        self._raw_events = []
        self._content_blocks = []
        self._text_buffer = ""
        self._current_tool_use_id = ""
        self._tool_index = 0
        self._result = None
        # Clear event queue
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _process_event(self, event: Any) -> Optional[StreamEvent]:
        """Process a raw event from ClaudeRunner.

        Args:
            event: Event from claude_runner stream

        Returns:
            StreamEvent to emit, or None
        """
        try:
            if isinstance(event, RawEvent):
                self._raw_events.append(event.data)
                return self._make_event("raw", event.data)

            elif isinstance(event, InitEvent):
                self.session.model = event.model
                self.session.context_window = event.context_window
                return self._make_event("init", {
                    "model": event.model,
                    "context_window": event.context_window,
                })

            elif isinstance(event, TextDelta):
                self._text_buffer += event.text
                return self._make_event("text", event.text)

            elif isinstance(event, ToolUseEvent):
                # Flush text buffer to content block
                if self._text_buffer.strip():
                    self._content_blocks.append(TextBlock(text=self._text_buffer))
                    self._text_buffer = ""

                # Create tool use block
                self._current_tool_use_id = event.tool_use_id
                tool_block = ToolUseBlock(
                    id=event.tool_use_id,
                    name=event.tool_name,
                    input=event.tool_input,
                )
                self._content_blocks.append(tool_block)

                tool_idx = self._tool_index
                self._tool_index += 1

                return self._make_event("tool_use", {
                    "tool_use_id": event.tool_use_id,
                    "tool_name": event.tool_name,
                    "tool_input": event.tool_input,
                    "tool_index": tool_idx,
                    "tool_block": tool_block,
                })

            elif isinstance(event, ToolResultEvent):
                result_block = ToolResultBlock(
                    tool_use_id=event.tool_use_id,
                    content=event.result,
                    is_error=False,
                )
                self._content_blocks.append(result_block)

                # Find the tool_index for this result (matches the tool_use_id)
                tool_idx = None
                for i, block in enumerate(self._content_blocks):
                    if isinstance(block, ToolUseBlock) and block.id == event.tool_use_id:
                        # Count how many tool uses came before this one
                        tool_idx = sum(
                            1 for b in self._content_blocks[:i]
                            if isinstance(b, ToolUseBlock)
                        )
                        break

                return self._make_event("tool_result", {
                    "tool_use_id": event.tool_use_id,
                    "result": event.result,
                    "tool_index": tool_idx,
                    "result_block": result_block,
                })

            elif isinstance(event, ResultEvent):
                self.session.update_usage(
                    event.input_tokens,
                    event.output_tokens,
                    event.total_cost_usd,
                    event.context_window,
                )
                return self._make_event("result", {
                    "input_tokens": event.input_tokens,
                    "output_tokens": event.output_tokens,
                    "total_cost": event.total_cost_usd,
                })

            return None

        except Exception as e:
            debug_log.warning(
                f"Failed to process event: {e}",
                session_id=self.session.id,
                category="event",
            )
            return None  # Skip bad event

    def _finalize_stream(self) -> None:
        """Finalize stream and create result."""
        # Flush remaining text
        if self._text_buffer.strip():
            self._content_blocks.append(TextBlock(text=self._text_buffer))

        # Reconstruct full text content from all TextBlocks
        text_parts = []
        for block in self._content_blocks:
            if isinstance(block, TextBlock) and block.text.strip():
                text_parts.append(block.text)
        full_content = "\n\n".join(text_parts)

        self._result = StreamResult(
            content=full_content,
            content_blocks=self._content_blocks,
            raw_events=self._raw_events,
            input_tokens=self.session.total_input_tokens,
            output_tokens=self.session.total_output_tokens,
            total_cost=self.session.total_cost,
        )
        self._status = RunnerStatus.IDLE
