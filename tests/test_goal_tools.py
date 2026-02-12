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


class TestUpdateGoal:
    """Tests for update_goal tool."""

    @pytest.mark.asyncio
    async def test_update_goal_rename(self, goal_storage, mock_session, monkeypatch):
        """Test renaming a goal."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        # Create a goal first
        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-123",
            title="Original Title",
            description="Original description",
            weight=5,
            status="active",
            acceptance_criteria=["Criterion 1"],
            created_at=now,
            updated_at=now,
        )
        await goal_storage.save_goal(goal)

        # Update the title
        result, is_error = await execute_goal_tool(
            "update_goal",
            {
                "goal_id": "goal-123",
                "title": "New Title",
            },
            mock_session,
        )

        assert not is_error
        assert "Updated goal" in result
        assert "New Title" in result
        assert "title:" in result

        # Verify goal was updated
        updated_goal = await goal_storage.load_goal("goal-123")
        assert updated_goal.title == "New Title"
        assert updated_goal.description == "Original description"  # Unchanged

    @pytest.mark.asyncio
    async def test_update_goal_with_prefix(self, goal_storage, mock_session, monkeypatch):
        """Test updating goal by ID prefix."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="abcdef12-3456-7890-abcd-ef1234567890",
            title="Goal",
            description="Desc",
            weight=5,
            status="active",
            acceptance_criteria=[],
            created_at=now,
            updated_at=now,
        )
        await goal_storage.save_goal(goal)

        result, is_error = await execute_goal_tool(
            "update_goal",
            {
                "goal_id": "abcdef12",  # Just prefix
                "title": "Updated Goal",
            },
            mock_session,
        )

        assert not is_error
        updated_goal = await goal_storage.load_goal("abcdef12-3456-7890-abcd-ef1234567890")
        assert updated_goal.title == "Updated Goal"

    @pytest.mark.asyncio
    async def test_update_goal_weight(self, goal_storage, mock_session, monkeypatch):
        """Test updating goal weight."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        result, is_error = await execute_goal_tool(
            "update_goal",
            {
                "goal_id": "goal-1",
                "weight": 9,
            },
            mock_session,
        )

        assert not is_error
        assert "weight: 5 → 9" in result

        updated_goal = await goal_storage.load_goal("goal-1")
        assert updated_goal.weight == 9

    @pytest.mark.asyncio
    async def test_update_goal_status(self, goal_storage, mock_session, monkeypatch):
        """Test updating goal status."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        result, is_error = await execute_goal_tool(
            "update_goal",
            {
                "goal_id": "goal-1",
                "status": "completed",
            },
            mock_session,
        )

        assert not is_error
        assert "status: active → completed" in result

        updated_goal = await goal_storage.load_goal("goal-1")
        assert updated_goal.status == "completed"

    @pytest.mark.asyncio
    async def test_update_goal_acceptance_criteria(self, goal_storage, mock_session, monkeypatch):
        """Test updating acceptance criteria."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=["Old criterion"], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        result, is_error = await execute_goal_tool(
            "update_goal",
            {
                "goal_id": "goal-1",
                "acceptance_criteria": ["New criterion 1", "New criterion 2"],
            },
            mock_session,
        )

        assert not is_error
        assert "acceptance criteria updated (2 items)" in result

        updated_goal = await goal_storage.load_goal("goal-1")
        assert len(updated_goal.acceptance_criteria) == 2

    @pytest.mark.asyncio
    async def test_update_goal_multiple_fields(self, goal_storage, mock_session, monkeypatch):
        """Test updating multiple fields at once."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Old Title", description="Old desc", weight=3, status="active",
            acceptance_criteria=["Old"], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        result, is_error = await execute_goal_tool(
            "update_goal",
            {
                "goal_id": "goal-1",
                "title": "New Title",
                "description": "New description",
                "weight": 8,
            },
            mock_session,
        )

        assert not is_error
        assert "title:" in result
        assert "description updated" in result
        assert "weight: 3 → 8" in result

        updated_goal = await goal_storage.load_goal("goal-1")
        assert updated_goal.title == "New Title"
        assert updated_goal.description == "New description"
        assert updated_goal.weight == 8

    @pytest.mark.asyncio
    async def test_update_goal_not_found(self, goal_storage, mock_session, monkeypatch):
        """Test error when goal doesn't exist."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "update_goal",
            {
                "goal_id": "nonexistent",
                "title": "New Title",
            },
            mock_session,
        )

        assert is_error
        assert "Goal not found" in result

    @pytest.mark.asyncio
    async def test_update_goal_no_updates(self, goal_storage, mock_session, monkeypatch):
        """Test error when no valid updates provided."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        result, is_error = await execute_goal_tool(
            "update_goal",
            {
                "goal_id": "goal-1",
                # No other fields provided
            },
            mock_session,
        )

        assert is_error
        assert "No valid updates" in result

    @pytest.mark.asyncio
    async def test_update_goal_missing_goal_id(self, goal_storage, mock_session, monkeypatch):
        """Test error when goal_id is missing."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "update_goal",
            {
                "title": "New Title",
            },
            mock_session,
        )

        assert is_error
        assert "goal_id is required" in result

    @pytest.mark.asyncio
    async def test_update_goal_invalid_weight(self, goal_storage, mock_session, monkeypatch):
        """Test that invalid weight values are ignored."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        # Weight out of range should be ignored
        result, is_error = await execute_goal_tool(
            "update_goal",
            {
                "goal_id": "goal-1",
                "weight": 15,  # Out of range (1-10)
            },
            mock_session,
        )

        # Since weight is invalid and no other valid updates, this should error
        assert is_error
        assert "No valid updates" in result

        # Verify weight unchanged
        updated_goal = await goal_storage.load_goal("goal-1")
        assert updated_goal.weight == 5


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


class TestUpdatePlan:
    """Tests for update_plan tool."""

    @pytest.mark.asyncio
    async def test_update_plan_rename(self, goal_storage, mock_session, monkeypatch):
        """Test renaming a plan."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        plan = PlanData(
            id="plan-123", goal_id="goal-1", title="Original Title",
            description="Original description", status="active",
            created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan)

        result, is_error = await execute_goal_tool(
            "update_plan",
            {
                "plan_id": "plan-123",
                "title": "New Title",
            },
            mock_session,
        )

        assert not is_error
        assert "Updated plan" in result
        assert "New Title" in result
        assert "title:" in result

        updated_plan = await goal_storage.load_plan("plan-123")
        assert updated_plan.title == "New Title"
        assert updated_plan.description == "Original description"  # Unchanged

    @pytest.mark.asyncio
    async def test_update_plan_with_prefix(self, goal_storage, mock_session, monkeypatch):
        """Test updating plan by ID prefix."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        plan = PlanData(
            id="abcdef12-3456-7890-abcd-ef1234567890", goal_id="goal-1",
            title="Plan", description="", status="active",
            created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan)

        result, is_error = await execute_goal_tool(
            "update_plan",
            {
                "plan_id": "abcdef12",  # Just prefix
                "title": "Updated Plan",
            },
            mock_session,
        )

        assert not is_error
        updated_plan = await goal_storage.load_plan("abcdef12-3456-7890-abcd-ef1234567890")
        assert updated_plan.title == "Updated Plan"

    @pytest.mark.asyncio
    async def test_update_plan_status(self, goal_storage, mock_session, monkeypatch):
        """Test updating plan status."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        plan = PlanData(
            id="plan-1", goal_id="goal-1", title="Plan", description="",
            status="draft", created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan)

        result, is_error = await execute_goal_tool(
            "update_plan",
            {
                "plan_id": "plan-1",
                "status": "completed",
            },
            mock_session,
        )

        assert not is_error
        assert "status: draft → completed" in result

        updated_plan = await goal_storage.load_plan("plan-1")
        assert updated_plan.status == "completed"

    @pytest.mark.asyncio
    async def test_update_plan_reparent(self, goal_storage, mock_session, monkeypatch):
        """Test reparenting a plan to a different goal."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal1 = GoalData(
            id="goal-1", title="Original Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal1)

        goal2 = GoalData(
            id="goal-2", title="New Goal", description="", weight=7, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal2)

        plan = PlanData(
            id="plan-1", goal_id="goal-1", title="Plan", description="",
            status="active", created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan)

        result, is_error = await execute_goal_tool(
            "update_plan",
            {
                "plan_id": "plan-1",
                "goal_id": "goal-2",  # Reparent to goal-2
            },
            mock_session,
        )

        assert not is_error
        assert "goal:" in result
        assert "Original Goal" in result
        assert "New Goal" in result

        updated_plan = await goal_storage.load_plan("plan-1")
        assert updated_plan.goal_id == "goal-2"

    @pytest.mark.asyncio
    async def test_update_plan_reparent_with_prefix(self, goal_storage, mock_session, monkeypatch):
        """Test reparenting with goal ID prefix."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal1 = GoalData(
            id="goal-aaa111", title="Goal A", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal1)

        goal2 = GoalData(
            id="goal-bbb222", title="Goal B", description="", weight=7, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal2)

        plan = PlanData(
            id="plan-1", goal_id="goal-aaa111", title="Plan", description="",
            status="active", created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan)

        result, is_error = await execute_goal_tool(
            "update_plan",
            {
                "plan_id": "plan-1",
                "goal_id": "goal-bbb",  # Prefix
            },
            mock_session,
        )

        assert not is_error
        updated_plan = await goal_storage.load_plan("plan-1")
        assert updated_plan.goal_id == "goal-bbb222"

    @pytest.mark.asyncio
    async def test_update_plan_reparent_goal_not_found(self, goal_storage, mock_session, monkeypatch):
        """Test error when reparenting to nonexistent goal."""
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
            "update_plan",
            {
                "plan_id": "plan-1",
                "goal_id": "nonexistent",
            },
            mock_session,
        )

        assert is_error
        assert "Goal not found for reparenting" in result

    @pytest.mark.asyncio
    async def test_update_plan_multiple_fields(self, goal_storage, mock_session, monkeypatch):
        """Test updating multiple fields at once."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal1 = GoalData(
            id="goal-1", title="Goal 1", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal1)

        goal2 = GoalData(
            id="goal-2", title="Goal 2", description="", weight=7, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal2)

        plan = PlanData(
            id="plan-1", goal_id="goal-1", title="Old Title",
            description="Old desc", status="draft",
            created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan)

        result, is_error = await execute_goal_tool(
            "update_plan",
            {
                "plan_id": "plan-1",
                "title": "New Title",
                "description": "New description",
                "status": "active",
                "goal_id": "goal-2",
            },
            mock_session,
        )

        assert not is_error
        assert "title:" in result
        assert "description updated" in result
        assert "status: draft → active" in result
        assert "goal:" in result

        updated_plan = await goal_storage.load_plan("plan-1")
        assert updated_plan.title == "New Title"
        assert updated_plan.description == "New description"
        assert updated_plan.status == "active"
        assert updated_plan.goal_id == "goal-2"

    @pytest.mark.asyncio
    async def test_update_plan_not_found(self, goal_storage, mock_session, monkeypatch):
        """Test error when plan doesn't exist."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "update_plan",
            {
                "plan_id": "nonexistent",
                "title": "New Title",
            },
            mock_session,
        )

        assert is_error
        assert "Plan not found" in result

    @pytest.mark.asyncio
    async def test_update_plan_no_updates(self, goal_storage, mock_session, monkeypatch):
        """Test error when no valid updates provided."""
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
            "update_plan",
            {
                "plan_id": "plan-1",
                # No other fields provided
            },
            mock_session,
        )

        assert is_error
        assert "No valid updates" in result

    @pytest.mark.asyncio
    async def test_update_plan_missing_plan_id(self, goal_storage, mock_session, monkeypatch):
        """Test error when plan_id is missing."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "update_plan",
            {
                "title": "New Title",
            },
            mock_session,
        )

        assert is_error
        assert "plan_id is required" in result

    @pytest.mark.asyncio
    async def test_update_plan_invalid_status(self, goal_storage, mock_session, monkeypatch):
        """Test that invalid status values are ignored."""
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
            "update_plan",
            {
                "plan_id": "plan-1",
                "status": "invalid_status",
            },
            mock_session,
        )

        # Since status is invalid and no other valid updates, this should error
        assert is_error
        assert "No valid updates" in result

        # Verify status unchanged
        updated_plan = await goal_storage.load_plan("plan-1")
        assert updated_plan.status == "active"


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


class TestUpdateTodo:
    """Tests for update_todo tool."""

    @pytest.mark.asyncio
    async def test_update_todo_rename(self, goal_storage, mock_session, monkeypatch):
        """Test renaming a todo."""
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
            id="todo-123", title="Original Title", description="Original description",
            status="pending", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)
        await goal_storage.save_todo_plan_link(TodoPlanLink(
            todo_id="todo-123", plan_id="plan-1", created_at=now,
        ))

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "todo-123",
                "title": "New Title",
            },
            mock_session,
        )

        assert not is_error
        assert "Updated todo" in result
        assert "New Title" in result
        assert "title:" in result

        updated_todo = await goal_storage.load_todo("todo-123")
        assert updated_todo.title == "New Title"
        assert updated_todo.description == "Original description"  # Unchanged

    @pytest.mark.asyncio
    async def test_update_todo_with_prefix(self, goal_storage, mock_session, monkeypatch):
        """Test updating todo by ID prefix."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        todo = TodoData(
            id="abcdef12-3456-7890-abcd-ef1234567890", title="Todo", description="",
            status="pending", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "abcdef12",  # Just prefix
                "title": "Updated Todo",
            },
            mock_session,
        )

        assert not is_error
        updated_todo = await goal_storage.load_todo("abcdef12-3456-7890-abcd-ef1234567890")
        assert updated_todo.title == "Updated Todo"

    @pytest.mark.asyncio
    async def test_update_todo_status(self, goal_storage, mock_session, monkeypatch):
        """Test updating todo status."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        todo = TodoData(
            id="todo-1", title="Todo", description="", status="pending",
            is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "todo-1",
                "status": "in_progress",
            },
            mock_session,
        )

        assert not is_error
        assert "status: pending → in_progress" in result

        updated_todo = await goal_storage.load_todo("todo-1")
        assert updated_todo.status == "in_progress"

    @pytest.mark.asyncio
    async def test_update_todo_convert_to_spike(self, goal_storage, mock_session, monkeypatch):
        """Test converting a regular todo to a spike."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        todo = TodoData(
            id="todo-1", title="Todo", description="", status="pending",
            is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "todo-1",
                "is_spike": True,
                "timebox_minutes": 30,
            },
            mock_session,
        )

        assert not is_error
        assert "converted to spike" in result
        assert "Spike" in result
        assert "30 min" in result

        updated_todo = await goal_storage.load_todo("todo-1")
        assert updated_todo.is_spike is True
        assert updated_todo.timebox_minutes == 30

    @pytest.mark.asyncio
    async def test_update_todo_convert_from_spike(self, goal_storage, mock_session, monkeypatch):
        """Test converting a spike back to a regular todo."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        todo = TodoData(
            id="todo-1", title="Todo", description="", status="pending",
            is_spike=True, timebox_minutes=30, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "todo-1",
                "is_spike": False,
            },
            mock_session,
        )

        assert not is_error
        assert "converted from spike to regular todo" in result

        updated_todo = await goal_storage.load_todo("todo-1")
        assert updated_todo.is_spike is False
        assert updated_todo.timebox_minutes is None  # Timebox cleared

    @pytest.mark.asyncio
    async def test_update_todo_timebox(self, goal_storage, mock_session, monkeypatch):
        """Test updating a spike's timebox."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        todo = TodoData(
            id="todo-1", title="Todo", description="", status="pending",
            is_spike=True, timebox_minutes=30, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "todo-1",
                "timebox_minutes": 60,
            },
            mock_session,
        )

        assert not is_error
        assert "timebox: 30 → 60 min" in result

        updated_todo = await goal_storage.load_todo("todo-1")
        assert updated_todo.timebox_minutes == 60

    @pytest.mark.asyncio
    async def test_update_todo_remove_timebox(self, goal_storage, mock_session, monkeypatch):
        """Test removing a spike's timebox."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        todo = TodoData(
            id="todo-1", title="Todo", description="", status="pending",
            is_spike=True, timebox_minutes=30, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "todo-1",
                "timebox_minutes": None,
            },
            mock_session,
        )

        assert not is_error
        assert "timebox removed" in result

        updated_todo = await goal_storage.load_todo("todo-1")
        assert updated_todo.timebox_minutes is None

    @pytest.mark.asyncio
    async def test_update_todo_reparent(self, goal_storage, mock_session, monkeypatch):
        """Test reparenting a todo to a different plan."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        plan1 = PlanData(
            id="plan-1", goal_id="goal-1", title="Original Plan",
            description="", status="active", created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan1)

        plan2 = PlanData(
            id="plan-2", goal_id="goal-1", title="New Plan",
            description="", status="active", created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan2)

        todo = TodoData(
            id="todo-1", title="Todo", description="", status="pending",
            is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)
        await goal_storage.save_todo_plan_link(TodoPlanLink(
            todo_id="todo-1", plan_id="plan-1", created_at=now,
        ))

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "todo-1",
                "plan_id": "plan-2",
            },
            mock_session,
        )

        assert not is_error
        assert "plan:" in result
        assert "Original Plan" in result
        assert "New Plan" in result

        # Verify the todo is now linked to plan-2
        plan_ids = await goal_storage.get_plans_for_todo("todo-1")
        assert len(plan_ids) == 1
        assert plan_ids[0] == "plan-2"

    @pytest.mark.asyncio
    async def test_update_todo_reparent_with_prefix(self, goal_storage, mock_session, monkeypatch):
        """Test reparenting with plan ID prefix."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        goal = GoalData(
            id="goal-1", title="Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at=now, updated_at=now,
        )
        await goal_storage.save_goal(goal)

        plan1 = PlanData(
            id="plan-aaa111", goal_id="goal-1", title="Plan A",
            description="", status="active", created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan1)

        plan2 = PlanData(
            id="plan-bbb222", goal_id="goal-1", title="Plan B",
            description="", status="active", created_at=now, updated_at=now,
        )
        await goal_storage.save_plan(plan2)

        todo = TodoData(
            id="todo-1", title="Todo", description="", status="pending",
            is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)
        await goal_storage.save_todo_plan_link(TodoPlanLink(
            todo_id="todo-1", plan_id="plan-aaa111", created_at=now,
        ))

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "todo-1",
                "plan_id": "plan-bbb",  # Prefix
            },
            mock_session,
        )

        assert not is_error
        plan_ids = await goal_storage.get_plans_for_todo("todo-1")
        assert plan_ids[0] == "plan-bbb222"

    @pytest.mark.asyncio
    async def test_update_todo_reparent_plan_not_found(self, goal_storage, mock_session, monkeypatch):
        """Test error when reparenting to nonexistent plan."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        todo = TodoData(
            id="todo-1", title="Todo", description="", status="pending",
            is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "todo-1",
                "plan_id": "nonexistent",
            },
            mock_session,
        )

        assert is_error
        assert "Plan not found for reparenting" in result

    @pytest.mark.asyncio
    async def test_update_todo_multiple_fields(self, goal_storage, mock_session, monkeypatch):
        """Test updating multiple fields at once."""
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
            id="todo-1", title="Old Title", description="Old desc",
            status="pending", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)
        await goal_storage.save_todo_plan_link(TodoPlanLink(
            todo_id="todo-1", plan_id="plan-1", created_at=now,
        ))

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "todo-1",
                "title": "New Title",
                "description": "New description",
                "status": "in_progress",
            },
            mock_session,
        )

        assert not is_error
        assert "title:" in result
        assert "description updated" in result
        assert "status: pending → in_progress" in result

        updated_todo = await goal_storage.load_todo("todo-1")
        assert updated_todo.title == "New Title"
        assert updated_todo.description == "New description"
        assert updated_todo.status == "in_progress"

    @pytest.mark.asyncio
    async def test_update_todo_not_found(self, goal_storage, mock_session, monkeypatch):
        """Test error when todo doesn't exist."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "nonexistent",
                "title": "New Title",
            },
            mock_session,
        )

        assert is_error
        assert "Todo not found" in result

    @pytest.mark.asyncio
    async def test_update_todo_no_updates(self, goal_storage, mock_session, monkeypatch):
        """Test error when no valid updates provided."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        todo = TodoData(
            id="todo-1", title="Todo", description="", status="pending",
            is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "todo-1",
                # No other fields provided
            },
            mock_session,
        )

        assert is_error
        assert "No valid updates" in result

    @pytest.mark.asyncio
    async def test_update_todo_missing_todo_id(self, goal_storage, mock_session, monkeypatch):
        """Test error when todo_id is missing."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "title": "New Title",
            },
            mock_session,
        )

        assert is_error
        assert "todo_id is required" in result

    @pytest.mark.asyncio
    async def test_update_todo_invalid_status(self, goal_storage, mock_session, monkeypatch):
        """Test that invalid status values are ignored."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        todo = TodoData(
            id="todo-1", title="Todo", description="", status="pending",
            is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)

        result, is_error = await execute_goal_tool(
            "update_todo",
            {
                "todo_id": "todo-1",
                "status": "invalid_status",
            },
            mock_session,
        )

        # Since status is invalid and no other valid updates, this should error
        assert is_error
        assert "No valid updates" in result

        # Verify status unchanged
        updated_todo = await goal_storage.load_todo("todo-1")
        assert updated_todo.status == "pending"


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


class TestListAllBindings:
    """Tests for list_all_bindings tool."""

    @pytest.mark.asyncio
    async def test_list_all_bindings_summary(self, goal_storage, mock_session, monkeypatch):
        """Test list_all_bindings in summary mode."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        # Mock session storage to return empty sessions
        async def mock_get_session_ids_set():
            return set()
        monkeypatch.setattr("core.goal_tools._get_session_ids_set", mock_get_session_ids_set)

        result, is_error = await execute_goal_tool(
            "list_all_bindings",
            {"mode": "summary"},
            mock_session,
        )

        assert not is_error
        assert "Session Bindings Summary" in result

    @pytest.mark.asyncio
    async def test_list_all_bindings_with_filter(self, goal_storage, mock_session, monkeypatch):
        """Test list_all_bindings with orphaned filter."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        async def mock_get_session_ids_set():
            return set()
        monkeypatch.setattr("core.goal_tools._get_session_ids_set", mock_get_session_ids_set)

        result, is_error = await execute_goal_tool(
            "list_all_bindings",
            {"filter": "orphaned", "mode": "detail"},
            mock_session,
        )

        assert not is_error
        # With no bindings, should return a message
        assert "orphaned" in result.lower() or "no " in result.lower()

    @pytest.mark.asyncio
    async def test_list_all_bindings_goal_not_found(self, goal_storage, mock_session, monkeypatch):
        """Test list_all_bindings with invalid goal_id filter."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        async def mock_get_session_ids_set():
            return set()
        monkeypatch.setattr("core.goal_tools._get_session_ids_set", mock_get_session_ids_set)

        result, is_error = await execute_goal_tool(
            "list_all_bindings",
            {"goal_id": "nonexistent"},
            mock_session,
        )

        assert is_error
        assert "Goal not found" in result


class TestRebindSession:
    """Tests for rebind_session tool."""

    @pytest.mark.asyncio
    async def test_rebind_session_missing_session_id(self, goal_storage, mock_session, monkeypatch):
        """Test error when session_id is missing."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "rebind_session",
            {
                "entity_type": "todo",
                "entity_id": "abc123",
            },
            mock_session,
        )

        assert is_error
        assert "session_id is required" in result

    @pytest.mark.asyncio
    async def test_rebind_session_invalid_entity_type(self, goal_storage, mock_session, monkeypatch):
        """Test error with invalid entity_type."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "rebind_session",
            {
                "session_id": "test123",
                "entity_type": "invalid",
                "entity_id": "abc123",
            },
            mock_session,
        )

        assert is_error
        assert "entity_type" in result


class TestBindEntityToSessions:
    """Tests for bind_entity_to_sessions tool."""

    @pytest.mark.asyncio
    async def test_bind_entity_missing_session_ids(self, goal_storage, mock_session, monkeypatch):
        """Test error when session_ids is missing."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "bind_entity_to_sessions",
            {
                "entity_type": "todo",
                "entity_id": "abc123",
            },
            mock_session,
        )

        assert is_error
        assert "session_ids is required" in result

    @pytest.mark.asyncio
    async def test_bind_entity_invalid_entity_type(self, goal_storage, mock_session, monkeypatch):
        """Test error with invalid entity_type."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "bind_entity_to_sessions",
            {
                "entity_type": "invalid",
                "entity_id": "abc123",
                "session_ids": ["sess1"],
            },
            mock_session,
        )

        assert is_error
        assert "entity_type" in result


class TestUnbindSessions:
    """Tests for unbind_sessions tool."""

    @pytest.mark.asyncio
    async def test_unbind_sessions_no_params(self, goal_storage, mock_session, monkeypatch):
        """Test error when neither session_ids nor orphans_only is provided."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        async def mock_get_session_ids_set():
            return set()
        monkeypatch.setattr("core.goal_tools._get_session_ids_set", mock_get_session_ids_set)

        result, is_error = await execute_goal_tool(
            "unbind_sessions",
            {},
            mock_session,
        )

        assert is_error
        assert "session_ids" in result or "orphans_only" in result

    @pytest.mark.asyncio
    async def test_unbind_sessions_orphans_only_empty(self, goal_storage, mock_session, monkeypatch):
        """Test unbind_sessions with orphans_only when no orphans exist."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        async def mock_get_session_ids_set():
            return set()
        monkeypatch.setattr("core.goal_tools._get_session_ids_set", mock_get_session_ids_set)

        result, is_error = await execute_goal_tool(
            "unbind_sessions",
            {"orphans_only": True},
            mock_session,
        )

        # Should succeed but find no orphans
        assert not is_error
        assert "No orphaned" in result or "0" in result or "no" in result.lower()


class TestDeleteTodo:
    """Tests for delete_todo tool."""

    @pytest.mark.asyncio
    async def test_delete_todo_success(self, goal_storage, mock_session, monkeypatch):
        """Test successful todo deletion."""
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
            id="todo-123", title="Task to delete", description="",
            status="pending", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)
        await goal_storage.save_todo_plan_link(TodoPlanLink(
            todo_id="todo-123", plan_id="plan-1", created_at=now,
        ))

        result, is_error = await execute_goal_tool(
            "delete_todo",
            {"todo_id": "todo-123"},
            mock_session,
        )

        assert not is_error
        assert "Deleted todo" in result
        assert "Task to delete" in result

        # Verify todo was deleted
        deleted_todo = await goal_storage.load_todo("todo-123")
        assert deleted_todo is None

        # Verify plan link was deleted
        plan_todos = await goal_storage.get_todos_for_plan("plan-1")
        assert "todo-123" not in plan_todos

    @pytest.mark.asyncio
    async def test_delete_todo_with_prefix(self, goal_storage, mock_session, monkeypatch):
        """Test deleting todo by ID prefix."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        todo = TodoData(
            id="abcdef12-3456-7890-abcd-ef1234567890", title="Task", description="",
            status="pending", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo)

        result, is_error = await execute_goal_tool(
            "delete_todo",
            {"todo_id": "abcdef12"},  # Just prefix
            mock_session,
        )

        assert not is_error
        deleted_todo = await goal_storage.load_todo("abcdef12-3456-7890-abcd-ef1234567890")
        assert deleted_todo is None

    @pytest.mark.asyncio
    async def test_delete_todo_not_found(self, goal_storage, mock_session, monkeypatch):
        """Test error when todo doesn't exist."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "delete_todo",
            {"todo_id": "nonexistent"},
            mock_session,
        )

        assert is_error
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_todo_missing_id(self, goal_storage, mock_session, monkeypatch):
        """Test error when todo_id is missing."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        result, is_error = await execute_goal_tool(
            "delete_todo",
            {},
            mock_session,
        )

        assert is_error
        assert "todo_id is required" in result

    @pytest.mark.asyncio
    async def test_delete_todo_with_dependencies(self, goal_storage, mock_session, monkeypatch):
        """Test deleting a todo that has dependencies."""
        from storage_schema import TodoDependency
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()

        # Create a todo that will depend on the one we delete
        dependent_todo = TodoData(
            id="dependent-todo", title="Dependent task", description="",
            status="pending", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(dependent_todo)

        # Create the todo to delete (with a dependency on it)
        todo_to_delete = TodoData(
            id="todo-to-delete", title="Task to delete", description="",
            status="pending", is_spike=False, created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(todo_to_delete)

        # dependent_todo depends on todo_to_delete
        await goal_storage.save_todo_dependency(TodoDependency(
            todo_id="dependent-todo", depends_on_id="todo-to-delete", created_at=now,
        ))

        result, is_error = await execute_goal_tool(
            "delete_todo",
            {"todo_id": "todo-to-delete"},
            mock_session,
        )

        assert not is_error
        assert "Deleted todo" in result
        assert "dependency" in result.lower()

        # Verify todo was deleted
        deleted_todo = await goal_storage.load_todo("todo-to-delete")
        assert deleted_todo is None

        # Verify dependency was cleaned up
        deps = await goal_storage.get_dependencies("dependent-todo")
        assert "todo-to-delete" not in deps

    @pytest.mark.asyncio
    async def test_delete_spike_todo(self, goal_storage, mock_session, monkeypatch):
        """Test deleting a spike todo."""
        monkeypatch.setattr("core.goal_tools.get_goal_storage", make_async_storage_getter(goal_storage))

        now = datetime.now().isoformat()
        spike = TodoData(
            id="spike-123", title="Spike to delete", description="",
            status="pending", is_spike=True, timebox_minutes=30,
            created_at=now, updated_at=now,
        )
        await goal_storage.save_todo(spike)

        result, is_error = await execute_goal_tool(
            "delete_todo",
            {"todo_id": "spike-123"},
            mock_session,
        )

        assert not is_error
        assert "Deleted todo" in result

        # Verify spike was deleted
        deleted_spike = await goal_storage.load_todo("spike-123")
        assert deleted_spike is None


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
