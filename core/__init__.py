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
from .prompt_builder import build_system_prompt, build_system_prompt_for_backend
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
    get_tools_for_request,
)
from .lsp_tools import execute_lsp_tool, LSP_TOOL_NAMES, LSP_TOOLS
from .lsp_client import get_lsp_client, LSPClient
from .tool_executor import execute_tool, parse_fork_proposal, parse_create_slide, SlideData, parse_merge_proposal
from .tool_result import ToolExecutionResult
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
    MergeProposal,
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
from .async_storage import AsyncStorage, is_rust_storage_available, DEFAULT_DB_PATH
from .supervisor_tools import (
    set_supervisor,
    get_supervisor,
    execute_supervisor_tool,
    get_running_count,
    stop_session_processes,
    shutdown_supervisor,
)

__all__ = [name for name in globals() if not name.startswith("_")]
