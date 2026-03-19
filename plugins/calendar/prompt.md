# Calendar Domain

Manage calendars and events with local storage and iCal feed support.

## Available Tools

### Calendar Management

**calendar_list** - List all calendars with their sync status and event counts.

**calendar_create** - Create a new local calendar.
- `name`: Calendar name (e.g., "Work", "Personal")
- `color`: Optional hex color (e.g., "#4285f4")

**calendar_delete** - Delete a calendar and all its events.
- `calendar_id`: Calendar ID or name

**calendar_connect_ical** - Connect an iCal feed by URL (read-only sync).
- `name`: Name for the calendar
- `url`: iCal feed URL (webcal:// or https://)
- `color`: Optional hex color

**calendar_sync** - Re-sync a calendar with its external provider.
- `calendar_id`: Calendar ID or name

### Event Management

**calendar_create_event** - Create a new event on a local calendar.
- `calendar_id`: Calendar ID or name
- `title`: Event title
- `start`: Start time (ISO format: "2024-03-15T09:00:00")
- `end`: End time (ISO format)
- `description`: Optional description
- `location`: Optional location
- `all_day`: Optional boolean for all-day events
- `color`: Optional override color

**calendar_update_event** - Update an existing event (local events only).
- `event_id`: Event ID
- Only provided fields are updated

**calendar_delete_event** - Delete an event (local events only).
- `event_id`: Event ID

**calendar_get_events** - Get events within a date range.
- `start`: Start date/time (ISO format)
- `end`: End date/time (ISO format)
- `calendar_id`: Optional filter to specific calendar

## Date/Time Formats

Use ISO 8601 format for all dates and times:
- Date only: `2024-03-15`
- DateTime: `2024-03-15T09:00:00`
- DateTime with timezone: `2024-03-15T09:00:00Z` (UTC)

## iCal Support

Supported iCal feed formats:
- webcal:// URLs (converted to https://)
- .ics file URLs
- Google Calendar public URLs
- Apple iCloud shared calendar URLs

Note: iCal calendars are read-only. Events from iCal feeds cannot be modified locally.

## Examples

```
# Create a local calendar
calendar_create name="Work" color="#4285f4"

# Import an iCal feed
calendar_connect_ical name="Holidays" url="webcal://example.com/holidays.ics"

# Create an event
calendar_create_event calendar_id="Work" title="Team Meeting" start="2024-03-15T14:00:00" end="2024-03-15T15:00:00" location="Conference Room A"

# Get this week's events
calendar_get_events start="2024-03-11" end="2024-03-17"
```
