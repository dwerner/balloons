"""Base runner interface for LLM backends."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import AsyncIterator, Union, Callable, Awaitable

from models import (
    Message, TextDelta, ResultEvent, InitEvent, RawEvent,
    ToolUseStartEvent, ToolInputDeltaEvent, ToolUseEvent, ToolResultEvent,
    SteeringInjectedEvent,
)


# Type alias for all possible events yielded by runners
RunnerEvent = Union[
    TextDelta, ResultEvent, InitEvent, RawEvent,
    ToolUseStartEvent, ToolInputDeltaEvent, ToolUseEvent, ToolResultEvent,
    SteeringInjectedEvent,
]

# Type alias for injection callback: returns message to inject or None
InjectionCallback = Callable[[], Awaitable[str | None]]


class SteeringCapability(Enum):
    """How a runner handles mid-stream user steering.

    Different backends support different methods of injecting user
    messages during tool execution:

    - HYBRID_TURN: Can bundle tool_result + user text in a single message
                   (Claude's native format)
    - SEPARATE_MESSAGES: Sends tool result then user message separately
                         (OpenAI/OpenRouter style)
    - NO_MID_STREAM: Cannot inject mid-stream; steering is queued for
                     after streaming completes
    """
    HYBRID_TURN = "hybrid"
    SEPARATE_MESSAGES = "separate"
    NO_MID_STREAM = "none"


class BaseRunner(ABC):
    """Abstract base class for all LLM runners.

    All runners must implement stream_response() and terminate().

    Mid-Stream Steering:
        Runners support injecting user messages mid-stream for steering.
        Use set_injection_callback() to provide a callback that returns
        queued user messages. The callback is checked after tool execution,
        allowing users to steer the conversation without cancelling.

        The steering_capability property indicates how the runner handles
        steering messages - some can bundle them with tool results (hybrid),
        some send them separately, and some don't support mid-stream injection.
    """

    _injection_callback: InjectionCallback | None = None

    @property
    def steering_capability(self) -> SteeringCapability:
        """What kind of mid-stream steering this runner supports.

        Subclasses should override this to indicate their capability:
        - HYBRID_TURN: Can bundle tool_result + text in one message (Claude)
        - SEPARATE_MESSAGES: Tool result and user text are separate messages (OpenAI)
        - NO_MID_STREAM: Can't inject mid-stream; queued for later

        Returns:
            The steering capability of this runner
        """
        return SteeringCapability.NO_MID_STREAM  # Safe default

    def set_injection_callback(self, callback: InjectionCallback | None) -> None:
        """Set a callback to check for user messages to inject mid-stream.

        The callback is called after each tool execution completes.
        If it returns a string, that message is injected into the
        conversation before the next LLM call, allowing users to
        steer the conversation without cancelling.

        Args:
            callback: Async function returning message to inject, or None
                      to disable injection.
        """
        self._injection_callback = callback

    @abstractmethod
    async def stream_response(
        self,
        messages: list[Message],
        prompt: str,
        allowed_tools: list[str] | None = None,
        working_dir: str | None = None,
        disable_tools: bool = False,
    ) -> AsyncIterator[RunnerEvent]:
        """Stream a response from the LLM.

        Args:
            messages: Message history for context
            prompt: The new prompt to send
            allowed_tools: List of tool names to allow, or None for all
            working_dir: Working directory for file operations
            disable_tools: If True, disable all tools (for simple text responses)

        Yields:
            Events from the LLM (text deltas, tool use, results, etc.)
        """
        pass

    @abstractmethod
    def terminate(self) -> None:
        """Terminate any running request."""
        pass

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the runner is currently processing a request."""
        pass
