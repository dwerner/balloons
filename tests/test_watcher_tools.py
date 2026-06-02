import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.watcher_tools import execute_watcher_tool


class TestWatcherToolsUseAttachedService:
    @pytest.mark.asyncio
    async def test_start_watching_session_uses_attached_live_service(self):
        manager = MagicMock()
        service = MagicMock()
        manager.get_service.return_value = service

        result_obj = MagicMock()
        result_obj.success = True
        result_obj.watcher_session_id = "watcher-123"
        result_obj.target_session_id = "target-456"
        result_obj.target_session_name = "Target"
        result_obj.watcher_name = "Watcher"
        service.start_watching_session = AsyncMock(return_value=result_obj)

        current_session = MagicMock()
        current_session.id = "current-123"
        current_session._manager = manager
        current_session.session_manager = manager

        result, is_error = await execute_watcher_tool(
            "start_watching_session",
            {"session_id": "watcher-123", "target_session_id": "target-456"},
            current_session,
        )

        assert is_error is False
        payload = json.loads(result)
        assert payload["status"] == "watching"
        manager.get_service.assert_called_once_with()
        service.start_watching_session.assert_awaited_once_with(
            session_id="watcher-123",
            target_session_id="target-456",
        )

    @pytest.mark.asyncio
    async def test_stop_watching_session_uses_attached_live_service(self):
        manager = MagicMock()
        service = MagicMock()
        manager.get_service.return_value = service
        service.stop_watching_session = AsyncMock(return_value=True)

        current_session = MagicMock()
        current_session.id = "current-123"
        current_session._manager = manager
        current_session.session_manager = manager

        result, is_error = await execute_watcher_tool(
            "stop_watching_session",
            {"session_id": "watcher-123", "target_session_id": "target-456", "reason": "user"},
            current_session,
        )

        assert is_error is False
        payload = json.loads(result)
        assert payload["status"] == "stopped"
        manager.get_service.assert_called_once_with()
        service.stop_watching_session.assert_awaited_once_with(
            session_id="watcher-123",
            target_session_id="target-456",
            reason="user",
        )

    @pytest.mark.asyncio
    async def test_watcher_tools_do_not_construct_fresh_service(self):
        manager = MagicMock()
        service = MagicMock()
        manager.get_service.return_value = service

        result_obj = MagicMock()
        result_obj.success = True
        result_obj.watcher_session_id = "watcher-123"
        result_obj.target_session_id = "target-456"
        result_obj.target_session_name = "Target"
        result_obj.watcher_name = "Watcher"
        service.start_watching_session = AsyncMock(return_value=result_obj)

        current_session = MagicMock()
        current_session.id = "current-123"
        current_session._manager = manager
        current_session.session_manager = manager

        with patch("service.session_manager_service.SessionManagerService", side_effect=AssertionError("fresh service should not be constructed")):
            result, is_error = await execute_watcher_tool(
                "start_watching_session",
                {"session_id": "watcher-123", "target_session_id": "target-456"},
                current_session,
            )

        assert is_error is False
        payload = json.loads(result)
        assert payload["status"] == "watching"

    @pytest.mark.asyncio
    async def test_start_watching_session_returns_error_without_attached_service(self):
        manager = MagicMock()
        manager.get_service.return_value = None

        current_session = MagicMock()
        current_session.id = "current-123"
        current_session._manager = manager
        current_session.session_manager = manager

        result, is_error = await execute_watcher_tool(
            "start_watching_session",
            {"session_id": "watcher-123", "target_session_id": "target-456"},
            current_session,
        )

        assert is_error is True
        assert "attached session manager service" in result

    @pytest.mark.asyncio
    async def test_stop_watching_session_returns_error_without_attached_service(self):
        manager = MagicMock()
        manager.get_service.return_value = None

        current_session = MagicMock()
        current_session.id = "current-123"
        current_session._manager = manager
        current_session.session_manager = manager

        result, is_error = await execute_watcher_tool(
            "stop_watching_session",
            {"session_id": "watcher-123"},
            current_session,
        )

        assert is_error is True
        assert "attached session manager service" in result
