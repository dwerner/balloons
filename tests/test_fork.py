"""Tests for the fork manager."""

import pytest
from unittest.mock import MagicMock, patch

from core.fork import (
    ForkManager,
    ForkResult,
    MergeResult,
    DeriveResult,
    SwitchResult,
)
from models import Message, TextBlock, ContextMode


class TestForkManager:
    """Tests for ForkManager."""

    def create_mock_session(self, **kwargs):
        """Create a mock session with default attributes."""
        session = MagicMock()
        session.id = kwargs.get("id", "test-session-123")
        session.turns = kwargs.get("turns", [])
        session.is_read_only = MagicMock(return_value=kwargs.get("read_only", False))
        session.is_fork = MagicMock(return_value=kwargs.get("is_fork", False))
        session.is_merged = MagicMock(return_value=kwargs.get("is_merged", False))
        session.get_parent = MagicMock(return_value=kwargs.get("parent", None))
        session.get_fork_display_name = MagicMock(return_value=kwargs.get("fork_name", "test-fork"))
        session.get_all_forks = MagicMock(return_value=kwargs.get("forks", []))
        session.add_child = MagicMock()
        session.add_message = MagicMock()
        session.save = MagicMock()
        session.mark_merged = MagicMock()
        session.mark_child_merged = MagicMock()
        return session

    def create_mock_context_builder(self):
        """Create a mock context builder."""
        builder = MagicMock()
        builder.build_context_summary_prompt = MagicMock(
            return_value="Please summarize this context..."
        )
        return builder

    def test_prepare_fork_read_only_session(self):
        """Fork from read-only session should fail."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        session = self.create_mock_session(read_only=True)

        result = manager.prepare_fork(
            current_session=session,
            indexed_messages=[],
            prompt="Do something",
            allowed_tools=["read", "write"],
        )

        assert not result.success
        assert "merged session" in result.error.lower()

    @patch("core.fork.Session")
    def test_prepare_fork_no_compression(self, mock_session_class):
        """Fork without compression should create child immediately."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123", messages=["msg1", "msg2"])
        child = self.create_mock_session(id="child-456")
        mock_session_class.return_value = child

        # Create messages that don't need compression (COPY mode)
        msg1 = Message(role="user", content="Hello", content_blocks=[TextBlock(text="Hello")], context_mode=ContextMode.COPY)
        msg2 = Message(role="assistant", content="Hi", content_blocks=[TextBlock(text="Hi")], context_mode=ContextMode.COPY)

        result = manager.prepare_fork(
            current_session=parent,
            indexed_messages=[(msg1, 0), (msg2, 1)],
            prompt="Continue this",
            allowed_tools=["read"],
            name="my-fork",
        )

        assert result.success
        assert not result.needs_compression
        assert result.child_session == child
        assert result.parent_session == parent
        assert result.prompt == "Continue this"
        assert result.name == "my-fork"

        # Verify child was saved
        child.save.assert_called()
        parent.save.assert_called()
        parent.add_child.assert_called_once()

    def test_prepare_merge_not_a_fork(self):
        """Merge from non-fork session should fail."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        session = self.create_mock_session(is_fork=False)

        result = manager.prepare_merge(session)

        assert not result.success
        assert "not in a fork" in result.error.lower()

    def test_prepare_merge_already_merged(self):
        """Merge from already-merged fork should fail."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        session = self.create_mock_session(is_fork=True, is_merged=True)

        result = manager.prepare_merge(session)

        assert not result.success
        assert "already merged" in result.error.lower()

    def test_prepare_merge_no_parent(self):
        """Merge when parent not found should fail."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        session = self.create_mock_session(is_fork=True, is_merged=False, parent=None)

        result = manager.prepare_merge(session)

        assert not result.success
        assert "parent" in result.error.lower()

    def test_prepare_merge_success(self):
        """Valid merge preparation should succeed."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123")
        fork = self.create_mock_session(
            id="fork-456",
            is_fork=True,
            is_merged=False,
            parent=parent,
            fork_name="feature-x",
        )

        result = manager.prepare_merge(fork)

        assert result.success
        assert result.fork_session == fork
        assert result.parent_session == parent
        assert result.fork_name == "feature-x"

    def test_complete_merge(self):
        """Complete merge should update sessions."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123", messages=["m1", "m2", "m3"])
        fork = self.create_mock_session(id="fork-456")

        result = manager.complete_merge(
            fork_session=fork,
            parent_session=parent,
            merge_message="Completed feature X",
        )

        assert result.success
        assert result.merge_message == "Completed feature X"

        fork.mark_merged.assert_called_once()
        fork.save.assert_called()
        parent.mark_child_merged.assert_called_once()
        parent.save.assert_called()

    @patch("core.fork.Session")
    def test_prepare_derive_no_compression(self, mock_session_class):
        """Derive without compression should create session immediately."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        new_session = self.create_mock_session(id="new-789")
        mock_session_class.return_value = new_session

        msg1 = Message(role="user", content="Query", content_blocks=[TextBlock(text="Query")], context_mode=ContextMode.COPY)

        result = manager.prepare_derive(
            indexed_messages=[(msg1, 0)],
            prompt="Start fresh",
            allowed_tools=["read", "write"],
        )

        assert result.success
        assert not result.needs_compression
        assert result.new_session == new_session
        assert result.prompt == "Start fresh"

        new_session.save.assert_called()

    def test_find_switch_target_empty_name(self):
        """Switch with empty name should return available forks."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        forks = [
            {"name": "fork-a", "session_id": "id-a"},
            {"name": "fork-b", "session_id": "id-b"},
        ]
        session = self.create_mock_session(forks=forks)

        result = manager.find_switch_target(session, "")

        assert not result.success  # No target selected
        assert result.available_forks == forks

    @patch("core.fork.Session")
    def test_find_switch_target_by_name(self, mock_session_class):
        """Switch by name should find matching fork."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        target = self.create_mock_session(id="id-a")
        mock_session_class.load = MagicMock(return_value=target)

        forks = [
            {"name": "fork-a", "session_id": "id-a"},
            {"name": "fork-b", "session_id": "id-b"},
        ]
        session = self.create_mock_session(forks=forks)

        result = manager.find_switch_target(session, "fork-a")

        assert result.success
        assert result.target_session == target
        mock_session_class.load.assert_called_with("id-a")

    @patch("core.fork.Session")
    def test_find_switch_target_by_id_prefix(self, mock_session_class):
        """Switch by ID prefix should find matching fork."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        target = self.create_mock_session(id="id-abc123")
        mock_session_class.load = MagicMock(return_value=target)

        forks = [{"name": "", "session_id": "id-abc123"}]
        session = self.create_mock_session(forks=forks)

        result = manager.find_switch_target(session, "id-abc")

        assert result.success
        assert result.target_session == target

    def test_find_switch_target_parent(self):
        """Switch to 'parent' should find parent session."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123")
        session = self.create_mock_session(is_fork=True, parent=parent)

        result = manager.find_switch_target(session, "parent")

        assert result.success
        assert result.target_session == parent

    def test_find_switch_target_not_found(self):
        """Switch to non-existent fork should fail."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        session = self.create_mock_session(forks=[])

        result = manager.find_switch_target(session, "nonexistent")

        assert not result.success
        assert "no fork found" in result.error.lower()
