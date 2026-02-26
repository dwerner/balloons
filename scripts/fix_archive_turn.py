#!/usr/bin/env python3
"""Fix an archive turn that has message_count=0 or regenerate its summary.

Usage:
    python scripts/fix_archive_turn.py <session_id> list
    python scripts/fix_archive_turn.py <session_id> <archive_id>
    python scripts/fix_archive_turn.py <session_id> <archive_id> --resummarize

This script:
1. Loads the session
2. Finds the turn with the archive block
3. Reads the archive file to get the actual turn count
4. Optionally regenerates the summary using the LLM
5. Updates the archive block with correct data
6. Saves the session
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.async_storage import AsyncStorage
from models import ArchiveBlock, ArchiveSummary


async def resummarize_archive(archive_path: Path, backend_name: str = "claude") -> tuple[str, ArchiveSummary | None]:
    """Regenerate summary for an archive file using the LLM.

    Returns:
        Tuple of (plain_summary, structured_summary)
    """
    from core.summarizer import Summarizer
    from core.runner_factory import create_runner
    from session import Message, Turn
    from core.archiver import Archiver
    from config import Config

    # Load the archive
    with open(archive_path) as f:
        archive_data = json.load(f)

    # Convert turns to messages for the summarizer
    archiver = Archiver()
    turns = [archiver._deserialize_turn(t) for t in archive_data.get("turns", [])]

    # Convert turns to messages (summarizer expects Message objects)
    messages = []
    for turn in turns:
        # Get text content from the turn
        content = ""
        if hasattr(turn.content_block, 'text'):
            content = turn.content_block.text
        elif hasattr(turn.content_block, 'name'):
            # Tool use
            content = f"[Tool: {turn.content_block.name}]"
        elif hasattr(turn.content_block, 'content'):
            # Tool result
            content = str(turn.content_block.content)[:500]

        if content:
            messages.append(Message(role=turn.role, content=content))

    print(f"  Loaded {len(messages)} messages from archive")

    # Load config and get backend
    config = Config.load()
    backend = config.get_backend(backend_name)

    # Create runner and summarizer
    runner = create_runner(backend)
    summarizer = Summarizer(runner)

    print(f"  Generating summary using {backend_name}...")
    summary = await summarizer.generate_archive_summary(messages)

    # Build plain text summary from structured
    plain_summary = summary.work_done
    if summary.files_modified:
        plain_summary = "FILES_MODIFIED:\n" + "\n".join(f"- {f}" for f in summary.files_modified) + "\n\nWORK_DONE:\n" + summary.work_done
        if summary.key_decisions:
            plain_summary += "\n\nKEY_DECISIONS:\n" + "\n".join(f"- {d}" for d in summary.key_decisions)

    return plain_summary, summary


async def fix_archive_turn(session_id: str, archive_id: str, resummarize: bool = False, backend: str = "claude"):
    """Fix an archive turn with incorrect message_count or regenerate summary."""
    storage = AsyncStorage()

    # Load the session
    print(f"Loading session {session_id}...")
    session = await storage.load_session(session_id)
    if not session:
        print(f"Session {session_id} not found")
        return False

    print(f"Session has {len(session.turns)} turns")

    # Find the archive turn
    archive_turn_idx = None
    archive_block = None
    for i, turn in enumerate(session.turns):
        if isinstance(turn.content_block, ArchiveBlock):
            if turn.content_block.archive_id == archive_id or archive_id.startswith(turn.content_block.archive_id[:8]):
                archive_turn_idx = i
                archive_block = turn.content_block
                break

    if archive_turn_idx is None:
        print(f"Archive turn with id {archive_id} not found")
        # List all archive blocks
        print("Found archive blocks:")
        for i, turn in enumerate(session.turns):
            if isinstance(turn.content_block, ArchiveBlock):
                ab = turn.content_block
                print(f"  Turn {i}: archive_id={ab.archive_id}, message_count={ab.message_count}")
        return False

    print(f"Found archive turn at index {archive_turn_idx}")
    print(f"  archive_id: {archive_block.archive_id}")
    print(f"  file_path: {archive_block.file_path}")
    print(f"  current message_count: {archive_block.message_count}")
    print(f"  current summary: {archive_block.summary[:100]}..." if archive_block.summary else "  current summary: (empty)")

    # Load the archive file to get actual turn count
    archive_path = Path(archive_block.file_path)
    if not archive_path.exists():
        print(f"Archive file not found: {archive_path}")
        return False

    with open(archive_path) as f:
        archive_data = json.load(f)

    actual_turn_count = len(archive_data.get("turns", []))
    print(f"  actual turn count in archive file: {actual_turn_count}")

    # Check if we need to do anything
    needs_fix = archive_block.message_count != actual_turn_count
    needs_summary = resummarize or not archive_block.summary

    if not needs_fix and not needs_summary:
        print("Archive is already correct and has a summary, nothing to fix")
        return True

    # Get new summary if requested
    new_summary = archive_block.summary
    new_structured_summary = archive_block.structured_summary

    if needs_summary:
        print("\nRegenerating summary...")
        new_summary, new_structured_summary = await resummarize_archive(archive_path, backend)
        print(f"\nNew summary:\n{new_summary[:500]}...")

    # Create new archive block with correct data
    print(f"\nUpdating archive block...")
    if needs_fix:
        print(f"  message_count: {archive_block.message_count} -> {actual_turn_count}")

    new_archive_block = ArchiveBlock(
        archive_id=archive_block.archive_id,
        file_path=archive_block.file_path,
        summary=new_summary,
        structured_summary=new_structured_summary,
        turn_start=archive_block.turn_start,
        turn_end=archive_block.turn_end,
        message_count=actual_turn_count,
        token_estimate=archive_block.token_estimate,
    )

    # Update the turn
    session.turns[archive_turn_idx].content_block = new_archive_block

    # Also update the archive file with new summary
    if needs_summary:
        archive_data["summary"] = new_summary
        if new_structured_summary:
            archive_data["structured_summary"] = {
                "files_modified": new_structured_summary.files_modified,
                "work_done": new_structured_summary.work_done,
                "key_decisions": new_structured_summary.key_decisions,
            }
        with open(archive_path, "w") as f:
            json.dump(archive_data, f, indent=2)
        print("  Updated archive file with new summary")

    # Save the session
    print("Saving session...")
    await session.save()
    print("Done!")

    return True


async def list_archives(session_id: str):
    """List all archives in a session."""
    storage = AsyncStorage()
    session = await storage.load_session(session_id)
    if not session:
        print(f"Session {session_id} not found")
        return

    print(f"Session has {len(session.turns)} turns")
    print("Archive blocks:")
    found_any = False
    for i, turn in enumerate(session.turns):
        if isinstance(turn.content_block, ArchiveBlock):
            found_any = True
            ab = turn.content_block
            print(f"  Turn {i}: archive_id={ab.archive_id}")
            print(f"           message_count={ab.message_count}")
            summary_preview = ab.summary[:80] if ab.summary else "(no summary)"
            print(f"           summary={summary_preview}...")
            print()

    if not found_any:
        print("  (no archive blocks found)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix archive turns or regenerate summaries")
    parser.add_argument("session_id", help="Session ID")
    parser.add_argument("archive_id", help="Archive ID (or 'list' to show all)")
    parser.add_argument("--resummarize", "-r", action="store_true",
                        help="Regenerate the summary using LLM")
    parser.add_argument("--backend", "-b", default="claude",
                        help="Backend to use for summarization (default: claude)")

    args = parser.parse_args()

    if args.archive_id == "list":
        asyncio.run(list_archives(args.session_id))
    else:
        success = asyncio.run(fix_archive_turn(
            args.session_id,
            args.archive_id,
            resummarize=args.resummarize,
            backend=args.backend
        ))
        sys.exit(0 if success else 1)
