"""Goal-centric tree view - organizes by goals → plans → todos with sessions as associated data.

This is an alternative view to NestedTreeView. Instead of organizing around sessions,
this tree organizes around the work being done (goals, plans, todos) with sessions
shown as children of the entities they're bound to.

Uses GoalTreeState as the source of truth via observer pattern.
"""

from __future__ import annotations

from textual.widgets import Tree
from textual.containers import Vertical
from textual.message import Message
from textual.events import Key, Click
from rich.text import Text
from rich.style import Style
from rich.markup import escape as escape_markup
from typing import TYPE_CHECKING, Any, Optional

from core.goal_tree_state import (
    GoalTreeState, GoalTreeEvent,
    GoalNodeData, PlanNodeData, TodoNodeData, SessionNodeData,
)
from core.tree_state import TreeState, TreeEvent
from core.goal_tree_sync import GoalTreeSyncManager
from storage_schema import GoalData, PlanData, TodoData

if TYPE_CHECKING:
    from session import Session


class GoalTreeWidget(Tree):
    """Tree widget for goal-centric display.

    Behavior:
    - Enter: activate/navigate to entity or session
    - Space: toggle expand/collapse (or context mode for sessions)
    - e: expand/collapse current node
    - /: search
    - d/Delete: delete entity or session
    - m: mark todo done
    - b: bind session to current entity (when on goal/plan/todo node)
    - n: create new session bound to current entity
    - r: rebind session to different entity (when on session node)
    - u: unbind session from entity (when on session node)
    - Click [done]: mark todo as complete (when on pending/in_progress todo)
    - Click [+session]: create new session bound to that entity
    - Click [+plan]: create new plan under goal
    - Click [+todo]: create new todo under plan
    - Click [bind]/[move]: rebind session to different entity
    - Click [unbind]: remove session's binding
    - :: jump to command input
    - left/right: collapse/expand or navigate parent
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def render_label(self, node, base_style: Style, style: Style) -> Text:
        """Render label with custom icons based on node type.

        For goal/plan/todo nodes, adds clickable buttons ONLY when cursor is on node:
        - Goals: [+plan] (cyan) and [+session] (bright green)
        - Plans: [+todo] (magenta) and [+session] (bright green)
        - Todos: [+session] (bright green)
        - Sessions: [move]/[bind] and [unbind]

        When not the cursor node, more space is available for text display.
        """
        TOGGLE_STYLE = Style.from_meta({"toggle": True})

        # Check if this is the cursor node - buttons only shown on cursor row
        is_cursor = node == self.cursor_node

        node_label = node._label.copy()
        node_label.stylize(style)

        if node._allow_expand:
            icon = self.ICON_NODE_EXPANDED if node.is_expanded else self.ICON_NODE

            # Color based on node type
            node_type = node.data.get("type") if node.data else None
            if node_type == "goal":
                prefix = Text(icon, style=Style(color="yellow") + TOGGLE_STYLE)
            elif node_type == "plan":
                prefix = Text(icon, style=Style(color="cyan") + TOGGLE_STYLE)
            elif node_type == "todo":
                prefix = Text(icon, style=Style(color="green") + TOGGLE_STYLE)
            elif node_type == "session":
                prefix = Text(icon, style=Style(color="blue") + TOGGLE_STYLE)
            else:
                prefix = Text(icon, style=base_style + TOGGLE_STYLE)
        else:
            prefix = Text("", style=base_style)

        text = Text.assemble(prefix, node_label)

        # Add clickable buttons ONLY on cursor row
        if not is_cursor:
            return text

        node_type = node.data.get("type") if node.data else None

        if node_type == "goal":
            goal_id = node.data.get("goal_id")
            if goal_id:
                # [+plan] button for goals - cyan to match plan color
                new_plan_style = Style.from_meta({
                    "new_plan": True,
                    "goal_id": goal_id,
                })
                text.append(" ")
                text.append("[+plan]", style=Style(color="cyan", bold=True) + new_plan_style)

                # [+session] button
                new_session_style = Style.from_meta({
                    "new_session": True,
                    "entity_type": "goal",
                    "entity_id": goal_id,
                })
                text.append(" ")
                text.append("[+session]", style=Style(color="bright_green", bold=True) + new_session_style)

        elif node_type == "plan":
            plan_id = node.data.get("plan_id")
            if plan_id:
                # [+todo] button for plans - magenta for visibility
                new_todo_style = Style.from_meta({
                    "new_todo": True,
                    "plan_id": plan_id,
                })
                text.append(" ")
                text.append("[+todo]", style=Style(color="magenta", bold=True) + new_todo_style)

                # [+session] button
                new_session_style = Style.from_meta({
                    "new_session": True,
                    "entity_type": "plan",
                    "entity_id": plan_id,
                })
                text.append(" ")
                text.append("[+session]", style=Style(color="bright_green", bold=True) + new_session_style)

        elif node_type == "todo":
            todo_id = node.data.get("todo_id")
            todo_status = node.data.get("todo_status", "pending")
            if todo_id:
                # [done] button for incomplete todos - allows marking complete via click
                if todo_status in ("pending", "in_progress"):
                    done_style = Style.from_meta({
                        "mark_done": True,
                        "todo_id": todo_id,
                    })
                    text.append(" ")
                    text.append("[done]", style=Style(color="green", bold=True) + done_style)

                # [+session] button for todos
                new_session_style = Style.from_meta({
                    "new_session": True,
                    "entity_type": "todo",
                    "entity_id": todo_id,
                })
                text.append(" ")
                text.append("[+session]", style=Style(color="bright_green", bold=True) + new_session_style)

        elif node_type == "session":
            session_id = node.data.get("session_id")
            bound_to_type = node.data.get("bound_to_type")
            if session_id:
                # [bind] button for sessions - allows rebinding or binding unbound sessions
                bind_style = Style.from_meta({
                    "bind_session": True,
                    "session_id": session_id,
                })
                text.append(" ")
                if bound_to_type:
                    # Already bound - show [move] to rebind
                    text.append("[move]", style=Style(color="yellow", bold=True) + bind_style)
                else:
                    # Unbound - show [bind]
                    text.append("[bind]", style=Style(color="bright_green", bold=True) + bind_style)

                # [unbind] button only for bound sessions
                if bound_to_type:
                    unbind_style = Style.from_meta({
                        "unbind_session": True,
                        "session_id": session_id,
                    })
                    text.append(" ")
                    text.append("[unbind]", style=Style(color="red") + unbind_style)

        return text

    # --- Messages ---

    class ActivateRequested(Message):
        """Fired when user presses Enter to activate/navigate."""
        def __init__(self, node_data: dict) -> None:
            self.node_data = node_data
            super().__init__()

    class ToggleRequested(Message):
        """Fired when user presses Space."""
        def __init__(self, node_data: dict) -> None:
            self.node_data = node_data
            super().__init__()

    class SessionActivateRequested(Message):
        """Fired when user activates a session node."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class ColonPressed(Message):
        """Fired when user types : to jump to text entry."""
        pass

    class SearchRequested(Message):
        """Fired when user presses / to start searching."""
        pass

    class DeleteRequested(Message):
        """Fired when user presses d/Delete to delete something."""
        def __init__(self, node_data: dict) -> None:
            self.node_data = node_data
            super().__init__()

    class MarkTodoDoneRequested(Message):
        """Fired when user presses m on a todo to mark it done."""
        def __init__(self, todo_id: str) -> None:
            self.todo_id = todo_id
            super().__init__()

    class BindSessionRequested(Message):
        """Fired when user presses b to bind current session to entity."""
        def __init__(self, entity_type: str, entity_id: str) -> None:
            self.entity_type = entity_type
            self.entity_id = entity_id
            super().__init__()

    class ContextModeToggleRequested(Message):
        """Fired when user presses space on a session to toggle context mode."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class NewSessionRequested(Message):
        """Fired when user clicks [+session] to create a new session bound to entity."""
        def __init__(self, entity_type: str, entity_id: str) -> None:
            self.entity_type = entity_type
            self.entity_id = entity_id
            super().__init__()

    class NewTodoRequested(Message):
        """Fired when user clicks [+todo] on a plan to create a new todo."""
        def __init__(self, plan_id: str) -> None:
            self.plan_id = plan_id
            super().__init__()

    class NewPlanRequested(Message):
        """Fired when user clicks [+plan] on a goal to create a new plan."""
        def __init__(self, goal_id: str) -> None:
            self.goal_id = goal_id
            super().__init__()

    class MoveSessionRequested(Message):
        """Fired when user clicks [move]/[bind] to rebind a session to a different entity."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class UnbindSessionRequested(Message):
        """Fired when user clicks [unbind] to remove session's binding."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    # --- Click handling ---

    def on_click(self, event: Click) -> None:
        """Handle clicks on tree nodes.

        Detects clicks on the [+session], [+todo], and [+plan] widgets.
        """
        meta = event.style.meta

        # Debug: log all meta to understand what's available
        from core.debug_log import debug_log
        debug_log.info(f"GoalTreeWidget click meta: {meta}", category="goal_tree")

        # Check if this is a click on [+plan] (on goal nodes)
        if meta.get("new_plan"):
            goal_id = meta.get("goal_id")
            debug_log.info(f"GoalTreeWidget [+plan] clicked: goal_id={goal_id}", category="goal_tree")
            if goal_id:
                self.post_message(self.NewPlanRequested(goal_id))
                event.stop()
                return

        # Check if this is a click on [+todo] (on plan nodes)
        if meta.get("new_todo"):
            plan_id = meta.get("plan_id")
            debug_log.info(f"GoalTreeWidget [+todo] clicked: plan_id={plan_id}", category="goal_tree")
            if plan_id:
                self.post_message(self.NewTodoRequested(plan_id))
                event.stop()
                return

        # Check if this is a click on the [+session] widget
        if meta.get("new_session"):
            entity_type = meta.get("entity_type")
            entity_id = meta.get("entity_id")
            debug_log.info(f"GoalTreeWidget [+session] clicked: type={entity_type}, id={entity_id}", category="goal_tree")
            if entity_type and entity_id:
                self.post_message(self.NewSessionRequested(entity_type, entity_id))
                event.stop()
                return

        # Check if this is a click on [bind]/[move] (on session nodes)
        if meta.get("bind_session"):
            session_id = meta.get("session_id")
            debug_log.info(f"GoalTreeWidget [bind]/[move] clicked: session_id={session_id}", category="goal_tree")
            if session_id:
                self.post_message(self.MoveSessionRequested(session_id))
                event.stop()
                return

        # Check if this is a click on [unbind] (on session nodes)
        if meta.get("unbind_session"):
            session_id = meta.get("session_id")
            debug_log.info(f"GoalTreeWidget [unbind] clicked: session_id={session_id}", category="goal_tree")
            if session_id:
                self.post_message(self.UnbindSessionRequested(session_id))
                event.stop()
                return

        # Check if this is a click on [done] (on todo nodes)
        if meta.get("mark_done"):
            todo_id = meta.get("todo_id")
            debug_log.info(f"GoalTreeWidget [done] clicked: todo_id={todo_id}", category="goal_tree")
            if todo_id:
                self.post_message(self.MarkTodoDoneRequested(todo_id))
                event.stop()
                return

    # --- Key handling ---

    async def _on_key(self, event: Key) -> None:
        node = self.cursor_node

        if event.key == "enter":
            if node and node.data:
                self.post_message(self.ActivateRequested(node.data))
                if node._allow_expand:
                    node.toggle()
                event.prevent_default()
                event.stop()
                return

        elif event.key == "space":
            if node and node.data:
                node_type = node.data.get("type")
                # For sessions, toggle context mode instead of expand
                if node_type == "session":
                    session_id = node.data.get("session_id")
                    if session_id:
                        self.post_message(self.ContextModeToggleRequested(session_id))
                        event.prevent_default()
                        event.stop()
                        return
                else:
                    # For other nodes, toggle expand/collapse
                    self.post_message(self.ToggleRequested(node.data))
                    if node._allow_expand:
                        node.toggle()
                    event.prevent_default()
                    event.stop()
                    return

        elif event.key == "e":
            if node and node._allow_expand:
                node.toggle()
                event.prevent_default()
                event.stop()
                return

        elif event.key == "colon":
            self.post_message(self.ColonPressed())
            event.prevent_default()
            event.stop()
            return

        elif event.key == "slash":
            self.post_message(self.SearchRequested())
            event.prevent_default()
            event.stop()
            return

        elif event.key in ("d", "delete"):
            if node and node.data:
                self.post_message(self.DeleteRequested(node.data))
                event.prevent_default()
                event.stop()
                return

        elif event.key == "m":
            # Mark todo done
            if node and node.data:
                node_type = node.data.get("type")
                if node_type == "todo":
                    todo_id = node.data.get("todo_id")
                    if todo_id:
                        self.post_message(self.MarkTodoDoneRequested(todo_id))
                        event.prevent_default()
                        event.stop()
                        return

        elif event.key == "b":
            # Bind session to current entity
            if node and node.data:
                node_type = node.data.get("type")
                if node_type in ("goal", "plan", "todo"):
                    entity_id = node.data.get(f"{node_type}_id")
                    if entity_id:
                        self.post_message(self.BindSessionRequested(node_type, entity_id))
                        event.prevent_default()
                        event.stop()
                        return

        elif event.key == "n":
            # Create new session bound to current entity
            if node and node.data:
                node_type = node.data.get("type")
                if node_type in ("goal", "plan", "todo"):
                    entity_id = node.data.get(f"{node_type}_id")
                    if entity_id:
                        self.post_message(self.NewSessionRequested(node_type, entity_id))
                        event.prevent_default()
                        event.stop()
                        return

        elif event.key == "r":
            # Rebind/move session to a different entity
            if node and node.data:
                node_type = node.data.get("type")
                if node_type == "session":
                    session_id = node.data.get("session_id")
                    if session_id:
                        self.post_message(self.MoveSessionRequested(session_id))
                        event.prevent_default()
                        event.stop()
                        return

        elif event.key == "u":
            # Unbind session from current entity
            if node and node.data:
                node_type = node.data.get("type")
                if node_type == "session":
                    session_id = node.data.get("session_id")
                    if session_id:
                        self.post_message(self.UnbindSessionRequested(session_id))
                        event.prevent_default()
                        event.stop()
                        return

        elif event.key == "right":
            if node and node._allow_expand and not node.is_expanded:
                node.expand()
                event.prevent_default()
                event.stop()
                return

        elif event.key == "left":
            if node:
                if node.is_expanded:
                    node.collapse()
                    event.prevent_default()
                    event.stop()
                    return
                elif node.parent and node.parent != self.root:
                    self.select_node(node.parent)
                    event.prevent_default()
                    event.stop()
                    return
        await super()._on_key(event)


class GoalTreeView(Vertical):
    """View container for goal-centric tree.

    Shows goals → plans → todos hierarchy, with sessions as children
    of the entities they're bound to.

    This is a PURE OBSERVER implementation - state comes from GoalTreeState
    and TreeState (for session data).
    """

    DEFAULT_CSS = """
    GoalTreeView {
        width: 50;
        height: 100%;
        border-right: solid $primary;
    }

    GoalTreeView > GoalTreeWidget {
        height: 1fr;
        background: $background;
    }
    """

    # --- Messages ---

    class SessionActivated(Message):
        """Fired when user clicks on a session to view it."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class EntitySelected(Message):
        """Fired when user selects a goal/plan/todo."""
        def __init__(self, entity_type: str, entity_id: str) -> None:
            self.entity_type = entity_type
            self.entity_id = entity_id
            super().__init__()

    class ColonPressed(Message):
        """Fired when user types : to jump to text entry."""
        pass

    class SearchRequested(Message):
        """Fired when user presses / to start searching."""
        pass

    class DeleteRequested(Message):
        """Fired when user requests to delete an entity."""
        def __init__(self, entity_type: str, entity_id: str) -> None:
            self.entity_type = entity_type
            self.entity_id = entity_id
            super().__init__()

    class SessionDeleteRequested(Message):
        """Fired when user requests to delete a session."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class MarkTodoDoneRequested(Message):
        """Fired when user marks a todo as done."""
        def __init__(self, todo_id: str) -> None:
            self.todo_id = todo_id
            super().__init__()

    class BindSessionRequested(Message):
        """Fired when user wants to bind current session to an entity."""
        def __init__(self, entity_type: str, entity_id: str) -> None:
            self.entity_type = entity_type
            self.entity_id = entity_id
            super().__init__()

    class ContextModeChanged(Message):
        """Fired when a session's context mode is toggled."""
        def __init__(self, session_id: str, turn_idx: int, new_mode) -> None:
            self.session_id = session_id
            self.turn_idx = turn_idx
            self.new_mode = new_mode
            super().__init__()

    class NewSessionRequested(Message):
        """Fired when user clicks [+session] to create a new session bound to entity."""
        def __init__(self, entity_type: str, entity_id: str) -> None:
            self.entity_type = entity_type
            self.entity_id = entity_id
            super().__init__()

    class NewTodoRequested(Message):
        """Fired when user clicks [+todo] on a plan to create a new todo."""
        def __init__(self, plan_id: str) -> None:
            self.plan_id = plan_id
            super().__init__()

    class NewPlanRequested(Message):
        """Fired when user clicks [+plan] on a goal to create a new plan."""
        def __init__(self, goal_id: str) -> None:
            self.goal_id = goal_id
            super().__init__()

    class MoveSessionRequested(Message):
        """Fired when user clicks [move]/[bind] to rebind a session to a different entity."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class UnbindSessionClicked(Message):
        """Fired when user clicks [unbind] to remove session's binding."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    def __init__(
        self,
        goal_state: GoalTreeState,
        tree_state: TreeState,
        sync_manager: Optional[GoalTreeSyncManager] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._goal_state = goal_state
        self._tree_state = tree_state  # For session data
        self._sync_manager = sync_manager

        # Node references: entity_id -> tree node
        self._goal_nodes: dict[str, Any] = {}
        self._plan_nodes: dict[str, Any] = {}
        self._todo_nodes: dict[str, Any] = {}
        self._session_nodes: dict[str, Any] = {}
        self._unbound_section_node: Any = None

    def compose(self):
        tree = GoalTreeWidget("[bold]Goals[/]", id="goal-tree-widget")
        tree.root.data = {"type": "root"}
        yield tree

    def on_mount(self) -> None:
        tree = self.query_one("#goal-tree-widget", GoalTreeWidget)
        tree.root.expand()
        tree.root.allow_expand = False
        tree.auto_expand = False

        # Register as observer for GoalTreeState
        self._goal_state.add_observer(self._on_goal_state_event)

        # Register as observer for TreeState (session changes)
        self._tree_state.add_observer(self._on_tree_state_event)

        # Initial build
        self._rebuild_tree()

    def on_unmount(self) -> None:
        self._goal_state.remove_observer(self._on_goal_state_event)
        self._tree_state.remove_observer(self._on_tree_state_event)

    # --- Observer Event Handler ---

    def _on_goal_state_event(self, event: GoalTreeEvent, data: dict) -> None:
        """Handle state change notifications from GoalTreeState."""
        if event == GoalTreeEvent.FULL_REBUILD:
            self._rebuild_tree()

        elif event == GoalTreeEvent.GOAL_ADDED:
            self._rebuild_tree()  # Simplest approach for now

        elif event == GoalTreeEvent.GOAL_UPDATED:
            goal_id = data.get("goal_id")
            if goal_id:
                self._update_goal_label(goal_id)

        elif event == GoalTreeEvent.GOAL_REMOVED:
            goal_id = data.get("goal_id")
            if goal_id and goal_id in self._goal_nodes:
                node = self._goal_nodes.pop(goal_id)
                node.remove()

        elif event == GoalTreeEvent.PLAN_ADDED:
            self._rebuild_tree()

        elif event == GoalTreeEvent.PLAN_UPDATED:
            plan_id = data.get("plan_id")
            if plan_id:
                self._update_plan_label(plan_id)

        elif event == GoalTreeEvent.TODO_ADDED:
            self._rebuild_tree()

        elif event == GoalTreeEvent.TODO_UPDATED:
            todo_id = data.get("todo_id")
            if todo_id:
                self._update_todo_label(todo_id)

        elif event == GoalTreeEvent.SESSION_BOUND:
            self._rebuild_tree()

        elif event == GoalTreeEvent.SESSION_UNBOUND:
            self._rebuild_tree()

        elif event == GoalTreeEvent.SESSION_UPDATED:
            # Session metadata changed (title, tokens, etc.) - update just that label
            session_id = data.get("session_id")
            if session_id:
                self._update_session_label(session_id)

    def _on_tree_state_event(self, event: TreeEvent, data: dict) -> None:
        """Handle TreeState events to keep session display in sync.

        Delegates to sync manager if available, or handles directly.
        """
        if self._sync_manager:
            # Let sync manager handle the event (updates GoalTreeState)
            self._sync_manager.on_tree_state_event(event, data)
        else:
            # Direct handling for simple cases
            if event == TreeEvent.SESSION_SELECTED:
                # Update current session highlighting
                session_id = data.get("session_id")
                prev_id = data.get("prev_session_id")
                if prev_id and prev_id in self._session_nodes:
                    self._update_session_label(prev_id)
                if session_id and session_id in self._session_nodes:
                    self._update_session_label(session_id)

            elif event == TreeEvent.STREAMING_STARTED:
                session_id = data.get("session_id")
                if session_id:
                    self._update_session_label(session_id)

            elif event == TreeEvent.STREAMING_STOPPED:
                session_id = data.get("session_id")
                if session_id:
                    self._update_session_label(session_id)

    def _update_session_label(self, session_id: str) -> None:
        """Update a session node's label from TreeState data."""
        node = self._session_nodes.get(session_id)
        if not node:
            return

        # Get session data from TreeState
        session_data = self._tree_state.get_session(session_id)
        if not session_data:
            return

        # Get binding role from node data
        role = node.data.get("binding_role", "") if node.data else ""

        # Create SessionNodeData from TreeState data
        if session_data.fork_name:
            name = session_data.fork_name
        elif session_data.title:
            name = session_data.title
        else:
            name = session_data.id[:8]

        session_node_data = SessionNodeData(
            session_id=session_data.id,
            name=name,
            token_count=session_data.cached_context_tokens,
            is_current=session_data.is_current,
            is_streaming=session_data.is_streaming,
            fork_status=session_data.fork_status,
            binding_role=role,
        )

        node.label = self._make_session_label(session_node_data)

    # --- Tree Building ---

    def _rebuild_tree(self) -> None:
        """Rebuild the entire tree from GoalTreeState."""
        tree = self.query_one("#goal-tree-widget", GoalTreeWidget)
        tree.root.remove_children()

        self._goal_nodes.clear()
        self._plan_nodes.clear()
        self._todo_nodes.clear()
        self._session_nodes.clear()
        self._unbound_section_node = None

        # Add goals
        goals = self._goal_state.get_all_goals()
        for goal_node_data in goals:
            self._add_goal_node(tree.root, goal_node_data)

        # Add unbound sessions section
        unbound = self._goal_state.get_unbound_sessions()
        if unbound:
            self._add_unbound_section(tree.root, unbound)

        self._update_root_label()

    def _add_goal_node(self, parent_node, goal_data: GoalNodeData) -> None:
        """Add a goal node to the tree."""
        label = self._make_goal_label(goal_data)

        goal_node = parent_node.add(
            label,
            data={"type": "goal", "goal_id": goal_data.id}
        )
        self._goal_nodes[goal_data.id] = goal_node

        # Add plans
        plans = self._goal_state.get_plans_for_goal(goal_data.id)
        for plan_data in plans:
            self._add_plan_node(goal_node, plan_data)

        # Add sessions bound directly to goal
        bound_sessions = self._goal_state.get_bound_sessions(goal_data.id)
        for session in bound_sessions:
            self._add_session_node(goal_node, session, "goal", goal_data.id)

        # Expand if has children
        if plans or bound_sessions:
            goal_node.expand()

    def _add_plan_node(self, parent_node, plan_data: PlanNodeData) -> None:
        """Add a plan node to the tree."""
        label = self._make_plan_label(plan_data)

        plan_node = parent_node.add(
            label,
            data={"type": "plan", "plan_id": plan_data.id, "goal_id": plan_data.goal_id}
        )
        self._plan_nodes[plan_data.id] = plan_node

        # Add todos
        todos = self._goal_state.get_todos_for_plan(plan_data.id)
        for todo_data in todos:
            self._add_todo_node(plan_node, todo_data)

        # Add sessions bound to plan
        bound_sessions = self._goal_state.get_bound_sessions(plan_data.id)
        for session in bound_sessions:
            self._add_session_node(plan_node, session, "plan", plan_data.id)

        # Expand if has children (todos or sessions)
        if todos or bound_sessions:
            plan_node.expand()

    def _add_todo_node(self, parent_node, todo_data: TodoNodeData) -> None:
        """Add a todo node to the tree."""
        label = self._make_todo_label(todo_data)

        todo_node = parent_node.add(
            label,
            data={"type": "todo", "todo_id": todo_data.id, "todo_status": todo_data.status}
        )
        self._todo_nodes[todo_data.id] = todo_node

        # Add sessions bound to todo
        bound_sessions = self._goal_state.get_bound_sessions(todo_data.id)
        for session in bound_sessions:
            self._add_session_node(todo_node, session, "todo", todo_data.id)

        # Expand if has sessions
        if bound_sessions:
            todo_node.expand()

    def _add_session_node(
        self,
        parent_node,
        session: SessionNodeData,
        entity_type: str,
        entity_id: str,
    ) -> None:
        """Add a session node to the tree."""
        label = self._make_session_label(session)

        session_node = parent_node.add(
            label,
            data={
                "type": "session",
                "session_id": session.session_id,
                "bound_to_type": entity_type,
                "bound_to_id": entity_id,
            },
            allow_expand=False,  # Sessions are leaf nodes in this view
        )
        self._session_nodes[session.session_id] = session_node

    def _add_unbound_section(self, parent_node, sessions: list[SessionNodeData]) -> None:
        """Add the unbound sessions section."""
        label = f"[dim]📁 Unbound Sessions ({len(sessions)})[/]"

        self._unbound_section_node = parent_node.add(
            label,
            data={"type": "unbound_section"}
        )

        for session in sessions:
            session_label = self._make_session_label(session)
            session_node = self._unbound_section_node.add(
                session_label,
                data={
                    "type": "session",
                    "session_id": session.session_id,
                    "bound_to_type": None,
                    "bound_to_id": None,
                },
                allow_expand=False,
            )
            self._session_nodes[session.session_id] = session_node

    # --- Label Formatters ---

    def _make_goal_label(self, goal_data: GoalNodeData) -> str:
        """Create label for a goal node.

        Title is not truncated here - the tree widget will handle overflow.
        Buttons are only shown on cursor row, so full text can be displayed.
        """
        status_icon = {
            "active": "[green]●[/]",
            "completed": "[blue]✓[/]",
            "superseded": "[yellow]→[/]",
            "abandoned": "[red]✗[/]",
        }.get(goal_data.status, "○")

        weight = goal_data.weight
        weight_bar = "█" * min(weight, 5) + "░" * max(0, 5 - weight)

        title = goal_data.title
        # No truncation - let tree widget handle overflow

        session_count = len(goal_data.bound_session_ids)
        session_indicator = f" [dim]({session_count}s)[/]" if session_count > 0 else ""

        return (
            f"{status_icon} 🎯 [bold]{escape_markup(title)}[/] "
            f"[dim][{weight_bar}][/]{session_indicator}"
        )

    def _make_plan_label(self, plan_data: PlanNodeData) -> str:
        """Create label for a plan node.

        Title is not truncated - tree widget handles overflow.
        Buttons only shown on cursor row.
        """
        status_icon = {
            "draft": "[yellow]◌[/]",
            "active": "[green]●[/]",
            "completed": "[blue]✓[/]",
            "abandoned": "[red]✗[/]",
        }.get(plan_data.status, "○")

        title = plan_data.title
        # No truncation - let tree widget handle overflow

        # Count todos
        todo_count = len(plan_data.todo_ids) if hasattr(plan_data, 'todo_ids') else 0
        todo_indicator = f" [dim]({todo_count}t)[/]" if todo_count > 0 else ""

        return f"{status_icon} 📋 [cyan]{escape_markup(title)}[/]{todo_indicator}"

    def _make_todo_label(self, todo_data: TodoNodeData) -> str:
        """Create label for a todo node.

        Title is not truncated - tree widget handles overflow.
        Buttons only shown on cursor row.
        """
        status_icon = {
            "pending": "[yellow]○[/]",
            "in_progress": "[cyan]◐[/]",
            "completed": "[green]✓[/]",
            "blocked": "[red]⊘[/]",
            "abandoned": "[dim]✗[/]",
        }.get(todo_data.status, "○")

        title = todo_data.title
        # No truncation - let tree widget handle overflow

        spike_marker = " [magenta][spike][/]" if todo_data.is_spike else ""
        priority_marker = f" [yellow]p:{todo_data.priority:.1f}[/]" if todo_data.priority > 0 else ""

        session_count = len(todo_data.bound_session_ids)
        session_indicator = f" [dim]({session_count}s)[/]" if session_count > 0 else ""

        return (
            f"{status_icon} {escape_markup(title)}"
            f"{spike_marker}{priority_marker}{session_indicator}"
        )

    def _make_session_label(self, session: SessionNodeData) -> str:
        """Create label for a session node."""
        # Token count
        from widgets.session_rendering import format_kt
        kt_str = format_kt(session.token_count) if session.token_count > 0 else ""
        token_part = f"[green]{kt_str}[/] " if kt_str else ""

        # Current indicator
        current_indicator = "[bold cyan]→ [/]" if session.is_current else ""

        # Streaming indicator
        streaming = "[yellow]●[/] " if session.is_streaming else ""

        # Fork status
        if session.fork_status == "merged":
            fork_indicator = "[green]✓[/] "
        elif session.fork_status:
            fork_indicator = "[magenta]↳[/] "
        else:
            fork_indicator = ""

        # Name - no truncation, let tree widget handle overflow
        name = session.name

        # Role indicator (use central ROLE_ABBREV mapping)
        from core.goal_commands import ROLE_ABBREV
        role_abbrev = ROLE_ABBREV.get(session.binding_role, "")
        role_indicator = f" [dim][{role_abbrev}][/]" if role_abbrev else ""

        return (
            f"{token_part}{current_indicator}{streaming}{fork_indicator}"
            f"📁 {escape_markup(name)}{role_indicator}"
        )

    def _update_goal_label(self, goal_id: str) -> None:
        """Update a goal node's label."""
        node = self._goal_nodes.get(goal_id)
        if not node:
            return
        goal_data = self._goal_state.get_goal(goal_id)
        if goal_data:
            node.label = self._make_goal_label(goal_data)

    def _update_plan_label(self, plan_id: str) -> None:
        """Update a plan node's label."""
        node = self._plan_nodes.get(plan_id)
        if not node:
            return
        plan_data = self._goal_state.get_plan(plan_id)
        if plan_data:
            node.label = self._make_plan_label(plan_data)

    def _update_todo_label(self, todo_id: str) -> None:
        """Update a todo node's label and status data."""
        node = self._todo_nodes.get(todo_id)
        if not node:
            return
        todo_data = self._goal_state.get_todo(todo_id)
        if todo_data:
            node.label = self._make_todo_label(todo_data)
            # Also update the node's data so render_label uses correct status
            # (affects whether [done] button is shown)
            if node.data:
                node.data["todo_status"] = todo_data.status

    def _update_root_label(self) -> None:
        """Update root label with stats."""
        tree = self.query_one("#goal-tree-widget", GoalTreeWidget)
        stats = self._goal_state.get_stats()

        active_goals = stats["active_goals"]
        pending_todos = stats["pending_todos"]
        in_progress = stats["in_progress_todos"]

        tree.root.label = (
            f"[bold]Goals[/] "
            f"[dim]({active_goals}g, {pending_todos}+{in_progress}t)[/]"
        )

    # --- Event Handlers ---

    def on_goal_tree_widget_activate_requested(self, event: GoalTreeWidget.ActivateRequested) -> None:
        """Handle Enter key activation."""
        node_type = event.node_data.get("type")

        if node_type == "session":
            session_id = event.node_data.get("session_id")
            if session_id:
                self.post_message(self.SessionActivated(session_id))

        elif node_type in ("goal", "plan", "todo"):
            entity_id = event.node_data.get(f"{node_type}_id")
            if entity_id:
                self._goal_state.select_entity(node_type, entity_id)
                self.post_message(self.EntitySelected(node_type, entity_id))

    def on_goal_tree_widget_toggle_requested(self, event: GoalTreeWidget.ToggleRequested) -> None:
        """Handle Space key toggle."""
        # For now, just toggle expand/collapse (handled by widget)
        # Future: toggle context mode for session nodes
        pass

    def on_goal_tree_widget_colon_pressed(self, event: GoalTreeWidget.ColonPressed) -> None:
        """Bubble up colon pressed."""
        self.post_message(self.ColonPressed())

    def on_goal_tree_widget_search_requested(self, event: GoalTreeWidget.SearchRequested) -> None:
        """Bubble up search request."""
        self.post_message(self.SearchRequested())

    def on_goal_tree_widget_delete_requested(self, event: GoalTreeWidget.DeleteRequested) -> None:
        """Handle delete request for entities or sessions."""
        node_type = event.node_data.get("type")

        if node_type == "session":
            session_id = event.node_data.get("session_id")
            if session_id:
                self.post_message(self.SessionDeleteRequested(session_id))
        elif node_type in ("goal", "plan", "todo"):
            entity_id = event.node_data.get(f"{node_type}_id")
            if entity_id:
                self.post_message(self.DeleteRequested(node_type, entity_id))

    def on_goal_tree_widget_mark_todo_done_requested(self, event: GoalTreeWidget.MarkTodoDoneRequested) -> None:
        """Bubble up mark todo done request."""
        self.post_message(self.MarkTodoDoneRequested(event.todo_id))

    def on_goal_tree_widget_bind_session_requested(self, event: GoalTreeWidget.BindSessionRequested) -> None:
        """Bubble up bind session request."""
        self.post_message(self.BindSessionRequested(event.entity_type, event.entity_id))

    def on_goal_tree_widget_context_mode_toggle_requested(self, event: GoalTreeWidget.ContextModeToggleRequested) -> None:
        """Handle context mode toggle for a session.

        This toggles the context mode for all turns in the session.
        """
        session_id = event.session_id
        session_data = self._tree_state.get_session(session_id)
        if not session_data or not session_data.turns:
            return

        from models import ContextMode

        # Toggle all turns: if any is COPY, set all to DROP; otherwise set all to COPY
        modes = [self._tree_state.get_context_mode(session_id, t.idx) for t in session_data.turns]
        any_copy = any(m == ContextMode.COPY for m in modes)

        new_mode = ContextMode.DROP if any_copy else ContextMode.COPY
        for turn in session_data.turns:
            self._tree_state.set_context_mode(session_id, turn.idx, new_mode)
            self.post_message(self.ContextModeChanged(session_id, turn.idx, new_mode))

    def on_goal_tree_widget_new_session_requested(self, event: GoalTreeWidget.NewSessionRequested) -> None:
        """Bubble up new session request."""
        from core.debug_log import debug_log
        debug_log.info(f"GoalTreeView received NewSessionRequested: type={event.entity_type}, id={event.entity_id}", category="goal_tree")
        self.post_message(self.NewSessionRequested(event.entity_type, event.entity_id))

    def on_goal_tree_widget_new_todo_requested(self, event: GoalTreeWidget.NewTodoRequested) -> None:
        """Bubble up new todo request."""
        from core.debug_log import debug_log
        debug_log.info(f"GoalTreeView received NewTodoRequested: plan_id={event.plan_id}", category="goal_tree")
        self.post_message(self.NewTodoRequested(event.plan_id))

    def on_goal_tree_widget_new_plan_requested(self, event: GoalTreeWidget.NewPlanRequested) -> None:
        """Bubble up new plan request."""
        from core.debug_log import debug_log
        debug_log.info(f"GoalTreeView received NewPlanRequested: goal_id={event.goal_id}", category="goal_tree")
        self.post_message(self.NewPlanRequested(event.goal_id))

    def on_goal_tree_widget_move_session_requested(self, event: GoalTreeWidget.MoveSessionRequested) -> None:
        """Bubble up move session request (rebind to different entity)."""
        from core.debug_log import debug_log
        debug_log.info(f"GoalTreeView received MoveSessionRequested: session_id={event.session_id}", category="goal_tree")
        self.post_message(self.MoveSessionRequested(event.session_id))

    def on_goal_tree_widget_unbind_session_requested(self, event: GoalTreeWidget.UnbindSessionRequested) -> None:
        """Bubble up unbind session request."""
        from core.debug_log import debug_log
        debug_log.info(f"GoalTreeView received UnbindSessionRequested: session_id={event.session_id}", category="goal_tree")
        self.post_message(self.UnbindSessionClicked(event.session_id))

    def on_tree_node_selected(self, event) -> None:
        """Handle node selection."""
        node_data = event.node.data
        if not node_data:
            return

        node_type = node_data.get("type")

        if node_type == "session":
            session_id = node_data.get("session_id")
            if session_id:
                self.post_message(self.SessionActivated(session_id))

    # --- Public API ---

    @property
    def goal_state(self) -> GoalTreeState:
        """Access the underlying GoalTreeState."""
        return self._goal_state

    @property
    def tree_state(self) -> TreeState:
        """Access the TreeState for session data."""
        return self._tree_state

    def refresh_sessions(self) -> None:
        """Refresh session data from TreeState.

        Call this when session data changes to update the tree.
        """
        # This would sync session data from TreeState to GoalTreeState
        # For now, just rebuild
        self._rebuild_tree()
