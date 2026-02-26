"""Tests for user authentication service."""

import pytest
from datetime import datetime, timezone

from service.user_auth import (
    UserAuthService,
    User,
    PasswordHasher,
    InMemoryUserStorage,
    UserNotFoundError,
    InvalidCredentialsError,
    UserDisabledError,
    UsernameExistsError,
)


class TestPasswordHasher:
    """Tests for PasswordHasher."""

    def test_hash_password(self):
        """Test that hashing produces a valid argon2 hash."""
        hasher = PasswordHasher()
        password = "test-password-123"
        hash = hasher.hash(password)

        assert hash is not None
        assert hash.startswith("$argon2")
        assert hash != password

    def test_verify_correct_password(self):
        """Test that correct password verifies successfully."""
        hasher = PasswordHasher()
        password = "correct-password"
        hash = hasher.hash(password)

        assert hasher.verify(password, hash) is True

    def test_verify_wrong_password(self):
        """Test that wrong password fails verification."""
        hasher = PasswordHasher()
        hash = hasher.hash("correct-password")

        assert hasher.verify("wrong-password", hash) is False

    def test_different_hashes_for_same_password(self):
        """Test that same password produces different hashes (due to salt)."""
        hasher = PasswordHasher()
        password = "same-password"

        hash1 = hasher.hash(password)
        hash2 = hasher.hash(password)

        assert hash1 != hash2  # Different salts
        assert hasher.verify(password, hash1) is True
        assert hasher.verify(password, hash2) is True


class TestUserAuthService:
    """Tests for UserAuthService."""

    @pytest.fixture
    def storage(self):
        """Create in-memory storage for testing."""
        return InMemoryUserStorage()

    @pytest.fixture
    def service(self, storage):
        """Create auth service with test storage."""
        return UserAuthService(storage)

    @pytest.mark.asyncio
    async def test_create_user(self, service):
        """Test creating a new user."""
        user = await service.create_user(
            username="testuser",
            password="test-password",
            role="user",
        )

        assert user.id is not None
        assert user.username == "testuser"
        assert user.role == "user"
        assert user.password_hash.startswith("$argon2")
        assert user.disabled is False

    @pytest.mark.asyncio
    async def test_create_user_normalizes_username(self, service):
        """Test that username is normalized (lowercase, trimmed)."""
        user = await service.create_user(
            username="  TestUser  ",
            password="password",
        )

        assert user.username == "testuser"

    @pytest.mark.asyncio
    async def test_create_admin_user(self, service):
        """Test creating an admin user."""
        user = await service.create_user(
            username="admin",
            password="admin-pass",
            role="admin",
        )

        assert user.role == "admin"

    @pytest.mark.asyncio
    async def test_create_user_duplicate_username(self, service):
        """Test that duplicate usernames are rejected."""
        await service.create_user("testuser", "password1")

        with pytest.raises(UsernameExistsError):
            await service.create_user("testuser", "password2")

    @pytest.mark.asyncio
    async def test_create_user_duplicate_case_insensitive(self, service):
        """Test that usernames are unique case-insensitively."""
        await service.create_user("TestUser", "password1")

        with pytest.raises(UsernameExistsError):
            await service.create_user("testuser", "password2")

    @pytest.mark.asyncio
    async def test_create_user_invalid_role(self, service):
        """Test that invalid roles are rejected."""
        with pytest.raises(ValueError, match="Invalid role"):
            await service.create_user("testuser", "password", role="superuser")

    @pytest.mark.asyncio
    async def test_authenticate_success(self, service):
        """Test successful authentication."""
        await service.create_user("testuser", "correct-password")

        user = await service.authenticate("testuser", "correct-password")

        assert user.username == "testuser"
        assert user.last_login is not None

    @pytest.mark.asyncio
    async def test_authenticate_case_insensitive_username(self, service):
        """Test that authentication is case-insensitive for username."""
        await service.create_user("TestUser", "password")

        user = await service.authenticate("testuser", "password")
        assert user.username == "testuser"

    @pytest.mark.asyncio
    async def test_authenticate_wrong_password(self, service):
        """Test authentication with wrong password."""
        await service.create_user("testuser", "correct-password")

        with pytest.raises(InvalidCredentialsError):
            await service.authenticate("testuser", "wrong-password")

    @pytest.mark.asyncio
    async def test_authenticate_nonexistent_user(self, service):
        """Test authentication for nonexistent user."""
        with pytest.raises(InvalidCredentialsError):
            await service.authenticate("nonexistent", "password")

    @pytest.mark.asyncio
    async def test_authenticate_disabled_user(self, service):
        """Test authentication for disabled user."""
        user = await service.create_user("testuser", "password")
        await service.set_disabled(user.id, True)

        with pytest.raises(UserDisabledError):
            await service.authenticate("testuser", "password")

    @pytest.mark.asyncio
    async def test_get_user_by_id(self, service):
        """Test getting user by ID."""
        created = await service.create_user("testuser", "password")

        found = await service.get_user(created.id)

        assert found is not None
        assert found.username == "testuser"

    @pytest.mark.asyncio
    async def test_get_user_by_id_not_found(self, service):
        """Test getting nonexistent user by ID."""
        found = await service.get_user("nonexistent-id")
        assert found is None

    @pytest.mark.asyncio
    async def test_get_user_by_username(self, service):
        """Test getting user by username."""
        await service.create_user("testuser", "password")

        found = await service.get_user_by_username("testuser")

        assert found is not None
        assert found.username == "testuser"

    @pytest.mark.asyncio
    async def test_list_users(self, service):
        """Test listing all users."""
        await service.create_user("user1", "pass1")
        await service.create_user("user2", "pass2")
        await service.create_user("admin", "admin", role="admin")

        users = await service.list_users()

        assert len(users) == 3
        usernames = {u.username for u in users}
        assert usernames == {"user1", "user2", "admin"}

    @pytest.mark.asyncio
    async def test_update_password(self, service):
        """Test updating a user's password."""
        user = await service.create_user("testuser", "old-password")

        await service.update_password(user.id, "new-password")

        # Old password should fail
        with pytest.raises(InvalidCredentialsError):
            await service.authenticate("testuser", "old-password")

        # New password should work
        authenticated = await service.authenticate("testuser", "new-password")
        assert authenticated.username == "testuser"

    @pytest.mark.asyncio
    async def test_update_password_not_found(self, service):
        """Test updating password for nonexistent user."""
        with pytest.raises(UserNotFoundError):
            await service.update_password("nonexistent", "new-password")

    @pytest.mark.asyncio
    async def test_set_disabled(self, service):
        """Test enabling/disabling user accounts."""
        user = await service.create_user("testuser", "password")
        assert user.disabled is False

        # Disable
        await service.set_disabled(user.id, True)
        user = await service.get_user(user.id)
        assert user.disabled is True

        # Re-enable
        await service.set_disabled(user.id, False)
        user = await service.get_user(user.id)
        assert user.disabled is False

    @pytest.mark.asyncio
    async def test_delete_user(self, service):
        """Test deleting a user."""
        user = await service.create_user("testuser", "password")

        await service.delete_user(user.id)

        assert await service.get_user(user.id) is None

    @pytest.mark.asyncio
    async def test_delete_user_not_found(self, service):
        """Test deleting nonexistent user."""
        with pytest.raises(UserNotFoundError):
            await service.delete_user("nonexistent")

    @pytest.mark.asyncio
    async def test_ensure_admin_exists_creates_admin(self, service):
        """Test that ensure_admin_exists creates admin when no users exist."""
        created = await service.ensure_admin_exists("admin", "admin-password")

        assert created is True

        users = await service.list_users()
        assert len(users) == 1
        assert users[0].username == "admin"
        assert users[0].role == "admin"

    @pytest.mark.asyncio
    async def test_ensure_admin_exists_does_nothing_if_users_exist(self, service):
        """Test that ensure_admin_exists doesn't create admin if users exist."""
        await service.create_user("existing", "password")

        created = await service.ensure_admin_exists("admin", "admin-password")

        assert created is False

        users = await service.list_users()
        assert len(users) == 1
        assert users[0].username == "existing"

    @pytest.mark.asyncio
    async def test_user_count(self, service):
        """Test getting user count."""
        assert await service.user_count() == 0

        await service.create_user("user1", "pass1")
        assert await service.user_count() == 1

        await service.create_user("user2", "pass2")
        assert await service.user_count() == 2

    @pytest.mark.asyncio
    async def test_created_by_tracking(self, service):
        """Test that created_by is tracked correctly."""
        admin = await service.create_user("admin", "pass", role="admin")

        user = await service.create_user(
            "newuser",
            "pass",
            role="user",
            created_by=admin.id,
        )

        assert user.created_by == admin.id
