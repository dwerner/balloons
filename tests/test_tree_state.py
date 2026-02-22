"""Tests for TreeState - the shared state layer for tree views."""

import pytest
from dataclasses import dataclass, field

# Standard imports - let Python's import system handle everything normally.
# The previous approach of manually loading modules via importlib.util polluted
# sys.modules and caused class identity issues (isinstance would fail because
# the same class loaded twice has different identity).
from core.tree_state import TreeState, TreeEvent, TurnData, SessionData
from models import ContextMode, TextBlock


@dataclass
class MockMessage:
    """Mock message for testing."""
    role: str
    content: str
    content_blocks: list = field(default_factory=list)
    content_block: object = None  # Single content block (new Turn model)
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
    turns: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    parent_id: str | None = None
    children: list = field(default_factory=list)
    fork_name: str = ""
    fork_status: str = "active"
    merge_message: str = ""
    backend_name: str = ""


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
            turns=[
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
            turns=[
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

    def test_load_session_calculates_cached_context_tokens(self):
        """Loading a session should calculate cached_context_tokens from turn tokens.

        Note: Only non-DROPped turns are counted. For the current session,
        turns default to COMPRESS, so they're all counted.
        """
        state = TreeState()
        session = MockSession(
            id="s1",
            turns=[
                MockMessage(
                    role="user",
                    content="Hello world",
                    content_block=TextBlock(text="Hello world"),
                ),
                MockMessage(
                    role="assistant",
                    content="Hi there, how can I help?",
                    content_block=TextBlock(text="Hi there, how can I help?"),
                ),
            ]
        )

        # Must set as current session so turns default to COMPRESS (not DROP)
        state.add_session(session, is_current=True)
        state.load_session("s1", session)

        data = state.get_session("s1")
        # Token counts should be calculated from content blocks
        assert data.turns[0].tokens > 0, "User turn should have tokens"
        assert data.turns[1].tokens > 0, "Assistant turn should have tokens"
        # Session cached_context_tokens should be sum of turn tokens
        expected_total = sum(t.tokens for t in data.turns)
        assert data.cached_context_tokens == expected_total
        assert data.cached_context_tokens > 0


class TestTreeStateTurnOperations:
    """Test turn management during streaming."""

    def test_start_turn(self):
        state = TreeState()
        session = MockSession(id="s1", turns=[])
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
        session = MockSession(id="s1", turns=[])
        state.load_session("s1", session)
        state.start_turn("s1", 0, "assistant")

        state.update_turn_content("s1", 0, "Hello, world!")

        turn = state.get_turn("s1", 0)
        assert turn.content == "Hello, world!"

    @pytest.mark.asyncio
    async def test_finish_turn(self):
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.load_session("s1", session)
        state.start_turn("s1", 0, "assistant")

        events = []
        state.add_observer(lambda e, d: events.append((e, d)))

        await state.finish_turn(
            "s1", 0,
            content="Final content",
            content_block=TextBlock(text="Final content"),
            events=[{"type": "done"}],
        )

        turn = state.get_turn("s1", 0)
        assert turn.streaming is False
        assert turn.content == "Final content"
        assert isinstance(turn.content_block, TextBlock)

        assert any(e[0] == TreeEvent.TURN_FINISHED for e in events)

    @pytest.mark.asyncio
    async def test_finish_turn_updates_cached_tokens_incrementally(self):
        """finish_turn should add to cached_context_tokens, not recalculate entire sum."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session, is_current=True)
        state.load_session("s1", session)

        data = state.get_session("s1")
        assert data.cached_context_tokens == 0  # Empty session

        # Start and finish first turn
        state.start_turn("s1", 0, "user")
        await state.finish_turn("s1", 0, "Hello", TextBlock(text="Hello"), [])

        turn0_tokens = data.turns[0].tokens
        assert turn0_tokens > 0
        assert data.cached_context_tokens == turn0_tokens

        # Start and finish second turn
        state.start_turn("s1", 1, "assistant")
        await state.finish_turn("s1", 1, "Hi there!", TextBlock(text="Hi there!"), [])

        turn1_tokens = data.turns[1].tokens
        assert turn1_tokens > 0
        # Should be sum of both turns (incremental add, not recalc)
        assert data.cached_context_tokens == turn0_tokens + turn1_tokens

    def test_start_turn_updates_existing_turn_instead_of_duplicating(self):
        """When start_turn is called with same index twice, update instead of duplicate.

        This handles the scenario where an empty assistant turn is pre-created,
        then a tool_use_turn_started event arrives with the same index.
        """
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.load_session("s1", session)

        # Create initial empty assistant turn (like _start_streaming does)
        state.start_turn("s1", 0, "assistant")

        data = state.get_session("s1")
        assert len(data.turns) == 1
        assert data.turns[0].role == "assistant"
        assert data.turns[0].content == ""
        assert data.message_count == 1

        # Now start_turn is called again with same index but different content
        # (like when tool_use_turn_started event arrives)
        state.start_turn(
            "s1", 0, "assistant",
            turn_type="tool_use",
            tool_name="Bash",
            tool_use_id="tool-123",
        )

        # Should update existing turn, not create duplicate
        data = state.get_session("s1")
        assert len(data.turns) == 1
        assert data.turns[0].role == "assistant"
        assert data.turns[0].content == "Bash"  # Updated from tool_name
        assert data.message_count == 1  # Still 1, not incremented


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

    def test_set_context_mode_updates_cached_tokens_incrementally(self):
        """Setting context mode to/from DROP should update cached_context_tokens."""
        state = TreeState()
        session = MockSession(
            id="s1",
            turns=[
                MockMessage(role="user", content="Hello", content_block=TextBlock(text="Hello")),
                MockMessage(role="assistant", content="Hi there", content_block=TextBlock(text="Hi there")),
            ],
        )
        state.add_session(session, is_current=True)
        state.load_session("s1", session)

        data = state.get_session("s1")
        initial_tokens = data.cached_context_tokens
        assert initial_tokens > 0, "Should have tokens from loaded turns"

        # Get the first turn's tokens
        turn0_tokens = data.turns[0].tokens
        assert turn0_tokens > 0

        # DROP the first turn - tokens should decrease
        state.set_context_mode("s1", 0, ContextMode.DROP)
        assert data.cached_context_tokens == initial_tokens - turn0_tokens

        # Un-DROP it (set to COPY) - tokens should increase back
        state.set_context_mode("s1", 0, ContextMode.COPY)
        assert data.cached_context_tokens == initial_tokens

        # COPY -> COMPRESS should NOT change tokens (both are counted)
        state.set_context_mode("s1", 0, ContextMode.COMPRESS)
        assert data.cached_context_tokens == initial_tokens

    def test_merge_modes(self):
        state = TreeState()

        # Default is COPY
        assert state.get_merge_mode("parent", "fork").value == "copy"

        state.set_merge_mode("parent", "fork", ContextMode.DROP)
        assert state.get_merge_mode("parent", "fork").value == "drop"

    def test_merge_modes_loaded_from_session_children(self):
        """Merge modes should be loaded from session children when session loads."""
        state = TreeState()

        # Create session with children that have persisted context_mode
        session = MockSession(
            id="parent",
            children=[
                {"session_id": "fork1", "status": "merged", "context_mode": "drop"},
                {"session_id": "fork2", "status": "merged", "context_mode": "compress"},
                {"session_id": "fork3", "status": "merged"},  # No context_mode, should default to COPY
                {"session_id": "fork4", "status": "active"},  # Not merged, should not load
            ]
        )

        state.load_session("parent", session)

        # Check merge modes loaded correctly
        assert state.get_merge_mode("parent", "fork1").value == "drop"
        assert state.get_merge_mode("parent", "fork2").value == "compress"
        assert state.get_merge_mode("parent", "fork3").value == "copy"  # Default
        assert state.get_merge_mode("parent", "fork4").value == "copy"  # Not loaded (not merged), default

    def test_set_merge_mode_updates_session_children(self):
        """Setting merge mode should update the session's children for persistence."""
        state = TreeState()

        # Create session with a merged child
        session = MockSession(
            id="parent",
            children=[
                {"session_id": "fork1", "status": "merged"},
            ]
        )

        state.load_session("parent", session)

        # Set merge mode
        state.set_merge_mode("parent", "fork1", ContextMode.COMPRESS)

        # Check that both in-memory and session object are updated
        assert state.get_merge_mode("parent", "fork1").value == "compress"
        assert session.children[0].get("context_mode") == "compress"


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
        session = MockSession(id="s1", turns=[])
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
        # Streaming is preserved by default (for load_all_sessions)
        assert state.is_streaming("s1") is True

    def test_clear_without_preserving_streaming(self):
        """Test that clear(preserve_streaming=False) clears streaming state."""
        state = TreeState()
        state.add_session(MockSession(id="s1"), is_current=True)
        state.start_streaming("s1")

        state.clear(preserve_streaming=False)

        assert state.get_session("s1") is None
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
        session = MockSession(id="s1", turns=[])
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
            turns=[
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
            turns=[
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
            turns=[
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
            turns=[
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
            turns=[
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
            turns=[
                MockMessage(role="user", content="Q", exchange_id="ex123"),
                MockMessage(role="assistant", content="A", exchange_id="ex123"),
            ]
        )
        state.load_session("s1", session)

        groups = state.get_turns_grouped_by_exchange("s1")

        assert all(t.exchange_id == "ex123" for t in groups[0])


class TestTreeStateViewedTracking:
    """Test tracking of viewed/unviewed turns."""

    def test_start_turn_user_is_viewed(self):
        """User turns start as viewed."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session)
        state.load_session("s1", session)

        state.start_turn("s1", 0, "user")

        turn = state.get_turn("s1", 0)
        assert turn.viewed is True

    def test_start_turn_assistant_is_unviewed(self):
        """Assistant turns start as unviewed."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session)
        state.load_session("s1", session)

        state.start_turn("s1", 0, "assistant")

        turn = state.get_turn("s1", 0)
        assert turn.viewed is False

    def test_mark_turn_viewed(self):
        """Can mark an unviewed turn as viewed."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session)
        state.load_session("s1", session)
        state.start_turn("s1", 0, "assistant")

        result = state.mark_turn_viewed("s1", 0)

        assert result is True
        turn = state.get_turn("s1", 0)
        assert turn.viewed is True

    def test_mark_turn_viewed_already_viewed_returns_false(self):
        """Marking an already-viewed turn returns False."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session)
        state.load_session("s1", session)
        state.start_turn("s1", 0, "user")  # User turns start viewed

        result = state.mark_turn_viewed("s1", 0)

        assert result is False

    def test_mark_turn_viewed_fires_event(self):
        """Marking a turn as viewed fires TURN_VIEWED event."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session)
        state.load_session("s1", session)
        state.start_turn("s1", 0, "assistant")

        events = []
        state.add_observer(lambda e, d: events.append((e, d)))

        state.mark_turn_viewed("s1", 0)

        turn_viewed_events = [e for e, d in events if e == TreeEvent.TURN_VIEWED]
        assert len(turn_viewed_events) == 1

    def test_get_unviewed_turns(self):
        """get_unviewed_turns returns indices of unviewed turns."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session)
        state.load_session("s1", session)
        state.start_turn("s1", 0, "user")
        state.start_turn("s1", 1, "assistant")  # unviewed
        state.start_turn("s1", 2, "assistant")  # unviewed

        unviewed = state.get_unviewed_turns("s1")

        assert unviewed == [1, 2]

    def test_has_unviewed_turns(self):
        """has_unviewed_turns returns True when there are unviewed turns."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session)
        state.load_session("s1", session)
        state.start_turn("s1", 0, "user")

        assert state.has_unviewed_turns("s1") is False

        state.start_turn("s1", 1, "assistant")

        assert state.has_unviewed_turns("s1") is True

    def test_get_unviewed_count(self):
        """get_unviewed_count returns count of unviewed turns."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session)
        state.load_session("s1", session)
        state.start_turn("s1", 0, "user")
        state.start_turn("s1", 1, "assistant")
        state.start_turn("s1", 2, "assistant")

        assert state.get_unviewed_count("s1") == 2

        state.mark_turn_viewed("s1", 1)

        assert state.get_unviewed_count("s1") == 1

    def test_mark_turns_viewed_batch(self):
        """mark_turns_viewed can mark multiple turns at once."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session)
        state.load_session("s1", session)
        state.start_turn("s1", 0, "assistant")
        state.start_turn("s1", 1, "assistant")
        state.start_turn("s1", 2, "user")  # Already viewed

        count = state.mark_turns_viewed("s1", [0, 1, 2])

        assert count == 2  # Only 2 were actually marked (user was already viewed)
        assert state.get_unviewed_count("s1") == 0


class TestTreeStateSessionHistory:
    """Test session history tracking."""

    def test_set_current_session_adds_to_history(self):
        """Setting current session adds it to history."""
        state = TreeState()
        state.add_session(MockSession(id="s1"))
        state.add_session(MockSession(id="s2"))

        state.set_current_session("s1")
        state.set_current_session("s2")

        history = state.get_session_history()
        assert history == ["s2", "s1"]  # Most recent first

    def test_history_moves_existing_to_front(self):
        """Revisiting a session moves it to front of history."""
        state = TreeState()
        state.add_session(MockSession(id="s1"))
        state.add_session(MockSession(id="s2"))
        state.add_session(MockSession(id="s3"))

        state.set_current_session("s1")
        state.set_current_session("s2")
        state.set_current_session("s3")
        state.set_current_session("s1")  # Revisit s1

        history = state.get_session_history()
        assert history == ["s1", "s3", "s2"]

    def test_history_limit_parameter(self):
        """get_session_history respects limit parameter."""
        state = TreeState()
        for i in range(5):
            state.add_session(MockSession(id=f"s{i}"))
            state.set_current_session(f"s{i}")

        history = state.get_session_history(limit=3)
        assert len(history) == 3
        assert history == ["s4", "s3", "s2"]

    def test_history_excludes_removed_sessions(self):
        """History excludes sessions that have been removed."""
        state = TreeState()
        state.add_session(MockSession(id="s1"))
        state.add_session(MockSession(id="s2"))

        state.set_current_session("s1")
        state.set_current_session("s2")
        state.remove_session("s1")

        history = state.get_session_history()
        assert history == ["s2"]  # s1 excluded because it no longer exists

    def test_clear_preserves_history_by_default(self):
        """clear() preserves history by default."""
        state = TreeState()
        state.add_session(MockSession(id="s1"))
        state.set_current_session("s1")

        state.clear()

        # History preserved but will be empty after filtering by existing sessions
        # Re-add the session to verify history was preserved
        state.add_session(MockSession(id="s1"))
        history = state.get_session_history()
        assert history == ["s1"]

    def test_clear_can_clear_history(self):
        """clear(preserve_history=False) clears history."""
        state = TreeState()
        state.add_session(MockSession(id="s1"))
        state.set_current_session("s1")

        state.clear(preserve_history=False)
        state.add_session(MockSession(id="s1"))

        history = state.get_session_history()
        assert history == []  # History was cleared

    def test_history_respects_max_limit(self):
        """History doesn't grow beyond max limit."""
        state = TreeState()
        state._session_history_max = 5  # Set small limit for testing

        for i in range(10):
            state.add_session(MockSession(id=f"s{i}"))
            state.set_current_session(f"s{i}")

        # Internal history should be limited
        assert len(state._session_history) == 5
        # Most recent 5 sessions
        assert state._session_history == ["s9", "s8", "s7", "s6", "s5"]

    def test_get_raw_session_history(self):
        """get_raw_session_history returns full internal list."""
        state = TreeState()
        state.add_session(MockSession(id="s1"))
        state.add_session(MockSession(id="s2"))
        state.set_current_session("s1")
        state.set_current_session("s2")

        # Remove s1 from sessions (simulating deleted session)
        state.remove_session("s1")

        # get_session_history filters out removed sessions
        assert state.get_session_history() == ["s2"]

        # get_raw_session_history returns the internal list (for persistence)
        raw = state.get_raw_session_history()
        assert "s2" in raw
        # s1 may or may not be in raw depending on when remove_session cleans it

    def test_set_session_history(self):
        """set_session_history restores history from storage."""
        state = TreeState()

        # Set history before any sessions are added
        state.set_session_history(["s3", "s1", "s2"])

        assert state._session_history == ["s3", "s1", "s2"]

    def test_set_session_history_trims_to_max(self):
        """set_session_history trims to max limit."""
        state = TreeState()
        state._session_history_max = 3

        # Try to set more than max
        state.set_session_history(["s1", "s2", "s3", "s4", "s5"])

        # Should be trimmed to max
        assert state._session_history == ["s1", "s2", "s3"]

    def test_session_history_changed_event(self):
        """SESSION_HISTORY_CHANGED event fires when history changes."""
        state = TreeState()
        events = []

        def callback(event, data):
            events.append((event, data))

        state.add_observer(callback)
        state.add_session(MockSession(id="s1"))
        state.add_session(MockSession(id="s2"))

        # First session switch - should fire event
        state.set_current_session("s1")
        history_events = [e for e in events if e[0] == TreeEvent.SESSION_HISTORY_CHANGED]
        assert len(history_events) == 1
        assert history_events[0][1]["session_history"] == ["s1"]

        events.clear()

        # Switch to s2 - should fire event
        state.set_current_session("s2")
        history_events = [e for e in events if e[0] == TreeEvent.SESSION_HISTORY_CHANGED]
        assert len(history_events) == 1
        assert history_events[0][1]["session_history"] == ["s2", "s1"]

    def test_session_history_no_event_if_unchanged(self):
        """SESSION_HISTORY_CHANGED event doesn't fire if already at front."""
        state = TreeState()
        events = []

        def callback(event, data):
            events.append((event, data))

        state.add_observer(callback)
        state.add_session(MockSession(id="s1"))
        state.set_current_session("s1")

        events.clear()

        # Set current to same session - should NOT fire history event
        state.set_current_session("s1")
        history_events = [e for e in events if e[0] == TreeEvent.SESSION_HISTORY_CHANGED]
        assert len(history_events) == 0
