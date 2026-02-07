"""Tests for custom link tools."""

import json
import pytest
from unittest.mock import Mock, patch

from core.link_tools import (
    LINK_TOOL_NAMES,
    execute_link_tool,
    register_app_tool_handler,
    unregister_app_tool_handler,
)
from claude_runner import ClaudeRunner
from session import Session
from models import Message, TextBlock, LinkBlock


class TestLinkToolNames:
    """Test that link tool names are defined correctly."""

    def test_tool_names(self):
        assert "list_links" in LINK_TOOL_NAMES
        assert "follow_link" in LINK_TOOL_NAMES
        assert "search_linked_session" in LINK_TOOL_NAMES
        assert "session_info" in LINK_TOOL_NAMES
        assert "screen_snapshot" in LINK_TOOL_NAMES


class TestScreenSnapshotTool:
    """Test screen_snapshot tool with app handler registration."""

    def test_screen_snapshot_without_handler_returns_error(self):
        """Without a registered handler, screen_snapshot returns an error."""
        session = Mock(spec=Session)
        result, is_error = execute_link_tool("screen_snapshot", {}, session)

        assert is_error
        assert "requires the Balloons app" in result

    def test_screen_snapshot_with_handler(self):
        """With a registered handler, screen_snapshot calls it."""
        session = Mock(spec=Session)

        # Register a mock handler
        def mock_handler():
            return "# Screen Snapshot\n```\nMocked screen content\n```", False

        register_app_tool_handler("screen_snapshot", mock_handler)
        try:
            result, is_error = execute_link_tool("screen_snapshot", {}, session)

            assert not is_error
            assert "Mocked screen content" in result
        finally:
            # Clean up
            unregister_app_tool_handler("screen_snapshot")

    def test_unregister_handler(self):
        """After unregistering, handler is no longer called."""
        session = Mock(spec=Session)

        def mock_handler():
            return "Handler was called", False

        register_app_tool_handler("screen_snapshot", mock_handler)
        unregister_app_tool_handler("screen_snapshot")

        result, is_error = execute_link_tool("screen_snapshot", {}, session)

        assert is_error
        assert "requires the Balloons app" in result


class TestExecuteLinkTool:
    """Test link tool execution."""

    def test_unknown_tool_returns_error(self):
        session = Mock(spec=Session)
        result, is_error = execute_link_tool("unknown_tool", {}, session)

        assert is_error
        assert "Unknown link tool" in result

    def test_list_links_empty_session(self):
        session = Mock(spec=Session)
        session.get_all_active_links.return_value = []

        result, is_error = execute_link_tool("list_links", {}, session)

        assert not is_error
        assert "No links found" in result

    def test_list_links_with_links(self):
        # Create a mock session with links
        session = Mock(spec=Session)
        session.get_all_active_links.return_value = [
            {"link_id": "link1", "linked_session_id": "sess1", "summary": "Test link"}
        ]

        # Mock the linked session lookup
        linked_session = Mock(spec=Session)
        linked_session.title = "Linked Session"
        linked_session.fork_name = None
        linked_session.turns = [Mock(), Mock()]

        with patch.object(Session, 'load', return_value=linked_session):
            result, is_error = execute_link_tool("list_links", {}, session)

        assert not is_error
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["link_id"] == "link1"
        assert data[0]["linked_session_name"] == "Linked Session"
        assert data[0]["message_count"] == 2

    def test_follow_link_missing_link_id(self):
        session = Mock(spec=Session)
        result, is_error = execute_link_tool("follow_link", {}, session)

        assert is_error
        assert "link_id is required" in result

    def test_follow_link_not_found(self):
        session = Mock(spec=Session)
        session.get_all_active_links.return_value = []

        result, is_error = execute_link_tool(
            "follow_link",
            {"link_id": "nonexistent"},
            session
        )

        assert is_error
        assert "Link not found" in result

    def test_search_linked_session_missing_args(self):
        session = Mock(spec=Session)

        # Missing link_id
        result, is_error = execute_link_tool(
            "search_linked_session",
            {"query": "test"},
            session
        )
        assert is_error
        assert "link_id is required" in result

        # Missing query
        result, is_error = execute_link_tool(
            "search_linked_session",
            {"link_id": "abc"},
            session
        )
        assert is_error
        assert "query is required" in result

    def test_session_info_basic(self):
        """Test session_info returns expected minimal structure."""
        session = Mock(spec=Session)
        session.id = "test-session-12345678"
        session.title = "Test Session"
        session.fork_name = ""
        session.cached_context_tokens = 40000  # 20% usage
        session.context_window = 200000
        session.is_merged.return_value = False
        session.parent_id = None

        result, is_error = execute_link_tool("session_info", {}, session)

        assert not is_error
        data = json.loads(result)

        # Check minimal structure (refactored to be concise for LLM)
        assert data["name"] == "Test Session"
        assert data["parents"] == []  # Root session has no parents
        assert data["merged"] is False
        assert data["context_tokens"] == 40000
        assert data["context_pct"] == 20.0

    def test_session_info_with_parent(self):
        """Test session_info shows parent chain for forked sessions."""
        session = Mock(spec=Session)
        session.id = "test-session-12345678"
        session.title = ""
        session.fork_name = "my-fork"
        session.cached_context_tokens = 160000
        session.context_window = 200000
        session.is_merged.return_value = False
        session.parent_id = "parent-1234"

        # Mock parent session
        parent_session = Mock(spec=Session)
        parent_session.id = "parent-1234"
        parent_session.title = "Parent Session"
        parent_session.fork_name = ""
        parent_session.parent_id = None  # Root parent

        with patch.object(Session, 'load', return_value=parent_session):
            result, is_error = execute_link_tool("session_info", {}, session)

        assert not is_error
        data = json.loads(result)

        # Name should come from fork_name when title is empty
        assert data["name"] == "my-fork"
        assert data["context_pct"] == 80.0
        # Should have one parent in the chain
        assert len(data["parents"]) == 1
        assert "Parent Session" in data["parents"][0]


class TestClaudeRunnerSession:
    """Test ClaudeRunner session management."""

    def test_set_session(self):
        runner = ClaudeRunner()
        session = Mock(spec=Session)

        runner.set_session(session)

        assert runner._current_session is session

    def test_session_initially_none(self):
        runner = ClaudeRunner()
        assert runner._current_session is None


class TestBalloonsToolParsing:
    """Test parsing of <balloons-tool> blocks from Claude's text output."""

    def test_parse_balloons_tool_simple(self):
        runner = ClaudeRunner()
        text = '''Let me check the links.

<balloons-tool>
{"name": "list_links", "args": {}}
</balloons-tool>'''

        tool_name, tool_id, tool_args = runner._parse_balloons_tool(text)

        assert tool_name == "list_links"
        assert tool_id is not None
        assert tool_id.startswith("balloons-")
        assert tool_args == {}

    def test_parse_balloons_tool_with_args(self):
        runner = ClaudeRunner()
        text = '''<balloons-tool>
{"name": "follow_link", "args": {"link_id": "abc123", "include_messages": 5}}
</balloons-tool>'''

        tool_name, tool_id, tool_args = runner._parse_balloons_tool(text)

        assert tool_name == "follow_link"
        assert tool_args == {"link_id": "abc123", "include_messages": 5}

    def test_parse_balloons_tool_no_match(self):
        runner = ClaudeRunner()
        text = "Just some regular text without any tool calls."

        tool_name, tool_id, tool_args = runner._parse_balloons_tool(text)

        assert tool_name is None
        assert tool_id is None
        assert tool_args is None

    def test_parse_balloons_tool_incomplete(self):
        runner = ClaudeRunner()
        text = "<balloons-tool>{"  # Incomplete - no closing tag

        tool_name, tool_id, tool_args = runner._parse_balloons_tool(text)

        assert tool_name is None

    def test_parse_balloons_tool_invalid_json(self):
        runner = ClaudeRunner()
        text = '''<balloons-tool>
{invalid json}
</balloons-tool>'''

        tool_name, tool_id, tool_args = runner._parse_balloons_tool(text)

        assert tool_name is None

    def test_parse_balloons_tool_embedded_in_text(self):
        runner = ClaudeRunner()
        text = '''I'll look up the linked sessions for more context.

<balloons-tool>
{"name": "list_links", "args": {}}
</balloons-tool>

Based on the results, I can see...'''

        tool_name, tool_id, tool_args = runner._parse_balloons_tool(text)

        assert tool_name == "list_links"
        assert tool_args == {}
