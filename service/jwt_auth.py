"""JWT authentication for WebSocket connections.

This module provides JWT token generation and validation for authenticating
WebSocket clients. Tokens are generated when a TUI session starts and
validated on each WebSocket connection.

Usage:
    from service.jwt_auth import JWTAuth, JWTConfig

    # Create auth handler
    config = JWTConfig(secret="your-secret-key")
    auth = JWTAuth(config)

    # Generate token (TUI side)
    token = auth.generate_token(subject="session-123")

    # Validate token (server side)
    claims = auth.validate_token(token)
    if claims:
        print(f"Authenticated: {claims['sub']}")

Token format:
    - Standard JWT with HS256 signing
    - Required claims: sub (subject), exp (expiration), iat (issued at)
    - Optional claims: Can include custom data

Wire protocol:
    Clients authenticate by passing the token in the WebSocket handshake:
    - Query parameter: ws://host:port?token=<jwt>
    - Or subprotocol: Sec-WebSocket-Protocol: balloons.auth.<jwt>
"""

import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Error codes for authentication failures
AUTH_ERROR_MISSING_TOKEN = 4001
AUTH_ERROR_INVALID_TOKEN = 4002
AUTH_ERROR_EXPIRED_TOKEN = 4003


@dataclass
class JWTConfig:
    """JWT authentication configuration.

    Attributes:
        enabled: Whether JWT auth is required (if False, all connections allowed)
        secret: Secret key for signing tokens. If None, a random secret is generated.
        expiration_seconds: Token lifetime in seconds (default 24 hours)
        algorithm: JWT signing algorithm (default HS256)
        issuer: Optional issuer claim for tokens
    """

    enabled: bool = True
    secret: Optional[str] = None
    expiration_seconds: int = 86400  # 24 hours
    algorithm: str = "HS256"
    issuer: Optional[str] = "balloons"

    # Generated at runtime if secret is None
    _runtime_secret: str = field(default_factory=lambda: secrets.token_urlsafe(32))

    def get_secret(self) -> str:
        """Get the secret key, using runtime-generated one if not configured."""
        return self.secret or self._runtime_secret


@dataclass
class TokenClaims:
    """Validated token claims.

    Attributes:
        subject: The subject (sub) claim - typically session or user ID
        issued_at: When the token was issued (Unix timestamp)
        expires_at: When the token expires (Unix timestamp)
        issuer: The issuer (iss) claim
        custom: Any additional custom claims
    """

    subject: str
    issued_at: int
    expires_at: int
    issuer: Optional[str] = None
    custom: dict[str, Any] = field(default_factory=dict)


class JWTAuthError(Exception):
    """Base exception for JWT authentication errors."""

    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


class MissingTokenError(JWTAuthError):
    """Raised when no token is provided but auth is required."""

    def __init__(self, message: str = "Authentication token required"):
        super().__init__(message, AUTH_ERROR_MISSING_TOKEN)


class InvalidTokenError(JWTAuthError):
    """Raised when token is malformed or signature is invalid."""

    def __init__(self, message: str = "Invalid authentication token"):
        super().__init__(message, AUTH_ERROR_INVALID_TOKEN)


class ExpiredTokenError(JWTAuthError):
    """Raised when token has expired."""

    def __init__(self, message: str = "Authentication token expired"):
        super().__init__(message, AUTH_ERROR_EXPIRED_TOKEN)


class JWTAuth:
    """JWT authentication handler.

    Generates and validates JWT tokens for WebSocket authentication.
    """

    def __init__(self, config: JWTConfig):
        """Initialize JWT auth handler.

        Args:
            config: JWT configuration
        """
        self.config = config
        self._jwt: Any = None  # Lazy import

    def _get_jwt(self) -> Any:
        """Lazy import of jwt module."""
        if self._jwt is None:
            try:
                import jwt

                self._jwt = jwt
            except ImportError:
                raise ImportError(
                    "PyJWT is required for JWT authentication. "
                    "Install it with: pip install PyJWT"
                )
        return self._jwt

    def generate_token(
        self,
        subject: str,
        custom_claims: Optional[dict[str, Any]] = None,
        expiration_seconds: Optional[int] = None,
    ) -> str:
        """Generate a JWT token.

        Args:
            subject: The subject claim (e.g., session ID, user ID)
            custom_claims: Optional additional claims to include
            expiration_seconds: Override default expiration time

        Returns:
            Encoded JWT token string
        """
        jwt = self._get_jwt()

        now = int(time.time())
        exp_seconds = expiration_seconds or self.config.expiration_seconds

        payload = {
            "sub": subject,
            "iat": now,
            "exp": now + exp_seconds,
        }

        if self.config.issuer:
            payload["iss"] = self.config.issuer

        if custom_claims:
            payload.update(custom_claims)

        token = jwt.encode(
            payload, self.config.get_secret(), algorithm=self.config.algorithm
        )

        logger.debug(f"Generated JWT token for subject: {subject}")
        return token

    def validate_token(self, token: str) -> TokenClaims:
        """Validate a JWT token and extract claims.

        Args:
            token: The JWT token string to validate

        Returns:
            TokenClaims with validated claims

        Raises:
            InvalidTokenError: If token is malformed or signature invalid
            ExpiredTokenError: If token has expired
        """
        jwt = self._get_jwt()

        try:
            payload = jwt.decode(
                token,
                self.config.get_secret(),
                algorithms=[self.config.algorithm],
                options={
                    "require": ["sub", "exp", "iat"],
                },
            )
        except jwt.ExpiredSignatureError:
            raise ExpiredTokenError()
        except jwt.InvalidTokenError as e:
            raise InvalidTokenError(f"Invalid token: {e}")

        # Extract standard claims
        subject = payload.get("sub")
        issued_at = payload.get("iat")
        expires_at = payload.get("exp")
        issuer = payload.get("iss")

        # Everything else is custom claims
        custom = {
            k: v for k, v in payload.items() if k not in ("sub", "iat", "exp", "iss")
        }

        return TokenClaims(
            subject=subject,
            issued_at=issued_at,
            expires_at=expires_at,
            issuer=issuer,
            custom=custom,
        )

    def extract_token_from_query(self, query_string: str) -> Optional[str]:
        """Extract JWT token from query string.

        Args:
            query_string: URL query string (e.g., "token=xxx&other=yyy")

        Returns:
            Token string if found, None otherwise
        """
        from urllib.parse import parse_qs

        params = parse_qs(query_string)
        tokens = params.get("token", [])
        return tokens[0] if tokens else None

    def extract_token_from_subprotocol(
        self, subprotocols: list[str]
    ) -> Optional[str]:
        """Extract JWT token from WebSocket subprotocols.

        Looks for a subprotocol in the format: balloons.auth.<token>

        Args:
            subprotocols: List of requested subprotocols

        Returns:
            Token string if found, None otherwise
        """
        prefix = "balloons.auth."
        for proto in subprotocols:
            if proto.startswith(prefix):
                return proto[len(prefix) :]
        return None


def create_auth(config: Optional[JWTConfig] = None) -> JWTAuth:
    """Create a JWT auth handler with default or provided config.

    Args:
        config: Optional JWT config. If None, creates default config.

    Returns:
        Configured JWTAuth instance
    """
    if config is None:
        config = JWTConfig()
    return JWTAuth(config)
