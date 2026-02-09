"""Actionable toast notifications that can trigger callbacks when clicked."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any, ClassVar
from uuid import uuid4

from textual import on
from textual.containers import Container
from textual.content import Content
from textual.css.query import NoMatches
from textual.events import Click, Mount
from textual.message import Message
from textual.notifications import SeverityLevel
from textual.widgets._static import Static


@dataclass
class ActionableNotification:
    """A notification that can trigger an action when clicked.

    Attributes:
        message: The message to display
        title: Optional title for the notification
        severity: The severity level (information, warning, error)
        timeout: How long to show the notification (seconds)
        action_data: Arbitrary data to include with the click action
        action_label: Label shown to indicate clickability (e.g., "Click to view")
    """
    message: str
    title: str = ""
    severity: SeverityLevel = "information"
    timeout: float = 8  # Longer default since it's actionable
    action_data: dict[str, Any] = field(default_factory=dict)
    action_label: str = "Click to view"
    raised_at: float = field(default_factory=time)
    identity: str = field(default_factory=lambda: str(uuid4()))

    @property
    def time_left(self) -> float:
        """Time remaining before notification expires."""
        return (self.raised_at + self.timeout) - time()

    @property
    def has_expired(self) -> bool:
        """Check if notification has expired."""
        return self.time_left <= 0


class ActionableToast(Static, inherit_css=False):
    """A toast widget that triggers an action when clicked."""

    DEFAULT_CSS = """
    ActionableToast {
        width: 60;
        max-width: 50%;
        height: auto;
        margin-top: 1;
        visibility: visible;
        padding: 1 1;
        background: $panel-lighten-1;
        link-background: initial;
        link-color: $foreground;
        link-style: underline;
        link-background-hover: $primary;
        link-color-hover: $foreground;
        link-style-hover: bold not underline;
    }

    ActionableToast:hover {
        background: $panel-lighten-2;
    }

    .actionable-toast--title {
        text-style: bold;
        color: $foreground;
    }

    .actionable-toast--action {
        text-style: italic;
        color: $text-muted;
    }

    ActionableToast.-information {
        border-left: outer $success;
    }

    ActionableToast.-information .actionable-toast--title {
        color: $text-success;
    }

    ActionableToast.-warning {
        border-left: outer $warning;
    }

    ActionableToast.-warning .actionable-toast--title {
        color: $text-warning;
    }

    ActionableToast.-error {
        border-left: outer $error;
    }

    ActionableToast.-error .actionable-toast--title {
       color: $text-error;
    }
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {"actionable-toast--title", "actionable-toast--action"}
    DEFAULT_CLASSES = "-textual-system"

    @dataclass
    class Clicked(Message):
        """Message sent when an actionable toast is clicked."""
        notification: ActionableNotification

        @property
        def action_data(self) -> dict[str, Any]:
            """The action data from the notification."""
            return self.notification.action_data

    def __init__(self, notification: ActionableNotification) -> None:
        """Initialize the toast.

        Args:
            notification: The notification to display
        """
        super().__init__(classes=f"-{notification.severity}")
        self._notification = notification
        self._timeout = notification.time_left

    def render(self) -> Content:
        """Render the toast content."""
        notification = self._notification

        # Build message content
        message_content = Content(notification.message)

        # Add action label hint
        action_style = self.get_visual_style("actionable-toast--action")
        message_content = Content.assemble(
            message_content,
            "\n",
            (f"[{notification.action_label}]", action_style),
        )

        # Add title if present
        if notification.title:
            header_style = self.get_visual_style("actionable-toast--title")
            message_content = Content.assemble(
                (notification.title, header_style),
                "\n",
                message_content,
            )

        return message_content

    def _on_mount(self, _: Mount) -> None:
        """Start the expiration timer when mounted."""
        self.set_timer(self._timeout, self._expire)

    @on(Click)
    def _on_click(self) -> None:
        """Handle click - post action message then remove."""
        # Post the clicked message with action data
        self.post_message(self.Clicked(self._notification))
        # Remove the toast
        self._remove_self()

    def _expire(self) -> None:
        """Remove the toast when it expires."""
        self._remove_self()

    def _remove_self(self) -> None:
        """Remove this toast from the display."""
        parent = self.parent
        if isinstance(parent, ActionableToastHolder):
            parent.remove()
        else:
            self.remove()


class ActionableToastHolder(Container, inherit_css=False):
    """Container that holds a single actionable toast for alignment."""

    DEFAULT_CSS = """
    ActionableToastHolder {
        align-horizontal: right;
        width: 1fr;
        height: auto;
        visibility: hidden;
    }
    """


class ActionableToastRack(Container, inherit_css=False):
    """A container for holding actionable toasts.

    Mount this in your app to display actionable notifications.
    Call add_notification() to show a new toast.
    """

    DEFAULT_CSS = """
    ActionableToastRack {
        display: none;
        layer: _toastrack;
        width: 1fr;
        height: auto;
        dock: bottom;
        align: right bottom;
        visibility: hidden;
        layout: vertical;
        overflow-y: scroll;
        margin-bottom: 1;
    }
    """
    DEFAULT_CLASSES = "-textual-system"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._notifications: dict[str, ActionableNotification] = {}

    @staticmethod
    def _toast_id(notification: ActionableNotification) -> str:
        """Create a DOM ID for a notification."""
        return f"--actionable-toast-{notification.identity}"

    def add_notification(self, notification: ActionableNotification) -> None:
        """Add and display a notification.

        Args:
            notification: The notification to show
        """
        # Clean up expired notifications
        self._reap_expired()

        # Store the notification
        self._notifications[notification.identity] = notification

        # Show the rack and mount the toast
        self.display = True
        holder = ActionableToastHolder(
            ActionableToast(notification),
            id=self._toast_id(notification),
        )
        self.mount(holder)
        self.call_later(self.scroll_end, animate=False, force=True)

    def _reap_expired(self) -> None:
        """Remove expired notifications."""
        expired = [
            nid for nid, n in self._notifications.items()
            if n.has_expired
        ]
        for nid in expired:
            del self._notifications[nid]

        # Also remove any orphaned toasts
        for toast in self.query(ActionableToast):
            if toast._notification.identity not in self._notifications:
                parent = toast.parent
                if isinstance(parent, ActionableToastHolder):
                    parent.remove()
                else:
                    toast.remove()

        # Hide if empty
        if not self._notifications:
            self.display = False

    def remove_notification(self, notification: ActionableNotification) -> None:
        """Remove a specific notification.

        Args:
            notification: The notification to remove
        """
        if notification.identity in self._notifications:
            del self._notifications[notification.identity]

            try:
                holder = self.get_child_by_id(self._toast_id(notification))
                holder.remove()
            except NoMatches:
                pass

            if not self._notifications:
                self.display = False
