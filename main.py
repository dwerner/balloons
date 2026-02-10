#!/usr/bin/env python3
"""Balloons - A TUI wrapper for Claude CLI."""

import argparse
import asyncio
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

    # Get backend config (will be used to create runners)
    backend_name = args.backend or config.default_backend
    backend_config = config.get_backend(backend_name)
    # Also get env for backwards compatibility with claude-type backends
    backend_env = config.get_env_for_backend(backend_name)

    if args.list:
        async def list_sessions():
            sessions = []
            for metadata in await Session.list_sessions():
                sessions.append(metadata)
            return sessions
        sessions = asyncio.run(list_sessions())
        if not sessions:
            print("No sessions found.")
        else:
            print(f"{'ID':<40} {'Created':<20} {'Title/Model'}")
            print("-" * 80)
            for session_metadata in sessions:
                session_id = session_metadata["id"]
                # Handle Rust storage: created_at (unix) vs created (ISO)
                created = session_metadata.get("created", "")
                if not created:
                    created_at = session_metadata.get("created_at", 0)
                    if created_at:
                        from datetime import datetime, timezone
                        created = datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat()
                model = session_metadata.get("model", "")
                # Handle Rust storage: name vs title
                title = session_metadata.get("title") or session_metadata.get("name", "")
                display = title[:30] if title else model
                print(f"{session_id:<40} {created[:19]:<20} {display}")
        return

    session = None

    if args.resume:
        session = asyncio.run(Session.load(args.resume))
        if session is None:
            print(f"Error: Session '{args.resume}' not found.", file=sys.stderr)
            sys.exit(1)
    elif args.new:
        session = Session()
        session.set_working_directory(os.getcwd())

    app = BalloonsApp(session=session, backend_config=backend_config)
    app.run()


if __name__ == "__main__":
    main()
