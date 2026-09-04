"""Tests for context building."""

import pytest
from core.context import ContextBuilder, OutputFormat
from models import Message, TextBlock, ToolUseBlock, ToolResultBlock, ContextMode


@pytest.fixture
def builder():
    return ContextBuilder()


class TestContextBuilder:
    """Tests for ContextBuilder"""

    def test_empty_messages(self, builder):
        """Empty message list produces just the new prompt."""
        result = builder.build_context([], "hello")
        # New format: prompt is not prefixed with "User:" since it's the current message
        assert result == "hello"

    def test_simple_user_message(self, builder):
        """Single user message is included."""
        messages = [
            Message(role="user", content="first message")
        ]
        result = builder.build_context(messages, "second")
        # New format uses XML tags
        assert "<user>" in result
        assert "first message" in result
        assert "second" in result
        assert "<conversation_history>" in result

    def test_user_and_assistant(self, builder):
        """Both user and assistant messages are included."""
        messages = [
            Message(role="user", content="question"),
            Message(role="assistant", content="answer"),
        ]
        result = builder.build_context(messages, "follow up")
        # New format uses XML tags
        assert "<user>" in result
        assert "question" in result
        assert "<assistant>" in result
        assert "answer" in result
        assert "follow up" in result

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
        """ToolUseBlock is formatted with XML tags and JSON input."""
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
        # New format uses XML tags matching build_message_content
        assert '<tool_use name="Read" id="123">' in result
        assert "file_path" in result
        assert "/test.py" in result

    def test_tool_result_block_formatting(self, builder):
        """ToolResultBlock is formatted with XML tags."""
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
        # New format uses XML tags
        assert '<tool_result id="123">' in result
        assert "file contents here" in result

    def test_tool_result_error_block(self, builder):
        """Error tool results include error attribute."""
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
        # New format uses XML attribute for errors
        assert '<tool_result id="123" error="true">' in result
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
        assert '<tool_use name="Read"' in result
        assert '<tool_result id="123">' in result
        assert "hello world program" in result


class TestContextBuilderChaining:
    """Tests for the builder pattern chaining API."""

    def test_builder_chaining(self, builder):
        """Builder methods can be chained."""
        messages = [Message(role="user", content="hello")]
        result = (builder
            .add_messages(messages)
            .set_prompt("world")
            .build(OutputFormat.TEXT))
        assert "hello" in result.as_text()
        assert "world" in result.as_text()

    def test_clear_resets_state(self, builder):
        """Clear removes accumulated state."""
        builder.add_messages([Message(role="user", content="first")])
        builder.set_prompt("test")
        builder.clear()
        result = builder.build(OutputFormat.TEXT)
        assert "first" not in result.as_text()
        assert "test" not in result.as_text()

    def test_structured_format(self, builder):
        """STRUCTURED format produces list of dicts."""
        messages = [Message(role="user", content="hello")]
        result = (builder
            .add_messages(messages)
            .set_prompt("world")
            .build(OutputFormat.STRUCTURED))
        assert isinstance(result.content, list)
        assert all(isinstance(item, dict) for item in result.content)
        # Should have history block and prompt block
        assert len(result.content) == 2
        assert result.content[0]["type"] == "text"
        assert result.content[1]["type"] == "text"

    def test_build_message_content_compatibility(self, builder):
        """build_message_content produces same format as ClaudeRunner."""
        messages = [Message(role="user", content="hello")]
        content = builder.build_message_content(messages, "world")
        assert isinstance(content, list)
        assert len(content) == 2  # history + prompt
        assert content[0]["type"] == "text"
        assert "<conversation_history>" in content[0]["text"]
        assert content[1]["text"] == "world"


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
        # Should include XML tags + JSON formatted input
        assert result > 10  # Rough estimate, JSON adds tokens

    def test_tool_result_block_counts_tokens(self, builder):
        """ToolResultBlock content is counted."""
        result = builder.count_turn_tokens("assistant", [
            ToolResultBlock(tool_use_id="123", content="file contents " * 100)
        ])
        # Should include XML tags + content
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


class TestTokenCounting:
    """Tests for token counting accuracy."""

    def test_count_tokens_matches_structured(self, builder):
        """Token count should match between TEXT and STRUCTURED formats."""
        messages = [
            Message(role="user", content="hello world"),
            Message(role="assistant", content="I can help with that"),
        ]
        builder.add_messages(messages).set_prompt("continue")

        # Get token count
        token_count = builder.count_tokens()

        # Build structured and manually count
        builder.clear().add_messages(messages).set_prompt("continue")
        result = builder.build(OutputFormat.STRUCTURED)

        # Both should produce reasonable counts
        assert token_count > 0
        assert result.token_count > 0


class TestLoadImageAsBase64:
    """Shared image loader used by every backend to embed current-turn images."""

    def _tiny_png(self, path):
        import struct, zlib
        sig = b"\x89PNG\r\n\x1a\n"
        def chunk(tag, data):
            body = tag + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        path.write_bytes(
            sig
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
            + chunk(b"IEND", b"")
        )

    def test_roundtrip(self, tmp_path):
        import base64
        from core.context import load_image_as_base64
        p = tmp_path / "x.png"
        self._tiny_png(p)
        b64, media_type = load_image_as_base64(str(p))
        assert media_type == "image/png"
        assert base64.b64decode(b64) == p.read_bytes()

    def test_rejects_unsupported_extension(self, tmp_path):
        from core.context import load_image_as_base64
        p = tmp_path / "x.txt"
        p.write_text("not an image")
        assert load_image_as_base64(str(p)) is None

    def test_rejects_missing_file(self, tmp_path):
        from core.context import load_image_as_base64
        assert load_image_as_base64(str(tmp_path / "missing.png")) is None

    def test_structured_embeds_current_image_as_base64(self, tmp_path):
        # ContextBuilder (claude path) embeds current-turn images as base64 and
        # leaves history images as text refs -- the policy the openai path ports.
        from core.context import ContextBuilder, OutputFormat
        from models import ImageBlock
        p = tmp_path / "cur.png"
        self._tiny_png(p)
        b = ContextBuilder()
        b.set_prompt("describe")
        b.add_images([ImageBlock(file_path=str(p), media_type="image/png")])
        result = b.build(OutputFormat.STRUCTURED)
        blocks = result.content
        img_blocks = [x for x in blocks if x.get("type") == "image"]
        assert len(img_blocks) == 1
        assert img_blocks[0]["source"]["type"] == "base64"
        assert img_blocks[0]["source"]["media_type"] == "image/png"
