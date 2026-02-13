"""Lifecycle hooks for goal-oriented task management.

These hooks fire at key decision points to maintain goal alignment:
- Todo completion: check if plan is done, prompt for next action
- Plan completion: trigger postmortem against acceptance criteria
- Spike completion: prompt for promotion, spawn, or discard

Hooks return LifecyclePrompt objects that the UI can display to the user.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from core.async_storage import GoalStorage, get_goal_storage
from storage_schema import (
    GoalData, PlanData, TodoData, SessionBinding,
    TodoPlanLink,
)


class PostmortemOutcome(str, Enum):
    """Possible outcomes from a plan postmortem."""
    SUCCESS = "success"  # Goal criteria met → mark goal complete
    RETRY = "retry"  # Criteria not met → create new plan (supersedes current)
    ADJUST = "adjust"  # Criteria were wrong → modify goal criteria, then retry
    ABANDON = "abandon"  # Stop pursuing this goal (with reason)


class SpikeOutcome(str, Enum):
    """Possible outcomes from spike completion."""
    PROMOTE = "promote"  # Promote to completed todo (code is production-worthy)
    SPAWN_GOAL = "spawn_goal"  # Create a new goal based on learnings
    DISCARD = "discard"  # Learned something, no further action needed


@dataclass
class LifecyclePrompt:
    """A prompt to show the user at a lifecycle decision point.

    The UI layer interprets these and shows appropriate UI (toast, dialog, etc.)
    """
    prompt_type: str  # "todo_complete", "plan_complete", "spike_complete", "postmortem"
    message: str  # Human-readable prompt
    entity_id: str  # ID of the entity triggering the prompt
    entity_type: str  # "todo", "plan", "goal", "spike"

    # Context for rendering
    entity_title: str = ""
    related_entities: list[dict] = field(default_factory=list)

    # Available choices (for UI)
    choices: list[str] = field(default_factory=list)

    # Optional: pre-filled data for the next action
    suggested_action: Optional[str] = None


@dataclass
class PostmortemContext:
    """Context gathered for running a postmortem."""
    plan: PlanData
    goal: GoalData
    completed_todos: list[TodoData]
    session_bindings: list[SessionBinding]


class LifecycleHooks:
    """Manages lifecycle hooks for goal-oriented entities.

    Usage:
        hooks = LifecycleHooks()

        # When marking a todo complete
        prompt = await hooks.on_todo_complete("todo-123", "session-456")
        if prompt:
            # Show prompt to user
            ...
    """

    def __init__(self, goal_storage: GoalStorage | None = None):
        """Initialize lifecycle hooks.

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
    # Todo Completion Hook
    # =========================================================================

    async def on_todo_complete(
        self,
        todo_id: str,
        session_id: str,
        completed_by: str = "llm",
    ) -> LifecyclePrompt | None:
        """Hook called when a todo is marked complete.

        Checks if all todos for the linked plan(s) are done:
        - If yes: triggers plan completion flow
        - If no: optionally prompts "continue to next todo?"

        Args:
            todo_id: The todo being completed
            session_id: The session completing the todo
            completed_by: Who initiated completion - "llm" or "user"

        Returns:
            LifecyclePrompt if user action needed, None otherwise
        """
        storage = await self._get_storage()

        todo = await storage.load_todo(todo_id)
        if not todo:
            return None

        # Handle spikes separately
        if todo.is_spike:
            return await self._handle_spike_complete(todo, session_id, completed_by)

        # Mark todo complete
        now = datetime.now().isoformat()
        todo.status = "completed"
        todo.completed_at = now
        todo.updated_at = now
        todo.completed_by_session = session_id
        todo.completed_by = completed_by
        await storage.save_todo(todo)

        # Get all plans this todo is linked to
        plan_ids = await storage.get_plans_for_todo(todo_id)
        if not plan_ids:
            # Todo not linked to any plan - just complete it
            return None

        # Check each linked plan for completion
        for plan_id in plan_ids:
            plan = await storage.load_plan(plan_id)
            if not plan or plan.status != "active":
                continue

            plan_complete = await self._check_plan_completion(plan_id)
            if plan_complete:
                return LifecyclePrompt(
                    prompt_type="plan_complete",
                    message=f"All todos for plan '{plan.title}' are complete. Ready for postmortem?",
                    entity_id=plan_id,
                    entity_type="plan",
                    entity_title=plan.title,
                    choices=["Start Postmortem", "Add More Todos", "Skip for Now"],
                    suggested_action="Start Postmortem",
                )

        # Plan not complete - optionally prompt for next todo
        # For now, just return None (no prompt needed)
        return None

    async def _handle_spike_complete(
        self,
        spike: TodoData,
        session_id: str,
        completed_by: str = "llm",
    ) -> LifecyclePrompt:
        """Handle spike completion with promotion/discard options.

        Args:
            spike: The spike being completed
            session_id: The session completing the spike
            completed_by: Who initiated completion - "llm" or "user"

        Returns:
            LifecyclePrompt with spike completion options
        """
        storage = await self._get_storage()

        # Mark spike as completed first
        now = datetime.now().isoformat()
        spike.status = "completed"
        spike.completed_at = now
        spike.updated_at = now
        spike.completed_by_session = session_id
        spike.completed_by = completed_by
        await storage.save_todo(spike)

        return LifecyclePrompt(
            prompt_type="spike_complete",
            message=f"Spike '{spike.title}' complete. What would you like to do?",
            entity_id=spike.id,
            entity_type="spike",
            entity_title=spike.title,
            choices=[
                "Promote to Todo (code is production-worthy)",
                "Spawn New Goal (exploration revealed new direction)",
                "Discard (learned something, no further action)",
            ],
            related_entities=[{
                "type": "timebox",
                "minutes": spike.timebox_minutes,
            }] if spike.timebox_minutes else [],
        )

    async def _check_plan_completion(self, plan_id: str) -> bool:
        """Check if all todos for a plan are complete.

        Args:
            plan_id: The plan to check

        Returns:
            True if all todos are completed, False otherwise
        """
        storage = await self._get_storage()

        todo_ids = await storage.get_todos_for_plan(plan_id)
        if not todo_ids:
            # No todos linked to plan - not complete
            return False

        for todo_id in todo_ids:
            todo = await storage.load_todo(todo_id)
            if not todo:
                continue
            # Skip spikes - they don't block plan completion
            if todo.is_spike:
                continue
            if todo.status != "completed":
                return False

        return True

    # =========================================================================
    # Plan Completion Hook
    # =========================================================================

    async def on_plan_complete(
        self,
        plan_id: str,
        session_id: str,
    ) -> LifecyclePrompt | None:
        """Hook called when a plan is marked complete.

        Triggers postmortem flow: evaluates work against goal's acceptance criteria.

        Args:
            plan_id: The plan being completed
            session_id: The session completing the plan

        Returns:
            LifecyclePrompt for postmortem, or None if plan not found
        """
        storage = await self._get_storage()

        plan = await storage.load_plan(plan_id)
        if not plan:
            return None

        goal = await storage.load_goal(plan.goal_id)
        if not goal:
            return None

        # Gather context for postmortem
        todo_ids = await storage.get_todos_for_plan(plan_id)
        completed_todos = []
        for todo_id in todo_ids:
            todo = await storage.load_todo(todo_id)
            if todo and todo.status == "completed":
                completed_todos.append(todo)

        # Build criteria checklist for the prompt
        criteria_list = "\n".join(
            f"  - {criterion}" for criterion in goal.acceptance_criteria
        )

        return LifecyclePrompt(
            prompt_type="postmortem",
            message=(
                f"Plan '{plan.title}' is complete.\n\n"
                f"Goal: {goal.title}\n\n"
                f"Acceptance Criteria:\n{criteria_list}\n\n"
                "Evaluate whether the goal's acceptance criteria have been met."
            ),
            entity_id=plan_id,
            entity_type="plan",
            entity_title=plan.title,
            choices=[
                "Success - Goal criteria met",
                "Retry - Need new plan",
                "Adjust - Criteria need revision",
                "Abandon - Stop pursuing this goal",
            ],
            related_entities=[
                {"type": "goal", "id": goal.id, "title": goal.title},
                {"type": "completed_todos", "count": len(completed_todos)},
            ],
        )

    # =========================================================================
    # Postmortem Execution
    # =========================================================================

    async def execute_postmortem(
        self,
        plan_id: str,
        outcome: PostmortemOutcome,
        session_id: str,
        notes: str = "",
        new_criteria: list[str] | None = None,
        abandon_reason: str = "",
    ) -> LifecyclePrompt | None:
        """Execute the postmortem outcome for a plan.

        Args:
            plan_id: The plan being evaluated
            outcome: The postmortem outcome chosen by user
            session_id: The session running the postmortem
            notes: Optional postmortem notes
            new_criteria: For ADJUST outcome, the new acceptance criteria
            abandon_reason: For ABANDON outcome, why the goal was abandoned

        Returns:
            LifecyclePrompt for follow-up action, or None if complete
        """
        storage = await self._get_storage()

        plan = await storage.load_plan(plan_id)
        if not plan:
            return None

        goal = await storage.load_goal(plan.goal_id)
        if not goal:
            return None

        now = datetime.now().isoformat()

        if outcome == PostmortemOutcome.SUCCESS:
            return await self._handle_postmortem_success(plan, goal, notes, now)
        elif outcome == PostmortemOutcome.RETRY:
            return await self._handle_postmortem_retry(plan, goal, notes, now)
        elif outcome == PostmortemOutcome.ADJUST:
            return await self._handle_postmortem_adjust(
                plan, goal, notes, new_criteria or [], now
            )
        elif outcome == PostmortemOutcome.ABANDON:
            return await self._handle_postmortem_abandon(
                plan, goal, abandon_reason, now
            )

        return None

    async def _handle_postmortem_success(
        self,
        plan: PlanData,
        goal: GoalData,
        notes: str,
        now: str,
    ) -> LifecyclePrompt | None:
        """Handle SUCCESS postmortem outcome.

        Marks plan and goal as completed.
        """
        storage = await self._get_storage()

        # Mark plan complete
        plan.status = "completed"
        plan.completed_at = now
        plan.updated_at = now
        plan.postmortem = notes or "Goal criteria met."
        await storage.save_plan(plan)

        # Mark goal complete
        goal.status = "completed"
        goal.completed_at = now
        goal.updated_at = now
        await storage.save_goal(goal)

        return LifecyclePrompt(
            prompt_type="goal_complete",
            message=f"Goal '{goal.title}' completed successfully!",
            entity_id=goal.id,
            entity_type="goal",
            entity_title=goal.title,
            choices=[],  # No choices needed - just informational
        )

    async def _handle_postmortem_retry(
        self,
        plan: PlanData,
        goal: GoalData,
        notes: str,
        now: str,
    ) -> LifecyclePrompt:
        """Handle RETRY postmortem outcome.

        Marks plan as completed with notes, prompts for new plan creation.
        """
        storage = await self._get_storage()

        # Mark current plan complete (but not successful)
        plan.status = "completed"
        plan.completed_at = now
        plan.updated_at = now
        plan.postmortem = notes or "Criteria not met - retry needed."
        await storage.save_plan(plan)

        return LifecyclePrompt(
            prompt_type="new_plan_needed",
            message=(
                f"Plan '{plan.title}' did not meet criteria.\n\n"
                f"Create a new plan for goal '{goal.title}'?"
            ),
            entity_id=goal.id,
            entity_type="goal",
            entity_title=goal.title,
            choices=["Create New Plan", "Try Later"],
            suggested_action="Create New Plan",
            related_entities=[
                {"type": "previous_plan", "id": plan.id, "title": plan.title},
            ],
        )

    async def _handle_postmortem_adjust(
        self,
        plan: PlanData,
        goal: GoalData,
        notes: str,
        new_criteria: list[str],
        now: str,
    ) -> LifecyclePrompt:
        """Handle ADJUST postmortem outcome.

        Updates goal's acceptance criteria and prompts for retry.
        """
        storage = await self._get_storage()

        # Mark plan complete with notes
        plan.status = "completed"
        plan.completed_at = now
        plan.updated_at = now
        plan.postmortem = notes or "Criteria adjusted."
        await storage.save_plan(plan)

        # Update goal criteria
        old_criteria = goal.acceptance_criteria.copy()
        goal.acceptance_criteria = new_criteria
        goal.updated_at = now
        await storage.save_goal(goal)

        return LifecyclePrompt(
            prompt_type="criteria_adjusted",
            message=(
                f"Goal '{goal.title}' criteria updated.\n\n"
                f"Old criteria:\n" +
                "\n".join(f"  - {c}" for c in old_criteria) +
                f"\n\nNew criteria:\n" +
                "\n".join(f"  - {c}" for c in new_criteria) +
                "\n\nCreate a new plan with updated criteria?"
            ),
            entity_id=goal.id,
            entity_type="goal",
            entity_title=goal.title,
            choices=["Create New Plan", "Done for Now"],
            suggested_action="Create New Plan",
        )

    async def _handle_postmortem_abandon(
        self,
        plan: PlanData,
        goal: GoalData,
        reason: str,
        now: str,
    ) -> LifecyclePrompt:
        """Handle ABANDON postmortem outcome.

        Marks goal as abandoned with reason.
        """
        storage = await self._get_storage()

        # Mark plan as abandoned
        plan.status = "abandoned"
        plan.updated_at = now
        plan.postmortem = reason or "Goal abandoned."
        await storage.save_plan(plan)

        # Mark goal as abandoned
        goal.status = "abandoned"
        goal.updated_at = now
        await storage.save_goal(goal)

        return LifecyclePrompt(
            prompt_type="goal_abandoned",
            message=f"Goal '{goal.title}' has been abandoned.\n\nReason: {reason}",
            entity_id=goal.id,
            entity_type="goal",
            entity_title=goal.title,
            choices=[],  # Informational only
        )

    # =========================================================================
    # Spike Completion Execution
    # =========================================================================

    async def execute_spike_outcome(
        self,
        spike_id: str,
        outcome: SpikeOutcome,
        session_id: str,
        notes: str = "",
        goal_draft: dict | None = None,
    ) -> LifecyclePrompt | None:
        """Execute the spike completion outcome.

        Args:
            spike_id: The spike being completed
            outcome: The outcome chosen by user
            session_id: The session completing the spike
            notes: Optional notes about the spike results
            goal_draft: For SPAWN_GOAL, draft of the new goal

        Returns:
            LifecyclePrompt for follow-up action, or None if complete
        """
        storage = await self._get_storage()

        spike = await storage.load_todo(spike_id)
        if not spike or not spike.is_spike:
            return None

        now = datetime.now().isoformat()

        if outcome == SpikeOutcome.PROMOTE:
            return await self._handle_spike_promote(spike, notes, now)
        elif outcome == SpikeOutcome.SPAWN_GOAL:
            return await self._handle_spike_spawn_goal(spike, goal_draft, now)
        elif outcome == SpikeOutcome.DISCARD:
            return await self._handle_spike_discard(spike, notes, now)

        return None

    async def _handle_spike_promote(
        self,
        spike: TodoData,
        notes: str,
        now: str,
    ) -> LifecyclePrompt | None:
        """Promote spike to completed todo.

        The spike becomes a regular completed todo.
        """
        storage = await self._get_storage()

        # Convert spike to regular completed todo
        spike.is_spike = False
        spike.status = "completed"
        spike.completed_at = now
        spike.updated_at = now
        spike.description = (
            f"{spike.description}\n\n"
            f"[Promoted from spike]\n{notes}" if notes else spike.description
        )
        spike.timebox_minutes = None
        await storage.save_todo(spike)

        return LifecyclePrompt(
            prompt_type="spike_promoted",
            message=f"Spike promoted to completed todo: '{spike.title}'",
            entity_id=spike.id,
            entity_type="todo",
            entity_title=spike.title,
            choices=[],
        )

    async def _handle_spike_spawn_goal(
        self,
        spike: TodoData,
        goal_draft: dict | None,
        now: str,
    ) -> LifecyclePrompt:
        """Spawn a new goal from spike exploration.

        Creates a draft goal based on what was learned.
        """
        storage = await self._get_storage()

        # Mark spike complete
        spike.status = "completed"
        spike.completed_at = now
        spike.updated_at = now
        await storage.save_todo(spike)

        # If goal_draft provided, create the goal
        if goal_draft:
            import uuid
            new_goal = GoalData(
                id=str(uuid.uuid4()),
                title=goal_draft.get("title", f"Goal from spike: {spike.title}"),
                description=goal_draft.get("description", spike.description),
                weight=goal_draft.get("weight", 5),
                status="active",
                acceptance_criteria=goal_draft.get("acceptance_criteria", []),
                created_at=now,
                updated_at=now,
            )
            await storage.save_goal(new_goal)

            return LifecyclePrompt(
                prompt_type="goal_spawned",
                message=f"New goal created from spike: '{new_goal.title}'",
                entity_id=new_goal.id,
                entity_type="goal",
                entity_title=new_goal.title,
                choices=["Create Plan", "Done for Now"],
                suggested_action="Create Plan",
            )

        # No draft provided - prompt for goal details
        return LifecyclePrompt(
            prompt_type="goal_draft_needed",
            message=(
                f"Spike '{spike.title}' suggests a new direction.\n\n"
                "Describe the new goal:"
            ),
            entity_id=spike.id,
            entity_type="spike",
            entity_title=spike.title,
            choices=["Create Goal", "Cancel"],
            related_entities=[
                {"type": "spike_description", "description": spike.description},
            ],
        )

    async def _handle_spike_discard(
        self,
        spike: TodoData,
        notes: str,
        now: str,
    ) -> LifecyclePrompt | None:
        """Discard spike - mark complete with learnings noted.
        """
        storage = await self._get_storage()

        # Mark spike complete but leave as spike (for record)
        spike.status = "completed"
        spike.completed_at = now
        spike.updated_at = now
        if notes:
            spike.description = f"{spike.description}\n\n[Discarded with learnings]\n{notes}"
        await storage.save_todo(spike)

        return LifecyclePrompt(
            prompt_type="spike_discarded",
            message=f"Spike '{spike.title}' completed and discarded.",
            entity_id=spike.id,
            entity_type="spike",
            entity_title=spike.title,
            choices=[],
        )

    # =========================================================================
    # Binding Release on Completion
    # =========================================================================

    async def release_bindings_for_entity(
        self,
        entity_type: str,
        entity_id: str,
    ) -> int:
        """Release all active bindings for a completed entity.

        When an entity (goal, plan, todo) is completed, its bindings
        should be released so sessions are no longer bound to it.

        Args:
            entity_type: "goal", "plan", or "todo"
            entity_id: The entity ID

        Returns:
            Number of bindings released
        """
        storage = await self._get_storage()

        bindings = await storage.get_bindings_for_entity(
            entity_type, entity_id, active_only=True
        )

        now = datetime.now().isoformat()
        released = 0

        for binding in bindings:
            binding.released_at = now
            await storage.save_session_binding(binding)
            released += 1

        return released


# =============================================================================
# Convenience Functions
# =============================================================================


async def on_todo_complete(
    todo_id: str, session_id: str, completed_by: str = "llm"
) -> LifecyclePrompt | None:
    """Convenience function for todo completion hook."""
    hooks = LifecycleHooks()
    return await hooks.on_todo_complete(todo_id, session_id, completed_by)


async def on_plan_complete(plan_id: str, session_id: str) -> LifecyclePrompt | None:
    """Convenience function for plan completion hook."""
    hooks = LifecycleHooks()
    return await hooks.on_plan_complete(plan_id, session_id)


async def execute_postmortem(
    plan_id: str,
    outcome: PostmortemOutcome,
    session_id: str,
    **kwargs,
) -> LifecyclePrompt | None:
    """Convenience function for postmortem execution."""
    hooks = LifecycleHooks()
    return await hooks.execute_postmortem(plan_id, outcome, session_id, **kwargs)


async def execute_spike_outcome(
    spike_id: str,
    outcome: SpikeOutcome,
    session_id: str,
    **kwargs,
) -> LifecyclePrompt | None:
    """Convenience function for spike outcome execution."""
    hooks = LifecycleHooks()
    return await hooks.execute_spike_outcome(spike_id, outcome, session_id, **kwargs)
