"""
Synchronization layer between GoalTreeState, TreeState, and goal storage.

This module handles:
1. Loading goals/plans/todos from storage into GoalTreeState
2. Loading session bindings and associating sessions with entities
3. Syncing session metadata from TreeState to GoalTreeState
4. Keeping the goal tree updated when sessions or bindings change
"""

from typing import Optional
import asyncio

from core.goal_tree_state import (
    GoalTreeState, SessionNodeData,
)
from core.tree_state import TreeState, SessionData
from core.async_storage import get_goal_storage, GoalStorage
from storage_schema import SessionBinding


async def load_goal_tree_data(
    goal_state: GoalTreeState,
    tree_state: TreeState,
    storage: Optional[GoalStorage] = None,
) -> None:
    """Load all goal/plan/todo data and session bindings into GoalTreeState.

    This is the main entry point for populating the goal tree.

    Args:
        goal_state: The GoalTreeState to populate
        tree_state: The TreeState containing session data
        storage: Optional GoalStorage instance (will be fetched if not provided)
    """
    if storage is None:
        storage = await get_goal_storage()

    # Clear existing state
    goal_state.clear()

    # Load goals
    goals = await storage.list_goals()
    for goal in goals:
        goal_state.add_goal(goal)

    # Load plans
    plans = await storage.list_plans()
    for plan in plans:
        goal_state.add_plan(plan)

    # Load todos with their plan links
    todos = await storage.list_todos(include_spikes=True)
    for todo in todos:
        # Get plan IDs for this todo
        plan_ids = await storage.get_plans_for_todo(todo.id)
        goal_state.add_todo(todo, plan_ids)

    # Load session bindings and associate sessions
    await sync_session_bindings(goal_state, tree_state, storage)


async def sync_session_bindings(
    goal_state: GoalTreeState,
    tree_state: TreeState,
    storage: Optional[GoalStorage] = None,
) -> None:
    """Sync session bindings from storage to GoalTreeState.

    Associates sessions with their bound entities, and places unbound
    sessions in the unbound section.

    Args:
        goal_state: The GoalTreeState to update
        tree_state: The TreeState containing session data
        storage: Optional GoalStorage instance
    """
    if storage is None:
        storage = await get_goal_storage()

    # Track which sessions are bound
    bound_session_ids: set[str] = set()

    # Get all active bindings
    all_sessions = tree_state.get_all_sessions()

    for session_id, session_data in all_sessions.items():
        bindings = await storage.get_bindings_for_session(session_id, active_only=True)

        if bindings:
            # Session is bound - add to each bound entity
            for binding in bindings:
                session_node = _create_session_node(session_data, binding.role)
                goal_state.bind_session(
                    binding.entity_type,
                    binding.entity_id,
                    session_node,
                )
                bound_session_ids.add(session_id)
        else:
            # Session is unbound
            session_node = _create_session_node(session_data, "")
            goal_state.add_unbound_session(session_node)


def _create_session_node(session_data: SessionData, role: str) -> SessionNodeData:
    """Create a SessionNodeData from TreeState's SessionData.

    Args:
        session_data: The session data from TreeState
        role: The binding role (empty if unbound)

    Returns:
        SessionNodeData suitable for GoalTreeState
    """
    # Determine display name
    if session_data.fork_name:
        name = session_data.fork_name
    elif session_data.title:
        name = session_data.title
    else:
        name = session_data.id[:8]

    return SessionNodeData(
        session_id=session_data.id,
        name=name,
        token_count=session_data.cached_context_tokens,
        is_current=session_data.is_current,
        is_streaming=session_data.is_streaming,
        fork_status=session_data.fork_status,
        binding_role=role,
    )


async def refresh_session_in_goal_tree(
    goal_state: GoalTreeState,
    tree_state: TreeState,
    session_id: str,
    storage: Optional[GoalStorage] = None,
) -> None:
    """Refresh a single session's data in the goal tree.

    Call this when a session's metadata changes (tokens, streaming status, etc.)

    Args:
        goal_state: The GoalTreeState to update
        tree_state: The TreeState containing session data
        session_id: The session to refresh
        storage: Optional GoalStorage instance
    """
    if storage is None:
        storage = await get_goal_storage()

    session_data = tree_state.get_session(session_id)
    if not session_data:
        return

    # Get current binding
    bindings = await storage.get_bindings_for_session(session_id, active_only=True)

    if bindings:
        # Session is bound
        for binding in bindings:
            session_node = _create_session_node(session_data, binding.role)
            goal_state.bind_session(
                binding.entity_type,
                binding.entity_id,
                session_node,
            )
    else:
        # Session is unbound
        # First remove from any existing bindings
        existing = goal_state.get_session_binding(session_id)
        if existing:
            goal_state.unbind_session(existing[1], session_id)

        session_node = _create_session_node(session_data, "")
        goal_state.add_unbound_session(session_node)


async def on_session_bound(
    goal_state: GoalTreeState,
    tree_state: TreeState,
    binding: SessionBinding,
) -> None:
    """Handle a new session binding.

    Call this when a session is bound to an entity.
    """
    session_data = tree_state.get_session(binding.session_id)
    if not session_data:
        return

    session_node = _create_session_node(session_data, binding.role)
    goal_state.bind_session(
        binding.entity_type,
        binding.entity_id,
        session_node,
    )


async def on_session_unbound(
    goal_state: GoalTreeState,
    tree_state: TreeState,
    session_id: str,
    entity_id: str,
) -> None:
    """Handle a session being unbound.

    Call this when a session binding is released.
    """
    goal_state.unbind_session(entity_id, session_id)

    # Check if session is still bound to anything else
    session_data = tree_state.get_session(session_id)
    if session_data and not goal_state.is_session_bound(session_id):
        # Move to unbound
        session_node = _create_session_node(session_data, "")
        goal_state.add_unbound_session(session_node)


class GoalTreeSyncManager:
    """Manager class that keeps GoalTreeState in sync with storage and TreeState.

    Usage:
        sync_manager = GoalTreeSyncManager(goal_state, tree_state)
        await sync_manager.initial_load()

        # When TreeState changes:
        sync_manager.on_tree_state_event(event, data)
    """

    def __init__(self, goal_state: GoalTreeState, tree_state: TreeState):
        self._goal_state = goal_state
        self._tree_state = tree_state
        self._storage: Optional[GoalStorage] = None

    async def _get_storage(self) -> GoalStorage:
        if self._storage is None:
            self._storage = await get_goal_storage()
        return self._storage

    async def initial_load(self) -> None:
        """Perform initial load of all goal tree data."""
        storage = await self._get_storage()
        await load_goal_tree_data(self._goal_state, self._tree_state, storage)

    async def refresh_all_sessions(self) -> None:
        """Refresh all session data from TreeState."""
        storage = await self._get_storage()
        await sync_session_bindings(self._goal_state, self._tree_state, storage)

    async def refresh_session(self, session_id: str) -> None:
        """Refresh a single session's data."""
        storage = await self._get_storage()
        await refresh_session_in_goal_tree(
            self._goal_state, self._tree_state, session_id, storage
        )

    async def handle_binding_created(self, binding: SessionBinding) -> None:
        """Handle a new binding being created."""
        await on_session_bound(self._goal_state, self._tree_state, binding)

    async def handle_binding_released(self, session_id: str, entity_id: str) -> None:
        """Handle a binding being released."""
        await on_session_unbound(
            self._goal_state, self._tree_state, session_id, entity_id
        )

    def on_tree_state_event(self, event, data: dict) -> None:
        """Handle TreeState events to keep goal tree in sync.

        This should be registered as an observer on TreeState.
        """
        from core.tree_state import TreeEvent

        if event == TreeEvent.SESSION_ADDED:
            session_id = data.get("session_id")
            if session_id:
                # Schedule async refresh
                asyncio.create_task(self.refresh_session(session_id))

        elif event == TreeEvent.SESSION_REMOVED:
            session_id = data.get("session_id")
            if session_id:
                # Remove from goal tree (handled by unbind)
                existing = self._goal_state.get_session_binding(session_id)
                if existing:
                    asyncio.create_task(
                        self.handle_binding_released(session_id, existing[1])
                    )

        elif event == TreeEvent.SESSION_UPDATED:
            session_id = data.get("session_id")
            if session_id:
                asyncio.create_task(self.refresh_session(session_id))

        elif event == TreeEvent.STREAMING_STARTED:
            session_id = data.get("session_id")
            if session_id:
                asyncio.create_task(self.refresh_session(session_id))

        elif event == TreeEvent.STREAMING_STOPPED:
            session_id = data.get("session_id")
            if session_id:
                asyncio.create_task(self.refresh_session(session_id))

        elif event == TreeEvent.CONTEXT_TOKENS_CHANGED:
            # Refresh all sessions to update token counts
            asyncio.create_task(self.refresh_all_sessions())
