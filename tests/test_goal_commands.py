"""Tests for goal-oriented task management commands."""

import pytest
import uuid
from datetime import datetime
from pathlib import Path
import tempfile
import shutil

from core.goal_commands import (
    GoalCommandExecutor,
    check_priority_divergence,
    get_session_binding_indicator,
)
from core.async_storage import GoalStorage
from storage_schema import (
    GoalData, PlanData, TodoData, TodoPlanLink, SessionBinding
)


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
def sample_goal():
    """Create a sample goal for testing."""
    return GoalData(
        id=str(uuid.uuid4()),
        title="Build UI Components",
        description="Create reusable UI components for the app",
        weight=8,
        status="active",
        acceptance_criteria=["Components are tested", "Documentation complete"],
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
    )


@pytest.fixture
def sample_plan(sample_goal):
    """Create a sample plan for testing."""
    return PlanData(
        id=str(uuid.uuid4()),
        goal_id=sample_goal.id,
        title="Phase 1: Core Components",
        description="Build button, input, and modal components",
        status="active",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
    )


@pytest.fixture
def sample_todo():
    """Create a sample todo for testing."""
    return TodoData(
        id=str(uuid.uuid4()),
        title="Implement Button Component",
        description="Create a reusable button with variants",
        status="pending",
        is_spike=False,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
    )


class TestGoalCommandExecutor:
    """Tests for GoalCommandExecutor."""

    @pytest.mark.asyncio
    async def test_list_goals_empty(self, goal_storage):
        """Test listing goals when none exist."""
        executor = GoalCommandExecutor(goal_storage)
        result = await executor.list_goals()

        assert result.success
        assert len(result.goals) == 0
        assert "No goals found" in result.formatted

    @pytest.mark.asyncio
    async def test_list_goals_with_data(self, goal_storage, sample_goal):
        """Test listing goals with data."""
        await goal_storage.save_goal(sample_goal)

        executor = GoalCommandExecutor(goal_storage)
        result = await executor.list_goals()

        assert result.success
        assert len(result.goals) == 1
        assert result.goals[0].id == sample_goal.id
        assert sample_goal.title in result.formatted

    @pytest.mark.asyncio
    async def test_list_goals_excludes_completed(self, goal_storage, sample_goal):
        """Test that completed goals are excluded by default."""
        # Create active and completed goals
        await goal_storage.save_goal(sample_goal)

        completed_goal = GoalData(
            id=str(uuid.uuid4()),
            title="Old Goal",
            description="Already done",
            weight=5,
            status="completed",
            acceptance_criteria=[],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        await goal_storage.save_goal(completed_goal)

        executor = GoalCommandExecutor(goal_storage)

        # Without --all, only active goals
        result = await executor.list_goals(include_completed=False)
        assert len(result.goals) == 1
        assert result.goals[0].status == "active"

        # With --all, all goals
        result = await executor.list_goals(include_completed=True)
        assert len(result.goals) == 2

    @pytest.mark.asyncio
    async def test_list_plans(self, goal_storage, sample_goal, sample_plan):
        """Test listing plans."""
        await goal_storage.save_goal(sample_goal)
        await goal_storage.save_plan(sample_plan)

        executor = GoalCommandExecutor(goal_storage)
        result = await executor.list_plans()

        assert result.success
        assert len(result.plans) == 1
        assert result.plans[0].id == sample_plan.id

    @pytest.mark.asyncio
    async def test_list_plans_filtered_by_goal(self, goal_storage, sample_goal, sample_plan):
        """Test listing plans filtered by goal."""
        await goal_storage.save_goal(sample_goal)
        await goal_storage.save_plan(sample_plan)

        # Create another goal with its own plan
        other_goal = GoalData(
            id=str(uuid.uuid4()),
            title="Other Goal",
            description="Different goal",
            weight=3,
            status="active",
            acceptance_criteria=[],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        await goal_storage.save_goal(other_goal)

        other_plan = PlanData(
            id=str(uuid.uuid4()),
            goal_id=other_goal.id,
            title="Other Plan",
            description="For other goal",
            status="active",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        await goal_storage.save_plan(other_plan)

        executor = GoalCommandExecutor(goal_storage)

        # Filter by goal ID prefix
        result = await executor.list_plans(sample_goal.id[:8])
        assert result.success
        assert len(result.plans) == 1
        assert result.plans[0].id == sample_plan.id

    @pytest.mark.asyncio
    async def test_list_todos_priority_ranked(
        self, goal_storage, sample_goal, sample_plan, sample_todo
    ):
        """Test listing todos with priority ranking."""
        await goal_storage.save_goal(sample_goal)
        await goal_storage.save_plan(sample_plan)
        await goal_storage.save_todo(sample_todo)

        # Link todo to plan
        link = TodoPlanLink(
            todo_id=sample_todo.id,
            plan_id=sample_plan.id,
            created_at=datetime.now().isoformat(),
        )
        await goal_storage.save_todo_plan_link(link)

        executor = GoalCommandExecutor(goal_storage)
        result = await executor.list_todos()

        assert result.success
        assert len(result.todos) == 1
        assert result.todos[0].todo.id == sample_todo.id
        # Priority should be goal_weight * completion_factor (0.1 for empty plan)
        assert result.todos[0].priority == pytest.approx(0.8, rel=0.1)  # 8 * 0.1

    @pytest.mark.asyncio
    async def test_bind_session(self, goal_storage, sample_goal):
        """Test binding a session to a goal."""
        await goal_storage.save_goal(sample_goal)

        executor = GoalCommandExecutor(goal_storage)
        session_id = str(uuid.uuid4())

        result = await executor.bind_session(
            session_id, "goal", sample_goal.id[:8], "planning"
        )

        assert result.success
        assert result.binding is not None
        assert result.binding.entity_type == "goal"
        assert result.binding.role == "planning"

        # Verify binding was saved
        bindings = await goal_storage.get_bindings_for_session(session_id)
        assert len(bindings) == 1

    @pytest.mark.asyncio
    async def test_unbind_session(self, goal_storage, sample_goal):
        """Test unbinding a session."""
        await goal_storage.save_goal(sample_goal)
        session_id = str(uuid.uuid4())

        # First bind
        executor = GoalCommandExecutor(goal_storage)
        await executor.bind_session(session_id, "goal", sample_goal.id[:8])

        # Then unbind
        result = await executor.unbind_session(session_id)

        assert result.success
        assert result.released_count == 1

        # Verify no active bindings remain
        bindings = await goal_storage.get_bindings_for_session(session_id, active_only=True)
        assert len(bindings) == 0


class TestPriorityDivergence:
    """Tests for priority divergence checking."""

    @pytest.mark.asyncio
    async def test_no_divergence_when_not_bound(self, goal_storage):
        """Test that no divergence is reported when session has no todo binding."""
        session_id = str(uuid.uuid4())

        # Patch the get_goal_storage to return our test storage
        import core.goal_commands
        original_get = core.goal_commands.get_goal_storage

        async def mock_get():
            return goal_storage

        core.goal_commands.get_goal_storage = mock_get

        try:
            info = await check_priority_divergence(session_id)
            assert not info.is_diverged
            assert info.bound_todo is None
        finally:
            core.goal_commands.get_goal_storage = original_get

    @pytest.mark.asyncio
    async def test_divergence_when_working_on_lower_priority(
        self, goal_storage, sample_goal
    ):
        """Test divergence detection when bound to lower priority todo."""
        # Create two todos with different priorities
        high_priority_goal = GoalData(
            id=str(uuid.uuid4()),
            title="Urgent Fix",
            description="Critical bug",
            weight=10,
            status="active",
            acceptance_criteria=[],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        await goal_storage.save_goal(high_priority_goal)

        low_priority_goal = GoalData(
            id=str(uuid.uuid4()),
            title="Nice to have",
            description="Low priority",
            weight=2,
            status="active",
            acceptance_criteria=[],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        await goal_storage.save_goal(low_priority_goal)

        # Create plans
        high_plan = PlanData(
            id=str(uuid.uuid4()),
            goal_id=high_priority_goal.id,
            title="Fix Plan",
            description="",
            status="active",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        await goal_storage.save_plan(high_plan)

        low_plan = PlanData(
            id=str(uuid.uuid4()),
            goal_id=low_priority_goal.id,
            title="Low Plan",
            description="",
            status="active",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        await goal_storage.save_plan(low_plan)

        # Create todos
        high_todo = TodoData(
            id=str(uuid.uuid4()),
            title="Fix critical bug",
            description="",
            status="pending",
            is_spike=False,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        await goal_storage.save_todo(high_todo)

        low_todo = TodoData(
            id=str(uuid.uuid4()),
            title="Minor cleanup",
            description="",
            status="pending",
            is_spike=False,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        await goal_storage.save_todo(low_todo)

        # Link todos to plans
        await goal_storage.save_todo_plan_link(TodoPlanLink(
            todo_id=high_todo.id,
            plan_id=high_plan.id,
            created_at=datetime.now().isoformat(),
        ))
        await goal_storage.save_todo_plan_link(TodoPlanLink(
            todo_id=low_todo.id,
            plan_id=low_plan.id,
            created_at=datetime.now().isoformat(),
        ))

        # Bind session to LOW priority todo
        session_id = str(uuid.uuid4())
        binding = SessionBinding(
            id=str(uuid.uuid4()),
            session_id=session_id,
            entity_type="todo",
            entity_id=low_todo.id,
            role="implementation",
            created_at=datetime.now().isoformat(),
        )
        await goal_storage.save_session_binding(binding)

        # Patch get_goal_storage
        import core.goal_commands
        original_get = core.goal_commands.get_goal_storage

        async def mock_get():
            return goal_storage

        core.goal_commands.get_goal_storage = mock_get

        try:
            info = await check_priority_divergence(session_id)

            assert info.is_diverged
            assert info.bound_todo.id == low_todo.id
            assert info.top_todo.id == high_todo.id
            assert info.top_priority > info.bound_priority
            assert "Higher priority" in info.message
        finally:
            core.goal_commands.get_goal_storage = original_get


class TestBindingIndicator:
    """Tests for session binding indicators."""

    @pytest.mark.asyncio
    async def test_no_indicator_when_not_bound(self, goal_storage):
        """Test that no indicator is returned when session has no bindings."""
        session_id = str(uuid.uuid4())

        # Patch the get_goal_storage to return our test storage
        import core.goal_commands
        original_get = core.goal_commands.get_goal_storage

        async def mock_get():
            return goal_storage

        core.goal_commands.get_goal_storage = mock_get

        try:
            indicator = await get_session_binding_indicator(session_id)
            assert indicator == ""
        finally:
            core.goal_commands.get_goal_storage = original_get

    @pytest.mark.asyncio
    async def test_indicator_for_todo_binding(self, goal_storage, sample_todo):
        """Test indicator format for todo binding."""
        await goal_storage.save_todo(sample_todo)

        session_id = str(uuid.uuid4())
        binding = SessionBinding(
            id=str(uuid.uuid4()),
            session_id=session_id,
            entity_type="todo",
            entity_id=sample_todo.id,
            role="implementation",
            created_at=datetime.now().isoformat(),
        )
        await goal_storage.save_session_binding(binding)

        # Patch get_goal_storage
        import core.goal_commands
        original_get = core.goal_commands.get_goal_storage

        async def mock_get():
            return goal_storage

        core.goal_commands.get_goal_storage = mock_get

        try:
            indicator = await get_session_binding_indicator(session_id)
            # Should be "[impl: Implement Button Component]"
            assert indicator.startswith("[impl:")
            assert "Button" in indicator or "Implement" in indicator
            assert indicator.endswith("]")
        finally:
            core.goal_commands.get_goal_storage = original_get

    @pytest.mark.asyncio
    async def test_indicator_prioritizes_todo_over_goal(self, goal_storage, sample_goal, sample_todo):
        """Test that todo binding takes priority over goal binding."""
        await goal_storage.save_goal(sample_goal)
        await goal_storage.save_todo(sample_todo)

        session_id = str(uuid.uuid4())

        # Bind to goal first
        goal_binding = SessionBinding(
            id=str(uuid.uuid4()),
            session_id=session_id,
            entity_type="goal",
            entity_id=sample_goal.id,
            role="planning",
            created_at="2024-01-01T00:00:00",  # Earlier
        )
        await goal_storage.save_session_binding(goal_binding)

        # Then bind to todo (more specific)
        todo_binding = SessionBinding(
            id=str(uuid.uuid4()),
            session_id=session_id,
            entity_type="todo",
            entity_id=sample_todo.id,
            role="implementation",
            created_at="2024-01-02T00:00:00",  # Later
        )
        await goal_storage.save_session_binding(todo_binding)

        # Patch get_goal_storage
        import core.goal_commands
        original_get = core.goal_commands.get_goal_storage

        async def mock_get():
            return goal_storage

        core.goal_commands.get_goal_storage = mock_get

        try:
            indicator = await get_session_binding_indicator(session_id)
            # Should show todo (more specific), not goal
            assert "impl" in indicator
            assert "plan" not in indicator  # Not the planning role
        finally:
            core.goal_commands.get_goal_storage = original_get

    @pytest.mark.asyncio
    async def test_indicator_truncates_long_titles(self, goal_storage):
        """Test that long entity titles are truncated."""
        long_todo = TodoData(
            id=str(uuid.uuid4()),
            title="This is a very long todo title that should be truncated for display",
            description="",
            status="pending",
            is_spike=False,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        await goal_storage.save_todo(long_todo)

        session_id = str(uuid.uuid4())
        binding = SessionBinding(
            id=str(uuid.uuid4()),
            session_id=session_id,
            entity_type="todo",
            entity_id=long_todo.id,
            role="implementation",
            created_at=datetime.now().isoformat(),
        )
        await goal_storage.save_session_binding(binding)

        # Patch get_goal_storage
        import core.goal_commands
        original_get = core.goal_commands.get_goal_storage

        async def mock_get():
            return goal_storage

        core.goal_commands.get_goal_storage = mock_get

        try:
            indicator = await get_session_binding_indicator(session_id)
            # Title should be truncated to 20 chars + "..."
            assert "..." in indicator
            # The full title should not be present
            assert "truncated for display" not in indicator
        finally:
            core.goal_commands.get_goal_storage = original_get
