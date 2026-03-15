"""Kanban domain plugin.

Provides persistent kanban board functionality with session-scoped boards.
"""

from typing import Any, TYPE_CHECKING
import os

from ..base import DomainEvent, DecoratedStatefulDomain, ToolResult
from ..decorators import llm_callable, Param
from ..storage import JsonFileStorage
from .. import PluginLogger
from .models import Board, Task, Column, SessionBoardAssociation
from .events import (
    BoardCreatedPayload,
    BoardDeletedPayload,
    TaskCreatedPayload,
    TaskUpdatedPayload,
    TaskDeletedPayload,
    TaskMovedPayload,
    ColumnDeletedPayload,
    BoardStateSyncPayload,
    BoardAssociatedPayload,
    BoardDisassociatedPayload,
)

if TYPE_CHECKING:
    from session import Session

# Plugin logger
log = PluginLogger("kanban")


# Global in-memory cache for boards and associations
_boards: dict[str, Board] = {}  # board_id -> Board
_associations: dict[str, SessionBoardAssociation] = {}  # assoc_id -> Association
_boards_loaded: bool = False

# Persistent storage
_board_storage: JsonFileStorage | None = None
_assoc_storage: JsonFileStorage | None = None


def _get_board_storage() -> JsonFileStorage:
    """Get the persistent storage for boards."""
    global _board_storage
    if _board_storage is None:
        _board_storage = JsonFileStorage("kanban/boards")
    return _board_storage


def _get_assoc_storage() -> JsonFileStorage:
    """Get the persistent storage for associations."""
    global _assoc_storage
    if _assoc_storage is None:
        _assoc_storage = JsonFileStorage("kanban/associations")
    return _assoc_storage


async def _load_all_data() -> None:
    """Load all boards and associations from storage."""
    global _boards_loaded
    if _boards_loaded:
        return

    # Load boards
    board_storage = _get_board_storage()
    board_ids = await board_storage.list_keys()
    for board_id in board_ids:
        board_data = await board_storage.load(board_id)
        if board_data:
            _boards[board_id] = Board.from_dict(board_data)

    # Load associations
    assoc_storage = _get_assoc_storage()
    assoc_ids = await assoc_storage.list_keys()
    for assoc_id in assoc_ids:
        assoc_data = await assoc_storage.load(assoc_id)
        if assoc_data:
            _associations[assoc_id] = SessionBoardAssociation.from_dict(assoc_data)

    _boards_loaded = True


async def _save_board(board: Board) -> None:
    """Save a single board to storage."""
    storage = _get_board_storage()
    await storage.save(board.id, board.to_dict())


async def _delete_board_file(board_id: str) -> None:
    """Delete a board's storage file."""
    storage = _get_board_storage()
    await storage.delete(board_id)


async def _save_association(assoc: SessionBoardAssociation) -> None:
    """Save an association to storage."""
    storage = _get_assoc_storage()
    await storage.save(assoc.id, assoc.to_dict())


async def _delete_association_file(assoc_id: str) -> None:
    """Delete an association's storage file."""
    storage = _get_assoc_storage()
    await storage.delete(assoc_id)


def _is_uuid(s: str) -> bool:
    """Check if a string looks like a UUID."""
    return len(s) == 36 and s.count('-') == 4


class KanbanDomain(DecoratedStatefulDomain):
    """Kanban domain providing persistent task boards.

    Tools:
        - kanban_get_boards: Get boards for current session
        - kanban_create_board: Create a new board
        - kanban_create_task: Create a new task
        - kanban_update_task: Update a task
        - kanban_move_task: Move task between columns
        - kanban_delete_task: Delete a task
        - kanban_list_tasks: List tasks on a board
        - kanban_get_board_state: Get full board state
        - kanban_delete_column: Delete a column

    Events emitted:
        - board_created: New board created
        - board_deleted: Board deleted
        - task_created: Task created
        - task_updated: Task updated
        - task_deleted: Task deleted
        - task_moved: Task moved between columns
        - column_deleted: Column deleted
        - board_state_sync: Full state sync (reconnection)
    """

    @property
    def id(self) -> str:
        return "kanban"

    @property
    def name(self) -> str:
        return "Kanban"

    @property
    def version(self) -> str:
        return "0.1.0"

    def get_prompt(self) -> str:
        """Load prompt from prompt.md file."""
        prompt_path = os.path.join(os.path.dirname(__file__), "prompt.md")
        try:
            with open(prompt_path, "r") as f:
                return f.read()
        except FileNotFoundError:
            return """## Kanban Board Tools

You can create and manage kanban boards using the kanban_* tools.
Boards are session-scoped and persist across turns."""

    def get_ui_config(self) -> dict | None:
        """Return UI configuration for the kanban domain."""
        return {
            "components": [
                {
                    "name": "KanbanBoard",
                    "path": "plugins/kanban/ui/KanbanBoard.tsx",
                    "description": "Interactive kanban board",
                },
            ],
            "tabs": [
                {
                    "id": "kanban",
                    "label": "Kanban",
                    "icon": "📋",
                    "component": "KanbanBoard",
                },
            ],
        }

    async def _get_boards_for_session(self, session_id: str) -> list[tuple[SessionBoardAssociation, Board]]:
        """Get all boards associated with a session."""
        await _load_all_data()
        result = []
        for assoc in _associations.values():
            if assoc.session_id == session_id:
                board = _boards.get(assoc.board_id)
                if board:
                    result.append((assoc, board))
        return result

    async def _get_primary_board(self, session_id: str) -> Board | None:
        """Get the primary board for a session."""
        boards = await self._get_boards_for_session(session_id)
        if boards:
            return boards[0][1]
        return None

    async def _resolve_task(self, task_ref: str, session_id: str) -> tuple[Task | None, Board | None]:
        """Resolve a task title or ID to a Task and its Board."""
        boards = await self._get_boards_for_session(session_id)

        # If it looks like a UUID, search by ID
        if _is_uuid(task_ref):
            for _, board in boards:
                task = board.get_task_by_id(task_ref)
                if task:
                    return task, board
        else:
            # Search by title (case-insensitive)
            for _, board in boards:
                task = board.get_task_by_title(task_ref)
                if task:
                    return task, board
            # Also try prefix ID match
            for _, board in boards:
                task = board.get_task_by_id(task_ref)
                if task:
                    return task, board

        return None, None

    async def _resolve_column(self, column_ref: str, session_id: str) -> tuple[Column | None, Board | None]:
        """Resolve a column name or ID to a Column and its Board."""
        boards = await self._get_boards_for_session(session_id)

        # If it looks like a UUID, search by ID
        if _is_uuid(column_ref):
            for _, board in boards:
                col = board.get_column_by_id(column_ref)
                if col:
                    return col, board
        else:
            # Search by name (case-insensitive)
            for _, board in boards:
                col = board.get_column_by_name(column_ref)
                if col:
                    return col, board
            # Also try prefix ID match
            for _, board in boards:
                col = board.get_column_by_id(column_ref)
                if col:
                    return col, board

        return None, None

    # --- LLM-callable tools ---

    @llm_callable(
        description="""Get kanban boards associated with the current session.

Returns a list of boards linked to this session, including any boards inherited
from parent sessions on fork. Use this to discover available boards before
creating or managing tasks.

If no boards exist, you can create one with kanban_create_board."""
    )
    async def kanban_get_boards(self, session: "Session" = None) -> ToolResult:
        """Get boards for the current session."""
        await _load_all_data()

        boards = await self._get_boards_for_session(session.id)

        if not boards:
            return ToolResult(
                "No boards associated with this session. Use kanban_create_board to create one."
            )

        result_lines = [f"Found {len(boards)} board(s) for this session:\n"]
        for assoc, board in boards:
            inherited = " (inherited)" if assoc.inherited_from else ""
            result_lines.append(f"- {board.name}{inherited}")
            result_lines.append(f"  ID: {board.id}")
            result_lines.append(f"  Role: {assoc.role or 'primary'}")
            result_lines.append("")

        # Emit sync event for UI
        event = DomainEvent(
            type="board_state_sync",
            source_domain=self.id,
            payload=BoardStateSyncPayload(
                boards=[b.to_dict() for _, b in boards],
                associations=[a.to_dict() for a, _ in boards],
            ),
            target_session=session.id,
        )

        return ToolResult("\n".join(result_lines), events=[event])

    @llm_callable(
        description="""Create a new kanban board and associate it with the current session.

Creates a board with default columns (Backlog, To Do, In Progress, Done).
The board is automatically associated with this session so tasks can be
added to it immediately.

Use this when:
- No board exists for the session yet
- Starting a new project or feature that needs its own board""",
        params={
            "name": Param(str, "Display name for the board (e.g., 'Feature X Tasks')"),
        }
    )
    async def kanban_create_board(self, name: str, session: "Session" = None) -> ToolResult:
        """Create a new board and associate with session."""
        await _load_all_data()

        name = name.strip()
        if not name:
            log.warning("Board creation failed: no name provided", session_id=session.id)
            return ToolResult("Error: Board name is required", is_error=True)

        # Create the board
        board = Board.create(name)
        _boards[board.id] = board
        await _save_board(board)
        log.info(f"Created board: {board.name}", session_id=session.id, details={"board_id": board.id})

        # Create association
        assoc = SessionBoardAssociation.create(
            session_id=session.id,
            board_id=board.id,
            role="primary",
            created_by="llm",
        )
        _associations[assoc.id] = assoc
        await _save_association(assoc)

        columns = ", ".join(col.name for col in board.columns)

        event = DomainEvent(
            type="board_created",
            source_domain=self.id,
            payload=BoardCreatedPayload(
                board_id=board.id,
                name=board.name,
                board=board.to_dict(),
            ),
            target_session=session.id,
        )

        return ToolResult(
            f"Created board '{board.name}' with ID {board.id}\n"
            f"Columns: {columns}\n"
            f"Default column: {board.default_column_id[:8]}...",
            events=[event],
        )

    @llm_callable(
        description="""Create a new task on a kanban board.

If no board_id is specified, uses the primary board for this session.
If no column_id is specified, the task is added to the default column
(usually 'Backlog' or the first column).

Use this when:
- Breaking down work into trackable tasks
- The user mentions something that should be tracked
- Adding items to a sprint or backlog""",
        params={
            "title": Param(str, "Short title for the task (max 100 chars)"),
            "description": Param(str, "Optional detailed description of the task", required=False),
            "board_id": Param(str, "Board ID to add the task to. If omitted, uses the session's primary board.", required=False),
            "column_id": Param(str, "Column ID to place the task in. If omitted, uses the board's default column.", required=False),
        }
    )
    async def kanban_create_task(
        self,
        title: str,
        description: str = "",
        board_id: str | None = None,
        column_id: str | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """Create a new task on a board."""
        await _load_all_data()

        title = title.strip()
        if not title:
            return ToolResult("Error: Task title is required", is_error=True)

        # Get the board
        if board_id:
            board = _boards.get(board_id)
            if not board:
                return ToolResult(f"Error: Board {board_id} not found", is_error=True)
        else:
            board = await self._get_primary_board(session.id)
            if not board:
                return ToolResult(
                    "No boards associated with this session. Use kanban_create_board first.",
                    is_error=True,
                )

        # Determine target column
        if column_id:
            col = board.get_column_by_id(column_id) or board.get_column_by_name(column_id)
            if not col:
                return ToolResult(f"Error: Column {column_id} not found", is_error=True)
            target_col = col
        else:
            target_col = board.get_column_by_id(board.default_column_id)
            if not target_col and board.columns:
                target_col = board.columns[0]

        if not target_col:
            return ToolResult("Error: No columns in board", is_error=True)

        # Create the task
        task = Task.create(title, description.strip())
        board.tasks[task.id] = task
        target_col.task_ids.append(task.id)

        await _save_board(board)
        log.info(
            f"Created task: {task.title}",
            session_id=session.id,
            details={"task_id": task.id, "board_id": board.id, "column": target_col.name}
        )

        event = DomainEvent(
            type="task_created",
            source_domain=self.id,
            payload=TaskCreatedPayload(
                board_id=board.id,
                task=task.to_dict(),
                column_id=target_col.id,
                position=len(target_col.task_ids) - 1,
            ),
            target_session=session.id,
        )

        return ToolResult(
            f"Created task '{task.title}'\n"
            f"ID: {task.id}\n"
            f"Column: {target_col.name}\n"
            f"Board: {board.name}",
            events=[event],
        )

    @llm_callable(
        description="""Update an existing task's title, description, or resolution.

Only modifies the fields provided; other fields remain unchanged.

The resolution field documents what was done to complete/resolve the task.
Write the resolution when moving a task to Done to capture the outcome.

Use this when:
- Renaming a task
- Adding or editing a task's description
- Documenting task completion (write the resolution)
- Clarifying task details""",
        params={
            "task_id": Param(str, "ID of the task to update"),
            "title": Param(str, "New title for the task", required=False),
            "description": Param(str, "New description for the task", required=False),
            "resolution": Param(str, "What was done to complete/resolve this task. Write this when moving to Done.", required=False),
        }
    )
    async def kanban_update_task(
        self,
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        resolution: str | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """Update an existing task."""
        await _load_all_data()

        task_id = task_id.strip()
        if not task_id:
            return ToolResult("Error: task_id is required", is_error=True)

        if title is None and description is None and resolution is None:
            return ToolResult(
                "Error: At least one of title, description, or resolution must be provided",
                is_error=True,
            )

        task, board = await self._resolve_task(task_id, session.id)
        if not task or not board:
            return ToolResult(f"Error: Task {task_id} not found", is_error=True)

        # Update fields
        if title is not None:
            task.title = title.strip()
        if description is not None:
            task.description = description.strip()
        if resolution is not None:
            task.resolution = resolution.strip()

        from .models import _now
        task.updated_at = _now()

        await _save_board(board)

        event = DomainEvent(
            type="task_updated",
            source_domain=self.id,
            payload=TaskUpdatedPayload(
                board_id=board.id,
                task=task.to_dict(),
            ),
            target_session=session.id,
        )

        result = f"Updated task '{task.title}' (ID: {task.id})"
        if resolution:
            result += f"\nResolution: {task.resolution}"

        return ToolResult(result, events=[event])

    @llm_callable(
        description="""Move a task to a different column.

Common column names are 'Backlog', 'To Do', 'In Progress', and 'Done'.
You can use either names or IDs for both task and column.

Use this when:
- Starting work on a task (move to 'In Progress')
- Completing a task (move to 'Done')
- Reprioritizing work""",
        params={
            "task": Param(str, "Task title (e.g., 'ctrl-enter') or task ID"),
            "to_column": Param(str, "Column name (e.g., 'Done', 'In Progress') or column ID"),
            "position": Param(int, "Optional position within the column (0 = top)", required=False),
        }
    )
    async def kanban_move_task(
        self,
        task: str,
        to_column: str,
        position: int | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """Move a task to a different column."""
        await _load_all_data()

        task_ref = task.strip()
        to_column_ref = to_column.strip()

        if not task_ref:
            return ToolResult("Error: task is required", is_error=True)
        if not to_column_ref:
            return ToolResult("Error: to_column is required", is_error=True)

        # Resolve task
        task_obj, board = await self._resolve_task(task_ref, session.id)
        if not task_obj or not board:
            return ToolResult(f"Error: Task '{task_ref}' not found", is_error=True)

        # Resolve column
        to_col = board.get_column_by_name(to_column_ref) or board.get_column_by_id(to_column_ref)
        if not to_col:
            return ToolResult(f"Error: Column '{to_column_ref}' not found", is_error=True)

        # Find current column and remove task
        from_col = board.find_task_column(task_obj.id)
        from_col_id = from_col.id if from_col else ""
        if from_col:
            from_col.task_ids = [tid for tid in from_col.task_ids if tid != task_obj.id]

        # Add to new column
        if position is not None and 0 <= position < len(to_col.task_ids):
            to_col.task_ids.insert(position, task_obj.id)
        else:
            to_col.task_ids.append(task_obj.id)
            position = len(to_col.task_ids) - 1

        await _save_board(board)

        event = DomainEvent(
            type="task_moved",
            source_domain=self.id,
            payload=TaskMovedPayload(
                board_id=board.id,
                task_id=task_obj.id,
                from_column_id=from_col_id,
                to_column_id=to_col.id,
                new_position=position,
            ),
            target_session=session.id,
        )

        return ToolResult(
            f"Moved task '{task_obj.title}' to column '{to_col.name}'",
            events=[event],
        )

    @llm_callable(
        description="""Delete a task from a board.

Permanently removes the task. Use with caution.

Use this when:
- A task is no longer relevant
- Cleaning up duplicate tasks
- The user explicitly asks to remove a task""",
        params={
            "task_id": Param(str, "ID of the task to delete"),
        }
    )
    async def kanban_delete_task(
        self,
        task_id: str,
        session: "Session" = None,
    ) -> ToolResult:
        """Delete a task."""
        await _load_all_data()

        task_id = task_id.strip()
        if not task_id:
            return ToolResult("Error: task_id is required", is_error=True)

        task, board = await self._resolve_task(task_id, session.id)
        if not task or not board:
            return ToolResult(f"Error: Task {task_id} not found", is_error=True)

        # Remove from column
        col = board.find_task_column(task.id)
        if col:
            col.task_ids = [tid for tid in col.task_ids if tid != task.id]

        # Remove from board
        del board.tasks[task.id]

        await _save_board(board)

        event = DomainEvent(
            type="task_deleted",
            source_domain=self.id,
            payload=TaskDeletedPayload(
                board_id=board.id,
                task_id=task.id,
            ),
            target_session=session.id,
        )

        return ToolResult(f"Deleted task '{task.title}'", events=[event])

    @llm_callable(
        description="""List tasks from a board, optionally filtered by column.

Returns tasks with their IDs, titles, descriptions, and current column.
Useful for getting an overview or finding specific tasks.

If no board_id is specified, uses the primary board for this session.""",
        params={
            "board_id": Param(str, "Board ID to list tasks from. If omitted, uses session's primary board.", required=False),
            "column_name": Param(str, "Optional column name to filter by (e.g., 'In Progress', 'Done')", required=False),
        }
    )
    async def kanban_list_tasks(
        self,
        board_id: str | None = None,
        column_name: str | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """List tasks from a board."""
        await _load_all_data()

        # Get the board
        if board_id:
            board = _boards.get(board_id)
            if not board:
                return ToolResult(f"Error: Board {board_id} not found", is_error=True)
        else:
            board = await self._get_primary_board(session.id)
            if not board:
                return ToolResult(
                    "No boards associated with this session. Use kanban_create_board first.",
                    is_error=True,
                )

        result_lines = [f"Tasks on board '{board.name}':\n"]

        for column in board.columns:
            # Filter by column name if specified
            if column_name and column.name.lower() != column_name.lower():
                continue

            result_lines.append(f"## {column.name} ({len(column.task_ids)} tasks)")

            if not column.task_ids:
                result_lines.append("  (empty)")
            else:
                for task_id in column.task_ids:
                    task = board.tasks.get(task_id)
                    if task:
                        desc_preview = task.description[:50] + "..." if len(task.description) > 50 else task.description
                        result_lines.append(f"  - [{task.id[:8]}] {task.title}")
                        if desc_preview:
                            result_lines.append(f"    {desc_preview}")

            result_lines.append("")

        return ToolResult("\n".join(result_lines))

    @llm_callable(
        description="""Get the full state of a kanban board.

Returns the board with all its columns and tasks, organized by column.
Useful for getting a complete view of the board structure.

If no board_id is specified, uses the primary board for this session.""",
        params={
            "board_id": Param(str, "Board ID. If omitted, uses session's primary board.", required=False),
        }
    )
    async def kanban_get_board_state(
        self,
        board_id: str | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """Get full board state."""
        await _load_all_data()

        # Get the board
        if board_id:
            board = _boards.get(board_id)
            if not board:
                return ToolResult(f"Error: Board {board_id} not found", is_error=True)
        else:
            board = await self._get_primary_board(session.id)
            if not board:
                return ToolResult(
                    "No boards associated with this session. Use kanban_create_board first.",
                    is_error=True,
                )

        result_lines = [
            f"# Board: {board.name}",
            f"ID: {board.id}",
            f"Default Column: {board.default_column_id[:8]}...",
            f"Created: {board.created_at}",
            "",
            "## Columns",
            ""
        ]

        for column in board.columns:
            result_lines.append(f"### {column.name} (ID: {column.id[:8]}...)")
            result_lines.append(f"Position: {column.position}")
            result_lines.append(f"Tasks: {len(column.task_ids)}")

            for task_id in column.task_ids:
                task = board.tasks.get(task_id)
                if task:
                    result_lines.append(f"  - {task.title} (ID: {task.id[:8]}...)")
                    if task.description:
                        result_lines.append(f"    {task.description[:80]}...")

            result_lines.append("")

        # Emit sync event for UI
        boards = await self._get_boards_for_session(session.id)
        event = DomainEvent(
            type="board_state_sync",
            source_domain=self.id,
            payload=BoardStateSyncPayload(
                boards=[b.to_dict() for _, b in boards],
                associations=[a.to_dict() for a, _ in boards],
            ),
            target_session=session.id,
        )

        return ToolResult("\n".join(result_lines), events=[event])

    @llm_callable(
        description="""Delete a column from a kanban board.

Removes a column. If the column has tasks, you can optionally move them
to another column; otherwise they become orphaned.

Use this when:
- Simplifying a board (e.g., removing unused 'To Do' or 'In Progress' columns)
- Reorganizing board structure""",
        params={
            "column": Param(str, "Column name (e.g., 'To Do') or column ID"),
            "move_tasks_to": Param(str, "Optional: column name or ID to move tasks to before deleting", required=False),
        }
    )
    async def kanban_delete_column(
        self,
        column: str,
        move_tasks_to: str | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """Delete a column from a board."""
        await _load_all_data()

        column_ref = column.strip()
        if not column_ref:
            return ToolResult("Error: column is required", is_error=True)

        col, board = await self._resolve_column(column_ref, session.id)
        if not col or not board:
            return ToolResult(f"Error: Column '{column_ref}' not found", is_error=True)

        # Resolve move_tasks_to column
        move_to_col = None
        if move_tasks_to:
            move_to_col = board.get_column_by_name(move_tasks_to) or board.get_column_by_id(move_tasks_to)
            if not move_to_col:
                return ToolResult(f"Error: Target column '{move_tasks_to}' not found", is_error=True)

        # Move tasks if needed
        if move_to_col and col.task_ids:
            move_to_col.task_ids.extend(col.task_ids)

        # Remove column from board
        board.columns = [c for c in board.columns if c.id != col.id]

        await _save_board(board)

        event = DomainEvent(
            type="column_deleted",
            source_domain=self.id,
            payload=ColumnDeletedPayload(
                board_id=board.id,
                column_id=col.id,
                tasks_moved_to=move_to_col.id if move_to_col else None,
            ),
            target_session=session.id,
        )

        if move_to_col:
            return ToolResult(
                f"Deleted column '{col.name}' and moved tasks to '{move_to_col.name}'",
                events=[event],
            )
        return ToolResult(f"Deleted column '{col.name}'", events=[event])

    # --- StatefulDomain methods ---

    async def get_state(self, session: "Session") -> dict[str, Any] | None:
        """Return current board state for a session."""
        await _load_all_data()
        boards = await self._get_boards_for_session(session.id)
        if not boards:
            return None

        return {
            "boards": [b.to_dict() for _, b in boards],
            "associations": [a.to_dict() for a, _ in boards],
        }

    async def save_state(self, session: "Session") -> dict[str, Any]:
        """Save state to persistent storage."""
        # Boards are auto-saved on each operation
        boards = await self._get_boards_for_session(session.id)
        return {
            "boards": [b.to_dict() for _, b in boards],
            "associations": [a.to_dict() for a, _ in boards],
        }

    async def load_state(self, session: "Session", state: dict[str, Any]) -> None:
        """Load state from persistent storage."""
        await _load_all_data()

    async def clear_state(self, session: "Session") -> None:
        """Clear boards for a session (removes associations only, not boards)."""
        await _load_all_data()

        # Remove associations for this session
        assocs_to_remove = [
            assoc_id
            for assoc_id, assoc in _associations.items()
            if assoc.session_id == session.id
        ]
        for assoc_id in assocs_to_remove:
            del _associations[assoc_id]
            await _delete_association_file(assoc_id)


def create_domain() -> KanbanDomain:
    """Factory function for domain loading."""
    return KanbanDomain()
