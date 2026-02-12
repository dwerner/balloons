"""Command execution for goal-oriented task management.

Handles execution of :goals, :plans, :todos, :todo-done, :bind, :unbind commands.
Returns formatted output for display in the TUI.
"""

from dataclasses import dataclass, field
from typing import Optional
import uuid
from datetime import datetime

from core.async_storage import GoalStorage, get_goal_storage
from core.priority_engine import PriorityEngine, TodoWithContext
from core.lifecycle_hooks import LifecycleHooks, LifecyclePrompt
from storage_schema import GoalData, PlanData, TodoData, SessionBinding, TodoPlanLink


@dataclass
class GoalListResult:
    """Result of :goals command."""
    success: bool
    error: Optional[str] = None
    goals: list[GoalData] = field(default_factory=list)
    formatted: str = ""


@dataclass
class PlanListResult:
    """Result of :plans command."""
    success: bool
    error: Optional[str] = None
    plans: list[PlanData] = field(default_factory=list)
    goal: Optional[GoalData] = None  # Parent goal if filtered
    formatted: str = ""


@dataclass
class TodoListResult:
    """Result of :todos command."""
    success: bool
    error: Optional[str] = None
    todos: list[TodoWithContext] = field(default_factory=list)
    plan: Optional[PlanData] = None  # Parent plan if filtered
    formatted: str = ""


@dataclass
class TodoDoneResult:
    """Result of :todo-done command."""
    success: bool
    error: Optional[str] = None
    todo: Optional[TodoData] = None
    lifecycle_prompt: Optional[LifecyclePrompt] = None
    formatted: str = ""


@dataclass
class BindResult:
    """Result of :bind command."""
    success: bool
    error: Optional[str] = None
    binding: Optional[SessionBinding] = None
    formatted: str = ""


@dataclass
class UnbindResult:
    """Result of :unbind command."""
    success: bool
    error: Optional[str] = None
    released_count: int = 0
    formatted: str = ""


class GoalCommandExecutor:
    """Executes goal-oriented task management commands.

    Usage:
        executor = GoalCommandExecutor()
        result = await executor.list_goals(include_completed=False)
        print(result.formatted)
    """

    def __init__(self, goal_storage: GoalStorage | None = None):
        self._goal_storage = goal_storage

    async def _get_storage(self) -> GoalStorage:
        if self._goal_storage is None:
            self._goal_storage = await get_goal_storage()
        return self._goal_storage

    # =========================================================================
    # :goals command
    # =========================================================================

    async def list_goals(self, include_completed: bool = False) -> GoalListResult:
        """List goals with status and weight."""
        try:
            storage = await self._get_storage()
            goals = await storage.list_goals()

            # Filter by status unless include_completed
            if not include_completed:
                goals = [g for g in goals if g.status == "active"]

            # Sort by weight descending
            goals.sort(key=lambda g: -g.weight)

            formatted = self._format_goals(goals)
            return GoalListResult(success=True, goals=goals, formatted=formatted)

        except Exception as e:
            return GoalListResult(success=False, error=str(e))

    def _format_goals(self, goals: list[GoalData]) -> str:
        """Format goals for display."""
        if not goals:
            return "[dim]No goals found. Create one with the interview workflow.[/dim]"

        lines = ["[bold cyan]Goals[/bold cyan]", ""]

        for goal in goals:
            status_icon = {
                "active": "[green]●[/green]",
                "completed": "[blue]✓[/blue]",
                "superseded": "[yellow]→[/yellow]",
                "abandoned": "[red]✗[/red]",
            }.get(goal.status, "○")

            weight_bar = "█" * goal.weight + "░" * (10 - goal.weight)
            lines.append(
                f"  {status_icon} [bold]{goal.title}[/bold] "
                f"[dim]({goal.id[:8]})[/dim]"
            )
            lines.append(f"      Weight: [{weight_bar}] {goal.weight}/10")
            if goal.description:
                desc = goal.description[:60] + "..." if len(goal.description) > 60 else goal.description
                lines.append(f"      {desc}")
            lines.append("")

        return "\n".join(lines)

    # =========================================================================
    # :plans command
    # =========================================================================

    async def list_plans(self, goal_id: str = "") -> PlanListResult:
        """List plans, optionally filtered by goal."""
        try:
            storage = await self._get_storage()

            goal = None
            if goal_id:
                # Try to find goal by prefix match
                goal = await self._find_goal_by_prefix(goal_id)
                if not goal:
                    return PlanListResult(
                        success=False,
                        error=f"Goal not found: {goal_id}"
                    )
                plans = await storage.list_plans(goal_id=goal.id)
            else:
                plans = await storage.list_plans()

            # Sort: active first, then by title
            plans.sort(key=lambda p: (p.status != "active", p.title))

            formatted = self._format_plans(plans, goal)
            return PlanListResult(success=True, plans=plans, goal=goal, formatted=formatted)

        except Exception as e:
            return PlanListResult(success=False, error=str(e))

    async def _find_goal_by_prefix(self, prefix: str) -> Optional[GoalData]:
        """Find a goal by ID prefix."""
        storage = await self._get_storage()
        goals = await storage.list_goals()
        for goal in goals:
            if goal.id.startswith(prefix):
                return goal
        return None

    def _format_plans(self, plans: list[PlanData], goal: Optional[GoalData]) -> str:
        """Format plans for display."""
        if not plans:
            if goal:
                return f"[dim]No plans for goal '{goal.title}'. Create one to break down the work.[/dim]"
            return "[dim]No plans found.[/dim]"

        lines = []
        if goal:
            lines.append(f"[bold cyan]Plans for: {goal.title}[/bold cyan]")
        else:
            lines.append("[bold cyan]All Plans[/bold cyan]")
        lines.append("")

        for plan in plans:
            status_icon = {
                "draft": "[yellow]◌[/yellow]",
                "active": "[green]●[/green]",
                "completed": "[blue]✓[/blue]",
                "abandoned": "[red]✗[/red]",
            }.get(plan.status, "○")

            lines.append(
                f"  {status_icon} [bold]{plan.title}[/bold] "
                f"[dim]({plan.id[:8]})[/dim]"
            )
            if plan.description:
                desc = plan.description[:60] + "..." if len(plan.description) > 60 else plan.description
                lines.append(f"      {desc}")
            lines.append("")

        return "\n".join(lines)

    # =========================================================================
    # :todos command
    # =========================================================================

    async def list_todos(self, plan_id: str = "") -> TodoListResult:
        """List todos with priority ranking."""
        try:
            storage = await self._get_storage()
            engine = PriorityEngine(storage)

            plan = None
            if plan_id:
                # Try to find plan by prefix match
                plan = await self._find_plan_by_prefix(plan_id)
                if not plan:
                    return TodoListResult(
                        success=False,
                        error=f"Plan not found: {plan_id}"
                    )
                # Get todos for specific plan
                todo_ids = await storage.get_todos_for_plan(plan.id)
                todos_with_context = []
                for todo_id in todo_ids:
                    todo = await storage.load_todo(todo_id)
                    if todo:
                        # Build minimal context
                        todos_with_context.append(TodoWithContext(
                            todo=todo,
                            priority=0.0,
                            goal=None,
                            plans=[plan],
                            completion_factor=0.0,
                        ))
            else:
                # Get priority-ranked available todos
                todos_with_context = await engine.get_priority_ranked_todos_with_context()

            formatted = self._format_todos(todos_with_context, plan)
            return TodoListResult(
                success=True,
                todos=todos_with_context,
                plan=plan,
                formatted=formatted
            )

        except Exception as e:
            return TodoListResult(success=False, error=str(e))

    # =========================================================================
    # Create plan
    # =========================================================================

    async def create_plan(
        self,
        goal_id: str,
        title: str,
        description: str = "",
        status: str = "active",
    ) -> BindResult:
        """Create a new plan under a goal."""
        try:
            storage = await self._get_storage()

            # Validate goal exists
            goal = await self._find_goal_by_prefix(goal_id)
            if not goal:
                return BindResult(success=False, error=f"Goal not found: {goal_id}")

            # Create plan
            now = datetime.now().isoformat()
            plan = PlanData(
                id=str(uuid.uuid4()),
                goal_id=goal.id,
                title=title,
                description=description,
                status=status,
                created_at=now,
                updated_at=now,
            )
            await storage.save_plan(plan)

            # Note: The plan-to-goal relationship is stored in plan.goal_id.
            # There's no plan_ids list on GoalData - the relationship is queried
            # by filtering plans by goal_id when needed.

            formatted = f"[green]✓[/green] Created plan: [bold]{title}[/bold]"
            return BindResult(success=True, formatted=formatted)

        except Exception as e:
            return BindResult(success=False, error=str(e))

    # =========================================================================
    # Create todo
    # =========================================================================

    async def create_todo(
        self,
        plan_id: str,
        title: str,
        description: str = "",
        is_spike: bool = False,
        timebox_minutes: Optional[int] = None,
    ) -> BindResult:
        """Create a new todo under a plan."""
        try:
            storage = await self._get_storage()

            # Validate plan exists
            plan = await self._find_plan_by_prefix(plan_id)
            if not plan:
                return BindResult(success=False, error=f"Plan not found: {plan_id}")

            # Create todo
            now = datetime.now().isoformat()
            todo = TodoData(
                id=str(uuid.uuid4()),
                title=title,
                description=description,
                status="pending",
                is_spike=is_spike,
                timebox_minutes=timebox_minutes,
                created_at=now,
                updated_at=now,
            )
            await storage.save_todo(todo)

            # Link todo to plan
            link = TodoPlanLink(
                todo_id=todo.id,
                plan_id=plan.id,
                created_at=now,
            )
            await storage.save_todo_plan_link(link)

            formatted = f"[green]✓[/green] Created todo: [bold]{title}[/bold]"
            if is_spike:
                formatted += f" [magenta][spike][/magenta]"
            return BindResult(success=True, formatted=formatted)

        except Exception as e:
            return BindResult(success=False, error=str(e))

    async def _find_plan_by_prefix(self, prefix: str) -> Optional[PlanData]:
        """Find a plan by ID prefix."""
        storage = await self._get_storage()
        plans = await storage.list_plans()
        for plan in plans:
            if plan.id.startswith(prefix):
                return plan
        return None

    def _format_todos(
        self,
        todos: list[TodoWithContext],
        plan: Optional[PlanData]
    ) -> str:
        """Format todos for display."""
        if not todos:
            if plan:
                return f"[dim]No todos for plan '{plan.title}'.[/dim]"
            return "[dim]No available todos. All work complete or blocked.[/dim]"

        lines = []
        if plan:
            lines.append(f"[bold cyan]Todos for: {plan.title}[/bold cyan]")
        else:
            lines.append("[bold cyan]Priority-Ranked Todos[/bold cyan]")
        lines.append("")

        for i, ctx in enumerate(todos, 1):
            todo = ctx.todo
            status_icon = {
                "pending": "[yellow]○[/yellow]",
                "in_progress": "[cyan]◐[/cyan]",
                "completed": "[green]✓[/green]",
                "blocked": "[red]⊘[/red]",
                "abandoned": "[dim]✗[/dim]",
            }.get(todo.status, "○")

            spike_marker = " [magenta][spike][/magenta]" if todo.is_spike else ""

            if ctx.priority > 0:
                lines.append(
                    f"  {i}. {status_icon} [bold]{todo.title}[/bold]{spike_marker} "
                    f"[dim]({todo.id[:8]})[/dim] "
                    f"[yellow]pri:{ctx.priority:.1f}[/yellow]"
                )
                if ctx.goal:
                    lines.append(f"       Goal: {ctx.goal.title}")
            else:
                lines.append(
                    f"  {status_icon} [bold]{todo.title}[/bold]{spike_marker} "
                    f"[dim]({todo.id[:8]})[/dim]"
                )

            if todo.description:
                desc = todo.description[:50] + "..." if len(todo.description) > 50 else todo.description
                lines.append(f"       {desc}")
            lines.append("")

        return "\n".join(lines)

    # =========================================================================
    # :todo-done command
    # =========================================================================

    async def mark_todo_done(self, todo_id: str, session_id: str) -> TodoDoneResult:
        """Mark a todo as complete, triggering lifecycle hooks."""
        try:
            storage = await self._get_storage()

            # Find todo by prefix
            todo = await self._find_todo_by_prefix(todo_id)
            if not todo:
                return TodoDoneResult(
                    success=False,
                    error=f"Todo not found: {todo_id}"
                )

            # Trigger lifecycle hook
            hooks = LifecycleHooks(storage)
            prompt = await hooks.on_todo_complete(todo.id, session_id)

            # Reload todo to get updated status
            todo = await storage.load_todo(todo.id)

            formatted = f"[green]✓[/green] Marked todo complete: [bold]{todo.title}[/bold]"
            if prompt:
                formatted += f"\n\n{prompt.message}"

            return TodoDoneResult(
                success=True,
                todo=todo,
                lifecycle_prompt=prompt,
                formatted=formatted
            )

        except Exception as e:
            return TodoDoneResult(success=False, error=str(e))

    async def _find_todo_by_prefix(self, prefix: str) -> Optional[TodoData]:
        """Find a todo by ID prefix."""
        storage = await self._get_storage()
        todos = await storage.list_todos(include_spikes=True)
        for todo in todos:
            if todo.id.startswith(prefix):
                return todo
        return None

    # =========================================================================
    # :bind command
    # =========================================================================

    async def bind_session(
        self,
        session_id: str,
        entity_type: str,
        entity_id: str,
        role: str = "implementation"
    ) -> BindResult:
        """Bind a session to a goal, plan, or todo."""
        try:
            storage = await self._get_storage()

            # Validate entity exists
            entity_title = ""
            if entity_type == "goal":
                entity = await self._find_goal_by_prefix(entity_id)
                if entity:
                    entity_id = entity.id
                    entity_title = entity.title
            elif entity_type == "plan":
                entity = await self._find_plan_by_prefix(entity_id)
                if entity:
                    entity_id = entity.id
                    entity_title = entity.title
            elif entity_type == "todo":
                entity = await self._find_todo_by_prefix(entity_id)
                if entity:
                    entity_id = entity.id
                    entity_title = entity.title
            else:
                return BindResult(success=False, error=f"Unknown entity type: {entity_type}")

            if not entity_title:
                return BindResult(success=False, error=f"{entity_type.title()} not found: {entity_id}")

            # Create binding
            now = datetime.now().isoformat()
            binding = SessionBinding(
                id=str(uuid.uuid4()),
                session_id=session_id,
                entity_type=entity_type,
                entity_id=entity_id,
                role=role,
                created_at=now,
            )
            await storage.save_session_binding(binding)

            formatted = (
                f"[green]✓[/green] Bound session to {entity_type}: "
                f"[bold]{entity_title}[/bold] (role: {role})"
            )
            return BindResult(success=True, binding=binding, formatted=formatted)

        except Exception as e:
            return BindResult(success=False, error=str(e))

    # =========================================================================
    # :unbind command
    # =========================================================================

    async def unbind_session(
        self,
        session_id: str,
        entity_id: str = ""
    ) -> UnbindResult:
        """Release session bindings."""
        try:
            storage = await self._get_storage()

            bindings = await storage.get_bindings_for_session(session_id, active_only=True)

            if not bindings:
                return UnbindResult(
                    success=True,
                    released_count=0,
                    formatted="[dim]No active bindings to release.[/dim]"
                )

            now = datetime.now().isoformat()
            released = 0

            for binding in bindings:
                if entity_id and not binding.entity_id.startswith(entity_id):
                    continue

                binding.released_at = now
                await storage.save_session_binding(binding)
                released += 1

            if released == 0 and entity_id:
                return UnbindResult(
                    success=False,
                    error=f"No binding found for entity: {entity_id}"
                )

            formatted = f"[green]✓[/green] Released {released} binding(s)"
            return UnbindResult(success=True, released_count=released, formatted=formatted)

        except Exception as e:
            return UnbindResult(success=False, error=str(e))


# =============================================================================
# Priority Divergence Check
# =============================================================================

@dataclass
class PriorityDivergenceInfo:
    """Information about priority divergence for the current session."""
    is_diverged: bool = False
    bound_todo: Optional[TodoData] = None
    bound_priority: float = 0.0
    top_todo: Optional[TodoData] = None
    top_priority: float = 0.0
    message: str = ""


async def check_priority_divergence(session_id: str) -> PriorityDivergenceInfo:
    """Check if session is working on a non-highest-priority todo.

    Returns info about whether the session's bound todo differs from
    the highest priority available todo.
    """
    try:
        storage = await get_goal_storage()
        engine = PriorityEngine(storage)

        # Get session's bound todo
        bindings = await storage.get_bindings_for_session(session_id, active_only=True)
        todo_bindings = [b for b in bindings if b.entity_type == "todo"]

        if not todo_bindings:
            return PriorityDivergenceInfo()  # Not bound to any todo

        # Get the bound todo
        binding = todo_bindings[0]  # Use first todo binding
        bound_todo = await storage.load_todo(binding.entity_id)
        if not bound_todo:
            return PriorityDivergenceInfo()

        # Get priority-ranked todos
        ranked = await engine.get_priority_ranked_todos()
        if not ranked:
            return PriorityDivergenceInfo()

        top_todo, top_priority = ranked[0]

        # Find priority of bound todo
        bound_priority = 0.0
        for todo, priority in ranked:
            if todo.id == bound_todo.id:
                bound_priority = priority
                break

        # Check for divergence
        if top_todo.id != bound_todo.id and top_priority > bound_priority:
            return PriorityDivergenceInfo(
                is_diverged=True,
                bound_todo=bound_todo,
                bound_priority=bound_priority,
                top_todo=top_todo,
                top_priority=top_priority,
                message=f"Higher priority: {top_todo.title} ({top_priority:.1f} vs {bound_priority:.1f})"
            )

        return PriorityDivergenceInfo(
            is_diverged=False,
            bound_todo=bound_todo,
            bound_priority=bound_priority,
        )

    except Exception:
        return PriorityDivergenceInfo()


# =============================================================================
# Convenience Functions
# =============================================================================

async def list_goals(include_completed: bool = False) -> GoalListResult:
    """Convenience function for listing goals."""
    executor = GoalCommandExecutor()
    return await executor.list_goals(include_completed)


async def list_plans(goal_id: str = "") -> PlanListResult:
    """Convenience function for listing plans."""
    executor = GoalCommandExecutor()
    return await executor.list_plans(goal_id)


async def list_todos(plan_id: str = "") -> TodoListResult:
    """Convenience function for listing todos."""
    executor = GoalCommandExecutor()
    return await executor.list_todos(plan_id)


async def mark_todo_done(todo_id: str, session_id: str) -> TodoDoneResult:
    """Convenience function for marking todo done."""
    executor = GoalCommandExecutor()
    return await executor.mark_todo_done(todo_id, session_id)


# =============================================================================
# Binding Indicator for Session Labels
# =============================================================================

# Role abbreviations for compact display
ROLE_ABBREV = {
    "interview": "int",
    "planning": "plan",
    "implementation": "impl",
    "postmortem": "post",
    "exploration": "expl",
}


async def get_session_binding_indicator(session_id: str) -> str:
    """Get binding indicator for a session's label.

    Returns a string like "[impl: Add caching]" if the session is bound
    to a todo/plan/goal, or empty string if not bound.

    The indicator format is: [role-abbrev: entity-title]
    - role-abbrev: impl, plan, int, post, expl
    - entity-title: truncated to 20 chars
    """
    try:
        storage = await get_goal_storage()
        bindings = await storage.get_bindings_for_session(session_id, active_only=True)

        if not bindings:
            return ""

        # Use the most specific binding (todo > plan > goal)
        # and the most recent one if multiple of same type
        best_binding = None
        type_priority = {"todo": 0, "plan": 1, "goal": 2}

        for binding in bindings:
            if best_binding is None:
                best_binding = binding
            elif type_priority.get(binding.entity_type, 99) < type_priority.get(best_binding.entity_type, 99):
                best_binding = binding
            elif (type_priority.get(binding.entity_type, 99) == type_priority.get(best_binding.entity_type, 99)
                  and binding.created_at > best_binding.created_at):
                best_binding = binding

        if not best_binding:
            return ""

        # Get entity title
        entity_title = ""
        if best_binding.entity_type == "todo":
            todo = await storage.load_todo(best_binding.entity_id)
            if todo:
                entity_title = todo.title
        elif best_binding.entity_type == "plan":
            plan = await storage.load_plan(best_binding.entity_id)
            if plan:
                entity_title = plan.title
        elif best_binding.entity_type == "goal":
            goal = await storage.load_goal(best_binding.entity_id)
            if goal:
                entity_title = goal.title

        if not entity_title:
            return ""

        # Format: [role: title]
        role_abbrev = ROLE_ABBREV.get(best_binding.role, best_binding.role[:4])
        truncated_title = entity_title[:20] + "..." if len(entity_title) > 20 else entity_title

        return f"[{role_abbrev}: {truncated_title}]"

    except Exception:
        return ""


async def get_all_session_binding_indicators(session_ids: list[str]) -> dict[str, str]:
    """Get binding indicators for multiple sessions (batch optimization).

    Returns a dict mapping session_id -> indicator string.
    Sessions without bindings are not included in the result.
    """
    result = {}
    try:
        storage = await get_goal_storage()

        for session_id in session_ids:
            indicator = await get_session_binding_indicator(session_id)
            if indicator:
                result[session_id] = indicator

    except Exception:
        pass

    return result


async def get_session_binding_preview(session_id: str) -> str:
    """Get a preview line for session binding display.

    Returns a string like "Add caching layer for database queries"
    showing the entity title and/or description snippet, suitable for
    display under the breadcrumb.

    Returns empty string if session is not bound to any entity.
    """
    try:
        storage = await get_goal_storage()
        bindings = await storage.get_bindings_for_session(session_id, active_only=True)

        if not bindings:
            return ""

        # Use the most specific binding (todo > plan > goal)
        # Same priority logic as get_session_binding_indicator
        best_binding = None
        type_priority = {"todo": 0, "plan": 1, "goal": 2}

        for binding in bindings:
            if best_binding is None:
                best_binding = binding
            elif type_priority.get(binding.entity_type, 99) < type_priority.get(best_binding.entity_type, 99):
                best_binding = binding
            elif (type_priority.get(binding.entity_type, 99) == type_priority.get(best_binding.entity_type, 99)
                  and binding.created_at > best_binding.created_at):
                best_binding = binding

        if not best_binding:
            return ""

        # Get entity title and description
        entity_title = ""
        entity_desc = ""

        if best_binding.entity_type == "todo":
            todo = await storage.load_todo(best_binding.entity_id)
            if todo:
                entity_title = todo.title
                entity_desc = todo.description or ""
        elif best_binding.entity_type == "plan":
            plan = await storage.load_plan(best_binding.entity_id)
            if plan:
                entity_title = plan.title
                entity_desc = plan.description or ""
        elif best_binding.entity_type == "goal":
            goal = await storage.load_goal(best_binding.entity_id)
            if goal:
                entity_title = goal.title
                entity_desc = goal.description or ""

        if not entity_title:
            return ""

        # Build preview: "title: description snippet" or just "title"
        # Truncate to fit typical terminal width (~80 chars)
        role_abbrev = ROLE_ABBREV.get(best_binding.role, best_binding.role[:4])
        preview_parts = [f"{role_abbrev}:"]

        if entity_desc:
            # First line of description, truncated
            first_line = entity_desc.split('\n')[0].strip()
            max_desc_len = 70 - len(role_abbrev) - 2  # Leave room for role prefix
            if len(first_line) > max_desc_len:
                first_line = first_line[:max_desc_len - 3] + "..."
            preview_parts.append(first_line)
        else:
            # No description, just show title
            max_title_len = 70 - len(role_abbrev) - 2
            if len(entity_title) > max_title_len:
                entity_title = entity_title[:max_title_len - 3] + "..."
            preview_parts.append(entity_title)

        return " ".join(preview_parts)

    except Exception:
        return ""


async def get_session_binding_info(session_id: str) -> tuple[str, str]:
    """Get both binding indicator and preview for a session.

    Returns (indicator, preview) tuple. Both may be empty strings
    if session is not bound.

    This is more efficient than calling both functions separately
    as it only queries storage once.
    """
    try:
        storage = await get_goal_storage()
        bindings = await storage.get_bindings_for_session(session_id, active_only=True)

        if not bindings:
            return ("", "")

        # Use the most specific binding (todo > plan > goal)
        best_binding = None
        type_priority = {"todo": 0, "plan": 1, "goal": 2}

        for binding in bindings:
            if best_binding is None:
                best_binding = binding
            elif type_priority.get(binding.entity_type, 99) < type_priority.get(best_binding.entity_type, 99):
                best_binding = binding
            elif (type_priority.get(binding.entity_type, 99) == type_priority.get(best_binding.entity_type, 99)
                  and binding.created_at > best_binding.created_at):
                best_binding = binding

        if not best_binding:
            return ("", "")

        # Get entity data
        entity_title = ""
        entity_desc = ""

        if best_binding.entity_type == "todo":
            todo = await storage.load_todo(best_binding.entity_id)
            if todo:
                entity_title = todo.title
                entity_desc = todo.description or ""
        elif best_binding.entity_type == "plan":
            plan = await storage.load_plan(best_binding.entity_id)
            if plan:
                entity_title = plan.title
                entity_desc = plan.description or ""
        elif best_binding.entity_type == "goal":
            goal = await storage.load_goal(best_binding.entity_id)
            if goal:
                entity_title = goal.title
                entity_desc = goal.description or ""

        if not entity_title:
            return ("", "")

        role_abbrev = ROLE_ABBREV.get(best_binding.role, best_binding.role[:4])

        # Build indicator: [role: title]
        truncated_title = entity_title[:20] + "..." if len(entity_title) > 20 else entity_title
        indicator = f"[{role_abbrev}: {truncated_title}]"

        # Build preview: "role: description" or "role: title"
        preview_parts = [f"{role_abbrev}:"]
        if entity_desc:
            first_line = entity_desc.split('\n')[0].strip()
            max_desc_len = 70 - len(role_abbrev) - 2
            if len(first_line) > max_desc_len:
                first_line = first_line[:max_desc_len - 3] + "..."
            preview_parts.append(first_line)
        else:
            max_title_len = 70 - len(role_abbrev) - 2
            if len(entity_title) > max_title_len:
                entity_title = entity_title[:max_title_len - 3] + "..."
            preview_parts.append(entity_title)

        preview = " ".join(preview_parts)

        return (indicator, preview)

    except Exception:
        return ("", "")
