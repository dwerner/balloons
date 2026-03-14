# Charts Domain Plugin

Persistent, interactive charts for Balloons sessions. Create and manage visualizations that persist across turns and sessions.

## Features

- **Multiple chart types**: Line, bar, area, scatter
- **Time series support**: Add/remove data points dynamically
- **Multi-series**: Compare multiple data series on one chart
- **Persistent**: Charts survive across turns and sessions
- **Real-time updates**: UI updates as data changes
- **Style control**: Colors, labels, grid, legend, axis ranges

## Installation

The charts plugin is included with Balloons. Load it with:

```
:load-domain charts
```

Or have the LLM load it when needed.

## Usage

### Creating a Chart

```
chart_create(name="CPU Usage", chart_type="line", y_label="Percent")
```

### Adding Data

```
chart_add_data(chart_id="a1b2c3", rows=[
  {x: "2024-01-01T00:00", y: 45},
  {x: "2024-01-01T01:00", y: 62},
  {x: "2024-01-01T02:00", y: 38},
])
```

### Multi-Series Data

```
chart_add_data(chart_id="a1b2c3", rows=[
  {x: "Jan", y: 100, series: "Sales"},
  {x: "Jan", y: 80, series: "Costs"},
  {x: "Feb", y: 120, series: "Sales"},
  {x: "Feb", y: 85, series: "Costs"},
])
```

### Styling

```
chart_set_style(chart_id="a1b2c3", style={
  title: "Monthly Metrics",
  colors: ["#8884d8", "#ff7c43"],
  show_legend: true,
  show_grid: true,
})
```

### Removing Data

```
# Remove all data before a timestamp
chart_remove_data(chart_id="a1b2c3", criteria={x_lt: "2024-01-01"})

# Clear all data
chart_remove_data(chart_id="a1b2c3", criteria={clear: true})
```

## Chart Types

| Type | Best For | Example Use Case |
|------|----------|------------------|
| line | Trends over time | CPU usage, stock prices |
| bar | Category comparison | Sales by region, votes |
| area | Cumulative values | Stacked metrics, totals |
| scatter | Correlations | Feature relationships |

## UI

The Charts tab shows all charts in the current session:
- Tab bar for switching between charts
- Interactive chart with hover tooltips
- Chart info (ID, type, row count)

## Storage

Charts are persisted to `~/.balloons/plugins/charts/{session_id}.json`.

## Events

The plugin emits events for UI synchronization:

| Event | When |
|-------|------|
| `chart_created` | New chart created |
| `chart_data_updated` | Data added/removed |
| `chart_style_updated` | Style changed |
| `chart_deleted` | Chart removed |
| `chart_state_sync` | Full state requested |

## Building the UI

```bash
cd plugins
bun run build-plugin-ui.ts charts
```

The built bundle is output to `plugins/dist/charts/`.
