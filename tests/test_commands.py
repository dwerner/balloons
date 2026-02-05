"""Tests for command parsing."""

import pytest
from core.commands import (
    CommandParser,
    NewSessionCommand,
    CopyTurnsCommand,
    QueryWithCommand,
    SuspendCommand,
    ShellCommand,
    ReturnCommand,
    PwdCommand,
    CdCommand,
    ReloadCommand,
    TitleCommand,
    ArchiveCommand,
    RehydrateCommand,
    FollowCommand,
)


@pytest.fixture
def parser():
    return CommandParser()


class TestCommandParser:
    """Tests for CommandParser.parse()"""

    def test_regular_prompt_returns_none(self, parser):
        """Regular prompts (not starting with :) return None."""
        assert parser.parse("hello world") is None
        assert parser.parse("") is None
        assert parser.parse("  some text  ") is None

    def test_new_session_no_prompt(self, parser):
        """':new' creates NewSessionCommand with empty prompt."""
        cmd = parser.parse(":new")
        assert isinstance(cmd, NewSessionCommand)
        assert cmd.prompt == ""

    def test_new_session_with_prompt(self, parser):
        """':new <prompt>' includes the initial prompt."""
        cmd = parser.parse(":new start with this")
        assert isinstance(cmd, NewSessionCommand)
        assert cmd.prompt == "start with this"

    def test_copy_turns(self, parser):
        """':copy-turns' creates CopyTurnsCommand."""
        cmd = parser.parse(":copy-turns")
        assert isinstance(cmd, CopyTurnsCommand)

    def test_query_with(self, parser):
        """':query-with <prompt>' creates QueryWithCommand."""
        cmd = parser.parse(":query-with what is this?")
        assert isinstance(cmd, QueryWithCommand)
        assert cmd.prompt == "what is this?"

    def test_query_with_no_prompt_raises(self, parser):
        """':query-with' without prompt raises ValueError."""
        with pytest.raises(ValueError, match="requires a prompt"):
            parser.parse(":query-with ")

    def test_suspend(self, parser):
        """':suspend <cmd>' creates SuspendCommand."""
        cmd = parser.parse(":suspend vim file.txt")
        assert isinstance(cmd, SuspendCommand)
        assert cmd.shell_cmd == "vim file.txt"

    def test_suspend_no_cmd_raises(self, parser):
        """':suspend' without command raises ValueError."""
        with pytest.raises(ValueError, match="requires a command"):
            parser.parse(":suspend ")

    def test_shell_command(self, parser):
        """':!<cmd>' creates ShellCommand."""
        cmd = parser.parse(":!ls -la")
        assert isinstance(cmd, ShellCommand)
        assert cmd.shell_cmd == "ls -la"

    def test_shell_command_no_cmd_raises(self, parser):
        """':!' without command raises ValueError."""
        with pytest.raises(ValueError, match="requires a command"):
            parser.parse(":!")

    def test_return_no_prompt(self, parser):
        """':return' creates ReturnCommand with empty prompt."""
        cmd = parser.parse(":return")
        assert isinstance(cmd, ReturnCommand)
        assert cmd.return_prompt == ""

    def test_return_with_prompt(self, parser):
        """':return <message>' includes the return message."""
        cmd = parser.parse(":return task completed successfully")
        assert isinstance(cmd, ReturnCommand)
        assert cmd.return_prompt == "task completed successfully"

    def test_pwd(self, parser):
        """':pwd' creates PwdCommand."""
        cmd = parser.parse(":pwd")
        assert isinstance(cmd, PwdCommand)

    def test_cd_no_path(self, parser):
        """':cd' creates CdCommand with empty path."""
        cmd = parser.parse(":cd")
        assert isinstance(cmd, CdCommand)
        assert cmd.path == ""

    def test_cd_with_path(self, parser):
        """':cd <path>' includes the path."""
        cmd = parser.parse(":cd /home/user")
        assert isinstance(cmd, CdCommand)
        assert cmd.path == "/home/user"

    def test_reload(self, parser):
        """':reload' creates ReloadCommand."""
        cmd = parser.parse(":reload")
        assert isinstance(cmd, ReloadCommand)

    def test_title(self, parser):
        """':title <title>' sets the session title."""
        cmd = parser.parse(":title My Session Title")
        assert isinstance(cmd, TitleCommand)
        assert cmd.title == "My Session Title"

    def test_title_no_title_raises(self, parser):
        """':title' without a title raises ValueError."""
        with pytest.raises(ValueError, match=":title requires a title"):
            parser.parse(":title")

    def test_unknown_command_raises(self, parser):
        """Unknown commands raise ValueError."""
        with pytest.raises(ValueError, match="Unknown command: :foo"):
            parser.parse(":foo")

    def test_whitespace_handling(self, parser):
        """Commands with extra whitespace are handled correctly."""
        cmd = parser.parse("  :new  hello  ")
        assert isinstance(cmd, NewSessionCommand)
        assert cmd.prompt == "hello"


class TestArchiveCommands:
    """Tests for :archive and :rehydrate commands."""

    @pytest.fixture
    def parser(self):
        return CommandParser()

    def test_archive_no_hint(self, parser):
        """':archive' creates ArchiveCommand with empty prompt."""
        cmd = parser.parse(":archive")
        assert isinstance(cmd, ArchiveCommand)
        assert cmd.prompt == ""

    def test_archive_with_hint(self, parser):
        """':archive <hint>' includes the hint."""
        cmd = parser.parse(":archive focus on the API changes")
        assert isinstance(cmd, ArchiveCommand)
        assert cmd.prompt == "focus on the API changes"

    def test_rehydrate(self, parser):
        """':rehydrate' creates RehydrateCommand."""
        cmd = parser.parse(":rehydrate")
        assert isinstance(cmd, RehydrateCommand)
        assert cmd.archive_turn_index == -1


class TestFollowCommand:
    """Tests for :follow command."""

    @pytest.fixture
    def parser(self):
        return CommandParser()

    def test_follow(self, parser):
        """':follow' creates FollowCommand."""
        cmd = parser.parse(":follow")
        assert isinstance(cmd, FollowCommand)
