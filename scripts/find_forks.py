#!/usr/bin/env python3
"""Find sessions with forks (children) in the LMDB storage."""

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


def main():
    storage = balloons_py.Storage(str(DEFAULT_DB_PATH))

    # List all sessions
    sessions_json = storage.list_sessions()
    sessions = json.loads(sessions_json)

    print(f"Total sessions: {len(sessions)}\n")

    # Find sessions with children (forks)
    sessions_with_forks = []
    all_child_ids = set()

    for s in sessions:
        session_id = s.get("id")
        # Load full metadata to check for children
        full_json = storage.load_session(session_id)
        if full_json:
            full = json.loads(full_json)
            children = full.get("children", [])
            if children:
                sessions_with_forks.append((s, children))
                for child in children:
                    all_child_ids.add(child.get("session_id"))

    print(f"Sessions with forks: {len(sessions_with_forks)}\n")
    print("=" * 80)

    for s, children in sessions_with_forks:
        name = s.get("name") or s.get("title") or "(untitled)"
        print(f"\n{name} ({s['id'][:12]}...)")
        print(f"  Turn count: {s.get('turn_count', 0)}")
        print(f"  Children ({len(children)}):")
        for child in children:
            child_id = child.get("session_id", "")[:12]
            child_name = child.get("name", "(unnamed)")
            status = child.get("status", "?")
            fork_point = child.get("fork_point", -1)
            print(f"    - {child_name} ({child_id}...) status={status} fork_point={fork_point}")

    # Also look for orphan forks (children not in main list)
    session_ids = {s.get("id") for s in sessions}
    orphans = all_child_ids - session_ids
    if orphans:
        print("\n" + "=" * 80)
        print(f"\nOrphan forks (referenced but not found): {len(orphans)}")
        for orphan in orphans:
            print(f"  - {orphan}")

    # Search for any session mentioning "tokio" or "remove" in content
    print("\n" + "=" * 80)
    print("\nSearching for tokio/remove mentions in session names/titles...")

    for s in sessions:
        name = (s.get("name") or s.get("title") or "").lower()
        if "tokio" in name or "remove" in name or "supervisor" in name or "python" in name:
            print(f"  - {s.get('name') or s.get('title')} ({s['id'][:12]}...)")


if __name__ == "__main__":
    main()
