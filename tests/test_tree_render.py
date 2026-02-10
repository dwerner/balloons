#!/usr/bin/env python3
"""Test script to verify ContextTreeView renders correctly with TreeState.

Usage:
    python test_tree_render.py [--session SESSION_ID] [--headless]

Renders the tree once and exits, printing any errors encountered.
"""

import argparse
import asyncio
import sys
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from widgets import ContextTreeView
from core.tree_state import TreeState
from session import Session


@pytest.fixture
def session(temp_storage):
    """Create a test session."""
    sess = Session()
    sess.add_message("user", "Test message")
    sess.add_message("assistant", "Test reply")
    return sess


async def test_headless(session: Session, temp_storage):
    """Test tree state population without Textual app (no TUI)."""
    print("=== Headless Test ===")

    tree_state = TreeState()

    # Simulate what ContextTreeView.load_all_sessions does to TreeState
    # First add current session
    tree_state.add_session(session, is_current=True)

    # Load all session metadata
    all_metadata = []
    async for meta in Session.list_sessions():
        all_metadata.append(meta)
    for meta in all_metadata:
        if meta["id"] != session.id:
            tree_state.add_session_from_metadata(meta, is_current=False)

    # Load full current session
    tree_state.load_session(session.id, session)

    # Print results
    sessions = list(tree_state._sessions.keys())
    print(f"Sessions in TreeState: {len(sessions)}")
    print(f"Current session: {tree_state._current_session_id}")
    print(f"Streaming sessions: {tree_state._streaming_sessions}")

    # Check loaded sessions
    loaded_count = sum(1 for s in tree_state._sessions.values() if s.turns is not None)
    print(f"Sessions with turns loaded: {loaded_count}")

    # Print first few
    if sessions:
        print(f"\nFirst 5 sessions:")
        for sid in sessions[:5]:
            data = tree_state._sessions[sid]
            loaded = f"turns={len(data.turns)}" if data.turns is not None else "lazy"
            print(f"  - {sid[:12]}... ({loaded})")

    # Test context mode operations
    if tree_state._current_session_id:
        current_data = tree_state._sessions.get(tree_state._current_session_id)
        if current_data and current_data.turns:
            print(f"\nContext modes for current session turns:")
            for i in range(min(3, len(current_data.turns))):
                mode = tree_state.get_context_mode(tree_state._current_session_id, i)
                print(f"  Turn {i}: {mode}")

    print("\n=== Headless test PASSED ===")
    return True


async def test_with_textual(session: Session, temp_storage):
    """Test full Textual app rendering."""
    from textual.app import App, ComposeResult
    from textual.containers import Container

    class TreeTestApp(App):
        CSS = """
        #tree-container {
            width: 60;
            height: 100%;
            border: solid green;
        }
        ContextTreeView {
            width: 100%;
            height: 100%;
        }
        """

        def __init__(self, sess: Session):
            super().__init__()
            self._session = sess
            self._tree_state = TreeState()
            self.test_results = {"session_count": 0, "current_session": None}

        def compose(self) -> ComposeResult:
            with Container(id="tree-container"):
                yield ContextTreeView(tree_state=self._tree_state)

    app = TreeTestApp(session)
    async with app.run_test() as pilot:
        # Load sessions
        context_tree = app.query_one(ContextTreeView)
        await context_tree.load_all_sessions(session)

        # Verify
        app.test_results["session_count"] = len(app._tree_state._sessions)
        app.test_results["current_session"] = app._tree_state._current_session_id

    # Assertions
    assert app.test_results["session_count"] >= 1
    assert app.test_results["current_session"] == session.id


def main():
    parser = argparse.ArgumentParser(description="Test ContextTreeView rendering")
    parser.add_argument(
        "--session", "-s",
        metavar="SESSION_ID",
        help="Load a specific session (default: create new empty session)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run headless test only (no Textual)",
    )
    parser.add_argument(
        "--textual",
        action="store_true",
        help="Run Textual app test (headless mode)",
    )
    args = parser.parse_args()

    # Load or create session
    if args.session:
        session = asyncio.run(Session.load(args.session))
        if session is None:
            print(f"Error: Session '{args.session}' not found.", file=sys.stderr)
            sys.exit(1)
        print(f"Using session: {args.session}")
        temp_dir = None  # Using real session, no temp dir needed
    else:
        # Create temp dir for ephemeral test session to avoid polluting real sessions
        temp_dir = tempfile.mkdtemp(prefix="balloons_test_")
        temp_sessions = Path(temp_dir) / "sessions"
        temp_sessions.mkdir()
        # Patch session storage to use temp dir
        import session as session_module
        session_module.SESSIONS_DIR = temp_sessions
        session_module.INDEX_FILE = temp_sessions / "index.json"
        session = Session()
        print(f"Using new empty session (temp dir: {temp_dir})")

    success = True

    # Default: run both tests
    if not args.headless and not args.textual:
        args.headless = True
        args.textual = True

    if args.headless:
        success = asyncio.run(test_headless(session)) and success

    if args.textual:
        success = asyncio.run(test_with_textual(session)) and success

    # Clean up temp dir if used
    if temp_dir:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Cleaned up temp dir: {temp_dir}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
