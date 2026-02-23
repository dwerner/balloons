"""Context building for Balloons.

Handles building context from messages, summarization, and token counting.
Uses the same formatting logic as ClaudeRunner.build_message_content() to ensure
token counts are accurate.

This is the single source of truth for context formatting. ClaudeRunner delegates
to this module for building conversation context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from models import (
    Message, TextBlock, ToolUseBlock, ToolResultBlock, ArchiveBlock, ContextMode,
    ImageBlock, LinkBlock, InterruptionBlock, ErrorBlock,
)
from tokenizer import count_tokens


class OutputFormat(Enum):
    """Output format for context building."""
    # Structured content blocks for API calls (list[dict])
    STRUCTURED = "structured"
    # Plain text with XML tags (for display/debugging)
    TEXT = "text"
    # Plain text without XML wrapper (for token counting - matches structured content)
    TEXT_UNWRAPPED = "text_unwrapped"


@dataclass
class ContextResult:
    """Result of building context."""
    # For STRUCTURED format: list of content dicts
    # For TEXT formats: the text string
    content: list[dict] | str

    # Images collected from history (for STRUCTURED format)
    history_images: list[ImageBlock] = field(default_factory=list)

    # Token count (computed lazily)
    _token_count: int | None = None

    @property
    def token_count(self) -> int:
        """Get token count, computing if needed."""
        if self._token_count is None:
            if isinstance(self.content, str):
                self._token_count = count_tokens(self.content)
            else:
                # For structured content, convert to text for counting
                text_parts = []
                for block in self.content:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                self._token_count = count_tokens("\n".join(text_parts))
        return self._token_count

    def as_text(self) -> str:
        """Get content as text string."""
        if isinstance(self.content, str):
            return self.content
        # Convert structured to text
        text_parts = []
        for block in self.content:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        return "\n".join(text_parts)


class ContextBuilder:
    """Build context from message history with deferred execution.

    Uses a builder pattern where messages and options are accumulated,
    then build() produces the final output in the requested format.

    The formatting matches ClaudeRunner.build_message_content() exactly,
    ensuring token counts are accurate regardless of output format.

    Usage:
        builder = ContextBuilder()
        result = (builder
            .add_messages(messages)
            .set_prompt("new prompt")
            .build(OutputFormat.STRUCTURED))

        # Or for token counting:
        token_count = builder.add_messages(messages).count_tokens()
    """

    def __init__(self) -> None:
        self._messages: list[Message] = []
        self._prompt: str = ""
        self._images: list[ImageBlock] = []

    def add_messages(self, messages: list[Message]) -> ContextBuilder:
        """Add messages to the context.

        Args:
            messages: Messages to add (appended to existing)

        Returns:
            Self for chaining
        """
        self._messages.extend(messages)
        return self

    def add_message(self, message: Message) -> ContextBuilder:
        """Add a single message to the context.

        Args:
            message: Message to add

        Returns:
            Self for chaining
        """
        self._messages.append(message)
        return self

    def set_prompt(self, prompt: str) -> ContextBuilder:
        """Set the new user prompt.

        Args:
            prompt: The new prompt to append after history

        Returns:
            Self for chaining
        """
        self._prompt = prompt
        return self

    def add_images(self, images: list[ImageBlock]) -> ContextBuilder:
        """Add images for the current message.

        Args:
            images: Images to include with the prompt

        Returns:
            Self for chaining
        """
        self._images.extend(images)
        return self

    def clear(self) -> ContextBuilder:
        """Clear all accumulated state.

        Returns:
            Self for chaining
        """
        self._messages = []
        self._prompt = ""
        self._images = []
        return self

    def build(self, output_format: OutputFormat = OutputFormat.TEXT) -> ContextResult:
        """Build the context in the specified format.

        Args:
            output_format: The output format to produce

        Returns:
            ContextResult with the built content
        """
        history_parts: list[str] = []
        history_images: list[ImageBlock] = []

        for msg in self._messages:
            if msg.context_mode == ContextMode.DROP:
                continue

            # Handle system messages
            if msg.role == "system":
                self._process_system_message(msg, history_parts)
                continue

            # Use summary if in SUMMARIZE mode
            if msg.context_mode == ContextMode.SUMMARIZE and msg.summary:
                role_name = "user" if msg.role == "user" else "assistant"
                history_parts.append(f"<{role_name}>\n[Summary] {msg.summary}\n</{role_name}>")
                continue

            # Build content from blocks
            if msg.content_blocks:
                role_name = "user" if msg.role == "user" else "assistant"
                block_texts = []

                for block in msg.content_blocks:
                    block_text = self._format_block(block, history_images)
                    if block_text:
                        block_texts.append(block_text)

                if block_texts:
                    history_parts.append(f"<{role_name}>\n" + "\n\n".join(block_texts) + f"\n</{role_name}>")
            elif msg.content:
                role_name = "user" if msg.role == "user" else "assistant"
                history_parts.append(f"<{role_name}>\n{msg.content}\n</{role_name}>")

        # Build based on output format
        if output_format == OutputFormat.STRUCTURED:
            return self._build_structured(history_parts, history_images)
        elif output_format == OutputFormat.TEXT:
            return self._build_text(history_parts, wrap=True)
        else:  # TEXT_UNWRAPPED
            return self._build_text(history_parts, wrap=False)

    def _process_system_message(self, msg: Message, history_parts: list[str]) -> None:
        """Process a system message, appending to history_parts."""
        if msg.content_blocks:
            for block in msg.content_blocks:
                if isinstance(block, LinkBlock):
                    link_info = f"[Link: {block.linked_session_id[:8]}]"
                    if block.summary:
                        link_info += f" - {block.summary}"
                    history_parts.append(link_info)
                elif isinstance(block, ArchiveBlock):
                    archive_info = f"[Archived {block.message_count} turns: {block.summary}]"
                    archive_info += f"\n(Archive ID: {block.archive_id}, JSON path: {block.file_path})"
                    history_parts.append(archive_info)
                elif isinstance(block, TextBlock) and block.text:
                    history_parts.append(block.text)
        elif msg.content:
            history_parts.append(msg.content)

    def _format_block(self, block: Any, history_images: list[ImageBlock]) -> str | None:
        """Format a content block as text.

        Args:
            block: The content block to format
            history_images: List to append ImageBlocks to (side effect)

        Returns:
            Formatted text, or None if block produces no text (e.g., images)
        """
        # Use type attribute for duck-typing compatibility
        block_type = getattr(block, 'type', None)

        if block_type == 'text' or isinstance(block, TextBlock):
            if block.text:
                return block.text
            return None

        elif block_type == 'image' or isinstance(block, ImageBlock):
            # Collect images to add as proper content blocks
            history_images.append(block)
            return None

        elif block_type == 'tool_use' or isinstance(block, ToolUseBlock):
            input_str = json.dumps(block.input, indent=2)
            return f"<tool_use name=\"{block.name}\" id=\"{block.id}\">\n{input_str}\n</tool_use>"

        elif block_type == 'tool_result' or isinstance(block, ToolResultBlock):
            error_attr = ' error="true"' if getattr(block, 'is_error', False) else ''
            return f"<tool_result id=\"{block.tool_use_id}\"{error_attr}>\n{block.content}\n</tool_result>"

        elif block_type == 'interruption' or isinstance(block, InterruptionBlock):
            return f"[Response interrupted: {block.reason}]"

        elif block_type == 'error' or isinstance(block, ErrorBlock):
            error_info = f"[Response truncated: {block.reason}]"
            if block.partial_tool_name:
                error_info += f" (incomplete tool: {block.partial_tool_name})"
            return error_info

        elif block_type == 'link' or isinstance(block, LinkBlock):
            link_info = f"[Link: {block.linked_session_id[:8]}]"
            if block.summary:
                link_info += f" - {block.summary}"
            return link_info

        elif block_type == 'archive' or isinstance(block, ArchiveBlock):
            archive_info = f"[Archived {block.message_count} turns: {block.summary}]"
            archive_info += f"\n(Archive ID: {block.archive_id}, JSON path: {block.file_path})"
            return archive_info

        return None

    def _build_structured(
        self, history_parts: list[str], history_images: list[ImageBlock]
    ) -> ContextResult:
        """Build structured content blocks for API calls."""
        content: list[dict] = []

        # Add history as a single text block if we have any
        if history_parts:
            history_text = "<conversation_history>\n" + "\n\n".join(history_parts) + "\n</conversation_history>"
            content.append({"type": "text", "text": history_text})

        # Add images from history as proper content blocks
        for img_block in history_images:
            content.append({
                "type": "image",
                "source": {
                    "type": "url",
                    "url": f"file://{img_block.file_path}",
                }
            })

        # Add images for the current message
        for img_block in self._images:
            content.append({
                "type": "image",
                "source": {
                    "type": "url",
                    "url": f"file://{img_block.file_path}",
                }
            })

        # Add the new prompt
        if self._prompt:
            content.append({"type": "text", "text": self._prompt})

        return ContextResult(
            content=content,
            history_images=history_images + self._images,
        )

    def _build_text(self, history_parts: list[str], wrap: bool = True) -> ContextResult:
        """Build text output."""
        parts: list[str] = []

        if history_parts:
            if wrap:
                parts.append("<conversation_history>\n" + "\n\n".join(history_parts) + "\n</conversation_history>")
            else:
                parts.extend(history_parts)

        if self._prompt:
            parts.append(self._prompt)

        text = "\n\n".join(parts) if wrap else "\n\n".join(parts)
        return ContextResult(content=text)

    # Convenience methods for common operations

    def count_tokens(self) -> int:
        """Count tokens for the accumulated context.

        Returns:
            Token count
        """
        # Use TEXT_UNWRAPPED to get accurate count matching structured format
        result = self.build(OutputFormat.TEXT_UNWRAPPED)
        return result.token_count

    def build_context(self, messages: list[Message], new_prompt: str) -> str:
        """Build context string (legacy API).

        This method exists for backward compatibility. Prefer using the
        builder pattern directly for new code.

        Args:
            messages: Message history
            new_prompt: New user prompt

        Returns:
            Formatted context string
        """
        self.clear()
        self.add_messages(messages)
        self.set_prompt(new_prompt)
        result = self.build(OutputFormat.TEXT)
        return result.as_text()

    def build_message_content(
        self,
        messages: list[Message],
        new_prompt: str,
        images: list[ImageBlock] | None = None,
    ) -> list[dict]:
        """Build structured content blocks (for API calls).

        This produces the same output as ClaudeRunner.build_message_content().

        Args:
            messages: Message history
            new_prompt: New user prompt
            images: Optional images for the current message

        Returns:
            List of content blocks for the API
        """
        self.clear()
        self.add_messages(messages)
        self.set_prompt(new_prompt)
        if images:
            self.add_images(images)
        result = self.build(OutputFormat.STRUCTURED)
        return result.content  # type: ignore

    def count_messages_tokens(self, messages: list[Message]) -> int:
        """Count tokens for a list of messages (legacy API).

        Args:
            messages: Messages to count

        Returns:
            Token count
        """
        if not messages:
            return 0
        self.clear()
        self.add_messages(messages)
        return self.count_tokens()

    def count_turn_tokens(self, role: str, content_blocks: list) -> int:
        """Count tokens for a single turn.

        This is the single source of truth for turn token counting.

        Args:
            role: "user", "assistant", or "tool"
            content_blocks: List of content blocks

        Returns:
            Token count for this turn
        """
        if not content_blocks:
            return 0

        # Create a synthetic message to reuse formatting logic
        msg = Message(role=role, content="", content_blocks=content_blocks)

        self.clear()
        self.add_message(msg)
        return self.count_tokens()

    def build_context_summary_prompt(self, messages: list[Message]) -> str:
        """Build a prompt for summarizing context.

        Args:
            messages: Messages to summarize

        Returns:
            Prompt string for LLM summarization
        """
        # For summary prompts, we want plain readable text
        context_parts = []
        for msg in messages:
            prefix = "User" if msg.role == "user" else "Assistant"
            # Use content or extract from blocks
            if msg.content:
                context_parts.append(f"{prefix}: {msg.content}")
            elif msg.content_blocks:
                block_texts = []
                for block in msg.content_blocks:
                    if isinstance(block, TextBlock) and block.text:
                        block_texts.append(block.text)
                if block_texts:
                    context_parts.append(f"{prefix}: " + "\n".join(block_texts))

        context = "\n\n".join(context_parts)

        return f"""Summarize the following conversation context concisely, preserving key information, decisions, and any important technical details:

{context}

Provide a clear, actionable summary that can be used as context for continuing this work."""

    def build_return_summary_prompt(self, messages: list[Message], return_prompt: str = "") -> str:
        """Build a prompt for generating return summary.

        Args:
            messages: Messages from child session
            return_prompt: Optional user-provided return message

        Returns:
            Prompt string for LLM return summarization
        """
        context_parts = []
        for msg in messages:
            prefix = "User" if msg.role == "user" else "Assistant"
            if msg.content:
                context_parts.append(f"{prefix}: {msg.content}")
            elif msg.content_blocks:
                block_texts = []
                for block in msg.content_blocks:
                    if isinstance(block, TextBlock) and block.text:
                        block_texts.append(block.text)
                if block_texts:
                    context_parts.append(f"{prefix}: " + "\n".join(block_texts))

        context = "\n\n".join(context_parts)

        if return_prompt:
            return f"{return_prompt}\n\nContext:\n{context}"
        else:
            return f"Summarize the key findings and conclusions from this conversation:\n\n{context}"
