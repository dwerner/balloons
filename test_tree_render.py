#!/usr/bin/env python3
"""Test script to verify ContextTree renders correctly with TreeState.

Usage:
    python test_tree_render.py [--session SESSION_ID] [--headless]

Renders the tree once and exits, printing any errors encountered.
"""

import argparse
import sys
from io import StringIO

from widgets import ContextTree
from core.tree_state import TreeState
from session import Session


def test_headless(session: Session):
    """Test tree state population without Textual app (no TUI)."""
    print("=== Headless Test ===")

    tree_state = TreeState()

    # Simulate what ContextTree.load_all_sessions does to TreeState
    # First add current session
    tree_state.add_session(session, is_current=True)

    # Load all session metadata
    all_metadata = Session.list_sessions()
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
                turn_key = (tree_state._current_session_id, i)
                mode = tree_state._context_modes.get(turn_key, "NOT SET")
                print(f"  Turn {i}: {mode}")

    print("\n=== Headless test PASSED ===")
    return True


def test_with_textual(session: Session):
    """Test full Textual app rendering."""
    from textual.app import App, ComposeResult
    from textual.containers import Container

    results = {"success": False, "error": None, "info": {}}

    class TreeTestApp(App):
        CSS = """
        #tree-container {
            width: 60;
            height: 100%;
            border: solid green;
        }
        ContextTree {
            width: 100%;
            height: 100%;
        }
        """

        def __init__(self, sess: Session):
            super().__init__()
            self._session = sess
            self._tree_state = TreeState()

        def compose(self) -> ComposeResult:
            with Container(id="tree-container"):
                yield ContextTree(tree_state=self._tree_state)

        async def on_mount(self) -> None:
            try:
                context_tree = self.query_one(ContextTree)
                context_tree.load_all_sessions(self._session)

                # Collect info
                results["info"]["session_count"] = len(self._tree_state._sessions)
                results["info"]["current_session"] = self._tree_state._current_session_id
                results["info"]["streaming"] = list(self._tree_state._streaming_sessions)

                results["success"] = True
                self.set_timer(0.3, lambda: self.exit(0))

            except Exception as e:
                results["error"] = e
                import traceback
                results["traceback"] = traceback.format_exc()
                self.exit(1)

    app = TreeTestApp(session)
    app.run(headless=True)  # Run without actual terminal

    print("\n=== Textual App Test ===")
    if results["success"]:
        print(f"Sessions loaded: {results['info']['session_count']}")
        print(f"Current session: {results['info']['current_session']}")
        print("=== Textual test PASSED ===")
    else:
        print(f"ERROR: {results['error']}")
        if results.get("traceback"):
            print(results["traceback"])
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Test ContextTree rendering")
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
        session = Session.load(args.session)
        if session is None:
            print(f"Error: Session '{args.session}' not found.", file=sys.stderr)
            sys.exit(1)
        print(f"Using session: {args.session}")
    else:
        session = Session()
        print("Using new empty session")

    success = True

    # Default: run both tests
    if not args.headless and not args.textual:
        args.headless = True
        args.textual = True

    if args.headless:
        success = test_headless(session) and success

    if args.textual:
        success = test_with_textual(session) and success

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
