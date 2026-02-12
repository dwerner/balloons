"""Entity picker modal for binding sessions to goals, plans, or todos.

When clicking [bind] on a session node in the goal tree, this modal lets
the user select which entity to bind the session to, with optional role selection.
"""

from dataclasses import dataclass
from typing import Optional

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static, OptionList, Select, Label
from textual.widgets.option_list import Option
from textual.containers import Vertical, Horizontal
from textual.binding import Binding

from storage_schema import GoalData, PlanData, TodoData


# Role options
ROLES = [
    ("interview", "Interview"),
    ("planning", "Planning"),
    ("implementation", "Implementation"),
    ("postmortem", "Postmortem"),
    ("exploration", "Exploration"),
]


@dataclass
class EntityPickerResult:
    """Result from EntityPickerModal."""
    entity_type: str  # "goal", "plan", "todo"
    entity_id: str
    entity_title: str
    role: str


class EntityPickerModal(ModalScreen[Optional[EntityPickerResult]]):
    """Modal for selecting an entity to bind a session to.

    Shows a hierarchical list:
    - Goals (with 🎯 icon)
      - Plans (with 📋 icon, indented)
        - Todos (with ○/● icon, double-indented)

    The user can select any level and optionally choose a role.
    """

    DEFAULT_CSS = """
    EntityPickerModal {
        align: center middle;
    }

    EntityPickerModal > Vertical {
        width: 80;
        height: auto;
        max-height: 85%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    EntityPickerModal #dialog-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
        height: 1;
    }

    EntityPickerModal #session-info {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
        height: auto;
    }

    EntityPickerModal OptionList {
        height: auto;
        max-height: 20;
        margin-bottom: 1;
    }

    EntityPickerModal .field-row {
        height: 3;
        margin-bottom: 1;
    }

    EntityPickerModal .field-label {
        width: 10;
        height: 1;
        padding-top: 1;
    }

    EntityPickerModal Select {
        width: 1fr;
    }

    EntityPickerModal #buttons {
        align: center middle;
        height: 3;
    }

    EntityPickerModal #buttons Static {
        margin: 0 2;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("enter", "select", "Select", show=True),
    ]

    def __init__(
        self,
        session_id: str,
        session_name: str,
        goals: list[GoalData],
        plans: list[PlanData],
        todos: list[TodoData],
        current_binding: Optional[tuple[str, str]] = None,  # (entity_type, entity_id)
        default_role: str = "implementation",
        todo_plan_mapping: Optional[dict[str, list[str]]] = None,  # plan_id -> [todo_ids]
        **kwargs
    ):
        super().__init__(**kwargs)
        self._session_id = session_id
        self._session_name = session_name
        self._goals = goals
        self._plans = plans
        self._todos = todos
        self._current_binding = current_binding
        self._default_role = default_role
        self._todo_plan_mapping = todo_plan_mapping or {}

        # Build entity lookup
        self._entity_lookup: dict[str, tuple[str, str, str]] = {}  # id -> (type, id, title)

        # Build reverse mapping: todo_id -> plan_id
        self._todo_to_plan: dict[str, str] = {}
        for plan_id, todo_ids in self._todo_plan_mapping.items():
            for todo_id in todo_ids:
                self._todo_to_plan[todo_id] = plan_id

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Bind Session to Entity", id="dialog-title")
            yield Static(f"[dim]Session: {self._session_name}[/]", id="session-info")

            # Entity list
            option_list = OptionList(id="entity-list")
            self._build_entity_options(option_list)
            yield option_list

            # Role selection
            with Horizontal(classes="field-row"):
                yield Label("Role:", classes="field-label")
                yield Select(
                    [(desc, role) for role, desc in ROLES],
                    value=self._default_role,
                    id="role-select",
                )

            # Buttons hint
            with Horizontal(id="buttons"):
                yield Static("[dim]Enter: Select | Escape: Cancel[/]")

    def _build_entity_options(self, option_list: OptionList) -> None:
        """Build hierarchical entity options."""
        # Group plans by goal
        plans_by_goal: dict[str, list[PlanData]] = {}
        for plan in self._plans:
            plans_by_goal.setdefault(plan.goal_id, []).append(plan)

        # Group todos by plan
        # We need to look up which plan each todo belongs to
        # For now, todos will be shown under their plans

        for goal in sorted(self._goals, key=lambda g: (-g.weight, g.title)):
            # Add goal option
            status_icon = "●" if goal.status == "active" else "○"
            is_current = self._current_binding == ("goal", goal.id)
            current_marker = " [cyan]← current[/]" if is_current else ""

            goal_label = f"🎯 {status_icon} [bold]{goal.title}[/]{current_marker}"
            option_list.add_option(Option(goal_label, id=f"goal:{goal.id}"))
            self._entity_lookup[f"goal:{goal.id}"] = ("goal", goal.id, goal.title)

            # Add plans under this goal
            goal_plans = plans_by_goal.get(goal.id, [])
            for plan in sorted(goal_plans, key=lambda p: p.title):
                is_current = self._current_binding == ("plan", plan.id)
                current_marker = " [cyan]← current[/]" if is_current else ""
                status_icon = "●" if plan.status == "active" else "○"

                plan_label = f"  📋 {status_icon} [cyan]{plan.title}[/]{current_marker}"
                option_list.add_option(Option(plan_label, id=f"plan:{plan.id}"))
                self._entity_lookup[f"plan:{plan.id}"] = ("plan", plan.id, plan.title)

                # Add todos under this plan
                # We need to find todos linked to this plan
                plan_todos = [t for t in self._todos if self._is_todo_in_plan(t.id, plan.id)]
                for todo in sorted(plan_todos, key=lambda t: t.title):
                    is_current = self._current_binding == ("todo", todo.id)
                    current_marker = " [cyan]← current[/]" if is_current else ""

                    if todo.status == "completed":
                        status_icon = "[green]✓[/]"
                    elif todo.status == "in_progress":
                        status_icon = "[cyan]◐[/]"
                    elif todo.status == "pending":
                        status_icon = "[yellow]○[/]"
                    else:
                        status_icon = "○"

                    spike_marker = " [magenta][spike][/]" if todo.is_spike else ""
                    todo_label = f"    {status_icon} {todo.title}{spike_marker}{current_marker}"
                    option_list.add_option(Option(todo_label, id=f"todo:{todo.id}"))
                    self._entity_lookup[f"todo:{todo.id}"] = ("todo", todo.id, todo.title)

        # Add separator and "unbind" option if currently bound
        if self._current_binding:
            option_list.add_option(Option("[dim]────────────────────────────────[/]", id="separator", disabled=True))
            option_list.add_option(Option("[red]✗ Remove binding (unbind)[/]", id="unbind"))

    def _is_todo_in_plan(self, todo_id: str, plan_id: str) -> bool:
        """Check if a todo is linked to a plan using the todo-plan mapping."""
        return self._todo_to_plan.get(todo_id) == plan_id

    def on_mount(self) -> None:
        self.query_one("#entity-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        self._submit_selection(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select(self) -> None:
        option_list = self.query_one("#entity-list", OptionList)
        if option_list.highlighted is not None:
            option = option_list.get_option_at_index(option_list.highlighted)
            self._submit_selection(option.id)

    def _submit_selection(self, option_id: str) -> None:
        """Submit the selected entity."""
        if option_id == "unbind":
            # Special case: unbind - return None to signal removal
            # We'll use a special marker
            self.dismiss(EntityPickerResult(
                entity_type="",
                entity_id="",
                entity_title="",
                role="",
            ))
            return

        if option_id not in self._entity_lookup:
            return

        entity_type, entity_id, entity_title = self._entity_lookup[option_id]
        role_select = self.query_one("#role-select", Select)
        role = role_select.value or self._default_role

        self.dismiss(EntityPickerResult(
            entity_type=entity_type,
            entity_id=entity_id,
            entity_title=entity_title,
            role=role,
        ))
