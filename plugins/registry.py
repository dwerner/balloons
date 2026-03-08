"""Domain registry for loading and managing domains.

The registry is responsible for:
- Discovering and loading domain modules
- Managing domain lifecycle (load/unload)
- Aggregating tools and prompts from all loaded domains
- Routing tool calls and events to appropriate domains
"""

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .base import Domain, DomainEvent, ToolDef, ToolResult

if TYPE_CHECKING:
    from session import Session


class DomainRegistry:
    """Registry for managing domain plugins.

    The registry maintains a collection of loaded domains and provides
    methods for aggregating their tools, prompts, and handling their
    tool calls and events.

    Example:
        registry = DomainRegistry()
        registry.load_domain("chess")
        registry.load_domain("music")

        # Get all tools for LLM
        tools = registry.get_all_tools()

        # Execute a tool call
        result = await registry.execute_tool("chess_move", {"move": "e4"}, session)
    """

    def __init__(self, plugins_dir: Path | None = None):
        """Initialize the registry.

        Args:
            plugins_dir: Directory containing domain plugins.
                        Defaults to the 'plugins' directory next to this file.
        """
        if plugins_dir is None:
            plugins_dir = Path(__file__).parent
        self.plugins_dir = plugins_dir
        self._domains: dict[str, Domain] = {}
        self._tool_to_domain: dict[str, str] = {}  # tool_name -> domain_id

    @property
    def loaded_domains(self) -> list[str]:
        """List of currently loaded domain IDs."""
        return list(self._domains.keys())

    def get_domain(self, domain_id: str) -> Domain | None:
        """Get a loaded domain by ID."""
        return self._domains.get(domain_id)

    def load_domain(self, domain_id: str, runtime: Any = None) -> Domain:
        """Load a domain by ID.

        Looks for a domain module in the plugins directory.
        The module should define a `create_domain()` function that
        returns a Domain instance.

        Args:
            domain_id: ID of the domain to load (e.g., 'chess')
            runtime: Optional runtime context passed to on_load()

        Returns:
            The loaded Domain instance

        Raises:
            ValueError: If domain is already loaded
            ModuleNotFoundError: If domain module not found
            AttributeError: If module doesn't define create_domain()
        """
        if domain_id in self._domains:
            raise ValueError(f"Domain '{domain_id}' is already loaded")

        # Look for domain module
        domain_dir = self.plugins_dir / domain_id
        domain_module_path = domain_dir / "domain.py"

        if not domain_module_path.exists():
            # Try flat module (plugins/{domain_id}.py)
            domain_module_path = self.plugins_dir / f"{domain_id}.py"

        if not domain_module_path.exists():
            raise ModuleNotFoundError(f"Domain module not found: {domain_id}")

        # Load the module
        spec = importlib.util.spec_from_file_location(
            f"plugins.{domain_id}.domain",
            domain_module_path,
        )
        if spec is None or spec.loader is None:
            raise ModuleNotFoundError(f"Failed to load domain module: {domain_id}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        # Get the domain instance - check for create_domain in domain.py
        # or fall back to package __init__.py
        if not hasattr(module, "create_domain"):
            # Try the package __init__.py
            init_path = domain_dir / "__init__.py"
            if init_path.exists():
                init_spec = importlib.util.spec_from_file_location(
                    f"plugins.{domain_id}",
                    init_path,
                )
                if init_spec and init_spec.loader:
                    init_module = importlib.util.module_from_spec(init_spec)
                    sys.modules[init_spec.name] = init_module
                    init_spec.loader.exec_module(init_module)
                    if hasattr(init_module, "create_domain"):
                        module = init_module

            if not hasattr(module, "create_domain"):
                raise AttributeError(
                    f"Domain module '{domain_id}' must define create_domain() function"
                )

        domain = module.create_domain()
        if not isinstance(domain, Domain):
            raise TypeError(
                f"create_domain() must return a Domain instance, got {type(domain)}"
            )

        # Check dependencies
        for dep_id in domain.dependencies:
            if dep_id not in self._domains:
                # Auto-load dependencies
                self.load_domain(dep_id, runtime)

        # Register tools
        for tool in domain.get_tools():
            if tool.name in self._tool_to_domain:
                existing = self._tool_to_domain[tool.name]
                raise ValueError(
                    f"Tool name conflict: '{tool.name}' defined by both "
                    f"'{existing}' and '{domain_id}'"
                )
            self._tool_to_domain[tool.name] = domain_id

        # Register domain
        self._domains[domain_id] = domain

        # Call lifecycle hook
        domain.on_load(runtime)

        return domain

    def unload_domain(self, domain_id: str) -> None:
        """Unload a domain.

        Calls the domain's on_unload() method and removes it from the registry.

        Args:
            domain_id: ID of the domain to unload

        Raises:
            ValueError: If domain is not loaded
            ValueError: If other domains depend on this one
        """
        if domain_id not in self._domains:
            raise ValueError(f"Domain '{domain_id}' is not loaded")

        # Check if any loaded domains depend on this one
        for other_id, other_domain in self._domains.items():
            if domain_id in other_domain.dependencies:
                raise ValueError(
                    f"Cannot unload '{domain_id}': '{other_id}' depends on it"
                )

        domain = self._domains[domain_id]

        # Unregister tools
        for tool in domain.get_tools():
            del self._tool_to_domain[tool.name]

        # Call lifecycle hook
        domain.on_unload()

        # Remove domain
        del self._domains[domain_id]

    def reload_domain(self, domain_id: str, runtime: Any = None) -> Domain:
        """Reload a domain (hot reload for development).

        Unloads and reloads the domain, picking up any code changes.

        Args:
            domain_id: ID of the domain to reload
            runtime: Optional runtime context passed to on_load()

        Returns:
            The reloaded Domain instance
        """
        if domain_id in self._domains:
            self.unload_domain(domain_id)

        # Clear cached module
        module_name = f"plugins.{domain_id}.domain"
        if module_name in sys.modules:
            del sys.modules[module_name]

        return self.load_domain(domain_id, runtime)

    # Tool Aggregation

    def get_all_tools(self) -> list[dict]:
        """Get all tools from all loaded domains in OpenAI format.

        Returns:
            List of tool definitions in OpenAI function calling format
        """
        tools = []
        for domain in self._domains.values():
            for tool in domain.get_tools():
                tools.append(tool.to_openai_format())
        return tools

    def get_all_tool_defs(self) -> list[ToolDef]:
        """Get all tool definitions from all loaded domains.

        Returns:
            List of ToolDef objects
        """
        tools = []
        for domain in self._domains.values():
            tools.extend(domain.get_tools())
        return tools

    def get_tool_names(self) -> set[str]:
        """Get all tool names from all loaded domains."""
        return set(self._tool_to_domain.keys())

    def is_domain_tool(self, tool_name: str) -> bool:
        """Check if a tool belongs to a loaded domain."""
        return tool_name in self._tool_to_domain

    def handles_tool(self, tool_name: str) -> bool:
        """Check if this provider handles a given tool (ToolProvider protocol)."""
        return self.is_domain_tool(tool_name)

    # Alias for ToolProvider protocol compatibility
    def get_tools(self) -> list[dict]:
        """Get all tools (ToolProvider protocol)."""
        return self.get_all_tools()

    def get_prompt(self) -> str:
        """Get combined prompts (PromptProvider protocol)."""
        return self.get_all_prompts()

    def get_context(self, session: "Session") -> str | None:
        """Get combined context (PromptProvider protocol)."""
        context = self.get_all_context(session)
        return context if context else None

    # Prompt Aggregation

    def get_all_prompts(self) -> str:
        """Get combined prompt fragments from all loaded domains.

        Returns:
            Combined prompt string with sections for each domain
        """
        parts = []
        for domain_id, domain in self._domains.items():
            prompt = domain.get_prompt()
            if prompt:
                parts.append(f"## {domain.name} Domain\n\n{prompt}")
        return "\n\n".join(parts)

    def get_all_context(self, session: "Session") -> str:
        """Get combined dynamic context from all loaded domains.

        Args:
            session: Current session

        Returns:
            Combined context string
        """
        parts = []
        for domain in self._domains.values():
            context = domain.get_context(session)
            if context:
                parts.append(context)
        return "\n\n".join(parts)

    # Tool Execution

    async def execute_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        session: "Session",
    ) -> ToolResult | None:
        """Execute a domain tool.

        Routes the tool call to the appropriate domain based on the tool name.

        Args:
            tool_name: Name of the tool to execute
            params: Tool parameters
            session: Current session

        Returns:
            ToolResult from the domain, or None if tool not found
        """
        domain_id = self._tool_to_domain.get(tool_name)
        if domain_id is None:
            return None

        domain = self._domains[domain_id]
        return await domain.handle_tool(tool_name, params, session)

    async def execute_tool_as_provider(
        self,
        tool_name: str,
        params: dict[str, Any],
        session: "Session",
        working_dir: str,
    ) -> tuple[str, bool]:
        """Execute a tool (ToolProvider protocol).

        This method matches the ToolProvider protocol signature for
        integration with the main tool executor.

        Args:
            tool_name: Name of the tool to execute
            params: Tool parameters
            session: Current session
            working_dir: Working directory (unused by domains)

        Returns:
            Tuple of (result_string, is_error)
        """
        result = await self.execute_tool(tool_name, params, session)
        if result is None:
            return f"Unknown domain tool: {tool_name}", True

        # Emit any events from the tool result to the session manager
        if result.events:
            print(f"[DomainRegistry] Emitting {len(result.events)} events for session {session.id}")
            await self._emit_events_to_session_manager(result.events, session)
        else:
            print(f"[DomainRegistry] No events to emit for {tool_name}")

        return result.result, result.is_error

    async def _emit_events_to_session_manager(
        self,
        events: list[DomainEvent],
        session: "Session",
    ) -> None:
        """Emit domain events through the session manager to WebSocket clients.

        This bridges the domain plugin event system to the Balloons WebSocket layer.
        """
        try:
            # Get the session manager service instance
            from service import get_session_manager_service
            session_manager = get_session_manager_service()
            if session_manager is None:
                return

            for event in events:
                await session_manager.emit_domain_event(
                    domain_id=event.source_domain,
                    event_type=event.type,
                    session_id=event.target_session or session.id,
                    data=event.payload,
                )
        except ImportError:
            # Session manager not available (e.g., in tests)
            pass
        except Exception as e:
            # Log but don't fail the tool execution
            print(f"Warning: Failed to emit domain event: {e}")

    # Event Routing

    async def route_event(
        self,
        event: DomainEvent,
        session: "Session",
    ) -> list[DomainEvent]:
        """Route an event to all interested domains.

        Each domain's handle_event() is called, and any resulting events
        are collected and returned.

        Args:
            event: Event to route
            session: Current session

        Returns:
            List of new events emitted by domains
        """
        new_events = []
        for domain in self._domains.values():
            if domain.id == event.source_domain:
                continue  # Don't route to source domain
            events = await domain.handle_event(event, session)
            new_events.extend(events)
        return new_events

    async def emit_event(
        self,
        event: DomainEvent,
        session: "Session",
    ) -> list[DomainEvent]:
        """Emit an event and process all resulting events.

        Routes the event and recursively processes any events emitted
        in response, until no new events are generated.

        Args:
            event: Event to emit
            session: Current session

        Returns:
            All events generated (including the original)
        """
        all_events = [event]
        pending = [event]

        # Prevent infinite loops
        max_iterations = 100
        iteration = 0

        while pending and iteration < max_iterations:
            iteration += 1
            event = pending.pop(0)
            new_events = await self.route_event(event, session)
            all_events.extend(new_events)
            pending.extend(new_events)

        return all_events


# Global registry instance
_registry: DomainRegistry | None = None


def get_registry() -> DomainRegistry:
    """Get the global domain registry."""
    global _registry
    if _registry is None:
        _registry = DomainRegistry()
    return _registry


def set_registry(registry: DomainRegistry) -> None:
    """Set the global domain registry."""
    global _registry
    _registry = registry
