"""Build context from session bindings for system prompt injection.

When a session is bound to goals, plans, or todos, this module builds
a formatted context string that can be added to the system prompt to
keep the LLM aligned with the intended work.

Role-specific guidance is loaded from prompts/shared/roles/{role}.md files,
which are the single source of truth for role behavior.
"""

from pathlib import Path
from typing import Optional

from core.async_storage import GoalStorage, get_goal_storage
from storage_schema import GoalData, PlanData, TodoData, SessionBinding


# Cache for loaded role guidance files
_role_guidance_cache: dict[str, str] = {}


# Completion guidance templates based on whether we're in a fork
_COMPLETION_IN_FORK = """
### Session Completion (Fork)
This session is a **fork** with a parent session. When work is complete:
- Propose a merge back to parent with a summary of what was accomplished
- Use `propose_merge` tool with summary, files_changed, and key_accomplishments
"""

_COMPLETION_NOT_IN_FORK = """
### Session Completion (Standalone)
This session is **not a fork** - it's a standalone session bound to a task.
When work is complete:
- **Do NOT propose a merge** (there's no parent to merge to)
- Instead, let the user know the task is complete and summarize what was done
- Mark the todo as done using `mark_todo_done` if appropriate
- The user can close this session and return to their main workflow
"""


def _get_prompts_dir() -> Path:
    """Get the prompts directory path."""
    # Navigate from core/ to project root, then to prompts/
    return Path(__file__).parent.parent / "prompts" / "shared" / "roles"


def _load_role_guidance(role: str) -> str:
    """Load role guidance from the corresponding prompt file.

    Args:
        role: The role name (interview, planning, implementation, etc.)

    Returns:
        The role guidance content, or empty string if file doesn't exist
    """
    if role in _role_guidance_cache:
        return _role_guidance_cache[role]

    role_file = _get_prompts_dir() / f"{role}.md"
    if role_file.exists():
        content = role_file.read_text()
        _role_guidance_cache[role] = content
        return content

    return ""


class BindingContextBuilder:
    """Builds context from session bindings for system prompt.

    Usage:
        builder = BindingContextBuilder()
        context = await builder.build_binding_context("session-123")
        if context:
            system_prompt = f"{base_prompt}\n\n{context}"
    """

    def __init__(self, goal_storage: GoalStorage | None = None):
        """Initialize the builder.

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

    async def build_binding_context(self, session_id: str, is_fork: bool = False) -> str:
        """Build context string from session's active bindings.

        Loads all active (non-released) bindings for the session and
        formats the bound entities into a context block suitable for
        system prompt injection. Includes role-specific behavioral guidance
        for each unique role in the bindings.

        Args:
            session_id: The session to build context for
            is_fork: Whether this session has a parent (is a fork)

        Returns:
            Formatted context string, or empty string if no bindings
        """
        storage = await self._get_storage()
        bindings = await storage.get_bindings_for_session(session_id, active_only=True)

        if not bindings:
            return ""

        parts = ["## Session Bindings", ""]
        parts.append("This session is bound to the following work items. Stay aligned with these goals:")
        parts.append("")

        # Format each binding
        for binding in bindings:
            entity_context = await self._format_binding(binding, storage)
            if entity_context:
                parts.append(entity_context)

        # Add role-specific guidance (once per unique role)
        seen_roles: set[str] = set()
        guidance_parts: list[str] = []
        for binding in bindings:
            if binding.role not in seen_roles:
                seen_roles.add(binding.role)
                guidance = self._get_role_guidance(binding.role)
                if guidance:
                    guidance_parts.append(guidance)

        if guidance_parts:
            parts.append("---")
            parts.append("")
            for guidance in guidance_parts:
                parts.append(guidance)
                parts.append("")

        # Add completion guidance based on fork status
        # Only add for roles that have completion workflows
        completion_roles = {"implementation", "planning", "exploration", "postmortem"}
        if seen_roles & completion_roles:
            if is_fork:
                parts.append(_COMPLETION_IN_FORK)
            else:
                parts.append(_COMPLETION_NOT_IN_FORK)
            parts.append("")

        return "\n".join(parts)

    def _get_role_guidance(self, role: str) -> str:
        """Get behavioral guidance for a session role.

        Loads guidance from prompts/shared/roles/{role}.md file.

        Args:
            role: The binding role (interview, planning, implementation, etc.)

        Returns:
            Guidance string for the role, or empty string if file doesn't exist
        """
        return _load_role_guidance(role)

    async def _format_binding(self, binding: SessionBinding, storage: GoalStorage) -> str:
        """Format a single binding for display.

        Args:
            binding: The binding to format
            storage: GoalStorage for loading entities

        Returns:
            Formatted string for this binding, or empty string on error
        """
        if binding.entity_type == "goal":
            return await self._format_goal_binding(binding, storage)
        elif binding.entity_type == "plan":
            return await self._format_plan_binding(binding, storage)
        elif binding.entity_type == "todo":
            return await self._format_todo_binding(binding, storage)
        return ""

    async def _format_goal_binding(self, binding: SessionBinding, storage: GoalStorage) -> str:
        """Format a goal binding."""
        goal = await storage.load_goal(binding.entity_id)
        if not goal:
            return ""

        lines = [
            f"### Goal (role: {binding.role})",
            f"**{goal.title}** (weight: {goal.weight}/10)",
            "",
        ]

        if goal.description:
            lines.append(goal.description)
            lines.append("")

        if goal.acceptance_criteria:
            lines.append("**Acceptance Criteria:**")
            for criterion in goal.acceptance_criteria:
                lines.append(f"- {criterion}")
            lines.append("")

        return "\n".join(lines)

    async def _format_plan_binding(self, binding: SessionBinding, storage: GoalStorage) -> str:
        """Format a plan binding."""
        plan = await storage.load_plan(binding.entity_id)
        if not plan:
            return ""

        lines = [
            f"### Plan (role: {binding.role})",
            f"**{plan.title}**",
            "",
        ]

        if plan.description:
            lines.append(plan.description)
            lines.append("")

        # Also show the parent goal for context
        if plan.goal_id:
            goal = await storage.load_goal(plan.goal_id)
            if goal:
                lines.append(f"*Part of goal: {goal.title}*")
                lines.append("")

        return "\n".join(lines)

    async def _format_todo_binding(self, binding: SessionBinding, storage: GoalStorage) -> str:
        """Format a todo binding."""
        todo = await storage.load_todo(binding.entity_id)
        if not todo:
            return ""

        lines = [
            f"### Todo (role: {binding.role})",
            f"**{todo.title}**",
            "",
        ]

        if todo.description:
            lines.append(todo.description)
            lines.append("")

        if todo.is_spike:
            timebox = f" ({todo.timebox_minutes} min)" if todo.timebox_minutes else ""
            lines.append(f"*This is a spike{timebox} - timeboxed exploration exempt from priority.*")
            lines.append("")

        return "\n".join(lines)


async def build_binding_context_for_session(session_id: str, is_fork: bool = False) -> str:
    """Convenience function to build binding context for a session.

    Args:
        session_id: The session to build context for
        is_fork: Whether this session has a parent (is a fork)

    Returns:
        Formatted context string, or empty string if no bindings
    """
    builder = BindingContextBuilder()
    return await builder.build_binding_context(session_id, is_fork=is_fork)
