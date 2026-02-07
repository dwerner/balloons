"""Tests for TTS module."""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from core.tts import TTSRunner, TTSConfig, get_tts_runner


class TestTTSConfig:
    """Test TTSConfig dataclass."""

    def test_defaults(self):
        """Test default configuration values."""
        config = TTSConfig()
        assert config.backend == "say"
        assert config.voice is None
        assert config.speed == 1.0
        assert config.enabled is True
        assert config.piper_model is None
        assert config.tortoise_quality == "fast"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = TTSConfig(
            backend="piper",
            voice="en_US-lessac-medium",
            speed=1.5,
            enabled=False,
            piper_model="/path/to/model.onnx",
            tortoise_quality="high_quality",
        )
        assert config.backend == "piper"
        assert config.voice == "en_US-lessac-medium"
        assert config.speed == 1.5
        assert config.enabled is False
        assert config.piper_model == "/path/to/model.onnx"
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
    async def test_speak_say_command(self, mock_which, enabled_runner):
        """Test that say command is constructed correctly."""
        mock_which.return_value = "/usr/bin/say"

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_process = MagicMock()
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            await enabled_runner._speak_say("Hello world")

            # Verify say was called
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            assert args[0] == "say"
            assert "Hello world" in args

    @patch("shutil.which")
    async def test_speak_say_with_voice(self, mock_which):
        """Test say command with custom voice."""
        mock_which.return_value = "/usr/bin/say"
        config = TTSConfig(backend="say", voice="Samantha")
        runner = TTSRunner(config)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_process = MagicMock()
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            await runner._speak_say("Hello")

            args = mock_exec.call_args[0]
            assert "-v" in args
            assert "Samantha" in args

    @patch("shutil.which")
    async def test_speak_say_with_speed(self, mock_which):
        """Test say command with custom speed."""
        mock_which.return_value = "/usr/bin/say"
        config = TTSConfig(backend="say", speed=1.5)
        runner = TTSRunner(config)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_process = MagicMock()
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            await runner._speak_say("Hello")

            args = mock_exec.call_args[0]
            assert "-r" in args
            # Speed 1.5 * 175 wpm = 262
            assert "262" in args


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
