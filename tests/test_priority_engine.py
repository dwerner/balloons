"""Tests for the priority engine."""

import tempfile
from pathlib import Path
from datetime import datetime

import pytest

from core.async_storage import GoalStorage
from core.priority_engine import PriorityEngine, TodoWithContext
from storage_schema import GoalData, PlanData, TodoData, TodoPlanLink, TodoDependency


@pytest.fixture
def temp_goal_dir():
    """Create a temporary directory for goal storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def goal_storage(temp_goal_dir):
    """Create a GoalStorage with a temp directory."""
    return GoalStorage(temp_goal_dir)


@pytest.fixture
def priority_engine(goal_storage):
    """Create a PriorityEngine with the test storage."""
    return PriorityEngine(goal_storage)


def now() -> str:
    """Get current ISO timestamp."""
    return datetime.now().isoformat()


# =============================================================================
# Basic Priority Ranking Tests
# =============================================================================


@pytest.mark.asyncio
async def test_empty_storage_returns_empty_list(priority_engine):
    """No todos should return empty list."""
    ranked = await priority_engine.get_priority_ranked_todos()
    assert ranked == []


@pytest.mark.asyncio
async def test_single_todo_priority(goal_storage, priority_engine):
    """Single todo returns correct priority."""
    ts = now()

    # Create goal with weight 8
    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=8,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    # Create active plan
    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    # Create todo
    todo = TodoData(
        id="todo-1", title="Test Todo", description="",
        status="pending", is_spike=False, created_at=ts, updated_at=ts,
    )
    await goal_storage.save_todo(todo)

    # Link todo to plan
    link = TodoPlanLink(todo_id="todo-1", plan_id="plan-1", created_at=ts)
    await goal_storage.save_todo_plan_link(link)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 1
    assert ranked[0][0].id == "todo-1"
    # Priority = weight (8) × completion_factor (0.1 minimum for empty plan)
    assert ranked[0][1] == pytest.approx(0.8, rel=0.01)


@pytest.mark.asyncio
async def test_priority_ordering_by_goal_weight(goal_storage, priority_engine):
    """Higher weight goals should produce higher priority todos."""
    ts = now()

    # Create two goals with different weights
    goals = [
        GoalData(id="goal-low", title="Low Priority", description="", weight=3,
                 status="active", acceptance_criteria=[], created_at=ts, updated_at=ts),
        GoalData(id="goal-high", title="High Priority", description="", weight=9,
                 status="active", acceptance_criteria=[], created_at=ts, updated_at=ts),
    ]

    for goal in goals:
        await goal_storage.save_goal(goal)

    # Create plans
    plans = [
        PlanData(id="plan-low", goal_id="goal-low", title="Low Plan", description="",
                 status="active", created_at=ts, updated_at=ts),
        PlanData(id="plan-high", goal_id="goal-high", title="High Plan", description="",
                 status="active", created_at=ts, updated_at=ts),
    ]

    for plan in plans:
        await goal_storage.save_plan(plan)

    # Create todos
    todos = [
        TodoData(id="todo-low", title="Low Todo", description="",
                 status="pending", is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-high", title="High Todo", description="",
                 status="pending", is_spike=False, created_at=ts, updated_at=ts),
    ]

    for todo in todos:
        await goal_storage.save_todo(todo)

    # Link todos to plans
    links = [
        TodoPlanLink(todo_id="todo-low", plan_id="plan-low", created_at=ts),
        TodoPlanLink(todo_id="todo-high", plan_id="plan-high", created_at=ts),
    ]

    for link in links:
        await goal_storage.save_todo_plan_link(link)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 2
    # High priority should come first
    assert ranked[0][0].id == "todo-high"
    assert ranked[1][0].id == "todo-low"
    # Verify priorities
    assert ranked[0][1] > ranked[1][1]


@pytest.mark.asyncio
async def test_completion_factor_affects_priority(goal_storage, priority_engine):
    """Completion factor should boost priority as more todos complete."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    # Create 3 todos - 2 complete, 1 pending
    todos = [
        TodoData(id="todo-1", title="Done 1", description="", status="completed",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-2", title="Done 2", description="", status="completed",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-3", title="Pending", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
    ]

    for todo in todos:
        await goal_storage.save_todo(todo)
        link = TodoPlanLink(todo_id=todo.id, plan_id="plan-1", created_at=ts)
        await goal_storage.save_todo_plan_link(link)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 1
    assert ranked[0][0].id == "todo-3"

    # completion_factor = 2/3 = 0.667
    # priority = 10 × 0.667 = 6.67
    assert ranked[0][1] == pytest.approx(6.67, rel=0.01)


# =============================================================================
# Dependency Tests
# =============================================================================


@pytest.mark.asyncio
async def test_blocked_todos_excluded(goal_storage, priority_engine):
    """Todos with incomplete dependencies should not appear in ranking."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    # todo-2 depends on todo-1
    todos = [
        TodoData(id="todo-1", title="First", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-2", title="Blocked", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
    ]

    for todo in todos:
        await goal_storage.save_todo(todo)
        link = TodoPlanLink(todo_id=todo.id, plan_id="plan-1", created_at=ts)
        await goal_storage.save_todo_plan_link(link)

    # Create dependency
    dep = TodoDependency(todo_id="todo-2", depends_on_id="todo-1", created_at=ts)
    await goal_storage.save_todo_dependency(dep)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 1
    assert ranked[0][0].id == "todo-1"  # Only unblocked todo


@pytest.mark.asyncio
async def test_dependency_resolved_makes_available(goal_storage, priority_engine):
    """Completing a dependency should make blocked todo available."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    # todo-2 depends on todo-1 (which is complete)
    todos = [
        TodoData(id="todo-1", title="First", description="", status="completed",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-2", title="Unblocked", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
    ]

    for todo in todos:
        await goal_storage.save_todo(todo)
        link = TodoPlanLink(todo_id=todo.id, plan_id="plan-1", created_at=ts)
        await goal_storage.save_todo_plan_link(link)

    dep = TodoDependency(todo_id="todo-2", depends_on_id="todo-1", created_at=ts)
    await goal_storage.save_todo_dependency(dep)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 1
    assert ranked[0][0].id == "todo-2"  # Now available


@pytest.mark.asyncio
async def test_get_blocked_todos(goal_storage, priority_engine):
    """get_blocked_todos should return todos with their blockers."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    # todo-3 depends on both todo-1 and todo-2
    todos = [
        TodoData(id="todo-1", title="Blocker 1", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-2", title="Blocker 2", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-3", title="Blocked", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
    ]

    for todo in todos:
        await goal_storage.save_todo(todo)
        link = TodoPlanLink(todo_id=todo.id, plan_id="plan-1", created_at=ts)
        await goal_storage.save_todo_plan_link(link)

    deps = [
        TodoDependency(todo_id="todo-3", depends_on_id="todo-1", created_at=ts),
        TodoDependency(todo_id="todo-3", depends_on_id="todo-2", created_at=ts),
    ]
    for dep in deps:
        await goal_storage.save_todo_dependency(dep)

    blocked = await priority_engine.get_blocked_todos()
    assert len(blocked) == 1
    blocked_todo, blockers = blocked[0]
    assert blocked_todo.id == "todo-3"
    assert len(blockers) == 2
    blocker_ids = {b.id for b in blockers}
    assert blocker_ids == {"todo-1", "todo-2"}


# =============================================================================
# Spike Exclusion Tests
# =============================================================================


@pytest.mark.asyncio
async def test_spikes_excluded_from_ranking(goal_storage, priority_engine):
    """Spikes should not appear in priority ranking."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    todos = [
        TodoData(id="todo-1", title="Regular", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="spike-1", title="Spike", description="", status="pending",
                 is_spike=True, timebox_minutes=60, created_at=ts, updated_at=ts),
    ]

    for todo in todos:
        await goal_storage.save_todo(todo)
        link = TodoPlanLink(todo_id=todo.id, plan_id="plan-1", created_at=ts)
        await goal_storage.save_todo_plan_link(link)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 1
    assert ranked[0][0].id == "todo-1"


@pytest.mark.asyncio
async def test_spikes_not_counted_in_completion_factor(goal_storage, priority_engine):
    """Spikes should not affect completion factor calculation."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    # 1 completed regular, 1 pending regular, 2 completed spikes
    todos = [
        TodoData(id="todo-1", title="Done", description="", status="completed",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-2", title="Pending", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="spike-1", title="Spike 1", description="", status="completed",
                 is_spike=True, created_at=ts, updated_at=ts),
        TodoData(id="spike-2", title="Spike 2", description="", status="completed",
                 is_spike=True, created_at=ts, updated_at=ts),
    ]

    for todo in todos:
        await goal_storage.save_todo(todo)
        link = TodoPlanLink(todo_id=todo.id, plan_id="plan-1", created_at=ts)
        await goal_storage.save_todo_plan_link(link)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 1

    # completion_factor = 1/2 = 0.5 (only regular todos count)
    # priority = 10 × 0.5 = 5.0
    assert ranked[0][1] == pytest.approx(5.0, rel=0.01)


# =============================================================================
# Multi-Plan Todo Tests
# =============================================================================


@pytest.mark.asyncio
async def test_multi_plan_todo_uses_max_priority(goal_storage, priority_engine):
    """Todo linked to multiple plans should use MAX of priorities."""
    ts = now()

    # Create two goals with different weights
    goals = [
        GoalData(id="goal-low", title="Low", description="", weight=3,
                 status="active", acceptance_criteria=[], created_at=ts, updated_at=ts),
        GoalData(id="goal-high", title="High", description="", weight=9,
                 status="active", acceptance_criteria=[], created_at=ts, updated_at=ts),
    ]

    for goal in goals:
        await goal_storage.save_goal(goal)

    plans = [
        PlanData(id="plan-low", goal_id="goal-low", title="Low Plan", description="",
                 status="active", created_at=ts, updated_at=ts),
        PlanData(id="plan-high", goal_id="goal-high", title="High Plan", description="",
                 status="active", created_at=ts, updated_at=ts),
    ]

    for plan in plans:
        await goal_storage.save_plan(plan)

    # Single todo linked to both plans
    todo = TodoData(
        id="todo-shared", title="Shared Todo", description="",
        status="pending", is_spike=False, created_at=ts, updated_at=ts,
    )
    await goal_storage.save_todo(todo)

    # Link to both plans
    for plan_id in ["plan-low", "plan-high"]:
        link = TodoPlanLink(todo_id="todo-shared", plan_id=plan_id, created_at=ts)
        await goal_storage.save_todo_plan_link(link)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 1

    # Should use MAX (weight 9), not MIN or AVG
    # priority = 9 × 0.1 = 0.9
    assert ranked[0][1] == pytest.approx(0.9, rel=0.01)


# =============================================================================
# Inactive Goal/Plan Tests
# =============================================================================


@pytest.mark.asyncio
async def test_inactive_goal_todos_excluded(goal_storage, priority_engine):
    """Todos linked to inactive goals should not appear."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Completed Goal", description="", weight=10,
        status="completed", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    todo = TodoData(
        id="todo-1", title="Orphaned Todo", description="",
        status="pending", is_spike=False, created_at=ts, updated_at=ts,
    )
    await goal_storage.save_todo(todo)
    link = TodoPlanLink(todo_id="todo-1", plan_id="plan-1", created_at=ts)
    await goal_storage.save_todo_plan_link(link)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 0


@pytest.mark.asyncio
async def test_inactive_plan_todos_excluded(goal_storage, priority_engine):
    """Todos linked only to inactive plans should not appear."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Abandoned Plan", description="",
        status="abandoned", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    todo = TodoData(
        id="todo-1", title="Orphaned Todo", description="",
        status="pending", is_spike=False, created_at=ts, updated_at=ts,
    )
    await goal_storage.save_todo(todo)
    link = TodoPlanLink(todo_id="todo-1", plan_id="plan-1", created_at=ts)
    await goal_storage.save_todo_plan_link(link)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 0


@pytest.mark.asyncio
async def test_unlinked_todo_excluded(goal_storage, priority_engine):
    """Todos not linked to any plan should not appear."""
    ts = now()

    todo = TodoData(
        id="todo-1", title="Unlinked Todo", description="",
        status="pending", is_spike=False, created_at=ts, updated_at=ts,
    )
    await goal_storage.save_todo(todo)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 0


# =============================================================================
# Context and Utility Method Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_priority_ranked_with_context(goal_storage, priority_engine):
    """get_priority_ranked_todos_with_context should return full context."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=8,
        status="active", acceptance_criteria=["Criterion 1"], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    todo = TodoData(
        id="todo-1", title="Test Todo", description="",
        status="pending", is_spike=False, created_at=ts, updated_at=ts,
    )
    await goal_storage.save_todo(todo)
    link = TodoPlanLink(todo_id="todo-1", plan_id="plan-1", created_at=ts)
    await goal_storage.save_todo_plan_link(link)

    ranked = await priority_engine.get_priority_ranked_todos_with_context()
    assert len(ranked) == 1

    context = ranked[0]
    assert isinstance(context, TodoWithContext)
    assert context.todo.id == "todo-1"
    assert context.goal.id == "goal-1"
    assert len(context.plans) == 1
    assert context.plans[0].id == "plan-1"
    assert context.completion_factor == pytest.approx(0.1, rel=0.01)
    assert context.priority == pytest.approx(0.8, rel=0.01)


@pytest.mark.asyncio
async def test_get_next_todo(goal_storage, priority_engine):
    """get_next_todo should return highest priority todo."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    todos = [
        TodoData(id="todo-1", title="First", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-2", title="Second", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
    ]

    for todo in todos:
        await goal_storage.save_todo(todo)
        link = TodoPlanLink(todo_id=todo.id, plan_id="plan-1", created_at=ts)
        await goal_storage.save_todo_plan_link(link)

    result = await priority_engine.get_next_todo()
    assert result is not None
    todo, priority = result
    assert todo.id in ["todo-1", "todo-2"]  # Either is fine, same priority


@pytest.mark.asyncio
async def test_get_next_todo_empty(priority_engine):
    """get_next_todo should return None when no todos available."""
    result = await priority_engine.get_next_todo()
    assert result is None


@pytest.mark.asyncio
async def test_get_goal_progress(goal_storage, priority_engine):
    """get_goal_progress should return correct stats."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plans = [
        PlanData(id="plan-1", goal_id="goal-1", title="Active", description="",
                 status="active", created_at=ts, updated_at=ts),
        PlanData(id="plan-2", goal_id="goal-1", title="Completed", description="",
                 status="completed", created_at=ts, updated_at=ts),
    ]

    for plan in plans:
        await goal_storage.save_plan(plan)

    # 2 completed, 2 pending (1 blocked), 1 spike
    todos = [
        TodoData(id="todo-1", title="Done 1", description="", status="completed",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-2", title="Done 2", description="", status="completed",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-3", title="Available", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-4", title="Blocked", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="spike-1", title="Spike", description="", status="pending",
                 is_spike=True, created_at=ts, updated_at=ts),
    ]

    for todo in todos:
        await goal_storage.save_todo(todo)
        link = TodoPlanLink(todo_id=todo.id, plan_id="plan-1", created_at=ts)
        await goal_storage.save_todo_plan_link(link)

    # todo-4 blocked by todo-3
    dep = TodoDependency(todo_id="todo-4", depends_on_id="todo-3", created_at=ts)
    await goal_storage.save_todo_dependency(dep)

    progress = await priority_engine.get_goal_progress("goal-1")
    assert progress["total_plans"] == 2
    assert progress["active_plans"] == 1
    assert progress["total_todos"] == 4  # Excludes spike
    assert progress["completed_todos"] == 2
    assert progress["blocked_todos"] == 1
    assert progress["available_todos"] == 1


@pytest.mark.asyncio
async def test_get_plan_progress(goal_storage, priority_engine):
    """get_plan_progress should return correct stats."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    todos = [
        TodoData(id="todo-1", title="Done", description="", status="completed",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-2", title="In Progress", description="", status="in_progress",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="todo-3", title="Pending", description="", status="pending",
                 is_spike=False, created_at=ts, updated_at=ts),
        TodoData(id="spike-1", title="Spike", description="", status="pending",
                 is_spike=True, created_at=ts, updated_at=ts),
    ]

    for todo in todos:
        await goal_storage.save_todo(todo)
        link = TodoPlanLink(todo_id=todo.id, plan_id="plan-1", created_at=ts)
        await goal_storage.save_todo_plan_link(link)

    progress = await priority_engine.get_plan_progress("plan-1")
    assert progress["total_todos"] == 3  # Excludes spike
    assert progress["completed_todos"] == 1
    assert progress["pending_todos"] == 1
    assert progress["in_progress_todos"] == 1
    assert progress["completion_pct"] == pytest.approx(33.33, rel=0.1)


# =============================================================================
# Edge Cases
# =============================================================================


@pytest.mark.asyncio
async def test_completed_todos_excluded(goal_storage, priority_engine):
    """Completed todos should not appear in ranking."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    todo = TodoData(
        id="todo-1", title="Completed", description="", status="completed",
        is_spike=False, created_at=ts, updated_at=ts,
    )
    await goal_storage.save_todo(todo)
    link = TodoPlanLink(todo_id="todo-1", plan_id="plan-1", created_at=ts)
    await goal_storage.save_todo_plan_link(link)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 0


@pytest.mark.asyncio
async def test_in_progress_todos_included(goal_storage, priority_engine):
    """In-progress todos should appear in ranking."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Test Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    todo = TodoData(
        id="todo-1", title="In Progress", description="", status="in_progress",
        is_spike=False, created_at=ts, updated_at=ts,
    )
    await goal_storage.save_todo(todo)
    link = TodoPlanLink(todo_id="todo-1", plan_id="plan-1", created_at=ts)
    await goal_storage.save_todo_plan_link(link)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 1
    assert ranked[0][0].id == "todo-1"


@pytest.mark.asyncio
async def test_minimum_completion_factor(goal_storage, priority_engine):
    """Empty plans should use minimum completion factor of 0.1."""
    ts = now()

    goal = GoalData(
        id="goal-1", title="Test Goal", description="", weight=10,
        status="active", acceptance_criteria=[], created_at=ts, updated_at=ts,
    )
    await goal_storage.save_goal(goal)

    plan = PlanData(
        id="plan-1", goal_id="goal-1", title="Empty Plan", description="",
        status="active", created_at=ts, updated_at=ts,
    )
    await goal_storage.save_plan(plan)

    todo = TodoData(
        id="todo-1", title="Only Todo", description="", status="pending",
        is_spike=False, created_at=ts, updated_at=ts,
    )
    await goal_storage.save_todo(todo)
    link = TodoPlanLink(todo_id="todo-1", plan_id="plan-1", created_at=ts)
    await goal_storage.save_todo_plan_link(link)

    ranked = await priority_engine.get_priority_ranked_todos()
    assert len(ranked) == 1

    # With only one pending todo, completion = 0/1 = 0
    # But minimum is 0.1, so priority = 10 × 0.1 = 1.0
    assert ranked[0][1] == pytest.approx(1.0, rel=0.01)
