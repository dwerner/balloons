"""Tests for streaming turn labels in context tree.

This test verifies that tool_use and tool_result turns get proper labels
during streaming, not just after finalization.
"""

import pytest
from dataclasses import dataclass, field

# Standard imports - let Python's import system handle everything normally.
# The previous approach of manually loading modules via importlib.util polluted
# sys.modules and caused class identity issues (isinstance would fail because
# the same class loaded twice has different identity).
from models import ContextMode, TextBlock, ToolUseBlock, ToolResultBlock
from core.tree_state import TreeState, TreeEvent, TurnData


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


class TestStreamingLabels:
    """Test that streaming turns get proper labels."""

    def test_text_turn_starts_with_no_content_block(self):
        """Text turns start with content_block=None (expected behavior)."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session, is_current=True)
        state.load_session("s1", session)

        # Simulate streaming: start a text turn
        state.start_turn("s1", turn_idx=0, role="assistant", exchange_id="ex1", turn_type="text")

        turn = state.get_turn("s1", 0)
        assert turn is not None
        assert turn.role == "assistant"
        assert turn.content_block is None  # Text turns don't need skeleton content_block

    def test_tool_use_turn_starts_with_skeleton_content_block(self):
        """Tool use turns get a skeleton ToolUseBlock for proper labels during streaming."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session, is_current=True)
        state.load_session("s1", session)

        # Simulate streaming: start a tool_use turn with turn_type info
        state.start_turn(
            "s1",
            turn_idx=0,
            role="assistant",
            exchange_id="ex1",
            turn_type="tool_use",
            tool_name="Read",
            tool_use_id="tool-123",
        )

        turn = state.get_turn("s1", 0)

        # The turn should have a skeleton content_block
        assert turn is not None
        assert turn.role == "assistant"
        assert turn.content_block is not None
        # Check by type name to avoid importlib class identity issues
        assert turn.content_block.__class__.__name__ == "ToolUseBlock"
        assert turn.content_block.name == "Read"
        assert turn.content_block.id == "tool-123"
        assert turn.content == "Read"  # Content is set to tool name for labels

    def test_tool_result_turn_starts_with_skeleton_content_block(self):
        """Tool result turns get a skeleton ToolResultBlock for proper labels during streaming."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session, is_current=True)
        state.load_session("s1", session)

        # Simulate streaming: start a tool_result turn with turn_type info
        state.start_turn(
            "s1",
            turn_idx=0,
            role="tool",
            exchange_id="ex1",
            turn_type="tool_result",
            tool_use_id="tool-123",
            result_preview="File contents...",
        )

        turn = state.get_turn("s1", 0)

        # The turn should have a skeleton content_block
        assert turn is not None
        assert turn.role == "tool"
        assert turn.content_block is not None
        # Check by type name to avoid importlib class identity issues
        assert turn.content_block.__class__.__name__ == "ToolResultBlock"
        assert turn.content_block.tool_use_id == "tool-123"
        assert turn.content == "File contents..."  # Content is set to preview for labels

    def test_finish_turn_replaces_skeleton_content_block(self):
        """finish_turn replaces the skeleton content_block with the real one."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session, is_current=True)
        state.load_session("s1", session)

        # Start with skeleton
        state.start_turn(
            "s1",
            turn_idx=0,
            role="assistant",
            exchange_id="ex1",
            turn_type="tool_use",
            tool_name="Read",
            tool_use_id="tool-123",
        )

        # Skeleton content_block has empty input
        turn = state.get_turn("s1", 0)
        assert turn.content_block.input == {}

        # Finish with real content_block that has actual input
        real_block = ToolUseBlock(id="tool-123", name="Read", input={"path": "/test"})
        state.finish_turn("s1", 0, "Read /test", real_block, [])

        turn = state.get_turn("s1", 0)

        # Now we have the real content_block with full input
        assert turn.content_block is not None
        assert isinstance(turn.content_block, ToolUseBlock)
        assert turn.content_block.name == "Read"
        assert turn.content_block.input == {"path": "/test"}

    def test_finish_turn_calculates_tokens(self):
        """finish_turn calculates token count from content_block."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session, is_current=True)
        state.load_session("s1", session)

        # Start with skeleton (tokens=0)
        state.start_turn(
            "s1",
            turn_idx=0,
            role="assistant",
            exchange_id="ex1",
            turn_type="tool_use",
            tool_name="Read",
            tool_use_id="tool-123",
        )

        turn = state.get_turn("s1", 0)
        assert turn.tokens == 0  # Skeleton starts with 0 tokens

        # Finish with real content_block
        real_block = ToolUseBlock(
            id="tool-123",
            name="Read",
            input={"file_path": "/home/user/project/src/some_file.py"},
        )
        state.finish_turn("s1", 0, "", real_block, [])

        turn = state.get_turn("s1", 0)

        # Tokens should now be calculated (non-zero for a real tool use)
        assert turn.tokens > 0

    def test_finish_turn_calculates_tokens_for_tool_result(self):
        """finish_turn calculates token count for tool_result turns."""
        state = TreeState()
        session = MockSession(id="s1", turns=[])
        state.add_session(session, is_current=True)
        state.load_session("s1", session)

        # Start with skeleton (tokens=0)
        state.start_turn(
            "s1",
            turn_idx=0,
            role="tool",
            exchange_id="ex1",
            turn_type="tool_result",
            tool_use_id="tool-123",
            result_preview="...",
        )

        turn = state.get_turn("s1", 0)
        assert turn.tokens == 0  # Skeleton starts with 0 tokens

        # Finish with real content_block containing actual result
        real_block = ToolResultBlock(
            tool_use_id="tool-123",
            content="Here is the file contents with lots of text that should result in tokens being counted properly.",
        )
        state.finish_turn("s1", 0, "", real_block, [])

        turn = state.get_turn("s1", 0)

        # Tokens should now be calculated (non-zero for a real tool result)
        assert turn.tokens > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
