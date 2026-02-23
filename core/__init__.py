"""Core module - GUI-independent business logic for Balloons.

This module uses lazy imports to avoid loading all submodules at once.
Direct imports from submodules (e.g., `from core.debug_log import debug_log`)
will only load that specific submodule.

For backwards compatibility, accessing attributes on the `core` module will
trigger lazy loading of the required submodule.
"""

from typing import TYPE_CHECKING

# Type hints for static analysis - these don't trigger imports at runtime
if TYPE_CHECKING:
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
    from .context import ContextBuilder
    from .formatter import Formatter, format_edit_as_diff, guess_language
    from .runner import SessionRunner, RunnerStatus, StreamEvent, StreamResult, HelperRunner
    from .manager import SessionManager, SessionInfo
    from .debug_log import debug_log, DebugLog, LogLevel, LogEntry, dump_failed_json, timed, perf_timed, perf_marker
    from .base_runner import BaseRunner, RunnerEvent
    from .exceptions import RateLimitError, InputRequiredError, BackendNotFoundError
    from .link_tools import LINK_TOOL_NAMES, execute_link_tool, register_app_tool_handler, unregister_app_tool_handler
    from .openai_runner import OpenAICompatibleRunner
    from .runner_factory import create_runner, resolve_env_var, validate_backend_config, ensure_prompts_installed
    from .tools import TOOLS, BALLOON_TOOLS, BALLOON_TOOL_NAMES, SUPERVISOR_TOOLS, SUPERVISOR_TOOL_NAMES, REVIEW_TOOLS, REVIEW_TOOL_NAMES, GOAL_TOOLS, GOAL_TOOL_NAMES, get_tools_for_request
    from .goal_tools import execute_goal_tool
    from .tool_executor import execute_tool, parse_fork_proposal, parse_create_slide, SlideData
    from .summarizer import Summarizer
    from .context_grouper import ContextGroups, group_messages_by_context_mode, build_context_messages
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
    from .fork import (
        ForkManager,
        ForkResult,
        MergeResult,
        DeriveResult,
        SwitchResult,
        ForkProposal,
        ContextAssignment,
        ForkData,
        DeriveData,
    )
    from .command_executor import (
        CommandExecutor,
        ArchiveResult,
        RehydrateResult,
        LinkResult,
        LinkTarget,
        BackendResult,
        BackendInfo,
    )
    from .json_stream import StreamingJsonParser
    from .stream_buffer import StreamBuffer, Timer, TimerFactory
    from .stream_state import (
        StreamState,
        Stream,
        StreamStatus,
        StreamType,
        StreamEvent,
        SessionStreamInfo,
        AsyncObserver,
        get_stream_state,
        TaskState,
        Task,
        TaskStatus,
        TaskType,
        TaskEvent,
        SessionTaskInfo,
        get_task_state,
    )
    from .queue_state import QueueState, QueueEvent, QueueSnapshot, QueuedMessageSnapshot, get_queue_state
    from .tts import TTSRunner, TTSConfig, TTSBackend, get_tts_runner, speak, stop_speaking
    from .stash import StashedMessage, MessageStash
    from .preferences import DEFAULT_TOOLS, ToolPreferences
    from .async_storage import AsyncStorage, is_rust_storage_available, DEFAULT_DB_PATH, GoalStorage, get_goal_storage
    from .binding_context import BindingContextBuilder, build_binding_context_for_session
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
    from .priority_engine import PriorityEngine, TodoWithContext, get_priority_ranked_todos, get_next_todo, is_todo_available
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
    from .supervisor_tools import (
        SUPERVISOR_TOOL_NAMES as SUP_TOOL_NAMES,
        set_supervisor,
        get_supervisor,
        execute_supervisor_tool,
        get_running_count,
        stop_session_processes,
    )
    from .status_report import StatusReportGenerator, StatusReportData, GoalStatus, PlanStatus, TodoStatus


# Mapping from attribute name to (module_name, attribute_name)
# Used by __getattr__ for lazy loading
_LAZY_IMPORTS = {
    # Commands
    "Command": (".commands", "Command"),
    "CommandParser": (".commands", "CommandParser"),
    "ArchiveCommand": (".commands", "ArchiveCommand"),
    "RehydrateCommand": (".commands", "RehydrateCommand"),
    "ReindexCommand": (".commands", "ReindexCommand"),
    "NewSessionCommand": (".commands", "NewSessionCommand"),
    "CopyTurnsCommand": (".commands", "CopyTurnsCommand"),
    "QueryWithCommand": (".commands", "QueryWithCommand"),
    "SuspendCommand": (".commands", "SuspendCommand"),
    "ShellCommand": (".commands", "ShellCommand"),
    "ForkCommand": (".commands", "ForkCommand"),
    "MergeCommand": (".commands", "MergeCommand"),
    "DeriveCommand": (".commands", "DeriveCommand"),
    "SwitchCommand": (".commands", "SwitchCommand"),
    "HistoryCommand": (".commands", "HistoryCommand"),
    "ReturnCommand": (".commands", "ReturnCommand"),
    "PwdCommand": (".commands", "PwdCommand"),
    "CdCommand": (".commands", "CdCommand"),
    "ReloadCommand": (".commands", "ReloadCommand"),
    "TitleCommand": (".commands", "TitleCommand"),
    "HelpCommand": (".commands", "HelpCommand"),
    "BackendCommand": (".commands", "BackendCommand"),
    "PrefsCommand": (".commands", "PrefsCommand"),
    "EditConfigCommand": (".commands", "EditConfigCommand"),
    "EditPromptCommand": (".commands", "EditPromptCommand"),
    "LinkCommand": (".commands", "LinkCommand"),
    "DebugToggleCommand": (".commands", "DebugToggleCommand"),
    "DebugClearCommand": (".commands", "DebugClearCommand"),
    "DebugPauseCommand": (".commands", "DebugPauseCommand"),
    "DebugFpsCommand": (".commands", "DebugFpsCommand"),
    "FollowCommand": (".commands", "FollowCommand"),
    "StashCommand": (".commands", "StashCommand"),
    "PopCommand": (".commands", "PopCommand"),
    "ClearAllSessionsCommand": (".commands", "ClearAllSessionsCommand"),
    "SnapCommand": (".commands", "SnapCommand"),
    "NewSlideCommand": (".commands", "NewSlideCommand"),
    "PresentCommand": (".commands", "PresentCommand"),
    "SlidesCommand": (".commands", "SlidesCommand"),
    "ChatCommand": (".commands", "ChatCommand"),
    "SupervisorStartCommand": (".commands", "SupervisorStartCommand"),
    "SupervisorListCommand": (".commands", "SupervisorListCommand"),
    "SupervisorLogsCommand": (".commands", "SupervisorLogsCommand"),
    "SupervisorStopCommand": (".commands", "SupervisorStopCommand"),
    "ReviewCommand": (".commands", "ReviewCommand"),
    "GoalInterviewCommand": (".commands", "GoalInterviewCommand"),
    "GoalsCommand": (".commands", "GoalsCommand"),
    "PlansCommand": (".commands", "PlansCommand"),
    "TodosCommand": (".commands", "TodosCommand"),
    "TodoDoneCommand": (".commands", "TodoDoneCommand"),
    "TodoUndoneCommand": (".commands", "TodoUndoneCommand"),
    "BindCommand": (".commands", "BindCommand"),
    "UnbindCommand": (".commands", "UnbindCommand"),
    "COMMAND_DOCS": (".commands", "COMMAND_DOCS"),
    # Context
    "ContextBuilder": (".context", "ContextBuilder"),
    # Formatter
    "Formatter": (".formatter", "Formatter"),
    "format_edit_as_diff": (".formatter", "format_edit_as_diff"),
    "guess_language": (".formatter", "guess_language"),
    # Runner
    "SessionRunner": (".runner", "SessionRunner"),
    "RunnerStatus": (".runner", "RunnerStatus"),
    "StreamEvent": (".runner", "StreamEvent"),
    "StreamResult": (".runner", "StreamResult"),
    "HelperRunner": (".runner", "HelperRunner"),
    # Manager
    "SessionManager": (".manager", "SessionManager"),
    "SessionInfo": (".manager", "SessionInfo"),
    # Debug
    "debug_log": (".debug_log", "debug_log"),
    "DebugLog": (".debug_log", "DebugLog"),
    "LogLevel": (".debug_log", "LogLevel"),
    "LogEntry": (".debug_log", "LogEntry"),
    "dump_failed_json": (".debug_log", "dump_failed_json"),
    "timed": (".debug_log", "timed"),
    "perf_timed": (".debug_log", "perf_timed"),
    "perf_marker": (".debug_log", "perf_marker"),
    # Base runner
    "BaseRunner": (".base_runner", "BaseRunner"),
    "RunnerEvent": (".base_runner", "RunnerEvent"),
    "OpenAICompatibleRunner": (".openai_runner", "OpenAICompatibleRunner"),
    "create_runner": (".runner_factory", "create_runner"),
    "resolve_env_var": (".runner_factory", "resolve_env_var"),
    "validate_backend_config": (".runner_factory", "validate_backend_config"),
    "ensure_prompts_installed": (".runner_factory", "ensure_prompts_installed"),
    # Tools
    "TOOLS": (".tools", "TOOLS"),
    "BALLOON_TOOLS": (".tools", "BALLOON_TOOLS"),
    "BALLOON_TOOL_NAMES": (".tools", "BALLOON_TOOL_NAMES"),
    "SUPERVISOR_TOOLS": (".tools", "SUPERVISOR_TOOLS"),
    "SUPERVISOR_TOOL_NAMES": (".tools", "SUPERVISOR_TOOL_NAMES"),
    "REVIEW_TOOLS": (".tools", "REVIEW_TOOLS"),
    "REVIEW_TOOL_NAMES": (".tools", "REVIEW_TOOL_NAMES"),
    "GOAL_TOOLS": (".tools", "GOAL_TOOLS"),
    "GOAL_TOOL_NAMES": (".tools", "GOAL_TOOL_NAMES"),
    "execute_goal_tool": (".goal_tools", "execute_goal_tool"),
    "get_tools_for_request": (".tools", "get_tools_for_request"),
    "LINK_TOOL_NAMES": (".link_tools", "LINK_TOOL_NAMES"),
    "execute_tool": (".tool_executor", "execute_tool"),
    "parse_fork_proposal": (".tool_executor", "parse_fork_proposal"),
    "parse_create_slide": (".tool_executor", "parse_create_slide"),
    "SlideData": (".tool_executor", "SlideData"),
    "register_app_tool_handler": (".link_tools", "register_app_tool_handler"),
    "unregister_app_tool_handler": (".link_tools", "unregister_app_tool_handler"),
    # Supervisor tools
    "set_supervisor": (".supervisor_tools", "set_supervisor"),
    "get_supervisor": (".supervisor_tools", "get_supervisor"),
    "execute_supervisor_tool": (".supervisor_tools", "execute_supervisor_tool"),
    "get_running_count": (".supervisor_tools", "get_running_count"),
    "stop_session_processes": (".supervisor_tools", "stop_session_processes"),
    # Summarizer
    "Summarizer": (".summarizer", "Summarizer"),
    # Context grouper
    "ContextGroups": (".context_grouper", "ContextGroups"),
    "group_messages_by_context_mode": (".context_grouper", "group_messages_by_context_mode"),
    "build_context_messages": (".context_grouper", "build_context_messages"),
    # Streaming
    "StreamingContext": (".streaming", "StreamingContext"),
    "StreamingCoordinator": (".streaming", "StreamingCoordinator"),
    "StreamingAction": (".streaming", "StreamingAction"),
    "TextAction": (".streaming", "TextAction"),
    "TextFlushAction": (".streaming", "TextFlushAction"),
    "InitAction": (".streaming", "InitAction"),
    "ResultAction": (".streaming", "ResultAction"),
    "ToolUseStartAction": (".streaming", "ToolUseStartAction"),
    "ToolInputDeltaAction": (".streaming", "ToolInputDeltaAction"),
    "ToolUseCompleteAction": (".streaming", "ToolUseCompleteAction"),
    "ToolResultAction": (".streaming", "ToolResultAction"),
    "DoneAction": (".streaming", "DoneAction"),
    "ErrorAction": (".streaming", "ErrorAction"),
    "RateLimitAction": (".streaming", "RateLimitAction"),
    "CancelledAction": (".streaming", "CancelledAction"),
    "InputRequiredAction": (".streaming", "InputRequiredAction"),
    "HelperDoneAction": (".streaming", "HelperDoneAction"),
    "NoAction": (".streaming", "NoAction"),
    "TurnStartedAction": (".streaming", "TurnStartedAction"),
    "ArchiveData": (".streaming", "ArchiveData"),
    "MergeData": (".streaming", "MergeData"),
    "LinkData": (".streaming", "LinkData"),
    "ReturnData": (".streaming", "ReturnData"),
    # Fork operations
    "ForkManager": (".fork", "ForkManager"),
    "ForkResult": (".fork", "ForkResult"),
    "MergeResult": (".fork", "MergeResult"),
    "DeriveResult": (".fork", "DeriveResult"),
    "SwitchResult": (".fork", "SwitchResult"),
    "ForkProposal": (".fork", "ForkProposal"),
    "ContextAssignment": (".fork", "ContextAssignment"),
    "ForkData": (".fork", "ForkData"),
    "DeriveData": (".fork", "DeriveData"),
    # Command executor
    "CommandExecutor": (".command_executor", "CommandExecutor"),
    "ArchiveResult": (".command_executor", "ArchiveResult"),
    "RehydrateResult": (".command_executor", "RehydrateResult"),
    "LinkResult": (".command_executor", "LinkResult"),
    "LinkTarget": (".command_executor", "LinkTarget"),
    "BackendResult": (".command_executor", "BackendResult"),
    "BackendInfo": (".command_executor", "BackendInfo"),
    # JSON streaming
    "StreamingJsonParser": (".json_stream", "StreamingJsonParser"),
    # Exceptions
    "RateLimitError": (".exceptions", "RateLimitError"),
    "InputRequiredError": (".exceptions", "InputRequiredError"),
    "BackendNotFoundError": (".exceptions", "BackendNotFoundError"),
    # Link tools
    "execute_link_tool": (".link_tools", "execute_link_tool"),
    # Stream buffer
    "StreamBuffer": (".stream_buffer", "StreamBuffer"),
    "Timer": (".stream_buffer", "Timer"),
    "TimerFactory": (".stream_buffer", "TimerFactory"),
    # Stream state (active LLM streams)
    "StreamState": (".stream_state", "StreamState"),
    "Stream": (".stream_state", "Stream"),
    "StreamStatus": (".stream_state", "StreamStatus"),
    "StreamType": (".stream_state", "StreamType"),
    # Note: StreamEvent already defined above for .runner
    "SessionStreamInfo": (".stream_state", "SessionStreamInfo"),
    "AsyncObserver": (".stream_state", "AsyncObserver"),
    "get_stream_state": (".stream_state", "get_stream_state"),
    # Backward compatibility aliases (deprecated, use Stream* instead)
    "TaskState": (".stream_state", "TaskState"),
    "Task": (".stream_state", "Task"),
    "TaskStatus": (".stream_state", "TaskStatus"),
    "TaskType": (".stream_state", "TaskType"),
    "TaskEvent": (".stream_state", "TaskEvent"),
    "SessionTaskInfo": (".stream_state", "SessionTaskInfo"),
    "get_task_state": (".stream_state", "get_task_state"),
    # Queue state
    "QueueState": (".queue_state", "QueueState"),
    "QueueEvent": (".queue_state", "QueueEvent"),
    "QueueSnapshot": (".queue_state", "QueueSnapshot"),
    "QueuedMessageSnapshot": (".queue_state", "QueuedMessageSnapshot"),
    "get_queue_state": (".queue_state", "get_queue_state"),
    # TTS
    "TTSRunner": (".tts", "TTSRunner"),
    "TTSConfig": (".tts", "TTSConfig"),
    "TTSBackend": (".tts", "TTSBackend"),
    "get_tts_runner": (".tts", "get_tts_runner"),
    "speak": (".tts", "speak"),
    "stop_speaking": (".tts", "stop_speaking"),
    # Stash
    "StashedMessage": (".stash", "StashedMessage"),
    "MessageStash": (".stash", "MessageStash"),
    # Preferences
    "DEFAULT_TOOLS": (".preferences", "DEFAULT_TOOLS"),
    "ToolPreferences": (".preferences", "ToolPreferences"),
    # Storage
    "AsyncStorage": (".async_storage", "AsyncStorage"),
    "is_rust_storage_available": (".async_storage", "is_rust_storage_available"),
    "DEFAULT_DB_PATH": (".async_storage", "DEFAULT_DB_PATH"),
    "GoalStorage": (".async_storage", "GoalStorage"),
    "get_goal_storage": (".async_storage", "get_goal_storage"),
    # Goal binding context
    "BindingContextBuilder": (".binding_context", "BindingContextBuilder"),
    "build_binding_context_for_session": (".binding_context", "build_binding_context_for_session"),
    # Lifecycle hooks
    "LifecycleHooks": (".lifecycle_hooks", "LifecycleHooks"),
    "LifecyclePrompt": (".lifecycle_hooks", "LifecyclePrompt"),
    "PostmortemOutcome": (".lifecycle_hooks", "PostmortemOutcome"),
    "SpikeOutcome": (".lifecycle_hooks", "SpikeOutcome"),
    "on_todo_complete": (".lifecycle_hooks", "on_todo_complete"),
    "on_plan_complete": (".lifecycle_hooks", "on_plan_complete"),
    "execute_postmortem": (".lifecycle_hooks", "execute_postmortem"),
    "execute_spike_outcome": (".lifecycle_hooks", "execute_spike_outcome"),
    # Priority engine
    "PriorityEngine": (".priority_engine", "PriorityEngine"),
    "TodoWithContext": (".priority_engine", "TodoWithContext"),
    "get_priority_ranked_todos": (".priority_engine", "get_priority_ranked_todos"),
    "get_next_todo": (".priority_engine", "get_next_todo"),
    "is_todo_available": (".priority_engine", "is_todo_available"),
    # Goal commands
    "GoalCommandExecutor": (".goal_commands", "GoalCommandExecutor"),
    "GoalListResult": (".goal_commands", "GoalListResult"),
    "PlanListResult": (".goal_commands", "PlanListResult"),
    "TodoListResult": (".goal_commands", "TodoListResult"),
    "TodoDoneResult": (".goal_commands", "TodoDoneResult"),
    "BindResult": (".goal_commands", "BindResult"),
    "UnbindResult": (".goal_commands", "UnbindResult"),
    "PriorityDivergenceInfo": (".goal_commands", "PriorityDivergenceInfo"),
    "check_priority_divergence": (".goal_commands", "check_priority_divergence"),
    "list_goals": (".goal_commands", "list_goals"),
    "list_plans": (".goal_commands", "list_plans"),
    "list_todos": (".goal_commands", "list_todos"),
    "mark_todo_done": (".goal_commands", "mark_todo_done"),
    # Status reports
    "StatusReportGenerator": (".status_report", "StatusReportGenerator"),
    "StatusReportData": (".status_report", "StatusReportData"),
    "GoalStatus": (".status_report", "GoalStatus"),
    "PlanStatus": (".status_report", "PlanStatus"),
    "TodoStatus": (".status_report", "TodoStatus"),
}

# Alias for SUPERVISOR_TOOL_NAMES (it's imported twice with different names)
# We handle this specially because of the "as SUP_TOOL_NAMES" import
_LAZY_IMPORTS["SUP_TOOL_NAMES"] = (".supervisor_tools", "SUPERVISOR_TOOL_NAMES")


def __getattr__(name: str):
    """Lazy import handler for the core package.

    When accessing an attribute that's not in the module's namespace,
    Python calls this function. We look up the attribute in _LAZY_IMPORTS
    and dynamically import the required submodule.

    This allows code like `from core import debug_log` to work without
    loading all of the core package's submodules.
    """
    if name in _LAZY_IMPORTS:
        module_name, attr_name = _LAZY_IMPORTS[name]
        import importlib
        module = importlib.import_module(module_name, package="core")
        value = getattr(module, attr_name)
        # Cache in module namespace for subsequent accesses
        globals()[name] = value
        return value
    raise AttributeError(f"module 'core' has no attribute {name!r}")


def __dir__():
    """List all available attributes including lazy imports."""
    return list(_LAZY_IMPORTS.keys()) + list(globals().keys())


__all__ = list(_LAZY_IMPORTS.keys())
