"""Modal for confirming which todos to start streaming sessions for."""

from dataclasses import dataclass, field
from typing import Optional

from textual.screen import ModalScreen
from textual.widgets import Static, Button, Checkbox
from textual.containers import Vertical, Horizontal, ScrollableContainer

from core.goal_tools import BeginStreamingTodoProposal
from storage_schema import TodoData


@dataclass
class BeginStreamingResult:
    """Result from the begin streaming modal."""
    accepted: bool
    # List of (todo_id, initial_prompt) for todos to start
    todos_to_start: list[tuple[str, str]] = field(default_factory=list)


class BeginStreamingModal(ModalScreen[Optional[BeginStreamingResult]]):
    """Modal for confirming which todos to start background sessions for.

    Displays checkboxes for each todo the LLM wants to start.
    User can select/deselect individual todos before confirming.
    """

    DEFAULT_CSS = """
    BeginStreamingModal {
        align: center middle;
    }

    #streaming-dialog {
        width: 90;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #streaming-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    #streaming-description {
        color: $text-muted;
        margin-bottom: 1;
    }

    #todo-list {
        height: auto;
        max-height: 50;
        padding: 0;
        margin-bottom: 1;
    }

    .todo-item {
        height: auto;
        padding: 1;
        margin-bottom: 1;
        background: $surface-darken-1;
        border: solid $primary-darken-2;
    }

    .todo-item:focus-within {
        border: solid $primary;
    }

    .todo-title {
        text-style: bold;
        color: $text;
    }

    .todo-description {
        color: $text-muted;
        padding-left: 2;
    }

    .todo-status {
        color: $warning;
        padding-left: 2;
    }

    #streaming-buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }

    #streaming-buttons Button {
        margin: 0 1;
    }

    #start-btn {
        background: $success;
    }

    #cancel-btn {
        background: $error-darken-1;
    }

    #select-all-btn {
        background: $primary-darken-1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "start", "Start Selected"),
    ]

    def __init__(
        self,
        proposal: BeginStreamingTodoProposal,
        **kwargs
    ):
        """Initialize the modal.

        Args:
            proposal: The BeginStreamingTodoProposal with resolved todos
        """
        super().__init__(**kwargs)
        self._proposal = proposal
        # Track which todos are selected (all selected by default)
        self._selected: dict[str, bool] = {
            todo.id: True for todo in proposal.resolved_todos
        }

    def compose(self):
        with Vertical(id="streaming-dialog"):
            yield Static("Start Todo Sessions", id="streaming-title")
            yield Static(
                f"The assistant wants to start {len(self._proposal.resolved_todos)} "
                "background session(s). Select which todos to start:",
                id="streaming-description"
            )

            with ScrollableContainer(id="todo-list"):
                for todo in self._proposal.resolved_todos:
                    with Vertical(classes="todo-item"):
                        yield Checkbox(
                            todo.title,
                            value=True,
                            id=f"check-{todo.id}",
                            classes="todo-title"
                        )
                        if todo.description:
                            # Truncate long descriptions
                            desc = todo.description
                            if len(desc) > 100:
                                desc = desc[:100] + "..."
                            yield Static(desc, classes="todo-description")
                        # Show status
                        yield Static(f"Status: {todo.status}", classes="todo-status")

            with Horizontal(id="streaming-buttons"):
                yield Button("Start Selected", id="start-btn", variant="success")
                yield Button("Select All", id="select-all-btn", variant="primary")
                yield Button("Cancel", id="cancel-btn", variant="error")

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Track checkbox changes."""
        # Extract todo ID from checkbox ID (format: "check-{todo_id}")
        checkbox_id = event.checkbox.id
        if checkbox_id and checkbox_id.startswith("check-"):
            todo_id = checkbox_id[6:]  # Remove "check-" prefix
            self._selected[todo_id] = event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-btn":
            self.action_start()
        elif event.button.id == "cancel-btn":
            self.action_cancel()
        elif event.button.id == "select-all-btn":
            self._toggle_all()

    def _toggle_all(self) -> None:
        """Toggle all checkboxes."""
        # Check if all are currently selected
        all_selected = all(self._selected.values())
        new_value = not all_selected

        # Update all checkboxes
        for todo in self._proposal.resolved_todos:
            checkbox = self.query_one(f"#check-{todo.id}", Checkbox)
            checkbox.value = new_value
            self._selected[todo.id] = new_value

        # Update button text
        btn = self.query_one("#select-all-btn", Button)
        btn.label = "Deselect All" if new_value else "Select All"

    def action_start(self) -> None:
        """Start sessions for selected todos."""
        todos_to_start = []

        for todo in self._proposal.resolved_todos:
            if self._selected.get(todo.id, False):
                # Get custom prompt if provided, otherwise generate default
                initial_prompt = self._proposal.initial_prompts.get(
                    todo.id,
                    self._generate_default_prompt(todo)
                )
                todos_to_start.append((todo.id, initial_prompt))

        if not todos_to_start:
            # Nothing selected - treat as cancel
            self.action_cancel()
            return

        result = BeginStreamingResult(
            accepted=True,
            todos_to_start=todos_to_start,
        )
        self.dismiss(result)

    def action_cancel(self) -> None:
        """Cancel without starting any sessions."""
        result = BeginStreamingResult(
            accepted=False,
        )
        self.dismiss(result)

    def _generate_default_prompt(self, todo: TodoData) -> str:
        """Generate a default initial prompt for a todo.

        Args:
            todo: The todo to generate a prompt for

        Returns:
            Default prompt string
        """
        prompt_parts = [
            f"I'm starting work on the todo: **{todo.title}**"
        ]

        if todo.description:
            prompt_parts.append(f"\nDescription: {todo.description}")

        prompt_parts.append(
            "\n\nPlease review the todo requirements and begin implementation. "
            "Use the goal management tools to understand the context (parent plan, "
            "related todos, dependencies) if needed."
        )

        return "\n".join(prompt_parts)
