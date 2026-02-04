"""Prompt file picker modal."""

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static, OptionList
from textual.widgets.option_list import Option


class PromptPickerModal(ModalScreen[Path | None]):
    """Modal for selecting a prompt file to edit."""

    DEFAULT_CSS = """
    PromptPickerModal {
        align: center middle;
    }

    PromptPickerModal > Vertical {
        width: 60;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    PromptPickerModal Static {
        width: 100%;
        text-align: center;
        margin-bottom: 1;
    }

    PromptPickerModal OptionList {
        height: auto;
        max-height: 20;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "select", "Select"),
    ]

    def __init__(self, prompt_files: list[Path]) -> None:
        super().__init__()
        self._prompt_files = prompt_files

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Select a prompt to edit")
            option_list = OptionList()
            for f in self._prompt_files:
                # Show parent dir name to distinguish app vs user prompts
                parent = f.parent.name
                label = f"{f.stem} ({parent})"
                option_list.add_option(Option(label, id=str(f)))
            yield option_list

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        prompt_path = Path(event.option.id)
        self.dismiss(prompt_path)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is not None:
            option = option_list.get_option_at_index(option_list.highlighted)
            self.dismiss(Path(option.id))
