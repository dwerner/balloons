"""Tests for core/kanban_service.py."""

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
        yield Path(tmpdir) / "test_kanban_service.db"


@pytest.fixture
def storage(temp_db):
    """Create an AsyncStorage instance."""
    from core.async_storage import AsyncStorage
    return AsyncStorage(temp_db)


@pytest.fixture
def kanban(storage):
    """Create a KanbanService instance."""
    from core.kanban_service import KanbanService
    return KanbanService(storage)


# =============================================================================
# Board Tests
# =============================================================================


class TestBoardOperations:
    """Tests for board CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_board_with_default_columns(self, kanban):
        """Test creating a board creates default columns."""
        state = await kanban.create_board("Sprint 1")

        assert state.board.name == "Sprint 1"
        assert state.board.id is not None
        assert len(state.columns) == 4

        # Check default column names and order
        column_names = [c.name for c in state.columns]
        assert column_names == ["Backlog", "To Do", "In Progress", "Done"]

        # Check positions
        positions = [c.position for c in state.columns]
        assert positions == [0, 1, 2, 3]

        # Default column should be first one (Backlog)
        assert state.board.default_column_id == state.columns[0].id

    @pytest.mark.asyncio
    async def test_create_board_with_custom_columns(self, kanban):
        """Test creating a board with custom columns."""
        custom_columns = [
            ("New", 0),
            ("Active", 1),
            ("Resolved", 2),
            ("Closed", 3),
            ("Archived", 4),
        ]
        state = await kanban.create_board("Custom Board", columns=custom_columns)

        assert state.board.name == "Custom Board"
        assert len(state.columns) == 5

        column_names = [c.name for c in state.columns]
        assert column_names == ["New", "Active", "Resolved", "Closed", "Archived"]

    @pytest.mark.asyncio
    async def test_get_board(self, kanban):
        """Test getting a board by ID."""
        state = await kanban.create_board("Test Board")

        board = await kanban.get_board(state.board.id)
        assert board is not None
        assert board.id == state.board.id
        assert board.name == "Test Board"

    @pytest.mark.asyncio
    async def test_get_nonexistent_board(self, kanban):
        """Test getting a board that doesn't exist."""
        board = await kanban.get_board("nonexistent-id")
        assert board is None

    @pytest.mark.asyncio
    async def test_list_boards(self, kanban):
        """Test listing all boards."""
        await kanban.create_board("Board 1")
        await kanban.create_board("Board 2")
        await kanban.create_board("Board 3")

        boards = await kanban.list_boards()
        assert len(boards) == 3
        names = {b.name for b in boards}
        assert names == {"Board 1", "Board 2", "Board 3"}

    @pytest.mark.asyncio
    async def test_delete_board(self, kanban):
        """Test deleting a board."""
        state = await kanban.create_board("To Delete")

        # Delete it
        result = await kanban.delete_board(state.board.id)
        assert result is True

        # Verify it's gone
        board = await kanban.get_board(state.board.id)
        assert board is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_board(self, kanban):
        """Test deleting a board that doesn't exist."""
        result = await kanban.delete_board("nonexistent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_board_state(self, kanban):
        """Test getting full board state."""
        state = await kanban.create_board("Full State Test")

        full_state = await kanban.get_board_state(state.board.id)
        assert full_state is not None
        assert full_state.board.name == "Full State Test"
        assert len(full_state.columns) == 4


# =============================================================================
# Task Tests
# =============================================================================


class TestTaskOperations:
    """Tests for task CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_task(self, kanban):
        """Test creating a task on a board."""
        state = await kanban.create_board("Task Board")

        task = await kanban.create_task(
            board_id=state.board.id,
            title="Implement feature",
            description="Add the new feature",
        )

        assert task is not None
        assert task.id is not None
        assert task.title == "Implement feature"
        assert task.description == "Add the new feature"

    @pytest.mark.asyncio
    async def test_create_task_in_specific_column(self, kanban):
        """Test creating a task in a specific column."""
        state = await kanban.create_board("Task Board")
        done_column = state.columns[3]  # "Done" column

        task = await kanban.create_task(
            board_id=state.board.id,
            title="Already done",
            column_id=done_column.id,
        )

        # Get board state and verify task is in Done column
        full_state = await kanban.get_board_state(state.board.id)
        done_col = next(c for c in full_state.columns if c.name == "Done")
        assert len(done_col.tasks) == 1
        assert done_col.tasks[0].id == task.id

    @pytest.mark.asyncio
    async def test_create_task_on_nonexistent_board(self, kanban):
        """Test creating a task on a board that doesn't exist."""
        task = await kanban.create_task(
            board_id="nonexistent",
            title="Should fail",
        )
        assert task is None

    @pytest.mark.asyncio
    async def test_get_task(self, kanban):
        """Test getting a task by ID."""
        state = await kanban.create_board("Task Board")
        created = await kanban.create_task(
            board_id=state.board.id,
            title="Test task",
        )

        task = await kanban.get_task(created.id)
        assert task is not None
        assert task.id == created.id
        assert task.title == "Test task"

    @pytest.mark.asyncio
    async def test_update_task(self, kanban):
        """Test updating a task."""
        state = await kanban.create_board("Task Board")
        task = await kanban.create_task(
            board_id=state.board.id,
            title="Original title",
            description="Original description",
        )

        updated = await kanban.update_task(
            task_id=task.id,
            title="Updated title",
            description="Updated description",
        )

        assert updated is not None
        assert updated.title == "Updated title"
        assert updated.description == "Updated description"
        assert updated.created_at == task.created_at
        assert updated.updated_at != task.updated_at

    @pytest.mark.asyncio
    async def test_update_task_partial(self, kanban):
        """Test updating only some task fields."""
        state = await kanban.create_board("Task Board")
        task = await kanban.create_task(
            board_id=state.board.id,
            title="Original title",
            description="Original description",
        )

        # Update only title
        updated = await kanban.update_task(
            task_id=task.id,
            title="New title",
        )

        assert updated.title == "New title"
        assert updated.description == "Original description"

    @pytest.mark.asyncio
    async def test_delete_task(self, kanban):
        """Test deleting a task."""
        state = await kanban.create_board("Task Board")
        task = await kanban.create_task(
            board_id=state.board.id,
            title="To delete",
        )

        result = await kanban.delete_task(task.id)
        assert result is True

        # Verify it's gone
        deleted = await kanban.get_task(task.id)
        assert deleted is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_task(self, kanban):
        """Test deleting a task that doesn't exist."""
        result = await kanban.delete_task("nonexistent-id")
        assert result is False


# =============================================================================
# Task Movement Tests
# =============================================================================


class TestTaskMovement:
    """Tests for moving tasks between columns."""

    @pytest.mark.asyncio
    async def test_move_task_to_different_column(self, kanban):
        """Test moving a task from one column to another."""
        state = await kanban.create_board("Movement Board")
        backlog = state.columns[0]
        done = state.columns[3]

        task = await kanban.create_task(
            board_id=state.board.id,
            title="Moving task",
        )

        # Verify task is in Backlog (default)
        full_state = await kanban.get_board_state(state.board.id)
        backlog_col = next(c for c in full_state.columns if c.id == backlog.id)
        assert len(backlog_col.tasks) == 1

        # Move to Done
        result = await kanban.move_task(task.id, to_column_id=done.id)
        assert result is True

        # Verify task is now in Done
        full_state = await kanban.get_board_state(state.board.id)
        done_col = next(c for c in full_state.columns if c.id == done.id)
        backlog_col = next(c for c in full_state.columns if c.id == backlog.id)
        assert len(done_col.tasks) == 1
        assert len(backlog_col.tasks) == 0
        assert done_col.tasks[0].id == task.id

    @pytest.mark.asyncio
    async def test_move_nonexistent_task(self, kanban):
        """Test moving a task that doesn't exist."""
        state = await kanban.create_board("Movement Board")
        done = state.columns[3]

        result = await kanban.move_task("nonexistent", to_column_id=done.id)
        assert result is False

    @pytest.mark.asyncio
    async def test_reorder_tasks_in_column(self, kanban):
        """Test reordering tasks within a column."""
        state = await kanban.create_board("Reorder Board")
        backlog = state.columns[0]

        # Create three tasks
        task1 = await kanban.create_task(state.board.id, "Task 1")
        task2 = await kanban.create_task(state.board.id, "Task 2")
        task3 = await kanban.create_task(state.board.id, "Task 3")

        # Reorder: 3, 1, 2
        result = await kanban.reorder_tasks(
            backlog.id,
            [task3.id, task1.id, task2.id]
        )
        assert result is True

        # Verify new order
        full_state = await kanban.get_board_state(state.board.id)
        backlog_col = next(c for c in full_state.columns if c.id == backlog.id)
        task_titles = [t.title for t in backlog_col.tasks]
        assert task_titles == ["Task 3", "Task 1", "Task 2"]

    @pytest.mark.asyncio
    async def test_reorder_tasks_with_missing_task(self, kanban):
        """Test reordering fails if a task ID isn't in the column."""
        state = await kanban.create_board("Reorder Board")
        backlog = state.columns[0]

        task1 = await kanban.create_task(state.board.id, "Task 1")
        await kanban.create_task(state.board.id, "Task 2")

        # Try to reorder with a task that doesn't exist in column
        result = await kanban.reorder_tasks(
            backlog.id,
            [task1.id, "nonexistent-id"]
        )
        assert result is False


# =============================================================================
# Column Tests
# =============================================================================


class TestColumnOperations:
    """Tests for column operations."""

    @pytest.mark.asyncio
    async def test_add_column(self, kanban):
        """Test adding a new column to a board."""
        state = await kanban.create_board("Column Board")
        assert len(state.columns) == 4

        column = await kanban.add_column(
            board_id=state.board.id,
            name="Review",
        )

        assert column is not None
        assert column.name == "Review"
        assert column.position == 4  # Added at end

        # Verify column appears in board state
        full_state = await kanban.get_board_state(state.board.id)
        assert len(full_state.columns) == 5
        column_names = [c.name for c in full_state.columns]
        assert "Review" in column_names

    @pytest.mark.asyncio
    async def test_add_column_with_position(self, kanban):
        """Test adding a column at a specific position."""
        state = await kanban.create_board("Column Board")

        # Insert at position 2 (between To Do and In Progress)
        column = await kanban.add_column(
            board_id=state.board.id,
            name="Review",
            position=2,
        )

        assert column.position == 2

    @pytest.mark.asyncio
    async def test_add_column_to_nonexistent_board(self, kanban):
        """Test adding a column to a board that doesn't exist."""
        column = await kanban.add_column(
            board_id="nonexistent",
            name="Should fail",
        )
        assert column is None

    @pytest.mark.asyncio
    async def test_delete_column(self, kanban):
        """Test deleting a column."""
        state = await kanban.create_board("Column Board")
        todo_column = state.columns[1]  # "To Do"

        result = await kanban.delete_column(todo_column.id)
        assert result is True

        # Verify column is gone
        full_state = await kanban.get_board_state(state.board.id)
        assert len(full_state.columns) == 3
        column_names = [c.name for c in full_state.columns]
        assert "To Do" not in column_names

    @pytest.mark.asyncio
    async def test_delete_column_with_task_migration(self, kanban):
        """Test deleting a column moves tasks to another column."""
        state = await kanban.create_board("Column Board")
        todo_column = state.columns[1]
        done_column = state.columns[3]

        # Add tasks to To Do column
        task = await kanban.create_task(
            board_id=state.board.id,
            title="Migrating task",
            column_id=todo_column.id,
        )

        # Delete To Do, moving tasks to Done
        result = await kanban.delete_column(todo_column.id, move_tasks_to=done_column.id)
        assert result is True

        # Verify task is now in Done
        full_state = await kanban.get_board_state(state.board.id)
        done_col = next(c for c in full_state.columns if c.id == done_column.id)
        assert len(done_col.tasks) == 1
        assert done_col.tasks[0].id == task.id

    @pytest.mark.asyncio
    async def test_delete_nonexistent_column(self, kanban):
        """Test deleting a column that doesn't exist."""
        result = await kanban.delete_column("nonexistent-id")
        assert result is False


# =============================================================================
# Integration Tests
# =============================================================================


class TestKanbanIntegration:
    """Integration tests for full kanban workflows."""

    @pytest.mark.asyncio
    async def test_full_workflow(self, kanban):
        """Test a complete kanban workflow."""
        # Create a sprint board
        state = await kanban.create_board("Sprint 1")
        board_id = state.board.id
        backlog = state.columns[0]
        todo = state.columns[1]
        in_progress = state.columns[2]
        done = state.columns[3]

        # Add some tasks to backlog
        task1 = await kanban.create_task(board_id, "Design API", "Create REST endpoints")
        task2 = await kanban.create_task(board_id, "Implement auth", "Add JWT support")
        task3 = await kanban.create_task(board_id, "Write tests", "Unit and integration")

        # Prioritize: move task2 to To Do
        await kanban.move_task(task2.id, todo.id)

        # Start working: move task2 to In Progress
        await kanban.move_task(task2.id, in_progress.id)

        # Complete task2
        await kanban.move_task(task2.id, done.id)

        # Update task1
        await kanban.update_task(task1.id, description="Create REST endpoints with OpenAPI spec")

        # Final state check
        full_state = await kanban.get_board_state(board_id)

        backlog_col = next(c for c in full_state.columns if c.id == backlog.id)
        done_col = next(c for c in full_state.columns if c.id == done.id)

        # Backlog should have task1 and task3
        assert len(backlog_col.tasks) == 2
        backlog_titles = {t.title for t in backlog_col.tasks}
        assert backlog_titles == {"Design API", "Write tests"}

        # Done should have task2
        assert len(done_col.tasks) == 1
        assert done_col.tasks[0].title == "Implement auth"

    @pytest.mark.asyncio
    async def test_multiple_boards_isolation(self, kanban):
        """Test that boards are isolated from each other."""
        state1 = await kanban.create_board("Board 1")
        state2 = await kanban.create_board("Board 2")

        # Add task to board 1
        task = await kanban.create_task(state1.board.id, "Board 1 Task")

        # Board 1 should have the task
        full_state1 = await kanban.get_board_state(state1.board.id)
        all_tasks1 = sum(len(c.tasks) for c in full_state1.columns)
        assert all_tasks1 == 1

        # Board 2 should be empty
        full_state2 = await kanban.get_board_state(state2.board.id)
        all_tasks2 = sum(len(c.tasks) for c in full_state2.columns)
        assert all_tasks2 == 0


# =============================================================================
# Session-Board Association Tests
# =============================================================================


class TestSessionBoardAssociations:
    """Tests for session-board association operations."""

    @pytest.mark.asyncio
    async def test_associate_board_with_session(self, kanban):
        """Test associating a board with a session."""
        state = await kanban.create_board("Test Board")
        session_id = "test-session-123"

        assoc = await kanban.associate_board_with_session(
            board_id=state.board.id,
            session_id=session_id,
            role="primary",
            created_by="user",
        )

        assert assoc is not None
        assert assoc.board_id == state.board.id
        assert assoc.session_id == session_id
        assert assoc.role == "primary"
        assert assoc.created_by == "user"
        assert assoc.inherited_from is None

    @pytest.mark.asyncio
    async def test_associate_board_with_inheritance(self, kanban):
        """Test associating a board with inheritance tracking."""
        state = await kanban.create_board("Test Board")
        session_id = "child-session"
        parent_id = "parent-session"

        assoc = await kanban.associate_board_with_session(
            board_id=state.board.id,
            session_id=session_id,
            role="reference",
            created_by="fork",
            inherited_from=parent_id,
        )

        assert assoc.inherited_from == parent_id
        assert assoc.created_by == "fork"
        assert assoc.role == "reference"

    @pytest.mark.asyncio
    async def test_get_associations_for_session(self, kanban):
        """Test getting all board associations for a session."""
        session_id = "test-session-456"

        # Create and associate multiple boards
        board1 = await kanban.create_board("Board 1")
        board2 = await kanban.create_board("Board 2")

        await kanban.associate_board_with_session(
            board_id=board1.board.id,
            session_id=session_id,
            role="primary",
        )
        await kanban.associate_board_with_session(
            board_id=board2.board.id,
            session_id=session_id,
            role="reference",
        )

        associations = await kanban.get_associations_for_session(session_id)

        assert len(associations) == 2
        board_ids = {a.board_id for a in associations}
        assert board1.board.id in board_ids
        assert board2.board.id in board_ids

    @pytest.mark.asyncio
    async def test_get_associations_for_session_empty(self, kanban):
        """Test getting associations for a session with no boards."""
        associations = await kanban.get_associations_for_session("nonexistent-session")
        assert associations == []

    @pytest.mark.asyncio
    async def test_get_boards_for_session(self, kanban):
        """Test getting boards with their associations for a session."""
        session_id = "test-session-789"

        board_state = await kanban.create_board("My Board")
        await kanban.associate_board_with_session(
            board_id=board_state.board.id,
            session_id=session_id,
        )

        boards = await kanban.get_boards_for_session(session_id)

        assert len(boards) == 1
        assoc, board = boards[0]
        assert board.id == board_state.board.id
        assert board.name == "My Board"
        assert assoc.session_id == session_id

    @pytest.mark.asyncio
    async def test_dissociate_board_from_session(self, kanban):
        """Test removing a board association from a session."""
        session_id = "test-session-abc"
        board_state = await kanban.create_board("Board to Remove")

        await kanban.associate_board_with_session(
            board_id=board_state.board.id,
            session_id=session_id,
        )

        # Verify association exists
        assocs = await kanban.get_associations_for_session(session_id)
        assert len(assocs) == 1

        # Dissociate
        result = await kanban.dissociate_board_from_session(
            board_id=board_state.board.id,
            session_id=session_id,
        )

        assert result is True

        # Verify association removed
        assocs = await kanban.get_associations_for_session(session_id)
        assert len(assocs) == 0

    @pytest.mark.asyncio
    async def test_dissociate_nonexistent_association(self, kanban):
        """Test dissociating a non-existent association returns False."""
        result = await kanban.dissociate_board_from_session(
            board_id="nonexistent-board",
            session_id="nonexistent-session",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_create_board_for_session(self, kanban):
        """Test creating a board that's automatically associated with a session."""
        session_id = "test-session-def"

        assoc, board_state = await kanban.create_board_for_session(
            session_id=session_id,
            name="Auto-associated Board",
        )

        assert assoc.session_id == session_id
        assert assoc.board_id == board_state.board.id
        assert assoc.role == "primary"
        assert assoc.created_by == "user"

        # Verify the board exists
        board = await kanban.get_board(board_state.board.id)
        assert board is not None
        assert board.name == "Auto-associated Board"

    @pytest.mark.asyncio
    async def test_inherit_board_associations(self, kanban):
        """Test inheriting board associations from parent to child session."""
        parent_id = "parent-session-xyz"
        child_id = "child-session-xyz"

        # Create boards and associate with parent
        board1 = await kanban.create_board("Inherited Board 1")
        board2 = await kanban.create_board("Inherited Board 2")

        await kanban.associate_board_with_session(
            board_id=board1.board.id,
            session_id=parent_id,
            role="primary",
        )
        await kanban.associate_board_with_session(
            board_id=board2.board.id,
            session_id=parent_id,
            role="reference",
        )

        # Inherit to child
        child_assocs = await kanban.inherit_board_associations(
            parent_session_id=parent_id,
            child_session_id=child_id,
        )

        assert len(child_assocs) == 2

        # All child associations should reference the parent
        for assoc in child_assocs:
            assert assoc.session_id == child_id
            assert assoc.created_by == "fork"
            assert assoc.inherited_from == parent_id

        # Child should have both boards
        child_boards = await kanban.get_boards_for_session(child_id)
        assert len(child_boards) == 2

        # Parent associations should be unchanged
        parent_assocs = await kanban.get_associations_for_session(parent_id)
        assert len(parent_assocs) == 2

    @pytest.mark.asyncio
    async def test_inherit_board_associations_empty_parent(self, kanban):
        """Test inheriting from a parent with no boards."""
        child_assocs = await kanban.inherit_board_associations(
            parent_session_id="empty-parent",
            child_session_id="empty-child",
        )
        assert child_assocs == []

    @pytest.mark.asyncio
    async def test_multiple_sessions_same_board(self, kanban):
        """Test that multiple sessions can share the same board."""
        board = await kanban.create_board("Shared Board")

        session1 = "session-1"
        session2 = "session-2"

        await kanban.associate_board_with_session(
            board_id=board.board.id,
            session_id=session1,
        )
        await kanban.associate_board_with_session(
            board_id=board.board.id,
            session_id=session2,
        )

        # Both sessions should see the board
        boards1 = await kanban.get_boards_for_session(session1)
        boards2 = await kanban.get_boards_for_session(session2)

        assert len(boards1) == 1
        assert len(boards2) == 1
        assert boards1[0][1].id == boards2[0][1].id
