"""Tests for the streaming coordinator."""

import pytest

from core.streaming import (
    StreamingContext,
    StreamingCoordinator,
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
)
from core.runner import StreamEvent


class TestStreamingContext:
    """Tests for StreamingContext dataclass."""

    def test_creation(self):
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )
        assert ctx.session_id == "test-123"
        assert ctx.content == ""
        assert ctx.tool_events == {}
        assert ctx.is_active
        assert not ctx.query_with

    def test_tool_events_default_initialization(self):
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )
        assert ctx.tool_events == {}
        # Should be a real dict, not None
        ctx.tool_events["test"] = "value"
        assert ctx.tool_events["test"] == "value"


class TestStreamingCoordinator:
    """Tests for StreamingCoordinator."""

    def test_text_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(event_type="text", data="Hello, world!")
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, TextAction)
        assert action.session_id == "test-123"
        assert action.text == "Hello, world!"
        assert ctx.content == "Hello, world!"

    def test_text_accumulation(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        coordinator.dispatch_event(StreamEvent(event_type="text", data="Hello"), ctx)
        coordinator.dispatch_event(StreamEvent(event_type="text", data=", world!"), ctx)

        assert ctx.content == "Hello, world!"

    def test_text_flush_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(event_type="text_flush", data={"text": "Completed text segment", "turn_index": 2})
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, TextFlushAction)
        assert action.session_id == "test-123"
        assert action.text == "Completed text segment"
        assert action.turn_idx == 2

    def test_init_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(
            event_type="init",
            data={"model": "claude-3-opus", "context_window": 200000},
        )
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, InitAction)
        assert action.session_id == "test-123"
        assert action.model == "claude-3-opus"
        assert action.context_window == 200000

    def test_result_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(
            event_type="result",
            data={"input_tokens": 100, "output_tokens": 50, "total_cost": 0.005},
        )
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, ResultAction)
        assert action.input_tokens == 100
        assert action.output_tokens == 50
        assert action.total_cost == 0.005

    def test_tool_use_start_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(
            event_type="tool_use_start",
            data={
                "tool_use_id": "tool-1",
                "tool_name": "read_file",
                "tool_index": 0,
            },
        )
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, ToolUseStartAction)
        assert action.session_id == "test-123"
        assert action.tool_use_id == "tool-1"
        assert action.tool_name == "read_file"
        assert action.tool_index == 0
        # Should be tracked in context
        assert "tool-1" in ctx.tool_events
        assert ctx.tool_events["tool-1"]["name"] == "read_file"

    def test_tool_input_delta_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )
        # First start the tool
        ctx.tool_events["tool-1"] = {"name": "read_file", "input": {}, "index": 0, "result": None}

        event = StreamEvent(
            event_type="tool_input_delta",
            data={"tool_use_id": "tool-1", "partial_json": '{"path": "/te'},
        )
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, ToolInputDeltaAction)
        assert action.tool_use_id == "tool-1"
        assert action.partial_json == '{"path": "/te'
        assert action.tool_name == "read_file"

    def test_tool_use_complete_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )
        # First start the tool
        ctx.tool_events["tool-1"] = {"name": "read_file", "input": {}, "index": 0, "result": None}

        event = StreamEvent(
            event_type="tool_use",
            data={
                "tool_use_id": "tool-1",
                "tool_name": "read_file",
                "tool_input": {"path": "/test.py"},
                "tool_index": 0,
            },
        )
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, ToolUseCompleteAction)
        assert action.tool_use_id == "tool-1"
        assert action.tool_name == "read_file"
        assert action.tool_input == {"path": "/test.py"}
        # Input should be tracked
        assert ctx.tool_events["tool-1"]["input"] == {"path": "/test.py"}

    def test_tool_result_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )
        ctx.tool_events["tool-1"] = {"name": "read_file", "input": {"path": "/test.py"}, "index": 0, "result": None}

        event = StreamEvent(
            event_type="tool_result",
            data={
                "tool_use_id": "tool-1",
                "result": "file contents here",
                "tool_index": 0,
            },
        )
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, ToolResultAction)
        assert action.tool_use_id == "tool-1"
        assert action.result == "file contents here"
        # Result should be tracked
        assert ctx.tool_events["tool-1"]["result"] == "file contents here"

    def test_error_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(event_type="error", data="API rate limit exceeded")
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, ErrorAction)
        assert action.session_id == "test-123"
        assert action.error == "API rate limit exceeded"

    def test_rate_limit_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(event_type="rate_limit", data="Retry after 30 seconds")
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, RateLimitAction)
        assert action.message == "Retry after 30 seconds"

    def test_cancelled_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(event_type="cancelled", data=None)
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, CancelledAction)
        assert action.session_id == "test-123"

    def test_input_required_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(event_type="input_required", data="Please confirm")
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, InputRequiredAction)
        assert action.message == "Please confirm"

    def test_turn_started_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(event_type="turn_started", data={"session_id": "test-123", "turn_index": 0})
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, NoAction)

    def test_text_turn_started_event(self):
        """text_turn_started event should return TurnStartedAction."""
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(event_type="text_turn_started", data={
            "turn_index": 2,
            "exchange_id": "exchange-abc",
            "role": "assistant",
            "turn_type": "text",
            "text_preview": "Some text...",
        })
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, TurnStartedAction)
        assert action.turn_idx == 2
        assert action.role == "assistant"
        assert action.exchange_id == "exchange-abc"
        assert action.turn_type == "text"

    def test_text_turn_started_resets_content(self):
        """text_turn_started event should reset ctx.content for the new turn.

        This is critical for correct accumulated values in content_delta events.
        Without this reset, content from previous turns would be included in
        the accumulated value, causing duplicate content in the web UI.
        """
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        # Simulate text from previous turn
        ctx.content = "Previous turn content"

        event = StreamEvent(event_type="text_turn_started", data={
            "turn_index": 2,
            "exchange_id": "exchange-abc",
            "role": "assistant",
        })
        coordinator.dispatch_event(event, ctx)

        # Content should be reset for the new turn
        assert ctx.content == ""

    def test_tool_use_turn_started_event(self):
        """tool_use_turn_started event should return TurnStartedAction with tool info."""
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(event_type="tool_use_turn_started", data={
            "turn_index": 3,
            "exchange_id": "exchange-abc",
            "role": "assistant",
            "turn_type": "tool_use",
            "tool_use_id": "tool-123",
            "tool_name": "Read",
        })
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, TurnStartedAction)
        assert action.turn_idx == 3
        assert action.role == "assistant"
        assert action.turn_type == "tool_use"
        assert action.tool_use_id == "tool-123"
        assert action.tool_name == "Read"

    def test_tool_result_turn_started_event(self):
        """tool_result_turn_started event should return TurnStartedAction with result info."""
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(event_type="tool_result_turn_started", data={
            "turn_index": 4,
            "exchange_id": "exchange-abc",
            "role": "tool",
            "turn_type": "tool_result",
            "tool_use_id": "tool-123",
        })
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, TurnStartedAction)
        assert action.turn_idx == 4
        assert action.role == "tool"
        assert action.turn_type == "tool_result"
        assert action.tool_use_id == "tool-123"

    def test_unknown_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="test-123",
            user_turn_idx=0,
            assistant_turn_idx=1,
            prompt="Hello",
        )

        event = StreamEvent(event_type="unknown_type", data={})
        action = coordinator.dispatch_event(event, ctx)

        assert isinstance(action, NoAction)


class TestStreamingCoordinatorHelperEvents:
    """Tests for helper session event handling."""

    def test_helper_text_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="helper-123",
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_helper=True,
            helper_type="compress",
        )

        event = StreamEvent(event_type="text", data="Compressed context")
        action = coordinator.dispatch_helper_event(event, ctx)

        assert isinstance(action, TextAction)
        assert action.session_id == "helper-123"
        assert ctx.content == "Compressed context"

    def test_helper_error_event(self):
        coordinator = StreamingCoordinator()
        ctx = StreamingContext(
            session_id="helper-123",
            user_turn_idx=-1,
            assistant_turn_idx=-1,
            prompt="",
            is_helper=True,
            helper_type="compress",
        )

        event = StreamEvent(event_type="error", data="Helper failed")
        action = coordinator.dispatch_helper_event(event, ctx)

        # Helper errors return HelperDoneAction with error set
        assert isinstance(action, HelperDoneAction)
        assert action.error == "Helper failed"
        assert action.helper_type == "compress"
