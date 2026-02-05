"""Tests for configuration loading and saving."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import patch

import yaml

from config import Config, BackendConfig, get_config_async, save_last_view_async


class TestConfigAsync:
    """Tests for async config operations."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path):
        """Use a temporary directory for config."""
        config_dir = tmp_path / ".balloons"
        config_dir.mkdir()
        return config_dir

    @pytest.fixture
    def sample_config_data(self):
        """Sample config data for testing."""
        return {
            "default_backend": "test-backend",
            "backends": {
                "test-backend": {
                    "type": "openai",
                    "base_url": "https://api.example.com",
                    "model": "gpt-4",
                },
                "claude": {},
            },
            "editor": "vim",
        }

    @pytest.mark.asyncio
    async def test_load_async(self, temp_config_dir, sample_config_data):
        """Test async config loading."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(yaml.safe_dump(sample_config_data))

        with patch.dict("os.environ", {"BALLOONS_CONFIG": str(config_file)}):
            config = await Config.load_async()

        assert config.default_backend == "test-backend"
        assert "test-backend" in config.backends
        assert config.backends["test-backend"].type == "openai"

    @pytest.mark.asyncio
    async def test_load_async_default_when_no_file(self, tmp_path):
        """Test async load returns default config when no file exists."""
        with patch.dict("os.environ", {"BALLOONS_CONFIG": ""}):
            with patch("config.Path.home", return_value=tmp_path):
                config = await Config.load_async()

        assert config.default_backend == "claude"
        assert "claude" in config.backends

    @pytest.mark.asyncio
    async def test_save_async(self, temp_config_dir):
        """Test async config saving."""
        config_file = temp_config_dir / "config.yaml"

        config = Config(
            default_backend="claude",
            backends={"claude": BackendConfig(name="claude")},
            last_view_session_id="test-session-123",
            last_view_turn_index=5,
            _config_path=config_file,
        )

        await config.save_async()

        assert config_file.exists()
        data = yaml.safe_load(config_file.read_text())
        assert data["last_view"]["session_id"] == "test-session-123"
        assert data["last_view"]["turn_index"] == 5

    @pytest.mark.asyncio
    async def test_save_async_preserves_existing_data(self, temp_config_dir):
        """Test that async save preserves existing config data."""
        config_file = temp_config_dir / "config.yaml"

        # Write some existing data
        existing_data = {
            "default_backend": "claude",
            "backends": {"claude": {}},
            "custom_setting": "should_be_preserved",
        }
        config_file.write_text(yaml.safe_dump(existing_data))

        config = Config(
            default_backend="claude",
            backends={"claude": BackendConfig(name="claude")},
            last_view_session_id="new-session",
            _config_path=config_file,
        )

        await config.save_async()

        data = yaml.safe_load(config_file.read_text())
        assert data["custom_setting"] == "should_be_preserved"
        assert data["last_view"]["session_id"] == "new-session"

    @pytest.mark.asyncio
    async def test_backend_load_system_prompt_async(self, temp_config_dir):
        """Test async loading of system prompt."""
        prompt_file = temp_config_dir / "system_prompt.txt"
        prompt_file.write_text("You are a helpful assistant.")

        backend = BackendConfig(
            name="test",
            system_prompt=str(prompt_file),
        )

        result = await backend.load_system_prompt_async()
        assert result == "You are a helpful assistant."
        assert backend._system_prompt_content == "You are a helpful assistant."

    @pytest.mark.asyncio
    async def test_backend_load_system_prompt_async_cached(self, temp_config_dir):
        """Test that async prompt loading uses cache."""
        prompt_file = temp_config_dir / "system_prompt.txt"
        prompt_file.write_text("Original prompt")

        backend = BackendConfig(
            name="test",
            system_prompt=str(prompt_file),
        )

        # First load
        result1 = await backend.load_system_prompt_async()

        # Modify file
        prompt_file.write_text("Modified prompt")

        # Second load should return cached value
        result2 = await backend.load_system_prompt_async()

        assert result1 == result2 == "Original prompt"

    @pytest.mark.asyncio
    async def test_backend_load_system_prompt_async_no_prompt(self):
        """Test async prompt loading when no prompt configured."""
        backend = BackendConfig(name="test")
        result = await backend.load_system_prompt_async()
        assert result is None

    @pytest.mark.asyncio
    async def test_save_last_view_async(self, temp_config_dir):
        """Test async save_last_view helper."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(yaml.safe_dump({"default_backend": "claude"}))

        # Reset global config
        import config as config_module
        old_config = config_module._config
        config_module._config = None

        try:
            with patch.dict("os.environ", {"BALLOONS_CONFIG": str(config_file)}):
                await save_last_view_async("my-session", 10)

            data = yaml.safe_load(config_file.read_text())
            assert data["last_view"]["session_id"] == "my-session"
            assert data["last_view"]["turn_index"] == 10
        finally:
            config_module._config = old_config


class TestConfigRoundTrip:
    """Test sync and async operations produce same results."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path):
        """Use a temporary directory for config."""
        config_dir = tmp_path / ".balloons"
        config_dir.mkdir()
        return config_dir

    @pytest.mark.asyncio
    async def test_sync_async_load_equivalent(self, temp_config_dir):
        """Sync and async load produce equivalent configs."""
        config_file = temp_config_dir / "config.yaml"
        config_data = {
            "default_backend": "test",
            "backends": {
                "test": {"type": "openai", "model": "gpt-4"},
                "claude": {},
            },
        }
        config_file.write_text(yaml.safe_dump(config_data))

        with patch.dict("os.environ", {"BALLOONS_CONFIG": str(config_file)}):
            sync_config = Config.load()
            async_config = await Config.load_async()

        assert sync_config.default_backend == async_config.default_backend
        assert set(sync_config.backends.keys()) == set(async_config.backends.keys())
        assert sync_config.backends["test"].model == async_config.backends["test"].model
