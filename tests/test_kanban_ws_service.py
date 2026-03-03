"""Tests for service/kanban_ws_service.py."""

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
        yield Path(tmpdir) / "test_kanban_ws.db"


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


@pytest.fixture
def ws_service(kanban):
    """Create a KanbanWebSocketService instance."""
    from service.kanban_ws_service import KanbanWebSocketService
    return KanbanWebSocketService(kanban)


@pytest.fixture
def event_collector(ws_service):
    """Fixture that collects events emitted by the service.

    Returns a list of (event_name, data, target_clients) tuples.
    """
    events = []

    def handler(event_name: str, data: dict, target_clients: set[str] | None):
        events.append((event_name, data, target_clients))

    ws_service.add_event_handler(handler)
    return events


# =============================================================================
# Subscription Tests
# =============================================================================


class TestSubscriptionManagement:
    """Tests for board subscription management."""

    @pytest.mark.asyncio
    async def test_subscribe_to_board(self, ws_service):
        """Test subscribing to a board returns initial state."""
        board = await ws_service.create_board("Test Board")

        result = await ws_service.subscribe_board(board.board.id, "client-1")

        assert result.subscribed is True
        assert result.board is not None
        assert result.board.board.id == board.board.id
        assert result.board.board.name == "Test Board"
        assert len(result.board.columns) == 4

    @pytest.mark.asyncio
    async def test_subscribe_to_nonexistent_board(self, ws_service):
        """Test subscribing to a board that doesn't exist."""
        result = await ws_service.subscribe_board("nonexistent", "client-1")

        assert result.subscribed is False
        assert result.error == "Board not found"
        assert result.board is None

    @pytest.mark.asyncio
    async def test_subscribe_without_client_id(self, ws_service):
        """Test subscribing without client_id fails."""
        board = await ws_service.create_board("Test Board")

        result = await ws_service.subscribe_board(board.board.id, "")

        assert result.subscribed is False
        assert result.error == "client_id is required"

    @pytest.mark.asyncio
    async def test_unsubscribe_from_board(self, ws_service):
        """Test unsubscribing from a board."""
        board = await ws_service.create_board("Test Board")
        await ws_service.subscribe_board(board.board.id, "client-1")

        result = await ws_service.unsubscribe_board(board.board.id, "client-1")

        assert result.unsubscribed is True

        # Verify not in subscribed list
        subscribed = await ws_service.get_subscribed_boards("client-1")
        assert board.board.id not in subscribed

    @pytest.mark.asyncio
    async def test_get_subscribed_boards(self, ws_service):
        """Test getting list of subscribed boards."""
        board1 = await ws_service.create_board("Board 1")
        board2 = await ws_service.create_board("Board 2")

        await ws_service.subscribe_board(board1.board.id, "client-1")
        await ws_service.subscribe_board(board2.board.id, "client-1")

        subscribed = await ws_service.get_subscribed_boards("client-1")

        assert set(subscribed) == {board1.board.id, board2.board.id}

    @pytest.mark.asyncio
    async def test_client_disconnected_cleanup(self, ws_service):
        """Test that client_disconnected cleans up subscriptions."""
        board1 = await ws_service.create_board("Board 1")
        board2 = await ws_service.create_board("Board 2")

        await ws_service.subscribe_board(board1.board.id, "client-1")
        await ws_service.subscribe_board(board2.board.id, "client-1")

        # Simulate disconnect
        ws_service.client_disconnected("client-1")

        # Verify cleaned up
        subscribed = await ws_service.get_subscribed_boards("client-1")
        assert subscribed == []


# =============================================================================
# Event Targeting Tests
# =============================================================================


class TestEventTargeting:
    """Tests for event targeting to subscribers only."""

    @pytest.mark.asyncio
    async def test_task_event_only_to_subscribers(self, ws_service, event_collector):
        """Test that task events only go to board subscribers."""
        board = await ws_service.create_board("Test Board")
        event_collector.clear()  # Clear board created event

        # Subscribe client-1 to board
        await ws_service.subscribe_board(board.board.id, "client-1")

        # Create a task
        await ws_service.create_task(board.board.id, "New Task")

        # Find taskCreated event
        task_events = [e for e in event_collector if e[0] == "taskCreated"]
        assert len(task_events) == 1

        event_name, data, target_clients = task_events[0]
        assert target_clients == {"client-1"}
        assert data["board_id"] == board.board.id

    @pytest.mark.asyncio
    async def test_board_created_broadcasts_to_all(self, ws_service, event_collector):
        """Test that boardCreated broadcasts to all (target_clients=None)."""
        await ws_service.create_board("Test Board")

        assert len(event_collector) == 1
        event_name, data, target_clients = event_collector[0]

        assert event_name == "boardCreated"
        assert target_clients is None  # Broadcast

    @pytest.mark.asyncio
    async def test_board_deleted_broadcasts_to_all(self, ws_service, event_collector):
        """Test that boardDeleted broadcasts to all."""
        board = await ws_service.create_board("Test Board")
        event_collector.clear()

        await ws_service.delete_board(board.board.id)

        assert len(event_collector) == 1
        event_name, data, target_clients = event_collector[0]

        assert event_name == "boardDeleted"
        assert target_clients is None  # Broadcast

    @pytest.mark.asyncio
    async def test_multiple_subscribers_receive_events(self, ws_service, event_collector):
        """Test that multiple subscribers all receive events."""
        board = await ws_service.create_board("Test Board")
        event_collector.clear()

        # Subscribe multiple clients
        await ws_service.subscribe_board(board.board.id, "client-1")
        await ws_service.subscribe_board(board.board.id, "client-2")
        await ws_service.subscribe_board(board.board.id, "client-3")

        # Create a task
        await ws_service.create_task(board.board.id, "New Task")

        task_events = [e for e in event_collector if e[0] == "taskCreated"]
        assert len(task_events) == 1

        _, _, target_clients = task_events[0]
        assert target_clients == {"client-1", "client-2", "client-3"}

    @pytest.mark.asyncio
    async def test_unsubscribed_client_doesnt_receive_events(
        self, ws_service, event_collector
    ):
        """Test that unsubscribed clients don't receive events."""
        board = await ws_service.create_board("Test Board")
        event_collector.clear()

        # Subscribe then unsubscribe
        await ws_service.subscribe_board(board.board.id, "client-1")
        await ws_service.unsubscribe_board(board.board.id, "client-1")

        # Create a task
        await ws_service.create_task(board.board.id, "New Task")

        # No events should target any clients (empty set)
        task_events = [e for e in event_collector if e[0] == "taskCreated"]
        # Event may or may not be emitted with empty target set, depending on implementation
        if task_events:
            _, _, target_clients = task_events[0]
            assert "client-1" not in (target_clients or set())


# =============================================================================
# Board Operations with Events
# =============================================================================


class TestWebSocketBoardOperations:
    """Tests for WebSocket board operations."""

    @pytest.mark.asyncio
    async def test_create_board(self, ws_service, event_collector):
        """Test creating a board via WebSocket."""
        result = await ws_service.create_board("Sprint 1")

        assert result.board.name == "Sprint 1"
        assert len(result.columns) == 4
        assert len(result.tasks) == 0

        # Check broadcast event
        assert len(event_collector) == 1
        event_name, event_data, target_clients = event_collector[0]
        assert event_name == "boardCreated"
        assert target_clients is None  # Broadcast

    @pytest.mark.asyncio
    async def test_get_board(self, ws_service):
        """Test getting a board via WebSocket."""
        created = await ws_service.create_board("Test Board")

        result = await ws_service.get_board(created.board.id)

        assert result is not None
        assert result.board.id == created.board.id
        assert result.board.name == "Test Board"

    @pytest.mark.asyncio
    async def test_list_boards(self, ws_service):
        """Test listing boards via WebSocket."""
        await ws_service.create_board("Board 1")
        await ws_service.create_board("Board 2")

        result = await ws_service.list_boards()

        assert len(result) == 2
        names = {b.name for b in result}
        assert names == {"Board 1", "Board 2"}

    @pytest.mark.asyncio
    async def test_delete_board_cleans_subscriptions(self, ws_service):
        """Test deleting a board cleans up subscriptions."""
        board = await ws_service.create_board("To Delete")
        await ws_service.subscribe_board(board.board.id, "client-1")

        await ws_service.delete_board(board.board.id)

        # Verify subscription cleaned up
        subscribed = await ws_service.get_subscribed_boards("client-1")
        assert board.board.id not in subscribed


# =============================================================================
# Task Operations with Events
# =============================================================================


class TestWebSocketTaskOperations:
    """Tests for WebSocket task operations."""

    @pytest.mark.asyncio
    async def test_create_task(self, ws_service, event_collector):
        """Test creating a task via WebSocket."""
        board = await ws_service.create_board("Task Board")
        await ws_service.subscribe_board(board.board.id, "client-1")
        event_collector.clear()

        task = await ws_service.create_task(
            board_id=board.board.id,
            title="New Task",
            description="Task description",
        )

        assert task is not None
        assert task.title == "New Task"

        # Check targeted event
        assert len(event_collector) == 1
        event_name, event_data, target_clients = event_collector[0]
        assert event_name == "taskCreated"
        assert target_clients == {"client-1"}
        assert event_data["task"]["title"] == "New Task"

    @pytest.mark.asyncio
    async def test_update_task(self, ws_service, event_collector):
        """Test updating a task via WebSocket."""
        board = await ws_service.create_board("Task Board")
        task = await ws_service.create_task(board.board.id, "Original")
        await ws_service.subscribe_board(board.board.id, "client-1")
        event_collector.clear()

        updated = await ws_service.update_task(
            task_id=task.id,
            board_id=board.board.id,
            title="Updated Title",
        )

        assert updated.title == "Updated Title"

        # Check targeted event
        event_name, event_data, target_clients = event_collector[0]
        assert event_name == "taskUpdated"
        assert target_clients == {"client-1"}

    @pytest.mark.asyncio
    async def test_delete_task(self, ws_service, event_collector):
        """Test deleting a task via WebSocket."""
        board = await ws_service.create_board("Task Board")
        task = await ws_service.create_task(board.board.id, "To Delete")
        await ws_service.subscribe_board(board.board.id, "client-1")
        event_collector.clear()

        result = await ws_service.delete_task(task.id, board.board.id)
        assert result is True

        # Check targeted event
        event_name, event_data, target_clients = event_collector[0]
        assert event_name == "taskDeleted"
        assert target_clients == {"client-1"}
        assert event_data["task_id"] == task.id

    @pytest.mark.asyncio
    async def test_move_task(self, ws_service, event_collector):
        """Test moving a task via WebSocket."""
        board = await ws_service.create_board("Task Board")
        done_column_id = board.columns[3].id
        task = await ws_service.create_task(board.board.id, "Moving")
        await ws_service.subscribe_board(board.board.id, "client-1")
        event_collector.clear()

        result = await ws_service.move_task(
            task_id=task.id,
            board_id=board.board.id,
            to_column_id=done_column_id,
            from_column_id=board.columns[0].id,
        )
        assert result is True

        # Check targeted event
        event_name, event_data, target_clients = event_collector[0]
        assert event_name == "taskMoved"
        assert target_clients == {"client-1"}
        assert event_data["to_column_id"] == done_column_id

    @pytest.mark.asyncio
    async def test_reorder_tasks(self, ws_service, event_collector):
        """Test reordering tasks via WebSocket."""
        board = await ws_service.create_board("Task Board")
        backlog_id = board.columns[0].id

        task1 = await ws_service.create_task(board.board.id, "Task 1")
        task2 = await ws_service.create_task(board.board.id, "Task 2")
        task3 = await ws_service.create_task(board.board.id, "Task 3")

        await ws_service.subscribe_board(board.board.id, "client-1")
        event_collector.clear()

        result = await ws_service.reorder_tasks(
            column_id=backlog_id,
            board_id=board.board.id,
            task_ids=[task3.id, task1.id, task2.id],
        )
        assert result is True

        # Check targeted event
        event_name, event_data, target_clients = event_collector[0]
        assert event_name == "tasksReordered"
        assert target_clients == {"client-1"}
        assert event_data["task_ids"] == [task3.id, task1.id, task2.id]


# =============================================================================
# Column Operations with Events
# =============================================================================


class TestWebSocketColumnOperations:
    """Tests for WebSocket column operations."""

    @pytest.mark.asyncio
    async def test_add_column(self, ws_service, event_collector):
        """Test adding a column via WebSocket."""
        board = await ws_service.create_board("Column Board")
        await ws_service.subscribe_board(board.board.id, "client-1")
        event_collector.clear()

        column = await ws_service.add_column(
            board_id=board.board.id,
            name="Review",
        )

        assert column is not None
        assert column.name == "Review"

        # Check targeted event
        event_name, event_data, target_clients = event_collector[0]
        assert event_name == "columnAdded"
        assert target_clients == {"client-1"}
        assert event_data["column"]["name"] == "Review"

    @pytest.mark.asyncio
    async def test_delete_column(self, ws_service, event_collector):
        """Test deleting a column via WebSocket."""
        board = await ws_service.create_board("Column Board")
        todo_column_id = board.columns[1].id
        await ws_service.subscribe_board(board.board.id, "client-1")
        event_collector.clear()

        result = await ws_service.delete_column(
            column_id=todo_column_id,
            board_id=board.board.id,
        )
        assert result is True

        # Check targeted event
        event_name, event_data, target_clients = event_collector[0]
        assert event_name == "columnDeleted"
        assert target_clients == {"client-1"}
        assert event_data["column_id"] == todo_column_id


# =============================================================================
# Wire Type Tests
# =============================================================================


class TestWireTypes:
    """Tests for wire type structure."""

    @pytest.mark.asyncio
    async def test_board_state_info_structure(self, ws_service):
        """Test BoardStateInfo has correct structure."""
        board = await ws_service.create_board("Test Board")

        await ws_service.create_task(board.board.id, "Task 1")
        await ws_service.create_task(board.board.id, "Task 2")

        state = await ws_service.get_board(board.board.id)

        assert hasattr(state, 'board')
        assert hasattr(state, 'columns')
        assert hasattr(state, 'tasks')

        assert len(state.tasks) == 2
        for task in state.tasks:
            assert hasattr(task, 'id')
            assert hasattr(task, 'title')

    @pytest.mark.asyncio
    async def test_subscription_result_includes_full_state(self, ws_service):
        """Test that subscription result includes full board state."""
        board = await ws_service.create_board("Test Board")
        await ws_service.create_task(board.board.id, "Task 1")

        result = await ws_service.subscribe_board(board.board.id, "client-1")

        assert result.subscribed is True
        assert result.board is not None
        assert len(result.board.tasks) == 1
        assert result.board.tasks[0].title == "Task 1"


# =============================================================================
# Event Handler Tests
# =============================================================================


class TestEventHandlers:
    """Tests for event handler management."""

    @pytest.mark.asyncio
    async def test_remove_event_handler(self, ws_service):
        """Test removing an event handler."""
        events = []

        def handler(event_name: str, data: dict, target_clients: set[str] | None):
            events.append(event_name)

        ws_service.add_event_handler(handler)
        await ws_service.create_board("Board 1")
        assert len(events) == 1

        ws_service.remove_event_handler(handler)
        await ws_service.create_board("Board 2")
        assert len(events) == 1  # No new event

    @pytest.mark.asyncio
    async def test_multiple_event_handlers(self, ws_service):
        """Test multiple event handlers receive events."""
        events1 = []
        events2 = []

        def handler1(event_name: str, data: dict, target_clients: set[str] | None):
            events1.append(event_name)

        def handler2(event_name: str, data: dict, target_clients: set[str] | None):
            events2.append(event_name)

        ws_service.add_event_handler(handler1)
        ws_service.add_event_handler(handler2)

        await ws_service.create_board("Test Board")

        assert len(events1) == 1
        assert len(events2) == 1
