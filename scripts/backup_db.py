#!/usr/bin/env python3
"""LMDB backup and recovery utilities for balloons.

Provides commands for:
- Creating timestamped backups of the LMDB database
- Exporting data to portable JSON format
- Importing data from JSON exports
- Checking database health
- Listing and restoring from backups

Usage:
    # Check database health
    python scripts/backup_db.py health

    # Create a backup
    python scripts/backup_db.py backup

    # List available backups
    python scripts/backup_db.py list-backups

    # Restore from a backup
    python scripts/backup_db.py restore <backup_path>

    # Export to JSON
    python scripts/backup_db.py export /path/to/export

    # Import from JSON
    python scripts/backup_db.py import /path/to/export

    # Full help
    python scripts/backup_db.py --help
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


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def cmd_health(args):
    """Check database health."""
    db_path = str(args.db_path)

    try:
        report = balloons_py.health_check(db_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(report, indent=2))
        if not report["is_healthy"]:
            sys.exit(1)
        return

    print(f"Checking health of: {db_path}")
    print("-" * 60)

    # Pretty print
    status = "HEALTHY" if report["is_healthy"] else "UNHEALTHY"
    status_color = "\033[92m" if report["is_healthy"] else "\033[91m"
    reset = "\033[0m"

    print(f"Status:          {status_color}{status}{reset}")
    print(f"Can open:        {'Yes' if report['can_open'] else 'No'}")
    print(f"Sessions:        {report['session_count']}")
    print(f"Turns:           {report['turn_count']}")
    print(f"Size:            {format_size(report['size_bytes'])}")

    if report["orphaned_turns"] > 0:
        print(f"Orphaned turns:  {report['orphaned_turns']}")
    if report["missing_turns"] > 0:
        print(f"Missing turns:   {report['missing_turns']}")

    if report["issues"]:
        print("\nIssues found:")
        for issue in report["issues"]:
            print(f"  - {issue}")

    if not report["is_healthy"]:
        sys.exit(1)


def cmd_backup(args):
    """Create a backup of the database."""
    db_path = str(args.db_path)
    backup_dir = str(args.backup_dir) if args.backup_dir else None

    print(f"Creating backup of: {db_path}")

    try:
        result = balloons_py.create_backup(db_path, backup_dir)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"Backup created successfully!")
    print(f"  Path:     {result['backup_path']}")
    print(f"  Size:     {format_size(result['size_bytes'])}")
    print(f"  Files:    {result['files_copied']}")
    print(f"  Time:     {result['timestamp']}")


def cmd_list_backups(args):
    """List available backups."""
    db_path = str(args.db_path)

    try:
        backups = balloons_py.list_backups(db_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(backups, indent=2))
        return

    if not backups:
        print(f"No backups found for: {db_path}")
        return

    print(f"Found {len(backups)} backup(s):\n")
    print(f"{'Timestamp':<20} {'Size':<12} {'Path'}")
    print("-" * 80)

    for backup in backups:
        ts = backup["timestamp"]
        size = format_size(backup["size_bytes"])
        path = backup["backup_path"]
        print(f"{ts:<20} {size:<12} {path}")


def cmd_restore(args):
    """Restore from a backup."""
    backup_path = str(args.backup_path)
    target_path = str(args.target_path) if args.target_path else str(args.db_path)

    if not args.force and Path(target_path).exists():
        print(f"Warning: Target path exists: {target_path}")
        response = input("Overwrite? [y/N] ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(1)

    print(f"Restoring from: {backup_path}")
    print(f"To: {target_path}")

    try:
        result = balloons_py.restore_from_backup(backup_path, target_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"Restore complete!")
    print(f"  Size:     {format_size(result['size_bytes'])}")
    print(f"  Files:    {result['files_copied']}")


def cmd_export(args):
    """Export database to JSON."""
    db_path = str(args.db_path)
    export_path = str(args.export_path)

    if Path(export_path).exists() and not args.force:
        print(f"Warning: Export path exists: {export_path}")
        response = input("Overwrite? [y/N] ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(1)

    print(f"Exporting: {db_path}")
    print(f"To: {export_path}")

    try:
        result = balloons_py.export_to_json(db_path, export_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"Export complete!")
    print(f"  Sessions: {result['sessions_exported']}")
    print(f"  Turns:    {result['turns_exported']}")
    print(f"  Size:     {format_size(result['size_bytes'])}")


def cmd_import(args):
    """Import from JSON export."""
    export_path = str(args.export_path)
    target_path = str(args.target_path) if args.target_path else str(args.db_path)

    print(f"Importing from: {export_path}")
    print(f"To: {target_path}")

    try:
        result = balloons_py.import_from_json(export_path, target_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"Import complete!")
    print(f"  Imported: {result['sessions_imported']} sessions ({result['turns_imported']} turns)")
    print(f"  Skipped:  {result['sessions_skipped']} sessions (already existed)")


def cmd_recover(args):
    """Recover sessions from one database to another."""
    source_path = str(args.source_path)
    target_path = str(args.target_path) if args.target_path else str(args.db_path)

    print(f"Recovering from: {source_path}")
    print(f"To: {target_path}")

    try:
        result = balloons_py.recover_database(source_path, target_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"Recovery complete!")
    print(f"  Sessions:  {result['recovered']} recovered, {result['skipped']} skipped, {result['failed']} failed")
    if result.get('history_entries', 0) > 0:
        print(f"  History:   {result['history_entries']} entries")
    if result.get('goals_recovered', 0) > 0:
        print(f"  Goals:     {result['goals_recovered']}")
    if result.get('plans_recovered', 0) > 0:
        print(f"  Plans:     {result['plans_recovered']}")
    if result.get('todos_recovered', 0) > 0:
        print(f"  Todos:     {result['todos_recovered']} ({result.get('links_recovered', 0)} links, {result.get('dependencies_recovered', 0)} deps)")
    if result.get('bindings_recovered', 0) > 0:
        print(f"  Bindings:  {result['bindings_recovered']}")


def main():
    parser = argparse.ArgumentParser(
        description="LMDB backup and recovery utilities for balloons",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to LMDB database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Health check
    health_parser = subparsers.add_parser("health", help="Check database health")
    health_parser.set_defaults(func=cmd_health)

    # Backup
    backup_parser = subparsers.add_parser("backup", help="Create a backup")
    backup_parser.add_argument(
        "--backup-dir", "-o",
        type=Path,
        help="Custom backup directory (default: next to source)",
    )
    backup_parser.set_defaults(func=cmd_backup)

    # List backups
    list_parser = subparsers.add_parser("list-backups", help="List available backups")
    list_parser.set_defaults(func=cmd_list_backups)

    # Restore
    restore_parser = subparsers.add_parser("restore", help="Restore from a backup")
    restore_parser.add_argument("backup_path", type=Path, help="Path to backup directory")
    restore_parser.add_argument(
        "--target", "-t",
        dest="target_path",
        type=Path,
        help="Target path (default: --db-path)",
    )
    restore_parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite target without prompting",
    )
    restore_parser.set_defaults(func=cmd_restore)

    # Export
    export_parser = subparsers.add_parser("export", help="Export to JSON")
    export_parser.add_argument("export_path", type=Path, help="Export directory")
    export_parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite export without prompting",
    )
    export_parser.set_defaults(func=cmd_export)

    # Import
    import_parser = subparsers.add_parser("import", help="Import from JSON export")
    import_parser.add_argument("export_path", type=Path, help="Path to export directory")
    import_parser.add_argument(
        "--target", "-t",
        dest="target_path",
        type=Path,
        help="Target database path (default: --db-path)",
    )
    import_parser.set_defaults(func=cmd_import)

    # Recover (database-to-database)
    recover_parser = subparsers.add_parser("recover", help="Recover from another LMDB database")
    recover_parser.add_argument("source_path", type=Path, help="Source database directory")
    recover_parser.add_argument(
        "--target", "-t",
        dest="target_path",
        type=Path,
        help="Target database path (default: --db-path)",
    )
    recover_parser.set_defaults(func=cmd_recover)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
