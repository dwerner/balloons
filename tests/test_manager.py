"""Tests for the session manager, particularly event polling."""

import pytest
from unittest.mock import Mock, patch, AsyncMock

from core.manager import SessionManager
from core.runner import SessionRunner, RunnerStatus, StreamEvent, StreamResult
from session import Session


class TestPollAll:
    """Tests for poll_all() behavior - the critical event polling."""

    @pytest.mark.asyncio
    @patch.object(Session, 'save', new_callable=AsyncMock)  # Don't write to disk
    async def test_poll_all_returns_events_from_streaming_runner(self, mock_save):
        """Events from actively streaming runners are returned."""
        manager = SessionManager()
        session = await manager.create_session()
        runner = manager.get_runner(session.id)

        # Simulate streaming state with queued events
        runner._status = RunnerStatus.STREAMING
        runner._event_queue.put_nowait(StreamEvent("text", "hello"))
        runner._event_queue.put_nowait(StreamEvent("text", " world"))

        results = manager.poll_all()

        assert len(results) == 1
        session_id, events = results[0]
        assert session_id == session.id
        assert len(events) == 2
        assert events[0].data == "hello"
        assert events[1].data == " world"

    @pytest.mark.asyncio
    @patch.object(Session, 'save', new_callable=AsyncMock)
    async def test_poll_all_returns_events_from_idle_runner_regression(self, mock_save):
        """REGRESSION TEST: Events from finished (IDLE) runners MUST be returned.

        This tests the bug where the "done" event was never polled because
        the runner had already transitioned to IDLE status before the poll.

        Sequence that caused the bug:
        1. Runner streaming, events flowing
        2. Stream ends, runner puts "done" in queue
        3. Runner sets _status = IDLE
        4. Poll timer fires, poll_all() called
        5. OLD BUG: poll_all checked `if runner.is_streaming` -> False, skipped!
        6. "done" event stuck in queue forever, UI frozen in streaming state
        """
        manager = SessionManager()
        session = await manager.create_session()
        runner = manager.get_runner(session.id)

        # Simulate the race condition that caused the bug:
        # Events in queue, but runner already finished (IDLE)
        runner._event_queue.put_nowait(StreamEvent("done", {"content": "response"}))
        runner._status = RunnerStatus.IDLE  # Already finished!

        results = manager.poll_all()

        # The "done" event MUST be returned even though runner is IDLE
        assert len(results) == 1, "Events from IDLE runner must be polled!"
        session_id, events = results[0]
        assert session_id == session.id
        assert len(events) == 1
        assert events[0].event_type == "done"

    @pytest.mark.asyncio
    @patch.object(Session, 'save', new_callable=AsyncMock)
    async def test_poll_all_returns_events_from_error_runner(self, mock_save):
        """Events from errored runners must still be returned."""
        manager = SessionManager()
        session = await manager.create_session()
        runner = manager.get_runner(session.id)

        # Simulate error with queued error event
        runner._event_queue.put_nowait(StreamEvent("error", "something failed"))
        runner._status = RunnerStatus.ERROR

        results = manager.poll_all()

        assert len(results) == 1
        _, events = results[0]
        assert events[0].event_type == "error"

    @pytest.mark.asyncio
    @patch.object(Session, 'save', new_callable=AsyncMock)
    async def test_poll_all_empty_when_no_events(self, mock_save):
        """No results when runners have no queued events."""
        manager = SessionManager()
        session = await manager.create_session()

        results = manager.poll_all()

        assert len(results) == 0

    @pytest.mark.asyncio
    @patch.object(Session, 'save', new_callable=AsyncMock)
    async def test_poll_all_multiple_sessions(self, mock_save):
        """Events from multiple sessions are all returned."""
        manager = SessionManager()
        session1 = await manager.create_session()
        session2 = await manager.create_session()

        runner1 = manager.get_runner(session1.id)
        runner2 = manager.get_runner(session2.id)

        runner1._event_queue.put_nowait(StreamEvent("text", "from session 1"))
        runner2._event_queue.put_nowait(StreamEvent("text", "from session 2"))

        results = manager.poll_all()

        assert len(results) == 2
        session_ids = {r[0] for r in results}
        assert session1.id in session_ids
        assert session2.id in session_ids


class TestStreamingLifecycle:
    """Tests for the full streaming lifecycle."""

    @pytest.mark.asyncio
    @patch.object(Session, 'save', new_callable=AsyncMock)
    async def test_events_drained_completely(self, mock_save):
        """After draining events, queue should be empty."""
        manager = SessionManager()
        session = await manager.create_session()
        runner = manager.get_runner(session.id)

        # Queue up a full sequence
        runner._event_queue.put_nowait(StreamEvent("text", "Hello"))
        runner._event_queue.put_nowait(StreamEvent("result", {"tokens": 100}))
        runner._event_queue.put_nowait(StreamEvent("done", {}))
        runner._status = RunnerStatus.IDLE

        # First poll gets all events
        results = manager.poll_all()
        assert len(results) == 1
        _, events = results[0]
        assert len(events) == 3
        assert events[2].event_type == "done"

        # Second poll should be empty
        results = manager.poll_all()
        assert len(results) == 0

    @pytest.mark.asyncio
    @patch.object(Session, 'save', new_callable=AsyncMock)
    async def test_runner_status_transitions(self, mock_save):
        """Runner status transitions correctly through lifecycle."""
        manager = SessionManager()
        session = await manager.create_session()
        runner = manager.get_runner(session.id)

        # Initial state
        assert runner.status == RunnerStatus.IDLE
        assert runner.is_done
        assert not runner.is_streaming

        # Simulate streaming start
        runner._status = RunnerStatus.STREAMING
        assert runner.is_streaming
        assert not runner.is_done

        # Simulate streaming end
        runner._status = RunnerStatus.IDLE
        assert not runner.is_streaming
        assert runner.is_done
