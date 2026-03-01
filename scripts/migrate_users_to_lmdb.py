#!/usr/bin/env python3
"""Migrate user data from JSON file to LMDB.

This script:
1. Reads existing users from ~/.balloons/users.json
2. Writes them to the LMDB database
3. Optionally backs up and removes the JSON file

Usage:
    python scripts/migrate_users_to_lmdb.py [--dry-run] [--no-backup]

Options:
    --dry-run    Show what would be migrated without making changes
    --no-backup  Don't create a backup of users.json (not recommended)
"""

import argparse
import asyncio
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def migrate_users(dry_run: bool = False, create_backup: bool = True) -> bool:
    """Migrate users from JSON to LMDB.

    Args:
        dry_run: If True, only show what would be done
        create_backup: If True, backup users.json before removing

    Returns:
        True if migration was successful or not needed
    """
    from core.async_storage import get_lmdb_user_storage
    from service.user_auth import User

    json_path = Path.home() / ".balloons" / "users.json"

    # Check if JSON file exists
    if not json_path.exists():
        print(f"No users.json found at {json_path}")
        print("Nothing to migrate.")
        return True

    # Read existing users
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading {json_path}: {e}")
        return False

    users_data = data.get("users", [])
    if not users_data:
        print("No users found in users.json")
        return True

    print(f"Found {len(users_data)} users to migrate:")
    for ud in users_data:
        print(f"  - {ud['username']} (role={ud['role']}, id={ud['id'][:8]}...)")

    if dry_run:
        print("\n[DRY RUN] Would migrate these users to LMDB")
        print("[DRY RUN] Would backup users.json to users.json.backup")
        return True

    # Get LMDB storage
    storage = await get_lmdb_user_storage()

    # Check for existing users in LMDB
    existing_users = await storage.list_all()
    if existing_users:
        print(f"\nWarning: Found {len(existing_users)} existing users in LMDB:")
        for u in existing_users:
            print(f"  - {u.username} (id={u.id[:8]}...)")

        response = input("\nContinue and overwrite if IDs match? [y/N] ")
        if response.lower() != 'y':
            print("Migration cancelled")
            return False

    # Migrate each user
    migrated = 0
    for ud in users_data:
        try:
            user = User(
                id=ud["id"],
                username=ud["username"],
                password_hash=ud["password_hash"],
                role=ud["role"],
                created_at=datetime.fromisoformat(ud["created_at"]),
                created_by=ud.get("created_by"),
                last_login=(
                    datetime.fromisoformat(ud["last_login"])
                    if ud.get("last_login")
                    else None
                ),
                disabled=ud.get("disabled", False),
            )
            await storage.save(user)
            print(f"Migrated: {user.username}")
            migrated += 1
        except Exception as e:
            print(f"Error migrating user {ud.get('username', 'unknown')}: {e}")
            return False

    print(f"\nSuccessfully migrated {migrated} users to LMDB")

    # Backup JSON file
    if create_backup:
        backup_path = json_path.with_suffix(".json.backup")
        shutil.copy2(json_path, backup_path)
        print(f"Backed up {json_path} to {backup_path}")

    # Optionally remove JSON file
    response = input("\nRemove users.json? [y/N] ")
    if response.lower() == 'y':
        json_path.unlink()
        print(f"Removed {json_path}")
    else:
        print(f"Kept {json_path} (you can remove it manually)")

    return True


def main():
    parser = argparse.ArgumentParser(description="Migrate users from JSON to LMDB")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--no-backup", action="store_true", help="Don't backup users.json")
    args = parser.parse_args()

    success = asyncio.run(migrate_users(
        dry_run=args.dry_run,
        create_backup=not args.no_backup
    ))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
