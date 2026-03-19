"""Typed event payloads for the Calendar domain.

Defines structured event data for type-safe event handling.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class CalendarCreatedPayload:
    """Payload for calendar_created event."""
    calendar_id: str
    name: str
    provider: str
    calendar: dict[str, Any]


@dataclass
class CalendarDeletedPayload:
    """Payload for calendar_deleted event."""
    calendar_id: str


@dataclass
class EventCreatedPayload:
    """Payload for event_created event."""
    calendar_id: str
    event: dict[str, Any]


@dataclass
class EventUpdatedPayload:
    """Payload for event_updated event."""
    calendar_id: str
    event: dict[str, Any]


@dataclass
class EventDeletedPayload:
    """Payload for event_deleted event."""
    calendar_id: str
    event_id: str


@dataclass
class SyncStatusPayload:
    """Payload for sync_status event."""
    calendar_id: str
    status: str  # "syncing", "synced", "error"
    error: str | None
    last_synced: str | None


@dataclass
class CalendarStateSyncPayload:
    """Payload for calendar_state_sync event.

    Emitted on reconnection or when state is requested.
    """
    calendars: list[dict[str, Any]]


# Map event types to their payload classes
EVENT_PAYLOADS = {
    "calendar_created": CalendarCreatedPayload,
    "calendar_deleted": CalendarDeletedPayload,
    "event_created": EventCreatedPayload,
    "event_updated": EventUpdatedPayload,
    "event_deleted": EventDeletedPayload,
    "sync_status": SyncStatusPayload,
    "calendar_state_sync": CalendarStateSyncPayload,
}
