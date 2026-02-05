"""Widget registry - provides lookup and highlight operations for chat widgets.

This module separates widget lookup and highlight logic from the ChatLogView,
enabling:
- Unit testing with mock widget lists
- Clear separation of concerns
- Reusable lookup patterns
"""

from typing import Iterator, Callable, Any, Protocol, TypeVar, runtime_checkable


# Type variable for generic widget types
W = TypeVar('W')


@runtime_checkable
class WidgetWithTurnId(Protocol):
    """Protocol for widgets that have a turn_id attribute."""
    turn_id: int

    def add_class(self, class_name: str) -> None: ...
    def remove_class(self, class_name: str) -> None: ...


@runtime_checkable
class ToolUseWidgetProtocol(Protocol):
    """Protocol for tool use widgets."""
    tool_use_id: str
    turn_id: int

    def add_class(self, class_name: str) -> None: ...
    def remove_class(self, class_name: str) -> None: ...


@runtime_checkable
class ToolResultWidgetProtocol(Protocol):
    """Protocol for tool result widgets."""
    tool_use_id: str
    turn_id: int

    def add_class(self, class_name: str) -> None: ...
    def remove_class(self, class_name: str) -> None: ...


@runtime_checkable
class MessageWidgetProtocol(Protocol):
    """Protocol for message widgets."""
    turn_id: int
    block_idx: int

    def add_class(self, class_name: str) -> None: ...
    def remove_class(self, class_name: str) -> None: ...


@runtime_checkable
class WithWidgetProtocol(Protocol):
    """Protocol for with widgets (nested sessions)."""
    child_session_id: str
    turn_id: int


@runtime_checkable
class ForkMarkerProtocol(Protocol):
    """Protocol for fork marker widgets.

    Distinguished from MergeMarkerProtocol by the 'prompt' attribute.
    """
    child_session_id: str
    turn_id: int
    prompt: str  # Distinguishes from MergeMarker


@runtime_checkable
class MergeMarkerProtocol(Protocol):
    """Protocol for merge marker widgets.

    Distinguished from ForkMarkerProtocol by the 'message' attribute.
    """
    child_session_id: str
    turn_id: int
    message: str  # Distinguishes from ForkMarker


@runtime_checkable
class LinkMarkerProtocol(Protocol):
    """Protocol for link marker widgets."""
    linked_session_id: str
    turn_id: int


@runtime_checkable
class ArchiveMarkerProtocol(Protocol):
    """Protocol for archive marker widgets."""
    turn_id: int

    @property
    def archive_block(self) -> Any:
        """Archive block with archive_id attribute."""
        ...


class WidgetRegistry:
    """Provides lookup and highlight operations for chat widgets.

    The registry operates on a children iterator/accessor, enabling it to work
    with any widget container without tight coupling to ChatLogView.

    Usage:
        registry = WidgetRegistry(
            get_children=lambda: chat_log.children,
            debug_log=debug_log,
        )

        # Find operations
        widget = registry.find_fork_marker(child_session_id)

        # Highlight operations (returns widget to scroll to, or None)
        to_scroll = registry.highlight_tool(tool_use_id)
        if to_scroll:
            scroll_controller.scroll_to_widget(to_scroll.region)
    """

    # CSS classes for context mode indicators
    CONTEXT_CLASSES = ("context-copy", "context-compress", "context-drop")

    def __init__(
        self,
        get_children: Callable[[], Iterator[Any]],
        debug_log: Any = None,
    ):
        """Initialize the widget registry.

        Args:
            get_children: Callable that returns an iterator of child widgets
            debug_log: Optional debug logger with .info(), .debug(), .warning() methods
        """
        self._get_children = get_children
        self._debug_log = debug_log

    # -------------------------------------------------------------------------
    # Find methods
    # -------------------------------------------------------------------------

    def find_with_widget(self, child_session_id: str) -> Any | None:
        """Find a WithWidget by its child session ID."""
        for child in self._get_children():
            if isinstance(child, WithWidgetProtocol) and child.child_session_id == child_session_id:
                return child
        return None

    def find_fork_marker(self, child_session_id: str) -> Any | None:
        """Find a ForkMarker by its child session ID."""
        for child in self._get_children():
            if isinstance(child, ForkMarkerProtocol) and child.child_session_id == child_session_id:
                return child
        return None

    def find_merge_marker(self, child_session_id: str) -> Any | None:
        """Find a MergeMarker by its child session ID."""
        for child in self._get_children():
            if isinstance(child, MergeMarkerProtocol) and child.child_session_id == child_session_id:
                return child
        return None

    def find_link_marker(self, linked_session_id: str) -> Any | None:
        """Find a LinkMarker by its linked session ID."""
        for child in self._get_children():
            if isinstance(child, LinkMarkerProtocol) and child.linked_session_id == linked_session_id:
                return child
        return None

    def find_archive_marker(self, archive_id: str) -> Any | None:
        """Find an ArchiveMarker by its archive ID."""
        for child in self._get_children():
            if isinstance(child, ArchiveMarkerProtocol):
                if hasattr(child.archive_block, 'archive_id') and child.archive_block.archive_id == archive_id:
                    return child
        return None

    # -------------------------------------------------------------------------
    # Highlight methods
    # -------------------------------------------------------------------------

    def highlight_tool(self, tool_use_id: str) -> Any | None:
        """Highlight a tool use and its result by tool_use_id.

        Returns the first highlighted widget (for scrolling), or None if not found.
        """
        self._log_info(f"highlight_tool: looking for tool_use_id={tool_use_id}")

        # First clear any existing highlights
        self.clear_highlights()

        # Find and highlight the matching widgets
        scroll_target = None
        found_use = False
        found_result = False

        for child in self._get_children():
            if isinstance(child, ToolUseWidgetProtocol):
                self._log_debug(f"  checking ToolUseWidget: tool_use_id={child.tool_use_id}")
                if child.tool_use_id == tool_use_id:
                    child.add_class("highlighted")
                    found_use = True
                    if scroll_target is None:
                        scroll_target = child
            elif isinstance(child, ToolResultWidgetProtocol):
                self._log_debug(f"  checking ToolResultWidget: tool_use_id={child.tool_use_id}")
                if child.tool_use_id == tool_use_id:
                    child.add_class("highlighted")
                    found_result = True

        if found_use or found_result:
            self._log_info(f"highlight_tool: found use={found_use} result={found_result}")
        else:
            self._log_warning(f"highlight_tool: tool_use_id={tool_use_id} NOT FOUND")

        return scroll_target

    def highlight_text_block(self, turn_id: int, block_idx: int) -> Any | None:
        """Highlight a text block by turn_id and block_idx.

        Returns the highlighted widget (for scrolling), or None if not found.
        """
        self._log_info(f"highlight_text_block: looking for turn_id={turn_id}, block_idx={block_idx}")

        # First clear any existing highlights
        self.clear_highlights()

        # Find and highlight the matching widget
        for child in self._get_children():
            if isinstance(child, MessageWidgetProtocol):
                self._log_debug(f"  checking MessageWidget: turn_id={child.turn_id}, block_idx={child.block_idx}")
                if child.turn_id == turn_id and child.block_idx == block_idx:
                    child.add_class("highlighted")
                    self._log_info("  -> FOUND and highlighted!")
                    return child

        self._log_warning("  -> NOT FOUND!")
        return None

    def highlight_turn(self, turn_id: int) -> Any | None:
        """Highlight the first widget in a turn by turn_id.

        Returns the highlighted widget (for scrolling), or None if not found.
        """
        self._log_info(f"highlight_turn: looking for turn_id={turn_id}")

        self.clear_highlights()

        # Find and highlight the first widget with matching turn_id
        for child in self._get_children():
            if isinstance(child, WidgetWithTurnId) and child.turn_id == turn_id:
                child.add_class("highlighted")
                self._log_info(f"highlight_turn: found and highlighted turn_id={turn_id}")
                return child

        self._log_warning(f"highlight_turn: turn_id={turn_id} NOT FOUND")
        return None

    def clear_highlights(self) -> None:
        """Remove all highlights from tools and messages."""
        for child in self._get_children():
            # Check for highlightable types
            if isinstance(child, (ToolUseWidgetProtocol, ToolResultWidgetProtocol, MessageWidgetProtocol)):
                child.remove_class("highlighted")

    # -------------------------------------------------------------------------
    # Filter and context mode methods
    # -------------------------------------------------------------------------

    def filter_by_turns(self, turn_ids: list[int], show_all: bool = False) -> None:
        """Show only specified turns, or all if show_all is True.

        DEPRECATED: Use set_turn_context_modes instead for visual indication without hiding.
        """
        for child in self._get_children():
            if isinstance(child, WidgetWithTurnId):
                if show_all or child.turn_id in turn_ids:
                    child.remove_class("hidden")
                else:
                    child.add_class("hidden")

    def set_turn_context_modes(self, turn_modes: dict[int, str]) -> None:
        """Apply visual context mode indicators to turns.

        Instead of hiding turns, this shows all turns but with visual indication
        of their context state:
        - COPY: green border (included in full)
        - COMPRESS: yellow border, slightly faded (will be summarized)
        - DROP: very faded (not included in context)

        Args:
            turn_modes: Dict mapping turn_id (1-indexed) to mode name ("COPY", "COMPRESS", "DROP")
        """
        for child in self._get_children():
            if isinstance(child, WidgetWithTurnId):
                # Remove any existing context classes
                for cls in self.CONTEXT_CLASSES:
                    child.remove_class(cls)
                # Remove hidden class - we show everything now
                child.remove_class("hidden")

                # Get mode for this turn (default to no visual if not specified)
                mode = turn_modes.get(child.turn_id, None)
                if mode == "COPY":
                    child.add_class("context-copy")
                elif mode in ("COMPRESS", "SUMMARIZE"):
                    child.add_class("context-compress")
                elif mode == "DROP":
                    child.add_class("context-drop")
                # If mode is None, no context class is applied (normal appearance)

    def clear_context_modes(self) -> None:
        """Remove all context mode visual indicators."""
        for child in self._get_children():
            if isinstance(child, WidgetWithTurnId):
                for cls in self.CONTEXT_CLASSES:
                    child.remove_class(cls)

    # -------------------------------------------------------------------------
    # Logging helpers
    # -------------------------------------------------------------------------

    def _log_info(self, message: str) -> None:
        """Log info message if debug_log is available."""
        if self._debug_log:
            self._debug_log.info(message, category="widget_registry")

    def _log_debug(self, message: str) -> None:
        """Log debug message if debug_log is available."""
        if self._debug_log:
            self._debug_log.debug(message, category="widget_registry")

    def _log_warning(self, message: str) -> None:
        """Log warning message if debug_log is available."""
        if self._debug_log:
            self._debug_log.warning(message, category="widget_registry")
