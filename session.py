import asyncio
import json
import uuid
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, AsyncIterator

import aiofiles

from models import Message, TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, LinkBlock, ArchiveBlock, ArchiveSummary, ContentBlock, ContextMode


SESSIONS_DIR = Path.home() / ".balloons" / "sessions"
INDEX_FILE = SESSIONS_DIR / "index.json"
INDEX_VERSION = 1


class SessionIndex:
    """Manages the session index file for fast startup.

    The index stores metadata for all sessions, avoiding the need to
    read each session file individually on startup. The index is updated
    whenever a session is saved.

    Index structure:
    {
        "version": 1,
        "sessions": {
            "session_id": {
                "id": "...",
                "created": "...",
                "last_modified": "...",
                "model": "...",
                "title": "...",
                "turn_count": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost": 0.0,
                "parent_id": null,
                "children": [],
                "fork_name": "",
                "fork_status": "active",
                "backend_name": "",
                "cached_context_tokens": 0
            }
        }
    }
    """

    _instance: "SessionIndex | None" = None
    _sessions: dict[str, dict]
    _dirty: bool
    _file_mtime: float  # Tracks file modification time for cache invalidation

    def __new__(cls) -> "SessionIndex":
        """Singleton pattern - only one index instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sessions = {}
            cls._instance._dirty = False
            cls._instance._loaded = False
            cls._instance._file_mtime = 0.0
        return cls._instance

    def _get_file_mtime(self) -> float:
        """Get the index file's modification time, or 0 if it doesn't exist."""
        try:
            return INDEX_FILE.stat().st_mtime
        except OSError:
            return 0.0

    def _is_stale(self) -> bool:
        """Check if our in-memory data is stale (file changed on disk)."""
        if not self._loaded:
            return False  # Not loaded yet, so not "stale"
        current_mtime = self._get_file_mtime()
        return current_mtime > self._file_mtime

    def load(self) -> bool:
        """Load the index from disk.

        Returns True if index was loaded successfully, False if index
        doesn't exist or is invalid (requiring a rebuild).
        """
        if not INDEX_FILE.exists():
            return False

        try:
            self._file_mtime = self._get_file_mtime()
            data = json.loads(INDEX_FILE.read_text())
            if data.get("version") != INDEX_VERSION:
                return False
            self._sessions = data.get("sessions", {})
            self._loaded = True
            self._dirty = False
            return True
        except (json.JSONDecodeError, KeyError, OSError):
            return False

    async def load_async(self) -> bool:
        """Async version of load()."""
        if not INDEX_FILE.exists():
            return False

        try:
            self._file_mtime = self._get_file_mtime()
            async with aiofiles.open(INDEX_FILE, encoding="utf-8") as f:
                content = await f.read()
            data = json.loads(content)
            if data.get("version") != INDEX_VERSION:
                return False
            self._sessions = data.get("sessions", {})
            self._loaded = True
            self._dirty = False
            return True
        except (json.JSONDecodeError, KeyError, OSError):
            return False

    def reload_if_stale(self) -> bool:
        """Reload from disk if the file has been modified by another process.

        Returns True if reloaded, False if not needed.
        """
        if not self._is_stale():
            return False
        self.load()
        return True

    def save(self) -> None:
        """Save the index to disk if dirty."""
        if not self._dirty:
            return

        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "version": INDEX_VERSION,
            "sessions": self._sessions,
        }
        INDEX_FILE.write_text(json.dumps(data, indent=2))
        self._dirty = False
        self._file_mtime = self._get_file_mtime()  # Update mtime after our write

    async def save_async(self) -> None:
        """Async version of save()."""
        if not self._dirty:
            return

        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "version": INDEX_VERSION,
            "sessions": self._sessions,
        }
        async with aiofiles.open(INDEX_FILE, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2))
        self._dirty = False
        self._file_mtime = self._get_file_mtime()  # Update mtime after our write

    def get(self, session_id: str) -> dict | None:
        """Get metadata for a session."""
        return self._sessions.get(session_id)

    def update(self, session: "Session") -> None:
        """Update index entry for a session."""
        turn_count = len(session.turns)
        self._sessions[session.id] = {
            "id": session.id,
            "created": session.created,
            "last_modified": session.last_modified,
            "model": session.model,
            "title": session.title,
            "turn_count": turn_count,
            "message_count": turn_count,  # Backwards compat alias
            "total_input_tokens": session.total_input_tokens,
            "total_output_tokens": session.total_output_tokens,
            "total_cost": session.total_cost,
            "parent_id": session.parent_id,
            "children": session.children,
            "fork_name": session.fork_name,
            "fork_status": session.fork_status,
            "backend_name": session.backend_name,
            "cached_context_tokens": session.cached_context_tokens,
        }
        self._dirty = True

    def remove(self, session_id: str) -> None:
        """Remove a session from the index."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            self._dirty = True

    def get_all(self) -> list[dict]:
        """Get all session metadata, sorted by last_modified descending."""
        sessions = list(self._sessions.values())
        sessions.sort(key=lambda x: x.get("last_modified", ""), reverse=True)
        return sessions

    def rebuild_from_files(self) -> None:
        """Rebuild the index by scanning all session files.

        This is a fallback when the index doesn't exist or is invalid.
        """
        self._sessions = {}
        if not SESSIONS_DIR.exists():
            return

        for path in SESSIONS_DIR.glob("*.json"):
            if path.name == "index.json":
                continue
            try:
                data = json.loads(path.read_text())
                session_id = data["id"]
                last_modified = data.get("last_modified", data.get("created", ""))
                turn_count = len(data.get("turns", []))
                if turn_count == 0:
                    for m in data.get("messages", []):
                        blocks = m.get("content_blocks", [])
                        turn_count += len(blocks) if blocks else 1

                self._sessions[session_id] = {
                    "id": session_id,
                    "created": data["created"],
                    "last_modified": last_modified,
                    "model": data.get("model", ""),
                    "title": data.get("title", ""),
                    "turn_count": turn_count,
                    "message_count": turn_count,
                    "total_input_tokens": data.get("total_input_tokens", 0),
                    "total_output_tokens": data.get("total_output_tokens", 0),
                    "total_cost": data.get("total_cost", 0.0),
                    "parent_id": data.get("parent_id"),
                    "children": data.get("children", []),
                    "fork_name": data.get("fork_name", ""),
                    "fork_status": data.get("fork_status", "active"),
                    "backend_name": data.get("backend_name", ""),
                    "cached_context_tokens": data.get("cached_context_tokens", 0),
                }
            except (json.JSONDecodeError, KeyError, OSError):
                continue

        self._dirty = True
        self._loaded = True

    async def rebuild_from_files_async(self) -> None:
        """Async version of rebuild_from_files()."""
        self._sessions = {}
        if not SESSIONS_DIR.exists():
            return

        for path in SESSIONS_DIR.glob("*.json"):
            if path.name == "index.json":
                continue
            try:
                async with aiofiles.open(path, encoding="utf-8") as f:
                    content = await f.read()
                data = json.loads(content)
                session_id = data["id"]
                last_modified = data.get("last_modified", data.get("created", ""))
                turn_count = len(data.get("turns", []))
                if turn_count == 0:
                    for m in data.get("messages", []):
                        blocks = m.get("content_blocks", [])
                        turn_count += len(blocks) if blocks else 1

                self._sessions[session_id] = {
                    "id": session_id,
                    "created": data["created"],
                    "last_modified": last_modified,
                    "model": data.get("model", ""),
                    "title": data.get("title", ""),
                    "turn_count": turn_count,
                    "message_count": turn_count,
                    "total_input_tokens": data.get("total_input_tokens", 0),
                    "total_output_tokens": data.get("total_output_tokens", 0),
                    "total_cost": data.get("total_cost", 0.0),
                    "parent_id": data.get("parent_id"),
                    "children": data.get("children", []),
                    "fork_name": data.get("fork_name", ""),
                    "fork_status": data.get("fork_status", "active"),
                    "backend_name": data.get("backend_name", ""),
                    "cached_context_tokens": data.get("cached_context_tokens", 0),
                }
            except (json.JSONDecodeError, KeyError, OSError):
                continue

        self._dirty = True
        self._loaded = True

    def is_loaded(self) -> bool:
        """Check if index has been loaded or rebuilt."""
        return self._loaded

    def ensure_loaded(self) -> None:
        """Ensure index is loaded and up-to-date.

        This method:
        1. Loads the index from disk if not already loaded
        2. Creates empty index if file is missing/invalid
        3. Reloads from disk if another process modified the file

        Note: Dir scanning for orphan sessions is disabled for performance.
        Sessions not in the index will only appear after being saved.
        """
        # If already loaded, check if file was modified by another process
        if self._loaded:
            if self._is_stale():
                self.load()
            return

        # First load
        if not self.load():
            # Index missing/invalid - start with empty index
            # Sessions will be added as they are saved
            self._sessions = {}
            self._loaded = True
            self._dirty = True
            self.save()

    async def ensure_loaded_async(self) -> None:
        """Async version of ensure_loaded()."""
        # If already loaded, check if file was modified by another process
        if self._loaded:
            if self._is_stale():
                await self.load_async()
            return

        # First load
        if not await self.load_async():
            # Index missing/invalid - start with empty index
            # Sessions will be added as they are saved
            self._sessions = {}
            self._loaded = True
            self._dirty = True
            await self.save_async()


@dataclass
class Turn:
    """A single turn in the conversation - one content block with metadata."""
    role: str  # "user", "assistant", "tool", or "system"
    content_block: ContentBlock  # Single content block
    tokens: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    context_mode: ContextMode = ContextMode.COMPRESS
    summary: str = ""  # Cached summary for SUMMARIZE mode
    exchange_id: Optional[str] = None  # Groups turns in an agentic loop

    @property
    def content(self) -> str:
        """Get text content for display/backwards compat."""
        if isinstance(self.content_block, TextBlock):
            return self.content_block.text
        elif isinstance(self.content_block, ToolResultBlock):
            return self.content_block.content
        return ""

    @property
    def content_blocks(self) -> list[ContentBlock]:
        """Backwards compat: return content_block as a list."""
        return [self.content_block]


@dataclass
class Session:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())
    model: str = ""
    turns: list[Turn] = field(default_factory=list)  # One content block per turn
    _messages_deprecated: list[Message] = field(default_factory=list)  # Migration only, not used

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    context_window: int = 200000
    # Session forking fields
    parent_id: Optional[str] = None
    children: list[dict] = field(default_factory=list)  # [{session_id, status, return_condition, prompt}]
    returned: bool = False
    return_condition: str = "manual"
    # Working directories for the session (resolved absolute paths)
    working_directories: list[str] = field(default_factory=list)
    # Session title and summary (generated by LLM)
    title: str = ""
    summary: str = ""
    # Fork/merge tracking (new model)
    fork_name: str = ""  # User-friendly name for this fork (e.g., "auth-bug")
    fork_status: str = "active"  # "active", "merged", "abandoned"
    fork_point_turn: int = -1  # Turn index in parent where fork was created
    merge_point_turn: int = -1  # Turn index in parent where merge happened
    merge_message: str = ""  # User's summary when merging back
    # Backend configuration
    backend_name: str = ""  # Name of backend to use (empty = default)
    # Cached context token count (calculated from compiled context, not turn content)
    # This is recalculated when turns change and saved to avoid expensive recomputation on load
    cached_context_tokens: int = 0
    # Note: Links are stored as LinkBlock content blocks in messages (turn-based).
    # The legacy `links` field has been removed - old sessions with links data
    # will have those links ignored (they were never actively used).

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def add_turn(
        self,
        role: str,
        content_block: ContentBlock,
        tokens: int = 0,
        exchange_id: str | None = None,
        timestamp: str | None = None,
        context_mode: ContextMode = ContextMode.COMPRESS,
    ) -> Turn:
        """Add a single turn with one content block.

        Args:
            role: "user", "assistant", "tool", or "system"
            content_block: Single content block (TextBlock, ToolUseBlock, etc.)
            tokens: Token count for this turn
            exchange_id: Groups turns in an agentic loop (user prompt + all responses)
            timestamp: Optional timestamp (defaults to now)
            context_mode: How to handle in context compilation
        """
        turn = Turn(
            role=role,
            content_block=content_block,
            tokens=tokens,
            exchange_id=exchange_id,
            timestamp=timestamp or datetime.now().isoformat(),
            context_mode=context_mode,
        )
        self.turns.append(turn)
        return turn

    def add_message(
        self,
        role: str,
        content: str,
        content_blocks: list[ContentBlock] | None = None,
        tokens: int = 0,
        exchange_id: str | None = None,
    ) -> Turn:
        """DEPRECATED: Add a message with optional rich content blocks.

        Use add_turn() instead for new code. This method exists for backwards
        compatibility and will add turns internally.

        Args:
            role: "user", "assistant", or "tool"
            content: Text-only summary for display/backwards compat
            content_blocks: Rich content blocks (TextBlock, ToolUseBlock, etc.)
            tokens: Token count for this message
            exchange_id: Groups turns in an agentic loop (user prompt + all responses)

        Returns:
            The last Turn added (for backwards compat, callers may expect a message-like object)
        """
        if content_blocks is None:
            # Default to a single text block
            content_blocks = [TextBlock(text=content)] if content else []

        # Add each content block as a separate turn
        timestamp = datetime.now().isoformat()
        last_turn = None
        for i, block in enumerate(content_blocks):
            # Only first block gets tokens (avoid double counting)
            block_tokens = tokens if i == 0 else 0
            last_turn = self.add_turn(
                role=role,
                content_block=block,
                tokens=block_tokens,
                exchange_id=exchange_id,
                timestamp=timestamp,
            )

        # Return last turn (messages field is no longer populated)
        return last_turn

    def update_usage(self, input_tokens: int, output_tokens: int, cost: float, context_window: int = 0):
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += cost
        if context_window:
            self.context_window = context_window

    def add_child(self, child_id: str, prompt: str, return_condition: str = "manual", name: str = "", fork_point: int = -1) -> None:
        """Register a child session (fork) spawned from this session."""
        self.children.append({
            "session_id": child_id,
            "status": "active",
            "return_condition": return_condition,
            "prompt": prompt,
            "name": name,
            "fork_point": fork_point,  # Turn index where fork was created
            "merge_point": -1,  # Will be set when merged
        })

    def mark_child_returned(self, child_id: str) -> None:
        """Mark a child session as returned. (Legacy - use mark_child_merged)"""
        self.mark_child_merged(child_id)

    def mark_child_merged(self, child_id: str, merge_point: int = -1) -> None:
        """Mark a child fork as merged."""
        for child in self.children:
            if child["session_id"] == child_id:
                child["status"] = "merged"
                if merge_point >= 0:
                    child["merge_point"] = merge_point
                break

    def get_parent(self) -> Optional["Session"]:
        """Load and return the parent session if this is a child."""
        if not self.parent_id:
            return None
        return Session.load(self.parent_id)

    def is_child_session(self) -> bool:
        """Check if this session is a child of another session."""
        return self.parent_id is not None

    def is_fork(self) -> bool:
        """Check if this session is a fork (has parent and can merge back)."""
        return self.parent_id is not None

    def is_merged(self) -> bool:
        """Check if this fork has been merged."""
        return self.fork_status == "merged"

    def is_read_only(self) -> bool:
        """Check if this session is read-only.

        Previously, merged forks were read-only. Now they can continue
        to be edited - the merge marker is just another turn that can
        be deleted, and re-merging is allowed if context advances.
        """
        return False

    def check_auto_return(self, response_content: str) -> bool:
        """Check if auto-return condition is met for a child session.

        Args:
            response_content: The assistant's response text to check

        Returns:
            True if the auto-return condition is satisfied
        """
        if not self.is_child_session():
            return False

        condition = self.return_condition

        if condition == "manual":
            return False

        if condition == "done":
            # Look for completion indicators
            done_indicators = [
                "task complete",
                "task is complete",
                "completed the task",
                "finished",
                "done",
                "all set",
            ]
            lower_content = response_content.lower()
            for indicator in done_indicators:
                if indicator in lower_content:
                    return True
            return False

        if condition.startswith("turns:"):
            try:
                max_turns = int(condition.split(":")[1])
                # Count assistant turns in this child session
                assistant_count = sum(1 for t in self.turns if t.role == "assistant")
                # +1 for the current response not yet saved
                return assistant_count + 1 >= max_turns
            except (ValueError, IndexError):
                return False

        return False

    def mark_merged(self, message: str, merge_turn: int) -> None:
        """Mark this fork as merged."""
        self.fork_status = "merged"
        self.merge_message = message
        self.merge_point_turn = merge_turn

    def get_fork_display_name(self) -> str:
        """Get display name for this fork."""
        if self.fork_name:
            return self.fork_name
        elif self.title:
            return self.title
        else:
            return self.id[:8]

    def delete_turn(self, turn_index: int) -> bool:
        """Delete a turn from the session history.

        Returns True if deleted, False if index invalid.
        """
        if 0 <= turn_index < len(self.turns):
            del self.turns[turn_index]
            return True
        return False

    def delete(self) -> bool:
        """Delete this session's file from disk.

        Returns True if deleted, False if file didn't exist.
        """
        path = SESSIONS_DIR / f"{self.id}.json"
        if path.exists():
            path.unlink()
            # Remove from index
            index = SessionIndex()
            index.ensure_loaded()
            index.remove(self.id)
            index.save()
            return True
        return False

    def get_active_forks(self) -> list[dict]:
        """Get list of active (non-merged) child forks."""
        return [c for c in self.children if c.get("status") == "active"]

    def get_all_forks(self) -> list[dict]:
        """Get all child forks (active and merged)."""
        return self.children

    def add_link_turn(self, link_id: str, linked_session_id: str, summary: str) -> Turn:
        """Add a link as a turn in the conversation."""
        link_block = LinkBlock(
            link_id=link_id,
            linked_session_id=linked_session_id,
            summary=summary,
            is_orphaned=False,
        )
        return self.add_turn(role="system", content_block=link_block)

    def get_all_link_ids(self) -> list[str]:
        """Get all link IDs from LinkBlock turns."""
        link_ids = []
        for turn in self.turns:
            if isinstance(turn.content_block, LinkBlock):
                link_ids.append(turn.content_block.link_id)
        return link_ids

    def get_all_active_links(self) -> list[dict]:
        """Get all non-orphaned links from LinkBlock turns."""
        active = []
        for turn in self.turns:
            block = turn.content_block
            if isinstance(block, LinkBlock) and not block.is_orphaned:
                active.append({
                    "link_id": block.link_id,
                    "linked_session_id": block.linked_session_id,
                    "summary": block.summary,
                    "is_orphaned": block.is_orphaned,
                })
        return active

    def mark_link_orphaned(self, link_id: str) -> None:
        """Mark a link as orphaned (linked session was deleted)."""
        for turn in self.turns:
            if isinstance(turn.content_block, LinkBlock) and turn.content_block.link_id == link_id:
                turn.content_block.is_orphaned = True
                return

    def has_active_links(self) -> bool:
        """Check if this session has any non-orphaned links."""
        return len(self.get_all_active_links()) > 0

    # =========================================================================
    # Archive Methods
    # =========================================================================

    def get_all_archives(self) -> list[tuple[int, ArchiveBlock]]:
        """Get all archive blocks with their turn indices.

        Returns:
            List of (turn_index, ArchiveBlock) tuples
        """
        archives = []
        for i, turn in enumerate(self.turns):
            if isinstance(turn.content_block, ArchiveBlock):
                archives.append((i, turn.content_block))
        return archives

    def archive_turns(self, turn_start: int, turn_end: int, summary: str) -> ArchiveBlock:
        """Archive a range of turns to a file, replacing them with an ArchiveBlock.

        Args:
            turn_start: Start index (inclusive)
            turn_end: End index (exclusive)
            summary: LLM-generated summary of the archived content

        Returns:
            The ArchiveBlock that was inserted

        Raises:
            ArchiveError: If indices are invalid or archive fails
        """
        from core.archiver import Archiver
        archiver = Archiver()
        archive_block, new_turns = archiver.archive_turns(
            session_id=self.id,
            turns=self.turns,
            turn_start=turn_start,
            turn_end=turn_end,
            summary=summary,
        )
        self.turns = new_turns
        return archive_block

    def rehydrate_archive(self, archive_turn_index: int) -> int:
        """Rehydrate an archived turn, restoring the original turns.

        Args:
            archive_turn_index: Index of the turn containing the ArchiveBlock

        Returns:
            Number of turns restored

        Raises:
            ArchiveError: If the turn doesn't contain an archive block or rehydration fails
        """
        from core.archiver import Archiver
        archiver = Archiver()

        # Get the archive block to know how many turns will be restored
        archive_turn = self.turns[archive_turn_index]
        if not isinstance(archive_turn.content_block, ArchiveBlock):
            from core.archiver import ArchiveError
            raise ArchiveError(f"Turn {archive_turn_index} does not contain an archive block")

        archive_block = archive_turn.content_block
        new_turns = archiver.rehydrate(self.turns, archive_turn_index)
        self.turns = new_turns
        return archive_block.message_count

    def has_archives(self) -> bool:
        """Check if this session has any archived turns."""
        return len(self.get_all_archives()) > 0

    @property
    def working_directory(self) -> Optional[str]:
        """Get the current working directory (first in list), or None if not set."""
        return self.working_directories[0] if self.working_directories else None

    def set_working_directory(self, path: str) -> None:
        """Set the working directory, resolving to absolute canonical path."""
        resolved = str(Path(path).resolve())
        if self.working_directories:
            self.working_directories[0] = resolved
        else:
            self.working_directories.append(resolved)

    def _serialize_content_block(self, block: ContentBlock) -> dict:
        """Serialize a content block to a dict."""
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
        return {"type": "unknown"}

    def _serialize_turn(self, turn: Turn) -> dict:
        """Serialize a turn to a dict."""
        data = {
            "role": turn.role,
            "content_block": self._serialize_content_block(turn.content_block),
            "tokens": turn.tokens,
            "timestamp": turn.timestamp,
            "context_mode": turn.context_mode.value,
            "summary": turn.summary,
        }
        if turn.exchange_id:
            data["exchange_id"] = turn.exchange_id
        return data

    def _serialize_message(self, msg: Message) -> dict:
        """Serialize a message with content blocks. DEPRECATED - for migration only."""
        data = {
            "role": msg.role,
            "content": msg.content,
            "content_blocks": [self._serialize_content_block(b) for b in msg.content_blocks],
            "tokens": msg.tokens,
            "timestamp": msg.timestamp,
            "context_mode": msg.context_mode.value,
            "summary": msg.summary,
        }
        # Only include exchange_id if set (backwards compat)
        if msg.exchange_id:
            data["exchange_id"] = msg.exchange_id
        return data

    def _build_save_data(self) -> dict:
        """Build the data dict for saving."""
        self.last_modified = datetime.now().isoformat()
        return {
            "id": self.id,
            "created": self.created,
            "last_modified": self.last_modified,
            "model": self.model,
            "turns": [self._serialize_turn(t) for t in self.turns],
            "messages": [],  # Truncated - data now in turns
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost": self.total_cost,
            "context_window": self.context_window,
            "parent_id": self.parent_id,
            "children": self.children,
            "returned": self.returned,
            "return_condition": self.return_condition,
            "working_directories": self.working_directories,
            "title": self.title,
            "summary": self.summary,
            # Fork/merge tracking
            "fork_name": self.fork_name,
            "fork_status": self.fork_status,
            "fork_point_turn": self.fork_point_turn,
            "merge_point_turn": self.merge_point_turn,
            "merge_message": self.merge_message,
            "backend_name": self.backend_name,
            "cached_context_tokens": self.cached_context_tokens,
        }

    def save(self):
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = SESSIONS_DIR / f"{self.id}.json"
        data = self._build_save_data()
        path.write_text(json.dumps(data, indent=2))

        # Update session index
        index = SessionIndex()
        index.ensure_loaded()
        index.update(self)
        index.save()

    async def save_async(self):
        """Async version of save()."""
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = SESSIONS_DIR / f"{self.id}.json"
        data = self._build_save_data()
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2))

        # Update session index
        index = SessionIndex()
        await index.ensure_loaded_async()
        index.update(self)
        await index.save_async()

    @classmethod
    def _load_working_directories(cls, data: dict) -> list[str]:
        """Load working directories with backwards compatibility for old format."""
        # New format: list of paths
        if "working_directories" in data:
            return data["working_directories"]
        # Old format: single path string
        if "working_directory" in data and data["working_directory"]:
            return [data["working_directory"]]
        return []

    @classmethod
    def _deserialize_content_block(cls, data: dict) -> ContentBlock:
        """Deserialize a content block from a dict."""
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
            return InterruptionBlock(
                reason=data.get("reason", "user_cancelled"),
            )
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
        # Fallback to text
        return TextBlock(text=str(data))

    @classmethod
    def _deserialize_turn(cls, data: dict) -> Turn:
        """Deserialize a turn from a dict."""
        content_block = cls._deserialize_content_block(data.get("content_block", {"type": "text", "text": ""}))

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

    @classmethod
    def _build_session_from_data(cls, data: dict) -> "Session":
        """Build a Session object from loaded data dict."""
        # For backwards compat, use created if last_modified missing
        last_modified = data.get("last_modified", data.get("created", ""))
        session = cls(
            id=data["id"],
            created=data["created"],
            last_modified=last_modified,
            model=data.get("model", ""),
            total_input_tokens=data.get("total_input_tokens", 0),
            total_output_tokens=data.get("total_output_tokens", 0),
            total_cost=data.get("total_cost", 0.0),
            context_window=data.get("context_window", 200000),
            parent_id=data.get("parent_id"),
            children=data.get("children", []),
            returned=data.get("returned", False),
            return_condition=data.get("return_condition", "manual"),
            working_directories=cls._load_working_directories(data),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            # Fork/merge tracking
            fork_name=data.get("fork_name", ""),
            fork_status=data.get("fork_status", "active"),
            fork_point_turn=data.get("fork_point_turn", -1),
            merge_point_turn=data.get("merge_point_turn", -1),
            merge_message=data.get("merge_message", ""),
            backend_name=data.get("backend_name", ""),
            cached_context_tokens=data.get("cached_context_tokens", 0),
        )

        # Load turns (new format)
        for t in data.get("turns", []):
            session.turns.append(cls._deserialize_turn(t))

        # Migration: if no turns but has messages, expand messages to turns
        if not session.turns and data.get("messages"):
            for m in data.get("messages", []):
                # Parse content_blocks if present, otherwise create from content
                raw_blocks = m.get("content_blocks", [])
                if raw_blocks:
                    content_blocks = [cls._deserialize_content_block(b) for b in raw_blocks]
                else:
                    # Backwards compat: create text block from content
                    content_blocks = [TextBlock(text=m.get("content", ""))] if m.get("content") else []

                # Parse context_mode
                mode_str = m.get("context_mode", "copy")
                try:
                    context_mode = ContextMode(mode_str)
                except ValueError:
                    context_mode = ContextMode.COPY

                # Expand each content block into a separate turn
                timestamp = m.get("timestamp", "")
                exchange_id = m.get("exchange_id")
                tokens = m.get("tokens", 0)

                for i, block in enumerate(content_blocks):
                    # Only first block gets tokens (avoid double counting)
                    block_tokens = tokens if i == 0 else 0
                    session.turns.append(Turn(
                        role=m["role"],
                        content_block=block,
                        tokens=block_tokens,
                        timestamp=timestamp,
                        context_mode=context_mode,
                        summary=m.get("summary", "") if i == 0 else "",
                        exchange_id=exchange_id,
                    ))

        return session

    @classmethod
    def load(cls, session_id: str) -> Optional["Session"]:
        path = SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return cls._build_session_from_data(data)

    @classmethod
    async def load_async(cls, session_id: str) -> Optional["Session"]:
        """Async version of load()."""
        path = SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        async with aiofiles.open(path, encoding="utf-8") as f:
            content = await f.read()
        data = json.loads(content)
        return cls._build_session_from_data(data)

    @classmethod
    def list_sessions(cls) -> list[dict]:
        """Return list of session metadata dicts without loading full data.

        Uses the session index for fast lookup. Rebuilds index from files
        if it doesn't exist.

        Returns list of dicts with keys: id, created, last_modified, model, title,
        turn_count, total_input_tokens, total_output_tokens, total_cost,
        parent_id, children, fork_name, fork_status.
        """
        index = SessionIndex()
        index.ensure_loaded()
        return index.get_all()

    @classmethod
    async def list_sessions_async(cls) -> AsyncIterator[dict]:
        """Async generator that yields session metadata dicts one at a time.

        Uses the session index for instant loading. The index is loaded
        asynchronously on first call, then sessions are yielded immediately
        from memory.

        Sessions are yielded in order of last_modified (most recent first).

        Yields dicts with keys: id, created, last_modified, model, title,
        turn_count, total_input_tokens, total_output_tokens, total_cost,
        parent_id, children, fork_name, fork_status.
        """
        index = SessionIndex()

        # Load index asynchronously if not already loaded
        if not index.is_loaded():
            await index.ensure_loaded_async()

        # Yield sessions from index (already sorted by last_modified desc)
        for metadata in index.get_all():
            yield metadata

    @classmethod
    def get_most_recent_session_id(cls) -> Optional[str]:
        """Get the ID of the most recently modified session without loading all data.

        Uses the session index for instant lookup.
        Returns None if no sessions exist.
        """
        index = SessionIndex()
        index.ensure_loaded()
        sessions = index.get_all()
        if sessions:
            return sessions[0]["id"]  # Already sorted by last_modified desc
        return None
