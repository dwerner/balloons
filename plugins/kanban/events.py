"""Typed event payloads for the Kanban domain.

Defines structured event data for type-safe event handling.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BoardCreatedPayload:
    """Payload for board_created event.

    Emitted when a new board is created.
    """
    board_id: str
    name: str
    board: dict[str, Any]  # Full board state


@dataclass
class BoardDeletedPayload:
    """Payload for board_deleted event.

    Emitted when a board is deleted.
    """
    board_id: str


@dataclass
class TaskCreatedPayload:
    """Payload for task_created event.

    Emitted when a task is created.
    """
    board_id: str
    task: dict[str, Any]
    column_id: str
    position: int


@dataclass
class TaskUpdatedPayload:
    """Payload for task_updated event.

    Emitted when a task is updated.
    """
    board_id: str
    task: dict[str, Any]


@dataclass
class TaskDeletedPayload:
    """Payload for task_deleted event.

    Emitted when a task is deleted.
    """
    board_id: str
    task_id: str


@dataclass
class TaskMovedPayload:
    """Payload for task_moved event.

    Emitted when a task is moved between columns.
    """
    board_id: str
    task_id: str
    from_column_id: str
    to_column_id: str
    new_position: int


@dataclass
class ColumnDeletedPayload:
    """Payload for column_deleted event.

    Emitted when a column is deleted.
    """
    board_id: str
    column_id: str
    tasks_moved_to: str | None


@dataclass
class BoardStateSyncPayload:
    """Payload for board_state_sync event.

    Emitted when the UI requests current state (e.g., on reconnection)
    or when board state is listed.
    """
    boards: list[dict[str, Any]]
    associations: list[dict[str, Any]]


@dataclass
class BoardAssociatedPayload:
    """Payload for board_associated event.

    Emitted when a board is associated with a session.
    """
    association: dict[str, Any]
    board: dict[str, Any]


@dataclass
class BoardDisassociatedPayload:
    """Payload for board_disassociated event.

    Emitted when a board is disassociated from a session.
    """
    session_id: str
    board_id: str
    association_id: str


# Map event types to their payload classes for validation/parsing
EVENT_PAYLOADS = {
    "board_created": BoardCreatedPayload,
    "board_deleted": BoardDeletedPayload,
    "task_created": TaskCreatedPayload,
    "task_updated": TaskUpdatedPayload,
    "task_deleted": TaskDeletedPayload,
    "task_moved": TaskMovedPayload,
    "column_deleted": ColumnDeletedPayload,
    "board_state_sync": BoardStateSyncPayload,
    "board_associated": BoardAssociatedPayload,
    "board_disassociated": BoardDisassociatedPayload,
}
