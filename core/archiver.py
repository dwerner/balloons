"""Archive and rehydrate conversation turns.

This module handles offloading large exchanges to files and rehydrating them
back into the session when needed. Archives are stored as JSON files containing
the full Turn objects.

Archive file format:
    {
        "archive_id": "uuid",
        "session_id": "session-uuid",
        "created": "ISO timestamp",
        "summary": "LLM-generated description",
        "turn_start": 5,
        "turn_end": 12,
        "turns": [/* serialized Turn objects */]
    }

Usage:
    archiver = Archiver()

    # Archive turns 5-12, returns the ArchiveBlock to insert
    archive_block = archiver.archive_turns(session, 5, 12, "Summary of the work")

    # Load archived turns from an archive block
    turns = archiver.load_archive(archive_block)

    # Rehydrate: replace archive block with original turns
    archiver.rehydrate(session, turn_index)
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiofiles

from models import (
    ArchiveBlock,
    ArchiveSummary,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    InterruptionBlock,
    ErrorBlock,
    LinkBlock,
    ForkBlock,
    MergeBlock,
    MergedToBlock,
    ContentBlock,
    ContextMode,
)
from session import Turn


ARCHIVES_DIR = Path.home() / ".balloons" / "archives"


class ArchiveError(Exception):
    """Error during archive or rehydrate operation."""
    pass


class Archiver:
    """Archive and rehydrate conversation turns."""

    def __init__(self, archives_dir: Optional[Path] = None):
        """Initialize with optional custom archives directory."""
        self.archives_dir = archives_dir or ARCHIVES_DIR

    def _get_session_archive_dir(self, session_id: str) -> Path:
        """Get the archive directory for a session."""
        return self.archives_dir / session_id

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
                "dump_file": block.dump_file,
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
        return {"type": "unknown"}

    def _deserialize_content_block(self, data: dict) -> ContentBlock:
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
        return TextBlock(text=str(data))

    def _serialize_turn(self, turn: Turn) -> dict:
        """Serialize a turn to dict for storage."""
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

    def _deserialize_turn(self, data: dict) -> Turn:
        """Deserialize a turn from dict."""
        content_block = self._deserialize_content_block(
            data.get("content_block", {"type": "text", "text": ""})
        )

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

    def archive_turns(
        self,
        session_id: str,
        turns: list[Turn],
        turn_start: int,
        turn_end: int,
        summary: str | ArchiveSummary,
    ) -> tuple[ArchiveBlock, list[Turn]]:
        """Archive a range of turns from a turn list.

        Args:
            session_id: The session ID (for organizing archive files)
            turns: The full turn list
            turn_start: Start index (inclusive)
            turn_end: End index (exclusive)
            summary: Plain text summary or ArchiveSummary object

        Returns:
            Tuple of (ArchiveBlock to insert, new turn list with archived turns replaced)

        Raises:
            ArchiveError: If indices are invalid or archive fails
        """
        if turn_start < 0 or turn_end > len(turns) or turn_start >= turn_end:
            raise ArchiveError(
                f"Invalid turn range: {turn_start}-{turn_end} (session has {len(turns)} turns)"
            )

        # Extract turns to archive
        to_archive = turns[turn_start:turn_end]

        # Estimate token count from archived turns
        token_estimate = sum(t.tokens for t in to_archive)

        # Generate archive ID and path
        archive_id = str(uuid.uuid4())
        archive_dir = self._get_session_archive_dir(session_id)
        archive_dir.mkdir(parents=True, exist_ok=True)
        file_path = archive_dir / f"{archive_id}.json"

        # Handle both string and ArchiveSummary
        if isinstance(summary, ArchiveSummary):
            structured_summary = summary
            plain_summary = summary.work_done or f"Archived {len(to_archive)} turns"
        else:
            structured_summary = None
            plain_summary = summary

        # Build archive data
        archive_data = {
            "archive_id": archive_id,
            "session_id": session_id,
            "created": datetime.now().isoformat(),
            "summary": plain_summary,
            "turn_start": turn_start,
            "turn_end": turn_end,
            "turns": [self._serialize_turn(t) for t in to_archive],
        }
        if structured_summary:
            archive_data["structured_summary"] = {
                "files_modified": structured_summary.files_modified,
                "work_done": structured_summary.work_done,
                "key_decisions": structured_summary.key_decisions,
            }

        # Write archive file
        try:
            file_path.write_text(json.dumps(archive_data, indent=2))
        except IOError as e:
            raise ArchiveError(f"Failed to write archive file: {e}")

        # Create the archive block
        archive_block = ArchiveBlock(
            archive_id=archive_id,
            file_path=str(file_path),
            summary=plain_summary,
            structured_summary=structured_summary,
            turn_start=turn_start,
            turn_end=turn_end,
            message_count=len(to_archive),
            token_estimate=token_estimate,
        )

        # Create archive marker turn with display summary
        archive_turn = Turn(
            role="system",
            content_block=archive_block,
        )

        # Build new turn list: before + archive marker + after
        new_turns = turns[:turn_start] + [archive_turn] + turns[turn_end:]

        return archive_block, new_turns

    def load_archive(self, archive_block: ArchiveBlock) -> list[Turn]:
        """Load archived turns from an archive block.

        Args:
            archive_block: The archive block containing file path

        Returns:
            List of archived Turn objects

        Raises:
            ArchiveError: If archive file cannot be read
        """
        file_path = Path(archive_block.file_path)
        if not file_path.exists():
            raise ArchiveError(f"Archive file not found: {file_path}")

        try:
            data = json.loads(file_path.read_text())
        except (IOError, json.JSONDecodeError) as e:
            raise ArchiveError(f"Failed to read archive file: {e}")

        # New format: turns field
        if "turns" in data:
            return [self._deserialize_turn(t) for t in data["turns"]]

        # Legacy format: messages field - expand content_blocks to turns
        legacy_turns = []
        for m in data.get("messages", []):
            raw_blocks = m.get("content_blocks", [])
            if raw_blocks:
                content_blocks = [self._deserialize_content_block(b) for b in raw_blocks]
            else:
                content_blocks = [TextBlock(text=m.get("content", ""))] if m.get("content") else []

            mode_str = m.get("context_mode", "compress")
            try:
                context_mode = ContextMode(mode_str)
            except ValueError:
                context_mode = ContextMode.COMPRESS

            timestamp = m.get("timestamp", "")
            exchange_id = m.get("exchange_id")
            tokens = m.get("tokens", 0)

            for i, block in enumerate(content_blocks):
                legacy_turns.append(Turn(
                    role=m["role"],
                    content_block=block,
                    tokens=tokens if i == 0 else 0,
                    timestamp=timestamp,
                    context_mode=context_mode,
                    summary=m.get("summary", "") if i == 0 else "",
                    exchange_id=exchange_id,
                ))
        return legacy_turns

    def rehydrate(
        self,
        turns: list[Turn],
        archive_turn_index: int,
    ) -> list[Turn]:
        """Rehydrate archived turns back into the turn list.

        Args:
            turns: The current turn list containing an archive block
            archive_turn_index: Index of the turn containing the ArchiveBlock

        Returns:
            New turn list with archive replaced by original turns

        Raises:
            ArchiveError: If the turn doesn't contain an archive block or rehydration fails
        """
        if archive_turn_index < 0 or archive_turn_index >= len(turns):
            raise ArchiveError(f"Invalid archive turn index: {archive_turn_index}")

        archive_turn = turns[archive_turn_index]

        # Get the ArchiveBlock from the turn's content_block
        if not isinstance(archive_turn.content_block, ArchiveBlock):
            raise ArchiveError(f"Turn {archive_turn_index} does not contain an archive block")

        archive_block = archive_turn.content_block

        # Load the archived turns
        archived_turns = self.load_archive(archive_block)

        # Build new turn list: before + archived turns + after
        new_turns = (
            turns[:archive_turn_index]
            + archived_turns
            + turns[archive_turn_index + 1:]
        )

        return new_turns

    def delete_archive(self, archive_block: ArchiveBlock) -> bool:
        """Delete an archive file.

        Args:
            archive_block: The archive block to delete

        Returns:
            True if deleted, False if file didn't exist
        """
        file_path = Path(archive_block.file_path)
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    def get_archive_info(self, archive_block: ArchiveBlock) -> Optional[dict]:
        """Get metadata about an archive without loading all turns.

        Args:
            archive_block: The archive block

        Returns:
            Dict with archive metadata, or None if file not found
        """
        file_path = Path(archive_block.file_path)
        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text())
            # Count turns (new format) or messages (legacy format)
            turn_count = len(data.get("turns", []))
            if turn_count == 0:
                turn_count = len(data.get("messages", []))
            return {
                "archive_id": data.get("archive_id"),
                "session_id": data.get("session_id"),
                "created": data.get("created"),
                "summary": data.get("summary"),
                "turn_start": data.get("turn_start"),
                "turn_end": data.get("turn_end"),
                "message_count": turn_count,
            }
        except (IOError, json.JSONDecodeError):
            return None

    # =========================================================================
    # Async versions of file I/O methods
    # =========================================================================

    async def archive_turns_async(
        self,
        session_id: str,
        turns: list[Turn],
        turn_start: int,
        turn_end: int,
        summary: str | ArchiveSummary,
    ) -> tuple[ArchiveBlock, list[Turn]]:
        """Async version of archive_turns()."""
        if turn_start < 0 or turn_end > len(turns) or turn_start >= turn_end:
            raise ArchiveError(
                f"Invalid turn range: {turn_start}-{turn_end} (session has {len(turns)} turns)"
            )

        to_archive = turns[turn_start:turn_end]
        token_estimate = sum(t.tokens for t in to_archive)
        archive_id = str(uuid.uuid4())
        archive_dir = self._get_session_archive_dir(session_id)
        archive_dir.mkdir(parents=True, exist_ok=True)
        file_path = archive_dir / f"{archive_id}.json"

        if isinstance(summary, ArchiveSummary):
            structured_summary = summary
            plain_summary = summary.work_done or f"Archived {len(to_archive)} turns"
        else:
            structured_summary = None
            plain_summary = summary

        archive_data = {
            "archive_id": archive_id,
            "session_id": session_id,
            "created": datetime.now().isoformat(),
            "summary": plain_summary,
            "turn_start": turn_start,
            "turn_end": turn_end,
            "turns": [self._serialize_turn(t) for t in to_archive],
        }
        if structured_summary:
            archive_data["structured_summary"] = {
                "files_modified": structured_summary.files_modified,
                "work_done": structured_summary.work_done,
                "key_decisions": structured_summary.key_decisions,
            }

        try:
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(archive_data, indent=2))
        except IOError as e:
            raise ArchiveError(f"Failed to write archive file: {e}")

        archive_block = ArchiveBlock(
            archive_id=archive_id,
            file_path=str(file_path),
            summary=plain_summary,
            structured_summary=structured_summary,
            turn_start=turn_start,
            turn_end=turn_end,
            message_count=len(to_archive),
            token_estimate=token_estimate,
        )

        archive_turn = Turn(
            role="system",
            content_block=archive_block,
        )

        new_turns = turns[:turn_start] + [archive_turn] + turns[turn_end:]
        return archive_block, new_turns

    async def load_archive_async(self, archive_block: ArchiveBlock) -> list[Turn]:
        """Async version of load_archive()."""
        file_path = Path(archive_block.file_path)
        if not file_path.exists():
            raise ArchiveError(f"Archive file not found: {file_path}")

        try:
            async with aiofiles.open(file_path, encoding="utf-8") as f:
                content = await f.read()
            data = json.loads(content)
        except (IOError, json.JSONDecodeError) as e:
            raise ArchiveError(f"Failed to read archive file: {e}")

        if "turns" in data:
            return [self._deserialize_turn(t) for t in data["turns"]]

        # Legacy format
        legacy_turns = []
        for m in data.get("messages", []):
            raw_blocks = m.get("content_blocks", [])
            if raw_blocks:
                content_blocks = [self._deserialize_content_block(b) for b in raw_blocks]
            else:
                content_blocks = [TextBlock(text=m.get("content", ""))] if m.get("content") else []

            mode_str = m.get("context_mode", "compress")
            try:
                context_mode = ContextMode(mode_str)
            except ValueError:
                context_mode = ContextMode.COMPRESS

            timestamp = m.get("timestamp", "")
            exchange_id = m.get("exchange_id")
            tokens = m.get("tokens", 0)

            for i, block in enumerate(content_blocks):
                legacy_turns.append(Turn(
                    role=m["role"],
                    content_block=block,
                    tokens=tokens if i == 0 else 0,
                    timestamp=timestamp,
                    context_mode=context_mode,
                    summary=m.get("summary", "") if i == 0 else "",
                    exchange_id=exchange_id,
                ))
        return legacy_turns

    async def rehydrate_async(
        self,
        turns: list[Turn],
        archive_turn_index: int,
    ) -> list[Turn]:
        """Async version of rehydrate()."""
        if archive_turn_index < 0 or archive_turn_index >= len(turns):
            raise ArchiveError(f"Invalid archive turn index: {archive_turn_index}")

        archive_turn = turns[archive_turn_index]
        if not isinstance(archive_turn.content_block, ArchiveBlock):
            raise ArchiveError(f"Turn {archive_turn_index} does not contain an archive block")

        archive_block = archive_turn.content_block
        archived_turns = await self.load_archive_async(archive_block)

        new_turns = (
            turns[:archive_turn_index]
            + archived_turns
            + turns[archive_turn_index + 1:]
        )
        return new_turns
