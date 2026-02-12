"""Tests for goal data migration from JSON to LMDB."""

import json
import tempfile
from pathlib import Path

import pytest

from storage_schema import GoalData, PlanData, TodoData, TodoPlanLink, TodoDependency, SessionBinding


@pytest.fixture
def temp_json_dir(tmp_path):
    """Create a temporary JSON goal directory structure."""
    goals_dir = tmp_path / "goals"
    goals_dir.mkdir()

    # Create subdirectories
    (goals_dir / "goals").mkdir()
    (goals_dir / "plans").mkdir()
    (goals_dir / "todos").mkdir()
    (goals_dir / "links").mkdir()
    (goals_dir / "dependencies").mkdir()
    (goals_dir / "bindings").mkdir()

    # Create sample goal
    goal = {
        "id": "goal-1",
        "title": "Test Goal",
        "description": "A test goal",
        "weight": 5,
        "status": "active",
        "acceptance_criteria": ["Criterion 1"],
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
        "completed_at": None,
        "supersedes_id": None,
    }
    with open(goals_dir / "goals" / "goal-1.json", "w") as f:
        json.dump(goal, f)

    # Create sample plan
    plan = {
        "id": "plan-1",
        "goal_id": "goal-1",
        "title": "Test Plan",
        "description": "A test plan",
        "status": "active",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
        "completed_at": None,
        "postmortem": None,
    }
    with open(goals_dir / "plans" / "plan-1.json", "w") as f:
        json.dump(plan, f)

    # Create sample todo
    todo = {
        "id": "todo-1",
        "title": "Test Todo",
        "description": "A test todo",
        "status": "pending",
        "is_spike": False,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
        "completed_at": None,
        "timebox_minutes": None,
    }
    with open(goals_dir / "todos" / "todo-1.json", "w") as f:
        json.dump(todo, f)

    # Create sample link
    link = {
        "todo_id": "todo-1",
        "plan_id": "plan-1",
        "created_at": "2024-01-01T00:00:00",
    }
    with open(goals_dir / "links" / "todo-1_plan-1.json", "w") as f:
        json.dump(link, f)

    return goals_dir


def test_dict_to_goal():
    """Test converting dict to GoalData."""
    from scripts.migrate_goals_to_lmdb import dict_to_goal

    data = {
        "id": "goal-1",
        "title": "Test Goal",
        "description": "Description",
        "weight": 5,
        "status": "active",
        "acceptance_criteria": ["Criterion 1"],
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }

    goal = dict_to_goal(data)
    assert goal.id == "goal-1"
    assert goal.title == "Test Goal"
    assert goal.weight == 5
    assert goal.status == "active"


def test_dict_to_plan():
    """Test converting dict to PlanData."""
    from scripts.migrate_goals_to_lmdb import dict_to_plan

    data = {
        "id": "plan-1",
        "goal_id": "goal-1",
        "title": "Test Plan",
        "description": "Description",
        "status": "active",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }

    plan = dict_to_plan(data)
    assert plan.id == "plan-1"
    assert plan.goal_id == "goal-1"
    assert plan.title == "Test Plan"


def test_dict_to_todo():
    """Test converting dict to TodoData."""
    from scripts.migrate_goals_to_lmdb import dict_to_todo

    data = {
        "id": "todo-1",
        "title": "Test Todo",
        "description": "Description",
        "status": "pending",
        "is_spike": False,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }

    todo = dict_to_todo(data)
    assert todo.id == "todo-1"
    assert todo.title == "Test Todo"
    assert todo.status == "pending"
    assert todo.is_spike is False


def test_dict_to_link():
    """Test converting dict to TodoPlanLink."""
    from scripts.migrate_goals_to_lmdb import dict_to_link

    data = {
        "todo_id": "todo-1",
        "plan_id": "plan-1",
        "created_at": "2024-01-01T00:00:00",
    }

    link = dict_to_link(data)
    assert link.todo_id == "todo-1"
    assert link.plan_id == "plan-1"


def test_dict_to_dependency():
    """Test converting dict to TodoDependency."""
    from scripts.migrate_goals_to_lmdb import dict_to_dependency

    data = {
        "todo_id": "todo-1",
        "depends_on_id": "todo-2",
        "created_at": "2024-01-01T00:00:00",
    }

    dep = dict_to_dependency(data)
    assert dep.todo_id == "todo-1"
    assert dep.depends_on_id == "todo-2"


def test_dict_to_binding():
    """Test converting dict to SessionBinding."""
    from scripts.migrate_goals_to_lmdb import dict_to_binding

    data = {
        "id": "binding-1",
        "session_id": "session-1",
        "entity_type": "todo",
        "entity_id": "todo-1",
        "role": "implementation",
        "created_at": "2024-01-01T00:00:00",
        "released_at": None,
    }

    binding = dict_to_binding(data)
    assert binding.id == "binding-1"
    assert binding.session_id == "session-1"
    assert binding.entity_type == "todo"
    assert binding.role == "implementation"


def test_load_all_json_files(temp_json_dir, monkeypatch):
    """Test loading all JSON files from a subdirectory."""
    from scripts.migrate_goals_to_lmdb import load_all_json_files, JSON_GOALS_DIR

    # Monkeypatch the JSON_GOALS_DIR to use our temp directory
    import scripts.migrate_goals_to_lmdb as migration_module
    monkeypatch.setattr(migration_module, "JSON_GOALS_DIR", temp_json_dir)

    goals = load_all_json_files("goals")
    assert len(goals) == 1
    assert goals[0]["id"] == "goal-1"

    plans = load_all_json_files("plans")
    assert len(plans) == 1
    assert plans[0]["id"] == "plan-1"

    todos = load_all_json_files("todos")
    assert len(todos) == 1
    assert todos[0]["id"] == "todo-1"

    links = load_all_json_files("links")
    assert len(links) == 1
    assert links[0]["todo_id"] == "todo-1"
