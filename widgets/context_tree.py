from textual.widgets import Tree, Input
from textual.containers import Vertical
from textual.message import Message
from textual.events import Key
from textual.binding import Binding
from datetime import datetime

from tokenizer import count_tokens
from session import Session
from models import ContextMode, TextBlock, ToolUseBlock, ToolResultBlock


class SelectableTree(Tree):
    """Tree with space-bar toggle for multiselect.

    Behavior:
    - Space: toggle context mode (COPY -> COMPRESS -> DROP)
    - Enter: activate/navigate to session (doesn't toggle expand)
    - a: select all turns in current session
    - n: deselect all turns in current session
    - /: search
    """

    class ToggleRequested(Message):
        def __init__(self, node_data: dict) -> None:
            self.node_data = node_data
            super().__init__()

    class ActivateRequested(Message):
        """Fired when user presses Enter to activate/navigate."""
        def __init__(self, node_data: dict) -> None:
            self.node_data = node_data
            super().__init__()

    class SelectAllRequested(Message):
        pass

    class SelectNoneRequested(Message):
        pass

    class SearchRequested(Message):
        """Fired when user presses / to start searching."""
        pass

    async def _on_key(self, event: Key) -> None:
        if event.key == "space":
            node = self.cursor_node
            if node and node.data:
                self.post_message(self.ToggleRequested(node.data))
                event.prevent_default()
                event.stop()
                return
        elif event.key == "enter":
            # Use Enter for activation instead of letting Tree toggle expand
            node = self.cursor_node
            if node and node.data:
                self.post_message(self.ActivateRequested(node.data))
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
        elif event.key == "slash":
            self.post_message(self.SearchRequested())
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

    ContextTree > #search-input {
        dock: top;
        display: none;
        height: auto;
        margin: 0;
        padding: 0 1;
        border: none;
        background: $surface;
    }

    ContextTree > #search-input.visible {
        display: block;
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
            turn_modes: dict[int, str] | None = None,
        ) -> None:
            self.selected_count = selected_count
            self.total_tokens = total_tokens
            self.selected_tokens = selected_tokens
            # Turn IDs for current session (1-indexed to match chat_log)
            self.selected_turn_ids = current_session_turn_ids
            self.show_all = False  # Could be computed if all current session turns selected
            # Full mapping of turn_id -> mode name for visual indication
            self.turn_modes = turn_modes or {}
            super().__init__()

    class SessionActivated(Message):
        """Fired when user clicks on a session to view it."""
        def __init__(self, session: Session) -> None:
            self.session = session
            super().__init__()

    class TurnInspected(Message):
        """Fired when user selects a turn to inspect its data."""
        def __init__(self, turn_data: dict, session_id: str | None = None) -> None:
            self.turn_data = turn_data
            self.session_id = session_id  # Session this turn belongs to
            super().__init__()

    class ContextModeChanged(Message):
        """Fired when a turn's context mode is toggled, so app can persist it."""
        def __init__(self, session_id: str, turn_idx: int, new_mode: ContextMode) -> None:
            self.session_id = session_id
            self.turn_idx = turn_idx
            self.new_mode = new_mode
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Context mode per turn: (session_id, turn_idx) -> ContextMode
        # Missing entries default to DROP (not in context)
        self._context_modes: dict[tuple[str, int], ContextMode] = {}
        # Context mode per merge: ("merge", parent_session_id, fork_session_id) -> ContextMode
        # Merges default to COPY (include merge summary in context)
        self._merge_modes: dict[tuple[str, str, str], ContextMode] = {}
        # All loaded sessions with their turns
        self._sessions: dict[str, dict] = {}  # session_id -> {session, turns, node}
        self._current_session_id: str | None = None
        self._search_query: str = ""

    def compose(self):
        yield Input(placeholder="Search sessions...", id="search-input")
        tree = SelectableTree("[dim]loading...[/]", id="turn-tree")
        tree.root.data = {"type": "root"}
        yield tree

    def on_mount(self) -> None:
        tree = self.query_one("#turn-tree", SelectableTree)
        tree.root.expand()
        tree.root.allow_expand = False
        tree.auto_expand = False  # Don't auto-expand on selection

    def load_all_sessions(self, current_session: Session) -> None:
        """Load all sessions into the tree."""
        self._current_session_id = current_session.id

        # Get all sessions
        all_sessions = Session.list_sessions()

        tree = self.query_one("#turn-tree", SelectableTree)
        tree.root.remove_children()
        self._sessions.clear()
        self._context_modes.clear()
        self._merge_modes.clear()

        # Add current session first if it's new (not in list)
        session_ids_in_list = {s[0] for s in all_sessions}
        if current_session.id not in session_ids_in_list:
            self._add_session_to_tree(tree, current_session, is_current=True)

        # Add all sessions (newest first - already sorted)
        for session_id, created, model, _title in all_sessions:
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

        # Show fork status indicator
        if session.is_fork():
            if session.is_merged():
                prefix = "[green]✓[/] "
                status = "[dim][merged][/]"
            else:
                prefix = "[magenta]↳[/] "
                status = ""
        else:
            prefix = ""
            status = ""

        # Build label: fork name or title (if present), session ID prefix, msg count, datetime
        if session.fork_name:
            name_part = session.fork_name
        elif session.title:
            name_part = session.title[:25] + "..." if len(session.title) > 25 else session.title
        else:
            name_part = None

        # Always show session ID prefix for identification
        id_prefix = f"[dim]{session.id[:8]}[/] "

        if name_part:
            label = f"{id_prefix}{name_part} ({msg_count}) {date_str} {status}"
        else:
            label = f"{id_prefix}{date_str} ({msg_count} msgs) {status}"

        # Highlight active session
        if is_active:
            return f"{prefix}[bold cyan]{label}[/]"
        else:
            return f"{prefix}{label}"

    def _add_session_to_tree(self, tree: SelectableTree, session: Session, is_current: bool) -> None:
        """Add a session and its turns to the tree.

        Forks are shown inline at their fork point in the parent session.
        """
        session_label = self._make_session_label(session, is_current)

        session_node = tree.root.add(
            session_label,
            data={"type": "session", "session_id": session.id}
        )
        if is_current:
            session_node.expand()

        # Build a map of fork_point -> fork info for inline display
        fork_points = {}  # turn_idx -> list of forks
        merge_points = {}  # turn_idx -> list of merges
        for child in session.children:
            fork_point = child.get("fork_point", -1)
            merge_point = child.get("merge_point", -1)
            if fork_point >= 0:
                fork_points.setdefault(fork_point, []).append(child)
            if merge_point >= 0 and child.get("status") == "merged":
                merge_points.setdefault(merge_point, []).append(child)

        turns = []
        for idx, msg in enumerate(session.messages):
            turn_key = (session.id, idx)
            # Use persisted context_mode from message
            if hasattr(msg, 'context_mode'):
                self._context_modes[turn_key] = msg.context_mode
            elif is_current:
                # Default: current session turns are COPY
                self._context_modes[turn_key] = ContextMode.COPY

            mode = self._context_modes.get(turn_key, ContextMode.DROP)
            content_blocks = msg.content_blocks if hasattr(msg, 'content_blocks') else []
            label = self._make_turn_label(msg.role, msg.content, mode, content_blocks)
            turn_node = session_node.add(
                label,
                data={"type": "turn", "session_id": session.id, "turn_idx": idx}
            )

            # Add child nodes for tool uses and results
            self._add_content_block_nodes(turn_node, session.id, idx, content_blocks)

            turns.append({
                "idx": idx,
                "role": msg.role,
                "content": msg.content,
                "content_blocks": content_blocks,
                "node": turn_node,
                "events": [],  # Could load from storage if we save them
            })

            # Add any forks that started after this turn
            for fork in fork_points.get(idx, []):
                self._add_fork_node(session_node, session.id, fork, tree)

            # Add any merges that happened after this turn
            for merge in merge_points.get(idx, []):
                self._add_merge_node(session_node, session.id, merge)

        # Add any forks at the end (fork_point >= len(messages))
        for fork in fork_points.get(len(session.messages), []):
            self._add_fork_node(session_node, session.id, fork, tree)

        self._sessions[session.id] = {
            "session": session,
            "turns": turns,
            "node": session_node,
            "is_current": is_current,
        }

    def _add_fork_node(self, parent_node, parent_session_id: str, fork: dict, tree: SelectableTree) -> None:
        """Add a fork node (with its contents) inline in the parent session."""
        fork_id = fork.get("session_id", "")
        fork_name = fork.get("name", "") or fork_id[:8]
        status = fork.get("status", "active")

        # Status indicator
        if status == "active":
            status_text = "[yellow][active][/]"
        elif status == "merged":
            status_text = "[green][merged ✓][/]"
        else:
            status_text = f"[dim][{status}][/]"

        label = f"[bold]🔀 {fork_name}[/] {status_text}"
        fork_node = parent_node.add(
            label,
            data={
                "type": "fork",
                "session_id": fork_id,
                "parent_session_id": parent_session_id,
                "fork_name": fork_name,
                "status": status,
            }
        )

        # Load and add the fork's turns as children
        fork_session = Session.load(fork_id)
        if fork_session:
            for idx, msg in enumerate(fork_session.messages):
                content_blocks = msg.content_blocks if hasattr(msg, 'content_blocks') else []
                # Fork turns don't have context modes - they're just for viewing
                turn_label = self._make_turn_label(msg.role, msg.content, ContextMode.DROP, content_blocks)
                turn_node = fork_node.add(
                    turn_label,
                    data={"type": "turn", "session_id": fork_id, "turn_idx": idx}
                )
                self._add_content_block_nodes(turn_node, fork_id, idx, content_blocks)

            # Recursively add nested forks
            for nested_fork in fork_session.children:
                nested_fork_point = nested_fork.get("fork_point", -1)
                if nested_fork_point >= 0:
                    # For simplicity, add nested forks at the end
                    self._add_fork_node(fork_node, fork_id, nested_fork, tree)

    def _add_merge_node(self, parent_node, parent_session_id: str, merge: dict) -> None:
        """Add a merge result node inline in the parent session."""
        fork_id = merge.get("session_id", "")
        fork_name = merge.get("name", "") or fork_id[:8]

        # Load fork to get merge message
        fork_session = Session.load(fork_id)
        merge_message = fork_session.merge_message if fork_session else ""

        # Get or initialize context mode for this merge
        merge_key = ("merge", parent_session_id, fork_id)
        # Default merges to COPY (include in context)
        if merge_key not in self._merge_modes:
            self._merge_modes[merge_key] = ContextMode.COPY
        mode = self._merge_modes[merge_key]

        label = self._make_merge_label(fork_name, merge_message, mode)
        parent_node.add(
            label,
            data={
                "type": "merge",
                "session_id": fork_id,
                "parent_session_id": parent_session_id,
                "fork_name": fork_name,
                "message": merge_message,
            }
        )

    def _make_merge_label(self, fork_name: str, merge_message: str, mode: ContextMode) -> str:
        """Create a label for a merge node with context mode indicator."""
        # Mode indicator (same style as turns)
        if mode == ContextMode.COPY:
            mode_indicator = "[green]●[/] "
        elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            mode_indicator = "[yellow]◐[/] "
        else:  # DROP
            mode_indicator = "[dim]○[/] "

        # Truncate message for display
        msg_preview = merge_message[:40] + "..." if len(merge_message) > 40 else merge_message
        msg_preview = msg_preview.replace("\n", " ")

        return f"{mode_indicator}[green]⬅️ Merged: {fork_name}[/] {msg_preview}"

    def _add_content_block_nodes(self, turn_node, session_id: str, turn_idx: int, content_blocks: list) -> None:
        """Add child nodes for text blocks, tool uses and results within a turn."""
        if not content_blocks:
            return

        import json
        # Track tool use nodes by their id so we can nest results under them
        tool_use_nodes: dict[str, any] = {}

        for block_idx, block in enumerate(content_blocks):
            if isinstance(block, TextBlock):
                # Only add text blocks with meaningful content
                if block.text.strip():
                    text_preview = block.text[:50].replace("\n", " ")
                    if len(block.text) > 50:
                        text_preview += "..."
                    label = f"[dim]💬[/] {text_preview}"
                    turn_node.add(
                        label,
                        data={
                            "type": "text",
                            "session_id": session_id,
                            "turn_idx": turn_idx,
                            "block_idx": block_idx,
                            "text": block.text,
                        }
                    )
            elif isinstance(block, ToolUseBlock):
                # Truncate input preview
                input_preview = json.dumps(block.input)[:50]
                if len(json.dumps(block.input)) > 50:
                    input_preview += "..."
                label = f"[cyan]🔧 {block.name}[/] {input_preview}"
                tool_node = turn_node.add(
                    label,
                    data={
                        "type": "tool_use",
                        "session_id": session_id,
                        "turn_idx": turn_idx,
                        "block_idx": block_idx,
                        "tool_name": block.name,
                        "tool_input": block.input,
                        "tool_use_id": block.id,
                    }
                )
                tool_use_nodes[block.id] = tool_node
            elif isinstance(block, ToolResultBlock):
                content_preview = str(block.content)[:50]
                if len(str(block.content)) > 50:
                    content_preview += "..."
                error_indicator = "[red]❌[/] " if block.is_error else ""
                label = f"{error_indicator}[blue]📋 Result[/] {content_preview}"
                # Find parent tool use node, or fall back to turn node
                parent_node = tool_use_nodes.get(block.tool_use_id, turn_node)
                parent_node.add(
                    label,
                    data={
                        "type": "tool_result",
                        "session_id": session_id,
                        "turn_idx": turn_idx,
                        "block_idx": block_idx,
                        "content": block.content,
                        "is_error": block.is_error,
                        "tool_use_id": block.tool_use_id,
                    }
                )

    def _make_turn_label(self, role: str, content: str, mode: ContextMode, content_blocks: list = None) -> str:
        # Mode indicator: copy=green check, compress=yellow Σ, drop=empty box
        if mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            indicator = "[yellow]Σ[/]"
        else:  # DROP
            indicator = "☐"

        icon = "👤" if role == "user" else "🤖"

        # Count tool uses if content_blocks provided
        tool_count = 0
        if content_blocks:
            tool_count = sum(1 for b in content_blocks if isinstance(b, ToolUseBlock))

        preview = content[:30] + "..." if len(content) > 30 else content
        preview = preview.replace("\n", " ")

        # Add tool indicator
        tool_indicator = f" [cyan]🔧{tool_count}[/]" if tool_count > 0 else ""
        return f"{indicator} {icon}{tool_indicator} {preview}"

    def _update_root_label(self) -> None:
        """Update root label with selected/total tokens."""
        tree = self.query_one("#turn-tree", SelectableTree)

        selected_tokens = 0
        total_tokens = 0
        current_session_turn_ids = []
        # Build turn_modes dict for current session (1-indexed turn_id -> mode name)
        turn_modes: dict[int, str] = {}

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

                # Build turn_modes for current session
                if session_id == self._current_session_id:
                    turn_id = turn["idx"] + 1  # 1-indexed
                    turn_modes[turn_id] = mode.name

            # Count merge summaries for this session
            session = session_data["session"]
            for child in session.children:
                if child.get("status") == "merged":
                    fork_id = child.get("session_id", "")
                    merge_key = ("merge", session_id, fork_id)
                    # Load fork to get merge message
                    fork_session = Session.load(fork_id)
                    if fork_session and fork_session.merge_message:
                        merge_tokens = count_tokens(fork_session.merge_message)
                        total_tokens += merge_tokens
                        mode = self._merge_modes.get(merge_key, ContextMode.COPY)
                        if mode != ContextMode.DROP:
                            selected_tokens += merge_tokens

        included_count = sum(1 for m in self._context_modes.values() if m != ContextMode.DROP)
        included_count += sum(1 for m in self._merge_modes.values() if m != ContextMode.DROP)
        tree.root.label = f"[bold]{selected_tokens:,}[/] / {total_tokens:,} [dim]tokens[/]"

        self.post_message(self.SelectionChanged(
            included_count, total_tokens, selected_tokens, current_session_turn_ids, turn_modes
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
                    turn["role"], turn["content"], mode, turn.get("content_blocks")
                )
                break

    def _update_merge_label(self, parent_session_id: str, fork_id: str, node_data: dict) -> None:
        """Update a merge node's mode indicator label."""
        # Find the merge node in the tree by walking children
        session_data = self._sessions.get(parent_session_id)
        if not session_data:
            return

        merge_key = ("merge", parent_session_id, fork_id)
        mode = self._merge_modes.get(merge_key, ContextMode.COPY)

        # Find the node in the session's children
        for node in session_data["node"].children:
            if node.data and node.data.get("type") == "merge" and node.data.get("session_id") == fork_id:
                fork_name = node_data.get("fork_name", fork_id[:8])
                merge_message = node_data.get("message", "")
                node.label = self._make_merge_label(fork_name, merge_message, mode)
                break

    def is_selection_curated(self) -> bool:
        """Check if selection differs from 'all current session turns as COPY'.

        Returns True if:
        - Any turn from another session is included, OR
        - Any turn from current session is not COPY, OR
        - Any turn uses COMPRESS mode
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

    def add_turn_to_current(self, role: str, content: str, raw_events: list[dict], content_blocks: list = None) -> None:
        """Add a new turn to the current session."""
        if not self._current_session_id:
            return

        session_data = self._sessions.get(self._current_session_id)
        if not session_data:
            return

        idx = len(session_data["turns"])
        turn_key = (self._current_session_id, idx)
        self._context_modes[turn_key] = ContextMode.COPY  # Auto-include new turns as COPY

        label = self._make_turn_label(role, content, ContextMode.COPY, content_blocks)
        turn_node = session_data["node"].add(
            label,
            data={"type": "turn", "session_id": self._current_session_id, "turn_idx": idx}
        )

        # Add child nodes for tool uses and results
        if content_blocks:
            self._add_content_block_nodes(turn_node, self._current_session_id, idx, content_blocks)

        session_data["turns"].append({
            "idx": idx,
            "role": role,
            "content": content,
            "content_blocks": content_blocks or [],
            "node": turn_node,
            "events": raw_events,
        })

        # Update session label with new count
        session = session_data["session"]
        is_active = session.id == self._current_session_id
        session_data["node"].label = self._make_session_label(session, is_active)

        self._update_root_label()

    # --- Streaming-aware methods for incremental tree updates ---

    def start_turn(self, session_id: str, turn_idx: int, role: str) -> None:
        """Start a new turn node when streaming begins.

        Called when a 'turn_started' event is received from SessionRunner.
        Creates a placeholder turn node that will be populated as events arrive.
        """
        session_data = self._sessions.get(session_id)
        if not session_data:
            return

        turn_key = (session_id, turn_idx)
        self._context_modes[turn_key] = ContextMode.COPY  # Auto-include as COPY

        # Create placeholder label
        label = self._make_turn_label(role, "[dim]streaming...[/]", ContextMode.COPY)
        turn_node = session_data["node"].add(
            label,
            data={"type": "turn", "session_id": session_id, "turn_idx": turn_idx}
        )
        turn_node.expand()

        # Track the streaming turn
        session_data["turns"].append({
            "idx": turn_idx,
            "role": role,
            "content": "",  # Will be updated when streaming completes
            "content_blocks": [],
            "node": turn_node,
            "events": [],
            "_streaming": True,  # Mark as streaming
            "_tool_use_nodes": {},  # Track tool use nodes by id for nesting results
        })

        # Update session label with new count
        session = session_data["session"]
        is_active = session.id == self._current_session_id
        session_data["node"].label = self._make_session_label(session, is_active)

        self._update_root_label()

    def add_tool_use_to_turn(
        self,
        session_id: str,
        turn_idx: int,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict,
        tool_index: int,
    ) -> None:
        """Add a tool use node during streaming.

        Called when a 'tool_use' event is received from SessionRunner.
        """
        session_data = self._sessions.get(session_id)
        if not session_data:
            return

        # Find the streaming turn
        turn = None
        for t in session_data["turns"]:
            if t["idx"] == turn_idx:
                turn = t
                break
        if not turn:
            return

        import json
        input_preview = json.dumps(tool_input)[:50]
        if len(json.dumps(tool_input)) > 50:
            input_preview += "..."
        label = f"[cyan]🔧 {tool_name}[/] {input_preview}"

        tool_node = turn["node"].add(
            label,
            data={
                "type": "tool_use",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "block_idx": tool_index,  # Use tool_index as block_idx
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_use_id": tool_use_id,
            }
        )

        # Track for nesting results
        turn.get("_tool_use_nodes", {})[tool_use_id] = tool_node

        # Update turn label to show tool count
        tool_count = len(turn.get("_tool_use_nodes", {}))
        icon = "👤" if turn["role"] == "user" else "🤖"
        mode = self._context_modes.get((session_id, turn_idx), ContextMode.DROP)
        if mode == ContextMode.COPY:
            indicator = "[green]☑[/]"
        elif mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            indicator = "[yellow]Σ[/]"
        else:
            indicator = "☐"
        turn["node"].label = f"{indicator} {icon} [cyan]🔧{tool_count}[/] [dim]streaming...[/]"

    def add_tool_result_to_turn(
        self,
        session_id: str,
        turn_idx: int,
        tool_use_id: str,
        result: str,
        is_error: bool = False,
        tool_index: int = None,
    ) -> None:
        """Add a tool result node during streaming.

        Called when a 'tool_result' event is received from SessionRunner.
        Results are nested under their corresponding tool use.
        """
        session_data = self._sessions.get(session_id)
        if not session_data:
            return

        # Find the streaming turn
        turn = None
        for t in session_data["turns"]:
            if t["idx"] == turn_idx:
                turn = t
                break
        if not turn:
            return

        content_preview = str(result)[:50]
        if len(str(result)) > 50:
            content_preview += "..."
        error_indicator = "[red]❌[/] " if is_error else ""
        label = f"{error_indicator}[blue]📋 Result[/] {content_preview}"

        # Find parent tool use node, or fall back to turn node
        tool_use_nodes = turn.get("_tool_use_nodes", {})
        parent_node = tool_use_nodes.get(tool_use_id, turn["node"])
        parent_node.add(
            label,
            data={
                "type": "tool_result",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "block_idx": tool_index,
                "content": result,
                "is_error": is_error,
                "tool_use_id": tool_use_id,
            }
        )

    def finish_turn(
        self,
        session_id: str,
        turn_idx: int,
        content: str,
        content_blocks: list,
        raw_events: list[dict],
    ) -> None:
        """Finalize a streaming turn when complete.

        Called when a 'done' event is received from SessionRunner.
        Updates the turn label with final content and rebuilds child nodes in order.
        """
        session_data = self._sessions.get(session_id)
        if not session_data:
            return

        # Find the streaming turn
        turn = None
        for t in session_data["turns"]:
            if t["idx"] == turn_idx:
                turn = t
                break
        if not turn:
            return

        # Update turn data
        turn["content"] = content
        turn["content_blocks"] = content_blocks
        turn["events"] = raw_events
        turn["_streaming"] = False

        # Clear existing children (added during streaming) and rebuild in correct order
        turn["node"].remove_children()
        self._add_content_block_nodes(turn["node"], session_id, turn_idx, content_blocks)

        # Update label with final content
        mode = self._context_modes.get((session_id, turn_idx), ContextMode.DROP)
        turn["node"].label = self._make_turn_label(
            turn["role"], content, mode, content_blocks
        )

        self._update_root_label()

    def on_tree_node_selected(self, event) -> None:
        """Handle node selection - switch session or inspect turn."""
        from core.debug_log import debug_log
        node_data = event.node.data
        if not node_data:
            debug_log.debug("on_tree_node_selected: no node_data", category="tree")
            return

        node_type = node_data.get("type")
        debug_log.info(f"on_tree_node_selected: type={node_type}, data={node_data}", category="tree")

        if node_type == "session":
            session_id = node_data.get("session_id")
            session_data = self._sessions.get(session_id)
            if session_data:
                self.post_message(self.SessionActivated(session_data["session"]))
        elif node_type == "summary":
            # Show full summary in the inspection pane
            session_id = node_data.get("session_id")
            session_data = self._sessions.get(session_id)
            if session_data:
                session = session_data["session"]
                self.post_message(self.TurnInspected({
                    "type": "summary",
                    "title": session.title,
                    "summary": session.summary,
                    "session_id": session_id,
                }))
        elif node_type == "turn":
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            session_data = self._sessions.get(session_id)
            if session_data:
                for turn in session_data["turns"]:
                    if turn["idx"] == turn_idx:
                        # Get context mode for this turn
                        turn_key = (session_id, turn_idx)
                        mode = self._context_modes.get(turn_key, ContextMode.DROP)
                        # Send turn data for inspection (includes session_id for cross-session navigation)
                        self.post_message(self.TurnInspected({
                            "type": "turn",
                            "role": turn["role"],
                            "content": turn["content"],
                            "events": turn.get("events", []),
                            "turn_idx": turn_idx,
                            "context_mode": mode.name,
                        }, session_id=session_id))
                        break
        elif node_type == "text":
            # Send text block data for inspection and highlighting
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            turn_key = (session_id, turn_idx)
            mode = self._context_modes.get(turn_key, ContextMode.DROP)
            self.post_message(self.TurnInspected({
                "type": "text",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "block_idx": node_data.get("block_idx"),
                "text": node_data.get("text"),
                "context_mode": mode.name,
            }, session_id=session_id))
        elif node_type == "tool_use":
            # Send tool use data for inspection and highlighting
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            turn_key = (session_id, turn_idx)
            mode = self._context_modes.get(turn_key, ContextMode.DROP)
            self.post_message(self.TurnInspected({
                "type": "tool_use",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "block_idx": node_data.get("block_idx"),
                "tool_name": node_data.get("tool_name"),
                "tool_input": node_data.get("tool_input"),
                "tool_use_id": node_data.get("tool_use_id"),
                "context_mode": mode.name,
            }, session_id=session_id))
        elif node_type == "tool_result":
            # Send tool result data for inspection and highlighting
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            turn_key = (session_id, turn_idx)
            mode = self._context_modes.get(turn_key, ContextMode.DROP)
            self.post_message(self.TurnInspected({
                "type": "tool_result",
                "session_id": session_id,
                "turn_idx": turn_idx,
                "block_idx": node_data.get("block_idx"),
                "content": node_data.get("content"),
                "is_error": node_data.get("is_error"),
                "tool_use_id": node_data.get("tool_use_id"),
                "context_mode": mode.name,
            }, session_id=session_id))
        elif node_type == "fork":
            # Navigate to the fork session
            session_id = node_data.get("session_id")
            fork_session = Session.load(session_id)
            if fork_session:
                self.post_message(self.SessionActivated(fork_session))
        elif node_type == "merge":
            # Show merge details in inspection pane
            fork_id = node_data.get("session_id")
            parent_session_id = node_data.get("parent_session_id")
            fork_name = node_data.get("fork_name", "")
            merge_message = node_data.get("message", "")
            merge_key = ("merge", parent_session_id, fork_id)
            mode = self._merge_modes.get(merge_key, ContextMode.COPY)
            self.post_message(self.TurnInspected({
                "type": "merge",
                "session_id": fork_id,
                "parent_session_id": parent_session_id,
                "fork_name": fork_name,
                "message": merge_message,
                "context_mode": mode.name,
            }, session_id=parent_session_id))

    def on_selectable_tree_activate_requested(self, event: SelectableTree.ActivateRequested) -> None:
        """Handle Enter key - activate/navigate without toggling expand."""
        node_data = event.node_data
        node_type = node_data.get("type")

        if node_type == "session":
            # Navigate to session
            session_id = node_data.get("session_id")
            session_data = self._sessions.get(session_id)
            if session_data:
                self.post_message(self.SessionActivated(session_data["session"]))
        elif node_type == "fork":
            # Navigate to fork
            session_id = node_data.get("session_id")
            fork_session = Session.load(session_id)
            if fork_session:
                self.post_message(self.SessionActivated(fork_session))
        elif node_type == "merge":
            # Navigate to merged fork
            session_id = node_data.get("session_id")
            fork_session = Session.load(session_id)
            if fork_session:
                self.post_message(self.SessionActivated(fork_session))
        elif node_type == "turn":
            # Toggle context mode on Enter for turns (same as space)
            session_id = node_data.get("session_id")
            turn_idx = node_data.get("turn_idx")
            turn_key = (session_id, turn_idx)
            current_mode = self._context_modes.get(turn_key, ContextMode.DROP)
            if current_mode == ContextMode.COPY:
                new_mode = ContextMode.COMPRESS
                self._context_modes[turn_key] = new_mode
            elif current_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
                new_mode = ContextMode.DROP
                self._context_modes.pop(turn_key, None)
            else:
                new_mode = ContextMode.COPY
                self._context_modes[turn_key] = new_mode
            self._update_turn_label(session_id, turn_idx)
            self._update_root_label()
            # Notify app to persist the change
            self.post_message(self.ContextModeChanged(session_id, turn_idx, new_mode))

    def on_selectable_tree_toggle_requested(self, event: SelectableTree.ToggleRequested) -> None:
        """Handle space bar toggle - cycle through COPY -> COMPRESS -> DROP."""
        node_type = event.node_data.get("type")

        if node_type == "turn":
            session_id = event.node_data.get("session_id")
            turn_idx = event.node_data.get("turn_idx")
            turn_key = (session_id, turn_idx)

            # Cycle: COPY -> COMPRESS -> DROP -> COPY
            current_mode = self._context_modes.get(turn_key, ContextMode.DROP)
            if current_mode == ContextMode.COPY:
                new_mode = ContextMode.COMPRESS
                self._context_modes[turn_key] = new_mode
            elif current_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
                # Remove from dict means DROP
                new_mode = ContextMode.DROP
                self._context_modes.pop(turn_key, None)
            else:  # DROP
                new_mode = ContextMode.COPY
                self._context_modes[turn_key] = new_mode

            self._update_turn_label(session_id, turn_idx)
            self._update_root_label()
            # Notify app to persist the change
            self.post_message(self.ContextModeChanged(session_id, turn_idx, new_mode))

        elif node_type == "merge":
            fork_id = event.node_data.get("session_id")
            parent_session_id = event.node_data.get("parent_session_id")
            merge_key = ("merge", parent_session_id, fork_id)

            # Cycle: COPY -> COMPRESS -> DROP -> COPY
            current_mode = self._merge_modes.get(merge_key, ContextMode.COPY)
            if current_mode == ContextMode.COPY:
                self._merge_modes[merge_key] = ContextMode.COMPRESS
            elif current_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
                self._merge_modes[merge_key] = ContextMode.DROP
            else:  # DROP
                self._merge_modes[merge_key] = ContextMode.COPY

            self._update_merge_label(parent_session_id, fork_id, event.node_data)
            self._update_root_label()

    def on_selectable_tree_select_all_requested(self, event: SelectableTree.SelectAllRequested) -> None:
        """Set all turns in CURRENT session to COPY mode."""
        if not self._current_session_id:
            return
        session_data = self._sessions.get(self._current_session_id)
        if not session_data:
            return
        for turn in session_data["turns"]:
            turn_key = (self._current_session_id, turn["idx"])
            self._context_modes[turn_key] = ContextMode.COPY
            self._update_turn_label(self._current_session_id, turn["idx"])
        self._update_root_label()

    def on_selectable_tree_select_none_requested(self, event: SelectableTree.SelectNoneRequested) -> None:
        """Set all turns in CURRENT session to DROP mode."""
        if not self._current_session_id:
            return
        session_data = self._sessions.get(self._current_session_id)
        if not session_data:
            return
        for turn in session_data["turns"]:
            turn_key = (self._current_session_id, turn["idx"])
            self._context_modes.pop(turn_key, None)
            self._update_turn_label(self._current_session_id, turn["idx"])
        self._update_root_label()

    def on_selectable_tree_search_requested(self, event: SelectableTree.SearchRequested) -> None:
        """Show the search input when / is pressed."""
        search_input = self.query_one("#search-input", Input)
        search_input.add_class("visible")
        search_input.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter tree nodes as user types."""
        if event.input.id == "search-input":
            self._search_query = event.value.lower()
            self._apply_search_filter()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Hide search and focus tree when Enter is pressed."""
        if event.input.id == "search-input":
            self._hide_search()

    def _on_key(self, event: Key) -> None:
        """Handle Escape to clear search."""
        if event.key == "escape":
            search_input = self.query_one("#search-input", Input)
            if search_input.has_class("visible"):
                self._clear_search()
                event.prevent_default()
                event.stop()

    def _hide_search(self) -> None:
        """Hide search input and focus tree."""
        search_input = self.query_one("#search-input", Input)
        search_input.remove_class("visible")
        tree = self.query_one("#turn-tree", SelectableTree)
        tree.focus()

    def _clear_search(self) -> None:
        """Clear search and show all nodes."""
        search_input = self.query_one("#search-input", Input)
        search_input.value = ""
        self._search_query = ""
        self._apply_search_filter()
        self._hide_search()

    def _apply_search_filter(self) -> None:
        """Rebuild tree showing only nodes matching the search query."""
        tree = self.query_one("#turn-tree", SelectableTree)
        tree.root.remove_children()

        for session_id, session_data in self._sessions.items():
            session = session_data["session"]
            is_current = session_data["is_current"]

            # Find matching turns
            matching_turns = []
            for turn in session_data["turns"]:
                if self._turn_matches_search(turn, session):
                    matching_turns.append(turn)

            # Skip session if no matches and we have a search query
            if self._search_query and not matching_turns:
                continue

            # Recreate session node
            session_label = self._make_session_label(session, is_current)
            session_node = tree.root.add(
                session_label,
                data={"type": "session", "session_id": session.id}
            )
            session_data["node"] = session_node

            # Add turns (filtered or all)
            turns_to_show = matching_turns if self._search_query else session_data["turns"]
            for turn in turns_to_show:
                idx = turn["idx"]
                mode = self._context_modes.get((session.id, idx), ContextMode.DROP)
                content_blocks = turn.get("content_blocks", [])
                label = self._make_turn_label(turn["role"], turn["content"], mode, content_blocks)
                turn_node = session_node.add(
                    label,
                    data={"type": "turn", "session_id": session.id, "turn_idx": idx}
                )
                turn["node"] = turn_node

                # Add content block children
                self._add_content_block_nodes(turn_node, session.id, idx, content_blocks)

            # Expand session if it has matches or is current
            if matching_turns or is_current:
                session_node.expand()

        self._update_root_label()

    def _turn_matches_search(self, turn: dict, session: Session) -> bool:
        """Check if a turn matches the current search query."""
        if not self._search_query:
            return True

        # Check session title
        if session.title and self._search_query in session.title.lower():
            return True

        # Check turn content
        if self._search_query in turn["content"].lower():
            return True

        # Check tool names
        for block in turn.get("content_blocks", []):
            if isinstance(block, ToolUseBlock):
                if self._search_query in block.name.lower():
                    return True

        return False

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
        self._merge_modes.clear()
        self._current_session_id = None
        self._update_root_label()
