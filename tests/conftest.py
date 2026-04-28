"""Shared test fixtures for balloons tests."""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: live or slow integration test")
from unittest.mock import patch


@pytest.fixture
def temp_storage(tmp_path):
    """Create a temporary storage for tests.

    Use this fixture when tests need isolated session storage.
    """
    import session as session_module
    from core.async_storage import AsyncStorage

    db_path = tmp_path / "test_sessions.db"

    # Create a new storage instance pointing to temp db
    temp_storage = AsyncStorage(db_path)

    # Replace the global storage singleton
    old_storage = session_module._rust_storage
    session_module._rust_storage = temp_storage

    yield tmp_path

    # Restore original storage
    session_module._rust_storage = old_storage


# Alias for backward compatibility with existing tests
@pytest.fixture
def temp_json_sessions_dir(temp_storage):
    """Alias for temp_storage (backward compatibility)."""
    yield temp_storage
