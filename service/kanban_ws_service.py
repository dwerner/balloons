"""WebSocket-exposed service for kanban board operations.

This service wraps KanbanService and exposes it via WebSocket RPC.
The @ws_expose decorators mark methods for client generation.

Subscription model:
- Clients subscribe to specific boards to receive real-time updates
- On subscription, clients receive the full board state (snapshot)
- After subscribing, clients receive targeted events for that board only
- Unsubscribing stops event delivery for that board

Example usage:
    kanban_service = KanbanService(storage)
    ws_service = KanbanWebSocketService(kanban_service)

    # Subscribe to a board (returns initial state):
    # {"id": "1", "method": "kanban.subscribeBoard", "params": {"boardId": "abc", "clientId": "xyz"}}
    # -> {"id": "1", "result": {"subscribed": true, "board": {...}}}

    # Events are pushed only to subscribed clients:
    # {"event": "taskMoved", "data": {"boardId": "abc", "taskId": "...", ...}}

    # Unsubscribe when done:
    # {"id": "2", "method": "kanban.unsubscribeBoard", "params": {"boardId": "abc", "clientId": "xyz"}}
"""

from dataclasses import dataclass, field, asdict
from typing import Callable, Any, Optional

from codegen import ws_service, ws_expose, ws_event, ws_type
from core.kanban_service import (
    KanbanService,
    Task,
    Column,
    Board,
    BoardState,
    SessionBoardAssociation,
)


# =============================================================================
# Wire Types for WebSocket Codegen
# =============================================================================


@ws_type
@dataclass
class KanbanTaskInfo:
    """Task information for kanban display."""
    id: str
    title: str
    description: str
    resolution: str  # What was done to complete/resolve the task
    created_at: str
    updated_at: str


@ws_type
@dataclass
class ColumnInfo:
    """Column information for display."""
    id: str
    name: str
    position: int
    task_ids: list[str] = field(default_factory=list)


@ws_type
@dataclass
class BoardInfo:
    """Board information for display."""
    id: str
    name: str
    default_column_id: str
    created_at: str


@ws_type
@dataclass
class BoardStateInfo:
    """Full board state with columns and tasks."""
    board: BoardInfo
    columns: list[ColumnInfo]
    tasks: list[KanbanTaskInfo]  # All tasks, referenced by task_ids in columns


# =============================================================================
# Subscription Types
# =============================================================================


@ws_type
@dataclass
class BoardSubscriptionResult:
    """Result of subscribing to a board."""
    board_id: str
    subscribed: bool
    board: BoardStateInfo | None = None  # Full state at subscription time
    error: str | None = None


@ws_type
@dataclass
class BoardUnsubscribeResult:
    """Result of unsubscribing from a board."""
    board_id: str
    unsubscribed: bool
    error: str | None = None


# =============================================================================
# Event Types - All include board_id for routing
# =============================================================================


@ws_type
@dataclass
class TaskMovedEvent:
    """Event fired when a task is moved between columns."""
    board_id: str
    task_id: str
    from_column_id: str
    to_column_id: str
    new_position: int


@ws_type
@dataclass
class TaskCreatedEvent:
    """Event fired when a task is created."""
    board_id: str
    task: KanbanTaskInfo
    column_id: str
    position: int


@ws_type
@dataclass
class TaskUpdatedEvent:
    """Event fired when a task is updated."""
    board_id: str
    task: KanbanTaskInfo


@ws_type
@dataclass
class TaskDeletedEvent:
    """Event fired when a task is deleted."""
    board_id: str
    task_id: str


@ws_type
@dataclass
class TasksReorderedEvent:
    """Event fired when tasks are reordered within a column."""
    board_id: str
    column_id: str
    task_ids: list[str]  # New order


@ws_type
@dataclass
class BoardCreatedEvent:
    """Event fired when a board is created (broadcast to all)."""
    board: BoardStateInfo


@ws_type
@dataclass
class BoardDeletedEvent:
    """Event fired when a board is deleted (broadcast to all)."""
    board_id: str


@ws_type
@dataclass
class ColumnAddedEvent:
    """Event fired when a column is added to a board."""
    board_id: str
    column: ColumnInfo


@ws_type
@dataclass
class ColumnDeletedEvent:
    """Event fired when a column is deleted from a board."""
    board_id: str
    column_id: str
    tasks_moved_to: str | None  # Column tasks were migrated to, if any


# =============================================================================
# Session-Board Association Types
# =============================================================================


@ws_type
@dataclass
class BoardAssociationInfo:
    """Information about a session-board association."""
    id: str
    session_id: str
    board_id: str
    role: str  # "primary", "reference", "archive"
    created_at: str
    created_by: str  # "user", "llm", "fork"
    inherited_from: str | None = None  # Parent session ID if inherited


@ws_type
@dataclass
class SessionBoardsResult:
    """Result of getting boards for a session."""
    session_id: str
    associations: list[BoardAssociationInfo]
    boards: list[BoardInfo]  # Matching boards in same order


@ws_type
@dataclass
class BoardSessionsResult:
    """Result of getting sessions for a board."""
    board_id: str
    associations: list[BoardAssociationInfo]


@ws_type
@dataclass
class BoardAssociatedEvent:
    """Event fired when a board is associated with a session."""
    association: BoardAssociationInfo
    board: BoardInfo


@ws_type
@dataclass
class BoardDisassociatedEvent:
    """Event fired when a board is disassociated from a session."""
    session_id: str
    board_id: str
    association_id: str


# =============================================================================
# Service Class
# =============================================================================


@ws_service
class KanbanWebSocketService:
    """WebSocket-exposed service for kanban board management.

    Provides CRUD operations for boards, columns, and tasks,
    with subscription-based real-time events for state changes.

    Subscription model:
    - Clients call subscribeBoard(boardId, clientId) to start receiving events
    - Events are only sent to clients subscribed to the affected board
    - Board lifecycle events (created/deleted) are broadcast to all clients
    """

    def __init__(self, kanban_service: KanbanService):
        """Initialize service with a KanbanService instance.

        Args:
            kanban_service: The KanbanService to expose via WebSocket
        """
        self._kanban = kanban_service

        # Subscription tracking: board_id -> set of client_ids
        self._board_subscriptions: dict[str, set[str]] = {}

        # Reverse mapping: client_id -> set of board_ids (for cleanup)
        self._client_boards: dict[str, set[str]] = {}

        # Event handlers: (event_name, data, target_clients) -> None
        # target_clients is None for broadcast, or set of client_ids
        self._event_handlers: list[Callable[[str, dict, set[str] | None], None]] = []

    def add_event_handler(
        self, handler: Callable[[str, dict, set[str] | None], None]
    ) -> None:
        """Register a handler for WebSocket events.

        The handler will be called with (event_name, data, target_clients).
        target_clients is a set of client_ids to receive the event,
        or None to broadcast to all connected clients.
        """
        self._event_handlers.append(handler)

    def remove_event_handler(
        self, handler: Callable[[str, dict, set[str] | None], None]
    ) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def _emit(
        self,
        event_name: str,
        data: Any,
        target_clients: set[str] | None = None,
    ) -> None:
        """Emit an event to registered handlers.

        Args:
            event_name: The event name (e.g., "taskMoved")
            data: The event payload (dataclass or dict)
            target_clients: Set of client_ids to receive event, or None for broadcast
        """
        event_data = asdict(data) if hasattr(data, '__dataclass_fields__') else data
        for handler in self._event_handlers:
            handler(event_name, event_data, target_clients)

    def _emit_to_board(self, board_id: str, event_name: str, data: Any) -> None:
        """Emit an event to all clients subscribed to a board.

        Args:
            board_id: The board ID
            event_name: The event name
            data: The event payload
        """
        subscribers = self._board_subscriptions.get(board_id, set())
        if subscribers:
            self._emit(event_name, data, subscribers)

    def _emit_broadcast(self, event_name: str, data: Any) -> None:
        """Emit an event to all connected clients.

        Args:
            event_name: The event name
            data: The event payload
        """
        self._emit(event_name, data, None)

    def client_disconnected(self, client_id: str) -> None:
        """Clean up subscriptions when a client disconnects.

        Args:
            client_id: The disconnected client's ID
        """
        if client_id not in self._client_boards:
            return

        # Remove client from all board subscriptions
        for board_id in self._client_boards[client_id]:
            if board_id in self._board_subscriptions:
                self._board_subscriptions[board_id].discard(client_id)
                # Clean up empty subscription sets
                if not self._board_subscriptions[board_id]:
                    del self._board_subscriptions[board_id]

        # Remove client tracking
        del self._client_boards[client_id]

    # --- Helper Methods ---

    def _task_to_info(self, task: Task) -> KanbanTaskInfo:
        """Convert Task to TaskInfo wire type."""
        return KanbanTaskInfo(
            id=task.id,
            title=task.title,
            description=task.description,
            resolution=task.resolution,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    def _column_to_info(self, column: Column) -> ColumnInfo:
        """Convert Column to ColumnInfo wire type."""
        return ColumnInfo(
            id=column.id,
            name=column.name,
            position=column.position,
            task_ids=[t.id for t in column.tasks],
        )

    def _board_to_info(self, board: Board) -> BoardInfo:
        """Convert Board to BoardInfo wire type."""
        return BoardInfo(
            id=board.id,
            name=board.name,
            default_column_id=board.default_column_id,
            created_at=board.created_at,
        )

    def _board_state_to_info(self, state: BoardState) -> BoardStateInfo:
        """Convert BoardState to BoardStateInfo wire type."""
        all_tasks: list[KanbanTaskInfo] = []
        columns: list[ColumnInfo] = []

        for col in state.columns:
            columns.append(self._column_to_info(col))
            for task in col.tasks:
                all_tasks.append(self._task_to_info(task))

        return BoardStateInfo(
            board=self._board_to_info(state.board),
            columns=columns,
            tasks=all_tasks,
        )

    # --- Subscription Management ---

    @ws_expose
    async def subscribe_board(
        self, board_id: str, client_id: str
    ) -> BoardSubscriptionResult:
        """Subscribe to real-time updates for a board.

        On subscription, returns the full board state. After subscribing,
        the client will receive events for any changes to this board.

        Args:
            board_id: The board to subscribe to
            client_id: Unique identifier for the client

        Returns:
            Subscription result with initial board state
        """
        if not client_id:
            return BoardSubscriptionResult(
                board_id=board_id,
                subscribed=False,
                error="client_id is required",
            )

        # Get the board state
        state = await self._kanban.get_board_state(board_id)
        if not state:
            return BoardSubscriptionResult(
                board_id=board_id,
                subscribed=False,
                error="Board not found",
            )

        # Add to subscriptions
        if board_id not in self._board_subscriptions:
            self._board_subscriptions[board_id] = set()
        self._board_subscriptions[board_id].add(client_id)

        # Track client -> boards for cleanup
        if client_id not in self._client_boards:
            self._client_boards[client_id] = set()
        self._client_boards[client_id].add(board_id)

        return BoardSubscriptionResult(
            board_id=board_id,
            subscribed=True,
            board=self._board_state_to_info(state),
        )

    @ws_expose
    async def unsubscribe_board(
        self, board_id: str, client_id: str
    ) -> BoardUnsubscribeResult:
        """Unsubscribe from real-time updates for a board.

        Args:
            board_id: The board to unsubscribe from
            client_id: The client's identifier

        Returns:
            Unsubscription result
        """
        if not client_id:
            return BoardUnsubscribeResult(
                board_id=board_id,
                unsubscribed=False,
                error="client_id is required",
            )

        # Remove from board subscriptions
        if board_id in self._board_subscriptions:
            self._board_subscriptions[board_id].discard(client_id)
            if not self._board_subscriptions[board_id]:
                del self._board_subscriptions[board_id]

        # Remove from client tracking
        if client_id in self._client_boards:
            self._client_boards[client_id].discard(board_id)
            if not self._client_boards[client_id]:
                del self._client_boards[client_id]

        return BoardUnsubscribeResult(
            board_id=board_id,
            unsubscribed=True,
        )

    @ws_expose
    async def get_subscribed_boards(self, client_id: str) -> list[str]:
        """Get list of board IDs a client is subscribed to.

        Args:
            client_id: The client's identifier

        Returns:
            List of subscribed board IDs
        """
        return list(self._client_boards.get(client_id, set()))

    # --- Board Operations ---

    @ws_expose
    async def create_board(self, name: str) -> BoardStateInfo:
        """Create a new board with default columns.

        Broadcasts boardCreated event to all connected clients.

        Args:
            name: Display name for the board

        Returns:
            Full board state with columns (Backlog, To Do, In Progress, Done)
        """
        state = await self._kanban.create_board(name)
        info = self._board_state_to_info(state)
        self._emit_broadcast("boardCreated", BoardCreatedEvent(board=info))
        return info

    @ws_expose
    async def get_board(self, board_id: str) -> BoardStateInfo | None:
        """Get full board state by ID.

        Args:
            board_id: The board ID

        Returns:
            BoardStateInfo with columns and tasks, or None if not found
        """
        state = await self._kanban.get_board_state(board_id)
        if not state:
            return None
        return self._board_state_to_info(state)

    @ws_expose
    async def list_boards(self) -> list[BoardInfo]:
        """List all boards.

        Returns:
            List of board info (without columns/tasks for efficiency)
        """
        boards = await self._kanban.list_boards()
        return [self._board_to_info(b) for b in boards]

    @ws_expose
    async def delete_board(self, board_id: str) -> bool:
        """Delete a board.

        Broadcasts boardDeleted event to all connected clients.
        Also cleans up subscriptions for the deleted board.

        Args:
            board_id: The board ID to delete

        Returns:
            True if deleted, False if not found
        """
        success = await self._kanban.delete_board(board_id)
        if success:
            # Broadcast deletion to all clients
            self._emit_broadcast("boardDeleted", BoardDeletedEvent(
                board_id=board_id,
            ))

            # Clean up subscriptions
            if board_id in self._board_subscriptions:
                for client_id in self._board_subscriptions[board_id]:
                    if client_id in self._client_boards:
                        self._client_boards[client_id].discard(board_id)
                del self._board_subscriptions[board_id]

        return success

    # --- Task Operations ---

    @ws_expose
    async def create_task(
        self,
        board_id: str,
        title: str,
        description: str = "",
        column_id: str | None = None,
    ) -> KanbanTaskInfo | None:
        """Create a new task on a board.

        Emits taskCreated event to board subscribers.

        Args:
            board_id: The board to add the task to
            title: Task title
            description: Task description (optional)
            column_id: Column to place task in (defaults to board's default column)

        Returns:
            Created task info, or None if board not found
        """
        # Get the board to determine actual column
        board = await self._kanban.get_board(board_id)
        if not board:
            return None

        actual_column_id = column_id or board.default_column_id

        task = await self._kanban.create_task(
            board_id=board_id,
            title=title,
            description=description,
            column_id=actual_column_id,
        )
        if not task:
            return None

        info = self._task_to_info(task)
        self._emit_to_board(board_id, "taskCreated", TaskCreatedEvent(
            board_id=board_id,
            task=info,
            column_id=actual_column_id,
            position=0,  # TODO: return actual position from create_task
        ))
        return info

    @ws_expose
    async def update_task(
        self,
        task_id: str,
        board_id: str,
        title: str | None = None,
        description: str | None = None,
        resolution: str | None = None,
    ) -> KanbanTaskInfo | None:
        """Update a task's title, description, and/or resolution.

        Emits taskUpdated event to board subscribers.

        Args:
            task_id: The task ID
            board_id: The board the task belongs to (for event routing)
            title: New title (optional)
            description: New description (optional)
            resolution: What was done to complete/resolve the task (optional)

        Returns:
            Updated task info, or None if not found
        """
        task = await self._kanban.update_task(
            task_id=task_id,
            title=title,
            description=description,
            resolution=resolution,
        )
        if not task:
            return None

        info = self._task_to_info(task)
        self._emit_to_board(board_id, "taskUpdated", TaskUpdatedEvent(
            board_id=board_id,
            task=info,
        ))
        return info

    @ws_expose
    async def delete_task(self, task_id: str, board_id: str) -> bool:
        """Delete a task.

        Emits taskDeleted event to board subscribers.

        Args:
            task_id: The task ID to delete
            board_id: The board the task belongs to (for event routing)

        Returns:
            True if deleted, False if not found
        """
        success = await self._kanban.delete_task(task_id)
        if success:
            self._emit_to_board(board_id, "taskDeleted", TaskDeletedEvent(
                board_id=board_id,
                task_id=task_id,
            ))
        return success

    @ws_expose
    async def move_task(
        self,
        task_id: str,
        board_id: str,
        to_column_id: str,
        position: int | None = None,
        from_column_id: str | None = None,
    ) -> bool:
        """Move a task to a different column or position.

        Emits taskMoved event to board subscribers.

        Args:
            task_id: The task to move
            board_id: The board the task belongs to (for event routing)
            to_column_id: Target column ID
            position: Position in target column (defaults to end)
            from_column_id: Source column ID (for event, optional)

        Returns:
            True if moved, False if task not found
        """
        success = await self._kanban.move_task(
            task_id=task_id,
            to_column_id=to_column_id,
            position=position,
        )
        if success:
            self._emit_to_board(board_id, "taskMoved", TaskMovedEvent(
                board_id=board_id,
                task_id=task_id,
                from_column_id=from_column_id or "",
                to_column_id=to_column_id,
                new_position=position or 0,
            ))
        return success

    @ws_expose
    async def reorder_tasks(
        self, column_id: str, board_id: str, task_ids: list[str]
    ) -> bool:
        """Reorder tasks within a column.

        Emits tasksReordered event to board subscribers.

        Args:
            column_id: The column containing the tasks
            board_id: The board the column belongs to (for event routing)
            task_ids: List of task IDs in desired order

        Returns:
            True if reordered, False if column has mismatched tasks
        """
        success = await self._kanban.reorder_tasks(column_id, task_ids)
        if success:
            self._emit_to_board(board_id, "tasksReordered", TasksReorderedEvent(
                board_id=board_id,
                column_id=column_id,
                task_ids=task_ids,
            ))
        return success

    # --- Column Operations ---

    @ws_expose
    async def add_column(
        self,
        board_id: str,
        name: str,
        position: int | None = None,
    ) -> ColumnInfo | None:
        """Add a new column to a board.

        Emits columnAdded event to board subscribers.

        Args:
            board_id: The board to add the column to
            name: Column name
            position: Position in board (defaults to end)

        Returns:
            Created column info, or None if board not found
        """
        column = await self._kanban.add_column(
            board_id=board_id,
            name=name,
            position=position,
        )
        if not column:
            return None

        info = self._column_to_info(column)
        self._emit_to_board(board_id, "columnAdded", ColumnAddedEvent(
            board_id=board_id,
            column=info,
        ))
        return info

    @ws_expose
    async def delete_column(
        self,
        column_id: str,
        board_id: str,
        move_tasks_to: str | None = None,
    ) -> bool:
        """Delete a column from a board.

        Emits columnDeleted event to board subscribers.

        Args:
            column_id: The column ID to delete
            board_id: The board the column belongs to (for event routing)
            move_tasks_to: Optional column ID to move tasks to

        Returns:
            True if deleted, False if not found
        """
        success = await self._kanban.delete_column(
            column_id=column_id,
            move_tasks_to=move_tasks_to,
        )
        if success:
            self._emit_to_board(board_id, "columnDeleted", ColumnDeletedEvent(
                board_id=board_id,
                column_id=column_id,
                tasks_moved_to=move_tasks_to,
            ))
        return success

    # --- Session-Board Association Operations ---

    def _association_to_info(self, assoc: SessionBoardAssociation) -> BoardAssociationInfo:
        """Convert SessionBoardAssociation to BoardAssociationInfo wire type."""
        return BoardAssociationInfo(
            id=assoc.id,
            session_id=assoc.session_id,
            board_id=assoc.board_id,
            role=assoc.role,
            created_at=assoc.created_at,
            created_by=assoc.created_by,
            inherited_from=assoc.inherited_from,
        )

    @ws_expose
    async def get_boards_for_session(self, session_id: str) -> SessionBoardsResult:
        """Get all boards associated with a session.

        Args:
            session_id: The session ID

        Returns:
            SessionBoardsResult with associations and matching boards
        """
        board_tuples = await self._kanban.get_boards_for_session(session_id)

        associations: list[BoardAssociationInfo] = []
        boards: list[BoardInfo] = []

        for assoc, board in board_tuples:
            associations.append(self._association_to_info(assoc))
            boards.append(self._board_to_info(board))

        return SessionBoardsResult(
            session_id=session_id,
            associations=associations,
            boards=boards,
        )

    @ws_expose
    async def get_sessions_for_board(self, board_id: str) -> BoardSessionsResult:
        """Get all sessions associated with a board.

        Args:
            board_id: The board ID

        Returns:
            BoardSessionsResult with associations
        """
        associations = await self._kanban.get_sessions_for_board(board_id)
        return BoardSessionsResult(
            board_id=board_id,
            associations=[self._association_to_info(a) for a in associations],
        )

    @ws_expose
    async def associate_board_with_session(
        self,
        board_id: str,
        session_id: str,
        role: str = "primary",
    ) -> BoardAssociationInfo | None:
        """Associate a board with a session.

        Emits boardAssociated event to all connected clients.

        Args:
            board_id: The board to associate
            session_id: The session to associate with
            role: Role of this association (primary, reference, archive)

        Returns:
            Association info, or None if board not found
        """
        # Verify board exists
        board = await self._kanban.get_board(board_id)
        if not board:
            return None

        assoc = await self._kanban.associate_board_with_session(
            board_id=board_id,
            session_id=session_id,
            role=role,
            created_by="user",
        )

        info = self._association_to_info(assoc)
        self._emit_broadcast("boardAssociated", BoardAssociatedEvent(
            association=info,
            board=self._board_to_info(board),
        ))
        return info

    @ws_expose
    async def dissociate_board_from_session(
        self,
        board_id: str,
        session_id: str,
    ) -> bool:
        """Remove a board association from a session.

        Emits boardDisassociated event to all connected clients.

        Args:
            board_id: The board to dissociate
            session_id: The session to dissociate from

        Returns:
            True if an association was removed, False if not found
        """
        # Get the association ID before deleting
        associations = await self._kanban.get_associations_for_session(session_id)
        assoc_id = None
        for assoc in associations:
            if assoc.board_id == board_id:
                assoc_id = assoc.id
                break

        success = await self._kanban.dissociate_board_from_session(
            board_id=board_id,
            session_id=session_id,
        )

        if success and assoc_id:
            self._emit_broadcast("boardDisassociated", BoardDisassociatedEvent(
                session_id=session_id,
                board_id=board_id,
                association_id=assoc_id,
            ))
        return success

    @ws_expose
    async def create_board_for_session(
        self,
        session_id: str,
        name: str,
    ) -> BoardStateInfo | None:
        """Create a new board and associate it with a session.

        Emits boardCreated and boardAssociated events.

        Args:
            session_id: The session to associate with
            name: Display name for the board

        Returns:
            Full board state, or None on error
        """
        assoc, board_state = await self._kanban.create_board_for_session(
            session_id=session_id,
            name=name,
        )

        info = self._board_state_to_info(board_state)

        # Emit boardCreated to all
        self._emit_broadcast("boardCreated", BoardCreatedEvent(board=info))

        # Emit boardAssociated to all
        self._emit_broadcast("boardAssociated", BoardAssociatedEvent(
            association=self._association_to_info(assoc),
            board=info.board,
        ))

        return info

    # --- Event Declarations (for codegen) ---
    # These are stub methods that declare event shapes for TypeScript client generation.
    # The actual events are emitted via _emit_to_board() and _emit_broadcast().

    @ws_event
    def board_created(self, event: BoardCreatedEvent) -> BoardCreatedEvent:
        """Fired when a new board is created (broadcast to all clients)."""
        pass

    @ws_event
    def board_deleted(self, event: BoardDeletedEvent) -> BoardDeletedEvent:
        """Fired when a board is deleted (broadcast to all clients)."""
        pass

    @ws_event
    def task_created(self, event: TaskCreatedEvent) -> TaskCreatedEvent:
        """Fired when a task is created (sent to board subscribers)."""
        pass

    @ws_event
    def task_updated(self, event: TaskUpdatedEvent) -> TaskUpdatedEvent:
        """Fired when a task is updated (sent to board subscribers)."""
        pass

    @ws_event
    def task_deleted(self, event: TaskDeletedEvent) -> TaskDeletedEvent:
        """Fired when a task is deleted (sent to board subscribers)."""
        pass

    @ws_event
    def task_moved(self, event: TaskMovedEvent) -> TaskMovedEvent:
        """Fired when a task is moved between columns (sent to board subscribers)."""
        pass

    @ws_event
    def tasks_reordered(self, event: TasksReorderedEvent) -> TasksReorderedEvent:
        """Fired when tasks are reordered within a column (sent to board subscribers)."""
        pass

    @ws_event
    def column_added(self, event: ColumnAddedEvent) -> ColumnAddedEvent:
        """Fired when a column is added to a board (sent to board subscribers)."""
        pass

    @ws_event
    def column_deleted(self, event: ColumnDeletedEvent) -> ColumnDeletedEvent:
        """Fired when a column is deleted from a board (sent to board subscribers)."""
        pass

    @ws_event
    def board_associated(self, event: BoardAssociatedEvent) -> BoardAssociatedEvent:
        """Fired when a board is associated with a session (broadcast to all clients)."""
        pass

    @ws_event
    def board_disassociated(self, event: BoardDisassociatedEvent) -> BoardDisassociatedEvent:
        """Fired when a board is disassociated from a session (broadcast to all clients)."""
        pass
