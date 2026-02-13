"""
GoalTreeState - Framework-agnostic shared state layer for goal-centric tree views.

This module implements the Model for a goal-centric tree view where the hierarchy
is organized by goals → plans → todos, with sessions as associated data.

Architecture mirrors TreeState but with goal-oriented organization:
- GoalTreeState: Central state container
- GoalNodeData, PlanNodeData, TodoNodeData: Node data models
- Observer pattern for change notifications

Data Flow:
1. App loads goals/plans/todos from storage
2. App loads session bindings to associate sessions with entities
3. GoalTreeState notifies observers of changes
4. GoalTreeView renders the goal-centric hierarchy
"""

from dataclasses import dataclass, field
from typing import Callable, Any, Optional
from enum import Enum

from storage_schema import GoalData, PlanData, TodoData, SessionBinding


class GoalTreeEvent(Enum):
    """Events that GoalTreeState notifies observers about."""
    # Goal events
    GOAL_ADDED = "goal_added"
    GOAL_UPDATED = "goal_updated"
    GOAL_REMOVED = "goal_removed"

    # Plan events
    PLAN_ADDED = "plan_added"
    PLAN_UPDATED = "plan_updated"
    PLAN_REMOVED = "plan_removed"

    # Todo events
    TODO_ADDED = "todo_added"
    TODO_UPDATED = "todo_updated"
    TODO_REMOVED = "todo_removed"

    # Session binding events
    SESSION_BOUND = "session_bound"
    SESSION_UNBOUND = "session_unbound"
    SESSION_UPDATED = "session_updated"  # Session metadata changed (title, tokens, etc.)

    # Selection events
    ENTITY_SELECTED = "entity_selected"

    # Rebuild
    FULL_REBUILD = "full_rebuild"


@dataclass
class GoalNodeData:
    """Data for a goal node in the tree.

    Includes the goal data plus computed/runtime fields.
    """
    goal: GoalData
    plan_ids: list[str] = field(default_factory=list)  # Child plan IDs
    bound_session_ids: list[str] = field(default_factory=list)  # Sessions bound directly to goal
    is_expanded: bool = False

    @property
    def id(self) -> str:
        return self.goal.id

    @property
    def title(self) -> str:
        return self.goal.title

    @property
    def weight(self) -> int:
        return self.goal.weight

    @property
    def status(self) -> str:
        return self.goal.status


@dataclass
class PlanNodeData:
    """Data for a plan node in the tree."""
    plan: PlanData
    goal_id: str  # Parent goal ID
    todo_ids: list[str] = field(default_factory=list)  # Child todo IDs
    bound_session_ids: list[str] = field(default_factory=list)  # Sessions bound to this plan
    is_expanded: bool = False

    @property
    def id(self) -> str:
        return self.plan.id

    @property
    def title(self) -> str:
        return self.plan.title

    @property
    def status(self) -> str:
        return self.plan.status


@dataclass
class TodoNodeData:
    """Data for a todo node in the tree."""
    todo: TodoData
    plan_ids: list[str] = field(default_factory=list)  # Parent plan IDs (can be multiple)
    bound_session_ids: list[str] = field(default_factory=list)  # Sessions bound to this todo
    dependency_ids: list[str] = field(default_factory=list)  # Todos this depends on
    is_expanded: bool = False
    priority: float = 0.0  # Computed priority score

    @property
    def id(self) -> str:
        return self.todo.id

    @property
    def title(self) -> str:
        return self.todo.title

    @property
    def status(self) -> str:
        return self.todo.status

    @property
    def is_spike(self) -> bool:
        return self.todo.is_spike


@dataclass
class SessionNodeData:
    """Minimal session data for display in goal tree.

    Full session data lives in TreeState; this just holds what we need
    for display in the goal-centric tree.
    """
    session_id: str
    name: str  # fork_name or title or id prefix
    token_count: int = 0
    is_current: bool = False
    is_streaming: bool = False
    fork_status: str = ""  # "merged", "active", ""
    binding_role: str = ""  # "implementation", "planning", etc.

    @property
    def id(self) -> str:
        return self.session_id


# Type alias for observer callbacks
GoalTreeObserverCallback = Callable[[GoalTreeEvent, dict[str, Any]], None]


class GoalTreeState:
    """
    Framework-agnostic state container for goal-centric tree data.

    Organizes data by goals → plans → todos, with sessions as associated
    data under the entities they're bound to.

    Thread-safety: Not thread-safe. All operations should be called
    from the main UI thread.
    """

    def __init__(self):
        # Entity data
        self._goals: dict[str, GoalNodeData] = {}
        self._plans: dict[str, PlanNodeData] = {}
        self._todos: dict[str, TodoNodeData] = {}

        # Session bindings: entity_id -> list of SessionNodeData
        self._bound_sessions: dict[str, list[SessionNodeData]] = {}

        # Unbound sessions (for "Unbound Sessions" section)
        self._unbound_sessions: list[SessionNodeData] = []

        # All session IDs we know about (for quick lookup)
        self._all_session_ids: set[str] = set()

        # Currently selected entity (goal, plan, or todo ID)
        self._selected_entity_id: Optional[str] = None
        self._selected_entity_type: Optional[str] = None  # "goal", "plan", "todo", "session"

        # Observer callbacks
        self._observers: list[GoalTreeObserverCallback] = []

        # Batch loading mode - when True, suppress individual notifications
        self._batch_loading = False

    # --- Observer Management ---

    def add_observer(self, callback: GoalTreeObserverCallback) -> None:
        """Register a callback to be notified of state changes."""
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: GoalTreeObserverCallback) -> None:
        """Unregister an observer callback."""
        if callback in self._observers:
            self._observers.remove(callback)

    def _notify(self, event: GoalTreeEvent, data: dict[str, Any] = None) -> None:
        """Notify all observers of a state change."""
        # Skip notifications during batch loading (except FULL_REBUILD)
        if self._batch_loading and event != GoalTreeEvent.FULL_REBUILD:
            return
        data = data or {}
        for callback in self._observers:
            callback(event, data)

    def begin_batch_loading(self) -> None:
        """Begin batch loading mode - suppress individual add/update notifications."""
        self._batch_loading = True

    def end_batch_loading(self) -> None:
        """End batch loading mode and trigger a full rebuild."""
        self._batch_loading = False
        self._notify(GoalTreeEvent.FULL_REBUILD, {})

    # --- Goal Operations ---

    def add_goal(self, goal: GoalData) -> None:
        """Add or update a goal."""
        is_new = goal.id not in self._goals

        if is_new:
            node = GoalNodeData(goal=goal)
            self._goals[goal.id] = node
            self._notify(GoalTreeEvent.GOAL_ADDED, {"goal_id": goal.id})
        else:
            self._goals[goal.id].goal = goal
            self._notify(GoalTreeEvent.GOAL_UPDATED, {"goal_id": goal.id})

    def remove_goal(self, goal_id: str) -> None:
        """Remove a goal and its children."""
        if goal_id not in self._goals:
            return

        # Remove child plans
        goal_node = self._goals[goal_id]
        for plan_id in goal_node.plan_ids:
            self.remove_plan(plan_id)

        # Remove bound sessions
        if goal_id in self._bound_sessions:
            del self._bound_sessions[goal_id]

        del self._goals[goal_id]
        self._notify(GoalTreeEvent.GOAL_REMOVED, {"goal_id": goal_id})

    def get_goal(self, goal_id: str) -> Optional[GoalNodeData]:
        """Get a goal by ID."""
        return self._goals.get(goal_id)

    def get_all_goals(self) -> list[GoalNodeData]:
        """Get all goals sorted by weight (descending)."""
        goals = list(self._goals.values())
        goals.sort(key=lambda g: -g.weight)
        return goals

    # --- Plan Operations ---

    def add_plan(self, plan: PlanData) -> None:
        """Add or update a plan."""
        is_new = plan.id not in self._plans

        if is_new:
            node = PlanNodeData(plan=plan, goal_id=plan.goal_id)
            self._plans[plan.id] = node

            # Add to parent goal's plan list
            if plan.goal_id in self._goals:
                if plan.id not in self._goals[plan.goal_id].plan_ids:
                    self._goals[plan.goal_id].plan_ids.append(plan.id)

            self._notify(GoalTreeEvent.PLAN_ADDED, {"plan_id": plan.id, "goal_id": plan.goal_id})
        else:
            self._plans[plan.id].plan = plan
            self._notify(GoalTreeEvent.PLAN_UPDATED, {"plan_id": plan.id})

    def remove_plan(self, plan_id: str) -> None:
        """Remove a plan and its children."""
        if plan_id not in self._plans:
            return

        plan_node = self._plans[plan_id]

        # Remove from parent goal's plan list
        if plan_node.goal_id in self._goals:
            goal_node = self._goals[plan_node.goal_id]
            if plan_id in goal_node.plan_ids:
                goal_node.plan_ids.remove(plan_id)

        # Note: We don't remove todos here since they can belong to multiple plans
        # Just remove the link

        # Remove bound sessions
        if plan_id in self._bound_sessions:
            del self._bound_sessions[plan_id]

        del self._plans[plan_id]
        self._notify(GoalTreeEvent.PLAN_REMOVED, {"plan_id": plan_id})

    def get_plan(self, plan_id: str) -> Optional[PlanNodeData]:
        """Get a plan by ID."""
        return self._plans.get(plan_id)

    def get_plans_for_goal(self, goal_id: str) -> list[PlanNodeData]:
        """Get all plans for a goal."""
        goal_node = self._goals.get(goal_id)
        if not goal_node:
            return []
        return [self._plans[pid] for pid in goal_node.plan_ids if pid in self._plans]

    # --- Todo Operations ---

    def add_todo(self, todo: TodoData, plan_ids: list[str] = None) -> None:
        """Add or update a todo."""
        is_new = todo.id not in self._todos
        plan_ids = plan_ids or []

        if is_new:
            node = TodoNodeData(todo=todo, plan_ids=plan_ids)
            self._todos[todo.id] = node

            # Add to parent plans' todo lists
            for plan_id in plan_ids:
                if plan_id in self._plans:
                    if todo.id not in self._plans[plan_id].todo_ids:
                        self._plans[plan_id].todo_ids.append(todo.id)

            self._notify(GoalTreeEvent.TODO_ADDED, {"todo_id": todo.id, "plan_ids": plan_ids})
        else:
            self._todos[todo.id].todo = todo
            # Update plan links if provided
            if plan_ids:
                self._todos[todo.id].plan_ids = plan_ids
            self._notify(GoalTreeEvent.TODO_UPDATED, {"todo_id": todo.id})

    def remove_todo(self, todo_id: str) -> None:
        """Remove a todo."""
        if todo_id not in self._todos:
            return

        todo_node = self._todos[todo_id]

        # Remove from parent plans' todo lists
        for plan_id in todo_node.plan_ids:
            if plan_id in self._plans:
                plan_node = self._plans[plan_id]
                if todo_id in plan_node.todo_ids:
                    plan_node.todo_ids.remove(todo_id)

        # Remove bound sessions
        if todo_id in self._bound_sessions:
            del self._bound_sessions[todo_id]

        del self._todos[todo_id]
        self._notify(GoalTreeEvent.TODO_REMOVED, {"todo_id": todo_id})

    def get_todo(self, todo_id: str) -> Optional[TodoNodeData]:
        """Get a todo by ID."""
        return self._todos.get(todo_id)

    def get_todos_for_plan(self, plan_id: str) -> list[TodoNodeData]:
        """Get all todos for a plan."""
        plan_node = self._plans.get(plan_id)
        if not plan_node:
            return []
        return [self._todos[tid] for tid in plan_node.todo_ids if tid in self._todos]

    def set_todo_priority(self, todo_id: str, priority: float) -> None:
        """Set the computed priority for a todo."""
        if todo_id in self._todos:
            self._todos[todo_id].priority = priority

    # --- Session Binding Operations ---

    def bind_session(
        self,
        entity_type: str,
        entity_id: str,
        session: SessionNodeData,
    ) -> None:
        """Bind a session to an entity (goal, plan, or todo)."""
        # Remove from unbound if present
        self._unbound_sessions = [s for s in self._unbound_sessions if s.session_id != session.session_id]

        # Add to entity's bound sessions
        if entity_id not in self._bound_sessions:
            self._bound_sessions[entity_id] = []

        # Check if already bound
        existing = next((s for s in self._bound_sessions[entity_id] if s.session_id == session.session_id), None)
        is_update = existing is not None
        if existing:
            # Update existing
            idx = self._bound_sessions[entity_id].index(existing)
            self._bound_sessions[entity_id][idx] = session
        else:
            self._bound_sessions[entity_id].append(session)

        # Update entity's bound_session_ids
        if entity_type == "goal" and entity_id in self._goals:
            if session.session_id not in self._goals[entity_id].bound_session_ids:
                self._goals[entity_id].bound_session_ids.append(session.session_id)
        elif entity_type == "plan" and entity_id in self._plans:
            if session.session_id not in self._plans[entity_id].bound_session_ids:
                self._plans[entity_id].bound_session_ids.append(session.session_id)
        elif entity_type == "todo" and entity_id in self._todos:
            if session.session_id not in self._todos[entity_id].bound_session_ids:
                self._todos[entity_id].bound_session_ids.append(session.session_id)

        self._all_session_ids.add(session.session_id)

        if is_update:
            # Just updating an existing session's data (title, tokens, etc.)
            self._notify(GoalTreeEvent.SESSION_UPDATED, {"session_id": session.session_id})
        else:
            # New binding
            self._notify(GoalTreeEvent.SESSION_BOUND, {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "session_id": session.session_id,
            })

    def unbind_session(self, entity_id: str, session_id: str) -> None:
        """Unbind a session from an entity."""
        if entity_id in self._bound_sessions:
            self._bound_sessions[entity_id] = [
                s for s in self._bound_sessions[entity_id]
                if s.session_id != session_id
            ]

        # Remove from entity's bound_session_ids
        for goal in self._goals.values():
            if session_id in goal.bound_session_ids:
                goal.bound_session_ids.remove(session_id)
        for plan in self._plans.values():
            if session_id in plan.bound_session_ids:
                plan.bound_session_ids.remove(session_id)
        for todo in self._todos.values():
            if session_id in todo.bound_session_ids:
                todo.bound_session_ids.remove(session_id)

        self._notify(GoalTreeEvent.SESSION_UNBOUND, {
            "entity_id": entity_id,
            "session_id": session_id,
        })

    def add_unbound_session(self, session: SessionNodeData) -> None:
        """Add a session to the unbound sessions list."""
        # Check if already in unbound
        existing = next((s for s in self._unbound_sessions if s.session_id == session.session_id), None)
        if existing:
            idx = self._unbound_sessions.index(existing)
            self._unbound_sessions[idx] = session
            # Notify observers that session was updated
            self._notify(GoalTreeEvent.SESSION_UPDATED, {"session_id": session.session_id})
        else:
            self._unbound_sessions.append(session)

        self._all_session_ids.add(session.session_id)

    def remove_unbound_session(self, session_id: str) -> None:
        """Remove a session from the unbound sessions list."""
        self._unbound_sessions = [s for s in self._unbound_sessions if s.session_id != session_id]
        self._all_session_ids.discard(session_id)
        self._notify(GoalTreeEvent.SESSION_UNBOUND, {"session_id": session_id})

    def get_bound_sessions(self, entity_id: str) -> list[SessionNodeData]:
        """Get sessions bound to an entity."""
        return self._bound_sessions.get(entity_id, [])

    def get_unbound_sessions(self) -> list[SessionNodeData]:
        """Get all unbound sessions."""
        return self._unbound_sessions.copy()

    def is_session_bound(self, session_id: str) -> bool:
        """Check if a session is bound to any entity."""
        for sessions in self._bound_sessions.values():
            if any(s.session_id == session_id for s in sessions):
                return True
        return False

    def get_session_binding(self, session_id: str) -> Optional[tuple[str, str]]:
        """Get the entity a session is bound to.

        Returns (entity_type, entity_id) or None if unbound.
        """
        for entity_id, sessions in self._bound_sessions.items():
            if any(s.session_id == session_id for s in sessions):
                # Determine entity type
                if entity_id in self._goals:
                    return ("goal", entity_id)
                elif entity_id in self._plans:
                    return ("plan", entity_id)
                elif entity_id in self._todos:
                    return ("todo", entity_id)
        return None

    # --- Selection ---

    def select_entity(self, entity_type: str, entity_id: str) -> None:
        """Select an entity in the tree."""
        prev_type = self._selected_entity_type
        prev_id = self._selected_entity_id

        self._selected_entity_type = entity_type
        self._selected_entity_id = entity_id

        self._notify(GoalTreeEvent.ENTITY_SELECTED, {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "prev_entity_type": prev_type,
            "prev_entity_id": prev_id,
        })

    def get_selected_entity(self) -> Optional[tuple[str, str]]:
        """Get the currently selected entity.

        Returns (entity_type, entity_id) or None.
        """
        if self._selected_entity_type and self._selected_entity_id:
            return (self._selected_entity_type, self._selected_entity_id)
        return None

    # --- Bulk Operations ---

    def clear(self) -> None:
        """Clear all state."""
        self._goals.clear()
        self._plans.clear()
        self._todos.clear()
        self._bound_sessions.clear()
        self._unbound_sessions.clear()
        self._all_session_ids.clear()
        self._selected_entity_id = None
        self._selected_entity_type = None
        self._notify(GoalTreeEvent.FULL_REBUILD, {})

    def request_rebuild(self) -> None:
        """Request that all observers rebuild their views."""
        self._notify(GoalTreeEvent.FULL_REBUILD, {})

    # --- Aggregate Stats ---

    def get_stats(self) -> dict[str, int]:
        """Get aggregate statistics for the tree."""
        active_goals = sum(1 for g in self._goals.values() if g.status == "active")
        active_plans = sum(1 for p in self._plans.values() if p.status == "active")
        pending_todos = sum(1 for t in self._todos.values() if t.status == "pending")
        in_progress_todos = sum(1 for t in self._todos.values() if t.status == "in_progress")

        return {
            "total_goals": len(self._goals),
            "active_goals": active_goals,
            "total_plans": len(self._plans),
            "active_plans": active_plans,
            "total_todos": len(self._todos),
            "pending_todos": pending_todos,
            "in_progress_todos": in_progress_todos,
            "bound_sessions": sum(len(s) for s in self._bound_sessions.values()),
            "unbound_sessions": len(self._unbound_sessions),
        }
