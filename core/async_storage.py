"""Async wrapper for Rust storage backend.

Provides an async interface to the synchronous Rust storage backend,
using ThreadPoolExecutor to run blocking calls without blocking the event loop.

Usage:
    storage = AsyncStorage()

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
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

# Import the Rust storage module
try:
    import balloons_storage
    RUST_STORAGE_AVAILABLE = True
except ImportError:
    RUST_STORAGE_AVAILABLE = False

from .debug_log import perf_timed, perf_marker, debug_log, Category

if TYPE_CHECKING:
    from session import Session
    from models import Turn, ContentBlock


# Default database path
# Note: LMDB uses a directory, not a single file (unlike redb)
DEFAULT_DB_PATH = Path.home() / ".balloons" / "sessions.lmdb"

# Shared storage handle (singleton pattern to avoid LMDB "already open" errors)
_shared_storage = None
_shared_storage_path = None


def _get_shared_storage(db_path: Path) -> "balloons_storage.Storage":
    """Get or create a shared storage handle.

    LMDB doesn't allow multiple opens with different options, so we need
    a single shared instance for the same database path.
    """
    global _shared_storage, _shared_storage_path

    if _shared_storage is not None and _shared_storage_path == db_path:
        return _shared_storage

    if not RUST_STORAGE_AVAILABLE:
        raise RuntimeError(
            "balloons_storage module not available. "
            "Run 'maturin develop' in balloons-rs/ to build it."
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    _shared_storage = balloons_storage.Storage(str(db_path))
    _shared_storage_path = db_path
    return _shared_storage


class AsyncStorage:
    """Async wrapper for Rust storage backend.

    Wraps the synchronous balloons_storage.Storage class with async methods,
    using a ThreadPoolExecutor to avoid blocking the asyncio event loop.

    The executor is shared across all AsyncStorage instances to limit thread usage.
    """

    # Shared executor for all instances (1 thread is enough for I/O-bound storage)
    _executor: ThreadPoolExecutor | None = None
    _executor_lock: asyncio.Lock | None = None

    def __init__(self, db_path: str | Path | None = None):
        """Initialize async storage.

        Args:
            db_path: Path to the database file. Defaults to ~/.balloons/sessions.db
        """
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        # Use shared storage handle to avoid LMDB "already open" errors
        self._storage = _get_shared_storage(self._db_path)

    @classmethod
    async def _get_executor(cls) -> ThreadPoolExecutor:
        """Get or create the shared thread pool executor."""
        if cls._executor is None:
            # Lazily create lock within async context to avoid event loop issues
            if cls._executor_lock is None:
                cls._executor_lock = asyncio.Lock()
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
        """Save a session to storage using incremental saves when possible.

        Incremental save strategy:
        1. Save session metadata only if _metadata_dirty
        2. Save only dirty turns (new or modified)
        3. Delete turns that were removed
        4. Reorder turns only if order changed

        Falls back to full replace_session_turns for new sessions (no saved order).

        Args:
            session: The Session object to save
        """
        import time
        start = time.perf_counter()

        # Check if this is a new session (never saved before)
        is_new_session = len(session._saved_turn_order) == 0

        if is_new_session:
            # New session: use full save (atomic batch)
            await self._full_save_session(session)
            save_type = "full"
            saved_turn_ids = None  # Full save handles all turns
        else:
            # Existing session: use incremental save
            save_type, saved_turn_ids = await self._incremental_save_session(session)

        # Mark saved items as clean
        # For incremental saves, only mark the turns that were actually saved
        # to avoid race conditions with turns added during the async save
        session.mark_saved_clean(saved_turn_ids)

        elapsed_ms = (time.perf_counter() - start) * 1000
        dirty_count = sum(1 for t in session.turns if t._dirty) if not is_new_session else len(session.turns)
        perf_marker(
            "storage.save_session",
            session_id=session.id[:8],
            turn_count=len(session.turns),
            save_type=save_type,
            dirty_turns=dirty_count,
            elapsed_ms=round(elapsed_ms, 1),
        )

    async def _full_save_session(self, session: Session) -> None:
        """Full save: session metadata + all turns atomically."""
        # Build the wire format data
        session_data = self._session_to_wire(session)
        session_json = json.dumps(session_data)

        # Build wire format for all turns
        turns_data = [self._turn_to_wire(turn) for turn in session.turns]
        turns_json = json.dumps(turns_data)

        # Debug: check if any turns have sentiment
        turns_with_sentiment = [(i, t.get('sentiment')) for i, t in enumerate(turns_data) if t.get('sentiment')]
        if turns_with_sentiment:
            from core.debug_log import debug_log
            debug_log.info(
                f"Saving session {session.id[:8]} with {len(turns_with_sentiment)} turns having sentiment: {turns_with_sentiment[:5]}",
                category=Category.STORAGE
            )

        # Save session metadata first (required for replace_session_turns)
        await self._run_sync(self._storage.save_session, session.id, session_json)

        # Atomically replace all turns (handles deletes, upserts, and ordering)
        await self._run_sync(self._storage.replace_session_turns, session.id, turns_json)

    async def _incremental_save_session(self, session: Session) -> tuple[str, set[str]]:
        """Incremental save: only write what changed.

        Returns a tuple of:
        - save_type: "none", "metadata", "turns", or "both"
        - saved_turn_ids: Set of turn IDs that were saved (for cleanup tracking)

        Note: We always save metadata since it's small and direct attribute
        assignments (like session.title = "x") don't trigger dirty tracking.
        The real performance win is from incremental turn saves.

        IMPORTANT: We take a snapshot of turns at the start to avoid race conditions.
        If new turns are added during the async save operations, they'll be picked up
        in the next save cycle. The snapshot ensures reorder_turns only references
        turns that were actually saved.
        """
        saved_metadata = False
        saved_turns = False

        # Take a snapshot of turn state at the start to avoid race conditions
        # This prevents reorder_turns from referencing turns added during save
        turns_snapshot = list(session.turns)
        dirty_turns = [t for t in turns_snapshot if t.is_dirty]
        deleted_ids = session.get_deleted_turn_ids()
        saved_turn_order = session._saved_turn_order.copy()

        # Track which turns we actually save
        saved_turn_ids = {t.id for t in turns_snapshot}

        # 1. Always save session metadata (small, and direct attribute changes
        # don't trigger dirty tracking without property setters)
        session_data = self._session_to_wire(session)
        session_json = json.dumps(session_data)
        await self._run_sync(self._storage.save_session, session.id, session_json)
        saved_metadata = True

        # 2. Delete removed turns
        # Note: We catch "Turn not found" errors because the turn may have already
        # been deleted (e.g., by a concurrent save or if the turn was never saved).
        # This makes deletion idempotent - trying to delete an already-deleted turn
        # is not an error.
        for turn_id in deleted_ids:
            try:
                await self._run_sync(self._storage.delete_turn, session.id, turn_id)
                saved_turns = True
            except Exception as e:
                if "Turn not found" in str(e):
                    # Turn already deleted or never saved - this is fine
                    debug_log.debug(
                        f"Turn {turn_id[:8]} already deleted or never saved, skipping",
                        category=Category.STORAGE,
                        session_id=session.id,
                    )
                else:
                    raise  # Re-raise unexpected errors

        # 3. Save dirty turns (new or modified)
        for turn in dirty_turns:
            turn_data = self._turn_to_wire(turn)
            turn_json = json.dumps(turn_data)
            await self._run_sync(self._storage.save_turn, session.id, turn_json)
            saved_turns = True

        # 4. Reorder turns if order changed
        # Build the new turn order based on what we know exists in the DB:
        # - Turns from saved_turn_order (what was in DB when we loaded)
        # - Plus turns we just saved (dirty_turns)
        # - In the order they appear in our snapshot
        #
        # We cannot include turns that:
        # - Were added by another server instance (not in our saved_turn_order or dirty_turns)
        # - Were deleted (in deleted_ids)
        #
        # This prevents "Turn not found" errors when another server instance
        # modified the same session concurrently.
        dirty_turn_ids = {t.id for t in dirty_turns}
        known_turn_ids = set(saved_turn_order) | dirty_turn_ids

        # Filter snapshot_order to only include turns we know exist in the DB
        safe_snapshot_order = [
            t.id for t in turns_snapshot
            if t.id in known_turn_ids and t.id not in deleted_ids
        ]

        if safe_snapshot_order != saved_turn_order:
            order_json = json.dumps(safe_snapshot_order)
            try:
                await self._run_sync(self._storage.reorder_turns, session.id, order_json)
                saved_turns = True
            except Exception as e:
                if "Turn not found" in str(e):
                    # Race condition: another server modified the turn order.
                    # Log and continue - the other server's order will persist.
                    debug_log.warning(
                        f"reorder_turns failed due to concurrent modification, skipping: {e}",
                        category=Category.STORAGE,
                        session_id=session.id,
                    )
                else:
                    raise

        if saved_metadata and saved_turns:
            save_type = "both"
        elif saved_metadata:
            save_type = "metadata"
        elif saved_turns:
            save_type = "turns"
        else:
            save_type = "none"

        return save_type, saved_turn_ids

    async def load_session(self, session_id: str) -> Optional[Session]:
        """Load a session from storage.

        Uses split storage model:
        1. Load session metadata from SESSIONS table
        2. Load turns from TURNS table via TURN_ORDER

        After loading, session is marked clean (no pending saves).

        Args:
            session_id: The session ID to load

        Returns:
            The Session object, or None if not found
        """
        import time
        start = time.perf_counter()

        json_data = await self._run_sync(self._storage.load_session, session_id)
        if json_data is None:
            return None

        data = json.loads(json_data)
        session = self._wire_to_session(data)

        # Load turns separately
        turns_data = await self.load_turns(session_id)
        for turn_data in turns_data:
            turn = self._wire_to_turn(turn_data)
            session.turns.append(turn)

        # Ensure cached_context_tokens is populated from turn data if it was 0
        # This handles sessions saved before token caching was implemented
        if session.cached_context_tokens == 0 and session.turns:
            session.cached_context_tokens = session.calculate_context_tokens()
            # Mark as dirty so the calculated value gets persisted
            session._metadata_dirty = True
        else:
            # Initialize dirty tracking state - session is clean after load
            session._metadata_dirty = False

        session._deleted_turn_ids = set()
        session._saved_turn_order = [t.id for t in session.turns]

        elapsed_ms = (time.perf_counter() - start) * 1000
        perf_marker(
            "storage.load_session",
            session_id=session_id[:8],
            turn_count=len(session.turns),
            elapsed_ms=round(elapsed_ms, 1),
        )

        return session

    async def delete_session(self, session_id: str) -> None:
        """Delete a session from storage.

        Args:
            session_id: The session ID to delete
        """
        await self._run_sync(self._storage.delete_session, session_id)

    async def list_sessions(self) -> list[dict]:
        """List all sessions with metadata.

        Returns:
            List of session metadata dicts sorted by updated_at (most recent first).
            Each dict has keys:
            - id: Session ID
            - name: Session title
            - created_at: Unix timestamp (seconds)
            - updated_at: Unix timestamp (seconds)
            - turn_count: Number of turns
        """
        json_data = await self._run_sync(self._storage.list_sessions)
        sessions = json.loads(json_data)
        # Sort by updated_at descending (most recently modified first)
        sessions.sort(key=lambda s: s.get("updated_at", 0), reverse=True)
        return sessions

    # =========================================================================
    # Review Operations (file-based for now, pending Rust integration)
    # =========================================================================

    async def save_review(self, review: "ReviewData") -> None:
        """Save a session quality review to storage.

        Uses file-based storage under ~/.balloons/reviews/ for now.
        Will migrate to Rust storage in a future version.

        Args:
            review: The ReviewData object to save
        """
        from storage_schema import ReviewData
        from dataclasses import asdict
        import aiofiles

        reviews_dir = Path.home() / ".balloons" / "reviews"
        reviews_dir.mkdir(parents=True, exist_ok=True)

        review_path = reviews_dir / f"{review.id}.json"
        review_data = asdict(review)
        review_json = json.dumps(review_data, indent=2)

        async with aiofiles.open(review_path, "w", encoding="utf-8") as f:
            await f.write(review_json)

    async def load_review(self, review_id: str) -> Optional["ReviewData"]:
        """Load a review from storage.

        Args:
            review_id: The review ID to load

        Returns:
            The ReviewData object, or None if not found
        """
        from storage_schema import ReviewData
        import aiofiles

        reviews_dir = Path.home() / ".balloons" / "reviews"
        review_path = reviews_dir / f"{review_id}.json"

        if not review_path.exists():
            return None

        try:
            async with aiofiles.open(review_path, "r", encoding="utf-8") as f:
                review_json = await f.read()
            data = json.loads(review_json)
            return ReviewData(**data)
        except Exception:
            return None

    async def list_reviews(self, session_id: str | None = None) -> list[dict]:
        """List reviews, optionally filtered by session.

        Args:
            session_id: Optional session ID to filter by

        Returns:
            List of review metadata dicts
        """
        import aiofiles

        reviews_dir = Path.home() / ".balloons" / "reviews"
        if not reviews_dir.exists():
            return []

        reviews = []
        for review_file in reviews_dir.glob("*.json"):
            try:
                async with aiofiles.open(review_file, "r", encoding="utf-8") as f:
                    review_json = await f.read()
                data = json.loads(review_json)
                if session_id is None or data.get("session_id") == session_id:
                    reviews.append({
                        "id": data.get("id"),
                        "session_id": data.get("session_id"),
                        "reviewed_at": data.get("reviewed_at"),
                        "model_under_review": data.get("model_under_review"),
                        "task_category": data.get("task_category"),
                    })
            except Exception:
                continue

        # Sort by reviewed_at, most recent first
        reviews.sort(key=lambda r: r.get("reviewed_at", ""), reverse=True)
        return reviews

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

    async def get_turn_count(self, session_id: str) -> int:
        """Get the number of turns for a session without loading turn data.

        Args:
            session_id: The session to count turns for

        Returns:
            Number of turns in the session (0 if session has no turns)
        """
        return await self._run_sync(self._storage.get_turn_count, session_id)

    async def load_turns_range(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        """Load a range of turns for a session (for chunked/paginated loading).

        Args:
            session_id: The session to load turns from
            offset: Starting index (0-indexed, oldest first)
            limit: Maximum number of turns to return

        Returns:
            List of turn data dicts in order
        """
        json_data = await self._run_sync(
            self._storage.load_turns_range, session_id, offset, limit
        )
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
    # Session History Operations
    # =========================================================================

    async def load_session_history(self) -> list[str]:
        """Load session history (most recently viewed sessions first).

        Returns:
            List of session IDs in order of most recent access
        """
        json_data = await self._run_sync(self._storage.load_session_history)
        return json.loads(json_data)

    async def save_session_history(self, session_ids: list[str]) -> None:
        """Save session history.

        Args:
            session_ids: List of session IDs in order of most recent access
        """
        json_data = json.dumps(session_ids)
        await self._run_sync(self._storage.save_session_history, json_data)

    # =========================================================================
    # Wire Format Conversion
    # =========================================================================

    def _session_to_wire(self, session: Session) -> dict:
        """Convert a Session to the wire format for storage.

        This matches the SessionData schema expected by Rust.
        Note: turns are NOT included - they are stored separately in the TURNS table.
        """
        return {
            "id": session.id,
            "created": session.created,
            "last_modified": session.last_modified,
            "model": session.model,
            # NOTE: turns are stored separately, not embedded in session data
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
        Turn now has a persistent `id` field, so we use that directly.
        """
        return {
            "id": turn.id,  # Turn.id is always set (generated on creation)
            "role": turn.role,
            "content_block": self._serialize_content_block(turn.content_block),
            "tokens": turn.tokens,
            "timestamp": turn.timestamp,
            "context_mode": turn.context_mode.value,
            "summary": turn.summary,
            "exchange_id": turn.exchange_id,
            "sentiment": turn.sentiment.value if turn.sentiment else None,
            "started_at": turn.started_at,
            "ended_at": turn.ended_at,
        }

    def _serialize_content_block(self, block: ContentBlock) -> dict:
        """Serialize a content block to a dict.

        This matches the JSON structure expected by Rust's serde_json::Value.
        """
        from models import (
            TextBlock, MarkdownBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock,
            ErrorBlock, LinkBlock, ForkBlock, MergeBlock, MergedToBlock,
            ArchiveBlock, SlideBlock, ReviewBlock, ForkProposalBlock, MergeProposalBlock
        )

        if isinstance(block, TextBlock):
            return {"type": "text", "text": block.text}
        elif isinstance(block, MarkdownBlock):
            return {"type": "markdown", "text": block.text}
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
                "files_changed": block.files_changed,
                "key_accomplishments": block.key_accomplishments,
                "reason": block.reason,
            }
        elif isinstance(block, MergedToBlock):
            return {
                "type": "merged_to",
                "merge_id": block.merge_id,
                "parent_session_id": block.parent_session_id,
                "parent_name": block.parent_name,
                "parent_turn": block.parent_turn,
                "message": block.message,
                "files_changed": block.files_changed,
                "key_accomplishments": block.key_accomplishments,
                "reason": block.reason,
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
        elif isinstance(block, ReviewBlock):
            return {
                "type": "review",
                "review_id": block.review_id,
                "child_session_id": block.child_session_id,
                "model_under_review": block.model_under_review,
                "status": block.status,
                "overall_score": block.overall_score,
                "task_category": block.task_category,
                "task_description": block.task_description,
            }
        elif isinstance(block, ForkProposalBlock):
            return {
                "type": "fork_proposal",
                "proposal_id": block.proposal_id,
                "name": block.name,
                "description": block.description,
                "context_plan": [
                    {
                        "exchange_range": cp.exchange_range,
                        "mode": cp.mode,
                        "reason": cp.reason,
                    }
                    for cp in block.context_plan
                ],
                "initial_prompt": block.initial_prompt,
                "bind_to": {
                    "entity_type": block.bind_to.entity_type,
                    "entity_id": block.bind_to.entity_id,
                    "role": block.bind_to.role,
                } if block.bind_to else None,
                "bind_to_inherit": block.bind_to_inherit,
                "status": block.status,
                "child_session_id": block.child_session_id,
                "all_exchanges": [
                    {
                        "index": ex.index,
                        "summary": ex.summary,
                        "mode": ex.mode,
                    }
                    for ex in block.all_exchanges
                ],
            }
        elif isinstance(block, MergeProposalBlock):
            return {
                "type": "merge_proposal",
                "proposal_id": block.proposal_id,
                "summary": block.summary,
                "reason": block.reason,
                "files_changed": block.files_changed,
                "key_accomplishments": block.key_accomplishments,
                "status": block.status,
            }
        return {"type": "unknown"}

    def _wire_to_session(self, data: dict) -> Session:
        """Convert wire format data to a Session object.

        This is the inverse of _session_to_wire.
        Note: turns are NOT included in data - they are loaded separately.
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
            context_window=data.get("context_window", 150000),
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

        # NOTE: turns are loaded separately via load_turns() and appended by the caller

        return session

    def _wire_to_turn(self, data: dict) -> Turn:
        """Convert wire format turn data to a Turn object.

        Loaded turns start clean (not dirty) since they're fresh from storage.
        """
        from models import Turn, ContextMode, Sentiment

        content_block = self._deserialize_content_block(data.get("content_block", {"type": "text", "text": ""}))

        mode_str = data.get("context_mode", "compress")
        try:
            context_mode = ContextMode(mode_str)
        except ValueError:
            context_mode = ContextMode.COMPRESS

        # Parse sentiment if present
        sentiment = None
        sentiment_str = data.get("sentiment")
        if sentiment_str:
            try:
                sentiment = Sentiment(sentiment_str)
            except ValueError:
                pass  # Invalid sentiment value, leave as None

        # Get turn ID from storage, or generate a new one for legacy data
        turn_id = data.get("id")
        if not turn_id:
            # Generate deterministic ID from content for backwards compat
            import hashlib
            content_str = json.dumps(self._serialize_content_block(content_block), sort_keys=True)
            content_hash = hashlib.md5(content_str.encode()).hexdigest()[:8]
            timestamp = data.get("timestamp", "")
            turn_id = f"{timestamp[:19].replace(':', '-').replace('T', '_')}_{content_hash}"

        turn = Turn(
            role=data["role"],
            content_block=content_block,
            tokens=data.get("tokens", 0),
            timestamp=data.get("timestamp", ""),
            context_mode=context_mode,
            summary=data.get("summary", ""),
            exchange_id=data.get("exchange_id"),
            sentiment=sentiment,
            started_at=data.get("started_at"),
            ended_at=data.get("ended_at"),
            id=turn_id,
            # Loaded turns start clean - they're fresh from storage
            _dirty=False,
        )
        return turn

    def _deserialize_content_block(self, data: dict) -> ContentBlock:
        """Deserialize a content block from a dict."""
        from models import (
            TextBlock, MarkdownBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock,
            ErrorBlock, LinkBlock, ForkBlock, MergeBlock, ArchiveBlock, SlideBlock,
            ReviewBlock, ArchiveSummary, ForkProposalBlock, MergeProposalBlock,
            ContextAssignmentData, ForkBindingData, ExchangeInfo
        )

        block_type = data.get("type", "text")

        if block_type == "text":
            return TextBlock(text=data.get("text", ""))
        elif block_type == "markdown":
            return MarkdownBlock(text=data.get("text", ""))
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
                files_changed=data.get("files_changed", []),
                key_accomplishments=data.get("key_accomplishments", []),
                reason=data.get("reason", ""),
            )
        elif block_type == "merged_to":
            from models import MergedToBlock
            return MergedToBlock(
                merge_id=data.get("merge_id", ""),
                parent_session_id=data.get("parent_session_id", ""),
                parent_name=data.get("parent_name", ""),
                parent_turn=data.get("parent_turn", 0),
                message=data.get("message", ""),
                files_changed=data.get("files_changed", []),
                key_accomplishments=data.get("key_accomplishments", []),
                reason=data.get("reason", ""),
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
        elif block_type == "review":
            return ReviewBlock(
                review_id=data.get("review_id", ""),
                child_session_id=data.get("child_session_id", ""),
                model_under_review=data.get("model_under_review", ""),
                status=data.get("status", "active"),
                overall_score=data.get("overall_score", 0.0),
                task_category=data.get("task_category", ""),
                task_description=data.get("task_description", ""),
            )
        elif block_type == "fork_proposal":
            # Deserialize context_plan
            context_plan = []
            for cp in data.get("context_plan", []):
                context_plan.append(ContextAssignmentData(
                    exchange_range=cp.get("exchange_range", ""),
                    mode=cp.get("mode", "copy"),
                    reason=cp.get("reason", ""),
                ))
            # Deserialize bind_to
            bind_to = None
            if data.get("bind_to"):
                bt = data["bind_to"]
                bind_to = ForkBindingData(
                    entity_type=bt.get("entity_type", ""),
                    entity_id=bt.get("entity_id", ""),
                    role=bt.get("role", ""),
                )
            # Deserialize all_exchanges
            all_exchanges = []
            for ex in data.get("all_exchanges", []):
                all_exchanges.append(ExchangeInfo(
                    index=ex.get("index", 0),
                    summary=ex.get("summary", ""),
                    mode=ex.get("mode", "compress"),
                ))
            return ForkProposalBlock(
                proposal_id=data.get("proposal_id", ""),
                name=data.get("name", ""),
                description=data.get("description", ""),
                context_plan=context_plan,
                initial_prompt=data.get("initial_prompt", ""),
                bind_to=bind_to,
                bind_to_inherit=data.get("bind_to_inherit", False),
                status=data.get("status", "pending"),
                child_session_id=data.get("child_session_id", ""),
                all_exchanges=all_exchanges,
            )
        elif block_type == "merge_proposal":
            return MergeProposalBlock(
                proposal_id=data.get("proposal_id", ""),
                summary=data.get("summary", ""),
                reason=data.get("reason", ""),
                files_changed=data.get("files_changed", []),
                key_accomplishments=data.get("key_accomplishments", []),
                status=data.get("status", "pending"),
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

    Uses the default database path (~/.balloons/sessions.db).
    """
    return AsyncStorage(DEFAULT_DB_PATH)


# =============================================================================
# Goal-Oriented Task Management Storage
# =============================================================================


class GoalStorage:
    """Async wrapper for goal-oriented task management storage using Rust backend.

    Provides an async interface to the synchronous Rust storage backend,
    using ThreadPoolExecutor to run blocking calls without blocking the event loop.

    Stores Goals, Plans, Todos, and their relationships in the LMDB database.
    """

    # Shared executor for all instances (same pattern as AsyncStorage)
    _executor: ThreadPoolExecutor | None = None
    _executor_lock: asyncio.Lock | None = None

    def __init__(self, db_path: str | Path | None = None):
        """Initialize goal storage.

        Args:
            db_path: Path to the database file. Defaults to ~/.balloons/sessions.lmdb
        """
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        # Use shared storage handle to avoid LMDB "already open" errors
        self._storage = _get_shared_storage(self._db_path)

    @classmethod
    async def _get_executor(cls) -> ThreadPoolExecutor:
        """Get or create the shared thread pool executor."""
        if cls._executor is None:
            # Lazily create lock within async context to avoid event loop issues
            if cls._executor_lock is None:
                cls._executor_lock = asyncio.Lock()
            async with cls._executor_lock:
                if cls._executor is None:
                    # Single thread is sufficient for sequential storage ops
                    cls._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="goal_storage")
        return cls._executor

    async def _run_sync(self, func, *args):
        """Run a synchronous function in the thread pool."""
        executor = await self._get_executor()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, func, *args)

    # =========================================================================
    # Goals CRUD
    # =========================================================================

    async def save_goal(self, goal: "GoalData") -> None:
        """Save a goal to storage."""
        from dataclasses import asdict

        goal_json = json.dumps(asdict(goal))
        await self._run_sync(self._storage.save_goal, goal_json)

    async def load_goal(self, goal_id: str) -> Optional["GoalData"]:
        """Load a goal from storage."""
        from storage_schema import GoalData

        json_data = await self._run_sync(self._storage.load_goal, goal_id)
        if json_data is None:
            return None

        try:
            data = json.loads(json_data)
            return GoalData(**data)
        except Exception:
            return None

    async def delete_goal(self, goal_id: str) -> None:
        """Delete a goal from storage."""
        await self._run_sync(self._storage.delete_goal, goal_id)

    async def list_goals(self, status: str | None = None) -> list["GoalData"]:
        """List all goals, optionally filtered by status."""
        from storage_schema import GoalData

        json_data = await self._run_sync(self._storage.list_goals)
        all_goals = json.loads(json_data)

        goals = []
        for data in all_goals:
            try:
                goal = GoalData(**data)
                if status is None or goal.status == status:
                    goals.append(goal)
            except Exception:
                continue

        # Sort by weight (descending) then created_at
        goals.sort(key=lambda g: (-g.weight, g.created_at))
        return goals

    # =========================================================================
    # Plans CRUD
    # =========================================================================

    async def save_plan(self, plan: "PlanData") -> None:
        """Save a plan to storage."""
        from dataclasses import asdict

        plan_json = json.dumps(asdict(plan))
        await self._run_sync(self._storage.save_plan, plan_json)

    async def load_plan(self, plan_id: str) -> Optional["PlanData"]:
        """Load a plan from storage."""
        from storage_schema import PlanData

        json_data = await self._run_sync(self._storage.load_plan, plan_id)
        if json_data is None:
            return None

        try:
            data = json.loads(json_data)
            return PlanData(**data)
        except Exception:
            return None

    async def delete_plan(self, plan_id: str) -> None:
        """Delete a plan from storage."""
        await self._run_sync(self._storage.delete_plan, plan_id)

    async def list_plans(self, goal_id: str | None = None, status: str | None = None) -> list["PlanData"]:
        """List plans, optionally filtered by goal and/or status."""
        from storage_schema import PlanData

        # Rust backend supports goal_id filtering
        json_data = await self._run_sync(self._storage.list_plans, goal_id)
        all_plans = json.loads(json_data)

        plans = []
        for data in all_plans:
            try:
                plan = PlanData(**data)
                # Apply status filter in Python (Rust doesn't filter by status)
                if status is None or plan.status == status:
                    plans.append(plan)
            except Exception:
                continue

        plans.sort(key=lambda p: p.created_at)
        return plans

    # =========================================================================
    # Todos CRUD
    # =========================================================================

    async def save_todo(self, todo: "TodoData") -> None:
        """Save a todo to storage."""
        from dataclasses import asdict

        todo_json = json.dumps(asdict(todo))
        await self._run_sync(self._storage.save_todo, todo_json)

    async def load_todo(self, todo_id: str) -> Optional["TodoData"]:
        """Load a todo from storage."""
        from storage_schema import TodoData

        json_data = await self._run_sync(self._storage.load_todo, todo_id)
        if json_data is None:
            return None

        try:
            data = json.loads(json_data)
            return TodoData(**data)
        except Exception:
            return None

    async def delete_todo(self, todo_id: str) -> None:
        """Delete a todo from storage."""
        await self._run_sync(self._storage.delete_todo, todo_id)

    async def list_todos(self, status: str | None = None, include_spikes: bool = True) -> list["TodoData"]:
        """List all todos, optionally filtered by status."""
        from storage_schema import TodoData

        # Rust backend can filter by plan_id but we want all todos here
        json_data = await self._run_sync(self._storage.list_todos, None)
        all_todos = json.loads(json_data)

        todos = []
        for data in all_todos:
            try:
                todo = TodoData(**data)
                if (status is None or todo.status == status) and \
                   (include_spikes or not todo.is_spike):
                    todos.append(todo)
            except Exception:
                continue

        todos.sort(key=lambda t: t.created_at)
        return todos

    # =========================================================================
    # Todo-Plan Links
    # =========================================================================

    async def save_todo_plan_link(self, link: "TodoPlanLink") -> None:
        """Save a todo-plan link."""
        from dataclasses import asdict

        link_json = json.dumps(asdict(link))
        await self._run_sync(self._storage.save_todo_plan_link, link_json)

    async def delete_todo_plan_link(self, todo_id: str, plan_id: str) -> None:
        """Delete a todo-plan link."""
        await self._run_sync(self._storage.delete_todo_plan_link, todo_id, plan_id)

    async def get_plans_for_todo(self, todo_id: str) -> list[str]:
        """Get all plan IDs linked to a todo."""
        # Rust returns full PlanData objects, we extract IDs for compatibility
        json_data = await self._run_sync(self._storage.get_plans_for_todo, todo_id)
        plans = json.loads(json_data)
        return [p["id"] for p in plans]

    async def get_todos_for_plan(self, plan_id: str) -> list[str]:
        """Get all todo IDs linked to a plan."""
        # Rust returns full TodoData objects, we extract IDs for compatibility
        json_data = await self._run_sync(self._storage.get_todos_for_plan, plan_id)
        todos = json.loads(json_data)
        return [t["id"] for t in todos]

    # =========================================================================
    # Todo Dependencies
    # =========================================================================

    async def save_todo_dependency(self, dep: "TodoDependency") -> None:
        """Save a todo dependency."""
        from dataclasses import asdict

        dep_json = json.dumps(asdict(dep))
        await self._run_sync(self._storage.save_todo_dependency, dep_json)

    async def delete_todo_dependency(self, todo_id: str, depends_on_id: str) -> None:
        """Delete a todo dependency."""
        await self._run_sync(self._storage.delete_todo_dependency, todo_id, depends_on_id)

    async def get_dependencies(self, todo_id: str) -> list[str]:
        """Get all todo IDs that a todo depends on."""
        # Rust returns full TodoData objects, we extract IDs for compatibility
        json_data = await self._run_sync(self._storage.get_dependencies, todo_id)
        todos = json.loads(json_data)
        return [t["id"] for t in todos]

    async def get_dependents(self, todo_id: str) -> list[str]:
        """Get all todo IDs that depend on a todo."""
        # Rust returns full TodoData objects, we extract IDs for compatibility
        json_data = await self._run_sync(self._storage.get_dependents, todo_id)
        todos = json.loads(json_data)
        return [t["id"] for t in todos]

    # =========================================================================
    # Session Bindings
    # =========================================================================

    async def save_session_binding(self, binding: "SessionBinding") -> None:
        """Save a session binding."""
        from dataclasses import asdict

        binding_json = json.dumps(asdict(binding))
        await self._run_sync(self._storage.save_session_binding, binding_json)

    async def load_session_binding(self, binding_id: str) -> Optional["SessionBinding"]:
        """Load a session binding."""
        from storage_schema import SessionBinding

        json_data = await self._run_sync(self._storage.load_session_binding, binding_id)
        if json_data is None:
            return None

        try:
            data = json.loads(json_data)
            return SessionBinding(**data)
        except Exception:
            return None

    async def delete_session_binding(self, binding_id: str) -> None:
        """Delete a session binding."""
        await self._run_sync(self._storage.delete_session_binding, binding_id)

    async def get_bindings_for_session(self, session_id: str, active_only: bool = True) -> list["SessionBinding"]:
        """Get all bindings for a session."""
        from storage_schema import SessionBinding

        json_data = await self._run_sync(self._storage.get_bindings_for_session, session_id)
        all_bindings = json.loads(json_data)

        bindings = []
        for data in all_bindings:
            try:
                binding = SessionBinding(**data)
                if not active_only or binding.released_at is None:
                    bindings.append(binding)
            except Exception:
                continue

        bindings.sort(key=lambda b: b.created_at)
        return bindings

    async def get_bindings_for_entity(self, entity_type: str, entity_id: str, active_only: bool = True) -> list["SessionBinding"]:
        """Get all bindings for an entity."""
        from storage_schema import SessionBinding

        json_data = await self._run_sync(self._storage.get_bindings_for_entity, entity_type, entity_id)
        all_bindings = json.loads(json_data)

        bindings = []
        for data in all_bindings:
            try:
                binding = SessionBinding(**data)
                if not active_only or binding.released_at is None:
                    bindings.append(binding)
            except Exception:
                continue

        bindings.sort(key=lambda b: b.created_at)
        return bindings

    async def list_bindings(self, active_only: bool = True) -> list["SessionBinding"]:
        """List all session bindings.

        Args:
            active_only: If True, only return bindings that haven't been released.

        Returns:
            List of all session bindings, sorted by created_at.
        """
        from storage_schema import SessionBinding

        json_data = await self._run_sync(self._storage.list_bindings)
        all_bindings = json.loads(json_data)

        bindings = []
        for data in all_bindings:
            try:
                binding = SessionBinding(**data)
                if not active_only or binding.released_at is None:
                    bindings.append(binding)
            except Exception:
                continue

        bindings.sort(key=lambda b: b.created_at)
        return bindings

    # =========================================================================
    # Hierarchy Traversal
    # =========================================================================

    async def get_hierarchy(
        self,
        entity_type: str,
        entity_id: str,
        include_bindings: bool = True,
        include_dependencies: bool = True,
    ) -> "EntityHierarchy":
        """Get the complete hierarchy for an entity.

        Traverses relationships to build a list of all related entities:
        - For a todo: traverses up to plans and goal, plus dependencies
        - For a plan: traverses up to goal and down to todos
        - For a goal: traverses down to plans and todos

        Watches for cycles in todo dependencies and reports them.

        Args:
            entity_type: "goal", "plan", or "todo"
            entity_id: The entity ID (can be prefix)
            include_bindings: Whether to include session bindings
            include_dependencies: Whether to traverse todo dependencies

        Returns:
            EntityHierarchy with all related entities
        """
        from storage_schema import GoalData, PlanData, TodoData, TodoPlanLink, TodoDependency, SessionBinding

        # Resolve entity by prefix
        resolved_id = await self._resolve_entity_id(entity_type, entity_id)
        if not resolved_id:
            # Return empty hierarchy if not found
            return EntityHierarchy(entity_type=entity_type, entity_id=entity_id)

        entity_id = resolved_id

        # Initialize result
        result = EntityHierarchy(entity_type=entity_type, entity_id=entity_id)

        # Track visited entities to detect cycles
        visited_goals: set[str] = set()
        visited_plans: set[str] = set()
        visited_todos: set[str] = set()

        # Collect entities
        goals_map: dict[str, GoalData] = {}
        plans_map: dict[str, PlanData] = {}
        todos_map: dict[str, TodoData] = {}

        if entity_type == "todo":
            await self._traverse_from_todo(
                entity_id, goals_map, plans_map, todos_map, result,
                visited_todos, include_dependencies
            )
        elif entity_type == "plan":
            await self._traverse_from_plan(
                entity_id, goals_map, plans_map, todos_map, result,
                visited_todos, include_dependencies
            )
        elif entity_type == "goal":
            await self._traverse_from_goal(
                entity_id, goals_map, plans_map, todos_map, result,
                visited_todos, include_dependencies
            )

        # Set the goal (there should be at most one)
        if goals_map:
            result.goal = list(goals_map.values())[0]

        # Set collections
        result.plans = list(plans_map.values())
        result.todos = list(todos_map.values())

        # Get all todo-plan links for the collected entities
        for todo_id in todos_map:
            plan_ids = await self.get_plans_for_todo(todo_id)
            for plan_id in plan_ids:
                # Only include links to plans in our hierarchy
                if plan_id in plans_map:
                    link = TodoPlanLink(
                        todo_id=todo_id,
                        plan_id=plan_id,
                        created_at=""  # We don't have the original timestamp
                    )
                    result.todo_plan_links.append(link)

        # Collect bindings if requested
        if include_bindings:
            entity_ids = []
            if result.goal:
                entity_ids.append(("goal", result.goal.id))
            for plan in result.plans:
                entity_ids.append(("plan", plan.id))
            for todo in result.todos:
                entity_ids.append(("todo", todo.id))

            for etype, eid in entity_ids:
                bindings = await self.get_bindings_for_entity(etype, eid, active_only=True)
                result.bindings.extend(bindings)

        return result

    async def _resolve_entity_id(self, entity_type: str, entity_id: str) -> Optional[str]:
        """Resolve an entity ID that may be a prefix to its full ID."""
        if entity_type == "goal":
            goals = await self.list_goals()
            for g in goals:
                if g.id.startswith(entity_id) or g.id == entity_id:
                    return g.id
        elif entity_type == "plan":
            plans = await self.list_plans()
            for p in plans:
                if p.id.startswith(entity_id) or p.id == entity_id:
                    return p.id
        elif entity_type == "todo":
            todos = await self.list_todos(include_spikes=True)
            for t in todos:
                if t.id.startswith(entity_id) or t.id == entity_id:
                    return t.id
        return None

    async def _traverse_from_todo(
        self,
        todo_id: str,
        goals_map: dict[str, "GoalData"],
        plans_map: dict[str, "PlanData"],
        todos_map: dict[str, "TodoData"],
        result: "EntityHierarchy",
        visited_todos: set[str],
        include_dependencies: bool,
        dependency_path: list[str] = None,
    ) -> None:
        """Traverse hierarchy starting from a todo.

        Goes up to plans and goal, and optionally traverses dependencies.
        """
        from storage_schema import TodoDependency

        # Check for cycle
        if dependency_path is None:
            dependency_path = []

        if todo_id in dependency_path:
            # Cycle detected!
            result.cycle_detected = True
            cycle_start = dependency_path.index(todo_id)
            result.cycle_path = dependency_path[cycle_start:] + [todo_id]
            return

        if todo_id in visited_todos:
            return

        visited_todos.add(todo_id)

        # Load the todo
        todo = await self.load_todo(todo_id)
        if not todo:
            return

        todos_map[todo_id] = todo

        # Get parent plans
        plan_ids = await self.get_plans_for_todo(todo_id)
        for plan_id in plan_ids:
            if plan_id not in plans_map:
                plan = await self.load_plan(plan_id)
                if plan:
                    plans_map[plan_id] = plan
                    # Get parent goal
                    if plan.goal_id and plan.goal_id not in goals_map:
                        goal = await self.load_goal(plan.goal_id)
                        if goal:
                            goals_map[plan.goal_id] = goal

        # Traverse dependencies if requested
        if include_dependencies:
            dep_ids = await self.get_dependencies(todo_id)
            for dep_id in dep_ids:
                # Record the dependency
                dep = TodoDependency(
                    todo_id=todo_id,
                    depends_on_id=dep_id,
                    created_at=""
                )
                result.dependencies.append(dep)

                # Recursively traverse, passing the current path for cycle detection
                await self._traverse_from_todo(
                    dep_id, goals_map, plans_map, todos_map, result,
                    visited_todos, include_dependencies,
                    dependency_path + [todo_id]
                )

            # Also get dependents (things that depend on this todo)
            dependent_ids = await self.get_dependents(todo_id)
            for dependent_id in dependent_ids:
                dep = TodoDependency(
                    todo_id=dependent_id,
                    depends_on_id=todo_id,
                    created_at=""
                )
                # Only add if not already present
                if not any(d.todo_id == dep.todo_id and d.depends_on_id == dep.depends_on_id
                           for d in result.dependencies):
                    result.dependencies.append(dep)

                # Traverse dependent todos (but not their dependencies to avoid explosion)
                if dependent_id not in visited_todos:
                    visited_todos.add(dependent_id)
                    dependent_todo = await self.load_todo(dependent_id)
                    if dependent_todo:
                        todos_map[dependent_id] = dependent_todo

    async def _traverse_from_plan(
        self,
        plan_id: str,
        goals_map: dict[str, "GoalData"],
        plans_map: dict[str, "PlanData"],
        todos_map: dict[str, "TodoData"],
        result: "EntityHierarchy",
        visited_todos: set[str],
        include_dependencies: bool,
    ) -> None:
        """Traverse hierarchy starting from a plan.

        Goes up to goal and down to todos.
        """
        # Load the plan
        plan = await self.load_plan(plan_id)
        if not plan:
            return

        plans_map[plan_id] = plan

        # Get parent goal
        if plan.goal_id and plan.goal_id not in goals_map:
            goal = await self.load_goal(plan.goal_id)
            if goal:
                goals_map[plan.goal_id] = goal

        # Get child todos
        todo_ids = await self.get_todos_for_plan(plan_id)
        for todo_id in todo_ids:
            await self._traverse_from_todo(
                todo_id, goals_map, plans_map, todos_map, result,
                visited_todos, include_dependencies
            )

    async def _traverse_from_goal(
        self,
        goal_id: str,
        goals_map: dict[str, "GoalData"],
        plans_map: dict[str, "PlanData"],
        todos_map: dict[str, "TodoData"],
        result: "EntityHierarchy",
        visited_todos: set[str],
        include_dependencies: bool,
    ) -> None:
        """Traverse hierarchy starting from a goal.

        Goes down to plans and todos.
        """
        # Load the goal
        goal = await self.load_goal(goal_id)
        if not goal:
            return

        goals_map[goal_id] = goal

        # Get child plans
        plans = await self.list_plans(goal_id=goal_id)
        for plan in plans:
            plans_map[plan.id] = plan

            # Get todos for each plan
            todo_ids = await self.get_todos_for_plan(plan.id)
            for todo_id in todo_ids:
                await self._traverse_from_todo(
                    todo_id, goals_map, plans_map, todos_map, result,
                    visited_todos, include_dependencies
                )


@dataclass
class EntityHierarchy:
    """Complete hierarchy for an entity.

    Contains the entity itself plus all related entities traversed
    upward (parents) and downward (children) in the goal→plan→todo
    hierarchy.

    Attributes:
        entity_type: The type of the root entity ("goal", "plan", or "todo")
        entity_id: The ID of the root entity
        goal: The goal at the top of the hierarchy (None if not found)
        plans: All plans in the hierarchy
        todos: All todos in the hierarchy
        todo_plan_links: Links between todos and plans
        dependencies: Todo dependencies found
        bindings: Session bindings for all entities in hierarchy
        cycle_detected: True if a cycle was detected during traversal
        cycle_path: If cycle detected, the path of entity IDs that form the cycle
    """
    entity_type: str
    entity_id: str
    goal: Optional["GoalData"] = None
    plans: list["PlanData"] = field(default_factory=list)
    todos: list["TodoData"] = field(default_factory=list)
    todo_plan_links: list["TodoPlanLink"] = field(default_factory=list)
    dependencies: list["TodoDependency"] = field(default_factory=list)
    bindings: list["SessionBinding"] = field(default_factory=list)
    cycle_detected: bool = False
    cycle_path: list[str] = field(default_factory=list)


# Singleton instance for GoalStorage
_goal_storage_instance: GoalStorage | None = None


async def get_goal_storage() -> GoalStorage:
    """Get the default GoalStorage instance (singleton).

    Uses the default database path (~/.balloons/sessions.lmdb).
    Returns the same instance on subsequent calls to avoid LMDB conflicts.
    """
    global _goal_storage_instance
    if _goal_storage_instance is None:
        _goal_storage_instance = GoalStorage(DEFAULT_DB_PATH)
    return _goal_storage_instance


# =============================================================================
# User Preferences Storage
# =============================================================================


@dataclass
class UserPrefs:
    """User preferences for UI state and settings.

    Mirrors the Rust UserPrefs type. Used to store persistent UI state
    like which tree nodes are collapsed and which sessions are pinned.
    """
    goal_tree_collapsed_ids: list[str] = field(default_factory=list)
    pinned_session_ids: list[str] = field(default_factory=list)


class UserPrefsStorage:
    """Async wrapper for user preferences storage using Rust backend.

    Provides load/save operations for user preferences stored in LMDB.
    """

    # Shared executor
    _executor: ThreadPoolExecutor | None = None
    _executor_lock: asyncio.Lock | None = None

    def __init__(self, db_path: str | Path | None = None):
        """Initialize user prefs storage.

        Args:
            db_path: Path to the database file. Defaults to ~/.balloons/sessions.lmdb
        """
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._storage = _get_shared_storage(self._db_path)

    @classmethod
    async def _get_executor(cls) -> ThreadPoolExecutor:
        """Get or create the shared thread pool executor."""
        if cls._executor is None:
            if cls._executor_lock is None:
                cls._executor_lock = asyncio.Lock()
            async with cls._executor_lock:
                if cls._executor is None:
                    cls._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="user_prefs")
        return cls._executor

    async def _run_sync(self, func, *args):
        """Run a synchronous function in the thread pool."""
        executor = await self._get_executor()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, func, *args)

    async def load_prefs(self) -> UserPrefs:
        """Load user preferences from storage.

        Returns:
            UserPrefs with current values, or defaults if none saved.
        """
        json_data = await self._run_sync(self._storage.load_user_prefs)
        data = json.loads(json_data)
        return UserPrefs(
            goal_tree_collapsed_ids=data.get("goal_tree_collapsed_ids", []),
            pinned_session_ids=data.get("pinned_session_ids", []),
        )

    async def save_prefs(self, prefs: UserPrefs) -> None:
        """Save user preferences to storage.

        Args:
            prefs: The preferences to save
        """
        data = {
            "goal_tree_collapsed_ids": prefs.goal_tree_collapsed_ids,
            "pinned_session_ids": prefs.pinned_session_ids,
        }
        json_data = json.dumps(data)
        await self._run_sync(self._storage.save_user_prefs, json_data)


# Singleton instance for UserPrefsStorage
_user_prefs_instance: UserPrefsStorage | None = None


async def get_user_prefs_storage() -> UserPrefsStorage:
    """Get the default UserPrefsStorage instance (singleton).

    Uses the default database path (~/.balloons/sessions.lmdb).
    """
    global _user_prefs_instance
    if _user_prefs_instance is None:
        _user_prefs_instance = UserPrefsStorage(DEFAULT_DB_PATH)
    return _user_prefs_instance
