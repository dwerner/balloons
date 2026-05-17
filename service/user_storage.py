"""User storage implementations.

Supports two backends:
1. JSON file (~/.balloons/users.json) - Original, simple implementation
2. LMDB (~/.balloons/sessions.lmdb) - Unified storage with sessions

The factory function get_user_storage() automatically selects:
- LMDB if the Rust storage module is available
- JSON file as fallback

Migration: Run `python scripts/migrate_users_to_lmdb.py` to move
users from JSON to LMDB when upgrading.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import aiofiles

from service.user_auth import User, UserStorage

if TYPE_CHECKING:
    from core.async_storage import LmdbUserStorage

logger = logging.getLogger(__name__)

# Default path for user storage
DEFAULT_USERS_PATH = Path.home() / ".balloons" / "users.json"


class JsonFileUserStorage(UserStorage):
    """User storage backed by a JSON file.

    Thread-safe via asyncio lock. File is read/written atomically.
    """

    def __init__(self, path: Optional[Path] = None):
        """Initialize storage.

        Args:
            path: Path to JSON file. Defaults to ~/.balloons/users.json
        """
        self._path = path or DEFAULT_USERS_PATH
        self._lock = asyncio.Lock()
        self._cache: dict[str, User] | None = None

    async def _ensure_loaded(self) -> dict[str, User]:
        """Load users from file if not cached.

        Returns:
            Dict mapping user ID to User
        """
        if self._cache is not None:
            return self._cache

        self._cache = {}

        if not self._path.exists():
            return self._cache

        try:
            async with aiofiles.open(self._path, "r", encoding="utf-8") as f:
                content = await f.read()
            data = json.loads(content)

            for user_data in data.get("users", []):
                user = self._user_from_dict(user_data)
                self._cache[user.id] = user

        except Exception as e:
            logger.error(f"Failed to load users from {self._path}: {e}")

        return self._cache

    async def _save(self) -> None:
        """Save users to file."""
        if self._cache is None:
            return

        # Ensure directory exists
        self._path.parent.mkdir(parents=True, exist_ok=True)

        data = {"users": [self._user_to_dict(u) for u in self._cache.values()]}

        # Write atomically via temp file
        temp_path = self._path.with_suffix(".json.tmp")
        try:
            async with aiofiles.open(temp_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, indent=2))
            temp_path.replace(self._path)
        except Exception as e:
            logger.error(f"Failed to save users to {self._path}: {e}")
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _user_to_dict(self, user: User) -> dict:
        """Convert User to dict for JSON storage."""
        return {
            "id": user.id,
            "username": user.username,
            "password_hash": user.password_hash,
            "role": user.role,
            "created_at": user.created_at.isoformat(),
            "created_by": user.created_by,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "disabled": user.disabled,
        }

    def _user_from_dict(self, data: dict) -> User:
        """Convert dict to User."""
        return User(
            id=data["id"],
            username=data["username"],
            password_hash=data["password_hash"],
            role=data["role"],
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by"),
            last_login=(
                datetime.fromisoformat(data["last_login"])
                if data.get("last_login")
                else None
            ),
            disabled=data.get("disabled", False),
        )

    async def get_by_id(self, user_id: str) -> Optional[User]:
        """Get a user by ID."""
        async with self._lock:
            users = await self._ensure_loaded()
            return users.get(user_id)

    async def get_by_username(self, username: str) -> Optional[User]:
        """Get a user by username (case-insensitive)."""
        async with self._lock:
            users = await self._ensure_loaded()
            username_lower = username.lower()
            for user in users.values():
                if user.username.lower() == username_lower:
                    return user
            return None

    async def list_all(self) -> list[User]:
        """List all users."""
        async with self._lock:
            users = await self._ensure_loaded()
            return list(users.values())

    async def save(self, user: User) -> None:
        """Save a user (create or update)."""
        async with self._lock:
            users = await self._ensure_loaded()
            users[user.id] = user
            await self._save()

    async def delete(self, user_id: str) -> None:
        """Delete a user by ID."""
        async with self._lock:
            users = await self._ensure_loaded()
            if user_id in users:
                del users[user_id]
                await self._save()


# Singleton instance (can be either JSON or LMDB backend)
_user_storage_instance: UserStorage | None = None


def _lmdb_available() -> bool:
    """Check if LMDB storage is available."""
    try:
        import balloons_py
        # Check if the user methods exist
        return hasattr(balloons_py.Storage, 'save_user')
    except ImportError:
        return False


async def get_user_storage() -> UserStorage:
    """Get the default user storage instance (singleton).

    Automatically selects the best available backend:
    - LMDB if Rust storage module is available (preferred)
    - JSON file as fallback

    Returns:
        UserStorage implementation (either LmdbUserStorage or JsonFileUserStorage)
    """
    global _user_storage_instance
    if _user_storage_instance is None:
        if _lmdb_available():
            from core.async_storage import LmdbUserStorage
            _user_storage_instance = LmdbUserStorage()
            logger.info("Using LMDB backend for user storage")
        else:
            _user_storage_instance = JsonFileUserStorage()
            logger.info("Using JSON file backend for user storage (LMDB not available)")
    return _user_storage_instance


async def get_json_user_storage() -> JsonFileUserStorage:
    """Get JSON file user storage (for migration or explicit use).

    Returns:
        JsonFileUserStorage instance
    """
    return JsonFileUserStorage()


async def get_lmdb_user_storage() -> "LmdbUserStorage":
    """Get LMDB user storage (requires Rust module).

    Raises:
        RuntimeError: If LMDB storage is not available

    Returns:
        LmdbUserStorage instance
    """
    if not _lmdb_available():
        raise RuntimeError(
            "LMDB storage not available. "
            "Run 'maturin develop' in balloons-rs/ to build it."
        )
    from core.async_storage import LmdbUserStorage
    return LmdbUserStorage()
