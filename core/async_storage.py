"""Async wrapper for Rust balloons_storage.

Provides an async interface to the synchronous Rust storage backend,
using ThreadPoolExecutor to run blocking calls without blocking the event loop.

The Rust backend (balloons_storage.Storage) provides ACID-compliant session
persistence via redb, with JSON serialization at the Python boundary.

Usage:
    storage = AsyncStorage("/path/to/sessions.redb")

    # Save a session
    await storage.save_session(session)

    # Load a session
    session = await storage.load_session(session_id)

    # List all sessions (returns metadata)
    sessions = await storage.list_sessions()
"""

from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

# Import the Rust storage module
try:
    import balloons_storage
    RUST_STORAGE_AVAILABLE = True
except ImportError:
    RUST_STORAGE_AVAILABLE = False

if TYPE_CHECKING:
    from session import Session
    from models import Turn, ContentBlock


# Default database path
DEFAULT_DB_PATH = Path.home() / ".balloons" / "sessions.redb"


class AsyncStorage:
    """Async wrapper for Rust storage backend.

    Wraps the synchronous balloons_storage.Storage class with async methods,
    using a ThreadPoolExecutor to avoid blocking the asyncio event loop.

    The executor is shared across all AsyncStorage instances to limit thread usage.
    """

    # Shared executor for all instances (1 thread is enough for I/O-bound storage)
    _executor: ThreadPoolExecutor | None = None
    _executor_lock = asyncio.Lock()

    def __init__(self, db_path: str | Path | None = None):
        """Initialize async storage.

        Args:
            db_path: Path to the redb database file. Defaults to ~/.balloons/sessions.redb
        """
        if not RUST_STORAGE_AVAILABLE:
            raise RuntimeError(
                "balloons_storage module not available. "
                "Run 'maturin develop' in balloons-rs/ to build it."
            )

        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create the sync Rust storage handle
        self._storage = balloons_storage.Storage(str(self._db_path))

    @classmethod
    async def _get_executor(cls) -> ThreadPoolExecutor:
        """Get or create the shared thread pool executor."""
        if cls._executor is None:
            async with cls._executor_lock:
                if cls._executor is None:
                    # Single thread is sufficient for sequential storage ops
                    cls._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="storage")
        return cls._executor

    async def _run_sync(self, func, *args):
        """Run a synchronous function in the thread pool."""
        executor = await self._get_executor()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, func, *args)

    # =========================================================================
    # Session Operations
    # =========================================================================

    async def save_session(self, session: Session) -> None:
        """Save a session to storage.

        Converts the Session object to the wire format (SessionData) and
        serializes to JSON for the Rust backend.

        Args:
            session: The Session object to save
        """
        # Build the wire format data
        session_data = self._session_to_wire(session)
        json_data = json.dumps(session_data)

        await self._run_sync(self._storage.save_session, session.id, json_data)

    async def load_session(self, session_id: str) -> Optional[Session]:
        """Load a session from storage.

        Args:
            session_id: The session ID to load

        Returns:
            The Session object, or None if not found
        """
        json_data = await self._run_sync(self._storage.load_session, session_id)
        if json_data is None:
            return None

        data = json.loads(json_data)
        return self._wire_to_session(data)

    async def delete_session(self, session_id: str) -> None:
        """Delete a session from storage.

        Args:
            session_id: The session ID to delete
        """
        await self._run_sync(self._storage.delete_session, session_id)

    async def list_sessions(self) -> list[dict]:
        """List all sessions with metadata.

        Returns:
            List of session metadata dicts with keys:
            - id: Session ID
            - name: Session title
            - created_at: ISO timestamp
            - updated_at: ISO timestamp
            - turn_count: Number of turns
        """
        json_data = await self._run_sync(self._storage.list_sessions)
        return json.loads(json_data)

    # =========================================================================
    # Turn Operations (for future separate turn storage)
    # =========================================================================

    async def save_turn(self, session_id: str, turn: Turn) -> None:
        """Save a single turn to storage.

        Args:
            session_id: The session this turn belongs to
            turn: The Turn object to save
        """
        turn_data = self._turn_to_wire(turn)
        json_data = json.dumps(turn_data)

        await self._run_sync(self._storage.save_turn, session_id, json_data)

    async def load_turns(self, session_id: str) -> list[dict]:
        """Load all turns for a session.

        Args:
            session_id: The session to load turns for

        Returns:
            List of turn data dicts
        """
        json_data = await self._run_sync(self._storage.load_turns, session_id)
        return json.loads(json_data)

    async def delete_turn(self, session_id: str, turn_id: str) -> None:
        """Delete a turn from storage.

        Args:
            session_id: The session the turn belongs to
            turn_id: The turn ID to delete
        """
        await self._run_sync(self._storage.delete_turn, session_id, turn_id)

    async def reorder_turns(self, session_id: str, turn_ids: list[str]) -> None:
        """Reorder turns within a session.

        Args:
            session_id: The session to reorder turns in
            turn_ids: List of turn IDs in the desired order
        """
        json_data = json.dumps(turn_ids)
        await self._run_sync(self._storage.reorder_turns, session_id, json_data)

    # =========================================================================
    # Wire Format Conversion
    # =========================================================================

    def _session_to_wire(self, session: Session) -> dict:
        """Convert a Session to the wire format for storage.

        This matches the SessionData schema expected by Rust.
        """
        return {
            "id": session.id,
            "created": session.created,
            "last_modified": session.last_modified,
            "model": session.model,
            "turns": [self._turn_to_wire(t) for t in session.turns],
            "total_input_tokens": session.total_input_tokens,
            "total_output_tokens": session.total_output_tokens,
            "total_cost": session.total_cost,
            "context_window": session.context_window,
            "parent_id": session.parent_id,
            "children": session.children,
            "returned": session.returned,
            "return_condition": session.return_condition,
            "working_directories": session.working_directories,
            "title": session.title,
            "summary": session.summary,
            "fork_name": session.fork_name,
            "fork_status": session.fork_status,
            "fork_point_turn": session.fork_point_turn,
            "merge_point_turn": session.merge_point_turn,
            "merge_message": session.merge_message,
            "backend_name": session.backend_name,
            "cached_context_tokens": session.cached_context_tokens,
            "message_queue": session.message_queue.to_dict() if session.message_queue else {},
        }

    def _turn_to_wire(self, turn: Turn) -> dict:
        """Convert a Turn to the wire format for storage.

        This matches the TurnData schema expected by Rust.
        """
        # Generate a stable turn ID if not present
        # For now, we use a combination of timestamp and content hash
        turn_id = getattr(turn, "id", None)
        if not turn_id:
            # Generate deterministic ID from content
            import hashlib
            content_str = json.dumps(self._serialize_content_block(turn.content_block), sort_keys=True)
            content_hash = hashlib.md5(content_str.encode()).hexdigest()[:8]
            turn_id = f"{turn.timestamp[:19].replace(':', '-').replace('T', '_')}_{content_hash}"

        return {
            "id": turn_id,
            "role": turn.role,
            "content_block": self._serialize_content_block(turn.content_block),
            "tokens": turn.tokens,
            "timestamp": turn.timestamp,
            "context_mode": turn.context_mode.value,
            "summary": turn.summary,
            "exchange_id": turn.exchange_id,
        }

    def _serialize_content_block(self, block: ContentBlock) -> dict:
        """Serialize a content block to a dict.

        This matches the JSON structure expected by Rust's serde_json::Value.
        """
        from models import (
            TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock,
            ErrorBlock, LinkBlock, ForkBlock, MergeBlock, ArchiveBlock, SlideBlock
        )

        if isinstance(block, TextBlock):
            return {"type": "text", "text": block.text}
        elif isinstance(block, ToolUseBlock):
            return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
        elif isinstance(block, ToolResultBlock):
            return {"type": "tool_result", "tool_use_id": block.tool_use_id, "content": block.content, "is_error": block.is_error}
        elif isinstance(block, InterruptionBlock):
            return {"type": "interruption", "reason": block.reason}
        elif isinstance(block, ErrorBlock):
            return {
                "type": "error",
                "reason": block.reason,
                "partial_tool_name": block.partial_tool_name,
                "partial_tool_input": block.partial_tool_input,
                "details": block.details,
            }
        elif isinstance(block, LinkBlock):
            return {
                "type": "link",
                "link_id": block.link_id,
                "linked_session_id": block.linked_session_id,
                "summary": block.summary,
                "is_orphaned": block.is_orphaned,
            }
        elif isinstance(block, ForkBlock):
            return {
                "type": "fork",
                "fork_id": block.fork_id,
                "child_session_id": block.child_session_id,
                "fork_name": block.fork_name,
                "prompt": block.prompt,
                "status": block.status,
            }
        elif isinstance(block, MergeBlock):
            return {
                "type": "merge",
                "merge_id": block.merge_id,
                "child_session_id": block.child_session_id,
                "fork_name": block.fork_name,
                "message": block.message,
            }
        elif isinstance(block, ArchiveBlock):
            data = {
                "type": "archive",
                "archive_id": block.archive_id,
                "file_path": block.file_path,
                "summary": block.summary,
                "turn_start": block.turn_start,
                "turn_end": block.turn_end,
                "message_count": block.message_count,
                "token_estimate": block.token_estimate,
            }
            if block.structured_summary:
                data["structured_summary"] = {
                    "files_modified": block.structured_summary.files_modified,
                    "work_done": block.structured_summary.work_done,
                    "key_decisions": block.structured_summary.key_decisions,
                }
            return data
        elif isinstance(block, SlideBlock):
            return {
                "type": "slide",
                "title": block.title,
                "content": block.content,
                "notes": block.notes,
            }
        return {"type": "unknown"}

    def _wire_to_session(self, data: dict) -> Session:
        """Convert wire format data to a Session object.

        This is the inverse of _session_to_wire.
        """
        # Import here to avoid circular imports
        from session import Session
        from models import MessageQueue

        session = Session(
            id=data["id"],
            created=data["created"],
            last_modified=data.get("last_modified", data["created"]),
            model=data.get("model", ""),
            total_input_tokens=data.get("total_input_tokens", 0),
            total_output_tokens=data.get("total_output_tokens", 0),
            total_cost=data.get("total_cost", 0.0),
            context_window=data.get("context_window", 200000),
            parent_id=data.get("parent_id"),
            children=data.get("children", []),
            returned=data.get("returned", False),
            return_condition=data.get("return_condition", "manual"),
            working_directories=data.get("working_directories", []),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            fork_name=data.get("fork_name", ""),
            fork_status=data.get("fork_status", "active"),
            fork_point_turn=data.get("fork_point_turn", -1),
            merge_point_turn=data.get("merge_point_turn", -1),
            merge_message=data.get("merge_message", ""),
            backend_name=data.get("backend_name", ""),
            cached_context_tokens=data.get("cached_context_tokens", 0),
            message_queue=MessageQueue.from_dict(data.get("message_queue", {})),
        )

        # Deserialize turns
        for turn_data in data.get("turns", []):
            turn = self._wire_to_turn(turn_data)
            session.turns.append(turn)

        return session

    def _wire_to_turn(self, data: dict) -> Turn:
        """Convert wire format turn data to a Turn object."""
        from models import Turn, ContextMode

        content_block = self._deserialize_content_block(data.get("content_block", {"type": "text", "text": ""}))

        mode_str = data.get("context_mode", "compress")
        try:
            context_mode = ContextMode(mode_str)
        except ValueError:
            context_mode = ContextMode.COMPRESS

        return Turn(
            role=data["role"],
            content_block=content_block,
            tokens=data.get("tokens", 0),
            timestamp=data.get("timestamp", ""),
            context_mode=context_mode,
            summary=data.get("summary", ""),
            exchange_id=data.get("exchange_id"),
        )

    def _deserialize_content_block(self, data: dict) -> ContentBlock:
        """Deserialize a content block from a dict."""
        from models import (
            TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock,
            ErrorBlock, LinkBlock, ForkBlock, MergeBlock, ArchiveBlock, SlideBlock,
            ArchiveSummary
        )

        block_type = data.get("type", "text")

        if block_type == "text":
            return TextBlock(text=data.get("text", ""))
        elif block_type == "tool_use":
            return ToolUseBlock(
                id=data.get("id", ""),
                name=data.get("name", ""),
                input=data.get("input", {}),
            )
        elif block_type == "tool_result":
            return ToolResultBlock(
                tool_use_id=data.get("tool_use_id", ""),
                content=data.get("content", ""),
                is_error=data.get("is_error", False),
            )
        elif block_type == "interruption":
            return InterruptionBlock(reason=data.get("reason", "user_cancelled"))
        elif block_type == "error":
            return ErrorBlock(
                reason=data.get("reason", "stream_error"),
                partial_tool_name=data.get("partial_tool_name", ""),
                partial_tool_input=data.get("partial_tool_input", ""),
                details=data.get("details", ""),
            )
        elif block_type == "link":
            return LinkBlock(
                link_id=data.get("link_id", ""),
                linked_session_id=data.get("linked_session_id", ""),
                summary=data.get("summary", ""),
                is_orphaned=data.get("is_orphaned", False),
            )
        elif block_type == "fork":
            return ForkBlock(
                fork_id=data.get("fork_id", ""),
                child_session_id=data.get("child_session_id", ""),
                fork_name=data.get("fork_name", ""),
                prompt=data.get("prompt", ""),
                status=data.get("status", "active"),
            )
        elif block_type == "merge":
            return MergeBlock(
                merge_id=data.get("merge_id", ""),
                child_session_id=data.get("child_session_id", ""),
                fork_name=data.get("fork_name", ""),
                message=data.get("message", ""),
            )
        elif block_type == "archive":
            structured_summary = None
            if "structured_summary" in data:
                ss = data["structured_summary"]
                structured_summary = ArchiveSummary(
                    files_modified=ss.get("files_modified", []),
                    work_done=ss.get("work_done", ""),
                    key_decisions=ss.get("key_decisions", []),
                )
            return ArchiveBlock(
                archive_id=data.get("archive_id", ""),
                file_path=data.get("file_path", ""),
                summary=data.get("summary", ""),
                structured_summary=structured_summary,
                turn_start=data.get("turn_start", 0),
                turn_end=data.get("turn_end", 0),
                message_count=data.get("message_count", 0),
                token_estimate=data.get("token_estimate", 0),
            )
        elif block_type == "slide":
            return SlideBlock(
                title=data.get("title", ""),
                content=data.get("content", ""),
                notes=data.get("notes", ""),
            )
        # Fallback to text
        return TextBlock(text=str(data))


# =========================================================================
# Convenience Functions
# =========================================================================


def is_rust_storage_available() -> bool:
    """Check if the Rust storage backend is available."""
    return RUST_STORAGE_AVAILABLE


async def get_default_storage() -> AsyncStorage:
    """Get the default AsyncStorage instance.

    Uses the default database path (~/.balloons/sessions.redb).
    """
    return AsyncStorage(DEFAULT_DB_PATH)
