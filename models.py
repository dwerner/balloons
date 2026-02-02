from dataclasses import dataclass, field
from typing import Optional, Any, Union
from datetime import datetime
from enum import Enum


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


@dataclass
class TextBlock:
    """Plain text content."""
    type: str = "text"
    text: str = ""


@dataclass
class ToolUseBlock:
    """Tool invocation by the assistant."""
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class ToolResultBlock:
    """Result from a tool invocation."""
    type: str = "tool_result"
    tool_use_id: str = ""
    content: str = ""
    is_error: bool = False


@dataclass
class InterruptionBlock:
    """Marker indicating the response was interrupted by the user."""
    type: str = "interruption"
    reason: str = "user_cancelled"  # e.g., "user_cancelled", "timeout"


@dataclass
class ErrorBlock:
    """Marker indicating the response ended with an error (truncated, decode error, etc.)."""
    type: str = "error"
    reason: str = "stream_error"  # e.g., "truncated", "json_decode_error"
    partial_tool_name: str = ""  # Tool name if a tool call was in progress
    partial_tool_input: str = ""  # Partial JSON if tool input was being streamed
    details: str = ""  # Error message or other details


@dataclass
class LinkBlock:
    """Marker indicating a bidirectional link to another session."""
    type: str = "link"
    link_id: str = ""  # UUID for this link pair (same in both sessions)
    linked_session_id: str = ""  # The other session's ID
    summary: str = ""  # LLM-generated summary
    is_orphaned: bool = False  # True if linked session was deleted


# Union type for all content block types
ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, LinkBlock]


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
