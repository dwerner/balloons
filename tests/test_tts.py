"""Tests for TTS module (Tortoise-TTS)."""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from core.tts import TTSRunner, TTSConfig, get_tts_runner


class TestTTSConfig:
    """Test TTSConfig dataclass."""

    def test_defaults(self):
        """Test default configuration values."""
        config = TTSConfig()
        assert config.backend == "tortoise"
        assert config.voice is None
        assert config.enabled is True
        assert config.tortoise_quality == "fast"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = TTSConfig(
            voice="train_grace",
            enabled=False,
            tortoise_quality="high_quality",
        )
        assert config.voice == "train_grace"
        assert config.enabled is False
        assert config.tortoise_quality == "high_quality"


class TestTTSRunner:
    """Test TTSRunner class."""

    @pytest.fixture
    def runner(self):
        """Create a test runner with TTS disabled."""
        config = TTSConfig(enabled=False)
        return TTSRunner(config)

    @pytest.fixture
    def enabled_runner(self):
        """Create a test runner with TTS enabled."""
        config = TTSConfig(enabled=True)
        return TTSRunner(config)

    async def test_speak_disabled_calls_callback(self, runner):
        """When TTS is disabled, speak should immediately call callback."""
        callback_called = False

        def callback():
            nonlocal callback_called
            callback_called = True

        await runner.speak("test text", on_complete=callback)
        assert callback_called

    async def test_speak_disabled_no_queue(self, runner):
        """When TTS is disabled, speak should not queue anything."""
        await runner.speak("test text")
        assert runner._queue.empty()

    async def test_start_stop(self, enabled_runner):
        """Test starting and stopping the runner."""
        await enabled_runner.start()
        assert enabled_runner._running is True

        await enabled_runner.stop()
        assert enabled_runner._running is False

    async def test_cancel_clears_queue(self, enabled_runner):
        """Test that cancel clears the queue."""
        await enabled_runner.start()

        # Add items without processing
        enabled_runner._running = False  # Pause processing
        await enabled_runner._queue.put(("text1", None))
        await enabled_runner._queue.put(("text2", None))

        assert not enabled_runner._queue.empty()

        await enabled_runner.cancel()
        assert enabled_runner._queue.empty()

    @patch("shutil.which")
    async def test_speak_tortoise_command(self, mock_which, enabled_runner):
        """Test that tortoise-tts command is constructed correctly."""
        mock_which.return_value = "/usr/bin/aplay"

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            # Mock the generation process
            mock_gen_process = MagicMock()
            mock_gen_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_gen_process.returncode = 0

            # Mock the playback process
            mock_play_process = MagicMock()
            mock_play_process.wait = AsyncMock()

            mock_exec.side_effect = [mock_gen_process, mock_play_process]

            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.unlink"):
                    await enabled_runner._speak_tortoise("Hello world")

            # Verify tortoise-tts was called
            first_call_args = mock_exec.call_args_list[0][0]
            assert first_call_args[0] == "tortoise-tts"
            assert "--text" in first_call_args
            assert "Hello world" in first_call_args
            assert "--preset" in first_call_args
            assert "fast" in first_call_args

    @patch("shutil.which")
    async def test_speak_tortoise_with_voice(self, mock_which):
        """Test tortoise command with custom voice."""
        mock_which.return_value = "/usr/bin/aplay"
        config = TTSConfig(voice="train_grace")
        runner = TTSRunner(config)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_gen_process = MagicMock()
            mock_gen_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_gen_process.returncode = 0

            mock_play_process = MagicMock()
            mock_play_process.wait = AsyncMock()

            mock_exec.side_effect = [mock_gen_process, mock_play_process]

            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.unlink"):
                    await runner._speak_tortoise("Hello")

            first_call_args = mock_exec.call_args_list[0][0]
            assert "--voice" in first_call_args
            assert "train_grace" in first_call_args

    @patch("shutil.which")
    async def test_speak_tortoise_quality_preset(self, mock_which):
        """Test tortoise command with different quality preset."""
        mock_which.return_value = "/usr/bin/aplay"
        config = TTSConfig(tortoise_quality="high_quality")
        runner = TTSRunner(config)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_gen_process = MagicMock()
            mock_gen_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_gen_process.returncode = 0

            mock_play_process = MagicMock()
            mock_play_process.wait = AsyncMock()

            mock_exec.side_effect = [mock_gen_process, mock_play_process]

            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.unlink"):
                    await runner._speak_tortoise("Hello")

            first_call_args = mock_exec.call_args_list[0][0]
            assert "--preset" in first_call_args
            assert "high_quality" in first_call_args


class TestGetTTSRunner:
    """Test the global runner getter."""

    def test_returns_runner(self):
        """Test that get_tts_runner returns a TTSRunner."""
        # Reset global state
        import core.tts
        core.tts._tts_runner = None

        runner = get_tts_runner(TTSConfig(enabled=False))
        assert isinstance(runner, TTSRunner)

    def test_returns_same_instance(self):
        """Test that get_tts_runner returns the same instance."""
        import core.tts
        core.tts._tts_runner = None

        runner1 = get_tts_runner(TTSConfig(enabled=False))
        runner2 = get_tts_runner()
        assert runner1 is runner2
