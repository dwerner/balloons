"""Tests for session binding context building."""

import tempfile
from pathlib import Path
from datetime import datetime

import pytest

from core.async_storage import GoalStorage
from core.binding_context import BindingContextBuilder, build_binding_context_for_session, _load_role_guidance
from storage_schema import GoalData, PlanData, TodoData, SessionBinding


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


@pytest.mark.asyncio
async def test_no_bindings_returns_empty(goal_storage):
    """Test that a session with no bindings returns empty context."""
    builder = BindingContextBuilder(goal_storage)
    context = await builder.build_binding_context("session-no-bindings")
    assert context == ""


@pytest.mark.asyncio
async def test_goal_binding_context(goal_storage, sample_goal):
    """Test building context from a goal binding."""
    await goal_storage.save_goal(sample_goal)

    now = datetime.now().isoformat()
    binding = SessionBinding(
        id="b1",
        session_id="session-1",
        entity_type="goal",
        entity_id=sample_goal.id,
        role="planning",
        created_at=now,
    )
    await goal_storage.save_session_binding(binding)

    builder = BindingContextBuilder(goal_storage)
    context = await builder.build_binding_context("session-1")

    assert "Session Bindings" in context
    assert "Build goal tracking system" in context
    assert "weight: 8/10" in context
    assert "role: planning" in context
    assert "Schema defined" in context
    assert "CRUD working" in context


@pytest.mark.asyncio
async def test_plan_binding_with_goal_context(goal_storage, sample_goal, sample_plan):
    """Test building context from a plan binding includes goal context."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)

    now = datetime.now().isoformat()
    binding = SessionBinding(
        id="b2",
        session_id="session-2",
        entity_type="plan",
        entity_id=sample_plan.id,
        role="implementation",
        created_at=now,
    )
    await goal_storage.save_session_binding(binding)

    builder = BindingContextBuilder(goal_storage)
    context = await builder.build_binding_context("session-2")

    assert "Phase 1: Schema and Storage" in context
    assert "role: implementation" in context
    assert "Define entities and implement storage layer" in context
    # Should include parent goal reference
    assert "Part of goal: Build goal tracking system" in context


@pytest.mark.asyncio
async def test_todo_binding_context(goal_storage, sample_todo):
    """Test building context from a todo binding."""
    await goal_storage.save_todo(sample_todo)

    now = datetime.now().isoformat()
    binding = SessionBinding(
        id="b3",
        session_id="session-3",
        entity_type="todo",
        entity_id=sample_todo.id,
        role="implementation",
        created_at=now,
    )
    await goal_storage.save_session_binding(binding)

    builder = BindingContextBuilder(goal_storage)
    context = await builder.build_binding_context("session-3")

    assert "Add dataclasses to storage_schema.py" in context
    assert "role: implementation" in context
    assert "Define GoalData, PlanData, TodoData" in context
    # Regular todo should not mention spike
    assert "spike" not in context.lower()


@pytest.mark.asyncio
async def test_spike_binding_context(goal_storage, sample_spike):
    """Test building context from a spike binding includes timebox info."""
    await goal_storage.save_todo(sample_spike)

    now = datetime.now().isoformat()
    binding = SessionBinding(
        id="b4",
        session_id="session-4",
        entity_type="todo",
        entity_id=sample_spike.id,
        role="exploration",
        created_at=now,
    )
    await goal_storage.save_session_binding(binding)

    builder = BindingContextBuilder(goal_storage)
    context = await builder.build_binding_context("session-4")

    assert "Investigate caching options" in context
    assert "spike" in context.lower()
    assert "60 min" in context
    assert "timeboxed exploration" in context.lower()


@pytest.mark.asyncio
async def test_multiple_bindings(goal_storage, sample_goal, sample_plan, sample_todo):
    """Test building context from multiple bindings."""
    await goal_storage.save_goal(sample_goal)
    await goal_storage.save_plan(sample_plan)
    await goal_storage.save_todo(sample_todo)

    now = datetime.now().isoformat()
    bindings = [
        SessionBinding(
            id="b5",
            session_id="session-5",
            entity_type="goal",
            entity_id=sample_goal.id,
            role="planning",
            created_at=now,
        ),
        SessionBinding(
            id="b6",
            session_id="session-5",
            entity_type="plan",
            entity_id=sample_plan.id,
            role="implementation",
            created_at=now,
        ),
        SessionBinding(
            id="b7",
            session_id="session-5",
            entity_type="todo",
            entity_id=sample_todo.id,
            role="implementation",
            created_at=now,
        ),
    ]

    for binding in bindings:
        await goal_storage.save_session_binding(binding)

    builder = BindingContextBuilder(goal_storage)
    context = await builder.build_binding_context("session-5")

    # All three should be present
    assert "Build goal tracking system" in context
    assert "Phase 1: Schema and Storage" in context
    assert "Add dataclasses to storage_schema.py" in context


@pytest.mark.asyncio
async def test_released_bindings_excluded(goal_storage, sample_goal):
    """Test that released bindings are not included in context."""
    await goal_storage.save_goal(sample_goal)

    now = datetime.now().isoformat()
    # Active binding
    active = SessionBinding(
        id="b8",
        session_id="session-6",
        entity_type="goal",
        entity_id=sample_goal.id,
        role="planning",
        created_at=now,
    )
    # Released binding
    released = SessionBinding(
        id="b9",
        session_id="session-6",
        entity_type="goal",
        entity_id="goal-other",
        role="postmortem",
        created_at=now,
        released_at=now,  # This binding has been released
    )

    await goal_storage.save_session_binding(active)
    await goal_storage.save_session_binding(released)

    builder = BindingContextBuilder(goal_storage)
    context = await builder.build_binding_context("session-6")

    # Only active binding should be present
    assert "role: planning" in context
    assert "postmortem" not in context


@pytest.mark.asyncio
async def test_missing_entity_handled_gracefully(goal_storage):
    """Test that binding to non-existent entity is handled gracefully."""
    now = datetime.now().isoformat()
    binding = SessionBinding(
        id="b10",
        session_id="session-7",
        entity_type="goal",
        entity_id="nonexistent-goal",
        role="planning",
        created_at=now,
    )
    await goal_storage.save_session_binding(binding)

    builder = BindingContextBuilder(goal_storage)
    context = await builder.build_binding_context("session-7")

    # Should still have header but no goal content
    assert "Session Bindings" in context
    assert "nonexistent-goal" not in context


@pytest.mark.asyncio
async def test_convenience_function(goal_storage, sample_goal, monkeypatch):
    """Test the convenience function for building context."""
    await goal_storage.save_goal(sample_goal)

    now = datetime.now().isoformat()
    binding = SessionBinding(
        id="b11",
        session_id="session-8",
        entity_type="goal",
        entity_id=sample_goal.id,
        role="planning",
        created_at=now,
    )
    await goal_storage.save_session_binding(binding)

    # Monkeypatch get_goal_storage to return our test storage
    async def mock_get_goal_storage():
        return goal_storage

    from core import binding_context
    monkeypatch.setattr(binding_context, "get_goal_storage", mock_get_goal_storage)

    context = await build_binding_context_for_session("session-8")
    assert "Build goal tracking system" in context


# =============================================================================
# Role Guidance Tests
# =============================================================================


class TestRoleGuidance:
    """Tests for role-specific guidance injection."""

    @pytest.mark.asyncio
    async def test_planning_role_includes_fork_guidance(self, goal_storage, sample_goal):
        """Test that planning role includes guidance to fork for implementation."""
        await goal_storage.save_goal(sample_goal)

        now = datetime.now().isoformat()
        binding = SessionBinding(
            id="b-plan-1",
            session_id="session-planning",
            entity_type="goal",
            entity_id=sample_goal.id,
            role="planning",
            created_at=now,
        )
        await goal_storage.save_session_binding(binding)

        builder = BindingContextBuilder(goal_storage)
        context = await builder.build_binding_context("session-planning")

        # Planning guidance should include fork instructions (from prompts/shared/roles/planning.md)
        assert "Planning Role" in context
        assert "propose_fork" in context
        assert "Do NOT implement code" in context

    @pytest.mark.asyncio
    async def test_implementation_role_includes_merge_guidance(self, goal_storage, sample_todo):
        """Test that implementation role includes guidance to merge when done."""
        await goal_storage.save_todo(sample_todo)

        now = datetime.now().isoformat()
        binding = SessionBinding(
            id="b-impl-1",
            session_id="session-impl",
            entity_type="todo",
            entity_id=sample_todo.id,
            role="implementation",
            created_at=now,
        )
        await goal_storage.save_session_binding(binding)

        builder = BindingContextBuilder(goal_storage)

        # Test standalone session (not a fork) - should NOT mention merge
        context_standalone = await builder.build_binding_context("session-impl", is_fork=False)
        assert "Implementation Role" in context_standalone
        assert "Stay focused" in context_standalone
        assert "Session Completion (Standalone)" in context_standalone
        assert "Do NOT propose a merge" in context_standalone

        # Test fork session - should include merge instructions
        context_fork = await builder.build_binding_context("session-impl", is_fork=True)
        assert "Implementation Role" in context_fork
        assert "Stay focused" in context_fork
        assert "Session Completion (Fork)" in context_fork
        assert "propose_merge" in context_fork

    @pytest.mark.asyncio
    async def test_interview_role_includes_discovery_guidance(self, goal_storage, sample_goal):
        """Test that interview role includes guidance to stay in discovery mode."""
        await goal_storage.save_goal(sample_goal)

        now = datetime.now().isoformat()
        binding = SessionBinding(
            id="b-int-1",
            session_id="session-interview",
            entity_type="goal",
            entity_id=sample_goal.id,
            role="interview",
            created_at=now,
        )
        await goal_storage.save_session_binding(binding)

        builder = BindingContextBuilder(goal_storage)
        context = await builder.build_binding_context("session-interview")

        # Interview guidance should focus on goal discovery (from prompts/shared/roles/interview.md)
        assert "Interview Role" in context
        assert "goal discovery mode" in context
        assert "Do NOT start coding" in context

    @pytest.mark.asyncio
    async def test_exploration_role_includes_timebox_guidance(self, goal_storage, sample_spike):
        """Test that exploration role includes timebox guidance."""
        await goal_storage.save_todo(sample_spike)

        now = datetime.now().isoformat()
        binding = SessionBinding(
            id="b-exp-1",
            session_id="session-explore",
            entity_type="todo",
            entity_id=sample_spike.id,
            role="exploration",
            created_at=now,
        )
        await goal_storage.save_session_binding(binding)

        builder = BindingContextBuilder(goal_storage)
        context = await builder.build_binding_context("session-explore")

        # Exploration guidance should mention timebox (from prompts/shared/roles/exploration.md)
        assert "Exploration Role" in context
        assert "timebox" in context.lower()
        assert "Document findings" in context

    @pytest.mark.asyncio
    async def test_postmortem_role_includes_retrospective_guidance(self, goal_storage, sample_plan):
        """Test that postmortem role includes retrospective guidance."""
        await goal_storage.save_plan(sample_plan)

        now = datetime.now().isoformat()
        binding = SessionBinding(
            id="b-post-1",
            session_id="session-postmortem",
            entity_type="plan",
            entity_id=sample_plan.id,
            role="postmortem",
            created_at=now,
        )
        await goal_storage.save_session_binding(binding)

        builder = BindingContextBuilder(goal_storage)
        context = await builder.build_binding_context("session-postmortem")

        # Postmortem guidance should focus on reflection (from prompts/shared/roles/postmortem.md)
        assert "Postmortem Role" in context
        assert "retrospective" in context.lower()
        assert "what went well" in context.lower() or "what worked well" in context.lower()

    @pytest.mark.asyncio
    async def test_multiple_bindings_same_role_guidance_once(self, goal_storage, sample_goal, sample_plan):
        """Test that role guidance appears only once even with multiple bindings of same role."""
        await goal_storage.save_goal(sample_goal)
        await goal_storage.save_plan(sample_plan)

        now = datetime.now().isoformat()
        # Two bindings with planning role
        bindings = [
            SessionBinding(
                id="b-multi-1",
                session_id="session-multi",
                entity_type="goal",
                entity_id=sample_goal.id,
                role="planning",
                created_at=now,
            ),
            SessionBinding(
                id="b-multi-2",
                session_id="session-multi",
                entity_type="plan",
                entity_id=sample_plan.id,
                role="planning",
                created_at=now,
            ),
        ]

        for binding in bindings:
            await goal_storage.save_session_binding(binding)

        builder = BindingContextBuilder(goal_storage)
        context = await builder.build_binding_context("session-multi")

        # Planning guidance should appear exactly once
        assert context.count("## Planning Role") == 1

    @pytest.mark.asyncio
    async def test_multiple_different_roles_get_all_guidance(self, goal_storage, sample_goal, sample_todo):
        """Test that multiple different roles each get their guidance."""
        await goal_storage.save_goal(sample_goal)
        await goal_storage.save_todo(sample_todo)

        now = datetime.now().isoformat()
        # One binding with planning, one with implementation
        bindings = [
            SessionBinding(
                id="b-mixed-1",
                session_id="session-mixed",
                entity_type="goal",
                entity_id=sample_goal.id,
                role="planning",
                created_at=now,
            ),
            SessionBinding(
                id="b-mixed-2",
                session_id="session-mixed",
                entity_type="todo",
                entity_id=sample_todo.id,
                role="implementation",
                created_at=now,
            ),
        ]

        for binding in bindings:
            await goal_storage.save_session_binding(binding)

        builder = BindingContextBuilder(goal_storage)
        context = await builder.build_binding_context("session-mixed")

        # Both role guidances should be present
        assert "## Planning Role" in context
        assert "## Implementation Role" in context

    def test_all_roles_have_guidance_files(self):
        """Test that all expected roles have guidance files."""
        expected_roles = ["interview", "planning", "implementation", "postmortem", "exploration"]
        for role in expected_roles:
            guidance = _load_role_guidance(role)
            assert guidance, f"Role '{role}' guidance file missing or empty"
            assert len(guidance) > 50, f"Role '{role}' guidance too short"

    def test_unknown_role_returns_empty_guidance(self):
        """Test that unknown roles return empty guidance."""
        guidance = _load_role_guidance("unknown_role")
        assert guidance == ""
