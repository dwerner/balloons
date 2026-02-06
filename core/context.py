"""Context building for Balloons.

Handles building context from messages, summarization, and token counting.
Extracted from app.py and claude_runner.py.
"""

import json
from typing import Optional

from models import Message, TextBlock, ToolUseBlock, ToolResultBlock, ArchiveBlock, ContextMode
from tokenizer import count_tokens


class ContextBuilder:
    """Build context strings from message history.

    Usage:
        builder = ContextBuilder()
        context = builder.build_context(messages, "new prompt")
        token_count = builder.count_tokens(context)
    """

    def build_context(self, messages: list[Message], new_prompt: str) -> str:
        """Build the full context string from message history + new prompt.

        Reconstructs tool calls and results so Claude has proper context.
        Respects ContextMode for each message (copy, summarize, drop).

        Args:
            messages: List of messages from session history
            new_prompt: The new user prompt to append

        Returns:
            Formatted context string ready to send to Claude
        """
        parts = []
        for msg in messages:
            # Respect context mode
            if msg.context_mode == ContextMode.DROP:
                continue

            prefix = "User" if msg.role == "user" else "Assistant"

            # Use summary if in SUMMARIZE mode and summary exists
            if msg.context_mode == ContextMode.SUMMARIZE and msg.summary:
                parts.append(f"{prefix}: [Summary] {msg.summary}")
                continue

            # Build content from blocks if available
            if msg.content_blocks:
                block_parts = []
                for block in msg.content_blocks:
                    # Use type attribute for duck-typing compatibility
                    block_type = getattr(block, 'type', None)
                    if block_type == 'text' or isinstance(block, TextBlock):
                        if block.text:
                            block_parts.append(block.text)
                    elif block_type == 'tool_use' or isinstance(block, ToolUseBlock):
                        # Format tool use so Claude knows what it did
                        input_str = json.dumps(block.input, indent=2)
                        block_parts.append(f"[Tool Use: {block.name}]\n{input_str}")
                    elif block_type == 'tool_result' or isinstance(block, ToolResultBlock):
                        # Format tool result so Claude sees what the tool returned
                        error_prefix = "[Error] " if getattr(block, 'is_error', False) else ""
                        block_parts.append(f"[Tool Result]{error_prefix}\n{block.content}")
                    elif block_type == 'archive' or isinstance(block, ArchiveBlock):
                        # Format archive as a summary reference with archive_id for retrieval
                        block_parts.append(
                            f"[Archived {block.message_count} turns: {block.summary}]\n"
                            f"(Archive ID: {block.archive_id}, JSON path: {block.file_path})"
                        )

                if block_parts:
                    parts.append(f"{prefix}: " + "\n\n".join(block_parts))
            else:
                # Fallback to plain content
                parts.append(f"{prefix}: {msg.content}")

        parts.append(f"User: {new_prompt}")
        return "\n\n".join(parts)

    def build_context_summary_prompt(self, messages: list[Message]) -> str:
        """Build a prompt for summarizing context for :with command.

        Args:
            messages: Messages marked for summarization

        Returns:
            Prompt string for LLM context summarization
        """
        context_parts = []
        for msg in messages:
            prefix = "User" if msg.role == "user" else "Assistant"
            context_parts.append(f"{prefix}: {msg.content}")
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
            context_parts.append(f"{prefix}: {msg.content}")
        context = "\n\n".join(context_parts)

        if return_prompt:
            return f"{return_prompt}\n\nContext:\n{context}"
        else:
            return f"Summarize the key findings and conclusions from this conversation:\n\n{context}"

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken.

        Args:
            text: Text to count tokens for

        Returns:
            Approximate token count
        """
        return count_tokens(text)

    def count_messages_tokens(self, messages: list[Message]) -> int:
        """Count tokens for a list of messages.

        Args:
            messages: Messages to count tokens for

        Returns:
            Total token count
        """
        # Build a pseudo-context to get accurate count
        if not messages:
            return 0
        context = self.build_context(messages, "")
        return self.count_tokens(context)

    def count_turn_tokens(self, role: str, content_blocks: list) -> int:
        """Count tokens for a single turn from its content blocks.

        This is the single source of truth for turn token counting.
        Uses the same formatting as build_context() so counts are accurate.

        Args:
            role: "user" or "assistant"
            content_blocks: List of content blocks (TextBlock, ToolUseBlock, etc.)

        Returns:
            Token count for this turn
        """
        if not content_blocks:
            return 0

        prefix = "User" if role == "user" else "Assistant"
        block_parts = []

        for block in content_blocks:
            # Use type attribute for duck-typing compatibility
            block_type = getattr(block, 'type', None)
            if block_type == 'text' or isinstance(block, TextBlock):
                if block.text:
                    block_parts.append(block.text)
            elif block_type == 'tool_use' or isinstance(block, ToolUseBlock):
                input_str = json.dumps(block.input, indent=2)
                block_parts.append(f"[Tool Use: {block.name}]\n{input_str}")
            elif block_type == 'tool_result' or isinstance(block, ToolResultBlock):
                error_prefix = "[Error] " if getattr(block, 'is_error', False) else ""
                block_parts.append(f"[Tool Result]{error_prefix}\n{block.content}")
            elif block_type == 'archive' or isinstance(block, ArchiveBlock):
                block_parts.append(
                    f"[Archived {block.message_count} turns: {block.summary}]\n"
                    f"(Archive ID: {block.archive_id}, JSON path: {block.file_path})"
                )

        if not block_parts:
            return 0

        full_content = f"{prefix}: " + "\n\n".join(block_parts)
        return self.count_tokens(full_content)
