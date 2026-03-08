"""Base domain protocol and types.

Defines the interface that all domains must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TYPE_CHECKING
from enum import Enum

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
class DomainEvent:
    """Event emitted by or sent to a domain.

    Events are the primary mechanism for inter-domain communication.
    For example, a chess domain might emit "move_made" events that
    an agent domain can react to.
    """

    type: str  # e.g., "move_made", "game_over", "error"
    source_domain: str  # Domain ID that emitted this event
    payload: dict[str, Any] = field(default_factory=dict)
    target_session: str | None = None  # Optional: specific session to route to


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
        """Return static system prompt fragment.

        This is injected into the system prompt when the domain is loaded.
        Should document the available tools and how to use them.
        """
        return ""

    def get_context(self, session: "Session") -> str | None:
        """Return dynamic per-session context.

        Called before each LLM turn. Returns context that should be
        injected based on current session state (e.g., current chess
        position, game status).

        Returns:
            Context string to inject, or None if no context needed
        """
        return None

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
