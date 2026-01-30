from textual.widgets import Static, Tree
from textual.containers import Vertical
from textual.message import Message
from rich.json import JSON
from rich.text import Text
from rich.panel import Panel
import json
from datetime import datetime


class RequestPane(Vertical):
    """Right panel showing request history and JSON inspection."""

    DEFAULT_CSS = """
    RequestPane {
        width: 60;
        height: 100%;
        border-left: solid $primary;
    }

    RequestPane > #request-list {
        height: 1fr;
        background: $background;
    }

    RequestPane > #json-viewer {
        height: 1fr;
        border-top: solid $primary;
        padding: 1;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._requests: list[dict] = []

    def compose(self):
        tree = Tree("[bold]Requests[/]", id="request-list")
        tree.root.expand()
        yield tree
        yield Static("Select a request or turn to inspect", id="json-viewer")

    def add_request(self, request_type: str, data: dict) -> None:
        """Add a request to the history."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        request = {
            "type": request_type,
            "timestamp": timestamp,
            "data": data,
        }
        self._requests.append(request)

        tree = self.query_one("#request-list", Tree)

        # Create label based on type
        if request_type == "claude_request":
            msg_count = len(data.get("messages", []))
            prompt_preview = data.get("prompt", "")[:30]
            label = f"[cyan]{timestamp}[/] Claude ({msg_count} msgs) {prompt_preview}..."
        elif request_type == "shell_command":
            cmd = data.get("cmd", "")[:30]
            label = f"[yellow]{timestamp}[/] Shell: {cmd}"
        else:
            label = f"[dim]{timestamp}[/] {request_type}"

        node = tree.root.add(label, data={"request_idx": len(self._requests) - 1})

    def on_tree_node_selected(self, event) -> None:
        """Show JSON for selected request."""
        node_data = event.node.data
        if not node_data:
            return

        request_idx = node_data.get("request_idx")
        if request_idx is not None and request_idx < len(self._requests):
            request = self._requests[request_idx]
            self.show_json(request)

    def show_json(self, data: dict) -> None:
        """Display JSON data in the viewer."""
        viewer = self.query_one("#json-viewer", Static)
        try:
            formatted = JSON(json.dumps(data, indent=2, default=str))
            viewer.update(formatted)
        except Exception as e:
            viewer.update(Text(f"Error: {e}"))

    def show_raw(self, content: str) -> None:
        """Display raw text in the viewer."""
        viewer = self.query_one("#json-viewer", Static)
        viewer.update(Text(content))
