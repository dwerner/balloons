#!/usr/bin/env python3
"""Balloons - A TUI wrapper for Claude CLI."""

import argparse
import os
import sys

from app import BalloonsApp
from config import get_config
from core.debug_log import debug_log
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
        help="Start a new session immediately",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available sessions and exit",
    )
    parser.add_argument(
        "--backend", "-b",
        metavar="NAME",
        help="Use a specific backend from config (e.g., llama70b)",
    )
    parser.add_argument(
        "--list-backends",
        action="store_true",
        help="List available backends and exit",
    )

    args = parser.parse_args()

    # Load config and set up backend
    config = get_config()

    # Configure debug log persistence if enabled
    if config.debug_log_file:
        debug_log.set_log_file(config.debug_log_file)

    if args.list_backends:
        print(f"Available backends (default: {config.default_backend}):")
        for name, backend in config.backends.items():
            marker = " *" if name == config.default_backend else ""
            if backend.base_url:
                print(f"  {name}{marker} -> {backend.base_url}")
            else:
                print(f"  {name}{marker} (native Claude API)")
        return

    # Get backend environment (will be passed to child processes)
    backend_name = args.backend or config.default_backend
    backend_env = config.get_env_for_backend(backend_name)

    if args.list:
        sessions = Session.list_sessions()
        if not sessions:
            print("No sessions found.")
        else:
            print(f"{'ID':<40} {'Created':<20} {'Title/Model'}")
            print("-" * 80)
            for session_id, created, model, title in sessions:
                display = title[:30] if title else model
                print(f"{session_id:<40} {created[:19]:<20} {display}")
        return

    session = None

    if args.resume:
        session = Session.load(args.resume)
        if session is None:
            print(f"Error: Session '{args.resume}' not found.", file=sys.stderr)
            sys.exit(1)
    elif args.new:
        session = Session()

    app = BalloonsApp(session=session, backend_env=backend_env)
    app.run()


if __name__ == "__main__":
    main()
