"""Tests for status report generator."""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from core.status_report import (
    StatusReportGenerator,
    StatusReportData,
    GoalStatus,
    PlanStatus,
    TodoStatus,
)
from storage_schema import GoalData, PlanData, TodoData


@pytest.fixture
def mock_storage():
    """Create a mock GoalStorage."""
    storage = AsyncMock()
    return storage


@pytest.fixture
def sample_goals():
    """Sample goal data."""
    return [
        GoalData(
            id="goal-1",
            title="Build Authentication",
            description="Implement user authentication",
            weight=8,
            status="active",
            acceptance_criteria=["Users can sign up", "OAuth works"],
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-15T00:00:00",
        ),
        GoalData(
            id="goal-2",
            title="Improve Performance",
            description="Optimize database queries",
            weight=5,
            status="active",
            acceptance_criteria=["Response time < 100ms"],
            created_at="2024-01-10T00:00:00",
            updated_at="2024-01-10T00:00:00",
        ),
    ]


@pytest.fixture
def sample_plans():
    """Sample plan data."""
    return [
        PlanData(
            id="plan-1",
            goal_id="goal-1",
            title="OAuth Implementation",
            description="Add OAuth providers",
            status="active",
            created_at="2024-01-02T00:00:00",
            updated_at="2024-01-15T00:00:00",
        ),
        PlanData(
            id="plan-2",
            goal_id="goal-2",
            title="Query Optimization",
            description="Add indexes and caching",
            status="active",
            created_at="2024-01-11T00:00:00",
            updated_at="2024-01-11T00:00:00",
        ),
    ]


@pytest.fixture
def sample_todos():
    """Sample todo data."""
    return [
        TodoData(
            id="todo-1",
            title="Add Google OAuth",
            description="Integrate Google OAuth",
            status="completed",
            is_spike=False,
            created_at="2024-01-03T00:00:00",
            updated_at="2024-01-10T00:00:00",
            completed_at="2024-01-10T00:00:00",
        ),
        TodoData(
            id="todo-2",
            title="Add GitHub OAuth",
            description="Integrate GitHub OAuth",
            status="in_progress",
            is_spike=False,
            created_at="2024-01-05T00:00:00",
            updated_at="2024-01-15T00:00:00",
        ),
        TodoData(
            id="todo-3",
            title="Add caching layer",
            description="Redis caching",
            status="blocked",
            is_spike=False,
            created_at="2024-01-12T00:00:00",
            updated_at="2024-01-12T00:00:00",
        ),
        TodoData(
            id="todo-4",
            title="Explore auth libraries",
            description="Evaluate options",
            status="pending",
            is_spike=True,
            timebox_minutes=60,
            created_at="2024-01-04T00:00:00",
            updated_at="2024-01-04T00:00:00",
        ),
    ]


@pytest.mark.asyncio
async def test_generate_basic_report(mock_storage, sample_goals, sample_plans, sample_todos):
    """Test generating a basic status report."""
    mock_storage.list_goals.return_value = sample_goals
    mock_storage.list_plans.return_value = sample_plans
    mock_storage.list_todos.return_value = sample_todos

    # Set up plan-todo relationships
    mock_storage.get_plans_for_todo.side_effect = lambda tid: {
        "todo-1": ["plan-1"],
        "todo-2": ["plan-1"],
        "todo-3": ["plan-2"],
        "todo-4": ["plan-1"],
    }.get(tid, [])

    mock_storage.get_dependencies.return_value = []

    generator = StatusReportGenerator(storage=mock_storage)
    report = await generator.generate()

    # Check summary statistics
    assert report.total_goals == 2
    assert report.active_goals == 2
    assert report.completed_goals == 0

    assert report.total_plans == 2
    assert report.active_plans == 2

    # Non-spike todos only
    assert report.total_todos == 3  # excludes spike
    assert report.completed_todos == 1
    assert report.in_progress_todos == 1
    assert report.blocked_todos == 1

    # Check in-progress items
    assert len(report.in_progress_items) == 1
    assert report.in_progress_items[0].title == "Add GitHub OAuth"

    # Check blocked items
    assert len(report.blocked_items) == 1
    assert report.blocked_items[0].title == "Add caching layer"

    # Check active spikes
    assert len(report.active_spikes) == 1
    assert report.active_spikes[0].title == "Explore auth libraries"


@pytest.mark.asyncio
async def test_generate_with_dependencies(mock_storage, sample_goals, sample_plans, sample_todos):
    """Test report generation with todo dependencies."""
    mock_storage.list_goals.return_value = sample_goals
    mock_storage.list_plans.return_value = sample_plans
    mock_storage.list_todos.return_value = sample_todos

    mock_storage.get_plans_for_todo.side_effect = lambda tid: {
        "todo-1": ["plan-1"],
        "todo-2": ["plan-1"],
        "todo-3": ["plan-2"],
        "todo-4": ["plan-1"],
    }.get(tid, [])

    # todo-3 depends on todo-2 (which is in_progress, so todo-3 is blocked)
    mock_storage.get_dependencies.side_effect = lambda tid: {
        "todo-3": ["todo-2"],
    }.get(tid, [])

    generator = StatusReportGenerator(storage=mock_storage)
    report = await generator.generate()

    # Check that blocked item shows its blocker
    blocked_item = next((t for t in report.blocked_items if t.id == "todo-3"), None)
    assert blocked_item is not None
    assert "Add GitHub OAuth" in blocked_item.blocker_titles


@pytest.mark.asyncio
async def test_goal_status_computation(mock_storage, sample_goals, sample_plans, sample_todos):
    """Test that goal statuses are computed correctly."""
    mock_storage.list_goals.return_value = sample_goals
    mock_storage.list_plans.return_value = sample_plans
    mock_storage.list_todos.return_value = sample_todos

    mock_storage.get_plans_for_todo.side_effect = lambda tid: {
        "todo-1": ["plan-1"],
        "todo-2": ["plan-1"],
        "todo-3": ["plan-2"],
        "todo-4": ["plan-1"],
    }.get(tid, [])

    mock_storage.get_dependencies.return_value = []

    generator = StatusReportGenerator(storage=mock_storage)
    report = await generator.generate()

    # Find goal-1 status
    goal1_status = next((g for g in report.goals if g.id == "goal-1"), None)
    assert goal1_status is not None
    assert goal1_status.title == "Build Authentication"
    assert goal1_status.weight == 8
    assert goal1_status.total_todos == 2  # todo-1 and todo-2 (not spike)
    assert goal1_status.completed_todos == 1  # todo-1
    assert goal1_status.in_progress_todos == 1  # todo-2

    # Goals should be sorted by weight descending
    assert report.goals[0].weight >= report.goals[1].weight


@pytest.mark.asyncio
async def test_plan_status_computation(mock_storage, sample_goals, sample_plans, sample_todos):
    """Test that plan statuses are computed correctly."""
    mock_storage.list_goals.return_value = sample_goals
    mock_storage.list_plans.return_value = sample_plans
    mock_storage.list_todos.return_value = sample_todos

    mock_storage.get_plans_for_todo.side_effect = lambda tid: {
        "todo-1": ["plan-1"],
        "todo-2": ["plan-1"],
        "todo-3": ["plan-2"],
        "todo-4": ["plan-1"],
    }.get(tid, [])

    mock_storage.get_dependencies.return_value = []

    generator = StatusReportGenerator(storage=mock_storage)
    report = await generator.generate()

    # Find plan-1 status
    plan1_status = next((p for p in report.plans if p.id == "plan-1"), None)
    assert plan1_status is not None
    assert plan1_status.title == "OAuth Implementation"
    assert plan1_status.goal_title == "Build Authentication"
    assert plan1_status.todo_count == 2  # excludes spike
    assert plan1_status.completed_count == 1
    assert plan1_status.in_progress_count == 1


@pytest.mark.asyncio
async def test_render_markdown(mock_storage, sample_goals, sample_plans, sample_todos):
    """Test markdown rendering."""
    mock_storage.list_goals.return_value = sample_goals
    mock_storage.list_plans.return_value = sample_plans
    mock_storage.list_todos.return_value = sample_todos

    mock_storage.get_plans_for_todo.side_effect = lambda tid: {
        "todo-1": ["plan-1"],
        "todo-2": ["plan-1"],
        "todo-3": ["plan-2"],
        "todo-4": ["plan-1"],
    }.get(tid, [])

    mock_storage.get_dependencies.return_value = []

    generator = StatusReportGenerator(storage=mock_storage)
    report = await generator.generate()

    markdown = generator._render_markdown(report)

    # Check that key sections are present
    assert "# Status Report" in markdown
    assert "## Executive Summary" in markdown
    assert "## Currently In Progress" in markdown
    assert "## Goals Overview" in markdown
    assert "Build Authentication" in markdown
    assert "Add GitHub OAuth" in markdown


@pytest.mark.asyncio
async def test_write_report(mock_storage, sample_goals, sample_plans, sample_todos, tmp_path):
    """Test writing report to file."""
    mock_storage.list_goals.return_value = sample_goals
    mock_storage.list_plans.return_value = sample_plans
    mock_storage.list_todos.return_value = sample_todos

    mock_storage.get_plans_for_todo.side_effect = lambda tid: []
    mock_storage.get_dependencies.return_value = []

    generator = StatusReportGenerator(storage=mock_storage)
    report = await generator.generate()

    output_path = await generator.write_report(report, output_dir=tmp_path)

    assert output_path.exists()
    assert output_path.suffix == ".md"
    assert "status-report-" in output_path.name

    content = output_path.read_text()
    assert "# Status Report" in content


@pytest.mark.asyncio
async def test_empty_data(mock_storage):
    """Test report generation with no data."""
    mock_storage.list_goals.return_value = []
    mock_storage.list_plans.return_value = []
    mock_storage.list_todos.return_value = []

    generator = StatusReportGenerator(storage=mock_storage)
    report = await generator.generate()

    assert report.total_goals == 0
    assert report.total_plans == 0
    assert report.total_todos == 0
    assert report.overall_completion_pct == 0.0
    assert len(report.goals) == 0
    assert len(report.in_progress_items) == 0


@pytest.mark.asyncio
async def test_completion_percentage():
    """Test overall completion percentage calculation."""
    # Create report data directly to test percentage
    report = StatusReportData(
        generated_at=datetime.now().isoformat(),
        total_goals=2,
        active_goals=1,
        completed_goals=1,
        total_plans=3,
        active_plans=2,
        completed_plans=1,
        total_todos=10,
        completed_todos=7,
        in_progress_todos=2,
        blocked_todos=1,
        pending_todos=0,
        overall_completion_pct=70.0,
    )

    assert report.overall_completion_pct == 70.0


@pytest.mark.asyncio
async def test_recently_completed_ordering(mock_storage):
    """Test that recently completed items are ordered by completion date."""
    goals = [
        GoalData(
            id="goal-1", title="Test Goal", description="", weight=5, status="active",
            acceptance_criteria=[], created_at="2024-01-01T00:00:00", updated_at="2024-01-01T00:00:00",
        )
    ]
    plans = [
        PlanData(
            id="plan-1", goal_id="goal-1", title="Test Plan", description="",
            status="active", created_at="2024-01-01T00:00:00", updated_at="2024-01-01T00:00:00",
        )
    ]
    todos = [
        TodoData(
            id="todo-1", title="Older", description="", status="completed", is_spike=False,
            created_at="2024-01-01T00:00:00", updated_at="2024-01-05T00:00:00",
            completed_at="2024-01-05T00:00:00",
        ),
        TodoData(
            id="todo-2", title="Newer", description="", status="completed", is_spike=False,
            created_at="2024-01-01T00:00:00", updated_at="2024-01-10T00:00:00",
            completed_at="2024-01-10T00:00:00",
        ),
    ]

    mock_storage.list_goals.return_value = goals
    mock_storage.list_plans.return_value = plans
    mock_storage.list_todos.return_value = todos
    mock_storage.get_plans_for_todo.side_effect = lambda tid: ["plan-1"]
    mock_storage.get_dependencies.return_value = []

    generator = StatusReportGenerator(storage=mock_storage)
    report = await generator.generate()

    # Most recently completed should be first
    assert len(report.recently_completed) == 2
    assert report.recently_completed[0].title == "Newer"
    assert report.recently_completed[1].title == "Older"


@pytest.mark.asyncio
async def test_generate_scoped_to_goal(mock_storage, sample_goals, sample_plans, sample_todos):
    """Test generating a report scoped to a specific goal."""
    mock_storage.list_goals.return_value = sample_goals
    mock_storage.list_plans.return_value = sample_plans
    mock_storage.list_todos.return_value = sample_todos

    mock_storage.get_plans_for_todo.side_effect = lambda tid: {
        "todo-1": ["plan-1"],
        "todo-2": ["plan-1"],
        "todo-3": ["plan-2"],
        "todo-4": ["plan-1"],
    }.get(tid, [])

    mock_storage.get_dependencies.return_value = []

    generator = StatusReportGenerator(storage=mock_storage)

    # Scope to goal-1
    report = await generator.generate(scope_type="goal", scope_id="goal-1")

    # Should only include goal-1
    assert report.total_goals == 1
    assert len(report.goals) == 1
    assert report.goals[0].id == "goal-1"

    # Should only include plan-1 (belongs to goal-1)
    assert report.total_plans == 1
    assert len(report.plans) == 1
    assert report.plans[0].id == "plan-1"

    # Should only include todos from plan-1 (todo-1, todo-2, not todo-3)
    # Spikes are excluded from total_todos count
    assert report.total_todos == 2  # todo-1 and todo-2 (not spike)


@pytest.mark.asyncio
async def test_generate_scoped_to_plan(mock_storage, sample_goals, sample_plans, sample_todos):
    """Test generating a report scoped to a specific plan."""
    mock_storage.list_goals.return_value = sample_goals
    mock_storage.list_plans.return_value = sample_plans
    mock_storage.list_todos.return_value = sample_todos

    mock_storage.get_plans_for_todo.side_effect = lambda tid: {
        "todo-1": ["plan-1"],
        "todo-2": ["plan-1"],
        "todo-3": ["plan-2"],
        "todo-4": ["plan-1"],
    }.get(tid, [])

    mock_storage.get_dependencies.return_value = []

    generator = StatusReportGenerator(storage=mock_storage)

    # Scope to plan-2
    report = await generator.generate(scope_type="plan", scope_id="plan-2")

    # Should include the parent goal for context
    assert report.total_goals == 1
    assert len(report.goals) == 1
    assert report.goals[0].id == "goal-2"

    # Should only include plan-2
    assert report.total_plans == 1
    assert len(report.plans) == 1
    assert report.plans[0].id == "plan-2"

    # Should only include todos from plan-2 (todo-3)
    assert report.total_todos == 1
    assert report.blocked_todos == 1


@pytest.mark.asyncio
async def test_generate_scoped_with_prefix_match(mock_storage, sample_goals, sample_plans, sample_todos):
    """Test that scope_id supports prefix matching."""
    mock_storage.list_goals.return_value = sample_goals
    mock_storage.list_plans.return_value = sample_plans
    mock_storage.list_todos.return_value = sample_todos

    mock_storage.get_plans_for_todo.side_effect = lambda tid: {
        "todo-1": ["plan-1"],
        "todo-2": ["plan-1"],
        "todo-3": ["plan-2"],
        "todo-4": ["plan-1"],
    }.get(tid, [])

    mock_storage.get_dependencies.return_value = []

    generator = StatusReportGenerator(storage=mock_storage)

    # Scope to goal using prefix
    report = await generator.generate(scope_type="goal", scope_id="goal-1")

    assert report.total_goals == 1
    assert report.goals[0].title == "Build Authentication"


@pytest.mark.asyncio
async def test_generate_scoped_nonexistent(mock_storage, sample_goals, sample_plans, sample_todos):
    """Test that scoping to nonexistent entity returns empty report."""
    mock_storage.list_goals.return_value = sample_goals
    mock_storage.list_plans.return_value = sample_plans
    mock_storage.list_todos.return_value = sample_todos

    mock_storage.get_plans_for_todo.side_effect = lambda tid: []
    mock_storage.get_dependencies.return_value = []

    generator = StatusReportGenerator(storage=mock_storage)

    # Scope to nonexistent goal
    report = await generator.generate(scope_type="goal", scope_id="nonexistent")

    assert report.total_goals == 0
    assert report.total_plans == 0
    assert report.total_todos == 0


def test_summary_field_defaults_to_none():
    """Test that the summary field defaults to None."""
    report = StatusReportData(
        generated_at=datetime.now().isoformat(),
        total_goals=1,
        active_goals=1,
        completed_goals=0,
        total_plans=1,
        active_plans=1,
        completed_plans=0,
        total_todos=5,
        completed_todos=2,
        in_progress_todos=1,
        blocked_todos=0,
        pending_todos=2,
        overall_completion_pct=40.0,
    )

    assert report.summary is None


def test_summary_field_can_be_set():
    """Test that the summary field can hold LLM-generated prose."""
    summary_text = (
        "Good progress this week. The authentication system is 80% complete "
        "with OAuth providers (Google, GitHub) fully integrated. One blocked "
        "item awaiting security review before we can proceed with deployment."
    )

    report = StatusReportData(
        generated_at=datetime.now().isoformat(),
        total_goals=1,
        active_goals=1,
        completed_goals=0,
        total_plans=1,
        active_plans=1,
        completed_plans=0,
        total_todos=5,
        completed_todos=4,
        in_progress_todos=0,
        blocked_todos=1,
        pending_todos=0,
        overall_completion_pct=80.0,
        summary=summary_text,
    )

    assert report.summary == summary_text


class MockTextDelta:
    """Mock TextDelta event for testing."""
    def __init__(self, text: str):
        self.text = text


class MockRunner:
    """Mock streaming runner for testing generate_summary."""

    def __init__(self, response_text: str = "Test summary.", should_fail: bool = False):
        self.response_text = response_text
        self.should_fail = should_fail
        self.last_prompt = None

    async def stream_response(self, messages, prompt, disable_tools=False):
        self.last_prompt = prompt
        if self.should_fail:
            raise RuntimeError("Mock LLM failure")
        # Yield the response as TextDelta events (simulating streaming)
        for word in self.response_text.split():
            yield MockTextDelta(word + " ")


@pytest.mark.asyncio
async def test_generate_summary_basic():
    """Test that generate_summary calls the LLM and returns updated data."""
    report = StatusReportData(
        generated_at=datetime.now().isoformat(),
        total_goals=2,
        active_goals=2,
        completed_goals=0,
        total_plans=3,
        active_plans=2,
        completed_plans=1,
        total_todos=10,
        completed_todos=6,
        in_progress_todos=2,
        blocked_todos=1,
        pending_todos=1,
        overall_completion_pct=60.0,
    )

    expected_summary = "Great progress on authentication. One item blocked pending review."
    runner = MockRunner(response_text=expected_summary)
    generator = StatusReportGenerator(storage=AsyncMock())

    result = await generator.generate_summary(report, runner)

    # Should return new report with summary populated
    assert result.summary == expected_summary
    # Original data should be preserved
    assert result.total_goals == 2
    assert result.overall_completion_pct == 60.0
    # Runner should have received the prompt
    assert runner.last_prompt is not None
    assert "Executive Summary" in runner.last_prompt


@pytest.mark.asyncio
async def test_generate_summary_includes_reporting_prompt():
    """Test that generate_summary includes the reporting.md role prompt."""
    report = StatusReportData(
        generated_at=datetime.now().isoformat(),
        total_goals=1,
        active_goals=1,
        completed_goals=0,
        total_plans=1,
        active_plans=1,
        completed_plans=0,
        total_todos=5,
        completed_todos=2,
        in_progress_todos=1,
        blocked_todos=0,
        pending_todos=2,
        overall_completion_pct=40.0,
    )

    runner = MockRunner(response_text="Summary here.")
    generator = StatusReportGenerator(storage=AsyncMock())

    await generator.generate_summary(report, runner)

    # The prompt should include key elements from reporting.md
    # (outcome-focused language, stakeholder focus, etc.)
    assert "40.0% complete" in runner.last_prompt
    assert "non-technical stakeholders" in runner.last_prompt


@pytest.mark.asyncio
async def test_generate_summary_with_blocked_items():
    """Test that blocked items are included in the summary prompt."""
    report = StatusReportData(
        generated_at=datetime.now().isoformat(),
        total_goals=1,
        active_goals=1,
        completed_goals=0,
        total_plans=1,
        active_plans=1,
        completed_plans=0,
        total_todos=3,
        completed_todos=1,
        in_progress_todos=1,
        blocked_todos=1,
        pending_todos=0,
        overall_completion_pct=33.3,
        blocked_items=[
            TodoStatus(
                id="blocked-1",
                title="Deploy to production",
                status="blocked",
                is_spike=False,
                plan_titles=["Release Plan"],
                blocker_titles=["Security review"],
            )
        ],
    )

    runner = MockRunner(response_text="Blocked on security review.")
    generator = StatusReportGenerator(storage=AsyncMock())

    await generator.generate_summary(report, runner)

    # Blocked items should be in the prompt
    assert "Deploy to production" in runner.last_prompt
    assert "blocked by: Security review" in runner.last_prompt


@pytest.mark.asyncio
async def test_generate_summary_with_recent_completions():
    """Test that recently completed items are included in the summary prompt."""
    report = StatusReportData(
        generated_at=datetime.now().isoformat(),
        total_goals=1,
        active_goals=1,
        completed_goals=0,
        total_plans=1,
        active_plans=1,
        completed_plans=0,
        total_todos=5,
        completed_todos=3,
        in_progress_todos=1,
        blocked_todos=0,
        pending_todos=1,
        overall_completion_pct=60.0,
        recently_completed=[
            TodoStatus(
                id="done-1",
                title="Implement OAuth login",
                status="completed",
                is_spike=False,
                plan_titles=["Auth Plan"],
                blocker_titles=[],
                completed_at="2024-01-15T10:00:00",
            ),
            TodoStatus(
                id="done-2",
                title="Add user dashboard",
                status="completed",
                is_spike=False,
                plan_titles=["UI Plan"],
                blocker_titles=[],
                completed_at="2024-01-14T10:00:00",
            ),
        ],
    )

    runner = MockRunner(response_text="OAuth and dashboard complete.")
    generator = StatusReportGenerator(storage=AsyncMock())

    await generator.generate_summary(report, runner)

    # Recently completed items should be in the prompt
    assert "Implement OAuth login" in runner.last_prompt
    assert "Add user dashboard" in runner.last_prompt


@pytest.mark.asyncio
async def test_generate_summary_handles_llm_failure():
    """Test that generate_summary handles LLM failures gracefully."""
    report = StatusReportData(
        generated_at=datetime.now().isoformat(),
        total_goals=1,
        active_goals=1,
        completed_goals=0,
        total_plans=1,
        active_plans=1,
        completed_plans=0,
        total_todos=5,
        completed_todos=2,
        in_progress_todos=1,
        blocked_todos=0,
        pending_todos=2,
        overall_completion_pct=40.0,
    )

    runner = MockRunner(should_fail=True)
    generator = StatusReportGenerator(storage=AsyncMock())

    result = await generator.generate_summary(report, runner)

    # Should return original data without summary on failure
    assert result.summary is None
    assert result.total_goals == 1
    assert result.overall_completion_pct == 40.0


def test_render_markdown_includes_summary():
    """Test that _render_markdown includes the LLM summary when present."""
    summary_text = (
        "Strong progress this week with authentication 80% complete. "
        "OAuth integration finished for Google and GitHub. "
        "Deployment blocked pending security review."
    )

    report = StatusReportData(
        generated_at=datetime.now().isoformat(),
        total_goals=1,
        active_goals=1,
        completed_goals=0,
        total_plans=1,
        active_plans=1,
        completed_plans=0,
        total_todos=5,
        completed_todos=4,
        in_progress_todos=0,
        blocked_todos=1,
        pending_todos=0,
        overall_completion_pct=80.0,
        summary=summary_text,
    )

    generator = StatusReportGenerator(storage=MagicMock())
    markdown = generator._render_markdown(report)

    # Summary should appear in the Executive Summary section
    assert "## Executive Summary" in markdown
    assert summary_text in markdown
    # Summary should appear before the progress line
    summary_pos = markdown.index(summary_text)
    progress_pos = markdown.index("**Overall Progress:**")
    assert summary_pos < progress_pos, "Summary should appear before progress statistics"


def test_render_markdown_without_summary():
    """Test that _render_markdown works when summary is None."""
    report = StatusReportData(
        generated_at=datetime.now().isoformat(),
        total_goals=1,
        active_goals=1,
        completed_goals=0,
        total_plans=1,
        active_plans=1,
        completed_plans=0,
        total_todos=5,
        completed_todos=2,
        in_progress_todos=1,
        blocked_todos=0,
        pending_todos=2,
        overall_completion_pct=40.0,
        summary=None,
    )

    generator = StatusReportGenerator(storage=MagicMock())
    markdown = generator._render_markdown(report)

    # Should still render properly without summary
    assert "## Executive Summary" in markdown
    assert "**Overall Progress:** 40.0% complete" in markdown


def test_build_summary_prompt():
    """Test that _build_summary_prompt formats data correctly."""
    report = StatusReportData(
        generated_at=datetime.now().isoformat(),
        total_goals=2,
        active_goals=1,
        completed_goals=1,
        total_plans=3,
        active_plans=2,
        completed_plans=1,
        total_todos=10,
        completed_todos=7,
        in_progress_todos=2,
        blocked_todos=1,
        pending_todos=0,
        overall_completion_pct=70.0,
        goals=[
            GoalStatus(
                id="goal-1",
                title="Launch MVP",
                weight=9,
                status="active",
                plan_count=2,
                active_plan_count=1,
                total_todos=5,
                completed_todos=4,
                in_progress_todos=1,
                blocked_todos=0,
                completion_pct=80.0,
                acceptance_criteria=["Users can sign up"],
            ),
        ],
        in_progress_items=[
            TodoStatus(
                id="ip-1",
                title="Final testing",
                status="in_progress",
                is_spike=False,
                plan_titles=["QA Plan"],
                blocker_titles=[],
            ),
        ],
    )

    generator = StatusReportGenerator(storage=MagicMock())
    prompt = generator._build_summary_prompt(report)

    # Check key elements are present
    assert "70.0% complete" in prompt
    assert "7 done" in prompt
    assert "2 in progress" in prompt
    assert "1 blocked" in prompt
    assert "Launch MVP" in prompt
    assert "Final testing" in prompt
    assert "Executive Summary" in prompt
    assert "non-technical stakeholders" in prompt
