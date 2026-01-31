#!/usr/bin/env python3
"""Balloons - A TUI wrapper for Claude CLI."""

import argparse
import sys

from app import BalloonsApp
from session import Session


def main():
    parser = argparse.ArgumentParser(
        description="Balloons - A TUI chat interface for Claude",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--resume", "-r",
        metavar="SESSION_ID",
        help="Resume an existing session by ID",
    )
    parser.add_argument(
        "--new", "-n",
        action="store_true",
        help="Start a new session immediately (skip picker)",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available sessions and exit",
    )

    args = parser.parse_args()

    if args.list:
        sessions = Session.list_sessions()
        if not sessions:
            print("No sessions found.")
        else:
            print(f"{'ID':<40} {'Created':<25} {'Model'}")
            print("-" * 80)
            for session_id, created, model in sessions:
                print(f"{session_id:<40} {created[:19]:<25} {model}")
        return

    session = None
    show_picker = True

    if args.resume:
        session = Session.load(args.resume)
        if session is None:
            print(f"Error: Session '{args.resume}' not found.", file=sys.stderr)
            sys.exit(1)
        show_picker = False
    elif args.new:
        session = Session()
        show_picker = False

    app = BalloonsApp(session=session, show_picker=show_picker)
    app.run()


if __name__ == "__main__":
    main()
