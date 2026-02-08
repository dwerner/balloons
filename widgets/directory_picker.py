"""Directory browser widget using DirectoryTree."""

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Button, Input, DirectoryTree
from textual.widget import Widget
from textual.message import Message
from textual.binding import Binding


class DirectoryBrowser(Widget):
    """A directory browser widget with tree view and path input.

    Posts DirectorySelected message when a directory is chosen.
    """

    DEFAULT_CSS = """
    DirectoryBrowser {
        height: 1fr;
        width: 1fr;
        layout: vertical;
    }

    DirectoryBrowser > Horizontal {
        height: 3;
        width: 100%;
    }

    DirectoryBrowser > Horizontal > Input {
        width: 1fr;
    }

    DirectoryBrowser > Horizontal > Button {
        width: auto;
        min-width: 4;
    }

    DirectoryBrowser > DirectoryTree {
        height: 1fr;
        width: 100%;
    }

    DirectoryBrowser > Button {
        width: 100%;
        height: 3;
    }
    """

    BINDINGS = [
        Binding("enter", "select", "Select", show=False),
    ]

    class DirectorySelected(Message):
        """Message sent when a directory is selected."""
        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    def __init__(
        self,
        start_path: Path | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._start_path = start_path or Path.home()
        self._selected_path: Path = self._start_path
        self._streaming_mode = False

    def compose(self) -> ComposeResult:
        # Path input row
        with Horizontal():
            yield Input(
                value=str(self._start_path),
                placeholder="Enter path...",
                id="path-input",
            )
            yield Button("→", id="go-btn", variant="default")

        # The directory tree
        yield DirectoryTree(str(self._start_path), id="dir-tree")

        # Select button
        yield Button("Select", id="select-btn", variant="primary")

    def on_mount(self) -> None:
        """Focus the directory tree when mounted."""
        try:
            self.query_one(DirectoryTree).focus()
        except Exception:
            pass

    def set_path(self, path: Path) -> None:
        """Set the current path and update the tree."""
        self._start_path = path
        self._selected_path = path
        self._navigate_to_path(path)

    def _navigate_to_path(self, path: Path) -> None:
        """Navigate the tree to the given path."""
        try:
            if path.is_dir():
                # Update input
                path_input = self.query_one("#path-input", Input)
                path_input.value = str(path)

                # Update the tree's path
                tree = self.query_one("#dir-tree", DirectoryTree)
                tree.path = path

                self._selected_path = path
                tree.focus()
        except Exception:
            pass

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        """Handle directory selection (double-click or enter on a directory).

        Just updates the selected path - user must click Select button to confirm.
        """
        self._selected_path = Path(event.path)
        # Update the path input to show the selected directory
        try:
            path_input = self.query_one("#path-input", Input)
            path_input.value = str(self._selected_path)
        except Exception:
            pass

    def on_directory_tree_node_highlighted(
        self, event: DirectoryTree.NodeHighlighted
    ) -> None:
        """Update selected path when navigating the tree."""
        if event.node.data and hasattr(event.node.data, "path"):
            path = Path(event.node.data.path)
            if path.is_dir():
                self._selected_path = path

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "select-btn":
            self._do_select()
            event.stop()
        elif event.button.id == "go-btn":
            self._navigate_to_input()
            event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle enter in the path input."""
        if event.input.id == "path-input":
            self._navigate_to_input()

    def _navigate_to_input(self) -> None:
        """Navigate the tree to the path in the input."""
        path_input = self.query_one("#path-input", Input)
        try:
            path = Path(path_input.value).expanduser().resolve()
            if path.is_dir():
                self._navigate_to_path(path)
            else:
                # Try parent directory
                if path.parent.is_dir():
                    self._navigate_to_path(path.parent)
        except Exception:
            pass

    def action_select(self) -> None:
        """Select the current directory."""
        self._do_select()

    def _do_select(self) -> None:
        """Perform the selection."""
        if self._streaming_mode:
            return  # Can't change directory during streaming
        if self._selected_path and self._selected_path.is_dir():
            self.post_message(self.DirectorySelected(self._selected_path))

    def set_streaming_mode(self, streaming: bool) -> None:
        """Enable/disable streaming mode.

        When streaming, the Select button is disabled to prevent
        changing the working directory mid-stream.
        """
        self._streaming_mode = streaming
        try:
            select_btn = self.query_one("#select-btn", Button)
            select_btn.disabled = streaming
        except Exception:
            pass
