"""Stream state management for Balloons.

This module provides a centralized view of all active LLM streams across sessions.
It tracks streaming sessions, helper streams (summaries, compression), and their states.

This is the "model" layer - it doesn't interact with UI, just provides data about
what's happening. The UI can poll or observe this to update displays.

Concepts:
    - Stream: Any in-flight LLM interaction (chat exchange, summary generation, etc.)
    - Session Stream: A chat exchange within a session (user prompt -> assistant response)
    - Helper Stream: A background LLM stream (compression, merge summary, link summary)

Usage:
    # Get the global stream state
    stream_state = get_stream_state()

    # Register a new streaming stream (updates state, schedules observer notification)
    stream_state.register_session_stream(
        session_id="abc123",
        exchange_id="def456",
        prompt="Tell me about...",
        backend_name="claude",
    )

    # Update stream status
    stream_state.update_stream(
        stream_id="def456",
        status=StreamStatus.STREAMING,
        tokens_streamed=150,
    )

    # Query active streams (sync - just reads in-memory state)
    all_streams = stream_state.get_all_streams()
    streaming = stream_state.get_streaming_streams()

    # Subscribe to events (async observers only)
    async def on_stream_event(event: StreamEvent, stream: Stream):
        print(f"Stream {stream.stream_id}: {event}")

    stream_state.add_observer(on_stream_event)
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Awaitable


class StreamStatus(Enum):
    """Status of a stream."""
    PENDING = "pending"      # Stream created but not yet started
    STREAMING = "streaming"  # Actively receiving tokens from LLM
    EXECUTING = "executing"  # Tool is executing (between LLM responses)
    COMPLETED = "completed"  # Stream finished successfully
    ERROR = "error"          # Stream failed with an error
    CANCELLED = "cancelled"  # Stream was cancelled by user


class StreamType(Enum):
    """Type of stream."""
    CHAT = "chat"                # Normal chat exchange (user -> assistant)
    COMPRESSION = "compression"  # Context compression (for forking)
    MERGE_SUMMARY = "merge"      # Merge summary generation
    LINK_SUMMARY = "link"        # Link summary generation
    ARCHIVE_SUMMARY = "archive"  # Archive summary generation
    TITLE = "title"              # Session title generation
    REPORT_SUMMARY = "report"    # Status report executive summary


@dataclass
class Stream:
    """A single LLM stream.

    Attributes:
        stream_id: Unique identifier for this stream (often exchange_id for chats)
        stream_type: What kind of stream this is
        status: Current status of the stream
        session_id: Associated session (if any)
        backend_name: Which backend is handling this stream
        started_at: When the stream started
        finished_at: When the stream completed (if done)
        prompt: The prompt that started this stream (truncated for display)
        tokens_streamed: Number of tokens received so far
        error: Error message if status is ERROR
        tool_name: Name of tool currently executing (if EXECUTING status)
        tool_count: Number of tools executed so far in this exchange
        token_samples: Recent (timestamp, token_count) samples for rate calculation
    """
    stream_id: str
    stream_type: StreamType
    status: StreamStatus = StreamStatus.PENDING
    session_id: Optional[str] = None
    backend_name: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    prompt: str = ""  # Truncated for display
    tokens_streamed: int = 0  # Estimated output tokens (chars/4)
    error: Optional[str] = None
    tool_name: Optional[str] = None  # Currently executing tool
    tool_count: int = 0  # Tools executed in this exchange
    # Actual token counts from API
    input_tokens: int = 0  # Context/input tokens
    output_tokens: int = 0  # Generated output tokens
    context_window: int = 0  # Model's context window size
    model: str = ""  # Model name
    # Token rate tracking: list of (timestamp, cumulative_tokens) samples
    # Keep last 20 samples for sparkline (about 2 seconds at 10 updates/sec)
    token_samples: list[tuple[float, int]] = field(default_factory=list)
    _max_samples: int = field(default=20, repr=False)

    @property
    def duration_seconds(self) -> float:
        """Get stream duration in seconds."""
        end = self.finished_at or datetime.now()
        return (end - self.started_at).total_seconds()

    @property
    def is_active(self) -> bool:
        """Check if stream is still in progress."""
        return self.status in (StreamStatus.PENDING, StreamStatus.STREAMING, StreamStatus.EXECUTING)

    @property
    def short_prompt(self) -> str:
        """Get a shortened version of the prompt for display."""
        if len(self.prompt) <= 60:
            return self.prompt
        return self.prompt[:57] + "..."

    def add_token_sample(self, tokens: int) -> None:
        """Record a token sample for rate calculation."""
        import time
        now = time.monotonic()
        self.token_samples.append((now, tokens))
        # Keep only recent samples
        if len(self.token_samples) > self._max_samples:
            self.token_samples = self.token_samples[-self._max_samples:]

    def get_token_rates(self) -> list[float]:
        """Get token rates (tokens/sec) between each sample.

        Returns list of rates for sparkline display.
        """
        if len(self.token_samples) < 2:
            return []

        rates = []
        for i in range(1, len(self.token_samples)):
            prev_time, prev_tokens = self.token_samples[i - 1]
            curr_time, curr_tokens = self.token_samples[i]
            dt = curr_time - prev_time
            if dt > 0:
                rate = (curr_tokens - prev_tokens) / dt
                rates.append(rate)
        return rates

    @property
    def current_token_rate(self) -> float:
        """Get current token rate (tokens/sec) based on recent samples."""
        if len(self.token_samples) < 2:
            return 0.0
        # Use last few samples for smoother average
        samples = self.token_samples[-5:] if len(self.token_samples) >= 5 else self.token_samples
        if len(samples) < 2:
            return 0.0
        first_time, first_tokens = samples[0]
        last_time, last_tokens = samples[-1]
        dt = last_time - first_time
        if dt > 0:
            return (last_tokens - first_tokens) / dt
        return 0.0


@dataclass
class SessionStreamInfo:
    """Summary of stream activity for a session.

    Provides a quick overview of what's happening in a session.
    """
    session_id: str
    session_title: str = ""
    backend_name: str = ""
    is_streaming: bool = False
    current_stream: Optional[Stream] = None
    total_exchanges: int = 0  # Number of completed exchanges
    last_activity: Optional[datetime] = None


class StreamEvent(Enum):
    """Events emitted by StreamState."""
    STREAM_STARTED = "stream_started"
    STREAM_UPDATED = "stream_updated"  # Status change, tokens updated, etc.
    STREAM_COMPLETED = "stream_completed"
    STREAM_ERROR = "stream_error"
    STREAM_CANCELLED = "stream_cancelled"


# Type alias for async observer callbacks
AsyncObserver = Callable[[StreamEvent, Stream], Awaitable[None]]


class StreamState:
    """Centralized state for all LLM streams.

    Singleton pattern - there's one StreamState for the application.

    All mutation methods are synchronous for easy use from any code path.
    Observer notifications are scheduled on the event loop asynchronously.
    Query methods are sync since they just read in-memory state.
    """

    _instance: "StreamState | None" = None

    def __new__(cls) -> "StreamState":
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize stream state (only runs once due to singleton)."""
        if self._initialized:
            return
        self._initialized = True

        # Stream storage
        self._streams: dict[str, Stream] = {}  # stream_id -> Stream

        # Session tracking (session_id -> current stream_id)
        self._session_streams: dict[str, str] = {}

        # Async observers for state changes
        self._observers: list[AsyncObserver] = []

    # =========================================================================
    # Observer Pattern
    # =========================================================================

    def add_observer(self, callback: AsyncObserver) -> None:
        """Add an async observer for stream state changes.

        Args:
            callback: Async function called with (event_type, stream) on changes
        """
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: AsyncObserver) -> None:
        """Remove an observer."""
        if callback in self._observers:
            self._observers.remove(callback)

    def _schedule_notification(self, event: StreamEvent, stream: Stream) -> None:
        """Schedule async observer notifications on the event loop.

        This is called from sync methods and schedules the async callbacks
        to run on the event loop without blocking.
        """
        if not self._observers:
            return

        for callback in self._observers:
            # Create a task for each observer
            asyncio.ensure_future(self._call_observer(callback, event, stream))

    async def _call_observer(self, callback: AsyncObserver, event: StreamEvent, stream: Stream) -> None:
        """Safely call an async observer."""
        try:
            await callback(event, stream)
        except Exception:
            pass  # Don't let observer errors break stream tracking

    # =========================================================================
    # Stream Registration
    # =========================================================================

    def register_session_stream(
        self,
        session_id: str,
        exchange_id: str,
        prompt: str,
        backend_name: str = "",
    ) -> Stream:
        """Register a new chat stream for a session.

        Args:
            session_id: The session this stream belongs to
            exchange_id: Unique ID for this exchange
            prompt: The user's prompt
            backend_name: Which backend is handling this

        Returns:
            The created Stream
        """
        stream = Stream(
            stream_id=exchange_id,
            stream_type=StreamType.CHAT,
            status=StreamStatus.STREAMING,
            session_id=session_id,
            backend_name=backend_name,
            prompt=prompt,
        )

        self._streams[exchange_id] = stream
        self._session_streams[session_id] = exchange_id

        self._schedule_notification(StreamEvent.STREAM_STARTED, stream)
        return stream

    def register_helper_stream(
        self,
        stream_id: str,
        stream_type: StreamType,
        prompt: str = "",
        session_id: Optional[str] = None,
        backend_name: str = "",
    ) -> Stream:
        """Register a helper stream (compression, summary, etc.).

        Args:
            stream_id: Unique ID for this stream
            stream_type: Type of helper stream
            prompt: Description of what's being done
            session_id: Associated session (if any)
            backend_name: Which backend is handling this

        Returns:
            The created Stream
        """
        stream = Stream(
            stream_id=stream_id,
            stream_type=stream_type,
            status=StreamStatus.STREAMING,
            session_id=session_id,
            backend_name=backend_name,
            prompt=prompt,
        )

        self._streams[stream_id] = stream

        self._schedule_notification(StreamEvent.STREAM_STARTED, stream)
        return stream

    # =========================================================================
    # Stream Updates
    # =========================================================================

    def update_stream(
        self,
        stream_id: str,
        status: Optional[StreamStatus] = None,
        tokens_streamed: Optional[int] = None,
        tool_name: Optional[str] = None,
        tool_count: Optional[int] = None,
        error: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        context_window: Optional[int] = None,
        model: Optional[str] = None,
    ) -> Optional[Stream]:
        """Update a stream's status.

        Args:
            stream_id: Stream to update
            status: New status (if changing)
            tokens_streamed: Updated estimated token count
            tool_name: Currently executing tool name
            tool_count: Updated tool count
            error: Error message (if status is ERROR)
            input_tokens: Actual input token count from API
            output_tokens: Actual output token count from API
            context_window: Model's context window size
            model: Model name

        Returns:
            Updated stream, or None if stream not found
        """
        stream = self._streams.get(stream_id)
        if not stream:
            return None

        # Update fields
        if status is not None:
            stream.status = status
            if status in (StreamStatus.COMPLETED, StreamStatus.ERROR, StreamStatus.CANCELLED):
                stream.finished_at = datetime.now()

        if tokens_streamed is not None:
            stream.tokens_streamed = tokens_streamed
            # Record sample for rate tracking
            stream.add_token_sample(tokens_streamed)

        if tool_name is not None:
            stream.tool_name = tool_name

        if tool_count is not None:
            stream.tool_count = tool_count

        if error is not None:
            stream.error = error

        if input_tokens is not None:
            stream.input_tokens = input_tokens

        if output_tokens is not None:
            stream.output_tokens = output_tokens
            # Also record for rate tracking (actual tokens are better than estimates)
            stream.add_token_sample(output_tokens)

        if context_window is not None:
            stream.context_window = context_window

        if model is not None:
            stream.model = model

        # Schedule appropriate event notification
        if status == StreamStatus.COMPLETED:
            self._schedule_notification(StreamEvent.STREAM_COMPLETED, stream)
        elif status == StreamStatus.ERROR:
            self._schedule_notification(StreamEvent.STREAM_ERROR, stream)
        elif status == StreamStatus.CANCELLED:
            self._schedule_notification(StreamEvent.STREAM_CANCELLED, stream)
        else:
            self._schedule_notification(StreamEvent.STREAM_UPDATED, stream)

        return stream

    def complete_stream(self, stream_id: str) -> Optional[Stream]:
        """Mark a stream as completed.

        Args:
            stream_id: Stream to complete

        Returns:
            Completed stream, or None if not found
        """
        return self.update_stream(stream_id, status=StreamStatus.COMPLETED)

    def fail_stream(self, stream_id: str, error: str) -> Optional[Stream]:
        """Mark a stream as failed.

        Args:
            stream_id: Stream that failed
            error: Error message

        Returns:
            Failed stream, or None if not found
        """
        return self.update_stream(stream_id, status=StreamStatus.ERROR, error=error)

    def cancel_stream(self, stream_id: str) -> Optional[Stream]:
        """Mark a stream as cancelled.

        Args:
            stream_id: Stream to cancel

        Returns:
            Cancelled stream, or None if not found
        """
        return self.update_stream(stream_id, status=StreamStatus.CANCELLED)

    # =========================================================================
    # Query Methods (Sync - just read in-memory state)
    # =========================================================================

    def get_stream(self, stream_id: str) -> Optional[Stream]:
        """Get a stream by ID.

        Args:
            stream_id: Stream ID to look up

        Returns:
            Stream if found, None otherwise
        """
        return self._streams.get(stream_id)

    def get_session_stream(self, session_id: str) -> Optional[Stream]:
        """Get the current active stream for a session.

        Args:
            session_id: Session to look up

        Returns:
            Current stream for session, or None if no active stream
        """
        stream_id = self._session_streams.get(session_id)
        if stream_id:
            stream = self._streams.get(stream_id)
            if stream and stream.is_active:
                return stream
        return None

    def get_all_streams(self) -> list[Stream]:
        """Get all tracked streams (active and recent).

        Returns:
            List of all streams, sorted by start time (newest first)
        """
        return sorted(
            self._streams.values(),
            key=lambda t: t.started_at,
            reverse=True,
        )

    def get_active_streams(self) -> list[Stream]:
        """Get all active streams (pending, streaming, or executing).

        Returns:
            List of active streams
        """
        return [t for t in self._streams.values() if t.is_active]

    def get_streaming_streams(self) -> list[Stream]:
        """Get all streams currently streaming.

        Returns:
            List of streams with STREAMING status
        """
        return [t for t in self._streams.values() if t.status == StreamStatus.STREAMING]

    def get_streams_by_type(self, stream_type: StreamType) -> list[Stream]:
        """Get all streams of a specific type.

        Args:
            stream_type: Type to filter by

        Returns:
            List of matching streams
        """
        return [t for t in self._streams.values() if t.stream_type == stream_type]

    def get_streams_by_session(self, session_id: str) -> list[Stream]:
        """Get all streams for a session (active and completed).

        Args:
            session_id: Session to look up

        Returns:
            List of streams for the session
        """
        return [t for t in self._streams.values() if t.session_id == session_id]

    def get_streams_by_backend(self, backend_name: str) -> list[Stream]:
        """Get all active streams using a specific backend.

        Args:
            backend_name: Backend to filter by

        Returns:
            List of active streams using that backend
        """
        return [
            t for t in self._streams.values()
            if t.backend_name == backend_name and t.is_active
        ]

    # =========================================================================
    # Summary Methods (Sync)
    # =========================================================================

    def get_streaming_count(self) -> int:
        """Get count of streams currently streaming.

        Returns:
            Number of streams with STREAMING status
        """
        return sum(1 for t in self._streams.values() if t.status == StreamStatus.STREAMING)

    def get_active_count(self) -> int:
        """Get count of all active streams.

        Returns:
            Number of active streams (pending, streaming, executing)
        """
        return sum(1 for t in self._streams.values() if t.is_active)

    def get_backend_summary(self) -> dict[str, int]:
        """Get count of active streams per backend.

        Returns:
            Dict of backend_name -> active stream count
        """
        summary = {}
        for stream in self._streams.values():
            if stream.is_active and stream.backend_name:
                summary[stream.backend_name] = summary.get(stream.backend_name, 0) + 1
        return summary

    def get_session_summary(self, session_id: str) -> SessionStreamInfo:
        """Get stream summary for a session.

        Args:
            session_id: Session to summarize

        Returns:
            SessionStreamInfo with current state
        """
        session_streams = self.get_streams_by_session(session_id)
        current_stream = self.get_session_stream(session_id)

        completed_chats = sum(
            1 for t in session_streams
            if t.stream_type == StreamType.CHAT and t.status == StreamStatus.COMPLETED
        )

        last_activity = None
        if session_streams:
            last_activity = max(
                t.finished_at or t.started_at
                for t in session_streams
            )

        backend_name = ""
        if current_stream:
            backend_name = current_stream.backend_name
        elif session_streams:
            # Use most recent stream's backend
            recent = max(session_streams, key=lambda t: t.started_at)
            backend_name = recent.backend_name

        return SessionStreamInfo(
            session_id=session_id,
            backend_name=backend_name,
            is_streaming=current_stream is not None and current_stream.status == StreamStatus.STREAMING,
            current_stream=current_stream,
            total_exchanges=completed_chats,
            last_activity=last_activity,
        )

    # =========================================================================
    # Cleanup
    # =========================================================================

    def clear_completed(self, max_age_seconds: float = 300) -> int:
        """Remove completed streams older than max_age_seconds.

        Args:
            max_age_seconds: Maximum age in seconds to keep completed streams

        Returns:
            Number of streams removed
        """
        now = datetime.now()
        to_remove = []

        for stream_id, stream in self._streams.items():
            if not stream.is_active and stream.finished_at:
                age = (now - stream.finished_at).total_seconds()
                if age > max_age_seconds:
                    to_remove.append(stream_id)

        for stream_id in to_remove:
            del self._streams[stream_id]

        # Also clean up session stream references
        self._session_streams = {
            sid: tid
            for sid, tid in self._session_streams.items()
            if tid in self._streams
        }

        return len(to_remove)

    def clear_all(self) -> None:
        """Clear all stream state. Use for testing or reset."""
        self._streams.clear()
        self._session_streams.clear()


# Convenience function to get the singleton
def get_stream_state() -> StreamState:
    """Get the global StreamState instance."""
    return StreamState()


# =============================================================================
# Backward Compatibility Aliases
# =============================================================================
# These allow existing code to continue working during migration.
# TODO: Remove these after all callers are updated.

TaskStatus = StreamStatus
TaskType = StreamType
Task = Stream
SessionTaskInfo = SessionStreamInfo
TaskEvent = StreamEvent
TaskState = StreamState

def get_task_state() -> StreamState:
    """Backward compatibility alias for get_stream_state()."""
    return get_stream_state()
