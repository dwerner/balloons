"""Domain RPC Service - Exposes domain @ws_expose methods to WebSocket clients.

This service acts as a bridge between the WebSocket RPC system and domain plugins.
When a domain is loaded, its @ws_expose methods are registered for direct RPC access.

Usage:
    # In domain:
    class ChartsDomain(DecoratedStatefulDomain):
        @ws_expose
        @llm_callable
        async def chart_delete(self, chart_id: str, session=None) -> ToolResult:
            '''Delete a chart. Callable by both LLM and UI.'''
            ...

    # From UI (via generated client):
    await client.domains.chartDelete({ chartId: "abc123", sessionId: "..." })

The service:
1. Scans loaded domains for @ws_expose methods
2. Builds a dispatch table mapping wire names to domain methods
3. Handles RPC calls by routing to the appropriate domain method
4. Converts ToolResult to JSON-serializable response
"""

from typing import Any, TYPE_CHECKING
import asyncio

from codegen.ws_expose import ws_service, ws_expose, MethodSpec
from core.debug_log import debug_log, Category

if TYPE_CHECKING:
    from session import Session


@ws_service
class DomainRpcService:
    """WebSocket RPC service for domain plugin methods.

    This service dynamically exposes domain methods marked with @ws_expose.
    Methods are registered when domains are loaded and unregistered when unloaded.
    """

    def __init__(self):
        self._domain_methods: dict[str, tuple[Any, str, str]] = {}  # wire_name -> (domain, method_name, domain_id)
        self._manager = None  # Set by headless.py

    def set_manager(self, manager: Any) -> None:
        """Set the session manager for session lookups."""
        self._manager = manager

    def register_domain(self, domain: Any) -> list[str]:
        """Register a domain's @ws_expose methods.

        Called when a domain is loaded. Returns list of registered wire names.
        """
        registered = []

        for attr_name in dir(domain.__class__):
            if attr_name.startswith("_"):
                continue

            attr = getattr(domain.__class__, attr_name, None)
            if attr is None:
                continue

            # Check for @ws_expose decorator
            if hasattr(attr, "_ws_method_spec"):
                spec: MethodSpec = attr._ws_method_spec
                wire_name = spec.wire_name

                # Store mapping: wire_name -> (domain_instance, method_name, domain_id)
                self._domain_methods[wire_name] = (domain, attr_name, domain.id)
                registered.append(wire_name)

                debug_log.info(
                    f"Registered domain RPC: {wire_name} -> {domain.id}.{attr_name}",
                    category=Category.API,
                )

        return registered

    def unregister_domain(self, domain_id: str) -> list[str]:
        """Unregister a domain's methods.

        Called when a domain is unloaded. Returns list of unregistered wire names.
        """
        to_remove = [
            wire_name
            for wire_name, (_, _, d_id) in self._domain_methods.items()
            if d_id == domain_id
        ]

        for wire_name in to_remove:
            del self._domain_methods[wire_name]
            debug_log.info(
                f"Unregistered domain RPC: {wire_name}",
                category=Category.API,
            )

        return to_remove

    @ws_expose
    async def call_domain_method(
        self,
        method_name: str,
        session_id: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a domain method by wire name.

        This is the generic dispatch endpoint. The generated client will also
        create typed methods for each registered domain method.

        Args:
            method_name: The camelCase wire name of the method
            session_id: The session ID for context
            params: Method parameters

        Returns:
            {result: str} on success, {error: str} on failure
        """
        debug_log.info(
            f"call_domain_method: {method_name}",
            category=Category.API,
            details={
                "session": session_id[:8] if session_id else None,
                "params": params,
                "registered_methods": list(self._domain_methods.keys()),
            },
        )
        if method_name not in self._domain_methods:
            return {"error": f"Unknown domain method: {method_name}"}

        domain, attr_name, domain_id = self._domain_methods[method_name]

        # Get session
        if self._manager is None:
            return {"error": "Service not initialized"}

        session = self._manager._manager.get_session(session_id)
        if session is None:
            return {"error": f"Session not found: {session_id}"}

        try:
            method = getattr(domain, attr_name)
            params = params or {}

            # Call the domain method
            result = await method(session=session, **params)

            # Handle ToolResult
            if hasattr(result, "result") and hasattr(result, "is_error"):
                if result.is_error:
                    return {"error": result.result}
                return {"result": result.result}

            # Handle JSON-serializable types directly
            if isinstance(result, (dict, list, str, int, float, bool, type(None))):
                return result

            # Fallback to string conversion
            return {"result": str(result)}

        except Exception as e:
            debug_log.error(
                f"Domain RPC call failed: {method_name}: {e}",
                category=Category.API,
            )
            return {"error": str(e)}

    def get_registered_methods(self) -> list[dict[str, str]]:
        """Get list of registered domain methods for introspection."""
        return [
            {
                "wireName": wire_name,
                "domainId": domain_id,
                "methodName": method_name,
            }
            for wire_name, (_, method_name, domain_id) in self._domain_methods.items()
        ]
