"""Tests for kanban LLM tools.

DEPRECATED: These tests are for the old core/kanban_tools.py implementation.
The kanban functionality has been migrated to plugins/kanban/domain.py.
See plugins/kanban/test_domain.py for the new tests.
"""

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from core.kanban_tools import (
    KANBAN_TOOLS,
    KANBAN_TOOL_NAMES,
    execute_kanban_tool,
    _get_boards,
    _create_board,
    _create_task,
    _update_task,
    _move_task,
    _delete_task,
    _get_primary_board,
)


class TestKanbanToolDefinitions:
    """Test that tool definitions are properly structured."""

    def test_tool_names_match_definitions(self):
        """Tool names in KANBAN_TOOL_NAMES should match KANBAN_TOOLS."""
        defined_names = {t["function"]["name"] for t in KANBAN_TOOLS}
        assert defined_names == KANBAN_TOOL_NAMES

    def test_all_tools_have_required_fields(self):
        """All tools should have type, function, name, description, parameters."""
        for tool in KANBAN_TOOLS:
            assert tool["type"] == "function"
            assert "function" in tool
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"

    def test_expected_tools_exist(self):
        """Expected tool names should exist."""
        expected = {
            "kanban_get_boards",
            "kanban_create_board",
            "kanban_create_task",
            "kanban_update_task",
            "kanban_move_task",
            "kanban_delete_task",
            "kanban_list_tasks",
            "kanban_get_board_state",
        }
        assert expected == KANBAN_TOOL_NAMES


class TestKanbanToolHelpers:
    """Test internal helper functions with mocked dependencies."""

    @pytest.fixture
    def mock_kanban(self):
        """Create a mock KanbanService."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_get_boards_empty(self, mock_kanban):
        """get_boards with no boards should return helpful message."""
        mock_kanban.get_boards_for_session = AsyncMock(return_value=[])

        result, is_error = await _get_boards("session-123", mock_kanban)

        assert not is_error
        assert "No boards" in result

    @pytest.mark.asyncio
    async def test_get_boards_with_boards(self, mock_kanban):
        """get_boards should list available boards."""
        mock_assoc = MagicMock()
        mock_assoc.role = "primary"
        mock_assoc.inherited_from = None

        mock_board = MagicMock()
        mock_board.id = "board-123"
        mock_board.name = "Test Board"

        mock_kanban.get_boards_for_session = AsyncMock(return_value=[(mock_assoc, mock_board)])

        result, is_error = await _get_boards("session-123", mock_kanban)

        assert not is_error
        assert "Test Board" in result
        assert "board-123" in result

    @pytest.mark.asyncio
    async def test_create_board_requires_name(self, mock_kanban):
        """create_board without name should error."""
        result, is_error = await _create_board({}, "session-123", mock_kanban)

        assert is_error
        assert "name" in result.lower()

    @pytest.mark.asyncio
    async def test_create_board_success(self, mock_kanban):
        """create_board with valid name should succeed."""
        mock_col1 = MagicMock()
        mock_col1.name = "Backlog"
        mock_col2 = MagicMock()
        mock_col2.name = "Done"

        mock_board_state = MagicMock()
        mock_board_state.board.id = "board-456"
        mock_board_state.board.name = "New Board"
        mock_board_state.board.default_column_id = "col-1"
        mock_board_state.columns = [mock_col1, mock_col2]

        mock_kanban.create_board_for_session = AsyncMock(return_value=mock_board_state)

        result, is_error = await _create_board({"name": "New Board"}, "session-123", mock_kanban)

        assert not is_error
        assert "New Board" in result
        assert "board-456" in result

    @pytest.mark.asyncio
    async def test_get_primary_board_empty(self, mock_kanban):
        """get_primary_board with no boards should return error."""
        mock_kanban.get_boards_for_session = AsyncMock(return_value=[])

        board_id, error = await _get_primary_board("session-123", mock_kanban)

        assert board_id is None
        assert error is not None
        assert "No boards" in error

    @pytest.mark.asyncio
    async def test_get_primary_board_exists(self, mock_kanban):
        """get_primary_board should return first board ID."""
        mock_board = MagicMock()
        mock_board.id = "board-123"

        mock_kanban.get_boards_for_session = AsyncMock(return_value=[(MagicMock(), mock_board)])

        board_id, error = await _get_primary_board("session-123", mock_kanban)

        assert board_id == "board-123"
        assert error is None

    @pytest.mark.asyncio
    async def test_create_task_requires_title(self, mock_kanban):
        """create_task without title should error."""
        result, is_error = await _create_task({}, "session-123", mock_kanban)

        assert is_error
        assert "title" in result.lower()

    @pytest.mark.asyncio
    async def test_update_task_requires_task_id(self, mock_kanban):
        """update_task without task_id should error."""
        result, is_error = await _update_task({"title": "New Title"}, mock_kanban)

        assert is_error
        assert "task_id" in result.lower()

    @pytest.mark.asyncio
    async def test_update_task_requires_field(self, mock_kanban):
        """update_task needs at least one field to update."""
        result, is_error = await _update_task({"task_id": "task-123"}, mock_kanban)

        assert is_error
        assert "title or description" in result.lower()

    @pytest.mark.asyncio
    async def test_move_task_requires_task_id(self, mock_kanban):
        """move_task without task_id should error."""
        result, is_error = await _move_task({"to_column_id": "col-123"}, mock_kanban)

        assert is_error
        assert "task_id" in result.lower()

    @pytest.mark.asyncio
    async def test_move_task_requires_to_column_id(self, mock_kanban):
        """move_task without to_column_id should error."""
        result, is_error = await _move_task({"task_id": "task-123"}, mock_kanban)

        assert is_error
        assert "to_column_id" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_task_requires_task_id(self, mock_kanban):
        """delete_task without task_id should error."""
        result, is_error = await _delete_task({}, mock_kanban)

        assert is_error
        assert "task_id" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_task_success(self, mock_kanban):
        """delete_task with valid ID should succeed."""
        mock_kanban.delete_task = AsyncMock(return_value=True)

        result, is_error = await _delete_task({"task_id": "task-123"}, mock_kanban)

        assert not is_error
        assert "task-123" in result
