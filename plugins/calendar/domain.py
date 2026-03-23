"""Calendar domain plugin.

Provides calendar functionality with local calendars and iCal sync support.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, TYPE_CHECKING
import os

from codegen.ws_expose import ws_expose
from ..base import DomainEvent, DecoratedStatefulDomain, ToolResult
from ..decorators import llm_callable, Param
from ..storage import JsonFileStorage
from .. import PluginLogger
from .models import Calendar, CalendarEvent, SyncStatus, _now
from .events import (
    CalendarCreatedPayload,
    CalendarDeletedPayload,
    EventCreatedPayload,
    EventUpdatedPayload,
    EventDeletedPayload,
    SyncStatusPayload,
    CalendarStateSyncPayload,
)
from .sync.ical import ICalProvider

if TYPE_CHECKING:
    from session import Session

# Plugin logger
log = PluginLogger("calendar")


# Global in-memory cache for calendars
_calendars: dict[str, Calendar] = {}
_calendars_loaded: bool = False

# Persistent storage
_storage: JsonFileStorage | None = None


def _get_storage() -> JsonFileStorage:
    """Get the persistent storage instance."""
    global _storage
    if _storage is None:
        _storage = JsonFileStorage("calendar")
    return _storage


async def _load_all_calendars() -> None:
    """Load all calendars from storage."""
    global _calendars_loaded
    if _calendars_loaded:
        return

    storage = _get_storage()
    calendar_ids = await storage.list_keys()

    for calendar_id in calendar_ids:
        calendar_data = await storage.load(calendar_id)
        if calendar_data:
            _calendars[calendar_id] = Calendar.from_dict(calendar_data)

    _calendars_loaded = True


async def _save_calendar(calendar: Calendar) -> None:
    """Save a single calendar to storage."""
    storage = _get_storage()
    await storage.save(calendar.id, calendar.to_dict())


async def _delete_calendar_file(calendar_id: str) -> None:
    """Delete a calendar's storage file."""
    storage = _get_storage()
    await storage.delete(calendar_id)


class CalendarDomain(DecoratedStatefulDomain):
    """Calendar domain providing persistent calendar and event management.

    Tools:
        - calendar_list: List all calendars
        - calendar_create: Create a new local calendar
        - calendar_delete: Delete a calendar
        - calendar_connect_ical: Connect an iCal feed
        - calendar_sync: Sync a calendar with its provider
        - calendar_create_event: Create a new event
        - calendar_update_event: Update an existing event
        - calendar_delete_event: Delete an event
        - calendar_get_events: Get events in a date range

    Events emitted:
        - calendar_created: New calendar created
        - calendar_deleted: Calendar deleted
        - event_created: Event created
        - event_updated: Event updated
        - event_deleted: Event deleted
        - sync_status: Sync status changed
        - calendar_state_sync: Full state sync
    """

    def __init__(self):
        self._ical_provider = ICalProvider()

    @property
    def id(self) -> str:
        return "calendar"

    @property
    def name(self) -> str:
        return "Calendar"

    @property
    def version(self) -> str:
        return "0.1.0"

    def get_prompt(self) -> str:
        """Load prompt from prompt.md file."""
        prompt_path = os.path.join(os.path.dirname(__file__), "prompt.md")
        try:
            with open(prompt_path, "r") as f:
                return f.read()
        except FileNotFoundError:
            return """## Calendar Domain

You can create and manage calendars and events using the calendar_* tools.
Supports local calendars and iCal feed imports."""

    def get_ui_config(self) -> dict | None:
        """Return UI configuration for the calendar domain."""
        return {
            "components": [
                {
                    "name": "CalendarTab",
                    "path": "plugins/calendar/ui/CalendarTab.tsx",
                    "description": "Calendar view with month and Gantt modes",
                },
            ],
            "tabs": [
                {
                    "id": "calendar",
                    "label": "Calendar",
                    "icon": "\U0001F4C5",  # Calendar emoji
                    "component": "CalendarTab",
                },
            ],
        }

    def _find_calendar(self, calendar_id: str) -> Calendar | None:
        """Find a calendar by ID (supports prefix matching)."""
        # Exact match first
        if calendar_id in _calendars:
            return _calendars[calendar_id]
        # Prefix match
        for cid, calendar in _calendars.items():
            if cid.startswith(calendar_id):
                return calendar
        # Name match (case-insensitive)
        for calendar in _calendars.values():
            if calendar.name.lower() == calendar_id.lower():
                return calendar
        return None

    def _find_event(self, event_id: str) -> tuple[CalendarEvent | None, Calendar | None]:
        """Find an event by ID across all calendars."""
        for calendar in _calendars.values():
            # Exact match
            if event_id in calendar.events:
                return calendar.events[event_id], calendar
            # Prefix match
            for eid, event in calendar.events.items():
                if eid.startswith(event_id):
                    return event, calendar
        return None, None

    # --- LLM-callable tools ---

    @llm_callable(description="List all calendars with their sync status and event counts.")
    async def calendar_list(self, session: "Session" = None) -> ToolResult:
        """List all calendars."""
        await _load_all_calendars()

        if not _calendars:
            return ToolResult(
                "No calendars found. Use calendar_create to create a local calendar, "
                "or calendar_connect_ical to import an iCal feed."
            )

        lines = ["Calendars:", ""]
        for calendar in _calendars.values():
            provider_info = f"({calendar.provider})" if calendar.provider != "local" else "(local)"
            sync_info = ""
            if calendar.provider != "local":
                status = calendar.sync_status
                if status.last_synced:
                    sync_info = f" - Last synced: {status.last_synced.strftime('%Y-%m-%d %H:%M')}"
                if status.error:
                    sync_info += f" [ERROR: {status.error}]"

            lines.append(
                f"  [{calendar.id}] {calendar.name} {provider_info} - {len(calendar.events)} events{sync_info}"
            )

        # Emit sync event for UI
        event = DomainEvent(
            type="calendar_state_sync",
            source_domain=self.id,
            payload=CalendarStateSyncPayload(
                calendars=[c.to_dict() for c in _calendars.values()],
            ),
            target_session=session.id,
        )

        return ToolResult("\n".join(lines), events=[event])

    @ws_expose
    @llm_callable(
        description="Create a new local calendar.",
        params={
            "name": Param(str, "Name for the calendar (e.g., 'Work', 'Personal')"),
            "color": Param(str, "Hex color for the calendar (e.g., '#4285f4')", required=False),
        },
    )
    async def calendar_create(
        self,
        name: str,
        color: str | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """Create a new local calendar."""
        await _load_all_calendars()

        name = name.strip()
        if not name:
            return ToolResult("Calendar name is required", is_error=True)

        calendar = Calendar.create(name=name, color=color)
        _calendars[calendar.id] = calendar

        await _save_calendar(calendar)
        log.info(f"Created calendar: {name}", session_id=session.id, details={"calendar_id": calendar.id})

        event = DomainEvent(
            type="calendar_created",
            source_domain=self.id,
            payload=CalendarCreatedPayload(
                calendar_id=calendar.id,
                name=calendar.name,
                provider=calendar.provider,
                calendar=calendar.to_dict(),
            ),
            target_session=session.id,
        )

        return ToolResult(
            f"Created calendar '{name}' with ID: {calendar.id}\nColor: {calendar.color}",
            events=[event],
        )

    @llm_callable(
        description="Delete a calendar and all its events.",
        params={
            "calendar_id": Param(str, "Calendar ID or name to delete"),
        },
    )
    async def calendar_delete(
        self,
        calendar_id: str,
        session: "Session" = None,
    ) -> ToolResult:
        """Delete a calendar."""
        await _load_all_calendars()

        calendar = self._find_calendar(calendar_id.strip())
        if not calendar:
            return ToolResult(f"Calendar not found: {calendar_id}", is_error=True)

        cal_id = calendar.id
        cal_name = calendar.name
        del _calendars[cal_id]

        await _delete_calendar_file(cal_id)
        log.info(f"Deleted calendar: {cal_name}", session_id=session.id, details={"calendar_id": cal_id})

        event = DomainEvent(
            type="calendar_deleted",
            source_domain=self.id,
            payload=CalendarDeletedPayload(calendar_id=cal_id),
            target_session=session.id,
        )

        return ToolResult(f"Deleted calendar '{cal_name}'", events=[event])

    @llm_callable(
        description="""Connect an iCal feed by URL. Creates a read-only calendar that syncs from the URL.

Supports:
- webcal:// URLs (automatically converted to https://)
- .ics file URLs
- Google Calendar public URLs
- Apple iCloud public calendar URLs""",
        params={
            "name": Param(str, "Name for the calendar"),
            "url": Param(str, "iCal feed URL (webcal:// or https://)"),
            "color": Param(str, "Hex color for the calendar", required=False),
        },
    )
    async def calendar_connect_ical(
        self,
        name: str,
        url: str,
        color: str | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """Connect an iCal feed."""
        await _load_all_calendars()

        name = name.strip()
        url = url.strip()

        if not name:
            return ToolResult("Calendar name is required", is_error=True)
        if not url:
            return ToolResult("iCal URL is required", is_error=True)

        # Create the calendar
        calendar = Calendar.create(
            name=name,
            color=color,
            provider="ical",
            provider_config={"url": url},
        )

        # Try to sync immediately
        calendar.sync_status = SyncStatus(state="syncing", last_synced=None, error=None)

        try:
            events = await self._ical_provider.fetch_events({"url": url})
            for event in events:
                calendar.add_event(event)

            calendar.sync_status = SyncStatus(state="synced", last_synced=_now(), error=None)
            log.info(
                f"Connected iCal: {name}",
                session_id=session.id,
                details={"calendar_id": calendar.id, "events": len(events)},
            )

        except Exception as e:
            calendar.sync_status = SyncStatus(state="error", last_synced=None, error=str(e))
            log.error(
                f"Failed to sync iCal: {name}",
                session_id=session.id,
                details={"error": str(e)},
            )

        _calendars[calendar.id] = calendar
        await _save_calendar(calendar)

        event = DomainEvent(
            type="calendar_created",
            source_domain=self.id,
            payload=CalendarCreatedPayload(
                calendar_id=calendar.id,
                name=calendar.name,
                provider=calendar.provider,
                calendar=calendar.to_dict(),
            ),
            target_session=session.id,
        )

        if calendar.sync_status.error:
            return ToolResult(
                f"Created calendar '{name}' but sync failed: {calendar.sync_status.error}\n"
                f"Calendar ID: {calendar.id}",
                events=[event],
            )

        return ToolResult(
            f"Created calendar '{name}' with {len(calendar.events)} events from iCal feed.\n"
            f"Calendar ID: {calendar.id}",
            events=[event],
        )

    @llm_callable(
        description="Sync a calendar with its external provider (iCal). Re-fetches all events.",
        params={
            "calendar_id": Param(str, "Calendar ID or name to sync"),
        },
    )
    async def calendar_sync(
        self,
        calendar_id: str,
        session: "Session" = None,
    ) -> ToolResult:
        """Sync a calendar with its provider."""
        await _load_all_calendars()

        calendar = self._find_calendar(calendar_id.strip())
        if not calendar:
            return ToolResult(f"Calendar not found: {calendar_id}", is_error=True)

        if calendar.provider == "local":
            return ToolResult("Local calendars don't need syncing", is_error=True)

        # Emit syncing status
        calendar.sync_status = SyncStatus(state="syncing", last_synced=calendar.sync_status.last_synced, error=None)

        sync_event = DomainEvent(
            type="sync_status",
            source_domain=self.id,
            payload=SyncStatusPayload(
                calendar_id=calendar.id,
                status="syncing",
                error=None,
                last_synced=calendar.sync_status.last_synced.isoformat() if calendar.sync_status.last_synced else None,
            ),
            target_session=session.id,
        )

        try:
            if calendar.provider == "ical":
                events = await self._ical_provider.fetch_events(calendar.provider_config)

                # Replace all events (full sync)
                old_count = len(calendar.events)
                calendar.events = {}
                for event in events:
                    calendar.add_event(event)

                calendar.sync_status = SyncStatus(state="synced", last_synced=_now(), error=None)
                await _save_calendar(calendar)

                log.info(
                    f"Synced iCal: {calendar.name}",
                    session_id=session.id,
                    details={"old_events": old_count, "new_events": len(events)},
                )

                # Emit state sync
                state_event = DomainEvent(
                    type="calendar_state_sync",
                    source_domain=self.id,
                    payload=CalendarStateSyncPayload(
                        calendars=[c.to_dict() for c in _calendars.values()],
                    ),
                    target_session=session.id,
                )

                return ToolResult(
                    f"Synced '{calendar.name}': {len(events)} events",
                    events=[sync_event, state_event],
                )

        except Exception as e:
            calendar.sync_status = SyncStatus(
                state="error",
                last_synced=calendar.sync_status.last_synced,
                error=str(e),
            )
            await _save_calendar(calendar)

            error_event = DomainEvent(
                type="sync_status",
                source_domain=self.id,
                payload=SyncStatusPayload(
                    calendar_id=calendar.id,
                    status="error",
                    error=str(e),
                    last_synced=calendar.sync_status.last_synced.isoformat() if calendar.sync_status.last_synced else None,
                ),
                target_session=session.id,
            )

            return ToolResult(f"Sync failed: {e}", is_error=True, events=[error_event])

        return ToolResult(f"Unsupported provider: {calendar.provider}", is_error=True)

    @ws_expose
    @llm_callable(
        description="""Create a new event on a calendar.

Times should be in ISO 8601 format (e.g., '2024-03-15T09:00:00' or '2024-03-15T09:00:00Z').
For all-day events, set all_day=true and use date-only format (e.g., '2024-03-15').""",
        params={
            "calendar_id": Param(str, "Calendar ID or name to add the event to"),
            "title": Param(str, "Event title"),
            "start": Param(str, "Start time in ISO format"),
            "end": Param(str, "End time in ISO format"),
            "description": Param(str, "Event description", required=False),
            "location": Param(str, "Event location", required=False),
            "all_day": Param(bool, "Whether this is an all-day event", required=False),
            "color": Param(str, "Override color (hex)", required=False),
        },
    )
    async def calendar_create_event(
        self,
        calendar_id: str,
        title: str,
        start: str,
        end: str,
        description: str = "",
        location: str | None = None,
        all_day: bool = False,
        color: str | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """Create a new event."""
        await _load_all_calendars()

        calendar = self._find_calendar(calendar_id.strip())
        if not calendar:
            return ToolResult(f"Calendar not found: {calendar_id}", is_error=True)

        if calendar.provider != "local":
            return ToolResult(
                f"Cannot create events on {calendar.provider} calendars (read-only)",
                is_error=True,
            )

        title = title.strip()
        if not title:
            return ToolResult("Event title is required", is_error=True)

        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return ToolResult(f"Invalid start time format: {start}", is_error=True)

        try:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return ToolResult(f"Invalid end time format: {end}", is_error=True)

        if end_dt <= start_dt:
            return ToolResult("End time must be after start time", is_error=True)

        event = CalendarEvent.create(
            title=title,
            start=start_dt,
            end=end_dt,
            description=description,
            location=location,
            all_day=all_day,
            color=color,
        )

        calendar.add_event(event)
        await _save_calendar(calendar)

        log.info(
            f"Created event: {title}",
            session_id=session.id,
            details={"event_id": event.id, "calendar_id": calendar.id},
        )

        domain_event = DomainEvent(
            type="event_created",
            source_domain=self.id,
            payload=EventCreatedPayload(
                calendar_id=calendar.id,
                event=event.to_dict(),
            ),
            target_session=session.id,
        )

        return ToolResult(
            f"Created event '{title}' on {calendar.name}\n"
            f"Event ID: {event.id}\n"
            f"Time: {start_dt.strftime('%Y-%m-%d %H:%M')} - {end_dt.strftime('%Y-%m-%d %H:%M')}",
            events=[domain_event],
        )

    @ws_expose
    @llm_callable(
        description="Update an existing event. Only provided fields are updated.",
        params={
            "event_id": Param(str, "Event ID to update"),
            "title": Param(str, "New title", required=False),
            "start": Param(str, "New start time (ISO format)", required=False),
            "end": Param(str, "New end time (ISO format)", required=False),
            "description": Param(str, "New description", required=False),
            "location": Param(str, "New location", required=False),
            "color": Param(str, "New color (hex)", required=False),
        },
    )
    async def calendar_update_event(
        self,
        event_id: str,
        title: str | None = None,
        start: str | None = None,
        end: str | None = None,
        description: str | None = None,
        location: str | None = None,
        color: str | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """Update an existing event."""
        await _load_all_calendars()

        event, calendar = self._find_event(event_id.strip())
        if not event or not calendar:
            return ToolResult(f"Event not found: {event_id}", is_error=True)

        if event.source != "local":
            return ToolResult(
                f"Cannot update {event.source} events (read-only)",
                is_error=True,
            )

        if title is not None:
            event.title = title.strip()

        if start is not None:
            try:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                event.start = start_dt
            except ValueError:
                return ToolResult(f"Invalid start time format: {start}", is_error=True)

        if end is not None:
            try:
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                event.end = end_dt
            except ValueError:
                return ToolResult(f"Invalid end time format: {end}", is_error=True)

        if event.end <= event.start:
            return ToolResult("End time must be after start time", is_error=True)

        if description is not None:
            event.description = description
        if location is not None:
            event.location = location
        if color is not None:
            event.color = color

        event.updated_at = _now()
        await _save_calendar(calendar)

        domain_event = DomainEvent(
            type="event_updated",
            source_domain=self.id,
            payload=EventUpdatedPayload(
                calendar_id=calendar.id,
                event=event.to_dict(),
            ),
            target_session=session.id,
        )

        return ToolResult(f"Updated event '{event.title}'", events=[domain_event])

    @llm_callable(
        description="Delete an event from a calendar.",
        params={
            "event_id": Param(str, "Event ID to delete"),
        },
    )
    async def calendar_delete_event(
        self,
        event_id: str,
        session: "Session" = None,
    ) -> ToolResult:
        """Delete an event."""
        await _load_all_calendars()

        event, calendar = self._find_event(event_id.strip())
        if not event or not calendar:
            return ToolResult(f"Event not found: {event_id}", is_error=True)

        if event.source != "local":
            return ToolResult(
                f"Cannot delete {event.source} events (read-only)",
                is_error=True,
            )

        event_title = event.title
        calendar.remove_event(event.id)
        await _save_calendar(calendar)

        log.info(
            f"Deleted event: {event_title}",
            session_id=session.id,
            details={"event_id": event.id, "calendar_id": calendar.id},
        )

        domain_event = DomainEvent(
            type="event_deleted",
            source_domain=self.id,
            payload=EventDeletedPayload(
                calendar_id=calendar.id,
                event_id=event.id,
            ),
            target_session=session.id,
        )

        return ToolResult(f"Deleted event '{event_title}'", events=[domain_event])

    @llm_callable(
        description="""Get events within a date range.

Returns events from all calendars or a specific calendar.
Dates should be in ISO format (e.g., '2024-03-01' or '2024-03-01T00:00:00').""",
        params={
            "start": Param(str, "Start of range (ISO date or datetime)"),
            "end": Param(str, "End of range (ISO date or datetime)"),
            "calendar_id": Param(str, "Filter to specific calendar (optional)", required=False),
        },
    )
    async def calendar_get_events(
        self,
        start: str,
        end: str,
        calendar_id: str | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """Get events in a date range."""
        await _load_all_calendars()

        try:
            # Parse start/end - handle date-only format
            if "T" not in start:
                start_dt = datetime.fromisoformat(start + "T00:00:00").replace(tzinfo=timezone.utc)
            else:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return ToolResult(f"Invalid start date format: {start}", is_error=True)

        try:
            if "T" not in end:
                end_dt = datetime.fromisoformat(end + "T23:59:59").replace(tzinfo=timezone.utc)
            else:
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return ToolResult(f"Invalid end date format: {end}", is_error=True)

        # Get calendars to search
        if calendar_id:
            calendar = self._find_calendar(calendar_id.strip())
            if not calendar:
                return ToolResult(f"Calendar not found: {calendar_id}", is_error=True)
            calendars = [calendar]
        else:
            calendars = list(_calendars.values())

        all_events: list[tuple[Calendar, CalendarEvent]] = []
        for cal in calendars:
            events = cal.get_events_in_range(start_dt, end_dt)
            for event in events:
                all_events.append((cal, event))

        # Sort by start time
        all_events.sort(key=lambda x: x[1].start)

        if not all_events:
            return ToolResult(f"No events found between {start} and {end}")

        lines = [f"Events from {start} to {end}:", ""]
        for cal, event in all_events:
            if event.all_day:
                time_str = event.start.strftime("%Y-%m-%d") + " (all day)"
            else:
                time_str = (
                    f"{event.start.strftime('%Y-%m-%d %H:%M')} - "
                    f"{event.end.strftime('%H:%M')}"
                )

            lines.append(f"  [{event.id}] {event.title}")
            lines.append(f"      {time_str} | {cal.name}")
            if event.location:
                lines.append(f"      Location: {event.location}")
            lines.append("")

        # Emit sync for UI
        state_event = DomainEvent(
            type="calendar_state_sync",
            source_domain=self.id,
            payload=CalendarStateSyncPayload(
                calendars=[c.to_dict() for c in _calendars.values()],
            ),
            target_session=session.id,
        )

        return ToolResult("\n".join(lines), events=[state_event])

    # --- StatefulDomain methods ---

    async def get_state(self, session: "Session") -> dict[str, Any] | None:
        """Return current calendar state."""
        await _load_all_calendars()
        if not _calendars:
            return None

        return {
            "calendars": [c.to_dict() for c in _calendars.values()],
        }

    async def save_state(self, session: "Session") -> dict[str, Any]:
        """Save all calendars to persistent storage."""
        for calendar in _calendars.values():
            await _save_calendar(calendar)

        return {
            "calendars": [c.to_dict() for c in _calendars.values()],
        }

    async def load_state(self, session: "Session", state: dict[str, Any]) -> None:
        """Load calendars from persistent storage."""
        await _load_all_calendars()

    async def clear_state(self, session: "Session") -> None:
        """Clear all calendars."""
        global _calendars_loaded
        storage = _get_storage()

        for calendar_id in list(_calendars.keys()):
            await storage.delete(calendar_id)

        _calendars.clear()
        _calendars_loaded = False


def create_domain() -> CalendarDomain:
    """Factory function for domain loading."""
    return CalendarDomain()
