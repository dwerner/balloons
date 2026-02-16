"""LLM-assisted todo placement.

Provides functionality for automatically placing todos under the appropriate plan
based on the todo's title and description, using an LLM to determine the best match.
"""

import uuid
from datetime import datetime
from typing import Optional

from storage_schema import TodoData, PlanData, GoalData, TodoPlanLink
from core.async_storage import get_goal_storage


# Prompt template for LLM plan matching
PLAN_MATCHING_PROMPT = """You are helping to organize a todo item by placing it under the most appropriate plan.

Here are the available goals and their plans:

{goals_and_plans}

The user wants to create a todo with:
- Title: {todo_title}
- Description: {todo_description}

Based on the todo's content, which plan should it be placed under? Consider:
1. How closely the todo relates to each plan's purpose
2. The goal context that each plan belongs to
3. If no plan is a good fit, you should indicate that

Respond with ONLY the plan_id that best matches, or "NONE" if no plan is appropriate.
Do not include any explanation - just the plan_id or "NONE".

Plan ID:"""


async def get_plans_summary_for_llm() -> tuple[str, dict[str, PlanData], dict[str, GoalData]]:
    """Get a formatted summary of all plans for LLM consumption.

    Returns:
        Tuple of:
        - Formatted string describing goals and plans
        - Dict mapping plan_id to PlanData
        - Dict mapping goal_id to GoalData
    """
    storage = await get_goal_storage()

    goals = await storage.list_goals()
    plans = await storage.list_plans()

    # Filter to only active goals and plans
    active_goals = [g for g in goals if g.status == "active"]
    active_plans = [p for p in plans if p.status in ("active", "draft")]

    if not active_plans:
        return "", {}, {}

    # Build lookup dicts
    plans_by_id = {p.id: p for p in active_plans}
    goals_by_id = {g.id: g for g in goals}  # Include all goals for hierarchy lookup

    # Group plans by goal
    plans_by_goal: dict[str, list[PlanData]] = {}
    for plan in active_plans:
        if plan.goal_id not in plans_by_goal:
            plans_by_goal[plan.goal_id] = []
        plans_by_goal[plan.goal_id].append(plan)

    # Build formatted output
    lines = []
    for goal in active_goals:
        if goal.id not in plans_by_goal:
            continue

        lines.append(f"## Goal: {goal.title}")
        if goal.description:
            lines.append(f"   Description: {goal.description[:200]}")
        lines.append(f"   Status: {goal.status}")
        lines.append("")
        lines.append("   Plans:")

        for plan in plans_by_goal[goal.id]:
            lines.append(f"   - plan_id: {plan.id}")
            lines.append(f"     Title: {plan.title}")
            if plan.description:
                lines.append(f"     Description: {plan.description[:150]}")
            lines.append("")

    return "\n".join(lines), plans_by_id, goals_by_id


async def create_todo_with_llm_placement(
    title: str,
    description: str = "",
    is_spike: bool = False,
    timebox_minutes: Optional[int] = None,
    llm_runner=None,
) -> tuple[TodoData | None, PlanData | None, str]:
    """Create a todo and use LLM to determine the best plan placement.

    Args:
        title: Todo title (required)
        description: Todo description (optional)
        is_spike: Whether this is a timeboxed exploration task
        timebox_minutes: For spikes, the maximum time to spend
        llm_runner: A runner implementing stream_response for LLM calls.
                   If None, returns an error.

    Returns:
        Tuple of:
        - TodoData if created, None if failed
        - PlanData the todo was linked to, None if no match
        - Message describing what happened
    """
    from models import TextDelta

    if not title.strip():
        return None, None, "Error: title is required"

    title = title.strip()[:80]
    description = description.strip() if description else ""

    # Get plans summary
    plans_summary, plans_by_id, goals_by_id = await get_plans_summary_for_llm()

    if not plans_summary:
        return None, None, "Error: No active plans found. Create a plan first."

    if llm_runner is None:
        return None, None, "Error: LLM runner not available"

    # Build prompt
    prompt = PLAN_MATCHING_PROMPT.format(
        goals_and_plans=plans_summary,
        todo_title=title,
        todo_description=description or "(no description)",
    )

    # Call LLM to get plan match
    response_parts = []
    try:
        async for event in llm_runner.stream_response([], prompt, disable_tools=True):
            if isinstance(event, TextDelta):
                response_parts.append(event.text)
    except Exception as e:
        return None, None, f"Error: LLM call failed: {e}"

    response = "".join(response_parts).strip()

    # Parse response - should be a plan_id or "NONE"
    # Clean up response (remove quotes, whitespace, etc.)
    cleaned_response = response.replace('"', '').replace("'", "").strip()

    if cleaned_response.upper() == "NONE" or not cleaned_response:
        return None, None, (
            "No matching plan found for this todo. "
            "Please create a plan first or specify a plan manually."
        )

    # Try to find the plan
    matched_plan = None

    # First try exact match
    if cleaned_response in plans_by_id:
        matched_plan = plans_by_id[cleaned_response]
    else:
        # Try prefix match (LLM might have truncated)
        for plan_id, plan in plans_by_id.items():
            if plan_id.startswith(cleaned_response) or cleaned_response.startswith(plan_id[:8]):
                matched_plan = plan
                break

    if not matched_plan:
        return None, None, (
            f"LLM suggested plan '{cleaned_response}' but it was not found. "
            "Please specify a plan manually."
        )

    # Create the todo
    storage = await get_goal_storage()
    now = datetime.now().isoformat()

    todo = TodoData(
        id=str(uuid.uuid4()),
        title=title,
        description=description,
        status="pending",
        is_spike=is_spike,
        timebox_minutes=timebox_minutes if is_spike else None,
        created_at=now,
        updated_at=now,
    )

    await storage.save_todo(todo)

    # Link to plan
    link = TodoPlanLink(
        todo_id=todo.id,
        plan_id=matched_plan.id,
        created_at=now,
    )
    await storage.save_todo_plan_link(link)

    # Get goal for the message
    goal = goals_by_id.get(matched_plan.goal_id)
    goal_title = goal.title if goal else "Unknown goal"

    result_msg = (
        f"Created todo: {todo.title}\n"
        f"ID: {todo.id}\n"
        f"Plan: {matched_plan.title}\n"
        f"Goal: {goal_title}"
    )

    if is_spike:
        result_msg += f"\nType: Spike"
        if timebox_minutes:
            result_msg += f" ({timebox_minutes} min)"

    return todo, matched_plan, result_msg


async def suggest_plan_for_todo(
    title: str,
    description: str = "",
    llm_runner=None,
) -> tuple[PlanData | None, GoalData | None, str]:
    """Suggest the best plan for a todo without creating it.

    Useful for previewing where a todo would be placed.

    Args:
        title: Todo title
        description: Todo description
        llm_runner: A runner implementing stream_response for LLM calls

    Returns:
        Tuple of:
        - Suggested PlanData, or None if no match
        - Parent GoalData, or None
        - Message describing the suggestion
    """
    from models import TextDelta

    if not title.strip():
        return None, None, "Error: title is required"

    title = title.strip()
    description = description.strip() if description else ""

    # Get plans summary
    plans_summary, plans_by_id, goals_by_id = await get_plans_summary_for_llm()

    if not plans_summary:
        return None, None, "No active plans found"

    if llm_runner is None:
        return None, None, "LLM runner not available"

    # Build prompt
    prompt = PLAN_MATCHING_PROMPT.format(
        goals_and_plans=plans_summary,
        todo_title=title,
        todo_description=description or "(no description)",
    )

    # Call LLM
    response_parts = []
    try:
        async for event in llm_runner.stream_response([], prompt, disable_tools=True):
            if isinstance(event, TextDelta):
                response_parts.append(event.text)
    except Exception as e:
        return None, None, f"LLM call failed: {e}"

    response = "".join(response_parts).strip()
    cleaned_response = response.replace('"', '').replace("'", "").strip()

    if cleaned_response.upper() == "NONE" or not cleaned_response:
        return None, None, "No matching plan found"

    # Find the plan
    matched_plan = None
    if cleaned_response in plans_by_id:
        matched_plan = plans_by_id[cleaned_response]
    else:
        for plan_id, plan in plans_by_id.items():
            if plan_id.startswith(cleaned_response) or cleaned_response.startswith(plan_id[:8]):
                matched_plan = plan
                break

    if not matched_plan:
        return None, None, f"Plan '{cleaned_response}' not found"

    goal = goals_by_id.get(matched_plan.goal_id)

    return matched_plan, goal, f"Suggested plan: {matched_plan.title}"
