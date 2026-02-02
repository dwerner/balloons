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
from textual.widgets import TextArea

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
from widgets import ChatLog, MoreBelowIndicator, InputBox, StatusBar, ContextTree, NestedSessionTree, VerticalSplitter, RequestPane, ToolBar, WithWidget, WithResultWidget, DebugPane, ForkMarker, MergeMarker, LinkMarker, Breadcrumb, ConfirmDialog, HelpModal, NewSessionModal, NewSessionResult
from claude_runner import ClaudeRunner
from session import Session
from config import get_config, BackendConfig, save_last_view
from models import (
    TextDelta, ToolUseEvent, ToolResultEvent,
    TextBlock, ToolUseBlock, InterruptionBlock, Message, ContextMode,
)
from core import (
    CommandParser,
    Formatter,
    ContextBuilder,
    SessionRunner,
    SessionManager,
    StreamEvent,
    HelperRunner,
    NewSessionCommand,
    CopyTurnsCommand,
    QueryWithCommand,
    SuspendCommand,
    ShellCommand,
    ForkCommand,
    MergeCommand,
    DeriveCommand,
    SwitchCommand,
    # Legacy
    WithCommand,
    WithCopyCommand,
    ReturnCommand,
    PwdCommand,
    CdCommand,
    ReloadCommand,
    TitleCommand,
    HelpCommand,
    BackendCommand,
    LinkCommand,
    debug_log,
    create_runner,
)
from core.tree_state import TreeState
from tokenizer import count_tokens


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
    # Track tool events for session resume (tool_use_id -> (name, input, result))
    tool_events: dict = None
    # Helper task tracking (for context compression, merge summaries)
    is_helper: bool = False  # True if this is a helper task, not a normal prompt
    helper_type: str = ""  # "compress", "merge", etc.
    # For fork context compression: data needed to complete the fork after compression
    fork_data: dict = None  # Contains indexed_messages, allowed_tools, name, background, etc.

    def __post_init__(self):
        if self.tool_events is None:
            self.tool_events = {}
        if self.fork_data is None:
            self.fork_data = {}


# Claude CLI system overhead: ~19.3k tokens for built-in tools and system prompt
CLAUDE_SYSTEM_OVERHEAD = 19300


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

    NestedSessionTree {
        width: 50;
        display: none;
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
        Binding("ctrl+space", "new_session", "New Session", show=True),
        Binding("ctrl+t", "toggle_tree", "Toggle Tree", show=True),
        Binding("ctrl+n", "switch_tree_view", "Switch Tree", show=True),
        Binding("ctrl+r", "toggle_requests", "Toggle Requests", show=True),
        Binding("ctrl+g", "toggle_debug", "Debug", show=True),
        Binding("ctrl+left", "resize_tree(-5)", "Shrink Tree", show=False),
        Binding("ctrl+right", "resize_tree(5)", "Grow Tree", show=False),
        Binding("ctrl+end", "scroll_to_bottom", "Follow", show=False),
        Binding("f1", "show_help", "Help", show=True),
    ]

    def __init__(self, session: Session = None, backend_config: BackendConfig | None = None):
        super().__init__()
        self._initial_session = session  # Will be loaded into manager
        self.streaming = False  # True if active session is streaming
        self._tree_width = 50
        self._shell_process: asyncio.subprocess.Process | None = None
        # Store backend config for creating runners
        self._backend_config = backend_config or BackendConfig(name="claude")
        # Core components
        self._command_parser = CommandParser()
        self._formatter = Formatter()
        self._context_builder = ContextBuilder()
        # Shared tree state - used by ContextTree and (future) NestedSessionTree
        self._tree_state = TreeState()
        # Session manager handles all sessions and runners
        self._manager = SessionManager(backend_config=self._backend_config)
        # Simple runner for helper streaming (summaries, etc.) - used for blocking operations
        self._helper_runner = create_runner(self._backend_config)
        # Timer for polling background sessions
        self._poll_timer = None
        # Per-session streaming contexts (session_id -> StreamingContext)
        self._streaming_contexts: dict[str, StreamingContext] = {}
        # Helper runners for non-blocking helper tasks (helper_id -> HelperRunner)
        self._helper_runners: dict[str, HelperRunner] = {}

    @property
    def session(self) -> Session | None:
        """Get the active session from the manager."""
        return self._manager.active_session

    @property
    def _session_runner(self) -> SessionRunner | None:
        """Get the active session's runner from the manager."""
        return self._manager.active_runner

    def _get_backend_for_session(self, session: Session) -> BackendConfig:
        """Get the backend config for a session, respecting session override."""
        config = get_config()
        if session.backend_name and session.backend_name in config.backends:
            return config.get_backend(session.backend_name)
        return self._backend_config

    def _create_session_runner(self, session: Session) -> SessionRunner:
        """Create a runner for a session, respecting session's backend preference."""
        backend = self._get_backend_for_session(session)
        return SessionRunner(session, runner=create_runner(backend))

    def _calculate_context_tokens(self, pending_prompt: str = "") -> int:
        """Calculate estimated context tokens for the next API call.

        Includes:
        - System overhead (Claude's built-in ~19.3k or custom system_prompt)
        - Selected conversation context
        - Pending user input

        Args:
            pending_prompt: Text currently in the input box

        Returns:
            Estimated total context tokens
        """
        backend = self._backend_config
        if self.session and self.session.backend_name:
            config = get_config()
            if self.session.backend_name in config.backends:
                backend = config.get_backend(self.session.backend_name)

        # System overhead
        if backend.type == "claude":
            system_tokens = CLAUDE_SYSTEM_OVERHEAD
        else:
            system_tokens = 0

        # Add configured system prompt tokens
        system_tokens += backend.get_system_prompt_tokens()

        # Conversation context from selected messages
        conversation_tokens = 0
        if self.session:
            try:
                context_tree = self.query_one("#context-tree", ContextTree)
                selected_messages = context_tree.get_selected_messages()
                if selected_messages:
                    conversation_tokens = self._context_builder.count_messages_tokens(selected_messages)
            except Exception:
                # Tree might not be mounted yet
                pass

        # Pending input tokens
        input_tokens = count_tokens(pending_prompt) if pending_prompt else 0

        return system_tokens + conversation_tokens + input_tokens

    def _update_context_tokens(self, pending_prompt: str = "") -> None:
        """Update the status bar with current context token count."""
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            context_tokens = self._calculate_context_tokens(pending_prompt)
            status_bar.update_stats(context_tokens=context_tokens)
        except Exception:
            # UI might not be ready
            pass

    def compose(self) -> ComposeResult:
        config = get_config()
        with Vertical():
            with Horizontal(id="main-split"):
                yield ContextTree(
                    initial_sort_order=config.session_sort_order,
                    tree_state=self._tree_state,
                    id="context-tree"
                )
                yield NestedSessionTree(
                    tree_state=self._tree_state,
                    id="nested-tree"
                )
                yield VerticalSplitter(id="splitter")
                with Vertical(id="chat-container"):
                    yield Breadcrumb(id="breadcrumb")
                    yield ChatLog(id="chat-log")
                    yield MoreBelowIndicator(id="more-below")
                yield RequestPane(id="request-pane", classes="hidden")
            yield ToolBar(id="tool-bar")
            yield DebugPane(id="debug-pane")
            yield StatusBar(id="status-bar")
            yield InputBox(id="input-box")

    def on_mount(self) -> None:
        """Initialize the app after mounting."""
        # Start the background session polling timer
        self._poll_timer = self.set_interval(0.1, self._poll_background_sessions)
        self._initialize_session()

    def _update_streaming_count(self) -> None:
        """Update the status bar with total streaming sessions count."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.set_streaming_count(len(self._streaming_contexts))

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
                        category="llm",
                        details={"event_type": event.event_type},
                    )
                    # Continue processing other events

        # Poll helper runners (for context compression, merge summaries, etc.)
        helper_ids_to_remove = []
        for helper_id, runner in self._helper_runners.items():
            ctx = self._streaming_contexts.get(helper_id)
            if not ctx:
                continue  # No context, skip

            events = runner.drain_events()
            for event in events:
                try:
                    self._dispatch_helper_event(helper_id, event, ctx, chat_log, status_bar)
                except Exception as e:
                    debug_log.error(
                        f"Helper event dispatch failed: {e}",
                        category="llm",
                        details={"event_type": event.event_type, "helper_id": helper_id},
                    )

            # Mark for removal if done
            if runner.is_done:
                helper_ids_to_remove.append(helper_id)

        # Clean up completed helpers
        for helper_id in helper_ids_to_remove:
            del self._helper_runners[helper_id]

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

            # Update tree with streaming text
            context_tree.update_streaming_text(
                session_id,
                ctx.assistant_turn_idx,
                text,
            )

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
                # Get session from manager for cost tracking
                session = self._manager._sessions.get(session_id)
                if session:
                    status_bar.update_stats(cost=session.total_cost)
                # Update context tokens now that new messages are added
                self._update_context_tokens()

        elif event.event_type == "tool_use_start":
            # Tool use started - input is still streaming
            data = event.data
            tool_use_id = data.get("tool_use_id")
            tool_name = data.get("tool_name")
            debug_event(f"tool_use_start: session={session_id[:8]} {tool_name}")

            # Initialize tracking (will be updated when tool_use completes)
            ctx.tool_events[tool_use_id] = {
                "name": tool_name,
                "input": {},  # Will be filled on tool_use
                "index": data.get("tool_index"),
                "result": None,
            }

            # Add placeholder to tree
            context_tree.add_tool_use_to_turn(
                session_id,
                ctx.assistant_turn_idx,
                tool_use_id,
                tool_name,
                {},  # Empty input for now
                data.get("tool_index"),
            )

            if is_active:
                # Add streaming tool widget
                chat_log.add_streaming_tool_use(tool_name, tool_use_id)

        elif event.event_type == "tool_input_delta":
            # Partial tool input JSON
            data = event.data
            tool_use_id = data.get("tool_use_id")
            partial_json = data.get("partial_json", "")

            # Update tree with streaming input
            tool_name = ctx.tool_events.get(tool_use_id, {}).get("name", "Tool")
            context_tree.update_tool_input_streaming(
                session_id,
                ctx.assistant_turn_idx,
                tool_use_id,
                tool_name,
                partial_json,
            )

            if is_active:
                # Update streaming tool widget
                chat_log.update_streaming_tool(tool_use_id, partial_json)

        elif event.event_type == "tool_use":
            # Tool input complete
            data = event.data
            tool_use_id = data.get("tool_use_id")
            debug_event(f"tool_use: session={session_id[:8]} {data.get('tool_name')}")

            # Update tracking with final input
            if tool_use_id in ctx.tool_events:
                ctx.tool_events[tool_use_id]["input"] = data.get("tool_input")
            else:
                ctx.tool_events[tool_use_id] = {
                    "name": data.get("tool_name"),
                    "input": data.get("tool_input"),
                    "index": data.get("tool_index"),
                    "result": None,
                }

            # Update tree with final input
            context_tree.add_tool_use_to_turn(
                session_id,
                ctx.assistant_turn_idx,
                tool_use_id,
                data.get("tool_name"),
                data.get("tool_input"),
                data.get("tool_index"),
            )

            if is_active:
                # Finish streaming tool widget with formatted content
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
                chat_log.finish_streaming_tool(
                    tool_use_id=data.get("tool_use_id"),
                    content=tool_content,
                    full_content=full_content,
                    tool_name=data.get("tool_name"),
                )

        elif event.event_type == "tool_result":
            data = event.data
            tool_use_id = data.get("tool_use_id")
            debug_event(f"tool_result: session={session_id[:8]} len={len(data.get('result', ''))}")

            # Track tool result for session resume
            if tool_use_id in ctx.tool_events:
                ctx.tool_events[tool_use_id]["result"] = data.get("result")

            # Add to tree
            context_tree.add_tool_result_to_turn(
                session_id,
                ctx.assistant_turn_idx,
                tool_use_id,
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
                status_bar.set_status("Claude asked a question (not supported in non-interactive mode)", animate=False)
            self._finalize_streaming(session_id, ctx, chat_log, context_tree, status_bar)

    def _dispatch_helper_event(
        self,
        helper_id: str,
        event: StreamEvent,
        ctx: StreamingContext,
        chat_log: ChatLog,
        status_bar: StatusBar,
    ) -> None:
        """Dispatch a helper event (context compression, merge summary).

        Helper events stream into the chat like regular messages, but when done
        trigger the next phase (e.g., start the actual fork prompt).
        """
        if event.event_type == "text":
            text = event.data
            debug_event(f"helper text: helper={helper_id[:8]} len={len(text)}")
            ctx.content += text
            if ctx.is_active:
                chat_log.append_to_current(text)

        elif event.event_type == "done":
            debug_event(f"helper done: helper={helper_id[:8]}")
            self._finalize_helper(helper_id, ctx, chat_log, status_bar)

        elif event.event_type == "error":
            debug_event(f"helper error: helper={helper_id[:8]} {event.data}")
            if ctx.is_active:
                chat_log.append_to_current(f"\n\n[Error: {event.data}]")
            self._finalize_helper(helper_id, ctx, chat_log, status_bar, error=event.data)

        elif event.event_type == "cancelled":
            debug_event(f"helper cancelled: helper={helper_id[:8]}")
            self._finalize_helper(helper_id, ctx, chat_log, status_bar, cancelled=True)

    def _finalize_helper(
        self,
        helper_id: str,
        ctx: StreamingContext,
        chat_log: ChatLog,
        status_bar: StatusBar,
        error: str = None,
        cancelled: bool = False,
    ) -> None:
        """Finalize a helper task and trigger the next phase."""
        debug_log.info(
            f"Finalizing helper (type={ctx.helper_type})",
            category="stream",
            details={"helper_id": helper_id},
        )

        if ctx.is_active:
            # Finish the helper message display
            chat_log.finish_current_message()

        # Clean up streaming context
        if helper_id in self._streaming_contexts:
            del self._streaming_contexts[helper_id]

        if error or cancelled:
            # Helper failed - clean up and re-enable input
            input_box = self.query_one("#input-box", InputBox)
            input_box.set_disabled(False)
            status_bar.set_streaming(False)
            self.streaming = False
            if error:
                status_bar.set_error(f"Helper failed: {error}")
            return

        # Success - trigger next phase based on helper type
        if ctx.helper_type == "compress":
            # Context compression complete - now start the actual fork
            self._complete_fork_after_compression(ctx, chat_log, status_bar)
        elif ctx.helper_type == "derive":
            # Context compression complete - now start the derived session
            self._complete_derive_after_compression(ctx, chat_log, status_bar)

    def _complete_fork_after_compression(
        self,
        ctx: StreamingContext,
        chat_log: ChatLog,
        status_bar: StatusBar,
    ) -> None:
        """Complete a fork after context compression finishes.

        The compression result is in ctx.content, and fork_data has the original params.
        """
        fork_data = ctx.fork_data
        if not fork_data:
            debug_log.error("No fork_data in context after compression", category="stream")
            # Clean up UI state
            input_box = self.query_one("#input-box", InputBox)
            input_box.set_disabled(False)
            status_bar.set_streaming(False)
            self.streaming = False
            status_bar.set_error("Fork failed: missing context data")
            return

        context_tree = self.query_one("#context-tree", ContextTree)
        input_box = self.query_one("#input-box", InputBox)

        # Extract fork params
        child_session = fork_data["child_session"]
        prompt = fork_data["prompt"]
        name = fork_data["name"]
        background = fork_data["background"]
        allowed_tools = fork_data["allowed_tools"]
        copy_items = fork_data["copy_items"]
        compress_group_positions = fork_data["compress_group_positions"]  # list of (summary_text, first_idx)

        # Build the summary items from compression result
        # For now, we only support one compress group streaming at a time
        summary_text = ctx.content.strip()
        summary_items = []
        if summary_text and compress_group_positions:
            first_idx = compress_group_positions[0]
            summary_msg = Message(
                role="user",
                content=f"[Context Summary]\n{summary_text}",
                content_blocks=[TextBlock(text=f"[Context Summary]\n{summary_text}")],
            )
            summary_items.append((summary_msg, first_idx))

        # Combine COPY messages and summaries, sorted by original index
        all_items = copy_items + summary_items
        all_items.sort(key=lambda x: x[1])
        context_messages = [msg for msg, _ in all_items]

        # Add all context messages to the child session
        for msg in context_messages:
            child_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

        child_session.save()

        # Register child in parent
        parent_session = fork_data["parent_session"]
        fork_point = fork_data["fork_point"]
        parent_session.add_child(
            child_session.id,
            prompt,
            name=name,
            fork_point=fork_point,
        )
        parent_session.save()

        # Add fork marker to parent's chat log
        chat_log.add_fork_marker(
            prompt=prompt,
            child_session_id=child_session.id,
            fork_name=name or child_session.id[:8],
            status="active" if not background else "background",
        )

        # Register child session with manager
        self._manager._sessions[child_session.id] = child_session
        self._manager._runners[child_session.id] = self._create_session_runner(child_session)

        if background:
            # Background mode - stay in parent
            turn_idx = len(child_session.messages)
            new_ctx = StreamingContext(
                session_id=child_session.id,
                user_turn_idx=turn_idx,
                assistant_turn_idx=turn_idx + 1,
                prompt=prompt,
                is_active=False,
            )
            self._streaming_contexts[child_session.id] = new_ctx

            # Update tree streaming indicator and status bar count
            context_tree.set_session_streaming(child_session.id, True)
            self._update_streaming_count()

            # Start tree turns for child
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
            status_bar.set_status(f"Fork '{name or child_session.id[:8]}' started in background", animate=False)
            input_box.set_disabled(False)
            self.streaming = False
        else:
            # Foreground mode - switch to child
            breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
            self._manager.set_active(child_session.id)
            chat_log.clear()
            chat_log.load_history(child_session.messages, session=child_session)
            context_tree.load_all_sessions(child_session)
            breadcrumb.set_session(child_session)

            # Start streaming the actual prompt
            self._start_streaming(prompt)

    def _complete_derive_after_compression(
        self,
        ctx: StreamingContext,
        chat_log: ChatLog,
        status_bar: StatusBar,
    ) -> None:
        """Complete a derive after context compression finishes.

        Similar to fork completion but simpler - no parent/child relationship.
        """
        fork_data = ctx.fork_data
        if not fork_data:
            debug_log.error("No fork_data in context after derive compression", category="stream")
            input_box = self.query_one("#input-box", InputBox)
            input_box.set_disabled(False)
            status_bar.set_streaming(False)
            self.streaming = False
            status_bar.set_error("Derive failed: missing context data")
            return

        context_tree = self.query_one("#context-tree", ContextTree)
        input_box = self.query_one("#input-box", InputBox)

        # Extract params
        new_session = fork_data["new_session"]
        prompt = fork_data["prompt"]
        allowed_tools = fork_data["allowed_tools"]
        copy_items = fork_data["copy_items"]
        compress_group_positions = fork_data["compress_group_positions"]

        # Build the summary items from compression result
        summary_text = ctx.content.strip()
        summary_items = []
        if summary_text and compress_group_positions:
            first_idx = compress_group_positions[0]
            summary_msg = Message(
                role="user",
                content=f"[Context Summary]\n{summary_text}",
                content_blocks=[TextBlock(text=f"[Context Summary]\n{summary_text}")],
            )
            summary_items.append((summary_msg, first_idx))

        # Combine COPY messages and summaries, sorted by original index
        all_items = copy_items + summary_items
        all_items.sort(key=lambda x: x[1])
        context_messages = [msg for msg, _ in all_items]

        # Add all context messages to the new session
        for msg in context_messages:
            new_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

        new_session.save()

        # Register and switch to new session
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
        self._manager._sessions[new_session.id] = new_session
        self._manager._runners[new_session.id] = self._create_session_runner(new_session)
        self._manager.set_active(new_session.id)

        chat_log.clear()
        chat_log.load_history(new_session.messages, session=new_session)
        context_tree.load_all_sessions(new_session)
        breadcrumb.set_session(new_session)

        # Start streaming the actual prompt
        self._start_streaming(prompt)

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

            # Add interruption marker if cancelled
            if cancelled:
                assistant_blocks.append(InterruptionBlock(reason="user_cancelled"))
                # Also add the visual marker to the chat log
                if ctx.is_active:
                    chat_log.add_interruption_marker("user_cancelled")

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
                # Get exchange_id and turns from result (if available)
                exchange_id = result.exchange_id if result else None
                turns = result.turns if result else []

                if ctx.query_with:
                    # query_with: only save assistant response, no user message
                    if turns:
                        # New model: save individual turns
                        for turn in turns:
                            session.messages.append(turn)
                    else:
                        # Legacy: single assistant message
                        session.add_message("assistant", content, content_blocks=assistant_blocks, exchange_id=exchange_id)
                else:
                    # Normal case: save user message + assistant turns
                    user_blocks = [TextBlock(text=ctx.prompt)]
                    session.add_message("user", ctx.prompt, content_blocks=user_blocks, exchange_id=exchange_id)

                    if turns:
                        # New model: save individual assistant turns
                        for turn in turns:
                            session.messages.append(turn)
                    else:
                        # Legacy: single assistant message
                        session.add_message("assistant", content, content_blocks=assistant_blocks, exchange_id=exchange_id)

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
                    status_bar.set_status(f"Background session done: {session_id[:8]}", animate=False)

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
                # Update tree streaming indicator and status bar count
                context_tree.set_session_streaming(session_id, False)
                self._tree_state.stop_streaming(session_id)
                self._update_streaming_count()
                debug_log.info("Finalization complete, context cleaned up", category="stream", session_id=session_id)

    def _load_last_viewed_session(self) -> tuple[Session | None, int | None]:
        """Load the last viewed session and turn index from config.

        Returns (session, turn_index) where turn_index may be None.
        Falls back to most recently modified session if last view doesn't exist.
        """
        config = get_config()

        # Try last viewed session first
        if config.last_view_session_id:
            session = self._manager.load_session(config.last_view_session_id)
            if session:
                return session, config.last_view_turn_index

        # Fall back to most recently modified
        all_sessions = Session.list_sessions()
        if not all_sessions:
            return None, None

        sort_order = config.session_sort_order

        # Sort sessions according to preference
        # list_sessions returns list of dicts with keys: id, created, last_modified, etc.
        if sort_order == "modified_desc":
            all_sessions.sort(key=lambda x: x["last_modified"], reverse=True)
        elif sort_order == "modified_asc":
            all_sessions.sort(key=lambda x: x["last_modified"])
        elif sort_order == "date_desc":
            all_sessions.sort(key=lambda x: x["created"], reverse=True)
        elif sort_order == "date_asc":
            all_sessions.sort(key=lambda x: x["created"])
        elif sort_order in ("title_asc", "title_desc"):
            # For title sort, still default to most recently modified
            all_sessions.sort(key=lambda x: x["last_modified"], reverse=True)
        else:
            # Default: most recently modified
            all_sessions.sort(key=lambda x: x["last_modified"], reverse=True)

        # Load the first session (top of sorted list)
        session_id = all_sessions[0]["id"]
        session = self._manager.load_session(session_id)
        return session, None  # No saved turn index for fallback

    def _initialize_session(self) -> None:
        """Initialize the UI with the current session."""
        restore_turn_index = None  # Turn index to scroll to after init

        if self._initial_session is not None:
            # Load initial session into manager (passed via --resume)
            self._manager._sessions[self._initial_session.id] = self._initial_session
            self._manager._runners[self._initial_session.id] = self._create_session_runner(self._initial_session)
            self._manager.set_active(self._initial_session.id)
            self._initial_session = None  # Clear so we don't reload on subsequent calls
        elif self.session is None:
            # No session passed - try to load the last viewed session
            session, restore_turn_index = self._load_last_viewed_session()
            if session is None:
                # No sessions exist - create a new one
                session = self._manager.create_session()
            self._manager.set_active(session.id)

        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        status_bar = self.query_one("#status-bar", StatusBar)
        input_box = self.query_one("#input-box", InputBox)
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)

        # Load all sessions into tree (current session's turns auto-selected)
        context_tree.load_all_sessions(self.session)

        # Load current session's messages into chat view
        if self.session.messages:
            chat_log.load_history(self.session.messages, session=self.session)

        # Set session title in chat header
        if self.session.title:
            chat_log.set_session_title(self.session.title)

        # Update breadcrumb to show current position in hierarchy
        breadcrumb.set_session(self.session)

        # Show session info in request pane
        request_pane = self.query_one("#request-pane", RequestPane)
        request_pane.show_session_info(
            self.session.title,
            self.session.summary,
            self.session.created,
            self.session.model,
        )

        # Update status bar with session info
        backend_name = self.session.backend_name or get_config().default_backend
        if self.session.model:
            status_bar.update_stats(
                model=self.session.model,
                backend=backend_name,
                context_window=self.session.context_window,
                cost=self.session.total_cost,
            )
        else:
            status_bar.update_stats(backend=backend_name)

        # Update working directory in status bar
        status_bar.update_working_directory(self.session.working_directory or "")

        # Focus the input box
        input_box.focus()

        # Scroll to restored turn if we have one
        if restore_turn_index is not None and restore_turn_index < len(self.session.messages):
            # Turn IDs in chat_log are 1-indexed
            turn_id = restore_turn_index + 1
            # Use call_after_refresh to ensure widgets are laid out before scrolling
            # Use default argument to capture turn_id value (avoid late binding)
            self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))

        # Initial context token update
        self._update_context_tokens()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Handle text changes in the input box - update context token count live."""
        # Only handle events from our input box
        if event.text_area.id == "input-box":
            self._update_context_tokens(event.text_area.text)

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

        # Update tree streaming indicator and status bar count
        context_tree.set_session_streaming(self.session.id, True)
        self._tree_state.start_streaming(self.session.id)
        self._update_streaming_count()

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
            await self._handle_new_session(cmd.prompt, cmd.title)
        elif isinstance(cmd, CopyTurnsCommand):
            self._handle_copy_turns()
        elif isinstance(cmd, QueryWithCommand):
            await self._handle_query_with(cmd.prompt)
        elif isinstance(cmd, SuspendCommand):
            self._handle_suspend(cmd.shell_cmd)
        elif isinstance(cmd, ShellCommand):
            await self._handle_shell_command(cmd.shell_cmd)
        # New fork/merge commands
        elif isinstance(cmd, ForkCommand):
            await self._handle_fork_command(cmd.prompt, cmd.name, cmd.background)
        elif isinstance(cmd, MergeCommand):
            await self._handle_merge_command(cmd.prompt)
        elif isinstance(cmd, DeriveCommand):
            await self._handle_derive_command(cmd.prompt)
        elif isinstance(cmd, SwitchCommand):
            self._handle_switch_command(cmd.name)
        # Legacy commands (still work for backwards compat)
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
        elif isinstance(cmd, TitleCommand):
            self._handle_title_command(cmd.title)
        elif isinstance(cmd, HelpCommand):
            self.push_screen(HelpModal())
        elif isinstance(cmd, BackendCommand):
            await self._handle_backend_command(cmd.backend_name)
        elif isinstance(cmd, LinkCommand):
            await self._handle_link_command(cmd.target_session_prefixes, cmd.prompt)

    def _format_tool_use(
        self, event: ToolUseEvent
    ) -> RenderableType | tuple[RenderableType, RenderableType]:
        """Format a tool use event for display.

        Returns single renderable, or tuple of (truncated, full) if content was truncated.
        """
        return self._formatter.format_tool_use(event)

    def _format_tool_use_for_resume(
        self, tool_name: str, tool_input: dict
    ) -> RenderableType | tuple[RenderableType, RenderableType]:
        """Format a tool use for display during session resume.

        Simple wrapper that creates a ToolUseEvent from raw data.
        """
        event = ToolUseEvent(
            tool_use_id="",  # Not needed for formatting
            tool_name=tool_name,
            tool_input=tool_input,
        )
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

    def _format_tool_result_for_resume(
        self, result: str
    ) -> RenderableType | tuple[RenderableType, RenderableType]:
        """Format a tool result for display during session resume.

        Simple wrapper that creates a ToolResultEvent from raw data.
        """
        event = ToolResultEvent(
            tool_use_id="",  # Not needed for formatting
            result=result,
        )
        # No last_tool_use context available during resume
        return self._formatter.format_tool_result(event, None)

    async def _handle_new_session(self, prompt: str = "", title: str = "") -> None:
        """Create a new session, optionally with an initial prompt and title."""
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        status_bar = self.query_one("#status-bar", StatusBar)
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)

        # Create new session through manager
        new_session = self._manager.create_session()
        if title:
            new_session.title = title
        self._manager.set_active(new_session.id)

        # Clear and reload UI
        chat_log.clear()
        context_tree.load_all_sessions(self.session)
        breadcrumb.set_session(self.session)
        status_bar.set_status("New session created", animate=False)

        # Update context tokens for new empty session
        self._update_context_tokens()

        # If a prompt was provided, send it
        if prompt:
            self._start_streaming(prompt)

    def _handle_pwd_command(self) -> None:
        """Show the current working directory for the session."""
        status_bar = self.query_one("#status-bar", StatusBar)
        if self.session.working_directory:
            status_bar.set_status(f"Working directory: {self.session.working_directory}", animate=False)
        else:
            status_bar.set_status(f"No working directory set (process cwd: {os.getcwd()})", animate=False)

    def _handle_cd_command(self, path_arg: str) -> None:
        """Change the working directory for the session."""
        status_bar = self.query_one("#status-bar", StatusBar)

        if not path_arg:
            # No argument - clear working directory or show current
            if self.session.working_directory:
                status_bar.set_status(f"Working directory: {self.session.working_directory}", animate=False)
            else:
                status_bar.set_status("No working directory set. Use :cd <path> to set one.", animate=False)
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

            # Set the working directory (resolves to canonical absolute path)
            self.session.set_working_directory(str(target_path))
            self.session.save()
            status_bar.update_working_directory(self.session.working_directory)
            status_bar.set_status(f"Changed to: {target_path}", animate=False)

        except Exception as e:
            status_bar.set_error(f"Invalid path: {e}")

    def _handle_reload(self) -> None:
        """Reload the app by re-executing the process."""
        self.session.save()
        # Save current view position so we return here after reload
        turn_index = len(self.session.messages) - 1 if self.session.messages else None
        save_last_view(self.session.id, turn_index)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _handle_title_command(self, title: str) -> None:
        """Set the session title."""
        status_bar = self.query_one("#status-bar", StatusBar)

        self.session.title = title
        self.session.save()

        # Update UI with new title
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.set_session_title(title)

        request_pane = self.query_one("#request-pane", RequestPane)
        request_pane.show_session_info(
            title,
            self.session.summary,
            self.session.created,
            self.session.model,
        )

        # Reload context tree to show title
        context_tree = self.query_one("#context-tree", ContextTree)
        context_tree.load_all_sessions(self.session)

        status_bar.set_status(f"Session titled: {title}", animate=False)

    async def _handle_backend_command(self, backend_name: str) -> None:
        """Set or show the backend for this session."""
        status_bar = self.query_one("#status-bar", StatusBar)
        config = get_config()

        if not backend_name:
            # Show current backend
            current = self.session.backend_name or config.default_backend
            available = list(config.backends.keys())
            status_bar.set_status(
                f"Backend: {current} (available: {', '.join(available)})",
                animate=False
            )
            return

        # Validate backend exists
        if backend_name not in config.backends:
            available = list(config.backends.keys())
            status_bar.set_status(
                f"Unknown backend: {backend_name}. Available: {', '.join(available)}",
                animate=False
            )
            return

        # Set backend for this session
        self.session.backend_name = backend_name
        self.session.save()

        # Recreate the runner for this session with new backend
        backend_config = config.get_backend(backend_name)
        self._manager._runners[self.session.id] = SessionRunner(
            self.session, runner=create_runner(backend_config)
        )

        # Update status bar with new backend and model
        # Use the backend's configured model, or clear it if not set
        status_bar.update_stats(backend=backend_name, model=backend_config.model or "")
        status_bar.set_status(f"Backend set to: {backend_name}", animate=False)

    async def _handle_link_command(self, target_prefixes: list[str], prompt: str) -> None:
        """Create bidirectional links to one or more sessions.

        Args:
            target_prefixes: List of 8-char hash prefixes of target sessions
            prompt: Prompt for generating link summary
        """
        import uuid
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Resolve all target sessions first
        all_sessions = Session.list_sessions()
        resolved_targets: list[tuple[str, Session]] = []  # (prefix, session)

        for target_prefix in target_prefixes:
            matches = [s for s in all_sessions if s["id"].startswith(target_prefix)]

            if not matches:
                status_bar.set_error(f"No session found matching '{target_prefix}'")
                return

            if len(matches) > 1:
                match_ids = [s["id"][:8] for s in matches[:5]]
                status_bar.set_error(f"Multiple sessions match '{target_prefix}': {', '.join(match_ids)}...")
                return

            target_session_id = matches[0]["id"]

            # Check not linking to self
            if target_session_id == self.session.id:
                status_bar.set_error("Cannot link session to itself")
                return

            # Load target session
            target_session = Session.load(target_session_id)
            if not target_session:
                status_bar.set_error(f"Failed to load session {target_prefix}")
                return

            resolved_targets.append((target_prefix, target_session))

        # Get selected context for summary generation
        indexed_messages = context_tree.get_selected_messages_with_indices()
        if not indexed_messages:
            status_bar.set_error("No context selected for link summary")
            return

        # Generate summary using LLM (one summary shared across all links)
        status_bar.set_status("Generating link summary...", animate=True)
        self.refresh()
        await asyncio.sleep(0)

        # Build messages for summary
        messages = [msg for msg, _ in indexed_messages]
        summary = await self._generate_link_summary(messages, prompt)

        # Current position in this session (same for all links from this session)
        current_link_point = len(self.session.messages)

        # Create links to each target
        linked_names = []
        for target_prefix, target_session in resolved_targets:
            # Create unique link ID (same for both sides of this pair)
            link_id = str(uuid.uuid4())
            target_link_point = len(target_session.messages)

            # Add link to current session
            self.session.add_link(
                link_id=link_id,
                linked_session_id=target_session.id,
                link_point=current_link_point,
                summary=summary,
            )

            # Add link to target session
            target_session.add_link(
                link_id=link_id,
                linked_session_id=self.session.id,
                link_point=target_link_point,
                summary=summary,
            )
            target_session.save()

            # Add link marker to current chat log
            target_name = target_session.title or target_session.fork_name or target_session.id[:8]
            chat_log.add_link_marker(
                summary=summary,
                linked_session_id=target_session.id,
                linked_session_name=target_name,
                link_point=target_link_point,
            )
            linked_names.append(target_name)

        # Save current session once (after all links added)
        self.session.save()

        if len(linked_names) == 1:
            status_bar.set_status(f"Linked to '{linked_names[0]}'", animate=False)
        else:
            status_bar.set_status(f"Linked to {len(linked_names)} sessions", animate=False)

    async def _generate_link_summary(self, messages: list[Message], user_prompt: str) -> str:
        """Generate a summary of context for a link.

        Args:
            messages: The messages to summarize
            user_prompt: User's guidance for the summary

        Returns:
            Generated summary string
        """
        # Build conversation context
        messages_text = []
        for msg in messages:
            role = "User" if msg.role == "user" else "Assistant"
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "..."
            messages_text.append(f"{role}: {content}")

        context_str = "\n\n".join(messages_text)

        summary_prompt = f"""Summarize the following conversation context in 1-3 concise sentences.
The summary will be used as a link reference between sessions.

{f"User guidance: {user_prompt}" if user_prompt else ""}

Conversation:
{context_str}

Provide a brief, informative summary:"""

        # Use the helper runner for summary generation
        summary_parts = []
        try:
            async for event in self._helper_runner.stream_response([], summary_prompt, disable_tools=True):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
        except Exception as e:
            debug_log.error(f"Link summary generation failed: {e}", category="link")
            return user_prompt or "Linked context"

        result = "".join(summary_parts)
        if result:
            return result.strip()
        else:
            # Fallback if LLM fails
            return user_prompt or "Linked context"

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

        # Cancel helper runner (used for context summaries, etc.)
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
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
        chat_log.clear()
        self._manager._sessions[new_session.id] = new_session
        self._manager._runners[new_session.id] = self._create_session_runner(new_session)
        self._manager.set_active(new_session.id)
        context_tree.load_all_sessions(new_session)
        chat_log.load_history(new_session.messages, session=new_session)
        breadcrumb.set_session(new_session)

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
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)

        # Get selected messages for context (before creating new session)
        selected_messages = context_tree.get_selected_messages()
        allowed_tools = tool_bar.get_enabled_tools()

        # Create new session for the response through manager
        new_session = self._manager.create_session()
        self._manager.set_active(new_session.id)

        # Clear chat log and switch to new session
        chat_log.clear()
        context_tree.load_all_sessions(new_session)
        breadcrumb.set_session(new_session)

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

        # Update tree streaming indicator and status bar count
        context_tree.set_session_streaming(new_session.id, True)
        self._update_streaming_count()

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
        """Fork a child session, respecting context modes (COPY verbatim, COMPRESS via Claude)."""
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
        compress_messages = [m for m in selected_messages if m.context_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE)]

        # Create child session with parent reference
        child_session = Session()
        child_session.parent_id = self.session.id
        child_session.return_condition = return_condition

        # Copy COPY-marked messages verbatim to child
        for msg in copy_messages:
            child_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

        # Generate summaries for COMPRESS-marked messages
        if compress_messages:
            status_bar.set_status("Compressing context...")
            input_box.set_disabled(True)

            summary = await self._generate_context_summary(compress_messages)

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
        self._manager._runners[child_session.id] = self._create_session_runner(child_session)

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

            # Update tree streaming indicator and status bar count
            context_tree.set_session_streaming(child_session.id, True)
            self._update_streaming_count()

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
            breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
            self._manager.set_active(child_session.id)
            chat_log.clear()
            chat_log.load_history(child_session.messages, session=child_session)
            context_tree.load_all_sessions(child_session)
            breadcrumb.set_session(child_session)

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

    async def _build_context_with_summaries(
        self,
        indexed_messages: list[tuple],
        status_bar,
        input_box,
    ) -> list[Message]:
        """Build context messages with summaries inserted at their original positions.

        This handles the interleaving of COPY messages (kept verbatim) and COMPRESS
        messages (summarized). Non-contiguous COMPRESS groups become separate summaries,
        each inserted at the position of the first message in that group.

        Args:
            indexed_messages: List of (Message, original_index) tuples from
                              get_selected_messages_with_indices()
            status_bar: StatusBar widget for progress updates
            input_box: InputBox widget to disable during summarization

        Returns:
            List of Message objects in correct order, with COMPRESS messages
            replaced by summary messages at appropriate positions.
        """
        if not indexed_messages:
            return []

        # Separate COPY and COMPRESS messages, keeping indices
        copy_items = []  # (msg, idx)
        compress_items = []  # (msg, idx)

        for msg, idx in indexed_messages:
            if msg.context_mode == ContextMode.COPY:
                copy_items.append((msg, idx))
            elif msg.context_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
                compress_items.append((msg, idx))

        # Group contiguous COMPRESS messages
        # Contiguous = consecutive original indices
        compress_groups = []  # list of [(msg, idx), ...]
        if compress_items:
            compress_items.sort(key=lambda x: x[1])
            current_group = [compress_items[0]]

            for i in range(1, len(compress_items)):
                msg, idx = compress_items[i]
                _, prev_idx = current_group[-1]

                # Check if contiguous (allowing for gaps where COPY messages are)
                # Two COMPRESS messages are in the same group if there are no
                # COPY messages between them
                copy_indices = {i for _, i in copy_items}
                has_copy_between = any(prev_idx < ci < idx for ci in copy_indices)

                if has_copy_between:
                    # Start new group
                    compress_groups.append(current_group)
                    current_group = [(msg, idx)]
                else:
                    # Continue current group
                    current_group.append((msg, idx))

            compress_groups.append(current_group)

        # Generate summaries for each COMPRESS group
        summary_items = []  # (summary_msg, insert_idx)
        if compress_groups:
            status_bar.set_status("Compressing context...", animate=True)
            input_box.set_disabled(True)
            # Force UI refresh before starting long operation
            self.refresh()
            await asyncio.sleep(0)

            for i, group in enumerate(compress_groups):
                group_messages = [msg for msg, _ in group]
                first_idx = group[0][1]  # Position of first message in group

                # Update status with progress
                if len(compress_groups) > 1:
                    status_bar.set_status(f"Compressing context ({i+1}/{len(compress_groups)})...", animate=True)
                    self.refresh()
                    await asyncio.sleep(0)

                summary = await self._generate_context_summary(group_messages)

                if summary:
                    summary_msg = Message(
                        role="user",
                        content=f"[Context Summary]\n{summary}",
                        content_blocks=[TextBlock(text=f"[Context Summary]\n{summary}")],
                    )
                    summary_items.append((summary_msg, first_idx))

            status_bar.set_status("", animate=False)
            input_box.set_disabled(False)

        # Combine COPY messages and summaries, sorted by original index
        all_items = copy_items + summary_items
        all_items.sort(key=lambda x: x[1])

        return [msg for msg, _ in all_items]

    async def _generate_merge_summary(self, fork_session: Session, user_prompt: str = "") -> str:
        """Generate a summary of what was accomplished in a fork.

        Args:
            fork_session: The fork session to summarize
            user_prompt: Optional user guidance for the summary

        Returns:
            A concise summary of the fork's work
        """
        # Build conversation context from the fork
        messages_text = []
        for msg in fork_session.messages:
            role = "User" if msg.role == "user" else "Assistant"
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            messages_text.append(f"{role}: {content}")

        conversation = "\n\n".join(messages_text)

        # Build the summary prompt
        if user_prompt:
            summary_prompt = f"""Summarize the following conversation, focusing on: {user_prompt}

The summary should be 1-3 sentences describing what was accomplished or discovered.
Be specific about outcomes, not process.

Conversation:
{conversation}

Summary:"""
        else:
            summary_prompt = f"""Summarize the following conversation in 1-3 sentences.
Focus on what was accomplished or discovered, not the process.
Be specific about outcomes.

Conversation:
{conversation}

Summary:"""

        # Stream response from Claude
        summary_parts = []
        try:
            async for event in self._helper_runner.stream_response([], summary_prompt):
                if isinstance(event, TextDelta):
                    summary_parts.append(event.text)
        except Exception as e:
            # Fall back to a simple message
            return f"Merge completed (summary generation failed: {e})"

        return "".join(summary_parts).strip() if summary_parts else "Merge completed"

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
        self._manager._runners[child_session.id] = self._create_session_runner(child_session)

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

            # Update tree streaming indicator and status bar count
            context_tree.set_session_streaming(child_session.id, True)
            self._update_streaming_count()

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
            breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
            self._manager.set_active(child_session.id)
            chat_log.clear()
            chat_log.load_history(child_session.messages, session=child_session)
            context_tree.load_all_sessions(child_session)
            breadcrumb.set_session(child_session)

            # Use _start_streaming which handles all the setup
            self._start_streaming(prompt)

    # ===== NEW FORK/MERGE COMMANDS =====

    async def _handle_fork_command(self, prompt: str, name: str = "", background: bool = False) -> None:
        """Fork a child session from current session.

        Uses context modes from tree selection:
        - COPY: Include verbatim
        - COMPRESS: LLM summarizes first (with summaries at original positions)
        - DROP: Exclude

        If COMPRESS messages exist, shows the compression streaming in the UI
        before creating the fork. This avoids UI blocking.

        Args:
            prompt: Initial prompt for the fork
            name: Optional name for easy reference (e.g., "auth-bug")
            background: If True, run in background and stay in parent
        """
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)
        tool_bar = self.query_one("#tool-bar", ToolBar)

        # Check if current session is read-only (merged fork)
        if self.session.is_read_only():
            status_bar.set_error("Cannot fork from a merged session")
            return

        # Get selected messages with their original indices
        indexed_messages = context_tree.get_selected_messages_with_indices()
        allowed_tools = tool_bar.get_enabled_tools()

        # Track fork point (current turn count in parent)
        fork_point = len(self.session.messages)

        # Separate COPY and COMPRESS messages
        copy_items = []  # (msg, idx)
        compress_items = []  # (msg, idx)

        for msg, idx in indexed_messages:
            if msg.context_mode == ContextMode.COPY:
                copy_items.append((msg, idx))
            elif msg.context_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
                compress_items.append((msg, idx))

        # Group contiguous COMPRESS messages
        compress_groups = []  # list of [(msg, idx), ...]
        if compress_items:
            compress_items.sort(key=lambda x: x[1])
            current_group = [compress_items[0]]

            for i in range(1, len(compress_items)):
                msg, idx = compress_items[i]
                _, prev_idx = current_group[-1]

                # Check if contiguous (no COPY messages between them)
                copy_indices = {i for _, i in copy_items}
                has_copy_between = any(prev_idx < ci < idx for ci in copy_indices)

                if has_copy_between:
                    compress_groups.append(current_group)
                    current_group = [(msg, idx)]
                else:
                    current_group.append((msg, idx))

            compress_groups.append(current_group)

        # Create child session with fork metadata (but don't populate yet)
        child_session = Session()
        child_session.parent_id = self.session.id
        child_session.fork_name = name
        child_session.fork_status = "active"
        child_session.fork_point_turn = fork_point

        if not compress_groups:
            # No compression needed - proceed immediately
            # Add COPY messages to child
            copy_items.sort(key=lambda x: x[1])
            for msg, _ in copy_items:
                child_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

            child_session.save()

            # Register child in parent
            self.session.add_child(
                child_session.id,
                prompt,
                name=name,
                fork_point=fork_point,
            )
            self.session.save()

            # Add fork marker to parent's chat log
            chat_log.add_fork_marker(
                prompt=prompt,
                child_session_id=child_session.id,
                fork_name=name or child_session.id[:8],
                status="active" if not background else "background",
            )

            # Register child session with manager
            self._manager._sessions[child_session.id] = child_session
            self._manager._runners[child_session.id] = self._create_session_runner(child_session)

            if background:
                # Background mode - stay in parent
                turn_idx = len(child_session.messages)
                ctx = StreamingContext(
                    session_id=child_session.id,
                    user_turn_idx=turn_idx,
                    assistant_turn_idx=turn_idx + 1,
                    prompt=prompt,
                    is_active=False,
                )
                self._streaming_contexts[child_session.id] = ctx

                context_tree.set_session_streaming(child_session.id, True)
                self._update_streaming_count()

                context_tree.start_turn(child_session.id, turn_idx, "user")
                context_tree.finish_turn(
                    child_session.id, turn_idx, prompt, [TextBlock(text=prompt)], []
                )
                context_tree.start_turn(child_session.id, turn_idx + 1, "assistant")

                child_runner = self._manager._runners[child_session.id]
                child_runner.start_background(
                    prompt=prompt,
                    messages=child_session.messages,
                    allowed_tools=allowed_tools,
                )
                status_bar.set_status(f"Fork '{name or child_session.id[:8]}' started in background", animate=False)
            else:
                # Foreground mode - switch to child
                # Save child again so it has a more recent timestamp than parent
                # (parent was saved after child to register the fork relationship)
                child_session.save()

                breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
                self._manager.set_active(child_session.id)
                chat_log.clear()
                chat_log.load_history(child_session.messages, session=child_session)
                context_tree.load_all_sessions(child_session)
                breadcrumb.set_session(child_session)

                self._start_streaming(prompt)
        else:
            # Compression needed - start helper streaming
            # For now, only support one compress group (most common case)
            # TODO: Support multiple compress groups with sequential streaming
            group = compress_groups[0]
            group_messages = [msg for msg, _ in group]
            first_idx = group[0][1]

            # Build summary prompt
            summary_prompt = self._context_builder.build_context_summary_prompt(group_messages)

            # Create helper runner
            import uuid
            helper_id = f"compress-{uuid.uuid4().hex[:8]}"
            helper_runner = HelperRunner(helper_id, runner=create_runner(self._backend_config))
            self._helper_runners[helper_id] = helper_runner

            # Create streaming context for the helper
            ctx = StreamingContext(
                session_id=helper_id,
                user_turn_idx=-1,  # Not a real turn
                assistant_turn_idx=-1,
                prompt="",
                is_active=True,
                is_helper=True,
                helper_type="compress",
                fork_data={
                    "child_session": child_session,
                    "parent_session": self.session,
                    "prompt": prompt,
                    "name": name,
                    "background": background,
                    "allowed_tools": allowed_tools,
                    "copy_items": copy_items,
                    "compress_group_positions": [first_idx],  # Just first group for now
                    "fork_point": fork_point,
                },
            )
            self._streaming_contexts[helper_id] = ctx

            # Set up UI for compression streaming
            input_box.set_disabled(True)
            status_bar.set_streaming(True)
            self.streaming = True

            # Add a "Compressing context..." message to chat
            chat_log.add_user_message("[Compressing context for fork...]")
            chat_log.add_assistant_message()

            # Start the helper
            helper_runner.start_background(summary_prompt)

    async def _handle_merge_command(self, prompt: str = "") -> None:
        """Merge fork back to parent.

        The LLM generates a summary of what was accomplished in the fork.
        Optional prompt guides the summary generation.
        After merge:
        - Fork becomes read-only
        - View switches to parent
        - Merge marker appears in parent with LLM summary
        """
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Check we're in a fork
        if not self.session.is_fork():
            status_bar.set_error("Not in a fork - use :new for blank session")
            return

        # Check not already merged
        if self.session.is_merged():
            status_bar.set_error("This fork is already merged")
            return

        # Load parent
        parent = self.session.get_parent()
        if not parent:
            status_bar.set_error("Parent session not found")
            return

        # Generate merge summary via LLM
        status_bar.set_status("Generating merge summary...", animate=True)
        self.refresh()
        await asyncio.sleep(0)
        merge_message = await self._generate_merge_summary(self.session, prompt)

        # Track merge point in parent
        merge_point = len(parent.messages)

        # Mark fork as merged
        self.session.mark_merged(merge_message, merge_point)
        self.session.save()

        # Update parent's child record
        parent.mark_child_merged(self.session.id, merge_point)
        parent.save()

        fork_id = self.session.id
        fork_name = self.session.get_fork_display_name()

        # Switch to parent
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
        self._manager._sessions[parent.id] = parent
        self._manager._runners[parent.id] = self._create_session_runner(parent)
        self._manager.set_active(parent.id)
        chat_log.clear()
        chat_log.load_history(parent.messages, session=parent)
        context_tree.load_all_sessions(parent)
        breadcrumb.set_session(parent)

        # Note: merge marker is reconstructed by load_history from parent.children

        status_bar.set_status(f"Merged from '{fork_name}'", animate=False)

    async def _handle_derive_command(self, prompt: str) -> None:
        """Create a new independent session with selected context.

        Like fork but no parent relationship - won't merge back.
        Context is built with summaries inserted at their original positions,
        preserving message order and interleaving.

        If COMPRESS messages exist, shows the compression streaming in the UI
        before creating the derived session. This avoids UI blocking.
        """
        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)
        tool_bar = self.query_one("#tool-bar", ToolBar)

        # Get selected messages with their original indices
        indexed_messages = context_tree.get_selected_messages_with_indices()
        allowed_tools = tool_bar.get_enabled_tools()

        # Separate COPY and COMPRESS messages
        copy_items = []  # (msg, idx)
        compress_items = []  # (msg, idx)

        for msg, idx in indexed_messages:
            if msg.context_mode == ContextMode.COPY:
                copy_items.append((msg, idx))
            elif msg.context_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
                compress_items.append((msg, idx))

        # Group contiguous COMPRESS messages
        compress_groups = []
        if compress_items:
            compress_items.sort(key=lambda x: x[1])
            current_group = [compress_items[0]]

            for i in range(1, len(compress_items)):
                msg, idx = compress_items[i]
                _, prev_idx = current_group[-1]

                copy_indices = {i for _, i in copy_items}
                has_copy_between = any(prev_idx < ci < idx for ci in copy_indices)

                if has_copy_between:
                    compress_groups.append(current_group)
                    current_group = [(msg, idx)]
                else:
                    current_group.append((msg, idx))

            compress_groups.append(current_group)

        # Create new independent session (no parent_id)
        new_session = Session()

        if not compress_groups:
            # No compression needed - proceed immediately
            copy_items.sort(key=lambda x: x[1])
            for msg, _ in copy_items:
                new_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

            new_session.save()

            # Register and switch to new session
            breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
            self._manager._sessions[new_session.id] = new_session
            self._manager._runners[new_session.id] = self._create_session_runner(new_session)
            self._manager.set_active(new_session.id)

            chat_log.clear()
            chat_log.load_history(new_session.messages, session=new_session)
            context_tree.load_all_sessions(new_session)
            breadcrumb.set_session(new_session)

            self._start_streaming(prompt)
        else:
            # Compression needed - start helper streaming
            group = compress_groups[0]
            group_messages = [msg for msg, _ in group]
            first_idx = group[0][1]

            summary_prompt = self._context_builder.build_context_summary_prompt(group_messages)

            import uuid
            helper_id = f"derive-compress-{uuid.uuid4().hex[:8]}"
            helper_runner = HelperRunner(helper_id, runner=create_runner(self._backend_config))
            self._helper_runners[helper_id] = helper_runner

            ctx = StreamingContext(
                session_id=helper_id,
                user_turn_idx=-1,
                assistant_turn_idx=-1,
                prompt="",
                is_active=True,
                is_helper=True,
                helper_type="derive",
                fork_data={
                    "new_session": new_session,
                    "prompt": prompt,
                    "allowed_tools": allowed_tools,
                    "copy_items": copy_items,
                    "compress_group_positions": [first_idx],
                },
            )
            self._streaming_contexts[helper_id] = ctx

            input_box.set_disabled(True)
            status_bar.set_streaming(True)
            self.streaming = True

            chat_log.add_user_message("[Compressing context for new session...]")
            chat_log.add_assistant_message()

            helper_runner.start_background(summary_prompt)

    def _handle_switch_command(self, name: str = "") -> None:
        """Switch view to a different session or fork.

        Args:
            name: Fork name or session ID prefix. Empty shows picker.
        """
        status_bar = self.query_one("#status-bar", StatusBar)

        if not name:
            # TODO: Show picker UI
            # For now, list available forks
            forks = self.session.get_all_forks()
            if forks:
                fork_list = ", ".join(
                    f.get("name") or f.get("session_id", "")[:8]
                    for f in forks
                )
                status_bar.set_status(f"Forks: {fork_list}", animate=False)
            else:
                status_bar.set_status("No forks in current session", animate=False)
            return

        # Find matching fork by name or ID prefix
        target_session = None

        # First check current session's forks
        for fork in self.session.get_all_forks():
            fork_name = fork.get("name", "")
            fork_id = fork.get("session_id", "")
            if fork_name == name or fork_id.startswith(name):
                target_session = Session.load(fork_id)
                break

        # If not found and we're in a fork, check parent's forks
        if not target_session and self.session.is_fork():
            parent = self.session.get_parent()
            if parent:
                for fork in parent.get_all_forks():
                    fork_name = fork.get("name", "")
                    fork_id = fork.get("session_id", "")
                    if fork_name == name or fork_id.startswith(name):
                        target_session = Session.load(fork_id)
                        break

        # Also check if it's a request to go to parent
        if not target_session and name in ("parent", ".."):
            if self.session.is_fork():
                target_session = self.session.get_parent()

        if target_session:
            self._switch_to_session(target_session)
        else:
            status_bar.set_error(f"No fork found matching '{name}'")

    # ===== END NEW COMMANDS =====

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
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
        self._manager._sessions[parent.id] = parent
        self._manager._runners[parent.id] = self._create_session_runner(parent)
        self._manager.set_active(parent.id)
        chat_log.clear()
        chat_log.load_history(parent.messages, session=parent)
        context_tree.load_all_sessions(parent)
        breadcrumb.set_session(parent)

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
        child_session = Session.load(event.child_session_id)
        if child_session:
            self._switch_to_session(child_session)

    def on_with_result_widget_child_clicked(self, event: WithResultWidget.ChildClicked) -> None:
        """Handle clicking on WithResultWidget to navigate to child session."""
        child_session = Session.load(event.child_session_id)
        if child_session:
            self._switch_to_session(child_session)

    def on_fork_marker_child_clicked(self, event: ForkMarker.ChildClicked) -> None:
        """Handle clicking on ForkMarker to navigate to the fork."""
        child_session = Session.load(event.child_session_id)
        if child_session:
            self._switch_to_session(child_session)

    def on_link_marker_linked_session_clicked(self, event: LinkMarker.LinkedSessionClicked) -> None:
        """Handle clicking on LinkMarker to navigate to the linked session."""
        linked_session = Session.load(event.linked_session_id)
        if linked_session:
            self._switch_to_session(linked_session)
            # TODO: Could scroll to the link_point turn in the target session

    def on_merge_marker_child_clicked(self, event: MergeMarker.ChildClicked) -> None:
        """Handle clicking on MergeMarker to navigate to the (read-only) fork."""
        child_session = Session.load(event.child_session_id)
        if child_session:
            self._switch_to_session(child_session)

    def _switch_to_session(self, session: Session, target_turn_index: int | None = None) -> None:
        """Switch to a different session.

        Supports switching while other sessions stream in background:
        - Marks old session's streaming context as inactive (continues streaming)
        - If new session is streaming, resumes display and marks it active
        - Updates input/status based on whether NEW session is streaming

        Args:
            session: The session to switch to
            target_turn_index: Optional turn index to scroll to (0-based)
        """
        old_session_id = self._manager._active_session_id
        debug_log.info(
            f"Switching session: {old_session_id[:8] if old_session_id else 'none'}... → {session.id[:8]}...",
            category="session",
            session_id=session.id,
            details={
                "from_session": old_session_id,
                "to_session": session.id,
                "title": session.title or "(untitled)",
                "messages": len(session.messages),
            },
        )

        chat_log = self.query_one("#chat-log", ChatLog)
        context_tree = self.query_one("#context-tree", ContextTree)
        request_pane = self.query_one("#request-pane", RequestPane)
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Mark OLD session's streaming context as inactive (if streaming)
        if old_session_id:
            old_ctx = self._streaming_contexts.get(old_session_id)
            if old_ctx:
                old_ctx.is_active = False
                debug_log.info(
                    f"Backgrounding streaming session {old_session_id[:8]}",
                    category="stream",
                    session_id=old_session_id,
                )

        # Register session with manager if not already known
        if session.id not in self._manager._sessions:
            self._manager._sessions[session.id] = session
            self._manager._runners[session.id] = self._create_session_runner(session)
        self._manager.set_active(session.id)
        context_tree.set_active_session(session.id)

        # Update breadcrumb to show current position in hierarchy
        breadcrumb.set_session(session)

        # Load session messages and filter by selection
        chat_log.clear()
        chat_log.load_history(session.messages, session=session)

        # Check if NEW session is currently streaming
        new_ctx = self._streaming_contexts.get(session.id)
        if new_ctx:
            # Resume streaming display for this session
            new_ctx.is_active = True
            self.streaming = True
            input_box.set_disabled(True)
            status_bar.set_streaming(True)
            debug_log.info(
                f"Resuming streaming session {session.id[:8]} with {len(new_ctx.content)} chars, {len(new_ctx.tool_events)} tools",
                category="stream",
                session_id=session.id,
            )
            # Resume the streaming display with user prompt, tool events, and accumulated content
            # For query_with, don't show user message (it's ephemeral)
            user_prompt = "" if new_ctx.query_with else new_ctx.prompt
            chat_log.resume_streaming(
                user_prompt,
                new_ctx.content,
                tool_events=new_ctx.tool_events,
                format_tool_use_fn=self._format_tool_use_for_resume,
                format_tool_result_fn=self._format_tool_result_for_resume,
            )
        else:
            # New session is not streaming - enable input
            self.streaming = False
            input_box.set_disabled(False)
            status_bar.set_streaming(False)

        # Update working directory in status bar
        status_bar.update_working_directory(session.working_directory or "")

        # Update header and request pane with session info
        chat_log.set_session_title(session.title)
        request_pane.show_session_info(
            session.title,
            session.summary,
            session.created,
            session.model,
        )

        # Build turn_modes dict for visual indication
        loaded_data = context_tree._loaded_sessions.get(session.id)
        if loaded_data:
            turn_modes = {}
            for turn in loaded_data["turns"]:
                turn_id = turn["idx"] + 1  # 1-indexed for chat_log
                mode = context_tree._context_modes.get(
                    (session.id, turn["idx"]), ContextMode.DROP
                )
                turn_modes[turn_id] = mode.name
            chat_log.set_turn_context_modes(turn_modes)

        # Update context tokens for the new session
        self._update_context_tokens()

        # Save the new view position
        # Default to last turn if no target specified
        turn_index = target_turn_index
        if turn_index is None and session.messages:
            turn_index = len(session.messages) - 1
        save_last_view(session.id, turn_index)

        # Scroll to target turn if specified
        if target_turn_index is not None and target_turn_index < len(session.messages):
            turn_id = target_turn_index + 1  # 1-indexed for chat_log
            # Use default argument to capture turn_id value (avoid late binding)
            self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))

    def on_context_tree_selection_changed(self, event: ContextTree.SelectionChanged) -> None:
        """Handle tree selection changes - apply visual context mode indicators."""
        chat_log = self.query_one("#chat-log", ChatLog)
        # Use visual indication instead of hiding
        chat_log.set_turn_context_modes(event.turn_modes)
        # Update context tokens when selection changes
        self._update_context_tokens()

    def on_chat_log_context_mode_toggle_requested(self, event: ChatLog.ContextModeToggleRequested) -> None:
        """Handle click on chat widget to toggle its context mode."""
        if not self.session:
            return

        context_tree = self.query_one("#context-tree", ContextTree)
        # Convert 1-indexed turn_id to 0-indexed turn_idx
        turn_idx = event.turn_id - 1
        turn_key = (self.session.id, turn_idx)

        # Cycle through context modes: COPY -> COMPRESS -> DROP -> COPY
        current_mode = context_tree._context_modes.get(turn_key, ContextMode.DROP)
        if current_mode == ContextMode.COPY:
            new_mode = ContextMode.COMPRESS
            context_tree._context_modes[turn_key] = new_mode
        elif current_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            new_mode = ContextMode.DROP
            context_tree._context_modes.pop(turn_key, None)  # DROP
        else:  # DROP
            new_mode = ContextMode.COPY
            context_tree._context_modes[turn_key] = new_mode

        # Persist to session message and save
        if turn_idx < len(self.session.messages):
            self.session.messages[turn_idx].context_mode = new_mode
            self.session.save()

        # Update tree label and trigger SelectionChanged to update chat visuals
        context_tree._update_turn_label(self.session.id, turn_idx)
        context_tree._update_root_label()
        # Update context tokens when mode changes
        self._update_context_tokens()

    def on_context_tree_context_mode_changed(self, event: ContextTree.ContextModeChanged) -> None:
        """Handle context mode change from tree - persist to session."""
        # Use in-memory session if it's the current one, otherwise load from disk
        if self.session and self.session.id == event.session_id:
            session = self.session
        else:
            session = Session.load(event.session_id)

        if session and event.turn_idx < len(session.messages):
            session.messages[event.turn_idx].context_mode = event.new_mode
            session.save()

    def on_context_tree_turn_delete_requested(self, event: ContextTree.TurnDeleteRequested) -> None:
        """Handle turn delete request - show confirmation dialog."""
        status_bar = self.query_one("#status-bar", StatusBar)

        # Use in-memory session if it's the current one, otherwise load from disk
        if self.session and self.session.id == event.session_id:
            session = self.session
        else:
            session = Session.load(event.session_id)

        if not session:
            status_bar.set_error("Session not found")
            return

        # Check if session is read-only (merged fork)
        if session.is_read_only():
            status_bar.set_error("Cannot delete from merged (read-only) session")
            return

        # Get turn preview for dialog
        if event.turn_index < len(session.messages):
            msg = session.messages[event.turn_index]
            role = "User" if msg.role == "user" else "Assistant"
            preview = msg.content[:50] + "..." if len(msg.content) > 50 else msg.content
            preview = preview.replace("\n", " ")
            message = f"{role}: {preview}"
        else:
            message = f"Turn {event.turn_index + 1}"

        # Show confirmation dialog
        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._execute_turn_delete(event.session_id, event.turn_index, session)

        self.push_screen(
            ConfirmDialog("Delete Turn?", message),
            on_confirm,
        )

    def _execute_turn_delete(self, session_id: str, turn_index: int, session: Session) -> None:
        """Execute the turn deletion after confirmation."""
        status_bar = self.query_one("#status-bar", StatusBar)
        context_tree = self.query_one("#context-tree", ContextTree)

        if session.delete_turn(turn_index):
            debug_log.info(
                f"Deleted turn {turn_index} from session {session_id[:8]}",
                session_id=session_id,
                category="event",
                details={"turn_index": turn_index},
            )
            session.save()

            # Efficiently update the tree without reloading everything
            context_tree.remove_turn(session_id, turn_index, updated_session=session)

            # Refresh chat log if this is the current session
            if self.session and self.session.id == session_id:
                chat_log = self.query_one("#chat-log", ChatLog)
                chat_log.clear()
                chat_log.load_history(session.messages, session=session)

            status_bar.set_status(f"Deleted turn {turn_index + 1}", animate=False)
        else:
            status_bar.set_error("Could not delete turn")

    def on_context_tree_sort_order_changed(self, event: ContextTree.SortOrderChanged) -> None:
        """Handle sort order change - persist to config."""
        config = get_config()
        config.session_sort_order = event.sort_order
        config.save()

    def on_context_tree_session_delete_requested(self, event: ContextTree.SessionDeleteRequested) -> None:
        """Handle session delete request - show confirmation dialog."""
        status_bar = self.query_one("#status-bar", StatusBar)

        # Load the session to get info for confirmation
        session = Session.load(event.session_id)
        if not session:
            status_bar.set_error("Session not found")
            return

        is_active = self.session and self.session.id == event.session_id

        # Build confirmation message
        msg_count = len(session.messages)
        if session.title:
            name = session.title[:30] + "..." if len(session.title) > 30 else session.title
        else:
            name = session.id[:8]
        message = f"{name} ({msg_count} messages)"

        # Check for active (non-orphaned) links
        active_links = session.get_active_links()
        if active_links:
            link_count = len(active_links)
            message += f"\n\nThis session has {link_count} active link(s) that will be orphaned."

        # Show confirmation dialog
        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._execute_session_delete(event.session_id, session, is_active)

        self.push_screen(
            ConfirmDialog("Delete Session?", message),
            on_confirm,
        )

    def _execute_session_delete(self, session_id: str, session: Session, was_active: bool) -> None:
        """Execute the session deletion after confirmation."""
        status_bar = self.query_one("#status-bar", StatusBar)
        context_tree = self.query_one("#context-tree", ContextTree)

        # Mark links as orphaned in linked sessions before deletion
        for link in session.get_active_links():
            linked_session = Session.load(link.get("linked_session_id", ""))
            if linked_session:
                linked_session.mark_link_orphaned(link.get("link_id", ""))
                linked_session.save()

        if session.delete():
            debug_log.info(
                f"Deleted session {session_id[:8]}",
                session_id=session_id,
                category="event",
            )

            # Remove from tree
            context_tree.remove_session(session_id)

            # If we deleted the active session, switch to another one
            if was_active:
                # Find another session to switch to
                remaining_sessions = Session.list_sessions()
                if remaining_sessions:
                    # Switch to the first remaining session
                    next_session = Session.load(remaining_sessions[0]["id"])
                    if next_session:
                        self._switch_to_session(next_session)
                else:
                    # No sessions left, create a new one
                    new_session = context_tree.create_new_session()
                    self._switch_to_session(new_session)

            status_bar.set_status(f"Deleted session {session_id[:8]}", animate=False)
        else:
            status_bar.set_error("Could not delete session")

    def on_context_tree_session_activated(self, event: ContextTree.SessionActivated) -> None:
        """Handle clicking on a session - switch to it."""
        # Switch to this session (works even while other sessions stream)
        self._switch_to_session(event.session)

    def on_context_tree_session_link_requested(self, event: ContextTree.SessionLinkRequested) -> None:
        """Handle ctrl+click on a session - populate or append to link command."""
        import re

        # Don't allow linking to the current session
        if self.session and event.session_id == self.session.id:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.set_error("Cannot link to current session")
            return

        input_box = self.query_one("#input-box", InputBox)
        new_hash = event.session_id[:8]
        current_text = input_box.text

        # Check if there's already a :link= command in the input
        link_match = re.match(r'^:link=([a-f0-9,]+)(\s.*)?$', current_text)

        if link_match:
            # Existing link command - append to the hash list
            existing_hashes = link_match.group(1)
            rest = link_match.group(2) or " "

            # Check if this hash is already in the list
            hash_list = [h.strip() for h in existing_hashes.split(",")]
            if new_hash in hash_list:
                status_bar = self.query_one("#status-bar", StatusBar)
                status_bar.set_error(f"Session {new_hash} already in link list")
                return

            # Append the new hash
            new_hashes = f"{existing_hashes},{new_hash}"
            new_text = f":link={new_hashes}{rest}"
            input_box.clear()
            input_box.insert(new_text)
        else:
            # No existing link command - create new one
            link_cmd = f":link={new_hash} "
            input_box.clear()
            input_box.insert(link_cmd)

        input_box.focus()

    def on_context_tree_turn_inspected(self, event: ContextTree.TurnInspected) -> None:
        """Handle turn inspection - show in request pane and highlight tool uses.

        If the turn belongs to a different session, switch to that session first.
        All turns are now always visible (with visual context mode indication),
        so we just need to scroll to and highlight the inspected turn.
        """
        request_pane = self.query_one("#request-pane", RequestPane)
        chat_log = self.query_one("#chat-log", ChatLog)

        # Handle different node types
        node_type = event.turn_data.get("type")
        turn_idx = event.turn_data.get("turn_idx", 0) if node_type == "turn" else None

        # Check if we need to switch sessions
        turn_session_id = event.session_id
        if turn_session_id and turn_session_id != self.session.id:
            # Switch to the turn's session first
            target_session = Session.load(turn_session_id)
            if target_session:
                self._switch_to_session(target_session, target_turn_index=turn_idx)

        if node_type == "summary":
            request_pane.show_session_info(
                event.turn_data.get("title", ""),
                event.turn_data.get("summary", ""),
                "",  # No created date for this view
                "",  # No model for this view
            )
            chat_log.clear_highlights()
        elif node_type == "turn":
            # Whole turn inspection - scroll to it and show in request pane
            turn_id = turn_idx + 1
            # Scroll to turn and disable follow mode if not at bottom
            chat_log.scroll_to_turn(turn_id)
            chat_log.clear_highlights()
            request_pane.show_json(event.turn_data)
            # Save last view position
            save_last_view(self.session.id, turn_idx)
        elif node_type == "text":
            # Highlight the text block in the chat log
            # turn_idx is 0-indexed but turn_id is 1-indexed
            turn_id = event.turn_data.get("turn_idx", 0) + 1
            block_idx = event.turn_data.get("block_idx", -1)
            chat_log.highlight_text_block(turn_id, block_idx)
            request_pane.show_json(event.turn_data)
        elif node_type == "tool_use":
            # Highlight the tool use in the chat log
            tool_use_id = event.turn_data.get("tool_use_id", "")
            if tool_use_id:
                chat_log.highlight_tool(tool_use_id)
            request_pane.show_json(event.turn_data)
        elif node_type == "tool_result":
            # Highlight the tool result and its parent tool use
            tool_use_id = event.turn_data.get("tool_use_id", "")
            if tool_use_id:
                chat_log.highlight_tool(tool_use_id)
            request_pane.show_json(event.turn_data)
        elif node_type == "merge":
            # Scroll to merge marker in chat and show in request pane
            child_session_id = event.turn_data.get("session_id", "")
            if child_session_id:
                chat_log.scroll_to_merge_marker(child_session_id)
            chat_log.clear_highlights()
            request_pane.show_json(event.turn_data)
        else:
            chat_log.clear_highlights()
            request_pane.show_json(event.turn_data)

    # --- NestedSessionTree Event Handlers ---
    # These mirror the ContextTree handlers since both trees emit the same message types

    def on_nested_session_tree_selection_changed(self, event: NestedSessionTree.SelectionChanged) -> None:
        """Handle nested tree selection changes - apply visual context mode indicators."""
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.set_turn_context_modes(event.turn_modes)
        # Update context tokens when selection changes
        self._update_context_tokens()

    def on_nested_session_tree_context_mode_changed(self, event: NestedSessionTree.ContextModeChanged) -> None:
        """Handle context mode change from nested tree - persist to session."""
        # Also update ContextTree's local state to keep them in sync
        context_tree = self.query_one("#context-tree", ContextTree)
        turn_key = (event.session_id, event.turn_idx)
        if event.new_mode == ContextMode.DROP:
            context_tree._context_modes.pop(turn_key, None)
        else:
            context_tree._context_modes[turn_key] = event.new_mode
        context_tree._update_turn_label(event.session_id, event.turn_idx)
        context_tree._update_root_label()

        # Persist to session
        if self.session and self.session.id == event.session_id:
            session = self.session
        else:
            session = Session.load(event.session_id)

        if session and event.turn_idx < len(session.messages):
            session.messages[event.turn_idx].context_mode = event.new_mode
            session.save()

        # Update context tokens when mode changes
        self._update_context_tokens()

    def on_nested_session_tree_session_activated(self, event: NestedSessionTree.SessionActivated) -> None:
        """Handle clicking on a session in nested tree - switch to it."""
        self._switch_to_session(event.session)

    def on_nested_session_tree_turn_inspected(self, event: NestedSessionTree.TurnInspected) -> None:
        """Handle turn inspection from nested tree."""
        request_pane = self.query_one("#request-pane", RequestPane)
        chat_log = self.query_one("#chat-log", ChatLog)

        node_type = event.turn_data.get("type")
        turn_idx = event.turn_data.get("turn_idx", 0) if node_type == "turn" else None

        # Check if we need to switch sessions
        turn_session_id = event.session_id
        if turn_session_id and self.session and turn_session_id != self.session.id:
            target_session = Session.load(turn_session_id)
            if target_session:
                self._switch_to_session(target_session, target_turn_index=turn_idx)
                # Return early - _switch_to_session handles scrolling
                if node_type == "turn":
                    chat_log.clear_highlights()
                    request_pane.show_json(event.turn_data)
                else:
                    chat_log.clear_highlights()
                    request_pane.show_json(event.turn_data)
                return

        if node_type == "turn":
            turn_id = turn_idx + 1
            chat_log.scroll_to_turn(turn_id)
            chat_log.clear_highlights()
            request_pane.show_json(event.turn_data)
            # Save last view position
            save_last_view(self.session.id, turn_idx)
        else:
            chat_log.clear_highlights()
            request_pane.show_json(event.turn_data)

    def on_nested_session_tree_turn_delete_requested(self, event: NestedSessionTree.TurnDeleteRequested) -> None:
        """Handle turn delete request from nested tree."""
        # Reuse the ContextTree handler logic
        context_tree_event = ContextTree.TurnDeleteRequested(event.session_id, event.turn_index)
        self.on_context_tree_turn_delete_requested(context_tree_event)

    def on_nested_session_tree_session_delete_requested(self, event: NestedSessionTree.SessionDeleteRequested) -> None:
        """Handle session delete request from nested tree."""
        # Reuse the ContextTree handler logic
        context_tree_event = ContextTree.SessionDeleteRequested(event.session_id)
        self.on_context_tree_session_delete_requested(context_tree_event)

    def on_nested_session_tree_session_link_requested(self, event: NestedSessionTree.SessionLinkRequested) -> None:
        """Handle ctrl+click link request from nested tree."""
        # Reuse the ContextTree handler logic
        context_tree_event = ContextTree.SessionLinkRequested(event.session_id)
        self.on_context_tree_session_link_requested(context_tree_event)

    def on_breadcrumb_segment_clicked(self, event: Breadcrumb.SegmentClicked) -> None:
        """Handle clicking a breadcrumb segment to navigate up."""
        target_session = Session.load(event.session_id)
        if target_session:
            self._switch_to_session(target_session)

    def action_new_session(self) -> None:
        """Create a new session from anywhere (ctrl+space)."""
        def handle_result(result: NewSessionResult | None) -> None:
            if result is not None:
                asyncio.create_task(self._create_session_from_modal(result))

        self.push_screen(NewSessionModal(), handle_result)

    async def _create_session_from_modal(self, result: NewSessionResult) -> None:
        """Handle the result from NewSessionModal."""
        # Create the session with optional title
        await self._handle_new_session(result.prompt)

        # Set title if provided
        if result.title:
            self.session.title = result.title
            self.session.save()
            # Update UI
            context_tree = self.query_one("#context-tree", ContextTree)
            context_tree.load_all_sessions(self.session)
            breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
            breadcrumb.set_session(self.session)

    def action_toggle_tree(self) -> None:
        """Toggle the tree sidebar visibility."""
        context_tree = self.query_one("#context-tree", ContextTree)
        nested_tree = self.query_one("#nested-tree", NestedSessionTree)
        splitter = self.query_one("#splitter", VerticalSplitter)

        # If either tree is visible, hide both; otherwise show the active one
        either_visible = context_tree.display or nested_tree.display
        if either_visible:
            context_tree.display = False
            nested_tree.display = False
            splitter.display = False
        else:
            # Show whichever was last active (context_tree by default)
            if getattr(self, "_nested_tree_active", False):
                nested_tree.display = True
            else:
                context_tree.display = True
            splitter.display = True

    def action_switch_tree_view(self) -> None:
        """Switch between flat (ContextTree) and nested (NestedSessionTree) views."""
        context_tree = self.query_one("#context-tree", ContextTree)
        nested_tree = self.query_one("#nested-tree", NestedSessionTree)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Toggle which tree is active
        if context_tree.display:
            context_tree.display = False
            nested_tree.display = True
            self._nested_tree_active = True
        elif nested_tree.display:
            nested_tree.display = False
            context_tree.display = True
            self._nested_tree_active = False
        else:
            # Neither visible - show the opposite of what was last active
            if getattr(self, "_nested_tree_active", False):
                context_tree.display = True
                self._nested_tree_active = False
            else:
                nested_tree.display = True
                self._nested_tree_active = True
            self.query_one("#splitter", VerticalSplitter).display = True

    def action_toggle_requests(self) -> None:
        """Toggle the request pane visibility."""
        pane = self.query_one("#request-pane", RequestPane)
        pane.display = not pane.display

    def action_toggle_debug(self) -> None:
        """Toggle the debug pane visibility."""
        pane = self.query_one("#debug-pane", DebugPane)
        pane.toggle()

    def action_show_help(self) -> None:
        """Show the help modal."""
        self.push_screen(HelpModal())

    def action_resize_tree(self, delta: int) -> None:
        """Resize the active tree by delta columns."""
        self._tree_width = max(20, min(100, self._tree_width + delta))
        context_tree = self.query_one("#context-tree", ContextTree)
        nested_tree = self.query_one("#nested-tree", NestedSessionTree)
        context_tree.styles.width = self._tree_width
        nested_tree.styles.width = self._tree_width

    def on_vertical_splitter_resized(self, event: VerticalSplitter.Resized) -> None:
        """Handle splitter drag."""
        self.action_resize_tree(event.delta_x)

    def on_chat_log_following_changed(self, event: ChatLog.FollowingChanged) -> None:
        """Update status bar and more-below indicator when chat log following state changes."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.following = event.following
        indicator = self.query_one("#more-below", MoreBelowIndicator)
        if event.following:
            # Hide indicator when following (at bottom)
            indicator.hide()
        else:
            # Show indicator when not following (content below)
            indicator.show_more_below()

    def on_chat_log_new_content_while_not_following(self, event: ChatLog.NewContentWhileNotFollowing) -> None:
        """Show new messages indicator when content arrives while not following."""
        indicator = self.query_one("#more-below", MoreBelowIndicator)
        indicator.show_new_messages()

    def on_status_bar_follow_clicked(self, event: StatusBar.FollowClicked) -> None:
        """Handle click on Follow indicator - scroll to bottom."""
        self.action_scroll_to_bottom()

    def on_more_below_indicator_clicked(self, event: MoreBelowIndicator.Clicked) -> None:
        """Handle click on more-below indicator - scroll to bottom."""
        self.action_scroll_to_bottom()

    def action_scroll_to_bottom(self) -> None:
        """Scroll to bottom of chat and re-enable following."""
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.following = True
        chat_log.scroll_end(animate=False)
        # Hide the more-below indicator
        indicator = self.query_one("#more-below", MoreBelowIndicator)
        indicator.hide()

    def action_quit(self) -> None:
        """Quit the application."""
        # Cancel all streaming sessions
        self._manager.cancel_all()
        # Stop polling timer
        if self._poll_timer:
            self._poll_timer.stop()
        self.exit()
