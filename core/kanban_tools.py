"""LLM-invocable tools for kanban board management.

These tools allow Claude to create and manage kanban tasks directly
during conversation, with automatic board selection based on the session.

Tool Names:
- kanban_get_boards: Get boards associated with the current session
- kanban_create_task: Create a new task on a board
- kanban_update_task: Update an existing task
- kanban_move_task: Move a task to a different column
- kanban_delete_task: Delete a task
- kanban_list_tasks: List tasks with optional filtering
- kanban_get_board_state: Get full state of a board (columns and tasks)
"""

import json
from typing import TYPE_CHECKING

from core.async_storage import AsyncStorage
from core.kanban_service import KanbanService

if TYPE_CHECKING:
    from session import Session


# Tool names for registration
KANBAN_TOOL_NAMES = {
    "kanban_get_boards",
    "kanban_create_task",
    "kanban_update_task",
    "kanban_move_task",
    "kanban_delete_task",
    "kanban_list_tasks",
    "kanban_get_board_state",
    "kanban_create_board",
    "kanban_delete_column",
}

# Tools that mutate kanban data
KANBAN_MUTATION_TOOLS = {
    "kanban_create_task",
    "kanban_update_task",
    "kanban_move_task",
    "kanban_delete_task",
    "kanban_create_board",
    "kanban_delete_column",
}


# Tool definitions in OpenAI function format
KANBAN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "kanban_get_boards",
            "description": """Get kanban boards associated with the current session.

Returns a list of boards linked to this session, including any boards inherited
from parent sessions on fork. Use this to discover available boards before
creating or managing tasks.

If no boards exist, you can create one with kanban_create_board.""",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kanban_create_board",
            "description": """Create a new kanban board and associate it with the current session.

Creates a board with default columns (Backlog, To Do, In Progress, Done).
The board is automatically associated with this session so tasks can be
added to it immediately.

Use this when:
- No board exists for the session yet
- Starting a new project or feature that needs its own board""",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Display name for the board (e.g., 'Feature X Tasks')"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kanban_create_task",
            "description": """Create a new task on a kanban board.

If no board_id is specified, uses the primary board for this session.
If no column_id is specified, the task is added to the default column
(usually 'Backlog' or the first column).

Use this when:
- Breaking down work into trackable tasks
- The user mentions something that should be tracked
- Adding items to a sprint or backlog""",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short title for the task (max 100 chars)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional detailed description of the task"
                    },
                    "board_id": {
                        "type": "string",
                        "description": "Board ID to add the task to. If omitted, uses the session's primary board."
                    },
                    "column_id": {
                        "type": "string",
                        "description": "Column ID to place the task in. If omitted, uses the board's default column."
                    }
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kanban_update_task",
            "description": """Update an existing task's title, description, or resolution.

Only modifies the fields provided; other fields remain unchanged.

The resolution field documents what was done to complete/resolve the task.
Write the resolution when moving a task to Done to capture the outcome.

Use this when:
- Renaming a task
- Adding or editing a task's description
- Documenting task completion (write the resolution)
- Clarifying task details""",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID of the task to update"
                    },
                    "title": {
                        "type": "string",
                        "description": "New title for the task"
                    },
                    "description": {
                        "type": "string",
                        "description": "New description for the task"
                    },
                    "resolution": {
                        "type": "string",
                        "description": "What was done to complete/resolve this task. Write this when moving to Done."
                    }
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kanban_move_task",
            "description": """Move a task to a different column.

Common column names are 'Backlog', 'To Do', 'In Progress', and 'Done'.
You can use either names or IDs for both task and column.

Use this when:
- Starting work on a task (move to 'In Progress')
- Completing a task (move to 'Done')
- Reprioritizing work""",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Task title (e.g., 'ctrl-enter') or task ID"
                    },
                    "to_column": {
                        "type": "string",
                        "description": "Column name (e.g., 'Done', 'In Progress') or column ID"
                    },
                    "position": {
                        "type": "integer",
                        "description": "Optional position within the column (0 = top)"
                    }
                },
                "required": ["task", "to_column"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kanban_delete_task",
            "description": """Delete a task from a board.

Permanently removes the task. Use with caution.

Use this when:
- A task is no longer relevant
- Cleaning up duplicate tasks
- The user explicitly asks to remove a task""",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID of the task to delete"
                    }
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kanban_list_tasks",
            "description": """List tasks from a board, optionally filtered by column.

Returns tasks with their IDs, titles, descriptions, and current column.
Useful for getting an overview or finding specific tasks.

If no board_id is specified, uses the primary board for this session.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "board_id": {
                        "type": "string",
                        "description": "Board ID to list tasks from. If omitted, uses session's primary board."
                    },
                    "column_name": {
                        "type": "string",
                        "description": "Optional column name to filter by (e.g., 'In Progress', 'Done')"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kanban_get_board_state",
            "description": """Get the full state of a kanban board.

Returns the board with all its columns and tasks, organized by column.
Useful for getting a complete view of the board structure.

If no board_id is specified, uses the primary board for this session.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "board_id": {
                        "type": "string",
                        "description": "Board ID. If omitted, uses session's primary board."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kanban_delete_column",
            "description": """Delete a column from a kanban board.

Removes a column. If the column has tasks, you can optionally move them
to another column; otherwise they become orphaned.

Use this when:
- Simplifying a board (e.g., removing unused 'To Do' or 'In Progress' columns)
- Reorganizing board structure""",
            "parameters": {
                "type": "object",
                "properties": {
                    "column": {
                        "type": "string",
                        "description": "Column name (e.g., 'To Do') or column ID"
                    },
                    "move_tasks_to": {
                        "type": "string",
                        "description": "Optional: column name or ID to move tasks to before deleting"
                    }
                },
                "required": ["column"]
            }
        }
    },
]


async def execute_kanban_tool(
    name: str,
    args: dict,
    session: "Session",
) -> tuple[str, bool]:
    """Execute a kanban tool and return the result.

    Args:
        name: Tool name (kanban_create_task, etc.)
        args: Tool arguments from the model
        session: Current session for context

    Returns:
        Tuple of (result_string, is_error)
    """
    # Get storage and service
    storage = AsyncStorage()
    kanban = KanbanService(storage)

    session_id = session.id

    try:
        if name == "kanban_get_boards":
            return await _get_boards(session_id, kanban)

        elif name == "kanban_create_board":
            return await _create_board(args, session_id, kanban)

        elif name == "kanban_create_task":
            return await _create_task(args, session_id, kanban)

        elif name == "kanban_update_task":
            return await _update_task(args, kanban)

        elif name == "kanban_move_task":
            return await _move_task(args, session_id, kanban)

        elif name == "kanban_delete_task":
            return await _delete_task(args, kanban)

        elif name == "kanban_list_tasks":
            return await _list_tasks(args, session_id, kanban)

        elif name == "kanban_get_board_state":
            return await _get_board_state(args, session_id, kanban)

        elif name == "kanban_delete_column":
            return await _delete_column(args, session_id, kanban)

        else:
            return f"Unknown kanban tool: {name}", True

    except Exception as e:
        return f"Error executing {name}: {str(e)}", True


async def _get_boards(session_id: str, kanban: KanbanService) -> tuple[str, bool]:
    """Get boards for the current session."""
    boards = await kanban.get_boards_for_session(session_id)

    if not boards:
        return "No boards associated with this session. Use kanban_create_board to create one.", False

    result_lines = [f"Found {len(boards)} board(s) for this session:\n"]
    for assoc, board in boards:
        inherited = " (inherited)" if assoc.inherited_from else ""
        result_lines.append(f"- {board.name}{inherited}")
        result_lines.append(f"  ID: {board.id}")
        result_lines.append(f"  Role: {assoc.role or 'primary'}")
        result_lines.append("")

    return "\n".join(result_lines), False


async def _create_board(args: dict, session_id: str, kanban: KanbanService) -> tuple[str, bool]:
    """Create a new board and associate with session."""
    name = args.get("name", "").strip()
    if not name:
        return "Error: Board name is required", True

    board_state = await kanban.create_board_for_session(session_id, name)
    if not board_state:
        return "Error: Failed to create board", True

    columns = ", ".join(col.name for col in board_state.columns)
    return (
        f"Created board '{board_state.board.name}' with ID {board_state.board.id}\n"
        f"Columns: {columns}\n"
        f"Default column: {board_state.board.default_column_id}"
    ), False


async def _get_primary_board(session_id: str, kanban: KanbanService) -> tuple[str | None, str | None]:
    """Get the primary board for a session.

    Returns:
        Tuple of (board_id, error_message). If error, board_id is None.
    """
    boards = await kanban.get_boards_for_session(session_id)
    if not boards:
        return None, "No boards associated with this session. Use kanban_create_board first."

    # Return the first board (primary)
    return boards[0][1].id, None


def _is_uuid(s: str) -> bool:
    """Check if a string looks like a UUID."""
    return len(s) == 36 and s.count('-') == 4


async def _resolve_column(column_ref: str, session_id: str, kanban: KanbanService) -> str | None:
    """Resolve a column name or ID to a column ID.

    Args:
        column_ref: Column name (e.g., 'Done') or column ID (UUID)
        session_id: Session ID to get boards from
        kanban: KanbanService instance

    Returns:
        Column ID if found, None otherwise
    """
    # If it looks like a UUID, return it directly
    if _is_uuid(column_ref):
        return column_ref

    # Otherwise, search for column by name in session's boards
    boards = await kanban.get_boards_for_session(session_id)
    for _, board in boards:
        board_state = await kanban.get_board_state(board.id)
        if board_state:
            for col in board_state.columns:
                if col.name.lower() == column_ref.lower():
                    return col.id

    return None


async def _resolve_task(task_ref: str, session_id: str, kanban: KanbanService) -> str | None:
    """Resolve a task title or ID to a task ID.

    Args:
        task_ref: Task title (e.g., 'ctrl-enter') or task ID (UUID)
        session_id: Session ID to get boards from
        kanban: KanbanService instance

    Returns:
        Task ID if found, None otherwise
    """
    # If it looks like a UUID, return it directly
    if _is_uuid(task_ref):
        return task_ref

    # Otherwise, search for task by title in session's boards
    task_ref_lower = task_ref.lower()
    boards = await kanban.get_boards_for_session(session_id)
    for _, board in boards:
        board_state = await kanban.get_board_state(board.id)
        if board_state:
            for col in board_state.columns:
                for task in col.tasks:
                    if task.title.lower() == task_ref_lower:
                        return task.id

    return None


async def _create_task(args: dict, session_id: str, kanban: KanbanService) -> tuple[str, bool]:
    """Create a new task."""
    title = args.get("title", "").strip()
    if not title:
        return "Error: Task title is required", True

    description = args.get("description", "").strip()
    board_id = args.get("board_id")
    column_id = args.get("column_id")

    # Get board_id if not provided
    if not board_id:
        board_id, error = await _get_primary_board(session_id, kanban)
        if error:
            return error, True

    task = await kanban.create_task(
        board_id=board_id,
        title=title,
        description=description,
        column_id=column_id,
    )

    if not task:
        return "Error: Failed to create task", True

    return (
        f"Created task '{task.title}'\n"
        f"ID: {task.id}\n"
        f"Board: {board_id}"
    ), False


async def _update_task(args: dict, kanban: KanbanService) -> tuple[str, bool]:
    """Update an existing task."""
    task_id = args.get("task_id", "").strip()
    if not task_id:
        return "Error: task_id is required", True

    title = args.get("title")
    description = args.get("description")
    resolution = args.get("resolution")

    if title is None and description is None and resolution is None:
        return "Error: At least one of title, description, or resolution must be provided", True

    task = await kanban.update_task(
        task_id=task_id,
        title=title.strip() if title else None,
        description=description.strip() if description else None,
        resolution=resolution.strip() if resolution else None,
    )

    if not task:
        return f"Error: Task {task_id} not found", True

    result = f"Updated task '{task.title}' (ID: {task.id})"
    if resolution:
        result += f"\nResolution: {task.resolution}"
    return result, False


async def _move_task(args: dict, session_id: str, kanban: KanbanService) -> tuple[str, bool]:
    """Move a task to a different column."""
    # Support both 'task' (new) and 'task_id' (legacy) parameter names
    task_ref = args.get("task", "").strip() or args.get("task_id", "").strip()
    if not task_ref:
        return "Error: task is required", True

    # Support both 'to_column' (new) and 'to_column_id' (legacy) parameter names
    to_column = args.get("to_column", "").strip() or args.get("to_column_id", "").strip()
    if not to_column:
        return "Error: to_column is required", True

    position = args.get("position")

    # Resolve task name to ID if needed
    task_id = await _resolve_task(task_ref, session_id, kanban)
    if not task_id:
        return f"Error: Task '{task_ref}' not found", True

    # Resolve column name to ID if needed
    to_column_id = await _resolve_column(to_column, session_id, kanban)
    if not to_column_id:
        return f"Error: Column '{to_column}' not found", True

    success = await kanban.move_task(
        task_id=task_id,
        to_column_id=to_column_id,
        position=position,
    )

    if not success:
        return f"Error: Failed to move task '{task_ref}'", True

    return f"Moved task '{task_ref}' to column '{to_column}'", False


async def _delete_task(args: dict, kanban: KanbanService) -> tuple[str, bool]:
    """Delete a task."""
    task_id = args.get("task_id", "").strip()
    if not task_id:
        return "Error: task_id is required", True

    success = await kanban.delete_task(task_id)

    if not success:
        return f"Error: Failed to delete task {task_id}", True

    return f"Deleted task {task_id}", False


async def _list_tasks(args: dict, session_id: str, kanban: KanbanService) -> tuple[str, bool]:
    """List tasks from a board."""
    board_id = args.get("board_id")
    column_name = args.get("column_name", "").strip().lower() if args.get("column_name") else None

    # Get board_id if not provided
    if not board_id:
        board_id, error = await _get_primary_board(session_id, kanban)
        if error:
            return error, True

    board_state = await kanban.get_board_state(board_id)
    if not board_state:
        return f"Error: Board {board_id} not found", True

    result_lines = [f"Tasks on board '{board_state.board.name}':\n"]

    for column in board_state.columns:
        # Filter by column name if specified
        if column_name and column.name.lower() != column_name:
            continue

        result_lines.append(f"## {column.name} ({len(column.tasks)} tasks)")

        if not column.tasks:
            result_lines.append("  (empty)")
        else:
            for task in column.tasks:
                desc_preview = task.description[:50] + "..." if len(task.description) > 50 else task.description
                result_lines.append(f"  - [{task.id[:8]}] {task.title}")
                if desc_preview:
                    result_lines.append(f"    {desc_preview}")

        result_lines.append("")

    return "\n".join(result_lines), False


async def _get_board_state(args: dict, session_id: str, kanban: KanbanService) -> tuple[str, bool]:
    """Get full board state."""
    board_id = args.get("board_id")

    # Get board_id if not provided
    if not board_id:
        board_id, error = await _get_primary_board(session_id, kanban)
        if error:
            return error, True

    board_state = await kanban.get_board_state(board_id)
    if not board_state:
        return f"Error: Board {board_id} not found", True

    result_lines = [
        f"# Board: {board_state.board.name}",
        f"ID: {board_state.board.id}",
        f"Default Column: {board_state.board.default_column_id}",
        f"Created: {board_state.board.created_at}",
        "",
        "## Columns",
        ""
    ]

    for column in board_state.columns:
        result_lines.append(f"### {column.name} (ID: {column.id})")
        result_lines.append(f"Position: {column.position}")
        result_lines.append(f"Tasks: {len(column.tasks)}")

        for task in column.tasks:
            result_lines.append(f"  - {task.title} (ID: {task.id})")
            if task.description:
                result_lines.append(f"    {task.description}")

        result_lines.append("")

    return "\n".join(result_lines), False


async def _delete_column(args: dict, session_id: str, kanban: KanbanService) -> tuple[str, bool]:
    """Delete a column from a board."""
    column_ref = args.get("column", "").strip()
    if not column_ref:
        return "Error: column is required", True

    move_tasks_to = args.get("move_tasks_to", "").strip() if args.get("move_tasks_to") else None

    # Resolve column name to ID
    column_id = await _resolve_column(column_ref, session_id, kanban)
    if not column_id:
        return f"Error: Column '{column_ref}' not found", True

    # Resolve move_tasks_to column if provided
    move_to_id = None
    if move_tasks_to:
        move_to_id = await _resolve_column(move_tasks_to, session_id, kanban)
        if not move_to_id:
            return f"Error: Target column '{move_tasks_to}' not found", True

    success = await kanban.delete_column(column_id, move_tasks_to=move_to_id)

    if not success:
        return f"Error: Failed to delete column '{column_ref}'", True

    if move_to_id:
        return f"Deleted column '{column_ref}' and moved tasks to '{move_tasks_to}'", False
    return f"Deleted column '{column_ref}'", False
