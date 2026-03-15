"""Data models for the Kanban domain.

Boards, columns, tasks, and session associations.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


def _now() -> str:
    """Get current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Task:
    """A task in the kanban system."""
    id: str
    title: str
    description: str
    resolution: str  # What was done to complete/resolve the task
    created_at: str
    updated_at: str

    @classmethod
    def create(cls, title: str, description: str = "") -> "Task":
        """Create a new task with a unique ID."""
        now = _now()
        return cls(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            resolution="",
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize task to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "resolution": self.resolution,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Deserialize task from dictionary."""
        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            resolution=data.get("resolution", ""),
            created_at=data.get("createdAt") or data.get("created_at", _now()),
            updated_at=data.get("updatedAt") or data.get("updated_at", _now()),
        )


@dataclass
class Column:
    """A column in a kanban board."""
    id: str
    name: str
    position: int
    task_ids: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, name: str, position: int) -> "Column":
        """Create a new column with a unique ID."""
        return cls(
            id=str(uuid.uuid4()),
            name=name,
            position=position,
            task_ids=[],
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize column to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "taskIds": self.task_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Column":
        """Deserialize column from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            position=data.get("position", 0),
            task_ids=data.get("taskIds") or data.get("task_ids", []),
        )


@dataclass
class Board:
    """A kanban board."""
    id: str
    name: str
    columns: list[Column] = field(default_factory=list)
    tasks: dict[str, Task] = field(default_factory=dict)  # task_id -> Task
    default_column_id: str = ""
    created_at: str = field(default_factory=_now)

    @classmethod
    def create(cls, name: str, columns: list[tuple[str, int]] | None = None) -> "Board":
        """Create a new board with default columns.

        Args:
            name: Display name for the board
            columns: Optional list of (name, position) tuples. Defaults to
                     Backlog, To Do, In Progress, Done.
        """
        column_defs = columns or [
            ("Backlog", 0),
            ("To Do", 1),
            ("In Progress", 2),
            ("Done", 3),
        ]

        board_columns = [Column.create(col_name, pos) for col_name, pos in column_defs]
        default_col_id = board_columns[0].id if board_columns else ""

        return cls(
            id=str(uuid.uuid4()),
            name=name,
            columns=board_columns,
            tasks={},
            default_column_id=default_col_id,
            created_at=_now(),
        )

    def get_column_by_name(self, name: str) -> Column | None:
        """Find a column by name (case-insensitive)."""
        name_lower = name.lower()
        for col in self.columns:
            if col.name.lower() == name_lower:
                return col
        return None

    def get_column_by_id(self, column_id: str) -> Column | None:
        """Find a column by ID (supports prefix matching)."""
        for col in self.columns:
            if col.id == column_id or col.id.startswith(column_id):
                return col
        return None

    def get_task_by_title(self, title: str) -> Task | None:
        """Find a task by title (case-insensitive)."""
        title_lower = title.lower()
        for task in self.tasks.values():
            if task.title.lower() == title_lower:
                return task
        return None

    def get_task_by_id(self, task_id: str) -> Task | None:
        """Find a task by ID (supports prefix matching)."""
        if task_id in self.tasks:
            return self.tasks[task_id]
        for tid, task in self.tasks.items():
            if tid.startswith(task_id):
                return task
        return None

    def find_task_column(self, task_id: str) -> Column | None:
        """Find which column contains a task."""
        for col in self.columns:
            if task_id in col.task_ids:
                return col
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize board to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "columns": [col.to_dict() for col in self.columns],
            "tasks": {tid: task.to_dict() for tid, task in self.tasks.items()},
            "defaultColumnId": self.default_column_id,
            "createdAt": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Board":
        """Deserialize board from dictionary."""
        columns = [Column.from_dict(c) for c in data.get("columns", [])]
        tasks = {
            tid: Task.from_dict(t)
            for tid, t in data.get("tasks", {}).items()
        }
        return cls(
            id=data["id"],
            name=data["name"],
            columns=columns,
            tasks=tasks,
            default_column_id=data.get("defaultColumnId") or data.get("default_column_id", ""),
            created_at=data.get("createdAt") or data.get("created_at", _now()),
        )


@dataclass
class SessionBoardAssociation:
    """Association between a session and a kanban board."""
    id: str
    session_id: str
    board_id: str
    role: str  # "primary", "reference", "archive"
    created_at: str
    created_by: str  # "user", "llm", "fork"
    inherited_from: str | None = None  # Parent session ID if inherited

    @classmethod
    def create(
        cls,
        session_id: str,
        board_id: str,
        role: str = "primary",
        created_by: str = "user",
        inherited_from: str | None = None,
    ) -> "SessionBoardAssociation":
        """Create a new association."""
        return cls(
            id=str(uuid.uuid4()),
            session_id=session_id,
            board_id=board_id,
            role=role,
            created_at=_now(),
            created_by=created_by,
            inherited_from=inherited_from,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize association to dictionary."""
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "boardId": self.board_id,
            "role": self.role,
            "createdAt": self.created_at,
            "createdBy": self.created_by,
            "inheritedFrom": self.inherited_from,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionBoardAssociation":
        """Deserialize association from dictionary."""
        return cls(
            id=data["id"],
            session_id=data.get("sessionId") or data.get("session_id", ""),
            board_id=data.get("boardId") or data.get("board_id", ""),
            role=data.get("role", "primary"),
            created_at=data.get("createdAt") or data.get("created_at", _now()),
            created_by=data.get("createdBy") or data.get("created_by", "user"),
            inherited_from=data.get("inheritedFrom") or data.get("inherited_from"),
        )
