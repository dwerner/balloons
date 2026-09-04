"""Server-side WebSocket traffic capture.

Records raw WebSocket frames (inbound and outbound) to a line-delimited text
file so a workflow can be audited after the fact.

LINE FORMAT (one line per frame, no header, no footer)::

    <utc-iso-datetime>||<origin>||<raw frame verbatim>

    2026-02-11T14:23:05.123456Z||client||{"id":42,"method":"sendMessage","params":{...}}
    2026-02-11T14:23:05.902118Z||server||{"id":42,"result":{"success":true}}

``origin`` is exactly ``client`` (inbound) or ``server`` (outbound). The payload
is written verbatim -- it is never re-encoded, wrapped, or truncated.

PARSING NOTE -- SPLIT ON THE FIRST TWO DELIMITERS ONLY::

    timestamp, origin, payload = line.rstrip("\\n").split("||", 2)

The payload routinely contains ``||`` (this is a coding agent; tool outputs and
file contents full of source code cross this socket). Splitting on every ``||``
corrupts the payload. Neither the timestamp nor the origin token can ever
contain ``||``, so anchoring on the first two delimiters is unambiguous.

Consequently ``awk -F'\\|\\|'`` is *unsafe* here (awk has no maxsplit and splits
on every occurrence). Anchor on the timestamp instead, e.g.::

    sed -E 's/^[0-9T:.Z-]+\\|\\|(client|server)\\|\\|//' capture.wslog | jq -c '.method // .event'

DESIGN -- NO TRUNCATION. Frames are never cut down, so every payload stays
valid, jq-parseable JSON. This socket carries base64 image uploads and
streaming chunks, so captures can grow large; the only bound is ``max_bytes``,
which *stops the capture* (setting ``stop_reason``) rather than mangling any
line. A capture that hits the cap is complete up to that point.

Usage:
    from core.traffic_capture import traffic_capture

    traffic_capture.start(label="checkout-flow")
    traffic_capture.record_inbound(raw_message)
    traffic_capture.record_outbound(raw_message)
    traffic_capture.stop()
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import aiofiles
except ImportError:  # pragma: no cover - aiofiles is a hard dep, degrade gracefully
    aiofiles = None  # type: ignore[assignment]


# Flush the in-memory buffer when either threshold is reached. Batching keeps
# per-frame cost to a list append -- no await on the hot path.
FLUSH_INTERVAL_SECONDS = 1.0
FLUSH_MAX_MESSAGES = 100

# Stop a capture once it exceeds this many bytes. This never truncates a frame;
# it ends the capture so a forgotten toggle cannot fill the disk.
DEFAULT_MAX_BYTES = 200 * 1024 * 1024

# Give up after this many consecutive failed flushes (bad path, disk full).
MAX_CONSECUTIVE_FLUSH_FAILURES = 3

FIELD_DELIMITER = "||"
ORIGIN_CLIENT = "client"
ORIGIN_SERVER = "server"

_LABEL_SAFE = re.compile(r"[^a-z0-9]+")


def _utc_now_stamp() -> str:
    """Sortable UTC timestamp with microseconds, e.g. 2026-02-11T14:23:05.123456Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _filename_stamp(dt: datetime) -> str:
    """Compact timestamp for filenames: 20260211T142305Z."""
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sanitize_label(label: str) -> str:
    """Make a label safe for use in a filename.

    Args:
        label: Free-form label from the caller

    Returns:
        Lowercased, hyphenated, length-capped label (never empty)
    """
    slug = _LABEL_SAFE.sub("-", (label or "").strip().lower()).strip("-")
    return slug[:48] or "capture"


def default_captures_dir() -> Path:
    """Default capture directory, mirroring the XDG logic used for reports.

    Returns:
        Platform-appropriate data directory for captures
    """
    import sys

    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "balloons"
    elif sys.platform == "linux":
        xdg_data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        base = Path(xdg_data) / "balloons"
    else:
        base = Path.home() / "Documents" / "balloons"
    return base / "captures"


def _compact(raw: str) -> str:
    """Collapse a frame to a single line, preserving the one-line invariant.

    This client always sends compact ``JSON.stringify`` output so embedded
    newlines are rare, but a frame containing a raw newline would otherwise
    split into two bogus records.

    Args:
        raw: Raw frame text containing a newline or carriage return

    Returns:
        Single-line version of the frame
    """
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":"))
    except Exception:
        # Not JSON -- escape rather than drop so the line still parses.
        return raw.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")


@dataclass
class CaptureInfo:
    """Snapshot of the current (or most recent) capture."""

    active: bool = False
    path: str = ""
    label: str = ""
    started_at: str = ""
    message_count: int = 0
    bytes_written: int = 0
    stop_reason: str = ""


@dataclass
class _Session:
    """Internal state for an in-progress capture."""

    path: Path
    label: str
    started_at: str
    max_bytes: int
    buffer: list[str] = field(default_factory=list)
    message_count: int = 0
    bytes_written: int = 0
    buffer_bytes: int = 0
    flush_failures: int = 0


class TrafficRecorder:
    """Singleton recorder for raw WebSocket frames.

    Starts inactive on server boot and never auto-resumes. ``start()`` and
    ``stop()`` are idempotent so a UI toggle can never double-open a capture or
    error out on a redundant click.

    When inactive, the only cost to the server is a single boolean check per
    frame -- no parsing, no I/O.
    """

    _instance: "TrafficRecorder | None" = None

    def __new__(cls) -> "TrafficRecorder":
        if cls._instance is None:
            instance = super().__new__(cls)
            cls._instance = instance
            instance._session: _Session | None = None
            instance._draining: _Session | None = None
            instance._flush_task: asyncio.Task | None = None
            instance._flush_inflight: asyncio.Task | None = None
            instance._flush_lock: asyncio.Lock | None = None
            instance._stop_event: asyncio.Event | None = None
            instance._captures_dir: Path | None = None
            instance._last_info: CaptureInfo = CaptureInfo()
        return cls._instance

    # -- configuration -----------------------------------------------------

    def set_captures_dir(self, path: str | Path | None) -> None:
        """Override the directory captures are written to (tests, config)."""
        self._captures_dir = Path(path).expanduser() if path else None

    @property
    def captures_dir(self) -> Path:
        """Directory captures are written to."""
        return self._captures_dir or default_captures_dir()

    # -- state -------------------------------------------------------------

    @property
    def active(self) -> bool:
        """Whether a capture is in progress.

        This is the only thing the hot path touches when capture is off.
        """
        return self._session is not None

    def status(self) -> CaptureInfo:
        """Current capture state, or the last finished one when idle."""
        session = self._session
        if session is None:
            return self._last_info
        return CaptureInfo(
            active=True,
            path=str(session.path),
            label=session.label,
            started_at=session.started_at,
            message_count=session.message_count,
            bytes_written=session.bytes_written,
            stop_reason="",
        )

    # -- control -----------------------------------------------------------

    def start(
        self,
        label: str = "",
        max_bytes: int = 0,
    ) -> tuple[CaptureInfo, bool]:
        """Start capturing, idempotently.

        Calling start() while already recording is a no-op: the existing
        capture keeps running and its file is never reopened or truncated.

        Args:
            label: Workflow name, embedded in the filename (there is no header
                line, so this is the only place the label survives)
            max_bytes: Stop the capture past this size; 0 uses the default

        Returns:
            (info, already_active) -- already_active is True when this call was
            a no-op because a capture was already running
        """
        session = self._session
        if session is not None:
            # Idempotent: report the running capture, touch nothing.
            return self.status(), True

        cap = max_bytes if max_bytes and max_bytes > 0 else DEFAULT_MAX_BYTES
        now = datetime.now(timezone.utc)
        directory = self.captures_dir
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_filename_stamp(now)}-{sanitize_label(label)}.wslog"

        self._session = _Session(
            path=path,
            label=sanitize_label(label),
            started_at=_utc_now_stamp(),
            max_bytes=cap,
        )
        self._draining = None
        self._last_info = CaptureInfo()
        self._start_flusher()

        return self.status(), False

    async def stop(self, reason: str = "stopped") -> tuple[CaptureInfo, bool]:
        """Stop capturing, idempotently, flushing any buffered lines.

        Calling stop() while not recording is a no-op.

        Args:
            reason: Why the capture ended, surfaced in status

        Returns:
            (info, already_inactive) -- already_inactive is True when this call
            was a no-op because nothing was running
        """
        session = self._session
        if session is None:
            return self._last_info, True

        # Clear first so no further frames are appended while we flush.
        self._session = None
        await self._stop_flusher()
        await self._flush(session)

        self._last_info = CaptureInfo(
            active=False,
            path=str(session.path),
            label=session.label,
            started_at=session.started_at,
            message_count=session.message_count,
            bytes_written=session.bytes_written,
            stop_reason=reason,
        )
        return self._last_info, False

    # -- recording ---------------------------------------------------------

    def record_inbound(self, raw: object) -> None:
        """Record a frame received from a client. No-op when inactive."""
        self._record(ORIGIN_CLIENT, raw)

    def record_outbound(self, raw: object) -> None:
        """Record a frame sent to a client. No-op when inactive."""
        self._record(ORIGIN_SERVER, raw)

    def _record(self, origin: str, raw: object) -> None:
        """Append one frame to the buffer. No-op when inactive.

        Deliberately synchronous and allocation-light: this runs on every
        WebSocket frame, including high-rate streaming deltas.
        """
        session = self._session
        if session is None:
            return

        if isinstance(raw, bytes):
            text = raw.decode("utf-8", "replace")
        elif isinstance(raw, str):
            text = raw
        else:
            text = str(raw)

        if "\n" in text or "\r" in text:
            text = _compact(text)

        line = f"{_utc_now_stamp()}{FIELD_DELIMITER}{origin}{FIELD_DELIMITER}{text}\n"
        session.buffer.append(line)
        session.message_count += 1
        # Running total so the size check stays O(1); summing the buffer here
        # would make every streamed delta pay for a scan.
        encoded = len(line) if line.isascii() else len(line.encode("utf-8"))
        session.buffer_bytes += encoded

        if session.bytes_written + session.buffer_bytes >= session.max_bytes:
            # Ends the capture without cutting any frame. The reference is kept
            # so the flush loop can still write out what is already buffered.
            self._session = None
            self._draining = session
            self._last_info = CaptureInfo(
                active=False,
                path=str(session.path),
                label=session.label,
                started_at=session.started_at,
                message_count=session.message_count,
                bytes_written=session.bytes_written,
                stop_reason="max_bytes",
            )
            return

        if len(session.buffer) >= FLUSH_MAX_MESSAGES:
            self._kick_flush()

    # -- flushing ----------------------------------------------------------

    def _start_flusher(self) -> None:
        """Start the periodic flush loop if an event loop is running."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._flush_lock is None:
            self._flush_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = loop.create_task(self._flush_loop())

    def _kick_flush(self) -> None:
        """Schedule an out-of-band flush once a batch threshold is reached."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        inflight = self._flush_inflight
        if inflight is not None and not inflight.done():
            return
        session = self._session
        if session is None:
            return
        self._flush_inflight = loop.create_task(self._flush(session))

    async def _stop_flusher(self) -> None:
        """Signal the flush loop to exit and wait for it to finish.

        Deliberately does NOT cancel the task: cancelling while the loop is
        inside ``await handle.write(...)`` would interrupt a write whose buffer
        was already drained, silently losing frames. Signalling lets the
        current write complete before the loop returns.
        """
        event = self._stop_event
        if event is not None:
            event.set()

        task = self._flush_task
        self._flush_task = None
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
            except Exception:
                pass

        inflight = self._flush_inflight
        self._flush_inflight = None
        if inflight is not None and not inflight.done():
            try:
                await inflight
            except Exception:
                pass

    async def _flush_loop(self) -> None:
        """Periodically flush so a live capture can be tailed with tail -f."""
        event = self._stop_event
        try:
            while event is None or not event.is_set():
                try:
                    # Wakes on the interval, or immediately when stopping.
                    await asyncio.wait_for(
                        event.wait() if event else asyncio.sleep(FLUSH_INTERVAL_SECONDS),
                        timeout=FLUSH_INTERVAL_SECONDS,
                    )
                except asyncio.TimeoutError:
                    pass

                session = self._session
                if session is not None:
                    await self._flush(session)
                    continue

                # No active capture: write out any tail left behind (e.g. by a
                # max_bytes stop) and exit. The loop's lifetime is tied to a
                # single capture -- start() spawns a fresh task and stop event
                # -- so a later capture never inherits a stale stop event.
                await self._flush_last()
                return
        except asyncio.CancelledError:
            pass

    async def _flush_last(self) -> None:
        """Write out the buffer of a session that max_bytes just ended.

        The session object is held in ``_draining`` precisely so its remaining
        buffered lines are not lost when the capture stops mid-stream.
        """
        session = self._draining
        if session is None:
            return
        self._draining = None
        await self._flush(session)

    async def _flush(self, session: _Session) -> None:
        """Append buffered lines to the capture file.

        Opens in append mode per flush (like debug_log) rather than holding a
        file handle, so there is nothing to leak if the server exits abruptly.
        """
        if not session.buffer:
            return

        lock = self._flush_lock
        if lock is None:
            lock = asyncio.Lock()
            self._flush_lock = lock

        async with lock:
            if not session.buffer:
                return
            lines = session.buffer
            session.buffer = []
            session.buffer_bytes = 0
            payload = "".join(lines)

            try:
                if aiofiles is not None:
                    async with aiofiles.open(session.path, "a") as handle:
                        await handle.write(payload)
                else:  # pragma: no cover - fallback
                    with open(session.path, "a", encoding="utf-8") as handle:
                        handle.write(payload)
                session.bytes_written += len(payload.encode("utf-8"))
                session.flush_failures = 0
            except Exception:
                # Never let a write error crash the server (matches debug_log).
                session.flush_failures += 1
                if session.flush_failures >= MAX_CONSECUTIVE_FLUSH_FAILURES:
                    self._abort(session, "write_error")

    def _abort(self, session: _Session, reason: str) -> None:
        """End a capture that can no longer write to disk."""
        if self._session is session:
            self._session = None
        self._last_info = CaptureInfo(
            active=False,
            path=str(session.path),
            label=session.label,
            started_at=session.started_at,
            message_count=session.message_count,
            bytes_written=session.bytes_written,
            stop_reason=reason,
        )


# Module-level singleton, matching the debug_log pattern.
traffic_capture = TrafficRecorder()