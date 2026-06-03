"""Base domain protocol and types.

Defines the interface that all domains must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TYPE_CHECKING, Sequence
from enum import Enum

# Re-export DomainEvent from the new events module for backwards compatibility
from .events import DomainEvent, payload_to_dict, RawPayload

if TYPE_CHECKING:
    from session import Session


@dataclass
class ToolDef:
    """Tool definition in OpenAI function calling format.

    This is the structure used by OpenAI-compatible APIs for function calling.
    """

    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai_format(self) -> dict:
        """Convert to OpenAI API format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolResult:
    """Result from executing a domain tool.

    Includes both the result string for the LLM and any events
    that should be emitted.
    """

    result: str
    is_error: bool = False
    events: list[DomainEvent] = field(default_factory=list)


class Domain(ABC):
    """Abstract base class for all domains.

    A domain is a coherent state space with its own persistence,
    mutation rules, and LLM interface. Domains compose via events.

    Lifecycle:
        1. __init__() - Called when domain module is loaded
        2. on_load(runtime) - Called when domain is registered with runtime
        3. get_tools/get_prompt/etc. - Called during session setup
        4. handle_tool() - Called when LLM invokes a domain tool
        5. handle_event() - Called when events are routed to this domain
        6. on_unload() - Called when domain is unregistered

    Examples:
        - Chess domain: Pure game rules, validates moves, emits game events
        - Agent domain: LLM + prompt, handles tool results, emits requests
        - File domain: Filesystem state, handles read/write/search
    """

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique identifier for this domain (e.g., 'chess', 'agent')."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for this domain."""
        ...

    @property
    def version(self) -> str:
        """Semantic version of this domain."""
        return "0.1.0"

    @property
    def dependencies(self) -> list[str]:
        """List of domain IDs this domain depends on."""
        return []

    # Tool Interface
    @abstractmethod
    def get_tools(self) -> list[ToolDef]:
        """Return tool definitions for the LLM.

        These tools will be available when this domain is loaded.
        Tool names should be prefixed with the domain ID to avoid
        conflicts (e.g., 'chess_move', 'chess_resign').
        """
        ...

    @abstractmethod
    async def handle_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        session: "Session",
    ) -> ToolResult:
        """Execute a tool call from the LLM.

        Args:
            tool_name: Name of the tool (without domain prefix)
            params: Tool parameters from the LLM
            session: Current session context

        Returns:
            ToolResult with result string and optional events
        """
        ...

    # Prompt Interface
    def get_prompt(self) -> str:
        """Return domain-level system prompt fragment.

        This is injected into the system prompt when the domain is loaded.
        It should describe domain-wide concepts and context, not per-tool usage.
        Tool-specific usage/help belongs in tool-level prompt fragments.
        """
        return ""

    def get_tool_prompts(self, enabled_tools: Sequence[str] | None = None) -> dict[str, str]:
        """Return tool-level prompt fragments keyed by tool name.

        Domains using decorator-based tools can override this automatically.
        The enabled_tools filter is optional and lets domains return only the
        prompts relevant to the currently selected tool set.
        """
        return {}

    # Event Interface
    async def handle_event(
        self,
        event: DomainEvent,
        session: "Session",
    ) -> list[DomainEvent]:
        """Handle an event from another domain.

        Events are the primary mechanism for inter-domain communication.
        For example, when a chess move is made, the chess domain emits
        a 'move_made' event. Other domains (like an agent observing the
        game) can react to this.

        Args:
            event: The event to handle
            session: Session context

        Returns:
            List of new events to emit (can be empty)
        """
        return []

    # UI Interface
    def get_ui_config(self) -> dict | None:
        """Return UI configuration for this domain.

        Specifies React components to load and how they integrate
        with the Balloons UI.

        Returns:
            Dict with:
                - 'components': List of component definitions
                - 'tabs': Optional tabs to add to the UI
                - 'panels': Optional sidebar panels
            Or None if no UI components
        """
        return None

    # Lifecycle
    def on_load(self, runtime: Any) -> None:
        """Called when domain is registered with the runtime.

        Use this to:
            - Initialize database connections
            - Set up file watchers
            - Connect to external services
        """
        pass

    def on_unload(self) -> None:
        """Called when domain is unregistered.

        Use this to:
            - Close database connections
            - Stop file watchers
            - Clean up resources
        """
        pass


class StatefulDomain(Domain):
    """Domain with per-session state persistence.

    Extends Domain with methods for saving/loading session-scoped state.
    Use this when your domain needs to maintain state across turns
    (e.g., chess position, conversation context).

    State flows:
    - Tool results push state changes via events
    - `get_state()` returns current state on demand (reconnection, explicit sync)
    - `save_state()`/`load_state()` handle persistence
    """

    @abstractmethod
    async def save_state(self, session: "Session") -> dict[str, Any]:
        """Serialize domain state for a session.

        Called when session is saved. Return a JSON-serializable dict.
        """
        ...

    @abstractmethod
    async def load_state(self, session: "Session", state: dict[str, Any]) -> None:
        """Deserialize domain state for a session.

        Called when session is loaded. Restore internal state from dict.
        """
        ...

    async def clear_state(self, session: "Session") -> None:
        """Clear domain state for a session.

        Called when session is reset or domain is unloaded from session.
        """
        pass

    async def get_state(self, session: "Session") -> dict[str, Any] | None:
        """Return current domain state for a session.

        Called when:
        - A client requests state sync (e.g., on reconnection)
        - Session starts and needs initial state

        The service layer wraps this in a DomainEvent for WebSocket broadcast.

        Args:
            session: The session to get state for

        Returns:
            State dict, or None if no state available
        """
        return None


def _dispatch_llm_tool(domain: Any, tool_name: str, params: dict[str, Any], session: "Session") -> "ToolResult":
    """Shared dispatch logic for decorated domains.

    Returns the coroutine to await, or raises ValueError if tool not found.
    """
    # Look for a method with matching _llm_callable_spec
    for attr_name in dir(domain.__class__):
        if attr_name.startswith("_"):
            continue

        attr = getattr(domain.__class__, attr_name, None)
        if attr is None:
            continue

        if hasattr(attr, "_llm_callable_spec"):
            spec = attr._llm_callable_spec
            if spec.name == tool_name:
                # Get the bound method
                method = getattr(domain, attr_name)
                return method, params

    raise ValueError(f"Unknown tool: {tool_name}")


class DecoratedDomain(Domain):
    """Domain that uses @llm_callable decorators for tools.

    Subclass this instead of Domain to use decorator-based tool definitions.
    Tools are automatically collected from @llm_callable methods, and
    handle_tool() dispatches to the appropriate method.

    Example:
        from plugins.base import DecoratedDomain, ToolResult
        from plugins.decorators import llm_callable, Param

        class MyDomain(DecoratedDomain):
            @property
            def id(self) -> str:
                return "my_domain"

            @property
            def name(self) -> str:
                return "My Domain"

            @llm_callable
            async def my_tool(self, value: str, session: "Session") -> ToolResult:
                '''Do something with value.'''
                return ToolResult(f"Got: {value}")

    No need to override get_tools() or handle_tool() - they're automatic!
    """

    def get_tools(self) -> list[ToolDef]:
        """Automatically collect tools from @llm_callable methods."""
        from .decorators import collect_llm_tools
        return collect_llm_tools(self.__class__)

    def get_tool_prompts(self, enabled_tools: Sequence[str] | None = None) -> dict[str, str]:
        """Automatically collect tool-level prompts from @llm_callable methods."""
        from .decorators import collect_llm_tool_prompts
        prompts = collect_llm_tool_prompts(self.__class__)
        if enabled_tools is None:
            return prompts
        enabled = set(enabled_tools)
        return {name: prompt for name, prompt in prompts.items() if name in enabled}

    async def handle_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        session: "Session",
    ) -> ToolResult:
        """Automatically dispatch to @llm_callable handler."""
        try:
            method, params = _dispatch_llm_tool(self, tool_name, params, session)
        except ValueError as e:
            return ToolResult(str(e), is_error=True)

        try:
            return await method(session=session, **params)
        except TypeError as e:
            # Handle missing required arguments gracefully
            error_msg = str(e)
            if "missing" in error_msg and "argument" in error_msg:
                return ToolResult(f"Missing required parameter: {error_msg}", is_error=True)
            raise  # Re-raise other TypeErrors


class DecoratedStatefulDomain(StatefulDomain):
    """StatefulDomain that uses @llm_callable decorators for tools.

    Same as DecoratedDomain but extends StatefulDomain for domains
    that need state persistence.

    Example:
        class ChartsDomain(DecoratedStatefulDomain):
            @llm_callable
            async def chart_create(self, name: str, session: "Session") -> ToolResult:
                '''Create a chart.'''
                ...

            async def get_state(self, session: "Session") -> dict | None:
                ...

            async def save_state(self, session: "Session") -> dict:
                ...

            async def load_state(self, session: "Session", state: dict) -> None:
                ...
    """

    def get_tools(self) -> list[ToolDef]:
        """Automatically collect tools from @llm_callable methods."""
        from .decorators import collect_llm_tools
        return collect_llm_tools(self.__class__)

    def get_tool_prompts(self, enabled_tools: Sequence[str] | None = None) -> dict[str, str]:
        """Automatically collect tool-level prompts from @llm_callable methods."""
        from .decorators import collect_llm_tool_prompts
        prompts = collect_llm_tool_prompts(self.__class__)
        if enabled_tools is None:
            return prompts
        enabled = set(enabled_tools)
        return {name: prompt for name, prompt in prompts.items() if name in enabled}

    async def handle_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        session: "Session",
    ) -> ToolResult:
        """Automatically dispatch to @llm_callable handler."""
        try:
            method, params = _dispatch_llm_tool(self, tool_name, params, session)
        except ValueError as e:
            return ToolResult(str(e), is_error=True)

        try:
            return await method(session=session, **params)
        except TypeError as e:
            # Handle missing required arguments gracefully
            error_msg = str(e)
            if "missing" in error_msg and "argument" in error_msg:
                return ToolResult(f"Missing required parameter: {error_msg}", is_error=True)
            raise  # Re-raise other TypeErrors
