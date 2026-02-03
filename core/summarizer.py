"""Summary generation for Balloons.

Handles LLM-based summarization of conversations, contexts, and merges.
Extracted from app.py to enable unit testing without the UI.
"""

from typing import Protocol

from models import Message, TextDelta
from session import Session
from core.context import ContextBuilder
from core.debug_log import debug_log


class StreamingRunner(Protocol):
    """Protocol for runners that can stream responses."""

    async def stream_response(
        self,
        messages: list[Message],
        prompt: str,
        disable_tools: bool = False,
    ):
        """Stream a response from the LLM."""
        ...


class Summarizer:
    """Generate summaries using an LLM runner.

    All methods are async and return plain strings.
    No UI dependencies - can be unit tested independently.

    Usage:
        summarizer = Summarizer(helper_runner)
        summary = await summarizer.generate_link_summary(messages, "focus on X")
    """

    def __init__(self, runner: StreamingRunner):
        """Initialize with a runner for LLM calls.

        Args:
            runner: A runner implementing stream_response (e.g., HelperRunner)
        """
        self._runner = runner
        self._context_builder = ContextBuilder()

    async def generate_link_summary(
        self, messages: list[Message], user_prompt: str = ""
    ) -> str:
        """Generate a summary of context for a link between sessions.

        Args:
            messages: The messages to summarize
            user_prompt: Optional user guidance for the summary

        Returns:
            Generated summary string, or fallback on error
        """
        # Build conversation context
        messages_text = []
        for msg in messages:
            role = "User" if msg.role == "user" else "Assistant"
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "..."
            messages_text.append(f"{role}: {content}")

        context_str = "\n\n".join(messages_text)

        summary_prompt = f"""Summarize the following conversation context in 1-3 concise sentences.
The summary will be used as a link reference between sessions.

{f"User guidance: {user_prompt}" if user_prompt else ""}

Conversation:
{context_str}

Provide a brief, informative summary:"""

        summary_parts = []
        try:
            async for event in self._runner.stream_response(
                [], summary_prompt, disable_tools=True
            ):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
        except Exception as e:
            debug_log.error(f"Link summary generation failed: {e}", category="link")
            return user_prompt or "Linked context"

        result = "".join(summary_parts)
        if result:
            return result.strip()
        else:
            return user_prompt or "Linked context"

    async def generate_context_summary(self, messages: list[Message]) -> str:
        """Generate a summary of messages for context compression.

        Args:
            messages: The messages to summarize

        Returns:
            Generated summary string, or error message with raw content on failure
        """
        if not messages:
            return ""

        summary_prompt = self._context_builder.build_context_summary_prompt(messages)

        summary_parts = []
        try:
            async for event in self._runner.stream_response([], summary_prompt):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
        except Exception as e:
            # Fall back to raw content
            context_parts = [
                f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}"
                for m in messages
            ]
            return f"Error generating summary: {e}\n\nRaw context:\n" + "\n\n".join(
                context_parts
            )

        return "".join(summary_parts) if summary_parts else ""

    async def generate_merge_summary(
        self, fork_session: Session, user_prompt: str = ""
    ) -> str:
        """Generate a summary of what was accomplished in a fork.

        Args:
            fork_session: The fork session to summarize
            user_prompt: Optional user guidance for the summary

        Returns:
            A concise summary of the fork's work
        """
        # Build conversation context from the fork
        messages_text = []
        for msg in fork_session.messages:
            role = "User" if msg.role == "user" else "Assistant"
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            messages_text.append(f"{role}: {content}")

        conversation = "\n\n".join(messages_text)

        # Build the summary prompt
        if user_prompt:
            summary_prompt = f"""Summarize the following conversation, focusing on: {user_prompt}

The summary should be 1-3 sentences describing what was accomplished or discovered.
Be specific about outcomes, not process.

Conversation:
{conversation}

Summary:"""
        else:
            summary_prompt = f"""Summarize the following conversation in 1-3 sentences.
Focus on what was accomplished or discovered, not the process.
Be specific about outcomes.

Conversation:
{conversation}

Summary:"""

        summary_parts = []
        try:
            async for event in self._runner.stream_response([], summary_prompt):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
        except Exception as e:
            return f"Merge completed (summary generation failed: {e})"

        return "".join(summary_parts).strip() if summary_parts else "Merge completed"

    async def generate_return_summary(
        self, messages: list[Message], return_prompt: str = ""
    ) -> str:
        """Generate a summary of selected messages for returning from a child session.

        Args:
            messages: Messages from child session to summarize
            return_prompt: Optional user-provided context for the summary

        Returns:
            Generated summary string, or error message with raw content on failure
        """
        if not messages:
            return ""

        prompt = self._context_builder.build_return_summary_prompt(
            messages, return_prompt
        )

        summary_parts = []
        try:
            async for event in self._runner.stream_response([], prompt):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
        except Exception as e:
            # Fall back to raw content
            context_parts = [
                f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}"
                for m in messages
            ]
            return f"Error generating summary: {e}\n\nRaw content:\n" + "\n\n".join(
                context_parts
            )

        return "".join(summary_parts) if summary_parts else ""
