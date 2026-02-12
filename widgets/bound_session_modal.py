"""Modal for creating a new session bound to a goal, plan, or todo.

When clicking [+] on goal tree nodes, this modal lets the user select the
session role and provides an appropriate initial prompt.
"""

from dataclasses import dataclass
from typing import Optional

from textual.screen import ModalScreen
from textual.widgets import Static, Button, Select, TextArea, Label
from textual.containers import Vertical, Horizontal

from storage_schema import GoalData, PlanData, TodoData


# Role options with descriptions
ROLES = [
    ("interview", "Interview - Goal discovery and requirements gathering"),
    ("planning", "Planning - Break down into plans and todos"),
    ("implementation", "Implementation - Execute a specific task"),
    ("postmortem", "Postmortem - Evaluate completed work"),
    ("exploration", "Exploration - Timeboxed spike/research"),
]

# Default role by entity type
DEFAULT_ROLES = {
    "goal": "planning",  # Goals typically need planning
    "plan": "implementation",  # Plans typically lead to implementation
    "todo": "implementation",  # Todos are typically implemented
}


@dataclass
class BoundSessionResult:
    """Result from BoundSessionModal."""
    entity_type: str  # "goal", "plan", "todo"
    entity_id: str
    role: str  # "interview", "planning", "implementation", etc.
    initial_prompt: str  # The prompt to start the conversation


def generate_initial_prompt(
    entity_type: str,
    entity_data: GoalData | PlanData | TodoData,
    role: str,
    parent_goal: GoalData | None = None,
    parent_plan: PlanData | None = None,
) -> str:
    """Generate an appropriate initial prompt based on entity type and role.

    Args:
        entity_type: "goal", "plan", or "todo"
        entity_data: The entity being bound to
        role: The session role
        parent_goal: For plans/todos, the parent goal
        parent_plan: For todos, the parent plan

    Returns:
        A prompt to start the conversation
    """
    title = entity_data.title
    description = getattr(entity_data, 'description', '')

    if role == "interview":
        if entity_type == "goal":
            return (
                f"I'd like to explore and refine this goal:\n\n"
                f"**{title}**\n\n"
                f"{description}\n\n"
                f"Can you help me clarify the requirements and acceptance criteria?"
            )
        elif entity_type == "plan":
            parent_info = f" (part of goal: {parent_goal.title})" if parent_goal else ""
            return (
                f"I'd like to review this plan{parent_info}:\n\n"
                f"**{title}**\n\n"
                f"{description}\n\n"
                f"Can you help me refine the approach?"
            )
        else:  # todo
            return (
                f"I'd like to discuss this task before starting:\n\n"
                f"**{title}**\n\n"
                f"{description}\n\n"
                f"Can you help me understand the requirements better?"
            )

    elif role == "planning":
        if entity_type == "goal":
            # Include acceptance criteria if available
            criteria = ""
            if hasattr(entity_data, 'acceptance_criteria') and entity_data.acceptance_criteria:
                criteria = "\n\nAcceptance criteria:\n" + "\n".join(
                    f"- {c}" for c in entity_data.acceptance_criteria
                )
            return (
                f"Let's create a plan to achieve this goal:\n\n"
                f"**{title}**\n\n"
                f"{description}{criteria}\n\n"
                f"Please help me break this down into concrete steps and create todos."
            )
        elif entity_type == "plan":
            return (
                f"Let's review and expand this plan:\n\n"
                f"**{title}**\n\n"
                f"{description}\n\n"
                f"Help me identify missing tasks and dependencies."
            )
        else:  # todo
            return (
                f"This task seems complex. Let's break it down:\n\n"
                f"**{title}**\n\n"
                f"{description}\n\n"
                f"Help me identify subtasks or create a plan for implementation."
            )

    elif role == "implementation":
        if entity_type == "goal":
            return (
                f"I'm ready to work on this goal directly:\n\n"
                f"**{title}**\n\n"
                f"{description}\n\n"
                f"Let's start implementing. What should we tackle first?"
            )
        elif entity_type == "plan":
            parent_info = f"\n\nThis is part of the goal: {parent_goal.title}" if parent_goal else ""
            return (
                f"Let's execute this plan:\n\n"
                f"**{title}**\n\n"
                f"{description}{parent_info}\n\n"
                f"What's the first step we should implement?"
            )
        else:  # todo
            # This is the most common case
            context_parts = []
            if parent_plan:
                context_parts.append(f"Plan: {parent_plan.title}")
            if parent_goal:
                context_parts.append(f"Goal: {parent_goal.title}")
            context = "\n".join(context_parts)
            if context:
                context = f"\n\n{context}"

            spike_note = ""
            if hasattr(entity_data, 'is_spike') and entity_data.is_spike:
                timebox = ""
                if hasattr(entity_data, 'timebox_minutes') and entity_data.timebox_minutes:
                    timebox = f" ({entity_data.timebox_minutes} minutes)"
                spike_note = f"\n\n*Note: This is a spike{timebox} - focus on learning, not production code.*"

            return (
                f"Let's implement this task:\n\n"
                f"**{title}**\n\n"
                f"{description}{context}{spike_note}\n\n"
                f"I'm ready to start. Please begin the implementation."
            )

    elif role == "postmortem":
        if entity_type == "goal":
            criteria = ""
            if hasattr(entity_data, 'acceptance_criteria') and entity_data.acceptance_criteria:
                criteria = "\n\nAcceptance criteria to evaluate:\n" + "\n".join(
                    f"- {c}" for c in entity_data.acceptance_criteria
                )
            return (
                f"Let's evaluate the completion of this goal:\n\n"
                f"**{title}**\n\n"
                f"{description}{criteria}\n\n"
                f"Please help me assess whether the acceptance criteria have been met "
                f"and identify any lessons learned or follow-up work needed."
            )
        elif entity_type == "plan":
            return (
                f"Let's review how this plan was executed:\n\n"
                f"**{title}**\n\n"
                f"{description}\n\n"
                f"Please help me evaluate what went well, what could be improved, "
                f"and document any learnings."
            )
        else:  # todo
            return (
                f"Let's review the completion of this task:\n\n"
                f"**{title}**\n\n"
                f"{description}\n\n"
                f"Please help me verify the task was completed properly and note any learnings."
            )

    elif role == "exploration":
        timebox = ""
        if hasattr(entity_data, 'timebox_minutes') and entity_data.timebox_minutes:
            timebox = f" We have {entity_data.timebox_minutes} minutes for this exploration."

        if entity_type == "goal":
            return (
                f"Let's explore approaches for this goal:\n\n"
                f"**{title}**\n\n"
                f"{description}{timebox}\n\n"
                f"This is a spike - focus on learning and documenting findings, "
                f"not production implementation."
            )
        elif entity_type == "plan":
            return (
                f"Let's explore this plan's approach:\n\n"
                f"**{title}**\n\n"
                f"{description}{timebox}\n\n"
                f"Help me investigate feasibility and document findings."
            )
        else:  # todo
            return (
                f"Let's explore this task:\n\n"
                f"**{title}**\n\n"
                f"{description}{timebox}\n\n"
                f"This is exploratory work. Focus on answering questions "
                f"and documenting what we learn."
            )

    # Fallback
    return f"Let's work on: {title}\n\n{description}"


class BoundSessionModal(ModalScreen[Optional[BoundSessionResult]]):
    """Modal for creating a session bound to a goal/plan/todo.

    Shows the entity being bound to, allows role selection,
    and generates an appropriate initial prompt.
    """

    DEFAULT_CSS = """
    BoundSessionModal {
        align: center middle;
    }

    #bound-session-dialog {
        width: 80;
        height: auto;
        max-height: 85%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #dialog-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
        color: $primary;
        height: auto;
    }

    #entity-info {
        height: auto;
        margin-bottom: 1;
        padding: 0 1;
        background: $surface-darken-1;
        border: solid $primary-darken-2;
    }

    #entity-type-label {
        color: $text-muted;
        text-style: italic;
        height: 1;
    }

    #entity-title {
        text-style: bold;
        height: auto;
    }

    #entity-description {
        color: $text-muted;
        height: auto;
    }

    .field-label {
        margin-top: 1;
        margin-bottom: 0;
        height: 1;
    }

    #role-select {
        margin-bottom: 1;
        width: 100%;
    }

    #prompt-input {
        height: 10;
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
        entity_type: str,
        entity_id: str,
        entity_data: GoalData | PlanData | TodoData,
        parent_goal: GoalData | None = None,
        parent_plan: PlanData | None = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.entity_data = entity_data
        self.parent_goal = parent_goal
        self.parent_plan = parent_plan
        self._current_role = DEFAULT_ROLES.get(entity_type, "implementation")

    def compose(self):
        # Truncate description for display
        description = getattr(self.entity_data, 'description', '') or ''
        if len(description) > 150:
            description = description[:147] + "..."

        type_display = self.entity_type.capitalize()

        with Vertical(id="bound-session-dialog"):
            yield Static("New Bound Session", id="dialog-title")

            # Show entity info
            with Vertical(id="entity-info"):
                yield Static(f"[dim]{type_display}[/]", id="entity-type-label")
                yield Static(f"[bold]{self.entity_data.title}[/]", id="entity-title")
                if description:
                    yield Static(f"[dim]{description}[/]", id="entity-description")

            # Role selection
            yield Label("Session Role:", classes="field-label")
            yield Select(
                [(desc, role) for role, desc in ROLES],
                value=self._current_role,
                id="role-select",
            )

            # Editable initial prompt
            yield Label("Initial Prompt (editable):", classes="field-label")
            initial_prompt = generate_initial_prompt(
                self.entity_type,
                self.entity_data,
                self._current_role,
                self.parent_goal,
                self.parent_plan,
            )
            yield TextArea(initial_prompt, id="prompt-input")

            # Buttons
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel-btn", variant="default")
                yield Button("Create Session", id="create-btn", variant="primary")

    def on_mount(self) -> None:
        """Focus the role select when modal opens."""
        self.query_one("#role-select", Select).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Update prompt when role changes."""
        if event.select.id == "role-select" and event.value is not None:
            self._current_role = event.value
            # Update the prompt textarea
            new_prompt = generate_initial_prompt(
                self.entity_type,
                self.entity_data,
                self._current_role,
                self.parent_goal,
                self.parent_plan,
            )
            prompt_input = self.query_one("#prompt-input", TextArea)
            prompt_input.load_text(new_prompt)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        """Submit the form with the user-edited prompt."""
        prompt_input = self.query_one("#prompt-input", TextArea)
        prompt = prompt_input.text.strip()
        self.dismiss(BoundSessionResult(
            entity_type=self.entity_type,
            entity_id=self.entity_id,
            role=self._current_role,
            initial_prompt=prompt,
        ))

    def action_cancel(self) -> None:
        self.dismiss(None)
