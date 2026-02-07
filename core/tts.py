"""Text-to-speech support for Balloons using Tortoise-TTS.

Provides high-quality neural TTS generation and playback.
Tortoise-TTS produces natural-sounding speech but requires GPU and takes time to generate.
"""

import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

from .debug_log import debug_log


@dataclass
class TTSConfig:
    """Tortoise-TTS configuration.

    Attributes:
        enabled: Whether TTS is enabled
        voice: Voice name or path to voice samples directory
        tortoise_quality: Quality preset (ultra_fast, fast, standard, high_quality)
    """
    backend: str = "tortoise"  # Keep for compatibility but only tortoise is supported
    enabled: bool = True
    voice: Optional[str] = None  # None = random voice
    tortoise_quality: str = "fast"  # ultra_fast, fast, standard, high_quality

    # Legacy fields kept for config compatibility
    speed: float = 1.0
    piper_model: Optional[str] = None


# For backwards compatibility
TTSBackend = str


class TTSRunner:
    """Manages Tortoise-TTS generation and playback.

    Handles:
    - Async audio generation via tortoise-tts CLI
    - Sequential playback queue
    - Stop/cancel support
    """

    def __init__(self, config: Optional[TTSConfig] = None):
        self.config = config or TTSConfig()
        self._queue: asyncio.Queue[tuple[str, Optional[Callable]]] = asyncio.Queue()
        self._current_process: Optional[asyncio.subprocess.Process] = None
        self._playback_process: Optional[asyncio.subprocess.Process] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stop_requested = False

    async def start(self) -> None:
        """Start the TTS processing loop."""
        if self._running:
            return
        self._running = True
        self._stop_requested = False
        self._task = asyncio.create_task(self._process_loop())
        debug_log.info("TTS runner started", category="tts")

    async def stop(self) -> None:
        """Stop the TTS runner and cancel any pending speech."""
        self._running = False
        self._stop_requested = True

        # Cancel current processes
        await self._cancel_current()

        # Clear the queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Cancel the processing task
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        debug_log.info("TTS runner stopped", category="tts")

    async def speak(
        self,
        text: str,
        on_complete: Optional[Callable[[], None]] = None,
    ) -> None:
        """Queue text to be spoken.

        Args:
            text: Text to speak
            on_complete: Callback when speech finishes
        """
        if not self.config.enabled:
            debug_log.info("TTS disabled, skipping", category="tts")
            if on_complete:
                on_complete()
            return

        # Start runner if not running
        if not self._running:
            await self.start()

        await self._queue.put((text, on_complete))
        debug_log.info(f"Queued TTS: {text[:50]}...", category="tts")

    async def speak_now(self, text: str) -> None:
        """Speak text immediately, canceling any current speech.

        Args:
            text: Text to speak
        """
        await self._cancel_current()
        await self.speak(text)

    async def cancel(self) -> None:
        """Cancel current speech and clear queue."""
        await self._cancel_current()

        # Clear queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _cancel_current(self) -> None:
        """Cancel currently playing audio."""
        if self._playback_process:
            try:
                self._playback_process.terminate()
                await asyncio.wait_for(self._playback_process.wait(), timeout=1.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    self._playback_process.kill()
                except ProcessLookupError:
                    pass
            self._playback_process = None

        if self._current_process:
            try:
                self._current_process.terminate()
                await asyncio.wait_for(self._current_process.wait(), timeout=1.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    self._current_process.kill()
                except ProcessLookupError:
                    pass
            self._current_process = None

    async def _process_loop(self) -> None:
        """Main processing loop - generates and plays audio from queue."""
        while self._running:
            try:
                # Wait for next item
                text, on_complete = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if self._stop_requested:
                break

            try:
                await self._speak_tortoise(text)
                if on_complete:
                    on_complete()
            except asyncio.CancelledError:
                break
            except Exception as e:
                debug_log.error(f"TTS error: {e}", category="tts")

    async def _speak_tortoise(self, text: str) -> None:
        """Speak using Tortoise-TTS.

        Generates audio to temp file then plays it.
        """
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        # Build tortoise-tts command
        cmd = [
            "tortoise-tts",
            "--text", text,
            "--output", temp_path,
            "--preset", self.config.tortoise_quality,
        ]

        if self.config.voice:
            cmd.extend(["--voice", self.config.voice])

        debug_log.info(
            f"Generating TTS with Tortoise (preset={self.config.tortoise_quality}, voice={self.config.voice or 'random'})",
            category="tts"
        )

        # Generate audio
        self._current_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await self._current_process.communicate()
        return_code = self._current_process.returncode
        self._current_process = None

        if return_code != 0:
            debug_log.error(
                f"Tortoise-TTS failed (exit {return_code}): {stderr.decode()[:500]}",
                category="tts"
            )
            Path(temp_path).unlink(missing_ok=True)
            return

        if not Path(temp_path).exists():
            debug_log.error("Tortoise failed to generate audio file", category="tts")
            return

        debug_log.info(f"Generated audio, playing: {temp_path}", category="tts")

        # Play the file
        if shutil.which("aplay"):
            play_cmd = ["aplay", temp_path]
        elif shutil.which("afplay"):
            play_cmd = ["afplay", temp_path]
        elif shutil.which("paplay"):
            play_cmd = ["paplay", temp_path]
        else:
            debug_log.error("No audio player found (tried aplay, afplay, paplay)", category="tts")
            Path(temp_path).unlink(missing_ok=True)
            return

        self._playback_process = await asyncio.create_subprocess_exec(
            *play_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await self._playback_process.wait()
        self._playback_process = None

        # Clean up temp file
        Path(temp_path).unlink(missing_ok=True)


# Global TTS runner instance
_tts_runner: Optional[TTSRunner] = None


def get_tts_runner(config: Optional[TTSConfig] = None) -> TTSRunner:
    """Get or create the global TTS runner.

    If no config provided and creating a new runner, loads from global config.

    Args:
        config: TTS configuration (only used if creating new runner)

    Returns:
        The global TTSRunner instance
    """
    global _tts_runner
    if _tts_runner is None:
        if config is None:
            # Try to load from global config
            try:
                from config import get_config
                app_config = get_config()
                # Convert config.TTSConfig to core.tts.TTSConfig
                config = TTSConfig(
                    backend=app_config.tts.backend,
                    voice=app_config.tts.voice,
                    enabled=app_config.tts.enabled,
                    tortoise_quality=app_config.tts.tortoise_quality,
                )
            except Exception:
                # Fall back to defaults
                config = TTSConfig()
        _tts_runner = TTSRunner(config)
    return _tts_runner


async def speak(text: str, on_complete: Optional[Callable[[], None]] = None) -> None:
    """Convenience function to speak text using the global runner.

    Args:
        text: Text to speak
        on_complete: Callback when speech finishes
    """
    runner = get_tts_runner()
    await runner.speak(text, on_complete)


async def stop_speaking() -> None:
    """Stop any current speech."""
    runner = get_tts_runner()
    await runner.cancel()
