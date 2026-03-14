"""Tests for the Charts domain plugin."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from .domain import ChartsDomain, _global_charts
from .models import Chart, ChartStyle, ChartDataRow
import plugins.charts.domain as charts_domain


class MockSession:
    """Mock session for testing."""
    def __init__(self, session_id: str = "test-session"):
        self.id = session_id


@pytest.fixture
def domain():
    """Create a fresh domain instance."""
    return ChartsDomain()


@pytest.fixture
def session():
    """Create a mock session."""
    return MockSession()


@pytest.fixture(autouse=True)
def clear_global_charts(tmp_path, monkeypatch):
    """Clear the global charts cache and use temp storage for tests."""
    from pathlib import Path

    _global_charts.clear()
    charts_domain._charts_loaded = False

    # Override storage to use temp directory
    class TempStorage:
        def __init__(self, base_dir):
            self._dir = base_dir
            self._dir.mkdir(parents=True, exist_ok=True)

        async def save(self, key: str, data: dict) -> None:
            import json
            (self._dir / f"{key}.json").write_text(json.dumps(data))

        async def load(self, key: str) -> dict | None:
            import json
            path = self._dir / f"{key}.json"
            if path.exists():
                return json.loads(path.read_text())
            return None

        async def delete(self, key: str) -> None:
            path = self._dir / f"{key}.json"
            if path.exists():
                path.unlink()

        async def list_keys(self) -> list[str]:
            return [f.stem for f in self._dir.glob("*.json")]

    temp_storage = TempStorage(tmp_path / "charts")
    monkeypatch.setattr(charts_domain, "_storage", temp_storage)

    yield

    _global_charts.clear()
    charts_domain._charts_loaded = False


class TestChartsDomain:
    """Tests for ChartsDomain."""

    def test_domain_properties(self, domain):
        """Test domain identity properties."""
        assert domain.id == "charts"
        assert domain.name == "Charts"
        assert domain.version == "0.1.0"

    def test_get_tools(self, domain):
        """Test that all expected tools are defined."""
        tools = domain.get_tools()
        tool_names = {t.name for t in tools}

        expected = {
            "chart_create",
            "chart_add_data",
            "chart_remove_data",
            "chart_set_style",
            "chart_list",
            "chart_show",
            "chart_delete",
        }
        assert tool_names == expected

    def test_get_ui_config(self, domain):
        """Test UI configuration."""
        config = domain.get_ui_config()
        assert config is not None
        assert "components" in config
        assert "tabs" in config
        assert len(config["tabs"]) == 1
        assert config["tabs"][0]["id"] == "charts"


class TestChartCreate:
    """Tests for chart_create tool."""

    @pytest.mark.asyncio
    async def test_create_basic_chart(self, domain, session):
        """Test creating a basic chart."""
        result = await domain.handle_tool(
            "chart_create",
            {"name": "Test Chart"},
            session
        )

        assert not result.is_error
        assert "Test Chart" in result.result
        assert len(result.events) == 1
        assert result.events[0].type == "chart_created"

    @pytest.mark.asyncio
    async def test_create_chart_with_options(self, domain, session):
        """Test creating a chart with all options."""
        result = await domain.handle_tool(
            "chart_create",
            {
                "name": "Sales",
                "chart_type": "bar",
                "title": "Monthly Sales",
                "x_label": "Month",
                "y_label": "Revenue ($)",
            },
            session
        )

        assert not result.is_error
        event = result.events[0]
        config = event.payload.config
        assert config["chartType"] == "bar"
        assert config["style"]["title"] == "Monthly Sales"

    @pytest.mark.asyncio
    async def test_create_requires_name(self, domain, session):
        """Test that name is required."""
        result = await domain.handle_tool(
            "chart_create",
            {},
            session
        )
        assert result.is_error
        assert "name" in result.result.lower()


class TestChartAddData:
    """Tests for chart_add_data tool."""

    @pytest.mark.asyncio
    async def test_add_single_row(self, domain, session):
        """Test adding a single data row."""
        # Create chart first
        create_result = await domain.handle_tool(
            "chart_create",
            {"name": "Test"},
            session
        )
        chart_id = create_result.events[0].payload.chart_id

        # Add data
        result = await domain.handle_tool(
            "chart_add_data",
            {
                "chart_id": chart_id,
                "rows": [{"x": 1, "y": 10}],
            },
            session
        )

        assert not result.is_error
        assert "Added 1 row" in result.result
        assert result.events[0].type == "chart_data_updated"
        assert result.events[0].payload.row_count == 1

    @pytest.mark.asyncio
    async def test_add_multiple_rows(self, domain, session):
        """Test adding multiple data rows."""
        create_result = await domain.handle_tool(
            "chart_create",
            {"name": "Test"},
            session
        )
        chart_id = create_result.events[0].payload.chart_id

        result = await domain.handle_tool(
            "chart_add_data",
            {
                "chart_id": chart_id,
                "rows": [
                    {"x": 1, "y": 10},
                    {"x": 2, "y": 20},
                    {"x": 3, "y": 30},
                ],
            },
            session
        )

        assert not result.is_error
        assert "Added 3 row" in result.result
        assert result.events[0].payload.row_count == 3

    @pytest.mark.asyncio
    async def test_add_with_series(self, domain, session):
        """Test adding data with series names."""
        create_result = await domain.handle_tool(
            "chart_create",
            {"name": "Test"},
            session
        )
        chart_id = create_result.events[0].payload.chart_id

        result = await domain.handle_tool(
            "chart_add_data",
            {
                "chart_id": chart_id,
                "rows": [
                    {"x": "Jan", "y": 100, "series": "Sales"},
                    {"x": "Jan", "y": 80, "series": "Costs"},
                ],
            },
            session
        )

        assert not result.is_error
        data = result.events[0].payload.data
        assert len(data) == 2
        assert data[0]["series"] == "Sales"
        assert data[1]["series"] == "Costs"


class TestChartRemoveData:
    """Tests for chart_remove_data tool."""

    @pytest.mark.asyncio
    async def test_clear_all_data(self, domain, session):
        """Test clearing all data."""
        # Create and populate chart
        create_result = await domain.handle_tool(
            "chart_create", {"name": "Test"}, session
        )
        chart_id = create_result.events[0].payload.chart_id

        await domain.handle_tool(
            "chart_add_data",
            {"chart_id": chart_id, "rows": [{"x": 1, "y": 10}, {"x": 2, "y": 20}]},
            session
        )

        # Clear data
        result = await domain.handle_tool(
            "chart_remove_data",
            {"chart_id": chart_id, "criteria": {"clear": True}},
            session
        )

        assert not result.is_error
        assert "Removed 2 row" in result.result
        assert result.events[0].payload.row_count == 0

    @pytest.mark.asyncio
    async def test_remove_by_criteria(self, domain, session):
        """Test removing data by criteria."""
        create_result = await domain.handle_tool(
            "chart_create", {"name": "Test"}, session
        )
        chart_id = create_result.events[0].payload.chart_id

        await domain.handle_tool(
            "chart_add_data",
            {"chart_id": chart_id, "rows": [
                {"x": 1, "y": 10},
                {"x": 2, "y": 20},
                {"x": 3, "y": 30},
            ]},
            session
        )

        # Remove rows where x < 3
        result = await domain.handle_tool(
            "chart_remove_data",
            {"chart_id": chart_id, "criteria": {"x_lt": 3}},
            session
        )

        assert not result.is_error
        assert "Removed 2 row" in result.result
        assert result.events[0].payload.row_count == 1


class TestChartSetStyle:
    """Tests for chart_set_style tool."""

    @pytest.mark.asyncio
    async def test_set_title(self, domain, session):
        """Test setting chart title."""
        create_result = await domain.handle_tool(
            "chart_create", {"name": "Test"}, session
        )
        chart_id = create_result.events[0].payload.chart_id

        result = await domain.handle_tool(
            "chart_set_style",
            {"chart_id": chart_id, "style": {"title": "My Chart"}},
            session
        )

        assert not result.is_error
        assert result.events[0].type == "chart_style_updated"
        assert result.events[0].payload.config["style"]["title"] == "My Chart"

    @pytest.mark.asyncio
    async def test_set_multiple_styles(self, domain, session):
        """Test setting multiple style properties."""
        create_result = await domain.handle_tool(
            "chart_create", {"name": "Test"}, session
        )
        chart_id = create_result.events[0].payload.chart_id

        result = await domain.handle_tool(
            "chart_set_style",
            {
                "chart_id": chart_id,
                "style": {
                    "title": "My Chart",
                    "x_label": "Time",
                    "colors": ["#ff0000", "#00ff00"],
                    "show_grid": False,
                }
            },
            session
        )

        assert not result.is_error
        style = result.events[0].payload.config["style"]
        assert style["title"] == "My Chart"
        assert style["xLabel"] == "Time"
        assert style["colors"] == ["#ff0000", "#00ff00"]
        assert style["showGrid"] == False


class TestChartListAndShow:
    """Tests for chart_list and chart_show tools."""

    @pytest.mark.asyncio
    async def test_list_empty(self, domain, session):
        """Test listing when no charts exist."""
        result = await domain.handle_tool("chart_list", {}, session)
        assert not result.is_error
        assert "No charts" in result.result

    @pytest.mark.asyncio
    async def test_list_charts(self, domain, session):
        """Test listing multiple charts."""
        await domain.handle_tool("chart_create", {"name": "Chart A"}, session)
        await domain.handle_tool("chart_create", {"name": "Chart B"}, session)

        result = await domain.handle_tool("chart_list", {}, session)

        assert not result.is_error
        assert "Chart A" in result.result
        assert "Chart B" in result.result
        assert result.events[0].type == "chart_state_sync"

    @pytest.mark.asyncio
    async def test_show_chart(self, domain, session):
        """Test showing a specific chart."""
        create_result = await domain.handle_tool(
            "chart_create", {"name": "Test Chart"}, session
        )
        chart_id = create_result.events[0].payload.chart_id

        await domain.handle_tool(
            "chart_add_data",
            {"chart_id": chart_id, "rows": [{"x": 1, "y": 10}]},
            session
        )

        result = await domain.handle_tool(
            "chart_show", {"chart_id": chart_id}, session
        )

        assert not result.is_error
        assert "Test Chart" in result.result
        assert "1" in result.result  # row count


class TestChartDelete:
    """Tests for chart_delete tool."""

    @pytest.mark.asyncio
    async def test_delete_chart(self, domain, session):
        """Test deleting a chart."""
        create_result = await domain.handle_tool(
            "chart_create", {"name": "Test"}, session
        )
        chart_id = create_result.events[0].payload.chart_id

        result = await domain.handle_tool(
            "chart_delete", {"chart_id": chart_id}, session
        )

        assert not result.is_error
        assert "Deleted" in result.result
        assert result.events[0].type == "chart_deleted"

        # Verify chart is gone
        list_result = await domain.handle_tool("chart_list", {}, session)
        assert "No charts" in list_result.result

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, domain, session):
        """Test deleting a chart that doesn't exist."""
        result = await domain.handle_tool(
            "chart_delete", {"chart_id": "nonexistent"}, session
        )
        assert result.is_error
        assert "not found" in result.result.lower()


class TestChartModels:
    """Tests for chart data models."""

    def test_chart_create(self):
        """Test Chart.create factory method."""
        chart = Chart.create(name="Test", chart_type="line")
        assert chart.name == "Test"
        assert chart.chart_type == "line"
        assert len(chart.id) == 8
        assert chart.data == []

    def test_chart_add_row(self):
        """Test adding rows to a chart."""
        chart = Chart.create(name="Test")
        chart.add_row(x=1, y=10)
        chart.add_row(x=2, y=20, series="other")

        assert len(chart.data) == 2
        assert chart.data[0]["x"] == 1
        assert chart.data[0]["y"] == 10
        assert chart.data[1]["series"] == "other"

    def test_chart_remove_rows(self):
        """Test removing rows from a chart."""
        chart = Chart.create(name="Test")
        chart.add_row(x=1, y=10)
        chart.add_row(x=2, y=20)
        chart.add_row(x=3, y=30)

        removed = chart.remove_rows({"x_lt": 3})
        assert removed == 2
        assert len(chart.data) == 1
        assert chart.data[0]["x"] == 3

    def test_chart_serialization(self):
        """Test chart to_dict/from_dict."""
        chart = Chart.create(name="Test", chart_type="bar")
        chart.add_row(x="A", y=100)
        chart.style.title = "My Title"

        data = chart.to_dict()
        restored = Chart.from_dict(data)

        assert restored.id == chart.id
        assert restored.name == chart.name
        assert restored.chart_type == chart.chart_type
        assert restored.data == chart.data
        assert restored.style.title == chart.style.title

    def test_chart_style_defaults(self):
        """Test ChartStyle default values."""
        style = ChartStyle()
        assert style.show_grid == True
        assert style.show_legend == True
        assert style.line_width == 2
        assert len(style.colors) == 4
