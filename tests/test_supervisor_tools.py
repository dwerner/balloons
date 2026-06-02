"""Tests for supervisor tools."""

import pytest
from core.supervisor_tools import (
    SUPERVISOR_TOOL_NAMES,
    get_running_count,
    set_supervisor,
    get_supervisor,
)
from core.commands import (
    CommandParser,
    SupervisorStartCommand,
    SupervisorListCommand,
    SupervisorLogsCommand,
    SupervisorStopCommand,
)
from core.tools import SUPERVISOR_TOOLS, get_tools_for_request


class TestSupervisorToolNames:
    """Test supervisor tool name constants."""

    def test_tool_names_defined(self):
        """Ensure all expected tool names are defined."""
        expected = {
            "supervisor_start",
            "supervisor_list",
            "supervisor_query",
            "supervisor_host_status",
            "supervisor_output",
            "supervisor_stop",
            "supervisor_input",
        }
        assert SUPERVISOR_TOOL_NAMES == expected

    def test_tool_definitions_match_names(self):
        """Ensure tool definitions match the name set."""
        defined_names = {t["function"]["name"] for t in SUPERVISOR_TOOLS}
        assert defined_names == SUPERVISOR_TOOL_NAMES


class TestSupervisorState:
    """Test supervisor state management."""

    def test_no_supervisor_initially(self):
        """Supervisor should be None before set."""
        # This assumes we're testing in isolation
        assert get_running_count() == 0  # Gracefully handles None supervisor


class TestCommandParsing:
    """Test supervisor command parsing."""

    @pytest.fixture
    def parser(self):
        return CommandParser()

    def test_sup_start_basic(self, parser):
        """Parse :sup-start <cmd>."""
        cmd = parser.parse(":sup-start npm run dev")
        assert isinstance(cmd, SupervisorStartCommand)
        assert cmd.command == "npm run dev"
        assert cmd.name == ""

    def test_sup_start_with_name(self, parser):
        """Parse :sup-start=name <cmd>."""
        cmd = parser.parse(":sup-start=dev-server npm run dev")
        assert isinstance(cmd, SupervisorStartCommand)
        assert cmd.command == "npm run dev"
        assert cmd.name == "dev-server"

    def test_sup_start_requires_command(self, parser):
        """Ensure :sup-start fails without command."""
        with pytest.raises(ValueError, match="requires a command"):
            parser.parse(":sup-start")

    def test_sup_start_name_only_fails(self, parser):
        """Ensure :sup-start=name alone fails."""
        with pytest.raises(ValueError, match="requires a command"):
            parser.parse(":sup-start=server")

    def test_sup_list_basic(self, parser):
        """Parse :sup-list."""
        cmd = parser.parse(":sup-list")
        assert isinstance(cmd, SupervisorListCommand)
        assert cmd.all_sessions is False

    def test_sup_list_all(self, parser):
        """Parse :sup-list --all."""
        cmd = parser.parse(":sup-list --all")
        assert isinstance(cmd, SupervisorListCommand)
        assert cmd.all_sessions is True

    def test_sup_logs_basic(self, parser):
        """Parse :sup-logs <id>."""
        cmd = parser.parse(":sup-logs abc123")
        assert isinstance(cmd, SupervisorLogsCommand)
        assert cmd.process_id == "abc123"
        assert cmd.limit == 50  # default

    def test_sup_logs_with_limit(self, parser):
        """Parse :sup-logs <id> <limit>."""
        cmd = parser.parse(":sup-logs abc123 100")
        assert isinstance(cmd, SupervisorLogsCommand)
        assert cmd.process_id == "abc123"
        assert cmd.limit == 100

    def test_sup_logs_requires_id(self, parser):
        """Ensure :sup-logs fails without process ID."""
        with pytest.raises(ValueError, match="requires a process ID"):
            parser.parse(":sup-logs")

    def test_sup_logs_invalid_limit(self, parser):
        """Ensure :sup-logs fails with non-numeric limit."""
        with pytest.raises(ValueError, match="Invalid limit"):
            parser.parse(":sup-logs abc123 notanumber")

    def test_sup_stop_basic(self, parser):
        """Parse :sup-stop <id>."""
        cmd = parser.parse(":sup-stop abc123")
        assert isinstance(cmd, SupervisorStopCommand)
        assert cmd.process_id == "abc123"

    def test_sup_stop_requires_id(self, parser):
        """Ensure :sup-stop fails without process ID."""
        with pytest.raises(ValueError, match="requires a process ID"):
            parser.parse(":sup-stop")


class TestToolsIntegration:
    """Test tools integration."""

    def test_supervisor_tools_included_by_default(self):
        """Supervisor tools should be included by default."""
        tools = get_tools_for_request()
        tool_names = {t["function"]["name"] for t in tools}
        assert "supervisor_start" in tool_names
        assert "supervisor_list" in tool_names
        assert "supervisor_output" in tool_names
        assert "supervisor_stop" in tool_names

    def test_supervisor_tools_can_be_excluded(self):
        """Supervisor tools can be excluded."""
        tools = get_tools_for_request(include_supervisor_tools=False)
        tool_names = {t["function"]["name"] for t in tools}
        assert "supervisor_start" not in tool_names
        assert "supervisor_list" not in tool_names

    def test_supervisor_tools_schema_valid(self):
        """Supervisor tool schemas should be valid."""
        for tool in SUPERVISOR_TOOLS:
            assert "type" in tool
            assert tool["type"] == "function"
            assert "function" in tool
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            params = func["parameters"]
            assert params.get("type") == "object"
            assert "properties" in params
