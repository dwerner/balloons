"""Tests for GoalTreeStateService - WebSocket-exposed goal tree state management."""

import pytest
from datetime import datetime

from core.goal_tree_state import GoalTreeState, GoalTreeEvent
from service.goal_tree_state_service import (
    GoalTreeStateService,
    GoalInfo,
    PlanInfo,
    TodoInfo,
    SessionBindingInfo,
    GoalTreeStats,
    GoalProgress,
    SelectedEntity,
)
from storage_schema import GoalData, PlanData, TodoData


# =============================================================================
# Test Fixtures
# =============================================================================


def make_goal(
    id: str = "goal-1",
    title: str = "Test Goal",
    weight: int = 5,
    status: str = "active",
    parent_goal_id: str | None = None,
) -> GoalData:
    """Create a test goal."""
    now = datetime.now().isoformat()
    return GoalData(
        id=id,
        title=title,
        description=f"Description for {title}",
        weight=weight,
        status=status,
        acceptance_criteria=["Criterion 1", "Criterion 2"],
        created_at=now,
        updated_at=now,
        parent_goal_id=parent_goal_id,
    )


def make_plan(
    id: str = "plan-1",
    goal_id: str = "goal-1",
    title: str = "Test Plan",
    status: str = "active",
) -> PlanData:
    """Create a test plan."""
    now = datetime.now().isoformat()
    return PlanData(
        id=id,
        goal_id=goal_id,
        title=title,
        description=f"Description for {title}",
        status=status,
        created_at=now,
        updated_at=now,
    )


def make_todo(
    id: str = "todo-1",
    title: str = "Test Todo",
    status: str = "pending",
    is_spike: bool = False,
) -> TodoData:
    """Create a test todo."""
    now = datetime.now().isoformat()
    return TodoData(
        id=id,
        title=title,
        description=f"Description for {title}",
        status=status,
        is_spike=is_spike,
        created_at=now,
        updated_at=now,
    )


# =============================================================================
# Test Observer Pattern
# =============================================================================


class TestGoalTreeStateServiceObservers:
    """Test event handler management."""

    def test_add_event_handler(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        events = []

        def handler(event_name, data):
            events.append((event_name, data))

        service.add_event_handler(handler)
        state.add_goal(make_goal())

        assert len(events) == 1
        assert events[0][0] == "goalAdded"
        assert events[0][1]["goal_id"] == "goal-1"

    def test_remove_event_handler(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        events = []

        def handler(event_name, data):
            events.append((event_name, data))

        service.add_event_handler(handler)
        state.add_goal(make_goal(id="g1"))
        assert len(events) == 1

        service.remove_event_handler(handler)
        state.add_goal(make_goal(id="g2"))
        assert len(events) == 1  # Still 1, handler was removed

    def test_event_name_conversion(self):
        """Test GoalTreeEvent to camelCase conversion."""
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        events = []

        def handler(event_name, data):
            events.append(event_name)

        service.add_event_handler(handler)

        # Test various events
        state.add_goal(make_goal())  # GOAL_ADDED -> goalAdded
        goal = make_goal()
        goal.title = "Updated"
        state.add_goal(goal)  # GOAL_UPDATED -> goalUpdated
        state.add_plan(make_plan())  # PLAN_ADDED -> planAdded
        state.add_todo(make_todo(), ["plan-1"])  # TODO_ADDED -> todoAdded

        assert "goalAdded" in events
        assert "goalUpdated" in events
        assert "planAdded" in events
        assert "todoAdded" in events


# =============================================================================
# Test Goal Operations
# =============================================================================


class TestGoalTreeStateServiceGoalOperations:
    """Test goal CRUD operations."""

    @pytest.mark.asyncio
    async def test_get_goal(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1", title="My Goal"))

        result = await service.get_goal("g1")

        assert result is not None
        assert isinstance(result, GoalInfo)
        assert result.id == "g1"
        assert result.title == "My Goal"
        assert result.acceptance_criteria == ["Criterion 1", "Criterion 2"]

    @pytest.mark.asyncio
    async def test_get_goal_not_found(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)

        result = await service.get_goal("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_goals(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1", weight=5))
        state.add_goal(make_goal(id="g2", weight=8))
        state.add_goal(make_goal(id="g3", weight=3))

        result = await service.get_all_goals()

        assert len(result) == 3
        # Should be sorted by weight descending
        assert result[0].id == "g2"
        assert result[1].id == "g1"
        assert result[2].id == "g3"

    @pytest.mark.asyncio
    async def test_get_root_goals(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1", weight=5))
        state.add_goal(make_goal(id="g2", weight=8, parent_goal_id="g1"))

        result = await service.get_root_goals()

        assert len(result) == 1
        assert result[0].id == "g1"

    @pytest.mark.asyncio
    async def test_get_child_goals(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        state.add_goal(make_goal(id="g2", weight=8, parent_goal_id="g1"))
        state.add_goal(make_goal(id="g3", weight=3, parent_goal_id="g1"))

        result = await service.get_child_goals("g1")

        assert len(result) == 2
        # Should be sorted by weight descending
        assert result[0].id == "g2"
        assert result[1].id == "g3"

    @pytest.mark.asyncio
    async def test_add_goal(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        now = datetime.now().isoformat()

        await service.add_goal({
            "id": "g1",
            "title": "New Goal",
            "description": "A new goal",
            "weight": 7,
            "status": "active",
            "acceptance_criteria": ["Done when X"],
            "created_at": now,
            "updated_at": now,
        })

        node = state.get_goal("g1")
        assert node is not None
        assert node.title == "New Goal"
        assert node.weight == 7

    @pytest.mark.asyncio
    async def test_remove_goal(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))

        await service.remove_goal("g1")

        assert state.get_goal("g1") is None

    @pytest.mark.asyncio
    async def test_get_goal_progress(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        state.add_plan(make_plan(id="p1", goal_id="g1"))
        state.add_todo(make_todo(id="t1", status="pending"), ["p1"])
        state.add_todo(make_todo(id="t2", status="completed"), ["p1"])
        state.add_todo(make_todo(id="t3", status="completed"), ["p1"])

        result = await service.get_goal_progress("g1")

        assert isinstance(result, GoalProgress)
        assert result.completed == 2
        assert result.total == 3


# =============================================================================
# Test Plan Operations
# =============================================================================


class TestGoalTreeStateServicePlanOperations:
    """Test plan CRUD operations."""

    @pytest.mark.asyncio
    async def test_get_plan(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        state.add_plan(make_plan(id="p1", goal_id="g1", title="My Plan"))

        result = await service.get_plan("p1")

        assert result is not None
        assert isinstance(result, PlanInfo)
        assert result.id == "p1"
        assert result.title == "My Plan"
        assert result.goal_id == "g1"

    @pytest.mark.asyncio
    async def test_get_plans_for_goal(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        state.add_plan(make_plan(id="p1", goal_id="g1"))
        state.add_plan(make_plan(id="p2", goal_id="g1"))

        result = await service.get_plans_for_goal("g1")

        assert len(result) == 2
        assert {r.id for r in result} == {"p1", "p2"}

    @pytest.mark.asyncio
    async def test_add_plan(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        now = datetime.now().isoformat()

        await service.add_plan({
            "id": "p1",
            "goal_id": "g1",
            "title": "New Plan",
            "description": "A new plan",
            "status": "active",
            "created_at": now,
            "updated_at": now,
        })

        node = state.get_plan("p1")
        assert node is not None
        assert node.title == "New Plan"

    @pytest.mark.asyncio
    async def test_remove_plan(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        state.add_plan(make_plan(id="p1"))

        await service.remove_plan("p1")

        assert state.get_plan("p1") is None


# =============================================================================
# Test Todo Operations
# =============================================================================


class TestGoalTreeStateServiceTodoOperations:
    """Test todo CRUD operations."""

    @pytest.mark.asyncio
    async def test_get_todo(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        state.add_plan(make_plan(id="p1"))
        state.add_todo(make_todo(id="t1", title="My Todo"), ["p1"])

        result = await service.get_todo("t1")

        assert result is not None
        assert isinstance(result, TodoInfo)
        assert result.id == "t1"
        assert result.title == "My Todo"
        assert result.plan_ids == ["p1"]

    @pytest.mark.asyncio
    async def test_get_todos_for_plan(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        state.add_plan(make_plan(id="p1"))
        state.add_todo(make_todo(id="t1"), ["p1"])
        state.add_todo(make_todo(id="t2"), ["p1"])

        result = await service.get_todos_for_plan("p1")

        assert len(result) == 2
        assert {r.id for r in result} == {"t1", "t2"}

    @pytest.mark.asyncio
    async def test_add_todo(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        state.add_plan(make_plan(id="p1"))
        now = datetime.now().isoformat()

        await service.add_todo(
            {
                "id": "t1",
                "title": "New Todo",
                "description": "A new todo",
                "status": "pending",
                "is_spike": False,
                "created_at": now,
                "updated_at": now,
            },
            ["p1"],
        )

        node = state.get_todo("t1")
        assert node is not None
        assert node.title == "New Todo"
        assert node.plan_ids == ["p1"]

    @pytest.mark.asyncio
    async def test_remove_todo(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        state.add_plan(make_plan(id="p1"))
        state.add_todo(make_todo(id="t1"), ["p1"])

        await service.remove_todo("t1")

        assert state.get_todo("t1") is None

    @pytest.mark.asyncio
    async def test_set_todo_priority(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        state.add_plan(make_plan(id="p1"))
        state.add_todo(make_todo(id="t1"), ["p1"])

        await service.set_todo_priority("t1", 7.5)

        node = state.get_todo("t1")
        assert node.priority == 7.5


# =============================================================================
# Test Session Binding Operations
# =============================================================================


class TestGoalTreeStateServiceSessionBindings:
    """Test session binding operations."""

    @pytest.mark.asyncio
    async def test_bind_session(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))

        await service.bind_session(
            entity_type="goal",
            entity_id="g1",
            session_id="s1",
            name="Test Session",
            binding_role="implementation",
            token_count=1000,
        )

        sessions = state.get_bound_sessions("g1")
        assert len(sessions) == 1
        assert sessions[0].session_id == "s1"
        assert sessions[0].name == "Test Session"
        assert sessions[0].binding_role == "implementation"

    @pytest.mark.asyncio
    async def test_unbind_session(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        await service.bind_session("goal", "g1", "s1", "Session")

        await service.unbind_session("g1", "s1")

        sessions = state.get_bound_sessions("g1")
        assert len(sessions) == 0

    @pytest.mark.asyncio
    async def test_add_unbound_session(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)

        await service.add_unbound_session(
            session_id="s1",
            name="Unbound Session",
            token_count=500,
        )

        sessions = await service.get_unbound_sessions()
        assert len(sessions) == 1
        assert sessions[0].session_id == "s1"

    @pytest.mark.asyncio
    async def test_remove_unbound_session(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        await service.add_unbound_session("s1", "Session")

        await service.remove_unbound_session("s1")

        sessions = await service.get_unbound_sessions()
        assert len(sessions) == 0

    @pytest.mark.asyncio
    async def test_get_bound_sessions(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        await service.bind_session("goal", "g1", "s1", "Session 1")
        await service.bind_session("goal", "g1", "s2", "Session 2")

        result = await service.get_bound_sessions("g1")

        assert len(result) == 2
        assert all(isinstance(r, SessionBindingInfo) for r in result)

    @pytest.mark.asyncio
    async def test_is_session_bound(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        await service.bind_session("goal", "g1", "s1", "Session")

        assert await service.is_session_bound("s1") is True
        assert await service.is_session_bound("s2") is False

    @pytest.mark.asyncio
    async def test_get_session_binding(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        await service.bind_session("goal", "g1", "s1", "Session")

        result = await service.get_session_binding("s1")

        assert result == ("goal", "g1")

    @pytest.mark.asyncio
    async def test_get_session_binding_unbound(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)

        result = await service.get_session_binding("s1")

        assert result is None


# =============================================================================
# Test Selection Operations
# =============================================================================


class TestGoalTreeStateServiceSelection:
    """Test entity selection operations."""

    @pytest.mark.asyncio
    async def test_select_entity(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        events = []
        service.add_event_handler(lambda e, d: events.append((e, d)))

        await service.select_entity("goal", "g1")

        result = await service.get_selected_entity()
        assert isinstance(result, SelectedEntity)
        assert result.entity_type == "goal"
        assert result.entity_id == "g1"
        assert any(e[0] == "entitySelected" for e in events)

    @pytest.mark.asyncio
    async def test_get_selected_entity_none(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)

        result = await service.get_selected_entity()

        assert result is None


# =============================================================================
# Test Collapsed State Operations
# =============================================================================


class TestGoalTreeStateServiceCollapsedState:
    """Test collapsed state operations."""

    @pytest.mark.asyncio
    async def test_is_collapsed_default(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)

        result = await service.is_collapsed("g1")

        assert result is False  # Nodes expanded by default

    @pytest.mark.asyncio
    async def test_set_collapsed(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)

        await service.set_collapsed("g1", True)

        assert await service.is_collapsed("g1") is True

        await service.set_collapsed("g1", False)

        assert await service.is_collapsed("g1") is False

    @pytest.mark.asyncio
    async def test_toggle_collapsed(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)

        result1 = await service.toggle_collapsed("g1")
        assert result1 is True  # Now collapsed

        result2 = await service.toggle_collapsed("g1")
        assert result2 is False  # Now expanded

    @pytest.mark.asyncio
    async def test_get_set_collapsed_ids(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)

        await service.set_collapsed_ids(["g1", "p1", "t1"])

        result = await service.get_collapsed_ids()
        assert set(result) == {"g1", "p1", "t1"}


# =============================================================================
# Test Statistics
# =============================================================================


class TestGoalTreeStateServiceStats:
    """Test statistics operations."""

    @pytest.mark.asyncio
    async def test_get_stats(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1", status="active"))
        state.add_goal(make_goal(id="g2", status="completed"))
        state.add_plan(make_plan(id="p1", status="active"))
        state.add_todo(make_todo(id="t1", status="pending"), ["p1"])
        state.add_todo(make_todo(id="t2", status="in_progress"), ["p1"])

        result = await service.get_stats()

        assert isinstance(result, GoalTreeStats)
        assert result.total_goals == 2
        assert result.active_goals == 1
        assert result.total_plans == 1
        assert result.active_plans == 1
        assert result.total_todos == 2
        assert result.pending_todos == 1
        assert result.in_progress_todos == 1


# =============================================================================
# Test Bulk Operations
# =============================================================================


class TestGoalTreeStateServiceBulkOperations:
    """Test bulk operations."""

    @pytest.mark.asyncio
    async def test_clear(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        state.add_goal(make_goal(id="g1"))
        state.add_plan(make_plan(id="p1"))

        await service.clear()

        assert await service.get_goal("g1") is None
        assert await service.get_plan("p1") is None

    @pytest.mark.asyncio
    async def test_request_rebuild(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        events = []
        service.add_event_handler(lambda e, d: events.append(e))

        await service.request_rebuild()

        assert "fullRebuild" in events

    @pytest.mark.asyncio
    async def test_batch_loading(self):
        state = GoalTreeState()
        service = GoalTreeStateService(state)
        events = []
        service.add_event_handler(lambda e, d: events.append(e))

        await service.begin_batch_loading()
        state.add_goal(make_goal(id="g1"))
        state.add_goal(make_goal(id="g2"))
        state.add_plan(make_plan(id="p1"))

        # Individual events suppressed during batch
        assert "goalAdded" not in events
        assert "planAdded" not in events

        await service.end_batch_loading()

        # Full rebuild triggered at end
        assert "fullRebuild" in events
