"""Todo picker modal for :todo-done command."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static, OptionList
from textual.widgets.option_list import Option

from storage_schema import TodoData


class TodoPickerModal(ModalScreen[str | None]):
    """Modal for selecting a todo to mark as done."""

    DEFAULT_CSS = """
    TodoPickerModal {
        align: center middle;
    }

    TodoPickerModal > Vertical {
        width: 70;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    TodoPickerModal Static {
        width: 100%;
        text-align: center;
        margin-bottom: 1;
    }

    TodoPickerModal OptionList {
        height: auto;
        max-height: 20;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "select", "Select"),
    ]

    def __init__(self, todos: list[TodoData]) -> None:
        super().__init__()
        self._todos = todos

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Which todo did you complete?")
            option_list = OptionList()
            for todo in self._todos:
                label = f"{todo.id[:8]}: {todo.title}"
                option_list.add_option(Option(label, id=todo.id))
            yield option_list

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is not None:
            option = option_list.get_option_at_index(option_list.highlighted)
            self.dismiss(option.id)
