import asyncio
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical

# Debug logging for event ordering
DEBUG_EVENTS = os.environ.get("BALLOONS_DEBUG_EVENTS", "").lower() in ("1", "true", "yes")
if DEBUG_EVENTS:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        filename="/tmp/balloons_events.log",
        filemode="w",
    )
    _log = logging.getLogger("balloons.events")
else:
    _log = None


def debug_event(msg: str) -> None:
    """Log a debug event if DEBUG_EVENTS is enabled."""
    if _log:
        _log.debug(msg)

from rich.console import RenderableType
from widgets import ChatLog, InputBox, StatusBar, ContextTree, VerticalSplitter, SessionPicker, RequestPane, ToolBar, WithWidget, WithResultWidget, DebugPane
from claude_runner import ClaudeRunner
from session import Session
from models import (
    TextDelta, ToolUseEvent, ToolResultEvent,
    TextBlock, ToolUseBlock, Message, ContextMode,
)
from core import (
    CommandParser,
    Formatter,
    ContextBuilder,
    SessionRunner,
    SessionManager,
    StreamEvent,
    NewSessionCommand,
    CopyTurnsCommand,
    QueryWithCommand,
    SuspendCommand,
    ShellCommand,
    WithCommand,
    WithCopyCommand,
    ReturnCommand,
    PwdCommand,
    CdCommand,
    ReloadCommand,
    SummarizeCommand,
    debug_log,
)


@dataclass
class StreamingContext:
    """Tracks streaming state for a session.

    Each streaming session needs to track its own state for proper
    event handling and UI updates.
    """
    session_id: str
    user_turn_idx: int  # Index of user turn in session.messages (-1 for query_with)
    assistant_turn_idx: int  # Index of assistant turn
    prompt: str  # Original prompt for saving
    content: str = ""  # Accumulated text content
    is_active: bool = True  # Is this the active/foreground session?
    query_with: bool = False  # Special case: no user message saved


class BalloonsApp(App):
    """A TUI chat interface for Claude."""

    TITLE = "Balloons"
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
        Binding("ctrl+g", "toggle_debug", "Debug", show=True),
        Binding("ctrl+o", "open_session", "Sessions", show=True),
        Binding("ctrl+left", "resize_tree(-5)", "Shrink Tree", show=False),
        Binding("ctrl+right", "resize_tree(5)", "Grow Tree", show=False),
    ]

    def __init__(self, session: Session = None, show_picker: bool = False):
        super().__init__()
        self._initial_session = session  # Will be loaded into manager
        self.streaming = False  # True if active session is streaming
        self._tree_width = 50
        self._show_picker = show_picker
        self._shell_process: asyncio.subprocess.Process | None = None
        # Core components
        self._command_parser = CommandParser()
        self._formatter = Formatter()
        self._context_builder = ContextBuilder()
        # Session manager handles all sessions and runners
        self._manager = SessionManager()
        # Simple runner for helper streaming (summaries, etc.)
        self._helper_runner = ClaudeRunner()
        # Timer for polling background sessions
        self._poll_timer = None
        # Per-session streaming contexts (session_id -> StreamingContext)
        self._streaming_contexts: dict[str, StreamingContext] = {}

    @property
    def session(self) -> Session | None:
        """Get the active session from the manager."""
        return self._manager.active_session

    @property
    def _session_runner(self) -> SessionRunner | None:
        """Get the active session's runner from the manager."""
        return self._manager.active_runner

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="main-split"):
                yield ContextTree(id="context-tree")
                yield VerticalSplitter(id="splitter")
                with Vertical(id="chat-container"):
                    yield ChatLog(id="chat-log")
                yield RequestPane(id="request-pane")
            yield ToolBar(id="tool-bar")
            yield DebugPane(id="debug-pane")
            yield StatusBar(id="status-bar")
            yield InputBox(id="input-box")

    def on_mount(self) -> None:
        """Initialize the app after mounting."""
        # Start the background session polling timer
        self._poll_timer = self.set_interval(0.1, self._poll_background_sessions)

        if self._show_picker:
            self.push_screen(SessionPicker(), self._on_session_picked)
        else:
            self._initialize_session()

    def _poll_background_sessions(self) -> None:
        """Poll ALL streaming sessions for events and update UI.

        This is the core of the event-driven architecture:
        - All sessions stream in background mode
        - This timer polls for events from all sessions
        - Events are dispatched to appropriate UI components
        """
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Get events from all streaming sessions
        for session_id, events in self._manager.poll_all():
            ctx = self._streaming_contexts.get(session_id)
            if not ctx:
                if events:
                    debug_log.warning(
                        f"Got {len(events)} events but no streaming context",
                        category="stream",
                        session_id=session_id,
                        details={"event_types": [e.event_type for e in events[:5]]},
                    )
                continue  # No context, skip

            for event in events:
                try:
                    self._dispatch_polled_event(session_id, event, ctx, chat_log, context_tree, status_bar)
                except Exception as e:
                    debug_log.error(
                        f"Event dispatch failed: {e}",
                        session_id=session_id,
                        category="event",
                        details={"event_type": event.event_type},
                    )
                    # Continue processing other events

    def _dispatch_polled_event(
        self,
        session_id: str,
        event: StreamEvent,
        ctx: StreamingContext,
        chat_log: ChatLog,
        context_tree: ContextTree,
        status_bar: StatusBar,
    ) -> None:
        """Dispatch a polled event to appropriate UI components.

        Handles events for both active (foreground) and background sessions.
        """
        is_active = ctx.is_active

        if event.event_type == "turn_started":
            debug_event(f"turn_started: session={session_id[:8]} turn={event.data.get('turn_index')}")

        elif event.event_type == "text":
            text = event.data
            debug_event(f"text: session={session_id[:8]} len={len(text)}")
            ctx.content += text
            if is_active:
                chat_log.append_to_current(text)
            else:
                # Update WithWidget for background session
                with_widget = chat_log.find_with_widget(session_id)
                if with_widget:
                    with_widget.update_streaming(text)

        elif event.event_type == "init":
            debug_event(f"init: session={session_id[:8]} model={event.data.get('model')}")
            if is_active:
                status_bar.update_stats(
                    model=event.data.get("model"),
                    context_window=event.data.get("context_window"),
                )

        elif event.event_type == "result":
            debug_event(f"result: session={session_id[:8]} in={event.data.get('input_tokens')} out={event.data.get('output_tokens')}")
            if is_active:
                # Get session from manager for token totals
                session = self._manager._sessions.get(session_id)
                if session:
                    status_bar.update_stats(
                        input_tokens=session.total_input_tokens,
                        output_tokens=session.total_output_tokens,
                        cost=session.total_cost,
                    )

        elif event.event_type == "tool_use":
            data = event.data
            debug_event(f"tool_use: session={session_id[:8]} {data.get('tool_name')}")

            # Add to tree
            context_tree.add_tool_use_to_turn(
                session_id,
                ctx.assistant_turn_idx,
                data.get("tool_use_id"),
                data.get("tool_name"),
                data.get("tool_input"),
                data.get("tool_index"),
            )

            if is_active:
                # Display tool use widget
                tool_event = ToolUseEvent(
                    tool_use_id=data.get("tool_use_id"),
                    tool_name=data.get("tool_name"),
                    tool_input=data.get("tool_input"),
                )
                formatted = self._format_tool_use(tool_event)
                if isinstance(formatted, tuple):
                    tool_content, full_content = formatted
                else:
                    tool_content, full_content = formatted, None
                chat_log.add_tool_use(
                    data.get("tool_name"), tool_content,
                    tool_use_id=data.get("tool_use_id"), full_content=full_content
                )

        elif event.event_type == "tool_result":
            data = event.data
            debug_event(f"tool_result: session={session_id[:8]} len={len(data.get('result', ''))}")

            # Add to tree
            context_tree.add_tool_result_to_turn(
                session_id,
                ctx.assistant_turn_idx,
                data.get("tool_use_id"),
                data.get("result"),
                data.get("tool_index"),
            )

            if is_active:
                # Display tool result widget
                tool_result_event = ToolResultEvent(
                    tool_use_id=data.get("tool_use_id"),
                    result=data.get("result"),
                )
                formatted = self._format_tool_result(tool_result_event, session_id)
                if isinstance(formatted, tuple):
                    result_content, full_content = formatted
                else:
                    result_content, full_content = formatted, None
                chat_log.add_tool_result(
                    result_content,
                    tool_use_id=data.get("tool_use_id"), full_content=full_content
                )

        elif event.event_type == "done":
            debug_event(f"done: session={session_id[:8]}")
            debug_log.info("Received done event, calling finalize", category="stream", session_id=session_id)
            self._finalize_streaming(session_id, ctx, chat_log, context_tree, status_bar)

        elif event.event_type == "error":
            debug_event(f"error: session={session_id[:8]} {event.data}")
            debug_log.error(event.data, session_id=session_id, category="stream")
            if is_active:
                chat_log.append_to_current(f"\n\n[Error: {event.data}]")
            self._finalize_streaming(session_id, ctx, chat_log, context_tree, status_bar, error=event.data)

        elif event.event_type == "rate_limit":
            debug_event(f"rate_limit: session={session_id[:8]} {event.data}")
            if is_active:
                chat_log.append_to_current(f"\n\n[Rate Limit] {event.data}")
            self._finalize_streaming(session_id, ctx, chat_log, context_tree, status_bar, error=event.data)

        elif event.event_type == "cancelled":
            debug_event(f"cancelled: session={session_id[:8]}")
            self._finalize_streaming(session_id, ctx, chat_log, context_tree, status_bar, cancelled=True)

        elif event.event_type == "input_required":
            debug_event(f"input_required: session={session_id[:8]} {event.data}")
            if is_active:
                chat_log.append_to_current("\n\n[Claude is asking a question - session ended]")
                status_bar.set_status("Claude asked a question (not supported in non-interactive mode)")
            self._finalize_streaming(session_id, ctx, chat_log, context_tree, status_bar)

    def _finalize_streaming(
        self,
        session_id: str,
        ctx: StreamingContext,
        chat_log: ChatLog,
        context_tree: ContextTree,
        status_bar: StatusBar,
        error: str = None,
        cancelled: bool = False,
    ) -> None:
        """Finalize a streaming session - save messages, update UI."""
        debug_log.info(
            f"Finalizing stream (is_active={ctx.is_active})",
            category="stream",
            session_id=session_id,
        )
        try:
            session = self._manager._sessions.get(session_id)
            runner = self._manager._runners.get(session_id)

            if ctx.is_active:
                # Finish the message display
                final_content = chat_log.finish_current_message()
                if not ctx.content:
                    ctx.content = final_content

            # Get result from runner for content blocks
            content = ctx.content
            if runner:
                result = runner.get_result()
                if result:
                    assistant_blocks = result.content_blocks if result.content_blocks else [TextBlock(text=content)]
                    raw_events = result.raw_events
                else:
                    assistant_blocks = [TextBlock(text=content)]
                    raw_events = []
            else:
                assistant_blocks = [TextBlock(text=content)]
                raw_events = []

            # Finish the assistant turn in tree
            context_tree.finish_turn(
                session_id,
                ctx.assistant_turn_idx,
                content,
                assistant_blocks,
                raw_events,
            )

            # Save messages to session
            if session:
                if ctx.query_with:
                    # query_with: only save assistant response, no user message
                    session.add_message("assistant", content, content_blocks=assistant_blocks)
                else:
                    # Normal case: save both user and assistant messages
                    user_blocks = [TextBlock(text=ctx.prompt)]
                    session.add_message("user", ctx.prompt, content_blocks=user_blocks)
                    session.add_message("assistant", content, content_blocks=assistant_blocks)
                session.save()

            if ctx.is_active:
                # Re-enable input
                debug_log.info("Re-enabling input (active session)", category="stream", session_id=session_id)
                self.streaming = False
                status_bar.set_streaming(False)
                input_box = self.query_one("#input-box", InputBox)
                input_box.set_disabled(False)

                # Check for auto-return conditions
                if session and self._check_auto_return(content):
                    asyncio.create_task(self._handle_return_command("Auto-return: condition met"))
            else:
                # Background session finished - update WithWidget
                with_widget = chat_log.find_with_widget(session_id)
                if with_widget:
                    with_widget.mark_done()
                if error:
                    status_bar.set_error(f"Background error: {error}")
                elif not cancelled:
                    status_bar.set_status(f"Background session done: {session_id[:8]}")

        except Exception as e:
            debug_log.error(
                f"Finalize failed: {e}",
                session_id=session_id,
                category="stream",
            )
            # Try to re-enable input on failure
            if ctx.is_active:
                try:
                    self.streaming = False
                    status_bar.set_streaming(False)
                    input_box = self.query_one("#input-box", InputBox)
                    input_box.set_disabled(False)
                except Exception:
                    pass

        finally:
            # Always clean up streaming context
            if session_id in self._streaming_contexts:
                del self._streaming_contexts[session_id]
                debug_log.info("Finalization complete, context cleaned up", category="stream", session_id=session_id)

    def _on_session_picked(self, session: Session | None) -> None:
        """Handle session picker result."""
        if session is None:
            self.exit()
        else:
            # Register picked session with manager and set active
            self._manager._sessions[session.id] = session
            self._manager._runners[session.id] = SessionRunner(session)
            self._manager.set_active(session.id)
            self._initialize_session()

    def _initialize_session(self) -> None:
        """Initialize the UI with the current session."""
        if self.session is None:
            # Create new session through manager
            session = self._manager.create_session()
            self._manager.set_active(session.id)
        elif self._initial_session is not None:
            # Load initial session into manager
            self._manager._sessions[self._initial_session.id] = self._initial_session
            self._manager._runners[self._initial_session.id] = SessionRunner(self._initial_session)
            self._manager.set_active(self._initial_session.id)
            self._initial_session = None  # Clear so we don't reload on subsequent calls

        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        status_bar = self.query_one("#status-bar", StatusBar)
        input_box = self.query_one("#input-box", InputBox)

        # Load all sessions into tree (current session's turns auto-selected)
        context_tree.load_all_sessions(self.session)

        # Load current session's messages into chat view
        if self.session.messages:
            chat_log.load_history(self.session.messages)

        # Set session title in chat header
        if self.session.title:
            chat_log.set_session_title(self.session.title)

        # Show session info in request pane
        request_pane = self.query_one("#request-pane", RequestPane)
        request_pane.show_session_info(
            self.session.title,
            self.session.summary,
            self.session.created,
            self.session.model,
        )

        # Update status bar with session info
        if self.session.model:
            status_bar.update_stats(
                model=self.session.model,
                input_tokens=self.session.total_input_tokens,
                output_tokens=self.session.total_output_tokens,
                context_window=self.session.context_window,
                cost=self.session.total_cost,
            )

        # Update working directory in status bar
        status_bar.update_working_directory(self.session.working_directory or "")

        # Focus the input box
        input_box.focus()

    async def on_input_box_submitted(self, event: InputBox.Submitted) -> None:
        """Handle user input submission."""
        if self.streaming:
            return

        prompt = event.value.strip()

        # Try to parse as a command
        try:
            cmd = self._command_parser.parse(prompt)
        except ValueError as e:
            # Invalid command
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.set_error(str(e))
            return

        # Dispatch to command handlers
        if cmd is not None:
            await self._execute_command(cmd)
            return

        # Log and start streaming in background (event-driven)
        debug_log.info(
            f"Prompt submitted ({len(prompt)} chars)",
            category="command",
            session_id=self.session.id if self.session else "",
        )
        self._start_streaming(prompt)

    def _start_streaming(self, prompt: str, is_active: bool = True) -> None:
        """Start a streaming response in background mode.

        This is the event-driven approach: start the background stream,
        then the poll timer picks up events and updates the UI.

        Args:
            prompt: User prompt to send
            is_active: True if this is the active/foreground session
        """
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

        # Track the turn index for tree updates
        turn_idx = len(self.session.messages)  # Next turn will be at this index

        # Start the user turn in tree immediately
        context_tree.start_turn(self.session.id, turn_idx, "user")
        context_tree.finish_turn(
            self.session.id, turn_idx, prompt, [TextBlock(text=prompt)], []
        )

        # Start the assistant turn in tree
        assistant_turn_idx = turn_idx + 1
        context_tree.start_turn(self.session.id, assistant_turn_idx, "assistant")

        # Create streaming context for this session
        ctx = StreamingContext(
            session_id=self.session.id,
            user_turn_idx=turn_idx,
            assistant_turn_idx=assistant_turn_idx,
            prompt=prompt,
            is_active=is_active,
        )
        self._streaming_contexts[self.session.id] = ctx

        if is_active:
            # Add user message to display
            chat_log.add_user_message(prompt)

            # Disable input during streaming
            input_box.set_disabled(True)
            status_bar.set_streaming(True)
            self.streaming = True

            # Start assistant message
            debug_event("add_assistant_message (streaming starts)")
            chat_log.add_assistant_message()

        # Start background streaming - poll timer will pick up events
        self._session_runner.start_background(prompt, selected_messages, allowed_tools)

    async def _execute_command(self, cmd) -> None:
        """Execute a parsed command."""
        # Log command execution
        cmd_name = type(cmd).__name__.replace("Command", "").lower()
        debug_log.info(f"Command: {cmd_name}", category="command")

        if isinstance(cmd, NewSessionCommand):
            await self._handle_new_session(cmd.initial_prompt)
        elif isinstance(cmd, CopyTurnsCommand):
            self._handle_copy_turns()
        elif isinstance(cmd, QueryWithCommand):
            await self._handle_query_with(cmd.prompt)
        elif isinstance(cmd, SuspendCommand):
            self._handle_suspend(cmd.shell_cmd)
        elif isinstance(cmd, ShellCommand):
            await self._handle_shell_command(cmd.shell_cmd)
        elif isinstance(cmd, WithCommand):
            await self._handle_with_command(cmd.prompt, cmd.return_condition, cmd.background)
        elif isinstance(cmd, WithCopyCommand):
            await self._handle_with_copy_command(cmd.prompt, cmd.return_condition, cmd.background)
        elif isinstance(cmd, ReturnCommand):
            await self._handle_return_command(cmd.return_prompt)
        elif isinstance(cmd, PwdCommand):
            self._handle_pwd_command()
        elif isinstance(cmd, CdCommand):
            self._handle_cd_command(cmd.path)
        elif isinstance(cmd, ReloadCommand):
            self._handle_reload()
        elif isinstance(cmd, SummarizeCommand):
            await self._handle_summarize_command(cmd.mode)

    def _format_tool_use(
        self, event: ToolUseEvent
    ) -> RenderableType | tuple[RenderableType, RenderableType]:
        """Format a tool use event for display.

        Returns single renderable, or tuple of (truncated, full) if content was truncated.
        """
        return self._formatter.format_tool_use(event)

    def _format_tool_result(
        self, event: ToolResultEvent, session_id: str = None
    ) -> RenderableType | tuple[RenderableType, RenderableType]:
        """Format a tool result for display.

        Returns single renderable, or tuple of (truncated, full) if content was truncated.
        """
        # Find the last tool use for context from SessionRunner's content blocks
        last_tool_use = None
        runner = self._manager._runners.get(session_id) if session_id else self._session_runner
        if runner:
            for block in reversed(runner._content_blocks):
                if isinstance(block, ToolUseBlock):
                    last_tool_use = block
                    break
        return self._formatter.format_tool_result(event, last_tool_use)

    async def _handle_new_session(self, initial_prompt: str = "") -> None:
        """Create a new session, optionally with an initial prompt."""
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)

        # Create new session through manager
        new_session = self._manager.create_session()
        self._manager.set_active(new_session.id)

        # Clear and reload UI
        chat_log.clear()
        context_tree.load_all_sessions(self.session)

        # If an initial prompt was provided, send it
        if initial_prompt:
            # Reuse the normal message flow
            event = InputBox.Submitted(initial_prompt)
            await self.on_input_box_submitted(event)

    def _handle_pwd_command(self) -> None:
        """Show the current working directory for the session."""
        status_bar = self.query_one("#status-bar", StatusBar)
        if self.session.working_directory:
            status_bar.set_status(f"Working directory: {self.session.working_directory}")
        else:
            status_bar.set_status(f"No working directory set (process cwd: {os.getcwd()})")

    def _handle_cd_command(self, path_arg: str) -> None:
        """Change the working directory for the session."""
        status_bar = self.query_one("#status-bar", StatusBar)

        if not path_arg:
            # No argument - clear working directory or show current
            if self.session.working_directory:
                status_bar.set_status(f"Working directory: {self.session.working_directory}")
            else:
                status_bar.set_status("No working directory set. Use :cd <path> to set one.")
            return

        # Expand ~ and resolve relative paths
        try:
            target_path = Path(path_arg).expanduser()
            if not target_path.is_absolute():
                # Resolve relative to current working directory or session's working directory
                base = Path(self.session.working_directory) if self.session.working_directory else Path.cwd()
                target_path = (base / target_path).resolve()
            else:
                target_path = target_path.resolve()

            if not target_path.exists():
                status_bar.set_error(f"Path does not exist: {target_path}")
                return

            if not target_path.is_dir():
                status_bar.set_error(f"Not a directory: {target_path}")
                return

            # Set the working directory
            self.session.working_directory = str(target_path)
            self.session.save()
            status_bar.update_working_directory(str(target_path))
            status_bar.set_status(f"Changed to: {target_path}")

        except Exception as e:
            status_bar.set_error(f"Invalid path: {e}")

    def _handle_reload(self) -> None:
        """Reload the app by re-executing the process."""
        self.session.save()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    async def _handle_summarize_command(self, mode: str) -> None:
        """Generate a title and summary for the current session.

        mode: 'quick' - summarize only user messages
              'detailed' - summarize all messages including assistant responses
        """
        status_bar = self.query_one("#status-bar", StatusBar)
        input_box = self.query_one("#input-box", InputBox)

        if not self.session.messages:
            status_bar.set_error("No messages to summarize")
            return

        status_bar.set_status(f"Generating {mode} summary...")
        input_box.set_disabled(True)
        debug_log.info(f"Starting {mode} summary generation", category="command")

        try:
            # Build prompt using context builder
            prompt = self._context_builder.build_summary_prompt(self.session.messages, mode)

            result_parts = []
            async for event in self._helper_runner.stream_response([], prompt):
                if isinstance(event, TextDelta):
                    result_parts.append(event.text)

            result = "".join(result_parts)
            debug_log.debug(
                f"Summary response: {result[:200]}..." if len(result) > 200 else f"Summary response: {result}",
                category="command",
            )

            # Parse the result
            title, summary = self._context_builder.parse_summary_response(result)
            debug_log.info(f"Parsed title='{title}', summary='{summary[:50]}...'" if summary else f"Parsed title='{title}', summary=''", category="command")

            self.session.title = title
            self.session.summary = summary
            self.session.save()

            # Update UI with new title/summary
            chat_log = self.query_one("#chat-log", ChatLog)
            chat_log.set_session_title(title)

            request_pane = self.query_one("#request-pane", RequestPane)
            request_pane.show_session_info(
                title,
                summary,
                self.session.created,
                self.session.model,
            )

            # Reload context tree to show summary
            context_tree = self.query_one("#context-tree", ContextTree)
            context_tree.load_all_sessions(self.session)

            status_bar.set_status(f"Session titled: {title}")

        except Exception as e:
            debug_log.error(f"Summary failed: {e}", category="command")
            status_bar.set_error(f"Summary failed: {e}")
        finally:
            debug_log.info("Summary generation finished", category="command")
            input_box.set_disabled(False)

    def _handle_suspend(self, cmd: str) -> None:
        """Suspend TUI and run interactive command in session's working directory."""
        cwd = self.session.working_directory
        with self.suspend():
            if cwd:
                os.system(f"cd {cwd!r} && {cmd}")
            else:
                os.system(cmd)

    def action_cancel_stream(self) -> None:
        """Cancel streaming/shell and focus input box. Double-tap clears input."""
        # Cancel any running shell process
        if self._shell_process and self._shell_process.returncode is None:
            self._shell_process.kill()
            self._shell_process = None
            self.query_one("#status-bar", StatusBar).set_status("")
            self.query_one("#input-box", InputBox).set_disabled(False)

        # Cancel any streaming (main runner)
        if self.streaming and self._session_runner and self._session_runner.is_streaming:
            self._session_runner.cancel()

        # Cancel helper runner (used for summaries, etc.)
        if self._helper_runner.is_running:
            debug_log.info("Cancelling helper runner", category="command")
            self._helper_runner.terminate()

        # Always focus the input box
        input_box = self.query_one("#input-box", InputBox)
        input_box.focus()

    def _handle_copy_turns(self) -> None:
        """Copy selected turns to a new session."""
        context_tree = self.query_one("#context-tree", ContextTree)
        chat_log = self.query_one("#chat-log", ChatLog)

        # Get selected messages
        selected_messages = context_tree.get_selected_messages()
        if not selected_messages:
            return

        # Create new session with selected messages (preserve content_blocks)
        new_session = Session()
        for msg in selected_messages:
            new_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)
        new_session.save()

        # Switch to new session through manager
        chat_log.clear()
        self._manager._sessions[new_session.id] = new_session
        self._manager._runners[new_session.id] = SessionRunner(new_session)
        self._manager.set_active(new_session.id)
        context_tree.load_all_sessions(new_session)
        chat_log.load_history(new_session.messages)

    async def _handle_query_with(self, prompt: str) -> None:
        """Query with selected turns as context, only response goes to new session.

        This is a special case: no user message is saved, only the assistant response.
        Uses the event-driven background streaming approach.
        """
        context_tree = self.query_one("#context-tree", ContextTree)
        chat_log = self.query_one("#chat-log", ChatLog)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)
        tool_bar = self.query_one("#tool-bar", ToolBar)

        # Get selected messages for context (before creating new session)
        selected_messages = context_tree.get_selected_messages()
        allowed_tools = tool_bar.get_enabled_tools()

        # Create new session for the response through manager
        new_session = self._manager.create_session()
        self._manager.set_active(new_session.id)

        # Clear chat log and switch to new session
        chat_log.clear()
        context_tree.load_all_sessions(new_session)

        # Create streaming context for query_with (special: no user turn saved)
        # assistant_turn_idx is 0 since we don't save the user message
        ctx = StreamingContext(
            session_id=new_session.id,
            user_turn_idx=-1,  # No user turn
            assistant_turn_idx=0,  # First turn is assistant
            prompt=prompt,
            is_active=True,
        )
        # Mark this as a query_with special case
        ctx.query_with = True
        self._streaming_contexts[new_session.id] = ctx

        # Disable input during streaming
        input_box.set_disabled(True)
        status_bar.set_streaming(True)
        self.streaming = True

        # Start assistant message (no user message shown - it's ephemeral)
        chat_log.add_assistant_message()

        # Start assistant turn in tree (no user turn for query_with)
        context_tree.start_turn(new_session.id, 0, "assistant")

        # Start background streaming - poll timer will handle events
        self._session_runner.start_background(prompt, selected_messages, allowed_tools)

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
        # Use session's working directory if set
        cwd = self.session.working_directory if self.session.working_directory else None
        try:
            self._shell_process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=cwd,
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

        # Use event-driven streaming (same as normal input)
        self._start_streaming(prompt)

    async def _handle_with_command(self, prompt: str, return_condition: str = "manual", background: bool = False) -> None:
        """Fork a child session, respecting context modes (COPY verbatim, SUMMARIZE via Claude)."""
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)
        tool_bar = self.query_one("#tool-bar", ToolBar)

        # Get selected messages from context tree (includes context_mode)
        selected_messages = context_tree.get_selected_messages()
        allowed_tools = tool_bar.get_enabled_tools()

        # Separate messages by context mode
        copy_messages = [m for m in selected_messages if m.context_mode == ContextMode.COPY]
        summarize_messages = [m for m in selected_messages if m.context_mode == ContextMode.SUMMARIZE]

        # Create child session with parent reference
        child_session = Session()
        child_session.parent_id = self.session.id
        child_session.return_condition = return_condition

        # Copy COPY-marked messages verbatim to child
        for msg in copy_messages:
            child_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

        # Generate summaries for SUMMARIZE-marked messages
        if summarize_messages:
            status_bar.set_status("Summarizing context...")
            input_box.set_disabled(True)

            summary = await self._generate_context_summary(summarize_messages)

            if summary:
                # Add summary as a system-like user message at the start
                child_session.messages.insert(0, Message(
                    role="user",
                    content=f"[Context Summary]\n{summary}",
                    content_blocks=[TextBlock(text=f"[Context Summary]\n{summary}")],
                ))

            status_bar.set_status("")
            input_box.set_disabled(False)

        child_session.save()

        # Register child in parent
        self.session.add_child(child_session.id, prompt, return_condition)
        self.session.save()

        # Add WithWidget to parent's chat log
        chat_log.add_with_widget(
            prompt=prompt,
            child_session_id=child_session.id,
            status="active" if not background else "background",
            return_condition=return_condition,
        )

        # Register child session with manager
        self._manager._sessions[child_session.id] = child_session
        self._manager._runners[child_session.id] = SessionRunner(child_session)

        if background:
            # Background mode - stay in parent, create streaming context for child
            turn_idx = len(child_session.messages)
            ctx = StreamingContext(
                session_id=child_session.id,
                user_turn_idx=turn_idx,
                assistant_turn_idx=turn_idx + 1,
                prompt=prompt,
                is_active=False,  # Background session
            )
            self._streaming_contexts[child_session.id] = ctx

            # Start the child's tree turns
            context_tree.start_turn(child_session.id, turn_idx, "user")
            context_tree.finish_turn(
                child_session.id, turn_idx, prompt, [TextBlock(text=prompt)], []
            )
            context_tree.start_turn(child_session.id, turn_idx + 1, "assistant")

            # Start background streaming
            child_runner = self._manager._runners[child_session.id]
            child_runner.start_background(
                prompt=prompt,
                messages=child_session.messages,
                allowed_tools=allowed_tools,
            )
            status_bar.set_status(f"Background: {prompt[:30]}...")
        else:
            # Foreground mode - switch to child session and stream
            self._manager.set_active(child_session.id)
            chat_log.clear()
            chat_log.load_history(child_session.messages)
            context_tree.load_all_sessions(child_session)

            # Use _start_streaming which handles all the setup
            self._start_streaming(prompt)

    async def _generate_context_summary(self, messages: list) -> str:
        """Generate a summary of messages marked for summarization."""
        if not messages:
            return ""

        summary_prompt = self._context_builder.build_context_summary_prompt(messages)

        # Stream response from Claude
        summary_parts = []
        try:
            async for event in self._helper_runner.stream_response([], summary_prompt):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
        except Exception as e:
            # Fall back to raw content
            context_parts = [f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}" for m in messages]
            return f"Error generating summary: {e}\n\nRaw context:\n" + "\n\n".join(context_parts)

        return "".join(summary_parts) if summary_parts else ""

    async def _handle_with_copy_command(self, prompt: str, return_condition: str = "manual", background: bool = False) -> None:
        """Fork a child session, copying selected nodes directly."""
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)
        tool_bar = self.query_one("#tool-bar", ToolBar)

        # Get selected messages from context tree
        selected_messages = context_tree.get_selected_messages()
        allowed_tools = tool_bar.get_enabled_tools()

        # Create child session with parent reference
        child_session = Session()
        child_session.parent_id = self.session.id
        child_session.return_condition = return_condition

        # Copy selected messages to child (preserve content_blocks)
        for msg in selected_messages:
            child_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)
        child_session.save()

        # Register child in parent
        self.session.add_child(child_session.id, prompt, return_condition)
        self.session.save()

        # Add WithWidget to parent's chat log
        chat_log.add_with_widget(
            prompt=prompt,
            child_session_id=child_session.id,
            status="active" if not background else "background",
            return_condition=return_condition,
        )

        # Register child session with manager
        self._manager._sessions[child_session.id] = child_session
        self._manager._runners[child_session.id] = SessionRunner(child_session)

        if background:
            # Background mode - stay in parent, create streaming context for child
            turn_idx = len(child_session.messages)
            ctx = StreamingContext(
                session_id=child_session.id,
                user_turn_idx=turn_idx,
                assistant_turn_idx=turn_idx + 1,
                prompt=prompt,
                is_active=False,  # Background session
            )
            self._streaming_contexts[child_session.id] = ctx

            # Start the child's tree turns
            context_tree.start_turn(child_session.id, turn_idx, "user")
            context_tree.finish_turn(
                child_session.id, turn_idx, prompt, [TextBlock(text=prompt)], []
            )
            context_tree.start_turn(child_session.id, turn_idx + 1, "assistant")

            # Start background streaming
            child_runner = self._manager._runners[child_session.id]
            child_runner.start_background(
                prompt=prompt,
                messages=child_session.messages,
                allowed_tools=allowed_tools,
            )
            status_bar.set_status(f"Background: {prompt[:30]}...")
        else:
            # Foreground mode - switch to child session and stream
            self._manager.set_active(child_session.id)
            chat_log.clear()
            chat_log.load_history(child_session.messages)
            context_tree.load_all_sessions(child_session)

            # Use _start_streaming which handles all the setup
            self._start_streaming(prompt)

    async def _handle_return_command(self, return_prompt: str = "") -> None:
        """Return from child session to parent."""
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        status_bar = self.query_one("#status-bar", StatusBar)
        input_box = self.query_one("#input-box", InputBox)

        # Check we're in a child session
        if not self.session.is_child_session():
            status_bar.set_error("Not in a child session")
            return

        # Get selected messages from context tree for return content
        selected_messages = context_tree.get_selected_messages()

        # Generate LLM summary of the child session
        status_bar.set_status("Generating summary...")
        input_box.set_disabled(True)

        return_content = await self._generate_return_summary(selected_messages, return_prompt)

        input_box.set_disabled(False)
        status_bar.set_status("")

        # Mark child as returned
        self.session.returned = True
        self.session.save()

        # Load parent and update it
        parent = self.session.get_parent()
        if not parent:
            status_bar.set_error("Parent session not found")
            return

        parent.mark_child_returned(self.session.id)
        parent.save()

        child_id = self.session.id

        # Switch to parent session through manager
        self._manager._sessions[parent.id] = parent
        self._manager._runners[parent.id] = SessionRunner(parent)
        self._manager.set_active(parent.id)
        chat_log.clear()
        chat_log.load_history(parent.messages)
        context_tree.load_all_sessions(parent)

        # Find and update the WithWidget
        with_widget = chat_log.find_with_widget(child_id)
        if with_widget:
            with_widget.mark_returned()

        # Add WithResultWidget to parent
        chat_log.add_with_result_widget(
            content=return_content,
            child_session_id=child_id,
            return_prompt=return_prompt,
        )

        status_bar.set_status("Returned from child session", animate=False)

    async def _generate_return_summary(self, messages: list, return_prompt: str) -> str:
        """Generate a summary of selected messages using Claude."""
        if not messages:
            return ""

        prompt = self._context_builder.build_return_summary_prompt(messages, return_prompt)

        # Stream response from Claude
        summary_parts = []
        try:
            async for event in self._helper_runner.stream_response([], prompt):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
        except Exception as e:
            # Fall back to raw content
            context_parts = [f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}" for m in messages]
            return f"Error generating summary: {e}\n\nRaw content:\n" + "\n\n".join(context_parts)

        return "".join(summary_parts) if summary_parts else ""

    def _check_auto_return(self, response_content: str) -> bool:
        """Check if auto-return condition is met. Returns True if should auto-return."""
        if not self.session.is_child_session():
            return False

        condition = self.session.return_condition

        if condition == "manual":
            return False

        if condition == "done":
            # Look for completion indicators
            done_indicators = [
                "task complete",
                "task is complete",
                "completed the task",
                "finished",
                "done",
                "all set",
            ]
            lower_content = response_content.lower()
            for indicator in done_indicators:
                if indicator in lower_content:
                    return True
            return False

        if condition.startswith("turns:"):
            try:
                max_turns = int(condition.split(":")[1])
                # Count assistant messages in this child session
                assistant_count = sum(1 for m in self.session.messages if m.role == "assistant")
                # +1 for the current response not yet saved
                return assistant_count + 1 >= max_turns
            except (ValueError, IndexError):
                return False

        return False

    def on_with_widget_child_clicked(self, event: WithWidget.ChildClicked) -> None:
        """Handle clicking on WithWidget to navigate to child session."""
        if self.streaming:
            return

        child_session = Session.load(event.child_session_id)
        if child_session:
            self._switch_to_session(child_session)

    def on_with_result_widget_child_clicked(self, event: WithResultWidget.ChildClicked) -> None:
        """Handle clicking on WithResultWidget to navigate to child session."""
        if self.streaming:
            return

        child_session = Session.load(event.child_session_id)
        if child_session:
            self._switch_to_session(child_session)

    def _switch_to_session(self, session: Session) -> None:
        """Switch to a different session."""
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        request_pane = self.query_one("#request-pane", RequestPane)

        # Register session with manager if not already known
        if session.id not in self._manager._sessions:
            self._manager._sessions[session.id] = session
            self._manager._runners[session.id] = SessionRunner(session)
        self._manager.set_active(session.id)
        context_tree.set_active_session(session.id)

        # Load session messages and filter by selection
        chat_log.clear()
        chat_log.load_history(session.messages)

        # Update header and request pane with session info
        chat_log.set_session_title(session.title)
        request_pane.show_session_info(
            session.title,
            session.summary,
            session.created,
            session.model,
        )

        # Get included turn IDs for this session (not DROP)
        session_data = context_tree._sessions.get(session.id)
        if session_data:
            included_turn_ids = [
                turn["idx"] + 1  # 1-indexed for chat_log
                for turn in session_data["turns"]
                if context_tree._context_modes.get(
                    (session.id, turn["idx"]), ContextMode.DROP
                ) != ContextMode.DROP
            ]
            show_all = len(included_turn_ids) == 0
            chat_log.filter_by_turns(included_turn_ids, show_all)

    def on_context_tree_selection_changed(self, event: ContextTree.SelectionChanged) -> None:
        """Handle tree selection changes - filter chat view."""
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.filter_by_turns(event.selected_turn_ids, event.show_all)

    def on_context_tree_session_activated(self, event: ContextTree.SessionActivated) -> None:
        """Handle clicking on a session - switch to it."""
        if self.streaming:
            return

        # Switch to this session
        self._switch_to_session(event.session)

    def on_context_tree_turn_inspected(self, event: ContextTree.TurnInspected) -> None:
        """Handle turn inspection - show in request pane and highlight tool uses."""
        request_pane = self.query_one("#request-pane", RequestPane)
        chat_log = self.query_one("#chat-log", ChatLog)

        # Handle summary nodes specially
        if event.turn_data.get("type") == "summary":
            request_pane.show_session_info(
                event.turn_data.get("title", ""),
                event.turn_data.get("summary", ""),
                "",  # No created date for this view
                "",  # No model for this view
            )
            chat_log.clear_highlights()
        elif event.turn_data.get("type") == "text":
            # Highlight the text block in the chat log
            # turn_idx is 0-indexed but turn_id is 1-indexed
            turn_id = event.turn_data.get("turn_idx", 0) + 1
            block_idx = event.turn_data.get("block_idx", -1)
            chat_log.highlight_text_block(turn_id, block_idx)
            request_pane.show_json(event.turn_data)
        elif event.turn_data.get("type") == "tool_use":
            # Highlight the tool use in the chat log
            tool_use_id = event.turn_data.get("tool_use_id", "")
            if tool_use_id:
                chat_log.highlight_tool(tool_use_id)
            request_pane.show_json(event.turn_data)
        elif event.turn_data.get("type") == "tool_result":
            # Highlight the tool result and its parent tool use
            tool_use_id = event.turn_data.get("tool_use_id", "")
            if tool_use_id:
                chat_log.highlight_tool(tool_use_id)
            request_pane.show_json(event.turn_data)
        else:
            chat_log.clear_highlights()
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

    def action_toggle_debug(self) -> None:
        """Toggle the debug pane visibility."""
        pane = self.query_one("#debug-pane", DebugPane)
        pane.toggle()

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

        # Register session with manager and initialize
        if session.id not in self._manager._sessions:
            self._manager._sessions[session.id] = session
            self._manager._runners[session.id] = SessionRunner(session)
        self._manager.set_active(session.id)
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
        # Cancel all streaming sessions
        self._manager.cancel_all()
        # Stop polling timer
        if self._poll_timer:
            self._poll_timer.stop()
        self.exit()
