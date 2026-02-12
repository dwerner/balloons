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
# Note: LMDB uses a directory, not a single file (unlike redb)
DEFAULT_DB_PATH = Path.home() / ".balloons" / "sessions.lmdb"


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
        """Save a session to storage.

        Uses atomic batch operations for efficiency:
        1. Save session metadata to SESSIONS table
        2. Atomically replace all turns (handles insert/update/delete/reorder)

        All operations happen in a single database transaction.

        Args:
            session: The Session object to save
        """
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
                category="storage"
            )

        # Save session metadata first (required for replace_session_turns)
        await self._run_sync(self._storage.save_session, session.id, session_json)

        # Atomically replace all turns (handles deletes, upserts, and ordering)
        await self._run_sync(self._storage.replace_session_turns, session.id, turns_json)

    async def load_session(self, session_id: str) -> Optional[Session]:
        """Load a session from storage.

        Uses split storage model:
        1. Load session metadata from SESSIONS table
        2. Load turns from TURNS table via TURN_ORDER

        Args:
            session_id: The session ID to load

        Returns:
            The Session object, or None if not found
        """
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
            "sentiment": turn.sentiment.value if turn.sentiment else None,
        }

    def _serialize_content_block(self, block: ContentBlock) -> dict:
        """Serialize a content block to a dict.

        This matches the JSON structure expected by Rust's serde_json::Value.
        """
        from models import (
            TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock,
            ErrorBlock, LinkBlock, ForkBlock, MergeBlock, MergedToBlock,
            ArchiveBlock, SlideBlock, ReviewBlock, ForkProposalBlock, MergeProposalBlock
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

        # NOTE: turns are loaded separately via load_turns() and appended by the caller

        return session

    def _wire_to_turn(self, data: dict) -> Turn:
        """Convert wire format turn data to a Turn object."""
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

        return Turn(
            role=data["role"],
            content_block=content_block,
            tokens=data.get("tokens", 0),
            timestamp=data.get("timestamp", ""),
            context_mode=context_mode,
            summary=data.get("summary", ""),
            exchange_id=data.get("exchange_id"),
            sentiment=sentiment,
        )

    def _deserialize_content_block(self, data: dict) -> ContentBlock:
        """Deserialize a content block from a dict."""
        from models import (
            TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock,
            ErrorBlock, LinkBlock, ForkBlock, MergeBlock, ArchiveBlock, SlideBlock,
            ReviewBlock, ArchiveSummary, ForkProposalBlock, MergeProposalBlock,
            ContextAssignmentData, ForkBindingData, ExchangeInfo
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
    """File-based storage for goal-oriented task management entities.

    Stores Goals, Plans, Todos, and their relationships in ~/.balloons/goals/
    Will migrate to Rust storage in a future version.
    """

    def __init__(self, base_path: Path | None = None):
        self._base_path = base_path or (Path.home() / ".balloons" / "goals")
        self._base_path.mkdir(parents=True, exist_ok=True)

        # Subdirectories for each entity type
        self._goals_dir = self._base_path / "goals"
        self._plans_dir = self._base_path / "plans"
        self._todos_dir = self._base_path / "todos"
        self._links_dir = self._base_path / "links"
        self._deps_dir = self._base_path / "dependencies"
        self._bindings_dir = self._base_path / "bindings"

        for d in [self._goals_dir, self._plans_dir, self._todos_dir,
                  self._links_dir, self._deps_dir, self._bindings_dir]:
            d.mkdir(exist_ok=True)

    # =========================================================================
    # Goals CRUD
    # =========================================================================

    async def save_goal(self, goal: "GoalData") -> None:
        """Save a goal to storage."""
        import aiofiles
        from dataclasses import asdict

        goal_path = self._goals_dir / f"{goal.id}.json"
        goal_json = json.dumps(asdict(goal), indent=2)

        async with aiofiles.open(goal_path, "w", encoding="utf-8") as f:
            await f.write(goal_json)

    async def load_goal(self, goal_id: str) -> Optional["GoalData"]:
        """Load a goal from storage."""
        import aiofiles
        from storage_schema import GoalData

        goal_path = self._goals_dir / f"{goal_id}.json"
        if not goal_path.exists():
            return None

        try:
            async with aiofiles.open(goal_path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            return GoalData(**data)
        except Exception:
            return None

    async def delete_goal(self, goal_id: str) -> None:
        """Delete a goal from storage."""
        goal_path = self._goals_dir / f"{goal_id}.json"
        if goal_path.exists():
            goal_path.unlink()

    async def list_goals(self, status: str | None = None) -> list["GoalData"]:
        """List all goals, optionally filtered by status."""
        import aiofiles
        from storage_schema import GoalData

        goals = []
        for goal_file in self._goals_dir.glob("*.json"):
            try:
                async with aiofiles.open(goal_file, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
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
        import aiofiles
        from dataclasses import asdict

        plan_path = self._plans_dir / f"{plan.id}.json"
        plan_json = json.dumps(asdict(plan), indent=2)

        async with aiofiles.open(plan_path, "w", encoding="utf-8") as f:
            await f.write(plan_json)

    async def load_plan(self, plan_id: str) -> Optional["PlanData"]:
        """Load a plan from storage."""
        import aiofiles
        from storage_schema import PlanData

        plan_path = self._plans_dir / f"{plan_id}.json"
        if not plan_path.exists():
            return None

        try:
            async with aiofiles.open(plan_path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            return PlanData(**data)
        except Exception:
            return None

    async def delete_plan(self, plan_id: str) -> None:
        """Delete a plan from storage."""
        plan_path = self._plans_dir / f"{plan_id}.json"
        if plan_path.exists():
            plan_path.unlink()

    async def list_plans(self, goal_id: str | None = None, status: str | None = None) -> list["PlanData"]:
        """List plans, optionally filtered by goal and/or status."""
        import aiofiles
        from storage_schema import PlanData

        plans = []
        for plan_file in self._plans_dir.glob("*.json"):
            try:
                async with aiofiles.open(plan_file, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
                plan = PlanData(**data)
                if (goal_id is None or plan.goal_id == goal_id) and \
                   (status is None or plan.status == status):
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
        import aiofiles
        from dataclasses import asdict

        todo_path = self._todos_dir / f"{todo.id}.json"
        todo_json = json.dumps(asdict(todo), indent=2)

        async with aiofiles.open(todo_path, "w", encoding="utf-8") as f:
            await f.write(todo_json)

    async def load_todo(self, todo_id: str) -> Optional["TodoData"]:
        """Load a todo from storage."""
        import aiofiles
        from storage_schema import TodoData

        todo_path = self._todos_dir / f"{todo_id}.json"
        if not todo_path.exists():
            return None

        try:
            async with aiofiles.open(todo_path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            return TodoData(**data)
        except Exception:
            return None

    async def delete_todo(self, todo_id: str) -> None:
        """Delete a todo from storage."""
        todo_path = self._todos_dir / f"{todo_id}.json"
        if todo_path.exists():
            todo_path.unlink()

    async def list_todos(self, status: str | None = None, include_spikes: bool = True) -> list["TodoData"]:
        """List all todos, optionally filtered by status."""
        import aiofiles
        from storage_schema import TodoData

        todos = []
        for todo_file in self._todos_dir.glob("*.json"):
            try:
                async with aiofiles.open(todo_file, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
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
        import aiofiles
        from dataclasses import asdict

        # Use composite key for file name
        link_path = self._links_dir / f"{link.todo_id}_{link.plan_id}.json"
        link_json = json.dumps(asdict(link), indent=2)

        async with aiofiles.open(link_path, "w", encoding="utf-8") as f:
            await f.write(link_json)

    async def delete_todo_plan_link(self, todo_id: str, plan_id: str) -> None:
        """Delete a todo-plan link."""
        link_path = self._links_dir / f"{todo_id}_{plan_id}.json"
        if link_path.exists():
            link_path.unlink()

    async def get_plans_for_todo(self, todo_id: str) -> list[str]:
        """Get all plan IDs linked to a todo."""
        import aiofiles

        plan_ids = []
        for link_file in self._links_dir.glob(f"{todo_id}_*.json"):
            try:
                async with aiofiles.open(link_file, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
                plan_ids.append(data["plan_id"])
            except Exception:
                continue
        return plan_ids

    async def get_todos_for_plan(self, plan_id: str) -> list[str]:
        """Get all todo IDs linked to a plan."""
        import aiofiles

        todo_ids = []
        for link_file in self._links_dir.glob(f"*_{plan_id}.json"):
            try:
                async with aiofiles.open(link_file, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
                todo_ids.append(data["todo_id"])
            except Exception:
                continue
        return todo_ids

    # =========================================================================
    # Todo Dependencies
    # =========================================================================

    async def save_todo_dependency(self, dep: "TodoDependency") -> None:
        """Save a todo dependency."""
        import aiofiles
        from dataclasses import asdict

        dep_path = self._deps_dir / f"{dep.todo_id}_{dep.depends_on_id}.json"
        dep_json = json.dumps(asdict(dep), indent=2)

        async with aiofiles.open(dep_path, "w", encoding="utf-8") as f:
            await f.write(dep_json)

    async def delete_todo_dependency(self, todo_id: str, depends_on_id: str) -> None:
        """Delete a todo dependency."""
        dep_path = self._deps_dir / f"{todo_id}_{depends_on_id}.json"
        if dep_path.exists():
            dep_path.unlink()

    async def get_dependencies(self, todo_id: str) -> list[str]:
        """Get all todo IDs that a todo depends on."""
        import aiofiles

        deps = []
        for dep_file in self._deps_dir.glob(f"{todo_id}_*.json"):
            try:
                async with aiofiles.open(dep_file, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
                deps.append(data["depends_on_id"])
            except Exception:
                continue
        return deps

    async def get_dependents(self, todo_id: str) -> list[str]:
        """Get all todo IDs that depend on a todo."""
        import aiofiles

        dependents = []
        for dep_file in self._deps_dir.glob(f"*_{todo_id}.json"):
            try:
                async with aiofiles.open(dep_file, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
                dependents.append(data["todo_id"])
            except Exception:
                continue
        return dependents

    # =========================================================================
    # Session Bindings
    # =========================================================================

    async def save_session_binding(self, binding: "SessionBinding") -> None:
        """Save a session binding."""
        import aiofiles
        from dataclasses import asdict

        binding_path = self._bindings_dir / f"{binding.id}.json"
        binding_json = json.dumps(asdict(binding), indent=2)

        async with aiofiles.open(binding_path, "w", encoding="utf-8") as f:
            await f.write(binding_json)

    async def load_session_binding(self, binding_id: str) -> Optional["SessionBinding"]:
        """Load a session binding."""
        import aiofiles
        from storage_schema import SessionBinding

        binding_path = self._bindings_dir / f"{binding_id}.json"
        if not binding_path.exists():
            return None

        try:
            async with aiofiles.open(binding_path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            return SessionBinding(**data)
        except Exception:
            return None

    async def delete_session_binding(self, binding_id: str) -> None:
        """Delete a session binding."""
        binding_path = self._bindings_dir / f"{binding_id}.json"
        if binding_path.exists():
            binding_path.unlink()

    async def get_bindings_for_session(self, session_id: str, active_only: bool = True) -> list["SessionBinding"]:
        """Get all bindings for a session."""
        import aiofiles
        from storage_schema import SessionBinding

        bindings = []
        for binding_file in self._bindings_dir.glob("*.json"):
            try:
                async with aiofiles.open(binding_file, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
                if data["session_id"] == session_id:
                    binding = SessionBinding(**data)
                    if not active_only or binding.released_at is None:
                        bindings.append(binding)
            except Exception:
                continue

        bindings.sort(key=lambda b: b.created_at)
        return bindings

    async def get_bindings_for_entity(self, entity_type: str, entity_id: str, active_only: bool = True) -> list["SessionBinding"]:
        """Get all bindings for an entity."""
        import aiofiles
        from storage_schema import SessionBinding

        bindings = []
        for binding_file in self._bindings_dir.glob("*.json"):
            try:
                async with aiofiles.open(binding_file, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
                if data["entity_type"] == entity_type and data["entity_id"] == entity_id:
                    binding = SessionBinding(**data)
                    if not active_only or binding.released_at is None:
                        bindings.append(binding)
            except Exception:
                continue

        bindings.sort(key=lambda b: b.created_at)
        return bindings


async def get_goal_storage() -> GoalStorage:
    """Get the default GoalStorage instance."""
    return GoalStorage()
