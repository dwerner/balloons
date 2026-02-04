"""Summary generation for Balloons.

Handles LLM-based summarization of conversations, contexts, and merges.
Extracted from app.py to enable unit testing without the UI.
"""

from typing import Protocol

from models import Message, TextDelta, ArchiveSummary
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
        turns_text = []
        for turn in fork_session.turns:
            role = "User" if turn.role == "user" else "Assistant"
            content = turn.content if isinstance(turn.content, str) else str(turn.content)
            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            turns_text.append(f"{role}: {content}")

        conversation = "\n\n".join(turns_text)

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

    async def generate_archive_summary(
        self, messages: list[Message], user_hint: str = ""
    ) -> ArchiveSummary:
        """Generate a structured summary of messages for archiving.

        Args:
            messages: Messages to summarize for archiving
            user_hint: Optional user hint for what to focus on

        Returns:
            ArchiveSummary with structured information about the archived content
        """
        if not messages:
            return ArchiveSummary()

        # Build conversation context
        messages_text = []
        for msg in messages:
            role = "User" if msg.role == "user" else "Assistant"
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            turns_text.append(f"{role}: {content}")

        conversation = "\n\n".join(turns_text)

        # Build the structured summary prompt
        hint_section = f"\nUser hint: {user_hint}\n" if user_hint else ""

        summary_prompt = f"""Analyze this conversation segment and provide a structured summary.
{hint_section}
Respond in EXACTLY this format (keep field names exactly as shown):

FILES_MODIFIED:
- file1.py (action)
- file2.py (action)

WORK_DONE:
1-3 sentences describing what was accomplished.

KEY_DECISIONS:
- Decision 1
- Decision 2

If no files were modified, write "None" for FILES_MODIFIED.
If no key decisions, write "None" for KEY_DECISIONS.

Conversation:
{conversation}

Structured summary:"""

        response_parts = []
        try:
            async for event in self._runner.stream_response(
                [], summary_prompt, disable_tools=True
            ):
                if isinstance(event, TextDelta):
                    response_parts.append(event.text)
        except Exception as e:
            debug_log.error(f"Archive summary generation failed: {e}", category="archive")
            # Return a basic summary on error
            return ArchiveSummary(
                work_done=f"Archived {len(messages)} turns" + (f" ({user_hint})" if user_hint else "")
            )

        response = "".join(response_parts)
        return self._parse_archive_summary(response, len(messages), user_hint)

    def _parse_archive_summary(
        self, response: str, message_count: int, user_hint: str
    ) -> ArchiveSummary:
        """Parse the LLM response into an ArchiveSummary."""
        files_modified = []
        work_done = ""
        key_decisions = []

        current_section = None
        lines = response.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Detect section headers
            if line.upper().startswith("FILES_MODIFIED"):
                current_section = "files"
                continue
            elif line.upper().startswith("WORK_DONE"):
                current_section = "work"
                continue
            elif line.upper().startswith("KEY_DECISIONS"):
                current_section = "decisions"
                continue

            # Parse content based on current section
            if current_section == "files":
                if line.startswith("-"):
                    file_entry = line[1:].strip()
                    if file_entry.lower() != "none":
                        files_modified.append(file_entry)
            elif current_section == "work":
                if line.lower() != "none":
                    if work_done:
                        work_done += " " + line
                    else:
                        work_done = line
            elif current_section == "decisions":
                if line.startswith("-"):
                    decision = line[1:].strip()
                    if decision.lower() != "none":
                        key_decisions.append(decision)

        # Fallback if parsing failed
        if not work_done:
            work_done = f"Archived {message_count} turns" + (f" ({user_hint})" if user_hint else "")

        return ArchiveSummary(
            files_modified=files_modified,
            work_done=work_done,
            key_decisions=key_decisions,
        )
