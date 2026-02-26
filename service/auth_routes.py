"""HTTP authentication routes.

This module provides REST API endpoints for user authentication
and management. These are served alongside the WebSocket endpoint
on the same port.

Endpoints:
    POST /auth/login - Authenticate and get JWT token
    POST /auth/refresh - Refresh an existing JWT token
    GET  /auth/me - Get current user info

Admin endpoints (require admin role):
    GET    /users - List all users
    POST   /users - Create a new user
    DELETE /users/{id} - Delete a user
    POST   /users/{id}/reset-password - Reset user's password
    POST   /users/{id}/disable - Disable user account
    POST   /users/{id}/enable - Enable user account
"""

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from aiohttp import web

if TYPE_CHECKING:
    from service.jwt_auth import JWTAuth
    from service.user_auth import UserAuthService

logger = logging.getLogger(__name__)


@dataclass
class AuthRoutes:
    """HTTP routes for authentication.

    This class manages auth-related HTTP endpoints and integrates
    with the UserAuthService and JWTAuth components.
    """

    user_service: "UserAuthService"
    jwt_auth: "JWTAuth"

    def register(self, app: web.Application) -> None:
        """Register routes with the aiohttp application.

        Args:
            app: The aiohttp web application
        """
        # Public auth endpoints
        app.router.add_post("/auth/login", self.handle_login)
        app.router.add_post("/auth/refresh", self.handle_refresh)
        app.router.add_get("/auth/me", self.handle_me)

        # Admin user management endpoints
        app.router.add_get("/users", self.handle_list_users)
        app.router.add_post("/users", self.handle_create_user)
        app.router.add_delete("/users/{user_id}", self.handle_delete_user)
        app.router.add_post(
            "/users/{user_id}/reset-password", self.handle_reset_password
        )
        app.router.add_post("/users/{user_id}/disable", self.handle_disable_user)
        app.router.add_post("/users/{user_id}/enable", self.handle_enable_user)

    async def _get_current_user(self, request: web.Request) -> Optional[dict]:
        """Extract and validate the current user from request.

        Args:
            request: The HTTP request

        Returns:
            User info dict if authenticated, None otherwise
        """
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]  # Strip "Bearer "
        try:
            claims = self.jwt_auth.validate_token(token)
            user = await self.user_service.get_user(claims.subject)
            if user and not user.disabled:
                return {
                    "id": user.id,
                    "username": user.username,
                    "role": user.role,
                }
        except Exception:
            pass
        return None

    async def _require_auth(self, request: web.Request) -> dict:
        """Require authentication, raising 401 if not authenticated.

        Args:
            request: The HTTP request

        Returns:
            User info dict

        Raises:
            web.HTTPUnauthorized: If not authenticated
        """
        user = await self._get_current_user(request)
        if not user:
            raise web.HTTPUnauthorized(
                text=json.dumps({"error": "Authentication required"}),
                content_type="application/json",
            )
        return user

    async def _require_admin(self, request: web.Request) -> dict:
        """Require admin role, raising 403 if not admin.

        Args:
            request: The HTTP request

        Returns:
            User info dict

        Raises:
            web.HTTPUnauthorized: If not authenticated
            web.HTTPForbidden: If not admin
        """
        user = await self._require_auth(request)
        if user["role"] != "admin":
            raise web.HTTPForbidden(
                text=json.dumps({"error": "Admin access required"}),
                content_type="application/json",
            )
        return user

    async def handle_login(self, request: web.Request) -> web.Response:
        """Handle login request.

        POST /auth/login
        Body: {"username": "...", "password": "..."}
        Response: {"token": "...", "user": {...}}
        """
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        username = data.get("username", "").strip()
        password = data.get("password", "")

        if not username or not password:
            return web.json_response(
                {"error": "Username and password required"}, status=400
            )

        try:
            from service.user_auth import (
                InvalidCredentialsError,
                UserDisabledError,
            )

            user = await self.user_service.authenticate(username, password)

            # Generate JWT token with user ID as subject
            token = self.jwt_auth.generate_token(
                subject=user.id,
                custom_claims={"username": user.username, "role": user.role},
            )

            logger.info(f"User logged in: {username}")
            return web.json_response(
                {
                    "token": token,
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "role": user.role,
                    },
                }
            )

        except InvalidCredentialsError:
            logger.warning(f"Failed login attempt for: {username}")
            return web.json_response(
                {"error": "Invalid username or password"}, status=401
            )
        except UserDisabledError:
            logger.warning(f"Disabled account login attempt: {username}")
            return web.json_response({"error": "Account is disabled"}, status=403)
        except Exception as e:
            logger.exception("Login error")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_refresh(self, request: web.Request) -> web.Response:
        """Handle token refresh request.

        POST /auth/refresh
        Headers: Authorization: Bearer <token>
        Response: {"token": "..."}
        """
        user = await self._require_auth(request)

        # Get full user to check if still active
        full_user = await self.user_service.get_user(user["id"])
        if not full_user or full_user.disabled:
            return web.json_response({"error": "Account is disabled"}, status=403)

        # Generate new token
        token = self.jwt_auth.generate_token(
            subject=user["id"],
            custom_claims={"username": user["username"], "role": user["role"]},
        )

        return web.json_response({"token": token})

    async def handle_me(self, request: web.Request) -> web.Response:
        """Get current user info.

        GET /auth/me
        Headers: Authorization: Bearer <token>
        Response: {"id": "...", "username": "...", "role": "..."}
        """
        user = await self._require_auth(request)
        return web.json_response(user)

    async def handle_list_users(self, request: web.Request) -> web.Response:
        """List all users (admin only).

        GET /users
        Response: {"users": [...]}
        """
        await self._require_admin(request)

        users = await self.user_service.list_users()
        return web.json_response(
            {
                "users": [
                    {
                        "id": u.id,
                        "username": u.username,
                        "role": u.role,
                        "disabled": u.disabled,
                        "created_at": u.created_at.isoformat(),
                        "last_login": u.last_login.isoformat() if u.last_login else None,
                    }
                    for u in users
                ]
            }
        )

    async def handle_create_user(self, request: web.Request) -> web.Response:
        """Create a new user (admin only).

        POST /users
        Body: {"username": "...", "password": "...", "role": "user|admin"}
        Response: {"user": {...}}
        """
        admin = await self._require_admin(request)

        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        username = data.get("username", "").strip()
        password = data.get("password", "")
        role = data.get("role", "user")

        if not username or not password:
            return web.json_response(
                {"error": "Username and password required"}, status=400
            )

        if role not in ("admin", "user"):
            return web.json_response(
                {"error": "Role must be 'admin' or 'user'"}, status=400
            )

        try:
            from service.user_auth import UsernameExistsError

            user = await self.user_service.create_user(
                username=username,
                password=password,
                role=role,
                created_by=admin["id"],
            )

            logger.info(f"Admin {admin['username']} created user: {username}")
            return web.json_response(
                {
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "role": user.role,
                        "disabled": user.disabled,
                        "created_at": user.created_at.isoformat(),
                    }
                },
                status=201,
            )

        except UsernameExistsError:
            return web.json_response(
                {"error": f"Username '{username}' already exists"}, status=409
            )
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_delete_user(self, request: web.Request) -> web.Response:
        """Delete a user (admin only).

        DELETE /users/{user_id}
        Response: {"deleted": true}
        """
        admin = await self._require_admin(request)
        user_id = request.match_info["user_id"]

        # Prevent self-deletion
        if user_id == admin["id"]:
            return web.json_response(
                {"error": "Cannot delete your own account"}, status=400
            )

        try:
            from service.user_auth import UserNotFoundError

            user = await self.user_service.get_user(user_id)
            if user:
                logger.info(
                    f"Admin {admin['username']} deleting user: {user.username}"
                )
            await self.user_service.delete_user(user_id)
            return web.json_response({"deleted": True})

        except UserNotFoundError:
            return web.json_response({"error": "User not found"}, status=404)

    async def handle_reset_password(self, request: web.Request) -> web.Response:
        """Reset a user's password (admin only).

        POST /users/{user_id}/reset-password
        Body: {"password": "..."}
        Response: {"reset": true}
        """
        admin = await self._require_admin(request)
        user_id = request.match_info["user_id"]

        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        new_password = data.get("password", "")
        if not new_password:
            return web.json_response({"error": "Password required"}, status=400)

        try:
            from service.user_auth import UserNotFoundError

            user = await self.user_service.get_user(user_id)
            if user:
                logger.info(
                    f"Admin {admin['username']} reset password for: {user.username}"
                )
            await self.user_service.update_password(user_id, new_password)
            return web.json_response({"reset": True})

        except UserNotFoundError:
            return web.json_response({"error": "User not found"}, status=404)

    async def handle_disable_user(self, request: web.Request) -> web.Response:
        """Disable a user account (admin only).

        POST /users/{user_id}/disable
        Response: {"disabled": true}
        """
        admin = await self._require_admin(request)
        user_id = request.match_info["user_id"]

        # Prevent self-disable
        if user_id == admin["id"]:
            return web.json_response(
                {"error": "Cannot disable your own account"}, status=400
            )

        try:
            from service.user_auth import UserNotFoundError

            user = await self.user_service.get_user(user_id)
            if user:
                logger.info(
                    f"Admin {admin['username']} disabled user: {user.username}"
                )
            await self.user_service.set_disabled(user_id, True)
            return web.json_response({"disabled": True})

        except UserNotFoundError:
            return web.json_response({"error": "User not found"}, status=404)

    async def handle_enable_user(self, request: web.Request) -> web.Response:
        """Enable a user account (admin only).

        POST /users/{user_id}/enable
        Response: {"enabled": true}
        """
        admin = await self._require_admin(request)
        user_id = request.match_info["user_id"]

        try:
            from service.user_auth import UserNotFoundError

            user = await self.user_service.get_user(user_id)
            if user:
                logger.info(f"Admin {admin['username']} enabled user: {user.username}")
            await self.user_service.set_disabled(user_id, False)
            return web.json_response({"enabled": True})

        except UserNotFoundError:
            return web.json_response({"error": "User not found"}, status=404)
