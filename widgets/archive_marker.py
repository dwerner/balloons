"""Archive marker widget - shows archived turns with rehydration support."""

from textual.widgets import Static
from textual.message import Message
from textual.events import Click
from rich.console import RenderableType
from rich.text import Text

from models import ArchiveBlock, ArchiveSummary


class ArchiveMarker(Static):
    """Shows archived turns with summary and rehydration option.

    Displays:
        📦 Archived: 7 turns (est. 2,400 tokens)
        Files: auth.py (created), utils.py (modified)
        Work: Implemented user authentication with JWT tokens
        Decisions: Used stateless auth, added refresh endpoint
        Archive: ~/.balloons/archives/session-id/archive-id.json

        Ctrl+Shift+Click to restore

    Ctrl+Shift+Click triggers rehydration (restores original turns).
    """

    DEFAULT_CSS = """
    ArchiveMarker {
        padding: 0 1;
        margin: 0 0 1 2;
        background: #1a2a2a;
        border-left: thick #4a9;
    }

    ArchiveMarker:hover {
        background: #2a3a3a;
    }

    ArchiveMarker.hidden {
        display: none;
    }

    /* Context mode visual indicators */
    ArchiveMarker.context-copy {
    }

    ArchiveMarker.context-compress {
        background: #2d2a1a;
    }

    ArchiveMarker.context-drop {
        opacity: 0.4;
    }
    """

    class RehydrateRequested(Message):
        """Posted when user ctrl+shift+clicks to rehydrate the archive."""

        def __init__(self, archive_id: str, turn_index: int, file_path: str) -> None:
            super().__init__()
            self.archive_id = archive_id
            self.turn_index = turn_index
            self.file_path = file_path

    def __init__(
        self,
        archive_block: ArchiveBlock,
        turn_id: int = 0,
        turn_index: int = 0,
        **kwargs
    ):
        """Create an archive marker.

        Args:
            archive_block: The ArchiveBlock data
            turn_id: Widget turn ID for chat log tracking
            turn_index: The turn index where this archive lives (for rehydration)
        """
        super().__init__(**kwargs)
        self.archive_block = archive_block
        self.turn_id = turn_id
        self.turn_index = turn_index

    def render(self) -> RenderableType:
        text = Text()
        block = self.archive_block

        # Header line
        text.append("📦 Archived: ", style="bold dim")
        text.append(f"{block.message_count} turns", style="cyan")
        if block.token_estimate > 0:
            text.append(f" (est. {block.token_estimate:,} tokens)", style="dim")
        text.append("\n")

        # Structured summary if available
        if block.structured_summary:
            summary = block.structured_summary

            # Files modified
            if summary.files_modified:
                text.append("Files: ", style="bold dim")
                files_str = ", ".join(summary.files_modified[:4])
                if len(summary.files_modified) > 4:
                    files_str += f" (+{len(summary.files_modified) - 4} more)"
                text.append(files_str, style="dim")
                text.append("\n")

            # Work done
            if summary.work_done:
                text.append("Work: ", style="bold dim")
                text.append(summary.work_done, style="italic")
                text.append("\n")

            # Key decisions
            if summary.key_decisions:
                text.append("Decisions: ", style="bold dim")
                decisions_str = "; ".join(summary.key_decisions[:3])
                if len(summary.key_decisions) > 3:
                    decisions_str += f" (+{len(summary.key_decisions) - 3} more)"
                text.append(decisions_str, style="dim italic")
                text.append("\n")
        elif block.summary:
            # Fallback to plain summary
            text.append(f'"{block.summary}"', style="italic dim")
            text.append("\n")

        # Show file path
        if block.file_path:
            text.append("Archive: ", style="bold dim")
            text.append(block.file_path, style="dim")
            text.append("\n")

        # Footer hint
        text.append("\nCtrl+Shift+Click to restore", style="dim")

        return text

    def on_click(self, event: Click) -> None:
        """Handle click - ctrl+shift+click triggers rehydration."""
        from core.debug_log import debug_log
        debug_log.info(
            f"ArchiveMarker clicked: ctrl={event.ctrl}, shift={event.shift}, "
            f"archive_id={self.archive_block.archive_id}",
            category="archive"
        )
        if event.ctrl and event.shift:
            debug_log.info(
                f"Posting RehydrateRequested for archive {self.archive_block.archive_id}",
                category="archive"
            )
            self.post_message(self.RehydrateRequested(
                self.archive_block.archive_id,
                self.turn_index,
                self.archive_block.file_path,
            ))
            event.stop()
