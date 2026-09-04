"""WebSocket-exposed service for capturing raw WebSocket traffic to disk.

Start a capture, run a workflow, stop the capture, and audit the resulting
line-delimited trace file offline.

Usage (from a web client):
    await client.trafficCapture.startCapture({ label: 'checkout-flow' });
    // ... exercise the workflow ...
    const done = await client.trafficCapture.stopCapture();
    console.log('wrote', done.messageCount, 'frames to', done.path);

Line format is documented in core/traffic_capture.py:

    <utc-iso-datetime>||<client|server>||<raw frame verbatim>

Method names are namespaced (startCapture/stopCapture/captureStatus) because
the dispatcher resolves short method names globally across all services, and a
collision silently routes calls to whichever service registered first.
"""

from dataclasses import dataclass

from codegen import ws_service, ws_expose, ws_type
from core.debug_log import debug_log, Category
from core.traffic_capture import traffic_capture, CaptureInfo


@ws_type
@dataclass
class CaptureStatus:
    """State of the current (or most recently finished) capture."""

    active: bool
    path: str
    label: str
    started_at: str
    message_count: int
    bytes_written: int
    stop_reason: str
    # Set when a start() call was a no-op because a capture was already running.
    already_active: bool = False
    # Set when a stop() call was a no-op because nothing was running.
    already_inactive: bool = False


def _to_status(info: CaptureInfo, already_active: bool = False, already_inactive: bool = False) -> CaptureStatus:
    """Convert core CaptureInfo to the wire DTO."""
    return CaptureStatus(
        active=info.active,
        path=info.path,
        label=info.label,
        started_at=info.started_at,
        message_count=info.message_count,
        bytes_written=info.bytes_written,
        stop_reason=info.stop_reason,
        already_active=already_active,
        already_inactive=already_inactive,
    )


@ws_service
class TrafficCaptureService:
    """WebSocket-exposed controls for raw traffic capture.

    Capture is global (all clients) and idempotent, so a UI toggle reflects and
    drives real server state rather than local assumptions. It starts inactive
    on server boot and never auto-resumes.
    """

    @ws_expose
    async def start_capture(self, label: str = "", max_bytes: int = 0) -> CaptureStatus:
        """Start capturing WebSocket traffic to a file.

        Idempotent: if a capture is already running this returns its state with
        already_active=True and leaves the running capture (and its file)
        untouched.

        Args:
            label: Workflow name, embedded in the capture filename
            max_bytes: Stop the capture past this size; 0 uses the default

        Returns:
            CaptureStatus for the running capture
        """
        info, already_active = traffic_capture.start(label=label, max_bytes=max_bytes)
        if not already_active:
            debug_log.info(
                f"Traffic capture started: {info.path}",
                category=Category.API,
                details={"label": info.label, "path": info.path},
            )
        return _to_status(info, already_active=already_active)

    @ws_expose
    async def stop_capture(self) -> CaptureStatus:
        """Stop capturing and flush buffered frames to disk.

        Idempotent: if nothing is running this returns the last capture's state
        with already_inactive=True.

        Returns:
            CaptureStatus describing the capture that just ended
        """
        info, already_inactive = await traffic_capture.stop()
        if not already_inactive:
            debug_log.info(
                f"Traffic capture stopped: {info.path}",
                category=Category.API,
                details={
                    "path": info.path,
                    "message_count": info.message_count,
                    "bytes_written": info.bytes_written,
                },
            )
        return _to_status(info, already_inactive=already_inactive)

    @ws_expose
    async def capture_status(self) -> CaptureStatus:
        """Get current capture state.

        While active this reports live counts; once stopped it reports the
        final state of the last capture, including why it ended.

        Returns:
            CaptureStatus for the current or most recent capture
        """
        return _to_status(traffic_capture.status())