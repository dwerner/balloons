"""Core module - GUI-independent business logic for Balloons."""

from .commands import (
    Command,
    CommandParser,
    ArchiveCommand,
    RehydrateCommand,
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
    LinkCommand,
    DebugToggleCommand,
    DebugClearCommand,
    DebugPauseCommand,
    COMMAND_DOCS,
)
from .context import ContextBuilder
from .formatter import Formatter, format_edit_as_diff, guess_language
from .runner import SessionRunner, RunnerStatus, StreamEvent, StreamResult, HelperRunner
from .manager import SessionManager, SessionInfo
from .debug_log import debug_log, DebugLog, LogLevel, LogEntry, dump_failed_json
from .base_runner import BaseRunner, RunnerEvent
from .exceptions import RateLimitError, InputRequiredError, BackendNotFoundError
from .link_tools import LINK_TOOLS, get_link_tools_prompt, execute_link_tool
from .openai_runner import OpenAICompatibleRunner
from .runner_factory import create_runner, resolve_env_var
from .tools import TOOLS, LINK_TOOLS as LINK_TOOLS_OPENAI, LINK_TOOL_NAMES, get_tools_for_request
from .tool_executor import execute_tool
from .summarizer import Summarizer
from .context_grouper import (
    ContextGroups,
    group_messages_by_context_mode,
    build_context_messages,
)
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
)
from .fork import (
    ForkManager,
    ForkResult,
    MergeResult,
    DeriveResult,
    SwitchResult,
)
from .json_stream import StreamingJsonParser

__all__ = [
    # Commands
    "Command",
    "CommandParser",
    "ArchiveCommand",
    "RehydrateCommand",
    "NewSessionCommand",
    "CopyTurnsCommand",
    "QueryWithCommand",
    "SuspendCommand",
    "ShellCommand",
    "ForkCommand",
    "MergeCommand",
    "DeriveCommand",
    "SwitchCommand",
    "ReturnCommand",
    "PwdCommand",
    "CdCommand",
    "ReloadCommand",
    "TitleCommand",
    "HelpCommand",
    "BackendCommand",
    "LinkCommand",
    "DebugToggleCommand",
    "DebugClearCommand",
    "DebugPauseCommand",
    "COMMAND_DOCS",
    # Context
    "ContextBuilder",
    # Formatting
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
    # Base runner
    "BaseRunner",
    "RunnerEvent",
    "OpenAICompatibleRunner",
    "create_runner",
    "resolve_env_var",
    # Tools
    "TOOLS",
    "LINK_TOOLS_OPENAI",
    "LINK_TOOL_NAMES",
    "get_tools_for_request",
    "execute_tool",
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
    # Fork operations
    "ForkManager",
    "ForkResult",
    "MergeResult",
    "DeriveResult",
    "SwitchResult",
    # JSON streaming
    "StreamingJsonParser",
    # Exceptions
    "RateLimitError",
    "InputRequiredError",
    "BackendNotFoundError",
    # Link tools
    "LINK_TOOLS",
    "get_link_tools_prompt",
    "execute_link_tool",
]
