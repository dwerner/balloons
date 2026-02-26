"""User authentication and management.

This module provides password hashing, user CRUD operations, and
authentication logic for the Balloons server.

Password hashing uses argon2id (memory-hard, secure against GPU attacks).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class User:
    """Domain model for a user."""

    id: str
    username: str
    password_hash: str
    role: str  # "admin" | "user"
    created_at: datetime
    created_by: Optional[str] = None
    last_login: Optional[datetime] = None
    disabled: bool = False


class PasswordHasher:
    """Handles password hashing and verification using argon2id."""

    def __init__(self):
        try:
            from argon2 import PasswordHasher as Argon2Hasher
            from argon2.exceptions import VerifyMismatchError

            self._hasher = Argon2Hasher()
            self._verify_error = VerifyMismatchError
        except ImportError:
            raise ImportError(
                "argon2-cffi is required for password hashing. "
                "Install it with: pip install argon2-cffi"
            )

    def hash(self, password: str) -> str:
        """Hash a password using argon2id.

        Args:
            password: Plain text password

        Returns:
            Hashed password string (includes algorithm parameters)
        """
        return self._hasher.hash(password)

    def verify(self, password: str, hash: str) -> bool:
        """Verify a password against a hash.

        Args:
            password: Plain text password to verify
            hash: The stored password hash

        Returns:
            True if password matches, False otherwise
        """
        try:
            self._hasher.verify(hash, password)
            return True
        except self._verify_error:
            return False

    def needs_rehash(self, hash: str) -> bool:
        """Check if a hash needs to be updated with new parameters.

        Args:
            hash: The stored password hash

        Returns:
            True if the hash should be regenerated
        """
        return self._hasher.check_needs_rehash(hash)


class UserAuthError(Exception):
    """Base exception for user authentication errors."""

    pass


class UserNotFoundError(UserAuthError):
    """Raised when a user is not found."""

    pass


class InvalidCredentialsError(UserAuthError):
    """Raised when username/password is incorrect."""

    pass


class UserDisabledError(UserAuthError):
    """Raised when a user account is disabled."""

    pass


class UsernameExistsError(UserAuthError):
    """Raised when trying to create a user with an existing username."""

    pass


class UserAuthService:
    """Service for user authentication and management.

    This service handles:
    - User creation with password hashing
    - Authentication (verify credentials, return user)
    - User listing, updates, and deletion
    - Admin bootstrap from config
    """

    def __init__(self, storage: "UserStorage"):
        """Initialize the user auth service.

        Args:
            storage: Storage backend for user data
        """
        self._storage = storage
        self._hasher = PasswordHasher()

    async def create_user(
        self,
        username: str,
        password: str,
        role: str = "user",
        created_by: Optional[str] = None,
    ) -> User:
        """Create a new user.

        Args:
            username: Unique username (case-insensitive)
            password: Plain text password (will be hashed)
            role: User role ("admin" or "user")
            created_by: ID of user creating this account (for audit)

        Returns:
            The created User

        Raises:
            UsernameExistsError: If username already exists
            ValueError: If role is invalid
        """
        if role not in ("admin", "user"):
            raise ValueError(f"Invalid role: {role}. Must be 'admin' or 'user'")

        # Normalize username
        username = username.lower().strip()
        if not username:
            raise ValueError("Username cannot be empty")

        # Check for existing user
        existing = await self._storage.get_by_username(username)
        if existing:
            raise UsernameExistsError(f"Username '{username}' already exists")

        # Create user
        now = datetime.now(timezone.utc)
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=self._hasher.hash(password),
            role=role,
            created_at=now,
            created_by=created_by,
        )

        await self._storage.save(user)
        logger.info(f"Created user: {username} (role={role})")
        return user

    async def authenticate(self, username: str, password: str) -> User:
        """Authenticate a user by username and password.

        Args:
            username: The username
            password: The password

        Returns:
            The authenticated User

        Raises:
            InvalidCredentialsError: If credentials are wrong
            UserDisabledError: If account is disabled
        """
        username = username.lower().strip()
        user = await self._storage.get_by_username(username)

        if not user:
            # Use constant-time comparison even for missing users
            self._hasher.hash("dummy-password")
            raise InvalidCredentialsError("Invalid username or password")

        if not self._hasher.verify(password, user.password_hash):
            raise InvalidCredentialsError("Invalid username or password")

        if user.disabled:
            raise UserDisabledError("Account is disabled")

        # Update last login
        user.last_login = datetime.now(timezone.utc)
        await self._storage.save(user)

        # Check if password needs rehash (algorithm parameters changed)
        if self._hasher.needs_rehash(user.password_hash):
            user.password_hash = self._hasher.hash(password)
            await self._storage.save(user)
            logger.info(f"Rehashed password for user: {username}")

        logger.info(f"User authenticated: {username}")
        return user

    async def get_user(self, user_id: str) -> Optional[User]:
        """Get a user by ID.

        Args:
            user_id: The user's ID

        Returns:
            The User if found, None otherwise
        """
        return await self._storage.get_by_id(user_id)

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get a user by username.

        Args:
            username: The username (case-insensitive)

        Returns:
            The User if found, None otherwise
        """
        return await self._storage.get_by_username(username.lower().strip())

    async def list_users(self) -> list[User]:
        """List all users.

        Returns:
            List of all users
        """
        return await self._storage.list_all()

    async def update_password(self, user_id: str, new_password: str) -> None:
        """Update a user's password.

        Args:
            user_id: The user's ID
            new_password: The new password (will be hashed)

        Raises:
            UserNotFoundError: If user doesn't exist
        """
        user = await self._storage.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User not found: {user_id}")

        user.password_hash = self._hasher.hash(new_password)
        await self._storage.save(user)
        logger.info(f"Password updated for user: {user.username}")

    async def set_disabled(self, user_id: str, disabled: bool) -> None:
        """Enable or disable a user account.

        Args:
            user_id: The user's ID
            disabled: True to disable, False to enable

        Raises:
            UserNotFoundError: If user doesn't exist
        """
        user = await self._storage.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User not found: {user_id}")

        user.disabled = disabled
        await self._storage.save(user)
        action = "disabled" if disabled else "enabled"
        logger.info(f"User {action}: {user.username}")

    async def delete_user(self, user_id: str) -> None:
        """Delete a user.

        Args:
            user_id: The user's ID

        Raises:
            UserNotFoundError: If user doesn't exist
        """
        user = await self._storage.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User not found: {user_id}")

        await self._storage.delete(user_id)
        logger.info(f"Deleted user: {user.username}")

    async def ensure_admin_exists(
        self,
        admin_username: str,
        admin_password: str,
    ) -> bool:
        """Ensure at least one admin user exists.

        If no users exist at all, creates an admin user with the
        provided credentials. This is used for bootstrap.

        Args:
            admin_username: Username for the admin account
            admin_password: Password for the admin account

        Returns:
            True if an admin was created, False if users already exist
        """
        users = await self._storage.list_all()
        if users:
            return False

        # No users exist - create admin
        await self.create_user(
            username=admin_username,
            password=admin_password,
            role="admin",
        )
        logger.warning(
            f"Created bootstrap admin user '{admin_username}'. "
            "Change the password immediately!"
        )
        return True

    async def user_count(self) -> int:
        """Get the total number of users.

        Returns:
            Number of users in the system
        """
        users = await self._storage.list_all()
        return len(users)


class UserStorage:
    """Abstract storage interface for users.

    Implementations can use LMDB, SQLite, or other backends.
    """

    async def get_by_id(self, user_id: str) -> Optional[User]:
        """Get a user by ID."""
        raise NotImplementedError

    async def get_by_username(self, username: str) -> Optional[User]:
        """Get a user by username (case-insensitive)."""
        raise NotImplementedError

    async def list_all(self) -> list[User]:
        """List all users."""
        raise NotImplementedError

    async def save(self, user: User) -> None:
        """Save a user (create or update)."""
        raise NotImplementedError

    async def delete(self, user_id: str) -> None:
        """Delete a user by ID."""
        raise NotImplementedError


class InMemoryUserStorage(UserStorage):
    """In-memory user storage for testing."""

    def __init__(self):
        self._users: dict[str, User] = {}
        self._by_username: dict[str, str] = {}  # username -> id

    async def get_by_id(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    async def get_by_username(self, username: str) -> Optional[User]:
        user_id = self._by_username.get(username.lower())
        if user_id:
            return self._users.get(user_id)
        return None

    async def list_all(self) -> list[User]:
        return list(self._users.values())

    async def save(self, user: User) -> None:
        self._users[user.id] = user
        self._by_username[user.username.lower()] = user.id

    async def delete(self, user_id: str) -> None:
        user = self._users.pop(user_id, None)
        if user:
            self._by_username.pop(user.username.lower(), None)
