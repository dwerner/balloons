"""Tests for session persistence and progressive saving."""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from session import Session, Turn, SessionIndex, SESSIONS_DIR, INDEX_FILE, MessageQueue, QueuedMessage
from models import Message, TextBlock, ToolUseBlock, ToolResultBlock


class TestSessionProgressiveSaving:
    """Tests demonstrating that sessions should save after each turn."""

    @pytest.fixture
    def temp_sessions_dir(self, tmp_path):
        """Use a temporary directory for sessions."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        index_file = sessions_dir / "index.json"
        with patch("session.SESSIONS_DIR", sessions_dir), \
             patch("session.INDEX_FILE", index_file):
            SessionIndex._instance = None
            yield sessions_dir
            SessionIndex._instance = None

    def test_session_save_persists_turns(self, temp_sessions_dir):
        """Basic test: saved session can be loaded."""
        session = Session()
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there")
        session.save()

        # Load and verify
        loaded = Session.load(session.id)
        assert loaded is not None
        assert len(loaded.turns) == 2
        assert loaded.turns[0].content == "Hello"
        assert loaded.turns[1].content == "Hi there"

    def test_progressive_save_each_turn(self, temp_sessions_dir):
        """Each turn should be persisted immediately after being added.

        This demonstrates the EXPECTED behavior: if we crash after adding
        a turn, that turn should still be on disk.
        """
        session = Session()
        session.save()  # Initial save

        # Simulate an agentic loop where each turn should be saved
        turn_data = [
            ("user", "What files are in the current directory?"),
            ("assistant", "I'll check that for you."),
            ("assistant", "Here are the files: main.py, utils.py"),
        ]

        for role, content in turn_data:
            session.add_message(role, content)
            session.save()  # Progressive save after each turn

            # Verify the turn is on disk
            loaded = Session.load(session.id)
            assert len(loaded.turns) == len(session.turns)
            assert loaded.turns[-1].content == content

    def test_crash_recovery_with_progressive_saves(self, temp_sessions_dir):
        """Simulate crash recovery: only saved turns should survive."""
        session = Session()
        session.save()

        # Add and save first turn
        session.add_message("user", "Turn 1")
        session.save()

        # Add and save second turn
        session.add_message("assistant", "Turn 2")
        session.save()

        # Add third turn but DON'T save (simulating crash before save)
        session.add_message("user", "Turn 3 - this will be lost")

        # Simulate crash by loading from disk (not from memory)
        recovered = Session.load(session.id)

        # Only the saved turns should survive
        assert len(recovered.turns) == 2
        assert recovered.turns[0].content == "Turn 1"
        assert recovered.turns[1].content == "Turn 2"

    def test_tool_loop_saves_each_step(self, temp_sessions_dir):
        """A tool use loop should save after each step.

        Scenario: User asks a question, assistant uses tools in a loop.
        Each tool call and result should be persisted.
        """
        session = Session()
        session.save()

        # User prompt
        session.add_message("user", "Find and read the config file")
        session.save()

        # Verify after user prompt is saved (1 turn: text block)
        loaded = Session.load(session.id)
        assert len(loaded.turns) == 1

        # Assistant decides to use a tool (2 content blocks = 2 turns)
        tool_use = ToolUseBlock(id="tool_1", name="Glob", input={"pattern": "*.yaml"})
        session.add_message(
            "assistant",
            "",
            content_blocks=[TextBlock(text="I'll search for config files."), tool_use]
        )
        session.save()

        # Verify after tool call is saved (1 + 2 = 3 turns)
        loaded = Session.load(session.id)
        assert len(loaded.turns) == 3

        # Tool result comes back (1 turn)
        tool_result = ToolResultBlock(tool_use_id="tool_1", content="config.yaml")
        session.add_message("user", "", content_blocks=[tool_result])
        session.save()

        # Verify after tool result is saved (3 + 1 = 4 turns)
        loaded = Session.load(session.id)
        assert len(loaded.turns) == 4

        # Assistant continues with another tool (2 content blocks = 2 turns)
        tool_use_2 = ToolUseBlock(id="tool_2", name="Read", input={"file_path": "config.yaml"})
        session.add_message(
            "assistant",
            "",
            content_blocks=[TextBlock(text="Found it, reading now."), tool_use_2]
        )
        session.save()

        # Final verification (4 + 2 = 6 turns)
        loaded = Session.load(session.id)
        assert len(loaded.turns) == 6

    def test_long_agent_loop_crash_midway(self, temp_sessions_dir):
        """Simulate a long agent loop where we crash midway.

        This is the bug scenario: if saves only happen at the end,
        we could lose many turns of work.
        """
        session = Session()
        session.save()

        # Simulate 10 turns in an agent loop
        saved_turn_count = 0
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            session.add_message(role, f"Turn {i}")

            # With progressive saving, we save after each turn
            session.save()
            saved_turn_count += 1

            # Simulate crash at turn 5
            if i == 5:
                break

        # Load from disk
        recovered = Session.load(session.id)

        # All 6 turns (0-5) should be recovered
        assert len(recovered.turns) == 6
        for i in range(6):
            assert recovered.turns[i].content == f"Turn {i}"

    def test_usage_updates_persisted(self, temp_sessions_dir):
        """Token usage should be saved with each turn."""
        session = Session()
        session.save()

        session.add_message("user", "Hello")
        session.update_usage(input_tokens=100, output_tokens=0, cost=0.001)
        session.save()

        session.add_message("assistant", "Hi there")
        session.update_usage(input_tokens=0, output_tokens=50, cost=0.002)
        session.save()

        loaded = Session.load(session.id)
        assert loaded.total_input_tokens == 100
        assert loaded.total_output_tokens == 50
        assert loaded.total_cost == pytest.approx(0.003)


class TestSessionSaveAtomicity:
    """Tests for atomic save operations."""

    @pytest.fixture
    def temp_sessions_dir(self, tmp_path):
        """Use a temporary directory for sessions."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        index_file = sessions_dir / "index.json"
        with patch("session.SESSIONS_DIR", sessions_dir), \
             patch("session.INDEX_FILE", index_file):
            SessionIndex._instance = None
            yield sessions_dir
            SessionIndex._instance = None

    def test_save_writes_valid_json(self, temp_sessions_dir):
        """Save should always produce valid JSON."""
        session = Session()
        session.add_message("user", "Test message with 'quotes' and \"escapes\"")
        session.add_message("assistant", "Response with\nnewlines\tand tabs")
        session.save()

        # Read raw file and verify it's valid JSON
        path = temp_sessions_dir / f"{session.id}.json"
        raw_content = path.read_text()
        data = json.loads(raw_content)  # Should not raise

        assert data["id"] == session.id
        assert len(data["turns"]) == 2
        assert data["messages"] == []  # Messages are truncated

    def test_last_modified_updated_on_each_save(self, temp_sessions_dir):
        """Each save should update last_modified timestamp."""
        session = Session()
        session.save()
        first_modified = session.last_modified

        import time
        time.sleep(0.01)  # Small delay to ensure timestamp changes

        session.add_message("user", "New message")
        session.save()
        second_modified = session.last_modified

        assert second_modified > first_modified


class TestSessionDeleteTurns:
    """Tests for delete_turn and delete_turns methods."""

    def test_delete_turn_valid_index(self):
        """delete_turn should remove turn at valid index."""
        session = Session()
        session.add_message("user", "Turn 0")
        session.add_message("assistant", "Turn 1")
        session.add_message("user", "Turn 2")

        result = session.delete_turn(1)

        assert result is True
        assert len(session.turns) == 2
        assert session.turns[0].content == "Turn 0"
        assert session.turns[1].content == "Turn 2"

    def test_delete_turn_invalid_index(self):
        """delete_turn should return False for invalid index."""
        session = Session()
        session.add_message("user", "Only turn")

        assert session.delete_turn(-1) is False
        assert session.delete_turn(1) is False
        assert session.delete_turn(100) is False
        assert len(session.turns) == 1

    def test_delete_turns_multiple(self):
        """delete_turns should remove multiple turns in one call."""
        session = Session()
        for i in range(5):
            session.add_message("user" if i % 2 == 0 else "assistant", f"Turn {i}")

        # Delete turns 1, 2, 3 (indices don't matter if done in reverse order internally)
        deleted = session.delete_turns([1, 2, 3])

        assert deleted == 3
        assert len(session.turns) == 2
        assert session.turns[0].content == "Turn 0"
        assert session.turns[1].content == "Turn 4"

    def test_delete_turns_reverse_order(self):
        """delete_turns should handle indices correctly regardless of order."""
        session = Session()
        for i in range(5):
            session.add_message("user", f"Turn {i}")

        # Pass indices in random order
        deleted = session.delete_turns([3, 1, 4])

        assert deleted == 3
        assert len(session.turns) == 2
        assert session.turns[0].content == "Turn 0"
        assert session.turns[1].content == "Turn 2"

    def test_delete_turns_with_invalid_indices(self):
        """delete_turns should skip invalid indices."""
        session = Session()
        session.add_message("user", "Turn 0")
        session.add_message("assistant", "Turn 1")

        # Mix of valid and invalid indices
        deleted = session.delete_turns([0, 100, -1])

        assert deleted == 1
        assert len(session.turns) == 1
        assert session.turns[0].content == "Turn 1"

    def test_delete_turns_empty_list(self):
        """delete_turns with empty list should do nothing."""
        session = Session()
        session.add_message("user", "Turn 0")

        deleted = session.delete_turns([])

        assert deleted == 0
        assert len(session.turns) == 1

    def test_delete_turns_duplicates(self):
        """delete_turns should handle duplicate indices."""
        session = Session()
        for i in range(3):
            session.add_message("user", f"Turn {i}")

        # Duplicate index 1
        deleted = session.delete_turns([1, 1, 1])

        assert deleted == 1  # Only deleted once
        assert len(session.turns) == 2


class TestSessionArchive:
    """Tests for session archive/rehydrate methods."""

    @pytest.fixture
    def temp_sessions_dir(self, tmp_path):
        """Use a temporary directory for sessions."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        index_file = sessions_dir / "index.json"
        with patch("session.SESSIONS_DIR", sessions_dir), \
             patch("session.INDEX_FILE", index_file):
            SessionIndex._instance = None
            yield sessions_dir
            SessionIndex._instance = None

    @pytest.fixture
    def temp_archives_dir(self, tmp_path):
        """Use a temporary directory for archives."""
        archives_dir = tmp_path / "archives"
        archives_dir.mkdir()
        with patch("core.archiver.ARCHIVES_DIR", archives_dir):
            yield archives_dir

    def test_archive_turns_modifies_session(self, temp_sessions_dir, temp_archives_dir):
        """archive_turns replaces turns with archive marker."""
        session = Session()
        session.add_message("user", "Message 1")
        session.add_message("assistant", "Message 2")
        session.add_message("user", "Message 3")
        session.add_message("assistant", "Message 4")
        session.add_message("user", "Message 5")
        session.save()

        # Archive turns 1-4
        archive_block = session.archive_turns(1, 4, "Middle messages archived")

        # Should have 3 turns now: turn 0, archive marker, turn 4
        assert len(session.turns) == 3
        assert session.turns[0].content == "Message 1"
        assert session.turns[2].content == "Message 5"
        assert archive_block.message_count == 3

    def test_archive_persists_after_save(self, temp_sessions_dir, temp_archives_dir):
        """Archived session can be saved and loaded."""
        session = Session()
        session.add_message("user", "Message 1")
        session.add_message("assistant", "Message 2")
        session.add_message("user", "Message 3")
        session.save()

        # Archive and save
        session.archive_turns(1, 2, "Archived message 2")
        session.save()

        # Load and verify
        loaded = Session.load(session.id)
        assert len(loaded.turns) == 3
        assert loaded.has_archives()

    def test_rehydrate_restores_turns(self, temp_sessions_dir, temp_archives_dir):
        """rehydrate_archive restores original turns."""
        session = Session()
        session.add_message("user", "Message 1")
        session.add_message("assistant", "Message 2")
        session.add_message("user", "Message 3")
        session.save()

        # Archive
        session.archive_turns(0, 2, "First two turns")
        assert len(session.turns) == 2  # archive marker + turn 3

        # Rehydrate
        count = session.rehydrate_archive(0)
        assert count == 2
        assert len(session.turns) == 3
        assert session.turns[0].content == "Message 1"

    def test_archive_rehydrate_round_trip_with_persistence(self, temp_sessions_dir, temp_archives_dir):
        """Archive, save, load, rehydrate works correctly."""
        # Create and archive
        session = Session()
        session.add_message("user", "Question")
        session.add_message("assistant", "Answer")
        session.add_message("user", "Follow up")
        session.save()

        session.archive_turns(0, 2, "Q&A")
        session.save()

        # Load fresh
        loaded = Session.load(session.id)
        assert loaded.has_archives()
        assert len(loaded.turns) == 2

        # Rehydrate
        loaded.rehydrate_archive(0)
        assert len(loaded.turns) == 3
        assert loaded.turns[0].content == "Question"
        assert loaded.turns[1].content == "Answer"

    def test_get_all_archives(self, temp_sessions_dir, temp_archives_dir):
        """get_all_archives returns all archive blocks with indices."""
        session = Session()
        for i in range(10):
            session.add_message("user" if i % 2 == 0 else "assistant", f"Msg {i}")
        session.save()

        # Create two archives
        session.archive_turns(0, 3, "First archive")
        session.archive_turns(3, 6, "Second archive")  # indices shifted

        archives = session.get_all_archives()
        assert len(archives) == 2
        assert archives[0][1].summary == "First archive"
        assert archives[1][1].summary == "Second archive"

    def test_has_archives(self, temp_sessions_dir, temp_archives_dir):
        """has_archives returns correct boolean."""
        session = Session()
        session.add_message("user", "Test")
        session.add_message("assistant", "Reply")
        session.save()

        assert not session.has_archives()

        session.archive_turns(0, 1, "Archived")
        assert session.has_archives()


class TestSessionLoadBackwardsCompat:
    """Tests for loading old session formats."""

    @pytest.fixture
    def temp_sessions_dir(self, tmp_path):
        """Use a temporary directory for sessions."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        index_file = sessions_dir / "index.json"
        with patch("session.SESSIONS_DIR", sessions_dir), \
             patch("session.INDEX_FILE", index_file):
            SessionIndex._instance = None
            yield sessions_dir
            SessionIndex._instance = None

    def test_load_session_without_content_blocks(self, temp_sessions_dir):
        """Old sessions without content_blocks should still load and migrate to turns."""
        # Write an old-format session directly
        old_session_data = {
            "id": "old-session-123",
            "created": "2024-01-01T00:00:00",
            "model": "claude-3",
            "messages": [
                {"role": "user", "content": "Hello", "tokens": 10},
                {"role": "assistant", "content": "Hi", "tokens": 5},
            ],
            "total_input_tokens": 10,
            "total_output_tokens": 5,
            "total_cost": 0.0,
        }

        path = temp_sessions_dir / "old-session-123.json"
        path.write_text(json.dumps(old_session_data))

        # Load and verify - should migrate to turns
        loaded = Session.load("old-session-123")
        assert loaded is not None
        assert len(loaded.turns) == 2
        # Content should be converted to TextBlock
        assert isinstance(loaded.turns[0].content_block, TextBlock)
        assert loaded.turns[0].content_block.text == "Hello"
        assert loaded.turns[0].content == "Hello"  # Via property


class TestAsyncSessionIO:
    """Tests for async session I/O methods."""

    @pytest.fixture
    def temp_sessions_dir(self, tmp_path):
        """Use a temporary directory for sessions."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        index_file = sessions_dir / "index.json"
        with patch("session.SESSIONS_DIR", sessions_dir), \
             patch("session.INDEX_FILE", index_file):
            # Reset the singleton for each test
            SessionIndex._instance = None
            yield sessions_dir
            SessionIndex._instance = None

    @pytest.mark.asyncio
    async def test_save_async(self, temp_sessions_dir):
        """Test async session save."""
        session = Session()
        session.add_message("user", "Hello async")
        session.add_message("assistant", "Hi there")
        await session.save_async()

        # Verify file was written
        path = temp_sessions_dir / f"{session.id}.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data["turns"]) == 2

    @pytest.mark.asyncio
    async def test_load_async(self, temp_sessions_dir):
        """Test async session load."""
        # Create session with sync save
        session = Session()
        session.add_message("user", "Test message")
        session.save()

        # Load with async
        loaded = await Session.load_async(session.id)
        assert loaded is not None
        assert len(loaded.turns) == 1
        assert loaded.turns[0].content == "Test message"

    @pytest.mark.asyncio
    async def test_load_async_nonexistent(self, temp_sessions_dir):
        """Test async load of nonexistent session returns None."""
        loaded = await Session.load_async("nonexistent-id")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_save_async_load_async_roundtrip(self, temp_sessions_dir):
        """Test async save and load roundtrip."""
        session = Session()
        session.add_message("user", "Question")
        session.add_message("assistant", "Answer")
        session.update_usage(input_tokens=100, output_tokens=50, cost=0.001)
        await session.save_async()

        loaded = await Session.load_async(session.id)
        assert loaded is not None
        assert len(loaded.turns) == 2
        assert loaded.total_input_tokens == 100
        assert loaded.total_output_tokens == 50

    @pytest.mark.asyncio
    async def test_list_sessions_async(self, temp_sessions_dir):
        """Test async session listing."""
        # Create a few sessions
        for i in range(3):
            session = Session()
            session.add_message("user", f"Session {i}")
            await session.save_async()

        # List sessions
        sessions = []
        async for metadata in Session.list_sessions_async():
            sessions.append(metadata)

        assert len(sessions) == 3

    @pytest.mark.asyncio
    async def test_index_async_operations(self, temp_sessions_dir):
        """Test async index load/save operations."""
        index = SessionIndex()
        await index.ensure_loaded_async()

        # Create a session
        session = Session()
        session.add_message("user", "Test")
        await session.save_async()

        # Verify index was updated
        metadata = index.get(session.id)
        assert metadata is not None
        assert metadata["turn_count"] == 1

    @pytest.mark.asyncio
    async def test_concurrent_saves(self, temp_sessions_dir):
        """Test multiple concurrent async saves."""
        sessions = [Session() for _ in range(5)]
        for i, session in enumerate(sessions):
            session.add_message("user", f"Message {i}")

        # Save all concurrently
        await asyncio.gather(*[s.save_async() for s in sessions])

        # Verify all were saved
        for session in sessions:
            path = temp_sessions_dir / f"{session.id}.json"
            assert path.exists()


class TestMessageQueue:
    """Tests for the MessageQueue with pause/blocked functionality."""

    def test_add_and_pop(self):
        """Test basic add and pop operations."""
        queue = MessageQueue()
        m1 = queue.add("First")
        m2 = queue.add("Second")

        assert len(queue) == 2
        popped = queue.pop()
        assert popped.content == "First"
        assert len(queue) == 1

    def test_paused_field_default(self):
        """Test that messages start unpaused."""
        queue = MessageQueue()
        msg = queue.add("Test message")
        assert msg.paused is False

    def test_toggle_pause(self):
        """Test toggling pause state."""
        queue = MessageQueue()
        msg = queue.add("Test message")

        # Toggle on
        result = queue.toggle_pause(msg.id)
        assert result is True
        assert msg.paused is True

        # Toggle off
        result = queue.toggle_pause(msg.id)
        assert result is False
        assert msg.paused is False

    def test_toggle_pause_nonexistent(self):
        """Test toggle on nonexistent message returns False."""
        queue = MessageQueue()
        result = queue.toggle_pause("nonexistent-id")
        assert result is False

    def test_is_blocked(self):
        """Test is_blocked when first message is paused."""
        queue = MessageQueue()
        m1 = queue.add("First")
        m2 = queue.add("Second")

        # Not blocked initially
        assert queue.is_blocked() is False

        # Pausing second doesn't block (first is still active)
        queue.toggle_pause(m2.id)
        assert queue.is_blocked() is False

        # Pausing first blocks the queue
        queue.toggle_pause(m1.id)
        assert queue.is_blocked() is True

    def test_first_pause_index(self):
        """Test finding first paused message index."""
        queue = MessageQueue()
        m1 = queue.add("First")
        m2 = queue.add("Second")
        m3 = queue.add("Third")

        # No paused messages
        assert queue.first_pause_index() == -1

        # Pause second
        queue.toggle_pause(m2.id)
        assert queue.first_pause_index() == 1

        # Pause first - should return 0 now
        queue.toggle_pause(m1.id)
        assert queue.first_pause_index() == 0

    def test_get(self):
        """Test get message by ID."""
        queue = MessageQueue()
        m1 = queue.add("First")
        m2 = queue.add("Second")

        found = queue.get(m1.id)
        assert found is m1
        assert found.content == "First"

        not_found = queue.get("nonexistent-id")
        assert not_found is None

    def test_update_content(self):
        """Test updating message content."""
        queue = MessageQueue()
        msg = queue.add("Original content")

        result = queue.update_content(msg.id, "Updated content")
        assert result is True
        assert msg.content == "Updated content"

        # Verify via get
        found = queue.get(msg.id)
        assert found.content == "Updated content"

    def test_update_content_nonexistent(self):
        """Test update on nonexistent message returns False."""
        queue = MessageQueue()
        result = queue.update_content("nonexistent-id", "New content")
        assert result is False

    def test_serialization_with_pause(self):
        """Test that paused state serializes and deserializes."""
        queue = MessageQueue()
        m1 = queue.add("First")
        m2 = queue.add("Second")

        # Pause first message
        queue.toggle_pause(m1.id)

        # Serialize
        data = queue.to_dict()
        assert data["messages"][0]["paused"] is True
        assert data["messages"][1]["paused"] is False

        # Deserialize
        loaded = MessageQueue.from_dict(data)
        assert loaded.messages[0].paused is True
        assert loaded.messages[1].paused is False
        assert loaded.is_blocked() is True

    def test_drain_respects_pause(self):
        """Test that draining stops at paused messages."""
        queue = MessageQueue()
        m1 = queue.add("First")
        m2 = queue.add("Second")
        m3 = queue.add("Third")

        # Pause second message - first should drain, second and third should stay
        queue.toggle_pause(m2.id)

        # Simulate drain logic: pop until we hit paused
        drained = []
        while queue:
            next_msg = queue.peek()
            if next_msg and next_msg.paused:
                break
            msg = queue.pop()
            if msg:
                drained.append(msg.content)

        # Should have drained only first message
        assert drained == ["First"]
        # Queue should still have 2 messages
        assert len(queue) == 2
        # First remaining should be the paused one
        assert queue.peek().content == "Second"
        assert queue.peek().paused is True
