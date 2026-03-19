"""Calendar sync providers.

Supports iCal and (future) Google Calendar sync.
"""

from .base import CalendarProvider
from .ical import ICalProvider

__all__ = ["CalendarProvider", "ICalProvider"]
