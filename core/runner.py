"""Session runner for Balloons.

Manages async streaming for individual sessions, enabling background execution.
Each SessionRunner wraps a BaseRunner and maintains an event queue.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import AsyncIterator, Any, Optional

from models import (
    Message, TextDelta, ResultEvent, InitEvent, RawEvent,
    ToolUseStartEvent, ToolInputDeltaEvent, ToolUseEvent, ToolResultEvent,
    TextBlock, ToolUseBlock, ToolResultBlock, ErrorBlock,
)
from .exceptions import RateLimitError, InputRequiredError
from session import Session, Turn
from .debug_log import debug_log
from .base_runner import BaseRunner


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
        - "text_flush": Text segment complete (before tool use), data has text content
        - "tool_use_start": Tool use began, data has tool_use_id, tool_name (input still streaming)
        - "tool_input_delta": Partial tool input JSON, data has tool_use_id, partial_json
        - "tool_use": Tool input complete, data has tool_use_id, tool_name, tool_input, tool_index
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
    """Result of a completed stream operation.

    Contains both the legacy flat structure (content, content_blocks) for
    backwards compatibility, and the new per-turn structure (turns, exchange_id).
    """
    content: str  # Full text content (legacy - combined from all turns)
    content_blocks: list  # Rich content blocks (legacy - all blocks flat)
    raw_events: list[dict]  # Raw JSON events
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    error: Optional[str] = None
    # New per-turn structure
    exchange_id: str = ""  # UUID grouping all turns in this exchange
    turns: list = field(default_factory=list)  # Individual turns (Turn objects)


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

    def __init__(
        self,
        session: Session,
        backend_env: dict[str, str] | None = None,
        runner: BaseRunner | None = None,
    ):
        self.session = session
        # Use provided runner, or create ClaudeRunner for backwards compatibility
        if runner is None:
            from claude_runner import ClaudeRunner
            runner = ClaudeRunner(backend_env=backend_env)
        self._runner = runner

        # Pass session to runners that support link navigation tools
        # ClaudeRunner and OpenAICompatibleRunner both have set_session()
        if hasattr(self._runner, 'set_session'):
            self._runner.set_session(session)
        self._status = RunnerStatus.IDLE
        self._event_queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        self._background_task: Optional[asyncio.Task] = None
        self._result: Optional[StreamResult] = None

        # Accumulation state during streaming
        self._raw_events: list[dict] = []
        self._content_blocks: list = []  # Legacy flat list
        self._text_buffer: str = ""
        self._current_tool_use_id: str = ""
        self._tool_index: int = 0  # Track tool order within turn
        self._turn_index: int = 0  # Track current turn in session

        # New per-turn tracking
        self._exchange_id: str = ""  # UUID for current exchange
        self._turns: list[Turn] = []  # Completed turns in this exchange
        self._user_message_saved: bool = False  # Track if user message added to session

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

        Note: Caller should add the user message to the session before calling this.
        The runner will add assistant/tool turns incrementally as they occur.

        Args:
            prompt: The user prompt
            messages: Context messages
            allowed_tools: List of allowed tool names, or None for all

        Yields:
            StreamEvent for each event from Claude
        """
        self._reset_state()
        self._status = RunnerStatus.STREAMING
        self._turn_index = len(self.session.turns)  # Next turn index

        # Emit turn_started event
        yield self._make_event("turn_started", {
            "turn_index": self._turn_index,
            "prompt": prompt,
            "exchange_id": self._exchange_id,
        })

        try:
            async for event in self._runner.stream_response(
                messages, prompt, allowed_tools,
                working_dir=self.session.working_directory
            ):
                for stream_event in self._process_event(event):
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

        Note: Caller should add the user message to the session before calling this.
        The runner will add assistant/tool turns incrementally as they occur.

        Args:
            prompt: The user prompt
            messages: Context messages
            allowed_tools: List of allowed tool names, or None for all
        """
        if self._status == RunnerStatus.STREAMING:
            raise RuntimeError("Runner is already streaming")

        self._reset_state()
        self._status = RunnerStatus.STREAMING
        self._turn_index = len(self.session.turns)  # Next turn index

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
            "exchange_id": self._exchange_id,
        }))

        try:
            async for event in self._runner.stream_response(
                messages, prompt, allowed_tools,
                working_dir=self.session.working_directory
            ):
                for stream_event in self._process_event(event):
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
        self._runner.terminate()
        self._status = RunnerStatus.CANCELLED

    def _reset_state(self) -> None:
        """Reset accumulation state for a new stream."""
        self._raw_events = []
        self._content_blocks = []
        self._text_buffer = ""
        self._current_tool_use_id = ""
        self._tool_index = 0
        self._result = None
        # New per-turn tracking
        self._exchange_id = str(uuid.uuid4())
        self._turns = []
        self._user_message_saved = False
        # Clear event queue
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _create_turn(self, role: str, content: str, content_blocks: list) -> Turn:
        """Create a Turn with the current exchange_id.

        Args:
            role: "user", "assistant", or "tool"
            content: Text summary for display (not used directly, content_block provides text)
            content_blocks: List with a single content block

        Returns:
            Turn with exchange_id set
        """
        if not content_blocks:
            raise ValueError("content_blocks must contain exactly one block")
        return Turn(
            role=role,
            content_block=content_blocks[0],  # Turn takes single content_block
            timestamp=datetime.now().isoformat(),
            exchange_id=self._exchange_id,
        )

    def _save_turn_to_session(self, turn: Turn, save_now: bool = False) -> None:
        """Add a turn to the session and optionally save to disk.

        This ensures turns are persisted incrementally during agentic loops,
        preventing data loss if the process crashes mid-exchange.

        Args:
            turn: The Turn to add to the session
            save_now: If True, save session to disk immediately
        """
        self.session.turns.append(turn)
        if save_now:
            self.session.save()
            debug_log.debug(
                f"Session saved incrementally ({len(self.session.turns)} turns)",
                session_id=self.session.id,
                category="stream",
            )

    def _flush_text_as_turn(self, emit_event: bool = False, save_now: bool = False) -> list[StreamEvent]:
        """Flush accumulated text buffer as a text turn if non-empty.

        Args:
            emit_event: If True, return events for UI notification
            save_now: If True, save session to disk after adding the turn

        Returns:
            List of StreamEvents if emit_event=True and there was text to flush, else empty list
        """
        events = []
        if self._text_buffer.strip():
            flushed_text = self._text_buffer
            text_block = TextBlock(text=flushed_text)
            self._content_blocks.append(text_block)  # Legacy

            # Get turn index for this text turn
            text_turn_idx = len(self.session.turns)

            # Create turn and save to session
            turn = self._create_turn("assistant", flushed_text, [text_block])
            self._turns.append(turn)
            self._save_turn_to_session(turn, save_now=save_now)
            self._text_buffer = ""

            if emit_event:
                # Emit turn_started for this text turn so UI creates a new node
                events.append(self._make_event("text_turn_started", {
                    "turn_index": text_turn_idx,
                    "exchange_id": self._exchange_id,
                    "role": "assistant",
                    "turn_type": "text",
                    "text_preview": flushed_text[:50] + "..." if len(flushed_text) > 50 else flushed_text,
                }))
                events.append(self._make_event("text_flush", {
                    "text": flushed_text,
                    "turn_index": text_turn_idx,
                }))
        return events

    def _process_event(self, event: Any) -> list[StreamEvent]:
        """Process a raw event from ClaudeRunner.

        Args:
            event: Event from claude_runner stream

        Returns:
            List of StreamEvents to emit (may be empty)
        """
        try:
            if isinstance(event, RawEvent):
                self._raw_events.append(event.data)
                return [self._make_event("raw", event.data)]

            elif isinstance(event, InitEvent):
                self.session.model = event.model
                self.session.context_window = event.context_window
                return [self._make_event("init", {
                    "model": event.model,
                    "context_window": event.context_window,
                })]

            elif isinstance(event, TextDelta):
                self._text_buffer += event.text
                return [self._make_event("text", event.text)]

            elif isinstance(event, ToolUseStartEvent):
                # Tool use started - input is still streaming
                # Flush text buffer before tool (emit events so UI can show it)
                events = []
                flush_events = self._flush_text_as_turn(emit_event=True)
                events.extend(flush_events)

                self._current_tool_use_id = event.tool_use_id
                tool_idx = self._tool_index
                self._tool_index += 1

                events.append(self._make_event("tool_use_start", {
                    "tool_use_id": event.tool_use_id,
                    "tool_name": event.tool_name,
                    "tool_index": tool_idx,
                }))
                return events

            elif isinstance(event, ToolInputDeltaEvent):
                # Partial tool input JSON
                return [self._make_event("tool_input_delta", {
                    "tool_use_id": event.tool_use_id,
                    "partial_json": event.partial_json,
                })]

            elif isinstance(event, ToolUseEvent):
                # Tool input complete - create the block and turn
                tool_block = ToolUseBlock(
                    id=event.tool_use_id,
                    name=event.tool_name,
                    input=event.tool_input,
                )
                self._content_blocks.append(tool_block)  # Legacy

                # Get turn index for this tool_use turn
                tool_use_turn_idx = len(self.session.turns)

                # Create tool_use turn and save to session (don't save to disk yet - wait for result)
                turn = self._create_turn(
                    "assistant",
                    f"[Tool: {event.tool_name}]",
                    [tool_block]
                )
                self._turns.append(turn)
                self._save_turn_to_session(turn, save_now=False)

                # Find the tool_index that was assigned at start
                tool_idx = sum(
                    1 for b in self._content_blocks
                    if isinstance(b, ToolUseBlock) and b.id != event.tool_use_id
                )

                events = []
                # Emit turn_started for this tool_use turn so UI creates a new node
                events.append(self._make_event("tool_use_turn_started", {
                    "turn_index": tool_use_turn_idx,
                    "exchange_id": self._exchange_id,
                    "role": "assistant",
                    "turn_type": "tool_use",
                    "tool_use_id": event.tool_use_id,
                    "tool_name": event.tool_name,
                }))
                events.append(self._make_event("tool_use", {
                    "tool_use_id": event.tool_use_id,
                    "tool_name": event.tool_name,
                    "tool_input": event.tool_input,
                    "tool_index": tool_idx,
                    "tool_block": tool_block,
                    "turn_index": tool_use_turn_idx,
                }))
                return events

            elif isinstance(event, ToolResultEvent):
                result_block = ToolResultBlock(
                    tool_use_id=event.tool_use_id,
                    content=event.result,
                    is_error=False,
                )
                self._content_blocks.append(result_block)  # Legacy

                # Get turn index for this tool_result turn
                tool_result_turn_idx = len(self.session.turns)

                # Create tool_result turn and save to session immediately
                # This is the key checkpoint - tool has executed, we must persist
                turn = self._create_turn(
                    "tool",
                    f"[Result: {len(event.result)} chars]",
                    [result_block]
                )
                self._turns.append(turn)
                self._save_turn_to_session(turn, save_now=True)

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

                # Create result preview for display
                result_preview = event.result[:50] if event.result else ""
                if len(event.result) > 50:
                    result_preview += "..."

                events = []
                # Emit turn_started for this tool_result turn so UI creates a new node
                events.append(self._make_event("tool_result_turn_started", {
                    "turn_index": tool_result_turn_idx,
                    "exchange_id": self._exchange_id,
                    "role": "tool",
                    "turn_type": "tool_result",
                    "tool_use_id": event.tool_use_id,
                    "result_preview": result_preview,
                }))
                events.append(self._make_event("tool_result", {
                    "tool_use_id": event.tool_use_id,
                    "result": event.result,
                    "tool_index": tool_idx,
                    "result_block": result_block,
                    "turn_index": tool_result_turn_idx,
                }))
                return events

            elif isinstance(event, ResultEvent):
                self.session.update_usage(
                    event.input_tokens,
                    event.output_tokens,
                    event.total_cost_usd,
                    event.context_window,
                )
                return [self._make_event("result", {
                    "input_tokens": event.input_tokens,
                    "output_tokens": event.output_tokens,
                    "total_cost": event.total_cost_usd,
                })]

            return []

        except Exception as e:
            debug_log.warning(
                f"Failed to process event: {e}",
                session_id=self.session.id,
                category="llm",
            )
            return []  # Skip bad event

    def _finalize_stream(self) -> None:
        """Finalize stream and create result."""
        # Flush remaining text as turn (also adds to legacy content_blocks)
        self._flush_text_as_turn()

        # Check for stream errors (truncated response, JSON decode errors)
        error_block = self._check_stream_errors()
        if error_block:
            self._content_blocks.append(error_block)
            # Create error turn and save to session
            turn = self._create_turn("assistant", f"[Error: {error_block.reason}]", [error_block])
            self._turns.append(turn)
            self._save_turn_to_session(turn, save_now=True)

        # Reconstruct full text content from all TextBlocks (legacy)
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
            exchange_id=self._exchange_id,
            turns=self._turns,
        )
        self._status = RunnerStatus.IDLE

    def _check_stream_errors(self) -> ErrorBlock | None:
        """Check if the stream ended with errors and create an ErrorBlock if so.

        Returns:
            ErrorBlock if errors occurred, None otherwise
        """
        # Check if runner supports error tracking (ClaudeRunner does)
        if not hasattr(self._runner, 'get_stream_errors'):
            return None

        json_errors, partial_tool = self._runner.get_stream_errors()

        if not json_errors and not partial_tool:
            return None

        # Build error block
        reason = "truncated" if partial_tool else "json_decode_error"
        partial_tool_name = partial_tool.get("name", "") if partial_tool else ""
        partial_tool_input = partial_tool.get("input_json", "") if partial_tool else ""

        # Extract error details and dump file paths from tuples
        error_details = [err[0] for err in json_errors[:3]]  # Limit to first 3
        dump_files = [err[1] for err in json_errors if err[1]]  # Get non-None dump paths
        details = "; ".join(error_details) if error_details else ""
        dump_file = dump_files[0] if dump_files else ""  # Use first dump file

        debug_log.warning(
            f"Stream ended with errors: {reason}",
            session_id=self.session.id,
            category="stream",
            details={
                "json_errors": len(json_errors),
                "partial_tool": partial_tool_name or None,
                "dump_file": dump_file or None,
            },
        )

        return ErrorBlock(
            reason=reason,
            partial_tool_name=partial_tool_name,
            partial_tool_input=partial_tool_input[:500] if partial_tool_input else "",  # Truncate long input
            details=details,
            dump_file=dump_file,
        )


class HelperRunner:
    """Lightweight runner for helper tasks (summaries, compression).

    Unlike SessionRunner, this doesn't track session state - just streams
    text and queues events for the poll timer.
    """

    def __init__(
        self,
        helper_id: str,
        backend_env: dict[str, str] | None = None,
        runner: BaseRunner | None = None,
    ):
        self.helper_id = helper_id  # Unique ID for this helper task
        # Use provided runner, or create ClaudeRunner for backwards compatibility
        if runner is None:
            from claude_runner import ClaudeRunner
            runner = ClaudeRunner(backend_env=backend_env)
        self._runner = runner
        self._status = RunnerStatus.IDLE
        self._event_queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        self._background_task: Optional[asyncio.Task] = None
        self._text_buffer: str = ""
        self._result: Optional[str] = None  # Just the text result

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
        """Create an event tagged with this helper's ID."""
        return StreamEvent(event_type, data, session_id=self.helper_id)

    def start_background(self, prompt: str) -> None:
        """Start helper streaming in background.

        Args:
            prompt: The prompt to send (no message history for helpers)
        """
        if self._status == RunnerStatus.STREAMING:
            raise RuntimeError("Helper is already streaming")

        self._text_buffer = ""
        self._result = None
        self._status = RunnerStatus.STREAMING
        self._background_task = asyncio.create_task(
            self._background_stream(prompt)
        )

    async def _background_stream(self, prompt: str) -> None:
        """Internal: background streaming task."""
        try:
            async for event in self._runner.stream_response(
                [], prompt, disable_tools=True
            ):
                if isinstance(event, TextDelta):
                    self._text_buffer += event.text
                    await self._event_queue.put(self._make_event("text", event.text))

            # Done - emit result
            self._result = self._text_buffer
            self._status = RunnerStatus.IDLE
            await self._event_queue.put(self._make_event("done", self._result))

        except asyncio.CancelledError:
            self._status = RunnerStatus.CANCELLED
            await self._event_queue.put(self._make_event("cancelled", None))
        except Exception as e:
            self._status = RunnerStatus.ERROR
            debug_log.error(f"Helper stream error: {e}", category="stream")
            await self._event_queue.put(self._make_event("error", str(e)))

    def drain_events(self) -> list[StreamEvent]:
        """Get all queued events without blocking."""
        events = []
        while not self._event_queue.empty():
            try:
                events.append(self._event_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    def get_result(self) -> Optional[str]:
        """Get the text result of a completed stream."""
        return self._result if self.is_done else None

    def cancel(self) -> None:
        """Cancel an ongoing stream."""
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
        self._runner.terminate()
        self._status = RunnerStatus.CANCELLED
