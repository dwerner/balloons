"""Tests for runner_factory module."""

import pytest
from unittest.mock import MagicMock

from core.runner_factory import validate_backend_config, create_runner


class TestValidateBackendConfig:
    """Tests for validate_backend_config function."""

    def test_claude_type_valid(self):
        """Claude type backends don't require extra fields."""
        backend = MagicMock(type="claude", name="test")
        result = validate_backend_config(backend)
        assert result is None

    def test_none_type_defaults_to_claude(self):
        """None type defaults to claude and is valid."""
        backend = MagicMock(type=None, name="test")
        result = validate_backend_config(backend)
        assert result is None

    def test_openai_type_requires_base_url(self):
        """OpenAI type requires base_url."""
        backend = MagicMock(
            type="openai",
            name="test-openai",
            base_url=None,
            model="gpt-4",
        )
        result = validate_backend_config(backend)
        assert result is not None
        assert "requires base_url" in result
        assert "test-openai" in result

    def test_openai_type_model_optional(self):
        """OpenAI type doesn't require model (for local servers like llama.cpp)."""
        backend = MagicMock(
            type="openai",
            name="test-openai",
            base_url="http://localhost:8080",
            model=None,
        )
        result = validate_backend_config(backend)
        # Model is optional - local servers like llama.cpp ignore it
        assert result is None

    def test_openai_strict_type_valid_with_all_fields(self):
        """OpenAI strict type is valid when all fields present."""
        backend = MagicMock(
            type="openai_strict",
            name="test-openai-strict",
            base_url="http://localhost:8080",
            model="llama-3",
        )
        result = validate_backend_config(backend)
        assert result is None

    def test_gemini_type_requires_api_key(self):
        """Gemini type requires api_key."""
        backend = MagicMock(
            type="gemini",
            name="test-gemini",
            api_key=None,
            model="gemini-2.5-flash",
        )
        result = validate_backend_config(backend)
        assert result is not None
        assert "requires api_key" in result
        assert "test-gemini" in result

    def test_gemini_type_valid_with_api_key(self):
        """Gemini type is valid when api_key present."""
        backend = MagicMock(
            type="gemini",
            name="test-gemini",
            api_key="test-key",
            model="gemini-2.5-flash",
        )
        result = validate_backend_config(backend)
        assert result is None

    def test_gemini_type_model_optional(self):
        """Gemini type doesn't require model (defaults to gemini-2.5-flash)."""
        backend = MagicMock(
            type="gemini",
            name="test-gemini",
            api_key="test-key",
            model=None,
        )
        result = validate_backend_config(backend)
        assert result is None

    def test_unknown_type_returns_error(self):
        """Unknown backend type returns error."""
        backend = MagicMock(type="unknown", name="test")
        result = validate_backend_config(backend)
        assert result is not None
        assert "Unknown backend type" in result
        assert "unknown" in result
        assert "claude" in result  # Lists valid types
        assert "gemini" in result  # Lists valid types
        assert "openai_strict" in result  # Lists valid types

    def test_empty_string_base_url_fails(self):
        """Empty string base_url is treated as missing."""
        backend = MagicMock(
            type="openai",
            name="test",
            base_url="",
            model="gpt-4",
        )
        result = validate_backend_config(backend)
        assert result is not None
        assert "requires base_url" in result

    def test_empty_string_model_valid(self):
        """Empty string model is valid (defaults to 'default' at runner creation)."""
        backend = MagicMock(
            type="openai",
            name="test",
            base_url="http://localhost",
            model="",
        )
        result = validate_backend_config(backend)
        # Empty model is fine - will default to "default" when runner is created
        assert result is None


class TestCreateRunner:
    def test_openai_strict_type_uses_experimental_runner(self):
        backend = MagicMock(
            type="openai_strict",
            name="strict-openai",
            base_url="http://localhost:8000/v1",
            api_key="test-key",
            model="mistral",
            context_window=12345,
        )
        backend.load_system_prompt.return_value = None

        runner = create_runner(backend)

        from core.strict_openai_runner import StrictOpenAICompatibleRunner
        assert type(runner) is StrictOpenAICompatibleRunner
