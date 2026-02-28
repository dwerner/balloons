"""Summary generation for Balloons.

Handles LLM-based summarization of conversations, contexts, and merges.
Extracted from app.py to enable unit testing without the UI.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Protocol, Optional

import aiofiles

from models import Message, TextDelta, ArchiveSummary, SessionSummaryBlock
from session import Session
from core.context import ContextBuilder
from core.debug_log import debug_log, Category
from core.stream_state import get_stream_state, StreamType, StreamStatus

# Load prompts from files
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_LINK_SUMMARY_PROMPT_PATH = _PROMPTS_DIR / "link-summary.md"
_SESSION_REVIEW_PROMPT_PATH = _PROMPTS_DIR / "session-review.md"

_DEFAULT_LINK_SUMMARY_PROMPT = """Summarize this conversation in one sentence (max 100 chars).
Be specific about what was built, fixed, or discussed.

Conversation:
{conversation}

Summary:"""

_DEFAULT_SESSION_REVIEW_PROMPT = """Analyze this conversation and provide a structured session review.

Respond in EXACTLY this format (keep field names exactly as shown):

PROPOSED_TITLE:
A concise, descriptive title for this session (max 50 chars)

FILES_MODIFIED:
- file1.py (created)

DECISIONS_MADE:
- Decision 1

WORK_DONE:
1-3 sentences describing what was accomplished.

NEXT_STEPS:
- Unfinished item 1

QUESTIONS_RAISED:
- Open question

Conversation:
{conversation}

Session review:"""


def _load_link_summary_prompt() -> str:
    """Load the link summary prompt from file."""
    try:
        return _LINK_SUMMARY_PROMPT_PATH.read_text()
    except Exception:
        return _DEFAULT_LINK_SUMMARY_PROMPT


def _load_session_review_prompt() -> str:
    """Load the session review prompt from file."""
    try:
        return _SESSION_REVIEW_PROMPT_PATH.read_text()
    except Exception:
        return _DEFAULT_SESSION_REVIEW_PROMPT


async def _load_link_summary_prompt_async() -> str:
    """Async version of _load_link_summary_prompt()."""
    try:
        async with aiofiles.open(_LINK_SUMMARY_PROMPT_PATH, encoding="utf-8") as f:
            return await f.read()
    except Exception:
        return _DEFAULT_LINK_SUMMARY_PROMPT


_LINK_SUMMARY_PROMPT = _load_link_summary_prompt()
_SESSION_REVIEW_PROMPT = _load_session_review_prompt()


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

    def _register_stream(self, stream_type: StreamType, prompt: str) -> str:
        """Register a helper stream with StreamState, returns stream_id."""
        stream_id = str(uuid.uuid4())
        get_stream_state().register_helper_stream(
            stream_id=stream_id,
            stream_type=stream_type,
            prompt=prompt,
            session_id=self._session_id,
            backend_name=self._backend_name,
        )
        return stream_id

    def _complete_stream(self, stream_id: str) -> None:
        """Mark a stream as completed."""
        get_stream_state().complete_stream(stream_id)

    def _fail_stream(self, stream_id: str, error: str) -> None:
        """Mark a stream as failed."""
        get_stream_state().fail_stream(stream_id, error)

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
        stream_id = self._register_stream(StreamType.COMPRESSION, f"Compressing {len(messages)} messages")

        summary_parts = []
        try:
            async for event in self._runner.stream_response([], summary_prompt):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
            self._complete_stream(stream_id)
        except Exception as e:
            self._fail_stream(stream_id, str(e))
            # Fall back to raw content
            context_parts = [
                f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}"
                for m in messages
            ]
            return f"Error generating summary: {e}\n\nRaw context:\n" + "\n\n".join(
                context_parts
            )

        return "".join(summary_parts) if summary_parts else ""

    def build_session_summary_prompt(self, session: Session) -> str | None:
        """Build the prompt for session (link) summary generation.

        This is separate from generate_session_summary() to support
        non-blocking helper runner streaming.

        Args:
            session: The session to summarize

        Returns:
            The prompt string, or None if session is empty
        """
        # Build conversation context from the session
        turns_text = []
        for turn in session.turns:
            role = "User" if turn.role == "user" else "Assistant"
            content = turn.content if isinstance(turn.content, str) else str(turn.content)
            # DON'T Truncate very long messages
            turns_text.append(f"{role}: {content}")

        if not turns_text:
            return None

        conversation = "\n\n".join(turns_text)

        # Use the prompt template from file
        return _LINK_SUMMARY_PROMPT.format(conversation=conversation)

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
        summary_prompt = self.build_session_summary_prompt(session)
        if summary_prompt is None:
            return session.title or "Empty session"

        stream_id = self._register_stream(StreamType.LINK_SUMMARY, f"Summarizing session: {session.title or session.id[:8]}")

        summary_parts = []
        try:
            async for event in self._runner.stream_response(
                [], summary_prompt, disable_tools=True
            ):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
            self._complete_stream(stream_id)
        except Exception as e:
            self._fail_stream(stream_id, str(e))
            debug_log.error(f"Session summary generation failed: {e}", category=Category.SESSION)
            return session.title or "Session"

        result = "".join(summary_parts).strip()
        return result if result else (session.title or "Session")

    def build_merge_summary_prompt(
        self, fork_session: Session, user_prompt: str = ""
    ) -> str:
        """Build the prompt for merge summary generation.

        This is separate from generate_merge_summary() to support
        non-blocking helper runner streaming.

        Args:
            fork_session: The fork session to summarize
            user_prompt: Optional user guidance for the summary

        Returns:
            The prompt string to send to the LLM
        """
        # Build conversation context from the fork
        turns_text = []
        for turn in fork_session.turns:
            role = "User" if turn.role == "user" else "Assistant"
            content = turn.content if isinstance(turn.content, str) else str(turn.content)
            # DONT Truncate very long messages
            turns_text.append(f"{role}: {content}")

        conversation = "\n\n".join(turns_text)

        # Build the summary prompt
        if user_prompt:
            return f"""Summarize the following conversation, focusing on: {user_prompt}

The summary should be 1-3 sentences describing what was accomplished or discovered.
Be specific about outcomes, not process.

Conversation:
{conversation}

Summary:"""
        else:
            return f"""Summarize the following conversation in 1-3 sentences.
Focus on what was accomplished or discovered, not the process.
Be specific about outcomes.

Conversation:
{conversation}

Summary:"""

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
        summary_prompt = self.build_merge_summary_prompt(fork_session, user_prompt)
        stream_id = self._register_stream(StreamType.MERGE_SUMMARY, f"Summarizing merge: {fork_session.title or fork_session.id[:8]}")

        summary_parts = []
        try:
            async for event in self._runner.stream_response([], summary_prompt):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
            self._complete_stream(stream_id)
        except Exception as e:
            self._fail_stream(stream_id, str(e))
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

        stream_id = self._register_stream(StreamType.COMPRESSION, f"Summarizing return ({len(messages)} messages)")

        summary_parts = []
        try:
            async for event in self._runner.stream_response([], prompt):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
            self._complete_stream(stream_id)
        except Exception as e:
            self._fail_stream(stream_id, str(e))
            # Fall back to raw content
            context_parts = [
                f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}"
                for m in messages
            ]
            return f"Error generating summary: {e}\n\nRaw content:\n" + "\n\n".join(
                context_parts
            )

        return "".join(summary_parts) if summary_parts else ""

    def build_return_summary_prompt(
        self, messages: list[Message], return_prompt: str = ""
    ) -> str:
        """Build the prompt for return summary generation.

        This is separate from generate_return_summary() to support
        non-blocking helper runner streaming.

        Args:
            messages: Messages from child session to summarize
            return_prompt: Optional user-provided context for the summary

        Returns:
            The prompt string to send to the LLM
        """
        return self._context_builder.build_return_summary_prompt(messages, return_prompt)

    def build_archive_summary_prompt(
        self, messages: list[Message], user_hint: str = ""
    ) -> str:
        """Build the prompt for archive summary generation.

        This is separate from generate_archive_summary() to support
        non-blocking helper runner streaming.

        Args:
            messages: Messages to summarize for archiving
            user_hint: Optional user hint for what to focus on

        Returns:
            The prompt string to send to the LLM
        """
        # Build conversation context
        turns_text = []
        for msg in messages:
            role = "User" if msg.role == "user" else "Assistant"
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # DONT Truncate very long messages
            turns_text.append(f"{role}: {content}")

        conversation = "\n\n".join(turns_text)

        # Build the structured summary prompt
        hint_section = f"\nUser hint: {user_hint}\n" if user_hint else ""

        return f"""Analyze this conversation segment and provide a structured summary.
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

        summary_prompt = self.build_archive_summary_prompt(messages, user_hint)
        stream_id = self._register_stream(StreamType.ARCHIVE_SUMMARY, f"Summarizing archive ({len(messages)} turns)")

        response_parts = []
        try:
            async for event in self._runner.stream_response(
                [], summary_prompt, disable_tools=True
            ):
                if isinstance(event, TextDelta):
                    response_parts.append(event.text)
            self._complete_stream(stream_id)
        except Exception as e:
            self._fail_stream(stream_id, str(e))
            debug_log.error(f"Archive summary generation failed: {e}", category=Category.RUNNER)
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

    def build_session_review_prompt(self, session: Session) -> str | None:
        """Build the prompt for session review generation.

        Args:
            session: The session to review

        Returns:
            The prompt string, or None if session is empty
        """
        # Build conversation context from the session
        turns_text = []
        for turn in session.turns:
            role = "User" if turn.role == "user" else "Assistant"
            content = turn.content if isinstance(turn.content, str) else str(turn.content)
            turns_text.append(f"{role}: {content}")

        if not turns_text:
            return None

        conversation = "\n\n".join(turns_text)
        return _SESSION_REVIEW_PROMPT.format(conversation=conversation)

    async def generate_session_review(self, session: Session) -> SessionSummaryBlock:
        """Generate a structured review of a session.

        Args:
            session: The session to review

        Returns:
            SessionSummaryBlock with structured review information
        """
        prompt = self.build_session_review_prompt(session)
        if prompt is None:
            # Empty session - return minimal review
            return SessionSummaryBlock(
                summary_id=str(uuid.uuid4()),
                proposed_title=session.title or "Empty session",
                work_done="No conversation content to review.",
                turn_count_at_review=0,
                reviewed_at=datetime.now().isoformat(),
                reviewed_by_backend=self._backend_name,
                status="pending",
            )

        stream_id = self._register_stream(
            StreamType.SESSION_REVIEW,
            f"Reviewing: {session.title or session.id[:8]}"
        )

        response_parts = []
        try:
            async for event in self._runner.stream_response(
                [], prompt, disable_tools=True
            ):
                if isinstance(event, TextDelta):
                    response_parts.append(event.text)
            self._complete_stream(stream_id)
        except Exception as e:
            self._fail_stream(stream_id, str(e))
            debug_log.error(f"Session review generation failed: {e}", category=Category.RUNNER)
            # Return a basic review on error
            return SessionSummaryBlock(
                summary_id=str(uuid.uuid4()),
                proposed_title=session.title or "Session",
                work_done=f"Review generation failed: {e}",
                turn_count_at_review=len(session.turns),
                reviewed_at=datetime.now().isoformat(),
                reviewed_by_backend=self._backend_name,
                status="pending",
            )

        response = "".join(response_parts)
        return self._parse_session_review(response, session)

    def _parse_session_review(
        self, response: str, session: Session
    ) -> SessionSummaryBlock:
        """Parse the LLM response into a SessionSummaryBlock."""
        proposed_title = ""
        files_modified = []
        decisions_made = []
        work_done = ""
        next_steps = []
        questions_raised = []

        current_section = None
        lines = response.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Detect section headers
            if line.upper().startswith("PROPOSED_TITLE"):
                current_section = "title"
                # Check if title is on same line after colon
                if ":" in line:
                    title_part = line.split(":", 1)[1].strip()
                    if title_part:
                        proposed_title = title_part
                continue
            elif line.upper().startswith("FILES_MODIFIED"):
                current_section = "files"
                continue
            elif line.upper().startswith("DECISIONS_MADE"):
                current_section = "decisions"
                continue
            elif line.upper().startswith("WORK_DONE"):
                current_section = "work"
                continue
            elif line.upper().startswith("NEXT_STEPS"):
                current_section = "next"
                continue
            elif line.upper().startswith("QUESTIONS_RAISED"):
                current_section = "questions"
                continue

            # Parse content based on current section
            if current_section == "title":
                if not proposed_title and line.lower() != "none":
                    proposed_title = line
            elif current_section == "files":
                if line.startswith("-"):
                    file_entry = line[1:].strip()
                    if file_entry.lower() != "none":
                        files_modified.append(file_entry)
            elif current_section == "decisions":
                if line.startswith("-"):
                    decision = line[1:].strip()
                    if decision.lower() != "none":
                        decisions_made.append(decision)
            elif current_section == "work":
                if line.lower() != "none":
                    if work_done:
                        work_done += " " + line
                    else:
                        work_done = line
            elif current_section == "next":
                if line.startswith("-"):
                    step = line[1:].strip()
                    if step.lower() != "none":
                        next_steps.append(step)
            elif current_section == "questions":
                if line.startswith("-"):
                    question = line[1:].strip()
                    if question.lower() != "none":
                        questions_raised.append(question)

        # Fallback if parsing failed
        if not proposed_title:
            proposed_title = session.title or "Session Review"
        if not work_done:
            work_done = f"Reviewed session with {len(session.turns)} turns"

        # Build markdown content from structured data
        markdown_content = self._format_review_as_markdown(
            work_done, files_modified, decisions_made, next_steps, questions_raised
        )

        return SessionSummaryBlock(
            summary_id=str(uuid.uuid4()),
            proposed_title=proposed_title,
            markdown_content=markdown_content,
            files_modified=files_modified,
            decisions_made=decisions_made,
            work_done=work_done,
            next_steps=next_steps,
            questions_raised=questions_raised,
            turn_count_at_review=len(session.turns),
            reviewed_at=datetime.now().isoformat(),
            reviewed_by_backend=self._backend_name,
            status="pending",
        )

    def _format_review_as_markdown(
        self,
        work_done: str,
        files_modified: list[str],
        decisions_made: list[str],
        next_steps: list[str],
        questions_raised: list[str],
    ) -> str:
        """Format review data as markdown for display/editing."""
        sections = []

        if work_done:
            sections.append(f"## Summary\n\n{work_done}")

        if files_modified:
            items = "\n".join(f"- {f}" for f in files_modified)
            sections.append(f"## Files Modified\n\n{items}")

        if decisions_made:
            items = "\n".join(f"- {d}" for d in decisions_made)
            sections.append(f"## Decisions Made\n\n{items}")

        if next_steps:
            items = "\n".join(f"- {n}" for n in next_steps)
            sections.append(f"## Next Steps\n\n{items}")

        if questions_raised:
            items = "\n".join(f"- {q}" for q in questions_raised)
            sections.append(f"## Open Questions\n\n{items}")

        return "\n\n".join(sections)
