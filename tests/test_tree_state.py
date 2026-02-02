"""Tests for TreeState - the shared state layer for tree views."""

import pytest
import sys
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

# Direct import to avoid core/__init__.py which has heavy dependencies
project_root = Path(__file__).parent.parent

# Import tree_state directly
spec = importlib.util.spec_from_file_location("tree_state", project_root / "core" / "tree_state.py")
tree_state_module = importlib.util.module_from_spec(spec)
sys.modules["tree_state"] = tree_state_module
spec.loader.exec_module(tree_state_module)

TreeState = tree_state_module.TreeState
TreeEvent = tree_state_module.TreeEvent
TurnData = tree_state_module.TurnData
SessionData = tree_state_module.SessionData

# Import models directly
spec2 = importlib.util.spec_from_file_location("models", project_root / "models.py")
models_module = importlib.util.module_from_spec(spec2)
sys.modules["models"] = models_module
spec2.loader.exec_module(models_module)

ContextMode = models_module.ContextMode


@dataclass
class MockMessage:
    """Mock message for testing."""
    role: str
    content: str
    content_blocks: list = field(default_factory=list)
    context_mode: ContextMode = None
    exchange_id: str | None = None


@dataclass
class MockSession:
    """Mock session for testing."""
    id: str
    created: str = "2024-01-01T00:00:00"
    last_modified: str = "2024-01-01T00:00:00"
    model: str = "test-model"
    title: str = "Test Session"
    messages: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    parent_id: str | None = None
    children: list = field(default_factory=list)
    fork_name: str = ""
    fork_status: str = "active"
    merge_message: str = ""


class TestTreeStateObservers:
    """Test observer pattern functionality."""

    def test_add_observer(self):
        state = TreeState()
        events = []

        def callback(event, data):
            events.append((event, data))

        state.add_observer(callback)
        state.add_session(MockSession(id="s1"))

        assert len(events) == 1
        assert events[0][0] == TreeEvent.SESSION_ADDED
        assert events[0][1]["session_id"] == "s1"

    def test_remove_observer(self):
        state = TreeState()
        events = []

        def callback(event, data):
            events.append((event, data))

        state.add_observer(callback)
        state.add_session(MockSession(id="s1"))
        assert len(events) == 1

        state.remove_observer(callback)
        state.add_session(MockSession(id="s2"))
        assert len(events) == 1  # Still 1, callback was removed

    def test_multiple_observers(self):
        state = TreeState()
        events1, events2 = [], []

        def callback1(event, data):
            events1.append(event)

        def callback2(event, data):
            events2.append(event)

        state.add_observer(callback1)
        state.add_observer(callback2)
        state.add_session(MockSession(id="s1"))

        assert len(events1) == 1
        assert len(events2) == 1


class TestTreeStateSessionOperations:
    """Test session management."""

    def test_add_session(self):
        state = TreeState()
        session = MockSession(id="s1", title="Test")

        state.add_session(session)

        data = state.get_session("s1")
        assert data is not None
        assert data.id == "s1"
        assert data.title == "Test"

    def test_add_session_as_current(self):
        state = TreeState()
        session = MockSession(id="s1")

        state.add_session(session, is_current=True)

        assert state.get_current_session_id() == "s1"
        assert state.get_session("s1").is_current is True

    def test_update_existing_session(self):
        state = TreeState()
        events = []

        def callback(event, data):
            events.append(event)

        state.add_observer(callback)

        state.add_session(MockSession(id="s1", title="Original"))
        state.add_session(MockSession(id="s1", title="Updated"))

        assert state.get_session("s1").title == "Updated"
        assert events == [TreeEvent.SESSION_ADDED, TreeEvent.SESSION_UPDATED]

    def test_remove_session(self):
        state = TreeState()
        state.add_session(MockSession(id="s1"))
        state.add_session(MockSession(id="s2"))

        state.remove_session("s1")

        assert state.get_session("s1") is None
        assert state.get_session("s2") is not None

    def test_remove_current_session_clears_current(self):
        state = TreeState()
        state.add_session(MockSession(id="s1"), is_current=True)

        state.remove_session("s1")

        assert state.get_current_session_id() is None

    def test_set_current_session(self):
        state = TreeState()
        state.add_session(MockSession(id="s1"))
        state.add_session(MockSession(id="s2"))

        state.set_current_session("s1")
        assert state.get_current_session_id() == "s1"
        assert state.get_session("s1").is_current is True

        state.set_current_session("s2")
        assert state.get_current_session_id() == "s2"
        assert state.get_session("s1").is_current is False
        assert state.get_session("s2").is_current is True

    def test_session_colors_assigned(self):
        state = TreeState()
        state.add_session(MockSession(id="s1"))
        state.add_session(MockSession(id="s2"))

        c1 = state.get_session_color("s1")
        c2 = state.get_session_color("s2")

        assert c1 in state._color_palette
        assert c2 in state._color_palette
        # Different sessions should get different colors (until palette cycles)
        assert c1 != c2

    def test_add_session_from_metadata(self):
        state = TreeState()
        metadata = {
            "id": "s1",
            "created": "2024-01-01",
            "last_modified": "2024-01-02",
            "model": "claude-3",
            "title": "Metadata Session",
            "message_count": 5,
            "total_input_tokens": 100,
            "total_output_tokens": 200,
            "total_cost": 0.01,
            "parent_id": None,
            "children": [],
            "fork_name": "",
            "fork_status": "active",
        }

        state.add_session_from_metadata(metadata)

        data = state.get_session("s1")
        assert data.title == "Metadata Session"
        assert data.message_count == 5


class TestTreeStateSessionLoading:
    """Test lazy loading of session data."""

    def test_load_session(self):
        state = TreeState()
        session = MockSession(
            id="s1",
            messages=[
                MockMessage(role="user", content="Hello"),
                MockMessage(role="assistant", content="Hi there"),
            ]
        )

        state.load_session("s1", session)

        assert state.is_session_loaded("s1")
        data = state.get_session("s1")
        assert data.turns is not None
        assert len(data.turns) == 2
        assert data.turns[0].role == "user"
        assert data.turns[1].content == "Hi there"

    def test_load_session_respects_message_context_mode(self):
        state = TreeState()
        session = MockSession(
            id="s1",
            messages=[
                MockMessage(role="user", content="Hello", context_mode=ContextMode.COPY),
            ]
        )

        state.load_session("s1", session)

        mode = state.get_context_mode("s1", 0)
        assert mode == ContextMode.COPY

    def test_unloaded_session_returns_false(self):
        state = TreeState()
        state.add_session(MockSession(id="s1"))

        assert state.is_session_loaded("s1") is False


class TestTreeStateTurnOperations:
    """Test turn management during streaming."""

    def test_start_turn(self):
        state = TreeState()
        session = MockSession(id="s1", messages=[])
        state.load_session("s1", session)

        events = []
        state.add_observer(lambda e, d: events.append((e, d)))

        state.start_turn("s1", 0, "user")

        data = state.get_session("s1")
        assert len(data.turns) == 1
        assert data.turns[0].role == "user"
        assert data.turns[0].streaming is True
        assert data.message_count == 1

        assert len(events) == 1
        assert events[0][0] == TreeEvent.TURN_STARTED

    def test_update_turn_content(self):
        state = TreeState()
        session = MockSession(id="s1", messages=[])
        state.load_session("s1", session)
        state.start_turn("s1", 0, "assistant")

        state.update_turn_content("s1", 0, "Hello, world!")

        turn = state.get_turn("s1", 0)
        assert turn.content == "Hello, world!"

    def test_finish_turn(self):
        state = TreeState()
        session = MockSession(id="s1", messages=[])
        state.load_session("s1", session)
        state.start_turn("s1", 0, "assistant")

        events = []
        state.add_observer(lambda e, d: events.append((e, d)))

        state.finish_turn(
            "s1", 0,
            content="Final content",
            content_blocks=[{"type": "text", "text": "Final content"}],
            events=[{"type": "done"}],
        )

        turn = state.get_turn("s1", 0)
        assert turn.streaming is False
        assert turn.content == "Final content"
        assert len(turn.content_blocks) == 1

        assert any(e[0] == TreeEvent.TURN_FINISHED for e in events)


class TestTreeStateContextModes:
    """Test context mode management."""

    def test_default_context_mode_is_drop(self):
        state = TreeState()

        mode = state.get_context_mode("s1", 0)
        assert mode.value == "drop"

    def test_set_context_mode(self):
        state = TreeState()

        state.set_context_mode("s1", 0, ContextMode.COPY)

        assert state.get_context_mode("s1", 0).value == "copy"

    def test_toggle_context_mode_cycle(self):
        state = TreeState()
        state.set_context_mode("s1", 0, ContextMode.COPY)

        # COPY -> COMPRESS
        result = state.toggle_context_mode("s1", 0)
        assert result.value == "compress"

        # COMPRESS -> DROP
        result = state.toggle_context_mode("s1", 0)
        assert result.value == "drop"

        # DROP -> COPY
        result = state.toggle_context_mode("s1", 0)
        assert result.value == "copy"

    def test_context_mode_fires_event(self):
        state = TreeState()
        events = []
        state.add_observer(lambda e, d: events.append((e, d)))

        state.set_context_mode("s1", 0, ContextMode.COPY)

        assert len(events) == 1
        assert events[0][0] == TreeEvent.CONTEXT_MODE_CHANGED
        assert events[0][1]["mode"].value == "copy"

    def test_merge_modes(self):
        state = TreeState()

        # Default is COPY
        assert state.get_merge_mode("parent", "fork").value == "copy"

        state.set_merge_mode("parent", "fork", ContextMode.DROP)
        assert state.get_merge_mode("parent", "fork").value == "drop"


class TestTreeStateStreaming:
    """Test streaming state management."""

    def test_start_streaming(self):
        state = TreeState()
        state.add_session(MockSession(id="s1"))

        state.start_streaming("s1")

        assert state.is_streaming("s1") is True
        assert state.get_session("s1").is_streaming is True

    def test_stop_streaming(self):
        state = TreeState()
        state.add_session(MockSession(id="s1"))
        state.start_streaming("s1")

        state.stop_streaming("s1")

        assert state.is_streaming("s1") is False
        assert state.get_session("s1").is_streaming is False

    def test_streaming_fires_events(self):
        state = TreeState()
        state.add_session(MockSession(id="s1"))

        events = []
        state.add_observer(lambda e, d: events.append(e))

        state.start_streaming("s1")
        state.stop_streaming("s1")

        assert TreeEvent.STREAMING_STARTED in events
        assert TreeEvent.STREAMING_STOPPED in events


class TestTreeStateToolUse:
    """Test tool use tracking."""

    def test_add_tool_use(self):
        state = TreeState()
        session = MockSession(id="s1", messages=[])
        state.load_session("s1", session)
        state.start_turn("s1", 0, "assistant")

        events = []
        state.add_observer(lambda e, d: events.append((e, d)))

        state.add_tool_use("s1", 0, "tool_123", "Bash", {"command": "ls"})

        turn = state.get_turn("s1", 0)
        assert "tool_123" in turn.tool_use_ids

        assert any(e[0] == TreeEvent.TOOL_USE_STARTED for e in events)

    def test_tool_result(self):
        state = TreeState()
        events = []
        state.add_observer(lambda e, d: events.append((e, d)))

        state.add_tool_result("s1", 0, "tool_123", "file1\nfile2", is_error=False)

        assert any(e[0] == TreeEvent.TOOL_RESULT_ADDED for e in events)


class TestTreeStateClear:
    """Test bulk operations."""

    def test_clear(self):
        state = TreeState()
        state.add_session(MockSession(id="s1"), is_current=True)
        state.set_context_mode("s1", 0, ContextMode.COPY)
        state.start_streaming("s1")

        state.clear()

        assert state.get_session("s1") is None
        assert state.get_current_session_id() is None
        assert state.get_context_mode("s1", 0).value == "drop"
        assert state.is_streaming("s1") is False

    def test_request_rebuild_fires_event(self):
        state = TreeState()
        events = []
        state.add_observer(lambda e, d: events.append(e))

        state.request_rebuild()

        assert TreeEvent.FULL_REBUILD in events


class TestTreeStateExchangeGrouping:
    """Test grouping turns by exchange_id."""

    def test_empty_session_returns_empty_list(self):
        state = TreeState()
        session = MockSession(id="s1", messages=[])
        state.load_session("s1", session)

        groups = state.get_turns_grouped_by_exchange("s1")

        assert groups == []

    def test_nonexistent_session_returns_empty_list(self):
        state = TreeState()

        groups = state.get_turns_grouped_by_exchange("nonexistent")

        assert groups == []

    def test_turns_without_exchange_id_each_in_own_group(self):
        state = TreeState()
        session = MockSession(
            id="s1",
            messages=[
                MockMessage(role="user", content="Hello"),
                MockMessage(role="assistant", content="Hi"),
                MockMessage(role="user", content="Bye"),
            ]
        )
        state.load_session("s1", session)

        groups = state.get_turns_grouped_by_exchange("s1")

        assert len(groups) == 3
        assert len(groups[0]) == 1
        assert len(groups[1]) == 1
        assert len(groups[2]) == 1
        assert groups[0][0].content == "Hello"
        assert groups[1][0].content == "Hi"
        assert groups[2][0].content == "Bye"

    def test_turns_with_same_exchange_id_grouped_together(self):
        state = TreeState()
        session = MockSession(
            id="s1",
            messages=[
                MockMessage(role="user", content="Do something", exchange_id="ex1"),
                MockMessage(role="assistant", content="Thinking...", exchange_id="ex1"),
                MockMessage(role="assistant", content="Done!", exchange_id="ex1"),
            ]
        )
        state.load_session("s1", session)

        groups = state.get_turns_grouped_by_exchange("s1")

        assert len(groups) == 1
        assert len(groups[0]) == 3
        assert groups[0][0].content == "Do something"
        assert groups[0][1].content == "Thinking..."
        assert groups[0][2].content == "Done!"

    def test_mixed_exchange_ids(self):
        """Multiple exchanges interleaved - each grouped separately."""
        state = TreeState()
        session = MockSession(
            id="s1",
            messages=[
                MockMessage(role="user", content="Q1", exchange_id="ex1"),
                MockMessage(role="assistant", content="A1", exchange_id="ex1"),
                MockMessage(role="user", content="Q2", exchange_id="ex2"),
                MockMessage(role="assistant", content="Tool call", exchange_id="ex2"),
                MockMessage(role="assistant", content="Tool result", exchange_id="ex2"),
                MockMessage(role="assistant", content="A2", exchange_id="ex2"),
            ]
        )
        state.load_session("s1", session)

        groups = state.get_turns_grouped_by_exchange("s1")

        assert len(groups) == 2
        # First exchange: Q1, A1
        assert len(groups[0]) == 2
        assert [t.content for t in groups[0]] == ["Q1", "A1"]
        # Second exchange: Q2, Tool call, Tool result, A2
        assert len(groups[1]) == 4
        assert [t.content for t in groups[1]] == ["Q2", "Tool call", "Tool result", "A2"]

    def test_turns_without_exchange_id_between_exchanges(self):
        """Turns without exchange_id are isolated from grouped turns."""
        state = TreeState()
        session = MockSession(
            id="s1",
            messages=[
                MockMessage(role="user", content="Q1", exchange_id="ex1"),
                MockMessage(role="assistant", content="A1", exchange_id="ex1"),
                MockMessage(role="system", content="System note"),  # No exchange_id
                MockMessage(role="user", content="Q2", exchange_id="ex2"),
                MockMessage(role="assistant", content="A2", exchange_id="ex2"),
            ]
        )
        state.load_session("s1", session)

        groups = state.get_turns_grouped_by_exchange("s1")

        assert len(groups) == 3
        # First exchange
        assert len(groups[0]) == 2
        assert [t.content for t in groups[0]] == ["Q1", "A1"]
        # Isolated turn
        assert len(groups[1]) == 1
        assert groups[1][0].content == "System note"
        # Second exchange
        assert len(groups[2]) == 2
        assert [t.content for t in groups[2]] == ["Q2", "A2"]

    def test_groups_preserve_turn_order(self):
        """Within a group, turns stay in original index order."""
        state = TreeState()
        session = MockSession(
            id="s1",
            messages=[
                MockMessage(role="user", content="First", exchange_id="ex1"),
                MockMessage(role="assistant", content="Second", exchange_id="ex1"),
                MockMessage(role="assistant", content="Third", exchange_id="ex1"),
            ]
        )
        state.load_session("s1", session)

        groups = state.get_turns_grouped_by_exchange("s1")

        assert len(groups) == 1
        indices = [t.idx for t in groups[0]]
        assert indices == [0, 1, 2]

    def test_exchange_id_preserved_on_turns(self):
        """Exchange IDs are preserved on TurnData."""
        state = TreeState()
        session = MockSession(
            id="s1",
            messages=[
                MockMessage(role="user", content="Q", exchange_id="ex123"),
                MockMessage(role="assistant", content="A", exchange_id="ex123"),
            ]
        )
        state.load_session("s1", session)

        groups = state.get_turns_grouped_by_exchange("s1")

        assert all(t.exchange_id == "ex123" for t in groups[0])
