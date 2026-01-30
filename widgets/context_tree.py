from textual.widgets import Tree
from textual.containers import Vertical
from textual.message import Message
from textual.events import Key
from datetime import datetime

from tokenizer import count_tokens
from session import Session


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
        # Global selection: (session_id, turn_idx) -> selected
        self._selected: set[tuple[str, int]] = set()
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
        self._selected.clear()

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

    def _add_session_to_tree(self, tree: SelectableTree, session: Session, is_current: bool) -> None:
        """Add a session and its turns to the tree."""
        # Format session label
        try:
            dt = datetime.fromisoformat(session.created)
            date_str = dt.strftime("%b %d %H:%M")
        except:
            date_str = session.created[:16]

        current_marker = " [bold cyan](current)[/]" if is_current else ""
        msg_count = len(session.messages)
        session_label = f"{date_str} ({msg_count} msgs){current_marker}"

        session_node = tree.root.add(
            session_label,
            data={"type": "session", "session_id": session.id}
        )
        if is_current:
            session_node.expand()

        turns = []
        for idx, msg in enumerate(session.messages):
            # Auto-select current session's turns
            turn_key = (session.id, idx)
            if is_current:
                self._selected.add(turn_key)

            selected = turn_key in self._selected
            label = self._make_turn_label(msg.role, msg.content, selected)
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

    def _make_turn_label(self, role: str, content: str, selected: bool) -> str:
        checkbox = "[green]☑[/]" if selected else "☐"
        icon = "👤" if role == "user" else "🤖"
        preview = content[:40] + "..." if len(content) > 40 else content
        preview = preview.replace("\n", " ")
        return f"{checkbox} {icon} {preview}"

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
                if turn_key in self._selected:
                    selected_tokens += tokens
                    # Track selected turns from current session (1-indexed for chat_log)
                    if session_id == self._current_session_id:
                        current_session_turn_ids.append(turn["idx"] + 1)

        tree.root.label = f"[bold]{selected_tokens:,}[/] / {total_tokens:,} [dim]tokens[/]"

        self.post_message(self.SelectionChanged(
            len(self._selected), total_tokens, selected_tokens, current_session_turn_ids
        ))

    def _update_turn_label(self, session_id: str, turn_idx: int) -> None:
        """Update a turn's checkbox label."""
        session_data = self._sessions.get(session_id)
        if not session_data:
            return

        for turn in session_data["turns"]:
            if turn["idx"] == turn_idx:
                selected = (session_id, turn_idx) in self._selected
                turn["node"].label = self._make_turn_label(
                    turn["role"], turn["content"], selected
                )
                break

    def is_selection_curated(self) -> bool:
        """Check if selection differs from 'all current session turns'.

        Returns True if:
        - Any turn from another session is selected, OR
        - Any turn from current session is deselected
        """
        if not self._current_session_id:
            return False

        current_data = self._sessions.get(self._current_session_id)
        if not current_data:
            return False

        # Check if any non-current session turns are selected
        for turn_key in self._selected:
            if turn_key[0] != self._current_session_id:
                return True

        # Check if all current session turns are selected
        current_turn_count = len(current_data["turns"])
        current_selected = sum(
            1 for s_id, _ in self._selected if s_id == self._current_session_id
        )

        return current_selected != current_turn_count

    def add_turn_to_current(self, role: str, content: str, raw_events: list[dict]) -> None:
        """Add a new turn to the current session."""
        if not self._current_session_id:
            return

        session_data = self._sessions.get(self._current_session_id)
        if not session_data:
            return

        idx = len(session_data["turns"])
        turn_key = (self._current_session_id, idx)
        self._selected.add(turn_key)  # Auto-select new turns

        label = self._make_turn_label(role, content, True)
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
        msg_count = len(session_data["turns"])
        try:
            dt = datetime.fromisoformat(session_data["session"].created)
            date_str = dt.strftime("%b %d %H:%M")
        except:
            date_str = "now"
        session_data["node"].label = f"{date_str} ({msg_count} msgs) [bold cyan](current)[/]"

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
        """Handle space bar toggle."""
        node_type = event.node_data.get("type")
        if node_type != "turn":
            return

        session_id = event.node_data.get("session_id")
        turn_idx = event.node_data.get("turn_idx")
        turn_key = (session_id, turn_idx)

        if turn_key in self._selected:
            self._selected.discard(turn_key)
        else:
            self._selected.add(turn_key)

        self._update_turn_label(session_id, turn_idx)
        self._update_root_label()

    def on_selectable_tree_select_all_requested(self, event: SelectableTree.SelectAllRequested) -> None:
        """Select all turns."""
        for session_id, session_data in self._sessions.items():
            for turn in session_data["turns"]:
                turn_key = (session_id, turn["idx"])
                self._selected.add(turn_key)
                self._update_turn_label(session_id, turn["idx"])
        self._update_root_label()

    def on_selectable_tree_select_none_requested(self, event: SelectableTree.SelectNoneRequested) -> None:
        """Deselect all turns."""
        for turn_key in list(self._selected):
            session_id, turn_idx = turn_key
            self._selected.discard(turn_key)
            self._update_turn_label(session_id, turn_idx)
        self._update_root_label()

    def get_selected_messages(self) -> list:
        """Get selected messages in order for context building."""
        from models import Message
        messages = []

        # Collect all selected turns with their session order
        selected_turns = []
        for session_id, session_data in self._sessions.items():
            for turn in session_data["turns"]:
                turn_key = (session_id, turn["idx"])
                if turn_key in self._selected:
                    selected_turns.append({
                        "session_created": session_data["session"].created,
                        "turn_idx": turn["idx"],
                        "role": turn["role"],
                        "content": turn["content"],
                    })

        # Sort by session date then turn index
        selected_turns.sort(key=lambda t: (t["session_created"], t["turn_idx"]))

        for turn in selected_turns:
            messages.append(Message(role=turn["role"], content=turn["content"]))

        return messages

    def create_new_session(self) -> Session:
        """Create a new session and make it current."""
        new_session = Session()
        self._current_session_id = new_session.id

        tree = self.query_one("#turn-tree", SelectableTree)

        # Add new session node at the top (after root's children start)
        date_str = datetime.now().strftime("%b %d %H:%M")
        session_node = tree.root.add(
            f"{date_str} (0 msgs) [bold cyan](current)[/]",
            data={"type": "session", "session_id": new_session.id}
        )
        session_node.expand()

        # Move to top by removing and re-adding others (hacky but works)
        # Actually, Textual trees add at the end, so we need to rebuild
        # For now, new sessions appear at bottom - we'll fix ordering later

        # Remove current marker from old current
        for session_id, session_data in self._sessions.items():
            if session_data.get("is_current"):
                session_data["is_current"] = False
                # Update label to remove (current)
                msg_count = len(session_data["turns"])
                try:
                    dt = datetime.fromisoformat(session_data["session"].created)
                    ds = dt.strftime("%b %d %H:%M")
                except:
                    ds = "?"
                session_data["node"].label = f"{ds} ({msg_count} msgs)"

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
        self._selected.clear()
        self._current_session_id = None
        self._update_root_label()
