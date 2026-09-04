"""Tests for the WebSocket traffic recorder.

Focus areas specific to the `datetime||origin||raw` line format:
- exact line shape and timestamp format
- payloads containing `||` survive a maxsplit=2 round-trip
- payloads containing newlines still produce exactly one line
- start/stop idempotency (the UI toggle depends on it)
- max_bytes stops a capture without mangling any line
"""

import asyncio
import json
import re
import socket
from pathlib import Path
from typing import Callable

import pytest
import websockets

from core import traffic_capture as traffic_capture_module
from core.traffic_capture import TrafficRecorder, sanitize_label

TIMESTAMP_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z")


@pytest.fixture
async def recorder(tmp_path, monkeypatch):
    """Isolated recorder writing to a temp dir, with a fast flush interval."""
    instance = TrafficRecorder()
    await instance.stop()
    instance.set_captures_dir(tmp_path)
    monkeypatch.setattr(traffic_capture_module, "FLUSH_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(traffic_capture_module, "FLUSH_MAX_MESSAGES", 1000)
    yield instance
    await instance.stop()
    instance.set_captures_dir(None)


def read_lines(path: str) -> list[str]:
    """Read capture file lines, ignoring any trailing newline."""
    return Path(path).read_text(encoding="utf-8").splitlines()


async def test_inactive_recorder_writes_nothing(recorder):
    assert recorder.active is False

    recorder.record_inbound('{"id":1}')
    recorder.record_outbound('{"id":1,"result":{}}')

    assert recorder.status().message_count == 0
    assert list(Path(recorder.captures_dir).iterdir()) == []


async def test_line_format_is_timestamp_origin_raw(recorder):
    info, already_active = recorder.start(label="checkout")
    assert already_active is False
    assert info.active is True

    recorder.record_inbound('{"id":1,"method":"ping"}')
    recorder.record_outbound('{"id":1,"result":{"pong":true}}')

    final, already_inactive = await recorder.stop()
    assert already_inactive is False
    assert final.active is False

    lines = read_lines(final.path)
    assert len(lines) == 2

    timestamp, origin, payload = lines[0].split("||", 2)
    assert TIMESTAMP_RE.fullmatch(timestamp), timestamp
    assert origin == "client"
    assert payload == '{"id":1,"method":"ping"}'

    _ts, out_origin, out_payload = lines[1].split("||", 2)
    assert out_origin == "server"
    assert json.loads(out_payload) == {"id": 1, "result": {"pong": True}}


async def test_no_header_or_footer_lines(recorder):
    recorder.start(label="audit")
    recorder.record_inbound('{"id":1}')
    final, _ = await recorder.stop()

    lines = read_lines(final.path)
    assert len(lines) == 1
    # Every line must have a valid timestamp first -- no meta rows.
    for line in lines:
        assert TIMESTAMP_RE.fullmatch(line.split("||", 2)[0])


async def test_filename_carries_label(recorder):
    """There is no header line, so the label only survives in the filename."""
    info, _ = recorder.start(label="Checkout Flow #42")
    recorder.record_inbound("{}")
    final, _ = await recorder.stop()

    assert final.path.endswith("-checkout-flow-42.wslog")
    assert Path(final.path).name.startswith("20")
    assert info.label == "checkout-flow-42"


async def test_payload_containing_delimiters_round_trips(recorder):
    """Payloads routinely contain `||`; splitting on the first two is required."""
    payload = json.dumps({"method": "bash", "params": {"cmd": "grep -r 'a || b' . || true"}})
    assert "||" in payload

    recorder.start(label="pipes")
    recorder.record_inbound(payload)
    final, _ = await recorder.stop()

    lines = read_lines(final.path)
    assert len(lines) == 1

    # maxsplit=2 keeps the payload intact.
    _ts, origin, recovered = lines[0].split("||", 2)
    assert origin == "client"
    assert recovered == payload
    assert json.loads(recovered) == json.loads(payload)

    # A naive split on every delimiter would corrupt it.
    assert len(lines[0].split("||")) > 3


async def test_payload_with_newline_stays_one_line(recorder):
    """One frame must never become two records."""
    recorder.start(label="multiline")
    recorder.record_inbound('{"text":"line one\nline two"}')
    final, _ = await recorder.stop()

    lines = read_lines(final.path)
    assert len(lines) == 1

    _ts, origin, payload = lines[0].split("||", 2)
    assert origin == "client"
    # Compacted to valid single-line JSON, so the value survives.
    assert json.loads(payload) == {"text": "line one\nline two"}


async def test_binary_frame_is_decoded(recorder):
    recorder.start(label="binary")
    recorder.record_inbound(b'{"id":1}')
    final, _ = await recorder.stop()

    _ts, origin, payload = read_lines(final.path)[0].split("||", 2)
    assert origin == "client"
    assert payload == '{"id":1}'


async def test_start_is_idempotent_and_does_not_truncate(recorder):
    first, already = recorder.start(label="first")
    assert already is False
    recorder.record_inbound('{"n":1}')

    # Second start must be a no-op: same file, no reopen, no truncation.
    second, already_again = recorder.start(label="second")
    assert already_again is True
    assert second.path == first.path

    recorder.record_inbound('{"n":2}')
    final, _ = await recorder.stop()

    lines = read_lines(final.path)
    assert len(lines) == 2
    assert [line.split("||", 2)[2] for line in lines] == ['{"n":1}', '{"n":2}']
    # The running capture keeps its original label.
    assert final.label == "first"


async def test_stop_is_idempotent(recorder):
    recorder.start(label="once")
    recorder.record_inbound("{}")
    first, already_inactive = await recorder.stop()
    assert already_inactive is False
    assert first.stop_reason == "stopped"

    # Redundant stop reports the last capture without touching the file.
    again, still_inactive = await recorder.stop()
    assert still_inactive is True
    assert again.path == first.path
    assert len(read_lines(first.path)) == 1


async def test_capture_can_be_restarted_after_stop(recorder):
    first, _ = recorder.start(label="one")
    recorder.record_inbound("{}")
    await recorder.stop()

    second, already = recorder.start(label="two")
    assert already is False
    assert second.path != first.path
    recorder.record_inbound('{"n":2}')
    final, _ = await recorder.stop()

    assert len(read_lines(first.path)) == 1
    assert len(read_lines(final.path)) == 1


async def test_status_reports_live_counts(recorder):
    recorder.start(label="live")
    for _ in range(5):
        recorder.record_inbound('{"id":1}')

    status = recorder.status()
    assert status.active is True
    assert status.message_count == 5
    assert status.stop_reason == ""


async def test_max_bytes_stops_without_mangling_lines(recorder):
    """The size cap ends the capture; it never truncates a frame."""
    info, _ = recorder.start(label="big", max_bytes=1000)
    frame = json.dumps({"cmd": "x" * 100})

    for _ in range(100):
        recorder.record_inbound(frame)

    assert recorder.active is False
    status = recorder.status()
    assert status.stop_reason == "max_bytes"
    assert status.message_count < 100

    # Buffered lines from the stopped session still get written out.
    await asyncio.sleep(traffic_capture_module.FLUSH_INTERVAL_SECONDS + 0.2)

    lines = read_lines(status.path)
    assert 0 < len(lines) <= status.message_count
    for line in lines:
        timestamp, origin, payload = line.split("||", 2)
        assert TIMESTAMP_RE.fullmatch(timestamp)
        assert origin == "client"
        # No line was cut down -- every payload is still whole JSON.
        assert json.loads(payload) == json.loads(frame)


async def test_max_bytes_defaults_when_zero(recorder):
    info, _ = recorder.start(label="default-cap", max_bytes=0)
    assert info.active is True
    await recorder.stop()


def test_sanitize_label_never_empty():
    assert sanitize_label("") == "capture"
    assert sanitize_label("///") == "capture"
    assert sanitize_label("  ") == "capture"
    assert sanitize_label("My Flow!!") == "my-flow"
    assert len(sanitize_label("a" * 200)) == 48


def test_singleton_identity():
    assert TrafficRecorder() is TrafficRecorder()

# ---------------------------------------------------------------------------
# End-to-end: real WebSocket connection through the server taps.
#
# The existing ws_server tests call _handle_message() directly, which bypasses
# the taps (they live in the socket loop), so these tests use a real client.
# ---------------------------------------------------------------------------

from codegen.ws_expose import ws_expose, ws_service
from service.ws_server import WsServer


@ws_service
class CaptureProbeService:
    """Minimal service used to generate real request/response traffic."""

    def __init__(self):
        self._event_handlers: list[Callable[[str, dict], None]] = []

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        self._event_handlers.append(handler)

    def emit(self, event_name: str, data: dict) -> None:
        for handler in self._event_handlers:
            handler(event_name, data)

    @ws_expose
    def probe_echo(self, message: str) -> str:
        return f"echo: {message}"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def live_server(tmp_path, monkeypatch):
    """A running WsServer with the probe service, plus a fast flush interval."""
    instance = TrafficRecorder()
    await instance.stop()
    instance.set_captures_dir(tmp_path)
    monkeypatch.setattr(traffic_capture_module, "FLUSH_INTERVAL_SECONDS", 0.05)

    server = WsServer(host="127.0.0.1", port=free_port())
    service = CaptureProbeService()
    server.register_service(service)
    await server.start()

    yield server, service

    await server.stop()
    await instance.stop()
    instance.set_captures_dir(None)


async def test_captures_real_request_and_response(live_server):
    server, _ = live_server
    info, _ = TrafficRecorder().start(label="audit-flow")

    async with websockets.connect(server.url) as ws:
        # First frame is the server's connected event.
        connected = json.loads(await ws.recv())
        assert connected["event"] == "connected"

        await ws.send(json.dumps({"id": "7", "method": "probeEcho", "params": {"message": "hi"}}))
        response = json.loads(await ws.recv())
        assert response["result"] == "echo: hi"

    final, _ = await TrafficRecorder().stop()

    lines = read_lines(final.path)
    assert len(lines) == 3  # connected event, request, response

    parsed = [line.split("||", 2) for line in lines]
    assert [origin for _ts, origin, _p in parsed] == ["server", "client", "server"]

    # The request is stored verbatim and still parses.
    request = json.loads(parsed[1][2])
    assert request["method"] == "probeEcho"

    # The response pairs with the request by JSON-RPC id.
    response_payload = json.loads(parsed[2][2])
    assert response_payload["id"] == request["id"] == "7"


async def test_captures_service_events(live_server):
    """Streaming events go out via _broadcast -- a separate tap from responses."""
    server, service = live_server
    TrafficRecorder().start(label="events")

    async with websockets.connect(server.url) as ws:
        await ws.recv()  # connected event

        service.emit("probeDelta", {"task_id": "t1", "text": "hello"})
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert event["event"] == "probeDelta"

    final, _ = await TrafficRecorder().stop()

    lines = read_lines(final.path)
    # connected event + the emitted event (no client request in this flow).
    assert len(lines) == 2

    emitted = [json.loads(line.split("||", 2)[2]) for line in lines if "probeDelta" in line]
    assert len(emitted) == 1
    assert emitted[0]["event"] == "probeDelta"
    # Keys are camelCased on the wire, and the capture records that verbatim.
    assert emitted[0]["data"] == {"taskId": "t1", "text": "hello"}

    # The event line is outbound, and the payload is stored byte-for-byte as
    # the server sent it -- spaces included, proving it was not re-encoded.
    event_line = next(line for line in lines if "probeDelta" in line)
    assert event_line.split("||", 2)[1] == "server"
    assert (
        event_line.split("||", 2)[2]
        == '{"event": "probeDelta", "data": {"taskId": "t1", "text": "hello"}}'
    )


async def test_no_capture_when_inactive(live_server):
    """The default state must add nothing to the hot path or the disk."""
    server, _ = live_server
    assert TrafficRecorder().active is False

    async with websockets.connect(server.url) as ws:
        await ws.recv()
        await ws.send(json.dumps({"id": "1", "method": "probeEcho", "params": {"message": "x"}}))
        await ws.recv()

    assert list(Path(TrafficRecorder().captures_dir).iterdir()) == []


# ---------------------------------------------------------------------------
# Flush durability: stopping must never drop buffered frames.
# ---------------------------------------------------------------------------

async def test_stop_during_active_flushing_loses_no_frames(recorder, monkeypatch):
    """Regression: cancelling the flush loop mid-write dropped a whole batch.

    With a tiny flush interval the loop is very likely inside a write when
    stop() lands, which is exactly when frames used to be lost.
    """
    monkeypatch.setattr(traffic_capture_module, "FLUSH_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr(traffic_capture_module, "FLUSH_MAX_MESSAGES", 5)

    info, _ = recorder.start(label="durability")
    total = 300
    for i in range(total):
        recorder.record_inbound(json.dumps({"seq": i}))
        if i % 10 == 0:
            await asyncio.sleep(0)  # let flushes actually interleave

    final, _ = await recorder.stop()

    lines = read_lines(final.path)
    assert len(lines) == total, f"lost {total - len(lines)} of {total} frames"
    assert final.message_count == total
    # Order preserved and every payload intact.
    assert [json.loads(l.split("||", 2)[2])["seq"] for l in lines] == list(range(total))


async def test_flush_loop_exits_after_max_bytes_stop(recorder, monkeypatch):
    """Regression: the loop used to spin forever after an auto-stop, so a later
    capture inherited a stale task/stop-event and stop() fell back to cancel."""
    monkeypatch.setattr(traffic_capture_module, "FLUSH_INTERVAL_SECONDS", 0.02)

    recorder.start(label="auto", max_bytes=600)
    for i in range(200):
        recorder.record_inbound(json.dumps({"i": i, "pad": "x" * 50}))
    assert recorder.active is False

    instance = TrafficRecorder()
    await asyncio.sleep(traffic_capture_module.FLUSH_INTERVAL_SECONDS + 0.15)
    task = instance._flush_task
    assert task is None or task.done(), "flush loop outlived the capture"

    # A subsequent capture gets a fresh loop and stops cleanly and promptly.
    second, already = recorder.start(label="second")
    assert already is False
    recorder.record_inbound('{"after":true}')
    final, inactive = await asyncio.wait_for(recorder.stop(), timeout=2.0)
    assert inactive is False
    assert len(read_lines(final.path)) == 1
