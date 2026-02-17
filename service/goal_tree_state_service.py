"""WebSocket-exposed service for goal tree state management.

This service wraps GoalTreeState and exposes its functionality via WebSocket RPC.
The @ws_expose decorators mark methods for client generation.

Example usage:
    goal_tree_state = GoalTreeState()
    service = GoalTreeStateService(goal_tree_state)

    # Service methods are called via WebSocket RPC:
    # {"id": "1", "method": "getGoal", "params": {"goalId": "abc"}}
    # -> {"id": "1", "result": {"id": "abc", "title": "...", ...}}

    # Events are pushed to subscribed clients:
    # {"event": "goalAdded", "data": {"goalId": "abc"}}
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Any, Optional
import uuid

from codegen import ws_service, ws_expose, ws_event, ws_type
from core.goal_tree_state import (
    GoalTreeState,
    GoalTreeEvent,
    GoalNodeData,
    PlanNodeData,
    TodoNodeData,
    SessionNodeData,
)
from storage_schema import GoalData, PlanData, TodoData, SessionBinding
from core.smart_todo import create_todo_with_llm_placement
from core.async_storage import get_goal_storage


# =============================================================================
# Wire Types for WebSocket Codegen
# =============================================================================


@ws_type
@dataclass
class GoalInfo:
    """Goal information for display."""

    id: str
    title: str
    description: str
    weight: int
    status: str
    acceptance_criteria: list[str]
    created_at: str
    updated_at: str
    completed_at: str | None = None
    parent_goal_id: str | None = None
    plan_ids: list[str] = field(default_factory=list)
    child_goal_ids: list[str] = field(default_factory=list)
    bound_session_ids: list[str] = field(default_factory=list)
    is_expanded: bool = False


@ws_type
@dataclass
class PlanInfo:
    """Plan information for display."""

    id: str
    goal_id: str
    title: str
    description: str
    status: str
    created_at: str
    updated_at: str
    completed_at: str | None = None
    postmortem: str | None = None
    todo_ids: list[str] = field(default_factory=list)
    bound_session_ids: list[str] = field(default_factory=list)
    is_expanded: bool = False


@ws_type
@dataclass
class TodoInfo:
    """Todo information for display."""

    id: str
    title: str
    description: str
    status: str
    is_spike: bool
    created_at: str
    updated_at: str
    completed_at: str | None = None
    timebox_minutes: int | None = None
    plan_ids: list[str] = field(default_factory=list)
    bound_session_ids: list[str] = field(default_factory=list)
    dependency_ids: list[str] = field(default_factory=list)
    is_expanded: bool = False
    priority: float = 0.0


@ws_type
@dataclass
class SessionBindingInfo:
    """Session binding information for display."""

    session_id: str
    name: str
    token_count: int
    is_current: bool
    is_streaming: bool
    fork_status: str
    binding_role: str


@ws_type
@dataclass
class GoalTreeStats:
    """Aggregate statistics for the goal tree."""

    total_goals: int
    active_goals: int
    total_plans: int
    active_plans: int
    total_todos: int
    pending_todos: int
    in_progress_todos: int
    bound_sessions: int
    unbound_sessions: int


@ws_type
@dataclass
class GoalProgress:
    """Progress information for a goal."""

    completed: int
    total: int


@ws_type
@dataclass
class SelectedEntity:
    """Currently selected entity in the tree."""

    entity_type: str  # "goal", "plan", "todo", "session"
    entity_id: str


@ws_type
@dataclass
class GoalTreeEventData:
    """Event payload for goal tree state changes."""

    event_type: str  # Maps to GoalTreeEvent enum value
    entity_type: str | None = None  # "goal", "plan", "todo", "session"
    entity_id: str | None = None
    data: dict = field(default_factory=dict)


@ws_type
@dataclass
class SmartTodoResult:
    """Result from creating a todo with LLM-assisted plan placement."""

    success: bool
    message: str
    todo_id: str | None = None
    todo_title: str | None = None
    plan_id: str | None = None
    plan_title: str | None = None
    goal_id: str | None = None
    goal_title: str | None = None


# =============================================================================
# Service Class
# =============================================================================


@ws_service
class GoalTreeStateService:
    """WebSocket-exposed service for goal tree state management.

    Provides read/write access to goals, plans, todos, and session bindings,
    with real-time event subscriptions for state changes.
    """

    def __init__(self, goal_tree_state: GoalTreeState, llm_runner=None):
        """Initialize service with a GoalTreeState instance.

        Args:
            goal_tree_state: The GoalTreeState to expose via WebSocket
            llm_runner: Optional LLM runner for smart todo placement.
                       Can be set later via set_llm_runner().
        """
        self._state = goal_tree_state
        self._llm_runner = llm_runner
        self._event_handlers: list[Callable[[str, dict], None]] = []

        # Wire up GoalTreeState observer to emit WebSocket events
        goal_tree_state.add_observer(self._on_tree_event)

    def set_llm_runner(self, runner) -> None:
        """Set the LLM runner for smart todo placement.

        Args:
            runner: A runner implementing stream_response for LLM calls
        """
        self._llm_runner = runner

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Register a handler for WebSocket events.

        The handler will be called with (event_name, data) for each event.
        """
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def _on_tree_event(self, event: GoalTreeEvent, data: dict) -> None:
        """Convert GoalTreeState events to WebSocket events."""
        # Map GoalTreeEvent enum to camelCase wire name
        event_name = self._tree_event_to_wire_name(event)

        for handler in self._event_handlers:
            handler(event_name, data)

    def _tree_event_to_wire_name(self, event: GoalTreeEvent) -> str:
        """Convert GoalTreeEvent enum to camelCase wire name."""
        # GoalTreeEvent.GOAL_ADDED -> "goalAdded"
        parts = event.value.split("_")
        return parts[0] + "".join(p.title() for p in parts[1:])

    # --- Helper Methods ---

    def _goal_node_to_info(self, node: GoalNodeData) -> GoalInfo:
        """Convert GoalNodeData to GoalInfo wire type."""
        return GoalInfo(
            id=node.id,
            title=node.title,
            description=node.goal.description,
            weight=node.weight,
            status=node.status,
            acceptance_criteria=node.goal.acceptance_criteria,
            created_at=node.goal.created_at,
            updated_at=node.goal.updated_at,
            completed_at=node.goal.completed_at,
            parent_goal_id=node.parent_goal_id,
            plan_ids=node.plan_ids,
            child_goal_ids=node.child_goal_ids,
            bound_session_ids=node.bound_session_ids,
            is_expanded=node.is_expanded,
        )

    def _plan_node_to_info(self, node: PlanNodeData) -> PlanInfo:
        """Convert PlanNodeData to PlanInfo wire type."""
        return PlanInfo(
            id=node.id,
            goal_id=node.goal_id,
            title=node.title,
            description=node.plan.description,
            status=node.status,
            created_at=node.plan.created_at,
            updated_at=node.plan.updated_at,
            completed_at=node.plan.completed_at,
            postmortem=node.plan.postmortem,
            todo_ids=node.todo_ids,
            bound_session_ids=node.bound_session_ids,
            is_expanded=node.is_expanded,
        )

    def _todo_node_to_info(self, node: TodoNodeData) -> TodoInfo:
        """Convert TodoNodeData to TodoInfo wire type."""
        return TodoInfo(
            id=node.id,
            title=node.title,
            description=node.todo.description,
            status=node.status,
            is_spike=node.is_spike,
            created_at=node.todo.created_at,
            updated_at=node.todo.updated_at,
            completed_at=node.todo.completed_at,
            timebox_minutes=node.todo.timebox_minutes,
            plan_ids=node.plan_ids,
            bound_session_ids=node.bound_session_ids,
            dependency_ids=node.dependency_ids,
            is_expanded=node.is_expanded,
            priority=node.priority,
        )

    def _session_node_to_info(self, node: SessionNodeData) -> SessionBindingInfo:
        """Convert SessionNodeData to SessionBindingInfo wire type."""
        return SessionBindingInfo(
            session_id=node.session_id,
            name=node.name,
            token_count=node.token_count,
            is_current=node.is_current,
            is_streaming=node.is_streaming,
            fork_status=node.fork_status,
            binding_role=node.binding_role,
        )

    # --- Goal Operations ---

    @ws_expose
    async def get_goal(self, goal_id: str) -> GoalInfo | None:
        """Get goal information by ID.

        Args:
            goal_id: The goal ID to look up

        Returns:
            Goal info if found, None otherwise
        """
        node = self._state.get_goal(goal_id)
        if not node:
            return None
        return self._goal_node_to_info(node)

    @ws_expose
    async def get_all_goals(self) -> list[GoalInfo]:
        """Get all goals sorted by weight (descending).

        Returns:
            List of all goal info objects
        """
        nodes = self._state.get_all_goals()
        return [self._goal_node_to_info(n) for n in nodes]

    @ws_expose
    async def get_root_goals(self) -> list[GoalInfo]:
        """Get root-level goals (goals with no parent).

        Returns:
            List of root goal info objects sorted by weight
        """
        nodes = self._state.get_root_goals()
        return [self._goal_node_to_info(n) for n in nodes]

    @ws_expose
    async def get_child_goals(self, goal_id: str) -> list[GoalInfo]:
        """Get child goals for a parent goal.

        Args:
            goal_id: The parent goal ID

        Returns:
            List of child goal info objects sorted by weight
        """
        nodes = self._state.get_child_goals(goal_id)
        return [self._goal_node_to_info(n) for n in nodes]

    @ws_expose
    async def add_goal(self, goal: dict) -> None:
        """Add or update a goal.

        Args:
            goal: Goal data as dictionary (will be converted to GoalData)
        """
        goal_data = GoalData(
            id=goal["id"],
            title=goal["title"],
            description=goal["description"],
            weight=goal["weight"],
            status=goal["status"],
            acceptance_criteria=goal["acceptance_criteria"],
            created_at=goal["created_at"],
            updated_at=goal["updated_at"],
            completed_at=goal.get("completed_at"),
            supersedes_id=goal.get("supersedes_id"),
            parent_goal_id=goal.get("parent_goal_id"),
        )
        self._state.add_goal(goal_data)

    @ws_expose
    async def remove_goal(self, goal_id: str) -> None:
        """Remove a goal and its children.

        Args:
            goal_id: The goal ID to remove
        """
        self._state.remove_goal(goal_id)

    @ws_expose
    async def get_goal_progress(self, goal_id: str) -> GoalProgress:
        """Get progress for a goal.

        Args:
            goal_id: The goal ID

        Returns:
            Progress as (completed_todos, total_todos)
        """
        completed, total = self._state.get_goal_progress(goal_id)
        return GoalProgress(completed=completed, total=total)

    # --- Plan Operations ---

    @ws_expose
    async def get_plan(self, plan_id: str) -> PlanInfo | None:
        """Get plan information by ID.

        Args:
            plan_id: The plan ID to look up

        Returns:
            Plan info if found, None otherwise
        """
        node = self._state.get_plan(plan_id)
        if not node:
            return None
        return self._plan_node_to_info(node)

    @ws_expose
    async def get_plans_for_goal(self, goal_id: str) -> list[PlanInfo]:
        """Get all plans for a goal.

        Args:
            goal_id: The parent goal ID

        Returns:
            List of plan info objects
        """
        nodes = self._state.get_plans_for_goal(goal_id)
        return [self._plan_node_to_info(n) for n in nodes]

    @ws_expose
    async def add_plan(self, plan: dict) -> None:
        """Add or update a plan.

        Args:
            plan: Plan data as dictionary (will be converted to PlanData)
        """
        plan_data = PlanData(
            id=plan["id"],
            goal_id=plan["goal_id"],
            title=plan["title"],
            description=plan["description"],
            status=plan["status"],
            created_at=plan["created_at"],
            updated_at=plan["updated_at"],
            completed_at=plan.get("completed_at"),
            postmortem=plan.get("postmortem"),
        )
        self._state.add_plan(plan_data)

    @ws_expose
    async def remove_plan(self, plan_id: str) -> None:
        """Remove a plan.

        Args:
            plan_id: The plan ID to remove
        """
        self._state.remove_plan(plan_id)

    # --- Todo Operations ---

    @ws_expose
    async def get_todo(self, todo_id: str) -> TodoInfo | None:
        """Get todo information by ID.

        Args:
            todo_id: The todo ID to look up

        Returns:
            Todo info if found, None otherwise
        """
        node = self._state.get_todo(todo_id)
        if not node:
            return None
        return self._todo_node_to_info(node)

    @ws_expose
    async def get_todos_for_plan(self, plan_id: str) -> list[TodoInfo]:
        """Get all todos for a plan.

        Args:
            plan_id: The parent plan ID

        Returns:
            List of todo info objects
        """
        nodes = self._state.get_todos_for_plan(plan_id)
        return [self._todo_node_to_info(n) for n in nodes]

    @ws_expose
    async def add_todo(self, todo: dict, plan_ids: list[str] | None = None) -> None:
        """Add or update a todo.

        Args:
            todo: Todo data as dictionary (will be converted to TodoData)
            plan_ids: Optional list of plan IDs to link the todo to
        """
        todo_data = TodoData(
            id=todo["id"],
            title=todo["title"],
            description=todo["description"],
            status=todo["status"],
            is_spike=todo["is_spike"],
            created_at=todo["created_at"],
            updated_at=todo["updated_at"],
            completed_at=todo.get("completed_at"),
            timebox_minutes=todo.get("timebox_minutes"),
            completed_by_session=todo.get("completed_by_session"),
            completed_by=todo.get("completed_by"),
        )
        self._state.add_todo(todo_data, plan_ids or [])

    @ws_expose
    async def remove_todo(self, todo_id: str) -> None:
        """Remove a todo.

        Args:
            todo_id: The todo ID to remove
        """
        self._state.remove_todo(todo_id)

    @ws_expose
    async def set_todo_priority(self, todo_id: str, priority: float) -> None:
        """Set the computed priority for a todo.

        Args:
            todo_id: The todo ID
            priority: The priority value
        """
        self._state.set_todo_priority(todo_id, priority)

    @ws_expose
    async def create_smart_todo(
        self,
        title: str,
        description: str = "",
        is_spike: bool = False,
        timebox_minutes: int | None = None,
    ) -> SmartTodoResult:
        """Create a todo with LLM-assisted plan placement.

        Uses an LLM to analyze the todo's title and description and automatically
        place it under the most appropriate plan based on existing goals and plans.

        This is useful for quick todo creation from web/mobile where the user
        doesn't need to manually select a plan - the LLM figures out where it belongs.

        Args:
            title: Todo title (required, max 80 chars)
            description: Todo description (optional)
            is_spike: Whether this is a timeboxed exploration task
            timebox_minutes: For spikes, the maximum time to spend

        Returns:
            SmartTodoResult with success status, created todo info, and placement details
        """
        if not self._llm_runner:
            return SmartTodoResult(
                success=False,
                message="LLM runner not available. Cannot determine plan placement.",
            )

        try:
            todo, plan, message = await create_todo_with_llm_placement(
                title=title,
                description=description,
                is_spike=is_spike,
                timebox_minutes=timebox_minutes,
                llm_runner=self._llm_runner,
            )

            if todo is None:
                return SmartTodoResult(
                    success=False,
                    message=message,
                )

            # Also add to in-memory state for immediate UI update
            if plan:
                self._state.add_todo(todo, [plan.id])

            # Get goal info
            goal_id = plan.goal_id if plan else None
            goal_title = None
            if goal_id:
                goal_node = self._state.get_goal(goal_id)
                if goal_node:
                    goal_title = goal_node.title

            return SmartTodoResult(
                success=True,
                message=message,
                todo_id=todo.id,
                todo_title=todo.title,
                plan_id=plan.id if plan else None,
                plan_title=plan.title if plan else None,
                goal_id=goal_id,
                goal_title=goal_title,
            )

        except Exception as e:
            return SmartTodoResult(
                success=False,
                message=f"Error creating todo: {e}",
            )

    # --- Session Binding Operations ---

    @ws_expose
    async def bind_session(
        self,
        entity_type: str,
        entity_id: str,
        session_id: str,
        name: str,
        binding_role: str = "",
        token_count: int = 0,
        is_current: bool = False,
        is_streaming: bool = False,
        fork_status: str = "",
    ) -> None:
        """Bind a session to an entity.

        Args:
            entity_type: Type of entity ("goal", "plan", "todo")
            entity_id: ID of the entity
            session_id: ID of the session to bind
            name: Display name for the session
            binding_role: Role of the binding (e.g., "implementation")
            token_count: Token count for the session
            is_current: Whether this is the current session
            is_streaming: Whether the session is streaming
            fork_status: Fork status of the session
        """
        # Update UI state
        session = SessionNodeData(
            session_id=session_id,
            name=name,
            token_count=token_count,
            is_current=is_current,
            is_streaming=is_streaming,
            fork_status=fork_status,
            binding_role=binding_role,
        )
        self._state.bind_session(entity_type, entity_id, session)

        # Persist binding to storage
        storage = await get_goal_storage()
        binding = SessionBinding(
            id=str(uuid.uuid4()),
            session_id=session_id,
            entity_type=entity_type,
            entity_id=entity_id,
            role=binding_role or "implementation",
            created_at=datetime.now().isoformat(),
        )
        await storage.save_session_binding(binding)

    @ws_expose
    async def unbind_session(self, entity_id: str, session_id: str) -> None:
        """Unbind a session from an entity.

        Args:
            entity_id: ID of the entity
            session_id: ID of the session to unbind
        """
        self._state.unbind_session(entity_id, session_id)

    @ws_expose
    async def add_unbound_session(
        self,
        session_id: str,
        name: str,
        token_count: int = 0,
        is_current: bool = False,
        is_streaming: bool = False,
        fork_status: str = "",
    ) -> None:
        """Add a session to the unbound sessions list.

        Args:
            session_id: ID of the session
            name: Display name for the session
            token_count: Token count for the session
            is_current: Whether this is the current session
            is_streaming: Whether the session is streaming
            fork_status: Fork status of the session
        """
        session = SessionNodeData(
            session_id=session_id,
            name=name,
            token_count=token_count,
            is_current=is_current,
            is_streaming=is_streaming,
            fork_status=fork_status,
        )
        self._state.add_unbound_session(session)

    @ws_expose
    async def remove_unbound_session(self, session_id: str) -> None:
        """Remove a session from the unbound sessions list.

        Args:
            session_id: ID of the session to remove
        """
        self._state.remove_unbound_session(session_id)

    @ws_expose
    async def get_bound_sessions(self, entity_id: str) -> list[SessionBindingInfo]:
        """Get sessions bound to an entity.

        Args:
            entity_id: ID of the entity

        Returns:
            List of session binding info objects
        """
        sessions = self._state.get_bound_sessions(entity_id)
        return [self._session_node_to_info(s) for s in sessions]

    @ws_expose
    async def get_unbound_sessions(self) -> list[SessionBindingInfo]:
        """Get all unbound sessions.

        Returns:
            List of session binding info objects
        """
        sessions = self._state.get_unbound_sessions()
        return [self._session_node_to_info(s) for s in sessions]

    @ws_expose
    async def is_session_bound(self, session_id: str) -> bool:
        """Check if a session is bound to any entity.

        Args:
            session_id: ID of the session

        Returns:
            True if bound, False otherwise
        """
        return self._state.is_session_bound(session_id)

    @ws_expose
    async def get_session_binding(
        self, session_id: str
    ) -> tuple[str, str] | None:
        """Get the entity a session is bound to.

        Args:
            session_id: ID of the session

        Returns:
            (entity_type, entity_id) tuple or None if unbound
        """
        return self._state.get_session_binding(session_id)

    # --- Selection ---

    @ws_expose
    async def select_entity(self, entity_type: str, entity_id: str) -> None:
        """Select an entity in the tree.

        Args:
            entity_type: Type of entity ("goal", "plan", "todo", "session")
            entity_id: ID of the entity
        """
        self._state.select_entity(entity_type, entity_id)

    @ws_expose
    async def get_selected_entity(self) -> SelectedEntity | None:
        """Get the currently selected entity.

        Returns:
            Selected entity info or None
        """
        result = self._state.get_selected_entity()
        if result:
            return SelectedEntity(entity_type=result[0], entity_id=result[1])
        return None

    # --- Collapsed State ---

    @ws_expose
    async def is_collapsed(self, entity_id: str) -> bool:
        """Check if a node is collapsed.

        Args:
            entity_id: ID of the entity

        Returns:
            True if collapsed, False otherwise
        """
        return self._state.is_collapsed(entity_id)

    @ws_expose
    async def set_collapsed(self, entity_id: str, collapsed: bool) -> None:
        """Set the collapsed state of a node.

        Args:
            entity_id: ID of the entity
            collapsed: True to collapse, False to expand
        """
        self._state.set_collapsed(entity_id, collapsed)

    @ws_expose
    async def toggle_collapsed(self, entity_id: str) -> bool:
        """Toggle the collapsed state of a node.

        Args:
            entity_id: ID of the entity

        Returns:
            The new collapsed state
        """
        return self._state.toggle_collapsed(entity_id)

    @ws_expose
    async def get_collapsed_ids(self) -> list[str]:
        """Get list of all collapsed node IDs.

        Returns:
            List of entity IDs that are collapsed
        """
        return self._state.get_collapsed_ids()

    @ws_expose
    async def set_collapsed_ids(self, collapsed_ids: list[str]) -> None:
        """Set the collapsed node IDs.

        Args:
            collapsed_ids: List of entity IDs that should be collapsed
        """
        self._state.set_collapsed_ids(collapsed_ids)

    # --- Statistics ---

    @ws_expose
    async def get_stats(self) -> GoalTreeStats:
        """Get aggregate statistics for the tree.

        Returns:
            Statistics object
        """
        stats = self._state.get_stats()
        return GoalTreeStats(
            total_goals=stats["total_goals"],
            active_goals=stats["active_goals"],
            total_plans=stats["total_plans"],
            active_plans=stats["active_plans"],
            total_todos=stats["total_todos"],
            pending_todos=stats["pending_todos"],
            in_progress_todos=stats["in_progress_todos"],
            bound_sessions=stats["bound_sessions"],
            unbound_sessions=stats["unbound_sessions"],
        )

    # --- Bulk Operations ---

    @ws_expose
    async def clear(self) -> None:
        """Clear all state."""
        self._state.clear()

    @ws_expose
    async def request_rebuild(self) -> None:
        """Request that all observers rebuild their views."""
        self._state.request_rebuild()

    @ws_expose
    async def begin_batch_loading(self) -> None:
        """Begin batch loading mode - suppress individual notifications."""
        self._state.begin_batch_loading()

    @ws_expose
    async def end_batch_loading(self) -> None:
        """End batch loading mode and trigger a full rebuild."""
        self._state.end_batch_loading()

    # --- Events ---

    @ws_event
    async def on_goal_added(self) -> GoalTreeEventData:
        """Emitted when a goal is added."""
        ...

    @ws_event
    async def on_goal_updated(self) -> GoalTreeEventData:
        """Emitted when a goal is updated."""
        ...

    @ws_event
    async def on_goal_removed(self) -> GoalTreeEventData:
        """Emitted when a goal is removed."""
        ...

    @ws_event
    async def on_plan_added(self) -> GoalTreeEventData:
        """Emitted when a plan is added."""
        ...

    @ws_event
    async def on_plan_updated(self) -> GoalTreeEventData:
        """Emitted when a plan is updated."""
        ...

    @ws_event
    async def on_plan_removed(self) -> GoalTreeEventData:
        """Emitted when a plan is removed."""
        ...

    @ws_event
    async def on_todo_added(self) -> GoalTreeEventData:
        """Emitted when a todo is added."""
        ...

    @ws_event
    async def on_todo_updated(self) -> GoalTreeEventData:
        """Emitted when a todo is updated."""
        ...

    @ws_event
    async def on_todo_removed(self) -> GoalTreeEventData:
        """Emitted when a todo is removed."""
        ...

    @ws_event
    async def on_session_bound(self) -> GoalTreeEventData:
        """Emitted when a session is bound to an entity."""
        ...

    @ws_event
    async def on_session_unbound(self) -> GoalTreeEventData:
        """Emitted when a session is unbound from an entity."""
        ...

    @ws_event
    async def on_session_updated(self) -> GoalTreeEventData:
        """Emitted when a session's metadata changes."""
        ...

    @ws_event
    async def on_entity_selected(self) -> GoalTreeEventData:
        """Emitted when an entity is selected."""
        ...

    @ws_event
    async def on_full_rebuild(self) -> GoalTreeEventData:
        """Emitted when a full rebuild is requested."""
        ...
