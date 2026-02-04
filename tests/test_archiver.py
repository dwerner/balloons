"""Tests for archiving and rehydrating conversation turns.

This module tests the Archiver class which handles:
1. Offloading ranges of turns to persistent files
2. Replacing those turns with an ArchiveBlock marker
3. Rehydrating (restoring) archived turns back into the session

SPEC: Archive/Rehydrate Flow
============================

Archive flow:
    1. Select turn range to archive (e.g., turns 5-12)
    2. Generate summary of those turns (via LLM)
    3. Serialize turns to JSON file in ~/.balloons/archives/{session_id}/{archive_id}.json
    4. Replace turns with single turn containing ArchiveBlock
    5. Save session

Rehydrate flow:
    1. Find turn with ArchiveBlock
    2. Load archived turns from file
    3. Replace archive turn with original turns
    4. Save session

The ArchiveBlock stores:
    - archive_id: UUID for this archive
    - file_path: Path to archive file
    - summary: LLM-generated summary
    - turn_start/turn_end: Original turn indices
    - message_count: Number of archived turns
    - token_estimate: Estimated tokens saved
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from models import (
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ArchiveBlock,
    ArchiveSummary,
    ContextMode,
)
from session import Turn
from core.archiver import Archiver, ArchiveError


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def temp_archives_dir(tmp_path):
    """Use a temporary directory for archives."""
    archives_dir = tmp_path / "archives"
    archives_dir.mkdir()
    return archives_dir


@pytest.fixture
def archiver(temp_archives_dir):
    """Create an archiver with temp directory."""
    return Archiver(archives_dir=temp_archives_dir)


@pytest.fixture
def simple_conversation():
    """A simple 5-turn conversation."""
    return [
        Turn(role="user", content_block=TextBlock(text="Hello"), tokens=10),
        Turn(role="assistant", content_block=TextBlock(text="Hi there!"), tokens=15),
        Turn(role="user", content_block=TextBlock(text="What is 2+2?"), tokens=12),
        Turn(role="assistant", content_block=TextBlock(text="The answer is 4."), tokens=18),
        Turn(role="user", content_block=TextBlock(text="Thanks!"), tokens=8),
    ]


@pytest.fixture
def conversation_with_tools():
    """Conversation with tool use blocks (each block is a separate turn)."""
    return [
        Turn(role="user", content_block=TextBlock(text="Read the config file"), tokens=20),
        Turn(role="assistant", content_block=TextBlock(text="I'll read that file."), tokens=50),
        Turn(role="assistant", content_block=ToolUseBlock(id="tool_001", name="Read", input={"file_path": "/etc/config.yaml"}), tokens=0),
        Turn(role="assistant", content_block=ToolResultBlock(tool_use_id="tool_001", content="key: value\nport: 8080"), tokens=100),
        Turn(role="assistant", content_block=TextBlock(text="The config contains key=value and port=8080."), tokens=30),
        Turn(role="user", content_block=TextBlock(text="Great, thanks!"), tokens=10),
    ]


@pytest.fixture
def long_conversation():
    """A longer conversation for testing ranges."""
    turns = []
    for i in range(20):
        role = "user" if i % 2 == 0 else "assistant"
        turns.append(Turn(
            role=role,
            content_block=TextBlock(text=f"Message {i}"),
            tokens=10 + i,
        ))
    return turns


# =============================================================================
# Archive Tests
# =============================================================================

class TestArchiveTurns:
    """Tests for archiving turns."""

    def test_archive_creates_file(self, archiver, simple_conversation, temp_archives_dir):
        """Archiving creates a JSON file in the archives directory."""
        session_id = "test-session-123"
        archive_block, new_turns = archiver.archive_turns(
            session_id=session_id,
            turns=simple_conversation,
            turn_start=1,
            turn_end=4,
            summary="Discussion about math",
        )

        # File should exist
        file_path = Path(archive_block.file_path)
        assert file_path.exists()
        assert file_path.parent == temp_archives_dir / session_id

    def test_archive_file_contains_turns(self, archiver, simple_conversation):
        """Archive file contains the serialized turns."""
        archive_block, _ = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=1,
            turn_end=4,
            summary="Test summary",
        )

        # Read and verify file contents
        data = json.loads(Path(archive_block.file_path).read_text())
        assert len(data["turns"]) == 3  # turns 1, 2, 3
        assert data["turns"][0]["content_block"]["text"] == "Hi there!"
        assert data["turns"][1]["content_block"]["text"] == "What is 2+2?"
        assert data["turns"][2]["content_block"]["text"] == "The answer is 4."

    def test_archive_returns_correct_block(self, archiver, simple_conversation):
        """Archive returns an ArchiveBlock with correct metadata."""
        archive_block, _ = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=1,
            turn_end=4,
            summary="Math discussion",
        )

        assert archive_block.type == "archive"
        assert archive_block.summary == "Math discussion"
        assert archive_block.turn_start == 1
        assert archive_block.turn_end == 4
        assert archive_block.message_count == 3
        assert archive_block.token_estimate == 15 + 12 + 18  # tokens from turns 1-3

    def test_archive_returns_modified_turn_list(self, archiver, simple_conversation):
        """Archive returns new turn list with archive marker replacing turns."""
        archive_block, new_turns = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=1,
            turn_end=4,
            summary="Test",
        )

        # Original: 5 turns, archived 3, replaced with 1 = 3 turns
        assert len(new_turns) == 3

        # First turn unchanged
        assert new_turns[0].content == "Hello"

        # Second turn is now the archive marker
        assert new_turns[1].role == "system"
        assert isinstance(new_turns[1].content_block, ArchiveBlock)

        # Third turn is the original last turn
        assert new_turns[2].content == "Thanks!"

    def test_archive_with_tool_blocks(self, archiver, conversation_with_tools):
        """Archiving preserves tool use and result blocks."""
        archive_block, _ = archiver.archive_turns(
            session_id="test-session",
            turns=conversation_with_tools,
            turn_start=1,
            turn_end=5,
            summary="Tool usage",
        )

        # Load and verify tool blocks preserved
        loaded = archiver.load_archive(archive_block)
        assert len(loaded) == 4  # 4 turns (text, tool_use, tool_result, text)

        # Check tool use block
        tool_turn = loaded[1]
        assert isinstance(tool_turn.content_block, ToolUseBlock)
        assert tool_turn.content_block.name == "Read"

        # Check tool result block
        result_turn = loaded[2]
        assert isinstance(result_turn.content_block, ToolResultBlock)
        assert "key: value" in result_turn.content_block.content

    def test_archive_full_range(self, archiver, simple_conversation):
        """Can archive all turns."""
        archive_block, new_turns = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=0,
            turn_end=5,
            summary="Entire conversation",
        )

        # Only the archive marker remains
        assert len(new_turns) == 1
        assert new_turns[0].role == "system"

    def test_archive_single_turn(self, archiver, simple_conversation):
        """Can archive a single turn."""
        archive_block, new_turns = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=2,
            turn_end=3,
            summary="Single question",
        )

        assert archive_block.message_count == 1
        assert len(new_turns) == 5  # 5 - 1 + 1 = 5

    def test_archive_preserves_context_mode(self, archiver):
        """Archive preserves context_mode on turns."""
        turns = [
            Turn(role="user", content_block=TextBlock(text="Drop me"), context_mode=ContextMode.DROP),
            Turn(role="assistant", content_block=TextBlock(text="Summarize me"), context_mode=ContextMode.SUMMARIZE, summary="Brief"),
            Turn(role="user", content_block=TextBlock(text="Copy me"), context_mode=ContextMode.COPY),
        ]

        archive_block, _ = archiver.archive_turns(
            session_id="test-session",
            turns=turns,
            turn_start=0,
            turn_end=3,
            summary="Mixed modes",
        )

        loaded = archiver.load_archive(archive_block)
        assert loaded[0].context_mode == ContextMode.DROP
        assert loaded[1].context_mode == ContextMode.SUMMARIZE
        assert loaded[1].summary == "Brief"
        assert loaded[2].context_mode == ContextMode.COPY

    def test_archive_preserves_exchange_id(self, archiver):
        """Archive preserves exchange_id grouping."""
        turns = [
            Turn(role="user", content_block=TextBlock(text="Start"), exchange_id="ex-001"),
            Turn(role="assistant", content_block=TextBlock(text="Response 1"), exchange_id="ex-001"),
            Turn(role="assistant", content_block=TextBlock(text="Response 2"), exchange_id="ex-001"),
        ]

        archive_block, _ = archiver.archive_turns(
            session_id="test-session",
            turns=turns,
            turn_start=0,
            turn_end=3,
            summary="Exchange",
        )

        loaded = archiver.load_archive(archive_block)
        assert all(t.exchange_id == "ex-001" for t in loaded)


class TestArchiveErrors:
    """Tests for archive error handling."""

    def test_invalid_start_index(self, archiver, simple_conversation):
        """Negative start index raises error."""
        with pytest.raises(ArchiveError) as exc_info:
            archiver.archive_turns(
                session_id="test",
                turns=simple_conversation,
                turn_start=-1,
                turn_end=3,
                summary="Test",
            )
        assert "Invalid turn range" in str(exc_info.value)

    def test_invalid_end_index(self, archiver, simple_conversation):
        """End index beyond turn count raises error."""
        with pytest.raises(ArchiveError) as exc_info:
            archiver.archive_turns(
                session_id="test",
                turns=simple_conversation,
                turn_start=0,
                turn_end=100,
                summary="Test",
            )
        assert "Invalid turn range" in str(exc_info.value)

    def test_start_equals_end(self, archiver, simple_conversation):
        """Empty range (start == end) raises error."""
        with pytest.raises(ArchiveError) as exc_info:
            archiver.archive_turns(
                session_id="test",
                turns=simple_conversation,
                turn_start=2,
                turn_end=2,
                summary="Test",
            )
        assert "Invalid turn range" in str(exc_info.value)

    def test_start_greater_than_end(self, archiver, simple_conversation):
        """Start > end raises error."""
        with pytest.raises(ArchiveError) as exc_info:
            archiver.archive_turns(
                session_id="test",
                turns=simple_conversation,
                turn_start=4,
                turn_end=2,
                summary="Test",
            )
        assert "Invalid turn range" in str(exc_info.value)


# =============================================================================
# Rehydrate Tests
# =============================================================================

class TestRehydrate:
    """Tests for rehydrating archived turns."""

    def test_rehydrate_restores_turns(self, archiver, simple_conversation):
        """Rehydrating replaces archive block with original turns."""
        # First archive
        archive_block, archived_turns = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=1,
            turn_end=4,
            summary="Test",
        )

        # Then rehydrate (archive is at index 1 in new list)
        restored_turns = archiver.rehydrate(archived_turns, archive_turn_index=1)

        # Should have all 5 original turns
        assert len(restored_turns) == 5
        assert restored_turns[0].content == "Hello"
        assert restored_turns[1].content == "Hi there!"
        assert restored_turns[2].content == "What is 2+2?"
        assert restored_turns[3].content == "The answer is 4."
        assert restored_turns[4].content == "Thanks!"

    def test_rehydrate_preserves_surrounding_turns(self, archiver, long_conversation):
        """Rehydrating preserves turns before and after the archive."""
        # Archive turns 5-10 (indices are 0-based)
        archive_block, archived_turns = archiver.archive_turns(
            session_id="test-session",
            turns=long_conversation,
            turn_start=5,
            turn_end=10,
            summary="Middle section",
        )

        # Verify the archived list structure
        # Original: 20 turns, archived 5 (indices 5-9), replaced with 1
        # Result: 5 + 1 + 10 = 16 turns
        assert len(archived_turns) == 16

        # Rehydrate
        restored = archiver.rehydrate(archived_turns, archive_turn_index=5)

        # Should have all 20 original turns back
        assert len(restored) == 20
        for i in range(20):
            assert restored[i].content == f"Message {i}"

    def test_rehydrate_with_tool_blocks(self, archiver, conversation_with_tools):
        """Rehydrating preserves tool blocks."""
        archive_block, archived_turns = archiver.archive_turns(
            session_id="test-session",
            turns=conversation_with_tools,
            turn_start=1,
            turn_end=5,
            summary="Tool session",
        )

        restored = archiver.rehydrate(archived_turns, archive_turn_index=1)

        # Verify tool blocks are intact
        assert len(restored) == 6
        assert isinstance(restored[2].content_block, ToolUseBlock)
        assert restored[2].content_block.name == "Read"
        assert isinstance(restored[3].content_block, ToolResultBlock)

    def test_rehydrate_archive_at_start(self, archiver, simple_conversation):
        """Can rehydrate an archive at the start of the turn list."""
        archive_block, archived_turns = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=0,
            turn_end=3,
            summary="Start",
        )

        # Archive is at index 0
        restored = archiver.rehydrate(archived_turns, archive_turn_index=0)

        assert len(restored) == 5
        assert restored[0].content == "Hello"

    def test_rehydrate_archive_at_end(self, archiver, simple_conversation):
        """Can rehydrate an archive at the end of the turn list."""
        archive_block, archived_turns = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=3,
            turn_end=5,
            summary="End",
        )

        # Archive is at index 3 (after turns 0, 1, 2)
        restored = archiver.rehydrate(archived_turns, archive_turn_index=3)

        assert len(restored) == 5
        assert restored[4].content == "Thanks!"


class TestRehydrateErrors:
    """Tests for rehydrate error handling."""

    def test_rehydrate_invalid_index(self, archiver, simple_conversation):
        """Invalid archive index raises error."""
        archive_block, archived_turns = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=1,
            turn_end=3,
            summary="Test",
        )

        with pytest.raises(ArchiveError) as exc_info:
            archiver.rehydrate(archived_turns, archive_turn_index=100)
        assert "Invalid archive turn index" in str(exc_info.value)

    def test_rehydrate_not_archive_block(self, archiver, simple_conversation):
        """Rehydrating a non-archive turn raises error."""
        with pytest.raises(ArchiveError) as exc_info:
            archiver.rehydrate(simple_conversation, archive_turn_index=0)
        assert "does not contain an archive block" in str(exc_info.value)

    def test_rehydrate_missing_file(self, archiver, simple_conversation, temp_archives_dir):
        """Rehydrating with missing archive file raises error."""
        archive_block, archived_turns = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=1,
            turn_end=3,
            summary="Test",
        )

        # Delete the archive file
        Path(archive_block.file_path).unlink()

        with pytest.raises(ArchiveError) as exc_info:
            archiver.rehydrate(archived_turns, archive_turn_index=1)
        assert "not found" in str(exc_info.value)


# =============================================================================
# Round-trip Tests
# =============================================================================

class TestArchiveRoundTrip:
    """Tests for archive -> rehydrate round-trips."""

    def test_full_round_trip_preserves_all_data(self, archiver, conversation_with_tools):
        """Full archive -> rehydrate preserves all turn data."""
        original = conversation_with_tools

        # Archive and rehydrate
        archive_block, archived = archiver.archive_turns(
            session_id="test-session",
            turns=original,
            turn_start=0,
            turn_end=len(original),
            summary="All turns",
        )
        restored = archiver.rehydrate(archived, archive_turn_index=0)

        # Compare each turn
        assert len(restored) == len(original)
        for orig, rest in zip(original, restored):
            assert rest.role == orig.role
            assert rest.tokens == orig.tokens
            assert type(rest.content_block) == type(orig.content_block)

    def test_multiple_archives_in_sequence(self, archiver, long_conversation):
        """Can create multiple archives in the same session."""
        session_id = "test-session"
        turns = long_conversation

        # Archive turns 0-5
        block1, turns = archiver.archive_turns(
            session_id=session_id,
            turns=turns,
            turn_start=0,
            turn_end=5,
            summary="First five",
        )

        # Now archive turns 10-15 (indices shifted due to first archive)
        # Original indices 10-15 are now at 6-11 (shifted by -4: 5 removed, 1 added)
        block2, turns = archiver.archive_turns(
            session_id=session_id,
            turns=turns,
            turn_start=6,
            turn_end=11,
            summary="Second batch",
        )

        # Should have: 1 archive + 5 turns + 1 archive + 5 turns = 12
        assert len(turns) == 12

        # Rehydrate second archive (at index 6)
        turns = archiver.rehydrate(turns, archive_turn_index=6)
        # Now: 1 archive + 5 turns + 5 turns + 5 turns = 16
        assert len(turns) == 16

        # Rehydrate first archive (at index 0)
        turns = archiver.rehydrate(turns, archive_turn_index=0)
        # Back to original 20
        assert len(turns) == 20

    def test_nested_archive_not_allowed(self, archiver, simple_conversation):
        """Archiving a range containing an archive block preserves it."""
        # First archive
        archive_block, archived = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=1,
            turn_end=3,
            summary="Inner archive",
        )

        # Archive the entire list including the archive marker
        outer_block, double_archived = archiver.archive_turns(
            session_id="test-session",
            turns=archived,
            turn_start=0,
            turn_end=len(archived),
            summary="Outer archive",
        )

        # Load outer archive, should contain the archive marker
        loaded = archiver.load_archive(outer_block)
        assert len(loaded) == 4  # Original minus 2 + archive marker

        # The archive marker should be preserved
        has_archive_block = False
        for turn in loaded:
            if isinstance(turn.content_block, ArchiveBlock):
                has_archive_block = True
        assert has_archive_block


# =============================================================================
# Delete and Info Tests
# =============================================================================

class TestArchiveManagement:
    """Tests for archive deletion and info retrieval."""

    def test_delete_archive(self, archiver, simple_conversation):
        """Can delete an archive file."""
        archive_block, _ = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=1,
            turn_end=3,
            summary="Test",
        )

        assert Path(archive_block.file_path).exists()

        result = archiver.delete_archive(archive_block)
        assert result is True
        assert not Path(archive_block.file_path).exists()

    def test_delete_nonexistent_archive(self, archiver):
        """Deleting nonexistent archive returns False."""
        fake_block = ArchiveBlock(
            archive_id="fake",
            file_path="/nonexistent/path.json",
            summary="Fake",
        )
        result = archiver.delete_archive(fake_block)
        assert result is False

    def test_get_archive_info(self, archiver, simple_conversation):
        """Can get archive metadata without loading turns."""
        archive_block, _ = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=1,
            turn_end=4,
            summary="Math discussion",
        )

        info = archiver.get_archive_info(archive_block)

        assert info is not None
        assert info["archive_id"] == archive_block.archive_id
        assert info["session_id"] == "test-session"
        assert info["summary"] == "Math discussion"
        assert info["turn_start"] == 1
        assert info["turn_end"] == 4
        assert info["message_count"] == 3

    def test_get_archive_info_missing_file(self, archiver):
        """Get info for missing archive returns None."""
        fake_block = ArchiveBlock(
            archive_id="fake",
            file_path="/nonexistent/path.json",
            summary="Fake",
        )
        info = archiver.get_archive_info(fake_block)
        assert info is None


# =============================================================================
# Structured Summary Tests
# =============================================================================

class TestArchiveSummary:
    """Tests for structured ArchiveSummary in archives."""

    @pytest.fixture
    def temp_archives_dir(self, tmp_path):
        """Use a temporary directory for archives."""
        archives_dir = tmp_path / "archives"
        archives_dir.mkdir()
        return archives_dir

    @pytest.fixture
    def archiver(self, temp_archives_dir):
        """Create an archiver with temp directory."""
        return Archiver(archives_dir=temp_archives_dir)

    @pytest.fixture
    def simple_conversation(self):
        """A simple 5-turn conversation."""
        return [
            Turn(role="user", content_block=TextBlock(text="Hello"), tokens=10),
            Turn(role="assistant", content_block=TextBlock(text="Hi there!"), tokens=15),
            Turn(role="user", content_block=TextBlock(text="What is 2+2?"), tokens=12),
            Turn(role="assistant", content_block=TextBlock(text="The answer is 4."), tokens=18),
            Turn(role="user", content_block=TextBlock(text="Thanks!"), tokens=8),
        ]

    def test_archive_with_structured_summary(self, archiver, simple_conversation):
        """Can archive with an ArchiveSummary instead of plain string."""
        summary = ArchiveSummary(
            files_modified=["math.py (created)", "utils.py (modified)"],
            work_done="Implemented basic arithmetic operations.",
            key_decisions=["Used integer math for simplicity"],
        )

        archive_block, new_turns = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=1,
            turn_end=4,
            summary=summary,
        )

        assert archive_block.structured_summary is not None
        assert archive_block.structured_summary.files_modified == ["math.py (created)", "utils.py (modified)"]
        assert archive_block.structured_summary.work_done == "Implemented basic arithmetic operations."
        assert archive_block.structured_summary.key_decisions == ["Used integer math for simplicity"]

    def test_structured_summary_persists_to_file(self, archiver, simple_conversation):
        """Structured summary is saved to archive file."""
        summary = ArchiveSummary(
            files_modified=["test.py"],
            work_done="Added tests.",
            key_decisions=["Used pytest"],
        )

        archive_block, _ = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=0,
            turn_end=2,
            summary=summary,
        )

        # Read the file directly
        data = json.loads(Path(archive_block.file_path).read_text())
        assert "structured_summary" in data
        assert data["structured_summary"]["files_modified"] == ["test.py"]
        assert data["structured_summary"]["work_done"] == "Added tests."

    def test_structured_summary_round_trip(self, archiver, simple_conversation):
        """Structured summary survives archive -> rehydrate."""
        summary = ArchiveSummary(
            files_modified=["a.py", "b.py"],
            work_done="Refactored code.",
            key_decisions=["Split into modules", "Added type hints"],
        )

        archive_block, archived = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=0,
            turn_end=5,
            summary=summary,
        )

        # The archive block in the archived turns should have the summary
        archive_turn = archived[0]
        block = archive_turn.content_block
        assert isinstance(block, ArchiveBlock)
        assert block.structured_summary is not None
        assert block.structured_summary.key_decisions == ["Split into modules", "Added type hints"]

    def test_get_display_summary_with_structured(self, archiver, simple_conversation):
        """get_display_summary uses structured summary when available."""
        summary = ArchiveSummary(
            files_modified=["core/main.py", "core/utils.py", "tests/test_main.py", "docs/README.md"],
            work_done="Implemented the main feature with tests and documentation.",
            key_decisions=[],
        )

        archive_block, _ = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=0,
            turn_end=3,
            summary=summary,
        )

        display = archive_block.get_display_summary()
        assert "Implemented the main feature" in display
        assert "Files:" in display
        assert "+1 more" in display  # 4 files, showing 3 + 1

    def test_get_display_summary_falls_back_to_plain(self):
        """get_display_summary uses plain summary when no structured."""
        block = ArchiveBlock(
            archive_id="test",
            file_path="/test.json",
            summary="Plain text summary",
            structured_summary=None,
        )

        assert block.get_display_summary() == "Plain text summary"

    def test_archive_with_plain_string_still_works(self, archiver, simple_conversation):
        """Plain string summary still works (backwards compat)."""
        archive_block, _ = archiver.archive_turns(
            session_id="test-session",
            turns=simple_conversation,
            turn_start=0,
            turn_end=2,
            summary="Just a plain summary",
        )

        assert archive_block.summary == "Just a plain summary"
        assert archive_block.structured_summary is None


# =============================================================================
# ArchiveMarker Widget Tests
# =============================================================================

class TestArchiveMarkerWidget:
    """Tests for the ArchiveMarker widget."""

    def test_archive_marker_creation(self):
        """ArchiveMarker can be created with an ArchiveBlock."""
        from widgets.archive_marker import ArchiveMarker

        block = ArchiveBlock(
            archive_id="test-archive-001",
            file_path="/archives/test.json",
            summary="Test archive",
            message_count=7,
            token_estimate=2400,
            turn_start=5,
            turn_end=12,
        )

        marker = ArchiveMarker(archive_block=block, turn_id=3, turn_index=5)

        assert marker.archive_block == block
        assert marker.turn_id == 3
        assert marker.turn_index == 5

    def test_archive_marker_with_structured_summary(self):
        """ArchiveMarker displays structured summary correctly."""
        from widgets.archive_marker import ArchiveMarker

        summary = ArchiveSummary(
            files_modified=["auth.py (created)", "utils.py (modified)"],
            work_done="Implemented user authentication with JWT tokens.",
            key_decisions=["Used stateless auth", "Added refresh endpoint"],
        )

        block = ArchiveBlock(
            archive_id="test-archive-002",
            file_path="/archives/test.json",
            summary="",
            structured_summary=summary,
            message_count=7,
            token_estimate=2400,
            turn_start=5,
            turn_end=12,
        )

        marker = ArchiveMarker(archive_block=block, turn_id=1, turn_index=5)

        # The marker should have access to structured summary
        assert marker.archive_block.structured_summary is not None
        assert marker.archive_block.structured_summary.work_done == "Implemented user authentication with JWT tokens."

    def test_archive_marker_render_content(self):
        """ArchiveMarker renders all expected content."""
        from widgets.archive_marker import ArchiveMarker

        summary = ArchiveSummary(
            files_modified=["core/auth.py"],
            work_done="Added authentication.",
            key_decisions=["JWT tokens"],
        )

        block = ArchiveBlock(
            archive_id="test",
            file_path="/test.json",
            structured_summary=summary,
            message_count=5,
            token_estimate=1500,
        )

        marker = ArchiveMarker(archive_block=block, turn_id=1, turn_index=0)
        rendered = marker.render()

        # Convert to string to check content
        rendered_str = str(rendered)
        assert "5 turns" in rendered_str
        assert "1,500 tokens" in rendered_str
        assert "core/auth.py" in rendered_str
        assert "Added authentication" in rendered_str
        assert "JWT tokens" in rendered_str
        assert "Ctrl+Shift+Click" in rendered_str

    def test_archive_marker_render_plain_summary(self):
        """ArchiveMarker renders plain summary when no structured summary."""
        from widgets.archive_marker import ArchiveMarker

        block = ArchiveBlock(
            archive_id="test",
            file_path="/test.json",
            summary="A plain text summary of the archive.",
            structured_summary=None,
            message_count=3,
            token_estimate=800,
        )

        marker = ArchiveMarker(archive_block=block, turn_id=1, turn_index=0)
        rendered = marker.render()

        rendered_str = str(rendered)
        assert "A plain text summary" in rendered_str
        assert "3 turns" in rendered_str

    def test_archive_marker_truncates_long_lists(self):
        """ArchiveMarker truncates long file and decision lists."""
        from widgets.archive_marker import ArchiveMarker

        summary = ArchiveSummary(
            files_modified=[
                "a.py", "b.py", "c.py", "d.py", "e.py", "f.py"
            ],
            work_done="Did many things.",
            key_decisions=[
                "Decision 1", "Decision 2", "Decision 3", "Decision 4", "Decision 5"
            ],
        )

        block = ArchiveBlock(
            archive_id="test",
            file_path="/test.json",
            structured_summary=summary,
            message_count=10,
        )

        marker = ArchiveMarker(archive_block=block, turn_id=1, turn_index=0)
        rendered = marker.render()

        rendered_str = str(rendered)
        # Files should show 4 + "more"
        assert "+2 more" in rendered_str  # 6 files - 4 shown = 2 more
        # Decisions should show 3 + "more"
        assert "+2 more" in rendered_str  # 5 decisions - 3 shown = 2 more

    def test_archive_marker_message_class(self):
        """ArchiveMarker has correct Message class for rehydration."""
        from widgets.archive_marker import ArchiveMarker

        block = ArchiveBlock(
            archive_id="test-id",
            file_path="/test.json",
            summary="Test",
            message_count=5,
        )

        marker = ArchiveMarker(archive_block=block, turn_id=1, turn_index=7)

        # Check the message class exists and has correct attributes
        assert hasattr(ArchiveMarker, "RehydrateRequested")

        # Create a message instance to verify structure
        msg = ArchiveMarker.RehydrateRequested(archive_id="test-id", turn_index=7, file_path="/test.json")
        assert msg.archive_id == "test-id"
        assert msg.turn_index == 7
        assert msg.file_path == "/test.json"

    def test_archive_marker_shows_file_path(self):
        """ArchiveMarker displays the archive file path."""
        from widgets.archive_marker import ArchiveMarker

        block = ArchiveBlock(
            archive_id="test",
            file_path="/home/user/.balloons/archives/session-123/archive-456.json",
            summary="Test archive",
            message_count=5,
        )

        marker = ArchiveMarker(archive_block=block, turn_id=1, turn_index=0)
        rendered = marker.render()

        rendered_str = str(rendered)
        assert "Archive:" in rendered_str
        assert "/home/user/.balloons/archives/session-123/archive-456.json" in rendered_str
        assert "Ctrl+Shift+Click" in rendered_str
