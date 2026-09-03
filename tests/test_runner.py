"""Tests for SessionRunner."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.runner import SessionRunner, RunnerStatus, StreamEvent, StreamResult
from session import Session
from models import Message, TextDelta, ThinkingDelta, InitEvent, ResultEvent, ToolUseStartEvent, ToolUseEvent, ToolResultEvent, RawEvent


@pytest.fixture
def temp_sessions_dir(tmp_path):
    """Use a temporary directory for sessions to avoid polluting real sessions."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    with patch("session.SESSIONS_DIR", sessions_dir), \
         patch("session.INDEX_FILE", sessions_dir / "index.json"):
        yield sessions_dir


@pytest.fixture
def session(temp_sessions_dir):
    """Create a test session."""
    s = Session()
    s.set_working_directory("/test")
    return s


@pytest.fixture
def runner(session):
    """Create a test runner with mocked session save to avoid storage dependency."""
    with patch.object(session, 'save', MagicMock()):
        yield SessionRunner(session)


class TestRunnerStatus:
    """Tests for runner status tracking."""

    def test_initial_status_is_idle(self, runner):
        """Runner starts in IDLE status."""
        assert runner.status == RunnerStatus.IDLE

    def test_is_streaming_false_when_idle(self, runner):
        """is_streaming is False when idle."""
        assert runner.is_streaming is False

    def test_is_done_true_when_idle(self, runner):
        """is_done is True when idle."""
        assert runner.is_done is True


class TestStreamProcessing:
    """Tests for event processing during streaming."""

    def test_process_text_delta(self, runner):
        """TextDelta events accumulate text."""
        event = TextDelta(text="hello")
        results = runner._process_event(event)

        assert len(results) == 1
        assert results[0].event_type == "text"
        assert results[0].data == "hello"
        assert runner._text_buffer == "hello"

    def test_process_init_event(self, runner, session):
        """InitEvent updates session model info."""
        event = InitEvent(model="claude-3", session_id="test", context_window=100000)
        results = runner._process_event(event)

        assert len(results) == 1
        assert results[0].event_type == "init"
        assert results[0].data["model"] == "claude-3"
        assert session.model == "claude-3"

    def test_process_tool_use_event(self, runner):
        """ToolUseEvent creates content block."""
        # First add some text
        runner._process_event(TextDelta(text="some text"))

        # Then tool use start (flushes text and emits text_turn_started + text_flush + tool_use_start events)
        start_results = runner._process_event(ToolUseStartEvent(
            tool_use_id="123",
            tool_name="Read",
        ))
        # Should have text_turn_started + text_flush + tool_use_start
        assert len(start_results) == 3
        assert start_results[0].event_type == "text_turn_started"
        assert start_results[1].event_type == "text_flush"
        assert start_results[2].event_type == "tool_use_start"

        # Then tool use complete
        event = ToolUseEvent(
            tool_use_id="123",
            tool_name="Read",
            tool_input={"file_path": "/test.py"},
        )
        results = runner._process_event(event)

        # Should have tool_use_turn_started + tool_use
        assert len(results) == 2
        assert results[0].event_type == "tool_use_turn_started"
        assert results[1].event_type == "tool_use"
        assert results[1].data["tool_name"] == "Read"
        # Text should be flushed to content block by ToolUseStartEvent
        assert len(runner._content_blocks) == 2  # TextBlock + ToolUseBlock

    async def test_process_tool_result_event(self, runner):
        """ToolResultEvent creates content block."""
        event = ToolResultEvent(tool_use_id="123", result="file contents")
        results = runner._process_event(event)

        # Should have tool_result_turn_started + tool_result
        assert len(results) == 2
        assert results[0].event_type == "tool_result_turn_started"
        assert results[1].event_type == "tool_result"
        assert results[1].data["result"] == "file contents"

    def test_process_result_event(self, runner, session):
        """ResultEvent updates session usage."""
        event = ResultEvent(
            input_tokens=100,
            output_tokens=50,
            total_cost_usd=0.01,
            context_window=200000,
        )
        results = runner._process_event(event)

        assert len(results) == 1
        assert results[0].event_type == "result"
        assert session.total_input_tokens == 100
        assert session.total_output_tokens == 50
        assert results[0].data["session_total_tokens"] == 150

    def test_process_raw_event(self, runner):
        """RawEvent is passed through."""
        event = RawEvent(data={"type": "test"})
        results = runner._process_event(event)

        assert len(results) == 1
        assert results[0].event_type == "raw"
        assert results[0].data == {"type": "test"}

    def test_tool_use_start_without_text_no_flush(self, runner):
        """ToolUseStartEvent without prior text only emits tool_use_start."""
        results = runner._process_event(ToolUseStartEvent(
            tool_use_id="123",
            tool_name="Read",
        ))
        # No text to flush, so only tool_use_start
        assert len(results) == 1
        assert results[0].event_type == "tool_use_start"


class TestReasoningTurns:
    """Reasoning deltas must stream as their own turn, separate from answer text."""

    def test_thinking_delta_does_not_raise(self, runner):
        """Regression: the ThinkingDelta branch used an uninitialized `events` list,
        which raised NameError on the first reasoning delta once runners emitted
        ThinkingDelta instead of folding reasoning into TextDelta."""
        results = runner._process_event(ThinkingDelta(text="hmm"))
        assert any(r.event_type == "thinking" for r in results)

    def test_reasoning_then_answer_splits_into_two_turns(self, runner):
        """Reasoning is flushed as its own turn before answer text accumulates."""
        runner._process_event(ThinkingDelta(text="let me think"))
        runner._process_event(ThinkingDelta(text=" about it"))
        results = runner._process_event(TextDelta(text="the answer"))

        # Reasoning persisted as its own ThinkingBlock turn
        assert len(runner._content_blocks) == 1
        assert runner._content_blocks[0].type == "thinking"
        assert runner._content_blocks[0].text == "let me think about it"

        # Reasoning turn finalized with its block kind...
        assert any(
            r.event_type == "text_flush" and r.data.get("block_kind") == "thinking"
            for r in results
        )
        # ...and the answer announced as a separate turn.
        assert any(
            r.event_type == "text_turn_started" and r.data.get("turn_type") == "text"
            for r in results
        )

    def test_answer_then_reasoning_splits_into_two_turns(self, runner):
        """Answer text is flushed as its own turn before reasoning accumulates."""
        runner._process_event(TextDelta(text="answer first"))
        results = runner._process_event(ThinkingDelta(text="now reasoning"))

        assert len(runner._content_blocks) == 1
        assert runner._content_blocks[0].type == "text"
        assert any(
            r.event_type == "text_flush" and r.data.get("block_kind") == "text"
            for r in results
        )
        assert any(
            r.event_type == "text_turn_started" and r.data.get("turn_type") == "thinking"
            for r in results
        )

    async def test_trailing_reasoning_persists_as_thinking_block(self, runner):
        """Final flush honors the buffer kind instead of hardcoding TextBlock."""
        runner._process_event(ThinkingDelta(text="reasoning at end"))
        await runner._finalize_stream()

        assert len(runner._content_blocks) == 1
        assert runner._content_blocks[0].type == "thinking"


class TestFinalization:
    """Tests for stream finalization."""

    @pytest.mark.asyncio
    async def test_finalize_creates_result(self, runner):
        """Finalization creates StreamResult."""
        runner._text_buffer = "test content"
        runner._raw_events = [{"type": "test"}]

        await runner._finalize_stream()

        assert runner._result is not None
        assert runner._result.raw_events == [{"type": "test"}]
        assert runner.status == RunnerStatus.IDLE

    @pytest.mark.asyncio
    async def test_finalize_flushes_text_buffer(self, runner):
        """Finalization flushes remaining text to content blocks."""
        runner._text_buffer = "remaining text"

        await runner._finalize_stream()

        assert len(runner._content_blocks) == 1
        assert runner._content_blocks[0].text == "remaining text"


class TestCancel:
    """Tests for cancellation."""

    def test_cancel_terminates_runner(self, runner):
        """Cancel terminates the underlying runner."""
        with patch.object(runner._runner, 'terminate') as mock_terminate:
            runner.cancel()
            mock_terminate.assert_called_once()

    def test_cancel_sets_status(self, runner):
        """Cancel sets status to CANCELLED."""
        with patch.object(runner._runner, 'terminate'):
            runner.cancel()
            assert runner.status == RunnerStatus.CANCELLED


class TestEventQueue:
    """Tests for event queue operations."""

    def test_drain_events_returns_queued(self, runner):
        """drain_events returns all queued events."""
        # Manually add events to queue
        runner._event_queue.put_nowait(StreamEvent("text", "a"))
        runner._event_queue.put_nowait(StreamEvent("text", "b"))

        events = runner.drain_events()

        assert len(events) == 2
        assert events[0].data == "a"
        assert events[1].data == "b"

    def test_drain_events_empties_queue(self, runner):
        """drain_events empties the queue."""
        runner._event_queue.put_nowait(StreamEvent("text", "a"))

        runner.drain_events()
        events = runner.drain_events()

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_wait_for_event_returns_next(self, runner):
        """wait_for_event returns the next event."""
        runner._event_queue.put_nowait(StreamEvent("text", "test"))

        event = await runner.wait_for_event(timeout=1.0)

        assert event is not None
        assert event.data == "test"

    @pytest.mark.asyncio
    async def test_wait_for_event_timeout(self, runner):
        """wait_for_event returns None on timeout."""
        event = await runner.wait_for_event(timeout=0.01)
        assert event is None


class TestGetResult:
    """Tests for result retrieval."""

    def test_get_result_returns_none_when_streaming(self, runner):
        """get_result returns None while streaming."""
        runner._status = RunnerStatus.STREAMING
        assert runner.get_result() is None

    def test_get_result_returns_result_when_done(self, runner):
        """get_result returns result when done."""
        runner._status = RunnerStatus.IDLE
        runner._result = StreamResult(
            content="test",
            content_blocks=[],
            raw_events=[],
        )

        result = runner.get_result()

        assert result is not None
        assert result.content == "test"
