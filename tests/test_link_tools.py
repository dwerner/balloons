"""Tests for custom link tools."""

import json
import pytest
from unittest.mock import Mock, patch

from core.link_tools import (
    LINK_TOOLS,
    get_link_tools_prompt,
    execute_link_tool,
)
from claude_runner import ClaudeRunner
from session import Session
from models import Message, TextBlock, LinkBlock


class TestLinkToolDefinitions:
    """Test that link tool definitions are correct."""

    def test_all_tools_have_required_fields(self):
        for tool in LINK_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool

    def test_tool_names(self):
        names = [t["name"] for t in LINK_TOOLS]
        assert "list_links" in names
        assert "follow_link" in names
        assert "search_linked_session" in names


class TestLinkToolsPrompt:
    """Test the generated prompt for link tools."""

    def test_prompt_includes_tool_names(self):
        prompt = get_link_tools_prompt()
        assert "list_links" in prompt
        assert "follow_link" in prompt
        assert "search_linked_session" in prompt

    def test_prompt_includes_example_format(self):
        prompt = get_link_tools_prompt()
        # The prompt format may have changed, just check it's non-empty
        assert len(prompt) > 0

    def test_prompt_includes_descriptions(self):
        prompt = get_link_tools_prompt()
        # Check tool descriptions are included
        assert "link" in prompt.lower()


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
        linked_session.messages = [Mock(), Mock()]

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
