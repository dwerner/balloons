"""Base protocol for calendar sync providers."""

from typing import Protocol, Any
from ..models import CalendarEvent


class CalendarProvider(Protocol):
    """Protocol for external calendar providers."""

    async def fetch_events(self, config: dict[str, Any]) -> list[CalendarEvent]:
        """Fetch events from the external source.

        Args:
            config: Provider-specific configuration (URL, credentials, etc.)

        Returns:
            List of events from the external source
        """
        ...

    def supports_write(self) -> bool:
        """Whether this provider supports creating/updating events."""
        ...
