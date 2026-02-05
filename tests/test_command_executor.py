"""Tests for CommandExecutor - business logic for archive, link, and backend commands."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from core.command_executor import (
    CommandExecutor,
    ArchiveResult,
    RehydrateResult,
    LinkResult,
    LinkTarget,
    BackendResult,
    BackendInfo,
)
from session import Session, Turn
from models import ArchiveBlock, ArchiveSummary, TextBlock, ContextMode


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def executor():
    """Create a CommandExecutor instance."""
    return CommandExecutor()


@pytest.fixture
def sample_session(temp_dir):
    """Create a sample session with some turns."""
    session = Session()
    session._storage_dir = temp_dir  # Override storage for testing

    # Add some turns (Turn takes content_block, not content)
    session.turns = [
        Turn(role="user", content_block=TextBlock(text="Hello")),
        Turn(role="assistant", content_block=TextBlock(text="Hi there!")),
        Turn(role="user", content_block=TextBlock(text="How are you?")),
        Turn(role="assistant", content_block=TextBlock(text="I'm good!")),
    ]

    return session


class TestArchiveResult:
    """Tests for ArchiveResult dataclass."""

    def test_success_result(self):
        """Test creating a successful archive result."""
        result = ArchiveResult(
            success=True,
            archive_block=ArchiveBlock(archive_id="test-123"),
            new_turns=[],
            archived_count=3,
            file_path="/path/to/archive.json",
        )

        assert result.success
        assert result.error is None
        assert result.archive_block.archive_id == "test-123"
        assert result.archived_count == 3

    def test_error_result(self):
        """Test creating an error archive result."""
        result = ArchiveResult(
            success=False,
            error="Invalid turn range",
        )

        assert not result.success
        assert result.error == "Invalid turn range"
        assert result.archive_block is None


class TestBackendResult:
    """Tests for BackendResult and BackendInfo dataclasses."""

    def test_backend_info(self):
        """Test BackendInfo contains expected fields."""
        info = BackendInfo(
            current="claude",
            available=["claude", "openai", "local"],
            is_missing=False,
        )

        assert info.current == "claude"
        assert len(info.available) == 3
        assert not info.is_missing

    def test_backend_result_for_show(self):
        """Test BackendResult for showing backend info."""
        result = BackendResult(
            success=True,
            info=BackendInfo(current="claude", available=["claude"]),
        )

        assert result.success
        assert result.info.current == "claude"
        assert result.new_backend == ""

    def test_backend_result_for_set(self):
        """Test BackendResult for setting backend."""
        result = BackendResult(
            success=True,
            new_backend="openai",
            model="gpt-4",
        )

        assert result.success
        assert result.new_backend == "openai"
        assert result.model == "gpt-4"


class TestCommandExecutorArchive:
    """Tests for CommandExecutor archive operations."""

    def test_prepare_archive_no_session(self, executor):
        """Test archive fails without a session."""
        result = executor.prepare_archive(
            session=None,
            turn_indices=[0, 1],
            summary="Test summary",
        )

        assert not result.success
        assert "No active session" in result.error

    def test_prepare_archive_no_turns(self, executor, sample_session):
        """Test archive fails with empty turn indices."""
        result = executor.prepare_archive(
            session=sample_session,
            turn_indices=[],
            summary="Test summary",
        )

        assert not result.success
        assert "No turns selected" in result.error

    def test_prepare_archive_success(self, executor, sample_session, temp_dir):
        """Test successful archive operation."""
        # Patch the Archiver to use temp directory
        from core import archiver
        original_dir = archiver.ARCHIVES_DIR
        archiver.ARCHIVES_DIR = temp_dir

        try:
            result = executor.prepare_archive(
                session=sample_session,
                turn_indices=[0, 1],
                summary="Test conversation",
            )

            assert result.success
            assert result.archive_block is not None
            assert result.archived_count == 2
            assert len(result.new_turns) == 3  # 4 original - 2 archived + 1 archive marker
        finally:
            archiver.ARCHIVES_DIR = original_dir


class TestCommandExecutorRehydrate:
    """Tests for CommandExecutor rehydrate operations."""

    def test_prepare_rehydrate_no_session(self, executor):
        """Test rehydrate fails without a session."""
        result = executor.prepare_rehydrate(
            session=None,
            turn_index=0,
        )

        assert not result.success
        assert "No active session" in result.error

    def test_prepare_rehydrate_invalid_index(self, executor, sample_session):
        """Test rehydrate fails with invalid turn index."""
        result = executor.prepare_rehydrate(
            session=sample_session,
            turn_index=100,
        )

        assert not result.success
        assert "Invalid turn index" in result.error

    def test_prepare_rehydrate_not_archive(self, executor, sample_session):
        """Test rehydrate fails if turn is not an archive."""
        result = executor.prepare_rehydrate(
            session=sample_session,
            turn_index=0,
        )

        assert not result.success
        assert "not an archive" in result.error


class TestCommandExecutorLink:
    """Tests for CommandExecutor link operations."""

    def test_resolve_no_session(self, executor):
        """Test link resolution fails without a session."""
        result = executor.resolve_link_targets(
            current_session=None,
            target_prefixes=["abc123"],
        )

        assert not result.success
        assert "No active session" in result.error

    def test_resolve_no_targets(self, executor, sample_session):
        """Test link resolution fails with no targets."""
        result = executor.resolve_link_targets(
            current_session=sample_session,
            target_prefixes=[],
        )

        assert not result.success
        assert "No target sessions" in result.error

    @patch('core.command_executor.Session.list_sessions')
    def test_resolve_no_match(self, mock_list, executor, sample_session):
        """Test link resolution fails if no session matches."""
        mock_list.return_value = []

        result = executor.resolve_link_targets(
            current_session=sample_session,
            target_prefixes=["nonexist"],
        )

        assert not result.success
        assert "No session found" in result.error

    @patch('core.command_executor.Session.list_sessions')
    def test_resolve_multiple_matches(self, mock_list, executor, sample_session):
        """Test link resolution fails with ambiguous prefix."""
        mock_list.return_value = [
            {"id": "abc12345-1"},
            {"id": "abc12345-2"},
        ]

        result = executor.resolve_link_targets(
            current_session=sample_session,
            target_prefixes=["abc123"],
        )

        assert not result.success
        assert "Multiple sessions match" in result.error

    @patch('core.command_executor.Session.list_sessions')
    def test_resolve_self_link(self, mock_list, executor, sample_session):
        """Test link resolution fails when linking to self."""
        mock_list.return_value = [{"id": sample_session.id}]

        result = executor.resolve_link_targets(
            current_session=sample_session,
            target_prefixes=[sample_session.id[:8]],
        )

        assert not result.success
        assert "Cannot link session to itself" in result.error

    def test_complete_link_creates_turns(self, executor, sample_session):
        """Test complete_link creates link turns in both sessions."""
        target_session = Session()
        target_session.summary = "Target summary"
        sample_session.summary = "Current summary"

        targets = [LinkTarget(
            prefix="abc123",
            session=target_session,
            summary="Target summary",
        )]

        result = executor.complete_link(
            current_session=sample_session,
            targets=targets,
            current_summary="Current summary",
        )

        assert result.success
        assert len(result.link_turns) == 1
        assert len(result.sessions_to_save) == 2  # Both current and target


class TestCommandExecutorBackend:
    """Tests for CommandExecutor backend operations."""

    def test_get_backend_info(self, executor, sample_session):
        """Test getting backend info."""
        mock_config = MagicMock()
        mock_config.default_backend = "claude"
        mock_config.backends = {"claude": MagicMock(), "openai": MagicMock()}

        sample_session.backend_name = None

        result = executor.get_backend_info(sample_session, mock_config)

        assert result.success
        assert result.info.current == "claude"
        assert "claude" in result.info.available
        assert "openai" in result.info.available
        assert not result.info.is_missing

    def test_get_backend_info_missing(self, executor, sample_session):
        """Test getting info when session's backend no longer exists."""
        mock_config = MagicMock()
        mock_config.default_backend = "claude"
        mock_config.backends = {"claude": MagicMock()}

        sample_session.backend_name = "deleted_backend"

        result = executor.get_backend_info(sample_session, mock_config)

        assert result.success
        assert result.info.is_missing

    def test_set_backend_success(self, executor, sample_session):
        """Test setting backend successfully."""
        mock_config = MagicMock()
        mock_config.backends = {"claude": MagicMock(), "openai": MagicMock()}
        mock_config.get_backend.return_value = MagicMock(model="gpt-4")

        result = executor.set_backend(sample_session, "openai", mock_config)

        assert result.success
        assert result.new_backend == "openai"
        assert result.model == "gpt-4"
        assert sample_session.backend_name == "openai"

    def test_set_backend_unknown(self, executor, sample_session):
        """Test setting unknown backend fails."""
        mock_config = MagicMock()
        mock_config.backends = {"claude": MagicMock()}

        result = executor.set_backend(sample_session, "unknown", mock_config)

        assert not result.success
        assert "Unknown backend" in result.error
        assert "claude" in result.error  # Lists available backends
