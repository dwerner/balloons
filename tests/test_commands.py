"""Tests for command parsing."""

import pytest
from core.commands import (
    CommandParser,
    NewSessionCommand,
    ForkCommand,
    MergeCommand,
    DeriveCommand,
    SwitchCommand,
    HistoryCommand,
    QueryWithCommand,
    SuspendCommand,
    ShellCommand,
    ReturnCommand,
    PwdCommand,
    CdCommand,
    ReloadCommand,
    TitleCommand,
    HelpCommand,
    DebugToggleCommand,
    DebugPauseCommand,
    DebugClearCommand,
    DebugFpsCommand,
    BackendCommand,
    PrefsCommand,
    EditConfigCommand,
    EditPromptCommand,
    LinkCommand,
    ArchiveCommand,
    RehydrateCommand,
    ReindexCommand,
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
)


@pytest.fixture
def parser():
    return CommandParser()


class TestCommandParser:
    def test_regular_text_returns_none(self, parser):
        assert parser.parse("hello") is None

    def test_new_command(self, parser):
        cmd = parser.parse(":new hello")
        assert isinstance(cmd, NewSessionCommand)
        assert cmd.prompt == "hello"

    def test_fork_command(self, parser):
        cmd = parser.parse(":fork do work")
        assert isinstance(cmd, ForkCommand)
        assert cmd.prompt == "do work"

    def test_merge_command(self, parser):
        cmd = parser.parse(":merge summary")
        assert isinstance(cmd, MergeCommand)
        assert cmd.prompt == "summary"

    def test_derive_command(self, parser):
        cmd = parser.parse(":derive explore")
        assert isinstance(cmd, DeriveCommand)
        assert cmd.prompt == "explore"

    def test_switch_command(self, parser):
        cmd = parser.parse(":switch child")
        assert isinstance(cmd, SwitchCommand)
        assert cmd.name == "child"

    def test_history_command(self, parser):
        cmd = parser.parse(":history 2")
        assert isinstance(cmd, HistoryCommand)
        assert cmd.index == 2

    def test_query_with_command(self, parser):
        cmd = parser.parse(":query-with summarize")
        assert isinstance(cmd, QueryWithCommand)

    def test_suspend_command(self, parser):
        cmd = parser.parse(":suspend vim")
        assert isinstance(cmd, SuspendCommand)

    def test_shell_command(self, parser):
        cmd = parser.parse(":!ls")
        assert isinstance(cmd, ShellCommand)

    def test_return_command(self, parser):
        cmd = parser.parse(":return done")
        assert isinstance(cmd, ReturnCommand)

    def test_misc_commands(self, parser):
        assert isinstance(parser.parse(":pwd"), PwdCommand)
        assert isinstance(parser.parse(":cd /tmp"), CdCommand)
        assert isinstance(parser.parse(":reload"), ReloadCommand)
        assert isinstance(parser.parse(":title hi"), TitleCommand)
        assert isinstance(parser.parse(":help"), HelpCommand)
        assert isinstance(parser.parse(":debug"), DebugToggleCommand)
        assert isinstance(parser.parse(":debug-pause"), DebugPauseCommand)
        assert isinstance(parser.parse(":debug-clear"), DebugClearCommand)
        assert isinstance(parser.parse(":debug-fps"), DebugFpsCommand)
        assert isinstance(parser.parse(":backend test"), BackendCommand)
        assert isinstance(parser.parse(":prefs"), PrefsCommand)
        assert isinstance(parser.parse(":edit-config"), EditConfigCommand)
        assert isinstance(parser.parse(":edit-prompt x"), EditPromptCommand)
        assert isinstance(parser.parse(":archive hint"), ArchiveCommand)
        assert isinstance(parser.parse(":rehydrate"), RehydrateCommand)
        assert isinstance(parser.parse(":reindex"), ReindexCommand)
        assert isinstance(parser.parse(":follow"), FollowCommand)
        assert isinstance(parser.parse(":stash note"), StashCommand)
        assert isinstance(parser.parse(":pop"), PopCommand)
        assert isinstance(parser.parse(":clear-all-sessions"), ClearAllSessionsCommand)
        assert isinstance(parser.parse(":snap now"), SnapCommand)
        assert isinstance(parser.parse(":new-slide Title"), NewSlideCommand)
        assert isinstance(parser.parse(":present"), PresentCommand)
        assert isinstance(parser.parse(":slides"), SlidesCommand)
        assert isinstance(parser.parse(":chat"), ChatCommand)
        assert isinstance(parser.parse(":review"), ReviewCommand)

    def test_link_command(self, parser):
        cmd = parser.parse(":link=abc123,def456")
        assert isinstance(cmd, LinkCommand)
        assert cmd.target_session_prefixes == ["abc123", "def456"]

    def test_supervisor_commands(self, parser):
        assert isinstance(parser.parse(":sup-start run"), SupervisorStartCommand)
        assert isinstance(parser.parse(":sup-list --all"), SupervisorListCommand)
        assert isinstance(parser.parse(":sup-logs pid 10"), SupervisorLogsCommand)
        assert isinstance(parser.parse(":sup-stop pid"), SupervisorStopCommand)

    def test_unknown_command_raises(self, parser):
        with pytest.raises(ValueError):
            parser.parse(":goals")
