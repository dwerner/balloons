"""Tests for context compilation from Message lists.

This module tests how internal Message structures are compiled into backend-specific
formats for API calls. It serves as both tests and specification for the expected
output formats.

SPEC: Context Compilation
=========================

The balloons app stores conversation history as a list of Message objects with
rich content_blocks (TextBlock, ToolUseBlock, ToolResultBlock, etc.). When making
API calls, this history must be compiled into the format expected by each backend.

Supported Backends:
1. Claude (via claude CLI) - Text-based context (single string)
2. OpenAI-compatible APIs - Chat completion format (list of message dicts)

CURRENT FORMAT (Text Serialization):
------------------------------------
Both backends currently serialize tool calls as text, not native API formats.

Claude format (single string, newline-separated):
    User: <content>

    Assistant: <text>

    [Tool Use: <name>]
    <json input>

    [Tool Result]
    <result content>

    User: <new prompt>

OpenAI format (list of message dicts):
    [
      {"role": "system", "content": "<system prompt>"},  # if configured
      {"role": "user", "content": "<content>"},
      {"role": "assistant", "content": "<text>\\n\\n[Tool Use: <name>]\\n<json>"},
      {"role": "user", "content": "<new prompt>"}
    ]

CONTEXT MODE RULES:
-------------------
- COPY: Include message content verbatim
- SUMMARIZE: Use msg.summary if present, else fall back to content
- DROP: Exclude message entirely

FUTURE: Native Tool Formats (not yet implemented):
--------------------------------------------------
Claude native format would use content blocks:
    [
      {"role": "user", "content": [{"type": "text", "text": "..."}]},
      {"role": "assistant", "content": [
        {"type": "text", "text": "..."},
        {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
      ]},
      {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "...", "content": "..."}
      ]}
    ]

OpenAI native format would use tool_calls and role=tool:
    [
      {"role": "user", "content": "..."},
      {"role": "assistant", "content": "...", "tool_calls": [
        {"id": "...", "type": "function", "function": {"name": "...", "arguments": "{...}"}}
      ]},
      {"role": "tool", "tool_call_id": "...", "content": "..."}
    ]
"""

import json
import pytest

from models import (
    Message, TextBlock, ToolUseBlock, ToolResultBlock,
    InterruptionBlock, ErrorBlock, ContextMode,
)

# Import OpenAI runner first (doesn't import claude_runner)
from core.openai_runner import OpenAICompatibleRunner
# Then import claude_runner (which may cause core/__init__.py to load, but that's OK
# since openai_runner is already loaded)
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
    """Conversation with tool use and result."""
    return [
        Message(role="user", content="Read the config file"),
        Message(
            role="assistant",
            content="Let me read that file.",
            content_blocks=[
                TextBlock(text="Let me read that file."),
                ToolUseBlock(
                    id="tool_001",
                    name="Read",
                    input={"file_path": "/etc/config.yaml"}
                ),
            ],
        ),
        Message(
            role="assistant",
            content="[Tool Result]",
            content_blocks=[
                ToolResultBlock(
                    tool_use_id="tool_001",
                    content="key: value\nport: 8080",
                    is_error=False,
                ),
            ],
        ),
        Message(
            role="assistant",
            content="The config file contains key=value and port=8080.",
            content_blocks=[
                TextBlock(text="The config file contains key=value and port=8080."),
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
            content="I'll search for test files.",
            content_blocks=[
                TextBlock(text="I'll search for test files."),
                ToolUseBlock(
                    id="tool_001",
                    name="Glob",
                    input={"pattern": "test_*.py"}
                ),
            ],
        ),
        Message(
            role="assistant",
            content="",
            content_blocks=[
                ToolResultBlock(
                    tool_use_id="tool_001",
                    content="test_foo.py\ntest_bar.py",
                ),
            ],
        ),
        Message(
            role="assistant",
            content="Found 2 test files, reading the first one.",
            content_blocks=[
                TextBlock(text="Found 2 test files, reading the first one."),
                ToolUseBlock(
                    id="tool_002",
                    name="Read",
                    input={"file_path": "test_foo.py"}
                ),
            ],
        ),
        Message(
            role="assistant",
            content="",
            content_blocks=[
                ToolResultBlock(
                    tool_use_id="tool_002",
                    content="def test_example():\n    assert True",
                ),
            ],
        ),
    ]


@pytest.fixture
def conversation_with_tool_error():
    """Conversation where a tool returns an error."""
    return [
        Message(role="user", content="Read the missing file"),
        Message(
            role="assistant",
            content="Let me try to read that.",
            content_blocks=[
                TextBlock(text="Let me try to read that."),
                ToolUseBlock(
                    id="tool_001",
                    name="Read",
                    input={"file_path": "/nonexistent.txt"}
                ),
            ],
        ),
        Message(
            role="assistant",
            content="",
            content_blocks=[
                ToolResultBlock(
                    tool_use_id="tool_001",
                    content="Error: File not found",
                    is_error=True,
                ),
            ],
        ),
    ]


@pytest.fixture
def conversation_with_interruption():
    """Conversation where response was interrupted."""
    return [
        Message(role="user", content="Write a long essay"),
        Message(
            role="assistant",
            content="Here is the beginning of the essay...",
            content_blocks=[
                TextBlock(text="Here is the beginning of the essay..."),
                InterruptionBlock(reason="user_cancelled"),
            ],
        ),
    ]


@pytest.fixture
def conversation_with_error_block():
    """Conversation where response was truncated."""
    return [
        Message(role="user", content="Do something complex"),
        Message(
            role="assistant",
            content="Starting the task...",
            content_blocks=[
                TextBlock(text="Starting the task..."),
                ErrorBlock(
                    reason="truncated",
                    partial_tool_name="Edit",
                    partial_tool_input='{"file_path": "/some/file',
                ),
            ],
        ),
    ]


@pytest.fixture
def conversation_with_context_modes():
    """Conversation with different context modes."""
    return [
        Message(
            role="user",
            content="First question",
            context_mode=ContextMode.COPY,
        ),
        Message(
            role="assistant",
            content="Long detailed answer that should be summarized...",
            context_mode=ContextMode.SUMMARIZE,
            summary="Brief: answered first question",
        ),
        Message(
            role="user",
            content="Off-topic tangent to drop",
            context_mode=ContextMode.DROP,
        ),
        Message(
            role="assistant",
            content="Response to tangent",
            context_mode=ContextMode.DROP,
        ),
        Message(
            role="user",
            content="Back on topic",
            context_mode=ContextMode.COPY,
        ),
    ]


# =============================================================================
# Claude Runner Tests
# =============================================================================

class TestClaudeContextFormat:
    """Tests for ClaudeRunner.build_context() output format."""

    def test_empty_messages_returns_just_prompt(self):
        """Empty message list produces just the new prompt."""
        result = ClaudeRunner.build_context([], "Hello")
        assert result == "User: Hello"

    def test_simple_conversation_format(self, simple_conversation):
        """Simple conversation uses User/Assistant prefixes."""
        result = ClaudeRunner.build_context(simple_conversation, "follow up")

        # Check structure
        lines = result.split("\n\n")
        assert len(lines) == 3

        assert lines[0] == "User: What is 2+2?"
        assert lines[1] == "Assistant: The answer is 4."
        assert lines[2] == "User: follow up"

    def test_tool_use_format(self, conversation_with_tool_use):
        """Tool use is formatted as [Tool Use: name] with JSON input."""
        result = ClaudeRunner.build_context(conversation_with_tool_use, "next")

        # Check tool use marker present
        assert "[Tool Use: Read]" in result

        # Check JSON input is included
        assert '"file_path"' in result
        assert '"/etc/config.yaml"' in result

    def test_tool_result_format(self, conversation_with_tool_use):
        """Tool result is formatted as [Tool Result] with content."""
        result = ClaudeRunner.build_context(conversation_with_tool_use, "next")

        assert "[Tool Result]" in result
        assert "key: value" in result
        assert "port: 8080" in result

    def test_tool_error_format(self, conversation_with_tool_error):
        """Tool errors include [Error] prefix in result."""
        result = ClaudeRunner.build_context(conversation_with_tool_error, "next")

        assert "[Tool Result][Error]" in result
        assert "File not found" in result

    def test_multiple_tools_ordering(self, conversation_with_multiple_tools):
        """Multiple tools appear in order with their results."""
        result = ClaudeRunner.build_context(conversation_with_multiple_tools, "done")

        # Find positions of each element
        glob_pos = result.find("[Tool Use: Glob]")
        glob_result_pos = result.find("test_foo.py")
        read_pos = result.find("[Tool Use: Read]")
        read_result_pos = result.find("def test_example")

        # Verify ordering
        assert glob_pos < glob_result_pos < read_pos < read_result_pos

    def test_interruption_block_format(self, conversation_with_interruption):
        """Interruption blocks are formatted with reason."""
        result = ClaudeRunner.build_context(conversation_with_interruption, "continue")

        assert "[Response interrupted: user_cancelled]" in result

    def test_error_block_format(self, conversation_with_error_block):
        """Error blocks show truncation info and partial tool state."""
        result = ClaudeRunner.build_context(conversation_with_error_block, "retry")

        assert "[Response truncated: truncated]" in result
        assert "[Incomplete tool call: Edit]" in result
        assert "[Partial input:" in result

    def test_drop_mode_excludes_messages(self, conversation_with_context_modes):
        """DROP mode messages are not included in output."""
        result = ClaudeRunner.build_context(conversation_with_context_modes, "new")

        assert "Off-topic tangent" not in result
        assert "Response to tangent" not in result

    def test_summarize_mode_uses_summary(self, conversation_with_context_modes):
        """SUMMARIZE mode uses summary field instead of content."""
        result = ClaudeRunner.build_context(conversation_with_context_modes, "new")

        assert "[Summary] Brief: answered first question" in result
        assert "Long detailed answer" not in result

    def test_copy_mode_includes_full_content(self, conversation_with_context_modes):
        """COPY mode includes full content."""
        result = ClaudeRunner.build_context(conversation_with_context_modes, "new")

        assert "First question" in result
        assert "Back on topic" in result

    def test_summarize_without_summary_falls_back(self):
        """SUMMARIZE mode without summary uses content."""
        messages = [
            Message(
                role="user",
                content="Original content",
                context_mode=ContextMode.SUMMARIZE,
                summary="",  # Empty summary
            ),
        ]
        result = ClaudeRunner.build_context(messages, "new")

        assert "Original content" in result

    def test_mixed_content_blocks_all_included(self):
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
        result = ClaudeRunner.build_context(messages, "next")

        assert "First I'll check the file." in result
        assert "[Tool Use: Read]" in result
        assert "[Tool Result]" in result
        assert "code here" in result
        assert "The file contains code." in result

    def test_empty_text_blocks_skipped(self):
        """Empty text blocks don't add extra whitespace."""
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
        result = ClaudeRunner.build_context(messages, "next")

        # Should have content but not extra blank entries
        assert "Actual content" in result
        assert "Assistant: \n\n" not in result  # No empty prefix


# =============================================================================
# OpenAI Runner Tests
# =============================================================================

class TestOpenAIContextFormat:
    """Tests for OpenAICompatibleRunner.build_messages() output format."""

    @pytest.fixture
    def runner(self):
        """Create runner without system prompt for basic tests."""
        return OpenAICompatibleRunner(
            base_url="http://test",
            api_key="test",
            model="test-model",
        )

    @pytest.fixture
    def runner_with_system(self):
        """Create runner with system prompt."""
        return OpenAICompatibleRunner(
            base_url="http://test",
            api_key="test",
            model="test-model",
            system_prompt="You are a helpful assistant.",
        )

    def test_empty_messages_returns_just_prompt(self, runner):
        """Empty message list produces just the new prompt."""
        result = runner.build_messages([], "Hello")

        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "Hello"}

    def test_system_prompt_prepended(self, runner_with_system):
        """System prompt is first message when configured."""
        result = runner_with_system.build_messages([], "Hello")

        assert len(result) == 2
        assert result[0] == {
            "role": "system",
            "content": "You are a helpful assistant.",
        }
        assert result[1] == {"role": "user", "content": "Hello"}

    def test_simple_conversation_format(self, runner, simple_conversation):
        """Simple conversation maps to user/assistant roles."""
        result = runner.build_messages(simple_conversation, "follow up")

        assert len(result) == 3
        assert result[0] == {"role": "user", "content": "What is 2+2?"}
        assert result[1] == {"role": "assistant", "content": "The answer is 4."}
        assert result[2] == {"role": "user", "content": "follow up"}

    def test_tool_use_serialized_as_text(self, runner, conversation_with_tool_use):
        """Tool use is currently serialized as text in content."""
        result = runner.build_messages(conversation_with_tool_use, "next")

        # Find the message with tool use
        tool_msg = next(m for m in result if "[Tool Use: Read]" in m.get("content", ""))

        assert tool_msg["role"] == "assistant"
        assert '"file_path"' in tool_msg["content"]
        assert '"/etc/config.yaml"' in tool_msg["content"]

    def test_tool_result_serialized_as_text(self, runner, conversation_with_tool_use):
        """Tool result is currently serialized as text in content."""
        result = runner.build_messages(conversation_with_tool_use, "next")

        # Find the message with tool result
        result_msg = next(m for m in result if "[Tool Result]" in m.get("content", ""))

        assert result_msg["role"] == "assistant"
        assert "key: value" in result_msg["content"]

    def test_tool_error_format(self, runner, conversation_with_tool_error):
        """Tool errors include [Error] prefix."""
        result = runner.build_messages(conversation_with_tool_error, "next")

        all_content = " ".join(m.get("content", "") for m in result)
        assert "[Tool Result][Error]" in all_content
        assert "File not found" in all_content

    def test_interruption_block_format(self, runner, conversation_with_interruption):
        """Interruption blocks are formatted with reason."""
        result = runner.build_messages(conversation_with_interruption, "continue")

        all_content = " ".join(m.get("content", "") for m in result)
        assert "[Response interrupted: user_cancelled]" in all_content

    def test_error_block_format(self, runner, conversation_with_error_block):
        """Error blocks show truncation info."""
        result = runner.build_messages(conversation_with_error_block, "retry")

        all_content = " ".join(m.get("content", "") for m in result)
        assert "[Response truncated: truncated]" in all_content
        assert "[Incomplete tool call: Edit]" in all_content

    def test_drop_mode_excludes_messages(self, runner, conversation_with_context_modes):
        """DROP mode messages are not included."""
        result = runner.build_messages(conversation_with_context_modes, "new")

        all_content = " ".join(m.get("content", "") for m in result)
        assert "Off-topic tangent" not in all_content
        assert "Response to tangent" not in all_content

    def test_summarize_mode_uses_summary(self, runner, conversation_with_context_modes):
        """SUMMARIZE mode uses summary field."""
        result = runner.build_messages(conversation_with_context_modes, "new")

        all_content = " ".join(m.get("content", "") for m in result)
        assert "[Summary] Brief: answered first question" in all_content
        assert "Long detailed answer" not in all_content

    def test_output_is_list_of_dicts(self, runner, simple_conversation):
        """Output is a list of dictionaries with role and content."""
        result = runner.build_messages(simple_conversation, "test")

        assert isinstance(result, list)
        for msg in result:
            assert isinstance(msg, dict)
            assert "role" in msg
            assert "content" in msg
            assert msg["role"] in ("user", "assistant", "system")

    def test_role_mapping(self, runner):
        """Internal roles map to OpenAI roles correctly."""
        messages = [
            Message(role="user", content="user msg"),
            Message(role="assistant", content="assistant msg"),
            # Note: "tool" role messages would be mapped to "assistant" in current impl
        ]
        result = runner.build_messages(messages, "new")

        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"


# =============================================================================
# Cross-Backend Consistency Tests
# =============================================================================

class TestCrossBackendConsistency:
    """Tests ensuring both backends handle the same scenarios consistently."""

    @pytest.fixture
    def openai_runner(self):
        return OpenAICompatibleRunner(
            base_url="http://test",
            api_key="test",
            model="test-model",
        )

    def test_both_include_all_tool_uses(self, openai_runner, conversation_with_multiple_tools):
        """Both backends include all tool uses from conversation."""
        claude_result = ClaudeRunner.build_context(conversation_with_multiple_tools, "done")
        openai_result = openai_runner.build_messages(conversation_with_multiple_tools, "done")
        openai_content = " ".join(m.get("content", "") for m in openai_result)

        # Both should have both tool uses
        for tool_name in ["Glob", "Read"]:
            assert f"[Tool Use: {tool_name}]" in claude_result
            assert f"[Tool Use: {tool_name}]" in openai_content

    def test_both_respect_drop_mode(self, openai_runner, conversation_with_context_modes):
        """Both backends respect DROP context mode."""
        claude_result = ClaudeRunner.build_context(conversation_with_context_modes, "new")
        openai_result = openai_runner.build_messages(conversation_with_context_modes, "new")
        openai_content = " ".join(m.get("content", "") for m in openai_result)

        # Neither should have dropped content
        assert "Off-topic tangent" not in claude_result
        assert "Off-topic tangent" not in openai_content

    def test_both_use_summary_in_summarize_mode(self, openai_runner, conversation_with_context_modes):
        """Both backends use summary field in SUMMARIZE mode."""
        claude_result = ClaudeRunner.build_context(conversation_with_context_modes, "new")
        openai_result = openai_runner.build_messages(conversation_with_context_modes, "new")
        openai_content = " ".join(m.get("content", "") for m in openai_result)

        # Both should use summary
        assert "[Summary]" in claude_result
        assert "[Summary]" in openai_content

    def test_both_handle_tool_errors(self, openai_runner, conversation_with_tool_error):
        """Both backends format tool errors with [Error] marker."""
        claude_result = ClaudeRunner.build_context(conversation_with_tool_error, "next")
        openai_result = openai_runner.build_messages(conversation_with_tool_error, "next")
        openai_content = " ".join(m.get("content", "") for m in openai_result)

        # Both should have error marker
        assert "[Error]" in claude_result
        assert "[Error]" in openai_content


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def openai_runner(self):
        return OpenAICompatibleRunner(
            base_url="http://test",
            api_key="test",
            model="test-model",
        )

    def test_empty_content_blocks_fallback_to_content(self, openai_runner):
        """Empty content_blocks uses plain content field."""
        messages = [
            Message(role="user", content="plain text", content_blocks=[]),
        ]

        claude_result = ClaudeRunner.build_context(messages, "new")
        openai_result = openai_runner.build_messages(messages, "new")

        assert "plain text" in claude_result
        assert "plain text" in openai_result[0]["content"]

    def test_special_characters_in_content(self, openai_runner):
        """Special characters are preserved."""
        messages = [
            Message(role="user", content="Code: `x = 1`\nJSON: {\"a\": 1}"),
        ]

        claude_result = ClaudeRunner.build_context(messages, "new")
        openai_result = openai_runner.build_messages(messages, "new")

        assert '`x = 1`' in claude_result
        assert '{"a": 1}' in claude_result
        assert '`x = 1`' in openai_result[0]["content"]

    def test_very_long_tool_result(self, openai_runner):
        """Long tool results are included fully (truncation is display concern)."""
        long_content = "x" * 50000
        messages = [
            Message(
                role="assistant",
                content="",
                content_blocks=[
                    ToolResultBlock(tool_use_id="t1", content=long_content),
                ],
            ),
        ]

        claude_result = ClaudeRunner.build_context(messages, "new")
        openai_result = openai_runner.build_messages(messages, "new")

        assert long_content in claude_result
        assert long_content in openai_result[0]["content"]

    def test_unicode_content(self, openai_runner):
        """Unicode content is handled correctly."""
        messages = [
            Message(role="user", content="Hello  World "),
        ]

        claude_result = ClaudeRunner.build_context(messages, "new")
        openai_result = openai_runner.build_messages(messages, "new")

        assert "" in claude_result
        assert "" in openai_result[0]["content"]

    def test_nested_json_in_tool_input(self, openai_runner):
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

        claude_result = ClaudeRunner.build_context(messages, "new")
        openai_result = openai_runner.build_messages(messages, "new")

        # Both should have the nested structure serialized
        assert '"nested"' in claude_result
        assert '"deep"' in claude_result
        assert '"nested"' in openai_result[0]["content"]

    def test_newlines_in_tool_result(self, openai_runner):
        """Newlines in tool results are preserved."""
        messages = [
            Message(
                role="assistant",
                content="",
                content_blocks=[
                    ToolResultBlock(
                        tool_use_id="t1",
                        content="line1\nline2\nline3",
                    ),
                ],
            ),
        ]

        claude_result = ClaudeRunner.build_context(messages, "new")
        openai_result = openai_runner.build_messages(messages, "new")

        assert "line1\nline2\nline3" in claude_result
        assert "line1\nline2\nline3" in openai_result[0]["content"]
