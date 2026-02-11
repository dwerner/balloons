import asyncio
import logging
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import TextArea, Button

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
from widgets import ChatLogView, MoreBelowIndicator, InputBox, StatusBar, ContextTreeView, NestedTreeView, GoalTreeView, VerticalSplitter, HorizontalSplitter, TaskPane, WithWidget, WithResultWidget, DebugPane, ForkMarker, MergeMarker, LinkMarker, ReviewMarker, ForkProposalMarker, MergeProposalMarker, Breadcrumb, ConfirmDialog, HelpModal, NewSessionModal, NewSessionResult, PreferencesModal, ToolPreferences, DEFAULT_TOOLS, ForkProposalModal, ForkProposalResult, MergeProposalModal, MergeProposalResult, MessageStash, StashPopup, SlidesPane, PresentationScreen, MessageQueuePopup, EntityPane, ActionableToastRack, ActionableNotification, ActionableToast
from widgets.input_box import CompletionPopup
from widgets.archive_marker import ArchiveMarker
from claude_runner import ClaudeRunner
from session import Session
from config import get_config, BackendConfig, save_last_view
from models import (
    TextDelta, ToolUseEvent, ToolResultEvent,
    TextBlock, ToolUseBlock, ToolResultBlock, InterruptionBlock, ErrorBlock, Message, ContextMode,
    ArchiveBlock, ContextAssignmentData, ForkBindingData, ExchangeInfo,
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
    ReturnCommand,
    PwdCommand,
    CdCommand,
    ReloadCommand,
    TitleCommand,
    HelpCommand,
    BackendCommand,
    PrefsCommand,
    EditConfigCommand,
    EditPromptCommand,
    LinkCommand,
    DebugToggleCommand,
    DebugClearCommand,
    DebugPauseCommand,
    ArchiveCommand,
    RehydrateCommand,
    ReindexCommand,
    FollowCommand,
    StashCommand,
    PopCommand,
    ClearAllSessionsCommand,
    SnapCommand,
    NewSlideCommand,
    PresentCommand,
    SlidesCommand,
    ChatCommand,
    ReviewCommand,
    # Goal-oriented task management commands
    GoalInterviewCommand,
    GoalsCommand,
    PlansCommand,
    TodosCommand,
    TodoDoneCommand,
    BindCommand,
    UnbindCommand,
    debug_log,
    create_runner,
    ensure_prompts_installed,
    register_app_tool_handler,
    unregister_app_tool_handler,
    # Streaming
    StreamingContext,
    StreamingCoordinator,
    TextAction,
    TextFlushAction,
    InitAction,
    ResultAction,
    ToolUseStartAction,
    ToolInputDeltaAction,
    ToolUseCompleteAction,
    ToolResultAction,
    DoneAction,
    ErrorAction,
    RateLimitAction,
    CancelledAction,
    InputRequiredAction,
    HelperDoneAction,
    NoAction,
    TurnStartedAction,
    # Helper data types
    ArchiveData,
    MergeData,
    LinkData,
    ReturnData,
)
from core.summarizer import Summarizer
from core.exceptions import BackendNotFoundError
from core.context_grouper import group_messages_by_context_mode, build_context_messages
from core.fork import ForkManager, ForkResult, MergeResult, DeriveResult, SwitchResult, ForkProposal, MergeProposal, ForkData, DeriveData, ForkBindingSpec
from core.command_executor import CommandExecutor, ArchiveResult, RehydrateResult, LinkResult, BackendResult, ShellResult
from core.goal_commands import GoalCommandExecutor, check_priority_divergence, get_session_binding_indicator
from core.tool_executor import parse_fork_proposal, parse_merge_proposal
from core.tree_state import TreeState, TreeEvent
from core.goal_tree_state import GoalTreeState
from core.goal_tree_sync import GoalTreeSyncManager
from core.goal_tools import GOAL_MUTATION_TOOLS
from core.task_state import get_task_state, TaskStatus
from core.sounds import play_error_sound, play_done_sound, play_notification_sound
from core.queue_state import get_queue_state, QueueState, QueueEvent, QueueSnapshot
from tokenizer import count_tokens


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

    ContextTreeView {
        width: 50;
    }

    NestedTreeView {
        width: 50;
        display: none;
    }

    GoalTreeView {
        width: 50;
        display: none;
    }

    #chat-container {
        height: 1fr;
    }

    #content-tabs {
        dock: top;
        height: auto;
        width: 100%;
        background: $surface;
        border-bottom: solid $primary-darken-2;
        padding: 0 1;
    }

    #content-tabs Button {
        min-width: 12;
        margin: 0 1 0 0;
        border: none;
        background: transparent;
    }

    #content-tabs Button:hover {
        background: $primary-darken-3;
    }

    #content-tabs Button.active {
        background: $primary-darken-2;
        text-style: bold;
    }

    #content-area {
        height: 1fr;
    }

    #slides-pane {
        display: none;
    }

    #slides-pane.visible {
        display: block;
    }

    #chat-log.hidden {
        display: none;
    }

    ChatLogView {
        height: 1fr;
    }

    StatusBar {
        height: 1;
        background: $surface;
        color: $text;
    }

    InputBox {
        height: auto;
    }

    HorizontalSplitter {
        dock: bottom;
    }

    #input-area {
        height: auto;
    }

    #completion-popup {
        display: none;
        margin-bottom: 0;
        margin-left: 1;
        width: auto;
        max-width: 40;
    }

    #stash-popup {
        display: none;
        margin-bottom: 0;
        margin-left: 1;
        width: auto;
        max-width: 60;
    }

    #queue-popup {
        dock: bottom;
        height: auto;
        max-height: 10;
        width: 100%;
        margin: 0;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel_stream", "Cancel", show=True),
        # Note: ctrl+c is reserved for copy (text selection) - use ctrl+q to quit
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+space", "new_session", "New Session", show=True),
        Binding("ctrl+t", "toggle_tree", "Toggle Tree", show=True),
        Binding("ctrl+n", "switch_tree_view", "Switch Tree", show=True),
        Binding("ctrl+r", "toggle_tasks", "Toggle Tasks", show=True),
        Binding("ctrl+g", "toggle_debug", "Debug", show=True),
        Binding("ctrl+p", "show_preferences", "Preferences", show=True),
        Binding("ctrl+s", "stash_toggle", "Stash", show=False),
        Binding("ctrl+left", "resize_tree(-5)", "Shrink Tree", show=False),
        Binding("ctrl+right", "resize_tree(5)", "Grow Tree", show=False),
        Binding("ctrl+end", "scroll_to_bottom", "Follow", show=False),
        Binding("f1", "show_help", "Help", show=True),
    ]

    def __init__(self, session: Session = None, backend_config: BackendConfig | None = None):
        super().__init__()
        # Enable file logging if configured (log message deferred to on_mount when event loop is running)
        config = get_config()
        if config.debug_log_file:
            debug_log.set_log_file(config.debug_log_file)
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
        # Shared tree state - used by ContextTreeView and NestedTreeView
        self._tree_state = TreeState()
        # Goal-centric tree state - used by GoalTreeView
        self._goal_tree_state = GoalTreeState()
        self._goal_tree_sync: GoalTreeSyncManager | None = None
        # Shared queue state - event-driven message queue management
        self._queue_state = get_queue_state()
        # Session manager handles all sessions and runners
        # Pass runner factory so manager respects per-session backend preferences
        self._manager = SessionManager(
            backend_config=self._backend_config,
            runner_factory=self._create_session_runner,
        )
        # Simple runner for helper streaming (summaries, etc.) - used for blocking operations
        self._helper_runner = create_runner(self._backend_config)
        # Summarizer for LLM-based summary generation
        self._summarizer = Summarizer(
            self._helper_runner,
            backend_name=self._backend_config.name,
        )
        # Timer for polling background sessions
        self._poll_timer = None
        # Per-session streaming contexts (session_id -> StreamingContext)
        self._streaming_contexts: dict[str, StreamingContext] = {}
        # Helper runners for non-blocking helper tasks (helper_id -> HelperRunner)
        self._helper_runners: dict[str, HelperRunner] = {}
        # Streaming coordinator for dispatching events to actions
        self._streaming_coordinator = StreamingCoordinator()
        # Fork manager for fork/merge/derive operations
        self._fork_manager = ForkManager(self._context_builder)
        # Command executor for archive/link/backend commands
        self._command_executor = CommandExecutor()
        # Tool preferences per backend (backend_name -> ToolPreferences)
        self._tool_preferences: dict[str, ToolPreferences] = {}
        # Debounce timer for context token updates during typing
        self._token_update_timer = None
        self._pending_token_text = ""
        # Message stash for deferred drafts
        self._message_stash = MessageStash()
        # Pending link targets for async link operations
        self._pending_link_targets: list = []
        # Pending fork bindings (fork_name -> ForkBindingSpec or "inherit")
        # Applied when fork creation completes
        self._pending_fork_bindings: dict[str, Any] = {}
        # Pending fork proposals (proposal_id -> proposal data dict)
        # Used to execute proposals when accepted
        self._pending_fork_proposals: dict[str, dict] = {}
        # Pending merge proposals (proposal_id -> proposal data dict)
        self._pending_merge_proposals: dict[str, dict] = {}
        # Suppress context token updates during batch context mode changes
        self._batch_context_mode_changes = False

    @property
    def session(self) -> Session | None:
        """Get the active session from the manager."""
        return self._manager.active_session

    @property
    def _session_runner(self) -> SessionRunner | None:
        """Get the active session's runner from the manager."""
        return self._manager.active_runner

    def _get_backend_for_session(self, session: Session) -> BackendConfig:
        """Get the backend config for a session, respecting session override.

        Raises:
            BackendNotFoundError: If the session specifies a backend that doesn't exist.
        """
        config = get_config()
        if session.backend_name:
            if session.backend_name in config.backends:
                return config.get_backend(session.backend_name)
            else:
                raise BackendNotFoundError(
                    session.backend_name, list(config.backends.keys())
                )
        return self._backend_config

    def _create_session_runner(
        self,
        session: Session,
        backend_config: BackendConfig = None,
        system_prompt: str = None,
    ) -> SessionRunner:
        """Create a runner for a session, respecting session's backend preference.

        If the session specifies a backend that no longer exists, falls back to the
        default backend and clears the invalid backend_name from the session.

        Args:
            session: The session to create a runner for
            backend_config: Optional backend config override (e.g., for review sessions)
            system_prompt: Optional system prompt override (e.g., for review agent)
        """
        if backend_config:
            backend = backend_config
        else:
            try:
                backend = self._get_backend_for_session(session)
            except BackendNotFoundError as e:
                debug_log.info(
                    f"Session backend '{e.backend_name}' not found, using default for runner",
                    category="session",
                    session_id=session.id,
                )
                # Clear invalid backend and use default
                session.backend_name = ""
                asyncio.create_task(session.save())
                backend = self._backend_config

        if system_prompt:
            # Create runner with custom system prompt
            runner = self._create_runner_with_system_prompt(backend, system_prompt)
        else:
            runner = create_runner(backend)

        return SessionRunner(session, runner=runner)

    def _create_runner_with_system_prompt(self, backend: BackendConfig, system_prompt: str):
        """Create a runner with a custom system prompt.

        Used for special runners like the review agent that need their own prompt.
        """
        from core.runner_factory import resolve_env_var

        backend_type = backend.type or "claude"

        if backend_type == "openai":
            from core.openai_runner import OpenAICompatibleRunner

            api_key = resolve_env_var(backend.api_key or "")
            model = backend.model or "default"

            return OpenAICompatibleRunner(
                base_url=backend.base_url,
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                context_window=backend.context_window,
            )
        else:  # claude
            from claude_runner import ClaudeRunner

            # Load Claude-specific tool prompts for XML-style <balloons-tool> calls
            balloons_prompt = ""
            balloons_prompt_path = Path(__file__).parent / "prompts" / "claude-balloons-tools.md"
            if balloons_prompt_path.exists():
                try:
                    balloons_prompt = balloons_prompt_path.read_text()
                except Exception:
                    pass

            full_prompt = f"{system_prompt}\n\n{balloons_prompt}" if balloons_prompt else system_prompt

            env = {}
            if backend.base_url:
                env["ANTHROPIC_BASE_URL"] = backend.base_url
            if backend.api_key:
                env["ANTHROPIC_API_KEY"] = resolve_env_var(backend.api_key)

            return ClaudeRunner(
                backend_env=env if env else None,
                system_prompt=full_prompt,
                context_window=backend.context_window,
            )

    def _update_base_context_tokens(self, use_cache: bool = False) -> None:
        """Calculate and store base context tokens in TreeState.

        Uses the incrementally-updated cached token count from TreeState's SessionData,
        which is maintained by finish_turn() as turns are added. Only falls back to
        expensive full-context tokenization when use_cache=False AND no cached value.

        Args:
            use_cache: If True, always use cached tokens. If False, may recalculate
                       if no cached value exists (e.g., after context mode change).
        """
        selected_tokens = 0
        total_tokens = 0

        if self.session:
            # Get cached tokens from TreeState (updated incrementally during streaming)
            session_data = self._tree_state.get_session(self.session.id)
            if session_data and session_data.cached_context_tokens > 0:
                selected_tokens = session_data.cached_context_tokens
            elif use_cache and self.session.cached_context_tokens > 0:
                # Fall back to session's persisted cache
                selected_tokens = self.session.cached_context_tokens
            elif not use_cache:
                # No cached value and not using cache - do expensive recompute
                # This happens after context mode changes
                try:
                    context_tree = self.query_one("#context-tree", ContextTreeView)
                    selected_messages = context_tree.get_selected_messages()
                    if selected_messages:
                        selected_tokens = self._context_builder.count_messages_tokens(selected_messages)
                except Exception:
                    pass

            # Sync caches
            self.session.cached_context_tokens = selected_tokens
            self._tree_state.update_session_tokens(self.session.id, selected_tokens)

        self._tree_state.set_context_tokens(selected_tokens, total_tokens)

    def _calculate_context_tokens(self, pending_prompt: str = "") -> tuple[int, int]:
        """Calculate estimated context tokens for the next API call.

        Includes:
        - System overhead (Claude's built-in ~19.3k or custom system_prompt)
        - Selected conversation context (from TreeState)
        - Pending user input

        Args:
            pending_prompt: Text currently in the input box

        Returns:
            Tuple of (overhead_tokens, context_tokens) where:
            - overhead_tokens: Fixed system overhead (Claude prompt, custom system prompt)
            - context_tokens: Conversation context + pending input
        """
        backend = self._backend_config
        if self.session and self.session.backend_name:
            config = get_config()
            if self.session.backend_name in config.backends:
                backend = config.get_backend(self.session.backend_name)

        # System overhead
        if backend.type == "claude":
            overhead_tokens = CLAUDE_SYSTEM_OVERHEAD
        else:
            overhead_tokens = 0

        # Add configured system prompt tokens to overhead
        overhead_tokens += backend.get_system_prompt_tokens()

        # Conversation context from TreeState (base tokens calculated elsewhere)
        selected_tokens, _ = self._tree_state.get_context_tokens()

        # Pending input tokens
        input_tokens = count_tokens(pending_prompt) if pending_prompt else 0

        return overhead_tokens, selected_tokens + input_tokens

    def _update_context_tokens(self, pending_prompt: str = "") -> None:
        """Update the status bar with current context token count."""
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            overhead_tokens, context_tokens = self._calculate_context_tokens(pending_prompt)
            status_bar.update_stats(overhead_tokens=overhead_tokens, context_tokens=context_tokens)
        except Exception:
            # UI might not be ready
            pass

    def compose(self) -> ComposeResult:
        config = get_config()
        with Vertical():
            with Horizontal(id="main-split"):
                yield ContextTreeView(
                    tree_state=self._tree_state,
                    id="context-tree"
                )
                yield NestedTreeView(
                    tree_state=self._tree_state,
                    id="nested-tree"
                )
                yield GoalTreeView(
                    goal_state=self._goal_tree_state,
                    tree_state=self._tree_state,
                    id="goal-tree"
                )
                yield VerticalSplitter(id="splitter")
                with Vertical(id="chat-container"):
                    yield Breadcrumb(id="breadcrumb")
                    with Horizontal(id="content-tabs"):
                        yield Button("💬 Chat", id="tab-chat", classes="active")
                        yield Button("📊 Slides", id="tab-slides")
                        yield Button("🗄️ Entities", id="tab-entities")
                    with Vertical(id="content-area"):
                        yield ChatLogView(id="chat-log")
                        yield SlidesPane(id="slides-pane")
                        yield EntityPane(id="entity-pane")
                        yield MessageQueuePopup(id="queue-popup")
                    yield MoreBelowIndicator(id="more-below")
                yield TaskPane(id="task-pane", classes="hidden")
            yield DebugPane(id="debug-pane")
            yield StatusBar(id="status-bar")
            with Vertical(id="input-area"):
                yield HorizontalSplitter(id="input-splitter")
                yield CompletionPopup(id="completion-popup")
                yield StashPopup(id="stash-popup")
                yield InputBox(id="input-box")
            yield ActionableToastRack(id="actionable-toast-rack")

    async def on_mount(self) -> None:
        """Initialize the app after mounting."""
        # Log deferred startup message now that event loop is running
        if debug_log._log_file:
            debug_log.info("Debug logging to file enabled", category="startup")
        # Ensure default prompts are installed to ~/.balloons/prompts/
        ensure_prompts_installed()
        # Subscribe to TreeState for context mode changes
        self._tree_state.add_observer(self._on_tree_state_event)
        # Start the background session polling timer
        self._poll_timer = self.set_interval(0.1, self._poll_background_sessions)
        await self._initialize_session()
        # Register app-level tool handlers
        register_app_tool_handler("screen_snapshot", self._execute_screen_snapshot_tool)

    def on_unmount(self) -> None:
        """Clean up when the app is unmounted."""
        # Unregister app-level tool handlers
        unregister_app_tool_handler("screen_snapshot")

    def _on_tree_state_event(self, event: TreeEvent, data: dict) -> None:
        """Handle state changes from TreeState that affect token counts and UI."""
        if event == TreeEvent.TURN_FINISHED:
            # Turn completed - recalculate tokens for the session
            # SKIP during streaming to avoid blocking UI with expensive tokenization
            session_id = data.get("session_id")
            if session_id == self._tree_state.get_current_session_id():
                # Only update tokens if not actively streaming
                # Token counts will be updated when streaming finishes (DoneAction)
                if not self.streaming:
                    self._update_base_context_tokens()
                    self._update_context_tokens()
                # Update scrollbar markers for unviewed turns
                self._update_unviewed_markers()

        elif event == TreeEvent.TURN_VIEWED:
            # Turn was viewed - update scrollbar markers
            session_id = data.get("session_id")
            if session_id == self._tree_state.get_current_session_id():
                self._update_unviewed_markers()

        elif event == TreeEvent.SESSION_LOADED:
            # Session loaded - update scrollbar markers
            session_id = data.get("session_id")
            if session_id == self._tree_state.get_current_session_id():
                self._update_unviewed_markers()

        elif event == TreeEvent.CONTEXT_MODE_CHANGED:
            # Context mode changed on a turn - recalculate tokens if it's the current session
            # Skip if we're in batch mode (bulk context mode changes like fork proposal)
            if self._batch_context_mode_changes:
                return
            session_id = data.get("session_id")
            if session_id == self._tree_state.get_current_session_id():
                self._update_base_context_tokens()
                self._update_context_tokens()

    def _update_unviewed_markers(self) -> None:
        """Update the chat log scrollbar markers for unviewed turns."""
        try:
            chat_log = self.query_one("#chat-log", ChatLogView)
            current_id = self._tree_state.get_current_session_id()
            if current_id:
                # Get unviewed turn indices (0-indexed) and convert to turn IDs (1-indexed)
                unviewed_indices = self._tree_state.get_unviewed_turns(current_id)
                unviewed_turn_ids = [idx + 1 for idx in unviewed_indices]
                chat_log.set_unviewed_markers(unviewed_turn_ids)
            else:
                chat_log.set_unviewed_markers([])
        except Exception:
            pass  # Chat log may not be mounted yet

    def _update_streaming_count(self) -> None:
        """Update the status bar with total streaming sessions count."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.set_streaming_count(len(self._streaming_contexts))

    def _show_actionable_notification(
        self,
        message: str,
        action: str,
        action_data: dict | None = None,
        action_label: str = "Click to view",
        title: str = "",
        severity: str = "information",
        timeout: float = 8,
    ) -> None:
        """Show an actionable notification that triggers a callback when clicked.

        Args:
            message: The notification message
            action: The action type (e.g., "switch_session")
            action_data: Additional data for the action
            action_label: Label shown indicating clickability
            title: Optional notification title
            severity: One of "information", "warning", "error"
            timeout: How long to show the notification (seconds)
        """
        try:
            toast_rack = self.query_one("#actionable-toast-rack", ActionableToastRack)
            notification = ActionableNotification(
                message=message,
                title=title,
                severity=severity,  # type: ignore
                timeout=timeout,
                action_data={"action": action, **(action_data or {})},
                action_label=action_label,
            )
            toast_rack.add_notification(notification)
        except Exception:
            # Fall back to regular notification if actionable toast fails
            self.notify(message, title=title, severity=severity)  # type: ignore

    def _update_queue_indicator(self) -> None:
        """Update the input box to show queue status.

        The popup auto-updates via QueueState observer, so we only
        need to update the input box border here.
        """
        if not self.session:
            return
        input_box = self.query_one("#input-box", InputBox)
        queue_len = self._queue_state.get_message_count(self.session.id)

        # Update input box border title
        # During streaming: show QUEUE mode with count
        if queue_len > 0 and self.streaming:
            input_box.border_title = f"[QUEUE] {queue_len} pending"
        elif queue_len > 0:
            # Not streaming but have queued items
            input_box.border_title = f"{queue_len} queued"
        elif self.streaming:
            input_box.border_title = "[QUEUE]"
        else:
            input_box.border_title = ""

    def _process_message_queue(self) -> None:
        """Process queued messages after streaming completes.

        Drains messages until a paused one is reached, combining them
        into a single prompt with newline separators.
        """
        if not self.session:
            return

        session_id = self.session.id

        # Check if queue is blocked (first message is paused)
        if self._queue_state.is_blocked(session_id):
            debug_log.info(
                "Queue is blocked - first message is paused",
                category="queue",
                session_id=session_id,
            )
            return

        # Drain all non-paused messages
        messages = self._queue_state.drain(session_id)
        if not messages:
            return

        # Update queue indicator (may still have items if we stopped at paused)
        self._update_queue_indicator()

        # Combine all messages with double-newline separator
        combined_prompt = "\n\n".join(messages)

        debug_log.info(
            f"Processing {len(messages)} queued messages as single prompt ({len(combined_prompt)} chars)",
            category="queue",
            session_id=session_id,
        )
        # Start streaming the combined prompt
        self._start_streaming(combined_prompt)

    def _poll_background_sessions(self) -> None:
        """Poll ALL streaming sessions for events and update UI.

        This is the core of the event-driven architecture:
        - All sessions stream in background mode
        - This timer polls for events from all sessions
        - Events are dispatched to appropriate UI components
        """
        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
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
        chat_log: ChatLogView,
        context_tree: ContextTreeView,
        status_bar: StatusBar,
    ) -> None:
        """Dispatch a polled event to appropriate UI components.

        Uses StreamingCoordinator to convert events to actions, then handles
        the actions with UI-specific code.
        """
        # Get action from coordinator (also updates ctx state)
        action = self._streaming_coordinator.dispatch_event(event, ctx)
        is_active = ctx.is_active

        # Log events for debugging
        if event.event_type == "turn_started":
            debug_event(f"turn_started: session={session_id[:8]} turn={event.data.get('turn_index')}")
        elif event.event_type in ("text", "tool_use_start", "tool_use", "tool_result", "done", "error", "rate_limit", "cancelled", "input_required"):
            debug_event(f"{event.event_type}: session={session_id[:8]}")

        # Handle action based on type
        self._handle_streaming_action(action, ctx, chat_log, context_tree, status_bar)

    def _handle_streaming_action(
        self,
        action,
        ctx: StreamingContext,
        chat_log: ChatLogView,
        context_tree: ContextTreeView,
        status_bar: StatusBar,
    ) -> None:
        """Handle a streaming action by updating UI components.

        This method contains all the UI-specific code for handling streaming actions.
        """
        session_id = action.session_id
        is_active = ctx.is_active

        if isinstance(action, NoAction):
            pass  # Nothing to do

        elif isinstance(action, TextAction):
            # Update tree with streaming text
            context_tree.update_streaming_text(
                session_id,
                ctx.assistant_turn_idx,
                action.text,
            )

            # Track accumulated content for token estimation
            ctx.content += action.text

            # Update task state with approximate token count (rough estimate: 4 chars per token)
            approx_tokens = len(ctx.content) // 4
            get_task_state().update_task(ctx.exchange_id, tokens_streamed=approx_tokens)

            if is_active:
                chat_log.append_to_current(action.text)
            else:
                # Update WithWidget for background session
                with_widget = chat_log.find_with_widget(session_id)
                if with_widget:
                    with_widget.update_streaming(action.text)

        elif isinstance(action, TextFlushAction):
            # Text segment complete before tool use - commit as visible node in tree
            # and finish the turn so it displays correctly
            context_tree.flush_streaming_text(
                session_id,
                action.turn_idx,
                action.text,
            )
            # Finish the text turn with proper content_block
            content_block = TextBlock(text=action.text)
            context_tree.finish_turn(
                session_id, action.turn_idx, action.text, content_block, []
            )

        elif isinstance(action, TurnStartedAction):
            # New turn started during streaming (text_turn, tool_use, or tool_result)
            # Create a new turn node in the context tree with turn_type info
            # so labels display correctly during streaming (not just after finish_turn)
            context_tree.start_turn(
                session_id,
                action.turn_idx,
                action.role,
                exchange_id=action.exchange_id,
                turn_type=action.turn_type,
                tool_name=action.tool_name,
                tool_use_id=action.tool_use_id,
                result_preview=action.result_preview,
            )
            # Track (tool_use_id, turn_type) -> turn_idx mapping for finish_turn calls
            # We need the turn_type in the key because tool_use and tool_result share the same tool_use_id
            if action.tool_use_id and action.turn_type in ("tool_use", "tool_result"):
                ctx.tool_turn_indices[(action.tool_use_id, action.turn_type)] = action.turn_idx
            if action.turn_type == "tool_use":
                debug_log.debug(
                    f"Tool use turn started: {action.tool_name}",
                    session_id=session_id,
                    category="stream",
                )
            elif action.turn_type == "tool_result":
                debug_log.debug(
                    f"Tool result turn started",
                    session_id=session_id,
                    category="stream",
                )

        elif isinstance(action, InitAction):
            # Update task with model info
            get_task_state().update_task(
                ctx.exchange_id,
                model=action.model,
                context_window=action.context_window,
            )
            if is_active:
                status_bar.update_stats(
                    model=action.model,
                    context_window=action.context_window,
                )

        elif isinstance(action, ResultAction):
            # Update task with actual token counts
            get_task_state().update_task(
                ctx.exchange_id,
                input_tokens=action.input_tokens,
                output_tokens=action.output_tokens,
            )
            if is_active:
                # Get session from manager for cost tracking
                session = self._manager._sessions.get(session_id)
                if session:
                    status_bar.update_stats(cost=session.total_cost)
                # Update context tokens to show cumulative context for NEXT request
                # (includes the response that was just added)
                self._update_base_context_tokens()
                self._update_context_tokens()

        elif isinstance(action, ToolUseStartAction):
            # Note: Tree node is created by TurnStartedAction (tool_use_turn_started event)
            # This action only updates the chat log streaming widget

            # Track tool count for task state
            ctx.tool_count = getattr(ctx, 'tool_count', 0) + 1
            get_task_state().update_task(
                ctx.exchange_id,
                status=TaskStatus.EXECUTING,
                tool_name=action.tool_name,
                tool_count=ctx.tool_count,
            )

            if is_active:
                # Add streaming tool widget
                chat_log.add_streaming_tool_use(action.tool_name, action.tool_use_id)

        elif isinstance(action, ToolInputDeltaAction):
            # Note: Tree node is created by TurnStartedAction (tool_use_turn_started event)
            # This action only updates the chat log streaming widget

            if is_active:
                # Update streaming tool widget
                chat_log.update_streaming_tool(action.tool_use_id, action.partial_json)

        elif isinstance(action, ToolUseCompleteAction):
            # Finalize the tool_use turn with real content_block and token count
            turn_idx = ctx.tool_turn_indices.get((action.tool_use_id, "tool_use"))
            if turn_idx is not None:
                content_block = ToolUseBlock(
                    id=action.tool_use_id,
                    name=action.tool_name,
                    input=action.tool_input,
                )
                # content param not used for tool turns - label uses content_block
                context_tree.finish_turn(
                    session_id, turn_idx, "", content_block, []
                )

            # Intercept propose_fork tool - show modal before execution
            # Only handle balloons-tool calls (id starts with "balloons-"), not native CLI tools
            if action.tool_name == "propose_fork" and is_active and action.tool_use_id.startswith("balloons-"):
                proposal = parse_fork_proposal(action.tool_input)
                if proposal:
                    self._handle_fork_proposal(
                        proposal,
                        action.tool_use_id,
                        session_id,
                        ctx,
                    )
                    # Don't show normal tool UI for propose_fork
                    return

            # Intercept propose_merge tool - show modal before execution
            if action.tool_name == "propose_merge" and is_active and action.tool_use_id.startswith("balloons-"):
                proposal = parse_merge_proposal(action.tool_input)
                if proposal:
                    self._handle_merge_proposal(
                        proposal,
                        action.tool_use_id,
                        session_id,
                        ctx,
                    )
                    # Don't show normal tool UI for propose_merge
                    return

            # Track tool names for post-result actions (like slides refresh)
            if action.tool_use_id.startswith("balloons-"):
                ctx.tool_names[action.tool_use_id] = action.tool_name
                debug_log.info(f"Tracking balloons tool: {action.tool_name} ({action.tool_use_id})", category="slides")

            if is_active:
                # Finish streaming tool widget with formatted content
                tool_event = ToolUseEvent(
                    tool_use_id=action.tool_use_id,
                    tool_name=action.tool_name,
                    tool_input=action.tool_input,
                )
                formatted = self._format_tool_use(tool_event)
                if isinstance(formatted, tuple):
                    tool_content, full_content = formatted
                else:
                    tool_content, full_content = formatted, None
                chat_log.finish_streaming_tool(
                    tool_use_id=action.tool_use_id,
                    content=tool_content,
                    full_content=full_content,
                    tool_name=action.tool_name,
                )

        elif isinstance(action, ToolResultAction):
            # Finalize the tool_result turn with real content_block and token count
            turn_idx = ctx.tool_turn_indices.get((action.tool_use_id, "tool_result"))
            if turn_idx is not None:
                content_block = ToolResultBlock(
                    tool_use_id=action.tool_use_id,
                    content=action.result,
                )
                # Use truncated result as preview
                preview = action.result[:100] if action.result else ""
                context_tree.finish_turn(
                    session_id, turn_idx, preview, content_block, []
                )

            # Tool done, back to streaming
            get_task_state().update_task(
                ctx.exchange_id,
                status=TaskStatus.STREAMING,
                tool_name=None,
            )

            # Refresh slides pane when create_slide tool completes
            tool_name = ctx.tool_names.get(action.tool_use_id)
            debug_log.debug(f"ToolResultAction: tool_use_id={action.tool_use_id}, tool_name={tool_name}, tool_names={ctx.tool_names}", category="slides")
            if tool_name == "create_slide" and action.tool_use_id.startswith("balloons-"):
                debug_log.info(f"create_slide tool completed, refreshing slides pane", category="slides")
                if session_id == self._tree_state.get_current_session_id():
                    # Use call_later to ensure refresh happens after session state settles
                    self.call_later(self._refresh_slides_pane)

            # Refresh goal tree when a goal mutation tool completes
            if tool_name in GOAL_MUTATION_TOOLS and action.tool_use_id.startswith("balloons-"):
                debug_log.info(f"Goal mutation tool {tool_name} completed, refreshing goal tree", category="goals")
                self.call_later(self._refresh_goal_tree)

            if is_active:
                # Display tool result widget
                tool_result_event = ToolResultEvent(
                    tool_use_id=action.tool_use_id,
                    result=action.result,
                )
                formatted = self._format_tool_result(tool_result_event, session_id)
                if isinstance(formatted, tuple):
                    result_content, full_content = formatted
                else:
                    result_content, full_content = formatted, None
                chat_log.add_tool_result(
                    result_content,
                    tool_use_id=action.tool_use_id, full_content=full_content
                )

        elif isinstance(action, DoneAction):
            debug_log.info("Received done action, calling finalize", category="stream", session_id=session_id)
            play_done_sound()
            self._finalize_streaming(session_id, ctx, chat_log, context_tree, status_bar)

        elif isinstance(action, ErrorAction):
            debug_log.error(action.error, session_id=session_id, category="stream")
            play_error_sound()
            if is_active:
                chat_log.append_to_current(f"\n\n[Error: {action.error}]")
            self._finalize_streaming(session_id, ctx, chat_log, context_tree, status_bar, error=action.error)

        elif isinstance(action, RateLimitAction):
            play_error_sound()
            if is_active:
                chat_log.append_to_current(f"\n\n[Rate Limit] {action.message}")
            self._finalize_streaming(session_id, ctx, chat_log, context_tree, status_bar, error=action.message)

        elif isinstance(action, CancelledAction):
            self._finalize_streaming(session_id, ctx, chat_log, context_tree, status_bar, cancelled=True)

        elif isinstance(action, InputRequiredAction):
            play_notification_sound()
            if is_active:
                chat_log.append_to_current("\n\n[Claude is asking a question - session ended]")
                self.notify("Claude asked a question (not supported)", severity="warning")
            self._finalize_streaming(session_id, ctx, chat_log, context_tree, status_bar)

    def _dispatch_helper_event(
        self,
        helper_id: str,
        event: StreamEvent,
        ctx: StreamingContext,
        chat_log: ChatLogView,
        status_bar: StatusBar,
    ) -> None:
        """Dispatch a helper event (context compression, merge summary).

        Uses StreamingCoordinator to convert events to actions, then handles
        the actions with UI-specific code.
        """
        # Log events for debugging
        if event.event_type == "text":
            debug_event(f"helper text: helper={helper_id[:8]} len={len(event.data)}")
        elif event.event_type in ("done", "error", "cancelled"):
            debug_event(f"helper {event.event_type}: helper={helper_id[:8]}")

        # Get action from coordinator (also updates ctx state)
        action = self._streaming_coordinator.dispatch_helper_event(event, ctx)

        # Handle action based on type
        if isinstance(action, TextAction):
            if ctx.is_active:
                chat_log.append_to_current(action.text)

        elif isinstance(action, HelperDoneAction):
            self._finalize_helper(
                helper_id, ctx, chat_log, status_bar,
                error=action.error, cancelled=action.cancelled
            )

    def _finalize_helper(
        self,
        helper_id: str,
        ctx: StreamingContext,
        chat_log: ChatLogView,
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
            # Helper failed - clean up
            status_bar.set_streaming(False)
            self.streaming = False
            if error:
                self.notify(f"Helper failed: {error}", severity="error")
            return

        # Success - trigger next phase based on helper type
        if ctx.helper_type == "compress":
            # Context compression complete - now start the actual fork
            asyncio.create_task(self._complete_fork_after_compression(ctx, chat_log, status_bar))
        elif ctx.helper_type == "derive":
            # Context compression complete - now start the derived session
            asyncio.create_task(self._complete_derive_after_compression(ctx, chat_log, status_bar))
        elif ctx.helper_type == "archive":
            # Archive summary complete - now finalize the archive
            asyncio.create_task(self._complete_archive_after_summary(ctx, chat_log))
        elif ctx.helper_type == "merge":
            # Merge summary complete - now finalize the merge
            asyncio.create_task(self._complete_merge_after_summary(ctx, chat_log))
        elif ctx.helper_type == "link":
            # Link summary complete - continue with next target or finalize
            asyncio.create_task(self._continue_link_after_summary(ctx, chat_log))
        elif ctx.helper_type == "return":
            # Return summary complete - now finalize the return
            asyncio.create_task(self._complete_return_after_summary(ctx, chat_log))

    async def _complete_fork_after_compression(
        self,
        ctx: StreamingContext,
        chat_log: ChatLogView,
        status_bar: StatusBar,
    ) -> None:
        """Complete a fork after context compression finishes.

        The compression result is in ctx.content, and fork_data has the original params.
        """
        debug_log.info(
            f"_complete_fork_after_compression called",
            category="fork",
            details={"content_len": len(ctx.content), "has_fork_data": ctx.fork_data is not None},
        )
        fork_data = ctx.fork_data
        if not fork_data or not isinstance(fork_data, ForkData):
            debug_log.error("No fork_data in context after compression", category="stream")
            # Clean up UI state
            status_bar.set_streaming(False)
            self.streaming = False
            self.notify("Fork failed: missing context data", severity="error")
            return

        context_tree = self.query_one("#context-tree", ContextTreeView)

        # Extract fork params from typed dataclass
        child_session = fork_data.child_session
        prompt = fork_data.prompt
        name = fork_data.name
        background = fork_data.background
        allowed_tools = fork_data.allowed_tools
        copy_items = fork_data.copy_items
        compress_group_positions = fork_data.compress_group_positions

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
        context_messages = build_context_messages(copy_items, summary_items)

        # Add all context messages to the child session
        for msg in context_messages:
            child_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

        asyncio.create_task(child_session.save())

        # Register child in parent and add fork turn marker
        parent_session = fork_data.parent_session
        fork_point = fork_data.fork_point
        parent_session.add_child(
            child_session.id,
            prompt,
            name=name,
            fork_point=fork_point,
        )
        # Add fork turn marker to parent session (part of the fork proposal exchange)
        parent_session.add_fork_turn(
            fork_id=str(uuid.uuid4()),
            child_session_id=child_session.id,
            fork_name=name or "fork",
            prompt=prompt,
            exchange_id=parent_session.get_last_exchange_id(),
        )
        asyncio.create_task(parent_session.save())

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
            turn_idx = len(child_session.turns)
            exchange_id = str(uuid.uuid4())  # Group user + assistant turns
            new_ctx = StreamingContext(
                session_id=child_session.id,
                user_turn_idx=turn_idx,
                assistant_turn_idx=turn_idx + 1,
                prompt=prompt,
                is_active=False,
                exchange_id=exchange_id,
            )
            self._streaming_contexts[child_session.id] = new_ctx

            # Add child session to TreeState so it appears in the tree
            # This must happen before set_session_streaming so the node exists
            self._tree_state.add_session(child_session, is_current=False)
            self._tree_state.load_session(child_session.id, child_session)

            # Update tree streaming indicator and status bar count
            context_tree.set_session_streaming(child_session.id, True)
            self._update_streaming_count()

            # Start tree turns for child (with exchange_id for grouping)
            context_tree.start_turn(child_session.id, turn_idx, "user", exchange_id=exchange_id)
            context_tree.finish_turn(
                child_session.id, turn_idx, prompt, TextBlock(text=prompt), []
            )
            context_tree.start_turn(child_session.id, turn_idx + 1, "assistant", exchange_id=exchange_id)

            # Add user message to child session before streaming starts
            # This ensures it's persisted even if we crash mid-exchange
            user_blocks = [TextBlock(text=prompt)]
            child_session.add_message("user", prompt, content_blocks=user_blocks, exchange_id=exchange_id)
            asyncio.create_task(child_session.save())

            # Start background streaming
            child_runner = self._manager._runners[child_session.id]
            child_runner.start_background(
                prompt=prompt,
                messages=child_session.turns,
                allowed_tools=allowed_tools,
            )
            self.notify(f"Fork '{name or child_session.id[:8]}' started in background")
            self.streaming = False
        else:
            # Foreground mode - switch to child
            breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
            await self._manager.set_active(child_session.id)
            chat_log.clear()
            await chat_log.load_history(child_session.turns, session=child_session)
            await context_tree.load_all_sessions(child_session)
            await breadcrumb.set_session(child_session)

            # Start streaming the actual prompt
            self._start_streaming(prompt)

    async def _complete_derive_after_compression(
        self,
        ctx: StreamingContext,
        chat_log: ChatLogView,
        status_bar: StatusBar,
    ) -> None:
        """Complete a derive after context compression finishes.

        Similar to fork completion but simpler - no parent/child relationship.
        """
        derive_data = ctx.fork_data
        if not derive_data or not isinstance(derive_data, DeriveData):
            debug_log.error("No derive_data in context after derive compression", category="stream")
            status_bar.set_streaming(False)
            self.streaming = False
            self.notify("Derive failed: missing context data", severity="error")
            return

        context_tree = self.query_one("#context-tree", ContextTreeView)

        # Extract params from typed dataclass
        new_session = derive_data.new_session
        prompt = derive_data.prompt
        allowed_tools = derive_data.allowed_tools
        copy_items = derive_data.copy_items
        compress_group_positions = derive_data.compress_group_positions

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
        context_messages = build_context_messages(copy_items, summary_items)

        # Add all context messages to the new session
        for msg in context_messages:
            new_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

        asyncio.create_task(new_session.save())

        # Register and switch to new session
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
        self._manager._sessions[new_session.id] = new_session
        self._manager._runners[new_session.id] = self._create_session_runner(new_session)
        await self._manager.set_active(new_session.id)

        chat_log.clear()
        await chat_log.load_history(new_session.turns, session=new_session)
        await context_tree.load_all_sessions(new_session)
        await breadcrumb.set_session(new_session)

        # Start streaming the actual prompt
        self._start_streaming(prompt)

    async def _complete_archive_after_summary(
        self,
        ctx: StreamingContext,
        chat_log: ChatLogView,
    ) -> None:
        """Complete an archive after summary generation finishes.

        The summary is in ctx.content, and archive_data has the original params.
        """
        status_bar = self.query_one("#status-bar", StatusBar)
        context_tree = self.query_one("#context-tree", ContextTreeView)

        archive_data = ctx.archive_data
        if not archive_data:
            debug_log.error("No archive_data in context after summary generation", category="archive")
            status_bar.set_streaming(False)
            self.streaming = False
            self.notify("Archive failed: missing context data", severity="error")
            return

        # Get the summary from the helper's output
        summary = ctx.content.strip()
        if not summary:
            # Fall back to simple summary
            summary = f"Archived turns {archive_data.turn_start}-{archive_data.turn_end - 1}"

        debug_log.info(
            f"Archive summary generated: {summary[:100]}...",
            category="archive",
        )

        # Get the session we're archiving from
        session = self._manager._sessions.get(archive_data.session_id)
        if not session:
            debug_log.error(f"Session {archive_data.session_id} not found", category="archive")
            status_bar.set_streaming(False)
            self.streaming = False
            self.notify("Archive failed: session not found", severity="error")
            return

        # Use command executor for business logic
        result = self._command_executor.prepare_archive(
            session=session,
            turn_indices=archive_data.turn_indices,
            summary=summary,
        )

        if not result.success:
            debug_log.error(f"Archive failed: {result.error}", category="archive")
            status_bar.set_streaming(False)
            self.streaming = False
            self.notify(f"Archive failed: {result.error}", severity="error")
            return

        # Update session state
        session.turns = result.new_turns
        await session.save()

        # Reload the UI first so TreeState has updated turns
        chat_log.clear()
        await chat_log.load_history(session.turns, session)
        await context_tree.load_all_sessions(session)

        # Recalculate token count after archiving (turns removed)
        # Must be after tree reload so TreeState has the new turns
        self._update_base_context_tokens()
        self._update_context_tokens()

        status_bar.set_streaming(False)
        self.streaming = False
        self.notify(f"Archived {result.archived_count} turns")

    async def _complete_merge_after_summary(
        self,
        ctx: StreamingContext,
        chat_log: ChatLogView,
    ) -> None:
        """Complete a merge after summary generation finishes.

        The summary is in ctx.content, and merge_data has the session info.
        """
        status_bar = self.query_one("#status-bar", StatusBar)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)

        merge_data = ctx.merge_data
        if not merge_data:
            debug_log.error("No merge_data in context after summary generation", category="merge")
            status_bar.set_streaming(False)
            self.streaming = False
            self.notify("Merge failed: missing context data", severity="error")
            return

        # Get the summary from the helper's output
        merge_message = ctx.content.strip()
        if not merge_message:
            # Fall back to simple summary
            merge_message = f"Merged from {merge_data.fork_name}"

        debug_log.info(
            f"Merge summary generated: {merge_message[:100]}...",
            category="merge",
        )

        # Get the sessions
        fork_session = self._manager._sessions.get(merge_data.fork_session_id)
        parent_session = self._manager._sessions.get(merge_data.parent_session_id)

        if not fork_session or not parent_session:
            debug_log.error("Session not found for merge", category="merge")
            status_bar.set_streaming(False)
            self.streaming = False
            self.notify("Merge failed: session not found", severity="error")
            return

        # Complete the merge
        result = await self._fork_manager.complete_merge(
            fork_session=fork_session,
            parent_session=parent_session,
            merge_message=merge_message,
        )

        # Switch to parent
        self._manager._sessions[result.parent_session.id] = result.parent_session
        self._manager._runners[result.parent_session.id] = self._create_session_runner(result.parent_session)
        await self._manager.set_active(result.parent_session.id)
        chat_log.clear()
        await chat_log.load_history(result.parent_session.turns, session=result.parent_session)
        await context_tree.load_all_sessions(result.parent_session)
        await breadcrumb.set_session(result.parent_session)

        status_bar.set_streaming(False)
        self.streaming = False
        self.notify(f"Merged from '{result.fork_name}'")

    async def _continue_link_after_summary(
        self,
        ctx: StreamingContext,
        chat_log: ChatLogView,
    ) -> None:
        """Continue link operation after a summary generation finishes.

        Updates the summary in link_data, then either starts the next
        summary or completes the link operation.
        """
        status_bar = self.query_one("#status-bar", StatusBar)
        context_tree = self.query_one("#context-tree", ContextTreeView)

        link_data = ctx.link_data
        if not link_data:
            debug_log.error("No link_data in context after summary generation", category="link")
            status_bar.set_streaming(False)
            self.streaming = False
            self.notify("Link failed: missing context data", severity="error")
            return

        # Get the summary from the helper's output
        summary = ctx.content.strip()
        if not summary:
            summary = "[No summary generated]"

        # Update the target's summary in the targets list
        current_idx = link_data.current_target_index
        targets = link_data.targets
        session_id, _ = targets[current_idx]
        targets[current_idx] = (session_id, summary)

        debug_log.info(
            f"Link summary generated for target {current_idx}: {summary[:100]}...",
            category="link",
        )

        # Get the pending linked targets
        linked_targets = getattr(self, "_pending_link_targets", None)
        if not linked_targets:
            debug_log.error("No pending link targets", category="link")
            status_bar.set_streaming(False)
            self.streaming = False
            self.notify("Link failed: missing target data", severity="error")
            return

        # Continue to next summary or complete
        self._start_next_link_summary_or_complete(
            targets, current_idx + 1, linked_targets, chat_log, context_tree, status_bar
        )

    async def _complete_return_after_summary(
        self,
        ctx: StreamingContext,
        chat_log: ChatLogView,
    ) -> None:
        """Complete a return after summary generation finishes.

        The summary is in ctx.content, and return_data has the session info.
        """
        status_bar = self.query_one("#status-bar", StatusBar)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)

        return_data = ctx.return_data
        if not return_data:
            debug_log.error("No return_data in context after summary generation", category="return")
            status_bar.set_streaming(False)
            self.streaming = False
            self.notify("Return failed: missing context data", severity="error")
            return

        # Get the summary from the helper's output
        return_content = ctx.content.strip()
        if not return_content:
            return_content = "[Return summary not available]"

        debug_log.info(
            f"Return summary generated: {return_content[:100]}...",
            category="return",
        )

        # Get the sessions
        child_session = self._manager._sessions.get(return_data.child_session_id)
        parent_session = self._manager._sessions.get(return_data.parent_session_id)

        # If parent not in manager, try to load it
        if not parent_session:
            parent_session = await Session.load(return_data.parent_session_id)

        if not child_session or not parent_session:
            debug_log.error("Session not found for return", category="return")
            status_bar.set_streaming(False)
            self.streaming = False
            self.notify("Return failed: session not found", severity="error")
            return

        # Mark child as returned
        child_session.returned = True
        await child_session.save()

        # Update parent
        parent_session.mark_child_returned(child_session.id)
        await parent_session.save()

        child_id = child_session.id

        # Switch to parent session through manager
        self._manager._sessions[parent_session.id] = parent_session
        self._manager._runners[parent_session.id] = self._create_session_runner(parent_session)
        await self._manager.set_active(parent_session.id)
        chat_log.clear()
        await chat_log.load_history(parent_session.turns, session=parent_session)
        await context_tree.load_all_sessions(parent_session)
        await breadcrumb.set_session(parent_session)

        # Find and update the WithWidget
        with_widget = chat_log.find_with_widget(child_id)
        if with_widget:
            with_widget.mark_returned()

        # Add WithResultWidget to parent
        chat_log.add_with_result_widget(
            content=return_content,
            child_session_id=child_id,
            return_prompt=return_data.return_prompt,
        )

        status_bar.set_streaming(False)
        self.streaming = False
        self.notify("Returned from child session")

    def _finalize_streaming(
        self,
        session_id: str,
        ctx: StreamingContext,
        chat_log: ChatLogView,
        context_tree: ContextTreeView,
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

            # Add visual error marker if there's an ErrorBlock in the result
            if ctx.is_active:
                for block in assistant_blocks:
                    if isinstance(block, ErrorBlock):
                        chat_log.add_error_marker(
                            reason=block.reason,
                            partial_tool_name=block.partial_tool_name,
                            details=block.details,
                            dump_file=block.dump_file,
                        )
                        break

            # Finish the assistant turn in tree
            # Note: assistant_blocks may have multiple blocks from legacy streaming model
            # The tree view uses single content_block - take primary block (first text or tool use)
            primary_block = assistant_blocks[0] if assistant_blocks else TextBlock(text=content)
            context_tree.finish_turn(
                session_id,
                ctx.assistant_turn_idx,
                content,
                primary_block,
                raw_events,
            )

            # Save final session state
            # Note: User message and turns are already added incrementally during streaming
            # (user message added in _start_streaming, turns added by runner on each tool result)
            # We just need to ensure exchange_id is set and do a final save
            if session:
                exchange_id = ctx.exchange_id or (result.exchange_id if result else None)
                turns = result.turns if result else []

                # Update exchange_id on turns (they're already in session.turns)
                # This ensures consistent grouping for the UI
                for turn in turns:
                    turn.exchange_id = exchange_id

                # Legacy fallback: if no turns were created, add a single assistant message
                # This handles backends that don't produce turn events
                if not turns and content:
                    session.add_message("assistant", content, content_blocks=assistant_blocks, exchange_id=exchange_id)

                # Final save to ensure all state is persisted
                asyncio.create_task(session.save())

            if ctx.is_active:
                # Exit streaming mode (re-enable normal input)
                debug_log.info("Re-enabling input (active session)", category="stream", session_id=session_id)
                self.streaming = False
                status_bar.set_streaming(False)
                input_box = self.query_one("#input-box", InputBox)
                input_box.set_streaming_mode(False)

                # Update queue indicator
                self._update_queue_indicator()

                # Process any queued messages
                if session and self._queue_state.has_messages(session.id):
                    self._process_message_queue()

                # Check for auto-return conditions
                if session and self._check_auto_return(content):
                    asyncio.create_task(self._handle_return_command("Auto-return: condition met"))
            else:
                # Background session finished - update WithWidget
                with_widget = chat_log.find_with_widget(session_id)
                if with_widget:
                    with_widget.mark_done()
                if error:
                    self.notify(f"Background error: {error}", severity="error")
                elif not cancelled:
                    # Show actionable toast that switches to the session when clicked
                    # Prefer fork_name (more descriptive), then title, then ID prefix
                    display_name = (
                        (session.fork_name if session else None)
                        or (session.title if session else None)
                        or session_id[:8]
                    )
                    self._show_actionable_notification(
                        f"Background session done: {display_name}",
                        action="switch_session",
                        action_data={"session_id": session_id},
                        action_label="Click to view",
                    )

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
                    input_box.set_streaming_mode(False)
                except Exception:
                    pass

        finally:
            # Clean up streaming context - but only if it's the SAME context we started with.
            # If _process_message_queue() started a NEW stream, we must NOT delete it.
            current_ctx = self._streaming_contexts.get(session_id)
            if current_ctx is ctx:
                # Update task state
                task_state = get_task_state()
                if cancelled:
                    task_state.cancel_task(ctx.exchange_id)
                elif error:
                    task_state.fail_task(ctx.exchange_id, error)
                else:
                    task_state.complete_task(ctx.exchange_id)

                del self._streaming_contexts[session_id]
                # Update tree streaming indicator and status bar count
                context_tree.set_session_streaming(session_id, False)
                self._tree_state.stop_streaming(session_id)
                self._update_streaming_count()
                debug_log.info("Finalization complete, context cleaned up", category="stream", session_id=session_id)
            elif current_ctx is not None:
                # A new stream was started (likely from queue processing) - don't clean up
                debug_log.info(
                    "New stream started during finalization, preserving context",
                    category="stream",
                    session_id=session_id,
                )
                # Still complete the OLD task
                task_state = get_task_state()
                if cancelled:
                    task_state.cancel_task(ctx.exchange_id)
                elif error:
                    task_state.fail_task(ctx.exchange_id, error)
                else:
                    task_state.complete_task(ctx.exchange_id)

    async def _load_last_viewed_session(self) -> tuple[Session | None, int | None]:
        """Load the last viewed session and turn index from config.

        Returns (session, turn_index) where turn_index may be None.
        Falls back to most recently modified session if last view doesn't exist.
        """
        config = get_config()

        # Try last viewed session first
        if config.last_view_session_id:
            session = await self._manager.load_session(config.last_view_session_id)
            if session:
                return session, config.last_view_turn_index

        # Fall back to most recently modified session
        session_id = None
        for metadata in await Session.list_sessions():
            session_id = metadata["id"]
            break  # Just need the first one (most recent)

        if not session_id:
            return None, None

        session = await self._manager.load_session(session_id)
        return session, None  # No saved turn index for fallback

    async def _initialize_session(self) -> None:
        """Initialize the UI with the current session."""
        restore_turn_index = None  # Turn index to scroll to after init

        if self._initial_session is not None:
            # Load initial session into manager (passed via --resume)
            self._manager._sessions[self._initial_session.id] = self._initial_session
            self._manager._runners[self._initial_session.id] = self._create_session_runner(self._initial_session)
            await self._manager.set_active(self._initial_session.id)
            self._initial_session = None  # Clear so we don't reload on subsequent calls
        elif self.session is None:
            # No session passed - try to load the last viewed session
            session, restore_turn_index = await self._load_last_viewed_session()
            if session is None:
                # No sessions exist - create a new one
                session = await self._manager.create_session()
            await self._manager.set_active(session.id)

        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        status_bar = self.query_one("#status-bar", StatusBar)
        input_box = self.query_one("#input-box", InputBox)
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)

        # Pre-seed TreeState with cached token count from session
        # This ensures the tree displays correct count immediately
        if self.session.cached_context_tokens > 0:
            self._tree_state.set_context_tokens(self.session.cached_context_tokens, 0)

        # Load all sessions from index (fast - single file read)
        # Sessions are lazy-loaded: only metadata initially, full data on expand/activate
        await context_tree.load_all_sessions(self.session)

        # Load current session's messages into chat view
        if self.session.turns:
            await chat_log.load_history(self.session.turns, session=self.session)

        # Set session title in chat header
        if self.session.title:
            chat_log.set_session_title(self.session.title)

        # Update breadcrumb to show current position in hierarchy
        await breadcrumb.set_session(self.session)

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

        # Scroll to restored turn, or default to the bottom/last message
        if restore_turn_index is not None and restore_turn_index < len(self.session.turns):
            # Turn IDs in chat_log are 1-indexed
            turn_id = restore_turn_index + 1
            # Use call_after_refresh to ensure widgets are laid out before scrolling
            # Use default argument to capture turn_id value (avoid late binding)
            self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))
        elif self.session.turns:
            # No saved position - scroll to the last turn
            turn_id = len(self.session.turns)
            self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))

        # Initial context token update (recalculate from actual selected context)
        self._update_base_context_tokens(use_cache=False)
        self._update_context_tokens()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Handle text changes in the input box - update context token count live."""
        # Only handle events from our input box
        if event.text_area.id == "input-box":
            # Debounce token updates to avoid lag during fast typing
            self._pending_token_text = event.text_area.text
            if self._token_update_timer is not None:
                self._token_update_timer.stop()
            self._token_update_timer = self.set_timer(0.15, self._do_debounced_token_update)

    def _do_debounced_token_update(self) -> None:
        """Actually update token count after debounce delay."""
        self._token_update_timer = None
        self._update_context_tokens(self._pending_token_text)

    def on_input_box_completion_changed(self, event: InputBox.CompletionChanged) -> None:
        """Handle completion popup visibility changes."""
        popup = self.query_one("#completion-popup", CompletionPopup)
        if event.visible and event.candidates:
            popup.show_candidates(event.candidates, event.selected)
        else:
            popup.hide()

    async def on_input_box_submitted(self, event: InputBox.Submitted) -> None:
        """Handle user input submission."""
        prompt = event.value.strip()
        if not prompt:
            return

        # Try to parse as a command
        try:
            cmd = self._command_parser.parse(prompt)
        except ValueError as e:
            # Invalid command
            self.notify(str(e), severity="error")
            return

        # Commands execute immediately (even during streaming for global commands)
        if cmd is not None:
            # Check if this is a "global" command that can run during streaming
            if self.streaming and not cmd.is_global:
                self.notify("Command unavailable during streaming", severity="warning")
                return
            await self._execute_command(cmd)
            return

        # Regular prompts queued during streaming
        if self.streaming:
            if self.session:
                self._queue_state.add_message(self.session.id, prompt)
                # NOTE: Don't save here - would race with streaming modifying turns.
                # Queue will be persisted when streaming finishes and session saves.
                queue_len = self._queue_state.get_message_count(self.session.id)
                self.notify(f"Message queued ({queue_len} pending)")
                self._update_queue_indicator()
            else:
                self.notify("No session to queue message", severity="error")
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
        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Use only selected messages for context
        selected_messages = context_tree.get_selected_messages()

        # Get enabled tools
        allowed_tools = self._get_enabled_tools()

        # Track the turn index for tree updates
        turn_idx = len(self.session.turns)  # Next turn will be at this index

        # Generate exchange_id to group user prompt + all assistant responses
        exchange_id = str(uuid.uuid4())

        # Start the user turn in tree immediately (with exchange_id for grouping)
        context_tree.start_turn(self.session.id, turn_idx, "user", exchange_id=exchange_id)
        context_tree.finish_turn(
            self.session.id, turn_idx, prompt, TextBlock(text=prompt), []
        )

        # Add user message to session immediately (before tool loops start)
        # This ensures the user prompt is persisted even if we crash mid-exchange
        user_blocks = [TextBlock(text=prompt)]
        self.session.add_message("user", prompt, content_blocks=user_blocks, exchange_id=exchange_id)
        asyncio.create_task(self.session.save())

        # Start the assistant turn in tree (with same exchange_id)
        assistant_turn_idx = turn_idx + 1
        context_tree.start_turn(self.session.id, assistant_turn_idx, "assistant", exchange_id=exchange_id)

        # Create streaming context for this session
        ctx = StreamingContext(
            session_id=self.session.id,
            user_turn_idx=turn_idx,
            assistant_turn_idx=assistant_turn_idx,
            prompt=prompt,
            is_active=is_active,
            exchange_id=exchange_id,
        )
        self._streaming_contexts[self.session.id] = ctx

        # Update tree streaming indicator and status bar count
        context_tree.set_session_streaming(self.session.id, True)
        self._tree_state.start_streaming(self.session.id)
        self._update_streaming_count()

        # Register task for task pane with context info
        backend_name = self.session.backend_name or self._backend_config.name
        overhead_tokens, context_tokens = self._calculate_context_tokens(prompt)
        context_window = self._backend_config.context_window
        task = get_task_state().register_session_task(
            session_id=self.session.id,
            exchange_id=exchange_id,
            prompt=prompt,
            backend_name=backend_name,
        )
        # Set initial context info (total tokens for task tracking)
        task.input_tokens = overhead_tokens + context_tokens
        task.context_window = context_window

        if is_active:
            # Add user message to display
            chat_log.add_user_message(prompt)

            # Enable streaming mode (allows queueing prompts)
            input_box.set_streaming_mode(True)
            status_bar.set_streaming(True)
            # Update status bar to show context tokens being sent for this request
            status_bar.update_stats(overhead_tokens=overhead_tokens, context_tokens=context_tokens)
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
            await self._handle_copy_turns()
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
            await self._handle_switch_command(cmd.name)
        elif isinstance(cmd, ReturnCommand):
            await self._handle_return_command(cmd.return_prompt)
        elif isinstance(cmd, PwdCommand):
            self._handle_pwd_command()
        elif isinstance(cmd, CdCommand):
            self._handle_cd_command(cmd.path)
        elif isinstance(cmd, ReloadCommand):
            self._handle_reload()
        elif isinstance(cmd, TitleCommand):
            await self._handle_title_command(cmd.title)
        elif isinstance(cmd, HelpCommand):
            self.push_screen(HelpModal())
        elif isinstance(cmd, PrefsCommand):
            self.action_show_preferences()
        elif isinstance(cmd, EditConfigCommand):
            self._handle_edit_config()
        elif isinstance(cmd, EditPromptCommand):
            self._handle_edit_prompt(cmd.prompt_name)
        elif isinstance(cmd, BackendCommand):
            await self._handle_backend_command(cmd.backend_name)
        elif isinstance(cmd, LinkCommand):
            await self._handle_link_command(cmd.target_session_prefixes)
        elif isinstance(cmd, DebugToggleCommand):
            self.action_toggle_debug()
        elif isinstance(cmd, DebugClearCommand):
            self._handle_debug_clear()
        elif isinstance(cmd, DebugPauseCommand):
            self._handle_debug_pause()
        elif isinstance(cmd, ArchiveCommand):
            await self._handle_archive_command(cmd.prompt)
        elif isinstance(cmd, RehydrateCommand):
            await self._handle_rehydrate_command()
        elif isinstance(cmd, ReindexCommand):
            await self._handle_reindex_command()
        elif isinstance(cmd, FollowCommand):
            self._handle_follow_toggle()
        elif isinstance(cmd, StashCommand):
            self._handle_stash_command(cmd.name)
        elif isinstance(cmd, PopCommand):
            self._handle_pop_command()
        elif isinstance(cmd, ClearAllSessionsCommand):
            self._handle_clear_all_sessions_command()
        elif isinstance(cmd, SnapCommand):
            await self._handle_snap_command(cmd.prompt)
        elif isinstance(cmd, NewSlideCommand):
            self._handle_new_slide_command(cmd.title)
        elif isinstance(cmd, PresentCommand):
            self._handle_present_command()
        elif isinstance(cmd, SlidesCommand):
            self._switch_to_slides_tab()
        elif isinstance(cmd, ChatCommand):
            self._switch_to_chat_tab()
        elif isinstance(cmd, ReviewCommand):
            await self._handle_review_command()
        # Goal-oriented task management commands
        elif isinstance(cmd, GoalInterviewCommand):
            await self._handle_goal_interview_command(cmd.name, cmd.prompt)
        elif isinstance(cmd, GoalsCommand):
            await self._handle_goals_command(cmd.include_completed)
        elif isinstance(cmd, PlansCommand):
            await self._handle_plans_command(cmd.goal_id)
        elif isinstance(cmd, TodosCommand):
            await self._handle_todos_command(cmd.plan_id)
        elif isinstance(cmd, TodoDoneCommand):
            await self._handle_todo_done_command(cmd.todo_id)
        elif isinstance(cmd, BindCommand):
            await self._handle_bind_command(cmd.entity_type, cmd.entity_id, cmd.role)
        elif isinstance(cmd, UnbindCommand):
            await self._handle_unbind_command(cmd.entity_id)

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
        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        status_bar = self.query_one("#status-bar", StatusBar)
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)

        # Background old session (mark streaming as inactive, sync queue)
        old_session_id = self._manager._active_session_id
        self._background_old_session(old_session_id)

        # Show loading indicator while creating session
        chat_log.show_loading("Creating new session...")

        # Create new session through manager
        new_session = await self._manager.create_session()
        if title:
            new_session.title = title
        await self._manager.set_active(new_session.id)

        # Reload UI (hide_loading is called automatically since new session has no history)
        chat_log.hide_loading()
        await context_tree.load_all_sessions(self.session)
        await breadcrumb.set_session(self.session)
        self.notify("New session created")

        # Update context tokens for new empty session
        self._update_base_context_tokens()
        self._update_context_tokens()

        # If a prompt was provided, send it
        if prompt:
            self._start_streaming(prompt)

    def _handle_pwd_command(self) -> None:
        """Show the current working directory for the session."""
        if self.session.working_directory:
            self.notify(f"Working directory: {self.session.working_directory}")
        else:
            self.notify(f"No working directory set (process cwd: {os.getcwd()})")

    def _handle_cd_command(self, path_arg: str) -> None:
        """Change the working directory for the session."""
        if not path_arg:
            # No argument - switch to files tab and show directory browser
            self._switch_to_files_tab()
            return

        # Expand ~ and resolve relative paths
        self._set_working_directory(path_arg)

    def _set_working_directory(self, path_arg: str) -> None:
        """Set the working directory to the given path."""
        status_bar = self.query_one("#status-bar", StatusBar)

        try:
            target_path = Path(path_arg).expanduser()
            if not target_path.is_absolute():
                # Resolve relative to current working directory or session's working directory
                base = Path(self.session.working_directory) if self.session.working_directory else Path.cwd()
                target_path = (base / target_path).resolve()
            else:
                target_path = target_path.resolve()

            if not target_path.exists():
                self.notify(f"Path does not exist: {target_path}", severity="error")
                return

            if not target_path.is_dir():
                self.notify(f"Not a directory: {target_path}", severity="error")
                return

            # Set the working directory (resolves to canonical absolute path)
            self.session.set_working_directory(str(target_path))
            asyncio.create_task(self.session.save())
            status_bar.update_working_directory(self.session.working_directory)
            self.notify(f"Changed to: {target_path}")

        except Exception as e:
            self.notify(f"Invalid path: {e}", severity="error")

    def _handle_reload(self) -> None:
        """Reload the app by re-executing the process."""
        asyncio.create_task(self.session.save())
        # Save current view position so we return here after reload
        turn_index = len(self.session.turns) - 1 if self.session.turns else None
        save_last_view(self.session.id, turn_index)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    async def _handle_title_command(self, title: str) -> None:
        """Set the session title."""
        self.session.title = title
        await self.session.save()

        # Update UI with new title
        chat_log = self.query_one("#chat-log", ChatLogView)
        chat_log.set_session_title(title)

        # Reload context tree to show title
        context_tree = self.query_one("#context-tree", ContextTreeView)
        await context_tree.load_all_sessions(self.session)

        self.notify(f"Session titled: {title}")

    async def _handle_backend_command(self, backend_name: str) -> None:
        """Set or show the backend for this session."""
        status_bar = self.query_one("#status-bar", StatusBar)
        config = get_config()

        if not backend_name:
            # Show current backend info
            result = self._command_executor.get_backend_info(self.session, config)
            info = result.info
            if info.is_missing:
                self.notify(f"Backend: {info.current} (MISSING - will use default)", severity="warning")
            else:
                self.notify(f"Backend: {info.current} (available: {', '.join(info.available)})")
            return

        # Set backend for this session
        result = self._command_executor.set_backend(self.session, backend_name, config)

        if not result.success:
            self.notify(result.error, severity="error")
            return

        # Save session and recreate runner
        asyncio.create_task(self.session.save())

        backend_config = config.get_backend(result.new_backend)
        self._manager._runners[self.session.id] = SessionRunner(
            self.session, runner=create_runner(backend_config)
        )

        # Update status bar with new backend and model
        status_bar.update_stats(backend=result.new_backend, model=result.model)
        self.notify(f"Backend set to: {result.new_backend}")

    async def _handle_link_command(self, target_prefixes: list[str]) -> None:
        """Create bidirectional links to one or more sessions.

        Each link uses summaries of the linked sessions as descriptions:
        - Current session's link marker shows summary of target session
        - Target session's link marker shows summary of current session

        Uses non-blocking helper runner pattern to generate summaries.

        Args:
            target_prefixes: List of 8-char hash prefixes of target sessions
        """
        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Phase 1: Resolve targets and identify what needs summaries
        resolve_result = await self._command_executor.resolve_link_targets(
            current_session=self.session,
            target_prefixes=target_prefixes,
        )

        if not resolve_result.success:
            self.notify(resolve_result.error, severity="error")
            return

        # Build targets list: (session_id, summary or None)
        targets: list[tuple[str, str | None]] = []
        for target in resolve_result.linked_targets:
            # If target has a summary, use it; otherwise mark as needing generation
            if target.summary:
                targets.append((target.session.id, target.summary))
            elif target.session.summary:
                targets.append((target.session.id, target.session.summary))
            else:
                targets.append((target.session.id, None))

        # Check if any summaries need generation
        needs_summary = any(summary is None for _, summary in targets)

        if not needs_summary:
            # All summaries available - complete immediately
            self._complete_link_operation(resolve_result.linked_targets, chat_log, context_tree)
            return

        # Phase 2: Generate summaries using helper runner
        # Find the first target needing a summary
        first_idx = next(i for i, (_, s) in enumerate(targets) if s is None)
        first_session_id = targets[first_idx][0]
        first_session = self._manager._sessions.get(first_session_id)

        if not first_session:
            self.notify(f"Session {first_session_id} not found", severity="error")
            return

        summary_prompt = self._summarizer.build_session_summary_prompt(first_session)
        if not summary_prompt:
            # Empty session - use empty summary and continue
            targets[first_idx] = (first_session_id, "[Empty session]")
            # Try next target or complete
            self._start_next_link_summary_or_complete(
                targets, first_idx + 1, resolve_result.linked_targets, chat_log, context_tree, status_bar
            )
            return

        # Create helper runner for background summary generation
        helper_id = f"link-{uuid.uuid4().hex[:8]}"
        helper_runner = HelperRunner(helper_id, runner=create_runner(self._backend_config))
        self._helper_runners[helper_id] = helper_runner

        # Create streaming context with link data
        ctx = StreamingContext(
            session_id=helper_id,
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_active=True,
            is_helper=True,
            helper_type="link",
            link_data=LinkData(
                current_session_id=self.session.id,
                targets=targets,
                current_target_index=first_idx,
            ),
        )
        self._streaming_contexts[helper_id] = ctx

        # Store resolve result for later use
        self._pending_link_targets = resolve_result.linked_targets

        # Set up UI for summary streaming
        status_bar.set_streaming(True)
        self.streaming = True

        session_name = first_session.title or first_session.fork_name or first_session.id[:8]
        chat_log.add_user_message(f"[Generating summary for '{session_name}'...]")
        chat_log.add_assistant_message()

        # Start background streaming
        helper_runner.start_background(summary_prompt)

    def _start_next_link_summary_or_complete(
        self,
        targets: list[tuple[str, str | None]],
        start_from_index: int,
        linked_targets: list,  # List[LinkTarget]
        chat_log: ChatLogView,
        context_tree: ContextTreeView,
        status_bar: StatusBar,
    ) -> None:
        """Start the next link summary generation or complete the operation.

        Finds the next target needing a summary and starts a helper, or
        completes the link operation if all summaries are ready.
        """
        # Find next target needing a summary
        next_idx = None
        for i in range(start_from_index, len(targets)):
            if targets[i][1] is None:
                next_idx = i
                break

        if next_idx is None:
            # All summaries ready - update linked_targets and complete
            for i, (session_id, summary) in enumerate(targets):
                if linked_targets[i].session.id == session_id:
                    linked_targets[i].summary = summary or ""
                    # Also update the session's summary
                    session = self._manager._sessions.get(session_id)
                    if session and not session.summary:
                        session.summary = summary or ""

            status_bar.set_streaming(False)
            self.streaming = False
            self._complete_link_operation(linked_targets, chat_log, context_tree)
            return

        # Start next summary generation
        session_id = targets[next_idx][0]
        session = self._manager._sessions.get(session_id)

        if not session:
            # Skip missing session
            targets[next_idx] = (session_id, "[Session not found]")
            self._start_next_link_summary_or_complete(
                targets, next_idx + 1, linked_targets, chat_log, context_tree, status_bar
            )
            return

        summary_prompt = self._summarizer.build_session_summary_prompt(session)
        if not summary_prompt:
            # Empty session
            targets[next_idx] = (session_id, "[Empty session]")
            self._start_next_link_summary_or_complete(
                targets, next_idx + 1, linked_targets, chat_log, context_tree, status_bar
            )
            return

        # Create helper runner
        helper_id = f"link-{uuid.uuid4().hex[:8]}"
        helper_runner = HelperRunner(helper_id, runner=create_runner(self._backend_config))
        self._helper_runners[helper_id] = helper_runner

        # Create streaming context
        ctx = StreamingContext(
            session_id=helper_id,
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_active=True,
            is_helper=True,
            helper_type="link",
            link_data=LinkData(
                current_session_id=self.session.id,
                targets=targets,
                current_target_index=next_idx,
            ),
        )
        self._streaming_contexts[helper_id] = ctx

        # Store linked targets for completion
        self._pending_link_targets = linked_targets

        session_name = session.title or session.fork_name or session.id[:8]
        chat_log.add_user_message(f"[Generating summary for '{session_name}'...]")
        chat_log.add_assistant_message()

        helper_runner.start_background(summary_prompt)

    def _complete_link_operation(
        self,
        linked_targets: list,  # List[LinkTarget]
        chat_log: ChatLogView,
        context_tree: ContextTreeView,
    ) -> None:
        """Complete the link operation after all summaries are ready."""
        # Phase 3: Complete the link operation
        link_result = self._command_executor.complete_link(
            current_session=self.session,
            targets=linked_targets,
            current_summary=self.session.summary,
        )

        # Save all modified sessions
        for session in link_result.sessions_to_save:
            asyncio.create_task(session.save())

        # Update UI for each link
        linked_names = []
        for target, link_turn in zip(link_result.linked_targets, link_result.link_turns):
            target_name = target.session.title or target.session.fork_name or target.session.id[:8]

            # Add link marker to chat log
            chat_log.add_link_marker(
                summary=target.summary,
                linked_session_id=target.session.id,
                linked_session_name=target_name,
                link_point=len(self.session.turns) - 1,
            )

            # Add link turn to context tree
            context_tree.add_turn_to_current(
                role=link_turn.role,
                content=link_turn.content,
                raw_events=[],
                content_block=link_turn.content_block,
            )
            linked_names.append(target_name)

        if len(linked_names) == 1:
            self.notify(f"Linked to '{linked_names[0]}'")
        else:
            self.notify(f"Linked to {len(linked_names)} sessions")

    async def _handle_archive_command(self, hint: str) -> None:
        """Archive selected turns to a file with LLM-generated summary.

        Archives the turn(s) at the cursor position:
        - Single turn: archives just that turn
        - Exchange group: archives all turns in the exchange

        Uses non-blocking helper runner pattern to generate summary.
        """
        context_tree = self.query_one("#context-tree", ContextTreeView)
        chat_log = self.query_one("#chat-log", ChatLogView)
        status_bar = self.query_one("#status-bar", StatusBar)

        if not self.session:
            self.notify("No active session", severity="error")
            return

        # Get the cursor selection from the tree (turn or exchange group)
        cursor_selection = context_tree.get_cursor_turns()
        if not cursor_selection:
            self.notify("Select a turn or exchange to archive", severity="error")
            return

        cursor_session_id, turn_indices = cursor_selection

        # Must be in the current session
        if cursor_session_id != self.session.id:
            self.notify("Selected turn must be in the current session", severity="error")
            return

        # Archive the selected range (contiguous turns)
        turn_start = min(turn_indices)
        turn_end = max(turn_indices) + 1

        # Get the turns to archive for summary generation
        turns_to_archive = self.session.turns[turn_start:turn_end]

        debug_log.info(
            f"Archiving turns {turn_start}-{turn_end} ({len(turns_to_archive)} turns)",
            category="archive",
            details={"hint": hint},
        )

        # Build the summary prompt (non-blocking)
        summary_prompt = self._summarizer.build_archive_summary_prompt(turns_to_archive, hint)

        # Create helper runner for background summary generation
        helper_id = f"archive-{uuid.uuid4().hex[:8]}"
        helper_runner = HelperRunner(helper_id, runner=create_runner(self._backend_config))
        self._helper_runners[helper_id] = helper_runner

        # Create streaming context with archive data
        ctx = StreamingContext(
            session_id=helper_id,
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_active=True,
            is_helper=True,
            helper_type="archive",
            archive_data=ArchiveData(
                session_id=self.session.id,
                turn_indices=list(turn_indices),
                turn_start=turn_start,
                turn_end=turn_end,
                hint=hint,
                message_count=len(turns_to_archive),
            ),
        )
        self._streaming_contexts[helper_id] = ctx

        # Set up UI for archive summary streaming
        status_bar.set_streaming(True)
        self.streaming = True

        chat_log.add_user_message("[Generating archive summary...]")
        chat_log.add_assistant_message()

        # Start background streaming
        helper_runner.start_background(summary_prompt)

    async def _archive_turns_from_tree(self, session_id: str, turn_indices: list[int]) -> None:
        """Archive turns requested from tree view (ctrl+shift+click or x key).

        Uses non-blocking helper runner pattern to generate summary.
        """
        chat_log = self.query_one("#chat-log", ChatLogView)
        status_bar = self.query_one("#status-bar", StatusBar)

        if not self.session:
            self.notify("No active session", severity="error")
            return

        # Verify the request is for the current session
        if session_id != self.session.id:
            self.notify("Can only archive turns in the current session", severity="error")
            return

        if not turn_indices:
            return

        # Archive the selected turns
        turn_start = min(turn_indices)
        turn_end = max(turn_indices) + 1

        # Get the turns to archive for summary generation
        turns_to_archive = self.session.turns[turn_start:turn_end]

        debug_log.info(
            f"Archiving turns {turn_start}-{turn_end} ({len(turns_to_archive)} turns) in session {session_id}",
            category="archive",
        )

        # Build the summary prompt (non-blocking)
        summary_prompt = self._summarizer.build_archive_summary_prompt(turns_to_archive, "")

        # Create helper runner for background summary generation
        helper_id = f"archive-tree-{uuid.uuid4().hex[:8]}"
        helper_runner = HelperRunner(helper_id, runner=create_runner(self._backend_config))
        self._helper_runners[helper_id] = helper_runner

        # Create streaming context with archive data
        ctx = StreamingContext(
            session_id=helper_id,
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_active=True,
            is_helper=True,
            helper_type="archive",
            archive_data=ArchiveData(
                session_id=self.session.id,
                turn_indices=list(turn_indices),
                turn_start=turn_start,
                turn_end=turn_end,
                hint="",
                message_count=len(turns_to_archive),
            ),
        )
        self._streaming_contexts[helper_id] = ctx

        # Set up UI for archive summary streaming
        status_bar.set_streaming(True)
        self.streaming = True

        chat_log.add_user_message("[Generating archive summary...]")
        chat_log.add_assistant_message()

        # Start background streaming
        helper_runner.start_background(summary_prompt)

    async def _handle_rehydrate_command(self) -> None:
        """Rehydrate selected archive marker back to original turns."""
        context_tree = self.query_one("#context-tree", ContextTreeView)
        chat_log = self.query_one("#chat-log", ChatLogView)

        if not self.session:
            self.notify("No active session", severity="error")
            return

        # Get selected turn indices - should contain the archive marker
        indexed_messages = context_tree.get_selected_messages_with_indices()
        selected_indices = [idx for _msg, idx in indexed_messages]

        if not selected_indices:
            self.notify("No archive marker selected", severity="error")
            return

        # Find archive block in selected turns
        archive_turn_index = None
        for idx in selected_indices:
            if idx < len(self.session.turns):
                turn = self.session.turns[idx]
                for block in turn.content_blocks:
                    if isinstance(block, ArchiveBlock):
                        archive_turn_index = idx
                        break
            if archive_turn_index is not None:
                break

        if archive_turn_index is None:
            self.notify("No archive marker in selection", severity="error")
            return

        debug_log.info(
            f"Rehydrating archive at turn {archive_turn_index}",
            category="archive",
        )

        # Use command executor for business logic
        result = self._command_executor.prepare_rehydrate(
            session=self.session,
            turn_index=archive_turn_index,
        )

        if not result.success:
            debug_log.error(f"Rehydration failed: {result.error}", category="archive")
            self.notify(f"Rehydration failed: {result.error}", severity="error")
            return

        # Update session state
        self.session.turns = result.new_turns
        asyncio.create_task(self.session.save())

        # Reload the UI first so TreeState has updated turns
        chat_log.clear()
        await chat_log.load_history(self.session.turns, self.session)
        await context_tree.load_all_sessions(self.session)

        # Recalculate token count after rehydration (turns restored)
        # Must be after tree reload so TreeState has the new turns
        self._update_base_context_tokens()
        self._update_context_tokens()

        self.notify(f"Restored {result.restored_count} archived turns")

    def _handle_suspend(self, cmd: str) -> None:
        """Suspend TUI and run interactive command in session's working directory."""
        cwd = self.session.working_directory
        with self.suspend():
            if cwd:
                os.system(f"cd {cwd!r} && {cmd}")
            else:
                os.system(cmd)

    def _handle_edit_config(self) -> None:
        """Open config file in external editor."""
        from config import Config

        config = Config.load()
        config_path = config._config_path or (Path.home() / ".balloons" / "config.yaml")

        # Create config directory and file if they don't exist
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            config_path.write_text("# Balloons configuration\n# See config/config.sample.yaml for examples\n\ndefault_backend: claude\n\nbackends:\n  claude:\n    # Uses ANTHROPIC_API_KEY from environment\n")

        editor = config.get_editor()

        with self.suspend():
            os.system(f"{editor} {config_path!s}")

    def _handle_edit_prompt(self, prompt_name: str) -> None:
        """Open a prompt file in external editor.

        If prompt_name is empty, show a picker with available prompts.
        Shows app prompts and user prompts from ~/.balloons/prompts/.
        """
        status_bar = self.query_one("#status-bar", StatusBar)

        # Collect all prompt files
        prompt_files: list[Path] = []

        # Internal app prompts
        app_prompts_dir = Path(__file__).parent / "prompts"
        if app_prompts_dir.exists():
            prompt_files.extend(app_prompts_dir.glob("*.md"))

        # User prompts directory
        user_prompts_dir = Path.home() / ".balloons" / "prompts"
        if user_prompts_dir.exists():
            prompt_files.extend(user_prompts_dir.glob("*.md"))

        if not prompt_files:
            self.notify("No prompt files found", severity="error")
            return

        if prompt_name:
            # Direct edit - find matching file
            matching = [f for f in prompt_files if f.stem == prompt_name or f.name == prompt_name]
            if not matching:
                # Try partial match
                matching = [f for f in prompt_files if prompt_name in f.stem]

            if not matching:
                available = ", ".join(f.stem for f in prompt_files)
                self.notify(f"Prompt not found: {prompt_name}", severity="error")
                return
            elif len(matching) > 1:
                matches = ", ".join(f.stem for f in matching)
                self.notify(f"Ambiguous: {matches}", severity="error")
                return

            prompt_path = matching[0]
        else:
            # Show picker
            from widgets.prompt_picker import PromptPickerModal
            self.push_screen(PromptPickerModal(prompt_files), self._on_prompt_selected)
            return

        self._open_prompt_in_editor(prompt_path)

    def _on_prompt_selected(self, prompt_path: Path | None) -> None:
        """Callback when user selects a prompt from picker."""
        if prompt_path:
            self._open_prompt_in_editor(prompt_path)

    def _open_prompt_in_editor(self, prompt_path: Path) -> None:
        """Open a prompt file in the external editor."""
        from config import Config
        config = Config.load()
        editor = config.get_editor()
        with self.suspend():
            os.system(f"{editor} {prompt_path!s}")

    def action_cancel_stream(self) -> None:
        """Cancel streaming/shell and focus input box. Double-tap clears input."""
        # Cancel any running shell process
        if self._shell_process and self._shell_process.returncode is None:
            self._shell_process.kill()
            self._shell_process = None
            self.query_one("#status-bar", StatusBar).set_status("")

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

    async def _handle_copy_turns(self) -> None:
        """Copy selected turns to a new session."""
        context_tree = self.query_one("#context-tree", ContextTreeView)
        chat_log = self.query_one("#chat-log", ChatLogView)

        # Get selected messages
        selected_messages = context_tree.get_selected_messages()
        if not selected_messages:
            return

        # Create new session with selected messages (preserve content_blocks)
        new_session = Session()
        for msg in selected_messages:
            new_session.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)
        asyncio.create_task(new_session.save())

        # Switch to new session through manager
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
        chat_log.clear()
        self._manager._sessions[new_session.id] = new_session
        self._manager._runners[new_session.id] = self._create_session_runner(new_session)
        await self._manager.set_active(new_session.id)
        await context_tree.load_all_sessions(new_session)
        await chat_log.load_history(new_session.turns, session=new_session)
        await breadcrumb.set_session(new_session)

    async def _handle_query_with(self, prompt: str) -> None:
        """Query with selected turns as context, only response goes to new session.

        This is a special case: no user message is saved, only the assistant response.
        Uses the event-driven background streaming approach.
        """
        context_tree = self.query_one("#context-tree", ContextTreeView)
        chat_log = self.query_one("#chat-log", ChatLogView)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)

        # Get selected messages for context (before creating new session)
        selected_messages = context_tree.get_selected_messages()
        allowed_tools = self._get_enabled_tools()

        # Create new session for the response through manager
        new_session = await self._manager.create_session()
        await self._manager.set_active(new_session.id)

        # Clear chat log and switch to new session
        chat_log.clear()
        await context_tree.load_all_sessions(new_session)
        await breadcrumb.set_session(new_session)

        # Create streaming context for query_with (special: no user turn saved)
        # assistant_turn_idx is 0 since we don't save the user message
        exchange_id = str(uuid.uuid4())
        ctx = StreamingContext(
            session_id=new_session.id,
            user_turn_idx=-1,  # No user turn
            assistant_turn_idx=0,  # First turn is assistant
            prompt=prompt,
            is_active=True,
            exchange_id=exchange_id,
        )
        # Mark this as a query_with special case
        ctx.query_with = True
        self._streaming_contexts[new_session.id] = ctx

        # Update tree streaming indicator and status bar count
        context_tree.set_session_streaming(new_session.id, True)
        self._update_streaming_count()

        # Enable streaming mode (allows queueing prompts)
        input_box.set_streaming_mode(True)
        status_bar.set_streaming(True)
        self.streaming = True

        # Start assistant message (no user message shown - it's ephemeral)
        chat_log.add_assistant_message()

        # Start assistant turn in tree (no user turn for query_with)
        context_tree.start_turn(new_session.id, 0, "assistant", exchange_id=exchange_id)

        # Start background streaming - poll timer will handle events
        self._session_runner.start_background(prompt, selected_messages, allowed_tools)

    async def _handle_shell_command(self, cmd: str) -> None:
        """Run a shell command and submit output to Claude."""
        status_bar = self.query_one("#status-bar", StatusBar)

        # Use session's working directory if set
        cwd = self.session.working_directory if self.session.working_directory else None

        # Execute via CommandExecutor
        result = await self._command_executor.execute_shell(cmd, cwd)

        if result.was_cancelled:
            return

        if not result.success:
            # Still send error output to Claude
            prompt = f"# User executed shell command:\n```bash\n$ {cmd}\n```\n# Error:\n```\n{result.error}\n```"
            self._start_streaming(prompt)
            return

        # Use the formatted prompt from the result
        self._start_streaming(result.prompt)

    async def _generate_context_summary(self, messages: list) -> str:
        """Generate a summary of messages marked for summarization."""
        if self.session:
            self._summarizer.set_session_id(self.session.id)
        return await self._summarizer.generate_context_summary(messages)

    async def _build_context_with_summaries(
        self,
        indexed_messages: list[tuple],
        status_bar,
    ) -> list[Message]:
        """Build context messages with summaries inserted at their original positions.

        This handles the interleaving of COPY messages (kept verbatim) and COMPRESS
        messages (summarized). Non-contiguous COMPRESS groups become separate summaries,
        each inserted at the position of the first message in that group.

        Args:
            indexed_messages: List of (Message, original_index) tuples from
                              get_selected_messages_with_indices()
            status_bar: StatusBar widget for progress updates

        Returns:
            List of Message objects in correct order, with COMPRESS messages
            replaced by summary messages at appropriate positions.
        """
        if not indexed_messages:
            return []

        # Use the grouper to separate and group messages
        groups = group_messages_by_context_mode(indexed_messages)

        # Generate summaries for each COMPRESS group
        summary_items = []  # (summary_msg, insert_idx)
        if groups.needs_compression:
            self.notify("Compressing context...")

            for i, group in enumerate(groups.compress_groups):
                group_messages = [msg for msg, _ in group]
                first_idx = group[0][1]  # Position of first message in group

                summary = await self._generate_context_summary(group_messages)

                if summary:
                    summary_msg = Message(
                        role="user",
                        content=f"[Context Summary]\n{summary}",
                        content_blocks=[TextBlock(text=f"[Context Summary]\n{summary}")],
                    )
                    summary_items.append((summary_msg, first_idx))

        return build_context_messages(groups.copy_items, summary_items)

    async def _generate_merge_summary(self, fork_session: Session, user_prompt: str = "") -> str:
        """Generate a summary of what was accomplished in a fork."""
        # Set the fork session context for task tracking
        self._summarizer.set_session_id(fork_session.id)
        return await self._summarizer.generate_merge_summary(fork_session, user_prompt)

    # ===== FORK PROPOSAL HANDLING =====

    def _handle_fork_proposal(
        self,
        proposal: ForkProposal,
        tool_use_id: str,
        session_id: str,
        ctx: StreamingContext,
    ) -> None:
        """Handle a propose_fork tool call by creating an inline proposal turn.

        When the LLM calls propose_fork, we create a proposal turn in the
        conversation that the user can accept or reject inline via buttons.
        This replaces the modal dialog approach.
        """
        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)

        # Convert ForkProposal to persistable format
        context_plan_data = [
            ContextAssignmentData(
                exchange_range=a.exchange_range,
                mode=a.mode,
                reason=a.reason,
            )
            for a in (proposal.context_plan or [])
        ]

        bind_to_data = None
        bind_to_inherit = False
        if proposal.bind_to == "inherit":
            bind_to_inherit = True
        elif isinstance(proposal.bind_to, ForkBindingSpec):
            bind_to_data = ForkBindingData(
                entity_type=proposal.bind_to.entity_type,
                entity_id=proposal.bind_to.entity_id,
                role=proposal.bind_to.role,
            )

        # Generate a unique proposal ID
        proposal_id = str(uuid.uuid4())

        # Get the current session (need full Session object with methods, not SessionData)
        session = self._manager._sessions.get(session_id)
        if not session:
            self.notify("Session not found for proposal", severity="error")
            return

        # Get all exchanges for the interactive tree BEFORE adding the proposal turn
        # (excludes the current exchange which contains the proposal)
        all_exchanges = self._get_all_exchange_info(session_id, exclude_current=True)
        debug_log.info(
            f"_handle_fork_proposal: got all_exchanges",
            category="fork",
            details={
                "session_id": session_id,
                "all_exchanges_count": len(all_exchanges),
                "session_in_tree_state": session_id in self._tree_state._sessions,
            },
        )

        # Add the proposal as a turn in the session
        exchange_id = ctx.exchange_id if ctx else None
        turn = session.add_fork_proposal_turn(
            proposal_id=proposal_id,
            name=proposal.name,
            description=proposal.description,
            context_plan=context_plan_data,
            initial_prompt=proposal.initial_prompt or "",
            bind_to=bind_to_data,
            bind_to_inherit=bind_to_inherit,
            status="pending",
            exchange_id=exchange_id,
            all_exchanges=all_exchanges,
        )

        # Get the turn index for later reference
        turn_idx = len(session.turns) - 1

        # Update context tree using the same pattern as streaming:
        # start_turn creates the node, finish_turn updates with final content
        context_tree.start_turn(session_id, turn_idx, "system", exchange_id=exchange_id)
        context_tree.finish_turn(
            session_id, turn_idx, "[Fork proposal]", turn.content_block, []
        )

        # Store metadata for later use when accepting the proposal
        self._pending_fork_proposals[proposal_id] = {
            "proposal": proposal,
            "session_id": session_id,
            "ctx": ctx,
            "turn_idx": turn_idx,
        }

        # Add the proposal widget to the chat log
        widget = ForkProposalMarker(
            proposal_id=proposal_id,
            name=proposal.name,
            description=proposal.description,
            context_plan=context_plan_data,
            initial_prompt=proposal.initial_prompt or "",
            bind_to=bind_to_data,
            bind_to_inherit=bind_to_inherit,
            status="pending",
            turn_id=turn_idx,
            all_exchanges=all_exchanges,
        )
        chat_log.mount(widget)
        chat_log.scroll_end(animate=False)

        # Save the session
        asyncio.create_task(session.save())

        debug_log.info(
            f"Fork proposal turn created",
            category="fork",
            details={"proposal_id": proposal_id, "name": proposal.name},
        )

    def _get_exchange_summaries(self, session_id: str, exclude_current: bool = True) -> list[str]:
        """Get short summaries of each exchange for display in the proposal modal.

        Args:
            session_id: The session to get exchange summaries for
            exclude_current: If True, exclude the last exchange (the one containing
                           the fork proposal). This aligns with how Claude thinks
                           about exchanges when proposing a fork - "last" means
                           the last exchange before its current response.
        """
        summaries = []
        groups = self._tree_state.get_turns_grouped_by_exchange(session_id)

        # Exclude the current (proposal) exchange if requested
        if exclude_current and groups:
            groups = groups[:-1]

        for group in groups:
            if not group:
                continue
            # Get first meaningful content from the group
            first_turn = group[0]
            content = first_turn.content or ""
            # Truncate for display
            if len(content) > 80:
                content = content[:77] + "..."
            # Remove newlines for single-line display
            content = content.replace("\n", " ").strip()
            role = first_turn.role
            summaries.append(f"[{role}] {content}")

        return summaries

    def _get_all_exchange_info(self, session_id: str, exclude_current: bool = True) -> list[ExchangeInfo]:
        """Get ExchangeInfo for each exchange for display in fork proposal tree.

        Args:
            session_id: The session to get exchange info for
            exclude_current: If True, exclude the last exchange (the one containing
                           the fork proposal). This aligns with how Claude thinks
                           about exchanges when proposing a fork - "last" means
                           the last exchange before its current response.
        """
        exchanges = []

        # Ensure session is loaded before getting exchange groups.
        # If not loaded, fork proposal tree would show no exchanges.
        if not self._tree_state.is_session_loaded(session_id):
            debug_log.warning(
                f"Session not loaded in TreeState during _get_all_exchange_info - loading now",
                category="fork",
                details={"session_id": session_id},
            )
            session = self._manager.get_session(session_id)
            if session:
                self._tree_state.load_session(session_id, session)

        groups = self._tree_state.get_turns_grouped_by_exchange(session_id)

        debug_log.info(
            f"_get_all_exchange_info: got groups",
            category="fork",
            details={
                "session_id": session_id,
                "groups_count": len(groups),
            },
        )

        # Exclude the current (proposal) exchange if requested
        if exclude_current and groups:
            groups = groups[:-1]

        for idx, group in enumerate(groups):
            if not group:
                continue
            # Get first meaningful content from the group
            first_turn = group[0]
            content = first_turn.content or ""
            # Truncate for display
            if len(content) > 60:
                content = content[:57] + "..."
            # Remove newlines for single-line display
            content = content.replace("\n", " ").strip()
            role = first_turn.role
            summary = f"[{role}] {content}"
            exchanges.append(ExchangeInfo(
                index=idx,
                summary=summary,
                mode="compress",  # Default, will be overridden by context_plan
            ))

        return exchanges

    async def _execute_fork_proposal(
        self,
        proposal: ForkProposal,
        session_id: str,
        ctx: StreamingContext,
    ) -> None:
        """Execute an accepted fork proposal by setting context modes and creating the fork."""
        debug_log.info(
            f"_execute_fork_proposal started",
            category="fork",
            details={"proposal_name": proposal.name, "session_id": session_id},
        )
        status_bar = self.query_one("#status-bar", StatusBar)
        debug_log.info("_execute_fork_proposal: got status_bar", category="fork")

        # Ensure session is loaded in TreeState before getting exchange groups.
        # This is a defensive check - the session should already be loaded by _switch_to_session,
        # but if it's not, fork proposals would silently lose all context.
        if not self._tree_state.is_session_loaded(session_id):
            debug_log.warning(
                f"Session not loaded in TreeState during fork proposal - loading now",
                category="fork",
                details={"session_id": session_id},
            )
            session = self._manager.get_session(session_id)
            if session:
                self._tree_state.load_session(session_id, session)
            else:
                debug_log.error(
                    f"Cannot load session for fork proposal - session not found in manager",
                    category="fork",
                    details={"session_id": session_id},
                )
                self.notify("Fork failed: session not found", severity="error")
                return

        # Get exchange groups to map exchange indices to turn indices
        groups = self._tree_state.get_turns_grouped_by_exchange(session_id)
        total_exchanges = len(groups)
        debug_log.info(f"_execute_fork_proposal: got {total_exchanges} exchange groups", category="fork")

        # Resolve the proposal's context plan to exchange indices.
        # exclude_current=True because the proposal was made during the current
        # exchange, so "last" should refer to the previous exchange (the one
        # before Claude's response containing the proposal).
        exchange_modes = proposal.resolve_exchange_indices(total_exchanges, exclude_current=True)
        debug_log.info(f"_execute_fork_proposal: resolved {len(exchange_modes)} exchange modes", category="fork")

        # Apply context modes to all turns in each exchange
        # Use batch mode to suppress per-turn token recalculation (huge perf win)
        self._batch_context_mode_changes = True
        try:
            for exchange_idx, mode in exchange_modes.items():
                if exchange_idx < len(groups):
                    for turn in groups[exchange_idx]:
                        self._tree_state.set_context_mode(session_id, turn.idx, mode)
        finally:
            self._batch_context_mode_changes = False
        debug_log.info("_execute_fork_proposal: applied context modes", category="fork")

        # Now do one token update for all the changes
        self._update_base_context_tokens()
        self._update_context_tokens()
        debug_log.info("_execute_fork_proposal: updated tokens", category="fork")

        # Show confirmation
        self.notify(f"Creating fork: {proposal.name}")

        # Store pending binding to apply after fork creation
        if proposal.bind_to:
            self._pending_fork_bindings[proposal.name] = proposal.bind_to
            debug_log.info(
                f"Stored pending binding for fork proposal",
                category="fork",
                details={"fork_name": proposal.name, "bind_to": str(proposal.bind_to)},
            )

        # Build session context to inject into the prompt so Claude knows it's in a fork
        parent_name = self.session.title or self.session.fork_name or self.session.id[:8]
        session_context_lines = [
            "[Session Context]",
            f"You are now in fork: {proposal.name}",
            f"Parent session: {parent_name}",
            f"Purpose: {proposal.description}",
        ]

        # Add binding info if present
        if proposal.bind_to:
            from core.fork import ForkBindingSpec
            if isinstance(proposal.bind_to, ForkBindingSpec):
                session_context_lines.append(
                    f"Bound to: {proposal.bind_to.entity_type} {proposal.bind_to.entity_id} (role: {proposal.bind_to.role})"
                )
            elif proposal.bind_to == "inherit":
                session_context_lines.append("Binding: inherited from parent")

        session_context_lines.append("")  # Blank line before user content
        session_context = "\n".join(session_context_lines)

        # Create the fork with the proposal's settings
        # Use initial_prompt if provided, otherwise a default
        user_prompt = proposal.initial_prompt or f"Continue with: {proposal.description}"
        prompt = f"{session_context}\n{user_prompt}"
        debug_log.info(
            f"_execute_fork_proposal calling _handle_fork_command",
            category="fork",
            details={"proposal_name": proposal.name},
        )
        await self._handle_fork_command(
            prompt=prompt,
            name=proposal.name,
            background=False,
        )
        debug_log.info(
            f"_execute_fork_proposal completed",
            category="fork",
            details={"proposal_name": proposal.name},
        )

    # ===== MERGE PROPOSAL HANDLING =====

    def _handle_merge_proposal(
        self,
        proposal: MergeProposal,
        tool_use_id: str,
        session_id: str,
        ctx: StreamingContext,
    ) -> None:
        """Handle a propose_merge tool call by creating an inline proposal turn.

        When the LLM calls propose_merge, we create a proposal turn in the
        conversation that the user can accept or reject inline via buttons.
        This replaces the modal dialog approach.
        """
        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)

        # Validate that we're in a fork
        if not self.session.is_fork():
            self.notify("Cannot merge: not in a fork", severity="error")
            return

        # Allow re-merging (updated fork status after each merge)
        # No longer block on is_merged()

        # Generate a unique proposal ID
        proposal_id = str(uuid.uuid4())

        # Add the proposal as a turn in the session
        exchange_id = ctx.exchange_id if ctx else None
        turn = self.session.add_merge_proposal_turn(
            proposal_id=proposal_id,
            summary=proposal.summary,
            reason=proposal.reason,
            files_changed=proposal.files_changed,
            key_accomplishments=proposal.key_accomplishments,
            status="pending",
            exchange_id=exchange_id,
        )

        # Update context tree using the same pattern as streaming:
        # start_turn creates the node, finish_turn updates with final content
        turn_idx = len(self.session.turns) - 1
        context_tree.start_turn(session_id, turn_idx, "system", exchange_id=exchange_id)
        context_tree.finish_turn(
            session_id, turn_idx, "[Merge proposal]", turn.content_block, []
        )

        # Store metadata for later use when accepting the proposal
        self._pending_merge_proposals[proposal_id] = {
            "proposal": proposal,
            "session_id": session_id,
            "ctx": ctx,
            "turn_idx": turn_idx,
        }

        # Add the proposal widget to the chat log
        widget = MergeProposalMarker(
            proposal_id=proposal_id,
            summary=proposal.summary,
            reason=proposal.reason,
            files_changed=proposal.files_changed,
            key_accomplishments=proposal.key_accomplishments,
            status="pending",
            turn_id=turn_idx,
        )
        chat_log.mount(widget)
        chat_log.scroll_end(animate=False)

        # Save the session
        asyncio.create_task(self.session.save())

        debug_log.info(
            f"Merge proposal turn created",
            category="merge",
            details={"proposal_id": proposal_id},
        )

    async def _execute_merge_proposal(
        self,
        summary: str,
        files_changed: list[str] | None = None,
        key_accomplishments: list[str] | None = None,
        reason: str = "",
    ) -> None:
        """Execute an accepted merge proposal with the given summary."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Validate merge via ForkManager
        prep_result = await self._fork_manager.prepare_merge(self.session)
        if not prep_result.success:
            self.notify(prep_result.error, severity="error")
            return

        # Complete the merge with the provided summary and metadata
        result = await self._fork_manager.complete_merge(
            fork_session=prep_result.fork_session,
            parent_session=prep_result.parent_session,
            merge_message=summary,
            files_changed=files_changed,
            key_accomplishments=key_accomplishments,
            reason=reason,
        )

        # Switch to parent
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
        self._manager._sessions[result.parent_session.id] = result.parent_session
        self._manager._runners[result.parent_session.id] = self._create_session_runner(result.parent_session)
        await self._manager.set_active(result.parent_session.id)
        chat_log.clear()
        await chat_log.load_history(result.parent_session.turns, session=result.parent_session)
        await context_tree.load_all_sessions(result.parent_session)
        await breadcrumb.set_session(result.parent_session)

        self.notify(f"Merged from '{result.fork_name}'")

    # ===== FORK/MERGE COMMANDS =====

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
        debug_log.info(
            f"_handle_fork_command started",
            category="fork",
            details={"name": name, "background": background},
        )
        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Get selected messages and tools from UI
        indexed_messages = context_tree.get_selected_messages_with_indices()
        allowed_tools = self._get_enabled_tools()

        # Count messages by context mode for debugging
        mode_counts = {"copy": 0, "compress": 0}
        for msg, _ in indexed_messages:
            if hasattr(msg, 'context_mode') and msg.context_mode:
                mode_name = msg.context_mode.name.lower()
                if mode_name in mode_counts:
                    mode_counts[mode_name] += 1

        # Prepare fork via ForkManager (handles validation and session creation)
        debug_log.info(
            f"_handle_fork_command calling prepare_fork",
            category="fork",
            details={"name": name, "indexed_messages_count": len(indexed_messages), "mode_counts": mode_counts},
        )
        result = await self._fork_manager.prepare_fork(
            current_session=self.session,
            indexed_messages=indexed_messages,
            prompt=prompt,
            allowed_tools=allowed_tools,
            name=name,
            background=background,
        )
        debug_log.info(
            f"_handle_fork_command prepare_fork returned",
            category="fork",
            details={
                "success": result.success,
                "needs_compression": result.needs_compression,
                "error": result.error,
            },
        )

        if not result.success:
            self.notify(result.error, severity="error")
            return

        if not result.needs_compression:
            # No compression - proceed with UI updates
            debug_log.info(f"_handle_fork_command calling _complete_fork_ui", category="fork")
            await self._complete_fork_ui(result, chat_log, context_tree, status_bar)
            debug_log.info(f"_handle_fork_command _complete_fork_ui returned", category="fork")
        else:
            # Compression needed - start helper streaming
            debug_log.info(
                f"_handle_fork_command starting compression helper",
                category="fork",
                details={"helper_id": result.helper_id},
            )
            helper_runner = HelperRunner(result.helper_id, runner=create_runner(self._backend_config))
            self._helper_runners[result.helper_id] = helper_runner

            # Create streaming context for the helper
            ctx = StreamingContext(
                session_id=result.helper_id,
                user_turn_idx=-1,
                assistant_turn_idx=-1,
                prompt="",
                is_active=True,
                is_helper=True,
                helper_type="compress",
                fork_data=result.fork_data,
            )
            self._streaming_contexts[result.helper_id] = ctx

            # Set up UI for compression streaming
            status_bar.set_streaming(True)
            self.streaming = True

            chat_log.add_user_message("[Compressing context for fork...]")
            chat_log.add_assistant_message()
            debug_log.info(
                f"_handle_fork_command compression helper started",
                category="fork",
                details={"helper_id": result.helper_id},
            )

            helper_runner.start_background(result.compression_prompt)

    async def _complete_fork_ui(self, result: ForkResult, chat_log: ChatLogView, context_tree: ContextTreeView, status_bar: StatusBar) -> None:
        """Complete fork UI updates after business logic is done.

        Called either directly (no compression) or after compression helper completes.
        """
        child_session = result.child_session
        parent_session = result.parent_session

        # Add fork marker to parent's chat log
        chat_log.add_fork_marker(
            prompt=result.prompt,
            child_session_id=child_session.id,
            fork_name=result.name or child_session.id[:8],
            status="active" if not result.background else "background",
        )

        # Register child session with manager
        self._manager._sessions[child_session.id] = child_session
        self._manager._runners[child_session.id] = self._create_session_runner(child_session)

        if result.background:
            # Background mode - stay in parent
            turn_idx = len(child_session.turns)
            exchange_id = str(uuid.uuid4())  # Group user + assistant turns
            ctx = StreamingContext(
                session_id=child_session.id,
                user_turn_idx=turn_idx,
                assistant_turn_idx=turn_idx + 1,
                prompt=result.prompt,
                is_active=False,
                exchange_id=exchange_id,
            )
            self._streaming_contexts[child_session.id] = ctx

            # Add child session to TreeState so it appears in the tree
            # This must happen before set_session_streaming so the node exists
            self._tree_state.add_session(child_session, is_current=False)
            self._tree_state.load_session(child_session.id, child_session)

            context_tree.set_session_streaming(child_session.id, True)
            self._update_streaming_count()

            context_tree.start_turn(child_session.id, turn_idx, "user", exchange_id=exchange_id)
            context_tree.finish_turn(
                child_session.id, turn_idx, result.prompt, TextBlock(text=result.prompt), []
            )
            context_tree.start_turn(child_session.id, turn_idx + 1, "assistant", exchange_id=exchange_id)

            # Add user message to child session before streaming starts
            # This ensures it's persisted even if we crash mid-exchange
            user_blocks = [TextBlock(text=result.prompt)]
            child_session.add_message("user", result.prompt, content_blocks=user_blocks, exchange_id=exchange_id)
            asyncio.create_task(child_session.save())

            child_runner = self._manager._runners[child_session.id]
            child_runner.start_background(
                prompt=result.prompt,
                messages=child_session.turns,
                allowed_tools=result.allowed_tools,
            )
            self.notify(f"Fork '{result.name or child_session.id[:8]}' started in background")
        else:
            # Foreground mode - switch to child
            asyncio.create_task(child_session.save())  # Ensure recent timestamp

            # Apply pending binding if any
            await self._apply_pending_fork_binding(result.name, child_session, parent_session)

            breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
            await self._manager.set_active(child_session.id)
            chat_log.clear()
            await chat_log.load_history(child_session.turns, session=child_session)
            await context_tree.load_all_sessions(child_session)
            await breadcrumb.set_session(child_session)

            self._start_streaming(result.prompt)

    async def _apply_pending_fork_binding(
        self,
        fork_name: str,
        child_session: Session,
        parent_session: Session,
    ) -> None:
        """Apply a pending binding to a newly created fork.

        Called after fork creation to bind the child session to a goal/plan/todo.
        Supports "inherit" to copy the parent's binding, or explicit binding spec.
        """
        debug_log.info(
            f"_apply_pending_fork_binding called",
            category="fork",
            details={"fork_name": fork_name, "pending_keys": list(self._pending_fork_bindings.keys())},
        )
        bind_to = self._pending_fork_bindings.pop(fork_name, None)
        if not bind_to:
            debug_log.info(
                f"No pending binding found for fork",
                category="fork",
                details={"fork_name": fork_name},
            )
            return
        debug_log.info(
            f"Found pending binding for fork",
            category="fork",
            details={"fork_name": fork_name, "bind_to": str(bind_to)},
        )

        from core.fork import ForkBindingSpec
        from core.async_storage import get_goal_storage
        from storage_schema import SessionBinding
        from datetime import datetime
        import uuid as uuid_mod

        storage = await get_goal_storage()

        if bind_to == "inherit":
            # Copy parent's active bindings
            parent_bindings = await storage.get_bindings_for_session(
                parent_session.id, active_only=True
            )
            for parent_binding in parent_bindings:
                new_binding = SessionBinding(
                    id=str(uuid_mod.uuid4()),
                    session_id=child_session.id,
                    entity_type=parent_binding.entity_type,
                    entity_id=parent_binding.entity_id,
                    role=parent_binding.role,
                    created_at=datetime.now().isoformat(),
                )
                await storage.save_session_binding(new_binding)
                debug_log.info(
                    f"Inherited binding to {parent_binding.entity_type} with role {parent_binding.role}",
                    category="fork",
                )
        elif isinstance(bind_to, ForkBindingSpec):
            # Create explicit binding
            # Resolve entity ID prefix if needed
            entity_id = bind_to.entity_id
            if bind_to.entity_type == "goal":
                goals = await storage.list_goals()
                for g in goals:
                    if g.id.startswith(entity_id):
                        entity_id = g.id
                        break
            elif bind_to.entity_type == "plan":
                plans = await storage.list_plans()
                for p in plans:
                    if p.id.startswith(entity_id):
                        entity_id = p.id
                        break
            elif bind_to.entity_type == "todo":
                todos = await storage.list_todos()
                for t in todos:
                    if t.id.startswith(entity_id):
                        entity_id = t.id
                        break

            new_binding = SessionBinding(
                id=str(uuid_mod.uuid4()),
                session_id=child_session.id,
                entity_type=bind_to.entity_type,
                entity_id=entity_id,
                role=bind_to.role,
                created_at=datetime.now().isoformat(),
            )
            await storage.save_session_binding(new_binding)
            debug_log.info(
                f"Created binding to {bind_to.entity_type} {entity_id} with role {bind_to.role}",
                category="fork",
            )

    async def _handle_merge_command(self, prompt: str = "") -> None:
        """Merge fork back to parent.

        The LLM generates a summary of what was accomplished in the fork.
        Optional prompt guides the summary generation.
        After merge:
        - Fork becomes read-only
        - View switches to parent
        - Merge marker appears in parent with LLM summary

        Uses non-blocking helper runner pattern to generate summary.
        """
        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Validate merge via ForkManager
        prep_result = await self._fork_manager.prepare_merge(self.session)
        if not prep_result.success:
            self.notify(prep_result.error, severity="error")
            return

        # Build the summary prompt (non-blocking)
        summary_prompt = self._summarizer.build_merge_summary_prompt(self.session, prompt)

        # Create helper runner for background summary generation
        helper_id = f"merge-{uuid.uuid4().hex[:8]}"
        helper_runner = HelperRunner(helper_id, runner=create_runner(self._backend_config))
        self._helper_runners[helper_id] = helper_runner

        # Create streaming context with merge data
        ctx = StreamingContext(
            session_id=helper_id,
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_active=True,
            is_helper=True,
            helper_type="merge",
            merge_data=MergeData(
                fork_session_id=prep_result.fork_session.id,
                parent_session_id=prep_result.parent_session.id,
                fork_name=prep_result.fork_session.get_fork_display_name(),
            ),
        )
        self._streaming_contexts[helper_id] = ctx

        # Set up UI for merge summary streaming
        status_bar.set_streaming(True)
        self.streaming = True

        chat_log.add_user_message("[Generating merge summary...]")
        chat_log.add_assistant_message()

        # Start background streaming
        helper_runner.start_background(summary_prompt)

    async def _handle_derive_command(self, prompt: str) -> None:
        """Create a new independent session with selected context.

        Like fork but no parent relationship - won't merge back.
        Context is built with summaries inserted at their original positions,
        preserving message order and interleaving.

        If COMPRESS messages exist, shows the compression streaming in the UI
        before creating the derived session. This avoids UI blocking.
        """
        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Get selected messages and tools from UI
        indexed_messages = context_tree.get_selected_messages_with_indices()
        allowed_tools = self._get_enabled_tools()

        # Prepare derive via ForkManager
        result = await self._fork_manager.prepare_derive(
            indexed_messages=indexed_messages,
            prompt=prompt,
            allowed_tools=allowed_tools,
        )

        if not result.success:
            self.notify(result.error, severity="error")
            return

        if not result.needs_compression:
            # No compression - proceed with UI updates
            await self._complete_derive_ui(result, chat_log, context_tree)
        else:
            # Compression needed - start helper streaming
            helper_runner = HelperRunner(result.helper_id, runner=create_runner(self._backend_config))
            self._helper_runners[result.helper_id] = helper_runner

            ctx = StreamingContext(
                session_id=result.helper_id,
                user_turn_idx=-1,
                assistant_turn_idx=-1,
                prompt="",
                is_active=True,
                is_helper=True,
                helper_type="derive",
                fork_data=result.derive_data,
            )
            self._streaming_contexts[result.helper_id] = ctx

            status_bar.set_streaming(True)
            self.streaming = True

            chat_log.add_user_message("[Compressing context for new session...]")
            chat_log.add_assistant_message()

            helper_runner.start_background(result.compression_prompt)

    async def _complete_derive_ui(self, result: DeriveResult, chat_log: ChatLogView, context_tree: ContextTreeView) -> None:
        """Complete derive UI updates after business logic is done."""
        new_session = result.new_session

        # Register and switch to new session
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
        self._manager._sessions[new_session.id] = new_session
        self._manager._runners[new_session.id] = self._create_session_runner(new_session)
        await self._manager.set_active(new_session.id)

        chat_log.clear()
        await chat_log.load_history(new_session.turns, session=new_session)
        await context_tree.load_all_sessions(new_session)
        await breadcrumb.set_session(new_session)

        self._start_streaming(result.prompt)

    async def _handle_switch_command(self, name: str = "") -> None:
        """Switch view to a different session or fork.

        Args:
            name: Fork name or session ID prefix. Empty shows picker.
        """
        status_bar = self.query_one("#status-bar", StatusBar)

        # Use ForkManager to find target
        result = await self._fork_manager.find_switch_target(self.session, name)

        if not name:
            # List available forks
            if result.available_forks:
                fork_list = ", ".join(
                    f.get("name") or f.get("session_id", "")[:8]
                    for f in result.available_forks
                )
                self.notify(f"Forks: {fork_list}")
            else:
                self.notify("No forks in current session")
            return

        if result.success:
            await self._switch_to_session(result.target_session)
        else:
            self.notify(result.error, severity="error")

    # ===== END NEW COMMANDS =====

    async def _handle_return_command(self, return_prompt: str = "") -> None:
        """Return from child session to parent.

        Uses non-blocking helper runner pattern to generate summary.
        """
        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Check we're in a child session
        if not self.session.is_child_session():
            self.notify("Not in a child session", severity="error")
            return

        # Get parent session ID before we start
        parent = await self.session.get_parent_async()
        if not parent:
            self.notify("Parent session not found", severity="error")
            return

        # Get selected messages from context tree for return content
        selected_messages = context_tree.get_selected_messages()

        # Build the summary prompt (non-blocking)
        summary_prompt = self._summarizer.build_return_summary_prompt(selected_messages, return_prompt)

        # Create helper runner for background summary generation
        helper_id = f"return-{uuid.uuid4().hex[:8]}"
        helper_runner = HelperRunner(helper_id, runner=create_runner(self._backend_config))
        self._helper_runners[helper_id] = helper_runner

        # Create streaming context with return data
        ctx = StreamingContext(
            session_id=helper_id,
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_active=True,
            is_helper=True,
            helper_type="return",
            return_data=ReturnData(
                child_session_id=self.session.id,
                parent_session_id=parent.id,
                return_prompt=return_prompt,
            ),
        )
        self._streaming_contexts[helper_id] = ctx

        # Set up UI for return summary streaming
        status_bar.set_streaming(True)
        self.streaming = True

        chat_log.add_user_message("[Generating return summary...]")
        chat_log.add_assistant_message()

        # Start background streaming
        helper_runner.start_background(summary_prompt)

    async def _generate_return_summary(self, messages: list, return_prompt: str) -> str:
        """Generate a summary of selected messages using Claude."""
        if self.session:
            self._summarizer.set_session_id(self.session.id)
        return await self._summarizer.generate_return_summary(messages, return_prompt)

    def _check_auto_return(self, response_content: str) -> bool:
        """Check if auto-return condition is met. Delegates to Session."""
        return self.session.check_auto_return(response_content)

    async def on_with_widget_child_clicked(self, event: WithWidget.ChildClicked) -> None:
        """Handle clicking on WithWidget to navigate to child session."""
        child_session = await Session.load(event.child_session_id)
        if child_session:
            await self._switch_to_session(child_session)

    async def on_with_result_widget_child_clicked(self, event: WithResultWidget.ChildClicked) -> None:
        """Handle clicking on WithResultWidget to navigate to child session."""
        child_session = await Session.load(event.child_session_id)
        if child_session:
            await self._switch_to_session(child_session)

    async def on_fork_marker_child_clicked(self, event: ForkMarker.ChildClicked) -> None:
        """Handle clicking on ForkMarker to navigate to the fork."""
        child_session = await Session.load(event.child_session_id)
        if child_session:
            await self._switch_to_session(child_session)

    async def on_link_marker_linked_session_clicked(self, event: LinkMarker.LinkedSessionClicked) -> None:
        """Handle clicking on LinkMarker to navigate to the linked session."""
        linked_session = await Session.load(event.linked_session_id)
        if linked_session:
            await self._switch_to_session(linked_session)
            # TODO: Could scroll to the link_point turn in the target session

    async def on_merge_marker_child_clicked(self, event: MergeMarker.ChildClicked) -> None:
        """Handle clicking on MergeMarker to navigate to the (read-only) fork."""
        child_session = await Session.load(event.child_session_id)
        if child_session:
            await self._switch_to_session(child_session)

    async def on_review_marker_child_clicked(self, event: ReviewMarker.ChildClicked) -> None:
        """Handle clicking on ReviewMarker to navigate to the review session."""
        child_session = await Session.load(event.child_session_id)
        if child_session:
            await self._switch_to_session(child_session)

    async def on_fork_proposal_marker_accepted(self, event: ForkProposalMarker.Accepted) -> None:
        """Handle accepting a fork proposal."""
        debug_log.info(
            f"Fork proposal accepted",
            category="fork",
            details={"proposal_id": event.proposal_id, "name": event.name},
        )

        # Look up the pending proposal data
        proposal_data = self._pending_fork_proposals.pop(event.proposal_id, None)
        if not proposal_data:
            # Proposal not found in pending - might be from a reloaded session
            # Try to reconstruct from the event data
            self.notify(f"Creating fork: {event.name}")

            # Need to get the original ForkProposal and ctx
            # For now, we'll create a minimal one from the event data
            from core.fork import ForkProposal, ContextAssignment

            # Convert back to ForkProposal format
            context_plan = [
                ContextAssignment(
                    exchange_range=a.exchange_range,
                    mode=a.mode,
                    reason=a.reason,
                )
                for a in event.context_plan
            ]

            # Convert binding data back to ForkBindingSpec or "inherit"
            bind_to = None
            if event.bind_to_inherit:
                bind_to = "inherit"
            elif event.bind_to:
                bind_to = ForkBindingSpec(
                    entity_type=event.bind_to.entity_type,
                    entity_id=event.bind_to.entity_id,
                    role=event.bind_to.role,
                )

            proposal = ForkProposal(
                name=event.name,
                description=event.description,
                context_plan=context_plan,
                initial_prompt=event.initial_prompt,
                bind_to=bind_to,
            )

            session_id = self.session.id if self.session else None
            if not session_id:
                self.notify("No active session", severity="error")
                return

            ctx = None  # No streaming context available for reloaded proposals
        else:
            proposal = proposal_data["proposal"]
            session_id = proposal_data["session_id"]
            ctx = proposal_data.get("ctx")

        # Update the proposal status in the session (need full Session object with methods)
        session = self._manager._sessions.get(session_id)
        if session:
            session.update_fork_proposal_status(event.proposal_id, "accepted")
            await session.save()

        # Execute the fork
        try:
            await self._execute_fork_proposal(proposal, session_id, ctx)
        except Exception as e:
            import traceback
            debug_log.error(
                f"_execute_fork_proposal failed: {e}",
                category="fork",
                details={"traceback": traceback.format_exc()},
            )
            self.notify(f"Fork creation failed: {e}", severity="error")

    async def on_fork_proposal_marker_rejected(self, event: ForkProposalMarker.Rejected) -> None:
        """Handle rejecting a fork proposal."""
        debug_log.info(
            f"Fork proposal rejected",
            category="fork",
            details={"proposal_id": event.proposal_id},
        )

        # Remove from pending
        self._pending_fork_proposals.pop(event.proposal_id, None)

        # Update the proposal status in the session
        if self.session:
            self.session.update_fork_proposal_status(event.proposal_id, "rejected")
            await self.session.save()

        # Notify the user
        self.notify("Fork proposal rejected")

        # Add rejection message to chat so Claude knows
        chat_log = self.query_one("#chat-log", ChatLogView)
        chat_log.add_user_message("[Fork proposal rejected by user]")

    async def on_merge_proposal_marker_accepted(self, event: MergeProposalMarker.Accepted) -> None:
        """Handle accepting a merge proposal."""
        debug_log.info(
            f"Merge proposal accepted",
            category="merge",
            details={"proposal_id": event.proposal_id, "summary_length": len(event.summary)},
        )

        # Remove from pending
        self._pending_merge_proposals.pop(event.proposal_id, None)

        # Update the proposal status in the session
        if self.session:
            self.session.update_merge_proposal_status(event.proposal_id, "accepted")
            await self.session.save()

        # Execute the merge
        try:
            await self._execute_merge_proposal(
                summary=event.summary,
                files_changed=event.files_changed,
                key_accomplishments=event.key_accomplishments,
                reason=event.reason,
            )
        except Exception as e:
            import traceback
            debug_log.error(
                f"_execute_merge_proposal failed: {e}",
                category="merge",
                details={"traceback": traceback.format_exc()},
            )
            self.notify(f"Merge failed: {e}", severity="error")

    async def on_merge_proposal_marker_rejected(self, event: MergeProposalMarker.Rejected) -> None:
        """Handle rejecting a merge proposal."""
        debug_log.info(
            f"Merge proposal rejected",
            category="merge",
            details={"proposal_id": event.proposal_id},
        )

        # Remove from pending
        self._pending_merge_proposals.pop(event.proposal_id, None)

        # Update the proposal status in the session
        if self.session:
            self.session.update_merge_proposal_status(event.proposal_id, "rejected")
            await self.session.save()

        # Notify the user
        self.notify("Merge proposal rejected")

        # Add rejection message to chat so Claude knows
        chat_log = self.query_one("#chat-log", ChatLogView)
        chat_log.add_user_message("[Merge proposal rejected by user]")

    async def on_archive_marker_rehydrate_requested(self, event: ArchiveMarker.RehydrateRequested) -> None:
        """Handle ctrl+shift+click on ArchiveMarker to rehydrate archived turns."""
        from core.archiver import Archiver, ArchiveError

        debug_log.info(
            f"Rehydrating archive {event.archive_id} at turn {event.turn_index}",
            category="archive",
            details={"file_path": event.file_path},
        )

        archiver = Archiver()
        try:
            # Rehydrate the archive
            new_turns = archiver.rehydrate(self.session.turns, event.turn_index)
            self.session.turns = new_turns
            await self.session.save()

            debug_log.info(
                f"Rehydrated archive from {event.file_path}",
                category="archive",
                details={"turn_count": len(new_turns)},
            )

            # Reload the UI first so TreeState has updated turns
            chat_log = self.query_one("#chat-log", ChatLogView)
            chat_log.clear()
            await chat_log.load_history(self.session.turns, self.session)

            # Update context tree
            context_tree = self.query_one("#context-tree", ContextTreeView)
            await context_tree.load_all_sessions(self.session)

            # Recalculate token count after rehydration (turns restored)
            # Must be after tree reload so TreeState has the new turns
            self._update_base_context_tokens()
            self._update_context_tokens()

            self.notify(f"Restored archived turns from {event.file_path}")

        except ArchiveError as e:
            debug_log.error(f"Rehydration failed: {e}", category="archive")
            self.notify(f"Failed to rehydrate: {e}", severity="error")

    def _background_old_session(self, old_session_id: str | None) -> None:
        """Mark old session's streaming context as inactive and sync queue state.

        This should be called before switching away from a session to ensure:
        1. Streaming events go to background widgets instead of main chat log
        2. Queue state is persisted to the session's message_queue
        """
        if not old_session_id:
            return

        # Mark streaming context as inactive
        old_ctx = self._streaming_contexts.get(old_session_id)
        if old_ctx:
            old_ctx.is_active = False
            debug_log.info(
                f"Backgrounding streaming session {old_session_id[:8]}",
                category="stream",
                session_id=old_session_id,
            )

        # Sync queue state to old session's message_queue before switching
        old_session = self._manager._sessions.get(old_session_id)
        if old_session:
            self._queue_state.sync_to_message_queue(old_session_id, old_session.message_queue)
            # Save async to persist the queue (safe even while streaming - only saving queue)
            asyncio.create_task(old_session.save())

    async def _switch_to_session(self, session: Session, target_turn_index: int | None = None) -> None:
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
                "turns": len(session.turns),
            },
        )

        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
        input_box = self.query_one("#input-box", InputBox)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Background old session (mark streaming as inactive, sync queue)
        self._background_old_session(old_session_id)

        # Show loading indicator while switching
        chat_log.show_loading("Switching session...")

        # Register session with manager if not already known
        if session.id not in self._manager._sessions:
            self._manager._sessions[session.id] = session
            self._manager._runners[session.id] = self._create_session_runner(session)
        await self._manager.set_active(session.id)

        # Pre-seed TreeState with cached token count before switching
        # This ensures the tree displays correct count immediately
        if session.cached_context_tokens > 0:
            self._tree_state.set_context_tokens(session.cached_context_tokens, 0)

        # IMPORTANT: Ensure session is loaded in TreeState before setting it active.
        # Without this, get_turns_grouped_by_exchange() returns empty, breaking fork proposals.
        # The session object has been loaded from disk (with turns), but TreeState may only
        # have metadata if the session was added via add_session_from_metadata().
        if not self._tree_state.is_session_loaded(session.id):
            self._tree_state.load_session(session.id, session)

        context_tree.set_active_session(session.id)

        # Update QueueState for the new session
        # Sync from persistence if this session has queued messages
        self._queue_state.sync_from_message_queue(session.id, session.message_queue)
        self._queue_state.set_active_session(session.id)

        # Update breadcrumb to show current position in hierarchy
        await breadcrumb.set_session(session)

        # Load session turns (this also hides the loading indicator)
        await chat_log.load_history(session.turns, session=session)

        # Update scrollbar markers for unviewed turns
        self._update_unviewed_markers()

        # Check if NEW session is currently streaming
        new_ctx = self._streaming_contexts.get(session.id)
        if new_ctx:
            # Resume streaming display for this session
            new_ctx.is_active = True
            self.streaming = True
            input_box.set_streaming_mode(True)
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
            # New session is not streaming - exit streaming mode
            self.streaming = False
            input_box.set_streaming_mode(False)
            status_bar.set_streaming(False)

        # Update working directory in status bar
        status_bar.update_working_directory(session.working_directory or "")

        # Update status bar with session's model/backend and ensure runner uses correct backend
        try:
            session_backend = self._get_backend_for_session(session)
        except BackendNotFoundError as e:
            # Backend no longer exists - warn user and fall back to default
            self.notify(f"Backend '{e.backend_name}' not found, using default", severity="warning")
            debug_log.info(
                f"Session backend '{e.backend_name}' not found, falling back to default",
                category="session",
                session_id=session.id,
            )
            # Clear the invalid backend from the session
            session.backend_name = ""
            asyncio.create_task(session.save())
            session_backend = self._backend_config

        status_bar.update_stats(
            backend=session_backend.name if session_backend.name != "claude" else "",
            model=session.model or session_backend.model or "",
        )

        # Ensure the session's runner uses the correct backend
        # The SessionManager always creates runners with the default backend, so we need
        # to recreate the runner if the session specifies a different backend
        if session.backend_name and session.backend_name != self._backend_config.name:
            self._manager._runners[session.id] = self._create_session_runner(session)

        # Update header with session title
        chat_log.set_session_title(session.title)

        # Build turn_modes dict for visual indication
        session_data = context_tree._state.get_session(session.id)
        if session_data and session_data.is_loaded and session_data.turns:
            turn_modes = {}
            for turn in session_data.turns:
                turn_id = turn.idx + 1  # 1-indexed for chat_log
                mode = context_tree._state.get_context_mode(session.id, turn.idx)
                turn_modes[turn_id] = mode.name
            chat_log.set_turn_context_modes(turn_modes)

        # Update context tokens for the new session (use cache on switch)
        self._update_base_context_tokens(use_cache=True)
        self._update_context_tokens()

        # Save the new view position
        # Default to last turn if no target specified
        turn_index = target_turn_index
        if turn_index is None and session.turns:
            turn_index = len(session.turns) - 1
        save_last_view(session.id, turn_index)

        # Scroll to target turn if specified
        if target_turn_index is not None and target_turn_index < len(session.turns):
            turn_id = target_turn_index + 1  # 1-indexed for chat_log
            # Use default argument to capture turn_id value (avoid late binding)
            self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))

        # Update slides pane with the new session
        self._refresh_slides_pane()

        # Update queue popup for the new session
        self._update_queue_indicator()

        # Check priority divergence and update binding indicator for the new session
        asyncio.create_task(self._update_priority_divergence(session.id))
        asyncio.create_task(self._update_session_binding_indicator(session.id))

    async def _update_priority_divergence(self, session_id: str) -> None:
        """Check if session is working on a non-highest-priority todo.

        Updates the status bar with a warning if there's a higher priority
        todo that should be worked on instead.
        """
        try:
            info = await check_priority_divergence(session_id)
            status_bar = self.query_one("#status-bar", StatusBar)
            if info.is_diverged:
                status_bar.set_priority_divergence(info.message)
            else:
                status_bar.set_priority_divergence("")
        except Exception:
            # Don't let priority check errors break session switching
            pass

    def on_context_tree_view_selection_changed(self, event: ContextTreeView.SelectionChanged) -> None:
        """Handle tree selection changes - apply visual context mode indicators."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        # Use visual indication instead of hiding
        chat_log.set_turn_context_modes(event.turn_modes)
        # Token count already updated via TreeState observer

    def on_chat_log_view_context_mode_toggle_requested(self, event: ChatLogView.ContextModeToggleRequested) -> None:
        """Handle click on chat widget to toggle its context mode."""
        if not self.session:
            return

        context_tree = self.query_one("#context-tree", ContextTreeView)
        # Convert 1-indexed turn_id to 0-indexed turn_idx
        turn_idx = event.turn_id - 1
        turn_key = (self.session.id, turn_idx)

        # Cycle through context modes: COPY -> COMPRESS -> DROP -> COPY
        current_mode = context_tree._state.get_context_mode(self.session.id, turn_idx)
        if current_mode == ContextMode.COPY:
            new_mode = ContextMode.COMPRESS
            context_tree._state.set_context_mode(self.session.id, turn_idx, new_mode)
        elif current_mode in (ContextMode.COMPRESS, ContextMode.SUMMARIZE):
            new_mode = ContextMode.DROP
            context_tree._state.remove_context_mode(self.session.id, turn_idx)
        else:  # DROP
            new_mode = ContextMode.COPY
            context_tree._state.set_context_mode(self.session.id, turn_idx, new_mode)

        # Persist to session turn and save
        if turn_idx < len(self.session.turns):
            self.session.turns[turn_idx].context_mode = new_mode
            asyncio.create_task(self.session.save())

        # Update tree label - root label and token count updated via TreeState observer
        context_tree._update_turn_label(self.session.id, turn_idx)

    def on_chat_log_view_turn_clicked(self, event: ChatLogView.TurnClicked) -> None:
        """Handle click on chat widget to highlight the turn in the tree."""
        if not self.session:
            return

        # Break out of follow mode when user clicks a turn
        chat_log = self.query_one("#chat-log", ChatLogView)
        chat_log.following = False

        context_tree = self.query_one("#context-tree", ContextTreeView)
        # Convert 1-indexed turn_id to 0-indexed turn_idx
        turn_idx = event.turn_id - 1
        context_tree.scroll_to_turn(self.session.id, turn_idx)

    async def on_context_tree_view_context_mode_changed(self, event: ContextTreeView.ContextModeChanged) -> None:
        """Handle context mode change from tree - persist to session."""
        # Use in-memory session if it's the current one, otherwise load from disk
        if self.session and self.session.id == event.session_id:
            session = self.session
        else:
            session = await Session.load(event.session_id)

        if session and event.turn_idx < len(session.turns):
            session.turns[event.turn_idx].context_mode = event.new_mode
            asyncio.create_task(session.save())

    async def on_context_tree_view_turn_delete_requested(self, event: ContextTreeView.TurnDeleteRequested) -> None:
        """Handle turn delete request - show confirmation dialog."""
        status_bar = self.query_one("#status-bar", StatusBar)

        # Use in-memory session if it's the current one, otherwise load from disk
        if self.session and self.session.id == event.session_id:
            session = self.session
        else:
            session = await Session.load(event.session_id)

        if not session:
            self.notify("Session not found", severity="error")
            return

        # Check if session is read-only (merged fork)
        if session.is_read_only():
            self.notify("Cannot delete from merged (read-only) session", severity="error")
            return

        # Get turn preview for dialog
        if event.turn_index < len(session.turns):
            turn = session.turns[event.turn_index]
            role = "User" if turn.role == "user" else "Assistant"
            preview = turn.content[:50] + "..." if len(turn.content) > 50 else turn.content
            preview = preview.replace("\n", " ")
            message = f"{role}: {preview}"
        else:
            message = f"Turn {event.turn_index + 1}"

        # Show confirmation dialog
        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                asyncio.create_task(self._execute_turn_delete(event.session_id, event.turn_index, session))

        self.push_screen(
            ConfirmDialog("Delete Turn?", message),
            on_confirm,
        )

    async def _execute_turn_delete(self, session_id: str, turn_index: int, session: Session) -> None:
        """Execute the turn deletion after confirmation."""
        context_tree = self.query_one("#context-tree", ContextTreeView)

        if session.delete_turn(turn_index):
            debug_log.info(
                f"Deleted turn {turn_index} from session {session_id[:8]}",
                session_id=session_id,
                category="event",
                details={"turn_index": turn_index},
            )
            asyncio.create_task(session.save())

            # Efficiently update the tree without reloading everything
            context_tree.remove_turn(session_id, turn_index, updated_session=session)

            # Refresh chat log if this is the current session
            if self.session and self.session.id == session_id:
                chat_log = self.query_one("#chat-log", ChatLogView)
                chat_log.clear()
                await chat_log.load_history(session.turns, session=session)

            self.notify(f"Deleted turn {turn_index + 1}")
        else:
            self.notify("Could not delete turn", severity="error")

    async def on_context_tree_view_session_delete_requested(self, event: ContextTreeView.SessionDeleteRequested) -> None:
        """Handle session delete request - show confirmation dialog."""
        # Load the session to get info for confirmation
        session = await Session.load(event.session_id)
        if not session:
            self.notify("Session not found", severity="error")
            return

        is_active = self.session and self.session.id == event.session_id

        # Build confirmation message
        turn_count = len(session.turns)
        if session.title:
            name = session.title[:30] + "..." if len(session.title) > 30 else session.title
        else:
            name = session.id[:8]
        message = f"{name} ({turn_count} turns)"

        # Show confirmation dialog
        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                asyncio.create_task(self._execute_session_delete(event.session_id, session, is_active))

        self.push_screen(
            ConfirmDialog("Delete Session?", message),
            on_confirm,
        )

    async def _execute_session_delete(self, session_id: str, session: Session, was_active: bool) -> None:
        """Execute the session deletion after confirmation."""
        status_bar = self.query_one("#status-bar", StatusBar)
        context_tree = self.query_one("#context-tree", ContextTreeView)

        # Mark links as orphaned in linked sessions before deletion
        # Check both legacy links and turn-based LinkBlocks
        for link in session.get_all_active_links():
            linked_session = await Session.load(link.get("linked_session_id", ""))
            if linked_session:
                linked_session.mark_link_orphaned(link.get("link_id", ""))
                await linked_session.save()

        # Execute async delete and handle result
        await self._complete_session_delete(session_id, session, was_active, session.delete())

    async def _complete_session_delete(self, session_id: str, session: Session, was_active: bool, delete_coro) -> None:
        """Complete session deletion after async delete."""
        context_tree = self.query_one("#context-tree", ContextTreeView)

        if await delete_coro:
            debug_log.info(
                f"Deleted session {session_id[:8]}",
                session_id=session_id,
                category="event",
            )

            # Remove from tree
            context_tree.remove_session(session_id)

            # If we deleted the active session, switch to another one
            if was_active:
                # Find another session to switch to - get just the first one
                first_session = None
                for session_info in await Session.list_sessions():
                    first_session = session_info
                    break

                if first_session:
                    # Switch to the first remaining session
                    next_session = await Session.load(first_session["id"])
                    if next_session:
                        await self._switch_to_session(next_session)
                else:
                    # No sessions left, create a new one
                    new_session = context_tree.create_new_session()
                    await self._switch_to_session(new_session)

            self.notify(f"Deleted session {session_id[:8]}")
        else:
            self.notify("Could not delete session", severity="error")

    async def on_context_tree_view_exchange_delete_requested(self, event: ContextTreeView.ExchangeDeleteRequested) -> None:
        """Handle exchange group delete request - show confirmation dialog."""
        # Load the session
        session = await Session.load(event.session_id)
        if not session:
            self.notify("Session not found", severity="error")
            return

        if session.is_read_only():
            self.notify("Cannot delete from merged (read-only) session", severity="error")
            return

        turn_count = len(event.turn_indices)
        message = f"Delete {turn_count} turns in this exchange?"

        # Show confirmation dialog
        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                asyncio.create_task(self._execute_exchange_delete(event.session_id, event.turn_indices, session))

        self.push_screen(
            ConfirmDialog("Delete Exchange?", message),
            on_confirm,
        )

    async def _execute_exchange_delete(self, session_id: str, turn_indices: list[int], session: Session) -> None:
        """Execute the exchange deletion after confirmation."""
        context_tree = self.query_one("#context-tree", ContextTreeView)

        deleted_count = session.delete_turns(turn_indices)
        if deleted_count > 0:
            debug_log.info(
                f"Deleted {deleted_count} turns from session {session_id[:8]}",
                session_id=session_id,
                category="event",
                details={"turn_indices": turn_indices, "deleted_count": deleted_count},
            )
            await session.save()

            # Reload the tree for this session (easier than updating multiple turns)
            await context_tree.load_all_sessions(session)

            # Refresh chat log if this is the current session
            if self.session and self.session.id == session_id:
                chat_log = self.query_one("#chat-log", ChatLogView)
                chat_log.clear()
                await chat_log.load_history(session.turns, session=session)

            self.notify(f"Deleted {deleted_count} turns")
        else:
            self.notify("Could not delete turns", severity="error")

    async def on_context_tree_view_session_activated(self, event: ContextTreeView.SessionActivated) -> None:
        """Handle clicking on a session - switch to it."""
        # Switch to this session (works even while other sessions stream)
        await self._switch_to_session(event.session)

    def on_context_tree_view_archive_requested(self, event: ContextTreeView.ArchiveRequested) -> None:
        """Handle ctrl+shift+click on turns to archive them."""
        # Delegate to async handler
        asyncio.create_task(self._archive_turns_from_tree(event.session_id, event.turn_indices))

    def on_context_tree_view_session_link_requested(self, event: ContextTreeView.SessionLinkRequested) -> None:
        """Handle ctrl+click on a session - populate or append to link command."""
        import re

        debug_log.info(f"LINK DEBUG: event.session_id = '{event.session_id}' (len={len(event.session_id)})", category="link")

        # Don't allow linking to the current session
        if self.session and event.session_id == self.session.id:
            self.notify("Cannot link to current session", severity="error")
            return

        input_box = self.query_one("#input-box", InputBox)
        new_hash = event.session_id[:8]
        current_text = input_box.text

        # Check if there's already a :link= command in the input
        link_match = re.match(r'^:link=([a-f0-9,]+)', current_text)

        if link_match:
            # Existing link command - append to the hash list
            existing_hashes = link_match.group(1)

            # Check if this hash is already in the list
            hash_list = [h.strip() for h in existing_hashes.split(",")]
            if new_hash in hash_list:
                self.notify(f"Session {new_hash} already in link list", severity="error")
                return

            # Append the new hash
            new_hashes = f"{existing_hashes},{new_hash}"
            new_text = f":link={new_hashes}"
            input_box.clear()
            input_box.insert(new_text)
        else:
            # No existing link command - create new one
            link_cmd = f":link={new_hash}"
            input_box.clear()
            input_box.insert(link_cmd)

        input_box.focus()

    def on_context_tree_view_colon_pressed(self, event: ContextTreeView.ColonPressed) -> None:
        """Handle : key from tree - jump to input box, insert colon only if empty."""
        input_box = self.query_one("#input-box", InputBox)
        input_box.focus()
        if not input_box.text:
            input_box.insert(":")

    async def on_context_tree_view_jump_to_exchange_end(self, event: ContextTreeView.JumpToExchangeEnd) -> None:
        """Handle 'g' key on exchange group - scroll to last turn in the exchange."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        # Check if we need to switch sessions
        if self.session and event.session_id != self.session.id:
            target_session = await Session.load(event.session_id)
            if target_session:
                await self._switch_to_session(target_session, target_turn_index=event.last_turn_idx)
                return
        # Scroll to the last turn in the exchange
        turn_id = event.last_turn_idx + 1
        self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))

    async def on_context_tree_view_turn_inspected(self, event: ContextTreeView.TurnInspected) -> None:
        """Handle turn inspection - highlight and scroll to turns and tool uses.

        If the turn belongs to a different session, switch to that session first.
        All turns are now always visible (with visual context mode indication),
        so we just need to scroll to and highlight the inspected turn.
        """
        chat_log = self.query_one("#chat-log", ChatLogView)

        # Handle different node types
        node_type = event.turn_data.get("type")
        # Extract turn_idx for node types that have it
        turn_idx = event.turn_data.get("turn_idx") if node_type in ("turn", "fork", "merge") else None

        # Check if we need to switch sessions
        turn_session_id = event.session_id
        current_session_id = self.session.id if self.session else None
        debug_log.info(
            f"on_context_tree_view_turn_inspected: type={node_type}, turn_session_id={turn_session_id}, current_session_id={current_session_id}, turn_idx={turn_idx}",
            category="tree"
        )
        if turn_session_id and turn_session_id != self.session.id:
            # Switch to the turn's session first - it handles scrolling
            debug_log.info(f"Switching to different session: {turn_session_id[:8]}...", category="tree")
            target_session = await Session.load(turn_session_id)
            if target_session:
                debug_log.info(f"Loaded target session, calling _switch_to_session with turn_idx={turn_idx}", category="tree")
                await self._switch_to_session(target_session, target_turn_index=turn_idx)
                # For tool_use and tool_result, we need to highlight after session switch
                if node_type in ("tool_use", "tool_result"):
                    tool_use_id = event.turn_data.get("tool_use_id", "")
                    if tool_use_id:
                        # Delay highlight to allow session switch to complete
                        def do_highlight():
                            chat_log.highlight_tool(tool_use_id)
                        self.call_later(do_highlight)
                elif node_type == "text":
                    turn_id = event.turn_data.get("turn_idx", 0) + 1
                    block_idx = event.turn_data.get("block_idx", -1)
                    def do_highlight():
                        chat_log.highlight_text_block(turn_id, block_idx)
                    self.call_later(do_highlight)
                return  # Session switch handles the rest
            else:
                debug_log.warning(f"Failed to load session {turn_session_id}", category="tree")

        if node_type == "summary":
            chat_log.clear_highlights()
        elif node_type == "turn":
            # Whole turn inspection - scroll to it, highlight it, and show in request pane
            turn_id = turn_idx + 1
            scroll_to_top = event.turn_data.get("scroll_to_top", False)
            # Use call_after_refresh to ensure layout is computed before scrolling
            # This fixes the "second click needed" bug where scroll fails on first click
            self.call_after_refresh(lambda tid=turn_id, stt=scroll_to_top: chat_log.highlight_turn(tid, scroll_to_top=stt))
            # Save last view position
            save_last_view(self.session.id, turn_idx)
        elif node_type == "text":
            # Highlight the text block in the chat log
            # turn_idx is 0-indexed but turn_id is 1-indexed
            turn_id = event.turn_data.get("turn_idx", 0) + 1
            block_idx = event.turn_data.get("block_idx", -1)
            chat_log.highlight_text_block(turn_id, block_idx)
        elif node_type == "tool_use":
            # Highlight the tool use in the chat log
            tool_use_id = event.turn_data.get("tool_use_id", "")
            if tool_use_id:
                chat_log.highlight_tool(tool_use_id)
        elif node_type == "tool_result":
            # Highlight the tool result and its parent tool use
            tool_use_id = event.turn_data.get("tool_use_id", "")
            if tool_use_id:
                chat_log.highlight_tool(tool_use_id)
        elif node_type == "fork":
            # Scroll to fork marker in chat and show in request pane
            # The turn_idx is the fork_point (0-indexed turn where fork was created)
            fork_turn_idx = event.turn_data.get("turn_idx", -1)
            if fork_turn_idx >= 0:
                # Fork markers appear after the turn at fork_point, so turn_id = fork_turn_idx + 1
                turn_id = fork_turn_idx + 1
                self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))
            chat_log.clear_highlights()
        elif node_type == "merge":
            # Scroll to merge marker in chat and show in request pane
            # Try turn_idx first (more reliable), fall back to scroll_to_merge_marker
            merge_turn_idx = event.turn_data.get("turn_idx", -1)
            if merge_turn_idx >= 0:
                # Merge markers appear after the turn at merge_point, so turn_id = merge_turn_idx + 1
                turn_id = merge_turn_idx + 1
                self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))
            else:
                # Fall back to finding marker by child session ID
                child_session_id = event.turn_data.get("session_id", "")
                if child_session_id:
                    chat_log.scroll_to_merge_marker(child_session_id)
            chat_log.clear_highlights()
        elif node_type == "link":
            # Scroll to link marker in chat and show in request pane
            turn_idx = event.turn_data.get("turn_idx")
            if turn_idx is not None:
                turn_id = turn_idx + 1
                self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))
            chat_log.clear_highlights()
        elif node_type in ("fork_block", "merge_block"):
            # Fork/merge blocks stored in content_blocks - scroll to the turn containing them
            turn_idx = event.turn_data.get("turn_idx")
            if turn_idx is not None:
                turn_id = turn_idx + 1
                self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))
            chat_log.clear_highlights()
        elif node_type == "exchange_group":
            # Scroll to the first turn in the exchange group
            turn_idx = event.turn_data.get("turn_idx")
            if turn_idx is not None:
                turn_id = turn_idx + 1
                self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))
            chat_log.clear_highlights()
        else:
            chat_log.clear_highlights()

    # --- NestedTreeView Event Handlers ---
    # These mirror the ContextTreeView handlers since both trees emit the same message types

    def on_nested_tree_view_selection_changed(self, event: NestedTreeView.SelectionChanged) -> None:
        """Handle nested tree selection changes - apply visual context mode indicators."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        chat_log.set_turn_context_modes(event.turn_modes)
        # Token count already updated via TreeState observer

    async def on_nested_tree_view_context_mode_changed(self, event: NestedTreeView.ContextModeChanged) -> None:
        """Handle context mode change from nested tree - persist to session."""
        # Update TreeState - this triggers observer chain for token recalculation
        context_tree = self.query_one("#context-tree", ContextTreeView)
        if event.new_mode == ContextMode.DROP:
            context_tree._state.remove_context_mode(event.session_id, event.turn_idx)
        else:
            context_tree._state.set_context_mode(event.session_id, event.turn_idx, event.new_mode)
        # Turn label updated here; root label and tokens updated via TreeState observer
        context_tree._update_turn_label(event.session_id, event.turn_idx)

        # Persist to session
        if self.session and self.session.id == event.session_id:
            session = self.session
        else:
            session = await Session.load(event.session_id)

        if session and event.turn_idx < len(session.turns):
            session.turns[event.turn_idx].context_mode = event.new_mode
            asyncio.create_task(session.save())

    async def on_nested_tree_view_session_activated(self, event: NestedTreeView.SessionActivated) -> None:
        """Handle clicking on a session in nested tree - switch to it."""
        await self._switch_to_session(event.session)

    async def on_nested_tree_view_turn_inspected(self, event: NestedTreeView.TurnInspected) -> None:
        """Handle turn inspection from nested tree."""
        chat_log = self.query_one("#chat-log", ChatLogView)

        node_type = event.turn_data.get("type")
        turn_idx = event.turn_data.get("turn_idx") if node_type in ("turn", "exchange_group") else None

        # Check if we need to switch sessions
        turn_session_id = event.session_id
        if turn_session_id and self.session and turn_session_id != self.session.id:
            target_session = await Session.load(turn_session_id)
            if target_session:
                await self._switch_to_session(target_session, target_turn_index=turn_idx)
                chat_log.clear_highlights()
                return

        if node_type == "turn":
            turn_id = turn_idx + 1
            scroll_to_top = event.turn_data.get("scroll_to_top", False)
            # Use call_after_refresh to ensure layout is computed before scrolling
            # This fixes the "second click needed" bug where scroll fails on first click
            self.call_after_refresh(lambda tid=turn_id, stt=scroll_to_top: chat_log.scroll_to_turn(tid, scroll_to_top=stt))
            chat_log.clear_highlights()
            # Save last view position
            save_last_view(self.session.id, turn_idx)
        elif node_type == "exchange_group":
            # Scroll to first turn in exchange group
            turn_idx = event.turn_data.get("turn_idx")
            if turn_idx is not None:
                turn_id = turn_idx + 1
                self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))
            chat_log.clear_highlights()
        else:
            chat_log.clear_highlights()

    def on_nested_tree_view_turn_delete_requested(self, event: NestedTreeView.TurnDeleteRequested) -> None:
        """Handle turn delete request from nested tree."""
        # Reuse the ContextTreeView handler logic
        context_tree_event = ContextTreeView.TurnDeleteRequested(event.session_id, event.turn_index)
        self.on_context_tree_turn_delete_requested(context_tree_event)

    def on_nested_tree_view_session_delete_requested(self, event: NestedTreeView.SessionDeleteRequested) -> None:
        """Handle session delete request from nested tree."""
        # Reuse the ContextTreeView handler logic
        context_tree_event = ContextTreeView.SessionDeleteRequested(event.session_id)
        self.on_context_tree_session_delete_requested(context_tree_event)

    def on_nested_tree_view_exchange_delete_requested(self, event: NestedTreeView.ExchangeDeleteRequested) -> None:
        """Handle exchange delete request from nested tree."""
        # Reuse the ContextTreeView handler logic
        context_tree_event = ContextTreeView.ExchangeDeleteRequested(event.session_id, event.turn_indices)
        self.on_context_tree_view_exchange_delete_requested(context_tree_event)

    def on_nested_tree_view_session_link_requested(self, event: NestedTreeView.SessionLinkRequested) -> None:
        """Handle ctrl+click link request from nested tree."""
        # Reuse the ContextTreeView handler logic
        context_tree_event = ContextTreeView.SessionLinkRequested(event.session_id)
        self.on_context_tree_session_link_requested(context_tree_event)

    async def on_nested_tree_view_session_load_requested(self, event: NestedTreeView.SessionLoadRequested) -> None:
        """Handle request to load a session's data for display in nested tree."""
        session = await Session.load(event.session_id)
        if session:
            # Load the session into TreeState
            self._tree_state.load_session(event.session_id, session)

    def on_nested_tree_view_colon_pressed(self, event: NestedTreeView.ColonPressed) -> None:
        """Handle : key from tree - jump to input box, insert colon only if empty."""
        input_box = self.query_one("#input-box", InputBox)
        input_box.focus()
        if not input_box.text:
            input_box.insert(":")

    async def on_nested_tree_view_jump_to_exchange_end(self, event: NestedTreeView.JumpToExchangeEnd) -> None:
        """Handle 'g' key on exchange group - scroll to last turn in the exchange."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        # Check if we need to switch sessions
        if self.session and event.session_id != self.session.id:
            target_session = await Session.load(event.session_id)
            if target_session:
                await self._switch_to_session(target_session, target_turn_index=event.last_turn_idx)
                return
        # Scroll to the last turn in the exchange
        turn_id = event.last_turn_idx + 1
        self.call_after_refresh(lambda tid=turn_id: chat_log.scroll_to_turn(tid))

    def on_nested_tree_view_archive_requested(self, event: NestedTreeView.ArchiveRequested) -> None:
        """Handle x key on turn or exchange group to archive them."""
        # Delegate to async handler
        asyncio.create_task(self._archive_turns_from_tree(event.session_id, event.turn_indices))

    # --- GoalTreeView Event Handlers ---

    async def on_goal_tree_view_session_activated(self, event: GoalTreeView.SessionActivated) -> None:
        """Handle clicking on a session in goal tree - switch to it."""
        session = await Session.load(event.session_id)
        if session:
            await self._switch_to_session(session)

    def on_goal_tree_view_entity_selected(self, event: GoalTreeView.EntitySelected) -> None:
        """Handle selecting a goal/plan/todo in the tree."""
        # Could show entity details in a pane, or just notify
        self.notify(f"Selected {event.entity_type}: {event.entity_id[:8]}")

    def on_goal_tree_view_colon_pressed(self, event: GoalTreeView.ColonPressed) -> None:
        """Handle : key from goal tree - jump to input box."""
        input_box = self.query_one("#input-box", InputBox)
        input_box.focus()
        if not input_box.text:
            input_box.insert(":")

    def on_goal_tree_view_search_requested(self, event: GoalTreeView.SearchRequested) -> None:
        """Handle / key from goal tree - start search."""
        # Could open a search dialog for goals/todos
        self.notify("Search in goal tree not yet implemented")

    def on_goal_tree_view_session_delete_requested(self, event: GoalTreeView.SessionDeleteRequested) -> None:
        """Handle session delete request from goal tree."""
        # Reuse the ContextTreeView handler logic
        context_tree_event = ContextTreeView.SessionDeleteRequested(event.session_id)
        self.on_context_tree_session_delete_requested(context_tree_event)

    def on_goal_tree_view_delete_requested(self, event: GoalTreeView.DeleteRequested) -> None:
        """Handle entity delete request from goal tree."""
        # For now just notify - could add confirmation and deletion
        self.notify(f"Delete {event.entity_type} not yet implemented")

    async def on_goal_tree_view_mark_todo_done_requested(self, event: GoalTreeView.MarkTodoDoneRequested) -> None:
        """Handle marking a todo as done from the goal tree."""
        from core.goal_commands import mark_todo_done
        result = await mark_todo_done(event.todo_id, self.session.id if self.session else "")
        if result.success:
            self.notify(f"Marked complete: {result.todo.title}")
            # Refresh the goal tree
            if self._goal_tree_sync:
                await self._goal_tree_sync.initial_load()
        else:
            self.notify(f"Error: {result.error}", severity="error")

    async def on_goal_tree_view_bind_session_requested(self, event: GoalTreeView.BindSessionRequested) -> None:
        """Handle binding current session to an entity."""
        if not self.session:
            self.notify("No active session to bind", severity="warning")
            return

        from core.goal_commands import GoalCommandExecutor
        from core.async_storage import get_goal_storage

        storage = await get_goal_storage()
        executor = GoalCommandExecutor(storage)
        result = await executor.bind_session(
            self.session.id,
            event.entity_type,
            event.entity_id,
            "implementation"  # Default role
        )

        if result.success:
            self.notify(f"Bound session to {event.entity_type}")
            # Refresh the goal tree
            if self._goal_tree_sync:
                await self._goal_tree_sync.initial_load()
        else:
            self.notify(f"Error: {result.error}", severity="error")

    async def on_goal_tree_view_context_mode_changed(self, event: GoalTreeView.ContextModeChanged) -> None:
        """Handle context mode change from goal tree - persist to session."""
        # Update TreeState - this triggers observer chain for token recalculation
        context_tree = self.query_one("#context-tree", ContextTreeView)
        if event.new_mode == ContextMode.DROP:
            context_tree._state.remove_context_mode(event.session_id, event.turn_idx)
        else:
            context_tree._state.set_context_mode(event.session_id, event.turn_idx, event.new_mode)

        # Persist to session if it's the current session
        if self.session and event.session_id == self.session.id:
            await self._persist_context_mode(event.turn_idx, event.new_mode)

    async def on_breadcrumb_segment_clicked(self, event: Breadcrumb.SegmentClicked) -> None:
        """Handle clicking a breadcrumb segment to navigate up."""
        target_session = await Session.load(event.session_id)
        if target_session:
            await self._switch_to_session(target_session)

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
            asyncio.create_task(self.session.save())
            # Update UI
            context_tree = self.query_one("#context-tree", ContextTreeView)
            await context_tree.load_all_sessions(self.session)
            breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
            await breadcrumb.set_session(self.session)

    def action_toggle_tree(self) -> None:
        """Toggle the tree sidebar visibility."""
        context_tree = self.query_one("#context-tree", ContextTreeView)
        nested_tree = self.query_one("#nested-tree", NestedTreeView)
        goal_tree = self.query_one("#goal-tree", GoalTreeView)
        splitter = self.query_one("#splitter", VerticalSplitter)

        # If any tree is visible, hide all; otherwise show the active one
        any_visible = context_tree.display or nested_tree.display or goal_tree.display
        if any_visible:
            context_tree.display = False
            nested_tree.display = False
            goal_tree.display = False
            splitter.display = False
        else:
            # Show whichever was last active (context_tree by default)
            active = getattr(self, "_active_tree_view", "context")
            if active == "nested":
                nested_tree.display = True
            elif active == "goal":
                goal_tree.display = True
                asyncio.create_task(self._ensure_goal_tree_loaded())
            else:
                context_tree.display = True
            splitter.display = True

    def action_switch_tree_view(self) -> None:
        """Switch between context tree, nested tree, and goal tree views.

        Cycles: Context -> Nested -> Goal -> Context
        """
        context_tree = self.query_one("#context-tree", ContextTreeView)
        nested_tree = self.query_one("#nested-tree", NestedTreeView)
        goal_tree = self.query_one("#goal-tree", GoalTreeView)
        status_bar = self.query_one("#status-bar", StatusBar)

        # Determine current view and cycle to next
        if context_tree.display:
            # Context -> Nested
            context_tree.display = False
            nested_tree.display = True
            goal_tree.display = False
            self._active_tree_view = "nested"
        elif nested_tree.display:
            # Nested -> Goal
            context_tree.display = False
            nested_tree.display = False
            goal_tree.display = True
            self._active_tree_view = "goal"
            # Load goal tree data if not already loaded
            asyncio.create_task(self._ensure_goal_tree_loaded())
        elif goal_tree.display:
            # Goal -> Context
            context_tree.display = True
            nested_tree.display = False
            goal_tree.display = False
            self._active_tree_view = "context"
        else:
            # None visible - show the last active one
            active = getattr(self, "_active_tree_view", "context")
            if active == "nested":
                nested_tree.display = True
            elif active == "goal":
                goal_tree.display = True
                asyncio.create_task(self._ensure_goal_tree_loaded())
            else:
                context_tree.display = True
            self.query_one("#splitter", VerticalSplitter).display = True

    async def _ensure_goal_tree_loaded(self) -> None:
        """Ensure goal tree data is loaded."""
        if self._goal_tree_sync is None:
            self._goal_tree_sync = GoalTreeSyncManager(
                self._goal_tree_state,
                self._tree_state
            )
        await self._goal_tree_sync.initial_load()

    def action_toggle_tasks(self) -> None:
        """Toggle the task pane visibility."""
        pane = self.query_one("#task-pane", TaskPane)
        pane.display = not pane.display

    def action_toggle_debug(self) -> None:
        """Toggle the debug pane visibility."""
        pane = self.query_one("#debug-pane", DebugPane)
        pane.toggle()

    def _handle_debug_clear(self) -> None:
        """Clear all debug log entries."""
        pane = self.query_one("#debug-pane", DebugPane)
        pane.clear_entries()

    def _handle_debug_pause(self) -> None:
        """Toggle debug logging on/off."""
        debug_log.enabled = not debug_log.enabled
        state = "enabled" if debug_log.enabled else "paused"
        self.notify(f"Debug logging {state}")

    def on_debug_pane_log_line_selected(self, event: DebugPane.LogLineSelected) -> None:
        """Handle Ctrl+click on a debug log line - insert into input."""
        input_box = self.query_one("#input-box", InputBox)
        # Insert with newlines before and after for clarity
        current_text = input_box.text
        if current_text and not current_text.endswith("\n"):
            input_box.insert("\n")
        input_box.insert(f"\n{event.text}\n\n")
        input_box.focus()

    async def _handle_reindex_command(self) -> None:
        """Refresh the session list."""
        from session import Session
        context_tree = self.query_one("#context-tree", ContextTreeView)

        self.notify("Refreshing session list...")
        session_count = 0
        for _ in await Session.list_sessions():
            session_count += 1
        self.notify(f"Found {session_count} sessions")

        # Reload tree with new data
        await context_tree.load_all_sessions(self.session)

    async def _handle_review_command(self) -> None:
        """Start a quality review of the current session.

        Creates a review fork with:
        - Full session conversation (actual messages, not a summary)
        - Review agent system prompt
        - Switches to review_backend (or default_backend)

        The review LLM sees the full conversation and can intelligently decide
        what to focus on, summarizing tool outputs if context is limited.
        """
        from pathlib import Path
        from models import Sentiment

        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)

        # Validate session has content to review
        if not self.session.turns:
            self.notify("No turns to review in this session", severity="warning")
            return

        # Get review backend config
        config = get_config()
        try:
            review_backend_config = config.get_review_backend()
        except ValueError as e:
            self.notify(str(e), severity="error")
            return

        # Load the review agent system prompt
        prompt_path = Path(__file__).parent / "prompts" / "review-agent.md"
        if not prompt_path.exists():
            self.notify("Review agent prompt not found", severity="error")
            return

        review_system_prompt = prompt_path.read_text()

        # Build metadata header for the review
        sentiment_counts = {}
        for turn in self.session.turns:
            if turn.sentiment:
                sentiment_counts[turn.sentiment.value] = sentiment_counts.get(turn.sentiment.value, 0) + 1

        metadata_parts = [
            "# Session Under Review",
            f"- Session ID: {self.session.id[:8]}",
            f"- Title: {self.session.title or '(untitled)'}",
            f"- Model: {self.session.backend_name or config.default_backend}",
            f"- Turn count: {len(self.session.turns)}",
        ]

        if sentiment_counts:
            metadata_parts.append("")
            metadata_parts.append("## Sentiment Summary")
            sentiment_emojis = {
                "excellent": "❤️",
                "good": "👍",
                "review": "🔍",
                "poor": "👎",
                "terrible": "☠️",
            }
            for sentiment, count in sorted(sentiment_counts.items()):
                emoji = sentiment_emojis.get(sentiment, "")
                metadata_parts.append(f"- {emoji} {sentiment}: {count}")

        metadata_parts.append("")
        metadata_parts.append("The full conversation follows. Please review it and help me evaluate its quality.")
        session_metadata = "\n".join(metadata_parts)

        # Create the review fork with descriptive title
        reviewed_session_name = self.session.title or self.session.fork_name or "(untitled)"
        reviewed_session_short_id = self.session.id[:8]

        review_session = Session()
        review_session.parent_id = self.session.id
        review_session.fork_name = f"Review: {reviewed_session_short_id} ({reviewed_session_name})"
        review_session.fork_status = "active"
        review_session.fork_point_turn = len(self.session.turns)
        review_session.backend_name = review_backend_config.name

        # Copy all turns from the original session to the review session
        # This gives the review LLM the full conversation context
        for turn in self.session.turns:
            review_session.add_turn(
                role=turn.role,
                content_block=turn.content_block,
                tokens=turn.tokens,
                exchange_id=turn.exchange_id,
                timestamp=turn.timestamp,
                context_mode=turn.context_mode,
            )

        await review_session.save()

        # Register child in parent
        self.session.add_child(
            review_session.id,
            "Quality review",
            name="review",
            fork_point=len(self.session.turns),
        )
        await self.session.save()

        # Register review session with manager
        self._manager._sessions[review_session.id] = review_session
        # Create runner with review backend and custom system prompt
        self._manager._runners[review_session.id] = self._create_session_runner(
            review_session,
            backend_config=review_backend_config,
            system_prompt=review_system_prompt,
        )

        # Switch to review session
        await self._manager.set_active(review_session.id)
        chat_log.clear()
        await chat_log.load_history(review_session.turns, session=review_session)
        await context_tree.load_all_sessions(review_session)
        await breadcrumb.set_session(review_session)

        # Start the review with metadata context
        # The LLM will see the full conversation history plus this prompt
        initial_prompt = f"{session_metadata}\n\nPlease help me review this session. Start by asking for my rubric scores."
        self._start_streaming(initial_prompt)

        self.notify(f"Started review session with {review_backend_config.name}")

    # =========================================================================
    # Goal-Oriented Task Management Command Handlers
    # =========================================================================

    async def _handle_goal_interview_command(self, name: str, prompt: str) -> None:
        """Handle :goal-interview=title <prompt> command - start a goal interview session.

        Both title and prompt are required.

        Creates a new session with:
        1. A title based on the name
        2. Binding to a pending goal with role: goal-interview
        3. Guidance prompt for the LLM to conduct requirements gathering
        """
        chat_log = self.query_one("#chat-log", ChatLogView)
        context_tree = self.query_one("#context-tree", ContextTreeView)
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)

        # Background old session
        old_session_id = self._manager._active_session_id
        self._background_old_session(old_session_id)

        # Show loading indicator
        chat_log.show_loading("Starting goal interview session...")

        # Create new session with title
        new_session = await self._manager.create_session()
        new_session.title = name
        await self._manager.set_active(new_session.id)

        # Reload UI
        chat_log.hide_loading()
        await context_tree.load_all_sessions(self.session)
        await breadcrumb.set_session(self.session)
        self.notify(f"Goal interview session created: {name}")

        # Update context tokens
        self._update_base_context_tokens()
        self._update_context_tokens()

        # Build the interview prompt
        interview_guidance = """You are starting a goal interview session. Your role is to help the user define a clear, actionable goal through requirements gathering.

## Interview Process

1. **Understand the vision**: Ask clarifying questions about what they want to achieve
2. **Explore constraints**: Discuss technical constraints, timelines, dependencies
3. **Define scope**: Help them narrow down to a clear, achievable goal
4. **Draft acceptance criteria**: Work with them to define how they'll know the goal is complete

## When the goal is clear:

1. **Create the goal** with `create_goal` tool (include title, description, weight, acceptance_criteria)
2. **Bind this session** with `bind_session(entity_type="goal", entity_id="...", role="interview")`
3. **Propose a fork** for planning with `propose_fork` to create the plan and todos

## Important guidelines:

- Ask one question at a time
- Don't assume - ask about anything unclear
- Help them think through edge cases
- Suggest acceptance criteria rather than prescribing them
- Keep the goal focused - one clear objective, not a laundry list

"""
        # If user provided a prompt, use it as the initial context
        if prompt:
            full_prompt = f"{interview_guidance}\nThe user wants to work on:\n\n{prompt}\n\nStart by asking clarifying questions to understand their goal better."
        else:
            full_prompt = f"{interview_guidance}\nAsk the user what goal they'd like to work on."

        # Start streaming with the interview prompt
        self._start_streaming(full_prompt)

    async def _handle_goals_command(self, include_completed: bool = False) -> None:
        """Handle :goals command - list all goals."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        executor = GoalCommandExecutor()
        result = await executor.list_goals(include_completed)

        if result.success:
            chat_log.add_info_message(result.formatted, title="Goals")
        else:
            self.notify(f"Error: {result.error}", severity="error")

    async def _handle_plans_command(self, goal_id: str = "") -> None:
        """Handle :plans command - list plans for a goal."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        executor = GoalCommandExecutor()
        result = await executor.list_plans(goal_id)

        if result.success:
            chat_log.add_info_message(result.formatted, title="Plans")
        else:
            self.notify(f"Error: {result.error}", severity="error")

    async def _handle_todos_command(self, plan_id: str = "") -> None:
        """Handle :todos command - list priority-ranked todos."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        executor = GoalCommandExecutor()
        result = await executor.list_todos(plan_id)

        if result.success:
            chat_log.add_info_message(result.formatted, title="Todos")
        else:
            self.notify(f"Error: {result.error}", severity="error")

    async def _handle_todo_done_command(self, todo_id: str) -> None:
        """Handle :todo-done command - mark todo complete.

        If no todo_id provided, marks the currently bound todo as done.
        """
        # If no todo_id, try to get from session binding
        if not todo_id:
            from core.async_storage import get_goal_storage
            from widgets.todo_picker import TodoPickerModal

            storage = await get_goal_storage()
            bindings = await storage.get_bindings_for_session(self.session.id, active_only=True)
            todo_bindings = [b for b in bindings if b.entity_type == "todo"]

            if not todo_bindings:
                self.notify("No todo bound to this session. Use :todo-done <id>", severity="warning")
                return

            # Load the todos for display
            todos = []
            for binding in todo_bindings:
                todo = await storage.load_todo(binding.entity_id)
                if todo and todo.status != "completed":
                    todos.append(todo)

            if not todos:
                self.notify("All bound todos are already complete.", severity="warning")
                return

            if len(todos) == 1:
                # Only one pending todo - use it directly
                todo_id = todos[0].id
            else:
                # Multiple pending todos - show picker
                selected_id = await self.push_screen_wait(TodoPickerModal(todos))
                if not selected_id:
                    return  # User cancelled
                todo_id = selected_id

        executor = GoalCommandExecutor()
        result = await executor.mark_todo_done(todo_id, self.session.id)

        if result.success:
            self.notify(result.formatted, timeout=5)

            # Handle lifecycle prompt if returned
            if result.lifecycle_prompt:
                # Show follow-up prompt (e.g., plan complete, spike complete)
                await self._handle_lifecycle_prompt(result.lifecycle_prompt)
        else:
            self.notify(f"Error: {result.error}", severity="error")

    async def _handle_bind_command(
        self, entity_type: str, entity_id: str, role: str
    ) -> None:
        """Handle :bind command - bind session to goal/plan/todo."""
        executor = GoalCommandExecutor()
        result = await executor.bind_session(
            self.session.id, entity_type, entity_id, role
        )

        if result.success:
            self.notify(result.formatted, timeout=5)
            # Update binding indicator in session label
            await self._update_session_binding_indicator(self.session.id)
        else:
            self.notify(f"Error: {result.error}", severity="error")

    async def _handle_unbind_command(self, entity_id: str = "") -> None:
        """Handle :unbind command - release session bindings."""
        executor = GoalCommandExecutor()
        result = await executor.unbind_session(self.session.id, entity_id)

        if result.success:
            self.notify(result.formatted, timeout=5)
            # Update binding indicator in session label
            await self._update_session_binding_indicator(self.session.id)
        else:
            self.notify(f"Error: {result.error}", severity="error")

    async def _update_session_binding_indicator(self, session_id: str) -> None:
        """Update the binding indicator for a session in the tree state and breadcrumb."""
        indicator = await get_session_binding_indicator(session_id)
        self._tree_state.update_session_binding_indicator(session_id, indicator)

        # Also update breadcrumb if this is the current session
        if session_id == self.session.id:
            breadcrumb = self.query_one("#breadcrumb", Breadcrumb)
            breadcrumb.update_binding_indicator(indicator)

    async def _handle_lifecycle_prompt(self, prompt) -> None:
        """Handle a lifecycle prompt from todo/plan completion.

        Shows appropriate UI for postmortem, spike completion, etc.
        """
        from core.lifecycle_hooks import LifecyclePrompt

        if not isinstance(prompt, LifecyclePrompt):
            return

        chat_log = self.query_one("#chat-log", ChatLogView)

        # Build formatted message
        title = prompt.prompt_type.replace('_', ' ').title()
        content = prompt.message

        if prompt.choices:
            content += "\n\n[bold]Options:[/bold]"
            for choice in prompt.choices:
                content += f"\n  • {choice}"

        # Show in chat log as info message (persistent, scrollable)
        chat_log.add_info_message(content, title=title)

    def _handle_clear_all_sessions_command(self) -> None:
        """Delete all sessions after confirmation."""
        asyncio.create_task(self._handle_clear_all_sessions_async())

    async def _handle_clear_all_sessions_async(self) -> None:
        """Async implementation of clear all sessions command."""
        from session import Session

        # Count sessions first (from Rust if available, else JSON index)
        session_count = 0
        for _ in await Session.list_sessions():
            session_count += 1

        if session_count == 0:
            self.notify("No sessions to delete")
            return

        # Show confirmation dialog
        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                asyncio.create_task(self._execute_clear_all_sessions_async())

        self.push_screen(
            ConfirmDialog(
                "Delete ALL Sessions?",
                f"This will permanently delete {session_count} sessions.\nThis action cannot be undone!"
            ),
            on_confirm,
        )

    async def _execute_clear_all_sessions_async(self) -> None:
        """Execute deletion of all sessions after confirmation (async)."""
        from session import Session
        from core.async_storage import get_default_storage

        context_tree = self.query_one("#context-tree", ContextTreeView)
        chat_log = self.query_one("#chat-log", ChatLogView)
        breadcrumb = self.query_one("#breadcrumb", Breadcrumb)

        # Delete all sessions from storage
        try:
            storage = await get_default_storage()
            sessions = await storage.list_sessions()
            for session_meta in sessions:
                try:
                    await storage.delete_session(session_meta["id"])
                except Exception:
                    pass  # Continue even if individual deletion fails
        except Exception:
            pass

        # Clear manager state
        self._manager._sessions.clear()
        self._manager._runners.clear()

        # Clear streaming contexts
        self._streaming_contexts.clear()

        # Create a fresh session
        new_session = await self._manager.create_session()
        await self._manager.set_active(new_session.id)

        # Reset TreeState (don't preserve streaming - all sessions deleted)
        self._tree_state.clear(preserve_streaming=False)
        self._tree_state.add_session(new_session, is_current=True)

        # Update UI
        chat_log.clear()
        await context_tree.load_all_sessions(new_session)
        await breadcrumb.set_session(new_session)

        # Update tokens
        self._update_base_context_tokens()
        self._update_context_tokens()

        self.notify(f"Deleted {deleted_count} sessions")
        debug_log.info(
            f"Cleared all sessions",
            category="session",
            details={"deleted_count": deleted_count},
        )

    def export_screen_text(self, *, styles: bool = False) -> str:
        """Export the current screen as plain text.

        Uses the same compositor that Textual uses for SVG screenshots,
        but exports as plain text instead.

        Args:
            styles: If True, include ANSI escape codes. If False, plain text only.

        Returns:
            String containing the screen contents as text.
        """
        import io
        from rich.console import Console

        assert self._driver is not None, "App must be running"
        width, height = self.size

        console = Console(
            width=width,
            height=height,
            file=io.StringIO(),
            force_terminal=True,
            color_system="truecolor",
            record=True,
            legacy_windows=False,
            safe_box=False,
        )
        screen_render = self.screen._compositor.render_update(
            full=True, screen_stack=self._background_screens, simplify=True
        )
        console.print(screen_render)
        return console.export_text(styles=styles)

    def _execute_screen_snapshot_tool(self) -> tuple[str, bool]:
        """Execute the screen_snapshot tool.

        Called by the tool executor when Claude requests a screen snapshot.

        Returns:
            Tuple of (screen_text, is_error)
        """
        try:
            screen_text = self.export_screen_text(styles=False)
            width, height = self.size
            result = f"# Screen Snapshot ({width}x{height})\n```\n{screen_text}```"
            return result, False
        except Exception as e:
            return f"Error capturing screen: {e}", True

    async def _handle_snap_command(self, prompt: str = "") -> None:
        """Capture the screen as text and send to Claude.

        Args:
            prompt: Optional additional prompt text to include with the snapshot.
        """
        status_bar = self.query_one("#status-bar", StatusBar)

        try:
            # Capture the screen
            screen_text = self.export_screen_text(styles=False)

            # Build the message with the snapshot
            message_parts = []
            message_parts.append("# Current TUI Screen State\n")
            message_parts.append("```\n")
            message_parts.append(screen_text)
            message_parts.append("```\n")

            if prompt:
                message_parts.append(f"\n{prompt}")
            else:
                message_parts.append("\nPlease analyze the current screen state shown above.")

            full_prompt = "".join(message_parts)

            # Send to Claude like a normal prompt
            self._start_streaming(full_prompt)

        except Exception as e:
            self.notify(f"Failed to capture screen: {e}", severity="error")
            debug_log.error(
                f"Screen capture failed: {e}",
                category="command",
            )

    # =========================================================================
    # Slide/Presentation Commands
    # =========================================================================

    def _handle_new_slide_command(self, title: str = "") -> None:
        """Create a new slide in the current session.

        Args:
            title: Optional slide title
        """
        if not self.session:
            self.notify("No active session", severity="error")
            return

        # Create the slide
        self.session.add_slide_turn(
            title=title or "New Slide",
            content="",
            notes="",
        )
        asyncio.create_task(self.session.save())

        # Refresh UI
        self._refresh_slides_pane()
        self._switch_to_slides_tab()

        status_bar.set_message(f"Created slide: {title or 'New Slide'}")
        debug_log.info(f"Created new slide: {title}", category="slides")

    def _handle_present_command(self) -> None:
        """Enter fullscreen presentation mode."""
        if not self.session:
            self.notify("No active session", severity="error")
            return

        slides = self.session.get_all_slides()
        if not slides:
            self.notify("No slides to present", severity="error")
            return

        debug_log.info(f"Entering presentation mode: {len(slides)} slides", category="slides")
        self.push_screen(PresentationScreen(slides))

    def _switch_to_slides_tab(self) -> None:
        """Switch to the Slides tab view."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        slides_pane = self.query_one("#slides-pane", SlidesPane)
        database_pane = self.query_one("#entity-pane", EntityPane)
        tab_chat = self.query_one("#tab-chat", Button)
        tab_slides = self.query_one("#tab-slides", Button)
        tab_database = self.query_one("#tab-entities", Button)

        # Update button states
        tab_chat.remove_class("active")
        tab_slides.add_class("active")
        tab_database.remove_class("active")

        # Update visibility
        chat_log.add_class("hidden")
        slides_pane.add_class("visible")
        database_pane.hide()

        # Update slide count in tab
        if self.session:
            count = self.session.get_slide_count()
            tab_slides.label = f"📊 Slides ({count})" if count > 0 else "📊 Slides"

        debug_log.info("Switched to Slides tab", category="ui")

    def _switch_to_chat_tab(self) -> None:
        """Switch to the Chat tab view."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        slides_pane = self.query_one("#slides-pane", SlidesPane)
        database_pane = self.query_one("#entity-pane", EntityPane)
        tab_chat = self.query_one("#tab-chat", Button)
        tab_slides = self.query_one("#tab-slides", Button)
        tab_database = self.query_one("#tab-entities", Button)

        # Update button states
        tab_chat.add_class("active")
        tab_slides.remove_class("active")
        tab_database.remove_class("active")

        # Update visibility
        chat_log.remove_class("hidden")
        slides_pane.remove_class("visible")
        database_pane.hide()

        debug_log.info("Switched to Chat tab", category="ui")

    def _switch_to_entities_tab(self) -> None:
        """Switch to the Entities tab view."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        slides_pane = self.query_one("#slides-pane", SlidesPane)
        database_pane = self.query_one("#entity-pane", EntityPane)
        tab_chat = self.query_one("#tab-chat", Button)
        tab_slides = self.query_one("#tab-slides", Button)
        tab_database = self.query_one("#tab-entities", Button)

        # Update button states
        tab_chat.remove_class("active")
        tab_slides.remove_class("active")
        tab_database.add_class("active")

        # Update visibility
        chat_log.add_class("hidden")
        slides_pane.remove_class("visible")
        database_pane.show()

        debug_log.info("Switched to Entities tab", category="ui")

    def _refresh_slides_pane(self) -> None:
        """Refresh the slides pane with current session data."""
        try:
            slides_pane = self.query_one("#slides-pane", SlidesPane)
            slides_pane.set_session(self.session)

            # Update tab label with count
            tab_slides = self.query_one("#tab-slides", Button)
            if self.session:
                count = self.session.get_slide_count()
                debug_log.info(f"Refreshing slides pane: {count} slides found", category="slides")
                tab_slides.label = f"📊 Slides ({count})" if count > 0 else "📊 Slides"
            else:
                debug_log.info("Refreshing slides pane: no session", category="slides")
                tab_slides.label = "📊 Slides"
        except Exception as e:
            debug_log.warning(f"Failed to refresh slides pane: {e}", category="slides")

    def _refresh_goal_tree(self) -> None:
        """Refresh the goal tree after goal data mutations."""
        if self._goal_tree_sync is None:
            return
        try:
            debug_log.info("Refreshing goal tree after mutation", category="goals")
            asyncio.create_task(self._goal_tree_sync.initial_load())
        except Exception as e:
            debug_log.warning(f"Failed to refresh goal tree: {e}", category="goals")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses for tab switching."""
        if event.button.id == "tab-chat":
            self._switch_to_chat_tab()
        elif event.button.id == "tab-slides":
            self._switch_to_slides_tab()
        elif event.button.id == "tab-entities":
            self._switch_to_entities_tab()
        elif event.button.id == "present-btn":
            self._handle_present_command()

    def on_slides_pane_present_requested(self, event: SlidesPane.PresentRequested) -> None:
        """Handle present button from slides pane."""
        self._handle_present_command()

    def action_show_help(self) -> None:
        """Show the help modal."""
        self.push_screen(HelpModal())

    def action_show_preferences(self) -> None:
        """Show the preferences modal."""
        current_backend = self._backend_config.name
        if self.session and self.session.backend_name:
            current_backend = self.session.backend_name
        self.push_screen(PreferencesModal(
            current_backend=current_backend,
            tool_preferences=self._tool_preferences,
        ))

    def on_preferences_modal_tools_changed(self, event: PreferencesModal.ToolsChanged) -> None:
        """Handle tool preference changes from the modal."""
        self._tool_preferences[event.backend_name] = ToolPreferences(
            enabled_tools=set(event.enabled_tools)
        )

    def on_preferences_modal_backend_changed(self, event: PreferencesModal.BackendChanged) -> None:
        """Handle backend change from the modal."""
        # Update the default backend
        config = get_config()
        if event.backend_name in config.backends:
            self._backend_config = config.get_backend(event.backend_name)

    def _get_enabled_tools(self) -> list[str]:
        """Get enabled tools for the current backend.

        For review sessions (fork_name == "review"), includes the save_review tool.
        """
        backend_name = self._backend_config.name
        if self.session and self.session.backend_name:
            backend_name = self.session.backend_name
        if backend_name in self._tool_preferences:
            tools = list(self._tool_preferences[backend_name].enabled_tools)
        else:
            tools = list(DEFAULT_TOOLS)

        # Add review tools for review sessions
        if self.session and self.session.fork_name == "review":
            from core.tools import REVIEW_TOOL_NAMES
            tools = list(set(tools) | REVIEW_TOOL_NAMES)

        return tools

    def action_resize_tree(self, delta: int) -> None:
        """Resize the active tree by delta columns."""
        self._tree_width = max(20, min(100, self._tree_width + delta))
        context_tree = self.query_one("#context-tree", ContextTreeView)
        nested_tree = self.query_one("#nested-tree", NestedTreeView)
        goal_tree = self.query_one("#goal-tree", GoalTreeView)
        context_tree.styles.width = self._tree_width
        nested_tree.styles.width = self._tree_width
        goal_tree.styles.width = self._tree_width

    def on_vertical_splitter_resized(self, event: VerticalSplitter.Resized) -> None:
        """Handle splitter drag."""
        self.action_resize_tree(event.delta_x)

    def on_horizontal_splitter_resized(self, event: HorizontalSplitter.Resized) -> None:
        """Handle input box height resize via splitter drag."""
        input_box = self.query_one("#input-box", InputBox)
        input_box.adjust_max_height(event.delta_y)

    def on_chat_log_view_following_changed(self, event: ChatLogView.FollowingChanged) -> None:
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

    def on_chat_log_view_new_content_while_not_following(self, event: ChatLogView.NewContentWhileNotFollowing) -> None:
        """Show new messages indicator when content arrives while not following."""
        indicator = self.query_one("#more-below", MoreBelowIndicator)
        indicator.show_new_messages()

    def on_chat_log_view_colon_pressed(self, event: ChatLogView.ColonPressed) -> None:
        """Handle : key from chat - jump to input box, insert colon only if empty."""
        input_box = self.query_one("#input-box", InputBox)
        input_box.focus()
        if not input_box.text:
            input_box.insert(":")

    def on_chat_log_view_turn_viewed(self, event: ChatLogView.TurnViewed) -> None:
        """Handle turn being viewed by user - mark it in TreeState."""
        if self.session:
            # Convert 1-indexed turn_id to 0-indexed turn_idx
            turn_idx = event.turn_id - 1
            self._tree_state.mark_turn_viewed(self.session.id, turn_idx)

    async def on_chat_log_view_sentiment_changed(self, event: ChatLogView.SentimentChanged) -> None:
        """Handle user changing sentiment rating on a turn."""
        # Capture session reference before await to avoid race conditions
        session = self.session
        if session:
            # Convert 1-indexed turn_id to 0-indexed turn_idx
            turn_idx = event.turn_id - 1
            if 0 <= turn_idx < len(session.turns):
                turn = session.turns[turn_idx]
                turn.sentiment = event.sentiment
                # Save the session to persist the change
                await session.save()
                from core.debug_log import debug_log
                debug_log.info(
                    f"Sentiment updated: session={session.id[:8]}, turn_idx={turn_idx}, sentiment={event.sentiment}",
                    category="sentiment"
                )

    def on_status_bar_follow_clicked(self, event: StatusBar.FollowClicked) -> None:
        """Handle click on Follow indicator - scroll to bottom."""
        self.action_scroll_to_bottom()

    def on_more_below_indicator_clicked(self, event: MoreBelowIndicator.Clicked) -> None:
        """Handle click on more-below indicator - scroll to bottom."""
        self.action_scroll_to_bottom()

    async def on_actionable_toast_clicked(self, event: ActionableToast.Clicked) -> None:
        """Handle click on an actionable toast notification.

        Supports action types:
        - "switch_session": Switch to session (action_data["session_id"])
        """
        action = event.action_data.get("action")
        if action == "switch_session":
            session_id = event.action_data.get("session_id")
            if session_id:
                session = self._manager._sessions.get(session_id)
                if not session:
                    # Try to load it
                    session = await Session.load(session_id)
                if session:
                    await self._switch_to_session(session)
                    # Scroll to end to show latest content
                    chat_log = self.query_one("#chat-log", ChatLogView)
                    chat_log.scroll_end(animate=False)

    def action_scroll_to_bottom(self) -> None:
        """Scroll to bottom of chat and re-enable following."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        chat_log.following = True
        chat_log.scroll_end(animate=False)
        # Hide the more-below indicator
        indicator = self.query_one("#more-below", MoreBelowIndicator)
        indicator.hide()

    def _handle_follow_toggle(self) -> None:
        """Toggle auto-scroll following mode."""
        chat_log = self.query_one("#chat-log", ChatLogView)
        status_bar = self.query_one("#status-bar", StatusBar)
        indicator = self.query_one("#more-below", MoreBelowIndicator)

        chat_log.following = not chat_log.following

        if chat_log.following:
            # When enabling follow, scroll to bottom
            chat_log.scroll_end(animate=False)
            indicator.hide()
            self.notify("Follow enabled")
        else:
            self.notify("Follow disabled - scroll freely")

    def _handle_stash_command(self, name: str = "") -> None:
        """Handle :stash command - stash current input."""
        input_box = self.query_one("#input-box", InputBox)

        content = input_box.text.strip()
        if not content:
            self.notify("Nothing to stash", severity="error")
            return

        self._message_stash.add(content, name if name else None)
        input_box.clear()
        count = len(self._message_stash)
        self.notify(f"Stashed ({count} total)")

    def _handle_pop_command(self) -> None:
        """Handle :pop command - show stash picker."""
        self._show_stash_popup()

    def _show_stash_popup(self) -> None:
        """Show the stash popup for selection."""
        stash_popup = self.query_one("#stash-popup", StashPopup)

        messages = self._message_stash.all()
        if not messages:
            self.notify("Stash is empty", severity="error")
            return

        stash_popup.show_messages(messages)

    def _hide_stash_popup(self) -> None:
        """Hide the stash popup."""
        stash_popup = self.query_one("#stash-popup", StashPopup)
        stash_popup.hide()

    def on_stash_popup_message_selected(self, event: StashPopup.MessageSelected) -> None:
        """Handle selection of a stashed message."""
        input_box = self.query_one("#input-box", InputBox)

        # Pop the message from stash (removes it)
        self._message_stash.pop(event.index)

        # Load content into input box
        input_box.clear()
        input_box.insert(event.message.content)
        input_box.focus()

        self._hide_stash_popup()
        self.notify("Loaded from stash")

    def on_stash_popup_message_deleted(self, event: StashPopup.MessageDeleted) -> None:
        """Handle deletion of a stashed message."""
        stash_popup = self.query_one("#stash-popup", StashPopup)

        self._message_stash.remove(event.index)

        # Refresh the popup
        messages = self._message_stash.all()
        if messages:
            stash_popup.show_messages(messages)
        else:
            self._hide_stash_popup()
            self.notify("Stash empty")

    def on_stash_popup_closed(self, event: StashPopup.Closed) -> None:
        """Handle stash popup being closed without selection."""
        self._hide_stash_popup()
        input_box = self.query_one("#input-box", InputBox)
        input_box.focus()

    # --- Message Queue Handlers ---

    def _sync_and_save_queue(self) -> None:
        """Sync queue state to session and save (if not streaming)."""
        if not self.session:
            return
        # Sync QueueState back to session.message_queue for persistence
        self._queue_state.sync_to_message_queue(self.session.id, self.session.message_queue)
        # Only save if not streaming (avoid race with turn modifications)
        if not self.streaming:
            asyncio.create_task(self.session.save())

    def on_message_queue_popup_message_removed(self, event: MessageQueuePopup.MessageRemoved) -> None:
        """Handle removing a queued message."""
        if not self.session:
            return
        removed = self._queue_state.remove_message(self.session.id, event.message_id)
        if removed:
            self._sync_and_save_queue()
            self._update_queue_indicator()
            self.notify("Message removed from queue")

    def on_message_queue_popup_queue_cleared(self, event: MessageQueuePopup.QueueCleared) -> None:
        """Handle clearing all queued messages."""
        if not self.session:
            return
        count = self._queue_state.clear(self.session.id)
        self._sync_and_save_queue()
        self._update_queue_indicator()
        self.notify(f"Cleared {count} queued messages")

    def on_message_queue_popup_closed(self, event: MessageQueuePopup.Closed) -> None:
        """Handle queue popup being closed."""
        input_box = self.query_one("#input-box", InputBox)
        input_box.focus()

    def on_message_queue_popup_focus_input(self, event: MessageQueuePopup.FocusInput) -> None:
        """Handle request to switch focus from queue popup to input."""
        input_box = self.query_one("#input-box", InputBox)
        input_box.focus()

    def on_message_queue_popup_message_pause_toggled(self, event: MessageQueuePopup.MessagePauseToggled) -> None:
        """Handle toggling pause on a queued message."""
        if not self.session:
            return
        new_paused = self._queue_state.toggle_pause(self.session.id, event.message_id)
        self._sync_and_save_queue()
        self._update_queue_indicator()
        # Popup auto-updates via observer
        if new_paused is not None:
            self.notify(f"Message {'paused' if new_paused else 'resumed'}")

    def on_message_queue_popup_message_edit_requested(self, event: MessageQueuePopup.MessageEditRequested) -> None:
        """Handle request to edit a queued message."""
        if not self.session:
            return
        # Remove from queue
        self._queue_state.remove_message(self.session.id, event.message_id)
        self._sync_and_save_queue()
        self._update_queue_indicator()

        # Put content in input box and focus it
        input_box = self.query_one("#input-box", InputBox)
        input_box.clear()
        input_box.insert(event.content)
        input_box.focus()

        # Popup auto-updates via observer
        self.notify("Editing queued message")

    def action_stash_toggle(self) -> None:
        """Toggle stash: if input has text, stash it; if empty, show popup (Ctrl+S)."""
        input_box = self.query_one("#input-box", InputBox)
        stash_popup = self.query_one("#stash-popup", StashPopup)

        # If popup is visible, close it
        if stash_popup.display:
            self._hide_stash_popup()
            input_box.focus()
            return

        # If input has text, stash it
        if input_box.text.strip():
            self._handle_stash_command()
        else:
            # Input is empty, show popup to retrieve
            self._show_stash_popup()


    def action_quit(self) -> None:
        """Quit the application."""
        # Cancel all streaming sessions
        self._manager.cancel_all()
        # Stop polling timer
        if self._poll_timer:
            self._poll_timer.stop()
        self.exit()
