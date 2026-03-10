"""Kanban service layer with high-level board operations.

This module provides a higher-level API for kanban operations, wrapping the
low-level storage methods with business logic like:
- Creating boards with default columns
- Managing task placement across columns
- Querying full board state with all tasks

Usage:
    from core.kanban_service import KanbanService
    from core.async_storage import AsyncStorage

    storage = AsyncStorage()
    kanban = KanbanService(storage)

    # Create a board with default columns
    board_state = await kanban.create_board("Sprint 1")

    # Add a task to the board
    task = await kanban.create_task(
        board_id=board_state.board.id,
        title="Implement feature X",
        description="Add the new feature"
    )

    # Move task to a different column
    await kanban.move_task(task.id, to_column_id=done_column_id)

    # Get full board state
    board_state = await kanban.get_board_state(board_id)
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.async_storage import AsyncStorage


# =============================================================================
# Domain Models (service layer types)
# =============================================================================


@dataclass
class Task:
    """A task in the kanban system."""
    id: str
    title: str
    description: str
    resolution: str  # What was done to complete/resolve the task
    created_at: str
    updated_at: str


@dataclass
class Column:
    """A column in a kanban board."""
    id: str
    name: str
    position: int
    tasks: list[Task] = field(default_factory=list)


@dataclass
class Board:
    """A kanban board."""
    id: str
    name: str
    default_column_id: str
    created_at: str


@dataclass
class BoardState:
    """Full state of a board with its columns and tasks."""
    board: Board
    columns: list[Column]


# =============================================================================
# Default Column Configuration
# =============================================================================


DEFAULT_COLUMNS = [
    ("Backlog", 0),
    ("To Do", 1),
    ("In Progress", 2),
    ("Done", 3),
]


# =============================================================================
# Service Class
# =============================================================================


class KanbanService:
    """High-level service for kanban operations.

    Provides board/task management with automatic column creation,
    task placement, and board state queries.
    """

    def __init__(self, storage: AsyncStorage):
        """Initialize with async storage backend.

        Args:
            storage: AsyncStorage instance for persistence
        """
        self._storage = storage

    # -------------------------------------------------------------------------
    # Board Operations
    # -------------------------------------------------------------------------

    async def create_board(
        self,
        name: str,
        columns: list[tuple[str, int]] | None = None,
    ) -> BoardState:
        """Create a new board with columns.

        Args:
            name: Display name for the board
            columns: Optional list of (name, position) tuples. Defaults to
                     Backlog, To Do, In Progress, Done.

        Returns:
            BoardState with the new board and its columns
        """
        now = datetime.now(timezone.utc).isoformat()
        board_id = str(uuid.uuid4())

        # Use default columns if not specified
        column_defs = columns or DEFAULT_COLUMNS

        # Create columns first
        created_columns: list[Column] = []
        for col_name, position in column_defs:
            col_id = str(uuid.uuid4())
            column_data = {
                "id": col_id,
                "name": col_name,
                "position": position,
            }
            await self._storage._run_sync(
                self._storage._storage.save_column,
                json.dumps(column_data)
            )
            created_columns.append(Column(
                id=col_id,
                name=col_name,
                position=position,
                tasks=[],
            ))

        # Create the board with first column as default
        default_col_id = created_columns[0].id if created_columns else ""
        board_data = {
            "id": board_id,
            "name": name,
            "default_column_id": default_col_id,
            "created_at": now,
        }
        await self._storage._run_sync(
            self._storage._storage.save_board,
            json.dumps(board_data)
        )

        # Link columns to board via edges
        for col in created_columns:
            edge_id = str(uuid.uuid4())
            edge_data = {
                "id": edge_id,
                "source_type": "column",
                "source_id": col.id,
                "target_type": "board",
                "target_id": board_id,
                "relationship": "part_of",
                "position": col.position,
                "created_at": now,
            }
            await self._storage._run_sync(
                self._storage._storage.save_edge,
                json.dumps(edge_data)
            )

        board = Board(
            id=board_id,
            name=name,
            default_column_id=default_col_id,
            created_at=now,
        )

        return BoardState(board=board, columns=created_columns)

    async def get_board(self, board_id: str) -> Board | None:
        """Get a board by ID.

        Args:
            board_id: The board ID

        Returns:
            Board if found, None otherwise
        """
        result = await self._storage._run_sync(
            self._storage._storage.load_board,
            board_id
        )
        if not result:
            return None

        data = json.loads(result)
        return Board(
            id=data["id"],
            name=data["name"],
            default_column_id=data["default_column_id"],
            created_at=data["created_at"],
        )

    async def list_boards(self) -> list[Board]:
        """List all boards.

        Returns:
            List of all boards
        """
        result = await self._storage._run_sync(
            self._storage._storage.list_boards
        )
        boards_data = json.loads(result)
        return [
            Board(
                id=b["id"],
                name=b["name"],
                default_column_id=b["default_column_id"],
                created_at=b["created_at"],
            )
            for b in boards_data
        ]

    async def delete_board(self, board_id: str) -> bool:
        """Delete a board and its related edges.

        Note: This does NOT delete the tasks or columns themselves,
        only removes the board and its edges. Tasks become orphaned
        and can be reassigned to other boards.

        Args:
            board_id: The board ID to delete

        Returns:
            True if deleted, False if not found
        """
        board = await self.get_board(board_id)
        if not board:
            return False

        # Get and delete edges pointing to this board
        edges_json = await self._storage._run_sync(
            self._storage._storage.get_edges_by_target,
            "board", board_id
        )
        edges = json.loads(edges_json)
        for edge in edges:
            await self._storage._run_sync(
                self._storage._storage.delete_edge,
                edge["id"]
            )

        # Delete edges from this board (shouldn't be any, but just in case)
        edges_json = await self._storage._run_sync(
            self._storage._storage.get_edges_by_source,
            "board", board_id
        )
        edges = json.loads(edges_json)
        for edge in edges:
            await self._storage._run_sync(
                self._storage._storage.delete_edge,
                edge["id"]
            )

        # Delete the board itself
        await self._storage._run_sync(
            self._storage._storage.delete_board,
            board_id
        )
        return True

    async def get_board_state(self, board_id: str) -> BoardState | None:
        """Get full board state with columns and tasks.

        Returns the board with all its columns (ordered by position),
        each containing their tasks (ordered by position within column).

        Args:
            board_id: The board ID

        Returns:
            BoardState if found, None otherwise
        """
        board = await self.get_board(board_id)
        if not board:
            return None

        # Get columns for this board
        edges_json = await self._storage._run_sync(
            self._storage._storage.get_edges_by_target_and_relationship,
            "board", board_id, "part_of"
        )
        column_edges = json.loads(edges_json)

        # Sort by position and load columns
        column_edges.sort(key=lambda e: e.get("position", 0))

        columns: list[Column] = []
        for edge in column_edges:
            col_id = edge["source_id"]
            col_json = await self._storage._run_sync(
                self._storage._storage.load_column,
                col_id
            )
            if col_json:
                col_data = json.loads(col_json)

                # Get tasks in this column
                task_edges_json = await self._storage._run_sync(
                    self._storage._storage.get_edges_by_target_and_relationship,
                    "column", col_id, "in_column"
                )
                task_edges = json.loads(task_edges_json)
                task_edges.sort(key=lambda e: e.get("position", 0) or 0)

                tasks: list[Task] = []
                for task_edge in task_edges:
                    task_json = await self._storage._run_sync(
                        self._storage._storage.load_task,
                        task_edge["source_id"]
                    )
                    if task_json:
                        task_data = json.loads(task_json)
                        tasks.append(Task(
                            id=task_data["id"],
                            title=task_data["title"],
                            description=task_data["description"],
                            resolution=task_data.get("resolution", ""),
                            created_at=task_data["created_at"],
                            updated_at=task_data["updated_at"],
                        ))

                columns.append(Column(
                    id=col_data["id"],
                    name=col_data["name"],
                    position=col_data["position"],
                    tasks=tasks,
                ))

        return BoardState(board=board, columns=columns)

    # -------------------------------------------------------------------------
    # Task Operations
    # -------------------------------------------------------------------------

    async def create_task(
        self,
        board_id: str,
        title: str,
        description: str = "",
        column_id: str | None = None,
        position: int | None = None,
    ) -> Task | None:
        """Create a new task on a board.

        Args:
            board_id: The board to add the task to
            title: Task title
            description: Task description (optional)
            column_id: Column to place task in. Defaults to board's default column.
            position: Position in column. Defaults to end of column.

        Returns:
            The created Task, or None if board not found
        """
        board = await self.get_board(board_id)
        if not board:
            return None

        now = datetime.now(timezone.utc).isoformat()
        task_id = str(uuid.uuid4())

        # Determine target column
        target_col_id = column_id or board.default_column_id

        # Determine position (default to end)
        if position is None:
            task_edges_json = await self._storage._run_sync(
                self._storage._storage.get_edges_by_target_and_relationship,
                "column", target_col_id, "in_column"
            )
            task_edges = json.loads(task_edges_json)
            position = len(task_edges)

        # Create the task
        task_data = {
            "id": task_id,
            "title": title,
            "description": description,
            "resolution": "",
            "created_at": now,
            "updated_at": now,
        }
        await self._storage._run_sync(
            self._storage._storage.save_task,
            json.dumps(task_data)
        )

        # Create tracked_on edge (task -> board)
        await self._storage._run_sync(
            self._storage._storage.save_edge,
            json.dumps({
                "id": str(uuid.uuid4()),
                "source_type": "task",
                "source_id": task_id,
                "target_type": "board",
                "target_id": board_id,
                "relationship": "tracked_on",
                "position": None,
                "created_at": now,
            })
        )

        # Create in_column edge (task -> column)
        await self._storage._run_sync(
            self._storage._storage.save_edge,
            json.dumps({
                "id": str(uuid.uuid4()),
                "source_type": "task",
                "source_id": task_id,
                "target_type": "column",
                "target_id": target_col_id,
                "relationship": "in_column",
                "position": position,
                "created_at": now,
            })
        )

        return Task(
            id=task_id,
            title=title,
            description=description,
            created_at=now,
            updated_at=now,
        )

    async def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID.

        Args:
            task_id: The task ID

        Returns:
            Task if found, None otherwise
        """
        result = await self._storage._run_sync(
            self._storage._storage.load_task,
            task_id
        )
        if not result:
            return None

        data = json.loads(result)
        return Task(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            resolution=data.get("resolution", ""),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )

    async def update_task(
        self,
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        resolution: str | None = None,
    ) -> Task | None:
        """Update a task's title, description, and/or resolution.

        Args:
            task_id: The task ID
            title: New title (optional)
            description: New description (optional)
            resolution: What was done to complete/resolve the task (optional)

        Returns:
            Updated Task if found, None otherwise
        """
        task = await self.get_task(task_id)
        if not task:
            return None

        now = datetime.now(timezone.utc).isoformat()

        task_data = {
            "id": task_id,
            "title": title if title is not None else task.title,
            "description": description if description is not None else task.description,
            "resolution": resolution if resolution is not None else task.resolution,
            "created_at": task.created_at,
            "updated_at": now,
        }
        await self._storage._run_sync(
            self._storage._storage.save_task,
            json.dumps(task_data)
        )

        return Task(
            id=task_id,
            title=task_data["title"],
            description=task_data["description"],
            resolution=task_data["resolution"],
            created_at=task.created_at,
            updated_at=now,
        )

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task and its edges.

        Args:
            task_id: The task ID to delete

        Returns:
            True if deleted, False if not found
        """
        task = await self.get_task(task_id)
        if not task:
            return False

        # Delete edges from this task
        edges_json = await self._storage._run_sync(
            self._storage._storage.get_edges_by_source,
            "task", task_id
        )
        edges = json.loads(edges_json)
        for edge in edges:
            await self._storage._run_sync(
                self._storage._storage.delete_edge,
                edge["id"]
            )

        # Delete the task
        await self._storage._run_sync(
            self._storage._storage.delete_task,
            task_id
        )
        return True

    async def move_task(
        self,
        task_id: str,
        to_column_id: str,
        position: int | None = None,
    ) -> bool:
        """Move a task to a different column.

        Args:
            task_id: The task to move
            to_column_id: Target column ID
            position: Position in target column. Defaults to end.

        Returns:
            True if moved, False if task not found
        """
        task = await self.get_task(task_id)
        if not task:
            return False

        now = datetime.now(timezone.utc).isoformat()

        # Find the existing in_column edge
        edges_json = await self._storage._run_sync(
            self._storage._storage.get_edges_by_source_and_relationship,
            "task", task_id, "in_column"
        )
        edges = json.loads(edges_json)

        if not edges:
            # Task has no column placement, create new edge
            edge_id = str(uuid.uuid4())
        else:
            # Update existing edge
            edge_id = edges[0]["id"]

        # Determine position
        if position is None:
            task_edges_json = await self._storage._run_sync(
                self._storage._storage.get_edges_by_target_and_relationship,
                "column", to_column_id, "in_column"
            )
            task_edges = json.loads(task_edges_json)
            position = len(task_edges)

        # Save the updated edge
        await self._storage._run_sync(
            self._storage._storage.save_edge,
            json.dumps({
                "id": edge_id,
                "source_type": "task",
                "source_id": task_id,
                "target_type": "column",
                "target_id": to_column_id,
                "relationship": "in_column",
                "position": position,
                "created_at": now,
            })
        )

        return True

    async def reorder_tasks(
        self,
        column_id: str,
        task_ids: list[str],
    ) -> bool:
        """Reorder tasks within a column.

        Updates the position of each task to match the provided order.

        Args:
            column_id: The column containing the tasks
            task_ids: List of task IDs in desired order

        Returns:
            True if reordered, False if column has mismatched tasks
        """
        now = datetime.now(timezone.utc).isoformat()

        # Get current task edges in column
        edges_json = await self._storage._run_sync(
            self._storage._storage.get_edges_by_target_and_relationship,
            "column", column_id, "in_column"
        )
        edges = json.loads(edges_json)

        # Build lookup of task_id -> edge
        edge_by_task = {e["source_id"]: e for e in edges}

        # Verify all task_ids are in column
        for task_id in task_ids:
            if task_id not in edge_by_task:
                return False

        # Update positions
        for position, task_id in enumerate(task_ids):
            edge = edge_by_task[task_id]
            edge["position"] = position
            edge["created_at"] = now
            await self._storage._run_sync(
                self._storage._storage.save_edge,
                json.dumps(edge)
            )

        return True

    # -------------------------------------------------------------------------
    # Column Operations
    # -------------------------------------------------------------------------

    async def add_column(
        self,
        board_id: str,
        name: str,
        position: int | None = None,
    ) -> Column | None:
        """Add a new column to a board.

        Args:
            board_id: The board to add the column to
            name: Column name
            position: Position in board. Defaults to end.

        Returns:
            The created Column, or None if board not found
        """
        board = await self.get_board(board_id)
        if not board:
            return None

        now = datetime.now(timezone.utc).isoformat()
        col_id = str(uuid.uuid4())

        # Determine position
        if position is None:
            edges_json = await self._storage._run_sync(
                self._storage._storage.get_edges_by_target_and_relationship,
                "board", board_id, "part_of"
            )
            edges = json.loads(edges_json)
            position = len(edges)

        # Create column
        await self._storage._run_sync(
            self._storage._storage.save_column,
            json.dumps({
                "id": col_id,
                "name": name,
                "position": position,
            })
        )

        # Create part_of edge (column -> board)
        await self._storage._run_sync(
            self._storage._storage.save_edge,
            json.dumps({
                "id": str(uuid.uuid4()),
                "source_type": "column",
                "source_id": col_id,
                "target_type": "board",
                "target_id": board_id,
                "relationship": "part_of",
                "position": position,
                "created_at": now,
            })
        )

        return Column(
            id=col_id,
            name=name,
            position=position,
            tasks=[],
        )

    async def delete_column(self, column_id: str, move_tasks_to: str | None = None) -> bool:
        """Delete a column from a board.

        Args:
            column_id: The column ID to delete
            move_tasks_to: Optional column ID to move tasks to.
                          If None, tasks in this column become orphaned.

        Returns:
            True if deleted, False if not found
        """
        col_json = await self._storage._run_sync(
            self._storage._storage.load_column,
            column_id
        )
        if not col_json:
            return False

        # Move tasks if destination specified
        if move_tasks_to:
            task_edges_json = await self._storage._run_sync(
                self._storage._storage.get_edges_by_target_and_relationship,
                "column", column_id, "in_column"
            )
            task_edges = json.loads(task_edges_json)

            for edge in task_edges:
                await self.move_task(edge["source_id"], move_tasks_to)
        else:
            # Delete in_column edges pointing to this column
            task_edges_json = await self._storage._run_sync(
                self._storage._storage.get_edges_by_target_and_relationship,
                "column", column_id, "in_column"
            )
            task_edges = json.loads(task_edges_json)
            for edge in task_edges:
                await self._storage._run_sync(
                    self._storage._storage.delete_edge,
                    edge["id"]
                )

        # Delete the part_of edge (column -> board)
        edges_json = await self._storage._run_sync(
            self._storage._storage.get_edges_by_source_and_relationship,
            "column", column_id, "part_of"
        )
        edges = json.loads(edges_json)
        for edge in edges:
            await self._storage._run_sync(
                self._storage._storage.delete_edge,
                edge["id"]
            )

        # Delete the column
        await self._storage._run_sync(
            self._storage._storage.delete_column,
            column_id
        )
        return True

    # -------------------------------------------------------------------------
    # Session-Board Association Operations
    # -------------------------------------------------------------------------

    async def associate_board_with_session(
        self,
        board_id: str,
        session_id: str,
        role: str = "primary",
        created_by: str = "user",
        inherited_from: str | None = None,
    ) -> "SessionBoardAssociation":
        """Associate a board with a session.

        Args:
            board_id: The board to associate
            session_id: The session to associate with
            role: Role of this association (primary, reference, archive)
            created_by: Who created this association (user, llm, fork)
            inherited_from: Parent session ID if inherited via fork

        Returns:
            The created SessionBoardAssociation
        """
        now = datetime.now(timezone.utc).isoformat()
        assoc_id = str(uuid.uuid4())

        assoc_data = {
            "id": assoc_id,
            "session_id": session_id,
            "board_id": board_id,
            "role": role,
            "created_at": now,
            "created_by": created_by,
            "inherited_from": inherited_from,
        }

        await self._storage._run_sync(
            self._storage._storage.save_session_board_association,
            json.dumps(assoc_data)
        )

        return SessionBoardAssociation(
            id=assoc_id,
            session_id=session_id,
            board_id=board_id,
            role=role,
            created_at=now,
            created_by=created_by,
            inherited_from=inherited_from,
        )

    async def dissociate_board_from_session(
        self,
        board_id: str,
        session_id: str,
    ) -> bool:
        """Remove a board association from a session.

        Args:
            board_id: The board to dissociate
            session_id: The session to dissociate from

        Returns:
            True if an association was removed, False if not found
        """
        associations = await self.get_associations_for_session(session_id)
        for assoc in associations:
            if assoc.board_id == board_id:
                await self._storage._run_sync(
                    self._storage._storage.delete_session_board_association,
                    assoc.id
                )
                return True
        return False

    async def get_associations_for_session(
        self,
        session_id: str,
    ) -> list["SessionBoardAssociation"]:
        """Get all board associations for a session.

        Args:
            session_id: The session ID

        Returns:
            List of SessionBoardAssociation objects
        """
        result = await self._storage._run_sync(
            self._storage._storage.get_board_associations_for_session,
            session_id
        )
        assoc_data_list = json.loads(result)
        return [
            SessionBoardAssociation(
                id=a["id"],
                session_id=a["session_id"],
                board_id=a["board_id"],
                role=a["role"],
                created_at=a["created_at"],
                created_by=a["created_by"],
                inherited_from=a.get("inherited_from"),
            )
            for a in assoc_data_list
        ]

    async def get_boards_for_session(
        self,
        session_id: str,
    ) -> list[tuple["SessionBoardAssociation", Board]]:
        """Get all boards associated with a session.

        Args:
            session_id: The session ID

        Returns:
            List of (association, board) tuples
        """
        associations = await self.get_associations_for_session(session_id)
        result: list[tuple[SessionBoardAssociation, Board]] = []

        for assoc in associations:
            board = await self.get_board(assoc.board_id)
            if board:
                result.append((assoc, board))

        return result

    async def get_sessions_for_board(
        self,
        board_id: str,
    ) -> list["SessionBoardAssociation"]:
        """Get all session associations for a board.

        Args:
            board_id: The board ID

        Returns:
            List of SessionBoardAssociation objects
        """
        # Get all associations and filter by board_id
        result = await self._storage._run_sync(
            self._storage._storage.list_session_board_associations
        )
        assoc_data_list = json.loads(result)
        return [
            SessionBoardAssociation(
                id=a["id"],
                session_id=a["session_id"],
                board_id=a["board_id"],
                role=a["role"],
                created_at=a["created_at"],
                created_by=a["created_by"],
                inherited_from=a.get("inherited_from"),
            )
            for a in assoc_data_list
            if a["board_id"] == board_id
        ]

    async def create_board_for_session(
        self,
        session_id: str,
        name: str,
        columns: list[tuple[str, int]] | None = None,
    ) -> tuple["SessionBoardAssociation", BoardState]:
        """Create a new board and associate it with a session.

        Args:
            session_id: The session to associate with
            name: Display name for the board
            columns: Optional list of (name, position) tuples

        Returns:
            Tuple of (association, board_state)
        """
        board_state = await self.create_board(name, columns)
        assoc = await self.associate_board_with_session(
            board_id=board_state.board.id,
            session_id=session_id,
            role="primary",
            created_by="user",
        )
        return assoc, board_state

    async def inherit_board_associations(
        self,
        parent_session_id: str,
        child_session_id: str,
    ) -> list["SessionBoardAssociation"]:
        """Copy board associations from parent to child session.

        Called during fork to inherit parent's kanban boards.

        Args:
            parent_session_id: The parent session to copy from
            child_session_id: The child session to copy to

        Returns:
            List of new associations created for the child
        """
        parent_assocs = await self.get_associations_for_session(parent_session_id)
        child_assocs: list[SessionBoardAssociation] = []

        for assoc in parent_assocs:
            child_assoc = await self.associate_board_with_session(
                board_id=assoc.board_id,
                session_id=child_session_id,
                role=assoc.role,
                created_by="fork",
                inherited_from=parent_session_id,
            )
            child_assocs.append(child_assoc)

        return child_assocs


# =============================================================================
# Session-Board Association Data Class
# =============================================================================


@dataclass
class SessionBoardAssociation:
    """Association between a session and a kanban board."""
    id: str
    session_id: str
    board_id: str
    role: str  # "primary", "reference", "archive"
    created_at: str
    created_by: str  # "user", "llm", "fork"
    inherited_from: Optional[str] = None  # Parent session ID if inherited
