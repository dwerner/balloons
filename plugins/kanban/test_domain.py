"""Tests for the Kanban domain plugin."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from plugins.kanban.domain import KanbanDomain, create_domain, _boards, _associations, _boards_loaded
from plugins.kanban.models import Board, Task, Column, SessionBoardAssociation


# Reset global state before each test
@pytest.fixture(autouse=True)
def reset_state():
    """Reset global state before each test."""
    global _boards, _associations, _boards_loaded
    import plugins.kanban.domain as domain_module
    domain_module._boards = {}
    domain_module._associations = {}
    domain_module._boards_loaded = True  # Skip loading from disk in tests
    yield
    domain_module._boards = {}
    domain_module._associations = {}
    domain_module._boards_loaded = False


@pytest.fixture
def domain():
    """Create a fresh domain instance."""
    return create_domain()


@pytest.fixture
def mock_session():
    """Create a mock session."""
    session = MagicMock()
    session.id = "test-session-123"
    return session


class TestDomainBasics:
    """Test basic domain properties."""

    def test_domain_id(self, domain):
        assert domain.id == "kanban"

    def test_domain_name(self, domain):
        assert domain.name == "Kanban"

    def test_domain_version(self, domain):
        assert domain.version == "0.1.0"

    def test_prompt_loaded(self, domain):
        prompt = domain.get_prompt()
        assert "kanban" in prompt.lower()
        assert "task" in prompt.lower()

    def test_ui_config(self, domain):
        config = domain.get_ui_config()
        assert config is not None
        assert "tabs" in config
        assert any(t["id"] == "kanban" for t in config["tabs"])


class TestToolDefinitions:
    """Test that tools are properly defined."""

    def test_tool_count(self, domain):
        tools = domain.get_tools()
        assert len(tools) == 9

    def test_expected_tools(self, domain):
        tools = domain.get_tools()
        tool_names = {t.name for t in tools}
        expected = {
            "kanban_get_boards",
            "kanban_create_board",
            "kanban_create_task",
            "kanban_update_task",
            "kanban_move_task",
            "kanban_delete_task",
            "kanban_list_tasks",
            "kanban_get_board_state",
            "kanban_delete_column",
        }
        assert tool_names == expected

    def test_tools_have_descriptions(self, domain):
        tools = domain.get_tools()
        for tool in tools:
            assert tool.description, f"{tool.name} should have a description"


class TestKanbanTools:
    """Test the kanban tool implementations."""

    @pytest.mark.asyncio
    async def test_get_boards_empty(self, domain, mock_session):
        result = await domain.kanban_get_boards(session=mock_session)
        assert not result.is_error
        assert "No boards" in result.result

    @pytest.mark.asyncio
    async def test_create_board(self, domain, mock_session):
        result = await domain.kanban_create_board(
            name="Test Board",
            session=mock_session
        )
        assert not result.is_error
        assert "Created board" in result.result
        assert "Test Board" in result.result
        assert len(result.events) == 1
        assert result.events[0].type == "board_created"

    @pytest.mark.asyncio
    async def test_create_board_requires_name(self, domain, mock_session):
        result = await domain.kanban_create_board(
            name="",
            session=mock_session
        )
        assert result.is_error
        assert "required" in result.result.lower()

    @pytest.mark.asyncio
    async def test_get_boards_after_create(self, domain, mock_session):
        # Create a board
        await domain.kanban_create_board(name="Test Board", session=mock_session)

        # Get boards
        result = await domain.kanban_get_boards(session=mock_session)
        assert not result.is_error
        assert "Test Board" in result.result
        assert "1 board" in result.result

    @pytest.mark.asyncio
    async def test_create_task(self, domain, mock_session):
        # Create a board first
        await domain.kanban_create_board(name="Test Board", session=mock_session)

        # Create a task
        result = await domain.kanban_create_task(
            title="Test Task",
            description="Test description",
            session=mock_session
        )
        assert not result.is_error
        assert "Created task" in result.result
        assert "Test Task" in result.result
        assert len(result.events) == 1
        assert result.events[0].type == "task_created"

    @pytest.mark.asyncio
    async def test_create_task_requires_title(self, domain, mock_session):
        result = await domain.kanban_create_task(
            title="",
            session=mock_session
        )
        assert result.is_error
        assert "required" in result.result.lower()

    @pytest.mark.asyncio
    async def test_create_task_no_board(self, domain, mock_session):
        result = await domain.kanban_create_task(
            title="Test Task",
            session=mock_session
        )
        assert result.is_error
        assert "No boards" in result.result

    @pytest.mark.asyncio
    async def test_move_task_by_title(self, domain, mock_session):
        # Setup: create board and task
        await domain.kanban_create_board(name="Test Board", session=mock_session)
        await domain.kanban_create_task(title="My Task", session=mock_session)

        # Move by title to "In Progress"
        result = await domain.kanban_move_task(
            task="My Task",
            to_column="In Progress",
            session=mock_session
        )
        assert not result.is_error
        assert "Moved task" in result.result
        assert "In Progress" in result.result

    @pytest.mark.asyncio
    async def test_move_task_not_found(self, domain, mock_session):
        await domain.kanban_create_board(name="Test Board", session=mock_session)

        result = await domain.kanban_move_task(
            task="Nonexistent Task",
            to_column="Done",
            session=mock_session
        )
        assert result.is_error
        assert "not found" in result.result.lower()

    @pytest.mark.asyncio
    async def test_update_task_resolution(self, domain, mock_session):
        # Setup
        await domain.kanban_create_board(name="Test Board", session=mock_session)
        create_result = await domain.kanban_create_task(title="My Task", session=mock_session)

        # Get task ID from the result
        import re
        task_id_match = re.search(r'ID: ([a-f0-9-]+)', create_result.result)
        task_id = task_id_match.group(1) if task_id_match else None
        assert task_id, "Should have task ID in result"

        # Update with resolution
        result = await domain.kanban_update_task(
            task_id=task_id,
            resolution="Completed successfully",
            session=mock_session
        )
        assert not result.is_error
        assert "Updated" in result.result
        assert "Resolution" in result.result

    @pytest.mark.asyncio
    async def test_delete_task(self, domain, mock_session):
        # Setup
        await domain.kanban_create_board(name="Test Board", session=mock_session)
        create_result = await domain.kanban_create_task(title="My Task", session=mock_session)

        import re
        task_id_match = re.search(r'ID: ([a-f0-9-]+)', create_result.result)
        task_id = task_id_match.group(1)

        # Delete
        result = await domain.kanban_delete_task(
            task_id=task_id,
            session=mock_session
        )
        assert not result.is_error
        assert "Deleted" in result.result

    @pytest.mark.asyncio
    async def test_list_tasks(self, domain, mock_session):
        # Setup
        await domain.kanban_create_board(name="Test Board", session=mock_session)
        await domain.kanban_create_task(title="Task 1", session=mock_session)
        await domain.kanban_create_task(title="Task 2", session=mock_session)

        # List
        result = await domain.kanban_list_tasks(session=mock_session)
        assert not result.is_error
        assert "Task 1" in result.result
        assert "Task 2" in result.result

    @pytest.mark.asyncio
    async def test_get_board_state(self, domain, mock_session):
        # Setup
        await domain.kanban_create_board(name="Test Board", session=mock_session)
        await domain.kanban_create_task(title="Task 1", session=mock_session)

        # Get state
        result = await domain.kanban_get_board_state(session=mock_session)
        assert not result.is_error
        assert "Test Board" in result.result
        assert "Backlog" in result.result
        assert "Task 1" in result.result


class TestModels:
    """Test the data models."""

    def test_board_create(self):
        board = Board.create("Test Board")
        assert board.name == "Test Board"
        assert len(board.columns) == 4  # Default columns
        assert board.columns[0].name == "Backlog"
        assert board.default_column_id == board.columns[0].id

    def test_task_create(self):
        task = Task.create("Test Task", "Description")
        assert task.title == "Test Task"
        assert task.description == "Description"
        assert task.resolution == ""

    def test_board_serialization(self):
        board = Board.create("Test Board")
        data = board.to_dict()
        restored = Board.from_dict(data)
        assert restored.name == board.name
        assert len(restored.columns) == len(board.columns)

    def test_task_serialization(self):
        task = Task.create("Test", "Desc")
        data = task.to_dict()
        restored = Task.from_dict(data)
        assert restored.title == task.title
        assert restored.description == task.description
