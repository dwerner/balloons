"""Tests for session persistence and progressive saving."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from session import Session, SESSIONS_DIR
from models import Message, TextBlock, ToolUseBlock, ToolResultBlock


class TestSessionProgressiveSaving:
    """Tests demonstrating that sessions should save after each turn."""

    @pytest.fixture
    def temp_sessions_dir(self, tmp_path):
        """Use a temporary directory for sessions."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        with patch("session.SESSIONS_DIR", sessions_dir):
            yield sessions_dir

    def test_session_save_persists_messages(self, temp_sessions_dir):
        """Basic test: saved session can be loaded."""
        session = Session()
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there")
        session.save()

        # Load and verify
        loaded = Session.load(session.id)
        assert loaded is not None
        assert len(loaded.messages) == 2
        assert loaded.messages[0].content == "Hello"
        assert loaded.messages[1].content == "Hi there"

    def test_progressive_save_each_turn(self, temp_sessions_dir):
        """Each turn should be persisted immediately after being added.

        This demonstrates the EXPECTED behavior: if we crash after adding
        a message, that message should still be on disk.
        """
        session = Session()
        session.save()  # Initial save

        # Simulate an agentic loop where each turn should be saved
        turns = [
            ("user", "What files are in the current directory?"),
            ("assistant", "I'll check that for you."),
            ("assistant", "Here are the files: main.py, utils.py"),
        ]

        for role, content in turns:
            session.add_message(role, content)
            session.save()  # Progressive save after each turn

            # Verify the turn is on disk
            loaded = Session.load(session.id)
            assert len(loaded.messages) == len(session.messages)
            assert loaded.messages[-1].content == content

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
        assert len(recovered.messages) == 2
        assert recovered.messages[0].content == "Turn 1"
        assert recovered.messages[1].content == "Turn 2"

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

        # Assistant decides to use a tool
        tool_use = ToolUseBlock(id="tool_1", name="Glob", input={"pattern": "*.yaml"})
        session.add_message(
            "assistant",
            "",
            content_blocks=[TextBlock(text="I'll search for config files."), tool_use]
        )
        session.save()

        # Verify after tool call is saved
        loaded = Session.load(session.id)
        assert len(loaded.messages) == 2

        # Tool result comes back
        tool_result = ToolResultBlock(tool_use_id="tool_1", content="config.yaml")
        session.add_message("user", "", content_blocks=[tool_result])
        session.save()

        # Verify after tool result is saved
        loaded = Session.load(session.id)
        assert len(loaded.messages) == 3

        # Assistant continues with another tool
        tool_use_2 = ToolUseBlock(id="tool_2", name="Read", input={"file_path": "config.yaml"})
        session.add_message(
            "assistant",
            "",
            content_blocks=[TextBlock(text="Found it, reading now."), tool_use_2]
        )
        session.save()

        # Final verification
        loaded = Session.load(session.id)
        assert len(loaded.messages) == 4

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
        assert len(recovered.messages) == 6
        for i in range(6):
            assert recovered.messages[i].content == f"Turn {i}"

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
        with patch("session.SESSIONS_DIR", sessions_dir):
            yield sessions_dir

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
        assert len(data["messages"]) == 2

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


class TestSessionLoadBackwardsCompat:
    """Tests for loading old session formats."""

    @pytest.fixture
    def temp_sessions_dir(self, tmp_path):
        """Use a temporary directory for sessions."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        with patch("session.SESSIONS_DIR", sessions_dir):
            yield sessions_dir

    def test_load_session_without_content_blocks(self, temp_sessions_dir):
        """Old sessions without content_blocks should still load."""
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

        # Load and verify
        loaded = Session.load("old-session-123")
        assert loaded is not None
        assert len(loaded.messages) == 2
        # Content should be converted to TextBlock
        assert len(loaded.messages[0].content_blocks) == 1
        assert isinstance(loaded.messages[0].content_blocks[0], TextBlock)
        assert loaded.messages[0].content_blocks[0].text == "Hello"
