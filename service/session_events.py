"""Session event types and observer protocol for async event distribution.

This module defines the typed events emitted by SessionManagerService and the
observer protocol that consumers must implement to receive events.

The observer pattern enables:
- SessionDataService to emit WebSocket events to subscribed clients
- TUI to update widgets without polling
- Any other component to observe session events

Usage:
    from service.session_events import SessionEventObserver, TurnDeltaEvent

    class MyObserver(SessionEventObserver):
        async def on_turn_delta(self, event: TurnDeltaEvent) -> None:
            # Handle the event
            pass

    # Register with SessionManagerService
    service.add_observer(observer)
"""

from dataclasses import dataclass, field
from typing import Protocol, Any, Union

from models import (
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ImageBlock,
    InterruptionBlock,
    ErrorBlock,
    LinkBlock,
    ForkBlock,
    MergeBlock,
    MergedToBlock,
    ArchiveBlock,
    SlideBlock,
    ReviewBlock,
    ForkProposalBlock,
    MergeProposalBlock,
)

# ContentBlock union type
ContentBlock = Union[
    TextBlock,
    ImageBlock,
    ToolUseBlock,
    ToolResultBlock,
    InterruptionBlock,
    ErrorBlock,
    LinkBlock,
    ForkBlock,
    MergeBlock,
    MergedToBlock,
    ArchiveBlock,
    SlideBlock,
    ReviewBlock,
    ForkProposalBlock,
    MergeProposalBlock,
]


# --- Event Dataclasses ---


@dataclass
class TurnCreatedEvent:
    """Emitted when a new turn is created.

    This is sent at the start of a turn before any content arrives.
    Used by observers to prepare UI elements for the new turn.
    """

    session_id: str
    turn_id: str  # Stable UUID for the turn
    turn_index: int  # Position in turn list
    role: str  # "user", "assistant", "tool", "system"
    exchange_id: str  # Groups related turns (user prompt + assistant response)
    content_block_type: str = "text"  # "text", "tool_use", "tool_result", "watch_start", etc.
    parallel_group_id: str | None = None  # Groups parallel tool calls


@dataclass
class TurnDeltaEvent:
    """Emitted when text content is streamed to a turn.

    Observers should accumulate deltas to build the full turn content.
    accumulated_length can be used to verify sync.
    """

    session_id: str
    turn_id: str
    turn_index: int
    delta: str  # New text chunk
    accumulated_length: int  # Total content length so far


@dataclass
class TurnFinishedEvent:
    """Emitted when a turn finishes streaming.

    Contains the final content block and token count.
    After this event, no more deltas will be sent for this turn.
    """

    session_id: str
    turn_id: str
    turn_index: int
    role: str
    content: str  # Final accumulated text content
    tokens: int  # Token count for this turn (0 if not counted yet)
    content_block: ContentBlock | None = None  # Structured content block
    # Cumulative token counts for the exchange (context sent to LLM + total output so far)
    context_tokens: int = 0  # Total context/input tokens sent to LLM
    output_tokens_total: int = 0  # Total output tokens generated so far in this exchange


@dataclass
class StreamStartedEvent:
    """Emitted when a session begins streaming.

    This is sent before any turn events for a new exchange.
    exchange_id links all turns in this streaming sequence.
    """

    session_id: str
    exchange_id: str
    prompt: str  # The user's prompt that started streaming


@dataclass
class StreamDoneEvent:
    """Emitted when streaming completes successfully.

    After this event, the session is no longer streaming.
    """

    session_id: str
    exchange_id: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StreamProgressEvent:
    """Emitted periodically during streaming with progress info.

    Provides real-time streaming status for the status bar.
    Throttled to avoid flooding (not sent on every delta).
    """

    session_id: str
    exchange_id: str
    tokens_streamed: int  # Estimated output tokens so far
    current_token_rate: float  # Tokens/sec
    tool_name: str | None  # Currently executing tool, if any
    tool_count: int  # Tools executed so far
    model: str  # Model name
    context_window: int  # Model's context window
    duration_seconds: float  # Time since stream started


@dataclass
class StreamErrorEvent:
    """Emitted when streaming fails with an error.

    The session is no longer streaming after this event.
    """

    session_id: str
    exchange_id: str
    error: str
    error_type: str = "error"  # "error", "rate_limit", "cancelled"


@dataclass
class ToolUseStartedEvent:
    """Emitted when a tool begins execution.

    This is sent before the tool runs, when Claude has decided to use a tool.
    """

    session_id: str
    exchange_id: str
    turn_index: int  # The assistant turn containing this tool use
    tool_use_id: str  # Unique ID for this tool invocation
    tool_name: str  # Name of the tool (e.g., "Bash", "Read")
    tool_index: int  # Index of this tool within the turn (0-based)


@dataclass
class ToolInputDeltaEvent:
    """Emitted when tool input JSON is streamed.

    Claude streams the tool input as JSON fragments.
    Observers can use this to show input being constructed.
    """

    session_id: str
    exchange_id: str
    tool_use_id: str
    partial_json: str  # JSON fragment


@dataclass
class ToolUseEvent:
    """Emitted when tool input is complete (tool is about to execute).

    Contains the full tool input. After this, the tool executes.
    """

    session_id: str
    exchange_id: str
    turn_index: int
    tool_use_id: str
    tool_name: str
    tool_input: dict[str, Any]  # Complete tool input
    tool_index: int


@dataclass
class ToolResultEvent:
    """Emitted when a tool finishes execution.

    Contains the tool's output. Streaming resumes after this.
    """

    session_id: str
    exchange_id: str
    turn_index: int  # The tool result turn
    tool_use_id: str
    tool_name: str
    result: str | Any  # Tool output
    is_error: bool
    tool_index: int


# --- Helper Events ---
# Helper runners are used for background LLM tasks like context compression,
# merge summaries, archive summaries, link summaries, etc.


@dataclass
class HelperStartedEvent:
    """Emitted when a helper task begins streaming.

    Helper tasks run LLM operations in the background for things like:
    - Context compression (compress, derive)
    - Merge/return summaries (merge, return)
    - Archive summaries (archive)
    - Link summaries (link)
    """

    helper_id: str  # Unique ID for this helper task
    helper_type: str  # "compress", "derive", "archive", "merge", "link", "return"
    session_id: str | None = None  # Associated session if applicable
    metadata: dict[str, Any] = field(default_factory=dict)  # Type-specific data


@dataclass
class HelperDeltaEvent:
    """Emitted when text content is streamed from a helper task.

    Observers can use this to display streaming progress.
    """

    helper_id: str
    helper_type: str
    delta: str  # New text chunk
    accumulated_length: int  # Total content length so far


@dataclass
class HelperDoneEvent:
    """Emitted when a helper task completes successfully.

    Contains the final result text and metadata needed for continuation.
    """

    helper_id: str
    helper_type: str
    result: str  # Final accumulated text
    metadata: dict[str, Any] = field(default_factory=dict)  # Type-specific result data


@dataclass
class HelperErrorEvent:
    """Emitted when a helper task fails or is cancelled.

    After this event, the helper task is no longer running.
    """

    helper_id: str
    helper_type: str
    error: str | None = None  # Error message (None if cancelled)
    cancelled: bool = False  # True if cancelled rather than errored


# --- Observer Protocol ---


class SessionEventObserver(Protocol):
    """Protocol for observing session streaming events.

    Implement this protocol to receive async notifications of session events.
    All methods are optional - implement only the ones you need.

    Methods receive typed event dataclasses with all relevant data.
    """

    async def on_turn_created(self, event: TurnCreatedEvent) -> None:
        """Called when a new turn is created."""
        ...

    async def on_turn_delta(self, event: TurnDeltaEvent) -> None:
        """Called when text content is streamed to a turn."""
        ...

    async def on_turn_finished(self, event: TurnFinishedEvent) -> None:
        """Called when a turn finishes streaming."""
        ...

    async def on_stream_started(self, event: StreamStartedEvent) -> None:
        """Called when a session begins streaming."""
        ...

    async def on_stream_done(self, event: StreamDoneEvent) -> None:
        """Called when streaming completes successfully."""
        ...

    async def on_stream_progress(self, event: StreamProgressEvent) -> None:
        """Called periodically with streaming progress info."""
        ...

    async def on_stream_error(self, event: StreamErrorEvent) -> None:
        """Called when streaming fails with an error."""
        ...

    async def on_tool_use_started(self, event: ToolUseStartedEvent) -> None:
        """Called when a tool begins execution."""
        ...

    async def on_tool_input_delta(self, event: ToolInputDeltaEvent) -> None:
        """Called when tool input JSON is streamed."""
        ...

    async def on_tool_use(self, event: ToolUseEvent) -> None:
        """Called when tool input is complete."""
        ...

    async def on_tool_result(self, event: ToolResultEvent) -> None:
        """Called when a tool finishes execution."""
        ...

    async def on_helper_started(self, event: HelperStartedEvent) -> None:
        """Called when a helper task begins streaming."""
        ...

    async def on_helper_delta(self, event: HelperDeltaEvent) -> None:
        """Called when text content is streamed from a helper task."""
        ...

    async def on_helper_done(self, event: HelperDoneEvent) -> None:
        """Called when a helper task completes successfully."""
        ...

    async def on_helper_error(self, event: HelperErrorEvent) -> None:
        """Called when a helper task fails or is cancelled."""
        ...
