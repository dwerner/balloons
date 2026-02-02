"""Core module - GUI-independent business logic for Balloons."""

from .commands import (
    Command,
    CommandParser,
    NewSessionCommand,
    CopyTurnsCommand,
    QueryWithCommand,
    SuspendCommand,
    ShellCommand,
    ForkCommand,
    MergeCommand,
    DeriveCommand,
    SwitchCommand,
    # Legacy aliases
    WithCommand,
    WithCopyCommand,
    ReturnCommand,
    PwdCommand,
    CdCommand,
    ReloadCommand,
    TitleCommand,
    HelpCommand,
    BackendCommand,
    COMMAND_DOCS,
)
from .context import ContextBuilder
from .formatter import Formatter, format_edit_as_diff, guess_language
from .runner import SessionRunner, RunnerStatus, StreamEvent, StreamResult, HelperRunner
from .manager import SessionManager, SessionInfo
from .debug_log import debug_log, DebugLog, LogLevel, LogEntry
from .base_runner import BaseRunner, RunnerEvent
from .openai_runner import OpenAICompatibleRunner
from .runner_factory import create_runner, resolve_env_var
from .tools import TOOLS, get_tools_for_request
from .tool_executor import execute_tool

__all__ = [
    # Commands
    "Command",
    "CommandParser",
    "NewSessionCommand",
    "CopyTurnsCommand",
    "QueryWithCommand",
    "SuspendCommand",
    "ShellCommand",
    "ForkCommand",
    "MergeCommand",
    "DeriveCommand",
    "SwitchCommand",
    # Legacy aliases
    "WithCommand",
    "WithCopyCommand",
    "ReturnCommand",
    "PwdCommand",
    "CdCommand",
    "ReloadCommand",
    "TitleCommand",
    "HelpCommand",
    "BackendCommand",
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
    # Base runner
    "BaseRunner",
    "RunnerEvent",
    "OpenAICompatibleRunner",
    "create_runner",
    "resolve_env_var",
    # Tools
    "TOOLS",
    "get_tools_for_request",
    "execute_tool",
]
