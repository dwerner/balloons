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
from typing import Any, Optional

from models import (
    TextBlock, ToolUseBlock, InterruptionBlock, ErrorBlock, Message,
    ToolUseEvent, ToolResultEvent,
)
from .debug_log import debug_log


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
    user_turn_idx: int  # Index of user turn in session.messages (-1 for query_with)
    assistant_turn_idx: int  # Index of assistant turn
    prompt: str  # Original prompt for saving
    content: str = ""  # Accumulated text content
    is_active: bool = True  # Is this the active/foreground session?
    query_with: bool = False  # Special case: no user message saved
    # Track tool events for session resume (tool_use_id -> (name, input, result))
    tool_events: dict = None
    # Helper task tracking (for context compression, merge summaries)
    is_helper: bool = False  # True if this is a helper task, not a normal prompt
    helper_type: str = ""  # "compress", "merge", etc.
    # For fork context compression: data needed to complete the fork after compression
    fork_data: dict = None  # Contains indexed_messages, allowed_tools, name, background, etc.

    def __post_init__(self):
        if self.tool_events is None:
            self.tool_events = {}
        if self.fork_data is None:
            self.fork_data = {}


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
    fork_data: dict
    error: Optional[str] = None
    cancelled: bool = False


@dataclass
class NoAction(StreamingAction):
    """No UI action needed."""
    pass


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
            # Just logging, no action needed
            return NoAction(session_id=session_id)

        elif event.event_type == "text":
            text = event.data
            ctx.content += text
            return TextAction(session_id=session_id, text=text)

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

            # Track tool result for session resume
            if tool_use_id in ctx.tool_events:
                ctx.tool_events[tool_use_id]["result"] = result

            return ToolResultAction(
                session_id=session_id,
                tool_use_id=tool_use_id,
                result=result,
                tool_index=tool_index,
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
            debug_log.warning(
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
        """Dispatch a helper event (context compression, merge summary).

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
            )

        elif event.event_type == "error":
            return HelperDoneAction(
                session_id=helper_id,
                helper_type=ctx.helper_type,
                content=ctx.content,
                fork_data=ctx.fork_data,
                error=event.data,
            )

        elif event.event_type == "cancelled":
            return HelperDoneAction(
                session_id=helper_id,
                helper_type=ctx.helper_type,
                content=ctx.content,
                fork_data=ctx.fork_data,
                cancelled=True,
            )

        else:
            # Other events (init, result) - no action needed for helpers
            return NoAction(session_id=helper_id)
