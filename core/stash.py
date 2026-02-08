"""Message stash - persistent storage for draft messages.

This module provides GUI-independent data models and persistence
for the message stash feature.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiofiles
import yaml


@dataclass
class StashedMessage:
    """A stashed draft message."""
    content: str
    name: Optional[str] = None  # User-provided name
    timestamp: datetime = field(default_factory=datetime.now)

    def display_name(self) -> str:
        """Get display name for the stash entry.

        Returns full content (newlines replaced with spaces).
        Truncation is handled by the popup widget based on available width.
        """
        if self.name:
            return self.name
        # Return full content, single line (let widget handle truncation)
        return self.content.replace("\n", " ")

    def to_dict(self) -> dict:
        """Convert to dict for YAML serialization."""
        return {
            "content": self.content,
            "name": self.name,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StashedMessage":
        """Create from dict (YAML deserialization)."""
        return cls(
            content=data["content"],
            name=data.get("name"),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(),
        )


class MessageStash:
    """Persistent storage for stashed messages."""

    def __init__(self, stash_file: Optional[Path] = None):
        self._stash_file = stash_file or (Path.home() / ".balloons" / "stash.yaml")
        self._messages: list[StashedMessage] = []
        self._load()

    def _load(self) -> None:
        """Load stash from file (sync, used at init)."""
        if self._stash_file.exists():
            try:
                with open(self._stash_file) as f:
                    data = yaml.safe_load(f) or {}
                self._messages = [
                    StashedMessage.from_dict(m) for m in data.get("messages", [])
                ]
            except Exception:
                self._messages = []

    async def _save_async(self) -> None:
        """Save stash to file (async, non-blocking)."""
        self._stash_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"messages": [m.to_dict() for m in self._messages]}
        content = yaml.safe_dump(data, default_flow_style=False)
        async with aiofiles.open(self._stash_file, "w") as f:
            await f.write(content)

    def _schedule_save(self) -> None:
        """Schedule an async save (fire-and-forget)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._save_async())
        except RuntimeError:
            # No event loop - fall back to sync save
            self._stash_file.parent.mkdir(parents=True, exist_ok=True)
            data = {"messages": [m.to_dict() for m in self._messages]}
            with open(self._stash_file, "w") as f:
                yaml.safe_dump(data, f, default_flow_style=False)

    def add(self, content: str, name: Optional[str] = None) -> StashedMessage:
        """Add a message to the stash."""
        msg = StashedMessage(content=content, name=name)
        self._messages.insert(0, msg)  # Most recent first
        self._schedule_save()
        return msg

    def remove(self, index: int) -> Optional[StashedMessage]:
        """Remove and return message at index."""
        if 0 <= index < len(self._messages):
            msg = self._messages.pop(index)
            self._schedule_save()
            return msg
        return None

    def get(self, index: int) -> Optional[StashedMessage]:
        """Get message at index without removing."""
        if 0 <= index < len(self._messages):
            return self._messages[index]
        return None

    def pop(self, index: int) -> Optional[StashedMessage]:
        """Remove and return message at index."""
        return self.remove(index)

    def all(self) -> list[StashedMessage]:
        """Get all stashed messages."""
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)
