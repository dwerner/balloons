"""Breadcrumb widget - shows current location in session hierarchy."""

from textual.widgets import Static
from textual.message import Message
from rich.console import RenderableType
from rich.text import Text

from session import Session


class Breadcrumb(Static):
    """Shows the current location in the session hierarchy.

    Displays a path like:
        Main Session > auth-bug > deep-dive

    Each segment is clickable to navigate up the hierarchy.
    Shows [merged] indicator for read-only forks.
    """

    DEFAULT_CSS = """
    Breadcrumb {
        height: auto;
        padding: 0 1;
        background: $surface;
        color: $text;
        border-bottom: solid $primary;
    }

    Breadcrumb.hidden {
        display: none;
    }
    """

    class SegmentClicked(Message):
        """Posted when user clicks a breadcrumb segment."""

        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._session: Session | None = None
        self._path: list[dict] = []  # [{session_id, name, is_merged}]
        self._binding_indicator: str = ""  # Role/binding for current session

    def render(self) -> RenderableType:
        if not self._path:
            return Text("")

        text = Text()
        for i, segment in enumerate(self._path):
            if i > 0:
                text.append(" > ", style="dim")

            name = segment["name"]
            is_merged = segment.get("is_merged", False)
            is_last = i == len(self._path) - 1

            if is_last:
                # Current location - bold
                text.append(name, style="bold cyan")
                if self._binding_indicator:
                    text.append(f" {self._binding_indicator}", style="magenta")
                if is_merged:
                    text.append(" [merged]", style="dim green")
            else:
                # Ancestor - clickable
                text.append(name, style="underline")

        return text

    async def set_session(self, session: Session, binding_indicator: str = "") -> None:
        """Update the breadcrumb to show the path to the given session.

        Args:
            session: The current session
            binding_indicator: Optional role/binding text like "[impl: Add caching]"
        """
        self._session = session
        self._binding_indicator = binding_indicator
        self._path = await self._build_path(session)
        self.remove_class("hidden")
        self.refresh()

    def update_binding_indicator(self, indicator: str) -> None:
        """Update just the binding indicator without rebuilding the path."""
        self._binding_indicator = indicator
        self.refresh()

    async def _build_path(self, session: Session) -> list[dict]:
        """Build the path from root session to current."""
        path = []

        # Walk up to root, collecting ancestors
        current = session
        while current:
            name = self._get_session_name(current)
            path.append({
                "session_id": current.id,
                "name": name,
                "is_merged": current.is_merged(),
            })
            if current.parent_id:
                current = await Session.load(current.parent_id)
            else:
                current = None

        # Reverse to get root-to-current order
        path.reverse()
        return path

    def _get_session_name(self, session: Session) -> str:
        """Get a display name for a session."""
        if session.fork_name:
            return session.fork_name
        elif session.title:
            return session.title[:20] + "..." if len(session.title) > 20 else session.title
        else:
            return session.id[:8]

    def on_click(self, event) -> None:
        """Handle clicks on breadcrumb segments.

        Note: This is a simplified implementation. For proper per-segment
        click handling, we'd need to track segment positions.
        """
        # For now, clicking anywhere navigates to parent (if in a fork)
        if len(self._path) > 1:
            # Navigate to parent (second-to-last in path)
            parent_segment = self._path[-2]
            self.post_message(self.SegmentClicked(parent_segment["session_id"]))

    def clear(self) -> None:
        """Clear the breadcrumb."""
        self._session = None
        self._path = []
        self._binding_indicator = ""
        self.add_class("hidden")
        self.refresh()
