"""Message stash popup widget.

Allows users to stash draft messages and retrieve them later.
Similar to command completion popup but for stored messages.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
import yaml

from textual.widgets import Static
from textual.message import Message
from textual.events import Key
from rich.text import Text


@dataclass
class StashedMessage:
    """A stashed draft message."""
    content: str
    name: Optional[str] = None  # User-provided name
    timestamp: datetime = field(default_factory=datetime.now)

    def display_name(self) -> str:
        """Get display name for the stash entry."""
        if self.name:
            return self.name
        # Show first 30 chars of content, single line
        preview = self.content.replace("\n", " ")[:30]
        if len(self.content) > 30:
            preview += "..."
        return preview

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
        """Load stash from file."""
        if self._stash_file.exists():
            try:
                with open(self._stash_file) as f:
                    data = yaml.safe_load(f) or {}
                self._messages = [
                    StashedMessage.from_dict(m) for m in data.get("messages", [])
                ]
            except Exception:
                self._messages = []

    def _save(self) -> None:
        """Save stash to file."""
        self._stash_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"messages": [m.to_dict() for m in self._messages]}
        with open(self._stash_file, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)

    def add(self, content: str, name: Optional[str] = None) -> StashedMessage:
        """Add a message to the stash."""
        msg = StashedMessage(content=content, name=name)
        self._messages.insert(0, msg)  # Most recent first
        self._save()
        return msg

    def remove(self, index: int) -> Optional[StashedMessage]:
        """Remove and return message at index."""
        if 0 <= index < len(self._messages):
            msg = self._messages.pop(index)
            self._save()
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


class StashPopup(Static, can_focus=True):
    """Popup showing stashed messages for selection."""

    DEFAULT_CSS = """
    StashPopup {
        background: $surface;
        border: solid $secondary;
        padding: 0 1;
        min-width: 30;
        height: auto;
        max-height: 14;
        max-width: 60;
    }
    StashPopup:focus {
        border: solid $accent;
    }
    """

    class MessageSelected(Message):
        """Emitted when user selects a stashed message."""
        def __init__(self, message: StashedMessage, index: int) -> None:
            self.message = message
            self.index = index
            super().__init__()

    class MessageDeleted(Message):
        """Emitted when user deletes a stashed message."""
        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    class Closed(Message):
        """Emitted when popup is closed without selection."""
        pass

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)  # Initialize with empty content
        self._messages: list[StashedMessage] = []
        self._selected_index: int = 0

    def show_messages(self, messages: list[StashedMessage]) -> None:
        """Show stash popup with given messages."""
        self._messages = messages
        self._selected_index = 0
        self._refresh_display()
        self.display = True
        self.focus()

    def hide(self) -> None:
        """Hide the popup."""
        self.display = False
        self._messages = []

    def cycle(self, delta: int) -> None:
        """Cycle through messages by delta."""
        if not self._messages:
            return
        self._selected_index = (self._selected_index + delta) % len(self._messages)
        self._refresh_display()

    def select_current(self) -> None:
        """Select the currently highlighted message."""
        if self._messages and 0 <= self._selected_index < len(self._messages):
            self.post_message(self.MessageSelected(
                self._messages[self._selected_index],
                self._selected_index
            ))

    def delete_current(self) -> None:
        """Delete the currently highlighted message."""
        if self._messages and 0 <= self._selected_index < len(self._messages):
            self.post_message(self.MessageDeleted(self._selected_index))

    @property
    def selected_index(self) -> int:
        return self._selected_index

    async def _on_key(self, event: Key) -> None:
        """Handle key events when popup has focus."""
        if event.key == "up":
            event.prevent_default()
            event.stop()
            self.cycle(-1)
        elif event.key == "down":
            event.prevent_default()
            event.stop()
            self.cycle(1)
        elif event.key == "enter":
            event.prevent_default()
            event.stop()
            self.select_current()
        elif event.key in ("delete", "backspace"):
            event.prevent_default()
            event.stop()
            self.delete_current()
        elif event.key == "escape":
            event.prevent_default()
            event.stop()
            self.post_message(self.Closed())

    def _refresh_display(self) -> None:
        """Update the displayed message list."""
        if not self._messages:
            self.update(Text("(empty)", style="dim italic"))
            return

        result = Text()

        # Header with title
        result.append("📋 Stash", style="bold cyan")
        result.append(f" ({len(self._messages)})\n", style="dim")

        # Message list
        for i, msg in enumerate(self._messages):
            name = msg.display_name()
            if i == self._selected_index:
                result.append(" › ", style="bold cyan")
                result.append(f"{name}\n", style="reverse")
            else:
                result.append("   ", style="dim")
                result.append(f"{name}\n", style="")

        # Help line with shortcuts
        result.append("─" * 28 + "\n", style="dim")
        result.append("↑↓", style="bold cyan")
        result.append(" nav  ", style="dim")
        result.append("Enter", style="bold cyan")
        result.append(" pop  ", style="dim")
        result.append("Del", style="bold cyan")
        result.append(" rm  ", style="dim")
        result.append("Esc", style="bold cyan")
        result.append(" close", style="dim")

        self.update(result)
