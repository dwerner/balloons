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
    import balloons_py
    RUST_STORAGE_AVAILABLE = True
except ImportError:
    RUST_STORAGE_AVAILABLE = False

from .debug_log import perf_timed, perf_marker, debug_log, Category

if TYPE_CHECKING:
    from session import Session
    from models import Turn, ContentBlock
    from service.user_auth import User


# Default database path
# Note: LMDB uses a directory, not a single file (unlike redb)
DEFAULT_DB_PATH = Path.home() / ".balloons" / "sessions.lmdb"

# Shared storage handle (singleton pattern to avoid LMDB "already open" errors)
_shared_storage = None
_shared_storage_path = None


def _get_shared_storage(db_path: Path) -> "balloons_py.Storage":
    """Get or create a shared storage handle.

    LMDB doesn't allow multiple opens with different options, so we need
    a single shared instance for the same database path.
    """
    global _shared_storage, _shared_storage_path

    if _shared_storage is not None and _shared_storage_path == db_path:
        return _shared_storage

    if not RUST_STORAGE_AVAILABLE:
        raise RuntimeError(
            "balloons_py module not available. "
            "Run 'maturin develop' in balloons-rs/ to build it."
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    _shared_storage = balloons_py.Storage(str(db_path))
    _shared_storage_path = db_path
    return _shared_storage


class AsyncStorage:
    """Async wrapper for Rust storage backend.

    Wraps the synchronous balloons_py.Storage class with async methods,
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
        # Update last_modified timestamp before saving
        from datetime import datetime
        session.last_modified = datetime.now().isoformat()

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
        # Update last_modified timestamp before saving
        from datetime import datetime
        session.last_modified = datetime.now().isoformat()

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
            "prompt_files": session.prompt_files,
            "enabled_tools": session.enabled_tools,
            "concluded": session.concluded,
            "concluded_at": session.concluded_at,
            "concluded_reason": session.concluded_reason,
            "message_queue": session.message_queue.to_dict() if session.message_queue else {},
            "loaded_domains": session.loaded_domains,
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
            "parallel_group_id": turn.parallel_group_id,
        }

    def _serialize_content_block(self, block: ContentBlock) -> dict:
        """Serialize a content block to a dict.

        This matches the JSON structure expected by Rust's serde_json::Value.
        """
        from models import (
            TextBlock, MarkdownBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock,
            ErrorBlock, LinkBlock, ForkBlock, MergeBlock, MergedToBlock,
            ArchiveBlock, SlideBlock, ReviewBlock, ForkProposalBlock, MergeProposalBlock,
            WatchStartBlock, WatchStopBlock, WatchSummaryBlock,
        )

        if isinstance(block, TextBlock):
            return {"type": "text", "text": block.text, "interrupted": block.interrupted}
        elif isinstance(block, MarkdownBlock):
            return {"type": "markdown", "text": block.text}
        elif isinstance(block, ThinkingBlock):
            return {"type": "thinking", "text": block.text, "interrupted": block.interrupted}
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
        elif isinstance(block, WatchStartBlock):
            return {
                "type": "watch_start",
                "target_session_id": block.target_session_id,
                "target_session_name": block.target_session_name,
            }
        elif isinstance(block, WatchStopBlock):
            return {
                "type": "watch_stop",
                "target_session_id": block.target_session_id,
                "target_session_name": block.target_session_name,
            }
        elif isinstance(block, WatchSummaryBlock):
            return {
                "type": "watch_summary",
                "target_session_id": block.target_session_id,
                "target_session_name": block.target_session_name,
                "exchange_index": block.exchange_index,
                "summary": block.summary,
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
            prompt_files=data.get("prompt_files", []),
            enabled_tools=data.get("enabled_tools", []),
            concluded=data.get("concluded", False),
            concluded_at=data.get("concluded_at"),
            concluded_reason=data.get("concluded_reason", ""),
            message_queue=MessageQueue.from_dict(data.get("message_queue", {})),
            loaded_domains=data.get("loaded_domains", []),
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
            parallel_group_id=data.get("parallel_group_id"),
            id=turn_id,
            # Loaded turns start clean - they're fresh from storage
            _dirty=False,
        )
        return turn

    def _deserialize_content_block(self, data: dict) -> ContentBlock:
        """Deserialize a content block from a dict."""
        from models import (
            TextBlock, MarkdownBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock,
            ErrorBlock, LinkBlock, ForkBlock, MergeBlock, ArchiveBlock, SlideBlock,
            ReviewBlock, ArchiveSummary, ForkProposalBlock, MergeProposalBlock,
            ContextAssignmentData, ForkBindingData, ExchangeInfo
        )

        block_type = data.get("type", "text")

        if block_type == "text":
            return TextBlock(text=data.get("text", ""), interrupted=data.get("interrupted", False))
        elif block_type == "markdown":
            return MarkdownBlock(text=data.get("text", ""))
        elif block_type == "thinking":
            return ThinkingBlock(text=data.get("text", ""), interrupted=data.get("interrupted", False))
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
                dump_file=data.get("dump_file", ""),
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
        elif block_type == "watch_start":
            from models import WatchStartBlock
            return WatchStartBlock(
                target_session_id=data.get("target_session_id", ""),
                target_session_name=data.get("target_session_name", ""),
            )
        elif block_type == "watch_stop":
            from models import WatchStopBlock
            return WatchStopBlock(
                target_session_id=data.get("target_session_id", ""),
                target_session_name=data.get("target_session_name", ""),
            )
        elif block_type == "watch_summary":
            from models import WatchSummaryBlock
            return WatchSummaryBlock(
                target_session_id=data.get("target_session_id", ""),
                target_session_name=data.get("target_session_name", ""),
                exchange_index=data.get("exchange_index", 0),
                summary=data.get("summary", ""),
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


# =============================================================================
# Watcher Storage
# =============================================================================


@dataclass
class WatcherRelationData:
    """Python representation of a watcher relationship."""
    id: str
    watcher_session_id: str
    target_session_id: str
    target_session_name: str
    created_at: str


class WatcherStorage:
    """Async wrapper for watcher relationship storage using Rust backend.

    Provides an async interface to the synchronous Rust storage backend,
    using ThreadPoolExecutor to run blocking calls without blocking the event loop.

    Stores watcher relationships for cross-session observation.
    """

    # Shared executor for all instances
    _executor: ThreadPoolExecutor | None = None
    _executor_lock: asyncio.Lock | None = None

    def __init__(self, db_path: str | Path | None = None):
        """Initialize watcher storage.

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
            if cls._executor_lock is None:
                cls._executor_lock = asyncio.Lock()
            async with cls._executor_lock:
                if cls._executor is None:
                    cls._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="watcher_storage")
        return cls._executor

    async def _run_sync(self, func, *args):
        """Run a synchronous function in the thread pool."""
        executor = await self._get_executor()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, func, *args)

    async def save_watcher(self, watcher: WatcherRelationData) -> None:
        """Save a watcher relationship (upsert).

        Args:
            watcher: The watcher relationship to save
        """
        from dataclasses import asdict
        watcher_json = json.dumps(asdict(watcher))
        await self._run_sync(self._storage.save_watcher, watcher_json)

    async def delete_watcher(self, watcher_id: str) -> None:
        """Delete a watcher relationship.

        Args:
            watcher_id: The ID of the watcher relationship to delete
        """
        await self._run_sync(self._storage.delete_watcher, watcher_id)

    async def get_watchers_for_target(self, target_session_id: str) -> list[WatcherRelationData]:
        """Get all watcher relationships for a target session.

        Args:
            target_session_id: The ID of the target session

        Returns:
            List of watcher relationships
        """
        json_data = await self._run_sync(self._storage.get_watchers_for_target, target_session_id)
        watchers = json.loads(json_data)
        return [WatcherRelationData(**w) for w in watchers]

    async def get_targets_for_watcher(self, watcher_session_id: str) -> list[WatcherRelationData]:
        """Get all targets a watcher session is watching.

        Args:
            watcher_session_id: The ID of the watcher session

        Returns:
            List of watcher relationships
        """
        json_data = await self._run_sync(self._storage.get_targets_for_watcher, watcher_session_id)
        watchers = json.loads(json_data)
        return [WatcherRelationData(**w) for w in watchers]

    async def list_watchers(self) -> list[WatcherRelationData]:
        """List all watcher relationships.

        Returns:
            List of all watcher relationships
        """
        json_data = await self._run_sync(self._storage.list_watchers)
        watchers = json.loads(json_data)
        return [WatcherRelationData(**w) for w in watchers]


# Singleton instance for WatcherStorage
_watcher_storage_instance: WatcherStorage | None = None


async def get_watcher_storage() -> WatcherStorage:
    """Get the default WatcherStorage instance (singleton).

    Uses the default database path (~/.balloons/sessions.lmdb).
    """
    global _watcher_storage_instance
    if _watcher_storage_instance is None:
        _watcher_storage_instance = WatcherStorage(DEFAULT_DB_PATH)
    return _watcher_storage_instance


# =============================================================================
# User Management Storage (LMDB)
# =============================================================================


class LmdbUserStorage:
    """User storage backed by LMDB via Rust.

    Implements the UserStorage protocol from user_auth.py, using the
    Rust balloons_py module for persistence.

    Thread-safe via the underlying Rust LMDB implementation.
    """

    # Shared executor
    _executor: ThreadPoolExecutor | None = None
    _executor_lock: asyncio.Lock | None = None

    def __init__(self, db_path: str | Path | None = None):
        """Initialize LMDB user storage.

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
                    cls._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lmdb_user")
        return cls._executor

    async def _run_sync(self, func, *args):
        """Run a synchronous function in the thread pool."""
        executor = await self._get_executor()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, func, *args)

    def _user_to_data(self, user: "User") -> dict:
        """Convert User domain object to storage dict."""
        return {
            "id": user.id,
            "username": user.username,
            "password_hash": user.password_hash,
            "role": user.role,
            "created_at": user.created_at.isoformat(),
            "created_by": user.created_by,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "disabled": user.disabled,
        }

    def _data_to_user(self, data: dict) -> "User":
        """Convert storage dict to User domain object."""
        from datetime import datetime
        from service.user_auth import User

        return User(
            id=data["id"],
            username=data["username"],
            password_hash=data["password_hash"],
            role=data["role"],
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by"),
            last_login=(
                datetime.fromisoformat(data["last_login"])
                if data.get("last_login")
                else None
            ),
            disabled=data.get("disabled", False),
        )

    async def get_by_id(self, user_id: str) -> Optional["User"]:
        """Get a user by ID."""
        json_data = await self._run_sync(self._storage.load_user, user_id)
        if json_data is None:
            return None

        try:
            data = json.loads(json_data)
            return self._data_to_user(data)
        except Exception:
            return None

    async def get_by_username(self, username: str) -> Optional["User"]:
        """Get a user by username (case-insensitive)."""
        json_data = await self._run_sync(self._storage.load_user_by_username, username)
        if json_data is None:
            return None

        try:
            data = json.loads(json_data)
            return self._data_to_user(data)
        except Exception:
            return None

    async def list_all(self) -> list["User"]:
        """List all users."""
        json_data = await self._run_sync(self._storage.list_users)
        all_users = json.loads(json_data)

        users = []
        for data in all_users:
            try:
                users.append(self._data_to_user(data))
            except Exception:
                continue

        users.sort(key=lambda u: u.created_at)
        return users

    async def save(self, user: "User") -> None:
        """Save a user (create or update)."""
        data = self._user_to_data(user)
        json_data = json.dumps(data)
        await self._run_sync(self._storage.save_user, json_data)

    async def delete(self, user_id: str) -> None:
        """Delete a user by ID."""
        await self._run_sync(self._storage.delete_user, user_id)


# Singleton instance for LmdbUserStorage
_lmdb_user_storage_instance: LmdbUserStorage | None = None


async def get_lmdb_user_storage() -> LmdbUserStorage:
    """Get the default LmdbUserStorage instance (singleton).

    Uses the default database path (~/.balloons/sessions.lmdb).
    """
    global _lmdb_user_storage_instance
    if _lmdb_user_storage_instance is None:
        _lmdb_user_storage_instance = LmdbUserStorage(DEFAULT_DB_PATH)
    return _lmdb_user_storage_instance
