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
    from service import SessionDataService, SessionManagerService
    from service.ws_server import WsServer

    # Create services
    session_data_service = SessionDataService(session_loader)
    session_manager_service = SessionManagerService(session_manager)

    # Create and start server
    server = WsServer(host="localhost", port=8765)
    server.register_service(session_data_service)
    server.register_service(session_manager_service)

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
    from config import WebSocketConfig, JWTConfig
    from service.jwt_auth import JWTAuth, TokenClaims

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
    service_name: str  # Class name (e.g., "SessionDataService")
    wire_name: str  # camelCase name (e.g., "sessionDataService")
    methods: dict[str, MethodSpec]  # wire_name -> MethodSpec


@dataclass
class ConnectedClient:
    """Represents a connected WebSocket client."""

    websocket: ServerConnection
    client_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subscriptions: set[str] = field(default_factory=set)  # Event patterns subscribed to
    authenticated: bool = False  # Whether client passed JWT auth
    token_subject: str | None = None  # Subject from JWT token (e.g., session ID)
    # Event queue for ordered delivery
    # Using asyncio.Queue ensures events are sent in FIFO order
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    queue_processor_task: asyncio.Task | None = field(default=None)


class WsServer:
    """WebSocket server with JSON-RPC dispatch to services.

    The server routes incoming requests to registered service methods and
    broadcasts events from services to connected clients.

    Method routing:
    - Methods can be called by their wire name directly: "getSession"
    - Or qualified with service: "SessionDataService.getSession"
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
            self._jwt_config = config.jwt
        else:
            self.host = host
            self.port = port
            self._tls_enabled = False
            self._tls_cert_path = None
            self._tls_key_path = None
            self._jwt_config = None

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

        # JWT auth handler (lazy initialized)
        self._jwt_auth: "JWTAuth | None" = None

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
            # Qualified name: "SessionDataService.getSession"
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

    def _notify_client_disconnected(self, client_id: str) -> None:
        """Notify all services that a client has disconnected.

        This allows services to clean up any client-specific state (e.g., subscriptions).

        Args:
            client_id: The disconnected client's ID
        """
        for registration in self._services.values():
            if hasattr(registration.instance, "client_disconnected"):
                try:
                    registration.instance.client_disconnected(client_id)
                except Exception as e:
                    logger.error(
                        f"Error notifying {registration.service_name} of client "
                        f"disconnect: {e}"
                    )

    def _on_service_event(
        self, event_name: str, data: dict, target_clients: set[str] | None = None
    ) -> None:
        """Handle events from services and broadcast to clients.

        This is called by services when they emit events. The event is
        formatted and sent to targeted clients (or all clients if no target specified).

        Args:
            event_name: Event name in camelCase (e.g., "sessionUpdated")
            data: Event payload data
            target_clients: Optional set of client_ids to send to. If None,
                broadcasts to all clients.
        """
        # Log history events at INFO level for debugging
        if "History" in event_name:
            logger.info(
                f"Service event: {event_name}, "
                f"targets: {target_clients if target_clients else 'all'}, "
                f"clients: {len(self._clients)}"
            )
        else:
            logger.debug(
                f"Service event: {event_name}, "
                f"targets: {len(target_clients) if target_clients else 'all'}, "
                f"clients: {len(self._clients)}"
            )
        # Convert data keys to camelCase for consistency with RPC responses
        camel_data = self._convert_keys_to_camel(data)
        message = {"event": event_name, "data": camel_data}
        asyncio.create_task(self._broadcast(message, target_clients))

    def _convert_keys_to_camel(self, data: Any) -> Any:
        """Convert dict keys from snake_case to camelCase recursively.

        Args:
            data: Dict, list, or primitive value

        Returns:
            Same structure with camelCase keys
        """
        from codegen.ws_expose import to_camel_case

        if isinstance(data, dict):
            return {
                to_camel_case(k): self._convert_keys_to_camel(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._convert_keys_to_camel(item) for item in data]
        else:
            return data

    def _enqueue_broadcast(
        self, message: dict, target_clients: set[str] | None = None
    ) -> None:
        """Enqueue a message for broadcast to connected clients.

        This method is synchronous and adds messages to per-client queues.
        The queue processor tasks send messages in FIFO order, ensuring
        streaming deltas arrive in correct order (fixes duplication bug).

        Args:
            message: Message dict to JSON-encode and send
            target_clients: Optional set of client_ids to send to. If None,
                broadcasts to all clients. If provided, only sends to clients
                whose client_id is in the set.
        """
        if not self._clients:
            return

        message_str = json.dumps(message)

        # Enqueue to each matching client's queue
        for websocket in list(self._clients):
            client_info = self._client_info.get(websocket)
            if client_info is None:
                continue

            # If target_clients is specified, only send to those clients
            if target_clients is not None and client_info.client_id not in target_clients:
                continue

            # Non-blocking enqueue (queue is unbounded)
            client_info.event_queue.put_nowait(message_str)

    async def _process_client_event_queue(self, client: ConnectedClient) -> None:
        """Process events from a client's queue and send them in order.

        This ensures events are sent in FIFO order, which is critical for
        streaming deltas to arrive in correct order.

        Args:
            client: The client whose queue to process
        """
        try:
            while True:
                # Wait for next message from queue
                message_str = await client.event_queue.get()
                try:
                    await client.websocket.send(message_str)
                except ConnectionClosed:
                    # Client disconnected, stop processing
                    break
                except Exception as e:
                    logger.warning(f"Error sending to client {client.client_id}: {e}")
                finally:
                    client.event_queue.task_done()
        except asyncio.CancelledError:
            # Normal shutdown
            pass

    async def _broadcast(
        self, message: dict, target_clients: set[str] | None = None
    ) -> None:
        """Broadcast a message to connected clients (legacy, uses queue).

        This method now delegates to _enqueue_broadcast for ordered delivery.

        Args:
            message: Message dict to JSON-encode and send
            target_clients: Optional set of client_ids to send to. If None,
                broadcasts to all clients. If provided, only sends to clients
                whose client_id is in the set.
        """
        self._enqueue_broadcast(message, target_clients)

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

    def _get_jwt_auth(self) -> "JWTAuth | None":
        """Get the JWT auth handler, creating it if needed.

        Returns:
            JWTAuth instance if JWT is configured and enabled, None otherwise.
        """
        if self._jwt_auth is not None:
            return self._jwt_auth

        if self._jwt_config is None or not self._jwt_config.enabled:
            return None

        # Lazy import to avoid circular dependency
        from service.jwt_auth import JWTAuth, JWTConfig as JWTAuthConfig

        # Convert config types
        auth_config = JWTAuthConfig(
            enabled=self._jwt_config.enabled,
            secret=self._jwt_config.secret,
            expiration_seconds=self._jwt_config.expiration_seconds,
        )
        self._jwt_auth = JWTAuth(auth_config)
        return self._jwt_auth

    def _extract_token_from_request(self, websocket: ServerConnection) -> str | None:
        """Extract JWT token from WebSocket connection request.

        Looks for token in:
        1. Query parameter: ws://host:port?token=<jwt>
        2. Subprotocol: Sec-WebSocket-Protocol: balloons.auth.<jwt>

        Args:
            websocket: The WebSocket connection

        Returns:
            Token string if found, None otherwise.
        """
        # Try query parameter first
        path = websocket.request.path if websocket.request else None
        if path and "?" in path:
            query_string = path.split("?", 1)[1]
            from urllib.parse import parse_qs

            params = parse_qs(query_string)
            tokens = params.get("token", [])
            if tokens:
                return tokens[0]

        # Try subprotocol
        subprotocols = websocket.subprotocol
        if subprotocols:
            # websockets library sets subprotocol to the selected one
            # We need to check the original request headers
            if hasattr(websocket.request, "headers"):
                proto_header = websocket.request.headers.get("Sec-WebSocket-Protocol", "")
                protos = [p.strip() for p in proto_header.split(",")]
                for proto in protos:
                    if proto.startswith("balloons.auth."):
                        return proto[len("balloons.auth.") :]

        return None

    async def _authenticate_connection(
        self, websocket: ServerConnection
    ) -> tuple[bool, str | None, str | None]:
        """Authenticate a WebSocket connection.

        Args:
            websocket: The WebSocket connection to authenticate

        Returns:
            Tuple of (authenticated, subject, error_message).
            If JWT is disabled, returns (True, None, None).
            If authenticated, returns (True, subject, None).
            If failed, returns (False, None, error_message).
        """
        jwt_auth = self._get_jwt_auth()
        if jwt_auth is None:
            # JWT disabled - allow all connections
            return (True, None, None)

        token = self._extract_token_from_request(websocket)
        if not token:
            return (False, None, "Authentication token required")

        try:
            claims = jwt_auth.validate_token(token)
            return (True, claims.subject, None)
        except Exception as e:
            return (False, None, str(e))

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
            max_size=50 * 1024 * 1024,  # 50MB max message size for image uploads
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

        This is the main handler for each client connection. It:
        1. Authenticates the connection (if JWT enabled)
        2. Receives messages and dispatches them to services
        3. Sends responses back to the client

        Args:
            websocket: The client's websocket connection
        """
        # Get remote address safely (for logging)
        remote = websocket.remote_address
        if remote:
            client_addr = f"{remote[0]}:{remote[1]}"
        else:
            client_addr = "unknown"

        # Authenticate the connection
        authenticated, subject, error = await self._authenticate_connection(websocket)
        if not authenticated:
            logger.warning(f"Authentication failed for {client_addr}: {error}")
            await websocket.close(4001, error or "Authentication failed")
            return

        # Create client record
        client = ConnectedClient(
            websocket=websocket,
            authenticated=authenticated,
            token_subject=subject,
        )
        self._clients.add(websocket)
        self._client_info[websocket] = client

        # Start the event queue processor for this client
        # This ensures events are sent in FIFO order (fixes streaming duplication bug)
        client.queue_processor_task = asyncio.create_task(
            self._process_client_event_queue(client)
        )

        if subject:
            logger.info(
                f"Client connected: {client.client_id} from {client_addr} "
                f"(subject: {subject})"
            )
        else:
            logger.info(f"Client connected: {client.client_id} from {client_addr}")

        # Send connected event with assigned clientId
        # This allows the client to use this ID for targeted subscriptions
        connected_event = {
            "event": "connected",
            "data": {
                "clientId": client.client_id,
                "subject": subject,  # session ID from JWT, if any
            }
        }
        await websocket.send(json.dumps(connected_event))

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
            # Stop the event queue processor
            if client.queue_processor_task and not client.queue_processor_task.done():
                client.queue_processor_task.cancel()
                try:
                    await client.queue_processor_task
                except asyncio.CancelledError:
                    pass
            # Cleanup
            self._clients.discard(websocket)
            self._client_info.pop(websocket, None)
            # Notify services about client disconnection
            self._notify_client_disconnected(client.client_id)

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

        # Handle built-in ping method for client heartbeat
        if method == "ping":
            import time
            return self._success_response(request_id, {"pong": True, "timestamp": time.time()})

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
            result = await self._dispatch_method(method, params or {}, client)
            return self._success_response(request_id, result)
        except MethodNotFoundError as e:
            return self._error_response(request_id, METHOD_NOT_FOUND, str(e))
        except InvalidParamsError as e:
            return self._error_response(request_id, INVALID_PARAMS, str(e))
        except Exception as e:
            logger.exception(f"Error dispatching method {method}")
            return self._error_response(request_id, INTERNAL_ERROR, str(e))

    async def _dispatch_method(
        self, method_name: str, params: dict, client: ConnectedClient
    ) -> Any:
        """Dispatch a method call to the appropriate service.

        Args:
            method_name: Method name (qualified or short)
            params: Method parameters (wire names, camelCase)
            client: The connected client making the request

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

        # Inject client_id for methods that accept it (if not already provided)
        # This allows subscription methods to know which client is subscribing
        if "client_id" not in python_params:
            for param_spec in method_spec.params:
                if param_spec.name == "client_id":
                    python_params["client_id"] = client.client_id
                    break

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

    @property
    def jwt_enabled(self) -> bool:
        """Check if JWT authentication is enabled."""
        return self._jwt_config is not None and self._jwt_config.enabled

    def generate_token(self, subject: str) -> str | None:
        """Generate a JWT token for a client.

        This is typically called by the TUI to get a token for connecting
        to the WebSocket server.

        Args:
            subject: The subject for the token (e.g., session ID)

        Returns:
            JWT token string, or None if JWT is not enabled.

        Raises:
            RuntimeError: If JWT is enabled but configuration is invalid.
        """
        jwt_auth = self._get_jwt_auth()
        if jwt_auth is None:
            return None
        return jwt_auth.generate_token(subject)



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
