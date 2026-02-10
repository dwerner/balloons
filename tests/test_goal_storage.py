"""Tests for goal-oriented task management storage."""

import tempfile
from pathlib import Path
from datetime import datetime

import pytest

from core.async_storage import GoalStorage
from storage_schema import GoalData, PlanData, TodoData, TodoPlanLink, TodoDependency, SessionBinding


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
def sample_goal():
    """Create a sample goal."""
    now = datetime.now().isoformat()
    return GoalData(
        id="goal-123",
        title="Build goal tracking system",
        description="Create a system for tracking goals across sessions",
        weight=8,
        status="active",
        acceptance_criteria=["Schema defined", "CRUD working", "UI integrated"],
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def sample_plan():
    """Create a sample plan."""
    now = datetime.now().isoformat()
    return PlanData(
        id="plan-456",
        goal_id="goal-123",
        title="Phase 1: Schema and Storage",
        description="Define entities and implement storage layer",
        status="active",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def sample_todo():
    """Create a sample todo."""
    now = datetime.now().isoformat()
    return TodoData(
        id="todo-789",
        title="Add dataclasses to storage_schema.py",
        description="Define GoalData, PlanData, TodoData, etc.",
        status="pending",
        is_spike=False,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_goal_crud(goal_storage, sample_goal):
    """Test goal create, read, update, delete."""
    # Create
    await goal_storage.save_goal(sample_goal)

    # Read
    loaded = await goal_storage.load_goal(sample_goal.id)
    assert loaded is not None
    assert loaded.id == sample_goal.id
    assert loaded.title == sample_goal.title
    assert loaded.weight == 8
    assert loaded.status == "active"
    assert len(loaded.acceptance_criteria) == 3

    # Update
    sample_goal.status = "completed"
    sample_goal.completed_at = "2026-02-09T12:00:00"
    await goal_storage.save_goal(sample_goal)

    loaded = await goal_storage.load_goal(sample_goal.id)
    assert loaded.status == "completed"
    assert loaded.completed_at == "2026-02-09T12:00:00"

    # Delete
    await goal_storage.delete_goal(sample_goal.id)
    loaded = await goal_storage.load_goal(sample_goal.id)
    assert loaded is None


@pytest.mark.asyncio
async def test_list_goals(goal_storage):
    """Test listing goals with filtering."""
    now = datetime.now().isoformat()

    # Create goals with different weights and statuses
    goals = [
        GoalData(id="g1", title="Low priority", description="", weight=3, status="active",
                 acceptance_criteria=[], created_at=now, updated_at=now),
        GoalData(id="g2", title="High priority", description="", weight=9, status="active",
                 acceptance_criteria=[], created_at=now, updated_at=now),
        GoalData(id="g3", title="Completed", description="", weight=5, status="completed",
                 acceptance_criteria=[], created_at=now, updated_at=now),
    ]

    for goal in goals:
        await goal_storage.save_goal(goal)

    # List all
    all_goals = await goal_storage.list_goals()
    assert len(all_goals) == 3
    # Should be sorted by weight descending
    assert all_goals[0].id == "g2"  # weight 9
    assert all_goals[1].id == "g3"  # weight 5
    assert all_goals[2].id == "g1"  # weight 3

    # Filter by status
    active_goals = await goal_storage.list_goals(status="active")
    assert len(active_goals) == 2
    assert all(g.status == "active" for g in active_goals)


@pytest.mark.asyncio
async def test_plan_crud(goal_storage, sample_plan):
    """Test plan create, read, update, delete."""
    await goal_storage.save_plan(sample_plan)

    loaded = await goal_storage.load_plan(sample_plan.id)
    assert loaded is not None
    assert loaded.goal_id == "goal-123"
    assert loaded.title == "Phase 1: Schema and Storage"

    # Update with postmortem
    sample_plan.status = "completed"
    sample_plan.postmortem = "Learned that file-based storage is good enough for MVP"
    await goal_storage.save_plan(sample_plan)

    loaded = await goal_storage.load_plan(sample_plan.id)
    assert loaded.status == "completed"
    assert "file-based storage" in loaded.postmortem

    await goal_storage.delete_plan(sample_plan.id)
    assert await goal_storage.load_plan(sample_plan.id) is None


@pytest.mark.asyncio
async def test_list_plans_by_goal(goal_storage):
    """Test listing plans filtered by goal."""
    now = datetime.now().isoformat()

    plans = [
        PlanData(id="p1", goal_id="goal-1", title="Plan 1", description="", status="active",
                 created_at=now, updated_at=now),
        PlanData(id="p2", goal_id="goal-1", title="Plan 2", description="", status="completed",
                 created_at=now, updated_at=now),
        PlanData(id="p3", goal_id="goal-2", title="Plan 3", description="", status="active",
                 created_at=now, updated_at=now),
    ]

    for plan in plans:
        await goal_storage.save_plan(plan)

    # Filter by goal
    goal1_plans = await goal_storage.list_plans(goal_id="goal-1")
    assert len(goal1_plans) == 2

    # Filter by goal and status
    active_goal1 = await goal_storage.list_plans(goal_id="goal-1", status="active")
    assert len(active_goal1) == 1
    assert active_goal1[0].id == "p1"


@pytest.mark.asyncio
async def test_todo_crud(goal_storage, sample_todo):
    """Test todo create, read, update, delete."""
    await goal_storage.save_todo(sample_todo)

    loaded = await goal_storage.load_todo(sample_todo.id)
    assert loaded is not None
    assert loaded.title == "Add dataclasses to storage_schema.py"
    assert loaded.is_spike is False

    # Update
    sample_todo.status = "completed"
    await goal_storage.save_todo(sample_todo)

    loaded = await goal_storage.load_todo(sample_todo.id)
    assert loaded.status == "completed"

    await goal_storage.delete_todo(sample_todo.id)
    assert await goal_storage.load_todo(sample_todo.id) is None


@pytest.mark.asyncio
async def test_todo_spike(goal_storage):
    """Test spike todos with timebox."""
    now = datetime.now().isoformat()

    spike = TodoData(
        id="spike-1",
        title="Investigate caching options",
        description="Research Redis vs memcached",
        status="pending",
        is_spike=True,
        timebox_minutes=60,
        created_at=now,
        updated_at=now,
    )

    await goal_storage.save_todo(spike)

    loaded = await goal_storage.load_todo("spike-1")
    assert loaded.is_spike is True
    assert loaded.timebox_minutes == 60

    # Test filtering spikes
    regular = TodoData(
        id="regular-1", title="Regular task", description="", status="pending",
        is_spike=False, created_at=now, updated_at=now,
    )
    await goal_storage.save_todo(regular)

    # Include spikes
    all_todos = await goal_storage.list_todos(include_spikes=True)
    assert len(all_todos) == 2

    # Exclude spikes
    no_spikes = await goal_storage.list_todos(include_spikes=False)
    assert len(no_spikes) == 1
    assert no_spikes[0].id == "regular-1"


@pytest.mark.asyncio
async def test_todo_plan_links(goal_storage):
    """Test many-to-many todo-plan linking."""
    now = datetime.now().isoformat()

    # Create links
    link1 = TodoPlanLink(todo_id="todo-1", plan_id="plan-1", created_at=now)
    link2 = TodoPlanLink(todo_id="todo-1", plan_id="plan-2", created_at=now)
    link3 = TodoPlanLink(todo_id="todo-2", plan_id="plan-1", created_at=now)

    for link in [link1, link2, link3]:
        await goal_storage.save_todo_plan_link(link)

    # Get plans for todo
    plans_for_todo1 = await goal_storage.get_plans_for_todo("todo-1")
    assert len(plans_for_todo1) == 2
    assert set(plans_for_todo1) == {"plan-1", "plan-2"}

    # Get todos for plan
    todos_for_plan1 = await goal_storage.get_todos_for_plan("plan-1")
    assert len(todos_for_plan1) == 2
    assert set(todos_for_plan1) == {"todo-1", "todo-2"}

    # Delete a link
    await goal_storage.delete_todo_plan_link("todo-1", "plan-1")
    plans_for_todo1 = await goal_storage.get_plans_for_todo("todo-1")
    assert len(plans_for_todo1) == 1
    assert plans_for_todo1[0] == "plan-2"


@pytest.mark.asyncio
async def test_todo_dependencies(goal_storage):
    """Test todo dependency graph."""
    now = datetime.now().isoformat()

    # todo-2 depends on todo-1
    # todo-3 depends on todo-1 and todo-2
    deps = [
        TodoDependency(todo_id="todo-2", depends_on_id="todo-1", created_at=now),
        TodoDependency(todo_id="todo-3", depends_on_id="todo-1", created_at=now),
        TodoDependency(todo_id="todo-3", depends_on_id="todo-2", created_at=now),
    ]

    for dep in deps:
        await goal_storage.save_todo_dependency(dep)

    # Get dependencies (what a todo depends on)
    deps_of_3 = await goal_storage.get_dependencies("todo-3")
    assert len(deps_of_3) == 2
    assert set(deps_of_3) == {"todo-1", "todo-2"}

    # Get dependents (what depends on a todo)
    dependents_of_1 = await goal_storage.get_dependents("todo-1")
    assert len(dependents_of_1) == 2
    assert set(dependents_of_1) == {"todo-2", "todo-3"}

    # Delete a dependency
    await goal_storage.delete_todo_dependency("todo-3", "todo-1")
    deps_of_3 = await goal_storage.get_dependencies("todo-3")
    assert len(deps_of_3) == 1
    assert deps_of_3[0] == "todo-2"


@pytest.mark.asyncio
async def test_session_bindings(goal_storage):
    """Test session bindings to entities."""
    now = datetime.now().isoformat()

    bindings = [
        SessionBinding(id="b1", session_id="session-1", entity_type="goal", entity_id="goal-1",
                       role="planning", created_at=now),
        SessionBinding(id="b2", session_id="session-1", entity_type="plan", entity_id="plan-1",
                       role="implementation", created_at=now),
        SessionBinding(id="b3", session_id="session-2", entity_type="goal", entity_id="goal-1",
                       role="postmortem", created_at=now, released_at=now),  # Released
    ]

    for binding in bindings:
        await goal_storage.save_session_binding(binding)

    # Get bindings for session (active only by default)
    session1_bindings = await goal_storage.get_bindings_for_session("session-1")
    assert len(session1_bindings) == 2

    # Get bindings for entity
    goal1_bindings = await goal_storage.get_bindings_for_entity("goal", "goal-1")
    assert len(goal1_bindings) == 1  # Only active (b3 is released)
    assert goal1_bindings[0].session_id == "session-1"

    # Include released bindings
    all_goal1_bindings = await goal_storage.get_bindings_for_entity("goal", "goal-1", active_only=False)
    assert len(all_goal1_bindings) == 2

    # Delete binding
    await goal_storage.delete_session_binding("b1")
    session1_bindings = await goal_storage.get_bindings_for_session("session-1")
    assert len(session1_bindings) == 1
    assert session1_bindings[0].id == "b2"


@pytest.mark.asyncio
async def test_load_nonexistent_entities(goal_storage):
    """Test loading entities that don't exist returns None."""
    assert await goal_storage.load_goal("nonexistent") is None
    assert await goal_storage.load_plan("nonexistent") is None
    assert await goal_storage.load_todo("nonexistent") is None
    assert await goal_storage.load_session_binding("nonexistent") is None


@pytest.mark.asyncio
async def test_goal_supersession(goal_storage):
    """Test goal supersession tracking."""
    now = datetime.now().isoformat()

    old_goal = GoalData(
        id="goal-old",
        title="Original approach",
        description="First attempt",
        weight=7,
        status="superseded",
        acceptance_criteria=[],
        created_at=now,
        updated_at=now,
    )

    new_goal = GoalData(
        id="goal-new",
        title="Better approach",
        description="Improved version",
        weight=8,
        status="active",
        acceptance_criteria=[],
        created_at=now,
        updated_at=now,
        supersedes_id="goal-old",
    )

    await goal_storage.save_goal(old_goal)
    await goal_storage.save_goal(new_goal)

    loaded = await goal_storage.load_goal("goal-new")
    assert loaded.supersedes_id == "goal-old"

    # Verify old goal is marked superseded
    old = await goal_storage.load_goal("goal-old")
    assert old.status == "superseded"
