"""Storage abstraction for domain plugins.

Domains can use this to persist state. The default implementation uses
JSON files in ~/.balloons/plugins/{domain_id}/. Domains can override
with their own storage backends (SQLite, LMDB, etc.).

Usage:
    from plugins.storage import JsonFileStorage

    class MyDomain(StatefulDomain):
        def __init__(self):
            self.storage = JsonFileStorage("my-domain")

        async def save_state(self, session):
            await self.storage.save(session.id, {"key": "value"})

        async def load_state(self, session, state):
            data = await self.storage.load(session.id)
            # ... restore state
"""

import json
import aiofiles
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol


class DomainStorage(Protocol):
    """Protocol for domain storage backends.

    Domains can implement this protocol to use custom storage
    (SQLite, LMDB, Redis, etc.).
    """

    async def save(self, key: str, data: dict[str, Any]) -> None:
        """Save data for a key (usually session ID).

        Args:
            key: Unique identifier (e.g., session ID)
            data: JSON-serializable dictionary
        """
        ...

    async def load(self, key: str) -> dict[str, Any] | None:
        """Load data for a key.

        Args:
            key: Unique identifier

        Returns:
            Stored data, or None if not found
        """
        ...

    async def delete(self, key: str) -> None:
        """Delete data for a key.

        Args:
            key: Unique identifier
        """
        ...

    async def list_keys(self) -> list[str]:
        """List all stored keys.

        Returns:
            List of key strings
        """
        ...

    async def clear(self) -> None:
        """Delete all stored data."""
        ...


class JsonFileStorage:
    """JSON file-based storage for domains.

    Stores each key as a separate JSON file in:
        ~/.balloons/plugins/{domain_id}/{key}.json

    Thread-safe for single-process use. For multi-process scenarios,
    consider using LMDB or SQLite.
    """

    def __init__(self, domain_id: str, base_dir: Path | None = None):
        """Initialize JSON file storage.

        Args:
            domain_id: Domain identifier (used as subdirectory name)
            base_dir: Base directory for storage. Defaults to ~/.balloons/plugins/
        """
        self.domain_id = domain_id
        if base_dir is None:
            base_dir = Path.home() / ".balloons" / "plugins"
        self.storage_dir = base_dir / domain_id
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Create storage directory if it doesn't exist."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _key_path(self, key: str) -> Path:
        """Get the file path for a key."""
        # Sanitize key to be filesystem-safe
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
        return self.storage_dir / f"{safe_key}.json"

    async def save(self, key: str, data: dict[str, Any]) -> None:
        """Save data to a JSON file."""
        path = self._key_path(key)
        content = json.dumps(data, indent=2, default=str)
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(content)

    async def load(self, key: str) -> dict[str, Any] | None:
        """Load data from a JSON file."""
        path = self._key_path(key)
        if not path.exists():
            return None
        try:
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                content = await f.read()
            return json.loads(content)
        except (json.JSONDecodeError, IOError):
            return None

    async def delete(self, key: str) -> None:
        """Delete a JSON file."""
        path = self._key_path(key)
        if path.exists():
            path.unlink()

    async def list_keys(self) -> list[str]:
        """List all stored keys."""
        keys = []
        for path in self.storage_dir.glob("*.json"):
            keys.append(path.stem)
        return keys

    async def clear(self) -> None:
        """Delete all JSON files in the storage directory."""
        for path in self.storage_dir.glob("*.json"):
            path.unlink()


class InMemoryStorage:
    """In-memory storage for testing and temporary data.

    Data is lost when the process exits.
    """

    def __init__(self):
        self._data: dict[str, dict[str, Any]] = {}

    async def save(self, key: str, data: dict[str, Any]) -> None:
        self._data[key] = data.copy()

    async def load(self, key: str) -> dict[str, Any] | None:
        data = self._data.get(key)
        return data.copy() if data else None

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def list_keys(self) -> list[str]:
        return list(self._data.keys())

    async def clear(self) -> None:
        self._data.clear()


class CompositeStorage:
    """Storage that delegates to multiple backends.

    Useful for caching: fast in-memory storage backed by persistent storage.
    Reads check memory first, writes go to both.
    """

    def __init__(self, primary: DomainStorage, secondary: DomainStorage):
        """Initialize composite storage.

        Args:
            primary: Fast storage checked first (e.g., InMemoryStorage)
            secondary: Persistent storage (e.g., JsonFileStorage)
        """
        self.primary = primary
        self.secondary = secondary

    async def save(self, key: str, data: dict[str, Any]) -> None:
        await self.primary.save(key, data)
        await self.secondary.save(key, data)

    async def load(self, key: str) -> dict[str, Any] | None:
        # Try primary first
        data = await self.primary.load(key)
        if data is not None:
            return data

        # Fall back to secondary
        data = await self.secondary.load(key)
        if data is not None:
            # Populate primary cache
            await self.primary.save(key, data)
        return data

    async def delete(self, key: str) -> None:
        await self.primary.delete(key)
        await self.secondary.delete(key)

    async def list_keys(self) -> list[str]:
        # Secondary is authoritative
        return await self.secondary.list_keys()

    async def clear(self) -> None:
        await self.primary.clear()
        await self.secondary.clear()
