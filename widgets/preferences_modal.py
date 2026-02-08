"""Preferences modal for configuring backends and tools."""

from pathlib import Path

from textual.screen import ModalScreen
from textual.widgets import Static, Button, Select, Switch, Label
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.message import Message

from config import get_config
from core.preferences import DEFAULT_TOOLS, ToolPreferences


class PreferencesModal(ModalScreen[None]):
    """Modal for configuring preferences, tools, and backends."""

    DEFAULT_CSS = """
    PreferencesModal {
        align: center middle;
    }

    #prefs-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #prefs-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #prefs-content {
        height: auto;
        max-height: 60%;
        padding: 1 0;
    }

    .section-title {
        text-style: bold;
        margin-top: 1;
        margin-bottom: 0;
    }

    .section-content {
        padding-left: 2;
    }

    #backend-select {
        width: 100%;
        margin-bottom: 1;
    }

    .tool-row {
        height: auto;
        margin: 0;
        padding: 0;
    }

    .tool-row Switch {
        margin-right: 1;
    }

    .tool-row Label {
        padding-top: 0;
    }

    #tools-grid {
        height: auto;
        layout: grid;
        grid-size: 2 4;
        grid-columns: 1fr 1fr;
        padding: 0 1;
    }

    #config-path {
        color: $text-muted;
        margin-top: 1;
    }

    #prefs-buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }

    #prefs-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
    ]

    class ToolsChanged(Message):
        """Message sent when tools are toggled."""
        def __init__(self, backend_name: str, enabled_tools: list[str]) -> None:
            self.backend_name = backend_name
            self.enabled_tools = enabled_tools
            super().__init__()

    class BackendChanged(Message):
        """Message sent when backend is changed."""
        def __init__(self, backend_name: str) -> None:
            self.backend_name = backend_name
            super().__init__()

    def __init__(
        self,
        current_backend: str,
        tool_preferences: dict[str, ToolPreferences],
        **kwargs
    ):
        super().__init__(**kwargs)
        self._current_backend = current_backend
        # Copy preferences to allow editing
        self._tool_preferences = {
            k: ToolPreferences(enabled_tools=set(v.enabled_tools))
            for k, v in tool_preferences.items()
        }

    def compose(self):
        config = get_config()
        backends = list(config.backends.keys())

        with Vertical(id="prefs-dialog"):
            yield Static("Preferences", id="prefs-title")

            with ScrollableContainer(id="prefs-content"):
                # Backend selection
                yield Static("Backend", classes="section-title")
                with Vertical(classes="section-content"):
                    yield Select(
                        [(b, b) for b in backends],
                        value=self._current_backend,
                        id="backend-select",
                    )

                # Tools section
                yield Static("Tools", classes="section-title")
                with Vertical(id="tools-grid", classes="section-content"):
                    # Get current prefs for selected backend
                    prefs = self._get_prefs(self._current_backend)
                    for tool in DEFAULT_TOOLS:
                        with Horizontal(classes="tool-row"):
                            yield Switch(
                                value=tool in prefs.enabled_tools,
                                id=f"tool-{tool.lower()}",
                            )
                            yield Label(tool)

                # Config file path
                config_path = config._config_path or Path.home() / ".balloons" / "config.yaml"
                yield Static(f"Config: {config_path}", id="config-path")

            with Horizontal(id="prefs-buttons"):
                yield Button("Close", id="close-btn", variant="primary")

    def _get_prefs(self, backend_name: str) -> ToolPreferences:
        """Get tool preferences for a backend, creating if needed."""
        if backend_name not in self._tool_preferences:
            self._tool_preferences[backend_name] = ToolPreferences()
        return self._tool_preferences[backend_name]

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle backend selection change."""
        if event.select.id == "backend-select":
            self._current_backend = str(event.value)
            # Update tool switches to reflect this backend's preferences
            prefs = self._get_prefs(self._current_backend)
            for tool in DEFAULT_TOOLS:
                switch = self.query_one(f"#tool-{tool.lower()}", Switch)
                switch.value = tool in prefs.enabled_tools
            # Notify app of backend change
            self.post_message(self.BackendChanged(self._current_backend))

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Handle tool toggle."""
        switch_id = event.switch.id
        if switch_id and switch_id.startswith("tool-"):
            tool_name = None
            for t in DEFAULT_TOOLS:
                if t.lower() == switch_id[5:]:
                    tool_name = t
                    break

            if tool_name:
                prefs = self._get_prefs(self._current_backend)
                if event.value:
                    prefs.enabled_tools.add(tool_name)
                else:
                    prefs.enabled_tools.discard(tool_name)
                # Notify app of tools change
                self.post_message(self.ToolsChanged(
                    self._current_backend,
                    list(prefs.enabled_tools)
                ))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def get_enabled_tools(self, backend_name: str) -> list[str]:
        """Get enabled tools for a backend."""
        return list(self._get_prefs(backend_name).enabled_tools)

    def get_all_preferences(self) -> dict[str, ToolPreferences]:
        """Get all tool preferences."""
        return self._tool_preferences
