"""Command parsing for Balloons.

Extracts command parsing from app.py into a GUI-independent module.
Commands are prefixed with ':' and map to specific actions.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Command:
    """Base class for all commands."""
    pass


@dataclass
class NewSessionCommand(Command):
    """Create a new session, optionally with an initial prompt."""
    initial_prompt: str = ""


@dataclass
class CopyTurnsCommand(Command):
    """Copy selected turns to a new session."""
    pass


@dataclass
class QueryWithCommand(Command):
    """Query with selected context, response goes to new session."""
    prompt: str = ""


@dataclass
class SuspendCommand(Command):
    """Suspend TUI and run interactive shell command."""
    shell_cmd: str = ""


@dataclass
class ShellCommand(Command):
    """Run shell command and send output to Claude."""
    shell_cmd: str = ""


@dataclass
class WithCommand(Command):
    """Fork child session with summarized context."""
    prompt: str = ""
    return_condition: str = "manual"
    background: bool = False


@dataclass
class WithCopyCommand(Command):
    """Fork child session copying context verbatim."""
    prompt: str = ""
    return_condition: str = "manual"
    background: bool = False


@dataclass
class ReturnCommand(Command):
    """Return from child session to parent."""
    return_prompt: str = ""


@dataclass
class PwdCommand(Command):
    """Show current working directory."""
    pass


@dataclass
class CdCommand(Command):
    """Change working directory."""
    path: str = ""


@dataclass
class ReloadCommand(Command):
    """Hot reload the app."""
    pass


@dataclass
class SummarizeCommand(Command):
    """Generate title and summary for session."""
    mode: str = "quick"  # "quick" or "detailed"


class CommandParser:
    """Parse user input into Command objects.

    Usage:
        parser = CommandParser()
        cmd = parser.parse(":new some prompt")
        if cmd:
            # Handle command
        else:
            # Regular prompt, send to Claude
    """

    def parse(self, text: str) -> Optional[Command]:
        """Parse input text into a Command, or None if it's a regular prompt.

        Returns:
            Command if input is a recognized command
            None if input is a regular prompt to send to Claude

        Raises:
            ValueError if input is an unrecognized command
        """
        text = text.strip()

        if not text.startswith(":"):
            return None

        # Handle :copy-turns
        if text == ":copy-turns":
            return CopyTurnsCommand()

        # Handle :new [prompt]
        if text == ":new" or text.startswith(":new "):
            initial_prompt = text[4:].strip() if len(text) > 4 else ""
            return NewSessionCommand(initial_prompt=initial_prompt)

        # Handle :query-with <prompt>
        if text == ":query-with" or text.startswith(":query-with "):
            prompt = text[len(":query-with"):].strip()
            if prompt:
                return QueryWithCommand(prompt=prompt)
            raise ValueError(":query-with requires a prompt")

        # Handle :suspend <cmd>
        if text == ":suspend" or text.startswith(":suspend "):
            shell_cmd = text[8:].strip()
            if shell_cmd:
                return SuspendCommand(shell_cmd=shell_cmd)
            raise ValueError(":suspend requires a command")

        # Handle :!<cmd>
        if text.startswith(":!"):
            shell_cmd = text[2:].strip()
            if shell_cmd:
                return ShellCommand(shell_cmd=shell_cmd)
            raise ValueError(":! requires a command")

        # Handle :with-copy <prompt> [--until condition] [--bg]
        if text.startswith(":with-copy"):
            args = text[10:].strip()
            if not args:
                raise ValueError(":with-copy requires a prompt")
            prompt, return_condition, background = self._parse_with_args(args)
            return WithCopyCommand(prompt=prompt, return_condition=return_condition, background=background)

        # Handle :with <prompt> [--until condition] [--bg]
        if text.startswith(":with"):
            args = text[5:].strip()
            if not args:
                raise ValueError(":with requires a prompt")
            prompt, return_condition, background = self._parse_with_args(args)
            return WithCommand(prompt=prompt, return_condition=return_condition, background=background)

        # Handle :return [message]
        if text.startswith(":return"):
            return_prompt = text[7:].strip() if len(text) > 7 else ""
            return ReturnCommand(return_prompt=return_prompt)

        # Handle :pwd
        if text == ":pwd":
            return PwdCommand()

        # Handle :cd [path]
        if text.startswith(":cd"):
            path = text[3:].strip() if len(text) > 3 else ""
            return CdCommand(path=path)

        # Handle :reload
        if text == ":reload":
            return ReloadCommand()

        # Handle :summarize [quick|detailed]
        if text.startswith(":summarize"):
            args = text[10:].strip() if len(text) > 10 else ""
            mode = args if args in ("quick", "detailed") else "quick"
            return SummarizeCommand(mode=mode)

        # Unknown command
        cmd_name = text.split()[0]
        raise ValueError(f"Unknown command: {cmd_name}")

    def _parse_with_args(self, args: str) -> tuple[str, str, bool]:
        """Parse :with/:with-copy arguments into (prompt, return_condition, background)."""
        return_condition = "manual"
        background = False
        prompt = args

        # Check for --bg flag
        if " --bg" in args or args.endswith("--bg"):
            background = True
            args = args.replace(" --bg", "").replace("--bg", "").strip()
            prompt = args

        if " --until " in args:
            parts = args.split(" --until ", 1)
            prompt = parts[0].strip()
            return_condition = parts[1].strip()
        elif args.endswith(" --until"):
            prompt = args[:-8].strip()
            return_condition = "manual"

        return prompt, return_condition, background
