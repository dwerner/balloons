"""Tests for the Calendar domain plugin."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock

from .domain import CalendarDomain, _calendars, _calendars_loaded
from .models import Calendar, CalendarEvent, RecurrenceRule


class MockSession:
    """Mock session for testing."""
    id = "test-session-123"


@pytest.fixture
def domain():
    """Create a fresh domain instance."""
    return CalendarDomain()


@pytest.fixture
def session():
    """Create a mock session."""
    return MockSession()


@pytest.fixture(autouse=True)
def reset_state():
    """Reset global state before each test."""
    global _calendars, _calendars_loaded
    _calendars.clear()
    import plugins.calendar.domain as domain_module
    domain_module._calendars = {}
    domain_module._calendars_loaded = True  # Skip loading from storage
    yield
    domain_module._calendars = {}
    domain_module._calendars_loaded = False


class TestCalendarModels:
    """Test Calendar and Event models."""

    def test_create_calendar(self):
        """Test calendar creation."""
        cal = Calendar.create("Work", color="#4285f4")
        assert cal.name == "Work"
        assert cal.color == "#4285f4"
        assert cal.provider == "local"
        assert len(cal.id) == 8
        assert cal.events == {}

    def test_create_event(self):
        """Test event creation."""
        now = datetime.now(timezone.utc)
        event = CalendarEvent.create(
            title="Meeting",
            start=now,
            end=now + timedelta(hours=1),
            description="Team sync",
            location="Room A",
        )
        assert event.title == "Meeting"
        assert event.description == "Team sync"
        assert event.location == "Room A"
        assert event.source == "local"
        assert not event.all_day

    def test_event_overlap(self):
        """Test event overlap detection."""
        base = datetime(2024, 3, 20, 10, 0, tzinfo=timezone.utc)

        event1 = CalendarEvent.create(
            title="Event 1",
            start=base,
            end=base + timedelta(hours=2),
        )
        event2 = CalendarEvent.create(
            title="Event 2",
            start=base + timedelta(hours=1),
            end=base + timedelta(hours=3),
        )
        event3 = CalendarEvent.create(
            title="Event 3",
            start=base + timedelta(hours=3),
            end=base + timedelta(hours=4),
        )

        assert event1.overlaps(event2)
        assert event2.overlaps(event1)
        assert not event1.overlaps(event3)
        assert not event3.overlaps(event1)

    def test_calendar_events_in_range(self):
        """Test getting events in a date range."""
        cal = Calendar.create("Test")
        base = datetime(2024, 3, 20, 10, 0, tzinfo=timezone.utc)

        # Add some events
        event1 = CalendarEvent.create("Event 1", base, base + timedelta(hours=1))
        event2 = CalendarEvent.create("Event 2", base + timedelta(days=1), base + timedelta(days=1, hours=1))
        event3 = CalendarEvent.create("Event 3", base + timedelta(days=5), base + timedelta(days=5, hours=1))

        cal.add_event(event1)
        cal.add_event(event2)
        cal.add_event(event3)

        # Get events in first 2 days
        range_start = base - timedelta(hours=1)
        range_end = base + timedelta(days=2)
        events = cal.get_events_in_range(range_start, range_end)

        assert len(events) == 2
        assert events[0].title == "Event 1"
        assert events[1].title == "Event 2"


class TestRecurrenceRule:
    """Test recurrence rules."""

    def test_parse_weekly_rrule(self):
        """Test parsing a weekly recurrence rule."""
        rule = RecurrenceRule(
            frequency="weekly",
            interval=1,
            by_day=["MO", "WE", "FR"],
        )
        assert rule.frequency == "weekly"
        assert rule.interval == 1
        assert rule.by_day == ["MO", "WE", "FR"]

    def test_rrule_to_dict(self):
        """Test serializing a recurrence rule."""
        from datetime import date
        rule = RecurrenceRule(
            frequency="monthly",
            interval=2,
            until=date(2024, 12, 31),
            by_month_day=15,
        )
        d = rule.to_dict()
        assert d["frequency"] == "monthly"
        assert d["interval"] == 2
        assert d["until"] == "2024-12-31"
        assert d["byMonthDay"] == 15


@pytest.mark.asyncio
class TestCalendarDomain:
    """Test CalendarDomain tool methods."""

    async def test_calendar_create(self, domain, session):
        """Test creating a calendar."""
        result = await domain.calendar_create(
            name="Work",
            color="#4285f4",
            session=session,
        )
        assert not result.is_error
        assert "Created calendar 'Work'" in result.result
        assert len(result.events) == 1
        assert result.events[0].type == "calendar_created"

    async def test_calendar_list_empty(self, domain, session):
        """Test listing calendars when empty."""
        result = await domain.calendar_list(session=session)
        assert "No calendars found" in result.result

    async def test_calendar_create_and_list(self, domain, session):
        """Test creating and listing calendars."""
        await domain.calendar_create(name="Work", session=session)
        await domain.calendar_create(name="Personal", session=session)

        result = await domain.calendar_list(session=session)
        assert "Work" in result.result
        assert "Personal" in result.result
        assert "2 events" not in result.result  # Should say "0 events"

    async def test_calendar_create_event(self, domain, session):
        """Test creating an event."""
        # First create a calendar
        await domain.calendar_create(name="Work", session=session)

        # Then create an event
        result = await domain.calendar_create_event(
            calendar_id="Work",
            title="Team Meeting",
            start="2024-03-20T14:00:00",
            end="2024-03-20T15:00:00",
            description="Weekly sync",
            location="Room A",
            session=session,
        )

        assert not result.is_error
        assert "Created event 'Team Meeting'" in result.result
        assert len(result.events) == 1
        assert result.events[0].type == "event_created"

    async def test_create_event_invalid_time(self, domain, session):
        """Test creating event with end before start."""
        await domain.calendar_create(name="Work", session=session)

        result = await domain.calendar_create_event(
            calendar_id="Work",
            title="Bad Event",
            start="2024-03-20T15:00:00",
            end="2024-03-20T14:00:00",  # End before start
            session=session,
        )

        assert result.is_error
        assert "End time must be after start time" in result.result

    async def test_calendar_get_events(self, domain, session):
        """Test getting events in a range."""
        await domain.calendar_create(name="Work", session=session)

        # Create some events
        await domain.calendar_create_event(
            calendar_id="Work",
            title="Meeting 1",
            start="2024-03-20T10:00:00",
            end="2024-03-20T11:00:00",
            session=session,
        )
        await domain.calendar_create_event(
            calendar_id="Work",
            title="Meeting 2",
            start="2024-03-21T14:00:00",
            end="2024-03-21T15:00:00",
            session=session,
        )

        result = await domain.calendar_get_events(
            start="2024-03-20",
            end="2024-03-22",
            session=session,
        )

        assert not result.is_error
        assert "Meeting 1" in result.result
        assert "Meeting 2" in result.result

    async def test_calendar_delete(self, domain, session):
        """Test deleting a calendar."""
        await domain.calendar_create(name="ToDelete", session=session)

        result = await domain.calendar_delete(
            calendar_id="ToDelete",
            session=session,
        )

        assert not result.is_error
        assert "Deleted calendar 'ToDelete'" in result.result

        # Verify it's gone
        list_result = await domain.calendar_list(session=session)
        assert "ToDelete" not in list_result.result


class TestICalProvider:
    """Test iCal sync provider."""

    def test_parse_basic_event(self):
        """Test parsing a basic iCal event."""
        from .sync.ical import ICalProvider

        ical = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:test@example.com
DTSTART:20240320T100000Z
DTEND:20240320T110000Z
SUMMARY:Test Event
END:VEVENT
END:VCALENDAR"""

        provider = ICalProvider()
        events = provider._parse_ical(ical, "test://source")

        assert len(events) == 1
        assert events[0].title == "Test Event"
        assert events[0].source == "ical"
        assert events[0].source_url == "test://source"

    def test_parse_all_day_event(self):
        """Test parsing an all-day event."""
        from .sync.ical import ICalProvider

        ical = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:allday@example.com
DTSTART;VALUE=DATE:20240320
DTEND;VALUE=DATE:20240321
SUMMARY:All Day
END:VEVENT
END:VCALENDAR"""

        provider = ICalProvider()
        events = provider._parse_ical(ical, "test://source")

        assert len(events) == 1
        assert events[0].title == "All Day"
        assert events[0].all_day is True

    def test_parse_recurring_event(self):
        """Test parsing a recurring event."""
        from .sync.ical import ICalProvider

        ical = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:recurring@example.com
DTSTART:20240320T100000Z
DTEND:20240320T110000Z
SUMMARY:Weekly Meeting
RRULE:FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,WE,FR
END:VEVENT
END:VCALENDAR"""

        provider = ICalProvider()
        events = provider._parse_ical(ical, "test://source")

        assert len(events) == 1
        assert events[0].recurrence is not None
        assert events[0].recurrence.frequency == "weekly"
        assert events[0].recurrence.by_day == ["MO", "WE", "FR"]

    def test_unescape_text(self):
        """Test unescaping iCal text."""
        from .sync.ical import ICalProvider

        provider = ICalProvider()

        assert provider._unescape("Hello\\nWorld") == "Hello\nWorld"
        assert provider._unescape("A\\,B\\;C") == "A,B;C"
        assert provider._unescape("Path\\\\to\\\\file") == "Path\\to\\file"
