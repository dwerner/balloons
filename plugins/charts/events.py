"""Typed event payloads for the Charts domain.

Defines structured event data for type-safe event handling.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChartCreatedPayload:
    """Payload for chart_created event.

    Emitted when a new chart is created via chart_create.
    """
    chart_id: str
    name: str
    chart_type: str  # "line", "bar", "area", "scatter"
    config: dict[str, Any]


@dataclass
class ChartDataUpdatedPayload:
    """Payload for chart_data_updated event.

    Emitted when data is added or removed from a chart.
    """
    chart_id: str
    operation: str  # "add", "remove", "clear"
    row_count: int
    # Full data is included for UI sync
    data: list[dict[str, Any]]


@dataclass
class ChartStyleUpdatedPayload:
    """Payload for chart_style_updated event.

    Emitted when chart styles are changed.
    """
    chart_id: str
    config: dict[str, Any]


@dataclass
class ChartDeletedPayload:
    """Payload for chart_deleted event.

    Emitted when a chart is deleted.
    """
    chart_id: str


@dataclass
class ChartStateSyncPayload:
    """Payload for chart_state_sync event.

    Emitted when the UI requests current state (e.g., on reconnection)
    or when chart_list/chart_show is called.
    """
    charts: list[dict[str, Any]]


# Map event types to their payload classes for validation/parsing
EVENT_PAYLOADS = {
    "chart_created": ChartCreatedPayload,
    "chart_data_updated": ChartDataUpdatedPayload,
    "chart_style_updated": ChartStyleUpdatedPayload,
    "chart_deleted": ChartDeletedPayload,
    "chart_state_sync": ChartStateSyncPayload,
}
