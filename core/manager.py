"""Session manager for Balloons.

Manages multiple sessions and their runners, enabling background execution.
"""

import os
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from datetime import datetime

from session import Session
from models import Message, TextBlock
from config import BackendConfig
from .runner import SessionRunner, RunnerStatus, StreamEvent, StreamResult
from .runner_factory import create_runner


@dataclass
class SessionInfo:
    """Summary info about a session for display."""
    id: str
    title: str
    created: str
    model: str
    message_count: int
    is_child: bool
    is_returned: bool
    status: RunnerStatus


class SessionManager:
    """Manages multiple sessions and their background runners.

    Usage:
        manager = SessionManager()

        # Create and work with sessions
        session = manager.create_session()
        manager.set_active(session.id)

        # Start background streaming
        runner = manager.get_runner(session.id)
        runner.start_background(prompt, messages)

        # Poll for updates
        for session_id, events in manager.poll_all():
            for event in events:
                # Handle event
    """

    def __init__(self, backend_config: BackendConfig | None = None):
        self._sessions: Dict[str, Session] = {}
        self._runners: Dict[str, SessionRunner] = {}
        self._active_session_id: Optional[str] = None
        self._backend_config = backend_config or BackendConfig(name="claude")

    @property
    def active_session(self) -> Optional[Session]:
        """Get the currently active session."""
        if self._active_session_id:
            return self._sessions.get(self._active_session_id)
        return None

    @property
    def active_runner(self) -> Optional[SessionRunner]:
        """Get the runner for the active session."""
        if self._active_session_id:
            return self._runners.get(self._active_session_id)
        return None

    def create_session(self, working_directory: str = None) -> Session:
        """Create a new session.

        Args:
            working_directory: Initial working directory

        Returns:
            New Session instance
        """
        session = Session()
        # Default to current working directory if not specified
        session.set_working_directory(working_directory or os.getcwd())
        session.save()

        self._sessions[session.id] = session
        self._runners[session.id] = SessionRunner(session, runner=create_runner(self._backend_config))

        return session

    def load_session(self, session_id: str) -> Optional[Session]:
        """Load a session by ID.

        Args:
            session_id: Session ID to load

        Returns:
            Session if found, None otherwise
        """
        if session_id in self._sessions:
            return self._sessions[session_id]

        session = Session.load(session_id)
        if session:
            self._sessions[session.id] = session
            self._runners[session.id] = SessionRunner(session, runner=create_runner(self._backend_config))

        return session

    def set_active(self, session_id: str) -> bool:
        """Set the active session.

        Args:
            session_id: Session ID to make active

        Returns:
            True if session exists and was set active
        """
        if session_id not in self._sessions:
            # Try to load it
            if not self.load_session(session_id):
                return False

        self._active_session_id = session_id
        return True

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID.

        Args:
            session_id: Session ID

        Returns:
            Session if found
        """
        return self._sessions.get(session_id)

    def get_runner(self, session_id: str) -> Optional[SessionRunner]:
        """Get a session's runner.

        Args:
            session_id: Session ID

        Returns:
            SessionRunner if session exists
        """
        return self._runners.get(session_id)

    def fork_session(
        self,
        parent_id: str,
        prompt: str,
        messages: List[Message],
        return_condition: str = "manual",
    ) -> Session:
        """Fork a child session from a parent.

        Args:
            parent_id: Parent session ID
            prompt: Fork prompt
            messages: Messages to copy to child
            return_condition: Auto-return condition

        Returns:
            New child Session
        """
        parent = self._sessions.get(parent_id)
        if not parent:
            raise ValueError(f"Parent session {parent_id} not found")

        # Create child session
        child = Session()
        child.parent_id = parent_id
        child.return_condition = return_condition
        child.working_directories = parent.working_directories.copy()

        # Copy messages to child
        for msg in messages:
            child.add_message(msg.role, msg.content, content_blocks=msg.content_blocks)

        child.save()

        # Register child with parent
        parent.add_child(child.id, prompt, return_condition)
        parent.save()

        # Track in manager
        self._sessions[child.id] = child
        self._runners[child.id] = SessionRunner(child, runner=create_runner(self._backend_config))

        return child

    def return_from_child(
        self,
        child_id: str,
        return_content: str = "",
    ) -> Optional[Session]:
        """Return from a child session to its parent.

        Args:
            child_id: Child session ID
            return_content: Content to return to parent

        Returns:
            Parent session, or None if child has no parent
        """
        child = self._sessions.get(child_id)
        if not child or not child.parent_id:
            return None

        parent = self.load_session(child.parent_id)
        if not parent:
            return None

        # Mark child as returned
        child.returned = True
        child.save()

        # Update parent
        parent.mark_child_returned(child_id)
        parent.save()

        return parent

    def list_sessions(self) -> List[SessionInfo]:
        """List all available sessions.

        Returns:
            List of SessionInfo for all sessions
        """
        infos = []

        # Get sessions from disk
        for session_metadata in Session.list_sessions():
            session_id = session_metadata["id"]
            title = session_metadata.get("title", "")
            # Load to get more info if not already loaded
            session = self._sessions.get(session_id) or Session.load(session_id)
            if session:
                runner = self._runners.get(session_id)
                status = runner.status if runner else RunnerStatus.IDLE

                infos.append(SessionInfo(
                    id=session_id,
                    title=title or f"Session {session_id[:8]}",
                    created=created,
                    model=model,
                    message_count=len(session.messages),
                    is_child=session.parent_id is not None,
                    is_returned=session.returned,
                    status=status,
                ))

        return infos

    def poll_all(self) -> List[tuple[str, List[StreamEvent]]]:
        """Poll all active runners for new events.

        Returns:
            List of (session_id, events) tuples for sessions with events

        Note: We drain events from ALL runners, not just streaming ones,
        because a runner may have finished (status=IDLE) but still have
        the "done" event in its queue waiting to be polled.
        """
        results = []
        for session_id, runner in self._runners.items():
            events = runner.drain_events()
            if events:
                results.append((session_id, events))
        return results

    def get_streaming_sessions(self) -> List[str]:
        """Get IDs of sessions currently streaming.

        Returns:
            List of session IDs that are streaming
        """
        return [
            session_id
            for session_id, runner in self._runners.items()
            if runner.is_streaming
        ]

    def cancel_all(self) -> None:
        """Cancel all active runners."""
        for runner in self._runners.values():
            if runner.is_streaming:
                runner.cancel()
