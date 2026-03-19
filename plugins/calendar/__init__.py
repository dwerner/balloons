"""Calendar domain plugin.

Provides calendar functionality with local calendars and iCal sync support.
"""


def create_domain():
    from .domain import CalendarDomain
    return CalendarDomain()
