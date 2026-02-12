"""Modals for creating new plans and todos from the goal tree.

These modals are shown when clicking [+plan] on a goal or [+todo] on a plan.
"""

from dataclasses import dataclass
from typing import Optional

from textual.screen import ModalScreen
from textual.widgets import Static, Button, Input, TextArea, Label, Checkbox
from textual.containers import Vertical, Horizontal


@dataclass
class CreatePlanResult:
    """Result from CreatePlanModal."""
    goal_id: str
    title: str
    description: str
    status: str  # "draft" or "active"
    begin_session: bool = False  # If True, also create and start a bound session


@dataclass
class CreateTodoResult:
    """Result from CreateTodoModal."""
    plan_id: str
    title: str
    description: str
    is_spike: bool
    timebox_minutes: Optional[int]
    begin_session: bool = False  # If True, also create and start a bound session


class CreatePlanModal(ModalScreen[Optional[CreatePlanResult]]):
    """Modal for creating a new plan under a goal."""

    DEFAULT_CSS = """
    CreatePlanModal {
        align: center middle;
    }

    #create-plan-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #dialog-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
        color: cyan;
        height: auto;
    }

    #goal-info {
        height: auto;
        margin-bottom: 1;
        padding: 0 1;
        background: $surface-darken-1;
        border: solid $primary-darken-2;
    }

    #goal-label {
        color: $text-muted;
        text-style: italic;
        height: 1;
    }

    #goal-title {
        text-style: bold;
        color: yellow;
        height: auto;
    }

    .field-label {
        margin-top: 1;
        margin-bottom: 0;
        height: 1;
    }

    #title-input {
        margin-bottom: 1;
        width: 100%;
    }

    #description-input {
        height: 6;
        margin-bottom: 1;
    }

    #status-row {
        height: auto;
        margin-bottom: 1;
    }

    #buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }

    #buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        goal_id: str,
        goal_title: str,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.goal_id = goal_id
        self.goal_title = goal_title

    def compose(self):
        with Vertical(id="create-plan-dialog"):
            yield Static("New Plan", id="dialog-title")

            # Show goal info
            with Vertical(id="goal-info"):
                yield Static("[dim]Goal[/]", id="goal-label")
                yield Static(f"[bold yellow]{self.goal_title}[/]", id="goal-title")

            # Title input
            yield Label("Title:", classes="field-label")
            yield Input(placeholder="Plan title...", id="title-input")

            # Description input
            yield Label("Description (optional):", classes="field-label")
            yield TextArea(id="description-input")

            # Status checkbox
            with Horizontal(id="status-row"):
                yield Checkbox("Start as active (otherwise draft)", id="active-checkbox", value=True)

            # Buttons
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel-btn", variant="default")
                yield Button("Create Plan", id="create-btn", variant="primary")
                yield Button("Create & Begin", id="create-begin-btn", variant="success")

    def on_mount(self) -> None:
        """Focus the title input when modal opens."""
        self.query_one("#title-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            self._submit(begin_session=False)
        elif event.button.id == "create-begin-btn":
            self._submit(begin_session=True)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Allow Enter in title field to submit."""
        if event.input.id == "title-input":
            self._submit(begin_session=False)

    def _submit(self, begin_session: bool = False) -> None:
        """Submit the form."""
        title_input = self.query_one("#title-input", Input)
        description_input = self.query_one("#description-input", TextArea)
        active_checkbox = self.query_one("#active-checkbox", Checkbox)

        title = title_input.value.strip()
        if not title:
            title_input.focus()
            return

        self.dismiss(CreatePlanResult(
            goal_id=self.goal_id,
            title=title,
            description=description_input.text.strip(),
            status="active" if active_checkbox.value else "draft",
            begin_session=begin_session,
        ))

    def action_cancel(self) -> None:
        self.dismiss(None)


class CreateTodoModal(ModalScreen[Optional[CreateTodoResult]]):
    """Modal for creating a new todo under a plan."""

    DEFAULT_CSS = """
    CreateTodoModal {
        align: center middle;
    }

    #create-todo-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #dialog-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
        color: green;
        height: auto;
    }

    #plan-info {
        height: auto;
        margin-bottom: 1;
        padding: 0 1;
        background: $surface-darken-1;
        border: solid $primary-darken-2;
    }

    #plan-label {
        color: $text-muted;
        text-style: italic;
        height: 1;
    }

    #plan-title {
        text-style: bold;
        color: cyan;
        height: auto;
    }

    .field-label {
        margin-top: 1;
        margin-bottom: 0;
        height: 1;
    }

    #title-input {
        margin-bottom: 1;
        width: 100%;
    }

    #description-input {
        height: 6;
        margin-bottom: 1;
    }

    #spike-row {
        height: auto;
        margin-bottom: 1;
    }

    #timebox-row {
        height: auto;
        margin-bottom: 1;
    }

    #timebox-input {
        width: 20;
    }

    #buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }

    #buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        plan_id: str,
        plan_title: str,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.plan_id = plan_id
        self.plan_title = plan_title

    def compose(self):
        with Vertical(id="create-todo-dialog"):
            yield Static("New Todo", id="dialog-title")

            # Show plan info
            with Vertical(id="plan-info"):
                yield Static("[dim]Plan[/]", id="plan-label")
                yield Static(f"[bold cyan]{self.plan_title}[/]", id="plan-title")

            # Title input
            yield Label("Title:", classes="field-label")
            yield Input(placeholder="Todo title...", id="title-input")

            # Description input
            yield Label("Description (optional):", classes="field-label")
            yield TextArea(id="description-input")

            # Spike checkbox
            with Horizontal(id="spike-row"):
                yield Checkbox("This is a spike (timeboxed exploration)", id="spike-checkbox")

            # Timebox input (shown when spike is checked)
            with Horizontal(id="timebox-row"):
                yield Label("Timebox (minutes): ", classes="field-label")
                yield Input(placeholder="30", id="timebox-input", disabled=True)

            # Buttons
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel-btn", variant="default")
                yield Button("Create Todo", id="create-btn", variant="primary")
                yield Button("Create & Begin", id="create-begin-btn", variant="success")

    def on_mount(self) -> None:
        """Focus the title input when modal opens."""
        self.query_one("#title-input", Input).focus()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Enable/disable timebox input based on spike checkbox."""
        if event.checkbox.id == "spike-checkbox":
            timebox_input = self.query_one("#timebox-input", Input)
            timebox_input.disabled = not event.value
            if event.value:
                timebox_input.value = "30"  # Default timebox

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            self._submit(begin_session=False)
        elif event.button.id == "create-begin-btn":
            self._submit(begin_session=True)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Allow Enter in title field to submit."""
        if event.input.id == "title-input":
            self._submit(begin_session=False)

    def _submit(self, begin_session: bool = False) -> None:
        """Submit the form."""
        title_input = self.query_one("#title-input", Input)
        description_input = self.query_one("#description-input", TextArea)
        spike_checkbox = self.query_one("#spike-checkbox", Checkbox)
        timebox_input = self.query_one("#timebox-input", Input)

        title = title_input.value.strip()
        if not title:
            title_input.focus()
            return

        timebox_minutes = None
        if spike_checkbox.value and timebox_input.value.strip():
            try:
                timebox_minutes = int(timebox_input.value.strip())
            except ValueError:
                pass  # Ignore invalid timebox

        self.dismiss(CreateTodoResult(
            plan_id=self.plan_id,
            title=title,
            description=description_input.text.strip(),
            is_spike=spike_checkbox.value,
            timebox_minutes=timebox_minutes,
            begin_session=begin_session,
        ))

    def action_cancel(self) -> None:
        self.dismiss(None)
