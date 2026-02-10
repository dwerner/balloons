"""Tests for fork binding inheritance."""

import tempfile
from pathlib import Path
from datetime import datetime

import pytest

from core.async_storage import GoalStorage
from core.fork import copy_session_bindings
from storage_schema import GoalData, SessionBinding


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


@pytest.mark.asyncio
async def test_copy_bindings_empty(goal_storage, monkeypatch):
    """Test copying bindings when parent has none."""
    # Monkeypatch get_goal_storage in the async_storage module
    async def mock_get_goal_storage():
        return goal_storage

    from core import async_storage
    monkeypatch.setattr(async_storage, "get_goal_storage", mock_get_goal_storage)

    copied = await copy_session_bindings("parent-1", "child-1")
    assert copied == 0

    # Verify child has no bindings
    child_bindings = await goal_storage.get_bindings_for_session("child-1")
    assert len(child_bindings) == 0


@pytest.mark.asyncio
async def test_copy_bindings_single(goal_storage, sample_goal, monkeypatch):
    """Test copying a single binding to child session."""
    await goal_storage.save_goal(sample_goal)

    now = datetime.now().isoformat()
    parent_binding = SessionBinding(
        id="parent-b1",
        session_id="parent-1",
        entity_type="goal",
        entity_id=sample_goal.id,
        role="planning",
        created_at=now,
    )
    await goal_storage.save_session_binding(parent_binding)

    # Monkeypatch get_goal_storage in the async_storage module
    async def mock_get_goal_storage():
        return goal_storage

    from core import async_storage
    monkeypatch.setattr(async_storage, "get_goal_storage", mock_get_goal_storage)

    copied = await copy_session_bindings("parent-1", "child-1")
    assert copied == 1

    # Verify child has binding
    child_bindings = await goal_storage.get_bindings_for_session("child-1")
    assert len(child_bindings) == 1
    assert child_bindings[0].entity_type == "goal"
    assert child_bindings[0].entity_id == sample_goal.id
    assert child_bindings[0].role == "planning"
    assert child_bindings[0].session_id == "child-1"
    # Child binding should have new ID
    assert child_bindings[0].id != parent_binding.id


@pytest.mark.asyncio
async def test_copy_bindings_multiple(goal_storage, monkeypatch):
    """Test copying multiple bindings to child session."""
    now = datetime.now().isoformat()

    # Create multiple bindings on parent
    bindings = [
        SessionBinding(
            id="parent-b1",
            session_id="parent-2",
            entity_type="goal",
            entity_id="goal-1",
            role="planning",
            created_at=now,
        ),
        SessionBinding(
            id="parent-b2",
            session_id="parent-2",
            entity_type="plan",
            entity_id="plan-1",
            role="implementation",
            created_at=now,
        ),
        SessionBinding(
            id="parent-b3",
            session_id="parent-2",
            entity_type="todo",
            entity_id="todo-1",
            role="implementation",
            created_at=now,
        ),
    ]

    for binding in bindings:
        await goal_storage.save_session_binding(binding)

    # Monkeypatch get_goal_storage in the async_storage module
    async def mock_get_goal_storage():
        return goal_storage

    from core import async_storage
    monkeypatch.setattr(async_storage, "get_goal_storage", mock_get_goal_storage)

    copied = await copy_session_bindings("parent-2", "child-2")
    assert copied == 3

    # Verify child has all bindings
    child_bindings = await goal_storage.get_bindings_for_session("child-2")
    assert len(child_bindings) == 3

    entity_types = {b.entity_type for b in child_bindings}
    assert entity_types == {"goal", "plan", "todo"}


@pytest.mark.asyncio
async def test_released_bindings_not_copied(goal_storage, monkeypatch):
    """Test that released bindings are not copied to child."""
    now = datetime.now().isoformat()

    # Active binding
    active = SessionBinding(
        id="parent-b1",
        session_id="parent-3",
        entity_type="goal",
        entity_id="goal-1",
        role="planning",
        created_at=now,
    )
    # Released binding
    released = SessionBinding(
        id="parent-b2",
        session_id="parent-3",
        entity_type="plan",
        entity_id="plan-1",
        role="postmortem",
        created_at=now,
        released_at=now,
    )

    await goal_storage.save_session_binding(active)
    await goal_storage.save_session_binding(released)

    # Monkeypatch get_goal_storage in the async_storage module
    async def mock_get_goal_storage():
        return goal_storage

    from core import async_storage
    monkeypatch.setattr(async_storage, "get_goal_storage", mock_get_goal_storage)

    copied = await copy_session_bindings("parent-3", "child-3")
    assert copied == 1  # Only active binding

    child_bindings = await goal_storage.get_bindings_for_session("child-3")
    assert len(child_bindings) == 1
    assert child_bindings[0].entity_type == "goal"
