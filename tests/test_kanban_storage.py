"""Tests for kanban/graph storage (tasks, boards, columns, edges)."""

import json
import tempfile
from pathlib import Path

import pytest

from core.async_storage import is_rust_storage_available


# Skip all tests if Rust storage is not available
pytestmark = pytest.mark.skipif(
    not is_rust_storage_available(),
    reason="Rust balloons_storage module not available"
)


@pytest.fixture
def temp_db():
    """Create a temporary database directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_kanban.db"


@pytest.fixture
def storage(temp_db):
    """Create a storage instance."""
    from balloons_storage import Storage
    return Storage(str(temp_db))


# =============================================================================
# Task Tests
# =============================================================================

class TestTaskCRUD:
    """Tests for task CRUD operations."""

    def test_save_and_load_task(self, storage):
        """Test saving and loading a task."""
        task = {
            "id": "task-1",
            "title": "Buy paint",
            "description": "Get art supplies from the store",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        storage.save_task(json.dumps(task))

        loaded = storage.load_task("task-1")
        assert loaded is not None

        loaded_task = json.loads(loaded)
        assert loaded_task["id"] == "task-1"
        assert loaded_task["title"] == "Buy paint"
        assert loaded_task["description"] == "Get art supplies from the store"

    def test_load_nonexistent_task(self, storage):
        """Test loading a task that doesn't exist returns None."""
        loaded = storage.load_task("nonexistent")
        assert loaded is None

    def test_delete_task(self, storage):
        """Test deleting a task."""
        task = {
            "id": "task-to-delete",
            "title": "Temporary",
            "description": "",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        storage.save_task(json.dumps(task))

        # Verify it exists
        assert storage.load_task("task-to-delete") is not None

        # Delete it
        storage.delete_task("task-to-delete")

        # Verify it's gone
        assert storage.load_task("task-to-delete") is None

    def test_list_tasks(self, storage):
        """Test listing all tasks."""
        tasks = [
            {"id": f"task-{i}", "title": f"Task {i}", "description": "",
             "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z"}
            for i in range(3)
        ]
        for task in tasks:
            storage.save_task(json.dumps(task))

        listed = json.loads(storage.list_tasks())
        assert len(listed) == 3
        assert {t["id"] for t in listed} == {"task-0", "task-1", "task-2"}

    def test_update_task(self, storage):
        """Test updating an existing task."""
        task = {
            "id": "task-update",
            "title": "Original Title",
            "description": "Original",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        storage.save_task(json.dumps(task))

        # Update the task
        task["title"] = "Updated Title"
        task["updated_at"] = "2024-01-02T00:00:00Z"
        storage.save_task(json.dumps(task))

        loaded = json.loads(storage.load_task("task-update"))
        assert loaded["title"] == "Updated Title"
        assert loaded["updated_at"] == "2024-01-02T00:00:00Z"


# =============================================================================
# Board Tests
# =============================================================================

class TestBoardCRUD:
    """Tests for board CRUD operations."""

    def test_save_and_load_board(self, storage):
        """Test saving and loading a board."""
        board = {
            "id": "board-1",
            "name": "Sprint 1",
            "default_column_id": "col-todo",
            "created_at": "2024-01-01T00:00:00Z",
        }
        storage.save_board(json.dumps(board))

        loaded = storage.load_board("board-1")
        assert loaded is not None

        loaded_board = json.loads(loaded)
        assert loaded_board["id"] == "board-1"
        assert loaded_board["name"] == "Sprint 1"
        assert loaded_board["default_column_id"] == "col-todo"

    def test_load_nonexistent_board(self, storage):
        """Test loading a board that doesn't exist returns None."""
        loaded = storage.load_board("nonexistent")
        assert loaded is None

    def test_delete_board(self, storage):
        """Test deleting a board."""
        board = {
            "id": "board-to-delete",
            "name": "Temporary",
            "default_column_id": "col-1",
            "created_at": "2024-01-01T00:00:00Z",
        }
        storage.save_board(json.dumps(board))

        assert storage.load_board("board-to-delete") is not None
        storage.delete_board("board-to-delete")
        assert storage.load_board("board-to-delete") is None

    def test_list_boards(self, storage):
        """Test listing all boards."""
        boards = [
            {"id": f"board-{i}", "name": f"Board {i}", "default_column_id": "col-1",
             "created_at": "2024-01-01T00:00:00Z"}
            for i in range(3)
        ]
        for board in boards:
            storage.save_board(json.dumps(board))

        listed = json.loads(storage.list_boards())
        assert len(listed) == 3


# =============================================================================
# Column Tests
# =============================================================================

class TestColumnCRUD:
    """Tests for column CRUD operations."""

    def test_save_and_load_column(self, storage):
        """Test saving and loading a column."""
        column = {
            "id": "col-todo",
            "name": "To Do",
            "position": 0,
        }
        storage.save_column(json.dumps(column))

        loaded = storage.load_column("col-todo")
        assert loaded is not None

        loaded_column = json.loads(loaded)
        assert loaded_column["id"] == "col-todo"
        assert loaded_column["name"] == "To Do"
        assert loaded_column["position"] == 0

    def test_delete_column(self, storage):
        """Test deleting a column."""
        column = {"id": "col-delete", "name": "Temp", "position": 0}
        storage.save_column(json.dumps(column))

        assert storage.load_column("col-delete") is not None
        storage.delete_column("col-delete")
        assert storage.load_column("col-delete") is None


# =============================================================================
# Edge Tests
# =============================================================================

class TestEdgeCRUD:
    """Tests for edge CRUD operations."""

    def test_save_and_load_edge(self, storage):
        """Test saving and loading an edge."""
        edge = {
            "id": "edge-1",
            "source_type": "column",
            "source_id": "col-todo",
            "target_type": "board",
            "target_id": "board-1",
            "relationship": "part_of",
            "position": 0,
            "created_at": "2024-01-01T00:00:00Z",
        }
        storage.save_edge(json.dumps(edge))

        loaded = storage.load_edge("edge-1")
        assert loaded is not None

        loaded_edge = json.loads(loaded)
        assert loaded_edge["id"] == "edge-1"
        assert loaded_edge["source_type"] == "column"
        assert loaded_edge["target_type"] == "board"
        assert loaded_edge["relationship"] == "part_of"

    def test_delete_edge(self, storage):
        """Test deleting an edge."""
        edge = {
            "id": "edge-delete",
            "source_type": "task",
            "source_id": "t1",
            "target_type": "board",
            "target_id": "b1",
            "relationship": "tracked_on",
            "position": None,
            "created_at": "2024-01-01T00:00:00Z",
        }
        storage.save_edge(json.dumps(edge))

        assert storage.load_edge("edge-delete") is not None
        storage.delete_edge("edge-delete")
        assert storage.load_edge("edge-delete") is None


class TestEdgeQueries:
    """Tests for edge query operations."""

    @pytest.fixture
    def setup_edges(self, storage):
        """Create a set of edges for testing queries."""
        # Board with 3 columns
        edges = [
            # Columns belong to board
            {"id": "e-col1", "source_type": "column", "source_id": "col-todo",
             "target_type": "board", "target_id": "board-1", "relationship": "part_of",
             "position": 0, "created_at": "2024-01-01T00:00:00Z"},
            {"id": "e-col2", "source_type": "column", "source_id": "col-wip",
             "target_type": "board", "target_id": "board-1", "relationship": "part_of",
             "position": 1, "created_at": "2024-01-01T00:00:00Z"},
            {"id": "e-col3", "source_type": "column", "source_id": "col-done",
             "target_type": "board", "target_id": "board-1", "relationship": "part_of",
             "position": 2, "created_at": "2024-01-01T00:00:00Z"},

            # Task tracked on board
            {"id": "e-task-board", "source_type": "task", "source_id": "task-1",
             "target_type": "board", "target_id": "board-1", "relationship": "tracked_on",
             "position": None, "created_at": "2024-01-01T00:00:00Z"},

            # Task in column
            {"id": "e-task-col", "source_type": "task", "source_id": "task-1",
             "target_type": "column", "target_id": "col-wip", "relationship": "in_column",
             "position": 0, "created_at": "2024-01-01T00:00:00Z"},
        ]
        for edge in edges:
            storage.save_edge(json.dumps(edge))
        return storage

    def test_get_edges_by_source(self, setup_edges):
        """Test querying edges by source."""
        storage = setup_edges

        # Get all edges from task-1
        edges = json.loads(storage.get_edges_by_source("task", "task-1"))
        assert len(edges) == 2
        assert {e["relationship"] for e in edges} == {"tracked_on", "in_column"}

    def test_get_edges_by_target(self, setup_edges):
        """Test querying edges by target."""
        storage = setup_edges

        # Get all edges pointing to board-1
        edges = json.loads(storage.get_edges_by_target("board", "board-1"))
        assert len(edges) == 4  # 3 columns + 1 task tracked_on

    def test_get_edges_by_source_and_relationship(self, setup_edges):
        """Test querying edges by source and relationship."""
        storage = setup_edges

        # Get only tracked_on edges from task-1
        edges = json.loads(
            storage.get_edges_by_source_and_relationship("task", "task-1", "tracked_on")
        )
        assert len(edges) == 1
        assert edges[0]["target_type"] == "board"

    def test_get_edges_by_target_and_relationship(self, setup_edges):
        """Test querying edges by target and relationship."""
        storage = setup_edges

        # Get only part_of edges pointing to board-1 (columns)
        edges = json.loads(
            storage.get_edges_by_target_and_relationship("board", "board-1", "part_of")
        )
        assert len(edges) == 3
        assert all(e["source_type"] == "column" for e in edges)

    def test_edge_position_ordering(self, setup_edges):
        """Test that edges are returned ordered by position."""
        storage = setup_edges

        # Columns should be ordered by position
        edges = json.loads(
            storage.get_edges_by_target_and_relationship("board", "board-1", "part_of")
        )
        positions = [e["position"] for e in edges]
        assert positions == [0, 1, 2]
        assert [e["source_id"] for e in edges] == ["col-todo", "col-wip", "col-done"]

    def test_edge_index_cleanup_on_delete(self, storage):
        """Test that deleting an edge cleans up the indexes."""
        edge = {
            "id": "edge-cleanup",
            "source_type": "task",
            "source_id": "task-cleanup",
            "target_type": "board",
            "target_id": "board-cleanup",
            "relationship": "tracked_on",
            "position": None,
            "created_at": "2024-01-01T00:00:00Z",
        }
        storage.save_edge(json.dumps(edge))

        # Verify edge is in indexes
        by_source = json.loads(storage.get_edges_by_source("task", "task-cleanup"))
        assert len(by_source) == 1

        by_target = json.loads(storage.get_edges_by_target("board", "board-cleanup"))
        assert len(by_target) == 1

        # Delete edge
        storage.delete_edge("edge-cleanup")

        # Verify indexes are cleaned
        by_source = json.loads(storage.get_edges_by_source("task", "task-cleanup"))
        assert len(by_source) == 0

        by_target = json.loads(storage.get_edges_by_target("board", "board-cleanup"))
        assert len(by_target) == 0


# =============================================================================
# Integration Tests
# =============================================================================

class TestKanbanIntegration:
    """Integration tests for a complete kanban workflow."""

    def test_full_kanban_setup(self, storage):
        """Test creating a complete kanban board with tasks."""
        # Create a board
        board = {
            "id": "sprint-1",
            "name": "Sprint 1",
            "default_column_id": "col-backlog",
            "created_at": "2024-01-01T00:00:00Z",
        }
        storage.save_board(json.dumps(board))

        # Create columns
        columns = [
            {"id": "col-backlog", "name": "Backlog", "position": 0},
            {"id": "col-todo", "name": "To Do", "position": 1},
            {"id": "col-wip", "name": "In Progress", "position": 2},
            {"id": "col-done", "name": "Done", "position": 3},
        ]
        for col in columns:
            storage.save_column(json.dumps(col))

        # Link columns to board
        for i, col in enumerate(columns):
            edge = {
                "id": f"e-{col['id']}-board",
                "source_type": "column",
                "source_id": col["id"],
                "target_type": "board",
                "target_id": "sprint-1",
                "relationship": "part_of",
                "position": i,
                "created_at": "2024-01-01T00:00:00Z",
            }
            storage.save_edge(json.dumps(edge))

        # Create tasks
        tasks = [
            {"id": "task-1", "title": "Design API", "description": "Design REST endpoints",
             "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z"},
            {"id": "task-2", "title": "Implement auth", "description": "Add JWT support",
             "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z"},
            {"id": "task-3", "title": "Write tests", "description": "Unit and integration tests",
             "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z"},
        ]
        for task in tasks:
            storage.save_task(json.dumps(task))

        # Add tasks to board and place in columns
        task_placements = [
            ("task-1", "col-done"),
            ("task-2", "col-wip"),
            ("task-3", "col-todo"),
        ]
        for task_id, col_id in task_placements:
            # Track on board
            storage.save_edge(json.dumps({
                "id": f"e-{task_id}-board",
                "source_type": "task",
                "source_id": task_id,
                "target_type": "board",
                "target_id": "sprint-1",
                "relationship": "tracked_on",
                "position": None,
                "created_at": "2024-01-01T00:00:00Z",
            }))
            # Place in column
            storage.save_edge(json.dumps({
                "id": f"e-{task_id}-col",
                "source_type": "task",
                "source_id": task_id,
                "target_type": "column",
                "target_id": col_id,
                "relationship": "in_column",
                "position": 0,
                "created_at": "2024-01-01T00:00:00Z",
            }))

        # Verify: get all columns for board
        board_columns = json.loads(
            storage.get_edges_by_target_and_relationship("board", "sprint-1", "part_of")
        )
        assert len(board_columns) == 4
        assert [e["source_id"] for e in board_columns] == [
            "col-backlog", "col-todo", "col-wip", "col-done"
        ]

        # Verify: get all tasks on board
        board_tasks = json.loads(
            storage.get_edges_by_target_and_relationship("board", "sprint-1", "tracked_on")
        )
        assert len(board_tasks) == 3

        # Verify: get tasks in WIP column
        wip_tasks = json.loads(
            storage.get_edges_by_target_and_relationship("column", "col-wip", "in_column")
        )
        assert len(wip_tasks) == 1
        assert wip_tasks[0]["source_id"] == "task-2"

    def test_move_task_between_columns(self, storage):
        """Test moving a task from one column to another."""
        # Setup: board, columns, task
        storage.save_board(json.dumps({
            "id": "board-1", "name": "Board", "default_column_id": "col-todo",
            "created_at": "2024-01-01T00:00:00Z"
        }))
        storage.save_column(json.dumps({"id": "col-todo", "name": "Todo", "position": 0}))
        storage.save_column(json.dumps({"id": "col-done", "name": "Done", "position": 1}))
        storage.save_task(json.dumps({
            "id": "task-move", "title": "Moving task", "description": "",
            "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z"
        }))

        # Place task in todo column
        storage.save_edge(json.dumps({
            "id": "e-task-col",
            "source_type": "task",
            "source_id": "task-move",
            "target_type": "column",
            "target_id": "col-todo",
            "relationship": "in_column",
            "position": 0,
            "created_at": "2024-01-01T00:00:00Z",
        }))

        # Verify task is in todo
        todo_tasks = json.loads(
            storage.get_edges_by_target_and_relationship("column", "col-todo", "in_column")
        )
        assert len(todo_tasks) == 1

        # Move task to done (update edge target)
        storage.save_edge(json.dumps({
            "id": "e-task-col",  # Same edge ID = update
            "source_type": "task",
            "source_id": "task-move",
            "target_type": "column",
            "target_id": "col-done",  # New column
            "relationship": "in_column",
            "position": 0,
            "created_at": "2024-01-01T00:00:00Z",
        }))

        # Verify: todo is empty
        todo_tasks = json.loads(
            storage.get_edges_by_target_and_relationship("column", "col-todo", "in_column")
        )
        assert len(todo_tasks) == 0

        # Verify: done has the task
        done_tasks = json.loads(
            storage.get_edges_by_target_and_relationship("column", "col-done", "in_column")
        )
        assert len(done_tasks) == 1
        assert done_tasks[0]["source_id"] == "task-move"
