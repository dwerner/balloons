"""Tests for scroll_controller module."""

import pytest
from dataclasses import dataclass
from typing import Any, Callable
from widgets.scroll_controller import ScrollController, ScrollableContainer, WidgetRegion


@dataclass
class MockSize:
    """Mock size object with height."""
    height: int = 100


class MockScrollContainer:
    """Mock implementation of ScrollableContainer for testing."""

    def __init__(
        self,
        scroll_y: float = 0,
        max_scroll_y: float = 1000,
        is_mounted: bool = True,
        height: int = 100,
    ):
        self._scroll_y = scroll_y
        self._max_scroll_y = max_scroll_y
        self._is_mounted = is_mounted
        self._size = MockSize(height=height)
        self._pending_callbacks: list[Callable[[], None]] = []
        self._scroll_end_called = False

    @property
    def scroll_y(self) -> float:
        return self._scroll_y

    @property
    def max_scroll_y(self) -> float:
        return self._max_scroll_y

    @property
    def is_mounted(self) -> bool:
        return self._is_mounted

    @property
    def size(self) -> MockSize:
        return self._size

    def scroll_end(self, *, animate: bool = False) -> None:
        self._scroll_end_called = True
        self._scroll_y = self._max_scroll_y

    def scroll_to(self, *, y: float, animate: bool = False) -> None:
        self._scroll_y = y

    def call_after_refresh(self, callback: Callable[[], None]) -> None:
        self._pending_callbacks.append(callback)

    def call_later(self, callback: Callable[[], None]) -> None:
        self._pending_callbacks.append(callback)

    def flush_callbacks(self) -> None:
        """Execute all pending callbacks (test helper)."""
        callbacks = self._pending_callbacks[:]
        self._pending_callbacks.clear()
        for cb in callbacks:
            cb()


class TestScrollControllerBasics:
    """Test basic scroll controller functionality."""

    def test_initial_state_is_following(self):
        """Controller starts in following mode."""
        container = MockScrollContainer()
        controller = ScrollController(container)

        assert controller.following is True

    def test_setting_following_to_false(self):
        """Can set following to False."""
        container = MockScrollContainer()
        controller = ScrollController(container)

        controller.following = False

        assert controller.following is False

    def test_following_changed_callback(self):
        """Callback is called when following state changes."""
        container = MockScrollContainer()
        changes: list[bool] = []
        controller = ScrollController(
            container,
            on_following_changed=lambda v: changes.append(v)
        )

        controller.following = False

        assert changes == [False]

    def test_no_callback_when_same_value(self):
        """Callback is not called when setting same value."""
        container = MockScrollContainer()
        changes: list[bool] = []
        controller = ScrollController(
            container,
            on_following_changed=lambda v: changes.append(v)
        )

        controller.following = True  # Same as initial

        assert changes == []

    def test_reset_to_following(self):
        """reset_to_following sets following True."""
        container = MockScrollContainer()
        controller = ScrollController(container)
        controller.following = False

        controller.reset_to_following()

        assert controller.following is True


class TestOnScrollChanged:
    """Test the on_scroll_changed behavior.

    Note: Follow mode is now manually controlled via toggle button.
    on_scroll_changed just tracks position, it doesn't change follow state.
    """

    def test_scroll_does_not_change_following_state(self):
        """Scrolling should not change following state (manual control only)."""
        container = MockScrollContainer(scroll_y=951, max_scroll_y=1000)
        controller = ScrollController(container)
        controller._following = False  # Start not following

        controller.on_scroll_changed()

        # Should remain not following - state is manual only
        assert controller.following is False

    def test_scroll_at_top_does_not_enable_following(self):
        """Scrolling to top should not disable following (manual control only)."""
        container = MockScrollContainer(scroll_y=0, max_scroll_y=1000)
        controller = ScrollController(container)
        controller._following = True  # Start following

        controller.on_scroll_changed()

        # Should remain following - state is manual only
        assert controller.following is True

    def test_small_content_preserves_following_state(self):
        """Small content should not auto-change following state."""
        container = MockScrollContainer(scroll_y=0, max_scroll_y=1)
        controller = ScrollController(container)
        controller._following = False  # Start not following

        controller.on_scroll_changed()

        # Should remain not following - state is manual only
        assert controller.following is False

    def test_not_mounted_does_nothing(self):
        """Does nothing if container is not mounted (preserves state)."""
        container = MockScrollContainer(scroll_y=0, max_scroll_y=1000, is_mounted=False)
        controller = ScrollController(container)
        controller._following = True

        controller.on_scroll_changed()

        # Should still be True (initial state)
        assert controller.following is True

    def test_tracks_last_scroll_position(self):
        """on_scroll_changed should track last scroll position."""
        container = MockScrollContainer(scroll_y=500, max_scroll_y=1000)
        controller = ScrollController(container)

        controller.on_scroll_changed()

        assert controller._last_scroll_y == 500

    def test_programmatic_scroll_context_still_works(self):
        """Programmatic scroll context flag should still work."""
        container = MockScrollContainer(scroll_y=0, max_scroll_y=1000)
        controller = ScrollController(container)

        with controller.programmatic_scroll_context():
            assert controller.is_programmatic_scroll is True

        assert controller.is_programmatic_scroll is False


class TestSmartScroll:
    """Test the smart_scroll behavior."""

    def test_smart_scroll_when_following(self):
        """smart_scroll schedules scroll_end when following."""
        container = MockScrollContainer()
        controller = ScrollController(container)

        controller.smart_scroll()
        container.flush_callbacks()

        assert container._scroll_end_called is True

    def test_smart_scroll_when_not_following(self):
        """smart_scroll does nothing when not following."""
        container = MockScrollContainer()
        controller = ScrollController(container)
        controller.following = False

        controller.smart_scroll()
        container.flush_callbacks()

        assert container._scroll_end_called is False

    def test_smart_scroll_uses_programmatic_context(self):
        """smart_scroll should mark its scroll as programmatic."""
        container = MockScrollContainer()
        controller = ScrollController(container)

        # Track whether programmatic flag was set during scroll_end
        programmatic_during_scroll = []
        original_scroll_end = container.scroll_end

        def tracking_scroll_end(*, animate=False):
            programmatic_during_scroll.append(controller.is_programmatic_scroll)
            original_scroll_end(animate=animate)

        container.scroll_end = tracking_scroll_end

        controller.smart_scroll()
        container.flush_callbacks()

        assert programmatic_during_scroll == [True]


class TestNotifyNewContent:
    """Test the notify_new_content behavior."""

    def test_notify_when_not_following(self):
        """Calls callback when not following."""
        container = MockScrollContainer()
        notifications: list[bool] = []
        controller = ScrollController(
            container,
            on_new_content_while_not_following=lambda: notifications.append(True)
        )
        controller.following = False

        controller.notify_new_content()

        assert notifications == [True]

    def test_no_notify_when_following(self):
        """Does not call callback when following."""
        container = MockScrollContainer()
        notifications: list[bool] = []
        controller = ScrollController(
            container,
            on_new_content_while_not_following=lambda: notifications.append(True)
        )

        controller.notify_new_content()

        assert notifications == []


class TestScrollToWidget:
    """Test the scroll_to_widget behavior."""

    def test_widget_already_visible(self):
        """No scroll when widget is already fully visible."""
        container = MockScrollContainer(scroll_y=100, height=100)
        controller = ScrollController(container)

        # Widget at y=120, height=30, so bottom=150
        # effective_viewport = 100 - 2 = 98
        # visible_top = 100, visible_bottom = 198
        # 120 >= 100 and 150 <= 198, so no scroll
        controller.scroll_to_widget(WidgetRegion(y=120, height=30))

        assert container.scroll_y == 100

    def test_widget_above_viewport(self):
        """Scrolls up when widget is above viewport."""
        container = MockScrollContainer(scroll_y=200, height=100)
        controller = ScrollController(container)

        # Widget is at y=50, we're scrolled to 200, so widget is above
        controller.scroll_to_widget(WidgetRegion(y=50, height=30))

        assert container.scroll_y == 50

    def test_widget_below_viewport(self):
        """Scrolls down when widget is below viewport."""
        container = MockScrollContainer(scroll_y=0, height=100)
        controller = ScrollController(container)

        # Widget at y=200, height=30, bottom=230
        # effective_viewport = 100 - 2 = 98
        # target_y = 230 - 98 = 132
        controller.scroll_to_widget(WidgetRegion(y=200, height=30))

        assert container.scroll_y == 132

    def test_widget_taller_than_viewport(self):
        """Scrolls to top when widget is taller than viewport."""
        container = MockScrollContainer(scroll_y=0, height=100)
        controller = ScrollController(container)

        # Widget doesn't fit (height 200 > effective_viewport 98), scroll to top
        controller.scroll_to_widget(WidgetRegion(y=200, height=200))

        assert container.scroll_y == 200


class TestScrollToWidgetAtTop:
    """Test the scroll_to_widget with at_top=True."""

    def test_scrolls_widget_to_top(self):
        """Always scrolls widget to top of viewport."""
        container = MockScrollContainer(scroll_y=0, height=100)
        controller = ScrollController(container)

        controller.scroll_to_widget(WidgetRegion(y=300, height=50), at_top=True)

        assert container.scroll_y == 300

    def test_accounts_for_content_offset(self):
        """Adjusts for container's content offset."""
        container = MockScrollContainer(scroll_y=0, height=100)
        controller = ScrollController(container)

        # adjusted_y = max(0, 300 - 10) = 290
        controller.scroll_to_widget(
            WidgetRegion(y=300, height=50),
            at_top=True,
            content_offset_y=10
        )

        assert container.scroll_y == 290

    def test_clamps_to_zero(self):
        """Does not scroll to negative position."""
        container = MockScrollContainer(scroll_y=0, height=100)
        controller = ScrollController(container)

        # adjusted_y = max(0, 20 - 50) = max(0, -30) = 0
        controller.scroll_to_widget(
            WidgetRegion(y=20, height=50),
            at_top=True,
            content_offset_y=50
        )

        assert container.scroll_y == 0


class TestManualFollowControl:
    """Test that follow mode is manually controlled via toggle only."""

    def test_upward_scroll_does_not_change_following(self):
        """Scrolling up should not change follow state (manual control only)."""
        container = MockScrollContainer(scroll_y=1000, max_scroll_y=1000)
        controller = ScrollController(container)
        assert controller.following is True

        # User scrolls up
        container._scroll_y = 900
        controller.on_scroll_changed(old_scroll_y=1000)

        # Should still be following - state is manual only
        assert controller.following is True

    def test_scroll_near_bottom_does_not_change_following(self):
        """Scrolling near bottom should not change follow state."""
        container = MockScrollContainer(scroll_y=1000, max_scroll_y=1000)
        controller = ScrollController(container)
        controller._following = False  # Manually disabled

        # Scroll near bottom
        container._scroll_y = 990
        controller.on_scroll_changed(old_scroll_y=1000)

        # Should still be not following - state is manual only
        assert controller.following is False

    def test_downward_scroll_preserves_following(self):
        """Scrolling down should preserve follow state (manual control only)."""
        container = MockScrollContainer(scroll_y=900, max_scroll_y=1000)
        controller = ScrollController(container)
        controller._following = False  # Start not following

        # Scroll down toward bottom
        container._scroll_y = 980
        controller.on_scroll_changed(old_scroll_y=900)

        # Still not following - state is manual only
        assert controller.following is False

    def test_programmatic_scroll_preserves_following(self):
        """Programmatic scrolls should preserve follow state."""
        container = MockScrollContainer(scroll_y=1000, max_scroll_y=1000)
        controller = ScrollController(container)

        # Programmatic scroll up
        with controller.programmatic_scroll_context():
            container._scroll_y = 500
            controller.on_scroll_changed(old_scroll_y=1000)

        # Still following - state is manual only
        assert controller.following is True

    def test_reset_to_following_enables_follow(self):
        """reset_to_following is the way to programmatically enable follow."""
        container = MockScrollContainer(scroll_y=0, max_scroll_y=1000)
        controller = ScrollController(container)
        controller._following = False

        controller.reset_to_following()

        assert controller.following is True

    def test_direct_assignment_changes_follow(self):
        """Direct assignment to following property is the toggle mechanism."""
        container = MockScrollContainer(scroll_y=500, max_scroll_y=1000)
        controller = ScrollController(container)

        # Toggle off
        controller.following = False
        assert controller.following is False

        # Toggle on
        controller.following = True
        assert controller.following is True


class TestProtocolCompliance:
    """Test that MockScrollContainer properly implements the protocol."""

    def test_mock_implements_protocol(self):
        """MockScrollContainer should satisfy ScrollableContainer protocol."""
        container = MockScrollContainer()
        # Protocol compliance is checked at runtime via isinstance
        # The protocol uses runtime_checkable decorator
        assert isinstance(container, ScrollableContainer)
