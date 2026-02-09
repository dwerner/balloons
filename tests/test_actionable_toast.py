"""Tests for ActionableToast widget."""

import pytest
from textual.app import App, ComposeResult
from textual.containers import Container

from widgets.actionable_toast import (
    ActionableToast,
    ActionableToastRack,
    ActionableNotification,
)


class ToastTestApp(App):
    """Test app for actionable toasts."""

    def compose(self) -> ComposeResult:
        yield Container(id="main")
        yield ActionableToastRack(id="toast-rack")


@pytest.mark.asyncio
async def test_actionable_notification_creation():
    """Test creating an ActionableNotification."""
    notification = ActionableNotification(
        message="Test message",
        title="Test Title",
        severity="information",
        action_data={"session_id": "abc123"},
        action_label="Click me",
    )

    assert notification.message == "Test message"
    assert notification.title == "Test Title"
    assert notification.action_data == {"session_id": "abc123"}
    assert notification.action_label == "Click me"
    assert not notification.has_expired


@pytest.mark.asyncio
async def test_toast_rack_add_notification():
    """Test adding a notification to the toast rack."""
    async with ToastTestApp().run_test() as pilot:
        app = pilot.app
        toast_rack = app.query_one("#toast-rack", ActionableToastRack)

        notification = ActionableNotification(
            message="Background job done",
            action_data={"action": "switch_session", "session_id": "test123"},
        )

        toast_rack.add_notification(notification)
        await pilot.pause()  # Allow mount to complete

        # Check that a toast was mounted
        toasts = toast_rack.query(ActionableToast)
        assert len(toasts) == 1


@pytest.mark.asyncio
async def test_toast_click_emits_message():
    """Test that clicking a toast emits the Clicked message."""
    messages_received = []

    class ClickTrackingApp(ToastTestApp):
        def on_actionable_toast_clicked(self, event: ActionableToast.Clicked):
            messages_received.append(event)

    async with ClickTrackingApp().run_test() as pilot:
        app = pilot.app
        toast_rack = app.query_one("#toast-rack", ActionableToastRack)

        notification = ActionableNotification(
            message="Click me",
            action_data={"action": "test_action", "value": 42},
        )

        toast_rack.add_notification(notification)
        await pilot.pause()

        # Find and click the toast
        toasts = toast_rack.query(ActionableToast)
        assert len(toasts) == 1

        await pilot.click(ActionableToast)
        await pilot.pause()

        # Check message was received
        assert len(messages_received) == 1
        assert messages_received[0].action_data["action"] == "test_action"
        assert messages_received[0].action_data["value"] == 42


@pytest.mark.asyncio
async def test_toast_removed_after_click():
    """Test that toast is removed after being clicked."""
    async with ToastTestApp().run_test() as pilot:
        app = pilot.app
        toast_rack = app.query_one("#toast-rack", ActionableToastRack)

        notification = ActionableNotification(
            message="Will be removed",
            action_data={},
        )

        toast_rack.add_notification(notification)
        await pilot.pause()

        # Verify toast exists
        assert len(toast_rack.query(ActionableToast)) == 1

        # Click the toast
        await pilot.click(ActionableToast)
        await pilot.pause()

        # Toast should be removed
        assert len(toast_rack.query(ActionableToast)) == 0
