"""Tests for context compilation from Message lists.

This module tests how internal Message structures are compiled into backend-specific
formats for API calls. It serves as both tests and specification for the expected
output formats.

SPEC: Context Compilation
=========================

The balloons app stores conversation history as a list of Message objects with
rich content_blocks (TextBlock, ToolUseBlock, ToolResultBlock, etc.). When making
API calls, this history must be compiled into the format expected by each backend.

CONTEXT FORMAT (XML-based):
---------------------------
Context is formatted with XML tags for structure:

    <conversation_history>
    <user>
    What is 2+2?
    </user>

    <assistant>
    The answer is 4.

    <tool_use name="Calculate" id="123">
    {"expression": "2+2"}
    </tool_use>
    </assistant>

    <tool_result id="123">
    4
    </tool_result>
    </conversation_history>

    new prompt here

This format is used consistently for:
- Sending to Claude API (via build_message_content)
- Token counting (via ContextBuilder.count_tokens)
- Display/debugging (via ContextBuilder.build_context)

OpenAI format (list of message dicts):
    [
      {"role": "system", "content": "<system prompt>"},  # if configured
      {"role": "user", "content": "<content>"},
      {"role": "assistant", "content": "<text>\\n\\n[Tool: <name>]\\n<json>"},
      {"role": "user", "content": "<new prompt>"}
    ]

CONTEXT MODE RULES:
-------------------
- COPY: Include message content verbatim
- SUMMARIZE: Use msg.summary if present, else fall back to content
- DROP: Exclude message entirely
"""

import json
import pytest

from models import (
    Message, TextBlock, ToolUseBlock, ToolResultBlock,
    InterruptionBlock, ErrorBlock, ArchiveBlock, ContextMode,
)

# Import builders
from core.context import ContextBuilder
from core.openai_runner import OpenAICompatibleRunner
from claude_runner import ClaudeRunner


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def simple_conversation():
    """Basic user-assistant exchange without tools."""
    return [
        Message(role="user", content="What is 2+2?"),
        Message(role="assistant", content="The answer is 4."),
    ]


@pytest.fixture
def conversation_with_tool_use():
    """Conversation with tool use and result.

    Note: Tool results come from the user role (representing the system
    executing the tool), not the assistant role.
    """
    return [
        Message(role="user", content="Read the config file"),
        Message(
            role="assistant",
            content="",
            content_blocks=[
                TextBlock(text="I'll read that file for you."),
                ToolUseBlock(
                    id="tool-123",
                    name="Read",
                    input={"file_path": "/etc/config.yaml"},
                ),
            ],
        ),
        Message(
            role="user",  # Tool results come from user role
            content="",
            content_blocks=[
                ToolResultBlock(
                    tool_use_id="tool-123",
                    content="key: value\nport: 8080",
                ),
            ],
        ),
    ]


@pytest.fixture
def conversation_with_tool_error():
    """Conversation with a tool that returns an error.

    Note: Tool results come from the user role.
    """
    return [
        Message(role="user", content="Read the missing file"),
        Message(
            role="assistant",
            content="",
            content_blocks=[
                ToolUseBlock(
                    id="tool-456",
                    name="Read",
                    input={"file_path": "/nonexistent"},
                ),
            ],
        ),
        Message(
            role="user",  # Tool results come from user role
            content="",
            content_blocks=[
                ToolResultBlock(
                    tool_use_id="tool-456",
                    content="File not found",
                    is_error=True,
                ),
            ],
        ),
    ]


@pytest.fixture
def conversation_with_multiple_tools():
    """Conversation with multiple tool uses in sequence."""
    return [
        Message(role="user", content="Find and read test files"),
        Message(
            role="assistant",
            content="",
            content_blocks=[
                ToolUseBlock(
                    id="tool-1",
                    name="Glob",
                    input={"pattern": "**/*test*.py"},
                ),
            ],
        ),
        Message(
            role="assistant",
            content="",
            content_blocks=[
                ToolResultBlock(
                    tool_use_id="tool-1",
                    content="test_foo.py\ntest_bar.py",
                ),
            ],
        ),
        Message(
            role="assistant",
            content="",
            content_blocks=[
                ToolUseBlock(
                    id="tool-2",
                    name="Read",
                    input={"file_path": "test_foo.py"},
                ),
            ],
        ),
        Message(
            role="assistant",
            content="",
            content_blocks=[
                ToolResultBlock(
                    tool_use_id="tool-2",
                    content="def test_example():\n    pass",
                ),
            ],
        ),
    ]


@pytest.fixture
def conversation_with_interruption():
    """Conversation with an interruption block."""
    return [
        Message(role="user", content="Do something long"),
        Message(
            role="assistant",
            content="",
            content_blocks=[
                TextBlock(text="Starting the task..."),
                InterruptionBlock(reason="user_cancelled"),
            ],
        ),
    ]


@pytest.fixture
def conversation_with_error_block():
    """Conversation with an error block (truncated response)."""
    return [
        Message(role="user", content="Generate a lot of text"),
        Message(
            role="assistant",
            content="",
            content_blocks=[
                TextBlock(text="Here is some text..."),
                ErrorBlock(reason="truncated", details="Response too long"),
            ],
        ),
    ]


@pytest.fixture
def conversation_with_context_modes():
    """Conversation with various context modes."""
    return [
        # COPY - include fully
        Message(role="user", content="First question", context_mode=ContextMode.COPY),
        # SUMMARIZE - use summary field
        Message(
            role="assistant",
            content="Long detailed answer that goes on and on...",
            context_mode=ContextMode.SUMMARIZE,
            summary="Brief: answered first question",
        ),
        # DROP - exclude entirely
        Message(role="user", content="Off-topic tangent", context_mode=ContextMode.DROP),
        Message(role="assistant", content="Response to tangent", context_mode=ContextMode.DROP),
        # COPY again
        Message(role="user", content="Back on topic", context_mode=ContextMode.COPY),
    ]


# =============================================================================
# ContextBuilder Tests (Single Source of Truth)
# =============================================================================

class TestContextBuilderFormat:
    """Tests for ContextBuilder output format - the single source of truth."""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_empty_messages_returns_just_prompt(self, builder):
        """Empty message list produces just the new prompt."""
        result = builder.build_context([], "Hello")
        assert result == "Hello"

    def test_simple_conversation_format(self, builder, simple_conversation):
        """Simple conversation uses XML tags."""
        result = builder.build_context(simple_conversation, "follow up")

        # Check XML structure
        assert "<conversation_history>" in result
        assert "</conversation_history>" in result
        assert "<user>" in result
        assert "</user>" in result
        assert "<assistant>" in result
        assert "</assistant>" in result
        assert "What is 2+2?" in result
        assert "The answer is 4." in result
        assert "follow up" in result

    def test_tool_use_format(self, builder, conversation_with_tool_use):
        """Tool use is formatted with XML tags."""
        result = builder.build_context(conversation_with_tool_use, "next")

        # Check tool use XML
        assert '<tool_use name="Read" id="tool-123">' in result
        assert '"file_path"' in result
        assert '"/etc/config.yaml"' in result

    def test_tool_result_format(self, builder, conversation_with_tool_use):
        """Tool result is formatted with XML tags."""
        result = builder.build_context(conversation_with_tool_use, "next")

        assert '<tool_result id="tool-123">' in result
        assert "key: value" in result
        assert "port: 8080" in result

    def test_tool_error_format(self, builder, conversation_with_tool_error):
        """Tool errors include error attribute."""
        result = builder.build_context(conversation_with_tool_error, "next")

        assert '<tool_result id="tool-456" error="true">' in result
        assert "File not found" in result

    def test_multiple_tools_ordering(self, builder, conversation_with_multiple_tools):
        """Multiple tools appear in order with their results."""
        result = builder.build_context(conversation_with_multiple_tools, "done")

        # Find positions of each element
        glob_pos = result.find('<tool_use name="Glob"')
        glob_result_pos = result.find("test_foo.py")
        read_pos = result.find('<tool_use name="Read"')
        read_result_pos = result.find("def test_example")

        # Verify ordering
        assert glob_pos < glob_result_pos < read_pos < read_result_pos

    def test_interruption_block_format(self, builder, conversation_with_interruption):
        """Interruption blocks are formatted with reason."""
        result = builder.build_context(conversation_with_interruption, "continue")

        assert "[Response interrupted: user_cancelled]" in result

    def test_error_block_format(self, builder, conversation_with_error_block):
        """Error blocks show truncation info."""
        result = builder.build_context(conversation_with_error_block, "retry")

        assert "[Response truncated: truncated]" in result

    def test_drop_mode_excludes_messages(self, builder, conversation_with_context_modes):
        """DROP mode messages are not included in output."""
        result = builder.build_context(conversation_with_context_modes, "new")

        assert "Off-topic tangent" not in result
        assert "Response to tangent" not in result

    def test_summarize_mode_uses_summary(self, builder, conversation_with_context_modes):
        """SUMMARIZE mode uses summary field instead of content."""
        result = builder.build_context(conversation_with_context_modes, "new")

        assert "[Summary] Brief: answered first question" in result
        assert "Long detailed answer" not in result

    def test_copy_mode_includes_full_content(self, builder, conversation_with_context_modes):
        """COPY mode includes full content."""
        result = builder.build_context(conversation_with_context_modes, "new")

        assert "First question" in result
        assert "Back on topic" in result

    def test_summarize_without_summary_falls_back(self, builder):
        """SUMMARIZE mode without summary uses content."""
        messages = [
            Message(
                role="user",
                content="Original content",
                context_mode=ContextMode.SUMMARIZE,
                summary="",  # Empty summary
            ),
        ]
        result = builder.build_context(messages, "new")

        assert "Original content" in result

    def test_mixed_content_blocks_all_included(self, builder):
        """Messages with mixed block types include all blocks."""
        messages = [
            Message(
                role="assistant",
                content="",
                content_blocks=[
                    TextBlock(text="First I'll check the file."),
                    ToolUseBlock(id="t1", name="Read", input={"file_path": "x.py"}),
                    ToolResultBlock(tool_use_id="t1", content="code here"),
                    TextBlock(text="The file contains code."),
                ],
            ),
        ]
        result = builder.build_context(messages, "next")

        assert "First I'll check the file." in result
        assert '<tool_use name="Read"' in result
        assert '<tool_result id="t1">' in result
        assert "code here" in result
        assert "The file contains code." in result

    def test_empty_text_blocks_skipped(self, builder):
        """Empty text blocks don't add extra content."""
        messages = [
            Message(
                role="assistant",
                content="",
                content_blocks=[
                    TextBlock(text=""),  # Empty
                    TextBlock(text="Actual content"),
                ],
            ),
        ]
        result = builder.build_context(messages, "next")

        assert "Actual content" in result


# =============================================================================
# ClaudeRunner Tests (Delegates to ContextBuilder)
# =============================================================================

class TestClaudeContextFormat:
    """Tests for ClaudeRunner.build_context() - should match ContextBuilder."""

    def test_delegates_to_context_builder(self, simple_conversation):
        """ClaudeRunner.build_context delegates to ContextBuilder."""
        claude_result = ClaudeRunner.build_context(simple_conversation, "follow up")
        builder_result = ContextBuilder().build_context(simple_conversation, "follow up")

        assert claude_result == builder_result

    def test_empty_messages_returns_just_prompt(self):
        """Empty message list produces just the new prompt."""
        result = ClaudeRunner.build_context([], "Hello")
        assert result == "Hello"

    def test_tool_use_format(self, conversation_with_tool_use):
        """Tool use is formatted with XML tags."""
        result = ClaudeRunner.build_context(conversation_with_tool_use, "next")
        assert '<tool_use name="Read"' in result

    def test_drop_mode_excludes_messages(self, conversation_with_context_modes):
        """DROP mode messages are not included in output."""
        result = ClaudeRunner.build_context(conversation_with_context_modes, "new")
        assert "Off-topic tangent" not in result


# =============================================================================
# OpenAI Runner Tests
# =============================================================================

class TestOpenAIContextFormat:
    """Tests for OpenAICompatibleRunner.build_messages() output format.

    Note: Runners now build system prompts per-turn, including balloons tools
    and domain prompts even when no user_prompt is provided. Tests account for
    this by checking that system prompts are present.
    """

    @pytest.fixture
    def runner(self):
        """Create runner without user prompt for basic tests.

        Note: Will still have balloons tools prompt from per-turn building.
        """
        return OpenAICompatibleRunner(
            base_url="http://test",
            api_key="test",
            model="test-model",
        )

    @pytest.fixture
    def runner_with_user_prompt(self):
        """Create runner with user-provided system prompt."""
        return OpenAICompatibleRunner(
            base_url="http://test",
            api_key="test",
            model="test-model",
            user_prompt="You are a helpful assistant.",
        )

    def test_empty_messages_includes_system_prompt(self, runner):
        """Empty message list includes system (balloons tools) and user prompt."""
        result = runner.build_messages([], "Hello")

        # Should have system prompt (balloons tools) + user message
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "Balloons" in result[0]["content"] or "supervisor" in result[0]["content"].lower()
        assert result[1] == {"role": "user", "content": "Hello"}

    def test_user_prompt_included_in_system(self, runner_with_user_prompt):
        """User-provided system prompt is included in system message."""
        result = runner_with_user_prompt.build_messages([], "Hello")

        assert len(result) == 2
        assert result[0]["role"] == "system"
        # User prompt should be included in the system message
        assert "You are a helpful assistant." in result[0]["content"]
        assert result[1] == {"role": "user", "content": "Hello"}

    def test_simple_conversation_format(self, runner, simple_conversation):
        """Simple conversation maps to user/assistant roles."""
        result = runner.build_messages(simple_conversation, "follow up")

        # Should have: system, user, assistant, user (follow up)
        assert len(result) == 4
        assert result[0]["role"] == "system"  # Balloons tools
        assert result[1]["role"] == "user"
        assert "What is 2+2?" in result[1]["content"]
        assert result[2]["role"] == "assistant"
        assert "The answer is 4." in result[2]["content"]
        assert result[3]["role"] == "user"
        assert result[3]["content"] == "follow up"

    def test_tool_use_in_tool_calls_field(self, runner, conversation_with_tool_use):
        """Tool uses appear in tool_calls field (proper OpenAI format)."""
        result = runner.build_messages(conversation_with_tool_use, "next")

        # Find assistant message with tool_calls
        assistant_msgs = [m for m in result if m.get("role") == "assistant"]
        assert len(assistant_msgs) >= 1

        # First assistant message should have tool_calls
        tool_msg = assistant_msgs[0]
        assert "tool_calls" in tool_msg
        assert len(tool_msg["tool_calls"]) == 1
        assert tool_msg["tool_calls"][0]["function"]["name"] == "Read"
        assert '"file_path"' in tool_msg["tool_calls"][0]["function"]["arguments"]

    def test_tool_result_as_tool_role(self, runner, conversation_with_tool_use):
        """Tool results appear as role=tool messages (proper OpenAI format)."""
        result = runner.build_messages(conversation_with_tool_use, "next")

        # Find tool role messages
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1
        assert tool_msgs[0]["tool_call_id"] == "tool-123"
        assert "key: value" in tool_msgs[0]["content"]

    def test_tool_error_in_tool_result(self, runner, conversation_with_tool_error):
        """Tool errors appear in tool role messages."""
        result = runner.build_messages(conversation_with_tool_error, "next")

        # Find tool role messages
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1
        assert "File not found" in tool_msgs[0]["content"]

    def test_interruption_block_format(self, runner, conversation_with_interruption):
        """Interruption blocks are formatted in OpenAI messages."""
        result = runner.build_messages(conversation_with_interruption, "continue")
        all_content = " ".join(m.get("content", "") for m in result)

        assert "[Interrupted: user_cancelled]" in all_content

    def test_error_block_format(self, runner, conversation_with_error_block):
        """Error blocks are formatted in OpenAI messages."""
        result = runner.build_messages(conversation_with_error_block, "retry")
        all_content = " ".join(m.get("content", "") for m in result)

        assert "[Error: truncated]" in all_content

    def test_drop_mode_excludes_messages(self, runner, conversation_with_context_modes):
        """DROP mode messages are not included in OpenAI output."""
        result = runner.build_messages(conversation_with_context_modes, "new")
        all_content = " ".join(m.get("content", "") for m in result)

        assert "Off-topic tangent" not in all_content

    def test_summarize_mode_uses_summary(self, runner, conversation_with_context_modes):
        """SUMMARIZE mode uses summary field in OpenAI format."""
        result = runner.build_messages(conversation_with_context_modes, "new")
        all_content = " ".join(m.get("content", "") for m in result)

        assert "[Summary]" in all_content

    def test_output_is_list_of_dicts(self, runner, simple_conversation):
        """Output is a list of message dicts."""
        result = runner.build_messages(simple_conversation, "next")

        assert isinstance(result, list)
        for msg in result:
            assert isinstance(msg, dict)
            assert "role" in msg
            assert "content" in msg

    def test_role_mapping(self, runner, simple_conversation):
        """Roles are correctly mapped (accounting for system prompt)."""
        result = runner.build_messages(simple_conversation, "next")

        # First message is system (balloons tools), then conversation follows
        assert result[0]["role"] == "system"  # Balloons tools
        assert result[1]["role"] == "user"    # First user message
        assert result[2]["role"] == "assistant"
        assert result[3]["role"] == "user"    # New prompt


# =============================================================================
# Cross-Backend Consistency
# =============================================================================

def _openai_content_str(result: list[dict]) -> str:
    """Join all content fields from OpenAI messages, handling None values."""
    parts = []
    for m in result:
        content = m.get("content")
        if content is not None:
            parts.append(content if isinstance(content, str) else str(content))
    return " ".join(parts)


def _openai_has_tool(result: list[dict], tool_name: str) -> bool:
    """Check if any message has a tool_call with the given name."""
    for m in result:
        if "tool_calls" in m:
            for tc in m["tool_calls"]:
                if tc.get("function", {}).get("name") == tool_name:
                    return True
    return False


class TestCrossBackendConsistency:
    """Tests ensuring both backends handle the same scenarios consistently.

    Note: ContextBuilder uses XML text format, while OpenAI uses structured
    tool_calls array. Tests check equivalent semantics, not identical text.
    """

    @pytest.fixture
    def openai_runner(self):
        return OpenAICompatibleRunner(
            base_url="http://test",
            api_key="test",
            model="test-model",
        )

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_both_include_all_tool_uses(self, builder, openai_runner, conversation_with_multiple_tools):
        """Both backends include all tool uses from conversation."""
        context_result = builder.build_context(conversation_with_multiple_tools, "done")
        openai_result = openai_runner.build_messages(conversation_with_multiple_tools, "done")

        # ContextBuilder uses XML format
        assert '<tool_use name="Glob"' in context_result
        assert '<tool_use name="Read"' in context_result

        # OpenAI uses tool_calls array (not text)
        assert _openai_has_tool(openai_result, "Glob")
        assert _openai_has_tool(openai_result, "Read")

    def test_both_respect_drop_mode(self, builder, openai_runner, conversation_with_context_modes):
        """Both backends respect DROP context mode."""
        context_result = builder.build_context(conversation_with_context_modes, "new")
        openai_result = openai_runner.build_messages(conversation_with_context_modes, "new")
        openai_content = _openai_content_str(openai_result)

        # Neither should have dropped content
        assert "Off-topic tangent" not in context_result
        assert "Off-topic tangent" not in openai_content

    def test_both_use_summary_in_summarize_mode(self, builder, openai_runner, conversation_with_context_modes):
        """Both backends use summary field in SUMMARIZE mode."""
        context_result = builder.build_context(conversation_with_context_modes, "new")
        openai_result = openai_runner.build_messages(conversation_with_context_modes, "new")
        openai_content = _openai_content_str(openai_result)

        # Both should use summary
        assert "[Summary]" in context_result
        assert "[Summary]" in openai_content

    def test_both_handle_tool_results(self, builder, openai_runner, conversation_with_tool_error):
        """Both backends include tool results."""
        context_result = builder.build_context(conversation_with_tool_error, "next")
        openai_result = openai_runner.build_messages(conversation_with_tool_error, "next")

        # ContextBuilder uses XML attribute for errors
        assert 'error="true"' in context_result

        # OpenAI uses role="tool" messages for results
        tool_msgs = [m for m in openai_result if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1
        assert "File not found" in tool_msgs[0]["content"]


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions.

    Note: OpenAI messages include a system prompt first, so user content
    is typically at index 1+. Use _openai_content_str() to join all content.
    """

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    @pytest.fixture
    def openai_runner(self):
        return OpenAICompatibleRunner(
            base_url="http://test",
            api_key="test",
            model="test-model",
        )

    def test_empty_content_blocks_fallback_to_content(self, builder, openai_runner):
        """Empty content_blocks uses plain content field."""
        messages = [
            Message(role="user", content="plain text", content_blocks=[]),
        ]

        context_result = builder.build_context(messages, "new")
        openai_result = openai_runner.build_messages(messages, "new")
        openai_content = _openai_content_str(openai_result)

        assert "plain text" in context_result
        assert "plain text" in openai_content

    def test_special_characters_in_content(self, builder, openai_runner):
        """Special characters are preserved."""
        messages = [
            Message(role="user", content="Code: `x = 1`\nJSON: {\"a\": 1}"),
        ]

        context_result = builder.build_context(messages, "new")
        openai_result = openai_runner.build_messages(messages, "new")
        openai_content = _openai_content_str(openai_result)

        assert '`x = 1`' in context_result
        assert '{"a": 1}' in context_result
        assert '`x = 1`' in openai_content

    def test_very_long_tool_result(self, builder, openai_runner):
        """Long tool results are included fully (truncation is display concern)."""
        long_content = "x" * 50000
        messages = [
            Message(
                role="user",  # Tool results come from user role
                content="",
                content_blocks=[
                    ToolResultBlock(tool_use_id="t1", content=long_content),
                ],
            ),
        ]

        context_result = builder.build_context(messages, "new")
        openai_result = openai_runner.build_messages(messages, "new")

        assert long_content in context_result
        # Find tool role message for the result
        tool_msgs = [m for m in openai_result if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1
        assert long_content in tool_msgs[0]["content"]

    def test_unicode_content(self, builder, openai_runner):
        """Unicode content is handled correctly."""
        messages = [
            Message(role="user", content="Hello 🌍 World 🎉"),
        ]

        context_result = builder.build_context(messages, "new")
        openai_result = openai_runner.build_messages(messages, "new")
        openai_content = _openai_content_str(openai_result)

        assert "🌍" in context_result
        assert "🌍" in openai_content

    def test_nested_json_in_tool_input(self, builder, openai_runner):
        """Nested JSON in tool input is properly serialized."""
        messages = [
            Message(
                role="assistant",
                content="",
                content_blocks=[
                    ToolUseBlock(
                        id="t1",
                        name="Write",
                        input={
                            "file_path": "test.json",
                            "content": {"nested": {"deep": [1, 2, 3]}},
                        },
                    ),
                ],
            ),
        ]

        context_result = builder.build_context(messages, "new")
        openai_result = openai_runner.build_messages(messages, "new")

        # Both should have the nested structure serialized
        assert '"nested"' in context_result
        assert '"deep"' in context_result

        # OpenAI puts tool input in tool_calls[].function.arguments
        assistant_msgs = [m for m in openai_result if m.get("tool_calls")]
        assert len(assistant_msgs) >= 1
        args_json = assistant_msgs[0]["tool_calls"][0]["function"]["arguments"]
        assert '"nested"' in args_json

    def test_newlines_in_tool_result(self, builder, openai_runner):
        """Newlines in tool results are preserved."""
        messages = [
            Message(
                role="user",  # Tool results come from user role
                content="",
                content_blocks=[
                    ToolResultBlock(
                        tool_use_id="t1",
                        content="line1\nline2\nline3",
                    ),
                ],
            ),
        ]

        context_result = builder.build_context(messages, "new")
        openai_result = openai_runner.build_messages(messages, "new")

        assert "line1\nline2\nline3" in context_result

        # OpenAI puts tool results in role=tool messages
        tool_msgs = [m for m in openai_result if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1
        assert "line1\nline2\nline3" in tool_msgs[0]["content"]


# =============================================================================
# Archive Block Tests
# =============================================================================

class TestArchiveBlockFormat:
    """Tests for ArchiveBlock context formatting."""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    @pytest.fixture
    def openai_runner(self):
        return OpenAICompatibleRunner(
            base_url="http://test",
            api_key="test",
            model="test-model",
        )

    @pytest.fixture
    def conversation_with_archive(self):
        """Conversation with an archive block."""
        return [
            Message(role="user", content="First message"),
            Message(
                role="system",
                content="[Archived 5 turns: Discussion about API design]",
                content_blocks=[
                    ArchiveBlock(
                        archive_id="archive-123-abc",
                        file_path="/path/to/archive.json",
                        summary="Discussion about API design",
                        turn_start=1,
                        turn_end=6,
                        message_count=5,
                        token_estimate=1500,
                    ),
                ],
            ),
            Message(role="user", content="Continuing the conversation"),
        ]

    def test_archive_block_shows_summary(self, builder, conversation_with_archive):
        """Archive block shows summary in context."""
        result = builder.build_context(conversation_with_archive, "new question")

        assert "Archived 5 turns" in result
        assert "Discussion about API design" in result

    def test_archive_block_shows_archive_id(self, builder, conversation_with_archive):
        """Archive block shows archive_id for retrieval."""
        result = builder.build_context(conversation_with_archive, "new question")

        assert "archive-123-abc" in result

    def test_archive_block_in_openai_format(self, openai_runner, conversation_with_archive):
        """Archive block is formatted correctly in OpenAI messages."""
        result = openai_runner.build_messages(conversation_with_archive, "new question")
        all_content = " ".join(m.get("content", "") for m in result)

        assert "Archived 5 turns" in all_content
        assert "Discussion about API design" in all_content

    def test_archive_in_assistant_message(self, builder, openai_runner):
        """Archive block in assistant message is formatted correctly."""
        messages = [
            Message(
                role="assistant",
                content="",
                content_blocks=[
                    TextBlock(text="Here's what happened earlier:"),
                    ArchiveBlock(
                        archive_id="archive-456",
                        file_path="/path/to/archive.json",
                        summary="Tool use and results for file operations",
                        turn_start=0,
                        turn_end=10,
                        message_count=10,
                        token_estimate=3000,
                    ),
                ],
            ),
        ]

        context_result = builder.build_context(messages, "continue")
        openai_result = openai_runner.build_messages(messages, "continue")
        openai_content = " ".join(m.get("content", "") for m in openai_result)

        # Both should have archive info
        assert "Archived 10 turns" in context_result
        assert "file operations" in context_result
        assert "archive-456" in context_result

        assert "Archived 10 turns" in openai_content
        assert "file operations" in openai_content

    def test_multiple_archives_in_context(self, builder):
        """Multiple archive blocks are all included."""
        messages = [
            Message(
                role="system",
                content="",
                content_blocks=[
                    ArchiveBlock(
                        archive_id="archive-1",
                        file_path="/path/1.json",
                        summary="Initial setup discussion",
                        turn_start=0,
                        turn_end=5,
                        message_count=5,
                        token_estimate=1000,
                    ),
                ],
            ),
            Message(role="user", content="Middle message"),
            Message(
                role="system",
                content="",
                content_blocks=[
                    ArchiveBlock(
                        archive_id="archive-2",
                        file_path="/path/2.json",
                        summary="Implementation details",
                        turn_start=6,
                        turn_end=15,
                        message_count=9,
                        token_estimate=2000,
                    ),
                ],
            ),
        ]

        result = builder.build_context(messages, "final")

        assert "Initial setup discussion" in result
        assert "Implementation details" in result
        assert "archive-1" in result
        assert "archive-2" in result
