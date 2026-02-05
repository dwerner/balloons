"""Scroll controller - manages auto-scroll ("following") behavior.

This module separates scroll state management from the ChatLogView widget,
enabling:
- Unit testing without full Textual widget instantiation
- Clear separation of scroll logic from content management
- Reusable scroll behavior for other scrolling containers
"""

from dataclasses import dataclass
from typing import Protocol, Callable, Any, runtime_checkable


@runtime_checkable
class ScrollableContainer(Protocol):
    """Protocol defining the interface needed from a scrollable container.

    This allows ScrollController to work with any Textual scroll container
    (VerticalScroll, ScrollView, etc.) and enables testing with mocks.
    """

    @property
    def scroll_y(self) -> float:
        """Current vertical scroll position."""
        ...

    @property
    def max_scroll_y(self) -> float:
        """Maximum vertical scroll position."""
        ...

    @property
    def size(self) -> Any:
        """Container size with .height attribute."""
        ...

    @property
    def is_mounted(self) -> bool:
        """Whether the container is mounted in the DOM."""
        ...

    def scroll_to(self, *, y: float, animate: bool = False) -> None:
        """Scroll to a specific position."""
        ...

    def scroll_end(self, *, animate: bool = False) -> None:
        """Scroll to the end (bottom) of content."""
        ...

    def call_after_refresh(self, callback: Callable[[], None]) -> None:
        """Schedule callback after next layout refresh."""
        ...

    def call_later(self, callback: Callable[[], None]) -> None:
        """Schedule callback for later execution."""
        ...


@dataclass
class WidgetRegion:
    """Minimal region data needed for scroll calculations."""
    y: float
    height: float


class ScrollController:
    """Manages scroll state and auto-follow behavior.

    The controller tracks whether the user is "following" new content
    (auto-scrolling to bottom) or has scrolled away to read history.

    Usage:
        controller = ScrollController(
            container=my_vertical_scroll,
            on_following_changed=lambda f: update_ui(f),
            on_new_content_while_not_following=lambda: show_indicator(),
        )

        # When content is added:
        controller.smart_scroll()
        controller.notify_new_content()

        # When user scrolls:
        controller.check_at_bottom()
    """

    # Threshold for considering scroll position "at bottom" (in pixels)
    AT_BOTTOM_THRESHOLD = 50

    # Reserved space for floating indicators (in lines)
    INDICATOR_HEIGHT = 2

    def __init__(
        self,
        container: ScrollableContainer,
        on_following_changed: Callable[[bool], None] | None = None,
        on_new_content_while_not_following: Callable[[], None] | None = None,
        debug_log: Any = None,
    ):
        """Initialize the scroll controller.

        Args:
            container: The scrollable container to control
            on_following_changed: Callback when following state changes
            on_new_content_while_not_following: Callback when content added while not following
            debug_log: Optional debug logger with .info(), .debug() methods
        """
        self._container = container
        self._on_following_changed = on_following_changed
        self._on_new_content_while_not_following = on_new_content_while_not_following
        self._debug_log = debug_log
        self._following = True

    @property
    def following(self) -> bool:
        """Whether we're auto-scrolling to new content."""
        return self._following

    @following.setter
    def following(self, value: bool) -> None:
        """Set following state and notify if changed."""
        if self._following != value:
            self._following = value
            self._log_info(f"following changed to {value}")
            if self._on_following_changed:
                self._on_following_changed(value)

    def check_at_bottom(self) -> None:
        """Check if we're at the bottom and update following state.

        Called after scroll events to determine if user has scrolled away
        from the bottom (stopping auto-follow) or back to it (resuming).
        """
        if not self._container.is_mounted:
            return

        max_y = self._container.max_scroll_y
        scroll_y = self._container.scroll_y

        # If max_scroll_y is 0 or very small, content fits in viewport - always following
        if max_y <= 1:
            at_bottom = True
        else:
            at_bottom = (max_y - scroll_y) < self.AT_BOTTOM_THRESHOLD

        # Only update if changed to avoid callback spam
        if self._following != at_bottom:
            self._log_info(
                f"check_at_bottom: following changing from {self._following} to {at_bottom}, "
                f"max_scroll_y={max_y}, scroll_y={scroll_y}, gap={max_y - scroll_y}"
            )
            self.following = at_bottom

    def smart_scroll(self) -> None:
        """Scroll to end only if user is following.

        This is the main method to call when new content is added.
        It respects the user's scroll position - if they've scrolled up
        to read history, it won't jump them to the bottom.
        """
        if self._following:
            self._log_debug("smart_scroll: following=True, scheduling scroll_end")
            # Defer scroll until after layout refresh so scroll_end knows the true max_scroll_y
            self._container.call_after_refresh(self._scroll_end_and_verify)
        else:
            self._log_debug("smart_scroll: following=False, NOT scrolling")

    def _scroll_end_and_verify(self) -> None:
        """Scroll to end and re-check if we're actually at the bottom."""
        self._log_debug(
            f"_scroll_end_and_verify: before scroll_end, "
            f"scroll_y={self._container.scroll_y}, max_scroll_y={self._container.max_scroll_y}"
        )
        self._container.scroll_end(animate=False)
        self._log_debug(
            f"_scroll_end_and_verify: after scroll_end, "
            f"scroll_y={self._container.scroll_y}, max_scroll_y={self._container.max_scroll_y}"
        )
        # Re-check after scroll in case content grew during the frame
        self._container.call_later(self.check_at_bottom)

    def notify_new_content(self) -> None:
        """Notify that new content was added while not following.

        Call this after adding content to trigger the "new content below"
        indicator if the user has scrolled away.
        """
        if not self._following:
            self._log_info("notify_new_content: NOT following, triggering callback")
            if self._on_new_content_while_not_following:
                self._on_new_content_while_not_following()

    def scroll_to_widget(
        self,
        widget_region: WidgetRegion,
        at_top: bool = False,
        content_offset_y: float = 0,
    ) -> None:
        """Scroll to show a widget, then check follow state.

        Args:
            widget_region: Region with y and height of the widget (virtual coordinates)
            at_top: If True, always scroll widget to top of viewport.
                   If False, use smart scroll that minimizes movement.
            content_offset_y: Content offset to subtract (for padding/borders)
        """
        if at_top:
            self._scroll_widget_to_top(widget_region, content_offset_y)
        else:
            self._scroll_widget_smart(widget_region)

        # After scrolling, check if we're at the bottom
        self._container.call_later(self.check_at_bottom)

    def _scroll_widget_smart(self, widget_region: WidgetRegion) -> None:
        """Scroll to widget using minimal movement strategy.

        If the widget is shorter than the viewport, scroll so the entire widget
        is visible. If the widget is taller than the viewport, scroll so the top
        of the widget is at the top of the viewport.
        """
        viewport_height = self._container.size.height
        effective_viewport = viewport_height - self.INDICATOR_HEIGHT

        widget_height = widget_region.height
        widget_top = widget_region.y
        widget_bottom = widget_top + widget_height

        self._log_info(
            f"scroll_widget_smart: widget_region=(y={widget_top}, h={widget_height}), "
            f"viewport_height={viewport_height}, effective_viewport={effective_viewport}, "
            f"current_scroll_y={self._container.scroll_y}"
        )

        if widget_height <= effective_viewport:
            # Widget fits in viewport - ensure entire widget is visible above indicator
            current_scroll = self._container.scroll_y
            visible_top = current_scroll
            visible_bottom = current_scroll + effective_viewport

            if widget_top >= visible_top and widget_bottom <= visible_bottom:
                # Already fully visible - no scroll needed
                self._log_info("  -> already visible, no scroll")
            elif widget_top < visible_top:
                # Widget is above viewport - scroll up to show it
                self._log_info(f"  -> widget above viewport, scrolling to y={widget_top}")
                self._container.scroll_to(y=widget_top, animate=False)
            else:
                # Widget is below viewport - scroll down so bottom of widget
                # is at bottom of effective viewport (above indicator)
                target_y = widget_bottom - effective_viewport
                self._log_info(f"  -> widget below viewport, scrolling to y={target_y}")
                self._container.scroll_to(y=target_y, animate=False)
        else:
            # Widget doesn't fit - scroll so top of widget is at top of viewport
            self._log_info(f"  -> widget too tall, scrolling to y={widget_top}")
            self._container.scroll_to(y=widget_top, animate=False)

    def _scroll_widget_to_top(self, widget_region: WidgetRegion, content_offset_y: float) -> None:
        """Scroll so the widget is at the top of the viewport."""
        widget_top = widget_region.y
        adjusted_y = max(0, widget_top - content_offset_y)

        self._log_info(
            f"scroll_widget_to_top: widget_region=(y={widget_top}), "
            f"content_offset_y={content_offset_y}, current_scroll_y={self._container.scroll_y}, "
            f"scrolling to y={adjusted_y}"
        )
        self._container.scroll_to(y=adjusted_y, animate=False)

    def reset_to_following(self) -> None:
        """Reset to following state (e.g., when user sends a message)."""
        self.following = True

    def _log_info(self, message: str) -> None:
        """Log info message if debug_log is available.

        Note: Using debug level to reduce noise - change back to info if debugging scroll issues.
        """
        if self._debug_log:
            self._debug_log.debug(message, category="scroll_controller")

    def _log_debug(self, message: str) -> None:
        """Log debug message if debug_log is available."""
        if self._debug_log:
            self._debug_log.debug(message, category="scroll_controller")
