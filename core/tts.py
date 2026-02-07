"""Text-to-speech support for Balloons.

Provides TTS generation and playback using various backends:
- tortoise: High-quality neural TTS (slow, requires GPU)
- piper: Fast neural TTS (CPU-friendly)
- say: macOS built-in TTS
- espeak: Cross-platform fallback
"""

import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable
from enum import Enum

from .debug_log import debug_log


class TTSBackend(str, Enum):
    """Available TTS backends."""
    TORTOISE = "tortoise"
    PIPER = "piper"
    SAY = "say"  # macOS
    ESPEAK = "espeak"


@dataclass
class TTSConfig:
    """TTS configuration.

    Attributes:
        backend: Which TTS engine to use
        voice: Voice identifier (backend-specific)
        speed: Speech rate multiplier (1.0 = normal)
        enabled: Whether TTS is enabled
        cache_dir: Directory for caching generated audio
    """
    backend: str = "say"  # Default to macOS say for simplicity
    voice: Optional[str] = None
    speed: float = 1.0
    enabled: bool = True
    cache_dir: Optional[str] = None

    # Tortoise-specific
    tortoise_quality: str = "fast"  # ultra_fast, fast, standard, high_quality

    # Piper-specific
    piper_model: Optional[str] = None  # Path to .onnx model


class TTSRunner:
    """Manages TTS generation and playback.

    Handles:
    - Async audio generation via subprocess
    - Sequential playback queue
    - Stop/cancel support
    - Backend auto-detection
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
                await self._speak_text(text)
                if on_complete:
                    on_complete()
            except asyncio.CancelledError:
                break
            except Exception as e:
                debug_log.error(f"TTS error: {e}", category="tts")

    async def _speak_text(self, text: str) -> None:
        """Generate and play speech for text.

        Args:
            text: Text to speak
        """
        backend = self.config.backend.lower()

        if backend == "say":
            await self._speak_say(text)
        elif backend == "espeak":
            await self._speak_espeak(text)
        elif backend == "piper":
            await self._speak_piper(text)
        elif backend == "tortoise":
            await self._speak_tortoise(text)
        else:
            # Auto-detect available backend
            await self._speak_auto(text)

    async def _speak_say(self, text: str) -> None:
        """Speak using macOS say command."""
        cmd = ["say"]

        if self.config.voice:
            cmd.extend(["-v", self.config.voice])

        if self.config.speed != 1.0:
            # say uses words per minute, default ~175
            rate = int(175 * self.config.speed)
            cmd.extend(["-r", str(rate)])

        cmd.append(text)

        self._playback_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await self._playback_process.wait()
        self._playback_process = None

    async def _speak_espeak(self, text: str) -> None:
        """Speak using espeak."""
        cmd = ["espeak"]

        if self.config.voice:
            cmd.extend(["-v", self.config.voice])

        if self.config.speed != 1.0:
            # espeak uses words per minute, default 175
            rate = int(175 * self.config.speed)
            cmd.extend(["-s", str(rate)])

        cmd.append(text)

        self._playback_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await self._playback_process.wait()
        self._playback_process = None

    async def _speak_piper(self, text: str) -> None:
        """Speak using Piper TTS.

        Piper generates audio to stdout, which we pipe to aplay/afplay.
        """
        if not self.config.piper_model:
            debug_log.error("Piper model not configured", category="tts")
            return

        # Generate audio with piper
        piper_cmd = [
            "piper",
            "--model", self.config.piper_model,
            "--output-raw",
        ]

        # Determine playback command
        if shutil.which("afplay"):
            # macOS - need to write to file first
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name

            piper_cmd = [
                "piper",
                "--model", self.config.piper_model,
                "--output_file", temp_path,
            ]

            self._current_process = await asyncio.create_subprocess_exec(
                *piper_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await self._current_process.communicate(input=text.encode())
            self._current_process = None

            # Play the file
            self._playback_process = await asyncio.create_subprocess_exec(
                "afplay", temp_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await self._playback_process.wait()
            self._playback_process = None

            # Clean up
            Path(temp_path).unlink(missing_ok=True)

        elif shutil.which("aplay"):
            # Linux - can pipe directly
            self._current_process = await asyncio.create_subprocess_exec(
                *piper_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )

            self._playback_process = await asyncio.create_subprocess_exec(
                "aplay", "-r", "22050", "-f", "S16_LE", "-t", "raw", "-",
                stdin=self._current_process.stdout,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

            await self._playback_process.wait()
            await self._current_process.wait()
            self._current_process = None
            self._playback_process = None

    async def _speak_tortoise(self, text: str) -> None:
        """Speak using Tortoise TTS.

        Tortoise is slow but high quality. Generates to temp file then plays.
        """
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        cmd = [
            "tortoise-tts",
            "--text", text,
            "--output", temp_path,
            "--preset", self.config.tortoise_quality,
        ]

        if self.config.voice:
            cmd.extend(["--voice", self.config.voice])

        debug_log.info(f"Generating TTS with tortoise (preset={self.config.tortoise_quality})", category="tts")

        self._current_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await self._current_process.wait()
        self._current_process = None

        if not Path(temp_path).exists():
            debug_log.error("Tortoise failed to generate audio", category="tts")
            return

        # Play the file
        if shutil.which("afplay"):
            play_cmd = ["afplay", temp_path]
        elif shutil.which("aplay"):
            play_cmd = ["aplay", temp_path]
        else:
            debug_log.error("No audio player found", category="tts")
            Path(temp_path).unlink(missing_ok=True)
            return

        self._playback_process = await asyncio.create_subprocess_exec(
            *play_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await self._playback_process.wait()
        self._playback_process = None

        Path(temp_path).unlink(missing_ok=True)

    async def _speak_auto(self, text: str) -> None:
        """Auto-detect available TTS backend and use it."""
        if shutil.which("say"):
            await self._speak_say(text)
        elif shutil.which("espeak"):
            await self._speak_espeak(text)
        elif shutil.which("piper") and self.config.piper_model:
            await self._speak_piper(text)
        else:
            debug_log.warning("No TTS backend available", category="tts")


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
                    speed=app_config.tts.speed,
                    enabled=app_config.tts.enabled,
                    piper_model=app_config.tts.piper_model,
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
