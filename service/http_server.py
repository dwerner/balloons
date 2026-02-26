"""HTTP server for authentication endpoints.

This module provides an HTTP server that handles:
- HTTP requests for authentication (login, token refresh)
- Health check endpoint

WebSocket connections are handled separately by WsServer.
The client gets a JWT from this server, then connects to WsServer with the token.
"""

import asyncio
import logging
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from aiohttp import web

if TYPE_CHECKING:
    from config import WebSocketConfig, AuthConfig
    from service.auth_routes import AuthRoutes
    from service.jwt_auth import JWTAuth
    from service.user_auth import UserAuthService

logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """Configuration for the combined HTTP/WS server."""

    host: str
    port: int
    tls_enabled: bool
    tls_cert_path: Optional[Path]
    tls_key_path: Optional[Path]


class HttpAuthServer:
    """HTTP server for authentication endpoints.

    This server handles:
    - HTTPS requests for /auth/* endpoints (login, token refresh)
    - Health check endpoint

    WebSocket connections are handled separately by WsServer.
    """

    def __init__(
        self,
        config: ServerConfig,
        auth_routes: "AuthRoutes",
        jwt_auth: "JWTAuth",
    ):
        """Initialize the server.

        Args:
            config: Server configuration
            auth_routes: HTTP routes for authentication
            jwt_auth: JWT authentication handler
        """
        self.config = config
        self._auth_routes = auth_routes
        self._jwt_auth = jwt_auth

        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._running = False

    def _create_ssl_context(self) -> Optional[ssl.SSLContext]:
        """Create SSL context for TLS.

        Returns:
            SSLContext if TLS configured, None otherwise.

        Raises:
            ValueError: If TLS paths don't exist.
        """
        if not self.config.tls_enabled:
            return None

        cert_path = self.config.tls_cert_path
        key_path = self.config.tls_key_path

        if not cert_path or not cert_path.exists():
            raise ValueError(f"Certificate file not found: {cert_path}")
        if not key_path or not key_path.exists():
            raise ValueError(f"Key file not found: {key_path}")

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(
            certfile=str(cert_path),
            keyfile=str(key_path),
        )
        return ssl_context

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({"status": "ok"})

    async def start(self) -> None:
        """Start the server."""
        if self._running:
            logger.warning("Server already running")
            return

        # Create aiohttp app
        self._app = web.Application()

        # Add CORS middleware for browser clients
        self._app.middlewares.append(self._cors_middleware)

        # Register auth routes
        self._auth_routes.register(self._app)

        # Health check
        self._app.router.add_get("/health", self._handle_health)

        # Create SSL context
        ssl_context = self._create_ssl_context()

        # Start server
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(
            self._runner,
            self.config.host,
            self.config.port,
            ssl_context=ssl_context,
        )
        await self._site.start()

        self._running = True
        scheme = "https" if self.config.tls_enabled else "http"
        logger.info(f"Server started on {scheme}://{self.config.host}:{self.config.port}")

    async def stop(self) -> None:
        """Stop the server."""
        if not self._running:
            return

        self._running = False

        if self._site:
            await self._site.stop()
            self._site = None

        if self._runner:
            await self._runner.cleanup()
            self._runner = None

        self._app = None
        logger.info("Server stopped")

    @web.middleware
    async def _cors_middleware(
        self, request: web.Request, handler: Any
    ) -> web.Response:
        """CORS middleware for browser clients.

        Allows cross-origin requests for the React frontend.
        """
        # Handle preflight requests
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            try:
                response = await handler(request)
            except web.HTTPException as e:
                response = e

        # Add CORS headers
        origin = request.headers.get("Origin", "*")
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = (
            "GET, POST, PUT, DELETE, OPTIONS"
        )
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization"
        )
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Max-Age"] = "86400"

        return response

    @property
    def url(self) -> str:
        """Get the server URL."""
        scheme = "https" if self.config.tls_enabled else "http"
        return f"{scheme}://{self.config.host}:{self.config.port}"

async def create_http_auth_server(
    ws_config: "WebSocketConfig",
    user_service: "UserAuthService",
) -> HttpAuthServer:
    """Create and configure the HTTP auth server.

    Args:
        ws_config: WebSocket configuration (for host/port/tls settings)
        user_service: User authentication service

    Returns:
        Configured HttpAuthServer instance
    """
    from service.jwt_auth import JWTAuth, JWTConfig as JWTAuthConfig
    from service.auth_routes import AuthRoutes

    # Create JWT auth
    jwt_config = JWTAuthConfig(
        enabled=ws_config.jwt.enabled,
        secret=ws_config.jwt.secret,
        expiration_seconds=ws_config.jwt.expiration_seconds,
    )
    jwt_auth = JWTAuth(jwt_config)

    # Create auth routes
    auth_routes = AuthRoutes(
        user_service=user_service,
        jwt_auth=jwt_auth,
    )

    # Create server config
    server_config = ServerConfig(
        host=ws_config.host,
        port=ws_config.port,
        tls_enabled=ws_config.tls.enabled,
        tls_cert_path=ws_config.tls.get_cert_path(),
        tls_key_path=ws_config.tls.get_key_path(),
    )

    # Create server
    server = HttpAuthServer(
        config=server_config,
        auth_routes=auth_routes,
        jwt_auth=jwt_auth,
    )

    return server
