"""Tests for widget_registry module."""

import pytest
from dataclasses import dataclass, field
from typing import Any
from widgets.widget_registry import (
    WidgetRegistry,
    WidgetWithTurnId,
    ToolUseWidgetProtocol,
    ToolResultWidgetProtocol,
    MessageWidgetProtocol,
    WithWidgetProtocol,
    ForkMarkerProtocol,
    MergeMarkerProtocol,
    LinkMarkerProtocol,
    ArchiveMarkerProtocol,
)


# -------------------------------------------------------------------------
# Mock widgets for testing
# -------------------------------------------------------------------------

@dataclass
class MockArchiveBlock:
    """Mock archive block with archive_id."""
    archive_id: str


@dataclass
class MockWidget:
    """Base mock widget with turn_id and CSS class tracking."""
    turn_id: int
    classes: set[str] = field(default_factory=set)

    def add_class(self, class_name: str) -> None:
        self.classes.add(class_name)

    def remove_class(self, class_name: str) -> None:
        self.classes.discard(class_name)


@dataclass
class MockToolUseWidget(MockWidget):
    """Mock ToolUseWidget."""
    tool_use_id: str = ""


@dataclass
class MockToolResultWidget(MockWidget):
    """Mock ToolResultWidget."""
    tool_use_id: str = ""


@dataclass
class MockMessageWidget(MockWidget):
    """Mock MessageWidget."""
    block_idx: int = 0


@dataclass
class MockWithWidget(MockWidget):
    """Mock WithWidget."""
    child_session_id: str = ""


@dataclass
class MockForkMarker(MockWidget):
    """Mock ForkMarker."""
    child_session_id: str = ""
    prompt: str = ""  # Distinguishes from MergeMarker


@dataclass
class MockMergeMarker(MockWidget):
    """Mock MergeMarker."""
    child_session_id: str = ""
    message: str = ""  # Distinguishes from ForkMarker


@dataclass
class MockLinkMarker(MockWidget):
    """Mock LinkMarker."""
    linked_session_id: str = ""


@dataclass
class MockArchiveMarker(MockWidget):
    """Mock ArchiveMarker."""
    archive_block: MockArchiveBlock = field(default_factory=lambda: MockArchiveBlock(""))


# -------------------------------------------------------------------------
# Test fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def empty_registry():
    """Registry with no children."""
    return WidgetRegistry(get_children=lambda: iter([]))


@pytest.fixture
def sample_widgets():
    """Sample widgets for testing."""
    return [
        MockToolUseWidget(turn_id=1, tool_use_id="tool_1"),
        MockToolResultWidget(turn_id=1, tool_use_id="tool_1"),
        MockMessageWidget(turn_id=2, block_idx=0),
        MockMessageWidget(turn_id=2, block_idx=1),
        MockToolUseWidget(turn_id=3, tool_use_id="tool_2"),
        MockToolResultWidget(turn_id=3, tool_use_id="tool_2"),
        MockForkMarker(turn_id=4, child_session_id="fork_session_1"),
        MockMergeMarker(turn_id=5, child_session_id="fork_session_1"),
        MockWithWidget(turn_id=6, child_session_id="with_session_1"),
        MockLinkMarker(turn_id=7, linked_session_id="linked_session_1"),
        MockArchiveMarker(turn_id=8, archive_block=MockArchiveBlock("archive_1")),
    ]


@pytest.fixture
def registry_with_widgets(sample_widgets):
    """Registry with sample widgets."""
    return WidgetRegistry(get_children=lambda: iter(sample_widgets))


# -------------------------------------------------------------------------
# Test find methods
# -------------------------------------------------------------------------

class TestFindMethods:
    """Test the find_* methods."""

    def test_find_fork_marker_exists(self, sample_widgets):
        """find_fork_marker returns marker when it exists."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.find_fork_marker("fork_session_1")

        assert result is not None
        assert result.child_session_id == "fork_session_1"
        assert result.turn_id == 4

    def test_find_fork_marker_not_found(self, sample_widgets):
        """find_fork_marker returns None when not found."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.find_fork_marker("nonexistent")

        assert result is None

    def test_find_merge_marker_exists(self, sample_widgets):
        """find_merge_marker returns marker when it exists."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.find_merge_marker("fork_session_1")

        assert result is not None
        assert result.child_session_id == "fork_session_1"
        assert result.turn_id == 5

    def test_find_merge_marker_not_found(self, sample_widgets):
        """find_merge_marker returns None when not found."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.find_merge_marker("nonexistent")

        assert result is None

    def test_find_with_widget_exists(self, sample_widgets):
        """find_with_widget returns widget when it exists."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.find_with_widget("with_session_1")

        assert result is not None
        assert result.child_session_id == "with_session_1"

    def test_find_with_widget_not_found(self, sample_widgets):
        """find_with_widget returns None when not found."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.find_with_widget("nonexistent")

        assert result is None

    def test_find_link_marker_exists(self, sample_widgets):
        """find_link_marker returns marker when it exists."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.find_link_marker("linked_session_1")

        assert result is not None
        assert result.linked_session_id == "linked_session_1"

    def test_find_link_marker_not_found(self, sample_widgets):
        """find_link_marker returns None when not found."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.find_link_marker("nonexistent")

        assert result is None

    def test_find_archive_marker_exists(self, sample_widgets):
        """find_archive_marker returns marker when it exists."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.find_archive_marker("archive_1")

        assert result is not None
        assert result.archive_block.archive_id == "archive_1"

    def test_find_archive_marker_not_found(self, sample_widgets):
        """find_archive_marker returns None when not found."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.find_archive_marker("nonexistent")

        assert result is None

    def test_find_on_empty_registry(self, empty_registry):
        """All find methods return None for empty registry."""
        assert empty_registry.find_fork_marker("any") is None
        assert empty_registry.find_merge_marker("any") is None
        assert empty_registry.find_with_widget("any") is None
        assert empty_registry.find_link_marker("any") is None
        assert empty_registry.find_archive_marker("any") is None


# -------------------------------------------------------------------------
# Test highlight methods
# -------------------------------------------------------------------------

class TestHighlightTool:
    """Test the highlight_tool method."""

    def test_highlight_tool_highlights_both_use_and_result(self, sample_widgets):
        """highlight_tool adds highlighted class to both widgets."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.highlight_tool("tool_1")

        # Should return the tool use widget (first one found)
        assert result is not None
        assert result.tool_use_id == "tool_1"

        # Both should be highlighted
        tool_use = sample_widgets[0]  # MockToolUseWidget with tool_1
        tool_result = sample_widgets[1]  # MockToolResultWidget with tool_1
        assert "highlighted" in tool_use.classes
        assert "highlighted" in tool_result.classes

    def test_highlight_tool_not_found(self, sample_widgets):
        """highlight_tool returns None when tool not found."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.highlight_tool("nonexistent")

        assert result is None

    def test_highlight_tool_clears_previous_highlights(self, sample_widgets):
        """highlight_tool clears previous highlights first."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        # First highlight tool_1
        registry.highlight_tool("tool_1")
        # Then highlight tool_2
        registry.highlight_tool("tool_2")

        # tool_1 widgets should no longer be highlighted
        tool_use_1 = sample_widgets[0]
        tool_result_1 = sample_widgets[1]
        assert "highlighted" not in tool_use_1.classes
        assert "highlighted" not in tool_result_1.classes

        # tool_2 widgets should be highlighted
        tool_use_2 = sample_widgets[4]
        tool_result_2 = sample_widgets[5]
        assert "highlighted" in tool_use_2.classes
        assert "highlighted" in tool_result_2.classes


class TestHighlightTextBlock:
    """Test the highlight_text_block method."""

    def test_highlight_text_block_found(self, sample_widgets):
        """highlight_text_block highlights matching widget."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.highlight_text_block(turn_id=2, block_idx=1)

        assert result is not None
        assert result.turn_id == 2
        assert result.block_idx == 1
        assert "highlighted" in result.classes

    def test_highlight_text_block_not_found(self, sample_widgets):
        """highlight_text_block returns None when not found."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.highlight_text_block(turn_id=99, block_idx=0)

        assert result is None

    def test_highlight_text_block_clears_previous(self, sample_widgets):
        """highlight_text_block clears previous highlights."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        # First highlight block 0
        result1 = registry.highlight_text_block(turn_id=2, block_idx=0)
        # Then highlight block 1
        result2 = registry.highlight_text_block(turn_id=2, block_idx=1)

        assert "highlighted" not in result1.classes
        assert "highlighted" in result2.classes


class TestHighlightTurn:
    """Test the highlight_turn method."""

    def test_highlight_turn_found(self, sample_widgets):
        """highlight_turn highlights first widget with turn_id."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.highlight_turn(turn_id=1)

        # Should return first widget with turn_id=1 (ToolUseWidget)
        assert result is not None
        assert result.turn_id == 1
        assert "highlighted" in result.classes

    def test_highlight_turn_not_found(self, sample_widgets):
        """highlight_turn returns None when turn not found."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.highlight_turn(turn_id=99)

        assert result is None

    def test_highlight_turn_only_highlights_first(self, sample_widgets):
        """highlight_turn only highlights the first widget in turn."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        result = registry.highlight_turn(turn_id=1)

        # First widget (ToolUseWidget) should be highlighted
        assert "highlighted" in sample_widgets[0].classes
        # Second widget (ToolResultWidget) should NOT be highlighted
        assert "highlighted" not in sample_widgets[1].classes


class TestClearHighlights:
    """Test the clear_highlights method."""

    def test_clear_highlights_removes_all(self, sample_widgets):
        """clear_highlights removes highlighted class from all widgets."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        # Add some highlights
        registry.highlight_tool("tool_1")
        registry.highlight_text_block(turn_id=2, block_idx=0)

        # Clear them
        registry.clear_highlights()

        # Check no widgets have highlighted class
        for widget in sample_widgets:
            assert "highlighted" not in widget.classes

    def test_clear_highlights_on_empty(self, empty_registry):
        """clear_highlights works on empty registry."""
        # Should not raise
        empty_registry.clear_highlights()


# -------------------------------------------------------------------------
# Test filter and context mode methods
# -------------------------------------------------------------------------

class TestFilterByTurns:
    """Test the filter_by_turns method."""

    def test_filter_shows_specified_turns(self, sample_widgets):
        """filter_by_turns shows only specified turns."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        registry.filter_by_turns([1, 2])

        # Turn 1 and 2 widgets should not have hidden class
        assert "hidden" not in sample_widgets[0].classes  # turn 1
        assert "hidden" not in sample_widgets[1].classes  # turn 1
        assert "hidden" not in sample_widgets[2].classes  # turn 2
        assert "hidden" not in sample_widgets[3].classes  # turn 2

        # Other turns should have hidden class
        assert "hidden" in sample_widgets[4].classes  # turn 3
        assert "hidden" in sample_widgets[5].classes  # turn 3

    def test_filter_show_all(self, sample_widgets):
        """filter_by_turns with show_all=True shows all turns."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        # First hide some
        registry.filter_by_turns([1])
        # Then show all
        registry.filter_by_turns([], show_all=True)

        for widget in sample_widgets:
            assert "hidden" not in widget.classes


class TestSetTurnContextModes:
    """Test the set_turn_context_modes method."""

    def test_sets_copy_class(self, sample_widgets):
        """set_turn_context_modes adds context-copy for COPY mode."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        registry.set_turn_context_modes({1: "COPY"})

        assert "context-copy" in sample_widgets[0].classes
        assert "context-copy" in sample_widgets[1].classes

    def test_sets_compress_class(self, sample_widgets):
        """set_turn_context_modes adds context-compress for COMPRESS mode."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        registry.set_turn_context_modes({2: "COMPRESS"})

        assert "context-compress" in sample_widgets[2].classes
        assert "context-compress" in sample_widgets[3].classes

    def test_sets_drop_class(self, sample_widgets):
        """set_turn_context_modes adds context-drop for DROP mode."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        registry.set_turn_context_modes({3: "DROP"})

        assert "context-drop" in sample_widgets[4].classes
        assert "context-drop" in sample_widgets[5].classes

    def test_accepts_summarize_as_compress(self, sample_widgets):
        """set_turn_context_modes treats SUMMARIZE same as COMPRESS."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        registry.set_turn_context_modes({2: "SUMMARIZE"})

        assert "context-compress" in sample_widgets[2].classes

    def test_removes_hidden_class(self, sample_widgets):
        """set_turn_context_modes removes hidden class."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        # First hide some widgets
        sample_widgets[0].add_class("hidden")
        sample_widgets[1].add_class("hidden")

        registry.set_turn_context_modes({1: "COPY"})

        assert "hidden" not in sample_widgets[0].classes
        assert "hidden" not in sample_widgets[1].classes

    def test_clears_previous_context_classes(self, sample_widgets):
        """set_turn_context_modes clears previous context classes."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        # First set to COPY
        registry.set_turn_context_modes({1: "COPY"})
        assert "context-copy" in sample_widgets[0].classes

        # Then change to DROP
        registry.set_turn_context_modes({1: "DROP"})
        assert "context-copy" not in sample_widgets[0].classes
        assert "context-drop" in sample_widgets[0].classes


class TestClearContextModes:
    """Test the clear_context_modes method."""

    def test_clears_all_context_classes(self, sample_widgets):
        """clear_context_modes removes all context classes."""
        registry = WidgetRegistry(get_children=lambda: iter(sample_widgets))

        # Set various context modes
        registry.set_turn_context_modes({
            1: "COPY",
            2: "COMPRESS",
            3: "DROP"
        })

        # Clear them all
        registry.clear_context_modes()

        for widget in sample_widgets:
            assert "context-copy" not in widget.classes
            assert "context-compress" not in widget.classes
            assert "context-drop" not in widget.classes


# -------------------------------------------------------------------------
# Test protocol compliance
# -------------------------------------------------------------------------

class TestProtocolCompliance:
    """Test that mock widgets satisfy the protocols."""

    def test_tool_use_widget_protocol(self):
        """MockToolUseWidget satisfies ToolUseWidgetProtocol."""
        widget = MockToolUseWidget(turn_id=1, tool_use_id="test")
        assert isinstance(widget, ToolUseWidgetProtocol)

    def test_tool_result_widget_protocol(self):
        """MockToolResultWidget satisfies ToolResultWidgetProtocol."""
        widget = MockToolResultWidget(turn_id=1, tool_use_id="test")
        assert isinstance(widget, ToolResultWidgetProtocol)

    def test_message_widget_protocol(self):
        """MockMessageWidget satisfies MessageWidgetProtocol."""
        widget = MockMessageWidget(turn_id=1, block_idx=0)
        assert isinstance(widget, MessageWidgetProtocol)

    def test_with_widget_protocol(self):
        """MockWithWidget satisfies WithWidgetProtocol."""
        widget = MockWithWidget(turn_id=1, child_session_id="test")
        assert isinstance(widget, WithWidgetProtocol)

    def test_fork_marker_protocol(self):
        """MockForkMarker satisfies ForkMarkerProtocol."""
        widget = MockForkMarker(turn_id=1, child_session_id="test")
        assert isinstance(widget, ForkMarkerProtocol)

    def test_merge_marker_protocol(self):
        """MockMergeMarker satisfies MergeMarkerProtocol."""
        widget = MockMergeMarker(turn_id=1, child_session_id="test")
        assert isinstance(widget, MergeMarkerProtocol)

    def test_link_marker_protocol(self):
        """MockLinkMarker satisfies LinkMarkerProtocol."""
        widget = MockLinkMarker(turn_id=1, linked_session_id="test")
        assert isinstance(widget, LinkMarkerProtocol)

    def test_archive_marker_protocol(self):
        """MockArchiveMarker satisfies ArchiveMarkerProtocol."""
        widget = MockArchiveMarker(
            turn_id=1,
            archive_block=MockArchiveBlock("test")
        )
        assert isinstance(widget, ArchiveMarkerProtocol)


# -------------------------------------------------------------------------
# Test with debug logging
# -------------------------------------------------------------------------

class MockDebugLog:
    """Mock debug log for testing."""

    def __init__(self):
        self.messages: list[tuple[str, str, str]] = []  # (level, message, category)

    def info(self, message: str, category: str = "") -> None:
        self.messages.append(("info", message, category))

    def debug(self, message: str, category: str = "") -> None:
        self.messages.append(("debug", message, category))

    def warning(self, message: str, category: str = "") -> None:
        self.messages.append(("warning", message, category))


class TestDebugLogging:
    """Test debug logging functionality."""

    def test_logs_highlight_tool_found(self, sample_widgets):
        """Logs info when tool is found."""
        debug_log = MockDebugLog()
        registry = WidgetRegistry(
            get_children=lambda: iter(sample_widgets),
            debug_log=debug_log
        )

        registry.highlight_tool("tool_1")

        info_messages = [m for level, m, _ in debug_log.messages if level == "info"]
        assert any("found use=True" in m for m in info_messages)

    def test_logs_highlight_tool_not_found(self, sample_widgets):
        """Logs warning when tool not found."""
        debug_log = MockDebugLog()
        registry = WidgetRegistry(
            get_children=lambda: iter(sample_widgets),
            debug_log=debug_log
        )

        registry.highlight_tool("nonexistent")

        warning_messages = [m for level, m, _ in debug_log.messages if level == "warning"]
        assert any("NOT FOUND" in m for m in warning_messages)

    def test_logs_to_widget_registry_category(self, sample_widgets):
        """All logs use widget_registry category."""
        debug_log = MockDebugLog()
        registry = WidgetRegistry(
            get_children=lambda: iter(sample_widgets),
            debug_log=debug_log
        )

        registry.highlight_tool("tool_1")

        categories = [cat for _, _, cat in debug_log.messages]
        assert all(cat == "widget_registry" for cat in categories)
