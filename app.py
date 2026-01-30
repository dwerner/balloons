import asyncio
import subprocess
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical

from widgets import ChatLog, InputBox, StatusBar, ContextTree, VerticalSplitter, SessionPicker, RequestPane, ToolBar
from claude_runner import ClaudeRunner
from session import Session
from models import TextDelta, ResultEvent, InitEvent, RawEvent, ToolUseEvent, ToolResultEvent


class BaloonsApp(App):
    """A TUI chat interface for Claude."""

    TITLE = "Baloons"
    SUB_TITLE = "Claude TUI"

    CSS = """
    #main-split {
        height: 1fr;
    }

    ContextTree {
        width: 50;
    }

    #chat-container {
        height: 1fr;
    }

    ChatLog {
        height: 1fr;
    }

    StatusBar {
        height: 1;
        background: $surface;
        color: $text;
    }

    InputBox {
        height: auto;
        max-height: 5;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel_stream", "Cancel", show=True),
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+q", "quit", "Quit", show=False),
        Binding("ctrl+t", "toggle_tree", "Toggle Tree", show=True),
        Binding("ctrl+r", "toggle_requests", "Toggle Requests", show=True),
        Binding("ctrl+o", "open_session", "Sessions", show=True),
        Binding("ctrl+left", "resize_tree(-5)", "Shrink Tree", show=False),
        Binding("ctrl+right", "resize_tree(5)", "Grow Tree", show=False),
    ]

    def __init__(self, session: Session = None, show_picker: bool = False):
        super().__init__()
        self.session = session
        self.runner = ClaudeRunner()
        self.streaming = False
        self._stream_task: asyncio.Task | None = None
        self._current_raw_events: list[dict] = []
        self._tree_width = 50
        self._show_picker = show_picker
        self._shell_process: asyncio.subprocess.Process | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="main-split"):
                yield ContextTree(id="context-tree")
                yield VerticalSplitter(id="splitter")
                with Vertical(id="chat-container"):
                    yield ChatLog(id="chat-log")
                yield RequestPane(id="request-pane")
            yield ToolBar(id="tool-bar")
            yield StatusBar(id="status-bar")
            yield InputBox(id="input-box")

    def on_mount(self) -> None:
        """Initialize the app after mounting."""
        if self._show_picker:
            self.push_screen(SessionPicker(), self._on_session_picked)
        else:
            self._initialize_session()

    def _on_session_picked(self, session: Session | None) -> None:
        """Handle session picker result."""
        if session is None:
            self.exit()
        else:
            self.session = session
            self._initialize_session()

    def _initialize_session(self) -> None:
        """Initialize the UI with the current session."""
        if self.session is None:
            self.session = Session()

        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        status_bar = self.query_one("#status-bar", StatusBar)
        input_box = self.query_one("#input-box", InputBox)

        # Load all sessions into tree (current session's turns auto-selected)
        context_tree.load_all_sessions(self.session)

        # Load current session's messages into chat view
        if self.session.messages:
            chat_log.load_history(self.session.messages)

        # Update status bar with session info
        if self.session.model:
            status_bar.update_stats(
                model=self.session.model,
                input_tokens=self.session.total_input_tokens,
                output_tokens=self.session.total_output_tokens,
                context_window=self.session.context_window,
                cost=self.session.total_cost,
            )

        # Focus the input box
        input_box.focus()

    async def on_input_box_submitted(self, event: InputBox.Submitted) -> None:
        """Handle user input submission."""
        if self.streaming:
            return

        prompt = event.value.strip()

        # Handle commands (: prefix)
        if prompt == ":copy-turns":
            self._handle_copy_turns()
            return
        elif prompt == ":new":
            self._handle_new_session()
            return
        elif prompt.startswith(":query-with "):
            query_prompt = prompt[len(":query-with "):].strip()
            if query_prompt:
                await self._handle_query_with(query_prompt)
            return
        elif prompt.startswith(":suspend "):
            # Suspend and run interactive command
            shell_cmd = prompt[9:].strip()
            if shell_cmd:
                self._handle_suspend(shell_cmd)
            return
        elif prompt.startswith(":!"):
            # Capture output and send to Claude
            shell_cmd = prompt[2:].strip()
            if shell_cmd:
                await self._handle_shell_command(shell_cmd)
            return
        elif prompt.startswith(":"):
            # Unknown command
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.set_error(f"Unknown command: {prompt.split()[0]}")
            return

        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Add user message to display and tree
        chat_log.add_user_message(prompt)
        context_tree.add_turn_to_current("user", prompt, [{"type": "user_input", "content": prompt}])

        # Disable input during streaming
        input_box.set_disabled(True)
        status_bar.set_streaming(True)
        self.streaming = True
        self._current_raw_events = []

        # Start assistant message
        chat_log.add_assistant_message()

        # Start streaming response
        self._stream_task = asyncio.create_task(
            self._handle_stream(prompt)
        )

    async def _handle_stream(self, prompt: str) -> None:
        """Handle the streaming response from Claude."""
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Use only selected messages for context
        selected_messages = context_tree.get_selected_messages()

        # Get enabled tools
        tool_bar = self.query_one("#tool-bar", ToolBar)
        allowed_tools = tool_bar.get_enabled_tools()

        # Log the request
        request_pane = self.query_one("#request-pane", RequestPane)
        request_pane.add_request("claude_request", {
            "prompt": prompt,
            "messages": [{"role": m.role, "content": m.content[:100] + "..." if len(m.content) > 100 else m.content} for m in selected_messages],
            "message_count": len(selected_messages),
            "allowed_tools": allowed_tools,
        })

        try:
            async for event in self.runner.stream_response(
                selected_messages, prompt, allowed_tools
            ):
                if isinstance(event, RawEvent):
                    # Collect raw events for tree inspection
                    self._current_raw_events.append(event.data)

                elif isinstance(event, InitEvent):
                    self.session.model = event.model
                    self.session.context_window = event.context_window
                    status_bar.update_stats(
                        model=event.model,
                        context_window=event.context_window,
                    )

                elif isinstance(event, TextDelta):
                    chat_log.append_to_current(event.text)

                elif isinstance(event, ResultEvent):
                    self.session.update_usage(
                        event.input_tokens,
                        event.output_tokens,
                        event.total_cost_usd,
                        event.context_window,
                    )
                    status_bar.update_stats(
                        input_tokens=event.input_tokens,
                        output_tokens=event.output_tokens,
                        cost=event.total_cost_usd,
                    )

                elif isinstance(event, ToolUseEvent):
                    # Display tool use as separate widget
                    tool_content = self._format_tool_use(event)
                    chat_log.add_tool_use(event.tool_name, tool_content)

                elif isinstance(event, ToolResultEvent):
                    # Display tool result
                    result_content = self._format_tool_result(event)
                    if result_content:
                        chat_log.add_tool_result(result_content)

        except Exception as e:
            chat_log.append_to_current(f"\n\n[Error: {e}]")

        finally:
            # Finish the message and save
            content = chat_log.finish_current_message()

            # Add assistant turn to tree with raw events
            context_tree.add_turn_to_current("assistant", content, self._current_raw_events)

            # Save messages to session
            self.session.add_message("user", prompt)
            self.session.add_message("assistant", content)
            self.session.save()

            # Re-enable input
            self.streaming = False
            status_bar.set_streaming(False)
            input_box.set_disabled(False)
            self._stream_task = None
            self._current_raw_events = []

    def _format_tool_use(self, event: ToolUseEvent) -> str:
        """Format a tool use event for display."""
        tool = event.tool_name
        inp = event.tool_input

        if tool == "Edit":
            file_path = inp.get("file_path", "")
            old = inp.get("old_string", "")
            new = inp.get("new_string", "")
            old_lines = "\n".join(f"- {line}" for line in old.split("\n"))
            new_lines = "\n".join(f"+ {line}" for line in new.split("\n"))
            return f"**Edit** `{file_path}`\n```diff\n{old_lines}\n{new_lines}\n```"

        elif tool == "Write":
            file_path = inp.get("file_path", "")
            content = inp.get("content", "")[:200]
            return f"**Write** `{file_path}`\n```\n{content}...\n```"

        elif tool == "Read":
            file_path = inp.get("file_path", "")
            return f"**Read** `{file_path}`"

        elif tool == "Bash":
            cmd = inp.get("command", "")
            return f"**Bash**\n```bash\n{cmd}\n```"

        elif tool == "Glob":
            pattern = inp.get("pattern", "")
            return f"**Glob** `{pattern}`"

        elif tool == "Grep":
            pattern = inp.get("pattern", "")
            path = inp.get("path", "")
            return f"**Grep** `{pattern}` in `{path}`"

        else:
            import json
            return f"**{tool}**\n```json\n{json.dumps(inp, indent=2)[:300]}\n```"

    def _format_tool_result(self, event: ToolResultEvent) -> str:
        """Format a tool result for display."""
        result = event.result
        if not result:
            return ""
        # Truncate long results
        if len(result) > 500:
            result = result[:500] + "..."
        return f"```\n{result}\n```"

    def _handle_new_session(self) -> None:
        """Create a new empty session."""
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)

        # Create new session
        self.session = Session()
        self.session.save()

        # Clear and reload UI
        chat_log.clear()
        context_tree.load_all_sessions(self.session)

    def _handle_suspend(self, cmd: str) -> None:
        """Suspend TUI and run interactive command."""
        import os
        with self.suspend():
            os.system(cmd)

    def action_cancel_stream(self) -> None:
        """Cancel the current streaming response or shell command."""
        if self._shell_process and self._shell_process.returncode is None:
            self._shell_process.kill()
            self._shell_process = None
            self.query_one("#status-bar", StatusBar).set_status("")
            self.query_one("#input-box", InputBox).set_disabled(False)
        if self.streaming and self.runner.is_running:
            self.runner.terminate()

    def _handle_copy_turns(self) -> None:
        """Copy selected turns to a new session."""
        context_tree = self.query_one("#context-tree", ContextTree)
        chat_log = self.query_one("#chat-log", ChatLog)

        # Get selected messages
        selected_messages = context_tree.get_selected_messages()
        if not selected_messages:
            return

        # Create new session with selected messages
        new_session = Session()
        for msg in selected_messages:
            new_session.add_message(msg.role, msg.content)
        new_session.save()

        # Switch to new session
        chat_log.clear()
        self.session = new_session
        context_tree.load_all_sessions(new_session)
        chat_log.load_history(new_session.messages)

    async def _handle_query_with(self, prompt: str) -> None:
        """Query with selected turns as context, only response goes to new session."""
        context_tree = self.query_one("#context-tree", ContextTree)
        chat_log = self.query_one("#chat-log", ChatLog)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)
        tool_bar = self.query_one("#tool-bar", ToolBar)

        # Get selected messages for context
        selected_messages = context_tree.get_selected_messages()
        allowed_tools = tool_bar.get_enabled_tools()

        # Create new session for the response
        new_session = Session()
        new_session.save()

        # Clear chat log and switch to new session
        chat_log.clear()
        self.session = new_session
        context_tree.load_all_sessions(new_session)

        # Disable input during streaming
        input_box.set_disabled(True)
        status_bar.set_streaming(True)
        self.streaming = True
        self._current_raw_events = []

        # Start assistant message (no user message shown - it's ephemeral)
        chat_log.add_assistant_message()

        # Stream response using selected context
        try:
            async for event in self.runner.stream_response(selected_messages, prompt, allowed_tools):
                if isinstance(event, RawEvent):
                    self._current_raw_events.append(event.data)
                elif isinstance(event, InitEvent):
                    self.session.model = event.model
                    self.session.context_window = event.context_window
                    status_bar.update_stats(model=event.model, context_window=event.context_window)
                elif isinstance(event, TextDelta):
                    chat_log.append_to_current(event.text)
                elif isinstance(event, ResultEvent):
                    self.session.update_usage(
                        event.input_tokens, event.output_tokens,
                        event.total_cost_usd, event.context_window
                    )
                    status_bar.update_stats(
                        input_tokens=event.input_tokens,
                        output_tokens=event.output_tokens,
                        cost=event.total_cost_usd
                    )
        except Exception as e:
            chat_log.append_to_current(f"\n\n[Error: {e}]")
        finally:
            content = chat_log.finish_current_message()
            context_tree.add_turn_to_current("assistant", content, self._current_raw_events)

            # Only save assistant response to new session
            self.session.add_message("assistant", content)
            self.session.save()

            self.streaming = False
            status_bar.set_streaming(False)
            input_box.set_disabled(False)
            self._current_raw_events = []

    async def _handle_shell_command(self, cmd: str) -> None:
        """Run a shell command and submit output to Claude."""
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Show processing state
        input_box.set_disabled(True)
        status_bar.set_status(f"Running: {cmd[:30]}...")

        # Run command and capture output
        import os
        env = os.environ.copy()
        env.update({
            "FORCE_COLOR": "1",
            "CLICOLOR_FORCE": "1",
            "TERM": "xterm-256color",
        })
        try:
            self._shell_process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            stdout, _ = await self._shell_process.communicate()
            output = stdout.decode("utf-8", errors="replace").rstrip()
            self._shell_process = None
        except asyncio.CancelledError:
            if self._shell_process:
                self._shell_process.kill()
                self._shell_process = None
            input_box.set_disabled(False)
            status_bar.set_status("")
            return
        except Exception as e:
            self._shell_process = None
            output = f"Error: {e}"

        status_bar.set_status("")

        # Format with explanatory header
        prompt = f"# User executed shell command:\n```bash\n$ {cmd}\n```\n# Output:\n```\n{output}\n```"

        # Now submit through normal flow (add user msg, stream Claude response)
        chat_log.add_user_message(prompt)
        context_tree.add_turn_to_current("user", prompt, [{"type": "shell_command", "cmd": cmd}])

        # Stream Claude's response
        status_bar.set_streaming(True)
        self.streaming = True
        self._current_raw_events = []
        chat_log.add_assistant_message()

        self._stream_task = asyncio.create_task(
            self._handle_stream(prompt)
        )

    def on_context_tree_selection_changed(self, event: ContextTree.SelectionChanged) -> None:
        """Handle tree selection changes - filter chat view."""
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.filter_by_turns(event.selected_turn_ids, event.show_all)

    def on_context_tree_session_activated(self, event: ContextTree.SessionActivated) -> None:
        """Handle clicking on a session to view it."""
        if self.streaming:
            return

        chat_log = self.query_one("#chat-log", ChatLog)

        # Load the activated session's messages
        chat_log.clear()
        chat_log.load_history(event.session.messages)

    def on_context_tree_turn_inspected(self, event: ContextTree.TurnInspected) -> None:
        """Handle turn inspection - show in request pane."""
        request_pane = self.query_one("#request-pane", RequestPane)
        request_pane.show_json(event.turn_data)

    def action_toggle_tree(self) -> None:
        """Toggle the context tree visibility."""
        tree = self.query_one("#context-tree", ContextTree)
        splitter = self.query_one("#splitter", VerticalSplitter)
        tree.display = not tree.display
        splitter.display = tree.display

    def action_toggle_requests(self) -> None:
        """Toggle the request pane visibility."""
        pane = self.query_one("#request-pane", RequestPane)
        pane.display = not pane.display

    def action_open_session(self) -> None:
        """Open the session picker."""
        if not self.streaming:
            self.push_screen(SessionPicker(), self._on_session_switched)

    def _on_session_switched(self, session: Session | None) -> None:
        """Handle session switch from picker."""
        if session is None:
            return  # User cancelled

        # Clear current display
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)

        # Clear displays
        chat_log.clear()
        context_tree.clear()

        # Set new session and initialize
        self.session = session
        self._initialize_session()

    def action_resize_tree(self, delta: int) -> None:
        """Resize the context tree by delta columns."""
        self._tree_width = max(20, min(100, self._tree_width + delta))
        tree = self.query_one("#context-tree", ContextTree)
        tree.styles.width = self._tree_width

    def on_vertical_splitter_resized(self, event: VerticalSplitter.Resized) -> None:
        """Handle splitter drag."""
        self.action_resize_tree(event.delta_x)

    def action_quit(self) -> None:
        """Quit the application."""
        if self.streaming:
            self.runner.terminate()
        self.exit()
