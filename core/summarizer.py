"""Summary generation for Balloons.

Handles LLM-based summarization of conversations, contexts, and merges.
Extracted from app.py to enable unit testing without the UI.
"""

import uuid
from pathlib import Path
from typing import Protocol, Optional

import aiofiles

from models import Message, TextDelta, ArchiveSummary
from session import Session
from core.context import ContextBuilder
from core.debug_log import debug_log
from core.task_state import get_task_state, TaskType, TaskStatus

# Load link summary prompt from file
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_LINK_SUMMARY_PROMPT_PATH = _PROMPTS_DIR / "link-summary.md"

_DEFAULT_LINK_SUMMARY_PROMPT = """Summarize this conversation in one sentence (max 100 chars).
Be specific about what was built, fixed, or discussed.

Conversation:
{conversation}

Summary:"""


def _load_link_summary_prompt() -> str:
    """Load the link summary prompt from file."""
    try:
        return _LINK_SUMMARY_PROMPT_PATH.read_text()
    except Exception:
        return _DEFAULT_LINK_SUMMARY_PROMPT


async def _load_link_summary_prompt_async() -> str:
    """Async version of _load_link_summary_prompt()."""
    try:
        async with aiofiles.open(_LINK_SUMMARY_PROMPT_PATH, encoding="utf-8") as f:
            return await f.read()
    except Exception:
        return _DEFAULT_LINK_SUMMARY_PROMPT


_LINK_SUMMARY_PROMPT = _load_link_summary_prompt()


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
        summary = await summarizer.generate_session_summary(session, "focus on X")
    """

    def __init__(self, runner: StreamingRunner, session_id: Optional[str] = None, backend_name: str = ""):
        """Initialize with a runner for LLM calls.

        Args:
            runner: A runner implementing stream_response (e.g., HelperRunner)
            session_id: Optional session ID for task tracking
            backend_name: Name of backend (for task display)
        """
        self._runner = runner
        self._context_builder = ContextBuilder()
        self._session_id = session_id
        self._backend_name = backend_name

    def set_session_id(self, session_id: str) -> None:
        """Update the session ID for task tracking."""
        self._session_id = session_id

    def _register_task(self, task_type: TaskType, prompt: str) -> str:
        """Register a helper task with TaskState, returns task_id."""
        task_id = str(uuid.uuid4())
        get_task_state().register_helper_task(
            task_id=task_id,
            task_type=task_type,
            prompt=prompt,
            session_id=self._session_id,
            backend_name=self._backend_name,
        )
        return task_id

    def _complete_task(self, task_id: str) -> None:
        """Mark a task as completed."""
        get_task_state().complete_task(task_id)

    def _fail_task(self, task_id: str, error: str) -> None:
        """Mark a task as failed."""
        get_task_state().fail_task(task_id, error)

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
        task_id = self._register_task(TaskType.COMPRESSION, f"Compressing {len(messages)} messages")

        summary_parts = []
        try:
            async for event in self._runner.stream_response([], summary_prompt):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
            self._complete_task(task_id)
        except Exception as e:
            self._fail_task(task_id, str(e))
            # Fall back to raw content
            context_parts = [
                f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}"
                for m in messages
            ]
            return f"Error generating summary: {e}\n\nRaw context:\n" + "\n\n".join(
                context_parts
            )

        return "".join(summary_parts) if summary_parts else ""

    async def generate_session_summary(self, session: Session) -> str:
        """Generate a summary of a session's conversation for linking.

        Uses the link-summary.md prompt to generate a short, specific summary.

        Note: This always generates a new summary. Callers should check
        session.summary first if they want to reuse existing summaries.

        Args:
            session: The session to summarize

        Returns:
            A concise summary of the session's content (max ~100 chars)
        """
        # Build conversation context from the session
        turns_text = []
        for turn in session.turns:
            role = "User" if turn.role == "user" else "Assistant"
            content = turn.content if isinstance(turn.content, str) else str(turn.content)
            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            turns_text.append(f"{role}: {content}")

        if not turns_text:
            return session.title or "Empty session"

        conversation = "\n\n".join(turns_text)

        # Use the prompt template from file
        summary_prompt = _LINK_SUMMARY_PROMPT.format(conversation=conversation)
        task_id = self._register_task(TaskType.LINK_SUMMARY, f"Summarizing session: {session.title or session.id[:8]}")

        summary_parts = []
        try:
            async for event in self._runner.stream_response(
                [], summary_prompt, disable_tools=True
            ):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
            self._complete_task(task_id)
        except Exception as e:
            self._fail_task(task_id, str(e))
            debug_log.error(f"Session summary generation failed: {e}", category="link")
            return session.title or "Session"

        result = "".join(summary_parts).strip()
        return result if result else (session.title or "Session")

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

        task_id = self._register_task(TaskType.MERGE_SUMMARY, f"Summarizing merge: {fork_session.title or fork_session.id[:8]}")

        summary_parts = []
        try:
            async for event in self._runner.stream_response([], summary_prompt):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
            self._complete_task(task_id)
        except Exception as e:
            self._fail_task(task_id, str(e))
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

        task_id = self._register_task(TaskType.COMPRESSION, f"Summarizing return ({len(messages)} messages)")

        summary_parts = []
        try:
            async for event in self._runner.stream_response([], prompt):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
            self._complete_task(task_id)
        except Exception as e:
            self._fail_task(task_id, str(e))
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
        turns_text = []
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

        task_id = self._register_task(TaskType.ARCHIVE_SUMMARY, f"Summarizing archive ({len(messages)} turns)")

        response_parts = []
        try:
            async for event in self._runner.stream_response(
                [], summary_prompt, disable_tools=True
            ):
                if isinstance(event, TextDelta):
                    response_parts.append(event.text)
            self._complete_task(task_id)
        except Exception as e:
            self._fail_task(task_id, str(e))
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
