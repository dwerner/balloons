#!/usr/bin/env python
"""CLI for the Kanban domain plugin.

Exercises the kanban domain's capabilities similarly to how the client uses them.
This is useful for testing and debugging the domain without the full server stack.

Usage:
    python -m plugins.kanban.cli [command] [options]

Commands:
    list-boards         List boards for current session
    list-all-boards     List all boards in the system
    create-board NAME   Create a new board
    link-board ID       Link an existing board to the session
    unlink-board ID     Unlink a board from the session
    find-board NAME     Find boards by name
    create-task TITLE   Create a task (requires a board)
    move-task TASK COL  Move task to column
    update-task ID      Update task (--title, --description, --resolution)
    delete-task ID      Delete a task
    list-tasks          List all tasks on the primary board
    board-state         Get full board state
    interactive         Interactive mode

Options:
    --session ID        Session ID to use (default: cli-session)
    --board ID          Board ID for task operations
    --column ID         Column ID for task creation
    --description TEXT  Description for task creation/update
    --resolution TEXT   Resolution for task update
    --title TEXT        Title for task update
"""

import argparse
import asyncio
import sys
from typing import Any
from unittest.mock import MagicMock

from .domain import create_domain, KanbanDomain
from ..base import ToolResult


class MockSession:
    """Mock session for CLI usage."""
    def __init__(self, session_id: str = "cli-session"):
        self.id = session_id


def print_result(result: ToolResult) -> None:
    """Pretty print a tool result."""
    if result.is_error:
        print(f"\033[91mError:\033[0m {result.result}")
    else:
        print(result.result)

    if result.events:
        print(f"\n\033[90m({len(result.events)} event(s) emitted)\033[0m")


async def cmd_list_boards(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """List boards for the current session."""
    result = await domain.kanban_get_boards(session=session)
    print_result(result)


async def cmd_list_all_boards(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """List all boards in the system."""
    result = await domain.kanban_list_all_boards(session=session)
    print_result(result)


async def cmd_create_board(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """Create a new board."""
    result = await domain.kanban_create_board(name=args.name, session=session)
    print_result(result)


async def cmd_link_board(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """Link an existing board to the session."""
    result = await domain.kanban_link_board(board_id=args.board_id, session=session)
    print_result(result)


async def cmd_unlink_board(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """Unlink a board from the session."""
    result = await domain.kanban_unlink_board(board_id=args.board_id, session=session)
    print_result(result)


async def cmd_find_board(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """Find boards by name."""
    result = await domain.kanban_find_board(name=args.name, session=session)
    print_result(result)


async def cmd_create_task(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """Create a new task."""
    result = await domain.kanban_create_task(
        title=args.title,
        description=args.description or "",
        board_id=args.board,
        column_id=args.column,
        session=session,
    )
    print_result(result)


async def cmd_move_task(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """Move a task to a different column."""
    result = await domain.kanban_move_task(
        task=args.task,
        to_column=args.column,
        session=session,
    )
    print_result(result)


async def cmd_update_task(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """Update a task."""
    result = await domain.kanban_update_task(
        task_id=args.task_id,
        title=args.title,
        description=args.description,
        resolution=args.resolution,
        session=session,
    )
    print_result(result)


async def cmd_delete_task(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """Delete a task."""
    result = await domain.kanban_delete_task(task_id=args.task_id, session=session)
    print_result(result)


async def cmd_list_tasks(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """List tasks on a board."""
    result = await domain.kanban_list_tasks(
        board_id=args.board,
        column_name=args.column,
        session=session,
    )
    print_result(result)


async def cmd_board_state(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """Get full board state."""
    result = await domain.kanban_get_board_state(board_id=args.board, session=session)
    print_result(result)


async def cmd_interactive(domain: KanbanDomain, session: MockSession, args: argparse.Namespace) -> None:
    """Interactive mode."""
    print("Kanban CLI Interactive Mode")
    print(f"Session: {session.id}")
    print("Type 'help' for commands, 'quit' to exit.\n")

    commands = {
        "boards": ("List session boards", lambda: domain.kanban_get_boards(session=session)),
        "all": ("List all boards", lambda: domain.kanban_list_all_boards(session=session)),
        "state": ("Show board state", lambda: domain.kanban_get_board_state(session=session)),
        "tasks": ("List tasks", lambda: domain.kanban_list_tasks(session=session)),
        "help": ("Show help", None),
        "quit": ("Exit", None),
        "exit": ("Exit", None),
    }

    while True:
        try:
            line = input("\033[94mkanban>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not line:
            continue

        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("quit", "exit"):
            print("Goodbye!")
            break

        if cmd == "help":
            print("\nAvailable commands:")
            print("  boards              - List boards for this session")
            print("  all                 - List all boards in the system")
            print("  state               - Show current board state")
            print("  tasks               - List all tasks")
            print("  create-board NAME   - Create a new board")
            print("  link BOARD_ID       - Link a board to this session")
            print("  unlink BOARD_ID     - Unlink a board from this session")
            print("  find NAME           - Find boards by name")
            print("  add TITLE           - Create a task")
            print("  move TASK to COLUMN - Move task to column")
            print("  done TASK           - Move task to Done")
            print("  progress TASK       - Move task to In Progress")
            print("  delete TASK_ID      - Delete a task")
            print("  resolve TASK_ID RESOLUTION - Set task resolution")
            print("  quit/exit           - Exit\n")
            continue

        try:
            if cmd in commands and commands[cmd][1]:
                result = await commands[cmd][1]()
                print_result(result)
            elif cmd == "create-board" and arg:
                result = await domain.kanban_create_board(name=arg, session=session)
                print_result(result)
            elif cmd == "link" and arg:
                result = await domain.kanban_link_board(board_id=arg, session=session)
                print_result(result)
            elif cmd == "unlink" and arg:
                result = await domain.kanban_unlink_board(board_id=arg, session=session)
                print_result(result)
            elif cmd == "find" and arg:
                result = await domain.kanban_find_board(name=arg, session=session)
                print_result(result)
            elif cmd == "add" and arg:
                result = await domain.kanban_create_task(title=arg, session=session)
                print_result(result)
            elif cmd == "move" and " to " in arg:
                task, column = arg.rsplit(" to ", 1)
                result = await domain.kanban_move_task(task=task.strip(), to_column=column.strip(), session=session)
                print_result(result)
            elif cmd == "done" and arg:
                result = await domain.kanban_move_task(task=arg, to_column="Done", session=session)
                print_result(result)
            elif cmd == "progress" and arg:
                result = await domain.kanban_move_task(task=arg, to_column="In Progress", session=session)
                print_result(result)
            elif cmd == "delete" and arg:
                result = await domain.kanban_delete_task(task_id=arg, session=session)
                print_result(result)
            elif cmd == "resolve" and arg:
                parts = arg.split(maxsplit=1)
                if len(parts) == 2:
                    result = await domain.kanban_update_task(
                        task_id=parts[0],
                        resolution=parts[1],
                        session=session,
                    )
                    print_result(result)
                else:
                    print("Usage: resolve TASK_ID RESOLUTION")
            else:
                print(f"Unknown command: {cmd}. Type 'help' for available commands.")
        except Exception as e:
            print(f"\033[91mError:\033[0m {e}")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        description="Kanban domain CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--session",
        default="cli-session",
        help="Session ID to use (default: cli-session)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # list-boards
    subparsers.add_parser("list-boards", help="List boards for current session")

    # list-all-boards
    subparsers.add_parser("list-all-boards", help="List all boards in the system")

    # create-board
    p = subparsers.add_parser("create-board", help="Create a new board")
    p.add_argument("name", help="Board name")

    # link-board
    p = subparsers.add_parser("link-board", help="Link an existing board to the session")
    p.add_argument("board_id", help="Board ID to link")

    # unlink-board
    p = subparsers.add_parser("unlink-board", help="Unlink a board from the session")
    p.add_argument("board_id", help="Board ID to unlink")

    # find-board
    p = subparsers.add_parser("find-board", help="Find boards by name")
    p.add_argument("name", help="Board name to search for")

    # create-task
    p = subparsers.add_parser("create-task", help="Create a new task")
    p.add_argument("title", help="Task title")
    p.add_argument("--board", help="Board ID (optional)")
    p.add_argument("--column", help="Column ID or name (optional)")
    p.add_argument("--description", help="Task description")

    # move-task
    p = subparsers.add_parser("move-task", help="Move a task to a different column")
    p.add_argument("task", help="Task title or ID")
    p.add_argument("column", help="Target column name or ID")

    # update-task
    p = subparsers.add_parser("update-task", help="Update a task")
    p.add_argument("task_id", help="Task ID")
    p.add_argument("--title", help="New title")
    p.add_argument("--description", help="New description")
    p.add_argument("--resolution", help="Resolution (what was done)")

    # delete-task
    p = subparsers.add_parser("delete-task", help="Delete a task")
    p.add_argument("task_id", help="Task ID")

    # list-tasks
    p = subparsers.add_parser("list-tasks", help="List tasks on a board")
    p.add_argument("--board", help="Board ID (optional)")
    p.add_argument("--column", help="Filter by column name")

    # board-state
    p = subparsers.add_parser("board-state", help="Get full board state")
    p.add_argument("--board", help="Board ID (optional)")

    # interactive
    subparsers.add_parser("interactive", aliases=["i"], help="Interactive mode")

    return parser


async def main() -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Create domain and session
    domain = create_domain()
    session = MockSession(args.session)

    # Route to command handler
    handlers = {
        "list-boards": cmd_list_boards,
        "list-all-boards": cmd_list_all_boards,
        "create-board": cmd_create_board,
        "link-board": cmd_link_board,
        "unlink-board": cmd_unlink_board,
        "find-board": cmd_find_board,
        "create-task": cmd_create_task,
        "move-task": cmd_move_task,
        "update-task": cmd_update_task,
        "delete-task": cmd_delete_task,
        "list-tasks": cmd_list_tasks,
        "board-state": cmd_board_state,
        "interactive": cmd_interactive,
        "i": cmd_interactive,
    }

    handler = handlers.get(args.command)
    if handler:
        await handler(domain, session, args)
        return 0
    else:
        parser.print_help()
        return 1


def run() -> None:
    """Entry point for running the CLI."""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    run()
