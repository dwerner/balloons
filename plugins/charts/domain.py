"""Charts domain plugin.

Provides persistent charting capabilities to Balloons sessions.
"""

from typing import Any, TYPE_CHECKING

from codegen.ws_expose import ws_expose
from ..base import DomainEvent, DecoratedStatefulDomain, ToolResult
from ..decorators import llm_callable, Param
from ..storage import JsonFileStorage
from .. import PluginLogger
from .models import Chart, ChartStyle
from .events import (
    ChartCreatedPayload,
    ChartDataUpdatedPayload,
    ChartStyleUpdatedPayload,
    ChartDeletedPayload,
    ChartStateSyncPayload,
)

if TYPE_CHECKING:
    from session import Session

# Plugin logger
log = PluginLogger("charts")


# Global in-memory cache for charts (shared across all sessions)
# Charts are workspace-scoped, not session-scoped - any session can work with any chart
_global_charts: dict[str, Chart] = {}
_charts_loaded: bool = False

# Persistent storage - each chart is stored as its own file: {chart_id}.json
_storage: JsonFileStorage | None = None


def _get_storage() -> JsonFileStorage:
    """Get the persistent storage instance."""
    global _storage
    if _storage is None:
        _storage = JsonFileStorage("charts")
    return _storage


def _get_charts(session_id: str) -> dict[str, Chart]:
    """Get the global charts dict.

    Note: session_id is kept for API compatibility but charts are global.
    """
    return _global_charts


async def _load_all_charts() -> None:
    """Load all charts from storage (each chart is a separate file)."""
    global _charts_loaded
    if _charts_loaded:
        return

    storage = _get_storage()
    chart_ids = await storage.list_keys()

    for chart_id in chart_ids:
        if chart_id == "global":  # Skip legacy global.json if it exists
            continue
        chart_data = await storage.load(chart_id)
        if chart_data:
            chart = Chart.from_dict(chart_data)
            _global_charts[chart.id] = chart

    _charts_loaded = True


async def _save_chart(chart: Chart) -> None:
    """Save a single chart to its own file."""
    storage = _get_storage()
    await storage.save(chart.id, chart.to_dict())


async def _delete_chart_file(chart_id: str) -> None:
    """Delete a chart's storage file."""
    storage = _get_storage()
    await storage.delete(chart_id)


async def _get_charts_async(session_id: str) -> dict[str, Chart]:
    """Get the global charts dict, auto-loading from storage if needed.

    Note: session_id is kept for API compatibility but charts are global.
    """
    await _load_all_charts()
    return _global_charts


class ChartsDomain(DecoratedStatefulDomain):
    """Charts domain providing persistent, interactive charting.

    Tools:
        - chart_create: Create a new named chart
        - chart_add_data: Add data rows to a chart
        - chart_remove_data: Remove data rows by criteria
        - chart_set_style: Configure chart appearance
        - chart_list: List all charts in session
        - chart_show: Show a specific chart's data
        - chart_delete: Delete a chart

    Events emitted:
        - chart_created: New chart created
        - chart_data_updated: Data added/removed
        - chart_style_updated: Style changed
        - chart_deleted: Chart removed
        - chart_state_sync: Full state sync (reconnection)
    """

    @property
    def id(self) -> str:
        return "charts"

    @property
    def name(self) -> str:
        return "Charts"

    @property
    def version(self) -> str:
        return "0.1.0"

    def get_prompt(self) -> str:
        """Load prompt from prompt.md file."""
        import os
        prompt_path = os.path.join(os.path.dirname(__file__), "prompt.md")
        try:
            with open(prompt_path, "r") as f:
                return f.read()
        except FileNotFoundError:
            return """## Charts Domain

You can create and manage persistent charts using the chart_* tools.
Charts are named entities that persist across turns. Use chart_create to create,
chart_add_data to populate, and chart_set_style to configure appearance."""

    def get_ui_config(self) -> dict | None:
        """Return UI configuration for the charts domain."""
        return {
            "components": [
                {
                    "name": "ChartView",
                    "path": "plugins/charts/ui/ChartView.tsx",
                    "description": "Single chart renderer",
                },
                {
                    "name": "ChartPanel",
                    "path": "plugins/charts/ui/ChartPanel.tsx",
                    "description": "Multi-chart panel with tabs",
                },
            ],
            "tabs": [
                {
                    "id": "charts",
                    "label": "Charts",
                    "icon": "📊",
                    "component": "ChartPanel",
                },
            ],
        }

    def _find_chart(self, session_id: str, chart_id: str) -> Chart | None:
        """Find a chart by ID (supports prefix matching)."""
        charts = _get_charts(session_id)
        # Exact match first
        if chart_id in charts:
            return charts[chart_id]
        # Prefix match
        for cid, chart in charts.items():
            if cid.startswith(chart_id):
                return chart
        # Name match (case-insensitive)
        for chart in charts.values():
            if chart.name.lower() == chart_id.lower():
                return chart
        return None

    async def _auto_save_chart(self, chart: Chart) -> None:
        """Auto-save a single chart to persistent storage."""
        await _save_chart(chart)

    # --- LLM-callable tools ---

    @llm_callable(
        description="""Create a new chart. Returns the chart ID for future operations.

Chart types:
- line: Time series, trends
- bar: Comparisons, categories
- area: Cumulative values, stacked data
- scatter: Correlations, distributions""",
        params={
            "name": Param(str, "Display name for the chart"),
            "chart_type": Param(str, "Type of chart (default: line)", enum=["line", "bar", "area", "scatter"], required=False),
            "title": Param(str, "Chart title (shown above chart)", required=False),
            "x_label": Param(str, "X-axis label", required=False),
            "y_label": Param(str, "Y-axis label", required=False),
        }
    )
    async def chart_create(
        self,
        name: str,
        chart_type: str = "line",
        title: str | None = None,
        x_label: str | None = None,
        y_label: str | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """Create a new chart."""
        # Ensure state is loaded from storage on first access
        await _get_charts_async(session.id)

        name = name.strip()
        if not name:
            return ToolResult("Chart name is required", is_error=True)

        if chart_type not in ["line", "bar", "area", "scatter"]:
            return ToolResult(f"Invalid chart type: {chart_type}. Use: line, bar, area, scatter", is_error=True)

        # Build initial style from params
        style = ChartStyle(
            title=title,
            x_label=x_label,
            y_label=y_label,
        )

        chart = Chart.create(name=name, chart_type=chart_type, style=style)
        charts = _get_charts(session.id)
        charts[chart.id] = chart

        event = DomainEvent(
            type="chart_created",
            source_domain=self.id,
            payload=ChartCreatedPayload(
                chart_id=chart.id,
                name=chart.name,
                chart_type=chart.chart_type,
                config=chart.to_dict(),
            ),
            target_session=session.id,
        )

        # Auto-save the new chart
        await self._auto_save_chart(chart)
        log.info(f"Created chart: {name}", session_id=session.id, details={"chart_id": chart.id, "type": chart_type})

        return ToolResult(
            f"Created {chart_type} chart '{name}' with ID: {chart.id}\n\nUse chart_add_data to add data points.",
            events=[event],
        )

    @llm_callable(
        description="""Add data rows to a chart. Each row has an x value, y value, and optional series name.

For time series: x can be ISO timestamp, unix timestamp, or relative ("now", "-1h", "-1d").
For categories: x is the category name.
For numeric: x is a number.

Multiple rows can be added at once.""",
        params={
            "chart_id": Param(str, "Chart ID (from chart_create or chart_list)"),
            "rows": Param(
                list,
                "Data rows to add",
                items=Param(
                    dict,
                    properties={
                        "x": Param(str, "X-axis value (timestamp, category, or number)"),
                        "y": Param(float, "Y-axis value"),
                        "series": Param(str, "Series name for multi-series charts (default: 'default')", required=False),
                        "label": Param(str, "Optional label for this data point", required=False),
                    }
                )
            ),
        }
    )
    async def chart_add_data(
        self,
        chart_id: str,
        rows: list[dict[str, Any]],
        session: "Session" = None,
    ) -> ToolResult:
        """Add data rows to a chart."""
        await _get_charts_async(session.id)

        chart_id = chart_id.strip()
        if not chart_id:
            return ToolResult("chart_id is required", is_error=True)

        chart = self._find_chart(session.id, chart_id)
        if not chart:
            return ToolResult(f"Chart not found: {chart_id}", is_error=True)

        if not rows:
            return ToolResult("rows is required", is_error=True)

        added = 0
        for row in rows:
            x = row.get("x")
            y = row.get("y")
            if x is None or y is None:
                continue
            series = row.get("series", "default")
            label = row.get("label")
            chart.add_row(x=x, y=float(y), series=series, label=label)
            added += 1

        event = DomainEvent(
            type="chart_data_updated",
            source_domain=self.id,
            payload=ChartDataUpdatedPayload(
                chart_id=chart.id,
                operation="add",
                row_count=len(chart.data),
                data=chart.data,
            ),
            target_session=session.id,
        )

        # Auto-save the modified chart
        await self._auto_save_chart(chart)

        return ToolResult(
            f"Added {added} row(s) to chart '{chart.name}'. Total rows: {len(chart.data)}",
            events=[event],
        )

    @llm_callable(
        description="""Remove data rows from a chart based on criteria.

Criteria can filter by:
- x_lt: Remove rows where x < value
- x_gt: Remove rows where x > value
- x_eq: Remove rows where x == value
- y_lt: Remove rows where y < value
- y_gt: Remove rows where y > value
- series: Remove rows from a specific series
- clear: If true, remove ALL data""",
        params={
            "chart_id": Param(str, "Chart ID"),
            "criteria": Param(
                dict,
                "Filter criteria for rows to remove",
                properties={
                    "x_lt": Param(str, "Remove where x < this value", required=False),
                    "x_gt": Param(str, "Remove where x > this value", required=False),
                    "x_eq": Param(str, "Remove where x == this value", required=False),
                    "y_lt": Param(float, "Remove where y < this value", required=False),
                    "y_gt": Param(float, "Remove where y > this value", required=False),
                    "series": Param(str, "Remove from this series only", required=False),
                    "clear": Param(bool, "Clear ALL data if true", required=False),
                },
                required=False,
            ),
        }
    )
    async def chart_remove_data(
        self,
        chart_id: str,
        criteria: dict[str, Any] | None = None,
        session: "Session" = None,
    ) -> ToolResult:
        """Remove data rows from a chart."""
        await _get_charts_async(session.id)

        chart_id = chart_id.strip()
        if not chart_id:
            return ToolResult("chart_id is required", is_error=True)

        chart = self._find_chart(session.id, chart_id)
        if not chart:
            return ToolResult(f"Chart not found: {chart_id}", is_error=True)

        criteria = criteria or {}

        if criteria.get("clear"):
            old_count = len(chart.data)
            chart.clear_data()
            removed = old_count
        else:
            removed = chart.remove_rows(criteria)

        event = DomainEvent(
            type="chart_data_updated",
            source_domain=self.id,
            payload=ChartDataUpdatedPayload(
                chart_id=chart.id,
                operation="remove" if not criteria.get("clear") else "clear",
                row_count=len(chart.data),
                data=chart.data,
            ),
            target_session=session.id,
        )

        # Auto-save the modified chart
        await self._auto_save_chart(chart)

        return ToolResult(
            f"Removed {removed} row(s) from chart '{chart.name}'. Remaining: {len(chart.data)}",
            events=[event],
        )

    @llm_callable(
        description="""Update chart styling and configuration.

Available style options:
- title: Chart title
- x_label, y_label: Axis labels
- colors: Array of hex colors for series
- show_grid, show_legend, show_dots: Boolean toggles
- line_width: Line thickness (pixels)
- y_min, y_max: Y-axis range (auto if not set)""",
        params={
            "chart_id": Param(str, "Chart ID"),
            "style": Param(
                dict,
                "Style configuration",
                properties={
                    "title": Param(str, "Chart title", required=False),
                    "x_label": Param(str, "X-axis label", required=False),
                    "y_label": Param(str, "Y-axis label", required=False),
                    "colors": Param(list, "Hex colors for series", items=Param(str), required=False),
                    "show_grid": Param(bool, "Show grid lines", required=False),
                    "show_legend": Param(bool, "Show legend", required=False),
                    "show_dots": Param(bool, "Show data points", required=False),
                    "line_width": Param(int, "Line thickness in pixels", required=False),
                    "bar_gap": Param(int, "Gap between bars in pixels", required=False),
                    "area_opacity": Param(float, "Area fill opacity (0-1)", required=False),
                    "animate": Param(bool, "Enable animations", required=False),
                    "y_min": Param(float, "Y-axis minimum", required=False),
                    "y_max": Param(float, "Y-axis maximum", required=False),
                },
            ),
        }
    )
    async def chart_set_style(
        self,
        chart_id: str,
        style: dict[str, Any],
        session: "Session" = None,
    ) -> ToolResult:
        """Update chart styling."""
        await _get_charts_async(session.id)

        chart_id = chart_id.strip()
        if not chart_id:
            return ToolResult("chart_id is required", is_error=True)

        chart = self._find_chart(session.id, chart_id)
        if not chart:
            return ToolResult(f"Chart not found: {chart_id}", is_error=True)

        # Update style fields that are provided
        if "title" in style:
            chart.style.title = style["title"]
        if "x_label" in style:
            chart.style.x_label = style["x_label"]
        if "y_label" in style:
            chart.style.y_label = style["y_label"]
        if "colors" in style:
            chart.style.colors = style["colors"]
        if "show_grid" in style:
            chart.style.show_grid = style["show_grid"]
        if "show_legend" in style:
            chart.style.show_legend = style["show_legend"]
        if "show_dots" in style:
            chart.style.show_dots = style["show_dots"]
        if "line_width" in style:
            chart.style.line_width = style["line_width"]
        if "bar_gap" in style:
            chart.style.bar_gap = style["bar_gap"]
        if "area_opacity" in style:
            chart.style.area_opacity = style["area_opacity"]
        if "animate" in style:
            chart.style.animate = style["animate"]
        if "y_min" in style:
            chart.style.y_min = style["y_min"]
        if "y_max" in style:
            chart.style.y_max = style["y_max"]

        event = DomainEvent(
            type="chart_style_updated",
            source_domain=self.id,
            payload=ChartStyleUpdatedPayload(
                chart_id=chart.id,
                config=chart.to_dict(),
            ),
            target_session=session.id,
        )

        # Auto-save the modified chart
        await self._auto_save_chart(chart)

        return ToolResult(
            f"Updated style for chart '{chart.name}'",
            events=[event],
        )

    @llm_callable(description="List all charts in the current session.")
    async def chart_list(self, session: "Session" = None) -> ToolResult:
        """List all charts."""
        await _get_charts_async(session.id)
        charts = _get_charts(session.id)

        if not charts:
            return ToolResult("No charts in this session. Use chart_create to create one.")

        lines = ["Charts in this session:", ""]
        for chart in charts.values():
            lines.append(f"  [{chart.id}] {chart.name} ({chart.chart_type}) - {len(chart.data)} rows")

        # Emit sync event for UI
        event = DomainEvent(
            type="chart_state_sync",
            source_domain=self.id,
            payload=ChartStateSyncPayload(
                charts=[c.to_dict() for c in charts.values()],
            ),
            target_session=session.id,
        )

        return ToolResult("\n".join(lines), events=[event])

    @llm_callable(
        description="Show details and data for a specific chart.",
        params={
            "chart_id": Param(str, "Chart ID to show"),
        }
    )
    async def chart_show(self, chart_id: str, session: "Session" = None) -> ToolResult:
        """Show a specific chart."""
        await _get_charts_async(session.id)

        chart_id = chart_id.strip()
        if not chart_id:
            return ToolResult("chart_id is required", is_error=True)

        chart = self._find_chart(session.id, chart_id)
        if not chart:
            return ToolResult(f"Chart not found: {chart_id}", is_error=True)

        # Build summary
        lines = [
            f"Chart: {chart.name}",
            f"ID: {chart.id}",
            f"Type: {chart.chart_type}",
            f"Data rows: {len(chart.data)}",
            "",
        ]

        if chart.style.title:
            lines.append(f"Title: {chart.style.title}")
        if chart.style.x_label:
            lines.append(f"X-axis: {chart.style.x_label}")
        if chart.style.y_label:
            lines.append(f"Y-axis: {chart.style.y_label}")

        # Show sample data
        if chart.data:
            lines.append("")
            lines.append("Data preview (first 5 rows):")
            for row in chart.data[:5]:
                lines.append(f"  x={row.get('x')}, y={row.get('y')}, series={row.get('series', 'default')}")
            if len(chart.data) > 5:
                lines.append(f"  ... and {len(chart.data) - 5} more rows")

        # Emit sync event with ALL charts (UI replaces state on sync)
        charts = _get_charts(session.id)
        event = DomainEvent(
            type="chart_state_sync",
            source_domain=self.id,
            payload=ChartStateSyncPayload(
                charts=[c.to_dict() for c in charts.values()],
            ),
            target_session=session.id,
        )

        return ToolResult("\n".join(lines), events=[event])

    @ws_expose
    @llm_callable(
        description="Delete a chart permanently.",
        params={
            "chart_id": Param(str, "Chart ID to delete"),
        }
    )
    async def chart_delete(self, chart_id: str, session: "Session" = None) -> ToolResult:
        """Delete a chart."""
        await _get_charts_async(session.id)

        chart_id = chart_id.strip()
        if not chart_id:
            return ToolResult("chart_id is required", is_error=True)

        chart = self._find_chart(session.id, chart_id)
        if not chart:
            return ToolResult(f"Chart not found: {chart_id}", is_error=True)

        charts = _get_charts(session.id)
        chart_id_to_delete = chart.id
        del charts[chart.id]

        event = DomainEvent(
            type="chart_deleted",
            source_domain=self.id,
            payload=ChartDeletedPayload(chart_id=chart_id_to_delete),
            target_session=session.id,
        )

        # Delete the chart file from storage
        await _delete_chart_file(chart_id_to_delete)

        return ToolResult(f"Deleted chart '{chart.name}'", events=[event])

    # --- StatefulDomain methods ---

    async def get_state(self, session: "Session") -> dict[str, Any] | None:
        """Return current charts state.

        Auto-loads from storage if not in memory.
        """
        # Ensure charts are loaded from storage first
        charts = await _get_charts_async(session.id)
        if not charts:
            return None

        return {
            "charts": [c.to_dict() for c in charts.values()],
        }

    async def save_state(self, session: "Session") -> dict[str, Any]:
        """Save all charts to persistent storage (each as its own file).

        Charts are global (workspace-scoped), not session-scoped.
        """
        charts = _get_charts(session.id)
        if not charts:
            return {}

        # Save each chart to its own file
        for chart in charts.values():
            await _save_chart(chart)

        return {
            "charts": [c.to_dict() for c in charts.values()],
        }

    async def load_state(self, session: "Session", state: dict[str, Any]) -> None:
        """Load charts from persistent storage (each chart is its own file).

        Charts are global (workspace-scoped), not session-scoped.
        """
        await _load_all_charts()

    async def clear_state(self, session: "Session") -> None:
        """Clear all charts from memory and persistent storage.

        WARNING: This clears ALL global charts.
        """
        global _charts_loaded
        storage = _get_storage()

        # Delete all chart files
        for chart_id in list(_global_charts.keys()):
            await storage.delete(chart_id)

        _global_charts.clear()
        _charts_loaded = False


def create_domain() -> ChartsDomain:
    """Factory function for domain loading."""
    return ChartsDomain()
