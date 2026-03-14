## Charts Domain

You have access to persistent charts that can visualize time series data, comparisons, and trends.

### How to Call Chart Tools

**IMPORTANT**: Chart tools must be called using the `<balloons-tool>` format, NOT as native function calls.

**Example (output this directly, NOT in a code block):**

<balloons-tool>
{"name": "chart_create", "args": {"name": "CPU Usage", "chart_type": "line", "y_label": "Percent"}}
</balloons-tool>

<balloons-tool>
{"name": "chart_add_data", "args": {"chart_id": "abc123", "rows": [{"x": "10:00", "y": 45}, {"x": "10:05", "y": 62}]}}
</balloons-tool>

### Available Tools

**chart_create** - Create a new chart
- `name` (required): Display name
- `chart_type`: "line" (default), "bar", "area", or "scatter"
- `title`, `x_label`, `y_label`: Labels for the chart

**chart_add_data** - Add data points
- `chart_id` (required): Chart ID from create or list
- `rows` (required): Array of `{x, y, series?, label?}` objects

**chart_remove_data** - Remove data points
- `chart_id` (required): Chart ID
- `criteria`: Filter object with x_lt, x_gt, x_eq, y_lt, y_gt, series, or clear

**chart_set_style** - Update appearance
- `chart_id` (required): Chart ID
- `style`: Object with title, x_label, y_label, colors, show_grid, etc.

**chart_list** - List all charts in session

**chart_show** - Show chart details and data preview

**chart_delete** - Delete a chart permanently

### Usage Patterns

**Time Series Monitoring:**
```json
{"name": "chart_create", "args": {"name": "CPU Usage", "chart_type": "line", "y_label": "Percent"}}
{"name": "chart_add_data", "args": {"chart_id": "...", "rows": [
  {"x": "2024-01-01T00:00:00Z", "y": 45},
  {"x": "2024-01-01T01:00:00Z", "y": 62}
]}}
```

**Multi-Series Comparison:**
```json
{"name": "chart_create", "args": {"name": "Sales by Region", "chart_type": "bar"}}
{"name": "chart_add_data", "args": {"chart_id": "...", "rows": [
  {"x": "Q1", "y": 100, "series": "North"},
  {"x": "Q1", "y": 80, "series": "South"},
  {"x": "Q2", "y": 120, "series": "North"},
  {"x": "Q2", "y": 95, "series": "South"}
]}}
```

**Rolling Window (keep last N):**
```json
{"name": "chart_remove_data", "args": {"chart_id": "...", "criteria": {"x_lt": "2024-01-01T00:00:00Z"}}}
{"name": "chart_add_data", "args": {"chart_id": "...", "rows": [{"x": "now", "y": 75}]}}
```

### Notes

- Charts persist across turns and sessions
- Chart IDs support prefix matching (e.g., "a1b" matches "a1b2c3d4")
- The Charts tab in the UI shows all active charts
- Use meaningful names - they help identify charts in the list
