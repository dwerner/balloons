"""Tests for lifecycle hooks in goal-oriented task management."""

import tempfile
from pathlib import Path
from datetime import datetime

import pytest

from core.async_storage import GoalStorage
from core.lifecycle_hooks import (
    LifecycleHooks,
    LifecyclePrompt,
    PostmortemOutcome,
    SpikeOutcome,
    on_todo_complete,
    on_plan_complete,
    execute_postmortem,
    execute_spike_outcome,
)
from storage_schema import (
    GoalData, PlanData, TodoData, TodoPlanLink, SessionBinding,
)


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
def hooks(goal_storage):
    """Create LifecycleHooks with test storage."""
    return LifecycleHooks(goal_storage)


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
        acceptance_criteria=[
            "Schema defined",
            "CRUD working",
            "UI integrated",
        ],
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def sample_plan(sample_goal):
    """Create a sample plan linked to the goal."""
    now = datetime.now().isoformat()
    return PlanData(
        id="plan-456",
        goal_id=sample_goal.id,
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


@pytest.fixture
def sample_spike():
    """Create a sample spike todo."""
    now = datetime.now().isoformat()
    return TodoData(
        id="spike-001",
        title="Investigate caching options",
        description="Research Redis vs memcached for session caching",
        status="pending",
        is_spike=True,
        timebox_minutes=60,
        created_at=now,
        updated_at=now,
    )


# =============================================================================
# Todo Completion Hook Tests
# =============================================================================


@pytest.mark.asyncio
async def test_todo_complete_not_found(hooks):
    """Test completing a todo that doesn't exist."""
    result = await hooks.on_todo_complete("nonexistent", "session-1")
    assert result is None


@pytest.mark.asyncio
async def test_todo_complete_no_plan_link(hooks, goal_storage, sample_todo):
    """Test completing a todo not linked to any plan."""
    await goal_storage.save_todo(sample_todo)

    result = await hooks.on_todo_complete(sample_todo.id, "session-1")

    # No prompt needed - just complete the todo
    assert result is None

    # Verify todo was marked complete
    loaded = await goal_storage.load_todo(sample_todo.id)
    assert loaded.status == "completed"
    assert loaded.completed_at is not None


@pytest.mark.asyncio
async def test_todo_complete_plan_not_done(hooks, goal_storage, sample_goal, sample_plan, sample_todo):
    """Test completing a todo when plan has more todos."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)
    await goal_storage.save_todo(sample_todo)

    # Create another pending todo linked to the same plan
    now = datetime.now().isoformat()
    other_todo = TodoData(
        id="todo-other",
        title="Other task",
        description="",
        status="pending",
        is_spike=False,
        created_at=now,
        updated_at=now,
    )
    await goal_storage.save_todo(other_todo)

    # Link both todos to plan
    await goal_storage.save_todo_plan_link(
        TodoPlanLink(todo_id=sample_todo.id, plan_id=sample_plan.id, created_at=now)
    )
    await goal_storage.save_todo_plan_link(
        TodoPlanLink(todo_id=other_todo.id, plan_id=sample_plan.id, created_at=now)
    )

    result = await hooks.on_todo_complete(sample_todo.id, "session-1")

    # No prompt - plan still has pending todos
    assert result is None


@pytest.mark.asyncio
async def test_todo_complete_triggers_plan_complete(hooks, goal_storage, sample_goal, sample_plan, sample_todo):
    """Test completing last todo triggers plan completion prompt."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)
    await goal_storage.save_todo(sample_todo)

    now = datetime.now().isoformat()
    await goal_storage.save_todo_plan_link(
        TodoPlanLink(todo_id=sample_todo.id, plan_id=sample_plan.id, created_at=now)
    )

    result = await hooks.on_todo_complete(sample_todo.id, "session-1")

    assert result is not None
    assert result.prompt_type == "plan_complete"
    assert "Phase 1: Schema and Storage" in result.message
    assert "postmortem" in result.message.lower()
    assert result.entity_id == sample_plan.id


@pytest.mark.asyncio
async def test_spike_complete_triggers_spike_prompt(hooks, goal_storage, sample_spike):
    """Test completing a spike triggers spike completion prompt."""
    await goal_storage.save_todo(sample_spike)

    result = await hooks.on_todo_complete(sample_spike.id, "session-1")

    assert result is not None
    assert result.prompt_type == "spike_complete"
    assert "Investigate caching options" in result.message
    assert len(result.choices) == 3
    assert "Promote" in result.choices[0]
    assert "Spawn" in result.choices[1]
    assert "Discard" in result.choices[2]


@pytest.mark.asyncio
async def test_spikes_dont_block_plan_completion(hooks, goal_storage, sample_goal, sample_plan, sample_todo, sample_spike):
    """Test that spikes don't block plan completion."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)
    await goal_storage.save_todo(sample_todo)
    await goal_storage.save_todo(sample_spike)

    now = datetime.now().isoformat()
    # Link both to plan
    await goal_storage.save_todo_plan_link(
        TodoPlanLink(todo_id=sample_todo.id, plan_id=sample_plan.id, created_at=now)
    )
    await goal_storage.save_todo_plan_link(
        TodoPlanLink(todo_id=sample_spike.id, plan_id=sample_plan.id, created_at=now)
    )

    # Complete the regular todo (spike still pending)
    result = await hooks.on_todo_complete(sample_todo.id, "session-1")

    # Should trigger plan complete - spike doesn't block it
    assert result is not None
    assert result.prompt_type == "plan_complete"


# =============================================================================
# Plan Completion Hook Tests
# =============================================================================


@pytest.mark.asyncio
async def test_plan_complete_not_found(hooks):
    """Test plan completion when plan doesn't exist."""
    result = await hooks.on_plan_complete("nonexistent", "session-1")
    assert result is None


@pytest.mark.asyncio
async def test_plan_complete_no_goal(hooks, goal_storage, sample_plan):
    """Test plan completion when goal doesn't exist."""
    await goal_storage.save_plan(sample_plan)

    result = await hooks.on_plan_complete(sample_plan.id, "session-1")
    assert result is None


@pytest.mark.asyncio
async def test_plan_complete_triggers_postmortem(hooks, goal_storage, sample_goal, sample_plan):
    """Test plan completion triggers postmortem prompt."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)

    result = await hooks.on_plan_complete(sample_plan.id, "session-1")

    assert result is not None
    assert result.prompt_type == "postmortem"
    assert sample_plan.title in result.message
    assert sample_goal.title in result.message
    # Check acceptance criteria are shown
    assert "Schema defined" in result.message
    assert "CRUD working" in result.message
    assert len(result.choices) == 4


# =============================================================================
# Postmortem Execution Tests
# =============================================================================


@pytest.mark.asyncio
async def test_postmortem_success(hooks, goal_storage, sample_goal, sample_plan):
    """Test SUCCESS postmortem outcome marks goal complete."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)

    result = await hooks.execute_postmortem(
        plan_id=sample_plan.id,
        outcome=PostmortemOutcome.SUCCESS,
        session_id="session-1",
        notes="All criteria verified and working.",
    )

    assert result is not None
    assert result.prompt_type == "goal_complete"
    assert sample_goal.title in result.message

    # Verify plan marked complete
    plan = await goal_storage.load_plan(sample_plan.id)
    assert plan.status == "completed"
    assert plan.completed_at is not None
    assert "criteria verified" in plan.postmortem

    # Verify goal marked complete
    goal = await goal_storage.load_goal(sample_goal.id)
    assert goal.status == "completed"
    assert goal.completed_at is not None


@pytest.mark.asyncio
async def test_postmortem_retry(hooks, goal_storage, sample_goal, sample_plan):
    """Test RETRY postmortem outcome prompts for new plan."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)

    result = await hooks.execute_postmortem(
        plan_id=sample_plan.id,
        outcome=PostmortemOutcome.RETRY,
        session_id="session-1",
        notes="UI integration still needs work.",
    )

    assert result is not None
    assert result.prompt_type == "new_plan_needed"
    assert "did not meet criteria" in result.message
    assert sample_goal.title in result.message

    # Verify plan marked complete but goal still active
    plan = await goal_storage.load_plan(sample_plan.id)
    assert plan.status == "completed"
    assert "retry needed" in plan.postmortem.lower() or "UI integration" in plan.postmortem

    goal = await goal_storage.load_goal(sample_goal.id)
    assert goal.status == "active"  # Goal stays active for retry


@pytest.mark.asyncio
async def test_postmortem_adjust(hooks, goal_storage, sample_goal, sample_plan):
    """Test ADJUST postmortem outcome updates criteria."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)

    new_criteria = [
        "Schema defined",
        "CRUD working",
        "Basic UI integrated (detailed UI in Phase 2)",
    ]

    result = await hooks.execute_postmortem(
        plan_id=sample_plan.id,
        outcome=PostmortemOutcome.ADJUST,
        session_id="session-1",
        notes="Simplified UI requirements.",
        new_criteria=new_criteria,
    )

    assert result is not None
    assert result.prompt_type == "criteria_adjusted"
    assert "criteria updated" in result.message.lower()

    # Verify goal criteria updated
    goal = await goal_storage.load_goal(sample_goal.id)
    assert goal.acceptance_criteria == new_criteria
    assert goal.status == "active"  # Goal stays active


@pytest.mark.asyncio
async def test_postmortem_abandon(hooks, goal_storage, sample_goal, sample_plan):
    """Test ABANDON postmortem outcome marks goal abandoned."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)

    result = await hooks.execute_postmortem(
        plan_id=sample_plan.id,
        outcome=PostmortemOutcome.ABANDON,
        session_id="session-1",
        abandon_reason="Requirements changed - feature no longer needed.",
    )

    assert result is not None
    assert result.prompt_type == "goal_abandoned"
    assert "Requirements changed" in result.message

    # Verify both plan and goal abandoned
    plan = await goal_storage.load_plan(sample_plan.id)
    assert plan.status == "abandoned"

    goal = await goal_storage.load_goal(sample_goal.id)
    assert goal.status == "abandoned"


# =============================================================================
# Spike Outcome Tests
# =============================================================================


@pytest.mark.asyncio
async def test_spike_promote(hooks, goal_storage, sample_spike):
    """Test promoting spike to completed todo."""
    await goal_storage.save_todo(sample_spike)

    result = await hooks.execute_spike_outcome(
        spike_id=sample_spike.id,
        outcome=SpikeOutcome.PROMOTE,
        session_id="session-1",
        notes="Redis implementation is production-ready.",
    )

    assert result is not None
    assert result.prompt_type == "spike_promoted"

    # Verify spike converted to regular completed todo
    todo = await goal_storage.load_todo(sample_spike.id)
    assert todo.status == "completed"
    assert todo.is_spike is False
    assert todo.timebox_minutes is None
    assert "production-ready" in todo.description


@pytest.mark.asyncio
async def test_spike_spawn_goal_with_draft(hooks, goal_storage, sample_spike):
    """Test spawning a new goal from spike with draft provided."""
    await goal_storage.save_todo(sample_spike)

    goal_draft = {
        "title": "Implement Redis caching layer",
        "description": "Add Redis caching to improve performance",
        "weight": 7,
        "acceptance_criteria": [
            "Redis cache client implemented",
            "Cache invalidation on writes",
            "TTL support",
        ],
    }

    result = await hooks.execute_spike_outcome(
        spike_id=sample_spike.id,
        outcome=SpikeOutcome.SPAWN_GOAL,
        session_id="session-1",
        goal_draft=goal_draft,
    )

    assert result is not None
    assert result.prompt_type == "goal_spawned"
    assert "Implement Redis caching layer" in result.message

    # Verify spike marked complete
    spike = await goal_storage.load_todo(sample_spike.id)
    assert spike.status == "completed"

    # Verify new goal created
    goals = await goal_storage.list_goals(status="active")
    assert len(goals) == 1
    assert goals[0].title == "Implement Redis caching layer"
    assert goals[0].weight == 7
    assert len(goals[0].acceptance_criteria) == 3


@pytest.mark.asyncio
async def test_spike_spawn_goal_without_draft(hooks, goal_storage, sample_spike):
    """Test spawning goal from spike without draft prompts for details."""
    await goal_storage.save_todo(sample_spike)

    result = await hooks.execute_spike_outcome(
        spike_id=sample_spike.id,
        outcome=SpikeOutcome.SPAWN_GOAL,
        session_id="session-1",
    )

    assert result is not None
    assert result.prompt_type == "goal_draft_needed"
    assert "new direction" in result.message.lower()
    assert "Create Goal" in result.choices


@pytest.mark.asyncio
async def test_spike_discard(hooks, goal_storage, sample_spike):
    """Test discarding spike with learnings noted."""
    await goal_storage.save_todo(sample_spike)

    result = await hooks.execute_spike_outcome(
        spike_id=sample_spike.id,
        outcome=SpikeOutcome.DISCARD,
        session_id="session-1",
        notes="Memcached sufficient for our use case - no need for Redis.",
    )

    assert result is not None
    assert result.prompt_type == "spike_discarded"

    # Verify spike marked complete with learnings
    spike = await goal_storage.load_todo(sample_spike.id)
    assert spike.status == "completed"
    assert spike.is_spike is True  # Still marked as spike
    assert "Memcached sufficient" in spike.description


# =============================================================================
# Binding Release Tests
# =============================================================================


@pytest.mark.asyncio
async def test_release_bindings_on_completion(hooks, goal_storage, sample_goal):
    """Test that bindings are released when entity is completed."""
    await goal_storage.save_goal(sample_goal)

    now = datetime.now().isoformat()
    bindings = [
        SessionBinding(
            id="b1",
            session_id="session-1",
            entity_type="goal",
            entity_id=sample_goal.id,
            role="planning",
            created_at=now,
        ),
        SessionBinding(
            id="b2",
            session_id="session-2",
            entity_type="goal",
            entity_id=sample_goal.id,
            role="implementation",
            created_at=now,
        ),
    ]

    for binding in bindings:
        await goal_storage.save_session_binding(binding)

    # Verify bindings are active
    active = await goal_storage.get_bindings_for_entity("goal", sample_goal.id, active_only=True)
    assert len(active) == 2

    # Release bindings
    released = await hooks.release_bindings_for_entity("goal", sample_goal.id)
    assert released == 2

    # Verify bindings are now released
    active = await goal_storage.get_bindings_for_entity("goal", sample_goal.id, active_only=True)
    assert len(active) == 0

    all_bindings = await goal_storage.get_bindings_for_entity("goal", sample_goal.id, active_only=False)
    assert len(all_bindings) == 2
    for binding in all_bindings:
        assert binding.released_at is not None


# =============================================================================
# Convenience Function Tests
# =============================================================================


@pytest.mark.asyncio
async def test_convenience_on_todo_complete(goal_storage, sample_todo, monkeypatch):
    """Test convenience function for todo completion."""
    await goal_storage.save_todo(sample_todo)

    async def mock_get_goal_storage():
        return goal_storage

    # Patch in lifecycle_hooks module where it's imported and used
    from core import lifecycle_hooks
    monkeypatch.setattr(lifecycle_hooks, "get_goal_storage", mock_get_goal_storage)

    result = await on_todo_complete(sample_todo.id, "session-1")
    # Todo not linked to plan, so no prompt
    assert result is None


@pytest.mark.asyncio
async def test_convenience_execute_postmortem(goal_storage, sample_goal, sample_plan, monkeypatch):
    """Test convenience function for postmortem execution."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)

    async def mock_get_goal_storage():
        return goal_storage

    # Patch in lifecycle_hooks module where it's imported and used
    from core import lifecycle_hooks
    monkeypatch.setattr(lifecycle_hooks, "get_goal_storage", mock_get_goal_storage)

    result = await execute_postmortem(
        sample_plan.id,
        PostmortemOutcome.SUCCESS,
        "session-1",
        notes="All done!",
    )

    assert result is not None
    assert result.prompt_type == "goal_complete"


# =============================================================================
# Edge Cases
# =============================================================================


@pytest.mark.asyncio
async def test_plan_with_only_completed_todos(hooks, goal_storage, sample_goal, sample_plan):
    """Test plan where all todos were already complete."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)

    now = datetime.now().isoformat()
    # Create already-completed todos
    for i in range(3):
        todo = TodoData(
            id=f"todo-{i}",
            title=f"Task {i}",
            description="",
            status="completed",
            completed_at=now,
            is_spike=False,
            created_at=now,
            updated_at=now,
        )
        await goal_storage.save_todo(todo)
        await goal_storage.save_todo_plan_link(
            TodoPlanLink(todo_id=todo.id, plan_id=sample_plan.id, created_at=now)
        )

    # Check plan completion
    is_complete = await hooks._check_plan_completion(sample_plan.id)
    assert is_complete is True


@pytest.mark.asyncio
async def test_plan_with_blocked_todo(hooks, goal_storage, sample_goal, sample_plan):
    """Test plan with blocked todo is not considered complete."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)

    now = datetime.now().isoformat()
    blocked = TodoData(
        id="blocked-todo",
        title="Blocked task",
        description="",
        status="blocked",
        is_spike=False,
        created_at=now,
        updated_at=now,
    )
    await goal_storage.save_todo(blocked)
    await goal_storage.save_todo_plan_link(
        TodoPlanLink(todo_id=blocked.id, plan_id=sample_plan.id, created_at=now)
    )

    is_complete = await hooks._check_plan_completion(sample_plan.id)
    assert is_complete is False


@pytest.mark.asyncio
async def test_plan_with_no_todos(hooks, goal_storage, sample_plan):
    """Test plan with no todos is not considered complete."""
    await goal_storage.save_plan(sample_plan)

    is_complete = await hooks._check_plan_completion(sample_plan.id)
    assert is_complete is False


@pytest.mark.asyncio
async def test_postmortem_plan_not_found(hooks):
    """Test postmortem when plan doesn't exist."""
    result = await hooks.execute_postmortem(
        plan_id="nonexistent",
        outcome=PostmortemOutcome.SUCCESS,
        session_id="session-1",
    )
    assert result is None


@pytest.mark.asyncio
async def test_spike_outcome_not_spike(hooks, goal_storage, sample_todo):
    """Test spike outcome on regular todo returns None."""
    await goal_storage.save_todo(sample_todo)

    result = await hooks.execute_spike_outcome(
        spike_id=sample_todo.id,
        outcome=SpikeOutcome.PROMOTE,
        session_id="session-1",
    )
    assert result is None
