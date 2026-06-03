from unittest.mock import AsyncMock, MagicMock

import pytest

from service.session_manager_service import SessionManagerService


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.id = "test-session-123"
    session.title = "Test Session"
    session.created = "2024-01-01T00:00:00"
    session.last_modified = "2024-01-01T00:00:00"
    session.model = "test-model"
    session.turns = []
    session.parent_id = None
    session.returned = False
    session.fork_name = ""
    session.fork_status = ""
    session.concluded = False
    session.concluded_at = None
    session.cached_context_tokens = 0
    session.context_window = 150000
    session.binding_indicator = ""
    session.backend_name = "openai"
    session.working_directory = "/tmp"
    session.loaded_domains = []
    session.enabled_tools = []
    session.ensure_context_tokens = MagicMock(return_value=0)
    session.get_enabled_tools_list = lambda: list(session.enabled_tools)
    session.get_enabled_tools_set = lambda: set(session.enabled_tools)
    session.save = AsyncMock()
    return session


@pytest.fixture
def mock_manager(mock_session):
    manager = MagicMock()
    manager._sessions = {mock_session.id: mock_session}
    manager._runners = {}
    manager._active_session_id = mock_session.id
    manager.get_session = MagicMock(side_effect=lambda sid: mock_session if sid == mock_session.id else None)
    manager.load_session = AsyncMock(side_effect=lambda sid: mock_session if sid == mock_session.id else None)
    manager.save_session = AsyncMock()
    return manager


@pytest.mark.asyncio
async def test_load_domain_auto_enables_session_tools_and_schema_preview_reads_session_state(mock_manager, mock_session):
    service = SessionManagerService(mock_manager)

    try:
        result = await service.load_domain("kanban", mock_session.id)
        assert result["success"] is True

        enabled_tools = await service.get_session_enabled_tools(mock_session.id)
        assert any(tool.startswith("kanban_") for tool in enabled_tools)

        preview = await service.get_tool_schemas_preview(mock_session.id)
        assert "kanban_" in preview["schemas"]
        assert preview["tool_count"] > 0
        mock_manager.save_session.assert_awaited()
    finally:
        await service.unload_domain("kanban", mock_session.id)


@pytest.mark.asyncio
async def test_unload_domain_removes_session_tools_and_schema_preview_updates(mock_manager, mock_session):
    service = SessionManagerService(mock_manager)

    load_result = await service.load_domain("kanban", mock_session.id)
    assert load_result["success"] is True

    try:
        enabled_before = await service.get_session_enabled_tools(mock_session.id)
        kanban_tools = [tool for tool in enabled_before if tool.startswith("kanban_")]
        assert kanban_tools

        unload_result = await service.unload_domain("kanban", mock_session.id)
        assert unload_result["success"] is True

        enabled_after = await service.get_session_enabled_tools(mock_session.id)
        assert not any(tool.startswith("kanban_") for tool in enabled_after)

        preview = await service.get_tool_schemas_preview(mock_session.id)
        assert "kanban_" not in preview["schemas"]
    finally:
        await service.unload_domain("kanban", mock_session.id)
