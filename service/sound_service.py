"""WebSocket-exposed service for sound management.

This service handles sound file listing, retrieval, and upload for web UI notifications.
Sounds are stored in ~/.balloons/sounds/ and can be played by the web browser.

Usage:
    # List available sounds
    sounds = await client.sounds.list_sounds()

    # Get sound data for playback
    data = await client.sounds.get_sound_data("Chord.ogg")
    # Play using: new Audio(`data:audio/ogg;base64,${data.data_base64}`).play()

    # Upload a custom sound
    result = await client.sounds.upload_sound(base64_data, "my-sound.mp3", "audio/mpeg")
"""

import asyncio
import base64
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from codegen import ws_service, ws_expose, ws_event, ws_type


# Default sound directory
SOUNDS_DIR = Path.home() / ".balloons" / "sounds"

# Supported audio MIME types
SUPPORTED_MEDIA_TYPES = {
    "audio/ogg",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/webm",
    "audio/x-wav",
    "audio/flac",
}

# File extensions for MIME types
MIME_TO_EXT = {
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/flac": ".flac",
}

# Extension to MIME type mapping
EXT_TO_MIME = {
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
}


@ws_type
@dataclass
class SoundInfo:
    """Information about a sound file."""

    filename: str  # Filename in sounds directory
    media_type: str  # MIME type
    size_bytes: int  # File size
    is_builtin: bool = True  # True for bundled sounds, False for uploaded


@ws_type
@dataclass
class SoundData:
    """Sound file data for playback."""

    filename: str
    media_type: str
    data_base64: str  # Base64-encoded audio data


@ws_type
@dataclass
class SoundUploadResult:
    """Result of uploading a sound."""

    filename: str  # Final filename (may be sanitized)
    media_type: str
    size_bytes: int
    success: bool
    error: str | None = None


@ws_type
@dataclass
class SoundEventData:
    """Event payload for sound events."""

    event_type: str
    filename: str
    data: dict = field(default_factory=dict)


@ws_service
class SoundService:
    """WebSocket-exposed service for sound file management.

    Handles listing available sounds, retrieving sound data for browser playback,
    and uploading custom sounds.
    """

    def __init__(
        self,
        sounds_dir: Path | str | None = None,
        max_file_size: int = 5 * 1024 * 1024,  # 5MB default
    ):
        """Initialize sound service.

        Args:
            sounds_dir: Directory for sound files. Defaults to ~/.balloons/sounds/
            max_file_size: Maximum upload file size in bytes (default 5MB)
        """
        self._sounds_dir = Path(sounds_dir) if sounds_dir else SOUNDS_DIR
        self._max_file_size = max_file_size
        self._event_handlers: list[Callable[[str, dict], None]] = []

        # Ensure sounds directory exists
        self._sounds_dir.mkdir(parents=True, exist_ok=True)

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Register a handler for WebSocket events."""
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def _emit_event(self, event_name: str, data: dict) -> None:
        """Emit an event to all registered handlers."""
        for handler in self._event_handlers:
            handler(event_name, data)

    def _get_media_type(self, path: Path) -> str:
        """Get MIME type for a sound file."""
        ext = path.suffix.lower()
        return EXT_TO_MIME.get(ext, "application/octet-stream")

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize a filename for safe storage.

        Removes path components, replaces unsafe characters.
        """
        # Remove any path components
        name = Path(filename).name

        # Replace spaces with underscores, remove other unsafe chars
        safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
        result = ""
        for char in name:
            if char in safe_chars:
                result += char
            elif char == " ":
                result += "_"

        # Ensure it has a valid extension
        if not any(result.lower().endswith(ext) for ext in EXT_TO_MIME.keys()):
            result += ".mp3"  # Default extension

        return result or "sound.mp3"

    @ws_expose
    async def list_sounds(self) -> list[SoundInfo]:
        """List all available sound files.

        Returns:
            List of SoundInfo objects for each sound file.
        """
        sounds = []

        if not self._sounds_dir.exists():
            return sounds

        for path in sorted(self._sounds_dir.iterdir()):
            if not path.is_file():
                continue

            ext = path.suffix.lower()
            if ext not in EXT_TO_MIME:
                continue

            stat = path.stat()
            sounds.append(
                SoundInfo(
                    filename=path.name,
                    media_type=self._get_media_type(path),
                    size_bytes=stat.st_size,
                    is_builtin=True,  # TODO: Track uploaded vs builtin
                )
            )

        return sounds

    @ws_expose
    async def get_sound_data(self, filename: str) -> SoundData | None:
        """Get sound file data for browser playback.

        Args:
            filename: Name of the sound file

        Returns:
            SoundData with base64-encoded audio, or None if not found
        """
        # Sanitize filename to prevent directory traversal
        safe_name = Path(filename).name
        path = self._sounds_dir / safe_name

        if not path.exists() or not path.is_file():
            return None

        # Read and encode. Avoid asyncio.to_thread(path.read_bytes) here because
        # repeated concurrent calls can briefly consume many file descriptors
        # (pathlib.open() in a thread keeps the file open until the read completes).
        # Reading via a context manager in the worker ensures descriptors close
        # immediately even under heavy concurrency.
        def _read_file() -> bytes:
            with path.open("rb") as f:
                return f.read()

        data = await asyncio.to_thread(_read_file)
        data_base64 = base64.b64encode(data).decode("ascii")

        return SoundData(
            filename=safe_name,
            media_type=self._get_media_type(path),
            data_base64=data_base64,
        )

    @ws_expose
    async def upload_sound(
        self,
        data_base64: str,
        filename: str,
        media_type: str,
    ) -> SoundUploadResult:
        """Upload a custom sound file.

        Args:
            data_base64: Base64-encoded audio data
            filename: Desired filename
            media_type: MIME type (audio/ogg, audio/mpeg, etc.)

        Returns:
            SoundUploadResult with success status
        """
        # Validate media type
        if media_type not in SUPPORTED_MEDIA_TYPES:
            return SoundUploadResult(
                filename=filename,
                media_type=media_type,
                size_bytes=0,
                success=False,
                error=f"Unsupported media type: {media_type}. Supported: {', '.join(sorted(SUPPORTED_MEDIA_TYPES))}",
            )

        # Decode base64 data
        try:
            data = base64.b64decode(data_base64)
        except Exception as e:
            return SoundUploadResult(
                filename=filename,
                media_type=media_type,
                size_bytes=0,
                success=False,
                error=f"Invalid base64 data: {e}",
            )

        # Check file size
        if len(data) > self._max_file_size:
            return SoundUploadResult(
                filename=filename,
                media_type=media_type,
                size_bytes=len(data),
                success=False,
                error=f"File too large: {len(data)} bytes (max {self._max_file_size})",
            )

        # Sanitize filename
        safe_filename = self._sanitize_filename(filename)

        # Ensure correct extension for media type
        expected_ext = MIME_TO_EXT.get(media_type)
        if expected_ext and not safe_filename.lower().endswith(expected_ext):
            base = Path(safe_filename).stem
            safe_filename = base + expected_ext

        # Write file
        path = self._sounds_dir / safe_filename
        await asyncio.to_thread(path.write_bytes, data)

        self._emit_event(
            "soundUploaded",
            {"filename": safe_filename, "size_bytes": len(data)},
        )

        return SoundUploadResult(
            filename=safe_filename,
            media_type=media_type,
            size_bytes=len(data),
            success=True,
        )

    @ws_expose
    async def delete_sound(self, filename: str) -> bool:
        """Delete a sound file.

        Args:
            filename: Name of the sound file to delete

        Returns:
            True if deleted, False if not found
        """
        # Sanitize filename
        safe_name = Path(filename).name
        path = self._sounds_dir / safe_name

        # Security check: ensure path is within sounds directory
        try:
            path.resolve().relative_to(self._sounds_dir.resolve())
        except ValueError:
            return False

        if not path.exists():
            return False

        await asyncio.to_thread(path.unlink)
        self._emit_event("soundDeleted", {"filename": safe_name})
        return True

    @ws_expose
    async def get_sounds_dir(self) -> str:
        """Get the sounds directory path.

        Returns:
            Absolute path to sounds directory
        """
        return str(self._sounds_dir.resolve())

    # --- Events ---

    @ws_event
    async def on_sound_uploaded(self) -> SoundEventData:
        """Emitted when a sound is uploaded."""
        ...

    @ws_event
    async def on_sound_deleted(self) -> SoundEventData:
        """Emitted when a sound is deleted."""
        ...
