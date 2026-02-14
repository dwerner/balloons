"""WebSocket server with service dispatch.

This module implements a WebSocket server that:
1. Accepts WebSocket connections from clients
2. Routes JSON-RPC requests to appropriate services based on the method name
3. Broadcasts events from services to connected clients

Wire Protocol (from ws_expose_design.md):

Request Format (Client -> Server):
    {"id": "uuid", "method": "getSession", "params": {"sessionId": "abc123"}}

Response Format (Server -> Client):
    {"id": "uuid", "result": {...}}  # Success
    {"id": "uuid", "error": {"code": -32600, "message": "..."}}  # Error

Event Format (Server -> Client):
    {"event": "sessionUpdated", "data": {...}}

Standard JSON-RPC error codes:
    -32700: Parse error
    -32600: Invalid request
    -32601: Method not found
    -32602: Invalid params
    -32603: Internal error

Usage:
    from service import TreeStateService, SessionManagerService
    from service.ws_server import WsServer

    # Create services
    tree_service = TreeStateService(tree_state)
    session_service = SessionManagerService(session_manager)

    # Create and start server
    server = WsServer(host="localhost", port=8765)
    server.register_service(tree_service)
    server.register_service(session_service)

    await server.start()
    # ... later ...
    await server.stop()
"""

import asyncio
import json
import logging
import ssl
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Protocol, TYPE_CHECKING
from weakref import WeakSet

from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosed

from codegen.ws_expose import WsExposeRegistry, to_snake_case, MethodSpec

if TYPE_CHECKING:
    from config import WebSocketConfig

logger = logging.getLogger(__name__)


# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass
class ServiceRegistration:
    """A registered service instance with its method specs."""

    instance: Any  # The service instance
    service_name: str  # Class name (e.g., "TreeStateService")
    wire_name: str  # camelCase name (e.g., "treeStateService")
    methods: dict[str, MethodSpec]  # wire_name -> MethodSpec


@dataclass
class ConnectedClient:
    """Represents a connected WebSocket client."""

    websocket: ServerConnection
    client_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subscriptions: set[str] = field(default_factory=set)  # Event patterns subscribed to


class WsServer:
    """WebSocket server with JSON-RPC dispatch to services.

    The server routes incoming requests to registered service methods and
    broadcasts events from services to connected clients.

    Method routing:
    - Methods can be called by their wire name directly: "getSession"
    - Or qualified with service: "TreeStateService.getSession"
    - If multiple services have the same method, qualified names are required

    Event broadcasting:
    - All events from registered services are broadcast to all clients
    - Future: Support subscription filtering
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8765,
        ping_interval: float = 20.0,
        ping_timeout: float = 20.0,
        config: "WebSocketConfig | None" = None,
    ):
        """Initialize the WebSocket server.

        Args:
            host: Host to bind to (overridden by config if provided)
            port: Port to bind to (overridden by config if provided)
            ping_interval: Interval for WebSocket ping/pong (seconds)
            ping_timeout: Timeout for ping response (seconds)
            config: WebSocketConfig object (if provided, overrides host/port)
        """
        # Config takes precedence over individual arguments
        if config:
            self.host = config.host
            self.port = config.port
            self._tls_enabled = config.tls.enabled
            self._tls_cert_path = config.tls.get_cert_path()
            self._tls_key_path = config.tls.get_key_path()
        else:
            self.host = host
            self.port = port
            self._tls_enabled = False
            self._tls_cert_path = None
            self._tls_key_path = None

        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout

        # Service registry: method wire_name -> (service_registration, method_spec)
        self._services: dict[str, ServiceRegistration] = {}
        self._method_dispatch: dict[str, tuple[ServiceRegistration, MethodSpec]] = {}
        self._qualified_dispatch: dict[str, tuple[ServiceRegistration, MethodSpec]] = {}

        # Connected clients
        self._clients: WeakSet[ServerConnection] = WeakSet()
        self._client_info: dict[ServerConnection, ConnectedClient] = {}

        # Server state
        self._server: Any = None  # Server type from websockets.asyncio.server
        self._running = False
        self._ssl_context: ssl.SSLContext | None = None

    def register_service(self, service_instance: Any) -> None:
        """Register a service instance for dispatch.

        The service must be decorated with @ws_service. All @ws_expose methods
        will be made available for RPC calls.

        Args:
            service_instance: Instance of a @ws_service decorated class

        Raises:
            ValueError: If service class is not decorated with @ws_service
        """
        service_cls = type(service_instance)

        # Check for @ws_service decorator
        if not hasattr(service_cls, "_ws_service_spec"):
            raise ValueError(
                f"Service {service_cls.__name__} must be decorated with @ws_service"
            )

        spec = service_cls._ws_service_spec
        service_name = spec.name
        wire_name = spec.wire_name

        # Build method lookup
        methods: dict[str, MethodSpec] = {}
        for method_spec in spec.methods:
            methods[method_spec.wire_name] = method_spec

        registration = ServiceRegistration(
            instance=service_instance,
            service_name=service_name,
            wire_name=wire_name,
            methods=methods,
        )

        self._services[service_name] = registration

        # Register dispatch routes
        for method_wire_name, method_spec in methods.items():
            # Qualified name: "TreeStateService.getSession"
            qualified_name = f"{service_name}.{method_wire_name}"
            self._qualified_dispatch[qualified_name] = (registration, method_spec)

            # Short name (if not already taken)
            if method_wire_name not in self._method_dispatch:
                self._method_dispatch[method_wire_name] = (registration, method_spec)
            else:
                # Collision - remove short name, require qualified
                logger.warning(
                    f"Method name collision: {method_wire_name} exists in multiple services. "
                    f"Use qualified names like {qualified_name}"
                )
                # Keep the first one registered (or could clear it)

        # Wire up event handler
        if hasattr(service_instance, "add_event_handler"):
            service_instance.add_event_handler(self._on_service_event)

        logger.info(
            f"Registered service {service_name} with {len(methods)} methods: "
            f"{list(methods.keys())}"
        )

    def _on_service_event(self, event_name: str, data: dict) -> None:
        """Handle events from services and broadcast to clients.

        This is called by services when they emit events. The event is
        formatted and broadcast to all connected clients.

        Args:
            event_name: Event name in camelCase (e.g., "sessionUpdated")
            data: Event payload data
        """
        message = {"event": event_name, "data": data}
        asyncio.create_task(self._broadcast(message))

    async def _broadcast(self, message: dict) -> None:
        """Broadcast a message to all connected clients.

        Args:
            message: Message dict to JSON-encode and send
        """
        if not self._clients:
            return

        message_str = json.dumps(message)

        # Send to all clients concurrently
        tasks = []
        for websocket in list(self._clients):
            tasks.append(self._send_to_client(websocket, message_str))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_to_client(
        self, websocket: ServerConnection, message: str
    ) -> None:
        """Send a message to a specific client.

        Args:
            websocket: The client's websocket connection
            message: Pre-encoded JSON message string
        """
        try:
            await websocket.send(message)
        except ConnectionClosed:
            # Client disconnected, will be cleaned up
            pass
        except Exception as e:
            logger.warning(f"Failed to send to client: {e}")

    def _create_ssl_context(self) -> ssl.SSLContext | None:
        """Create an SSL context for TLS connections.

        Returns:
            SSLContext configured for the server, or None if TLS not enabled.

        Raises:
            ValueError: If TLS enabled but cert/key files not found.
        """
        if not self._tls_enabled:
            return None

        if not self._tls_cert_path or not self._tls_key_path:
            raise ValueError("TLS enabled but cert_path or key_path not configured")

        if not self._tls_cert_path.exists():
            raise ValueError(f"Certificate file not found: {self._tls_cert_path}")
        if not self._tls_key_path.exists():
            raise ValueError(f"Key file not found: {self._tls_key_path}")

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(
            certfile=str(self._tls_cert_path),
            keyfile=str(self._tls_key_path),
        )
        return ssl_context

    async def start(self) -> None:
        """Start the WebSocket server.

        This starts the server listening for connections. Use stop() to shut down.

        Raises:
            ValueError: If TLS enabled but certificates not found.
        """
        if self._running:
            logger.warning("Server already running")
            return

        # Create SSL context if TLS enabled
        self._ssl_context = self._create_ssl_context()

        self._server = await serve(
            self._handle_connection,
            self.host,
            self.port,
            ping_interval=self.ping_interval,
            ping_timeout=self.ping_timeout,
            ssl=self._ssl_context,
        )
        self._running = True

        scheme = "wss" if self._tls_enabled else "ws"
        logger.info(f"WebSocket server started on {scheme}://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the WebSocket server.

        Closes all client connections and stops accepting new ones.
        """
        if not self._running:
            return

        self._running = False

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Clear client tracking
        self._clients.clear()
        self._client_info.clear()

        logger.info("WebSocket server stopped")

    async def _handle_connection(self, websocket: ServerConnection) -> None:
        """Handle a new WebSocket connection.

        This is the main handler for each client connection. It receives
        messages, dispatches them to services, and sends responses.

        Args:
            websocket: The client's websocket connection
        """
        client = ConnectedClient(websocket=websocket)
        self._clients.add(websocket)
        self._client_info[websocket] = client

        # Get remote address safely
        remote = websocket.remote_address
        if remote:
            client_addr = f"{remote[0]}:{remote[1]}"
        else:
            client_addr = "unknown"
        logger.info(f"Client connected: {client.client_id} from {client_addr}")

        try:
            async for message in websocket:
                response = await self._handle_message(message, client)
                if response:
                    await websocket.send(json.dumps(response))
        except ConnectionClosed as e:
            logger.info(
                f"Client {client.client_id} disconnected: "
                f"code={e.code}, reason={e.reason or 'none'}"
            )
        except Exception as e:
            logger.error(f"Error handling client {client.client_id}: {e}")
        finally:
            # Cleanup
            self._clients.discard(websocket)
            self._client_info.pop(websocket, None)

    async def _handle_message(
        self, message: str, client: ConnectedClient
    ) -> dict | None:
        """Handle an incoming message from a client.

        Parses the JSON-RPC request and dispatches to the appropriate service method.

        Args:
            message: Raw message string from client
            client: The client info

        Returns:
            Response dict to send back, or None if no response needed
        """
        # Parse JSON
        try:
            request = json.loads(message)
        except json.JSONDecodeError as e:
            return self._error_response(None, PARSE_ERROR, f"Parse error: {e}")

        # Validate request structure
        if not isinstance(request, dict):
            return self._error_response(None, INVALID_REQUEST, "Request must be object")

        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if not method:
            return self._error_response(request_id, INVALID_REQUEST, "Missing 'method'")

        if not isinstance(method, str):
            return self._error_response(
                request_id, INVALID_REQUEST, "'method' must be string"
            )

        if params is not None and not isinstance(params, dict):
            return self._error_response(
                request_id, INVALID_REQUEST, "'params' must be object or null"
            )

        # Dispatch to service
        try:
            result = await self._dispatch_method(method, params or {})
            return self._success_response(request_id, result)
        except MethodNotFoundError as e:
            return self._error_response(request_id, METHOD_NOT_FOUND, str(e))
        except InvalidParamsError as e:
            return self._error_response(request_id, INVALID_PARAMS, str(e))
        except Exception as e:
            logger.exception(f"Error dispatching method {method}")
            return self._error_response(request_id, INTERNAL_ERROR, str(e))

    async def _dispatch_method(self, method_name: str, params: dict) -> Any:
        """Dispatch a method call to the appropriate service.

        Args:
            method_name: Method name (qualified or short)
            params: Method parameters (wire names, camelCase)

        Returns:
            Method result

        Raises:
            MethodNotFoundError: If method not found
            InvalidParamsError: If parameters invalid
        """
        # Try qualified name first (ServiceName.methodName)
        dispatch_entry = self._qualified_dispatch.get(method_name)

        # Fall back to short name
        if not dispatch_entry:
            dispatch_entry = self._method_dispatch.get(method_name)

        if not dispatch_entry:
            available = list(self._method_dispatch.keys())
            raise MethodNotFoundError(
                f"Method '{method_name}' not found. Available: {available}"
            )

        registration, method_spec = dispatch_entry

        # Convert params from wire names (camelCase) to Python names (snake_case)
        python_params = {}
        for wire_name, value in params.items():
            python_name = to_snake_case(wire_name)
            python_params[python_name] = value

        # Validate required params
        for param_spec in method_spec.params:
            if param_spec.required and param_spec.name not in python_params:
                raise InvalidParamsError(
                    f"Missing required parameter: {param_spec.wire_name}"
                )

        # Get the method from the service instance
        method = getattr(registration.instance, method_spec.name, None)
        if not method:
            raise MethodNotFoundError(
                f"Method {method_spec.name} not found on service instance"
            )

        # Call the method
        if method_spec.is_async:
            result = await method(**python_params)
        else:
            result = method(**python_params)

        # Serialize result
        return self._serialize_result(result)

    def _serialize_result(self, result: Any) -> Any:
        """Serialize a method result to JSON-compatible format.

        Handles dataclasses by converting to dicts with camelCase keys.

        Args:
            result: The method return value

        Returns:
            JSON-serializable value
        """
        if result is None:
            return None

        # Handle dataclasses
        if hasattr(result, "__dataclass_fields__"):
            from codegen.ws_expose import to_camel_case

            return {
                to_camel_case(k): self._serialize_result(v)
                for k, v in result.__dict__.items()
            }

        # Handle lists
        if isinstance(result, list):
            return [self._serialize_result(item) for item in result]

        # Handle tuples (convert to list)
        if isinstance(result, tuple):
            return [self._serialize_result(item) for item in result]

        # Handle dicts
        if isinstance(result, dict):
            from codegen.ws_expose import to_camel_case

            return {
                to_camel_case(k) if isinstance(k, str) else k: self._serialize_result(v)
                for k, v in result.items()
            }

        # Handle enums
        if hasattr(result, "value"):
            return result.value

        # Primitives pass through
        return result

    def _success_response(self, request_id: Any, result: Any) -> dict:
        """Build a success response.

        Args:
            request_id: The request ID to echo back
            result: The method result

        Returns:
            Response dict
        """
        return {"id": request_id, "result": result}

    def _error_response(self, request_id: Any, code: int, message: str) -> dict:
        """Build an error response.

        Args:
            request_id: The request ID to echo back (may be None)
            code: JSON-RPC error code
            message: Error message

        Returns:
            Response dict
        """
        return {"id": request_id, "error": {"code": code, "message": message}}

    @property
    def client_count(self) -> int:
        """Get the number of connected clients."""
        return len(self._clients)

    @property
    def tls_enabled(self) -> bool:
        """Check if TLS is enabled for this server."""
        return self._tls_enabled

    @property
    def url(self) -> str:
        """Get the WebSocket URL for this server."""
        scheme = "wss" if self._tls_enabled else "ws"
        return f"{scheme}://{self.host}:{self.port}"

    def get_registered_methods(self) -> list[str]:
        """Get list of all registered method names (wire format)."""
        return list(self._method_dispatch.keys())

    def get_registered_services(self) -> list[str]:
        """Get list of all registered service names."""
        return list(self._services.keys())


class MethodNotFoundError(Exception):
    """Raised when a requested method is not found."""

    pass


class InvalidParamsError(Exception):
    """Raised when method parameters are invalid."""

    pass


# Convenience function to create and start a server
async def create_server(
    services: list[Any],
    host: str = "localhost",
    port: int = 8765,
    config: "WebSocketConfig | None" = None,
) -> WsServer:
    """Create and start a WebSocket server with the given services.

    Args:
        services: List of service instances to register
        host: Host to bind to (ignored if config provided)
        port: Port to bind to (ignored if config provided)
        config: WebSocketConfig object (if provided, overrides host/port)

    Returns:
        The started WsServer instance
    """
    if config:
        server = WsServer(config=config)
    else:
        server = WsServer(host=host, port=port)

    for service in services:
        server.register_service(service)

    await server.start()
    return server
