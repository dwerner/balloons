"""Core module - GUI-independent business logic for Balloons."""

# Commands
from .commands import (
    Command,
    CommandParser,
    ArchiveCommand,
    RehydrateCommand,
    ReindexCommand,
    NewSessionCommand,
    CopyTurnsCommand,
    QueryWithCommand,
    SuspendCommand,
    ShellCommand,
    ForkCommand,
    MergeCommand,
    DeriveCommand,
    SwitchCommand,
    HistoryCommand,
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
    DebugFpsCommand,
    FollowCommand,
    StashCommand,
    PopCommand,
    ClearAllSessionsCommand,
    SnapCommand,
    NewSlideCommand,
    PresentCommand,
    SlidesCommand,
    ChatCommand,
    SupervisorStartCommand,
    SupervisorListCommand,
    SupervisorLogsCommand,
    SupervisorStopCommand,
    ReviewCommand,
    GoalInterviewCommand,
    GoalsCommand,
    PlansCommand,
    TodosCommand,
    TodoDoneCommand,
    TodoUndoneCommand,
    BindCommand,
    UnbindCommand,
    COMMAND_DOCS,
)

# Context
from .context import ContextBuilder

# Formatter
from .formatter import Formatter, format_edit_as_diff, guess_language

# Runner
from .runner import SessionRunner, RunnerStatus, StreamEvent, StreamResult, HelperRunner

# Manager
from .manager import SessionManager, SessionInfo

# Debug
from .debug_log import debug_log, DebugLog, LogLevel, LogEntry, dump_failed_json, timed, perf_timed, perf_marker

# Base runner
from .base_runner import BaseRunner, RunnerEvent

# Exceptions
from .exceptions import RateLimitError, InputRequiredError, BackendNotFoundError

# Link tools
from .link_tools import LINK_TOOL_NAMES, execute_link_tool, register_app_tool_handler, unregister_app_tool_handler

# OpenAI runner
from .openai_runner import OpenAICompatibleRunner

# Runner factory
from .runner_factory import create_runner, resolve_env_var, validate_backend_config, ensure_prompts_installed

# Prompt builder (per-turn system prompt building)
from .prompt_builder import build_system_prompt, build_system_prompt_for_backend

# Tools
from .tools import (
    TOOLS,
    BALLOON_TOOLS,
    BALLOON_TOOL_NAMES,
    SUPERVISOR_TOOLS,
    SUPERVISOR_TOOL_NAMES,
    REVIEW_TOOLS,
    REVIEW_TOOL_NAMES,
    GOAL_TOOLS,
    GOAL_TOOL_NAMES,
    KANBAN_TOOLS,
    KANBAN_TOOL_NAMES,
    get_tools_for_request,
)

# Goal tools
from .goal_tools import execute_goal_tool

# Kanban tools
from .kanban_tools import execute_kanban_tool

# LSP tools
from .lsp_tools import execute_lsp_tool, LSP_TOOL_NAMES, LSP_TOOLS
from .lsp_client import get_lsp_client, LSPClient

# Tool executor
from .tool_executor import execute_tool, parse_fork_proposal, parse_create_slide, SlideData, parse_merge_proposal

# Summarizer
from .summarizer import Summarizer

# Context grouper
from .context_grouper import ContextGroups, group_messages_by_context_mode, build_context_messages

# Streaming
from .streaming import (
    StreamingContext,
    StreamingCoordinator,
    StreamingAction,
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
    ArchiveData,
    MergeData,
    LinkData,
    ReturnData,
)

# Fork operations
from .fork import (
    ForkManager,
    ForkResult,
    MergeResult,
    DeriveResult,
    SwitchResult,
    ForkProposal,
    MergeProposal,
    ContextAssignment,
    ForkData,
    DeriveData,
)

# Command executor
from .command_executor import (
    CommandExecutor,
    ArchiveResult,
    RehydrateResult,
    LinkResult,
    LinkTarget,
    BackendResult,
    BackendInfo,
)

# JSON streaming
from .json_stream import StreamingJsonParser

# Stream buffer
from .stream_buffer import StreamBuffer, Timer, TimerFactory

# Stream state (active LLM streams)
from .stream_state import (
    StreamState,
    Stream,
    StreamStatus,
    StreamType,
    SessionStreamInfo,
    AsyncObserver,
    get_stream_state,
    # Backward compatibility aliases (deprecated, use Stream* instead)
    TaskState,
    Task,
    TaskStatus,
    TaskType,
    TaskEvent,
    SessionTaskInfo,
    get_task_state,
)

# Queue state
from .queue_state import QueueState, QueueEvent, QueueSnapshot, QueuedMessageSnapshot, get_queue_state

# TTS
from .tts import TTSRunner, TTSConfig, TTSBackend, get_tts_runner, speak, stop_speaking

# Stash
from .stash import StashedMessage, MessageStash

# Preferences
from .preferences import DEFAULT_TOOLS, ToolPreferences

# Storage
from .async_storage import AsyncStorage, is_rust_storage_available, DEFAULT_DB_PATH, GoalStorage, get_goal_storage

# Goal binding context
from .binding_context import BindingContextBuilder, build_binding_context_for_session

# Lifecycle hooks
from .lifecycle_hooks import (
    LifecycleHooks,
    LifecyclePrompt,
    PostmortemOutcome,
    SpikeOutcome,
    on_todo_complete,
    on_plan_complete,
    execute_postmortem,
    execute_spike_outcome,
)

# Priority engine
from .priority_engine import PriorityEngine, TodoWithContext, get_priority_ranked_todos, get_next_todo, is_todo_available

# Goal commands
from .goal_commands import (
    GoalCommandExecutor,
    GoalListResult,
    PlanListResult,
    TodoListResult,
    TodoDoneResult,
    BindResult,
    UnbindResult,
    PriorityDivergenceInfo,
    check_priority_divergence,
    list_goals,
    list_plans,
    list_todos,
    mark_todo_done,
)

# Supervisor tools
from .supervisor_tools import (
    set_supervisor,
    get_supervisor,
    execute_supervisor_tool,
    get_running_count,
    stop_session_processes,
    shutdown_supervisor,
)

# Status reports
from .status_report import StatusReportGenerator, StatusReportData, GoalStatus, PlanStatus, TodoStatus

# Goal tree state
from .goal_tree_state import GoalTreeState

__all__ = [
    # Commands
    "Command",
    "CommandParser",
    "ArchiveCommand",
    "RehydrateCommand",
    "ReindexCommand",
    "NewSessionCommand",
    "CopyTurnsCommand",
    "QueryWithCommand",
    "SuspendCommand",
    "ShellCommand",
    "ForkCommand",
    "MergeCommand",
    "DeriveCommand",
    "SwitchCommand",
    "HistoryCommand",
    "ReturnCommand",
    "PwdCommand",
    "CdCommand",
    "ReloadCommand",
    "TitleCommand",
    "HelpCommand",
    "BackendCommand",
    "PrefsCommand",
    "EditConfigCommand",
    "EditPromptCommand",
    "LinkCommand",
    "DebugToggleCommand",
    "DebugClearCommand",
    "DebugPauseCommand",
    "DebugFpsCommand",
    "FollowCommand",
    "StashCommand",
    "PopCommand",
    "ClearAllSessionsCommand",
    "SnapCommand",
    "NewSlideCommand",
    "PresentCommand",
    "SlidesCommand",
    "ChatCommand",
    "SupervisorStartCommand",
    "SupervisorListCommand",
    "SupervisorLogsCommand",
    "SupervisorStopCommand",
    "ReviewCommand",
    "GoalInterviewCommand",
    "GoalsCommand",
    "PlansCommand",
    "TodosCommand",
    "TodoDoneCommand",
    "TodoUndoneCommand",
    "BindCommand",
    "UnbindCommand",
    "COMMAND_DOCS",
    # Context
    "ContextBuilder",
    # Formatter
    "Formatter",
    "format_edit_as_diff",
    "guess_language",
    # Runner
    "SessionRunner",
    "RunnerStatus",
    "StreamEvent",
    "StreamResult",
    "HelperRunner",
    # Manager
    "SessionManager",
    "SessionInfo",
    # Debug
    "debug_log",
    "DebugLog",
    "LogLevel",
    "LogEntry",
    "dump_failed_json",
    "timed",
    "perf_timed",
    "perf_marker",
    # Base runner
    "BaseRunner",
    "RunnerEvent",
    # Exceptions
    "RateLimitError",
    "InputRequiredError",
    "BackendNotFoundError",
    # Link tools
    "LINK_TOOL_NAMES",
    "execute_link_tool",
    "register_app_tool_handler",
    "unregister_app_tool_handler",
    # OpenAI runner
    "OpenAICompatibleRunner",
    # Runner factory
    "create_runner",
    "resolve_env_var",
    "validate_backend_config",
    "ensure_prompts_installed",
    # Prompt builder
    "build_system_prompt",
    "build_system_prompt_for_backend",
    # Tools
    "TOOLS",
    "BALLOON_TOOLS",
    "BALLOON_TOOL_NAMES",
    "SUPERVISOR_TOOLS",
    "SUPERVISOR_TOOL_NAMES",
    "REVIEW_TOOLS",
    "REVIEW_TOOL_NAMES",
    "GOAL_TOOLS",
    "GOAL_TOOL_NAMES",
    "KANBAN_TOOLS",
    "KANBAN_TOOL_NAMES",
    "get_tools_for_request",
    # Goal tools
    "execute_goal_tool",
    # Kanban tools
    "execute_kanban_tool",
    # LSP tools
    "execute_lsp_tool",
    "LSP_TOOL_NAMES",
    "LSP_TOOLS",
    "get_lsp_client",
    "LSPClient",
    # Tool executor
    "execute_tool",
    "parse_fork_proposal",
    "parse_merge_proposal",
    "parse_create_slide",
    "SlideData",
    # Summarizer
    "Summarizer",
    # Context grouper
    "ContextGroups",
    "group_messages_by_context_mode",
    "build_context_messages",
    # Streaming
    "StreamingContext",
    "StreamingCoordinator",
    "StreamingAction",
    "TextAction",
    "TextFlushAction",
    "InitAction",
    "ResultAction",
    "ToolUseStartAction",
    "ToolInputDeltaAction",
    "ToolUseCompleteAction",
    "ToolResultAction",
    "DoneAction",
    "ErrorAction",
    "RateLimitAction",
    "CancelledAction",
    "InputRequiredAction",
    "HelperDoneAction",
    "NoAction",
    "TurnStartedAction",
    "ArchiveData",
    "MergeData",
    "LinkData",
    "ReturnData",
    # Fork operations
    "ForkManager",
    "ForkResult",
    "MergeResult",
    "DeriveResult",
    "SwitchResult",
    "ForkProposal",
    "MergeProposal",
    "ContextAssignment",
    "ForkData",
    "DeriveData",
    # Command executor
    "CommandExecutor",
    "ArchiveResult",
    "RehydrateResult",
    "LinkResult",
    "LinkTarget",
    "BackendResult",
    "BackendInfo",
    # JSON streaming
    "StreamingJsonParser",
    # Stream buffer
    "StreamBuffer",
    "Timer",
    "TimerFactory",
    # Stream state
    "StreamState",
    "Stream",
    "StreamStatus",
    "StreamType",
    "SessionStreamInfo",
    "AsyncObserver",
    "get_stream_state",
    # Backward compat
    "TaskState",
    "Task",
    "TaskStatus",
    "TaskType",
    "TaskEvent",
    "SessionTaskInfo",
    "get_task_state",
    # Queue state
    "QueueState",
    "QueueEvent",
    "QueueSnapshot",
    "QueuedMessageSnapshot",
    "get_queue_state",
    # TTS
    "TTSRunner",
    "TTSConfig",
    "TTSBackend",
    "get_tts_runner",
    "speak",
    "stop_speaking",
    # Stash
    "StashedMessage",
    "MessageStash",
    # Preferences
    "DEFAULT_TOOLS",
    "ToolPreferences",
    # Storage
    "AsyncStorage",
    "is_rust_storage_available",
    "DEFAULT_DB_PATH",
    "GoalStorage",
    "get_goal_storage",
    # Goal binding context
    "BindingContextBuilder",
    "build_binding_context_for_session",
    # Lifecycle hooks
    "LifecycleHooks",
    "LifecyclePrompt",
    "PostmortemOutcome",
    "SpikeOutcome",
    "on_todo_complete",
    "on_plan_complete",
    "execute_postmortem",
    "execute_spike_outcome",
    # Priority engine
    "PriorityEngine",
    "TodoWithContext",
    "get_priority_ranked_todos",
    "get_next_todo",
    "is_todo_available",
    # Goal commands
    "GoalCommandExecutor",
    "GoalListResult",
    "PlanListResult",
    "TodoListResult",
    "TodoDoneResult",
    "BindResult",
    "UnbindResult",
    "PriorityDivergenceInfo",
    "check_priority_divergence",
    "list_goals",
    "list_plans",
    "list_todos",
    "mark_todo_done",
    # Supervisor tools
    "set_supervisor",
    "get_supervisor",
    "execute_supervisor_tool",
    "get_running_count",
    "stop_session_processes",
    "shutdown_supervisor",
    # Status reports
    "StatusReportGenerator",
    "StatusReportData",
    "GoalStatus",
    "PlanStatus",
    "TodoStatus",
    # Goal tree state
    "GoalTreeState",
]
