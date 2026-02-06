"""Tests for context building."""

import pytest
from core.context import ContextBuilder
from models import Message, TextBlock, ToolUseBlock, ToolResultBlock, ContextMode


@pytest.fixture
def builder():
    return ContextBuilder()


class TestContextBuilder:
    """Tests for ContextBuilder"""

    def test_empty_messages(self, builder):
        """Empty message list produces just the new prompt."""
        result = builder.build_context([], "hello")
        assert result == "User: hello"

    def test_simple_user_message(self, builder):
        """Single user message is included."""
        messages = [
            Message(role="user", content="first message")
        ]
        result = builder.build_context(messages, "second")
        assert "User: first message" in result
        assert "User: second" in result

    def test_user_and_assistant(self, builder):
        """Both user and assistant messages are included."""
        messages = [
            Message(role="user", content="question"),
            Message(role="assistant", content="answer"),
        ]
        result = builder.build_context(messages, "follow up")
        assert "User: question" in result
        assert "Assistant: answer" in result
        assert "User: follow up" in result

    def test_drop_mode_excludes_message(self, builder):
        """Messages with DROP context_mode are excluded."""
        messages = [
            Message(role="user", content="keep this"),
            Message(role="user", content="drop this", context_mode=ContextMode.DROP),
            Message(role="user", content="keep this too"),
        ]
        result = builder.build_context(messages, "new")
        assert "keep this" in result
        assert "drop this" not in result
        assert "keep this too" in result

    def test_summarize_mode_uses_summary(self, builder):
        """Messages with SUMMARIZE mode use the summary field."""
        messages = [
            Message(
                role="user",
                content="long original content here",
                context_mode=ContextMode.SUMMARIZE,
                summary="short summary",
            ),
        ]
        result = builder.build_context(messages, "new")
        assert "[Summary] short summary" in result
        assert "long original content" not in result

    def test_summarize_mode_without_summary_uses_content(self, builder):
        """SUMMARIZE mode without summary falls back to content."""
        messages = [
            Message(
                role="user",
                content="original content",
                context_mode=ContextMode.SUMMARIZE,
                summary="",  # Empty summary
            ),
        ]
        result = builder.build_context(messages, "new")
        assert "original content" in result

    def test_tool_use_block_formatting(self, builder):
        """ToolUseBlock is formatted with tool name and JSON input."""
        messages = [
            Message(
                role="assistant",
                content="",
                content_blocks=[
                    ToolUseBlock(id="123", name="Read", input={"file_path": "/test.py"})
                ],
            ),
        ]
        result = builder.build_context(messages, "new")
        assert "[Tool Use: Read]" in result
        assert "file_path" in result
        assert "/test.py" in result

    def test_tool_result_block_formatting(self, builder):
        """ToolResultBlock is formatted with result content."""
        messages = [
            Message(
                role="assistant",
                content="",
                content_blocks=[
                    ToolResultBlock(tool_use_id="123", content="file contents here")
                ],
            ),
        ]
        result = builder.build_context(messages, "new")
        assert "[Tool Result]" in result
        assert "file contents here" in result

    def test_tool_result_error_block(self, builder):
        """Error tool results include [Error] prefix."""
        messages = [
            Message(
                role="assistant",
                content="",
                content_blocks=[
                    ToolResultBlock(tool_use_id="123", content="file not found", is_error=True)
                ],
            ),
        ]
        result = builder.build_context(messages, "new")
        assert "[Tool Result][Error]" in result
        assert "file not found" in result

    def test_long_tool_result_included_fully(self, builder):
        """Tool results are included fully (truncation done elsewhere if needed)."""
        long_content = "x" * 15000
        messages = [
            Message(
                role="assistant",
                content="",
                content_blocks=[
                    ToolResultBlock(tool_use_id="123", content=long_content)
                ],
            ),
        ]
        result = builder.build_context(messages, "new")
        # Full content is included - truncation is handled at display/save layer
        assert long_content in result

    def test_mixed_content_blocks(self, builder):
        """Mixed text, tool use, and tool result blocks are all included."""
        messages = [
            Message(
                role="assistant",
                content="",
                content_blocks=[
                    TextBlock(text="Let me check that file"),
                    ToolUseBlock(id="123", name="Read", input={"file_path": "/test.py"}),
                    ToolResultBlock(tool_use_id="123", content="print('hello')"),
                    TextBlock(text="The file contains a hello world program"),
                ],
            ),
        ]
        result = builder.build_context(messages, "new")
        assert "Let me check that file" in result
        assert "[Tool Use: Read]" in result
        assert "[Tool Result]" in result
        assert "hello world program" in result


class TestContextSummaryPrompt:
    """Tests for :with context summarization."""

    def test_build_context_summary_prompt(self, builder):
        """Context summary prompt includes all messages."""
        messages = [
            Message(role="user", content="do something"),
            Message(role="assistant", content="done"),
        ]
        result = builder.build_context_summary_prompt(messages)
        assert "User: do something" in result
        assert "Assistant: done" in result
        assert "Summarize" in result


class TestReturnSummaryPrompt:
    """Tests for :return summary generation."""

    def test_build_return_summary_prompt_no_message(self, builder):
        """Without return prompt, generates generic summary request."""
        messages = [
            Message(role="user", content="question"),
            Message(role="assistant", content="answer"),
        ]
        result = builder.build_return_summary_prompt(messages)
        assert "Summarize the key findings" in result
        assert "question" in result
        assert "answer" in result

    def test_build_return_summary_prompt_with_message(self, builder):
        """With return prompt, uses it as prefix."""
        messages = [
            Message(role="user", content="question"),
        ]
        result = builder.build_return_summary_prompt(messages, "Custom instruction")
        assert "Custom instruction" in result
        assert "Context:" in result


class TestCountTurnTokens:
    """Tests for count_turn_tokens - single source of truth for turn token counting."""

    def test_empty_blocks_returns_zero(self, builder):
        """Empty content blocks returns 0 tokens."""
        result = builder.count_turn_tokens("user", [])
        assert result == 0

    def test_text_block_counts_tokens(self, builder):
        """TextBlock content is counted."""
        result = builder.count_turn_tokens("user", [TextBlock(text="hello world")])
        assert result > 0

    def test_tool_use_block_counts_tokens(self, builder):
        """ToolUseBlock with JSON input is counted."""
        result = builder.count_turn_tokens("assistant", [
            ToolUseBlock(id="123", name="Read", input={"file_path": "/very/long/path/to/file.py"})
        ])
        # Should include "[Tool Use: Read]\n" + JSON formatted input
        assert result > 10  # Rough estimate, JSON adds tokens

    def test_tool_result_block_counts_tokens(self, builder):
        """ToolResultBlock content is counted."""
        result = builder.count_turn_tokens("assistant", [
            ToolResultBlock(tool_use_id="123", content="file contents " * 100)
        ])
        # Should include "[Tool Result]\n" + content
        assert result > 50  # Lots of content

    def test_multiple_blocks_sum_correctly(self, builder):
        """Multiple blocks are all counted."""
        blocks = [
            TextBlock(text="Thinking about this"),
            ToolUseBlock(id="123", name="Read", input={"file_path": "/test.py"}),
            ToolResultBlock(tool_use_id="123", content="print('hello')"),
        ]
        result = builder.count_turn_tokens("assistant", blocks)
        # Count individual blocks to verify they're all included
        text_only = builder.count_turn_tokens("assistant", [blocks[0]])
        tool_use_only = builder.count_turn_tokens("assistant", [blocks[1]])
        tool_result_only = builder.count_turn_tokens("assistant", [blocks[2]])
        # Combined should be roughly the sum (with some overhead from role prefix being counted once)
        assert result > text_only
        assert result > tool_use_only
        assert result > tool_result_only
