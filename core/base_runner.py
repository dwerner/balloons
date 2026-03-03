"""Base runner interface for LLM backends."""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Union, Callable, Awaitable

from models import (
    Message, TextDelta, ResultEvent, InitEvent, RawEvent,
    ToolUseStartEvent, ToolInputDeltaEvent, ToolUseEvent, ToolResultEvent,
)


# Type alias for all possible events yielded by runners
RunnerEvent = Union[
    TextDelta, ResultEvent, InitEvent, RawEvent,
    ToolUseStartEvent, ToolInputDeltaEvent, ToolUseEvent, ToolResultEvent,
]

# Type alias for injection callback: returns message to inject or None
InjectionCallback = Callable[[], Awaitable[str | None]]


class BaseRunner(ABC):
    """Abstract base class for all LLM runners.

    All runners must implement stream_response() and terminate().

    Mid-Stream Injection:
        Runners support injecting user messages mid-stream for steering.
        Use set_injection_callback() to provide a callback that returns
        queued user messages. The callback is checked after tool execution,
        allowing users to steer the conversation without cancelling.
    """

    _injection_callback: InjectionCallback | None = None

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
