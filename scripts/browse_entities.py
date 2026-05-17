#!/usr/bin/env python3
"""Browse session entities in the LMDB storage.

A utility script for inspecting sessions and turns stored in the balloons database.

Usage:
    # List all sessions
    python scripts/browse_entities.py

    # Show a specific session by name (partial match)
    python scripts/browse_entities.py testing-qwen

    # Show a specific session by ID
    python scripts/browse_entities.py 59b24335-3772-4042-9507-3e860ee01967

    # Show specific turns (by index range)
    python scripts/browse_entities.py testing-qwen --turns 0-5

    # Show only session metadata (no turns)
    python scripts/browse_entities.py testing-qwen --metadata-only

    # Output as JSON
    python scripts/browse_entities.py testing-qwen --json
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import balloons_py
except ImportError:
    print("Error: balloons_py not available", file=sys.stderr)
    print("Run: cd balloons-rs && maturin develop", file=sys.stderr)
    sys.exit(1)


DEFAULT_DB_PATH = Path.home() / ".balloons" / "sessions.lmdb"


def get_storage(db_path: Path = DEFAULT_DB_PATH):
    """Get a storage handle."""
    return balloons_py.Storage(str(db_path))


def list_sessions(storage, limit: int = 50) -> list[dict]:
    """List all sessions with metadata."""
    sessions_json = storage.list_sessions()
    sessions = json.loads(sessions_json)
    return sessions[:limit]


def find_session(storage, query: str) -> dict | None:
    """Find a session by name or ID (partial match)."""
    sessions = list_sessions(storage, limit=1000)
    query_lower = query.lower()

    # Try exact ID match first
    for s in sessions:
        if s.get("id") == query:
            return s

    # Try partial ID match
    for s in sessions:
        if s.get("id", "").startswith(query):
            return s

    # Try name/title match
    for s in sessions:
        name = (s.get("name") or s.get("title") or "").lower()
        if query_lower in name:
            return s

    return None


def load_session_metadata(storage, session_id: str) -> dict | None:
    """Load full session metadata (without turns)."""
    session_json = storage.load_session(session_id)
    if session_json:
        return json.loads(session_json)
    return None


def load_turns(storage, session_id: str) -> list[dict]:
    """Load all turns for a session."""
    turns_json = storage.load_turns(session_id)
    return json.loads(turns_json)


def format_turn_preview(turn: dict, max_len: int = 80) -> str:
    """Get a short preview of a turn's content."""
    cb = turn.get("content_block", {})
    block_type = cb.get("type", "unknown")

    if block_type == "text":
        text = cb.get("text", "")
        # First line, cleaned up
        first_line = text.split("\n")[0].strip()
        if len(first_line) > max_len:
            return first_line[:max_len - 3] + "..."
        return first_line

    elif block_type == "tool_use":
        name = cb.get("name", "unknown")
        return f"tool: {name}"

    elif block_type == "tool_result":
        is_error = cb.get("is_error", False)
        content = cb.get("content", "")[:50].replace("\n", " ")
        prefix = "error: " if is_error else ""
        return f"{prefix}{content}"

    elif block_type == "slide":
        title = cb.get("title", "")
        return f"slide: {title[:50]}"

    elif block_type == "fork":
        return f"fork: {cb.get('fork_name', '')}"

    elif block_type == "merge":
        return f"merge: {cb.get('fork_name', '')}"

    elif block_type == "interruption":
        return f"interruption: {cb.get('reason', '')}"

    elif block_type == "error":
        return f"error: {cb.get('reason', '')}"

    return block_type


def print_sessions_list(sessions: list[dict]):
    """Print a formatted list of sessions."""
    print(f"{'ID':<12} {'Name':<40} {'Turns':>6} {'Updated':<20}")
    print("-" * 82)

    for s in sessions:
        sid = s.get("id", "")[:10] + ".."
        name = (s.get("name") or s.get("title") or "(untitled)")[:38]
        turn_count = s.get("turn_count", 0)

        updated = s.get("updated_at", 0)
        if isinstance(updated, (int, float)) and updated > 0:
            from datetime import datetime
            updated = datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M")
        else:
            updated = ""

        print(f"{sid:<12} {name:<40} {turn_count:>6} {updated:<20}")


def print_session_detail(metadata: dict, turns: list[dict], turn_range: tuple[int, int] | None = None):
    """Print detailed session information."""
    print("=" * 80)
    print("SESSION METADATA")
    print("=" * 80)

    print(f"ID:              {metadata.get('id', '')}")
    print(f"Title:           {metadata.get('title', '') or '(untitled)'}")
    print(f"Model:           {metadata.get('model', '')}")
    print(f"Backend:         {metadata.get('backend_name', '') or '(default)'}")
    print(f"Created:         {metadata.get('created', '')[:19]}")
    print(f"Last Modified:   {metadata.get('last_modified', '')[:19]}")
    print(f"Working Dir:     {(metadata.get('working_directories') or [''])[0]}")
    print()
    print(f"Input Tokens:    {metadata.get('total_input_tokens', 0):,}")
    print(f"Output Tokens:   {metadata.get('total_output_tokens', 0):,}")
    print(f"Total Cost:      ${metadata.get('total_cost', 0):.4f}")
    print(f"Context Window:  {metadata.get('context_window', 0):,}")
    print(f"Cached Context:  {metadata.get('cached_context_tokens', 0):,}")
    print()

    # Fork info
    if metadata.get("parent_id"):
        print(f"Parent Session:  {metadata.get('parent_id', '')[:16]}...")
        print(f"Fork Name:       {metadata.get('fork_name', '')}")
        print(f"Fork Status:     {metadata.get('fork_status', '')}")

    if metadata.get("children"):
        print(f"Children:        {len(metadata.get('children', []))} forks")

    print()
    print("=" * 80)
    print(f"TURNS ({len(turns)} total)")
    print("=" * 80)

    # Determine range to show
    start, end = 0, len(turns)
    if turn_range:
        start, end = turn_range
        start = max(0, start)
        end = min(len(turns), end)

    for i in range(start, end):
        turn = turns[i]
        role = turn.get("role", "unknown")
        cb = turn.get("content_block", {})
        block_type = cb.get("type", "unknown")
        tokens = turn.get("tokens", 0)
        mode = turn.get("context_mode", "compress")

        # Role emoji
        role_icon = {
            "user": "👤",
            "assistant": "🤖",
            "tool": "🔧",
            "system": "⚙️",
            "slide": "📊",
        }.get(role, "📝")

        # Mode color hint
        mode_hint = {"copy": "C", "compress": "~", "drop": "X"}.get(mode, "?")

        print(f"\n--- Turn {i} {role_icon} [{role}] type={block_type} tokens={tokens} [{mode_hint}] ---")

        if block_type == "text":
            text = cb.get("text", "")
            if len(text) > 2000:
                print(text[:2000])
                print(f"\n... [{len(text) - 2000} more chars]")
            else:
                print(text)

        elif block_type == "tool_use":
            print(f"Tool: {cb.get('name', '')}")
            print(f"Tool ID: {cb.get('id', '')}")
            input_data = cb.get("input", {})
            input_str = json.dumps(input_data, indent=2)
            if len(input_str) > 500:
                print(f"Input: {input_str[:500]}...")
            else:
                print(f"Input: {input_str}")

        elif block_type == "tool_result":
            print(f"Tool Use ID: {cb.get('tool_use_id', '')}")
            print(f"Is Error: {cb.get('is_error', False)}")
            content = cb.get("content", "")
            if len(content) > 1000:
                print(f"Content: {content[:1000]}")
                print(f"\n... [{len(content) - 1000} more chars]")
            else:
                print(f"Content: {content}")

        elif block_type == "interruption":
            print(f"Reason: {cb.get('reason', '')}")

        elif block_type == "error":
            print(f"Reason: {cb.get('reason', '')}")
            if cb.get("details"):
                print(f"Details: {cb.get('details', '')[:500]}")

        elif block_type == "slide":
            print(f"Title: {cb.get('title', '')}")
            print(f"Content:\n{cb.get('content', '')}")
            if cb.get("notes"):
                print(f"Notes: {cb.get('notes', '')}")

        elif block_type == "fork":
            print(f"Fork Name: {cb.get('fork_name', '')}")
            print(f"Child Session: {cb.get('child_session_id', '')}")
            print(f"Status: {cb.get('status', '')}")

        elif block_type == "merge":
            print(f"Fork Name: {cb.get('fork_name', '')}")
            print(f"Child Session: {cb.get('child_session_id', '')}")
            print(f"Message: {cb.get('message', '')}")

        else:
            print(json.dumps(cb, indent=2))

    if turn_range and (start > 0 or end < len(turns)):
        shown = end - start
        print(f"\n... showing turns {start}-{end-1} of {len(turns)} total")


def print_json_output(metadata: dict, turns: list[dict]):
    """Print session data as JSON."""
    output = {
        "metadata": metadata,
        "turns": turns,
    }
    print(json.dumps(output, indent=2))


def parse_turn_range(range_str: str) -> tuple[int, int]:
    """Parse a turn range like '0-5' or '10'."""
    if "-" in range_str:
        parts = range_str.split("-")
        return int(parts[0]), int(parts[1]) + 1
    else:
        idx = int(range_str)
        return idx, idx + 1


def main():
    parser = argparse.ArgumentParser(
        description="Browse session entities in balloons storage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Session name or ID to search for (partial match)",
    )
    parser.add_argument(
        "--turns", "-t",
        help="Turn range to show (e.g., '0-5' or '10')",
    )
    parser.add_argument(
        "--metadata-only", "-m",
        action="store_true",
        help="Show only session metadata, no turns",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to LMDB database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=50,
        help="Max sessions to list (default: 50)",
    )

    args = parser.parse_args()

    # Open storage
    storage = get_storage(args.db_path)

    if not args.query:
        # List all sessions
        sessions = list_sessions(storage, limit=args.limit)
        if args.json:
            print(json.dumps(sessions, indent=2))
        else:
            print(f"Found {len(sessions)} sessions:\n")
            print_sessions_list(sessions)
        return

    # Find specific session
    session_meta = find_session(storage, args.query)
    if not session_meta:
        print(f"Session not found: {args.query}", file=sys.stderr)
        print("\nAvailable sessions:", file=sys.stderr)
        sessions = list_sessions(storage, limit=20)
        for s in sessions:
            name = s.get("name") or s.get("title") or "(untitled)"
            print(f"  - {name} (id: {s['id'][:16]}...)", file=sys.stderr)
        sys.exit(1)

    session_id = session_meta["id"]

    # Load full metadata
    metadata = load_session_metadata(storage, session_id)
    if not metadata:
        print(f"Failed to load session: {session_id}", file=sys.stderr)
        sys.exit(1)

    # Load turns (unless metadata-only)
    turns = []
    if not args.metadata_only:
        turns = load_turns(storage, session_id)

    # Parse turn range
    turn_range = None
    if args.turns:
        turn_range = parse_turn_range(args.turns)

    # Output
    if args.json:
        print_json_output(metadata, turns)
    else:
        print_session_detail(metadata, turns, turn_range)


if __name__ == "__main__":
    main()
