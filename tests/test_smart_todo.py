"""Tests for smart_todo.py - LLM-assisted todo placement."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from core.smart_todo import (
    create_todo_with_llm_placement,
    suggest_plan_for_todo,
    get_plans_summary_for_llm,
)
from storage_schema import GoalData, PlanData, TodoData
from models import TextDelta


class MockRunner:
    """Mock LLM runner for testing."""

    def __init__(self, response: str):
        self.response = response
        self.calls = []

    async def stream_response(self, messages, prompt, disable_tools=False):
        self.calls.append((messages, prompt, disable_tools))
        # Yield the response as TextDelta events (using actual TextDelta)
        for char in self.response:
            yield TextDelta(text=char)


@pytest.fixture
def mock_storage(monkeypatch):
    """Set up mock storage with test data."""
    goals = [
        GoalData(
            id="goal-1",
            title="Build Authentication",
            description="Implement user authentication system",
            weight=8,
            status="active",
            acceptance_criteria=["Users can log in", "Sessions are secure"],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        ),
        GoalData(
            id="goal-2",
            title="Build Dashboard",
            description="Create analytics dashboard",
            weight=5,
            status="active",
            acceptance_criteria=["Shows charts", "Real-time data"],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        ),
    ]

    plans = [
        PlanData(
            id="plan-auth-core",
            goal_id="goal-1",
            title="Core Auth Implementation",
            description="Implement basic username/password authentication",
            status="active",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        ),
        PlanData(
            id="plan-auth-oauth",
            goal_id="goal-1",
            title="OAuth Integration",
            description="Add OAuth providers like Google and GitHub",
            status="draft",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        ),
        PlanData(
            id="plan-dashboard-charts",
            goal_id="goal-2",
            title="Chart Components",
            description="Build reusable chart components",
            status="active",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        ),
    ]

    saved_todos = []
    saved_links = []

    class MockStorage:
        async def list_goals(self):
            return goals

        async def list_plans(self):
            return plans

        async def list_todos(self, include_spikes=False):
            return []

        async def save_todo(self, todo):
            saved_todos.append(todo)

        async def save_todo_plan_link(self, link):
            saved_links.append(link)

    mock = MockStorage()
    mock.saved_todos = saved_todos
    mock.saved_links = saved_links

    # Patch get_goal_storage to return our mock
    async def get_mock_storage():
        return mock

    import core.smart_todo
    monkeypatch.setattr(core.smart_todo, "get_goal_storage", get_mock_storage)

    return mock


class TestGetPlansSummaryForLLM:
    """Tests for get_plans_summary_for_llm."""

    @pytest.mark.asyncio
    async def test_returns_formatted_summary(self, mock_storage):
        """Should return a formatted summary of goals and plans."""
        summary, plans_by_id, goals_by_id = await get_plans_summary_for_llm()

        # Should include goal titles
        assert "Build Authentication" in summary
        assert "Build Dashboard" in summary

        # Should include plan IDs and titles
        assert "plan-auth-core" in summary
        assert "Core Auth Implementation" in summary
        assert "plan-dashboard-charts" in summary
        assert "Chart Components" in summary

        # Should have correct lookups
        assert len(plans_by_id) == 3
        assert "plan-auth-core" in plans_by_id
        assert len(goals_by_id) >= 2


class TestCreateTodoWithLLMPlacement:
    """Tests for create_todo_with_llm_placement."""

    @pytest.mark.asyncio
    async def test_creates_todo_with_matched_plan(self, mock_storage):
        """Should create todo linked to LLM-selected plan."""
        runner = MockRunner("plan-auth-core")

        todo, plan, message = await create_todo_with_llm_placement(
            title="Add password hashing",
            description="Use bcrypt for secure password storage",
            llm_runner=runner,
        )

        # Should have created a todo
        assert todo is not None
        assert todo.title == "Add password hashing"
        assert todo.description == "Use bcrypt for secure password storage"
        assert todo.status == "pending"
        assert not todo.is_spike

        # Should have matched to auth plan
        assert plan is not None
        assert plan.id == "plan-auth-core"

        # Should have saved todo and link
        assert len(mock_storage.saved_todos) == 1
        assert len(mock_storage.saved_links) == 1
        assert mock_storage.saved_links[0].plan_id == "plan-auth-core"

        # Message should indicate success
        assert "Created todo" in message
        assert "plan-auth-core" in message or "Core Auth" in message

    @pytest.mark.asyncio
    async def test_creates_spike_todo(self, mock_storage):
        """Should create spike todo with timebox."""
        runner = MockRunner("plan-dashboard-charts")

        todo, plan, message = await create_todo_with_llm_placement(
            title="Research charting libraries",
            description="Evaluate D3.js vs Chart.js",
            is_spike=True,
            timebox_minutes=60,
            llm_runner=runner,
        )

        assert todo is not None
        assert todo.is_spike is True
        assert todo.timebox_minutes == 60
        assert "Spike" in message

    @pytest.mark.asyncio
    async def test_returns_error_when_no_plans(self, mock_storage, monkeypatch):
        """Should return error when no plans exist."""
        # Override to return empty plans
        async def list_no_plans():
            return []

        mock_storage.list_plans = list_no_plans

        runner = MockRunner("some-plan")

        todo, plan, message = await create_todo_with_llm_placement(
            title="Some task",
            llm_runner=runner,
        )

        assert todo is None
        assert plan is None
        assert "No active plans" in message

    @pytest.mark.asyncio
    async def test_returns_error_when_llm_says_none(self, mock_storage):
        """Should return error when LLM can't find a matching plan."""
        runner = MockRunner("NONE")

        todo, plan, message = await create_todo_with_llm_placement(
            title="Unrelated task about cooking",
            description="Make a cake",
            llm_runner=runner,
        )

        assert todo is None
        assert plan is None
        assert "No matching plan" in message

    @pytest.mark.asyncio
    async def test_returns_error_without_llm_runner(self, mock_storage):
        """Should return error when no LLM runner provided."""
        todo, plan, message = await create_todo_with_llm_placement(
            title="Some task",
            llm_runner=None,
        )

        assert todo is None
        assert plan is None
        assert "LLM runner not available" in message

    @pytest.mark.asyncio
    async def test_returns_error_for_empty_title(self, mock_storage):
        """Should return error for empty title."""
        runner = MockRunner("plan-auth-core")

        todo, plan, message = await create_todo_with_llm_placement(
            title="   ",
            llm_runner=runner,
        )

        assert todo is None
        assert "title is required" in message

    @pytest.mark.asyncio
    async def test_truncates_long_title(self, mock_storage):
        """Should truncate title to 80 chars."""
        runner = MockRunner("plan-auth-core")
        long_title = "A" * 100

        todo, plan, message = await create_todo_with_llm_placement(
            title=long_title,
            llm_runner=runner,
        )

        assert todo is not None
        assert len(todo.title) == 80


class TestSuggestPlanForTodo:
    """Tests for suggest_plan_for_todo."""

    @pytest.mark.asyncio
    async def test_suggests_matching_plan(self, mock_storage):
        """Should suggest a plan without creating todo."""
        runner = MockRunner("plan-auth-oauth")

        plan, goal, message = await suggest_plan_for_todo(
            title="Add GitHub OAuth",
            description="Implement GitHub as OAuth provider",
            llm_runner=runner,
        )

        assert plan is not None
        assert plan.id == "plan-auth-oauth"
        assert goal is not None
        assert goal.id == "goal-1"

        # Should NOT have created any todos
        assert len(mock_storage.saved_todos) == 0

    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self, mock_storage):
        """Should return None when no plan matches."""
        runner = MockRunner("NONE")

        plan, goal, message = await suggest_plan_for_todo(
            title="Random unrelated task",
            llm_runner=runner,
        )

        assert plan is None
        assert goal is None
        assert "No matching plan" in message
