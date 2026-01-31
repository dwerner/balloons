from textual.widgets import Static
from textual.containers import Horizontal
from textual.message import Message


class ToolBar(Horizontal):
    """Bar with toggles for enabling Claude tools."""

    DEFAULT_CSS = """
    ToolBar {
        height: 1;
        background: $surface;
    }

    ToolBar > Static {
        width: auto;
        padding: 0 1;
    }

    ToolBar > Static:hover {
        background: $primary-background;
    }
    """

    TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "NotebookEdit"]

    class ToolsChanged(Message):
        """Fired when tools change."""
        def __init__(self, enabled_tools: list[str]) -> None:
            self.enabled_tools = enabled_tools
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._enabled: set[str] = set(self.TOOLS)

    def compose(self):
        yield Static("[dim]Tools:[/]", id="tools-label")
        for tool in self.TOOLS:
            yield Static(f"[green]☑[/] {tool}", id=f"tool-{tool.lower()}")

    def on_click(self, event) -> None:
        """Handle click on tool toggles."""
        target_id = event.widget.id
        if target_id and target_id.startswith("tool-"):
            tool_name = None
            for t in self.TOOLS:
                if t.lower() == target_id[5:]:
                    tool_name = t
                    break

            if tool_name:
                widget = self.query_one(f"#{target_id}", Static)
                if tool_name in self._enabled:
                    self._enabled.discard(tool_name)
                    widget.update(f"[dim]☐ {tool_name}[/]")
                else:
                    self._enabled.add(tool_name)
                    widget.update(f"[green]☑[/] {tool_name}")

    def get_enabled_tools(self) -> list[str]:
        """Get list of enabled tool names."""
        return list(self._enabled)
