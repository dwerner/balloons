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
    SnapCommand,
    NewSlideCommand,
    PresentCommand,
    SlidesCommand,
    ChatCommand,
    ReviewCommand,
    GoalInterviewCommand,
    HistoryCommand,
    StatusCommand,
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


class TestSnapCommand:
    """Tests for :snap command."""

    @pytest.fixture
    def parser(self):
        return CommandParser()

    def test_snap_no_prompt(self, parser):
        """':snap' creates SnapCommand with empty prompt."""
        cmd = parser.parse(":snap")
        assert isinstance(cmd, SnapCommand)
        assert cmd.prompt == ""

    def test_snap_with_prompt(self, parser):
        """':snap <prompt>' includes the prompt."""
        cmd = parser.parse(":snap what does this show?")
        assert isinstance(cmd, SnapCommand)
        assert cmd.prompt == "what does this show?"


class TestSlideCommands:
    def test_new_slide_no_title(self, parser):
        cmd = parser.parse(":new-slide")
        assert isinstance(cmd, NewSlideCommand)
        assert cmd.title == ""

    def test_new_slide_with_title(self, parser):
        cmd = parser.parse(":new-slide Introduction")
        assert isinstance(cmd, NewSlideCommand)
        assert cmd.title == "Introduction"

    def test_present(self, parser):
        cmd = parser.parse(":present")
        assert isinstance(cmd, PresentCommand)

    def test_slides(self, parser):
        cmd = parser.parse(":slides")
        assert isinstance(cmd, SlidesCommand)

    def test_chat(self, parser):
        cmd = parser.parse(":chat")
        assert isinstance(cmd, ChatCommand)


class TestReviewCommand:
    def test_review(self, parser):
        """':review' starts a session quality review."""
        cmd = parser.parse(":review")
        assert isinstance(cmd, ReviewCommand)


class TestGoalInterviewCommand:
    def test_goal_interview_no_args(self, parser):
        """':goal-interview' with no arguments should error."""
        with pytest.raises(ValueError, match="Missing title"):
            parser.parse(":goal-interview")

    def test_goal_interview_with_name_only(self, parser):
        """':goal-interview=name' with just a name should error."""
        with pytest.raises(ValueError, match="Missing prompt"):
            parser.parse(":goal-interview=web-frontend")

    def test_goal_interview_with_prompt_only(self, parser):
        """':goal-interview prompt' with just a prompt should error."""
        with pytest.raises(ValueError, match="Missing title"):
            parser.parse(":goal-interview I want to build a web UI")

    def test_goal_interview_with_name_and_prompt(self, parser):
        """':goal-interview=name prompt' with both name and prompt."""
        cmd = parser.parse(":goal-interview=web-frontend I want to build a web UI for balloons")
        assert isinstance(cmd, GoalInterviewCommand)
        assert cmd.name == "web-frontend"
        assert cmd.prompt == "I want to build a web UI for balloons"
        assert cmd.is_global is True

    def test_goal_interview_empty_title(self, parser):
        """':goal-interview= prompt' with empty title should error."""
        with pytest.raises(ValueError, match="Missing title"):
            parser.parse(":goal-interview= I want to build a web UI")


class TestHistoryCommand:
    """Tests for :history command parsing."""

    def test_history_no_args(self, parser):
        """':history' returns HistoryCommand with index=0 (show list)."""
        cmd = parser.parse(":history")
        assert isinstance(cmd, HistoryCommand)
        assert cmd.index == 0
        assert cmd.is_global is True

    def test_history_with_index(self, parser):
        """':history N' returns HistoryCommand with that index."""
        cmd = parser.parse(":history 3")
        assert isinstance(cmd, HistoryCommand)
        assert cmd.index == 3

    def test_history_with_invalid_index(self, parser):
        """':history abc' should error."""
        with pytest.raises(ValueError, match="index must be a number"):
            parser.parse(":history abc")


class TestStatusCommand:
    """Tests for :status command parsing."""

    def test_status_no_args(self, parser):
        """':status' returns StatusCommand with scope='all'."""
        cmd = parser.parse(":status")
        assert isinstance(cmd, StatusCommand)
        assert cmd.scope == "all"
        assert cmd.is_global is True

    def test_status_with_all(self, parser):
        """':status all' returns StatusCommand with scope='all'."""
        cmd = parser.parse(":status all")
        assert isinstance(cmd, StatusCommand)
        assert cmd.scope == "all"

    def test_status_with_goal_id(self, parser):
        """':status abc123' returns StatusCommand with that scope."""
        cmd = parser.parse(":status abc123")
        assert isinstance(cmd, StatusCommand)
        assert cmd.scope == "abc123"

    def test_status_with_plan_id(self, parser):
        """':status plan456' returns StatusCommand with that scope."""
        cmd = parser.parse(":status plan456")
        assert isinstance(cmd, StatusCommand)
        assert cmd.scope == "plan456"

    def test_status_with_trailing_space(self, parser):
        """':status ' (trailing space) returns scope='all'."""
        cmd = parser.parse(":status ")
        assert isinstance(cmd, StatusCommand)
        assert cmd.scope == "all"

    def test_status_strips_extra_spaces(self, parser):
        """':status   spaced  ' strips extra whitespace from scope."""
        cmd = parser.parse(":status   spaced  ")
        assert isinstance(cmd, StatusCommand)
        assert cmd.scope == "spaced"
