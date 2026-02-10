"""Priority engine for goal-oriented task management.

Computes dynamic priorities for todos based on:
- Goal weight (1-10)
- Completion factor (momentum from in-progress work)
- Dependency availability (blocked todos are not ranked)

Priority formula:
    todo_priority = goal_weight × completion_factor

Where:
- goal_weight: 1-10 from the parent goal
- completion_factor: max(sibling_progress) for each linked plan
  - sibling_progress = completed_todos / total_todos for a plan
  - This rewards momentum on in-progress goals

Usage:
    engine = PriorityEngine()
    ranked = await engine.get_priority_ranked_todos()
    for todo, priority in ranked:
        print(f"{todo.title}: {priority:.2f}")
"""

from dataclasses import dataclass
from typing import Optional

from core.async_storage import GoalStorage, get_goal_storage
from storage_schema import GoalData, PlanData, TodoData


@dataclass
class TodoWithContext:
    """A todo with its computed priority and context."""
    todo: TodoData
    priority: float
    goal: GoalData
    plans: list[PlanData]
    completion_factor: float


class PriorityEngine:
    """Computes dynamic priorities for todos.

    The priority engine answers "what should I work on next?" by:
    1. Finding all available todos (dependencies complete, not spikes)
    2. Computing priority = goal_weight × completion_factor
    3. Ranking by priority descending

    For multi-plan todos, uses MAX of plan priorities.

    Usage:
        engine = PriorityEngine()
        ranked = await engine.get_priority_ranked_todos()
    """

    def __init__(self, goal_storage: GoalStorage | None = None):
        """Initialize the priority engine.

        Args:
            goal_storage: Optional GoalStorage instance. If not provided,
                         the default storage will be used.
        """
        self._goal_storage = goal_storage

    async def _get_storage(self) -> GoalStorage:
        """Get or create the goal storage instance."""
        if self._goal_storage is None:
            self._goal_storage = await get_goal_storage()
        return self._goal_storage

    # =========================================================================
    # Main API
    # =========================================================================

    async def get_priority_ranked_todos(self) -> list[tuple[TodoData, float]]:
        """Return todos sorted by priority, with their computed priority scores.

        Only returns available todos:
        - Dependencies are complete
        - Not spikes (spikes are timeboxed exploration, exempt from priority)
        - Status is pending or in_progress

        Returns:
            List of (TodoData, priority) tuples, sorted by priority descending
        """
        storage = await self._get_storage()

        # Get all non-spike, non-completed todos
        todos = await storage.list_todos(include_spikes=False)
        todos = [t for t in todos if t.status in ("pending", "in_progress")]

        # Compute priority for each available todo
        ranked = []
        for todo in todos:
            if not await self._is_todo_available(todo.id):
                continue  # Skip blocked todos

            priority = await self._compute_todo_priority(todo)
            if priority > 0:  # Only include if linked to active goal/plan
                ranked.append((todo, priority))

        # Sort by priority descending
        ranked.sort(key=lambda x: -x[1])
        return ranked

    async def get_priority_ranked_todos_with_context(
        self,
    ) -> list[TodoWithContext]:
        """Return todos with full context (goal, plans, completion factor).

        Same as get_priority_ranked_todos but includes additional context
        useful for UI display.

        Returns:
            List of TodoWithContext objects, sorted by priority descending
        """
        storage = await self._get_storage()

        todos = await storage.list_todos(include_spikes=False)
        todos = [t for t in todos if t.status in ("pending", "in_progress")]

        ranked = []
        for todo in todos:
            if not await self._is_todo_available(todo.id):
                continue

            context = await self._compute_todo_priority_with_context(todo)
            if context and context.priority > 0:
                ranked.append(context)

        ranked.sort(key=lambda x: -x.priority)
        return ranked

    async def get_next_todo(self) -> Optional[tuple[TodoData, float]]:
        """Get the highest priority available todo.

        Convenience method for getting just the next task to work on.

        Returns:
            (TodoData, priority) tuple or None if no available todos
        """
        ranked = await self.get_priority_ranked_todos()
        return ranked[0] if ranked else None

    # =========================================================================
    # Availability Checking
    # =========================================================================

    async def _is_todo_available(self, todo_id: str) -> bool:
        """Check if a todo is available to work on.

        A todo is available if:
        1. All its dependencies are completed
        2. It's linked to at least one active plan
        3. That plan's goal is active

        Args:
            todo_id: The todo to check

        Returns:
            True if the todo can be worked on
        """
        storage = await self._get_storage()

        # Check dependencies
        dependencies = await storage.get_dependencies(todo_id)
        for dep_id in dependencies:
            dep_todo = await storage.load_todo(dep_id)
            if not dep_todo or dep_todo.status != "completed":
                return False  # Blocked by incomplete dependency

        # Check linked to active plan with active goal
        plan_ids = await storage.get_plans_for_todo(todo_id)
        if not plan_ids:
            return False  # No plans linked

        for plan_id in plan_ids:
            plan = await storage.load_plan(plan_id)
            if not plan or plan.status != "active":
                continue

            goal = await storage.load_goal(plan.goal_id)
            if goal and goal.status == "active":
                return True  # Found at least one active plan with active goal

        return False  # No active plan/goal combination

    async def get_blocked_todos(self) -> list[tuple[TodoData, list[TodoData]]]:
        """Get todos that are blocked by incomplete dependencies.

        Returns:
            List of (blocked_todo, [blocking_todos]) tuples
        """
        storage = await self._get_storage()

        todos = await storage.list_todos(include_spikes=False)
        todos = [t for t in todos if t.status in ("pending", "in_progress")]

        blocked = []
        for todo in todos:
            blocking = await self._get_blocking_todos(todo.id)
            if blocking:
                blocked.append((todo, blocking))

        return blocked

    async def _get_blocking_todos(self, todo_id: str) -> list[TodoData]:
        """Get the todos that are blocking a given todo.

        Args:
            todo_id: The todo to check

        Returns:
            List of incomplete todos that this todo depends on
        """
        storage = await self._get_storage()

        dependencies = await storage.get_dependencies(todo_id)
        blocking = []

        for dep_id in dependencies:
            dep_todo = await storage.load_todo(dep_id)
            if dep_todo and dep_todo.status != "completed":
                blocking.append(dep_todo)

        return blocking

    # =========================================================================
    # Priority Computation
    # =========================================================================

    async def _compute_todo_priority(self, todo: TodoData) -> float:
        """Compute the priority score for a todo.

        Priority = goal_weight × completion_factor

        For todos linked to multiple plans, uses MAX of priorities
        (completing once satisfies all).

        Args:
            todo: The todo to compute priority for

        Returns:
            Priority score (0 if not linked to active goal/plan)
        """
        storage = await self._get_storage()

        plan_ids = await storage.get_plans_for_todo(todo.id)
        if not plan_ids:
            return 0.0

        max_priority = 0.0

        for plan_id in plan_ids:
            plan = await storage.load_plan(plan_id)
            if not plan or plan.status != "active":
                continue

            goal = await storage.load_goal(plan.goal_id)
            if not goal or goal.status != "active":
                continue

            completion_factor = await self._get_completion_factor(plan_id)
            priority = goal.weight * completion_factor
            max_priority = max(max_priority, priority)

        return max_priority

    async def _compute_todo_priority_with_context(
        self,
        todo: TodoData,
    ) -> Optional[TodoWithContext]:
        """Compute priority with full context for UI display.

        Args:
            todo: The todo to compute priority for

        Returns:
            TodoWithContext or None if not linked to active goal/plan
        """
        storage = await self._get_storage()

        plan_ids = await storage.get_plans_for_todo(todo.id)
        if not plan_ids:
            return None

        max_priority = 0.0
        best_goal = None
        all_plans = []
        best_completion_factor = 0.0

        for plan_id in plan_ids:
            plan = await storage.load_plan(plan_id)
            if not plan or plan.status != "active":
                continue

            goal = await storage.load_goal(plan.goal_id)
            if not goal or goal.status != "active":
                continue

            all_plans.append(plan)
            completion_factor = await self._get_completion_factor(plan_id)
            priority = goal.weight * completion_factor

            if priority > max_priority:
                max_priority = priority
                best_goal = goal
                best_completion_factor = completion_factor

        if not best_goal:
            return None

        return TodoWithContext(
            todo=todo,
            priority=max_priority,
            goal=best_goal,
            plans=all_plans,
            completion_factor=best_completion_factor,
        )

    async def _get_completion_factor(self, plan_id: str) -> float:
        """Compute the completion factor for a plan.

        completion_factor = max(0.1, completed_todos / total_todos)

        The minimum of 0.1 ensures todos always have some priority,
        even on plans with no progress yet.

        Args:
            plan_id: The plan to compute completion factor for

        Returns:
            Completion factor between 0.1 and 1.0
        """
        storage = await self._get_storage()

        todo_ids = await storage.get_todos_for_plan(plan_id)
        if not todo_ids:
            return 0.1  # No todos - use minimum

        total = 0
        completed = 0

        for todo_id in todo_ids:
            todo = await storage.load_todo(todo_id)
            if not todo:
                continue
            # Skip spikes - they don't count toward plan progress
            if todo.is_spike:
                continue

            total += 1
            if todo.status == "completed":
                completed += 1

        if total == 0:
            return 0.1  # Only spikes - use minimum

        # Minimum 0.1 to ensure fresh plans have some priority
        return max(0.1, completed / total)

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def get_goal_progress(self, goal_id: str) -> dict:
        """Get progress summary for a goal.

        Returns:
            Dict with progress stats:
            - total_plans: Number of plans
            - active_plans: Number of active plans
            - total_todos: Total todos across all plans
            - completed_todos: Completed todos
            - blocked_todos: Blocked by dependencies
            - available_todos: Ready to work on
        """
        storage = await self._get_storage()

        plans = await storage.list_plans(goal_id=goal_id)

        stats = {
            "total_plans": len(plans),
            "active_plans": 0,
            "total_todos": 0,
            "completed_todos": 0,
            "blocked_todos": 0,
            "available_todos": 0,
        }

        seen_todos = set()  # Avoid double-counting multi-plan todos

        for plan in plans:
            if plan.status == "active":
                stats["active_plans"] += 1

            todo_ids = await storage.get_todos_for_plan(plan.id)
            for todo_id in todo_ids:
                if todo_id in seen_todos:
                    continue
                seen_todos.add(todo_id)

                todo = await storage.load_todo(todo_id)
                if not todo or todo.is_spike:
                    continue

                stats["total_todos"] += 1

                if todo.status == "completed":
                    stats["completed_todos"] += 1
                elif await self._is_todo_available(todo_id):
                    stats["available_todos"] += 1
                elif todo.status in ("pending", "in_progress"):
                    blocking = await self._get_blocking_todos(todo_id)
                    if blocking:
                        stats["blocked_todos"] += 1

        return stats

    async def get_plan_progress(self, plan_id: str) -> dict:
        """Get progress summary for a plan.

        Returns:
            Dict with progress stats:
            - total_todos: Total non-spike todos
            - completed_todos: Completed todos
            - pending_todos: Pending todos
            - in_progress_todos: In-progress todos
            - blocked_todos: Blocked by dependencies
            - completion_pct: Percentage complete (0-100)
        """
        storage = await self._get_storage()

        todo_ids = await storage.get_todos_for_plan(plan_id)

        stats = {
            "total_todos": 0,
            "completed_todos": 0,
            "pending_todos": 0,
            "in_progress_todos": 0,
            "blocked_todos": 0,
            "completion_pct": 0.0,
        }

        for todo_id in todo_ids:
            todo = await storage.load_todo(todo_id)
            if not todo or todo.is_spike:
                continue

            stats["total_todos"] += 1

            if todo.status == "completed":
                stats["completed_todos"] += 1
            elif todo.status == "pending":
                stats["pending_todos"] += 1
            elif todo.status == "in_progress":
                stats["in_progress_todos"] += 1

            if todo.status in ("pending", "in_progress"):
                blocking = await self._get_blocking_todos(todo_id)
                if blocking:
                    stats["blocked_todos"] += 1

        if stats["total_todos"] > 0:
            stats["completion_pct"] = (
                100.0 * stats["completed_todos"] / stats["total_todos"]
            )

        return stats


# =============================================================================
# Convenience Functions
# =============================================================================


async def get_priority_ranked_todos() -> list[tuple[TodoData, float]]:
    """Convenience function to get priority-ranked todos."""
    engine = PriorityEngine()
    return await engine.get_priority_ranked_todos()


async def get_next_todo() -> Optional[tuple[TodoData, float]]:
    """Convenience function to get the next highest priority todo."""
    engine = PriorityEngine()
    return await engine.get_next_todo()


async def is_todo_available(todo_id: str) -> bool:
    """Convenience function to check if a todo is available."""
    engine = PriorityEngine()
    return await engine._is_todo_available(todo_id)
