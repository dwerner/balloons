"""Streaming coordination for Balloons.

This module decouples streaming event dispatch from UI widgets by using
action objects. The StreamingCoordinator processes events and returns
actions that the UI layer interprets.

Pattern:
    action = coordinator.dispatch_event(event, ctx)
    if isinstance(action, TextAction):
        chat_log.append_to_current(action.text)
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Union

from models import (
    TextBlock, ToolUseBlock, InterruptionBlock, ErrorBlock, Message,
    ToolUseEvent, ToolResultEvent,
)
from .debug_log import debug_log
from .fork import ForkData, DeriveData


# =============================================================================
# Helper Data Classes - Typed data passed to helper completion handlers
# =============================================================================

@dataclass
class ArchiveData:
    """Data needed to complete an archive after summary generation.

    Tracks the session, turn range, and context needed to finalize archiving
    after the LLM generates a summary.
    """
    session_id: str
    turn_indices: list[int]
    turn_start: int
    turn_end: int
    hint: str = ""  # User-provided hint for what to focus on
    message_count: int = 0  # Number of messages being archived (for fallback summary)


@dataclass
class MergeData:
    """Data needed to complete a merge after summary generation.

    Tracks the fork and parent sessions for finalizing the merge.
    """
    fork_session_id: str
    parent_session_id: str
    fork_name: str


@dataclass
class LinkData:
    """Data needed to complete a link after summary generation.

    Tracks which sessions need summaries and final link targets.
    """
    current_session_id: str
    # List of (session_id, summary) tuples - summary may be None if not yet generated
    targets: list[tuple[str, str | None]]
    # Index of the target currently being summarized (for sequential generation)
    current_target_index: int = 0


@dataclass
class ReturnData:
    """Data needed to complete a return after summary generation.

    Tracks the child session being returned from and the parent session.
    """
    child_session_id: str
    parent_session_id: str
    return_prompt: str = ""  # User-provided return message


# =============================================================================
# StreamingContext - Tracks streaming state for a session
# =============================================================================

@dataclass
class StreamingContext:
    """Tracks streaming state for a session.

    Each streaming session needs to track its own state for proper
    event handling and UI updates.
    """
    session_id: str
    user_turn_idx: int  # Index of user turn in session.turns (-1 for query_with)
    assistant_turn_idx: int  # Index of assistant turn
    prompt: str  # Original prompt for saving
    content: str = ""  # Accumulated text content
    is_active: bool = True  # Is this the active/foreground session?
    query_with: bool = False  # Special case: no user message saved
    exchange_id: str = ""  # Groups all turns in this exchange (user + assistant responses)
    # Track tool events for session resume (tool_use_id -> (name, input, result))
    tool_events: dict = None
    # Track tool_use_id -> turn_idx mapping for finish_turn calls
    tool_turn_indices: dict = None
    # Track (tool_use_id, turn_type) -> turn_id mapping for emit calls
    tool_turn_ids: dict = None
    # Track tool_use_id -> tool_name for tools that need post-result actions
    tool_names: dict = None
    # Helper task tracking (for context compression, merge summaries, archives, links)
    is_helper: bool = False  # True if this is a helper task, not a normal prompt
    helper_type: str = ""  # "compress", "merge", "derive", "archive", "link"
    # For fork/derive context compression: data needed to complete after compression
    fork_data: Optional[Union[ForkData, DeriveData]] = None
    # For archive summary generation
    archive_data: Optional["ArchiveData"] = None
    # For merge summary generation
    merge_data: Optional["MergeData"] = None
    # For link summary generation
    link_data: Optional["LinkData"] = None
    # For return summary generation
    return_data: Optional["ReturnData"] = None
    # Track the final text turn for emit on done
    # -1 means no final text turn to emit (already flushed via TextFlushAction)
    final_turn_idx: int = -1
    final_turn_id: str = ""  # Stable UUID for the final text turn
    final_text_content: str = ""
    # Track total tool count for this exchange
    tool_count: int = 0

    def __post_init__(self):
        if self.tool_events is None:
            self.tool_events = {}
        if self.tool_turn_indices is None:
            self.tool_turn_indices = {}
        if self.tool_turn_ids is None:
            self.tool_turn_ids = {}
        if self.tool_names is None:
            self.tool_names = {}


# =============================================================================
# Action Objects - UI-agnostic instructions from event dispatch
# =============================================================================

@dataclass
class StreamingAction:
    """Base class for streaming actions."""
    session_id: str


@dataclass
class TextAction(StreamingAction):
    """Append text to the current message."""
    text: str


@dataclass
class TextFlushAction(StreamingAction):
    """Text segment complete (before tool use). Commit accumulated text as a visible node."""
    text: str
    turn_idx: int  # The turn index to finish
    turn_id: str = ""  # Stable UUID for the turn


@dataclass
class InitAction(StreamingAction):
    """Initialize with model info."""
    model: str
    context_window: int


@dataclass
class ResultAction(StreamingAction):
    """Usage stats received."""
    input_tokens: int
    output_tokens: int
    total_cost: float


@dataclass
class ToolUseStartAction(StreamingAction):
    """Tool use started (input still streaming)."""
    tool_use_id: str
    tool_name: str
    tool_index: int


@dataclass
class ToolInputDeltaAction(StreamingAction):
    """Partial tool input JSON received."""
    tool_use_id: str
    tool_name: str
    partial_json: str


@dataclass
class ToolUseCompleteAction(StreamingAction):
    """Tool input complete."""
    tool_use_id: str
    tool_name: str
    tool_input: dict
    tool_index: int


@dataclass
class ToolResultAction(StreamingAction):
    """Tool result received."""
    tool_use_id: str
    result: str
    tool_index: int
    turn_id: str = ""  # Stable UUID for the turn


@dataclass
class DoneAction(StreamingAction):
    """Stream completed successfully."""
    content: str
    content_blocks: list
    raw_events: list
    exchange_id: str
    turns: list[Message]
    cancelled: bool = False
    error: Optional[str] = None


@dataclass
class ErrorAction(StreamingAction):
    """Error occurred during streaming."""
    error: str


@dataclass
class RateLimitAction(StreamingAction):
    """Rate limit hit."""
    message: str


@dataclass
class CancelledAction(StreamingAction):
    """Stream was cancelled."""
    pass


@dataclass
class InputRequiredAction(StreamingAction):
    """Claude is asking a question (non-interactive mode)."""
    message: str


@dataclass
class HelperDoneAction(StreamingAction):
    """Helper task completed."""
    helper_type: str
    content: str
    fork_data: Optional[Union[ForkData, DeriveData]] = None
    archive_data: Optional["ArchiveData"] = None
    merge_data: Optional["MergeData"] = None
    link_data: Optional["LinkData"] = None
    return_data: Optional["ReturnData"] = None
    error: Optional[str] = None
    cancelled: bool = False


@dataclass
class NoAction(StreamingAction):
    """No UI action needed."""
    pass


@dataclass
class TurnStartedAction(StreamingAction):
    """A new turn has started during streaming.

    Used to create new turn nodes in the context tree for tool_use and tool_result turns.
    The initial assistant turn is started via the 'turn_started' event, but subsequent
    turns (tool_use, tool_result) need their own TurnStartedAction.
    """
    turn_idx: int
    turn_id: str  # Stable UUID for the turn
    role: str  # "assistant" for tool_use, "tool" for tool_result
    exchange_id: str
    turn_type: str  # "text", "tool_use", "tool_result"
    # For tool_use turns
    tool_use_id: str = ""
    tool_name: str = ""
    # For tool_result turns
    result_preview: str = ""


# =============================================================================
# StreamingCoordinator - Dispatches events and returns actions
# =============================================================================

class StreamingCoordinator:
    """Coordinates streaming events and returns UI-agnostic actions.

    This class processes StreamEvent objects and returns action objects
    that describe what should happen in the UI, without directly calling
    any widget methods.

    Usage:
        coordinator = StreamingCoordinator()

        # When polling events:
        for event in events:
            action = coordinator.dispatch_event(event, ctx)
            # UI layer interprets action
            if isinstance(action, TextAction):
                chat_log.append_to_current(action.text)
    """

    def dispatch_event(
        self,
        event,  # StreamEvent
        ctx: StreamingContext,
    ) -> StreamingAction:
        """Dispatch a streaming event and return the appropriate action.

        Args:
            event: The StreamEvent to process
            ctx: The StreamingContext tracking this session's state

        Returns:
            A StreamingAction describing what the UI should do
        """
        session_id = ctx.session_id

        if event.event_type == "turn_started":
            # Initial assistant turn - just logging, no action needed
            # (the UI creates the node when streaming starts)
            return NoAction(session_id=session_id)

        elif event.event_type == "text_turn_started":
            # Text segment flushed before tool use - create a new turn node
            # Reset accumulated content for the new turn (same as SessionManagerService does)
            ctx.content = ""
            data = event.data
            return TurnStartedAction(
                session_id=session_id,
                turn_idx=data.get("turn_index", 0),
                turn_id=data.get("turn_id", ""),
                role=data.get("role", "assistant"),
                exchange_id=data.get("exchange_id", ""),
                turn_type="text",
            )

        elif event.event_type == "tool_use_turn_started":
            # Tool use turn - create a new turn node
            data = event.data
            return TurnStartedAction(
                session_id=session_id,
                turn_idx=data.get("turn_index", 0),
                turn_id=data.get("turn_id", ""),
                role=data.get("role", "assistant"),
                exchange_id=data.get("exchange_id", ""),
                turn_type="tool_use",
                tool_use_id=data.get("tool_use_id", ""),
                tool_name=data.get("tool_name", ""),
            )

        elif event.event_type == "tool_result_turn_started":
            # Tool result turn - create a new turn node
            data = event.data
            return TurnStartedAction(
                session_id=session_id,
                turn_idx=data.get("turn_index", 0),
                turn_id=data.get("turn_id", ""),
                role=data.get("role", "tool"),
                exchange_id=data.get("exchange_id", ""),
                turn_type="tool_result",
                tool_use_id=data.get("tool_use_id", ""),
                result_preview=data.get("result_preview", ""),
            )

        elif event.event_type == "text":
            text = event.data
            ctx.content += text
            return TextAction(session_id=session_id, text=text)

        elif event.event_type == "text_flush":
            # Text segment complete (before tool use) - commit as visible node
            text = event.data.get("text", "")
            turn_idx = event.data.get("turn_index", 0)
            turn_id = event.data.get("turn_id", "")
            return TextFlushAction(session_id=session_id, text=text, turn_idx=turn_idx, turn_id=turn_id)

        elif event.event_type == "init":
            return InitAction(
                session_id=session_id,
                model=event.data.get("model", ""),
                context_window=event.data.get("context_window", 0),
            )

        elif event.event_type == "result":
            return ResultAction(
                session_id=session_id,
                input_tokens=event.data.get("input_tokens", 0),
                output_tokens=event.data.get("output_tokens", 0),
                total_cost=event.data.get("total_cost", 0.0),
            )

        elif event.event_type == "tool_use_start":
            data = event.data
            tool_use_id = data.get("tool_use_id")
            tool_name = data.get("tool_name")
            tool_index = data.get("tool_index", 0)

            # Initialize tracking (will be updated when tool_use completes)
            ctx.tool_events[tool_use_id] = {
                "name": tool_name,
                "input": {},  # Will be filled on tool_use
                "index": tool_index,
                "result": None,
            }

            return ToolUseStartAction(
                session_id=session_id,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                tool_index=tool_index,
            )

        elif event.event_type == "tool_input_delta":
            data = event.data
            tool_use_id = data.get("tool_use_id")
            partial_json = data.get("partial_json", "")
            tool_name = ctx.tool_events.get(tool_use_id, {}).get("name", "Tool")

            return ToolInputDeltaAction(
                session_id=session_id,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                partial_json=partial_json,
            )

        elif event.event_type == "tool_use":
            data = event.data
            tool_use_id = data.get("tool_use_id")
            tool_name = data.get("tool_name")
            tool_input = data.get("tool_input")
            tool_index = data.get("tool_index", 0)

            # Update tracking with final input
            if tool_use_id in ctx.tool_events:
                ctx.tool_events[tool_use_id]["input"] = tool_input
            else:
                ctx.tool_events[tool_use_id] = {
                    "name": tool_name,
                    "input": tool_input,
                    "index": tool_index,
                    "result": None,
                }

            return ToolUseCompleteAction(
                session_id=session_id,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_index=tool_index,
            )

        elif event.event_type == "tool_result":
            data = event.data
            tool_use_id = data.get("tool_use_id")
            result = data.get("result", "")
            tool_index = data.get("tool_index", 0)
            turn_id = data.get("turn_id", "")

            # Track tool result for session resume
            if tool_use_id in ctx.tool_events:
                ctx.tool_events[tool_use_id]["result"] = result

            return ToolResultAction(
                session_id=session_id,
                tool_use_id=tool_use_id,
                result=result,
                tool_index=tool_index,
                turn_id=turn_id,
            )

        elif event.event_type == "done":
            # The result is in event.data (StreamResult)
            result = event.data
            return DoneAction(
                session_id=session_id,
                content=ctx.content,
                content_blocks=result.content_blocks if result else [TextBlock(text=ctx.content)],
                raw_events=result.raw_events if result else [],
                exchange_id=result.exchange_id if result else "",
                turns=result.turns if result else [],
            )

        elif event.event_type == "error":
            return ErrorAction(session_id=session_id, error=event.data)

        elif event.event_type == "rate_limit":
            return RateLimitAction(session_id=session_id, message=event.data)

        elif event.event_type == "cancelled":
            return CancelledAction(session_id=session_id)

        elif event.event_type == "input_required":
            return InputRequiredAction(session_id=session_id, message=event.data)

        else:
            # Note: "raw" events are common and benign - use debug level to reduce noise
            debug_log.debug(
                f"Unknown event type: {event.event_type}",
                category="stream",
                session_id=session_id,
            )
            return NoAction(session_id=session_id)

    def dispatch_helper_event(
        self,
        event,  # StreamEvent
        ctx: StreamingContext,
    ) -> StreamingAction:
        """Dispatch a helper event (context compression, merge summary, archive, link).

        Helper events stream into the chat like regular messages, but when done
        trigger the next phase (e.g., start the actual fork after compression).

        Args:
            event: The StreamEvent to process
            ctx: The StreamingContext tracking this helper's state

        Returns:
            A StreamingAction describing what the UI should do
        """
        helper_id = ctx.session_id

        if event.event_type == "text":
            text = event.data
            ctx.content += text
            return TextAction(session_id=helper_id, text=text)

        elif event.event_type == "done":
            return HelperDoneAction(
                session_id=helper_id,
                helper_type=ctx.helper_type,
                content=ctx.content,
                fork_data=ctx.fork_data,
                archive_data=ctx.archive_data,
                merge_data=ctx.merge_data,
                link_data=ctx.link_data,
                return_data=ctx.return_data,
            )

        elif event.event_type == "error":
            return HelperDoneAction(
                session_id=helper_id,
                helper_type=ctx.helper_type,
                content=ctx.content,
                fork_data=ctx.fork_data,
                archive_data=ctx.archive_data,
                merge_data=ctx.merge_data,
                link_data=ctx.link_data,
                return_data=ctx.return_data,
                error=event.data,
            )

        elif event.event_type == "cancelled":
            return HelperDoneAction(
                session_id=helper_id,
                helper_type=ctx.helper_type,
                content=ctx.content,
                fork_data=ctx.fork_data,
                archive_data=ctx.archive_data,
                merge_data=ctx.merge_data,
                link_data=ctx.link_data,
                return_data=ctx.return_data,
                cancelled=True,
            )

        else:
            # Other events (init, result) - no action needed for helpers
            return NoAction(session_id=helper_id)
