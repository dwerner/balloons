import uuid
from dataclasses import dataclass, field
from typing import Optional, Any, Union
from datetime import datetime
from enum import Enum

from codegen import ws_type


class ContextMode(Enum):
    """How a turn should be included in context when forking.

    COPY: Include turn verbatim in fork
    COMPRESS: LLM summarizes the turn before fork starts
    DROP: Exclude from fork context
    """
    COPY = "copy"
    COMPRESS = "compress"  # New name - LLM compresses before fork
    SUMMARIZE = "summarize"  # Legacy alias for COMPRESS
    DROP = "drop"


class Sentiment(Enum):
    """User sentiment rating for an assistant turn.

    Used for quick quality feedback during a session. Applied only to
    assistant text responses, not tool calls or user inputs.
    """
    EXCELLENT = "excellent"  # ❤️ Notably good
    GOOD = "good"            # 👍 Worked as expected
    REVIEW = "review"        # 🔍 Mark for review (no judgment)
    POOR = "poor"            # 👎 Didn't work well
    TERRIBLE = "terrible"    # ☠️ Actively harmful/wrong


@ws_type
@dataclass
class TextBlock:
    """Plain text content."""
    type: str = "text"
    text: str = ""


@ws_type
@dataclass
class ImageBlock:
    """Image content - stores reference to uploaded image.

    Images can be:
    - Pasted from clipboard (screenshot, copied image)
    - Uploaded via file picker

    The image is stored on disk and referenced by file_path.
    media_type is the MIME type (e.g., "image/png", "image/jpeg").
    """
    type: str = "image"
    file_path: str = ""  # Path to stored image file
    media_type: str = ""  # MIME type: image/png, image/jpeg, image/gif, image/webp
    filename: str = ""  # Original filename (for uploads) or generated name
    width: int = 0  # Image dimensions (optional, for display)
    height: int = 0


@ws_type
@dataclass
class ToolUseBlock:
    """Tool invocation by the assistant."""
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@ws_type
@dataclass
class ToolResultBlock:
    """Result from a tool invocation."""
    type: str = "tool_result"
    tool_use_id: str = ""
    content: str = ""
    is_error: bool = False


@ws_type
@dataclass
class InterruptionBlock:
    """Marker indicating the response was interrupted by the user."""
    type: str = "interruption"
    reason: str = "user_cancelled"  # e.g., "user_cancelled", "timeout"


@ws_type
@dataclass
class ErrorBlock:
    """Marker indicating the response ended with an error (truncated, decode error, etc.)."""
    type: str = "error"
    reason: str = "stream_error"  # e.g., "truncated", "json_decode_error"
    partial_tool_name: str = ""  # Tool name if a tool call was in progress
    partial_tool_input: str = ""  # Partial JSON if tool input was being streamed
    details: str = ""  # Error message or other details
    dump_file: str = ""  # Path to dumped content file for LLM completion


@ws_type
@dataclass
class LinkBlock:
    """Marker indicating a bidirectional link to another session."""
    type: str = "link"
    link_id: str = ""  # UUID for this link pair (same in both sessions)
    linked_session_id: str = ""  # The other session's ID
    summary: str = ""  # LLM-generated summary
    is_orphaned: bool = False  # True if linked session was deleted


@ws_type
@dataclass
class ForkBlock:
    """Marker indicating where a fork was created.

    Stored as a turn in the parent session's history. When nested forks exist,
    these blocks persist through merges, preserving the full fork history.
    """
    type: str = "fork"
    fork_id: str = ""  # UUID for this fork (same as child session ID typically)
    child_session_id: str = ""  # The forked session's ID
    fork_name: str = ""  # User-friendly name for the fork
    prompt: str = ""  # The prompt that started the fork
    status: str = "active"  # "active", "merged", "abandoned"


@ws_type
@dataclass
class MergeBlock:
    """Marker indicating where a fork was merged back.

    Stored as a turn in the parent session's history. Contains the merge summary,
    allowing nested merge info to propagate when sessions are re-merged.
    """
    type: str = "merge"
    merge_id: str = ""  # UUID for this merge event
    child_session_id: str = ""  # The fork session that was merged
    fork_name: str = ""  # Name of the fork
    message: str = ""  # Summary of what was accomplished in the fork
    files_changed: list[str] = field(default_factory=list)  # Key files modified
    key_accomplishments: list[str] = field(default_factory=list)  # What was done
    reason: str = ""  # Why the merge happened now


@ws_type
@dataclass
class MergedToBlock:
    """Marker indicating this fork was merged back to its parent.

    Stored as the final turn in a fork session's history when it is merged.
    This is the counterpart to MergeBlock which is stored in the parent.
    """
    type: str = "merged_to"
    merge_id: str = ""  # UUID for this merge event (same as MergeBlock)
    parent_session_id: str = ""  # The parent session that received the merge
    parent_name: str = ""  # Name of the parent session
    parent_turn: int = 0  # Turn index in parent where merge marker was added
    message: str = ""  # Summary of what was accomplished (same as in parent)
    files_changed: list[str] = field(default_factory=list)  # Key files modified
    key_accomplishments: list[str] = field(default_factory=list)  # What was done
    reason: str = ""  # Why the merge happened now


@ws_type
@dataclass
class ForkedFromBlock:
    """Marker indicating this session was forked from a parent.

    Stored as the first turn in a fork session's history when it is created.
    This is the counterpart to ForkBlock which is stored in the parent.
    Provides a backlink to navigate back to the parent session.
    """
    type: str = "forked_from"
    fork_id: str = ""  # UUID for this fork (same as ForkBlock)
    parent_session_id: str = ""  # The parent session this was forked from
    parent_name: str = ""  # Name of the parent session
    parent_turn: int = 0  # Turn index in parent where fork marker was added (fork_point)
    fork_name: str = ""  # Name of this fork
    prompt: str = ""  # The initial prompt for this fork


@ws_type
@dataclass
class SlideBlock:
    """Slide content for presentation mode.

    Slides are a first-class turn type that can be:
    - Created manually via :new-slide command
    - Generated by Claude via create_slide balloons-tool
    - Viewed in a dedicated Slides tab
    - Presented fullscreen in presentation mode
    """
    type: str = "slide"
    title: str = ""  # Slide title, max ~50 chars for 1080p
    content: str = ""  # Markdown body, max ~10 lines for 1080p
    notes: str = ""  # Speaker notes (not shown in presentation)


@ws_type
@dataclass
class ReviewBlock:
    """Marker indicating where a quality review was initiated.

    Stored as a turn in the reviewed session's history. The review itself
    happens in a child session (like a fork), allowing the review conversation
    to be preserved separately.
    """
    type: str = "review"
    review_id: str = ""  # UUID for this review
    child_session_id: str = ""  # The review session's ID
    model_under_review: str = ""  # Backend name of model being evaluated
    status: str = "active"  # "active", "completed", "abandoned"
    # Summary fields populated when review completes
    overall_score: float = 0.0  # Average of rubric scores (1-5)
    task_category: str = ""  # debugging, feature, refactor, etc.
    task_description: str = ""  # 1-sentence description
    notes: str = ""  # Speaker notes (not shown in presentation)


@ws_type
@dataclass
class ContextAssignmentData:
    """A context mode assignment for a range of exchanges (stored form).

    This is the persistable version of core.fork.ContextAssignment.
    """
    exchange_range: str = ""  # e.g., "0-2", "5", "last", "all"
    mode: str = ""  # "copy", "compress", "drop"
    reason: str = ""  # Why this mode for these exchanges


@ws_type
@dataclass
class ExchangeInfo:
    """Information about an exchange for display in fork proposal tree.

    Used to show ALL exchanges in the context tree, not just those
    explicitly mentioned in the LLM's proposal.
    """
    index: int = 0  # Exchange index (0-based)
    summary: str = ""  # Short summary of the exchange content
    mode: str = "compress"  # Default mode - can be overridden by context_plan


@ws_type
@dataclass
class ForkBindingData:
    """Binding specification for a fork (stored form).

    This is the persistable version of core.fork.ForkBindingSpec.
    """
    entity_type: str = ""  # "goal", "plan", or "todo"
    entity_id: str = ""  # ID of the entity (can be prefix)
    role: str = ""  # "interview", "planning", "implementation", "postmortem", "exploration"


@ws_type
@dataclass
class ForkProposalBlock:
    """An inline fork proposal from the LLM.

    Stored as a turn in the session's history. The user can accept or reject
    the proposal inline, rather than via a modal dialog. This ensures proposals
    persist even if the user switches sessions.
    """
    type: str = "fork_proposal"
    proposal_id: str = ""  # UUID for this proposal
    name: str = ""  # Short fork name (e.g., "implement-cache-layer")
    description: str = ""  # What this fork will accomplish
    context_plan: list[ContextAssignmentData] = field(default_factory=list)
    initial_prompt: str = ""  # Optional starting prompt
    bind_to: Optional[ForkBindingData] = None  # Explicit binding spec
    bind_to_inherit: bool = False  # True if bind_to was "inherit"
    status: str = "pending"  # "pending", "accepted", "rejected"
    all_exchanges: list[ExchangeInfo] = field(default_factory=list)  # All exchanges for interactive tree
    child_session_id: str = ""  # ID of created fork session (set on accept)


@ws_type
@dataclass
class MergeProposalBlock:
    """An inline merge proposal from the LLM.

    Stored as a turn in the session's history. The user can accept (with optional
    edits to the summary) or reject the proposal inline.
    """
    type: str = "merge_proposal"
    proposal_id: str = ""  # UUID for this proposal
    summary: str = ""  # Preview of the merge summary
    reason: str = ""  # Why the LLM thinks merge is appropriate now
    files_changed: list[str] = field(default_factory=list)  # Key files modified
    key_accomplishments: list[str] = field(default_factory=list)  # What was done
    status: str = "pending"  # "pending", "accepted", "rejected"


@ws_type
@dataclass
class ArchiveSummary:
    """Structured summary of archived content.

    Generated by LLM with specific prompt to capture:
    - What files were modified
    - What work was done
    - Key decisions made
    """
    files_modified: list[str] = field(default_factory=list)  # e.g., ["core/archiver.py (created)", "models.py (modified)"]
    work_done: str = ""  # 1-3 sentence description of what was accomplished
    key_decisions: list[str] = field(default_factory=list)  # Important design decisions


@ws_type
@dataclass
class ArchiveBlock:
    """Marker for archived turns stored in an external file.

    When turns are archived, they are replaced with a single message containing
    this block. The original messages are stored in a file and can be rehydrated.
    """
    type: str = "archive"
    archive_id: str = ""  # UUID for this archive
    file_path: str = ""  # Path to the archived content file
    summary: str = ""  # Plain text summary (legacy/fallback)
    structured_summary: Optional[ArchiveSummary] = None  # Structured summary
    turn_start: int = 0  # Original turn index (start, inclusive)
    turn_end: int = 0  # Original turn index (end, exclusive)
    message_count: int = 0  # Number of archived messages
    token_estimate: int = 0  # Estimated tokens saved by archiving

    def get_display_summary(self) -> str:
        """Get a display-friendly summary string."""
        if self.structured_summary:
            parts = []
            if self.structured_summary.work_done:
                parts.append(self.structured_summary.work_done)
            if self.structured_summary.files_modified:
                files = ", ".join(self.structured_summary.files_modified[:3])
                if len(self.structured_summary.files_modified) > 3:
                    files += f" (+{len(self.structured_summary.files_modified) - 3} more)"
                parts.append(f"Files: {files}")
            return " | ".join(parts) if parts else self.summary
        return self.summary


# Union type for all content block types
ContentBlock = Union[TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, LinkBlock, ForkBlock, MergeBlock, MergedToBlock, ForkedFromBlock, ArchiveBlock, SlideBlock, ReviewBlock, ForkProposalBlock, MergeProposalBlock]


@dataclass
class Message:
    role: str  # "user", "assistant", or "tool"
    content: str  # Text-only summary for display/backwards compat
    content_blocks: list[ContentBlock] = field(default_factory=list)  # Rich content
    tokens: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    context_mode: ContextMode = ContextMode.COMPRESS
    summary: str = ""  # Cached summary for SUMMARIZE mode
    exchange_id: Optional[str] = None  # Groups turns in an agentic loop (user prompt + all responses)


@dataclass
class TextDelta:
    text: str
    raw: dict = field(default_factory=dict)


@dataclass
class ContextTokensEvent:
    """Emitted when context tokens are counted before sending to Claude."""
    context_tokens: int


@dataclass
class ResultEvent:
    input_tokens: int
    output_tokens: int
    total_cost_usd: float
    context_window: int = 200000
    raw: dict = field(default_factory=dict)


@dataclass
class InitEvent:
    model: str
    session_id: str
    context_window: int
    raw: dict = field(default_factory=dict)


@dataclass
class RawEvent:
    """Raw JSON event for inspection (non-parsed events)."""
    data: dict


@dataclass
class ToolUseStartEvent:
    """Tool use started - name known but input still streaming."""
    tool_use_id: str
    tool_name: str


@dataclass
class ToolInputDeltaEvent:
    """Partial tool input JSON."""
    tool_use_id: str
    partial_json: str


@dataclass
class ToolUseEvent:
    """Claude finished defining a tool use (input complete)."""
    tool_use_id: str
    tool_name: str
    tool_input: dict


@dataclass
class ToolResultEvent:
    """Result from a tool use."""
    tool_use_id: str
    result: str


# =============================================================================
# Message Queue Domain Entities
# =============================================================================


@dataclass
class QueuedMessage:
    """A message waiting to be sent.

    Represents a user message queued during streaming mode,
    waiting to be sent to the LLM when streaming completes.
    """
    id: str
    content: str
    created: datetime
    paused: bool = False  # When True, this message and all after it are blocked

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "created": self.created.isoformat(),
            "paused": self.paused,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QueuedMessage":
        return cls(
            id=data["id"],
            content=data["content"],
            created=datetime.fromisoformat(data["created"]),
            paused=data.get("paused", False),
        )


@dataclass
class MessageQueue:
    """Queue of messages pending for a session.

    Implements a FIFO queue with pause/resume support for individual messages.
    When a message is paused, it and all subsequent messages are blocked from
    being sent until it is unpaused.
    """
    messages: list[QueuedMessage] = field(default_factory=list)

    def add(self, content: str) -> QueuedMessage:
        """Add a message to the queue."""
        msg = QueuedMessage(
            id=str(uuid.uuid4()),
            content=content,
            created=datetime.now(),
        )
        self.messages.append(msg)
        return msg

    def pop(self) -> Optional[QueuedMessage]:
        """Remove and return the next message, or None if empty."""
        if self.messages:
            return self.messages.pop(0)
        return None

    def peek(self) -> Optional[QueuedMessage]:
        """Return the next message without removing it."""
        if self.messages:
            return self.messages[0]
        return None

    def remove(self, message_id: str) -> bool:
        """Remove a specific message by ID. Returns True if found."""
        for i, msg in enumerate(self.messages):
            if msg.id == message_id:
                self.messages.pop(i)
                return True
        return False

    def toggle_pause(self, message_id: str) -> bool:
        """Toggle the paused state of a message. Returns new paused state."""
        for msg in self.messages:
            if msg.id == message_id:
                msg.paused = not msg.paused
                return msg.paused
        return False

    def get(self, message_id: str) -> Optional[QueuedMessage]:
        """Get a message by ID."""
        for msg in self.messages:
            if msg.id == message_id:
                return msg
        return None

    def update_content(self, message_id: str, new_content: str) -> bool:
        """Update the content of a message. Returns True if found."""
        for msg in self.messages:
            if msg.id == message_id:
                msg.content = new_content
                return True
        return False

    def is_blocked(self) -> bool:
        """Check if the queue is blocked (first message is paused)."""
        if self.messages:
            return self.messages[0].paused
        return False

    def first_pause_index(self) -> int:
        """Return index of first paused message, or -1 if none."""
        for i, msg in enumerate(self.messages):
            if msg.paused:
                return i
        return -1

    def drain(self) -> list[str]:
        """Remove and return content of all messages up to (but not including) the first paused message.

        Returns list of message content strings. If no messages or blocked, returns empty list.
        """
        if not self.messages or self.messages[0].paused:
            return []

        result: list[str] = []
        while self.messages and not self.messages[0].paused:
            msg = self.messages.pop(0)
            result.append(msg.content)
        return result

    def clear(self) -> int:
        """Clear all messages. Returns count of cleared messages."""
        count = len(self.messages)
        self.messages = []
        return count

    def __len__(self) -> int:
        return len(self.messages)

    def __bool__(self) -> bool:
        return bool(self.messages)

    def to_dict(self) -> dict:
        return {
            "messages": [m.to_dict() for m in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MessageQueue":
        return cls(
            messages=[QueuedMessage.from_dict(m) for m in data.get("messages", [])],
        )


# =============================================================================
# Turn Domain Entity
# =============================================================================


def _generate_turn_id() -> str:
    """Generate a unique turn ID using UUID."""
    return str(uuid.uuid4())


@dataclass
class Turn:
    """A single turn in the conversation - one content block with metadata.

    Timing fields for diagnosing streaming issues:
    - started_at: When the turn began (streaming started)
    - ended_at: When the turn completed (streaming finished)
    - duration_ms property: Calculated duration in milliseconds

    These help diagnose whether apparent "hangs" are:
    1. LLM taking long to respond (long duration)
    2. Streaming getting stuck (started_at set but no ended_at)
    3. UI not updating (both timestamps present but UI lagging)

    Dirty tracking for incremental saves:
    - _dirty: True if turn has been modified since last save
    - Turns start dirty (new) and become clean after save
    - Modifications automatically set _dirty = True
    """
    role: str  # "user", "assistant", "tool", or "system"
    content_block: ContentBlock  # Single content block
    tokens: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    context_mode: ContextMode = ContextMode.COMPRESS
    summary: str = ""  # Cached summary for SUMMARIZE mode
    exchange_id: Optional[str] = None  # Groups turns in an agentic loop
    sentiment: Optional[Sentiment] = None  # User sentiment rating (assistant turns only)
    started_at: Optional[str] = None  # ISO timestamp when streaming began
    ended_at: Optional[str] = None  # ISO timestamp when streaming completed
    parallel_group_id: Optional[str] = None  # Groups parallel tool calls from same LLM response
    # Persistent ID for incremental saves (generated once, stored in DB)
    id: str = field(default_factory=_generate_turn_id)
    # Dirty tracking - not persisted, used for incremental saves
    _dirty: bool = field(default=True, repr=False, compare=False)

    def mark_dirty(self) -> None:
        """Mark this turn as modified, requiring save."""
        self._dirty = True

    def mark_clean(self) -> None:
        """Mark this turn as saved (no longer dirty)."""
        self._dirty = False

    @property
    def is_dirty(self) -> bool:
        """Check if this turn needs to be saved."""
        return self._dirty

    @property
    def duration_ms(self) -> Optional[int]:
        """Calculate duration in milliseconds if both timestamps are set.

        Returns:
            Duration in milliseconds, or None if timestamps are missing/invalid
        """
        if not self.started_at or not self.ended_at:
            return None
        try:
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.ended_at)
            delta = end - start
            return int(delta.total_seconds() * 1000)
        except (ValueError, TypeError):
            return None

    @property
    def content(self) -> str:
        """Get text content for display/backwards compat."""
        if isinstance(self.content_block, TextBlock):
            return self.content_block.text
        elif isinstance(self.content_block, ToolResultBlock):
            return self.content_block.content
        return ""

    @property
    def content_blocks(self) -> list[ContentBlock]:
        """Backwards compat: return content_block as a list."""
        return [self.content_block]