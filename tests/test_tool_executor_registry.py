"""Registry-dispatch tests for built-in tool families in tool_executor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.tool_executor import execute_tool
from core.tool_result import ToolExecutionResult


class TestRegisteredBuiltinFamilies:
    @pytest.mark.asyncio
    async def test_dispatches_link_tool_via_registry(self, tmp_path):
        session = MagicMock()
        with patch("core.tool_executor.execute_link_tool", new=AsyncMock(return_value=("ok-link", False))) as mock_exec:
            result, is_error = await execute_tool("list_links", {}, str(tmp_path), session=session)
        assert (result, is_error) == ("ok-link", False)
        mock_exec.assert_awaited_once_with("list_links", {}, session)

    @pytest.mark.asyncio
    async def test_dispatches_supervisor_tool_via_registry(self, tmp_path):
        session = MagicMock()
        with patch("core.tool_executor.execute_supervisor_tool", new=AsyncMock(return_value=("ok-supervisor", False))) as mock_exec:
            result, is_error = await execute_tool("supervisor_list", {}, str(tmp_path), session=session)
        assert (result, is_error) == ("ok-supervisor", False)
        mock_exec.assert_awaited_once_with("supervisor_list", {}, session, str(tmp_path))

    @pytest.mark.asyncio
    async def test_dispatches_review_tool_via_registry(self, tmp_path):
        session = MagicMock()
        with patch("core.tool_executor.execute_review_tool", new=AsyncMock(return_value=("ok-review", False))) as mock_exec:
            result, is_error = await execute_tool("save_review", {"session_id": "abc"}, str(tmp_path), session=session)
        assert (result, is_error) == ("ok-review", False)
        mock_exec.assert_awaited_once_with("save_review", {"session_id": "abc"}, session)

    @pytest.mark.asyncio
    async def test_dispatches_debug_tool_via_registry(self, tmp_path):
        session = MagicMock()
        with patch("core.tool_executor.execute_debug_tool", new=AsyncMock(return_value=("ok-debug", False))) as mock_exec:
            result, is_error = await execute_tool("debug_log_query", {"category": "runner"}, str(tmp_path), session=session)
        assert (result, is_error) == ("ok-debug", False)
        mock_exec.assert_awaited_once_with("debug_log_query", {"category": "runner"}, session)

    @pytest.mark.asyncio
    async def test_dispatches_watcher_tool_via_registry(self, tmp_path):
        session = MagicMock()
        with patch("core.tool_executor.execute_watcher_tool", new=AsyncMock(return_value=("ok-watch", False))) as mock_exec:
            result, is_error = await execute_tool("send_to_target", {"message": "hi"}, str(tmp_path), session=session)
        assert (result, is_error) == ("ok-watch", False)
        mock_exec.assert_awaited_once_with("send_to_target", {"message": "hi"}, session)

    @pytest.mark.asyncio
    async def test_dispatches_lsp_tool_via_registry(self, tmp_path):
        session = MagicMock()
        with patch("core.tool_executor.execute_lsp_tool", new=AsyncMock(return_value=("ok-lsp", False))) as mock_exec:
            result, is_error = await execute_tool("lsp_status", {}, str(tmp_path), session=session)
        assert (result, is_error) == ("ok-lsp", False)
        mock_exec.assert_awaited_once_with("lsp_status", {}, session, str(tmp_path))

    @pytest.mark.asyncio
    async def test_dispatches_domain_management_tool_via_registry(self, tmp_path):
        session = MagicMock()
        tool_result = ToolExecutionResult("ok-domain", is_error=False, domains_changed=True)
        with patch("core.tool_executor.execute_domain_management_tool", new=AsyncMock(return_value=tool_result)) as mock_exec:
            result = await execute_tool("list_domains", {}, str(tmp_path), session=session)
        assert result is tool_result
        mock_exec.assert_awaited_once_with("list_domains", {}, session)

    @pytest.mark.asyncio
    async def test_dispatches_browser_tool_via_registry(self, tmp_path):
        session = MagicMock()
        with patch("core.tool_executor.execute_browser_tool", new=AsyncMock(return_value=("ok-browser", False))) as mock_exec:
            result, is_error = await execute_tool("browser_list", {}, str(tmp_path), session=session)
        assert (result, is_error) == ("ok-browser", False)
        mock_exec.assert_awaited_once_with("browser_list", {}, session, str(tmp_path))

    @pytest.mark.asyncio
    async def test_session_required_tools_fail_without_session(self, tmp_path):
        result, is_error = await execute_tool("list_links", {}, str(tmp_path), session=None)
        assert is_error is True
        assert "session context" in result.lower()

        result, is_error = await execute_tool("browser_list", {}, str(tmp_path), session=None)
        assert is_error is True
        assert "session context" in result.lower()
