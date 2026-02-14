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
- update_todo: Update an existing todo (rename, change status, reparent, etc.)
- delete_todo: Permanently delete a todo
- split_todo: Split a todo into multiple smaller todos
- merge_todos: Merge multiple todos into a single todo
- list_goals: List all goals with their status
- list_plans: List all plans
- list_todos: List priority-ranked available todos
- get_todo: Get details of a single todo by ID
- get_hierarchy: Get the complete hierarchy for any entity
- mark_todo_done: Mark a todo as complete
- bind_session: Bind current session to a goal/plan/todo
- list_all_bindings: List all session bindings with filtering
- rebind_session: Rebind any session to a different entity
- bind_entity_to_sessions: Bulk bind an entity to multiple sessions
- unbind_sessions: Bulk unbind sessions or cleanup orphans
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from core.async_storage import get_goal_storage, AsyncStorage
from core.goal_commands import GoalCommandExecutor
from core.lifecycle_hooks import LifecycleHooks
from storage_schema import GoalData, PlanData, TodoData, TodoPlanLink, TodoDependency, SessionBinding

if TYPE_CHECKING:
    from session import Session


# Tool names for registration
GOAL_TOOL_NAMES = {
    "create_goal",
    "update_goal",
    "reparent_goal",
    "create_plan",
    "update_plan",
    "create_todo",
    "update_todo",
    "delete_todo",
    "split_todo",
    "merge_todos",
    "list_goals",
    "list_plans",
    "list_todos",
    "get_todo",
    "get_hierarchy",
    "mark_todo_done",
    "bind_session",
    "list_all_bindings",
    "rebind_session",
    "bind_entity_to_sessions",
    "unbind_sessions",
    "begin_streaming_todo",
}

# Tools that mutate goal data and require UI refresh
GOAL_MUTATION_TOOLS = {
    "create_goal",
    "update_goal",
    "reparent_goal",
    "create_plan",
    "update_plan",
    "create_todo",
    "update_todo",
    "delete_todo",
    "split_todo",
    "merge_todos",
    "mark_todo_done",
    "bind_session",
    "rebind_session",
    "bind_entity_to_sessions",
    "unbind_sessions",
}


# Tool definitions in OpenAI function format
GOAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_goal",
            "description": """Create a new goal for tracking work.

Goals are high-level objectives with acceptance criteria that define completion.
Each goal has a weight (1-10) indicating priority. Goals can be nested under
parent goals to create a hierarchy.

Use this when:
- Starting a new project or feature
- Breaking down a large initiative
- The user describes something they want to accomplish
- Creating a sub-goal under an existing goal

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
                    },
                    "parent_goal_id": {
                        "type": "string",
                        "description": "Optional: ID of a parent goal to nest this goal under (can be prefix)"
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
            "name": "reparent_goal",
            "description": """Move a goal under a different parent goal or make it a root-level goal.

Goals can be nested under other goals to create a hierarchy. A child goal's
completion contributes to its parent's progress. This tool lets you reorganize
the goal hierarchy.

Use this when:
- Organizing goals into a hierarchy
- Moving a goal to become a child of another goal
- Making a nested goal into a root-level goal (unparenting)

Note: Cannot create circular references (goal cannot be its own ancestor).""",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {
                        "type": "string",
                        "description": "ID of the goal to reparent (can be prefix)"
                    },
                    "parent_goal_id": {
                        "type": "string",
                        "description": "ID of the new parent goal (can be prefix). Use null or empty string to make it a root-level goal."
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
            "name": "update_todo",
            "description": """Update an existing todo's fields.

Allows modifying a todo's title, description, status, is_spike, timebox_minutes, or parent plan (reparenting).
Only the fields provided will be updated; others remain unchanged.

Use this when:
- Renaming a todo (updating title)
- Refining a todo's description
- Changing status (pending/in_progress/done/abandoned)
- Converting a regular todo to a spike (or vice versa)
- Adjusting a spike's timebox
- Moving a todo to a different plan (reparenting)""",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "string",
                        "description": "ID of the todo to update (can be prefix)"
                    },
                    "title": {
                        "type": "string",
                        "description": "New title for the todo (max 80 chars)"
                    },
                    "description": {
                        "type": "string",
                        "description": "New description"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "done", "abandoned"],
                        "description": "New status"
                    },
                    "is_spike": {
                        "type": "boolean",
                        "description": "Whether this is a timeboxed exploration task"
                    },
                    "timebox_minutes": {
                        "type": "integer",
                        "description": "For spikes: maximum time to spend (minutes). Set to null to remove timebox."
                    },
                    "plan_id": {
                        "type": "string",
                        "description": "New parent plan ID (can be prefix) - reparents the todo"
                    }
                },
                "required": ["todo_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_todo",
            "description": """Permanently delete a todo.

Removes the todo, its plan links, dependencies, and any session bindings.
This action cannot be undone.

Use this when:
- A todo was created by mistake
- A todo is no longer relevant and should be removed (not just abandoned)
- Cleaning up duplicate todos

Note: Consider using update_todo with status='abandoned' if you want to
preserve the todo for historical reference instead of permanently deleting it.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "string",
                        "description": "ID of the todo to delete (can be prefix)"
                    }
                },
                "required": ["todo_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "split_todo",
            "description": """Split a todo into multiple smaller todos.

Takes an existing todo and breaks it into multiple new todos. The original
todo is marked as abandoned with a note indicating it was split. The new
todos inherit the original's plan linkage and can optionally depend on
each other in sequence.

Use this when:
- A todo turns out to be larger than expected
- You want to break down a complex task into subtasks
- A todo covers multiple distinct pieces of work

Returns the IDs of the newly created todos.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "string",
                        "description": "ID of the todo to split (can be prefix)"
                    },
                    "new_todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "Title for the new todo (max 80 chars)"
                                },
                                "description": {
                                    "type": "string",
                                    "description": "Description for the new todo"
                                }
                            },
                            "required": ["title"]
                        },
                        "description": "List of new todo specifications to create"
                    },
                    "chain_dependencies": {
                        "type": "boolean",
                        "description": "If true, each todo depends on the previous one (creates a sequence). Default: false"
                    }
                },
                "required": ["todo_id", "new_todos"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "merge_todos",
            "description": """Merge multiple todos into a single todo.

Combines several related todos into one, useful when:
- Similar tasks should be done together
- Todos were created with too much granularity
- Consolidating duplicate or overlapping work

The merged todo:
- Gets a combined title/description from sources
- Inherits all plan links from source todos
- Inherits all dependencies from source todos
- Takes over as the dependency for todos that depended on sources

Source todos are marked as 'merged' (abandoned status).
Session bindings from source todos are released.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of todo IDs to merge (can be prefixes). Minimum 2 required."
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional: custom title for merged todo. If not provided, titles are combined."
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional: custom description for merged todo. If not provided, descriptions are combined."
                    }
                },
                "required": ["todo_ids"]
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
            "name": "get_hierarchy",
            "description": """Get the complete hierarchy for any entity (goal, plan, or todo).

Traverses all relationships to build a comprehensive view:
- For a todo: traverses up to parent plans and goal, plus all dependencies
- For a plan: traverses up to goal and down to all todos
- For a goal: traverses down to all plans and their todos

The result includes:
- The goal at the top of the hierarchy
- All related plans
- All related todos
- Todo-plan links (many-to-many relationships)
- Todo dependencies (what depends on what)
- Session bindings for all entities
- Cycle detection for dependency graphs

Use this when you need to understand the full context of an entity,
see all related work items, or detect circular dependencies.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["goal", "plan", "todo"],
                        "description": "Type of entity to get hierarchy for"
                    },
                    "entity_id": {
                        "type": "string",
                        "description": "ID of the entity (can be prefix)"
                    },
                    "include_bindings": {
                        "type": "boolean",
                        "description": "Include session bindings in result. Default: true"
                    },
                    "include_dependencies": {
                        "type": "boolean",
                        "description": "Traverse todo dependencies. Default: true"
                    }
                },
                "required": ["entity_type", "entity_id"]
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
    {
        "type": "function",
        "function": {
            "name": "list_all_bindings",
            "description": """List all session bindings across the system.

Shows which sessions are bound to which goals/plans/todos, with filters
to help identify orphaned bindings (sessions that no longer exist) or
focus on specific areas.

Results are paginated. Use offset/limit to page through large result sets.
Use this to review and clean up session bindings.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "enum": ["all", "active", "orphaned", "released"],
                        "description": "Filter bindings: 'active' (default), 'orphaned' (session missing), 'released', or 'all'"
                    },
                    "goal_id": {
                        "type": "string",
                        "description": "Optional: only show bindings for entities under this goal (can be prefix)"
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["summary", "detail"],
                        "description": "Output mode: 'summary' for counts only, 'detail' (default) for full list"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of entities to show. Default: 10"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Number of entities to skip. Default: 0"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rebind_session",
            "description": """Rebind any session to a different entity.

Unlike bind_session (which only works on current session), this can
rebind any session. Useful for cleanup and reorganization.

The old binding is released and a new one created.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "ID of the session to rebind (can be prefix)"
                    },
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
                "required": ["session_id", "entity_type", "entity_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bind_entity_to_sessions",
            "description": """Bulk bind an entity to multiple sessions.

Entity-centric binding: specify which sessions should be bound to
a goal/plan/todo. Optionally unbind other sessions not in the list.

Useful for reorganization: "this todo should have exactly these sessions".""",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["goal", "plan", "todo"],
                        "description": "Type of entity"
                    },
                    "entity_id": {
                        "type": "string",
                        "description": "ID of the entity (can be prefix)"
                    },
                    "session_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of session IDs to bind (can be prefixes)"
                    },
                    "role": {
                        "type": "string",
                        "enum": ["interview", "planning", "implementation", "postmortem", "exploration"],
                        "description": "Role for all sessions. Default: 'implementation'"
                    },
                    "unbind_others": {
                        "type": "boolean",
                        "description": "If true, unbind sessions not in the list. Default: false"
                    }
                },
                "required": ["entity_type", "entity_id", "session_ids"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "unbind_sessions",
            "description": """Bulk unbind sessions.

Can unbind specific sessions or clean up orphaned bindings
(bindings for sessions that no longer exist).""",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of session IDs to unbind (can be prefixes). If empty with orphans_only=true, only cleans orphans."
                    },
                    "orphans_only": {
                        "type": "boolean",
                        "description": "If true, only unbind orphaned sessions (session no longer exists). Default: false"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "begin_streaming_todo",
            "description": """Start background sessions to work on one or more todos.

Creates new sessions bound to the specified todos and begins streaming in the
background. The user will be shown a confirmation modal listing the todos
before any sessions are started.

Use this when:
- You've planned work and want to parallelize execution across multiple todos
- The user asks you to start working on specific todos
- After creating a plan with todos, you're ready to begin implementation

Each todo gets its own session with role: implementation. Sessions stream
in the background so you can continue working in the current session.

The user must confirm which todos to start - they can select/deselect
individual todos from your proposed list.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of todo IDs to start sessions for (can be prefixes)"
                    },
                    "initial_prompts": {
                        "type": "object",
                        "description": "Optional map of todo_id -> custom initial prompt. If not provided, a default prompt based on the todo title/description is used.",
                        "additionalProperties": {"type": "string"}
                    }
                },
                "required": ["todo_ids"]
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
    elif name == "reparent_goal":
        return await _reparent_goal(args, storage)
    elif name == "create_plan":
        return await _create_plan(args, storage)
    elif name == "update_plan":
        return await _update_plan(args, storage)
    elif name == "create_todo":
        return await _create_todo(args, storage)
    elif name == "update_todo":
        return await _update_todo(args, storage)
    elif name == "delete_todo":
        return await _delete_todo(args, storage)
    elif name == "split_todo":
        return await _split_todo(args, storage)
    elif name == "merge_todos":
        return await _merge_todos(args, storage)
    elif name == "list_goals":
        return await _list_goals(args, storage)
    elif name == "list_plans":
        return await _list_plans(args, storage)
    elif name == "list_todos":
        return await _list_todos(args, storage)
    elif name == "get_todo":
        return await _get_todo(args, storage)
    elif name == "get_hierarchy":
        return await _get_hierarchy(args, storage)
    elif name == "mark_todo_done":
        return await _mark_todo_done(args, storage, session)
    elif name == "bind_session":
        return await _bind_session(args, storage, session)
    elif name == "list_all_bindings":
        return await _list_all_bindings(args, storage)
    elif name == "rebind_session":
        return await _rebind_session(args, storage)
    elif name == "bind_entity_to_sessions":
        return await _bind_entity_to_sessions(args, storage)
    elif name == "unbind_sessions":
        return await _unbind_sessions(args, storage)
    elif name == "begin_streaming_todo":
        return await _begin_streaming_todo(args, storage)
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

    # Handle optional parent_goal_id
    parent_goal_id = None
    parent_goal_id_prefix = args.get("parent_goal_id", "").strip()
    parent_title = None
    if parent_goal_id_prefix:
        goals = await storage.list_goals()
        for g in goals:
            if g.id.startswith(parent_goal_id_prefix):
                parent_goal_id = g.id
                parent_title = g.title
                break
        if not parent_goal_id:
            return f"Error: Parent goal not found: {parent_goal_id_prefix}", True

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
        parent_goal_id=parent_goal_id,
    )

    await storage.save_goal(goal)

    criteria_str = "\n".join(f"  - {c}" for c in acceptance_criteria)
    result = (
        f"Created goal: {goal.title}\n"
        f"ID: {goal.id}\n"
        f"Weight: {goal.weight}/10\n"
    )
    if parent_title:
        result += f"Parent: {parent_title}\n"
    result += f"Acceptance Criteria:\n{criteria_str}"
    return result, False


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


async def _reparent_goal(args: dict, storage) -> tuple[str, bool]:
    """Reparent a goal under a different parent or make it a root-level goal."""
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

    # Handle parent_goal_id - can be empty/null to unparent
    new_parent_id = None
    new_parent_title = None
    parent_goal_id_prefix = args.get("parent_goal_id", "").strip() if args.get("parent_goal_id") else ""

    if parent_goal_id_prefix:
        # Find new parent
        for g in goals:
            if g.id.startswith(parent_goal_id_prefix):
                new_parent_id = g.id
                new_parent_title = g.title
                break

        if not new_parent_id:
            return f"Error: Parent goal not found: {parent_goal_id_prefix}", True

        # Check for circular reference - goal cannot be its own ancestor
        if new_parent_id == goal.id:
            return "Error: A goal cannot be its own parent", True

        # Check if new parent is a descendant of this goal (would create cycle)
        ancestor_id = new_parent_id
        visited = set()
        while ancestor_id:
            if ancestor_id in visited:
                break  # Already checked this one (shouldn't happen, but safety)
            visited.add(ancestor_id)

            if ancestor_id == goal.id:
                return "Error: Cannot reparent - would create a circular reference", True

            # Find the ancestor's parent
            ancestor_goal = next((g for g in goals if g.id == ancestor_id), None)
            if ancestor_goal:
                ancestor_id = ancestor_goal.parent_goal_id
            else:
                break

    # Get old parent info for output
    old_parent_title = None
    if goal.parent_goal_id:
        old_parent = next((g for g in goals if g.id == goal.parent_goal_id), None)
        if old_parent:
            old_parent_title = old_parent.title

    # Update the goal's parent
    goal.parent_goal_id = new_parent_id
    goal.updated_at = datetime.now().isoformat()
    await storage.save_goal(goal)

    # Build result message
    if old_parent_title and new_parent_title:
        change = f"Moved from '{old_parent_title}' to '{new_parent_title}'"
    elif old_parent_title:
        change = f"Moved from '{old_parent_title}' to root level"
    elif new_parent_title:
        change = f"Moved under '{new_parent_title}'"
    else:
        change = "No change (already at root level)"

    return (
        f"Reparented goal: {goal.title}\n"
        f"ID: {goal.id}\n"
        f"{change}"
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


async def _update_todo(args: dict, storage) -> tuple[str, bool]:
    """Update an existing todo."""
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

    # Track what we're updating for the response
    updates = []

    # Update title if provided
    if "title" in args:
        new_title = args["title"].strip()
        if new_title:
            old_title = todo.title
            todo.title = new_title[:80]
            updates.append(f"title: '{old_title}' → '{todo.title}'")

    # Update description if provided
    if "description" in args:
        new_desc = args["description"].strip()
        if new_desc:
            todo.description = new_desc
            updates.append("description updated")

    # Update status if provided
    if "status" in args:
        new_status = args["status"]
        if new_status in ("pending", "in_progress", "done", "abandoned"):
            old_status = todo.status
            todo.status = new_status
            updates.append(f"status: {old_status} → {new_status}")

    # Update is_spike if provided
    if "is_spike" in args:
        new_is_spike = args["is_spike"]
        if isinstance(new_is_spike, bool):
            old_is_spike = todo.is_spike
            todo.is_spike = new_is_spike
            if old_is_spike != new_is_spike:
                if new_is_spike:
                    updates.append("converted to spike")
                else:
                    updates.append("converted from spike to regular todo")
                    # Clear timebox when converting from spike
                    if todo.timebox_minutes is not None:
                        todo.timebox_minutes = None

    # Update timebox_minutes if provided (only meaningful for spikes)
    if "timebox_minutes" in args:
        new_timebox = args["timebox_minutes"]
        if new_timebox is None:
            if todo.timebox_minutes is not None:
                old_timebox = todo.timebox_minutes
                todo.timebox_minutes = None
                updates.append(f"timebox removed (was {old_timebox} min)")
        elif isinstance(new_timebox, int) and new_timebox > 0:
            old_timebox = todo.timebox_minutes
            todo.timebox_minutes = new_timebox
            if old_timebox is None:
                updates.append(f"timebox set to {new_timebox} min")
            else:
                updates.append(f"timebox: {old_timebox} → {new_timebox} min")

    # Reparent to different plan if plan_id provided
    if "plan_id" in args:
        new_plan_id_prefix = args["plan_id"].strip()
        if new_plan_id_prefix:
            # Find new plan by prefix
            plans = await storage.list_plans()
            new_plan = None
            for p in plans:
                if p.id.startswith(new_plan_id_prefix):
                    new_plan = p
                    break

            if not new_plan:
                return f"Error: Plan not found for reparenting: {new_plan_id_prefix}", True

            # Get current plan(s) for display
            current_plan_ids = await storage.get_plans_for_todo(todo.id)
            old_plan_title = "unlinked"
            if current_plan_ids:
                old_plan = await storage.load_plan(current_plan_ids[0])
                old_plan_title = old_plan.title if old_plan else current_plan_ids[0][:8]
                # Remove old link(s)
                for old_plan_id in current_plan_ids:
                    await storage.delete_todo_plan_link(todo.id, old_plan_id)

            # Create new link
            now = datetime.now().isoformat()
            link = TodoPlanLink(
                todo_id=todo.id,
                plan_id=new_plan.id,
                created_at=now,
            )
            await storage.save_todo_plan_link(link)
            updates.append(f"plan: '{old_plan_title}' → '{new_plan.title}'")

    if not updates:
        return "No valid updates provided", True

    # Update the timestamp
    todo.updated_at = datetime.now().isoformat()

    # Save the updated todo
    await storage.save_todo(todo)

    # Get current plan for display
    current_plan_ids = await storage.get_plans_for_todo(todo.id)
    plan_title = "unlinked"
    if current_plan_ids:
        current_plan = await storage.load_plan(current_plan_ids[0])
        plan_title = current_plan.title if current_plan else current_plan_ids[0][:8]

    result = (
        f"Updated todo: {todo.title}\n"
        f"ID: {todo.id}\n"
        f"Plan: {plan_title}\n"
        f"Changes:\n" + "\n".join(f"  - {u}" for u in updates)
    )

    if todo.is_spike:
        result += f"\nType: Spike"
        if todo.timebox_minutes:
            result += f" ({todo.timebox_minutes} min)"

    return result, False


async def _delete_todo(args: dict, storage) -> tuple[str, bool]:
    """Delete a todo permanently."""
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

    # Get plan info for display before deleting
    plan_ids = await storage.get_plans_for_todo(todo.id)
    plan_title = "unlinked"
    if plan_ids:
        plan = await storage.load_plan(plan_ids[0])
        if plan:
            plan_title = plan.title

    # Delete all plan links
    for plan_id in plan_ids:
        await storage.delete_todo_plan_link(todo.id, plan_id)

    # Delete all dependencies (both directions)
    # Get todos that this todo depends on
    dep_ids = await storage.get_dependencies(todo.id)
    for dep_id in dep_ids:
        await storage.delete_todo_dependency(todo.id, dep_id)

    # Get todos that depend on this todo
    dependent_ids = await storage.get_dependents(todo.id)
    for dependent_id in dependent_ids:
        await storage.delete_todo_dependency(dependent_id, todo.id)

    # Release any session bindings for this todo
    bindings = await storage.get_bindings_for_entity("todo", todo.id, active_only=True)
    now = datetime.now().isoformat()
    for binding in bindings:
        binding.released_at = now
        await storage.save_session_binding(binding)

    # Delete the todo itself
    await storage.delete_todo(todo.id)

    return (
        f"Deleted todo: {todo.title}\n"
        f"ID: {todo.id}\n"
        f"Plan: {plan_title}\n"
        f"Cleaned up: {len(plan_ids)} plan link(s), {len(dep_ids) + len(dependent_ids)} dependency(ies), {len(bindings)} binding(s)"
    ), False


async def _split_todo(args: dict, storage) -> tuple[str, bool]:
    """Split a todo into multiple smaller todos."""
    todo_id_prefix = args.get("todo_id", "").strip()
    if not todo_id_prefix:
        return "Error: todo_id is required", True

    new_todos_specs = args.get("new_todos", [])
    if not new_todos_specs:
        return "Error: new_todos is required (list of {title, description?})", True

    if len(new_todos_specs) < 2:
        return "Error: new_todos must contain at least 2 items to split", True

    chain_dependencies = args.get("chain_dependencies", False)

    # Find the original todo by prefix
    all_todos = await storage.list_todos(include_spikes=True)
    original_todo = None
    for t in all_todos:
        if t.id.startswith(todo_id_prefix):
            original_todo = t
            break

    if not original_todo:
        return f"Error: Todo not found: {todo_id_prefix}", True

    # Check if todo can be split (not already completed or abandoned)
    if original_todo.status in ("completed", "done", "abandoned"):
        return f"Error: Cannot split a {original_todo.status} todo", True

    # Get the original todo's plan links to inherit
    plan_ids = await storage.get_plans_for_todo(original_todo.id)

    now = datetime.now().isoformat()
    created_todos = []
    previous_todo_id = None

    # Create the new todos
    for spec in new_todos_specs:
        title = spec.get("title", "").strip()
        if not title:
            # Clean up any already-created todos on error
            for created in created_todos:
                await storage.delete_todo(created.id)
            return "Error: Each new todo must have a title", True

        description = spec.get("description", "").strip()

        new_todo = TodoData(
            id=str(uuid.uuid4()),
            title=title[:80],
            description=description,
            status="pending",
            is_spike=False,  # New todos from split are not spikes
            created_at=now,
            updated_at=now,
        )

        await storage.save_todo(new_todo)
        created_todos.append(new_todo)

        # Link to all of the original's plans
        for plan_id in plan_ids:
            link = TodoPlanLink(
                todo_id=new_todo.id,
                plan_id=plan_id,
                created_at=now,
            )
            await storage.save_todo_plan_link(link)

        # If chaining dependencies, make this todo depend on the previous one
        if chain_dependencies and previous_todo_id is not None:
            dep = TodoDependency(
                todo_id=new_todo.id,
                depends_on_id=previous_todo_id,
                created_at=now,
            )
            await storage.save_todo_dependency(dep)

        previous_todo_id = new_todo.id

    # Mark the original todo as abandoned with a note
    original_todo.status = "abandoned"
    original_todo.description = (
        f"[Split into {len(created_todos)} todos: "
        f"{', '.join(t.id[:8] for t in created_todos)}]\n\n"
        f"{original_todo.description}"
    ).strip()
    original_todo.updated_at = now
    await storage.save_todo(original_todo)

    # Release any session bindings for the original todo
    bindings = await storage.get_bindings_for_entity("todo", original_todo.id, active_only=True)
    for binding in bindings:
        binding.released_at = now
        await storage.save_session_binding(binding)

    # Build result message
    plan_info = ""
    if plan_ids:
        plan = await storage.load_plan(plan_ids[0])
        if plan:
            plan_info = f"Plan: {plan.title}\n"

    new_todos_list = "\n".join(
        f"  - {t.title} ({t.id[:8]})"
        for t in created_todos
    )

    return (
        f"Split todo: {original_todo.title}\n"
        f"Original ID: {original_todo.id} (now abandoned)\n"
        f"{plan_info}"
        f"Created {len(created_todos)} new todos:\n{new_todos_list}\n"
        f"Dependencies: {'chained' if chain_dependencies else 'none'}\n"
        f"New todo IDs: {', '.join(t.id for t in created_todos)}"
    ), False


async def _merge_todos(args: dict, storage) -> tuple[str, bool]:
    """Merge multiple todos into a single todo."""
    todo_id_prefixes = args.get("todo_ids", [])
    if not todo_id_prefixes or len(todo_id_prefixes) < 2:
        return "Error: todo_ids must contain at least 2 todo IDs to merge", True

    # Find all todos by prefix
    all_todos = await storage.list_todos(include_spikes=True)
    source_todos = []
    not_found = []

    for prefix in todo_id_prefixes:
        prefix = prefix.strip()
        found = None
        for t in all_todos:
            if t.id.startswith(prefix):
                found = t
                break
        if found:
            # Avoid duplicates
            if found.id not in [st.id for st in source_todos]:
                source_todos.append(found)
        else:
            not_found.append(prefix)

    if not_found:
        return f"Error: Todos not found: {', '.join(not_found)}", True

    if len(source_todos) < 2:
        return "Error: Need at least 2 distinct todos to merge", True

    # Check that none of the source todos are already completed or abandoned
    invalid_status = []
    for todo in source_todos:
        if todo.status in ("completed", "done", "abandoned"):
            invalid_status.append(f"{todo.title} ({todo.status})")

    if invalid_status:
        return f"Error: Cannot merge completed/abandoned todos: {', '.join(invalid_status)}", True

    now = datetime.now().isoformat()

    # Build merged title and description
    custom_title = args.get("title", "").strip()
    custom_description = args.get("description", "").strip()

    if custom_title:
        merged_title = custom_title[:80]
    else:
        # Combine titles
        titles = [t.title for t in source_todos]
        merged_title = " + ".join(titles)[:80]

    if custom_description:
        merged_description = custom_description
    else:
        # Combine descriptions
        descriptions = [t.description for t in source_todos if t.description]
        if descriptions:
            merged_description = "\n\n---\n\n".join(descriptions)
        else:
            merged_description = ""

    # Create the merged todo
    merged_todo = TodoData(
        id=str(uuid.uuid4()),
        title=merged_title,
        description=merged_description,
        status="pending",
        is_spike=any(t.is_spike for t in source_todos),  # Spike if any source was spike
        timebox_minutes=max((t.timebox_minutes or 0) for t in source_todos) or None,
        created_at=now,
        updated_at=now,
    )
    await storage.save_todo(merged_todo)

    # Collect all unique plan IDs from source todos
    all_plan_ids = set()
    for todo in source_todos:
        plan_ids = await storage.get_plans_for_todo(todo.id)
        all_plan_ids.update(plan_ids)

    # Link merged todo to all plans
    for plan_id in all_plan_ids:
        link = TodoPlanLink(
            todo_id=merged_todo.id,
            plan_id=plan_id,
            created_at=now,
        )
        await storage.save_todo_plan_link(link)

    # Collect all dependencies from source todos (what they depend on)
    all_dependency_ids = set()
    for todo in source_todos:
        dep_ids = await storage.get_dependencies(todo.id)
        all_dependency_ids.update(dep_ids)

    # Remove self-references (don't depend on ourselves)
    source_ids = {t.id for t in source_todos}
    all_dependency_ids -= source_ids

    # Create dependencies for merged todo
    for dep_id in all_dependency_ids:
        dep = TodoDependency(
            todo_id=merged_todo.id,
            depends_on_id=dep_id,
            created_at=now,
        )
        await storage.save_todo_dependency(dep)

    # Find todos that depended on any source todo and update them
    # to depend on the merged todo instead
    dependents_updated = 0
    for todo in source_todos:
        dependent_ids = await storage.get_dependents(todo.id)
        for dependent_id in dependent_ids:
            # Skip if the dependent is one of our source todos
            if dependent_id in source_ids:
                continue

            # Delete old dependency
            await storage.delete_todo_dependency(dependent_id, todo.id)

            # Create new dependency on merged todo (avoid duplicates)
            dep = TodoDependency(
                todo_id=dependent_id,
                depends_on_id=merged_todo.id,
                created_at=now,
            )
            await storage.save_todo_dependency(dep)
            dependents_updated += 1

    # Mark source todos as abandoned (merged) and clean up
    for todo in source_todos:
        # Delete plan links
        plan_ids = await storage.get_plans_for_todo(todo.id)
        for plan_id in plan_ids:
            await storage.delete_todo_plan_link(todo.id, plan_id)

        # Delete dependencies (what this todo depends on)
        dep_ids = await storage.get_dependencies(todo.id)
        for dep_id in dep_ids:
            await storage.delete_todo_dependency(todo.id, dep_id)

        # Release session bindings
        bindings = await storage.get_bindings_for_entity("todo", todo.id, active_only=True)
        for binding in bindings:
            binding.released_at = now
            await storage.save_session_binding(binding)

        # Mark as abandoned with merge note
        todo.status = "abandoned"
        todo.description = f"[Merged into {merged_todo.id[:8]}] {todo.description}"
        todo.updated_at = now
        await storage.save_todo(todo)

    # Get plan names for display
    plan_names = []
    for plan_id in all_plan_ids:
        plan = await storage.load_plan(plan_id)
        if plan:
            plan_names.append(plan.title)

    source_titles = [t.title for t in source_todos]

    result = (
        f"Merged {len(source_todos)} todos into:\n"
        f"  Title: {merged_todo.title}\n"
        f"  ID: {merged_todo.id}\n"
        f"  Plans: {', '.join(plan_names) if plan_names else 'none'}\n"
        f"\nSource todos (now abandoned):\n"
    )
    for title in source_titles:
        result += f"  - {title}\n"

    if all_dependency_ids:
        result += f"\nInherited {len(all_dependency_ids)} dependency(ies)"
    if dependents_updated:
        result += f"\nUpdated {dependents_updated} dependent todo(s) to point to merged todo"

    if merged_todo.is_spike:
        result += f"\nType: Spike"
        if merged_todo.timebox_minutes:
            result += f" ({merged_todo.timebox_minutes} min)"

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


async def _get_hierarchy(args: dict, storage) -> tuple[str, bool]:
    """Get the complete hierarchy for an entity."""
    entity_type = args.get("entity_type", "").strip()
    if entity_type not in ("goal", "plan", "todo"):
        return "Error: entity_type must be 'goal', 'plan', or 'todo'", True

    entity_id = args.get("entity_id", "").strip()
    if not entity_id:
        return "Error: entity_id is required", True

    include_bindings = args.get("include_bindings", True)
    include_dependencies = args.get("include_dependencies", True)

    hierarchy = await storage.get_hierarchy(
        entity_type, entity_id,
        include_bindings=include_bindings,
        include_dependencies=include_dependencies
    )

    # Check if entity was found
    if entity_type == "goal" and hierarchy.goal is None:
        return f"Error: Goal not found: {entity_id}", True
    elif entity_type == "plan" and len(hierarchy.plans) == 0:
        return f"Error: Plan not found: {entity_id}", True
    elif entity_type == "todo" and len(hierarchy.todos) == 0:
        return f"Error: Todo not found: {entity_id}", True

    # Build formatted output
    lines = [f"Hierarchy for {entity_type}: {entity_id}"]
    lines.append("")

    # Goal section
    if hierarchy.goal:
        lines.append(f"Goal: {hierarchy.goal.title}")
        lines.append(f"  ID: {hierarchy.goal.id}")
        lines.append(f"  Status: {hierarchy.goal.status}")
        lines.append(f"  Weight: {hierarchy.goal.weight}/10")
        lines.append("")

    # Plans section
    if hierarchy.plans:
        lines.append(f"Plans ({len(hierarchy.plans)}):")
        for plan in hierarchy.plans:
            lines.append(f"  - {plan.title}")
            lines.append(f"    ID: {plan.id[:8]}")
            lines.append(f"    Status: {plan.status}")
        lines.append("")

    # Todos section
    if hierarchy.todos:
        lines.append(f"Todos ({len(hierarchy.todos)}):")
        for todo in hierarchy.todos:
            status_icon = {
                "pending": "○",
                "in_progress": "◐",
                "done": "✓",
                "completed": "✓",
                "abandoned": "✗",
                "blocked": "⊘",
            }.get(todo.status, "?")
            spike_marker = " [spike]" if todo.is_spike else ""
            lines.append(f"  {status_icon} {todo.title}{spike_marker}")
            lines.append(f"    ID: {todo.id[:8]}")
            lines.append(f"    Status: {todo.status}")
        lines.append("")

    # Dependencies section
    if hierarchy.dependencies:
        lines.append(f"Dependencies ({len(hierarchy.dependencies)}):")
        for dep in hierarchy.dependencies:
            lines.append(f"  {dep.todo_id[:8]} depends on {dep.depends_on_id[:8]}")
        lines.append("")

    # Cycle warning
    if hierarchy.cycle_detected:
        lines.append("⚠️  CYCLE DETECTED in dependencies!")
        if hierarchy.cycle_path:
            path_str = " → ".join(p[:8] for p in hierarchy.cycle_path)
            lines.append(f"  Cycle path: {path_str}")
        lines.append("")

    # Bindings section
    if hierarchy.bindings:
        lines.append(f"Session Bindings ({len(hierarchy.bindings)}):")
        for binding in hierarchy.bindings:
            lines.append(f"  - Session {binding.session_id[:8]} → {binding.entity_type} ({binding.role})")
        lines.append("")

    # Summary
    lines.append("Summary:")
    lines.append(f"  Goals: {1 if hierarchy.goal else 0}")
    lines.append(f"  Plans: {len(hierarchy.plans)}")
    lines.append(f"  Todos: {len(hierarchy.todos)}")
    if include_dependencies:
        lines.append(f"  Dependencies: {len(hierarchy.dependencies)}")
    if include_bindings:
        lines.append(f"  Bindings: {len(hierarchy.bindings)}")

    return "\n".join(lines), False


async def _mark_todo_done(args: dict, storage, session) -> tuple[str, bool]:
    """Mark a todo as complete."""
    todo_id = args.get("todo_id", "").strip()
    if not todo_id:
        return "Error: todo_id is required", True

    executor = GoalCommandExecutor(storage)
    result = await executor.mark_todo_done(todo_id, session.id)

    if result.success:
        response = f"Marked complete: {result.todo.title}\nID: {result.todo.id}"
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
        session_name = session.title or session.id[:8]
        entity_title = result.entity_title or entity_id
        return f"Session {session_name} bound to {entity_type} {entity_title} with role: {role}", False
    else:
        return f"Error: {result.error}", True


async def _get_session_ids_set() -> set[str]:
    """Get set of all existing session IDs."""
    session_storage = AsyncStorage()
    sessions = await session_storage.list_sessions()
    return {s["id"] for s in sessions}


async def _find_session_by_prefix(session_id_prefix: str) -> str | None:
    """Find a session ID by prefix. Returns full ID or None."""
    session_storage = AsyncStorage()
    sessions = await session_storage.list_sessions()
    for s in sessions:
        if s["id"].startswith(session_id_prefix):
            return s["id"]
    return None


async def _list_all_bindings(args: dict, storage) -> tuple[str, bool]:
    """List all session bindings with filtering and pagination."""
    filter_type = args.get("filter", "active")
    goal_id_prefix = args.get("goal_id", "")
    mode = args.get("mode", "detail")
    limit = args.get("limit", 10)
    offset = args.get("offset", 0)

    # Get all existing session IDs
    existing_sessions = await _get_session_ids_set()

    # Get all goal/plan/todo IDs for filtering
    goal_filter_id = None
    plan_ids_under_goal = set()
    todo_ids_under_goal = set()

    if goal_id_prefix:
        # Find the goal
        goals = await storage.list_goals()
        for g in goals:
            if g.id.startswith(goal_id_prefix):
                goal_filter_id = g.id
                break
        if not goal_filter_id:
            return f"Error: Goal not found: {goal_id_prefix}", True

        # Get plans under this goal
        plans = await storage.list_plans(goal_id=goal_filter_id)
        plan_ids_under_goal = {p.id for p in plans}

        # Get todos under these plans
        for plan in plans:
            todo_ids = await storage.get_todos_for_plan(plan.id)
            todo_ids_under_goal.update(todo_ids)

    # Get all bindings (include released for filtering)
    all_bindings = await storage.list_bindings(active_only=False)

    # Classify bindings
    active_bindings = []
    orphaned_bindings = []
    released_bindings = []

    for binding in all_bindings:
        # Check if under goal filter
        if goal_filter_id:
            if binding.entity_type == "goal" and binding.entity_id != goal_filter_id:
                continue
            if binding.entity_type == "plan" and binding.entity_id not in plan_ids_under_goal:
                continue
            if binding.entity_type == "todo" and binding.entity_id not in todo_ids_under_goal:
                continue

        session_exists = binding.session_id in existing_sessions

        if binding.released_at is not None:
            released_bindings.append((binding, session_exists))
        elif not session_exists:
            orphaned_bindings.append(binding)
        else:
            active_bindings.append(binding)

    # Summary mode
    if mode == "summary":
        lines = ["Session Bindings Summary"]
        lines.append(f"  Active: {len(active_bindings)}")
        lines.append(f"  Orphaned: {len(orphaned_bindings)} (session deleted)")
        lines.append(f"  Released: {len(released_bindings)}")
        if goal_filter_id:
            goal = await storage.load_goal(goal_filter_id)
            lines.append(f"\nFiltered to goal: {goal.title if goal else goal_filter_id[:8]}")
        return "\n".join(lines), False

    # Detail mode - filter by type
    if filter_type == "active":
        bindings_to_show = [(b, True) for b in active_bindings]
    elif filter_type == "orphaned":
        bindings_to_show = [(b, False) for b in orphaned_bindings]
    elif filter_type == "released":
        bindings_to_show = released_bindings
    else:  # all
        bindings_to_show = (
            [(b, True) for b in active_bindings] +
            [(b, False) for b in orphaned_bindings] +
            released_bindings
        )

    if not bindings_to_show:
        return f"No {filter_type} bindings found.", False

    # Group by entity for readability
    by_entity = {}
    for binding, session_exists in bindings_to_show:
        key = (binding.entity_type, binding.entity_id)
        if key not in by_entity:
            by_entity[key] = []
        by_entity[key].append((binding, session_exists))

    # Sort entities and apply pagination
    sorted_entities = sorted(by_entity.items())
    total_entities = len(sorted_entities)
    paginated_entities = sorted_entities[offset:offset + limit]

    if not paginated_entities:
        return f"No {filter_type} bindings found at offset {offset}.", False

    # Format output
    lines = [f"Session Bindings ({filter_type})"]
    lines.append(f"Showing {offset + 1}-{offset + len(paginated_entities)} of {total_entities} entities")
    lines.append("")

    for (entity_type, entity_id), entity_bindings in paginated_entities:
        # Get entity name
        entity_name = entity_id[:8]
        if entity_type == "goal":
            goal = await storage.load_goal(entity_id)
            if goal:
                entity_name = goal.title
        elif entity_type == "plan":
            plan = await storage.load_plan(entity_id)
            if plan:
                entity_name = plan.title
        elif entity_type == "todo":
            todo = await storage.load_todo(entity_id)
            if todo:
                entity_name = todo.title

        lines.append(f"{entity_type.title()}: {entity_name}")
        for binding, session_exists in entity_bindings:
            status = ""
            if binding.released_at:
                status = " [released]"
            elif not session_exists:
                status = " [orphaned]"
            lines.append(f"  - {binding.session_id[:8]} ({binding.role}){status}")
        lines.append("")

    # Add pagination hint if there are more results
    if offset + limit < total_entities:
        lines.append(f"[Use offset={offset + limit} to see more]")

    return "\n".join(lines), False


async def _rebind_session(args: dict, storage) -> tuple[str, bool]:
    """Rebind any session to a different entity."""
    session_id_prefix = args.get("session_id", "").strip()
    if not session_id_prefix:
        return "Error: session_id is required", True

    entity_type = args.get("entity_type", "").strip()
    if entity_type not in ("goal", "plan", "todo"):
        return "Error: entity_type must be 'goal', 'plan', or 'todo'", True

    entity_id_prefix = args.get("entity_id", "").strip()
    if not entity_id_prefix:
        return "Error: entity_id is required", True

    role = args.get("role", "implementation")
    valid_roles = ("interview", "planning", "implementation", "postmortem", "exploration")
    if role not in valid_roles:
        role = "implementation"

    # Find full session ID
    full_session_id = await _find_session_by_prefix(session_id_prefix)
    if not full_session_id:
        return f"Error: Session not found: {session_id_prefix}", True

    # Use GoalCommandExecutor to bind (it handles entity resolution and unbinding)
    executor = GoalCommandExecutor(storage)

    # First unbind existing bindings for this session
    await executor.unbind_session(full_session_id)

    # Then bind to new entity
    result = await executor.bind_session(full_session_id, entity_type, entity_id_prefix, role)

    if result.success:
        return f"Rebound session {full_session_id[:8]} to {entity_type} with role: {role}", False
    else:
        return f"Error: {result.error}", True


async def _bind_entity_to_sessions(args: dict, storage) -> tuple[str, bool]:
    """Bulk bind an entity to multiple sessions."""
    entity_type = args.get("entity_type", "").strip()
    if entity_type not in ("goal", "plan", "todo"):
        return "Error: entity_type must be 'goal', 'plan', or 'todo'", True

    entity_id_prefix = args.get("entity_id", "").strip()
    if not entity_id_prefix:
        return "Error: entity_id is required", True

    session_id_prefixes = args.get("session_ids", [])
    if not session_id_prefixes:
        return "Error: session_ids is required (list of session IDs)", True

    role = args.get("role", "implementation")
    valid_roles = ("interview", "planning", "implementation", "postmortem", "exploration")
    if role not in valid_roles:
        role = "implementation"

    unbind_others = args.get("unbind_others", False)

    executor = GoalCommandExecutor(storage)

    # Resolve entity ID
    entity_title = ""
    full_entity_id = None
    if entity_type == "goal":
        goals = await storage.list_goals()
        for g in goals:
            if g.id.startswith(entity_id_prefix):
                full_entity_id = g.id
                entity_title = g.title
                break
    elif entity_type == "plan":
        plans = await storage.list_plans()
        for p in plans:
            if p.id.startswith(entity_id_prefix):
                full_entity_id = p.id
                entity_title = p.title
                break
    elif entity_type == "todo":
        todos = await storage.list_todos(include_spikes=True)
        for t in todos:
            if t.id.startswith(entity_id_prefix):
                full_entity_id = t.id
                entity_title = t.title
                break

    if not full_entity_id:
        return f"Error: {entity_type.title()} not found: {entity_id_prefix}", True

    # Resolve session IDs
    full_session_ids = []
    not_found = []
    for prefix in session_id_prefixes:
        full_id = await _find_session_by_prefix(prefix)
        if full_id:
            full_session_ids.append(full_id)
        else:
            not_found.append(prefix)

    if not_found:
        return f"Error: Sessions not found: {', '.join(not_found)}", True

    # If unbind_others, release bindings for sessions not in the list
    if unbind_others:
        existing_bindings = await storage.get_bindings_for_entity(entity_type, full_entity_id, active_only=True)
        for binding in existing_bindings:
            if binding.session_id not in full_session_ids:
                binding.released_at = datetime.now().isoformat()
                await storage.save_session_binding(binding)

    # Bind each session
    bound_count = 0
    for session_id in full_session_ids:
        # Check if already bound
        existing = await storage.get_bindings_for_session(session_id, active_only=True)
        already_bound = any(
            b.entity_type == entity_type and b.entity_id == full_entity_id
            for b in existing
        )

        if not already_bound:
            result = await executor.bind_session(session_id, entity_type, entity_id_prefix, role)
            if result.success:
                bound_count += 1

    result_msg = f"Bound {bound_count} session(s) to {entity_type}: {entity_title}"
    if unbind_others:
        result_msg += " (unbound others)"

    return result_msg, False


async def _unbind_sessions(args: dict, storage) -> tuple[str, bool]:
    """Bulk unbind sessions or cleanup orphans."""
    session_id_prefixes = args.get("session_ids", [])
    orphans_only = args.get("orphans_only", False)

    existing_sessions = await _get_session_ids_set()

    # Get all active bindings
    all_bindings = await storage.list_bindings(active_only=True)

    # Determine which bindings to release
    to_release = []

    if orphans_only:
        # Only orphaned bindings
        for binding in all_bindings:
            if binding.session_id not in existing_sessions:
                to_release.append(binding)
    elif session_id_prefixes:
        # Specific sessions
        for binding in all_bindings:
            for prefix in session_id_prefixes:
                if binding.session_id.startswith(prefix):
                    to_release.append(binding)
                    break
    else:
        return "Error: Provide session_ids or set orphans_only=true", True

    if not to_release:
        if orphans_only:
            return "No orphaned bindings found.", False
        return "No matching bindings found.", False

    # Release the bindings
    now = datetime.now().isoformat()
    for binding in to_release:
        binding.released_at = now
        await storage.save_session_binding(binding)

    if orphans_only:
        return f"Released {len(to_release)} orphaned binding(s).", False
    else:
        return f"Released {len(to_release)} binding(s).", False


async def _begin_streaming_todo(args: dict, storage) -> tuple[str, bool]:
    """Validate and prepare begin_streaming_todo request.

    This tool returns a special PENDING result that the app layer intercepts
    to show a confirmation modal. The actual session creation happens in the
    app after user confirmation.
    """
    todo_id_prefixes = args.get("todo_ids", [])
    if not todo_id_prefixes:
        return "Error: todo_ids is required (list of todo IDs)", True

    initial_prompts = args.get("initial_prompts", {})

    # Resolve todo IDs and validate they exist
    todos = await storage.list_todos(include_spikes=True)
    resolved_todos = []
    not_found = []

    for prefix in todo_id_prefixes:
        prefix = prefix.strip()
        found = None
        for todo in todos:
            if todo.id.startswith(prefix):
                found = todo
                break

        if found:
            # Check if todo is already done or abandoned
            if found.status in ("done", "abandoned"):
                return f"Error: Todo '{found.title}' is already {found.status}", True
            resolved_todos.append(found)
        else:
            not_found.append(prefix)

    if not_found:
        return f"Error: Todos not found: {', '.join(not_found)}", True

    if not resolved_todos:
        return "Error: No valid todos to start", True

    # Return pending result - app will intercept and show confirmation modal
    # The actual execution happens in the app layer after user confirms
    return "BEGIN_STREAMING_TODO_PENDING", False


# =============================================================================
# Data class for begin_streaming_todo proposal parsing
# =============================================================================

from dataclasses import dataclass, field
from typing import Optional

@dataclass
class BeginStreamingTodoProposal:
    """A proposal to start streaming sessions for todos.

    Parsed from the begin_streaming_todo tool arguments by the app layer.
    """
    todo_ids: list[str] = field(default_factory=list)
    initial_prompts: dict[str, str] = field(default_factory=dict)
    # Resolved todo data (populated by parse function)
    resolved_todos: list = field(default_factory=list)  # List of TodoData


async def parse_begin_streaming_todo_proposal(args: dict) -> Optional[BeginStreamingTodoProposal]:
    """Parse tool arguments into a BeginStreamingTodoProposal.

    Called by the app layer when it intercepts a begin_streaming_todo tool call.
    Resolves todo IDs to full TodoData objects for display in the confirmation modal.

    Args:
        args: Tool arguments from the model

    Returns:
        BeginStreamingTodoProposal object, or None if parsing fails
    """
    try:
        todo_id_prefixes = args.get("todo_ids", [])
        initial_prompts = args.get("initial_prompts", {})

        if not todo_id_prefixes:
            return None

        # Resolve todos
        storage = await get_goal_storage()
        todos = await storage.list_todos(include_spikes=True)

        resolved_todos = []
        resolved_ids = []
        for prefix in todo_id_prefixes:
            prefix = prefix.strip()
            for todo in todos:
                if todo.id.startswith(prefix):
                    resolved_todos.append(todo)
                    resolved_ids.append(todo.id)
                    break

        return BeginStreamingTodoProposal(
            todo_ids=resolved_ids,
            initial_prompts=initial_prompts,
            resolved_todos=resolved_todos,
        )
    except Exception:
        return None
