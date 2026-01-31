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
    SummarizeCommand,
)
from .context import ContextBuilder
from .formatter import Formatter, format_edit_as_diff, guess_language
from .runner import SessionRunner, RunnerStatus, StreamEvent, StreamResult
from .manager import SessionManager, SessionInfo
from .debug_log import debug_log, DebugLog, LogLevel, LogEntry

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
    "SummarizeCommand",
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
    # Manager
    "SessionManager",
    "SessionInfo",
    # Debug
    "debug_log",
    "DebugLog",
    "LogLevel",
    "LogEntry",
]
