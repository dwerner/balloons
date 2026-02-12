#!/usr/bin/env python3
"""Migrate goal data from JSON files to LMDB storage.

Reads JSON files from ~/.balloons/goals/{goals,plans,todos,links,dependencies,bindings}/
and writes them to the LMDB database via the Rust backend.

Usage:
    # Dry run (show what would be migrated)
    python scripts/migrate_goals_to_lmdb.py --dry-run

    # Run migration
    python scripts/migrate_goals_to_lmdb.py

    # Run migration and backup JSON files
    python scripts/migrate_goals_to_lmdb.py --backup

    # Force re-migration even if data exists in LMDB
    python scripts/migrate_goals_to_lmdb.py --force
"""

import argparse
import asyncio
import json
import shutil
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from storage_schema import (
    GoalData, PlanData, TodoData, TodoPlanLink, TodoDependency, SessionBinding
)


# Source directory for JSON files
JSON_GOALS_DIR = Path.home() / ".balloons" / "goals"

# Backup directory
BACKUP_DIR = Path.home() / ".balloons" / "goals.bak"


def load_json_file(path: Path) -> dict | None:
    """Load a single JSON file, returning None on error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  Warning: Failed to load {path}: {e}")
        return None


def load_all_json_files(subdir: str) -> list[dict]:
    """Load all JSON files from a subdirectory."""
    dir_path = JSON_GOALS_DIR / subdir
    if not dir_path.exists():
        return []

    results = []
    for json_file in sorted(dir_path.glob("*.json")):
        data = load_json_file(json_file)
        if data:
            results.append(data)
    return results


def dict_to_goal(data: dict) -> GoalData:
    """Convert a dict to GoalData."""
    return GoalData(
        id=data["id"],
        title=data["title"],
        description=data["description"],
        weight=data["weight"],
        status=data["status"],
        acceptance_criteria=data.get("acceptance_criteria", []),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        completed_at=data.get("completed_at"),
        supersedes_id=data.get("supersedes_id"),
    )


def dict_to_plan(data: dict) -> PlanData:
    """Convert a dict to PlanData."""
    return PlanData(
        id=data["id"],
        goal_id=data["goal_id"],
        title=data["title"],
        description=data["description"],
        status=data["status"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        completed_at=data.get("completed_at"),
        postmortem=data.get("postmortem"),
    )


def dict_to_todo(data: dict) -> TodoData:
    """Convert a dict to TodoData."""
    return TodoData(
        id=data["id"],
        title=data["title"],
        description=data["description"],
        status=data["status"],
        is_spike=data.get("is_spike", False),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        completed_at=data.get("completed_at"),
        timebox_minutes=data.get("timebox_minutes"),
    )


def dict_to_link(data: dict) -> TodoPlanLink:
    """Convert a dict to TodoPlanLink."""
    return TodoPlanLink(
        todo_id=data["todo_id"],
        plan_id=data["plan_id"],
        created_at=data["created_at"],
    )


def dict_to_dependency(data: dict) -> TodoDependency:
    """Convert a dict to TodoDependency."""
    return TodoDependency(
        todo_id=data["todo_id"],
        depends_on_id=data["depends_on_id"],
        created_at=data["created_at"],
    )


def dict_to_binding(data: dict) -> SessionBinding:
    """Convert a dict to SessionBinding."""
    return SessionBinding(
        id=data["id"],
        session_id=data["session_id"],
        entity_type=data["entity_type"],
        entity_id=data["entity_id"],
        role=data["role"],
        created_at=data["created_at"],
        released_at=data.get("released_at"),
    )


async def check_lmdb_has_data() -> tuple[bool, dict[str, int]]:
    """Check if LMDB already has goal data.

    Returns (has_data, counts) where counts is a dict of entity type to count.
    """
    from core.async_storage import get_goal_storage

    storage = await get_goal_storage()

    counts = {
        "goals": len(await storage.list_goals()),
        "plans": len(await storage.list_plans()),
        "todos": len(await storage.list_todos(include_spikes=True)),
        "bindings": len(await storage.list_bindings(active_only=False)),
    }

    has_data = any(v > 0 for v in counts.values())
    return has_data, counts


async def migrate_goals(goals: list[GoalData], dry_run: bool = False) -> int:
    """Migrate goals to LMDB. Returns count of migrated items."""
    if dry_run:
        return len(goals)

    from core.async_storage import get_goal_storage
    storage = await get_goal_storage()

    for goal in goals:
        await storage.save_goal(goal)

    return len(goals)


async def migrate_plans(plans: list[PlanData], dry_run: bool = False) -> int:
    """Migrate plans to LMDB. Returns count of migrated items."""
    if dry_run:
        return len(plans)

    from core.async_storage import get_goal_storage
    storage = await get_goal_storage()

    for plan in plans:
        await storage.save_plan(plan)

    return len(plans)


async def migrate_todos(todos: list[TodoData], dry_run: bool = False) -> int:
    """Migrate todos to LMDB. Returns count of migrated items."""
    if dry_run:
        return len(todos)

    from core.async_storage import get_goal_storage
    storage = await get_goal_storage()

    for todo in todos:
        await storage.save_todo(todo)

    return len(todos)


async def migrate_links(links: list[TodoPlanLink], dry_run: bool = False) -> int:
    """Migrate todo-plan links to LMDB. Returns count of migrated items."""
    if dry_run:
        return len(links)

    from core.async_storage import get_goal_storage
    storage = await get_goal_storage()

    for link in links:
        await storage.save_todo_plan_link(link)

    return len(links)


async def migrate_dependencies(deps: list[TodoDependency], dry_run: bool = False) -> int:
    """Migrate todo dependencies to LMDB. Returns count of migrated items."""
    if dry_run:
        return len(deps)

    from core.async_storage import get_goal_storage
    storage = await get_goal_storage()

    for dep in deps:
        await storage.save_todo_dependency(dep)

    return len(deps)


async def migrate_bindings(bindings: list[SessionBinding], dry_run: bool = False) -> int:
    """Migrate session bindings to LMDB. Returns count of migrated items."""
    if dry_run:
        return len(bindings)

    from core.async_storage import get_goal_storage
    storage = await get_goal_storage()

    for binding in bindings:
        await storage.save_session_binding(binding)

    return len(bindings)


async def verify_migration(
    goals: list[GoalData],
    plans: list[PlanData],
    todos: list[TodoData],
    bindings: list[SessionBinding],
) -> tuple[bool, list[str]]:
    """Verify migration by reading back and comparing counts.

    Returns (success, errors).
    """
    from core.async_storage import get_goal_storage
    storage = await get_goal_storage()

    errors = []

    # Verify goals
    db_goals = await storage.list_goals()
    if len(db_goals) < len(goals):
        errors.append(f"Goals: expected {len(goals)}, found {len(db_goals)}")

    # Verify plans
    db_plans = await storage.list_plans()
    if len(db_plans) < len(plans):
        errors.append(f"Plans: expected {len(plans)}, found {len(db_plans)}")

    # Verify todos
    db_todos = await storage.list_todos(include_spikes=True)
    if len(db_todos) < len(todos):
        errors.append(f"Todos: expected {len(todos)}, found {len(db_todos)}")

    # Verify bindings
    db_bindings = await storage.list_bindings(active_only=False)
    if len(db_bindings) < len(bindings):
        errors.append(f"Bindings: expected {len(bindings)}, found {len(db_bindings)}")

    return len(errors) == 0, errors


def backup_json_files() -> bool:
    """Backup JSON goal files to ~/.balloons/goals.bak/

    Returns True on success.
    """
    if not JSON_GOALS_DIR.exists():
        print("  No JSON files to backup")
        return True

    # Create timestamped backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / timestamp

    try:
        shutil.copytree(JSON_GOALS_DIR, backup_path)
        print(f"  Backed up to {backup_path}")
        return True
    except Exception as e:
        print(f"  Error backing up: {e}")
        return False


async def run_migration(
    dry_run: bool = False,
    force: bool = False,
    backup: bool = False,
    verbose: bool = True,
) -> bool:
    """Run the full migration.

    Args:
        dry_run: If True, don't actually write to LMDB
        force: If True, migrate even if LMDB already has data
        backup: If True, backup JSON files before migration
        verbose: If True, print progress

    Returns:
        True if migration succeeded
    """
    if verbose:
        print("Goal Data Migration: JSON -> LMDB")
        print("=" * 40)

    # Check if JSON source exists
    if not JSON_GOALS_DIR.exists():
        if verbose:
            print(f"\nNo JSON goal directory found at {JSON_GOALS_DIR}")
            print("Nothing to migrate.")
        return True

    # Check if LMDB already has data
    if not dry_run:
        has_data, counts = await check_lmdb_has_data()
        if has_data and not force:
            if verbose:
                print(f"\nLMDB already contains goal data:")
                for k, v in counts.items():
                    print(f"  {k}: {v}")
                print("\nUse --force to re-migrate anyway.")
            return False

    # Load all JSON data
    if verbose:
        print("\nLoading JSON files...")

    goals_data = load_all_json_files("goals")
    plans_data = load_all_json_files("plans")
    todos_data = load_all_json_files("todos")
    links_data = load_all_json_files("links")
    deps_data = load_all_json_files("dependencies")
    bindings_data = load_all_json_files("bindings")

    if verbose:
        print(f"  Goals: {len(goals_data)}")
        print(f"  Plans: {len(plans_data)}")
        print(f"  Todos: {len(todos_data)}")
        print(f"  Links: {len(links_data)}")
        print(f"  Dependencies: {len(deps_data)}")
        print(f"  Bindings: {len(bindings_data)}")

    # Convert to typed objects
    goals = [dict_to_goal(d) for d in goals_data]
    plans = [dict_to_plan(d) for d in plans_data]
    todos = [dict_to_todo(d) for d in todos_data]
    links = [dict_to_link(d) for d in links_data]
    deps = [dict_to_dependency(d) for d in deps_data]
    bindings = [dict_to_binding(d) for d in bindings_data]

    # Backup if requested
    if backup and not dry_run:
        if verbose:
            print("\nBacking up JSON files...")
        if not backup_json_files():
            print("Backup failed, aborting migration")
            return False

    # Run migration
    if verbose:
        action = "Would migrate" if dry_run else "Migrating"
        print(f"\n{action} to LMDB...")

    await migrate_goals(goals, dry_run)
    await migrate_plans(plans, dry_run)
    await migrate_todos(todos, dry_run)
    await migrate_links(links, dry_run)
    await migrate_dependencies(deps, dry_run)
    await migrate_bindings(bindings, dry_run)

    if verbose:
        print("  Done!")

    # Verify
    if not dry_run:
        if verbose:
            print("\nVerifying migration...")
        success, errors = await verify_migration(goals, plans, todos, bindings)
        if success:
            if verbose:
                print("  Verification passed!")
        else:
            if verbose:
                print("  Verification failed:")
                for error in errors:
                    print(f"    - {error}")
            return False

    # Create migration marker file to prevent re-running
    if not dry_run:
        marker_file = JSON_GOALS_DIR / ".migrated"
        try:
            marker_file.write_text(f"Migrated to LMDB on {datetime.now().isoformat()}\n")
        except Exception:
            pass  # Non-critical, just means migration might try again

    if verbose:
        print("\nMigration complete!")
        if dry_run:
            print("(This was a dry run - no data was written)")

    return True


async def needs_migration() -> bool:
    """Check if migration is needed.

    Returns True if:
    - JSON goal files exist AND
    - Migration marker file does not exist (indicates migration already done)

    We avoid checking LMDB here because the app may have already opened it,
    and LMDB doesn't allow multiple opens with different options.
    """
    # Check if migration was already completed
    migration_marker = JSON_GOALS_DIR / ".migrated"
    if migration_marker.exists():
        return False

    # Check if JSON source exists
    if not JSON_GOALS_DIR.exists():
        return False

    # Check if any JSON files exist
    has_json = any(
        (JSON_GOALS_DIR / subdir).exists() and list((JSON_GOALS_DIR / subdir).glob("*.json"))
        for subdir in ["goals", "plans", "todos"]
    )

    return has_json


async def auto_migrate_if_needed(verbose: bool = False) -> bool:
    """Automatically migrate if needed.

    This is intended to be called on application startup.
    Only migrates if JSON files exist and LMDB is empty.

    Returns True if migration happened and succeeded.
    """
    if not await needs_migration():
        return False

    if verbose:
        print("Detected JSON goal data, migrating to LMDB...")

    return await run_migration(dry_run=False, force=False, backup=True, verbose=verbose)


def main():
    parser = argparse.ArgumentParser(
        description="Migrate goal data from JSON files to LMDB storage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without writing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Migrate even if LMDB already has data",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Backup JSON files to ~/.balloons/goals.bak/",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress output (exit code indicates success)",
    )

    args = parser.parse_args()

    success = asyncio.run(run_migration(
        dry_run=args.dry_run,
        force=args.force,
        backup=args.backup,
        verbose=not args.quiet,
    ))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
