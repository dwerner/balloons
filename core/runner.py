"""Session runner for Balloons.

Manages async streaming for individual sessions, enabling background execution.
Each SessionRunner wraps a BaseRunner and maintains an event queue.
"""

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import AsyncIterator, Any, Optional

from models import (
    Message, TextDelta, ResultEvent, InitEvent, RawEvent, ContextTokensEvent,
    ToolUseStartEvent, ToolInputDeltaEvent, ToolUseEvent, ToolResultEvent,
    TextBlock, ToolUseBlock, ToolResultBlock, ErrorBlock,
)
from .exceptions import RateLimitError, InputRequiredError, StreamTimeoutError
from .binding_context import build_binding_context_for_session
from session import Session, Turn
from .debug_log import debug_log, perf_marker, Category
from .base_runner import BaseRunner


# =============================================================================
# Utility Functions
# =============================================================================

# Pattern to match <system-reminder>...</system-reminder> blocks
# Captures surrounding whitespace to clean up the result
_SYSTEM_REMINDER_PATTERN = re.compile(
    r'\s*<system-reminder>[\s\S]*?</system-reminder>\s*',
    re.MULTILINE
)

# Pattern to extract just the reminder content (for logging)
_SYSTEM_REMINDER_CONTENT_PATTERN = re.compile(
    r'<system-reminder>([\s\S]*?)</system-reminder>',
    re.MULTILINE
)

# Track already-logged reminders to avoid duplicates within a running instance
_logged_reminders: set[str] = set()


def _log_system_reminder(reminder_content: str, session_id: str = "") -> None:
    """Log a stripped system reminder to a separate JSONL file.

    Deduplicates within a running instance - each unique reminder is logged once.
    """
    import json
    from pathlib import Path

    reminder_stripped = reminder_content.strip()

    # Skip if we've already logged this exact reminder
    if reminder_stripped in _logged_reminders:
        return
    _logged_reminders.add(reminder_stripped)

    log_dir = Path.home() / ".balloons" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "system_reminders.jsonl"

    entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "reminder": reminder_stripped,
    }

    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Don't let logging failures break tool results


def strip_system_reminders(text: str, session_id: str = "") -> str:
    """Strip <system-reminder> tags from tool result content.

    Claude's API injects these reminders into tool results, but they're noise
    for display and waste tokens when re-sent in context.

    Stripped reminders are logged to ~/.balloons/logs/system_reminders.jsonl
    """
    # Find and log any reminders before stripping
    for match in _SYSTEM_REMINDER_CONTENT_PATTERN.finditer(text):
        _log_system_reminder(match.group(1), session_id)

    result = _SYSTEM_REMINDER_PATTERN.sub('', text)
    return result.rstrip()  # Clean trailing whitespace


# =============================================================================
# Runner State Types
# =============================================================================

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
        self._last_tool_index_for_text: int = 0  # Track if text is post-tool (for new turn events)
        self._pending_text_turn_id: str | None = None  # Turn ID for post-tool text (sent in text_turn_started)

        # New per-turn tracking
        self._exchange_id: str = ""  # UUID for current exchange
        self._turns: list[Turn] = []  # Completed turns in this exchange
        self._user_message_saved: bool = False  # Track if user message added to session
        # Timing tracking for diagnosing streaming hangs
        self._text_turn_started_at: str | None = None  # When first text arrived
        self._tool_use_started_at: dict[str, str] = {}  # tool_use_id -> ISO timestamp
        # Pre-generated ID for the initial assistant turn (used in turn_started event)
        self._initial_turn_id: str | None = None

        # Debounced save state - coalesce rapid save requests
        self._save_pending: bool = False
        self._save_task: Optional[asyncio.Task] = None
        self._save_debounce_interval: float = 0.5  # 500ms debounce

    @property
    def status(self) -> RunnerStatus:
        return self._status

    @property
    def is_streaming(self) -> bool:
        return self._status == RunnerStatus.STREAMING

    @property
    def is_done(self) -> bool:
        return self._status in (RunnerStatus.IDLE, RunnerStatus.ERROR, RunnerStatus.CANCELLED)

    def set_injection_callback(self, callback) -> None:
        """Set a callback for mid-stream message injection.

        The callback is called after each tool execution. If it returns
        a string, that message is injected into the conversation before
        the next LLM call, allowing users to steer without cancelling.

        Args:
            callback: Async function returning message to inject, or None
        """
        if hasattr(self._runner, 'set_injection_callback'):
            self._runner.set_injection_callback(callback)

    def _make_event(self, event_type: str, data: Any = None) -> StreamEvent:
        """Create an event tagged with this session's ID."""
        return StreamEvent(event_type, data, session_id=self.session.id)

    async def _build_prompt_with_bindings(self, prompt: str) -> str:
        """Build prompt with binding context prepended.

        If the session has active bindings to goals/plans/todos, their
        context is prepended to the prompt so the LLM stays aligned.

        Args:
            prompt: The user's prompt

        Returns:
            Prompt with binding context prepended, or original prompt if no bindings
        """
        try:
            # Check if this session is a fork (has a parent)
            is_fork = self.session.parent_id is not None
            binding_context = await build_binding_context_for_session(
                self.session.id, is_fork=is_fork
            )
            if binding_context:
                debug_log.info(
                    f"Prepending binding context ({len(binding_context)} chars, is_fork={is_fork})",
                    session_id=self.session.id,
                    category=Category.RUNNER,
                )
                return f"{binding_context}\n\n---\n\n{prompt}"
            return prompt
        except Exception as e:
            debug_log.warning(
                f"Failed to load binding context: {e}",
                session_id=self.session.id,
                category=Category.RUNNER,
            )
            return prompt

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
        import time

        self._reset_state()
        self._status = RunnerStatus.STREAMING
        self._turn_index = len(self.session.turns)  # Next turn index

        # If this is a watcher session, include watcher tools (send_to_target)
        if self.session.is_watcher:
            if allowed_tools is None:
                # None means "all tools" - add watcher tools to that set
                allowed_tools = None  # Keep as None, watcher tools will be included via system
            else:
                # Specific allowed tools - add send_to_target
                allowed_tools = list(allowed_tools) + ["send_to_target"]
            debug_log.debug(
                "Watcher session - including send_to_target tool",
                session_id=self.session.id,
                category=Category.RUNNER,
            )

        # Add binding context to prompt if session has active bindings
        effective_prompt = await self._build_prompt_with_bindings(prompt)

        # Emit turn_started event with pre-generated turn_id so web UI can track it
        yield self._make_event("turn_started", {
            "turn_index": self._turn_index,
            "turn_id": self._initial_turn_id,
            "prompt": prompt,  # Original prompt for display
            "exchange_id": self._exchange_id,
        })

        stream_start = time.perf_counter()
        first_token_time = None
        token_count = 0

        try:
            async for event in self._runner.stream_response(
                messages, effective_prompt, allowed_tools,
                working_dir=self.session.working_directory
            ):
                # Track first token timing
                if first_token_time is None and isinstance(event, TextDelta):
                    first_token_time = time.perf_counter()
                    ttft_ms = (first_token_time - stream_start) * 1000
                    perf_marker(
                        "llm.first_token",
                        session_id=self.session.id[:8],
                        ttft_ms=round(ttft_ms, 1),
                    )
                if isinstance(event, TextDelta):
                    token_count += 1

                for stream_event in self._process_event(event):
                    yield stream_event

            # Log stream completion timing
            stream_elapsed_ms = (time.perf_counter() - stream_start) * 1000
            perf_marker(
                "llm.stream_complete",
                session_id=self.session.id[:8],
                elapsed_ms=round(stream_elapsed_ms, 1),
                token_events=token_count,
            )

            # Finalize - emit any final turn events before done
            final_events = await self._finalize_stream()
            for event in final_events:
                yield event
            yield self._make_event("done", self._result)

        except asyncio.CancelledError:
            self._status = RunnerStatus.CANCELLED
            raise
        except RateLimitError as e:
            self._status = RunnerStatus.ERROR
            debug_log.warning(f"Rate limit: {e}", session_id=self.session.id, category=Category.RUNNER)
            self._result = StreamResult(
                content=self._text_buffer,
                content_blocks=self._content_blocks,
                raw_events=self._raw_events,
                error=str(e),
            )
            yield self._make_event("rate_limit", str(e))
        except InputRequiredError as e:
            self._status = RunnerStatus.IDLE  # Not an error - just needs input
            debug_log.info(f"Input required: {e}", session_id=self.session.id, category=Category.RUNNER)
            await self._finalize_stream()
            self._result.error = "Claude is asking a question"
            yield self._make_event("input_required", str(e))
        except StreamTimeoutError as e:
            self._status = RunnerStatus.ERROR
            debug_log.error(f"Stream timeout: {e}", session_id=self.session.id, category=Category.RUNNER)
            # Create an error turn with the timeout info
            error_block = ErrorBlock(
                reason="timeout",
                details=str(e),
            )
            self._content_blocks.append(error_block)
            turn = self._create_turn("assistant", f"[Timeout: {e}]", [error_block])
            self._turns.append(turn)
            self._save_turn_to_session(turn, save_now=True)
            await self._flush_pending_save()
            self._result = StreamResult(
                content=self._text_buffer,
                content_blocks=self._content_blocks,
                raw_events=self._raw_events,
                error=str(e),
                exchange_id=self._exchange_id,
                turns=self._turns,
            )
            yield self._make_event("error", str(e))
        except Exception as e:
            self._status = RunnerStatus.ERROR
            debug_log.error(f"Stream error: {e}", session_id=self.session.id, category=Category.RUNNER)
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

        # If this is a watcher session, include watcher tools (send_to_target)
        if self.session.is_watcher:
            if allowed_tools is not None:
                # Specific allowed tools - add send_to_target
                allowed_tools = list(allowed_tools) + ["send_to_target"]

        # Debug log to trace turn_id
        from core.debug_log import debug_log
        debug_log.info(
            f"SessionRunner.start_background: _initial_turn_id={self._initial_turn_id}, session={self.session.id[:8]}",
            category=Category.RUNNER,
        )

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
        import time

        # Add binding context to prompt if session has active bindings
        effective_prompt = await self._build_prompt_with_bindings(prompt)

        # Emit turn_started event with pre-generated turn_id so web UI can track it
        await self._event_queue.put(self._make_event("turn_started", {
            "turn_index": self._turn_index,
            "turn_id": self._initial_turn_id,
            "prompt": prompt,  # Original prompt for display
            "exchange_id": self._exchange_id,
        }))

        stream_start = time.perf_counter()
        first_token_time = None
        token_count = 0

        try:
            async for event in self._runner.stream_response(
                messages, effective_prompt, allowed_tools,
                working_dir=self.session.working_directory
            ):
                # Track first token timing
                if first_token_time is None and isinstance(event, TextDelta):
                    first_token_time = time.perf_counter()
                    ttft_ms = (first_token_time - stream_start) * 1000
                    perf_marker(
                        "llm.first_token",
                        session_id=self.session.id[:8],
                        ttft_ms=round(ttft_ms, 1),
                    )
                if isinstance(event, TextDelta):
                    token_count += 1

                for stream_event in self._process_event(event):
                    await self._event_queue.put(stream_event)

            # Log stream completion timing
            stream_elapsed_ms = (time.perf_counter() - stream_start) * 1000
            perf_marker(
                "llm.stream_complete",
                session_id=self.session.id[:8],
                elapsed_ms=round(stream_elapsed_ms, 1),
                token_events=token_count,
            )

            # Finalize - emit any final turn events before done
            final_events = await self._finalize_stream()
            for event in final_events:
                await self._event_queue.put(event)
            debug_log.info("Emitting done event", category=Category.RUNNER, session_id=self.session.id)
            await self._event_queue.put(self._make_event("done", self._result))
            self._status = RunnerStatus.IDLE

        except asyncio.CancelledError:
            self._status = RunnerStatus.CANCELLED
            await self._event_queue.put(self._make_event("cancelled", None))
        except RateLimitError as e:
            self._status = RunnerStatus.ERROR
            debug_log.warning(f"Rate limit: {e}", session_id=self.session.id, category=Category.RUNNER)
            self._result = StreamResult(
                content=self._text_buffer,
                content_blocks=self._content_blocks,
                raw_events=self._raw_events,
                error=str(e),
            )
            await self._event_queue.put(self._make_event("rate_limit", str(e)))
        except InputRequiredError as e:
            self._status = RunnerStatus.IDLE  # Not an error - just needs input
            debug_log.info(f"Input required: {e}", session_id=self.session.id, category=Category.RUNNER)
            await self._finalize_stream()
            self._result.error = "Claude is asking a question"
            await self._event_queue.put(self._make_event("input_required", str(e)))
        except StreamTimeoutError as e:
            self._status = RunnerStatus.ERROR
            debug_log.error(f"Stream timeout: {e}", session_id=self.session.id, category=Category.RUNNER)
            # Create an error turn with the timeout info
            error_block = ErrorBlock(
                reason="timeout",
                details=str(e),
            )
            self._content_blocks.append(error_block)
            turn = self._create_turn("assistant", f"[Timeout: {e}]", [error_block])
            self._turns.append(turn)
            self._save_turn_to_session(turn, save_now=True)
            await self._flush_pending_save()
            self._result = StreamResult(
                content=self._text_buffer,
                content_blocks=self._content_blocks,
                raw_events=self._raw_events,
                error=str(e),
                exchange_id=self._exchange_id,
                turns=self._turns,
            )
            await self._event_queue.put(self._make_event("error", str(e)))
        except Exception as e:
            self._status = RunnerStatus.ERROR
            debug_log.error(f"Stream error: {e}", session_id=self.session.id, category=Category.RUNNER)
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
        # Put cancelled event directly - the async task may not complete to emit it
        self._event_queue.put_nowait(self._make_event("cancelled", None))

    def _reset_state(self) -> None:
        """Reset accumulation state for a new stream."""
        self._raw_events = []
        self._content_blocks = []
        self._text_buffer = ""
        self._current_tool_use_id = ""
        self._tool_index = 0
        self._last_tool_index_for_text = 0  # Reset post-tool tracking
        self._pending_text_turn_id = None  # Reset pending turn ID
        self._result = None
        # New per-turn tracking
        self._exchange_id = str(uuid.uuid4())
        self._turns = []
        self._user_message_saved = False
        # Timing tracking for diagnosing streaming hangs
        self._text_turn_started_at: str | None = None  # When first text arrived
        self._tool_use_started_at: dict[str, str] = {}  # tool_use_id -> ISO timestamp
        # Pre-generated ID for the initial assistant turn (used in turn_started event)
        self._initial_turn_id: str = str(uuid.uuid4())
        # Clear event queue
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _create_turn(
        self,
        role: str,
        content: str,
        content_blocks: list,
        started_at: str | None = None,
        ended_at: str | None = None,
        turn_id: str | None = None,
        parallel_group_id: str | None = None,
    ) -> Turn:
        """Create a Turn with the current exchange_id and timing info.

        Args:
            role: "user", "assistant", or "tool"
            content: Text summary for display (not used directly, content_block provides text)
            content_blocks: List with a single content block
            started_at: ISO timestamp when this turn began streaming (optional)
            ended_at: ISO timestamp when this turn completed (optional, defaults to now)
            turn_id: Pre-generated turn ID (optional, auto-generated if not provided)
            parallel_group_id: Groups parallel tool calls from same LLM response

        Returns:
            Turn with exchange_id and timing fields set
        """
        if not content_blocks:
            raise ValueError("content_blocks must contain exactly one block")
        now = datetime.now().isoformat()
        turn = Turn(
            role=role,
            content_block=content_blocks[0],  # Turn takes single content_block
            timestamp=now,
            exchange_id=self._exchange_id,
            started_at=started_at,
            ended_at=ended_at or now,  # Default ended_at to now if not specified
            parallel_group_id=parallel_group_id,
        )
        # Use pre-generated ID if provided (e.g., from turn_started event)
        if turn_id:
            turn.id = turn_id
        return turn

    def _save_turn_to_session(self, turn: Turn, save_now: bool = False) -> None:
        """Add a turn to the session and optionally save to disk.

        This ensures turns are persisted incrementally during agentic loops,
        preventing data loss if the process crashes mid-exchange.

        Args:
            turn: The Turn to add to the session
            save_now: If True, schedule a debounced save to disk (non-blocking)
        """
        self.session.turns.append(turn)
        if save_now:
            self._schedule_debounced_save()

    def _schedule_debounced_save(self) -> None:
        """Schedule a debounced save - coalesces rapid save requests.

        Instead of saving immediately on every tool result, we mark the session
        as needing a save and schedule it after a short delay. Multiple save
        requests within the debounce interval are coalesced into a single save.
        """
        self._save_pending = True

        # Only schedule new task if one isn't already pending
        if self._save_task is None or self._save_task.done():
            self._save_task = asyncio.create_task(self._debounced_save())

    async def _debounced_save(self) -> None:
        """Wait for debounce interval then save if still pending."""
        await asyncio.sleep(self._save_debounce_interval)

        if self._save_pending:
            self._save_pending = False
            await self._async_save_session()

    async def _async_save_session(self) -> None:
        """Save session asynchronously without blocking the event loop."""
        try:
            await self.session.save()
            debug_log.debug(
                f"Session saved incrementally ({len(self.session.turns)} turns)",
                session_id=self.session.id,
                category=Category.RUNNER,
            )
        except Exception as e:
            debug_log.error(
                f"Async session save failed: {e}",
                session_id=self.session.id,
                category=Category.RUNNER,
            )

    async def _flush_pending_save(self) -> None:
        """Immediately save if there's a pending save (call on stream completion)."""
        if self._save_pending:
            self._save_pending = False
            if self._save_task is not None and not self._save_task.done():
                self._save_task.cancel()
                try:
                    await self._save_task
                except asyncio.CancelledError:
                    pass
            await self._async_save_session()

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

            # Determine which turn ID to use:
            # 1. If there's a pending post-tool turn ID, use that (matches text_turn_started event)
            # 2. For the first text turn, use the pre-generated initial ID
            # 3. Otherwise, let _create_turn generate a new one
            use_pending_id = self._pending_text_turn_id is not None
            use_initial_id = not use_pending_id and self._initial_turn_id is not None and len(self._turns) == 0

            turn_id_to_use = None
            if use_pending_id:
                turn_id_to_use = self._pending_text_turn_id
            elif use_initial_id:
                turn_id_to_use = self._initial_turn_id

            # Create turn with timing info and save to session
            turn = self._create_turn(
                "assistant",
                flushed_text,
                [text_block],
                started_at=self._text_turn_started_at,
                turn_id=turn_id_to_use,
            )
            self._turns.append(turn)
            self._save_turn_to_session(turn, save_now=save_now)
            self._text_buffer = ""
            self._text_turn_started_at = None  # Reset for next text turn

            # Clear pending turn ID after use (post-tool text was flushed)
            if use_pending_id:
                self._pending_text_turn_id = None
            # Clear initial turn ID after first use so subsequent turns get new IDs
            if use_initial_id:
                self._initial_turn_id = None

            if emit_event:
                # Only emit text_turn_started if we didn't already send it in TextDelta handler
                # (use_pending_id means we already sent text_turn_started for post-tool text)
                if not use_pending_id:
                    events.append(self._make_event("text_turn_started", {
                        "turn_index": text_turn_idx,
                        "turn_id": turn.id,
                        "exchange_id": self._exchange_id,
                        "role": "assistant",
                        "turn_type": "text",
                        "text_preview": flushed_text[:50] + "..." if len(flushed_text) > 50 else flushed_text,
                    }))
                events.append(self._make_event("text_flush", {
                    "text": flushed_text,
                    "turn_index": text_turn_idx,
                    "turn_id": turn.id,
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
                events = []

                # Check if this is the start of a NEW text segment after tool execution
                # If tool_index has increased since our last text, we need to signal a new turn
                is_post_tool_text = (
                    self._tool_index > self._last_tool_index_for_text
                    and self._text_buffer == ""  # Starting fresh text buffer
                )

                if is_post_tool_text:
                    # Generate a new turn ID for this post-tool text segment
                    new_turn_id = str(uuid.uuid4())
                    text_turn_idx = len(self.session.turns)

                    debug_log.info(
                        f"Post-tool text starting - new turn {new_turn_id[:8]}",
                        category=Category.RUNNER,
                        session_id=self.session.id,
                        details={
                            "tool_index": self._tool_index,
                            "last_tool_index_for_text": self._last_tool_index_for_text,
                            "turn_idx": text_turn_idx,
                        },
                    )

                    # Update tracking so subsequent text deltas know they're not starting a new turn
                    self._last_tool_index_for_text = self._tool_index

                    # Store the turn ID so _flush_text_as_turn can use it later
                    self._pending_text_turn_id = new_turn_id

                    # Emit text_turn_started so frontend creates new turn with correct ID
                    events.append(self._make_event("text_turn_started", {
                        "turn_index": text_turn_idx,
                        "turn_id": new_turn_id,
                        "exchange_id": self._exchange_id,
                        "role": "assistant",
                        "turn_type": "text",
                        "text_preview": "",  # Preview will be filled in when we have text
                        "post_tool": True,  # Flag to help debugging
                    }))

                # Track when text streaming started (first text delta)
                if not self._text_turn_started_at and self._text_buffer == "":
                    self._text_turn_started_at = datetime.now().isoformat()

                self._text_buffer += event.text
                events.append(self._make_event("text", event.text))
                return events

            elif isinstance(event, ToolUseStartEvent):
                # Tool use started - input is still streaming
                # Flush text buffer before tool (emit events so UI can show it)
                events = []
                flush_events = self._flush_text_as_turn(emit_event=True)
                events.extend(flush_events)

                self._current_tool_use_id = event.tool_use_id
                tool_idx = self._tool_index
                self._tool_index += 1

                # Track when this tool use started streaming
                self._tool_use_started_at[event.tool_use_id] = datetime.now().isoformat()

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
                debug_log.info(
                    f"_process_event: ToolUseEvent received",
                    category=Category.RUNNER,
                    details={
                        "tool_use_id": event.tool_use_id[:20] if event.tool_use_id else "",
                        "tool_name": event.tool_name,
                    },
                )
                tool_block = ToolUseBlock(
                    id=event.tool_use_id,
                    name=event.tool_name,
                    input=event.tool_input,
                )
                self._content_blocks.append(tool_block)  # Legacy

                # Get turn index for this tool_use turn
                tool_use_turn_idx = len(self.session.turns)

                # Get the start time we recorded when tool use began
                tool_started_at = self._tool_use_started_at.get(event.tool_use_id)

                # Create tool_use turn and save to session (don't save to disk yet - wait for result)
                turn = self._create_turn(
                    "assistant",
                    f"[Tool: {event.tool_name}]",
                    [tool_block],
                    started_at=tool_started_at,
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
                    "turn_id": turn.id,
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
                    "turn_id": turn.id,
                }))
                return events

            elif isinstance(event, ToolResultEvent):
                # Strip system reminders from tool results before storing
                clean_result = strip_system_reminders(event.result, self.session.id)

                result_block = ToolResultBlock(
                    tool_use_id=event.tool_use_id,
                    content=clean_result,
                    is_error=False,
                )
                self._content_blocks.append(result_block)  # Legacy

                # Get turn index for this tool_result turn
                tool_result_turn_idx = len(self.session.turns)

                # For tool results, started_at is when we started executing the tool
                # (which is right after tool_use completed - we track this via the tool_use turn's ended_at)
                # Since we create tool_use turn right before execution, we can look at its ended_at
                # For simplicity, use the current time as both start and end (tool execution is sync)
                tool_result_ended_at = datetime.now().isoformat()

                # Create tool_result turn and save to session immediately
                # This is the key checkpoint - tool has executed, we must persist
                # Note: For tool results, started_at approximates when tool execution began
                turn = self._create_turn(
                    "tool",
                    f"[Result: {len(clean_result)} chars]",
                    [result_block],
                    started_at=tool_result_ended_at,  # Tool execution is nearly instant
                    ended_at=tool_result_ended_at,
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

                events = []
                # Emit turn_started for this tool_result turn so UI creates a new node
                events.append(self._make_event("tool_result_turn_started", {
                    "turn_index": tool_result_turn_idx,
                    "turn_id": turn.id,
                    "exchange_id": self._exchange_id,
                    "role": "tool",
                    "turn_type": "tool_result",
                    "tool_use_id": event.tool_use_id,
                }))
                events.append(self._make_event("tool_result", {
                    "tool_use_id": event.tool_use_id,
                    "result": clean_result,
                    "tool_index": tool_idx,
                    "result_block": result_block,
                    "turn_index": tool_result_turn_idx,
                    "turn_id": turn.id,
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

            elif isinstance(event, ContextTokensEvent):
                # Context tokens counted via tiktoken before sending to Claude
                # Update session with accurate token count
                self.session.cached_context_tokens = event.context_tokens
                return [self._make_event("context_tokens", {
                    "context_tokens": event.context_tokens,
                })]

            return []

        except Exception as e:
            debug_log.warning(
                f"Failed to process event: {e}",
                session_id=self.session.id,
                category=Category.RUNNER,
            )
            return []  # Skip bad event

    async def _finalize_stream(self) -> list[StreamEvent]:
        """Finalize stream and create result.

        Returns:
            List of events to emit (final text turn events) before the done event.
        """
        # Flush remaining text as turn WITH events so client gets proper turn ordering
        # This is critical: without emit_event=True, the final text turn would have
        # the wrong order (the initial turn's index) causing tool_use/tool_result
        # turns to appear AFTER the final assistant text (Bug #10).
        final_turn_events = self._flush_text_as_turn(emit_event=True, save_now=True)

        # Check for stream errors (truncated response, JSON decode errors)
        error_block = self._check_stream_errors()
        if error_block:
            self._content_blocks.append(error_block)
            # Create error turn and save to session
            turn = self._create_turn("assistant", f"[Error: {error_block.reason}]", [error_block])
            self._turns.append(turn)
            self._save_turn_to_session(turn, save_now=True)

        # Flush any pending debounced saves now that streaming is complete
        await self._flush_pending_save()

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

        return final_turn_events

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
            category=Category.RUNNER,
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
            debug_log.error(f"Helper stream error: {e}", category=Category.RUNNER)
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
        # Put cancelled event directly - the async task may not complete to emit it
        self._event_queue.put_nowait(self._make_event("cancelled", None))
