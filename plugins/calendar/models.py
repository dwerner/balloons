"""Data models for the Calendar domain.

Calendars and events with support for recurrence and external sync.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, date, timedelta
from typing import Any
import uuid


def _now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


def _generate_id() -> str:
    """Generate a short unique ID."""
    return str(uuid.uuid4())[:8]


@dataclass
class RecurrenceRule:
    """Recurrence rule for repeating events (simplified RRULE)."""

    frequency: str  # "daily", "weekly", "monthly", "yearly"
    interval: int = 1  # Every N frequency units
    count: int | None = None  # Number of occurrences (None = infinite)
    until: date | None = None  # End date (None = infinite)
    by_day: list[str] | None = None  # For weekly: ["MO", "TU", "WE", ...]
    by_month_day: int | None = None  # For monthly: day of month (1-31)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frequency": self.frequency,
            "interval": self.interval,
            "count": self.count,
            "until": self.until.isoformat() if self.until else None,
            "byDay": self.by_day,
            "byMonthDay": self.by_month_day,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecurrenceRule":
        return cls(
            frequency=data["frequency"],
            interval=data.get("interval", 1),
            count=data.get("count"),
            until=date.fromisoformat(data["until"]) if data.get("until") else None,
            by_day=data.get("byDay"),
            by_month_day=data.get("byMonthDay"),
        )


@dataclass
class CalendarEvent:
    """A calendar event."""

    id: str
    title: str
    description: str
    start: datetime
    end: datetime
    all_day: bool
    location: str | None
    color: str | None  # Override calendar color
    recurrence: RecurrenceRule | None
    source: str  # "local", "ical", "google"
    source_id: str | None  # External ID for synced events
    source_url: str | None  # For iCal events, the source calendar URL
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        title: str,
        start: datetime,
        end: datetime,
        description: str = "",
        all_day: bool = False,
        location: str | None = None,
        color: str | None = None,
        recurrence: RecurrenceRule | None = None,
    ) -> "CalendarEvent":
        """Create a new local event."""
        now = _now()
        return cls(
            id=_generate_id(),
            title=title,
            description=description,
            start=start,
            end=end,
            all_day=all_day,
            location=location,
            color=color,
            recurrence=recurrence,
            source="local",
            source_id=None,
            source_url=None,
            metadata={},
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "allDay": self.all_day,
            "location": self.location,
            "color": self.color,
            "recurrence": self.recurrence.to_dict() if self.recurrence else None,
            "source": self.source,
            "sourceId": self.source_id,
            "sourceUrl": self.source_url,
            "metadata": self.metadata,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CalendarEvent":
        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]),
            all_day=data.get("allDay", False),
            location=data.get("location"),
            color=data.get("color"),
            recurrence=RecurrenceRule.from_dict(data["recurrence"]) if data.get("recurrence") else None,
            source=data.get("source", "local"),
            source_id=data.get("sourceId"),
            source_url=data.get("sourceUrl"),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data.get("createdAt", _now().isoformat())),
            updated_at=datetime.fromisoformat(data.get("updatedAt", _now().isoformat())),
        )

    def overlaps(self, other: "CalendarEvent") -> bool:
        """Check if this event overlaps with another."""
        return self.start < other.end and self.end > other.start


@dataclass
class SyncStatus:
    """Sync status for a calendar."""

    state: str  # "idle", "syncing", "synced", "error"
    last_synced: datetime | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "lastSynced": self.last_synced.isoformat() if self.last_synced else None,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SyncStatus":
        return cls(
            state=data.get("state", "idle"),
            last_synced=datetime.fromisoformat(data["lastSynced"]) if data.get("lastSynced") else None,
            error=data.get("error"),
        )

    @classmethod
    def idle(cls) -> "SyncStatus":
        return cls(state="idle", last_synced=None, error=None)


# Default calendar colors
DEFAULT_COLORS = [
    "#4285f4",  # Google Blue
    "#ea4335",  # Google Red
    "#fbbc05",  # Google Yellow
    "#34a853",  # Google Green
    "#8e44ad",  # Purple
    "#e67e22",  # Orange
    "#1abc9c",  # Teal
    "#e91e63",  # Pink
]


@dataclass
class Calendar:
    """A calendar containing events."""

    id: str
    name: str
    color: str
    provider: str  # "local", "ical"
    provider_config: dict[str, Any]  # URL for ical, credentials for google, etc.
    events: dict[str, CalendarEvent]  # event_id -> event
    sync_status: SyncStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        name: str,
        color: str | None = None,
        provider: str = "local",
        provider_config: dict[str, Any] | None = None,
    ) -> "Calendar":
        """Create a new calendar."""
        now = _now()
        # Pick a random default color if none provided
        import random
        if color is None:
            color = random.choice(DEFAULT_COLORS)

        return cls(
            id=_generate_id(),
            name=name,
            color=color,
            provider=provider,
            provider_config=provider_config or {},
            events={},
            sync_status=SyncStatus.idle(),
            created_at=now,
            updated_at=now,
        )

    def add_event(self, event: CalendarEvent) -> None:
        """Add an event to the calendar."""
        self.events[event.id] = event
        self.updated_at = _now()

    def remove_event(self, event_id: str) -> CalendarEvent | None:
        """Remove an event from the calendar."""
        event = self.events.pop(event_id, None)
        if event:
            self.updated_at = _now()
        return event

    def get_events_in_range(
        self,
        start: datetime,
        end: datetime,
    ) -> list[CalendarEvent]:
        """Get events that fall within a date range."""
        result = []
        for event in self.events.values():
            # Event overlaps range if it starts before range ends AND ends after range starts
            if event.start < end and event.end > start:
                result.append(event)
        # Sort by start time
        result.sort(key=lambda e: e.start)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "provider": self.provider,
            "providerConfig": self.provider_config,
            "events": [e.to_dict() for e in self.events.values()],
            "syncStatus": self.sync_status.to_dict(),
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Calendar":
        events_data = data.get("events", [])
        events = {}
        for e in events_data:
            event = CalendarEvent.from_dict(e)
            events[event.id] = event

        return cls(
            id=data["id"],
            name=data["name"],
            color=data.get("color", DEFAULT_COLORS[0]),
            provider=data.get("provider", "local"),
            provider_config=data.get("providerConfig", {}),
            events=events,
            sync_status=SyncStatus.from_dict(data.get("syncStatus", {})),
            created_at=datetime.fromisoformat(data.get("createdAt", _now().isoformat())),
            updated_at=datetime.fromisoformat(data.get("updatedAt", _now().isoformat())),
        )
