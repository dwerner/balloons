"""Tests for goal management tools."""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock

from core.goal_tools import (
    execute_goal_tool,
    GOAL_TOOL_NAMES,
    GOAL_TOOLS,
)
from core.async_storage import GoalStorage
from storage_schema import GoalData, PlanData, TodoData, TodoPlanLink


@pytest.fixture
def temp_storage_dir():
    """Create a temporary directory for test storage."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def goal_storage(temp_storage_dir):
    """Create a GoalStorage instance using the temp directory."""
    return GoalStorage(temp_storage_dir)


@pytest.fixture
def mock_session():
    """Create a mock session for testing."""
    session = MagicMock()
    session.id = "test-session-123"
    return session


def make_async_storage_getter(storage):
    """Create an async function that returns the storage."""
    async def getter():
        return storage
    return getter


class TestGoalToolDefinitions:
    """Test that goal tools are properly defined."""

    def test_tool_names_match_definitions(self):
        """Verify GOAL_TOOL_NAMES matches actual tool definitions."""
        tool_names_from_defs = {t["function"]["name"] for t in GOAL_TOOLS}
        assert tool_names_from_defs == GOAL_TOOL_NAMES

    def test_all_tools_have_required_fields(self):
        """Verify all tool definitions have required OpenAI format fields."""
        for tool in GOAL_TOOLS:
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]


class TestCreateGoal:
    """Tests for create_goal tool."""

    @pytest.mark.asyncio
    async def test_create_goal_success(self, goal_storage, mock_session, monkeypatch):
        """Test successful goal creation."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "create_goal",
            {
                "title": "Build testing framework",
                "description": "Create automated testing for the application",
                "weight": 8,
                "acceptance_criteria": ["Unit tests pass", "Integration tests pass"],
            },
            mock_session,
        )

        assert not is_error
        assert "Created goal" in result
        assert "Build testing framework" in result
        assert "8/10" in result

        # Verify goal was saved
        goals = await goal_storage.list_goals()
        assert len(goals) == 1
        assert goals[0].title == "Build testing framework"
        assert goals[0].weight == 8

    @pytest.mark.asyncio
    async def test_create_goal_missing_title(self, goal_storage, mock_session, monkeypatch):
        """Test error when title is missing."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "create_goal",
            {
                "description": "Some description",
                "acceptance_criteria": ["Criterion 1"],
            },
            mock_session,
        )

        assert is_error
        assert "title is required" in result

    @pytest.mark.asyncio
    async def test_create_goal_missing_acceptance_criteria(self, goal_storage, mock_session, monkeypatch):
        """Test error when acceptance_criteria is missing."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "create_goal",
            {
                "title": "Test goal",
                "description": "Description",
            },
            mock_session,
        )

        assert is_error
        assert "acceptance_criteria is required" in result

    @pytest.mark.asyncio
    async def test_create_goal_default_weight(self, goal_storage, mock_session, monkeypatch):
        """Test default weight when not specified."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "create_goal",
            {
                "title": "Test goal",
                "description": "Description",
                "acceptance_criteria": ["Done"],
            },
            mock_session,
        )

        assert not is_error
        goals = await goal_storage.list_goals()
        assert goals[0].weight == 5  # Default weight


class TestCreatePlan:
    """Tests for create_plan tool."""

    @pytest.mark.asyncio
    async def test_create_plan_success(self, goal_storage, mock_session, monkeypatch):
        """Test successful plan creation."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        # First create a goal
        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-123",
            title="Parent Goal",
            description="",
            weight=7,
            status="active",
            acceptance_criteria=["Done"],
            created_at=now,
            updated_at=now,
        )
        await goal_storage.save_goal(goal)

        # Now create a plan
        result, is_error = await execute_goal_tool(
            "create_plan",
            {
                "goal_id": "goal-123",
                "title": "Implementation Plan",
                "description": "Step by step implementation",
            },
            mock_session,
        )

        assert not is_error
        assert "Created plan" in result
        assert "Implementation Plan" in result

        # Verify plan was saved
        plans = await goal_storage.list_plans()
        assert len(plans) == 1
        assert plans[0].goal_id == "goal-123"

    @pytest.mark.asyncio
    async def test_create_plan_goal_not_found(self, goal_storage, mock_session, monkeypatch):
        """Test error when goal doesn't exist."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "create_plan",
            {
                "goal_id": "nonexistent",
                "title": "Plan",
                "description": "Description",
            },
            mock_session,
        )

        assert is_error
        assert "Goal not found" in result

    @pytest.mark.asyncio
    async def test_create_plan_with_prefix(self, goal_storage, mock_session, monkeypatch):
        """Test plan creation with goal ID prefix."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="abcdef12-3456-7890-abcd-ef1234567890",
            title="Goal",
            description="",
            weight=5,
            status="active",
            acceptance_criteria=[],
            created_at=now,
            updated_at=now,
        )
        await goal_storage.save_goal(goal)

        result, is_error = await execute_goal_tool(
            "create_plan",
            {
                "goal_id": "abcdef12",  # Just prefix
                "title": "Plan",
                "description": "Description",
            },
            mock_session,
        )

        assert not is_error
        plans = await goal_storage.list_plans()
        assert plans[0].goal_id == goal.id


class TestCreateTodo:
    """Tests for create_todo tool."""

    @pytest.mark.asyncio
    async def test_create_todo_success(self, goal_storage, mock_session, monkeypatch):
        """Test successful todo creation."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        # Create goal and plan first
        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        plan = PlanData(
            id="plan-1", goal_id="goal-1", title="Plan", description="",
            status="active", created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan)

        result, is_error = await execute_goal_tool(
            "create_todo",
            {
                "plan_id": "plan-1",
                "title": "Write tests",
                "description": "Unit tests for the module",
            },
            mock_session,
        )

        assert not is_error
        assert "Created todo" in result
        assert "Write tests" in result

        # Verify todo and link were saved
        todos = await goal_storage.list_todos()
        assert len(todos) == 1

        plan_todos = await goal_storage.get_todos_for_plan("plan-1")
        assert len(plan_todos) == 1

    @pytest.mark.asyncio
    async def test_create_spike_todo(self, goal_storage, mock_session, monkeypatch):
        """Test creating a spike (timeboxed exploration)."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        plan = PlanData(
            id="plan-1", goal_id="goal-1", title="Plan", description="",
            status="active", created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan)

        result, is_error = await execute_goal_tool(
            "create_todo",
            {
                "plan_id": "plan-1",
                "title": "Investigate caching",
                "is_spike": True,
                "timebox_minutes": 30,
            },
            mock_session,
        )

        assert not is_error
        assert "Spike" in result
        assert "30 min" in result

        todos = await goal_storage.list_todos(include_spikes=True)
        assert todos[0].is_spike is True
        assert todos[0].timebox_minutes == 30

    @pytest.mark.asyncio
    async def test_create_todo_with_dependency(self, goal_storage, mock_session, monkeypatch):
        """Test creating todo with dependencies."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        plan = PlanData(
            id="plan-1", goal_id="goal-1", title="Plan", description="",
            status="active", created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan)

        # Create first todo
        first_todo = TodoData(
            id="todo-first", title="First task", description="",
            status="pending", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(first_todo)

        # Create dependent todo
        result, is_error = await execute_goal_tool(
            "create_todo",
            {
                "plan_id": "plan-1",
                "title": "Second task",
                "depends_on": ["todo-first"],
            },
            mock_session,
        )

        assert not is_error
        assert "Depends on" in result
        assert "First task" in result


class TestListGoals:
    """Tests for list_goals tool."""

    @pytest.mark.asyncio
    async def test_list_goals_empty(self, goal_storage, mock_session, monkeypatch):
        """Test listing when no goals exist."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "list_goals",
            {},
            mock_session,
        )

        assert not is_error
        assert "No goals found" in result

    @pytest.mark.asyncio
    async def test_list_goals_with_data(self, goal_storage, mock_session, monkeypatch):
        """Test listing goals."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Test Goal", description="Desc", weight=8,
            status="active", acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        result, is_error = await execute_goal_tool(
            "list_goals",
            {},
            mock_session,
        )

        assert not is_error
        assert "Test Goal" in result
        assert "8/10" in result


class TestListTodos:
    """Tests for list_todos tool."""

    @pytest.mark.asyncio
    async def test_list_todos_empty(self, goal_storage, mock_session, monkeypatch):
        """Test listing when no todos exist."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "list_todos",
            {},
            mock_session,
        )

        assert not is_error
        assert "No available todos" in result


class TestGetTodo:
    """Tests for get_todo tool."""

    @pytest.mark.asyncio
    async def test_get_todo_success(self, goal_storage, mock_session, monkeypatch):
        """Test getting a single todo's details."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Test Goal", description="", weight=7, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        plan = PlanData(
            id="plan-1", goal_id="goal-1", title="Test Plan", description="",
            status="active", created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan)

        todo = TodoData(
            id="todo-abc123", title="Write unit tests", description="Cover edge cases",
            status="pending", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)
        await goal_storage.save_todo_plan_link(TodoPlanLink(
            todo_id="todo-abc123", plan_id="plan-1", created_at=now,
        ))

        result, is_error = await execute_goal_tool(
            "get_todo",
            {"todo_id": "todo-abc123"},
            mock_session,
        )

        assert not is_error
        assert "Write unit tests" in result
        assert "todo-abc123" in result
        assert "pending" in result
        assert "Cover edge cases" in result
        assert "Test Plan" in result
        assert "Test Goal" in result
        assert "7/10" in result

    @pytest.mark.asyncio
    async def test_get_todo_with_prefix(self, goal_storage, mock_session, monkeypatch):
        """Test getting todo by ID prefix."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        todo = TodoData(
            id="abcdef12-3456-7890-abcd-ef1234567890", title="Task", description="",
            status="pending", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)

        result, is_error = await execute_goal_tool(
            "get_todo",
            {"todo_id": "abcdef12"},  # Just prefix
            mock_session,
        )

        assert not is_error
        assert "Task" in result
        assert "abcdef12-3456-7890-abcd-ef1234567890" in result

    @pytest.mark.asyncio
    async def test_get_todo_not_found(self, goal_storage, mock_session, monkeypatch):
        """Test error when todo doesn't exist."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "get_todo",
            {"todo_id": "nonexistent"},
            mock_session,
        )

        assert is_error
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_get_spike_todo(self, goal_storage, mock_session, monkeypatch):
        """Test getting a spike todo with timebox."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        todo = TodoData(
            id="spike-1", title="Investigate caching", description="",
            status="pending", is_spike=True, timebox_minutes=30,
            created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)

        result, is_error = await execute_goal_tool(
            "get_todo",
            {"todo_id": "spike-1"},
            mock_session,
        )

        assert not is_error
        assert "Spike" in result
        assert "30 min" in result

    @pytest.mark.asyncio
    async def test_get_todo_with_dependencies(self, goal_storage, mock_session, monkeypatch):
        """Test getting a todo that has dependencies."""
        from storage_schema import TodoDependency
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        dep_todo = TodoData(
            id="dep-todo-1", title="First task", description="",
            status="done", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(dep_todo)

        main_todo = TodoData(
            id="main-todo-1", title="Second task", description="",
            status="pending", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(main_todo)
        await goal_storage.save_todo_dependency(TodoDependency(
            todo_id="main-todo-1", depends_on_id="dep-todo-1", created_at=now,
        ))

        result, is_error = await execute_goal_tool(
            "get_todo",
            {"todo_id": "main-todo-1"},
            mock_session,
        )

        assert not is_error
        assert "Dependencies" in result
        assert "First task" in result
        assert "✓" in result  # Done status icon


class TestMarkTodoDone:
    """Tests for mark_todo_done tool."""

    @pytest.mark.asyncio
    async def test_mark_todo_done(self, goal_storage, mock_session, monkeypatch):
        """Test marking a todo as complete."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        plan = PlanData(
            id="plan-1", goal_id="goal-1", title="Plan", description="",
            status="active", created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan)

        todo = TodoData(
            id="todo-1", title="Test task", description="",
            status="pending", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)
        await goal_storage.save_todo_plan_link(TodoPlanLink(
            todo_id="todo-1", plan_id="plan-1", created_at=now,
        ))

        result, is_error = await execute_goal_tool(
            "mark_todo_done",
            {"todo_id": "todo-1"},
            mock_session,
        )

        assert not is_error
        assert "Marked complete" in result

        # Verify status changed
        updated_todo = await goal_storage.load_todo("todo-1")
        assert updated_todo.status == "completed"

    @pytest.mark.asyncio
    async def test_mark_todo_done_not_found(self, goal_storage, mock_session, monkeypatch):
        """Test error when todo doesn't exist."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "mark_todo_done",
            {"todo_id": "nonexistent"},
            mock_session,
        )

        assert is_error
        assert "not found" in result.lower()


class TestBindSession:
    """Tests for bind_session tool."""

    @pytest.mark.asyncio
    async def test_bind_session_to_goal(self, goal_storage, mock_session, monkeypatch):
        """Test binding session to a goal."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        result, is_error = await execute_goal_tool(
            "bind_session",
            {
                "entity_type": "goal",
                "entity_id": "goal-1",
                "role": "planning",
            },
            mock_session,
        )

        assert not is_error
        assert "bound to goal" in result
        assert "planning" in result

        # Verify binding was created
        bindings = await goal_storage.get_bindings_for_session(mock_session.id)
        assert len(bindings) == 1
        assert bindings[0].role == "planning"

    @pytest.mark.asyncio
    async def test_bind_session_invalid_entity_type(self, goal_storage, mock_session, monkeypatch):
        """Test error for invalid entity type."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "bind_session",
            {
                "entity_type": "invalid",
                "entity_id": "some-id",
            },
            mock_session,
        )

        assert is_error
        assert "goal" in result or "plan" in result or "todo" in result


class TestUnknownTool:
    """Test handling of unknown tool names."""

    @pytest.mark.asyncio
    async def test_unknown_tool(self, goal_storage, mock_session, monkeypatch):
        """Test error for unknown tool name."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "unknown_tool",
            {},
            mock_session,
        )

        assert is_error
        assert "Unknown" in result
