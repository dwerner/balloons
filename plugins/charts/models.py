"""Data models for the Charts domain.

Charts are persistent entities with:
- Unique ID (UUID)
- User-defined name
- Type (line, bar, area, scatter)
- Data series (list of rows)
- Style configuration
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


def _now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


@dataclass
class ChartDataRow:
    """A single data row in a chart."""
    x: Any  # X-axis value (timestamp, category, number)
    y: float  # Y-axis value
    label: str | None = None  # Optional label for this point
    series: str = "default"  # Series name for multi-series charts
    metadata: dict[str, Any] = field(default_factory=dict)  # Extra data


@dataclass
class ChartStyle:
    """Style configuration for a chart."""
    title: str | None = None
    x_label: str | None = None
    y_label: str | None = None
    colors: list[str] = field(default_factory=lambda: ["#8884d8", "#82ca9d", "#ffc658", "#ff7c43"])
    show_grid: bool = True
    show_legend: bool = True
    show_dots: bool = True
    line_width: int = 2
    bar_gap: int = 4
    area_opacity: float = 0.3
    animate: bool = True
    y_min: float | None = None
    y_max: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "xLabel": self.x_label,
            "yLabel": self.y_label,
            "colors": self.colors,
            "showGrid": self.show_grid,
            "showLegend": self.show_legend,
            "showDots": self.show_dots,
            "lineWidth": self.line_width,
            "barGap": self.bar_gap,
            "areaOpacity": self.area_opacity,
            "animate": self.animate,
            "yMin": self.y_min,
            "yMax": self.y_max,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChartStyle":
        return cls(
            title=data.get("title"),
            x_label=data.get("xLabel") or data.get("x_label"),
            y_label=data.get("yLabel") or data.get("y_label"),
            colors=data.get("colors", ["#8884d8", "#82ca9d", "#ffc658", "#ff7c43"]),
            show_grid=data.get("showGrid", data.get("show_grid", True)),
            show_legend=data.get("showLegend", data.get("show_legend", True)),
            show_dots=data.get("showDots", data.get("show_dots", True)),
            line_width=data.get("lineWidth", data.get("line_width", 2)),
            bar_gap=data.get("barGap", data.get("bar_gap", 4)),
            area_opacity=data.get("areaOpacity", data.get("area_opacity", 0.3)),
            animate=data.get("animate", True),
            y_min=data.get("yMin") or data.get("y_min"),
            y_max=data.get("yMax") or data.get("y_max"),
        )


@dataclass
class Chart:
    """A persistent chart entity."""
    id: str
    name: str
    chart_type: str  # "line", "bar", "area", "scatter"
    data: list[dict[str, Any]]  # Raw data rows
    style: ChartStyle
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(cls, name: str, chart_type: str = "line", style: ChartStyle | None = None) -> "Chart":
        """Create a new chart with a unique ID."""
        now = _now()
        return cls(
            id=str(uuid.uuid4())[:8],  # Short ID for convenience
            name=name,
            chart_type=chart_type,
            data=[],
            style=style or ChartStyle(),
            created_at=now,
            updated_at=now,
        )

    def add_row(self, x: Any, y: float, series: str = "default", label: str | None = None, **metadata) -> None:
        """Add a data row to the chart."""
        row = {
            "x": x,
            "y": y,
            "series": series,
        }
        if label:
            row["label"] = label
        if metadata:
            row["metadata"] = metadata
        self.data.append(row)
        self.updated_at = _now()

    def remove_rows(self, predicate: dict[str, Any]) -> int:
        """Remove rows matching the predicate. Returns count removed."""
        initial_count = len(self.data)

        def matches(row: dict) -> bool:
            for key, value in predicate.items():
                if key == "x_lt" and row.get("x") >= value:
                    return False
                if key == "x_gt" and row.get("x") <= value:
                    return False
                if key == "x_eq" and row.get("x") != value:
                    return False
                if key == "series" and row.get("series") != value:
                    return False
                if key == "y_lt" and row.get("y") >= value:
                    return False
                if key == "y_gt" and row.get("y") <= value:
                    return False
            return True

        self.data = [row for row in self.data if not matches(row)]
        removed = initial_count - len(self.data)
        if removed > 0:
            self.updated_at = _now()
        return removed

    def clear_data(self) -> None:
        """Clear all data from the chart."""
        self.data = []
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        """Serialize chart to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "chartType": self.chart_type,
            "data": self.data,
            "style": self.style.to_dict(),
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chart":
        """Deserialize chart from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            chart_type=data.get("chartType") or data.get("chart_type", "line"),
            data=data.get("data", []),
            style=ChartStyle.from_dict(data.get("style", {})),
            created_at=datetime.fromisoformat(data.get("createdAt") or data.get("created_at", _now().isoformat())),
            updated_at=datetime.fromisoformat(data.get("updatedAt") or data.get("updated_at", _now().isoformat())),
        )
