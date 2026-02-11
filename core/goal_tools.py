"""LLM-invocable tools for goal-oriented task management.

These tools allow Claude to create and manage goals, plans, and todos
directly during conversation, enabling self-hosting workflows where
the system tracks its own development.

Tool Names:
- create_goal: Create a new goal with acceptance criteria
- update_goal: Update an existing goal (rename, change weight, etc.)
- create_plan: Create a plan for achieving a goal
- update_plan: Update an existing plan (rename, change status, reparent)
- create_todo: Create a todo and link it to a plan
- list_goals: List all goals with their status
- list_todos: List priority-ranked available todos
- get_todo: Get details of a single todo by ID
- mark_todo_done: Mark a todo as complete
- bind_session: Bind current session to a goal/plan/todo
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from core.async_storage import get_goal_storage
from core.goal_commands import GoalCommandExecutor
from core.lifecycle_hooks import LifecycleHooks
from storage_schema import GoalData, PlanData, TodoData, TodoPlanLink, TodoDependency

if TYPE_CHECKING:
    from session import Session


# Tool names for registration
GOAL_TOOL_NAMES = {
    "create_goal",
    "update_goal",
    "create_plan",
    "update_plan",
    "create_todo",
    "list_goals",
    "list_plans",
    "list_todos",
    "get_todo",
    "mark_todo_done",
    "bind_session",
}


# Tool definitions in OpenAI function format
GOAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_goal",
            "description": """Create a new goal for tracking work.

Goals are high-level objectives with acceptance criteria that define completion.
Each goal has a weight (1-10) indicating priority.

Use this when:
- Starting a new project or feature
- Breaking down a large initiative
- The user describes something they want to accomplish

The goal will be created with 'active' status.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short title for the goal (max 80 chars)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of what the goal aims to achieve"
                    },
                    "weight": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "Priority weight (1=low, 10=critical). Default: 5"
                    },
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of conditions that must be met to consider the goal complete"
                    }
                },
                "required": ["title", "description", "acceptance_criteria"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_goal",
            "description": """Update an existing goal's fields.

Allows modifying a goal's title, description, weight, acceptance criteria, or status.
Only the fields provided will be updated; others remain unchanged.

Use this when:
- Renaming a goal (updating title)
- Refining a goal's description or acceptance criteria
- Adjusting priority (weight)
- Changing status (active/completed/abandoned)""",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {
                        "type": "string",
                        "description": "ID of the goal to update (can be prefix)"
                    },
                    "title": {
                        "type": "string",
                        "description": "New title for the goal (max 80 chars)"
                    },
                    "description": {
                        "type": "string",
                        "description": "New description"
                    },
                    "weight": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "New priority weight (1=low, 10=critical)"
                    },
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New list of acceptance criteria (replaces existing)"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "completed", "abandoned"],
                        "description": "New status"
                    }
                },
                "required": ["goal_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": """Create a plan for achieving a goal.

Plans break down goals into actionable strategies. A goal may have multiple
plans (different approaches), but typically one active plan at a time.

Use this when:
- You've identified an approach to achieve a goal
- Breaking down a goal into phases
- Proposing a strategy for the user to approve""",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {
                        "type": "string",
                        "description": "ID of the parent goal (can be prefix, e.g., first 8 chars)"
                    },
                    "title": {
                        "type": "string",
                        "description": "Short title for the plan (max 80 chars)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Description of the approach/strategy"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["draft", "active"],
                        "description": "Initial status. Default: 'active'"
                    }
                },
                "required": ["goal_id", "title", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_plan",
            "description": """Update an existing plan's fields.

Allows modifying a plan's title, description, status, or parent goal (reparenting).
Only the fields provided will be updated; others remain unchanged.

Use this when:
- Renaming a plan (updating title)
- Refining a plan's description
- Changing status (draft/active/completed/abandoned)
- Moving a plan to a different goal (reparenting)""",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                        "description": "ID of the plan to update (can be prefix)"
                    },
                    "title": {
                        "type": "string",
                        "description": "New title for the plan (max 80 chars)"
                    },
                    "description": {
                        "type": "string",
                        "description": "New description"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["draft", "active", "completed", "abandoned"],
                        "description": "New status"
                    },
                    "goal_id": {
                        "type": "string",
                        "description": "New parent goal ID (can be prefix) - reparents the plan"
                    }
                },
                "required": ["plan_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_todo",
            "description": """Create a todo task linked to a plan.

Todos are concrete tasks that can be completed. They can be regular tasks
or "spikes" (timeboxed exploration). Todos can have dependencies on other todos.

Use this when:
- Breaking down a plan into specific tasks
- Identifying work items
- Creating exploration spikes for uncertain areas""",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                        "description": "ID of the parent plan (can be prefix)"
                    },
                    "title": {
                        "type": "string",
                        "description": "Short title for the todo (max 80 chars)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Details about what needs to be done"
                    },
                    "is_spike": {
                        "type": "boolean",
                        "description": "If true, this is timeboxed exploration. Default: false"
                    },
                    "timebox_minutes": {
                        "type": "integer",
                        "description": "For spikes: maximum time to spend (minutes)"
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of todo IDs this task depends on (can be prefixes)"
                    }
                },
                "required": ["plan_id", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_goals",
            "description": """List all goals with their status and progress.

Returns formatted list of goals sorted by weight, showing:
- Status (active/completed/abandoned)
- Weight
- Title and description
- ID (for reference in other commands)

Use this to see what goals exist and their current state.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_completed": {
                        "type": "boolean",
                        "description": "Include completed/abandoned goals. Default: false"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_plans",
            "description": """List all plans, optionally filtered by goal.

Returns formatted list of plans showing:
- Status (draft/active/completed/abandoned)
- Parent goal
- Title and description
- ID (needed for create_todo)

Use this to find plan IDs when creating todos.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {
                        "type": "string",
                        "description": "Optional: filter to plans for a specific goal (can be prefix)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": """List priority-ranked todos that are available to work on.

Returns todos sorted by priority (goal_weight × completion_factor).
Only shows available todos (dependencies complete, not blocked).
Excludes spikes from priority ranking.

Use this to see what should be worked on next.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                        "description": "Optional: filter to todos for a specific plan (can be prefix)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_todo",
            "description": """Get detailed information about a single todo.

Returns the todo's full details including:
- Title and description
- Status (pending/in_progress/done/abandoned)
- Whether it's a spike (and timebox if set)
- Dependencies (what it depends on)
- Parent plan and goal information

Use this when you need to see the full context of a specific todo,
such as when starting work on it or checking its details.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "string",
                        "description": "ID of the todo to retrieve (can be prefix)"
                    }
                },
                "required": ["todo_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mark_todo_done",
            "description": """Mark a todo as complete.

Triggers lifecycle hooks:
- If all plan todos are done, prompts for postmortem
- If this is a spike, prompts for promote/spawn/discard decision

Use this when a task is finished.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "string",
                        "description": "ID of the todo to complete (can be prefix)"
                    }
                },
                "required": ["todo_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bind_session",
            "description": """Bind the current session to a goal, plan, or todo.

Session binding injects context about the bound entity into the system prompt,
helping keep focus aligned with the intended work.

Roles:
- interview: Gathering requirements, defining acceptance criteria
- planning: Breaking down work, creating plans
- implementation: Writing code, completing todos
- postmortem: Evaluating completed work against criteria
- exploration: Open-ended investigation""",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["goal", "plan", "todo"],
                        "description": "Type of entity to bind to"
                    },
                    "entity_id": {
                        "type": "string",
                        "description": "ID of the entity (can be prefix)"
                    },
                    "role": {
                        "type": "string",
                        "enum": ["interview", "planning", "implementation", "postmortem", "exploration"],
                        "description": "Role for this session. Default: 'implementation'"
                    }
                },
                "required": ["entity_type", "entity_id"]
            }
        }
    },
]


async def execute_goal_tool(
    name: str,
    args: dict,
    session: "Session",
) -> tuple[str, bool]:
    """Execute a goal management tool.

    Args:
        name: Tool name
        args: Tool arguments from the model
        session: Current session (for binding)

    Returns:
        Tuple of (result_string, is_error)
    """
    storage = await get_goal_storage()

    if name == "create_goal":
        return await _create_goal(args, storage)
    elif name == "update_goal":
        return await _update_goal(args, storage)
    elif name == "create_plan":
        return await _create_plan(args, storage)
    elif name == "update_plan":
        return await _update_plan(args, storage)
    elif name == "create_todo":
        return await _create_todo(args, storage)
    elif name == "list_goals":
        return await _list_goals(args, storage)
    elif name == "list_plans":
        return await _list_plans(args, storage)
    elif name == "list_todos":
        return await _list_todos(args, storage)
    elif name == "get_todo":
        return await _get_todo(args, storage)
    elif name == "mark_todo_done":
        return await _mark_todo_done(args, storage, session)
    elif name == "bind_session":
        return await _bind_session(args, storage, session)
    else:
        return f"Unknown goal tool: {name}", True


async def _create_goal(args: dict, storage) -> tuple[str, bool]:
    """Create a new goal."""
    title = args.get("title", "").strip()
    if not title:
        return "Error: title is required", True

    description = args.get("description", "").strip()
    if not description:
        return "Error: description is required", True

    acceptance_criteria = args.get("acceptance_criteria", [])
    if not acceptance_criteria:
        return "Error: acceptance_criteria is required (list of strings)", True

    weight = args.get("weight", 5)
    if not 1 <= weight <= 10:
        weight = max(1, min(10, weight))

    now = datetime.now().isoformat()
    goal = GoalData(
        id=str(uuid.uuid4()),
        title=title[:80],
        description=description,
        weight=weight,
        status="active",
        acceptance_criteria=acceptance_criteria,
        created_at=now,
        updated_at=now,
    )

    await storage.save_goal(goal)

    criteria_str = "\n".join(f"  - {c}" for c in acceptance_criteria)
    return (
        f"Created goal: {goal.title}\n"
        f"ID: {goal.id}\n"
        f"Weight: {goal.weight}/10\n"
        f"Acceptance Criteria:\n{criteria_str}"
    ), False


async def _update_goal(args: dict, storage) -> tuple[str, bool]:
    """Update an existing goal."""
    goal_id_prefix = args.get("goal_id", "").strip()
    if not goal_id_prefix:
        return "Error: goal_id is required", True

    # Find goal by prefix
    goals = await storage.list_goals()
    goal = None
    for g in goals:
        if g.id.startswith(goal_id_prefix):
            goal = g
            break

    if not goal:
        return f"Error: Goal not found: {goal_id_prefix}", True

    # Track what we're updating for the response
    updates = []

    # Update title if provided
    if "title" in args:
        new_title = args["title"].strip()
        if new_title:
            old_title = goal.title
            goal.title = new_title[:80]
            updates.append(f"title: '{old_title}' → '{goal.title}'")

    # Update description if provided
    if "description" in args:
        new_desc = args["description"].strip()
        if new_desc:
            goal.description = new_desc
            updates.append("description updated")

    # Update weight if provided
    if "weight" in args:
        new_weight = args["weight"]
        if isinstance(new_weight, int) and 1 <= new_weight <= 10:
            old_weight = goal.weight
            goal.weight = new_weight
            updates.append(f"weight: {old_weight} → {new_weight}")

    # Update acceptance_criteria if provided
    if "acceptance_criteria" in args:
        new_criteria = args["acceptance_criteria"]
        if isinstance(new_criteria, list) and new_criteria:
            goal.acceptance_criteria = new_criteria
            updates.append(f"acceptance criteria updated ({len(new_criteria)} items)")

    # Update status if provided
    if "status" in args:
        new_status = args["status"]
        if new_status in ("active", "completed", "abandoned"):
            old_status = goal.status
            goal.status = new_status
            updates.append(f"status: {old_status} → {new_status}")

    if not updates:
        return "No valid updates provided", True

    # Update the timestamp
    goal.updated_at = datetime.now().isoformat()

    # Save the updated goal
    await storage.save_goal(goal)

    return (
        f"Updated goal: {goal.title}\n"
        f"ID: {goal.id}\n"
        f"Changes:\n" + "\n".join(f"  - {u}" for u in updates)
    ), False


async def _create_plan(args: dict, storage) -> tuple[str, bool]:
    """Create a plan for a goal."""
    goal_id_prefix = args.get("goal_id", "").strip()
    if not goal_id_prefix:
        return "Error: goal_id is required", True

    # Find goal by prefix
    goals = await storage.list_goals()
    goal = None
    for g in goals:
        if g.id.startswith(goal_id_prefix):
            goal = g
            break

    if not goal:
        return f"Error: Goal not found: {goal_id_prefix}", True

    title = args.get("title", "").strip()
    if not title:
        return "Error: title is required", True

    description = args.get("description", "").strip()
    status = args.get("status", "active")
    if status not in ("draft", "active"):
        status = "active"

    now = datetime.now().isoformat()
    plan = PlanData(
        id=str(uuid.uuid4()),
        goal_id=goal.id,
        title=title[:80],
        description=description,
        status=status,
        created_at=now,
        updated_at=now,
    )

    await storage.save_plan(plan)

    return (
        f"Created plan: {plan.title}\n"
        f"ID: {plan.id}\n"
        f"Status: {plan.status}\n"
        f"Goal: {goal.title}"
    ), False


async def _update_plan(args: dict, storage) -> tuple[str, bool]:
    """Update an existing plan."""
    plan_id_prefix = args.get("plan_id", "").strip()
    if not plan_id_prefix:
        return "Error: plan_id is required", True

    # Find plan by prefix
    plans = await storage.list_plans()
    plan = None
    for p in plans:
        if p.id.startswith(plan_id_prefix):
            plan = p
            break

    if not plan:
        return f"Error: Plan not found: {plan_id_prefix}", True

    # Track what we're updating for the response
    updates = []

    # Update title if provided
    if "title" in args:
        new_title = args["title"].strip()
        if new_title:
            old_title = plan.title
            plan.title = new_title[:80]
            updates.append(f"title: '{old_title}' → '{plan.title}'")

    # Update description if provided
    if "description" in args:
        new_desc = args["description"].strip()
        if new_desc:
            plan.description = new_desc
            updates.append("description updated")

    # Update status if provided
    if "status" in args:
        new_status = args["status"]
        if new_status in ("draft", "active", "completed", "abandoned"):
            old_status = plan.status
            plan.status = new_status
            updates.append(f"status: {old_status} → {new_status}")

    # Reparent to different goal if goal_id provided
    if "goal_id" in args:
        new_goal_id_prefix = args["goal_id"].strip()
        if new_goal_id_prefix:
            # Find new goal by prefix
            goals = await storage.list_goals()
            new_goal = None
            for g in goals:
                if g.id.startswith(new_goal_id_prefix):
                    new_goal = g
                    break

            if not new_goal:
                return f"Error: Goal not found for reparenting: {new_goal_id_prefix}", True

            # Get old goal for display
            old_goal = await storage.load_goal(plan.goal_id)
            old_goal_title = old_goal.title if old_goal else plan.goal_id[:8]

            plan.goal_id = new_goal.id
            updates.append(f"goal: '{old_goal_title}' → '{new_goal.title}'")

    if not updates:
        return "No valid updates provided", True

    # Update the timestamp
    plan.updated_at = datetime.now().isoformat()

    # Save the updated plan
    await storage.save_plan(plan)

    # Get current goal for display
    current_goal = await storage.load_goal(plan.goal_id)
    goal_title = current_goal.title if current_goal else plan.goal_id[:8]

    return (
        f"Updated plan: {plan.title}\n"
        f"ID: {plan.id}\n"
        f"Goal: {goal_title}\n"
        f"Changes:\n" + "\n".join(f"  - {u}" for u in updates)
    ), False


async def _create_todo(args: dict, storage) -> tuple[str, bool]:
    """Create a todo linked to a plan."""
    plan_id_prefix = args.get("plan_id", "").strip()
    if not plan_id_prefix:
        return "Error: plan_id is required", True

    # Find plan by prefix
    plans = await storage.list_plans()
    plan = None
    for p in plans:
        if p.id.startswith(plan_id_prefix):
            plan = p
            break

    if not plan:
        return f"Error: Plan not found: {plan_id_prefix}", True

    title = args.get("title", "").strip()
    if not title:
        return "Error: title is required", True

    description = args.get("description", "").strip()
    is_spike = args.get("is_spike", False)
    timebox_minutes = args.get("timebox_minutes")

    now = datetime.now().isoformat()
    todo = TodoData(
        id=str(uuid.uuid4()),
        title=title[:80],
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
        plan_id=plan.id,
        created_at=now,
    )
    await storage.save_todo_plan_link(link)

    # Handle dependencies
    depends_on = args.get("depends_on", [])
    all_todos = await storage.list_todos(include_spikes=True)
    deps_added = []

    for dep_prefix in depends_on:
        for t in all_todos:
            if t.id.startswith(dep_prefix):
                dep = TodoDependency(
                    todo_id=todo.id,
                    depends_on_id=t.id,
                    created_at=now,
                )
                await storage.save_todo_dependency(dep)
                deps_added.append(t.title)
                break

    result = f"Created todo: {todo.title}\nID: {todo.id}\nPlan: {plan.title}"
    if is_spike:
        result += f"\nType: Spike"
        if timebox_minutes:
            result += f" ({timebox_minutes} min)"
    if deps_added:
        result += f"\nDepends on: {', '.join(deps_added)}"

    return result, False


async def _list_goals(args: dict, storage) -> tuple[str, bool]:
    """List goals."""
    include_completed = args.get("include_completed", False)
    executor = GoalCommandExecutor(storage)
    result = await executor.list_goals(include_completed)

    if result.success:
        # Strip Rich markup for tool output
        formatted = result.formatted
        formatted = formatted.replace("[bold cyan]", "").replace("[/bold cyan]", "")
        formatted = formatted.replace("[bold]", "").replace("[/bold]", "")
        formatted = formatted.replace("[dim]", "").replace("[/dim]", "")
        formatted = formatted.replace("[green]●[/green]", "●")
        formatted = formatted.replace("[blue]✓[/blue]", "✓")
        formatted = formatted.replace("[yellow]→[/yellow]", "→")
        formatted = formatted.replace("[red]✗[/red]", "✗")
        return formatted, False
    else:
        return f"Error: {result.error}", True


async def _list_plans(args: dict, storage) -> tuple[str, bool]:
    """List plans."""
    goal_id = args.get("goal_id", "")
    executor = GoalCommandExecutor(storage)
    result = await executor.list_plans(goal_id)

    if result.success:
        # Strip Rich markup for tool output
        formatted = result.formatted
        formatted = formatted.replace("[bold cyan]", "").replace("[/bold cyan]", "")
        formatted = formatted.replace("[bold]", "").replace("[/bold]", "")
        formatted = formatted.replace("[dim]", "").replace("[/dim]", "")
        formatted = formatted.replace("[green]●[/green]", "●")
        formatted = formatted.replace("[blue]✓[/blue]", "✓")
        formatted = formatted.replace("[yellow]→[/yellow]", "→")
        formatted = formatted.replace("[red]✗[/red]", "✗")
        return formatted, False
    else:
        return f"Error: {result.error}", True


async def _list_todos(args: dict, storage) -> tuple[str, bool]:
    """List priority-ranked todos."""
    plan_id = args.get("plan_id", "")
    executor = GoalCommandExecutor(storage)
    result = await executor.list_todos(plan_id)

    if result.success:
        # Strip Rich markup for tool output
        formatted = result.formatted
        formatted = formatted.replace("[bold cyan]", "").replace("[/bold cyan]", "")
        formatted = formatted.replace("[bold]", "").replace("[/bold]", "")
        formatted = formatted.replace("[dim]", "").replace("[/dim]", "")
        formatted = formatted.replace("[yellow]○[/yellow]", "○")
        formatted = formatted.replace("[cyan]◐[/cyan]", "◐")
        formatted = formatted.replace("[green]✓[/green]", "✓")
        formatted = formatted.replace("[red]⊘[/red]", "⊘")
        formatted = formatted.replace("[yellow]", "").replace("[/yellow]", "")
        formatted = formatted.replace("[magenta]", "").replace("[/magenta]", "")
        return formatted, False
    else:
        return f"Error: {result.error}", True


async def _get_todo(args: dict, storage) -> tuple[str, bool]:
    """Get detailed information about a single todo."""
    todo_id_prefix = args.get("todo_id", "").strip()
    if not todo_id_prefix:
        return "Error: todo_id is required", True

    # Find todo by prefix
    all_todos = await storage.list_todos(include_spikes=True)
    todo = None
    for t in all_todos:
        if t.id.startswith(todo_id_prefix):
            todo = t
            break

    if not todo:
        return f"Error: Todo not found: {todo_id_prefix}", True

    # Build response
    lines = [
        f"Todo: {todo.title}",
        f"ID: {todo.id}",
        f"Status: {todo.status}",
    ]

    if todo.description:
        lines.append(f"Description: {todo.description}")

    if todo.is_spike:
        spike_info = "Type: Spike"
        if todo.timebox_minutes:
            spike_info += f" ({todo.timebox_minutes} min timebox)"
        lines.append(spike_info)

    # Get parent plan and goal info
    plan_ids = await storage.get_plans_for_todo(todo.id)
    if plan_ids:
        plan = await storage.load_plan(plan_ids[0])
        if plan:
            lines.append(f"Plan: {plan.title} ({plan.id[:8]})")
            goal = await storage.load_goal(plan.goal_id)
            if goal:
                lines.append(f"Goal: {goal.title} (weight: {goal.weight}/10)")

    # Get dependencies
    dep_ids = await storage.get_dependencies(todo.id)
    if dep_ids:
        dep_names = []
        for dep_id in dep_ids:
            dep_todo = await storage.load_todo(dep_id)
            if dep_todo:
                status_icon = "✓" if dep_todo.status == "done" else "○"
                dep_names.append(f"{status_icon} {dep_todo.title} ({dep_id[:8]})")
        if dep_names:
            lines.append("Dependencies:")
            for dep in dep_names:
                lines.append(f"  - {dep}")

    lines.append(f"Created: {todo.created_at}")
    if todo.updated_at != todo.created_at:
        lines.append(f"Updated: {todo.updated_at}")

    return "\n".join(lines), False


async def _mark_todo_done(args: dict, storage, session) -> tuple[str, bool]:
    """Mark a todo as complete."""
    todo_id = args.get("todo_id", "").strip()
    if not todo_id:
        return "Error: todo_id is required", True

    executor = GoalCommandExecutor(storage)
    result = await executor.mark_todo_done(todo_id, session.id)

    if result.success:
        response = f"Marked complete: {result.todo.title}"
        if result.lifecycle_prompt:
            response += f"\n\nLifecycle prompt: {result.lifecycle_prompt.prompt_type}"
            response += f"\n{result.lifecycle_prompt.message}"
            if result.lifecycle_prompt.choices:
                response += f"\nOptions: {', '.join(result.lifecycle_prompt.choices)}"
        return response, False
    else:
        return f"Error: {result.error}", True


async def _bind_session(args: dict, storage, session) -> tuple[str, bool]:
    """Bind session to an entity."""
    entity_type = args.get("entity_type", "").strip()
    if entity_type not in ("goal", "plan", "todo"):
        return "Error: entity_type must be 'goal', 'plan', or 'todo'", True

    entity_id = args.get("entity_id", "").strip()
    if not entity_id:
        return "Error: entity_id is required", True

    role = args.get("role", "implementation")
    valid_roles = ("interview", "planning", "implementation", "postmortem", "exploration")
    if role not in valid_roles:
        role = "implementation"

    executor = GoalCommandExecutor(storage)
    result = await executor.bind_session(session.id, entity_type, entity_id, role)

    if result.success:
        return f"Session bound to {entity_type} with role: {role}", False
    else:
        return f"Error: {result.error}", True
