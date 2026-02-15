"""WebSocket-exposed service for image management.

This service handles image upload, storage, and cleanup for the chat interface.
Images are stored on disk and referenced by file path.

Storage location defaults to ~/.balloons/uploads/ but can be configured.
"""

import asyncio
import base64
import hashlib
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from codegen import ws_service, ws_expose, ws_event, ws_type


# Supported image MIME types
SUPPORTED_MEDIA_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
}

# File extensions for MIME types
MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def get_default_upload_dir() -> Path:
    """Get the default upload directory path."""
    balloons_dir = Path.home() / ".balloons"
    return balloons_dir / "uploads"


@ws_type
@dataclass
class ImageUploadResult:
    """Result of uploading an image."""

    file_path: str  # Absolute path to stored image
    filename: str  # Generated filename
    media_type: str  # MIME type
    size_bytes: int  # File size
    width: int = 0  # Image width (if detected)
    height: int = 0  # Image height (if detected)


@ws_type
@dataclass
class ImageInfo:
    """Information about a stored image."""

    file_path: str
    filename: str
    media_type: str
    size_bytes: int
    created_at: str  # ISO timestamp
    session_id: str | None = None  # Session that uploaded this image


@ws_type
@dataclass
class ImageEventData:
    """Event payload for image events."""

    event_type: str
    file_path: str
    data: dict = field(default_factory=dict)


@ws_service
class ImageService:
    """WebSocket-exposed service for image management.

    Handles image upload, storage, retrieval, and cleanup.
    Images are stored on disk with unique filenames based on content hash.
    """

    def __init__(
        self,
        upload_dir: Path | str | None = None,
        retention_hours: int = 24 * 7,  # Keep images for 7 days by default
    ):
        """Initialize image service.

        Args:
            upload_dir: Directory for storing uploads. Defaults to ~/.config/balloons/uploads/
            retention_hours: Hours to keep uploaded images before cleanup (default 7 days)
        """
        self._upload_dir = Path(upload_dir) if upload_dir else get_default_upload_dir()
        self._retention_hours = retention_hours
        self._event_handlers: list[Callable[[str, dict], None]] = []

        # Track uploaded images by session
        self._session_images: dict[str, list[str]] = {}  # session_id -> [file_paths]

        # Ensure upload directory exists
        self._upload_dir.mkdir(parents=True, exist_ok=True)

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

    def _generate_filename(self, data: bytes, media_type: str) -> str:
        """Generate a unique filename based on content hash and timestamp.

        Uses first 12 chars of SHA256 hash plus timestamp for uniqueness
        while being somewhat readable.
        """
        content_hash = hashlib.sha256(data).hexdigest()[:12]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = MIME_TO_EXT.get(media_type, ".bin")
        return f"{timestamp}_{content_hash}{ext}"

    def _get_image_dimensions(self, data: bytes) -> tuple[int, int]:
        """Try to get image dimensions from image data.

        Returns (width, height) or (0, 0) if detection fails.
        Uses simple header parsing - no external dependencies.
        """
        try:
            # PNG: First 8 bytes are signature, then IHDR chunk with width/height
            if data[:8] == b'\x89PNG\r\n\x1a\n':
                # Width and height are at bytes 16-24 (4 bytes each, big-endian)
                width = int.from_bytes(data[16:20], 'big')
                height = int.from_bytes(data[20:24], 'big')
                return (width, height)

            # JPEG: Parse SOF0 marker for dimensions
            if data[:2] == b'\xff\xd8':
                # Find SOF0 marker (0xFFC0)
                i = 2
                while i < len(data) - 9:
                    if data[i] == 0xFF:
                        marker = data[i + 1]
                        if marker == 0xC0 or marker == 0xC2:  # SOF0 or SOF2
                            height = int.from_bytes(data[i + 5:i + 7], 'big')
                            width = int.from_bytes(data[i + 7:i + 9], 'big')
                            return (width, height)
                        # Skip to next marker
                        length = int.from_bytes(data[i + 2:i + 4], 'big')
                        i += 2 + length
                    else:
                        i += 1

            # GIF: Width and height at bytes 6-10 (little-endian)
            if data[:6] in (b'GIF87a', b'GIF89a'):
                width = int.from_bytes(data[6:8], 'little')
                height = int.from_bytes(data[8:10], 'little')
                return (width, height)

            # WebP: RIFF container, dimensions in VP8 chunk
            if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
                # This is simplified - full WebP parsing is complex
                # Look for VP8 chunk
                if data[12:16] == b'VP8 ':
                    # Dimensions at offset 26-30
                    width = int.from_bytes(data[26:28], 'little') & 0x3FFF
                    height = int.from_bytes(data[28:30], 'little') & 0x3FFF
                    return (width, height)
        except Exception:
            pass

        return (0, 0)

    @ws_expose
    async def upload_image(
        self,
        data_base64: str,
        media_type: str,
        session_id: str | None = None,
        original_filename: str | None = None,
    ) -> ImageUploadResult:
        """Upload an image from base64 data.

        Args:
            data_base64: Base64-encoded image data
            media_type: MIME type (image/png, image/jpeg, etc.)
            session_id: Optional session ID to associate with this image
            original_filename: Optional original filename

        Returns:
            ImageUploadResult with file path and metadata

        Raises:
            ValueError: If media type is not supported or data is invalid
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"upload_image called: media_type={media_type}, session_id={session_id}, filename={original_filename}, data_len={len(data_base64)}")

        # Validate media type
        if media_type not in SUPPORTED_MEDIA_TYPES:
            raise ValueError(
                f"Unsupported media type: {media_type}. "
                f"Supported types: {', '.join(SUPPORTED_MEDIA_TYPES)}"
            )

        # Decode base64 data
        try:
            data = base64.b64decode(data_base64)
        except Exception as e:
            raise ValueError(f"Invalid base64 data: {e}")

        # Check for reasonable size (max 20MB)
        max_size = 20 * 1024 * 1024
        if len(data) > max_size:
            raise ValueError(f"Image too large: {len(data)} bytes (max {max_size})")

        # Generate filename and save
        filename = self._generate_filename(data, media_type)
        file_path = self._upload_dir / filename

        # Write file asynchronously
        await asyncio.to_thread(file_path.write_bytes, data)

        # Get dimensions
        width, height = self._get_image_dimensions(data)

        # Track by session if provided
        if session_id:
            if session_id not in self._session_images:
                self._session_images[session_id] = []
            self._session_images[session_id].append(str(file_path))

        result = ImageUploadResult(
            file_path=str(file_path),
            filename=filename,
            media_type=media_type,
            size_bytes=len(data),
            width=width,
            height=height,
        )

        self._emit_event("imageUploaded", {
            "file_path": str(file_path),
            "session_id": session_id,
            "size_bytes": len(data),
        })

        return result

    @ws_expose
    async def get_image_info(self, file_path: str) -> ImageInfo | None:
        """Get information about a stored image.

        Args:
            file_path: Path to the image file

        Returns:
            ImageInfo if found, None otherwise
        """
        path = Path(file_path)
        if not path.exists():
            return None

        stat = path.stat()

        # Determine media type from extension
        ext = path.suffix.lower()
        ext_to_mime = {v: k for k, v in MIME_TO_EXT.items()}
        media_type = ext_to_mime.get(ext, "application/octet-stream")

        # Find session ID if tracked
        session_id = None
        for sid, paths in self._session_images.items():
            if file_path in paths:
                session_id = sid
                break

        return ImageInfo(
            file_path=file_path,
            filename=path.name,
            media_type=media_type,
            size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_ctime).isoformat(),
            session_id=session_id,
        )

    @ws_expose
    async def delete_image(self, file_path: str) -> bool:
        """Delete an uploaded image.

        Args:
            file_path: Path to the image file

        Returns:
            True if deleted, False if not found
        """
        path = Path(file_path)

        # Security check: only delete files in upload directory
        try:
            path.resolve().relative_to(self._upload_dir.resolve())
        except ValueError:
            return False

        if not path.exists():
            return False

        await asyncio.to_thread(path.unlink)

        # Remove from session tracking
        for paths in self._session_images.values():
            if file_path in paths:
                paths.remove(file_path)

        self._emit_event("imageDeleted", {"file_path": file_path})
        return True

    @ws_expose
    async def cleanup_old_images(self, max_age_hours: int | None = None) -> int:
        """Clean up images older than the retention period.

        Args:
            max_age_hours: Max age in hours (defaults to service retention setting)

        Returns:
            Number of images deleted
        """
        hours = max_age_hours if max_age_hours is not None else self._retention_hours
        cutoff = datetime.now() - timedelta(hours=hours)
        deleted = 0

        for file_path in self._upload_dir.iterdir():
            if not file_path.is_file():
                continue

            stat = file_path.stat()
            created = datetime.fromtimestamp(stat.st_ctime)

            if created < cutoff:
                await asyncio.to_thread(file_path.unlink)
                deleted += 1

                # Remove from session tracking
                path_str = str(file_path)
                for paths in self._session_images.values():
                    if path_str in paths:
                        paths.remove(path_str)

        if deleted > 0:
            self._emit_event("cleanupCompleted", {"deleted_count": deleted})

        return deleted

    @ws_expose
    async def get_session_images(self, session_id: str) -> list[str]:
        """Get all image paths uploaded by a session.

        Args:
            session_id: The session ID

        Returns:
            List of file paths
        """
        return self._session_images.get(session_id, [])

    @ws_expose
    async def get_upload_dir(self) -> str:
        """Get the upload directory path.

        Returns:
            Absolute path to upload directory
        """
        return str(self._upload_dir.resolve())

    # --- Events ---

    @ws_event
    async def on_image_uploaded(self) -> ImageEventData:
        """Emitted when an image is uploaded."""
        ...

    @ws_event
    async def on_image_deleted(self) -> ImageEventData:
        """Emitted when an image is deleted."""
        ...

    @ws_event
    async def on_cleanup_completed(self) -> ImageEventData:
        """Emitted when cleanup completes."""
        ...
