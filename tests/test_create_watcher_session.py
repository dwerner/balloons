"""Tests for SessionManagerService.create_watcher_session.

Regression guard: the UI "Watch session" action calls createWatcherSession,
which had been removed from the service while the frontend still called it
(the call resolved to undefined at runtime). These tests pin the restored
behaviour: a new session is created, titled, seeded with a WatchStartBlock
plus watcher instructions, and registered against the target.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from core.stream_state import StreamState
from service.session_manager_service import SessionManagerService


class FakeTurn:
    """Minimal turn stand-in with identity semantics."""

    _counter = 0

    def __init__(self, content_block):
        FakeTurn._counter += 1
        self.id = f"turn-{FakeTurn._counter}"
        self.content_block = content_block


class FakeSession:
    """Session double with real turn bookkeeping (so index math is exercised)."""

    def __init__(self, session_id, working_directory="/tmp"):
        self.id = session_id
        self.title = None
        self.fork_name = None
        self.working_directory = working_directory
        self.turns = []
        self.saved = False

    def add_watch_start_turn(self, target_session_id, target_session_name):
        turn = FakeTurn({"type": "watch_start", "target": target_session_id})
        self.turns.append(turn)
        return turn

    def add_turn(self, role, content_block):
        turn = FakeTurn(content_block)
        self.turns.append(turn)
        return turn

    async def save(self):
        self.saved = True


def _make_service(target_session, watcher_session):
    manager = MagicMock()
    manager.get_session = MagicMock(
        side_effect=lambda sid: target_session if sid == target_session.id else None
    )
    manager.load_session = AsyncMock(
        side_effect=lambda sid: target_session if sid == target_session.id else None
    )
    manager.create_session = AsyncMock(return_value=watcher_session)

    service = SessionManagerService(manager, StreamState())
    # Isolate orchestration from event plumbing / storage side effects.
    service._register_watcher_internal = AsyncMock()
    service._emit_event = MagicMock()
    service._emit_session_added = MagicMock()
    return service, manager


def test_create_watcher_session_success():
    target = FakeSession("target-1", working_directory="/repo")
    target.title = "My Target"
    watcher = FakeSession("watcher-1")
    service, manager = _make_service(target, watcher)

    result = asyncio.run(service.create_watcher_session("target-1"))

    assert result.success is True
    assert result.watcher_session_id == "watcher-1"
    assert result.target_session_id == "target-1"
    assert result.target_session_name == "My Target"
    assert result.watcher_name == "Watcher for My Target"

    # New session created in the target's working directory.
    manager.create_session.assert_awaited_once_with(working_directory="/repo")

    # Title set, watcher instructions seeded, relationship registered, saved.
    assert watcher.title == "Watcher for My Target"
    assert watcher.saved is True
    assert len(watcher.turns) == 2  # watch_start + instructions
    assert watcher.turns[0].content_block["type"] == "watch_start"
    # Instructions turn is a real TextBlock built by the service.
    assert type(watcher.turns[1].content_block).__name__ == "TextBlock"
    assert watcher.turns[1].content_block.text
    service._register_watcher_internal.assert_awaited_once_with(
        "watcher-1", "target-1", "My Target"
    )


def test_create_watcher_session_missing_target():
    watcher = FakeSession("watcher-1")
    service, _ = _make_service(FakeSession("other"), watcher)

    result = asyncio.run(service.create_watcher_session("missing"))

    assert result.success is False
    assert "not found" in (result.error or "")
    service._register_watcher_internal.assert_not_awaited()