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
    """Create a new blank session, optionally with an initial prompt."""
    prompt: str = ""


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
class ForkCommand(Command):
    """Fork a child session from current session.

    Creates a child session that can be merged back.
    Context modes (COPY/COMPRESS/DROP) control what's inherited.
    """
    prompt: str = ""
    name: str = ""  # Optional fork name for easy reference
    background: bool = False


@dataclass
class MergeCommand(Command):
    """Merge fork back to parent.

    Takes a prompt that directs the LLM to summarize the fork's work.
    The LLM generates the merge message. Fork becomes read-only after merge.
    """
    prompt: str = ""  # Optional prompt to guide summary generation


@dataclass
class DeriveCommand(Command):
    """Create a new independent session with selected context.

    Like fork but no parent relationship - won't merge back.
    """
    prompt: str = ""


@dataclass
class SwitchCommand(Command):
    """Switch view to a different session or fork.

    Without name: show picker
    With name: switch to that named fork
    """
    name: str = ""


# Legacy aliases for backwards compatibility
@dataclass
class WithCommand(Command):
    """Fork child session with summarized context. (Legacy - use :fork)"""
    prompt: str = ""
    return_condition: str = "manual"
    background: bool = False


@dataclass
class WithCopyCommand(Command):
    """Fork child session copying context verbatim. (Legacy - use :fork)"""
    prompt: str = ""
    return_condition: str = "manual"
    background: bool = False


@dataclass
class ReturnCommand(Command):
    """Return from child session to parent. (Legacy - use :merge)"""
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
class TitleCommand(Command):
    """Set session title."""
    title: str = ""


class CommandParser:
    """Parse user input into Command objects.

    Usage:
        parser = CommandParser()
        cmd = parser.parse(":new")
        if cmd:
            # Handle command
        else:
            # Regular prompt, send to Claude

    Commands:
        :new [prompt]           - Create new session, optionally with initial prompt
        :fork[=name] <prompt>   - Fork with selected context, start working
        :merge [prompt]         - Merge fork back to parent (LLM summarizes)
        :derive <prompt>        - New independent session with selected context
        :switch [name]          - Switch to fork/session (picker if no name)
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
            prompt = text[4:].strip() if len(text) > 4 else ""
            return NewSessionCommand(prompt=prompt)

        # Handle :fork[=name] <prompt> [--bg]
        if text.startswith(":fork"):
            return self._parse_fork(text)

        # Handle :merge [prompt]
        if text == ":merge" or text.startswith(":merge "):
            prompt = text[6:].strip() if len(text) > 6 else ""
            return MergeCommand(prompt=prompt)

        # Handle :derive <prompt>
        if text.startswith(":derive"):
            prompt = text[7:].strip()
            if not prompt:
                raise ValueError(":derive requires a prompt")
            return DeriveCommand(prompt=prompt)

        # Handle :switch [name]
        if text == ":switch" or text.startswith(":switch "):
            name = text[7:].strip() if len(text) > 7 else ""
            return SwitchCommand(name=name)

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

        # Legacy: :with-copy → convert to ForkCommand
        if text.startswith(":with-copy"):
            args = text[10:].strip()
            if not args:
                raise ValueError(":with-copy requires a prompt")
            prompt, return_condition, background = self._parse_with_args(args)
            return WithCopyCommand(prompt=prompt, return_condition=return_condition, background=background)

        # Legacy: :with → convert to ForkCommand
        if text.startswith(":with"):
            args = text[5:].strip()
            if not args:
                raise ValueError(":with requires a prompt")
            prompt, return_condition, background = self._parse_with_args(args)
            return WithCommand(prompt=prompt, return_condition=return_condition, background=background)

        # Legacy: :return → convert to MergeCommand
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

        # Handle :title <title>
        if text.startswith(":title"):
            title = text[6:].strip() if len(text) > 6 else ""
            if not title:
                raise ValueError(":title requires a title")
            return TitleCommand(title=title)

        # Unknown command
        cmd_name = text.split()[0]
        raise ValueError(f"Unknown command: {cmd_name}")

    def _parse_fork(self, text: str) -> ForkCommand:
        """Parse :fork[=name] <prompt> [--bg] command."""
        # Check for =name syntax: :fork=auth-bug <prompt>
        name = ""
        remaining = text[5:]  # Remove ":fork"

        if remaining.startswith("="):
            # Extract name until space
            eq_part = remaining[1:]  # Remove "="
            if " " in eq_part:
                name, remaining = eq_part.split(" ", 1)
            else:
                name = eq_part
                remaining = ""
        else:
            remaining = remaining.strip()

        if not remaining:
            raise ValueError(":fork requires a prompt")

        # Check for --bg flag
        background = False
        if " --bg" in remaining or remaining.endswith("--bg"):
            background = True
            remaining = remaining.replace(" --bg", "").replace("--bg", "").strip()

        prompt = remaining.strip()
        if not prompt:
            raise ValueError(":fork requires a prompt")

        return ForkCommand(prompt=prompt, name=name, background=background)

    def _parse_with_args(self, args: str) -> tuple[str, str, bool]:
        """Parse :with/:with-copy arguments into (prompt, return_condition, background).

        Legacy support - new code should use :fork instead.
        """
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
