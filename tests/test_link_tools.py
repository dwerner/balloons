"""Tests for custom link tools."""

import json
import pytest
from unittest.mock import AsyncMock, Mock, patch

from core.link_tools import (
    LINK_TOOL_NAMES,
    execute_link_tool,
    register_app_tool_handler,
    unregister_app_tool_handler,
)
from claude_runner import ClaudeRunner
from session import Session
from models import Message, TextBlock, LinkBlock, ForkBlock, MergeBlock, MergedToBlock, Turn
from storage_schema import SessionBinding


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

    @pytest.mark.asyncio
    async def test_screen_snapshot_without_handler_returns_error(self):
        """Without a registered handler, screen_snapshot returns an error."""
        session = Mock(spec=Session)
        result, is_error = await execute_link_tool("screen_snapshot", {}, session)

        assert is_error
        assert "requires the Balloons app" in result

    @pytest.mark.asyncio
    async def test_screen_snapshot_with_handler(self):
        """With a registered handler, screen_snapshot calls it."""
        session = Mock(spec=Session)

        # Register a mock handler
        def mock_handler():
            return "# Screen Snapshot\n```\nMocked screen content\n```", False

        register_app_tool_handler("screen_snapshot", mock_handler)
        try:
            result, is_error = await execute_link_tool("screen_snapshot", {}, session)

            assert not is_error
            assert "Mocked screen content" in result
        finally:
            # Clean up
            unregister_app_tool_handler("screen_snapshot")

    @pytest.mark.asyncio
    async def test_unregister_handler(self):
        """After unregistering, handler is no longer called."""
        session = Mock(spec=Session)

        def mock_handler():
            return "Handler was called", False

        register_app_tool_handler("screen_snapshot", mock_handler)
        unregister_app_tool_handler("screen_snapshot")

        result, is_error = await execute_link_tool("screen_snapshot", {}, session)

        assert is_error
        assert "requires the Balloons app" in result


class TestExecuteLinkTool:
    """Test link tool execution."""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        session = Mock(spec=Session)
        result, is_error = await execute_link_tool("unknown_tool", {}, session)

        assert is_error
        assert "Unknown link tool" in result

    @pytest.mark.asyncio
    async def test_list_links_empty_session(self):
        session = Mock(spec=Session)
        session.get_all_active_links.return_value = []

        result, is_error = await execute_link_tool("list_links", {}, session)

        assert not is_error
        assert "No links found" in result

    @pytest.mark.asyncio
    async def test_list_links_with_links(self):
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
            result, is_error = await execute_link_tool("list_links", {}, session)

        assert not is_error
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["link_id"] == "link1"
        assert data[0]["linked_session_name"] == "Linked Session"
        assert data[0]["message_count"] == 2

    @pytest.mark.asyncio
    async def test_follow_link_missing_link_id(self):
        session = Mock(spec=Session)
        result, is_error = await execute_link_tool("follow_link", {}, session)

        assert is_error
        assert "link_id or session_id is required" in result

    @pytest.mark.asyncio
    async def test_follow_link_not_found(self):
        session = Mock(spec=Session)
        session.get_all_active_links.return_value = []

        result, is_error = await execute_link_tool(
            "follow_link",
            {"link_id": "nonexistent"},
            session
        )

        assert is_error
        assert "Link not found" in result

    @pytest.mark.asyncio
    async def test_search_linked_session_missing_args(self):
        session = Mock(spec=Session)

        # Missing link_id
        result, is_error = await execute_link_tool(
            "search_linked_session",
            {"query": "test"},
            session
        )
        assert is_error
        assert "link_id is required" in result

        # Missing query
        result, is_error = await execute_link_tool(
            "search_linked_session",
            {"link_id": "abc"},
            session
        )
        assert is_error
        assert "query is required" in result

    @pytest.mark.asyncio
    async def test_session_info_basic(self):
        """Test session_info returns expected minimal structure."""
        session = Mock(spec=Session)
        session.id = "test-session-12345678"
        session.title = "Test Session"
        session.fork_name = ""
        session.backend_name = "anthropic"
        session.cached_context_tokens = 40000  # 20% usage
        session.context_window = 200000
        session.ensure_context_tokens.return_value = 40000  # Mock the new method
        session.is_merged.return_value = False
        session.parent_id = None
        session.get_all_merge_blocks.return_value = []
        session.get_all_fork_blocks.return_value = []
        session.get_merged_to_block.return_value = None

        result, is_error = await execute_link_tool("session_info", {}, session)

        assert not is_error
        data = json.loads(result)

        # Check structure
        assert data["name"] == "Test Session"
        assert data["session_id"] == "test-session-12345678"
        assert data["backend"] == "anthropic"
        assert data["parents"] == []  # Root session has no parents
        assert data["merged_to"] is None  # Not merged
        assert data["merged_from"] == []  # No child merges
        assert data["forked_to"] == []  # No child forks
        assert data["context_tokens"] == 40000
        assert data["context_pct"] == 20.0

    @pytest.mark.asyncio
    async def test_session_info_with_parent(self):
        """Test session_info shows parent chain for forked sessions."""
        session = Mock(spec=Session)
        session.id = "test-session-12345678"
        session.title = ""
        session.fork_name = "my-fork"
        session.backend_name = "openrouter"
        session.cached_context_tokens = 160000
        session.context_window = 200000
        session.ensure_context_tokens.return_value = 160000
        session.is_merged.return_value = False
        session.parent_id = "parent-1234"
        session.get_all_merge_blocks.return_value = []
        session.get_all_fork_blocks.return_value = []
        session.get_merged_to_block.return_value = None

        # Mock parent session
        parent_session = Mock(spec=Session)
        parent_session.id = "parent-1234"
        parent_session.title = "Parent Session"
        parent_session.fork_name = ""
        parent_session.parent_id = None  # Root parent

        with patch.object(Session, 'load', return_value=parent_session):
            result, is_error = await execute_link_tool("session_info", {}, session)

        assert not is_error
        data = json.loads(result)

        # Name should come from fork_name when title is empty
        assert data["name"] == "my-fork"
        assert data["context_pct"] == 80.0
        # Should have one parent in the chain
        assert len(data["parents"]) == 1
        assert "Parent Session" in data["parents"][0]
        # Not merged, so no merged_to
        assert data["merged_to"] is None

    @pytest.mark.asyncio
    async def test_session_info_with_merge_and_fork_blocks(self):
        """Test session_info shows merged_from and forked_to from turns."""
        session = Mock(spec=Session)
        session.id = "test-session-12345678"
        session.title = "Main Session"
        session.fork_name = ""
        session.backend_name = "anthropic"
        session.cached_context_tokens = 50000
        session.context_window = 200000
        session.ensure_context_tokens.return_value = 50000
        session.is_merged.return_value = False
        session.parent_id = None
        session.get_merged_to_block.return_value = None

        # Mock merge block (child merged into this session at turn 15)
        merge_block = MergeBlock(
            merge_id="merge-123",
            child_session_id="child-abc",
            fork_name="fix-cache",
            message="Added Redis caching with TTL support",
        )
        session.get_all_merge_blocks.return_value = [(15, merge_block)]

        # Mock fork block (this session forked to a child at turn 8)
        fork_block = ForkBlock(
            fork_id="fork-456",
            child_session_id="child-def",
            fork_name="try-memcached",
            status="active",
        )
        session.get_all_fork_blocks.return_value = [(8, fork_block)]

        result, is_error = await execute_link_tool("session_info", {}, session)

        assert not is_error
        data = json.loads(result)

        # Check merged_from
        assert len(data["merged_from"]) == 1
        assert data["merged_from"][0]["turn"] == 15
        assert data["merged_from"][0]["session_id"] == "child-abc"
        assert data["merged_from"][0]["name"] == "fix-cache"
        assert "Redis" in data["merged_from"][0]["summary"]

        # Check forked_to
        assert len(data["forked_to"]) == 1
        assert data["forked_to"][0]["turn"] == 8
        assert data["forked_to"][0]["session_id"] == "child-def"
        assert data["forked_to"][0]["name"] == "try-memcached"
        assert data["forked_to"][0]["status"] == "active"

    @pytest.mark.asyncio
    async def test_session_info_merged_session(self):
        """Test session_info shows merged_to when session is merged to parent."""
        session = Mock(spec=Session)
        session.id = "child-session-123"
        session.title = ""
        session.fork_name = "auth-fix"
        session.backend_name = "anthropic"
        session.cached_context_tokens = 30000
        session.context_window = 200000
        session.ensure_context_tokens.return_value = 30000
        session.is_merged.return_value = True
        session.parent_id = "parent-session-456"
        session.merge_point_turn = 42
        session.merge_message = "Fixed authentication by refreshing tokens"
        session.get_all_merge_blocks.return_value = []
        session.get_all_fork_blocks.return_value = []

        # Mock MergedToBlock (now the primary source for merged_to info)
        merged_to_block = MergedToBlock(
            merge_id="merge-xyz",
            parent_session_id="parent-session-456",
            parent_turn=42,
            message="Fixed authentication by refreshing tokens",
        )
        session.get_merged_to_block.return_value = merged_to_block

        # Mock parent session for parents chain
        parent_session = Mock(spec=Session)
        parent_session.id = "parent-session-456"
        parent_session.title = "Main Project"
        parent_session.fork_name = ""
        parent_session.parent_id = None

        with patch.object(Session, 'load', return_value=parent_session):
            result, is_error = await execute_link_tool("session_info", {}, session)

        assert not is_error
        data = json.loads(result)

        # Check merged_to
        assert data["merged_to"] is not None
        assert data["merged_to"]["merge_id"] == "merge-xyz"
        assert data["merged_to"]["parent_session_id"] == "parent-session-456"
        assert data["merged_to"]["parent_turn"] == 42
        assert "authentication" in data["merged_to"]["summary"]

    @pytest.mark.asyncio
    async def test_session_info_with_binding(self):
        """Test session_info includes binding info when session is bound to an entity."""
        session = Mock(spec=Session)
        session.id = "test-session-12345678"
        session.title = "Implementation Session"
        session.fork_name = ""
        session.backend_name = "anthropic"
        session.cached_context_tokens = 40000
        session.context_window = 200000
        session.ensure_context_tokens.return_value = 40000
        session.is_merged.return_value = False
        session.parent_id = None
        session.get_all_merge_blocks.return_value = []
        session.get_all_fork_blocks.return_value = []
        session.get_merged_to_block.return_value = None

        # Mock binding
        binding = SessionBinding(
            id="binding-123",
            session_id="test-session-12345678",
            entity_type="todo",
            entity_id="todo-456",
            role="implementation",
            created_at="2024-01-01T00:00:00",
            released_at=None,
        )

        with patch('core.link_tools.GoalStorage') as MockStorage:
            mock_instance = MockStorage.return_value
            mock_instance.get_bindings_for_session = AsyncMock(return_value=[binding])
            result, is_error = await execute_link_tool("session_info", {}, session)

        assert not is_error
        data = json.loads(result)

        # Check binding is present
        assert "binding" in data
        assert data["binding"]["entity_type"] == "todo"
        assert data["binding"]["entity_id"] == "todo-456"
        assert data["binding"]["role"] == "implementation"

    @pytest.mark.asyncio
    async def test_session_info_no_binding(self):
        """Test session_info omits binding when session has no binding."""
        session = Mock(spec=Session)
        session.id = "test-session-12345678"
        session.title = "Unbound Session"
        session.fork_name = ""
        session.backend_name = None  # No explicit backend
        session.cached_context_tokens = 40000
        session.context_window = 200000
        session.ensure_context_tokens.return_value = 40000
        session.is_merged.return_value = False
        session.parent_id = None
        session.get_all_merge_blocks.return_value = []
        session.get_all_fork_blocks.return_value = []
        session.get_merged_to_block.return_value = None

        with patch('core.link_tools.GoalStorage') as MockStorage:
            mock_instance = MockStorage.return_value
            mock_instance.get_bindings_for_session = AsyncMock(return_value=[])  # No bindings
            result, is_error = await execute_link_tool("session_info", {}, session)

        assert not is_error
        data = json.loads(result)

        # Check binding is NOT present (omitted, not null)
        assert "binding" not in data

    @pytest.mark.asyncio
    async def test_follow_link_with_session_id(self):
        """Test follow_link can directly load a session by ID."""
        current_session = Mock(spec=Session)

        # Target session to load
        target_session = Mock(spec=Session)
        target_session.id = "target-session-123"
        target_session.title = "Target Session"
        target_session.fork_name = ""
        target_session.created = "2024-01-01T00:00:00"
        target_session.last_modified = "2024-01-02T00:00:00"
        target_session.turns = []

        with patch.object(Session, 'load', return_value=target_session):
            result, is_error = await execute_link_tool(
                "follow_link",
                {"session_id": "target-session-123"},
                current_session
            )

        assert not is_error
        data = json.loads(result)

        assert data["session_id"] == "target-session-123"
        assert data["name"] == "Target Session"
        assert "link_summary" not in data  # No link_summary when using session_id

    @pytest.mark.asyncio
    async def test_follow_link_session_id_not_found(self):
        """Test follow_link returns error when session_id doesn't exist."""
        current_session = Mock(spec=Session)

        with patch.object(Session, 'load', return_value=None):
            result, is_error = await execute_link_tool(
                "follow_link",
                {"session_id": "nonexistent-123"},
                current_session
            )

        assert is_error
        assert "Session not found" in result


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

    def test_parse_balloons_tools_simple(self):
        runner = ClaudeRunner()
        text = '''Let me check the links.

<balloons-tool>
{"name": "list_links", "args": {}}
</balloons-tool>'''

        results = runner._parse_balloons_tools(text)

        assert len(results) == 1
        tool_name, tool_id, tool_args = results[0]
        assert tool_name == "list_links"
        assert tool_id is not None
        assert tool_id.startswith("balloons-")
        assert tool_args == {}

    def test_parse_balloons_tools_with_args(self):
        runner = ClaudeRunner()
        text = '''<balloons-tool>
{"name": "follow_link", "args": {"link_id": "abc123", "include_messages": 5}}
</balloons-tool>'''

        results = runner._parse_balloons_tools(text)

        assert len(results) == 1
        tool_name, tool_id, tool_args = results[0]
        assert tool_name == "follow_link"
        assert tool_args == {"link_id": "abc123", "include_messages": 5}

    def test_parse_balloons_tools_no_match(self):
        runner = ClaudeRunner()
        text = "Just some regular text without any tool calls."

        results = runner._parse_balloons_tools(text)

        assert results == []

    def test_parse_balloons_tools_incomplete(self):
        runner = ClaudeRunner()
        text = "<balloons-tool>{"  # Incomplete - no closing tag

        results = runner._parse_balloons_tools(text)

        assert results == []

    def test_parse_balloons_tools_invalid_json(self):
        runner = ClaudeRunner()
        text = '''<balloons-tool>
{invalid json}
</balloons-tool>'''

        results = runner._parse_balloons_tools(text)

        # Invalid JSON is skipped but doesn't fail
        assert results == []

    def test_parse_balloons_tools_embedded_in_text(self):
        runner = ClaudeRunner()
        text = '''I'll look up the linked sessions for more context.

<balloons-tool>
{"name": "list_links", "args": {}}
</balloons-tool>

Based on the results, I can see...'''

        results = runner._parse_balloons_tools(text)

        assert len(results) == 1
        tool_name, tool_id, tool_args = results[0]
        assert tool_name == "list_links"
        assert tool_args == {}

    def test_parse_balloons_tools_multiple_calls(self):
        """Test parsing multiple balloons-tool blocks in a single message."""
        runner = ClaudeRunner()
        text = '''Let me check the session info and list the links.

<balloons-tool>
{"name": "session_info", "args": {}}
</balloons-tool>

<balloons-tool>
{"name": "list_links", "args": {}}
</balloons-tool>

I'll analyze the results shortly.'''

        results = runner._parse_balloons_tools(text)

        assert len(results) == 2
        assert results[0][0] == "session_info"
        assert results[0][2] == {}
        assert results[1][0] == "list_links"
        assert results[1][2] == {}

    def test_parse_balloons_tools_multiple_with_args(self):
        """Test parsing multiple balloons-tool blocks with various arguments."""
        runner = ClaudeRunner()
        text = '''<balloons-tool>
{"name": "follow_link", "args": {"link_id": "abc123", "limit": 5}}
</balloons-tool>

<balloons-tool>
{"name": "search_linked_session", "args": {"link_id": "abc123", "query": "authentication"}}
</balloons-tool>'''

        results = runner._parse_balloons_tools(text)

        assert len(results) == 2
        assert results[0][0] == "follow_link"
        assert results[0][2] == {"link_id": "abc123", "limit": 5}
        assert results[1][0] == "search_linked_session"
        assert results[1][2] == {"link_id": "abc123", "query": "authentication"}

    def test_parse_balloons_tools_partial_invalid(self):
        """Test that valid tools are still parsed even if some are invalid."""
        runner = ClaudeRunner()
        text = '''<balloons-tool>
{"name": "session_info", "args": {}}
</balloons-tool>

<balloons-tool>
{invalid json here}
</balloons-tool>

<balloons-tool>
{"name": "list_links", "args": {}}
</balloons-tool>'''

        results = runner._parse_balloons_tools(text)

        # Should get 2 valid results, skipping the invalid one
        assert len(results) == 2
        assert results[0][0] == "session_info"
        assert results[1][0] == "list_links"

    def test_parse_balloons_tools_nested_json(self):
        """Test parsing tool with nested JSON arguments (like propose_fork context_plan)."""
        runner = ClaudeRunner()
        text = '''<balloons-tool>
{"name": "propose_fork", "args": {"name": "test-fork", "description": "Test", "context_plan": [{"exchange_range": "0", "mode": "copy", "reason": "Keep it"}]}}
</balloons-tool>'''

        results = runner._parse_balloons_tools(text)

        assert len(results) == 1
        tool_name, tool_id, tool_args = results[0]
        assert tool_name == "propose_fork"
        assert tool_args["name"] == "test-fork"
        assert len(tool_args["context_plan"]) == 1
        assert tool_args["context_plan"][0]["mode"] == "copy"

    def test_parse_balloons_tools_each_has_unique_id(self):
        """Test that each parsed tool gets a unique ID."""
        runner = ClaudeRunner()
        text = '''<balloons-tool>
{"name": "session_info", "args": {}}
</balloons-tool>

<balloons-tool>
{"name": "list_links", "args": {}}
</balloons-tool>'''

        results = runner._parse_balloons_tools(text)

        assert len(results) == 2
        # IDs should be different
        assert results[0][1] != results[1][1]
        # Both should start with balloons-
        assert results[0][1].startswith("balloons-")
        assert results[1][1].startswith("balloons-")

    def test_parse_balloons_tools_filters_code_fence_examples(self):
        """Test that balloons-tool blocks inside code fences are ignored (examples)."""
        runner = ClaudeRunner()
        text = '''Here's how to use the tool:

```
<balloons-tool>
{"name": "example_call", "args": {"this": "is an example"}}
</balloons-tool>
```

Now I'll actually call it:

<balloons-tool>
{"name": "real_call", "args": {"value": 42}}
</balloons-tool>'''

        results = runner._parse_balloons_tools(text)

        # Should only get the real call, not the example
        assert len(results) == 1
        tool_name, tool_id, tool_args = results[0]
        assert tool_name == "real_call"
        assert tool_args == {"value": 42}

    def test_parse_balloons_tools_all_in_code_fence(self):
        """Test that when all blocks are in code fences, nothing is parsed."""
        runner = ClaudeRunner()
        text = '''Here are some examples:

```
<balloons-tool>
{"name": "example1", "args": {}}
</balloons-tool>
```

```
<balloons-tool>
{"name": "example2", "args": {}}
</balloons-tool>
```'''

        results = runner._parse_balloons_tools(text)

        # No real calls, all examples
        assert len(results) == 0

    def test_parse_balloons_tools_multiple_in_one_fence(self):
        """Test that multiple blocks in one code fence are all ignored."""
        runner = ClaudeRunner()
        text = '''Examples of multiple calls:

```
<balloons-tool>
{"name": "example1", "args": {}}
</balloons-tool>

<balloons-tool>
{"name": "example2", "args": {}}
</balloons-tool>
```

Real call:

<balloons-tool>
{"name": "real_call", "args": {}}
</balloons-tool>'''

        results = runner._parse_balloons_tools(text)

        # Should only get the real call
        assert len(results) == 1
        assert results[0][0] == "real_call"
