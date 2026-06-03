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
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from .base import Domain, DomainEvent, StatefulDomain, ToolDef, ToolResult
from .events import payload_to_dict

if TYPE_CHECKING:
    from session import Session


# Type alias for the event emitter callback
EventEmitter = Callable[[str, str, str, dict[str, Any]], Awaitable[None]]
"""Callback signature: (domain_id, event_type, session_id, payload_dict) -> None"""


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

    def __init__(
        self,
        plugins_dir: Path | None = None,
        event_emitter: EventEmitter | None = None,
    ):
        """Initialize the registry.

        Args:
            plugins_dir: Directory containing domain plugins.
                        Defaults to the 'plugins' directory next to this file.
            event_emitter: Optional callback for emitting events to the service layer.
                          Signature: (domain_id, event_type, session_id, payload_dict) -> None
                          If not provided, events are emitted via the service locator
                          (backwards compatible behavior).
        """
        if plugins_dir is None:
            plugins_dir = Path(__file__).parent
        self.plugins_dir = plugins_dir
        self._domains: dict[str, Domain] = {}
        self._tool_to_domain: dict[str, str] = {}  # tool_name -> domain_id
        self._event_emitter = event_emitter
        self._rpc_service: Any = None  # DomainRpcService for @ws_expose methods

    def set_rpc_service(self, rpc_service: Any) -> None:
        """Set the RPC service for domain method exposure.

        When set, domains with @ws_expose methods will have them registered
        for direct WebSocket RPC access.

        Args:
            rpc_service: DomainRpcService instance
        """
        self._rpc_service = rpc_service
        # Register any already-loaded domains
        for domain in self._domains.values():
            rpc_service.register_domain(domain)

    def set_event_emitter(self, emitter: EventEmitter | None) -> None:
        """Set the event emitter callback.

        This allows setting the emitter after construction, which is useful
        when the registry is created before the service layer is initialized.

        Args:
            emitter: Callback for emitting events, or None to use service locator
        """
        self._event_emitter = emitter

    @property
    def loaded_domains(self) -> list[str]:
        """List of currently loaded domain IDs."""
        return list(self._domains.keys())

    @property
    def available_domains(self) -> list[str]:
        """List of all available domain IDs (loaded or not).

        Discovers domains by looking for:
        - plugins/{domain}/domain.py
        - plugins/{domain}/__init__.py with create_domain()
        """
        domains = []
        if not self.plugins_dir.exists():
            return domains

        for item in self.plugins_dir.iterdir():
            if not item.is_dir():
                continue
            # Check for domain.py
            if (item / "domain.py").exists():
                domains.append(item.name)
            # Or __init__.py with create_domain
            elif (item / "__init__.py").exists():
                init_file = item / "__init__.py"
                try:
                    content = init_file.read_text()
                    if "def create_domain" in content:
                        domains.append(item.name)
                except Exception:
                    pass
        return sorted(domains)

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

        # Register @ws_expose methods with RPC service
        if self._rpc_service is not None:
            self._rpc_service.register_domain(domain)

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

        # Unregister @ws_expose methods from RPC service
        if self._rpc_service is not None:
            self._rpc_service.unregister_domain(domain_id)

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

    # Prompt Aggregation

    def get_all_prompts(self) -> str:
        """Get combined domain-level prompt fragments from all loaded domains."""
        parts = []
        for domain_id, domain in self._domains.items():
            prompt = domain.get_prompt()
            if prompt:
                parts.append(f"## {domain.name} Domain\n\n{prompt}")
        return "\n\n".join(parts)

    def get_all_tool_prompts(self, enabled_tools: list[str] | None = None) -> str:
        """Get combined tool-level prompt fragments from all loaded domains.

        Only prompts for enabled tools are included when enabled_tools is provided.
        Order follows the provided enabled_tools list where possible.
        """
        enabled_order = list(enabled_tools) if enabled_tools is not None else None
        enabled_set = set(enabled_order) if enabled_order is not None else None

        prompt_map: dict[str, tuple[str, str]] = {}
        for domain in self._domains.values():
            for tool_name, prompt in domain.get_tool_prompts(enabled_order).items():
                if not prompt:
                    continue
                if enabled_set is not None and tool_name not in enabled_set:
                    continue
                prompt_map[tool_name] = (domain.name, prompt)

        parts: list[str] = []
        if enabled_order is not None:
            for tool_name in enabled_order:
                item = prompt_map.get(tool_name)
                if item is None:
                    continue
                domain_name, prompt = item
                parts.append(f"### {tool_name} ({domain_name})\n\n{prompt}")
        else:
            for tool_name in sorted(prompt_map):
                domain_name, prompt = prompt_map[tool_name]
                parts.append(f"### {tool_name} ({domain_name})\n\n{prompt}")

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
        """Emit domain events through the configured event emitter.

        This bridges the domain plugin event system to the Balloons WebSocket layer.
        If no event emitter is configured, event forwarding is skipped.
        """
        emitter = self._event_emitter
        if emitter is None:
            return

        for event in events:
            session_id = event.target_session or session.id
            payload_dict = payload_to_dict(event.payload)

            try:
                await emitter(
                    event.source_domain,
                    event.type,
                    session_id,
                    payload_dict,
                )
            except Exception as e:
                print(f"Warning: Event emitter failed: {e}")

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

    # State Sync

    async def get_state(
        self,
        domain_id: str,
        session: "Session",
    ) -> dict[str, Any] | None:
        """Get current state from a stateful domain.

        This allows core services to request domain state without knowing
        about domain internals. The service layer wraps the result in a
        DomainEvent for WebSocket broadcast.

        Args:
            domain_id: ID of the domain to query
            session: Session to get state for

        Returns:
            State dict, or None if domain not found or has no state
        """
        domain = self._domains.get(domain_id)
        if domain is None:
            return None

        if not isinstance(domain, StatefulDomain):
            return None

        return await domain.get_state(session)


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
