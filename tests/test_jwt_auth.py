"""Tests for JWT authentication module."""

import time
import pytest
from unittest.mock import MagicMock, patch

from service.jwt_auth import (
    JWTAuth,
    JWTConfig,
    TokenClaims,
    JWTAuthError,
    MissingTokenError,
    InvalidTokenError,
    ExpiredTokenError,
    AUTH_ERROR_MISSING_TOKEN,
    AUTH_ERROR_INVALID_TOKEN,
    AUTH_ERROR_EXPIRED_TOKEN,
    create_auth,
)


class TestJWTConfig:
    """Tests for JWTConfig dataclass."""

    def test_default_values(self):
        config = JWTConfig()
        assert config.enabled is True
        assert config.secret is None
        assert config.expiration_seconds == 86400
        assert config.algorithm == "HS256"
        assert config.issuer == "balloons"

    def test_get_secret_with_configured_secret(self):
        config = JWTConfig(secret="my-secret-key-32-bytes-minimum!!")
        assert config.get_secret() == "my-secret-key-32-bytes-minimum!!"

    def test_get_secret_generates_runtime_secret(self):
        config = JWTConfig(secret=None)
        secret = config.get_secret()
        assert secret is not None
        assert len(secret) >= 32  # Should meet HS256 recommended minimum length
        # Same instance should return same runtime secret
        assert config.get_secret() == secret

    def test_different_instances_different_runtime_secrets(self):
        config1 = JWTConfig(secret=None)
        config2 = JWTConfig(secret=None)
        # Different instances should have different runtime secrets
        assert config1.get_secret() != config2.get_secret()


class TestJWTAuth:
    """Tests for JWTAuth class."""

    @pytest.fixture
    def auth(self):
        """Create auth handler with a fixed secret for testing."""
        config = JWTConfig(secret="test-secret-key-12345-32-bytes!!")
        return JWTAuth(config)

    @pytest.fixture
    def short_expiry_auth(self):
        """Create auth handler with short token expiry."""
        config = JWTConfig(secret="test-secret-32-bytes-minimum!!!!", expiration_seconds=1)
        return JWTAuth(config)

    def test_generate_token_basic(self, auth):
        token = auth.generate_token(subject="test-subject")
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_generate_token_with_custom_claims(self, auth):
        token = auth.generate_token(
            subject="test-subject",
            custom_claims={"role": "admin", "features": ["read", "write"]},
        )
        assert token is not None

    def test_validate_token_success(self, auth):
        token = auth.generate_token(subject="my-session-123")
        claims = auth.validate_token(token)

        assert isinstance(claims, TokenClaims)
        assert claims.subject == "my-session-123"
        assert claims.issuer == "balloons"
        assert claims.issued_at is not None
        assert claims.expires_at is not None
        assert claims.expires_at > claims.issued_at

    def test_validate_token_with_custom_claims(self, auth):
        token = auth.generate_token(
            subject="test",
            custom_claims={"role": "admin", "level": 5},
        )
        claims = auth.validate_token(token)

        assert claims.custom["role"] == "admin"
        assert claims.custom["level"] == 5

    def test_validate_token_expired(self, short_expiry_auth):
        token = short_expiry_auth.generate_token(subject="test")
        # Wait for token to expire
        time.sleep(1.5)

        with pytest.raises(ExpiredTokenError):
            short_expiry_auth.validate_token(token)

    def test_validate_token_invalid_signature(self, auth):
        # Generate a token with different secret
        other_auth = JWTAuth(JWTConfig(secret="different-secret-32-bytes-min!!!"))
        token = other_auth.generate_token(subject="test")

        with pytest.raises(InvalidTokenError):
            auth.validate_token(token)

    def test_validate_token_malformed(self, auth):
        with pytest.raises(InvalidTokenError):
            auth.validate_token("not-a-valid-jwt")

    def test_validate_token_empty(self, auth):
        with pytest.raises(InvalidTokenError):
            auth.validate_token("")

    def test_validate_token_missing_claims(self, auth):
        # Create a token without required claims
        import jwt

        payload = {"foo": "bar"}  # Missing sub, exp, iat
        token = jwt.encode(payload, "test-secret-key-12345-32-bytes!!", algorithm="HS256")

        with pytest.raises(InvalidTokenError):
            auth.validate_token(token)


class TestTokenExtraction:
    """Tests for token extraction from query strings and subprotocols."""

    @pytest.fixture
    def auth(self):
        return JWTAuth(JWTConfig(secret="test-test-test-test-test-test-1234"))

    def test_extract_token_from_query_simple(self, auth):
        query = "token=abc123"
        token = auth.extract_token_from_query(query)
        assert token == "abc123"

    def test_extract_token_from_query_with_other_params(self, auth):
        query = "foo=bar&token=mytoken&baz=qux"
        token = auth.extract_token_from_query(query)
        assert token == "mytoken"

    def test_extract_token_from_query_missing(self, auth):
        query = "foo=bar&baz=qux"
        token = auth.extract_token_from_query(query)
        assert token is None

    def test_extract_token_from_query_empty(self, auth):
        token = auth.extract_token_from_query("")
        assert token is None

    def test_extract_token_from_subprotocol_found(self, auth):
        subprotocols = ["graphql", "balloons.auth.xyz789", "other"]
        token = auth.extract_token_from_subprotocol(subprotocols)
        assert token == "xyz789"

    def test_extract_token_from_subprotocol_not_found(self, auth):
        subprotocols = ["graphql", "json", "other"]
        token = auth.extract_token_from_subprotocol(subprotocols)
        assert token is None

    def test_extract_token_from_subprotocol_empty(self, auth):
        token = auth.extract_token_from_subprotocol([])
        assert token is None

    def test_extract_token_from_subprotocol_with_dots_in_token(self, auth):
        # JWT tokens have dots in them
        jwt_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.payload.signature"
        subprotocols = [f"balloons.auth.{jwt_token}"]
        token = auth.extract_token_from_subprotocol(subprotocols)
        assert token == jwt_token


class TestJWTAuthErrors:
    """Tests for JWT error classes."""

    def test_missing_token_error(self):
        error = MissingTokenError()
        assert error.code == AUTH_ERROR_MISSING_TOKEN
        assert "required" in str(error).lower()

    def test_missing_token_error_custom_message(self):
        error = MissingTokenError("Custom message")
        assert str(error) == "Custom message"

    def test_invalid_token_error(self):
        error = InvalidTokenError()
        assert error.code == AUTH_ERROR_INVALID_TOKEN

    def test_expired_token_error(self):
        error = ExpiredTokenError()
        assert error.code == AUTH_ERROR_EXPIRED_TOKEN


class TestCreateAuth:
    """Tests for create_auth helper function."""

    def test_create_auth_default_config(self):
        auth = create_auth()
        assert isinstance(auth, JWTAuth)
        assert auth.config.enabled is True

    def test_create_auth_custom_config(self):
        config = JWTConfig(enabled=False, secret="custom-secret-32-bytes-minimum!")
        auth = create_auth(config)
        assert auth.config.enabled is False
        assert auth.config.secret == "custom-secret-32-bytes-minimum!"


class TestJWTAuthLazyImport:
    """Tests for lazy jwt module import."""

    def test_import_error_message(self):
        """Test that a helpful error message is shown when jwt is not installed."""
        config = JWTConfig(secret="test-test-test-test-test-test-1234")
        auth = JWTAuth(config)

        # Mock the import to fail
        with patch.dict("sys.modules", {"jwt": None}):
            auth._jwt = None
            with patch("builtins.__import__", side_effect=ImportError("No module")):
                with pytest.raises(ImportError) as exc_info:
                    auth._get_jwt()

                assert "PyJWT" in str(exc_info.value)
                assert "pip install" in str(exc_info.value)


class TestRoundTrip:
    """End-to-end tests for token generation and validation."""

    def test_roundtrip_basic(self):
        auth = create_auth(JWTConfig(secret="roundtrip-secret-32-bytes-min!!!"))

        # Generate
        token = auth.generate_token(subject="session-abc-123")

        # Validate
        claims = auth.validate_token(token)
        assert claims.subject == "session-abc-123"

    def test_roundtrip_with_custom_claims(self):
        auth = create_auth(JWTConfig(secret="roundtrip-secret-32-bytes-min!!!"))

        token = auth.generate_token(
            subject="user-42",
            custom_claims={
                "permissions": ["read", "write"],
                "metadata": {"version": 1},
            },
        )

        claims = auth.validate_token(token)
        assert claims.subject == "user-42"
        assert claims.custom["permissions"] == ["read", "write"]
        assert claims.custom["metadata"]["version"] == 1

    def test_roundtrip_custom_expiration(self):
        auth = create_auth(JWTConfig(secret="test-test-test-test-test-test-1234", expiration_seconds=3600))

        token = auth.generate_token(subject="test", expiration_seconds=7200)

        claims = auth.validate_token(token)
        # Token should expire ~2 hours from now
        now = int(time.time())
        assert claims.expires_at - now >= 7100  # Give some slack

    def test_tokens_with_different_subjects_differ(self):
        auth = create_auth(JWTConfig(secret="test-test-test-test-test-test-1234"))

        token1 = auth.generate_token(subject="session-1")
        token2 = auth.generate_token(subject="session-2")

        # Tokens should be different (different subjects)
        assert token1 != token2

    def test_same_token_validates_multiple_times(self):
        auth = create_auth(JWTConfig(secret="test-test-test-test-test-test-1234"))

        token = auth.generate_token(subject="test")

        # Should be able to validate the same token multiple times
        claims1 = auth.validate_token(token)
        claims2 = auth.validate_token(token)

        assert claims1.subject == claims2.subject
