from textual.widgets import Tree
from textual.containers import Vertical
from textual.message import Message
from textual.events import Key
from datetime import datetime

from tokenizer import count_tokens
from session import Session
from models import ContextMode


class SelectableTree(Tree):
    """Tree with space-bar toggle for multiselect."""

    class ToggleRequested(Message):
        def __init__(self, node_data: dict) -> None:
            self.node_data = node_data
            super().__init__()

    class SelectAllRequested(Message):
        pass

    class SelectNoneRequested(Message):
        pass

    async def _on_key(self, event: Key) -> None:
        if event.key == "space":
            node = self.cursor_node
            if node and node.data:
                self.post_message(self.ToggleRequested(node.data))
                event.prevent_default()
                event.stop()
                return
        elif event.key == "a":
            self.post_message(self.SelectAllRequested())
            event.prevent_default()
            event.stop()
            return
        elif event.key == "n":
            self.post_message(self.SelectNoneRequested())
            event.prevent_default()
            event.stop()
            return
        await super()._on_key(event)


class ContextTree(Vertical):
    """Left panel showing all sessions with selectable turns."""

    DEFAULT_CSS = """
    ContextTree {
        width: 40;
        height: 100%;
        border-right: solid $primary;
    }

    ContextTree > SelectableTree {
        height: 1fr;
        background: $background;
    }
    """

    class SelectionChanged(Message):
        """Fired when turn selection changes."""
        def __init__(
            self,
            selected_count: int,
            total_tokens: int,
            selected_tokens: int,
            current_session_turn_ids: list[int],
        ) -> None:
            self.selected_count = selected_count
            self.total_tokens = total_tokens
            self.selected_tokens = selected_tokens
            # Turn IDs for current session (1-indexed to match chat_log)
            self.selected_turn_ids = current_session_turn_ids
            self.show_all = False  # Could be computed if all current session turns selected
            super().__init__()

    class SessionActivated(Message):
        """Fired when user clicks on a session to view it."""
        def __init__(self, session: Session) -> None:
            self.session = session
            super().__init__()

    class TurnInspected(Message):
        """Fired when user selects a turn to inspect its data."""
        def __init__(self, turn_data: dict) -> None:
            self.turn_data = turn_data
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Context mode per turn: (session_id, turn_idx) -> ContextMode
        # Missing entries default to DROP (not in context)
        self._context_modes: dict[tuple[str, int], ContextMode] = {}
        # All loaded sessions with their turns
        self._sessions: dict[str, dict] = {}  # session_id -> {session, turns, node}
        self._current_session_id: str | None = None

    def compose(self):
        tree = SelectableTree("[dim]loading...[/]", id="turn-tree")
        tree.root.data = {"type": "root"}
        yield tree

    def on_mount(self) -> None:
        tree = self.query_one("#turn-tree", SelectableTree)
        tree.root.expand()
        tree.root.allow_expand = False

    def load_all_sessions(self, current_session: Session) -> None:
        """Load all sessions into the tree."""
        self._current_session_id = current_session.id

        # Get all sessions
        all_sessions = Session.list_sessions()

        tree = self.query_one("#turn-tree", SelectableTree)
        tree.root.remove_children()
        self._sessions.clear()
        self._context_modes.clear()

        # Add current session first if it's new (not in list)
        session_ids_in_list = {s[0] for s in all_sessions}
        if current_session.id not in session_ids_in_list:
            self._add_session_to_tree(tree, current_session, is_current=True)

        # Add all sessions (newest first - already sorted)
        for session_id, created, model in all_sessions:
            session = Session.load(session_id)
            if session:
                is_current = session_id == current_session.id
                self._add_session_to_tree(tree, session, is_current=is_current)

        self._update_root_label()

    def _make_session_label(self, session: Session, is_active: bool) -> str:
        """Create a label for a session node."""
        try:
            dt = datetime.fromisoformat(session.created)
            date_str = dt.strftime("%b %d %H:%M")
        except:
            date_str = session.created[:16]

        msg_count = len(session.messages)

        # Show child/returned status indicator
        if session.parent_id:
            if session.returned:
                prefix = "[green]✓[/] "
            else:
                prefix = "[magenta]↳[/] "
        else:
            prefix = ""

        # Highlight active session
        if is_active:
            return f"{prefix}[bold cyan]{date_str} ({msg_count} msgs)[/]"
        else:
            return f"{prefix}{date_str} ({msg_count} msgs)"

    def _add_session_to_tree(self, tree: SelectableTree, session: Session, is_current: bool) -> None:
        """Add a session and its turns to the tree."""
        session_label = self._make_session_label(session, is_current)

        session_node = tree.root.add(
            session_label,
            data={"type": "session", "session_id": session.id}
        )
        if is_current:
            session_node.expand()

        turns = []
        for idx, msg in enumerate(session.messages):
            # Auto-include current session's turns as COPY
            turn_key = (session.id, idx)
            if is_current:
                self._context_modes[turn_key] = ContextMode.COPY

            mode = self._context_modes.get(turn_key, ContextMode.DROP)
            label = self._make_turn_label(msg.role, msg.content, mode)
            turn_node = session_node.add(
                label,
                data={"type": "turn", "session_id": session.id, "turn_idx": idx}
            )
            turns.append({
                "idx": idx,
                "role": msg.role,
                "content": msg.content,
                "node": turn_node,
                "events": [],  # Could load from storage if we save them
            })

        self._sessions[session.id] = {
            "session": session,
            "turns": turns,
            "node": session_node,
            "is_current": is_current,
        }

    def _make_turn_label(self, role: str, content: str, mode: ContextMode) -> str:
        # Mode indicator: copy=green check, summarize=yellow S, drop=empty box
        if mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif mode == ContextMode.SUMMARIZE:
            indicator = "[yellow]Σ[/]"
        else:  # DROP
            indicator = "☐"

        icon = "👤" if role == "user" else "🤖"
        preview = content[:40] + "..." if len(content) > 40 else content
        preview = preview.replace("\n", " ")
        return f"{indicator} {icon} {preview}"

    def _update_root_label(self) -> None:
        """Update root label with selected/total tokens."""
        tree = self.query_one("#turn-tree", SelectableTree)

        selected_tokens = 0
        total_tokens = 0
        current_session_turn_ids = []

        for session_id, session_data in self._sessions.items():
            for turn in session_data["turns"]:
                turn_key = (session_id, turn["idx"])
                content = f"{'User' if turn['role'] == 'user' else 'Assistant'}: {turn['content']}"
                tokens = count_tokens(content)
                total_tokens += tokens
                mode = self._context_modes.get(turn_key, ContextMode.DROP)
                if mode != ContextMode.DROP:
                    selected_tokens += tokens
                    # Track included turns from current session (1-indexed for chat_log)
                    if session_id == self._current_session_id:
                        current_session_turn_ids.append(turn["idx"] + 1)

        included_count = sum(1 for m in self._context_modes.values() if m != ContextMode.DROP)
        tree.root.label = f"[bold]{selected_tokens:,}[/] / {total_tokens:,} [dim]tokens[/]"

        self.post_message(self.SelectionChanged(
            included_count, total_tokens, selected_tokens, current_session_turn_ids
        ))

    def _update_turn_label(self, session_id: str, turn_idx: int) -> None:
        """Update a turn's mode indicator label."""
        session_data = self._sessions.get(session_id)
        if not session_data:
            return

        for turn in session_data["turns"]:
            if turn["idx"] == turn_idx:
                turn_key = (session_id, turn_idx)
                mode = self._context_modes.get(turn_key, ContextMode.DROP)
                turn["node"].label = self._make_turn_label(
                    turn["role"], turn["content"], mode
                )
                break

    def is_selection_curated(self) -> bool:
        """Check if selection differs from 'all current session turns as COPY'.

        Returns True if:
        - Any turn from another session is included, OR
        - Any turn from current session is not COPY, OR
        - Any turn uses SUMMARIZE mode
        """
        if not self._current_session_id:
            return False

        current_data = self._sessions.get(self._current_session_id)
        if not current_data:
            return False

        # Check if any non-current session turns are included
        for turn_key, mode in self._context_modes.items():
            if mode != ContextMode.DROP and turn_key[0] != self._current_session_id:
                return True

        # Check if all current session turns are COPY
        for turn in current_data["turns"]:
            turn_key = (self._current_session_id, turn["idx"])
            mode = self._context_modes.get(turn_key, ContextMode.DROP)
            if mode != ContextMode.COPY:
                return True

        return False

    def add_turn_to_current(self, role: str, content: str, raw_events: list[dict]) -> None:
        """Add a new turn to the current session."""
        if not self._current_session_id:
            return

        session_data = self._sessions.get(self._current_session_id)
        if not session_data:
            return

        idx = len(session_data["turns"])
        turn_key = (self._current_session_id, idx)
        self._context_modes[turn_key] = ContextMode.COPY  # Auto-include new turns as COPY

        label = self._make_turn_label(role, content, ContextMode.COPY)
        turn_node = session_data["node"].add(
            label,
            data={"type": "turn", "session_id": self._current_session_id, "turn_idx": idx}
        )

        session_data["turns"].append({
            "idx": idx,
            "role": role,
            "content": content,
            "node": turn_node,
            "events": raw_events,
        })

        # Update session label with new count
        session = session_data["session"]
        is_active = session.id == self._current_session_id
        session_data["node"].label = self._make_session_label(session, is_active)

        self._update_root_label()

    def on_tree_node_selected(self, event) -> None:
        """Handle node selection - switch session or inspect turn."""
        node_data = event.node.data
        if not node_data:
            return

        node_type = node_data.get("type")

        if node_type == "session":
            session_id = node_data.get("session_id")
            session_data = self._sessions.get(session_id)
            if session_data:
                self.post_message(self.SessionActivated(session_data["session"]))
        elif node_type == "turn":
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            session_data = self._sessions.get(session_id)
            if session_data:
                for turn in session_data["turns"]:
                    if turn["idx"] == turn_idx:
                        # Send turn data for inspection
                        self.post_message(self.TurnInspected({
                            "role": turn["role"],
                            "content": turn["content"],
                            "events": turn.get("events", []),
                        }))
                        break

    def on_selectable_tree_toggle_requested(self, event: SelectableTree.ToggleRequested) -> None:
        """Handle space bar toggle - cycle through COPY -> SUMMARIZE -> DROP."""
        node_type = event.node_data.get("type")
        if node_type != "turn":
            return

        session_id = event.node_data.get("session_id")
        turn_idx = event.node_data.get("turn_idx")
        turn_key = (session_id, turn_idx)

        # Cycle: COPY -> SUMMARIZE -> DROP -> COPY
        current_mode = self._context_modes.get(turn_key, ContextMode.DROP)
        if current_mode == ContextMode.COPY:
            self._context_modes[turn_key] = ContextMode.SUMMARIZE
        elif current_mode == ContextMode.SUMMARIZE:
            # Remove from dict means DROP
            self._context_modes.pop(turn_key, None)
        else:  # DROP
            self._context_modes[turn_key] = ContextMode.COPY

        self._update_turn_label(session_id, turn_idx)
        self._update_root_label()

    def on_selectable_tree_select_all_requested(self, event: SelectableTree.SelectAllRequested) -> None:
        """Set all turns to COPY mode."""
        for session_id, session_data in self._sessions.items():
            for turn in session_data["turns"]:
                turn_key = (session_id, turn["idx"])
                self._context_modes[turn_key] = ContextMode.COPY
                self._update_turn_label(session_id, turn["idx"])
        self._update_root_label()

    def on_selectable_tree_select_none_requested(self, event: SelectableTree.SelectNoneRequested) -> None:
        """Set all turns to DROP mode."""
        for turn_key in list(self._context_modes.keys()):
            session_id, turn_idx = turn_key
            self._context_modes.pop(turn_key, None)
            self._update_turn_label(session_id, turn_idx)
        self._update_root_label()

    def get_selected_messages(self) -> list:
        """Get included messages in order for context building.

        Returns Message objects with context_mode and content_blocks set
        from the original session message data.
        """
        from models import Message, TextBlock
        messages = []

        # Collect all included turns with their session order
        included_turns = []
        for session_id, session_data in self._sessions.items():
            session = session_data["session"]
            for turn in session_data["turns"]:
                turn_key = (session_id, turn["idx"])
                mode = self._context_modes.get(turn_key, ContextMode.DROP)
                if mode != ContextMode.DROP:
                    # Get original message from session if available
                    orig_msg = None
                    if turn["idx"] < len(session.messages):
                        orig_msg = session.messages[turn["idx"]]

                    included_turns.append({
                        "session_created": session.created,
                        "turn_idx": turn["idx"],
                        "role": turn["role"],
                        "content": turn["content"],
                        "mode": mode,
                        "orig_msg": orig_msg,
                    })

        # Sort by session date then turn index
        included_turns.sort(key=lambda t: (t["session_created"], t["turn_idx"]))

        for turn in included_turns:
            orig = turn["orig_msg"]
            if orig:
                # Use rich content from original message
                msg = Message(
                    role=turn["role"],
                    content=turn["content"],
                    content_blocks=orig.content_blocks,
                    context_mode=turn["mode"],
                    summary=orig.summary,
                )
            else:
                # Fallback to text-only
                msg = Message(
                    role=turn["role"],
                    content=turn["content"],
                    content_blocks=[TextBlock(text=turn["content"])],
                    context_mode=turn["mode"],
                )
            messages.append(msg)

        return messages

    def set_active_session(self, session_id: str) -> None:
        """Set the active session and update visual highlighting."""
        old_session_id = self._current_session_id
        self._current_session_id = session_id

        # Update old session's label (remove highlight)
        if old_session_id and old_session_id in self._sessions:
            old_data = self._sessions[old_session_id]
            old_data["is_current"] = False
            old_data["node"].label = self._make_session_label(old_data["session"], False)

        # Update new session's label (add highlight)
        if session_id in self._sessions:
            new_data = self._sessions[session_id]
            new_data["is_current"] = True
            new_data["node"].label = self._make_session_label(new_data["session"], True)

    def create_new_session(self) -> Session:
        """Create a new session and make it current."""
        new_session = Session()

        tree = self.query_one("#turn-tree", SelectableTree)

        # Add new session node (will be highlighted as active)
        session_label = self._make_session_label(new_session, True)
        session_node = tree.root.add(
            session_label,
            data={"type": "session", "session_id": new_session.id}
        )
        session_node.expand()

        # Update old active session's highlighting
        if self._current_session_id and self._current_session_id in self._sessions:
            old_data = self._sessions[self._current_session_id]
            old_data["is_current"] = False
            old_data["node"].label = self._make_session_label(old_data["session"], False)

        self._current_session_id = new_session.id

        self._sessions[new_session.id] = {
            "session": new_session,
            "turns": [],
            "node": session_node,
            "is_current": True,
        }

        self._update_root_label()
        return new_session

    def clear(self) -> None:
        """Clear all data."""
        tree = self.query_one("#turn-tree", SelectableTree)
        tree.root.remove_children()
        self._sessions.clear()
        self._context_modes.clear()
        self._current_session_id = None
        self._update_root_label()
