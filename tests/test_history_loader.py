"""Tests for history_loader module."""

import pytest
from core.history_loader import (
    HistoryLoader, HistoryLoadResult,
    RenderMessage, RenderToolUse, RenderToolResult,
    RenderInterruption, RenderError, RenderLink, RenderArchive,
    RenderFork, RenderMerge
)
from models import (
    Message, TextBlock, ToolUseBlock, ToolResultBlock,
    InterruptionBlock, ErrorBlock, LinkBlock, ForkBlock,
    MergeBlock, ArchiveBlock
)


class MockSession:
    """Mock session for testing."""
    def __init__(self, id: str, title: str = "", fork_name: str = "", children=None, merge_message: str = ""):
        self.id = id
        self.title = title
        self.fork_name = fork_name
        self.children = children or []
        self.merge_message = merge_message

    def get_fork_display_name(self):
        return self.fork_name or self.id[:8]


class TestHistoryLoaderBasics:
    """Test basic message transformation."""

    def test_empty_messages(self):
        """Empty message list returns empty instructions."""
        loader = HistoryLoader()
        result = loader.load([])

        assert result.instructions == []
        assert result.final_turn_id == 0

    def test_simple_text_message(self):
        """Single text message produces RenderMessage."""
        loader = HistoryLoader()
        msg = Message(
            role="user",
            content="Hello world",
            content_blocks=[TextBlock(text="Hello world")]
        )
        result = loader.load([msg])

        assert len(result.instructions) == 1
        instr = result.instructions[0]
        assert isinstance(instr, RenderMessage)
        assert instr.role == "user"
        assert instr.text == "Hello world"
        assert instr.turn_id == 1
        assert instr.block_idx == 0

    def test_fallback_to_content_field(self):
        """Message without content_blocks uses content field."""
        loader = HistoryLoader()
        msg = Message(role="assistant", content="Fallback text", content_blocks=[])
        result = loader.load([msg])

        assert len(result.instructions) == 1
        instr = result.instructions[0]
        assert isinstance(instr, RenderMessage)
        assert instr.text == "Fallback text"

    def test_empty_text_skipped(self):
        """Empty or whitespace-only text blocks are skipped."""
        loader = HistoryLoader()
        msg = Message(
            role="user",
            content="",
            content_blocks=[TextBlock(text=""), TextBlock(text="   ")]
        )
        result = loader.load([msg])

        assert len(result.instructions) == 0

    def test_multiple_messages_increment_turn_id(self):
        """Each message gets a unique incrementing turn_id."""
        loader = HistoryLoader()
        messages = [
            Message(role="user", content="First", content_blocks=[TextBlock(text="First")]),
            Message(role="assistant", content="Second", content_blocks=[TextBlock(text="Second")]),
            Message(role="user", content="Third", content_blocks=[TextBlock(text="Third")]),
        ]
        result = loader.load(messages)

        assert len(result.instructions) == 3
        assert result.instructions[0].turn_id == 1
        assert result.instructions[1].turn_id == 2
        assert result.instructions[2].turn_id == 3
        assert result.final_turn_id == 3


class TestToolBlocks:
    """Test tool use and result blocks."""

    def test_tool_use_block(self):
        """ToolUseBlock produces RenderToolUse."""
        loader = HistoryLoader()
        msg = Message(
            role="assistant",
            content="",
            content_blocks=[
                ToolUseBlock(id="tool-123", name="read_file", input={"path": "/foo"})
            ]
        )
        result = loader.load([msg])

        assert len(result.instructions) == 1
        instr = result.instructions[0]
        assert isinstance(instr, RenderToolUse)
        assert instr.tool_name == "read_file"
        assert instr.tool_use_id == "tool-123"
        assert instr.tool_input == {"path": "/foo"}

    def test_tool_result_block(self):
        """ToolResultBlock produces RenderToolResult."""
        loader = HistoryLoader()
        msg = Message(
            role="user",
            content="",
            content_blocks=[
                ToolResultBlock(tool_use_id="tool-123", content="file contents", is_error=False)
            ]
        )
        result = loader.load([msg])

        assert len(result.instructions) == 1
        instr = result.instructions[0]
        assert isinstance(instr, RenderToolResult)
        assert instr.tool_use_id == "tool-123"
        assert instr.content == "file contents"
        assert instr.is_error is False

    def test_tool_result_error(self):
        """Tool result with error flag is preserved."""
        loader = HistoryLoader()
        msg = Message(
            role="user",
            content="",
            content_blocks=[
                ToolResultBlock(tool_use_id="tool-456", content="Error: not found", is_error=True)
            ]
        )
        result = loader.load([msg])

        instr = result.instructions[0]
        assert instr.is_error is True


class TestSpecialBlocks:
    """Test special marker blocks."""

    def test_interruption_block(self):
        """InterruptionBlock produces RenderInterruption."""
        loader = HistoryLoader()
        msg = Message(
            role="assistant",
            content="",
            content_blocks=[InterruptionBlock(reason="user_cancelled")]
        )
        result = loader.load([msg])

        instr = result.instructions[0]
        assert isinstance(instr, RenderInterruption)
        assert instr.reason == "user_cancelled"

    def test_error_block(self):
        """ErrorBlock produces RenderError with all fields."""
        loader = HistoryLoader()
        msg = Message(
            role="assistant",
            content="",
            content_blocks=[
                ErrorBlock(
                    reason="truncated",
                    partial_tool_name="write_file",
                    details="Stream ended unexpectedly",
                    dump_file="/tmp/dump.json"
                )
            ]
        )
        result = loader.load([msg])

        instr = result.instructions[0]
        assert isinstance(instr, RenderError)
        assert instr.reason == "truncated"
        assert instr.partial_tool_name == "write_file"
        assert instr.details == "Stream ended unexpectedly"
        assert instr.dump_file == "/tmp/dump.json"

    def test_archive_block(self):
        """ArchiveBlock produces RenderArchive."""
        loader = HistoryLoader()
        archive = ArchiveBlock(
            archive_id="arch-1",
            file_path="/archives/arch-1.json",
            summary="Implemented feature X",
            turn_start=5,
            turn_end=10,
            message_count=5
        )
        msg = Message(role="user", content="", content_blocks=[archive])
        result = loader.load([msg])

        instr = result.instructions[0]
        assert isinstance(instr, RenderArchive)
        assert instr.archive_block is archive
        assert instr.turn_index == 0


class TestLinkBlock:
    """Test link block with session lookup."""

    def test_link_block_with_session(self):
        """LinkBlock looks up linked session for name."""
        sessions = {
            "linked-sess-123": MockSession(
                id="linked-sess-123",
                title="Linked Chat",
                fork_name=""
            )
        }
        loader = HistoryLoader(session_loader=lambda id: sessions.get(id))

        msg = Message(
            role="user",
            content="",
            content_blocks=[
                LinkBlock(
                    link_id="link-1",
                    linked_session_id="linked-sess-123",
                    summary="Related discussion"
                )
            ]
        )
        result = loader.load([msg])

        instr = result.instructions[0]
        assert isinstance(instr, RenderLink)
        assert instr.linked_session_id == "linked-sess-123"
        assert instr.linked_session_name == "Linked Chat"
        assert instr.summary == "Related discussion"
        assert instr.is_orphaned is False

    def test_link_block_orphaned(self):
        """LinkBlock with missing session becomes orphaned."""
        loader = HistoryLoader(session_loader=lambda id: None)

        msg = Message(
            role="user",
            content="",
            content_blocks=[
                LinkBlock(
                    link_id="link-2",
                    linked_session_id="missing-sess",
                    summary="Lost link"
                )
            ]
        )
        result = loader.load([msg])

        instr = result.instructions[0]
        assert instr.is_orphaned is True
        assert instr.linked_session_name == "missing-"  # First 8 chars


class TestForkMergeBlocks:
    """Test fork and merge blocks (from content blocks)."""

    def test_fork_block_in_content(self):
        """ForkBlock in content produces RenderFork."""
        loader = HistoryLoader()
        msg = Message(
            role="assistant",
            content="",
            content_blocks=[
                ForkBlock(
                    fork_id="fork-1",
                    child_session_id="child-123",
                    fork_name="refactor-branch",
                    prompt="Let's refactor this",
                    status="active"
                )
            ]
        )
        result = loader.load([msg])

        instr = result.instructions[0]
        assert isinstance(instr, RenderFork)
        assert instr.child_session_id == "child-123"
        assert instr.fork_name == "refactor-branch"
        assert instr.prompt == "Let's refactor this"
        assert instr.status == "active"

    def test_merge_block_in_content(self):
        """MergeBlock in content produces RenderMerge."""
        loader = HistoryLoader()
        msg = Message(
            role="assistant",
            content="",
            content_blocks=[
                MergeBlock(
                    merge_id="merge-1",
                    child_session_id="child-123",
                    fork_name="refactor-branch",
                    message="Refactoring complete"
                )
            ]
        )
        result = loader.load([msg])

        instr = result.instructions[0]
        assert isinstance(instr, RenderMerge)
        assert instr.child_session_id == "child-123"
        assert instr.fork_name == "refactor-branch"
        assert instr.message == "Refactoring complete"


class TestForkMergeFromSession:
    """Test fork/merge markers from session children metadata."""

    def test_fork_from_session_children(self):
        """Fork markers are created from session.children with fork_point."""
        child_session = MockSession(
            id="child-456",
            fork_name="feature-x"
        )
        sessions = {"child-456": child_session}

        # Parent session with child info
        parent_session = MockSession(
            id="parent-1",
            children=[{
                "session_id": "child-456",
                "fork_point": 1,  # After turn index 1
                "prompt": "Implement feature X",
                "name": "feature-x",
                "status": "active"
            }]
        )

        loader = HistoryLoader(session_loader=lambda id: sessions.get(id))
        messages = [
            Message(role="user", content="Hello", content_blocks=[TextBlock(text="Hello")]),
            Message(role="assistant", content="Hi", content_blocks=[TextBlock(text="Hi")]),
        ]
        result = loader.load(messages, session=parent_session)

        # Should have: msg1, msg2, fork_marker (after turn 1)
        assert len(result.instructions) == 3
        fork_instr = result.instructions[2]
        assert isinstance(fork_instr, RenderFork)
        assert fork_instr.child_session_id == "child-456"
        assert fork_instr.fork_name == "feature-x"
        assert fork_instr.prompt == "Implement feature X"

    def test_merge_from_session_children(self):
        """Merge markers are created from merged children."""
        child_session = MockSession(
            id="child-789",
            fork_name="bugfix",
            merge_message="Fixed the bug"
        )
        sessions = {"child-789": child_session}

        parent_session = MockSession(
            id="parent-2",
            children=[{
                "session_id": "child-789",
                "fork_point": 0,
                "merge_point": 2,  # After turn index 2
                "name": "bugfix",
                "status": "merged"
            }]
        )

        loader = HistoryLoader(session_loader=lambda id: sessions.get(id))
        messages = [
            Message(role="user", content="Fix bug", content_blocks=[TextBlock(text="Fix bug")]),
            Message(role="assistant", content="Ok", content_blocks=[TextBlock(text="Ok")]),
            Message(role="user", content="Done", content_blocks=[TextBlock(text="Done")]),
        ]
        result = loader.load(messages, session=parent_session)

        # Should have: msg1, fork (after 0), msg2, msg3, merge (after 2)
        # Order: msg1(turn1), fork(turn1), msg2(turn2), msg3(turn3), merge(turn3)
        fork_instrs = [i for i in result.instructions if isinstance(i, RenderFork)]
        merge_instrs = [i for i in result.instructions if isinstance(i, RenderMerge)]

        assert len(fork_instrs) == 1
        assert len(merge_instrs) == 1
        assert merge_instrs[0].message == "Fixed the bug"
        assert merge_instrs[0].turn_id == 3

    def test_fork_at_end(self):
        """Fork at end (fork_point == len(messages)) is handled."""
        child_session = MockSession(id="child-end", fork_name="end-fork")
        sessions = {"child-end": child_session}

        parent_session = MockSession(
            id="parent-3",
            children=[{
                "session_id": "child-end",
                "fork_point": 1,  # After all messages (len == 1)
                "status": "active"
            }]
        )

        loader = HistoryLoader(session_loader=lambda id: sessions.get(id))
        messages = [
            Message(role="user", content="Start", content_blocks=[TextBlock(text="Start")]),
        ]
        result = loader.load(messages, session=parent_session)

        fork_instrs = [i for i in result.instructions if isinstance(i, RenderFork)]
        assert len(fork_instrs) == 1


class TestMixedContent:
    """Test messages with multiple content blocks."""

    def test_multiple_blocks_in_message(self):
        """Message with multiple blocks produces multiple instructions."""
        loader = HistoryLoader()
        msg = Message(
            role="assistant",
            content="",
            content_blocks=[
                TextBlock(text="Let me read that file"),
                ToolUseBlock(id="t1", name="read_file", input={"path": "/foo"}),
            ]
        )
        result = loader.load([msg])

        assert len(result.instructions) == 2
        assert isinstance(result.instructions[0], RenderMessage)
        assert isinstance(result.instructions[1], RenderToolUse)
        # Both have same turn_id
        assert result.instructions[0].turn_id == result.instructions[1].turn_id

    def test_block_idx_increments(self):
        """block_idx increments for text blocks within a message."""
        loader = HistoryLoader()
        msg = Message(
            role="assistant",
            content="",
            content_blocks=[
                TextBlock(text="First paragraph"),
                TextBlock(text="Second paragraph"),
            ]
        )
        result = loader.load([msg])

        assert result.instructions[0].block_idx == 0
        assert result.instructions[1].block_idx == 1


class TestStartTurnId:
    """Test starting from non-zero turn_id."""

    def test_start_turn_id(self):
        """Can start from a specific turn_id for appending."""
        loader = HistoryLoader()
        messages = [
            Message(role="user", content="New message", content_blocks=[TextBlock(text="New message")]),
        ]
        result = loader.load(messages, start_turn_id=10)

        assert result.instructions[0].turn_id == 11
        assert result.final_turn_id == 11
