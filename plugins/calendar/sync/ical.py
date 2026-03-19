"""iCal (.ics) calendar sync provider.

Supports fetching events from iCal URLs (read-only).
"""

import re
from datetime import datetime, timezone, timedelta, date
from typing import Any
import urllib.request
import ssl

from ..models import CalendarEvent, RecurrenceRule, _now, _generate_id


class ICalProvider:
    """Provider for iCal (.ics) feeds."""

    def supports_write(self) -> bool:
        """iCal feeds are read-only."""
        return False

    async def fetch_events(self, config: dict[str, Any]) -> list[CalendarEvent]:
        """Fetch events from an iCal URL.

        Args:
            config: Must contain "url" key with the iCal feed URL

        Returns:
            List of CalendarEvent objects
        """
        url = config.get("url")
        if not url:
            raise ValueError("iCal config must include 'url'")

        # Handle webcal:// protocol
        if url.startswith("webcal://"):
            url = "https://" + url[9:]

        # Fetch the iCal data
        ical_data = await self._fetch_url(url)

        # Parse and return events
        return self._parse_ical(ical_data, url)

    async def _fetch_url(self, url: str) -> str:
        """Fetch content from a URL."""
        # Create SSL context that doesn't verify (some calendar servers have issues)
        ctx = ssl.create_default_context()

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Balloons Calendar/1.0",
                "Accept": "text/calendar, */*",
            },
        )

        try:
            with urllib.request.urlopen(request, context=ctx, timeout=30) as response:
                return response.read().decode("utf-8")
        except Exception as e:
            raise ValueError(f"Failed to fetch iCal feed: {e}")

    def _parse_ical(self, ical_data: str, source_url: str) -> list[CalendarEvent]:
        """Parse iCal data into CalendarEvent objects.

        This is a simplified parser that handles common VEVENT properties.
        For full RFC 5545 compliance, consider using the icalendar library.
        """
        events = []
        lines = self._unfold_lines(ical_data)

        current_event: dict[str, Any] | None = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line == "BEGIN:VEVENT":
                current_event = {}
            elif line == "END:VEVENT":
                if current_event:
                    event = self._make_event(current_event, source_url)
                    if event:
                        events.append(event)
                current_event = None
            elif current_event is not None:
                # Parse property
                key, value = self._parse_property(line)
                if key:
                    current_event[key] = value

        return events

    def _unfold_lines(self, data: str) -> list[str]:
        """Unfold continuation lines per RFC 5545.

        Lines that start with a space or tab are continuations.
        """
        lines = data.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        result = []

        for line in lines:
            if line.startswith((" ", "\t")) and result:
                # Continuation of previous line
                result[-1] += line[1:]
            else:
                result.append(line)

        return result

    def _parse_property(self, line: str) -> tuple[str | None, Any]:
        """Parse an iCal property line.

        Returns (property_name, value) tuple.
        """
        # Handle properties with parameters (e.g., DTSTART;TZID=America/New_York:20240101T090000)
        if ":" not in line:
            return None, None

        prop_part, value = line.split(":", 1)

        # Extract property name (before any ;)
        if ";" in prop_part:
            prop_name = prop_part.split(";")[0].upper()
            params = prop_part.split(";")[1:]
        else:
            prop_name = prop_part.upper()
            params = []

        # Parse based on property type
        if prop_name in ("DTSTART", "DTEND"):
            dt = self._parse_datetime(value, params)
            return prop_name.lower(), dt
        elif prop_name == "SUMMARY":
            return "summary", self._unescape(value)
        elif prop_name == "DESCRIPTION":
            return "description", self._unescape(value)
        elif prop_name == "LOCATION":
            return "location", self._unescape(value)
        elif prop_name == "UID":
            return "uid", value
        elif prop_name == "RRULE":
            return "rrule", self._parse_rrule(value)

        return None, None

    def _parse_datetime(self, value: str, params: list[str]) -> datetime | date:
        """Parse an iCal datetime value."""
        # Check for VALUE=DATE (all-day event)
        is_date = any(p.upper().startswith("VALUE=DATE") and "DATE-TIME" not in p.upper() for p in params)

        if is_date or len(value) == 8:
            # Date only: YYYYMMDD
            return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))

        # DateTime: YYYYMMDDTHHMMSS or YYYYMMDDTHHMMSSZ
        if "T" in value:
            date_part = value.split("T")[0]
            time_part = value.split("T")[1]

            year = int(date_part[0:4])
            month = int(date_part[4:6])
            day = int(date_part[6:8])

            hour = int(time_part[0:2])
            minute = int(time_part[2:4])
            second = int(time_part[4:6]) if len(time_part) >= 6 else 0

            # Check for UTC indicator
            if time_part.endswith("Z"):
                return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)

            # Check for TZID parameter
            for param in params:
                if param.upper().startswith("TZID="):
                    # For simplicity, treat as local time converted to UTC
                    # Full implementation would use pytz/zoneinfo
                    dt = datetime(year, month, day, hour, minute, second)
                    return dt.replace(tzinfo=timezone.utc)

            # No timezone info - assume UTC
            return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)

        # Fallback
        return datetime.now(timezone.utc)

    def _parse_rrule(self, value: str) -> RecurrenceRule | None:
        """Parse an RRULE value into a RecurrenceRule."""
        parts = dict(p.split("=") for p in value.split(";") if "=" in p)

        freq = parts.get("FREQ", "").lower()
        if freq not in ("daily", "weekly", "monthly", "yearly"):
            return None

        interval = int(parts.get("INTERVAL", "1"))
        count = int(parts["COUNT"]) if "COUNT" in parts else None

        until = None
        if "UNTIL" in parts:
            until_str = parts["UNTIL"]
            if len(until_str) >= 8:
                until = date(int(until_str[0:4]), int(until_str[4:6]), int(until_str[6:8]))

        by_day = parts.get("BYDAY", "").split(",") if "BYDAY" in parts else None
        by_month_day = int(parts["BYMONTHDAY"]) if "BYMONTHDAY" in parts else None

        return RecurrenceRule(
            frequency=freq,
            interval=interval,
            count=count,
            until=until,
            by_day=by_day if by_day and by_day[0] else None,
            by_month_day=by_month_day,
        )

    def _unescape(self, value: str) -> str:
        """Unescape iCal text values."""
        return (
            value.replace("\\n", "\n")
            .replace("\\N", "\n")
            .replace("\\,", ",")
            .replace("\\;", ";")
            .replace("\\\\", "\\")
        )

    def _make_event(self, data: dict[str, Any], source_url: str) -> CalendarEvent | None:
        """Create a CalendarEvent from parsed iCal data."""
        summary = data.get("summary", "Untitled Event")
        dtstart = data.get("dtstart")
        dtend = data.get("dtend")

        if dtstart is None:
            return None

        # Handle all-day events
        all_day = isinstance(dtstart, date) and not isinstance(dtstart, datetime)

        if all_day:
            # Convert date to datetime for storage
            start = datetime.combine(dtstart, datetime.min.time(), tzinfo=timezone.utc)
            if dtend:
                end = datetime.combine(dtend, datetime.min.time(), tzinfo=timezone.utc)
            else:
                end = start + timedelta(days=1)
        else:
            start = dtstart if isinstance(dtstart, datetime) else datetime.combine(
                dtstart, datetime.min.time(), tzinfo=timezone.utc
            )
            if dtend:
                end = dtend if isinstance(dtend, datetime) else datetime.combine(
                    dtend, datetime.min.time(), tzinfo=timezone.utc
                )
            else:
                # Default to 1 hour duration
                end = start + timedelta(hours=1)

        now = _now()
        return CalendarEvent(
            id=_generate_id(),
            title=summary,
            description=data.get("description", ""),
            start=start,
            end=end,
            all_day=all_day,
            location=data.get("location"),
            color=None,
            recurrence=data.get("rrule"),
            source="ical",
            source_id=data.get("uid"),
            source_url=source_url,
            metadata={},
            created_at=now,
            updated_at=now,
        )
