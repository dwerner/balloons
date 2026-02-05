"""Tests for the fork manager."""

import pytest
from unittest.mock import MagicMock, patch

from core.fork import (
    ForkManager,
    ForkResult,
    MergeResult,
    DeriveResult,
    SwitchResult,
    ForkProposal,
    MergeProposal,
    ContextAssignment,
)
from core.tool_executor import (
    execute_propose_merge,
    parse_merge_proposal,
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


class TestForkProposal:
    """Tests for ForkProposal context resolution."""

    def test_resolve_single_index(self):
        """Single index should resolve to one exchange."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="2", mode="copy"),
            ],
        )

        result = proposal.resolve_exchange_indices(5)

        assert result == {2: ContextMode.COPY}

    def test_resolve_range(self):
        """Range should resolve to multiple exchanges."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="0-2", mode="copy"),
            ],
        )

        result = proposal.resolve_exchange_indices(5)

        assert result == {
            0: ContextMode.COPY,
            1: ContextMode.COPY,
            2: ContextMode.COPY,
        }

    def test_resolve_last(self):
        """'last' should resolve to final exchange."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="last", mode="copy"),
            ],
        )

        result = proposal.resolve_exchange_indices(5)

        assert result == {4: ContextMode.COPY}

    def test_resolve_last_n(self):
        """'last-N' should resolve to last N+1 exchanges."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="last-2", mode="compress"),
            ],
        )

        result = proposal.resolve_exchange_indices(5)

        assert result == {
            2: ContextMode.COMPRESS,
            3: ContextMode.COMPRESS,
            4: ContextMode.COMPRESS,
        }

    def test_resolve_negative(self):
        """Negative index should resolve to last N exchanges."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="-2", mode="drop"),
            ],
        )

        result = proposal.resolve_exchange_indices(5)

        assert result == {
            3: ContextMode.DROP,
            4: ContextMode.DROP,
        }

    def test_resolve_all(self):
        """'all' should resolve to all exchanges."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="all", mode="compress"),
            ],
        )

        result = proposal.resolve_exchange_indices(3)

        assert result == {
            0: ContextMode.COMPRESS,
            1: ContextMode.COMPRESS,
            2: ContextMode.COMPRESS,
        }

    def test_resolve_multiple_assignments(self):
        """Multiple assignments should all be applied, later overriding earlier."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="all", mode="drop"),
                ContextAssignment(exchange_range="0", mode="copy"),
                ContextAssignment(exchange_range="last", mode="copy"),
            ],
        )

        result = proposal.resolve_exchange_indices(5)

        assert result == {
            0: ContextMode.COPY,
            1: ContextMode.DROP,
            2: ContextMode.DROP,
            3: ContextMode.DROP,
            4: ContextMode.COPY,
        }

    def test_resolve_out_of_range(self):
        """Out of range indices should be ignored."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="10", mode="copy"),
            ],
        )

        result = proposal.resolve_exchange_indices(5)

        assert result == {}

    def test_resolve_empty_session(self):
        """Empty session should return empty dict."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="all", mode="copy"),
            ],
        )

        result = proposal.resolve_exchange_indices(0)

        assert result == {}


class TestMergeProposal:
    """Tests for MergeProposal dataclass."""

    def test_create_minimal(self):
        """Minimal merge proposal with only summary."""
        proposal = MergeProposal(summary="Fixed the bug")
        assert proposal.summary == "Fixed the bug"
        assert proposal.reason == ""
        assert proposal.files_changed == []
        assert proposal.key_accomplishments == []

    def test_create_full(self):
        """Full merge proposal with all fields."""
        proposal = MergeProposal(
            summary="Implemented caching layer",
            reason="All tests pass",
            files_changed=["cache.py", "config.py"],
            key_accomplishments=["Added Redis client", "TTL support"],
        )
        assert proposal.summary == "Implemented caching layer"
        assert proposal.reason == "All tests pass"
        assert proposal.files_changed == ["cache.py", "config.py"]
        assert proposal.key_accomplishments == ["Added Redis client", "TTL support"]


class TestProposeMergeTool:
    """Tests for the propose_merge tool executor."""

    def test_execute_missing_summary(self):
        """Should error if summary is missing."""
        result, is_error = execute_propose_merge({})
        assert is_error
        assert "summary is required" in result

    def test_execute_empty_summary(self):
        """Should error if summary is empty."""
        result, is_error = execute_propose_merge({"summary": ""})
        assert is_error
        assert "summary is required" in result

    def test_execute_invalid_files_changed_type(self):
        """Should error if files_changed is not a list."""
        result, is_error = execute_propose_merge({
            "summary": "Test",
            "files_changed": "not-a-list",
        })
        assert is_error
        assert "files_changed must be a list" in result

    def test_execute_invalid_accomplishments_type(self):
        """Should error if key_accomplishments is not a list."""
        result, is_error = execute_propose_merge({
            "summary": "Test",
            "key_accomplishments": "not-a-list",
        })
        assert is_error
        assert "key_accomplishments must be a list" in result

    def test_execute_valid_minimal(self):
        """Valid minimal proposal should return pending."""
        result, is_error = execute_propose_merge({"summary": "Test summary"})
        assert not is_error
        assert result == "MERGE_PROPOSAL_PENDING"

    def test_execute_valid_full(self):
        """Valid full proposal should return pending."""
        result, is_error = execute_propose_merge({
            "summary": "Test summary",
            "reason": "Work is done",
            "files_changed": ["file1.py", "file2.py"],
            "key_accomplishments": ["Done thing 1", "Done thing 2"],
        })
        assert not is_error
        assert result == "MERGE_PROPOSAL_PENDING"


class TestParseMergeProposal:
    """Tests for parse_merge_proposal function."""

    def test_parse_minimal(self):
        """Parse minimal proposal."""
        proposal = parse_merge_proposal({"summary": "Test"})
        assert proposal is not None
        assert proposal.summary == "Test"
        assert proposal.reason == ""
        assert proposal.files_changed == []
        assert proposal.key_accomplishments == []

    def test_parse_full(self):
        """Parse full proposal."""
        proposal = parse_merge_proposal({
            "summary": "Implemented feature X",
            "reason": "Tests pass",
            "files_changed": ["a.py", "b.py"],
            "key_accomplishments": ["Added X", "Fixed Y"],
        })
        assert proposal is not None
        assert proposal.summary == "Implemented feature X"
        assert proposal.reason == "Tests pass"
        assert proposal.files_changed == ["a.py", "b.py"]
        assert proposal.key_accomplishments == ["Added X", "Fixed Y"]

    def test_parse_filters_empty_values(self):
        """Empty strings in lists should be filtered."""
        proposal = parse_merge_proposal({
            "summary": "Test",
            "files_changed": ["a.py", "", "b.py", None],
            "key_accomplishments": ["Done", "", None, "Also done"],
        })
        assert proposal is not None
        assert proposal.files_changed == ["a.py", "b.py"]
        assert proposal.key_accomplishments == ["Done", "Also done"]

    def test_parse_converts_to_strings(self):
        """Non-string values should be converted to strings."""
        proposal = parse_merge_proposal({
            "summary": "Test",
            "files_changed": [123, True],
            "key_accomplishments": [456],
        })
        assert proposal is not None
        assert proposal.files_changed == ["123", "True"]
        assert proposal.key_accomplishments == ["456"]

    def test_parse_empty_args(self):
        """Empty args should return proposal with empty summary."""
        proposal = parse_merge_proposal({})
        assert proposal is not None
        assert proposal.summary == ""
