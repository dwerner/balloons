"""Tests for plugin storage backends."""

import pytest
import tempfile
from pathlib import Path

from .storage import JsonFileStorage, InMemoryStorage, CompositeStorage


class TestInMemoryStorage:
    @pytest.mark.asyncio
    async def test_save_and_load(self):
        storage = InMemoryStorage()
        await storage.save("key1", {"name": "test", "value": 42})

        data = await storage.load("key1")
        assert data == {"name": "test", "value": 42}

    @pytest.mark.asyncio
    async def test_load_missing(self):
        storage = InMemoryStorage()
        data = await storage.load("nonexistent")
        assert data is None

    @pytest.mark.asyncio
    async def test_delete(self):
        storage = InMemoryStorage()
        await storage.save("key1", {"test": True})
        await storage.delete("key1")

        data = await storage.load("key1")
        assert data is None

    @pytest.mark.asyncio
    async def test_list_keys(self):
        storage = InMemoryStorage()
        await storage.save("key1", {})
        await storage.save("key2", {})
        await storage.save("key3", {})

        keys = await storage.list_keys()
        assert set(keys) == {"key1", "key2", "key3"}

    @pytest.mark.asyncio
    async def test_clear(self):
        storage = InMemoryStorage()
        await storage.save("key1", {})
        await storage.save("key2", {})
        await storage.clear()

        keys = await storage.list_keys()
        assert keys == []


class TestJsonFileStorage:
    @pytest.mark.asyncio
    async def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = JsonFileStorage("test-domain", Path(tmpdir))
            await storage.save("session-123", {"fen": "rnbqkbnr/...", "moves": ["e2e4"]})

            data = await storage.load("session-123")
            assert data == {"fen": "rnbqkbnr/...", "moves": ["e2e4"]}

    @pytest.mark.asyncio
    async def test_load_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = JsonFileStorage("test-domain", Path(tmpdir))
            data = await storage.load("nonexistent")
            assert data is None

    @pytest.mark.asyncio
    async def test_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = JsonFileStorage("test-domain", Path(tmpdir))
            await storage.save("key1", {"test": True})
            await storage.delete("key1")

            data = await storage.load("key1")
            assert data is None

    @pytest.mark.asyncio
    async def test_list_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = JsonFileStorage("test-domain", Path(tmpdir))
            await storage.save("key1", {})
            await storage.save("key2", {})

            keys = await storage.list_keys()
            assert set(keys) == {"key1", "key2"}

    @pytest.mark.asyncio
    async def test_sanitizes_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = JsonFileStorage("test-domain", Path(tmpdir))
            # Key with special characters should be sanitized
            await storage.save("session/with:special?chars", {"test": True})

            # File should exist with sanitized name
            files = list(storage.storage_dir.glob("*.json"))
            assert len(files) == 1
            assert "/" not in files[0].name


class TestCompositeStorage:
    @pytest.mark.asyncio
    async def test_reads_from_primary_first(self):
        primary = InMemoryStorage()
        secondary = InMemoryStorage()
        composite = CompositeStorage(primary, secondary)

        # Data in primary only
        await primary.save("key1", {"source": "primary"})

        data = await composite.load("key1")
        assert data == {"source": "primary"}

    @pytest.mark.asyncio
    async def test_falls_back_to_secondary(self):
        primary = InMemoryStorage()
        secondary = InMemoryStorage()
        composite = CompositeStorage(primary, secondary)

        # Data in secondary only
        await secondary.save("key1", {"source": "secondary"})

        data = await composite.load("key1")
        assert data == {"source": "secondary"}

    @pytest.mark.asyncio
    async def test_populates_primary_cache(self):
        primary = InMemoryStorage()
        secondary = InMemoryStorage()
        composite = CompositeStorage(primary, secondary)

        # Data in secondary
        await secondary.save("key1", {"value": 42})

        # Load via composite
        await composite.load("key1")

        # Primary should now have the data
        data = await primary.load("key1")
        assert data == {"value": 42}

    @pytest.mark.asyncio
    async def test_writes_to_both(self):
        primary = InMemoryStorage()
        secondary = InMemoryStorage()
        composite = CompositeStorage(primary, secondary)

        await composite.save("key1", {"test": True})

        # Both should have the data
        assert await primary.load("key1") == {"test": True}
        assert await secondary.load("key1") == {"test": True}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
