"""Tests for the fork manager."""

import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

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
        session.get_parent_async = AsyncMock(return_value=kwargs.get("parent", None))
        session.get_fork_display_name = MagicMock(return_value=kwargs.get("fork_name", "test-fork"))
        session.get_all_forks = MagicMock(return_value=kwargs.get("forks", []))
        session.add_child = MagicMock()
        session.add_message = MagicMock()
        session.save = MagicMock()
        session.save = AsyncMock()
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

    @pytest.mark.asyncio
    async def test_prepare_fork_read_only_session(self):
        """Fork from read-only session should fail."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        session = self.create_mock_session(read_only=True)

        result = await manager.prepare_fork(
            current_session=session,
            indexed_messages=[],
            prompt="Do something",
            allowed_tools=["read", "write"],
        )

        assert not result.success
        assert "merged session" in result.error.lower()

    @pytest.mark.asyncio
    @patch("core.fork.Session")
    async def test_prepare_fork_no_compression(self, mock_session_class):
        """Fork without compression should create child immediately."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123", messages=["msg1", "msg2"])
        child = self.create_mock_session(id="child-456")
        mock_session_class.return_value = child

        # Create messages that don't need compression (COPY mode)
        msg1 = Message(role="user", content="Hello", content_blocks=[TextBlock(text="Hello")], context_mode=ContextMode.COPY)
        msg2 = Message(role="assistant", content="Hi", content_blocks=[TextBlock(text="Hi")], context_mode=ContextMode.COPY)

        result = await manager.prepare_fork(
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

        # Verify child was saved (async)
        child.save.assert_called()
        parent.save.assert_called()
        parent.add_child.assert_called_once()

    @pytest.mark.asyncio
    async def test_prepare_merge_not_a_fork(self):
        """Merge from non-fork session should fail."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        session = self.create_mock_session(is_fork=False)

        result = await manager.prepare_merge(session)

        assert not result.success
        assert "not in a fork" in result.error.lower()

    @pytest.mark.asyncio
    async def test_prepare_merge_already_merged_allowed(self):
        """Merge from already-merged fork should succeed (re-merging is allowed)."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123")
        session = self.create_mock_session(
            is_fork=True,
            is_merged=True,
            parent=parent,
            fork_name="feature-x",
        )

        result = await manager.prepare_merge(session)

        # Re-merging should be allowed - forks can be merged multiple times
        assert result.success
        assert result.fork_session == session
        assert result.parent_session == parent

    @pytest.mark.asyncio
    async def test_prepare_merge_no_parent(self):
        """Merge when parent not found should fail."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        session = self.create_mock_session(is_fork=True, is_merged=False, parent=None)

        result = await manager.prepare_merge(session)

        assert not result.success
        assert "parent" in result.error.lower()

    @pytest.mark.asyncio
    async def test_prepare_merge_success(self):
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

        result = await manager.prepare_merge(fork)

        assert result.success
        assert result.fork_session == fork
        assert result.parent_session == parent
        assert result.fork_name == "feature-x"

    @pytest.mark.asyncio
    async def test_complete_merge(self):
        """Complete merge should update sessions."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123", messages=["m1", "m2", "m3"])
        fork = self.create_mock_session(id="fork-456")

        result = await manager.complete_merge(
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

    @pytest.mark.asyncio
    @patch("core.fork.Session")
    async def test_prepare_derive_no_compression(self, mock_session_class):
        """Derive without compression should create session immediately."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        new_session = self.create_mock_session(id="new-789")
        mock_session_class.return_value = new_session

        msg1 = Message(role="user", content="Query", content_blocks=[TextBlock(text="Query")], context_mode=ContextMode.COPY)

        result = await manager.prepare_derive(
            indexed_messages=[(msg1, 0)],
            prompt="Start fresh",
            allowed_tools=["read", "write"],
        )

        assert result.success
        assert not result.needs_compression
        assert result.new_session == new_session
        assert result.prompt == "Start fresh"

        new_session.save.assert_called()

    @pytest.mark.asyncio
    async def test_find_switch_target_empty_name(self):
        """Switch with empty name should return available forks."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        forks = [
            {"name": "fork-a", "session_id": "id-a"},
            {"name": "fork-b", "session_id": "id-b"},
        ]
        session = self.create_mock_session(forks=forks)

        result = await manager.find_switch_target(session, "")

        assert not result.success  # No target selected
        assert result.available_forks == forks

    @pytest.mark.asyncio
    @patch("core.fork.Session")
    async def test_find_switch_target_by_name(self, mock_session_class):
        """Switch by name should find matching fork."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        target = self.create_mock_session(id="id-a")
        mock_session_class.load = AsyncMock(return_value=target)

        forks = [
            {"name": "fork-a", "session_id": "id-a"},
            {"name": "fork-b", "session_id": "id-b"},
        ]
        session = self.create_mock_session(forks=forks)

        result = await manager.find_switch_target(session, "fork-a")

        assert result.success
        assert result.target_session == target
        mock_session_class.load.assert_called_with("id-a")

    @pytest.mark.asyncio
    @patch("core.fork.Session")
    async def test_find_switch_target_by_id_prefix(self, mock_session_class):
        """Switch by ID prefix should find matching fork."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        target = self.create_mock_session(id="id-abc123")
        mock_session_class.load = AsyncMock(return_value=target)

        forks = [{"name": "", "session_id": "id-abc123"}]
        session = self.create_mock_session(forks=forks)

        result = await manager.find_switch_target(session, "id-abc")

        assert result.success
        assert result.target_session == target

    @pytest.mark.asyncio
    async def test_find_switch_target_parent(self):
        """Switch to 'parent' should find parent session."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123")
        session = self.create_mock_session(is_fork=True, parent=parent)

        result = await manager.find_switch_target(session, "parent")

        assert result.success
        assert result.target_session == parent

    @pytest.mark.asyncio
    async def test_find_switch_target_not_found(self):
        """Switch to non-existent fork should fail."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        session = self.create_mock_session(forks=[])

        result = await manager.find_switch_target(session, "nonexistent")

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

    def test_resolve_last_exclude_current(self):
        """'last' with exclude_current should resolve to second-to-last exchange.

        This is the fix for the timing issue where Claude proposes a fork during
        the current exchange, so 'last' should mean the exchange before Claude's
        response, not the exchange containing the proposal itself.
        """
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="last", mode="copy"),
            ],
        )

        # 5 exchanges total, but current (proposal) exchange is excluded
        # So "last" resolves against 4 exchanges, giving index 3
        result = proposal.resolve_exchange_indices(5, exclude_current=True)

        assert result == {3: ContextMode.COPY}

    def test_resolve_last_n_exclude_current(self):
        """'last-2' with exclude_current should exclude current exchange."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="last-2", mode="compress"),
            ],
        )

        # 5 exchanges, exclude current -> effective 4 exchanges
        # "last-2" means last 3 exchanges: indices 1, 2, 3
        result = proposal.resolve_exchange_indices(5, exclude_current=True)

        assert result == {
            1: ContextMode.COMPRESS,
            2: ContextMode.COMPRESS,
            3: ContextMode.COMPRESS,
        }

    def test_resolve_all_exclude_current(self):
        """'all' with exclude_current should exclude current exchange."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="all", mode="copy"),
            ],
        )

        # 5 exchanges, exclude current -> copies exchanges 0-3 (not 4)
        result = proposal.resolve_exchange_indices(5, exclude_current=True)

        assert result == {
            0: ContextMode.COPY,
            1: ContextMode.COPY,
            2: ContextMode.COPY,
            3: ContextMode.COPY,
        }

    def test_resolve_absolute_index_unaffected_by_exclude_current(self):
        """Absolute indices like '0' should not be affected by exclude_current."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="0", mode="copy"),
            ],
        )

        # Absolute index 0 should work the same regardless of exclude_current
        result = proposal.resolve_exchange_indices(5, exclude_current=True)

        assert result == {0: ContextMode.COPY}

    def test_resolve_range_unaffected_by_exclude_current(self):
        """Absolute ranges like '1-3' should not be affected by exclude_current."""
        proposal = ForkProposal(
            name="test",
            description="test",
            context_plan=[
                ContextAssignment(exchange_range="1-3", mode="compress"),
            ],
        )

        # Range 1-3 should work the same regardless of exclude_current
        result = proposal.resolve_exchange_indices(5, exclude_current=True)

        assert result == {
            1: ContextMode.COMPRESS,
            2: ContextMode.COMPRESS,
            3: ContextMode.COMPRESS,
        }


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


class TestContextGrouper:
    """Tests for group_messages_by_context_mode function."""

    def test_empty_list(self):
        """Empty input should return empty groups."""
        from core.context_grouper import group_messages_by_context_mode

        result = group_messages_by_context_mode([])

        assert result.copy_items == []
        assert result.compress_groups == []
        assert not result.needs_compression

    def test_all_copy_messages(self):
        """All COPY messages should go to copy_items, no compression needed."""
        from core.context_grouper import group_messages_by_context_mode

        msg1 = Message(role="user", content="Hello", context_mode=ContextMode.COPY)
        msg2 = Message(role="assistant", content="Hi", context_mode=ContextMode.COPY)

        result = group_messages_by_context_mode([(msg1, 0), (msg2, 1)])

        assert len(result.copy_items) == 2
        assert result.compress_groups == []
        assert not result.needs_compression

    def test_all_compress_messages(self):
        """All COMPRESS messages should form one group."""
        from core.context_grouper import group_messages_by_context_mode

        msg1 = Message(role="user", content="Hello", context_mode=ContextMode.COMPRESS)
        msg2 = Message(role="assistant", content="Hi", context_mode=ContextMode.COMPRESS)

        result = group_messages_by_context_mode([(msg1, 0), (msg2, 1)])

        assert result.copy_items == []
        assert len(result.compress_groups) == 1
        assert len(result.compress_groups[0]) == 2
        assert result.needs_compression

    def test_drop_messages_excluded(self):
        """DROP messages should be completely excluded."""
        from core.context_grouper import group_messages_by_context_mode

        msg1 = Message(role="user", content="Hello", context_mode=ContextMode.COPY)
        msg2 = Message(role="assistant", content="Secret", context_mode=ContextMode.DROP)
        msg3 = Message(role="user", content="Bye", context_mode=ContextMode.COPY)

        result = group_messages_by_context_mode([(msg1, 0), (msg2, 1), (msg3, 2)])

        assert len(result.copy_items) == 2
        assert result.compress_groups == []
        # Only indices 0 and 2, not 1
        indices = [idx for _, idx in result.copy_items]
        assert 1 not in indices

    def test_mixed_copy_compress_creates_separate_groups(self):
        """COPY message between COMPRESS messages creates separate groups."""
        from core.context_grouper import group_messages_by_context_mode

        msg1 = Message(role="user", content="Q1", context_mode=ContextMode.COMPRESS)
        msg2 = Message(role="assistant", content="A1", context_mode=ContextMode.COMPRESS)
        msg3 = Message(role="user", content="Important", context_mode=ContextMode.COPY)
        msg4 = Message(role="assistant", content="Q2", context_mode=ContextMode.COMPRESS)
        msg5 = Message(role="user", content="A2", context_mode=ContextMode.COMPRESS)

        result = group_messages_by_context_mode([
            (msg1, 0), (msg2, 1), (msg3, 2), (msg4, 3), (msg5, 4)
        ])

        # Should have 1 copy item and 2 compress groups
        assert len(result.copy_items) == 1
        assert len(result.compress_groups) == 2
        # First group: indices 0, 1
        assert len(result.compress_groups[0]) == 2
        # Second group: indices 3, 4
        assert len(result.compress_groups[1]) == 2
        assert result.needs_compression

    def test_compress_group_positions(self):
        """compress_group_positions should return first index of each group."""
        from core.context_grouper import group_messages_by_context_mode

        msg1 = Message(role="user", content="Q1", context_mode=ContextMode.COMPRESS)
        msg2 = Message(role="assistant", content="A1", context_mode=ContextMode.COMPRESS)
        msg3 = Message(role="user", content="Important", context_mode=ContextMode.COPY)
        msg4 = Message(role="assistant", content="Q2", context_mode=ContextMode.COMPRESS)

        result = group_messages_by_context_mode([
            (msg1, 0), (msg2, 1), (msg3, 2), (msg4, 3)
        ])

        # First group starts at 0, second at 3
        assert result.compress_group_positions == [0, 3]

    def test_summarize_mode_treated_as_compress(self):
        """SUMMARIZE mode (legacy alias) should be treated as COMPRESS."""
        from core.context_grouper import group_messages_by_context_mode

        msg1 = Message(role="user", content="Hello", context_mode=ContextMode.SUMMARIZE)

        result = group_messages_by_context_mode([(msg1, 0)])

        assert len(result.compress_groups) == 1
        assert result.needs_compression

    def test_out_of_order_indices_sorted(self):
        """Messages passed out of order should be sorted by index."""
        from core.context_grouper import group_messages_by_context_mode

        msg1 = Message(role="user", content="First", context_mode=ContextMode.COMPRESS)
        msg2 = Message(role="assistant", content="Second", context_mode=ContextMode.COMPRESS)
        msg3 = Message(role="user", content="Third", context_mode=ContextMode.COMPRESS)

        # Pass out of order
        result = group_messages_by_context_mode([
            (msg3, 2), (msg1, 0), (msg2, 1)
        ])

        # Should all be in one group, sorted
        assert len(result.compress_groups) == 1
        group = result.compress_groups[0]
        indices = [idx for _, idx in group]
        assert indices == [0, 1, 2]


# TestTreeStateContextModeForFork removed - TreeState deleted in Phase 8


class TestPrepareForkWithCompression:
    """Tests for ForkManager.prepare_fork when compression is needed."""

    def create_mock_session(self, **kwargs):
        """Create a mock session with default attributes."""
        session = MagicMock()
        session.id = kwargs.get("id", "test-session-123")
        session.turns = kwargs.get("turns", [])
        session.is_read_only = MagicMock(return_value=kwargs.get("read_only", False))
        session.is_fork = MagicMock(return_value=kwargs.get("is_fork", False))
        session.is_merged = MagicMock(return_value=kwargs.get("is_merged", False))
        session.get_parent = MagicMock(return_value=kwargs.get("parent", None))
        session.get_parent_async = AsyncMock(return_value=kwargs.get("parent", None))
        session.get_fork_display_name = MagicMock(return_value=kwargs.get("fork_name", "test-fork"))
        session.get_all_forks = MagicMock(return_value=kwargs.get("forks", []))
        session.add_child = MagicMock()
        session.add_message = MagicMock()
        session.add_fork_turn = MagicMock()
        session.get_last_exchange_id = MagicMock(return_value="ex-123")
        session.save = AsyncMock()
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

    @pytest.mark.asyncio
    @patch("core.fork.Session")
    @patch("core.fork.copy_session_bindings")
    async def test_prepare_fork_with_compress_messages(self, mock_copy_bindings, mock_session_class):
        """Fork with COMPRESS messages should return needs_compression=True."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123")
        child = self.create_mock_session(id="child-456")
        mock_session_class.return_value = child
        mock_copy_bindings.return_value = 0

        # Create messages with COMPRESS mode
        msg1 = Message(
            role="user",
            content="Old context",
            content_blocks=[TextBlock(text="Old context")],
            context_mode=ContextMode.COMPRESS,
        )
        msg2 = Message(
            role="assistant",
            content="Old response",
            content_blocks=[TextBlock(text="Old response")],
            context_mode=ContextMode.COMPRESS,
        )

        result = await manager.prepare_fork(
            current_session=parent,
            indexed_messages=[(msg1, 0), (msg2, 1)],
            prompt="Continue",
            allowed_tools=["read"],
            name="test-fork",
        )

        assert result.success
        assert result.needs_compression
        assert result.compression_prompt is not None
        assert result.helper_id is not None
        assert result.fork_data is not None
        context_builder.build_context_summary_prompt.assert_called_once()

    @pytest.mark.asyncio
    @patch("core.fork.Session")
    @patch("core.fork.copy_session_bindings")
    async def test_prepare_fork_mixed_copy_and_compress(self, mock_copy_bindings, mock_session_class):
        """Fork with mixed COPY and COMPRESS should need compression."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123")
        child = self.create_mock_session(id="child-456")
        mock_session_class.return_value = child
        mock_copy_bindings.return_value = 0

        msg1 = Message(
            role="user",
            content="Requirements",
            content_blocks=[TextBlock(text="Requirements")],
            context_mode=ContextMode.COPY,  # Keep verbatim
        )
        msg2 = Message(
            role="assistant",
            content="Background",
            content_blocks=[TextBlock(text="Background")],
            context_mode=ContextMode.COMPRESS,  # Summarize
        )

        result = await manager.prepare_fork(
            current_session=parent,
            indexed_messages=[(msg1, 0), (msg2, 1)],
            prompt="Continue",
            allowed_tools=["read"],
        )

        assert result.success
        assert result.needs_compression
        # Fork data should separate copy and compress items
        assert result.fork_data is not None
        assert len(result.fork_data.copy_items) == 1
        assert len(result.fork_data.compress_group_positions) == 1

    @pytest.mark.asyncio
    @patch("core.fork.Session")
    @patch("core.fork.copy_session_bindings")
    async def test_prepare_fork_all_drop_returns_empty(self, mock_copy_bindings, mock_session_class):
        """Fork with all DROP messages should not need compression but have no content."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123")
        child = self.create_mock_session(id="child-456")
        mock_session_class.return_value = child
        mock_copy_bindings.return_value = 0

        msg1 = Message(
            role="user",
            content="Dropped",
            content_blocks=[TextBlock(text="Dropped")],
            context_mode=ContextMode.DROP,
        )

        result = await manager.prepare_fork(
            current_session=parent,
            indexed_messages=[(msg1, 0)],
            prompt="Continue",
            allowed_tools=["read"],
        )

        # Should succeed but no compression needed (nothing to compress)
        assert result.success
        assert not result.needs_compression


class TestForkProposalContextModeIntegration:
    """Integration tests for the full fork proposal context mode flow.

    These tests verify the end-to-end flow:
    1. ForkProposal.resolve_exchange_indices maps proposal to exchange indices
    2. Context modes are passed via context_modes parameter to fork_session
    3. group_messages_by_context_mode separates COPY/COMPRESS
    4. prepare_fork handles compression correctly
    """

    def test_full_flow_proposal_to_grouped_messages(self):
        """Test full flow from proposal to grouped messages."""
        from core.context_grouper import group_messages_by_context_mode

        # Step 1: Create a fork proposal with context plan
        proposal = ForkProposal(
            name="implement-feature",
            description="Implement the feature",
            context_plan=[
                ContextAssignment(exchange_range="0", mode="copy"),
                ContextAssignment(exchange_range="1-2", mode="compress"),
                ContextAssignment(exchange_range="last", mode="copy"),
            ],
        )

        # Step 2: Resolve to exchange indices (simulating 4 exchanges)
        exchange_modes = proposal.resolve_exchange_indices(4, exclude_current=False)

        # Verify resolution
        assert exchange_modes == {
            0: ContextMode.COPY,
            1: ContextMode.COMPRESS,
            2: ContextMode.COMPRESS,
            3: ContextMode.COPY,
        }

        # Step 3: Create messages with the resolved modes
        messages = []
        for exchange_idx in range(4):
            mode = exchange_modes.get(exchange_idx, ContextMode.DROP)
            # Two turns per exchange (user + assistant)
            for turn_offset, role in enumerate(["user", "assistant"]):
                turn_idx = exchange_idx * 2 + turn_offset
                msg = Message(
                    role=role,
                    content=f"Content {turn_idx}",
                    content_blocks=[TextBlock(text=f"Content {turn_idx}")],
                    context_mode=mode,
                )
                messages.append((msg, turn_idx))

        # Step 4: Group by context mode
        groups = group_messages_by_context_mode(messages)

        # Should have 4 COPY items (indices 0, 1, 6, 7)
        assert len(groups.copy_items) == 4
        copy_indices = [idx for _, idx in groups.copy_items]
        assert sorted(copy_indices) == [0, 1, 6, 7]

        # Should have 1 compress group with 4 items (indices 2, 3, 4, 5)
        assert len(groups.compress_groups) == 1
        assert len(groups.compress_groups[0]) == 4
        compress_indices = [idx for _, idx in groups.compress_groups[0]]
        assert sorted(compress_indices) == [2, 3, 4, 5]

        # Should need compression
        assert groups.needs_compression

    def test_proposal_with_drop_excludes_exchanges(self):
        """Exchanges marked DROP should be excluded from context."""
        from core.context_grouper import group_messages_by_context_mode

        proposal = ForkProposal(
            name="focused-fork",
            description="Only keep relevant exchanges",
            context_plan=[
                ContextAssignment(exchange_range="all", mode="drop"),  # Drop all first
                ContextAssignment(exchange_range="0", mode="copy"),  # Keep first
                ContextAssignment(exchange_range="last", mode="copy"),  # Keep last
            ],
        )

        # 5 exchanges
        exchange_modes = proposal.resolve_exchange_indices(5, exclude_current=False)

        # Only 0 and 4 should be COPY, rest DROP
        assert exchange_modes[0].value == "copy"
        assert exchange_modes[1].value == "drop"
        assert exchange_modes[2].value == "drop"
        assert exchange_modes[3].value == "drop"
        assert exchange_modes[4].value == "copy"

        # Create messages
        messages = []
        for i in range(5):
            mode = exchange_modes[i]
            msg = Message(
                role="user",
                content=f"Content {i}",
                context_mode=mode,
            )
            messages.append((msg, i))

        # Group - only COPY items, no compression
        groups = group_messages_by_context_mode(messages)

        assert len(groups.copy_items) == 2
        assert len(groups.compress_groups) == 0
        assert not groups.needs_compression

    def test_context_modes_preserved_through_message_creation(self):
        """Messages created with context modes should preserve the mode attribute."""
        modes = [ContextMode.COPY, ContextMode.COMPRESS, ContextMode.DROP]

        # Create messages with explicit modes
        messages = []
        for i, mode in enumerate(modes):
            if mode != ContextMode.DROP:
                msg = Message(
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"Content {i}",
                    context_mode=mode,
                )
                messages.append((msg, i))

        # Should only have 2 messages (DROP excluded)
        assert len(messages) == 2

        # Verify modes on messages
        assert messages[0][0].context_mode.value == "copy"
        assert messages[0][1] == 0
        assert messages[1][0].context_mode.value == "compress"
        assert messages[1][1] == 1

    def test_end_to_end_fork_proposal_creates_compression_data(self):
        """End-to-end test: fork proposal with compress mode creates ForkData for compression."""
        from core.context_grouper import group_messages_by_context_mode

        # Step 1: Create proposal
        proposal = ForkProposal(
            name="compress-test",
            description="Test compression flow",
            context_plan=[
                ContextAssignment(exchange_range="0", mode="copy"),
                ContextAssignment(exchange_range="1", mode="compress"),
            ],
        )

        # Step 2: Resolve (2 exchanges)
        exchange_modes = proposal.resolve_exchange_indices(2, exclude_current=False)

        # Step 3: Build messages with resolved modes
        indexed_messages = []
        for i in range(2):
            mode = exchange_modes.get(i, ContextMode.DROP)
            if mode != ContextMode.DROP:
                msg = Message(
                    role="user",
                    content=f"Exchange {i}",
                    content_blocks=[TextBlock(text=f"Exchange {i}")],
                    context_mode=mode,
                )
                indexed_messages.append((msg, i))

        # Step 4: Group by context mode
        groups = group_messages_by_context_mode(indexed_messages)

        # Verify the data needed for ForkManager
        assert len(groups.copy_items) == 1
        assert groups.copy_items[0][1] == 0  # Index 0 is COPY
        assert len(groups.compress_groups) == 1
        assert groups.compress_groups[0][0][1] == 1  # Index 1 is COMPRESS
        assert groups.needs_compression
        assert groups.compress_group_positions == [1]

    # test_session_id_mismatch_modes_still_found removed - TreeState deleted in Phase 8


class TestBuildContextMessages:
    """Tests for build_context_messages function."""

    def test_empty_inputs(self):
        """Empty inputs should return empty list."""
        from core.context_grouper import build_context_messages

        result = build_context_messages([], [])

        assert result == []

    def test_only_copy_items(self):
        """Only copy items should be returned in order."""
        from core.context_grouper import build_context_messages

        msg1 = Message(role="user", content="First")
        msg2 = Message(role="assistant", content="Second")

        result = build_context_messages(
            copy_items=[(msg1, 0), (msg2, 1)],
            summary_items=[],
        )

        assert len(result) == 2
        assert result[0].content == "First"
        assert result[1].content == "Second"

    def test_only_summary_items(self):
        """Only summary items should be returned in order."""
        from core.context_grouper import build_context_messages

        summary = Message(role="user", content="[Summary] Combined context")

        result = build_context_messages(
            copy_items=[],
            summary_items=[(summary, 0)],
        )

        assert len(result) == 1
        assert "[Summary]" in result[0].content

    def test_interleaved_copy_and_summary(self):
        """Copy and summary items should be sorted by index."""
        from core.context_grouper import build_context_messages

        msg1 = Message(role="user", content="First")  # index 0
        summary = Message(role="user", content="[Summary]")  # index 1 (replacing compressed)
        msg3 = Message(role="assistant", content="Last")  # index 2

        result = build_context_messages(
            copy_items=[(msg1, 0), (msg3, 2)],
            summary_items=[(summary, 1)],
        )

        assert len(result) == 3
        assert result[0].content == "First"
        assert "[Summary]" in result[1].content
        assert result[2].content == "Last"

    def test_out_of_order_inputs_sorted(self):
        """Items passed out of order should be sorted by index."""
        from core.context_grouper import build_context_messages

        msg1 = Message(role="user", content="First")
        msg2 = Message(role="assistant", content="Second")
        msg3 = Message(role="user", content="Third")

        # Pass in reverse order
        result = build_context_messages(
            copy_items=[(msg3, 2), (msg1, 0)],
            summary_items=[(msg2, 1)],
        )

        assert len(result) == 3
        assert result[0].content == "First"
        assert result[1].content == "Second"
        assert result[2].content == "Third"


class TestCompressionHelperFlow:
    """Tests for the compression helper flow.

    Verifies the end-to-end flow when COMPRESS mode is used:
    1. prepare_fork returns needs_compression=True with helper_id and compression_prompt
    2. HelperRunner is created and started correctly
    3. Helper completion triggers complete_fork_after_compression
    4. Compressed summary is inserted at correct position in child session
    """

    def create_mock_session(self, **kwargs):
        """Create a mock session with default attributes."""
        session = MagicMock()
        session.id = kwargs.get("id", "test-session-123")
        session.turns = kwargs.get("turns", [])
        session.is_read_only = MagicMock(return_value=kwargs.get("read_only", False))
        session.is_fork = MagicMock(return_value=kwargs.get("is_fork", False))
        session.is_merged = MagicMock(return_value=kwargs.get("is_merged", False))
        session.get_parent = MagicMock(return_value=kwargs.get("parent", None))
        session.get_parent_async = AsyncMock(return_value=kwargs.get("parent", None))
        session.get_fork_display_name = MagicMock(return_value=kwargs.get("fork_name", "test-fork"))
        session.get_all_forks = MagicMock(return_value=kwargs.get("forks", []))
        session.add_child = MagicMock()
        session.add_message = MagicMock()
        session.add_fork_turn = MagicMock()
        session.save = AsyncMock()
        session.mark_merged = MagicMock()
        session.mark_child_merged = MagicMock()
        session.get_last_exchange_id = MagicMock(return_value="exchange-123")
        return session

    def create_mock_context_builder(self):
        """Create a mock context builder."""
        builder = MagicMock()
        builder.build_context_summary_prompt = MagicMock(
            return_value="Please summarize this context..."
        )
        return builder

    @pytest.mark.asyncio
    @patch("core.fork.Session")
    @patch("core.fork.copy_session_bindings")
    async def test_prepare_fork_returns_valid_compression_prompt(self, mock_copy_bindings, mock_session_class):
        """prepare_fork should return a valid compression_prompt when COMPRESS messages exist."""
        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123")
        child = self.create_mock_session(id="child-456")
        mock_session_class.return_value = child
        mock_copy_bindings.return_value = 0

        msg1 = Message(
            role="user",
            content="Context to compress",
            content_blocks=[TextBlock(text="Context to compress")],
            context_mode=ContextMode.COMPRESS,
        )

        result = await manager.prepare_fork(
            current_session=parent,
            indexed_messages=[(msg1, 0)],
            prompt="Continue",
            allowed_tools=["read"],
        )

        assert result.success
        assert result.needs_compression
        assert result.compression_prompt is not None
        assert "summarize" in result.compression_prompt.lower() or "Please" in result.compression_prompt
        assert result.helper_id is not None
        assert len(result.helper_id) > 0

    @pytest.mark.asyncio
    @patch("core.fork.Session")
    @patch("core.fork.copy_session_bindings")
    async def test_fork_data_contains_correct_info(self, mock_copy_bindings, mock_session_class):
        """ForkData should contain all necessary info for completing the fork."""
        from core.fork import ForkData

        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)

        parent = self.create_mock_session(id="parent-123")
        child = self.create_mock_session(id="child-456")
        mock_session_class.return_value = child
        mock_copy_bindings.return_value = 0

        msg1 = Message(
            role="user",
            content="Copy this",
            content_blocks=[TextBlock(text="Copy this")],
            context_mode=ContextMode.COPY,
        )
        msg2 = Message(
            role="assistant",
            content="Compress this",
            content_blocks=[TextBlock(text="Compress this")],
            context_mode=ContextMode.COMPRESS,
        )

        result = await manager.prepare_fork(
            current_session=parent,
            indexed_messages=[(msg1, 0), (msg2, 1)],
            prompt="Continue",
            allowed_tools=["read", "write"],
            name="test-fork",
            background=True,
        )

        assert result.success
        assert result.needs_compression
        assert result.fork_data is not None
        assert isinstance(result.fork_data, ForkData)

        # Verify ForkData contents
        fork_data = result.fork_data
        assert fork_data.child_session == child
        assert fork_data.parent_session == parent
        assert fork_data.prompt == "Continue"
        assert fork_data.name == "test-fork"
        assert fork_data.background is True
        assert fork_data.allowed_tools == ["read", "write"]
        assert len(fork_data.copy_items) == 1
        assert len(fork_data.compress_group_positions) == 1

    @pytest.mark.asyncio
    @patch("core.fork.copy_session_bindings")
    async def test_complete_fork_after_compression_inserts_summary(self, mock_copy_bindings):
        """complete_fork_after_compression should insert summary at correct position."""
        from core.fork import ForkData

        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)
        mock_copy_bindings.return_value = 0

        parent = self.create_mock_session(id="parent-123")
        child = self.create_mock_session(id="child-456")

        msg1 = Message(
            role="user",
            content="Copy this",
            content_blocks=[TextBlock(text="Copy this")],
            context_mode=ContextMode.COPY,
        )

        fork_data = ForkData(
            child_session=child,
            parent_session=parent,
            prompt="Continue",
            name="test-fork",
            background=False,
            allowed_tools=["read"],
            copy_items=[(msg1, 0)],
            compress_group_positions=[1],  # Summary should go at position 1
            fork_point=0,
        )

        compressed_summary = "This is the compressed context summary."

        result = await manager.complete_fork_after_compression(fork_data, compressed_summary)

        assert result.success
        assert not result.needs_compression  # Should be done with compression

        # Verify child.add_message was called correctly
        calls = child.add_message.call_args_list
        assert len(calls) == 2  # One for copy, one for summary

        # First call should be the copy item (index 0)
        first_call = calls[0]
        assert first_call[0][0] == "user"  # role
        assert first_call[0][1] == "Copy this"  # content

        # Second call should be the summary (index 1)
        second_call = calls[1]
        assert second_call[0][0] == "user"  # role
        assert "[Context Summary]" in second_call[0][1]
        assert compressed_summary in second_call[0][1]

    @pytest.mark.asyncio
    @patch("core.fork.copy_session_bindings")
    async def test_complete_fork_registers_child_with_parent(self, mock_copy_bindings):
        """complete_fork_after_compression should register child with parent."""
        from core.fork import ForkData

        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)
        mock_copy_bindings.return_value = 0

        parent = self.create_mock_session(id="parent-123")
        child = self.create_mock_session(id="child-456")

        fork_data = ForkData(
            child_session=child,
            parent_session=parent,
            prompt="Continue",
            name="my-fork",
            background=False,
            allowed_tools=["read"],
            copy_items=[],
            compress_group_positions=[],
            fork_point=5,
        )

        await manager.complete_fork_after_compression(fork_data, "Summary")

        # Verify parent.add_child was called
        parent.add_child.assert_called_once_with(
            child.id,
            "Continue",
            name="my-fork",
            fork_point=5,
        )

        # Verify parent.add_fork_turn was called
        parent.add_fork_turn.assert_called_once()
        call_kwargs = parent.add_fork_turn.call_args[1]
        assert call_kwargs["child_session_id"] == child.id
        assert call_kwargs["fork_name"] == "my-fork"
        assert call_kwargs["prompt"] == "Continue"

    @pytest.mark.asyncio
    @patch("core.fork.copy_session_bindings")
    async def test_complete_fork_saves_sessions(self, mock_copy_bindings):
        """complete_fork_after_compression should save both sessions."""
        from core.fork import ForkData

        context_builder = self.create_mock_context_builder()
        manager = ForkManager(context_builder)
        mock_copy_bindings.return_value = 0

        parent = self.create_mock_session(id="parent-123")
        child = self.create_mock_session(id="child-456")

        fork_data = ForkData(
            child_session=child,
            parent_session=parent,
            prompt="Continue",
            name="test-fork",
            background=False,
            allowed_tools=[],
            copy_items=[],
            compress_group_positions=[],
            fork_point=0,
        )

        await manager.complete_fork_after_compression(fork_data, "Summary")

        child.save.assert_called_once()
        parent.save.assert_called_once()


class TestHelperRunner:
    """Tests for HelperRunner used in compression flow."""

    @pytest.mark.asyncio
    async def test_helper_runner_starts_background_task(self):
        """HelperRunner.start_background should start streaming."""
        from core.runner import HelperRunner, RunnerStatus
        from models import TextDelta

        # Create a mock runner that yields text
        mock_runner = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield TextDelta(text="Part 1")
            yield TextDelta(text=" Part 2")

        mock_runner.stream_response = mock_stream

        helper = HelperRunner("helper-123", runner=mock_runner)

        assert helper.status == RunnerStatus.IDLE

        helper.start_background("Compress this context")

        # Give async task time to run
        await asyncio.sleep(0.05)

        # Should have transitioned through STREAMING to IDLE
        assert helper.is_done
        assert helper.get_result() == "Part 1 Part 2"

    @pytest.mark.asyncio
    async def test_helper_runner_queues_events(self):
        """HelperRunner should queue text events for polling."""
        from core.runner import HelperRunner
        from models import TextDelta

        mock_runner = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield TextDelta(text="Chunk1")
            yield TextDelta(text="Chunk2")

        mock_runner.stream_response = mock_stream

        helper = HelperRunner("helper-123", runner=mock_runner)
        helper.start_background("Compress")

        # Give async task time to run
        await asyncio.sleep(0.05)

        events = helper.drain_events()

        # Should have text events and done event
        text_events = [e for e in events if e.event_type == "text"]
        done_events = [e for e in events if e.event_type == "done"]

        assert len(text_events) == 2
        assert text_events[0].data == "Chunk1"
        assert text_events[1].data == "Chunk2"
        assert len(done_events) == 1
        assert done_events[0].data == "Chunk1Chunk2"

    @pytest.mark.asyncio
    async def test_helper_runner_handles_error(self):
        """HelperRunner should emit error event on exception."""
        from core.runner import HelperRunner, RunnerStatus

        mock_runner = MagicMock()

        async def mock_stream(*args, **kwargs):
            raise RuntimeError("API error")
            yield  # Make it a generator

        mock_runner.stream_response = mock_stream

        helper = HelperRunner("helper-123", runner=mock_runner)
        helper.start_background("Compress")

        # Give async task time to run
        await asyncio.sleep(0.05)

        assert helper.status == RunnerStatus.ERROR

        events = helper.drain_events()
        error_events = [e for e in events if e.event_type == "error"]

        assert len(error_events) == 1
        assert "API error" in error_events[0].data

    @pytest.mark.asyncio
    async def test_helper_runner_cancel(self):
        """HelperRunner.cancel should stop streaming."""
        from core.runner import HelperRunner, RunnerStatus
        from models import TextDelta

        mock_runner = MagicMock()
        mock_runner.terminate = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield TextDelta(text="Start")
            await asyncio.sleep(10)  # Long wait to be cancelled
            yield TextDelta(text="Never reached")

        mock_runner.stream_response = mock_stream

        helper = HelperRunner("helper-123", runner=mock_runner)
        helper.start_background("Compress")

        # Give task time to start
        await asyncio.sleep(0.01)

        helper.cancel()

        # Give cancel time to propagate
        await asyncio.sleep(0.05)

        assert helper.status == RunnerStatus.CANCELLED
        mock_runner.terminate.assert_called_once()


class TestStreamingContextForkData:
    """Tests for StreamingContext.fork_data handling in compression flow."""

    def test_streaming_context_stores_fork_data(self):
        """StreamingContext should store ForkData for compression helpers."""
        from core.streaming import StreamingContext
        from core.fork import ForkData
        from session import Session
        from unittest.mock import MagicMock

        # Create mock sessions
        parent = MagicMock(spec=Session)
        child = MagicMock(spec=Session)

        fork_data = ForkData(
            child_session=child,
            parent_session=parent,
            prompt="Continue",
            name="test",
            background=False,
            allowed_tools=[],
            copy_items=[],
            compress_group_positions=[0],
            fork_point=0,
        )

        ctx = StreamingContext(
            session_id="helper-123",
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_helper=True,
            helper_type="compress",
            fork_data=fork_data,
        )

        assert ctx.fork_data is fork_data
        assert ctx.helper_type == "compress"
        assert ctx.is_helper is True

    def test_streaming_context_accumulates_content(self):
        """StreamingContext should accumulate content from text events."""
        from core.streaming import StreamingContext

        ctx = StreamingContext(
            session_id="helper-123",
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_helper=True,
            helper_type="compress",
        )

        # Initially empty
        assert ctx.content == ""

        # Accumulate content
        ctx.content += "Part 1"
        ctx.content += " Part 2"

        assert ctx.content == "Part 1 Part 2"


class TestCompressionHelperIntegration:
    """Integration tests that verify the complete compression helper flow.

    These tests verify that:
    1. Helper events are properly dispatched
    2. HelperDoneAction contains the accumulated content
    3. The fork_data is preserved through the flow
    """

    @pytest.mark.asyncio
    async def test_helper_event_dispatch_accumulates_content(self):
        """Text events should accumulate in ctx.content via StreamingCoordinator."""
        from core.streaming import StreamingCoordinator, StreamingContext
        from core.runner import StreamEvent

        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="helper-123",
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_helper=True,
            helper_type="compress",
        )

        # Simulate multiple text events
        event1 = StreamEvent(event_type="text", data="First chunk.")
        event2 = StreamEvent(event_type="text", data=" Second chunk.")
        event3 = StreamEvent(event_type="text", data=" Third chunk.")

        action1 = coordinator.dispatch_helper_event(event1, ctx)
        action2 = coordinator.dispatch_helper_event(event2, ctx)
        action3 = coordinator.dispatch_helper_event(event3, ctx)

        # All should return TextAction
        from core.streaming import TextAction
        assert isinstance(action1, TextAction)
        assert isinstance(action2, TextAction)
        assert isinstance(action3, TextAction)

        # Content should accumulate
        assert ctx.content == "First chunk. Second chunk. Third chunk."

    @pytest.mark.asyncio
    async def test_helper_done_event_preserves_fork_data(self):
        """Done event should include accumulated content and fork_data."""
        from core.streaming import StreamingCoordinator, StreamingContext, HelperDoneAction
        from core.runner import StreamEvent
        from core.fork import ForkData

        # Create fork_data
        parent = MagicMock()
        child = MagicMock()
        fork_data = ForkData(
            child_session=child,
            parent_session=parent,
            prompt="Continue",
            name="test",
            background=False,
            allowed_tools=[],
            copy_items=[],
            compress_group_positions=[0],
            fork_point=0,
        )

        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="helper-123",
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_helper=True,
            helper_type="compress",
            fork_data=fork_data,
        )

        # Simulate text events
        coordinator.dispatch_helper_event(StreamEvent(event_type="text", data="Summary: "), ctx)
        coordinator.dispatch_helper_event(StreamEvent(event_type="text", data="The conversation covered X and Y."), ctx)

        # Simulate done event
        action = coordinator.dispatch_helper_event(StreamEvent(event_type="done", data=""), ctx)

        assert isinstance(action, HelperDoneAction)
        assert action.helper_type == "compress"
        assert action.content == "Summary: The conversation covered X and Y."
        assert action.fork_data is fork_data
        assert action.error is None
        assert action.cancelled is False

    @pytest.mark.asyncio
    async def test_full_helper_flow_end_to_end(self):
        """Test the complete helper flow from start to completion."""
        from core.runner import HelperRunner, StreamEvent
        from core.streaming import StreamingCoordinator, StreamingContext, HelperDoneAction
        from core.fork import ForkData
        from models import TextDelta

        # Create mock runner that yields a summary
        mock_runner = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield TextDelta(text="This is a ")
            yield TextDelta(text="compressed summary ")
            yield TextDelta(text="of the context.")

        mock_runner.stream_response = mock_stream

        # Create fork_data
        parent = MagicMock()
        child = MagicMock()
        fork_data = ForkData(
            child_session=child,
            parent_session=parent,
            prompt="Continue",
            name="test",
            background=False,
            allowed_tools=[],
            copy_items=[],
            compress_group_positions=[0],
            fork_point=0,
        )

        # Create helper runner and streaming context
        helper = HelperRunner("helper-123", runner=mock_runner)
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="helper-123",
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_helper=True,
            helper_type="compress",
            fork_data=fork_data,
        )

        # Start helper
        helper.start_background("Please compress this context...")

        # Wait for completion
        await asyncio.sleep(0.1)

        assert helper.is_done

        # Drain events and dispatch them
        events = helper.drain_events()
        assert len(events) > 0

        final_action = None
        for event in events:
            action = coordinator.dispatch_helper_event(event, ctx)
            if isinstance(action, HelperDoneAction):
                final_action = action

        # Verify final action
        assert final_action is not None
        assert final_action.helper_type == "compress"
        assert final_action.content == "This is a compressed summary of the context."
        assert final_action.fork_data is fork_data
        assert ctx.content == "This is a compressed summary of the context."
