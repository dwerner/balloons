# Balloons WebSocket Traffic Analysis

Tools for analyzing WebSocket traffic captures (`.wslog`) produced by
`TrafficCaptureService`. Use these to answer: **where do the bytes go, how
slow are RPCs, what is being polled, and what traffic is redundant.**

This is the network-layer counterpart to [`tools/profiling/`](../profiling),
which covers CPU/memory. Profiling tells you the UI is slow; wslog tells you
whether the socket is the cause.

## Capture Format

One frame per line, three fields split on `||`:

```
2026-09-06T18:48:21.432230Z||client||{"id":"1469","method":"TaskStateService.getTask","params":{}}
2026-09-06T18:48:21.432430Z||server||{"id": "1469", "result": {...}}
2026-09-06T18:48:33.118012Z||server||{"event": "contentDelta", "data": {...}}
```

**Split on the first two `||` only.** Payloads may legitimately contain `||`
(tool output, code, markdown tables). `str.split("||", 2)` handles this; a
naive `split("||")` will corrupt those lines. The parser does this correctly.

The third field is JSON:

| direction | shape | meaning |
|---|---|---|
| client → server | `{"id","method","params"}` | request |
| server → client | `{"id","result"}` / `{"id","error"}` | response |
| server → client | `{"event","data"}` | server-push event |

Requests and responses correlate on `id`. Note the server pretty-prints JSON
(spaces after `:` and `,`) while the client sends compact JSON — so a request
and its response are never byte-identical even if they shared a payload.

## Capturing Traffic

Captures are written by `TrafficCaptureService` to
`~/.local/share/balloons/captures/<timestamp>-capture.wslog`.

```bash
# list captures, newest first
ls -lt ~/.local/share/balloons/captures/*.wslog | head

# start / stop from a client socket
{"id":"1","method":"TrafficCaptureService.startCapture","params":{"label":"mytest"}}
{"id":"2","method":"TrafficCaptureService.captureStatus","params":{}}
{"id":"3","method":"TrafficCaptureService.stopCapture","params":{}}
```

**Capture what you mean to measure.** A capture is only as good as its
scenario: switch sessions, send a message, run a tool call, stream a long
response. The final `stopCapture` request has no response in the file (the
capture ends before the reply is written) — the tools treat that as expected,
not a bug.

## Scripts

Run from `tools/wslog/` (the scripts import each other by plain module name).

### `wslog.py` — parser + quick summary

The core library. Everything else builds on it.

```bash
python tools/wslog/wslog.py <capture.wslog>
```

Prints frame counts by direction, time window, malformed-line count, client
method histogram, and server event histogram. Start here to see what kind of
session you captured.

### `traffic_report.py` — the main analysis

```bash
python tools/wslog/traffic_report.py <capture.wslog> [--top N] [--json]
```

Four sections:

1. **Bandwidth by category** — bytes per request method and event name, with a
   headline "% of capture is debug-log + RPC-response overhead" number.
2. **RPC latency** — p50/p95/max per method from matched request/response
   pairs, plus any unanswered requests.
3. **Polling cadence** — request rate and modal inter-arrival gap per method,
   and detection of same-instant duplicate polls (N identical requests within
   50 ms = N independent pollers with no in-flight coalescing).
4. **Redundancy** — byte-identical duplicate event frames, dual-channel
   delivery (legacy `x` vs `sessionDataX`), and client log calls that merely
   echo receipt of an event the socket just delivered.

`--json` emits a machine-readable summary for diffing captures or trending.

### `timeline.py` — narrative + sanity checks

```bash
python tools/wslog/timeline.py <capture.wslog>            # timeline + checks
python tools/wslog/timeline.py <capture.wslog> --content  # + reassembled text
python tools/wslog/timeline.py <capture.wslog> --quiet    # checks only
```

Reconstructs the session story (submitted message → turns → tool calls →
stream progress → completion) with polling/log noise filtered out.

`--content` **reassembles streamed assistant text and tool output from the
`contentDelta` / `toolResultDelta` events** — you can read the entire
conversation, including the `ls` output, from the wire frames alone. Useful
for confirming the deltas actually sum to the right content.

Sanity checks flag: negative `currentTokenRate`, `turnStarted` without a
matching `turnFinished`, duplicate `turnStarted` for the same turn,
`sessionDataStreamDone` with `inputTokens=0`, dual-channel count mismatches,
duplicate frames, and unanswered requests.

**Exit code is 1 if any `[BUG]`-severity check fires**, 0 otherwise — so
`timeline.py --quiet` can gate CI or a pre-commit smoke capture.

## Programmatic Use

```python
from wslog import WsLog

log = WsLog.load("~/.local/share/balloons/captures/....wslog")
print(log.summary())

# events of one type, with decoded data
for f in log.events("contentDelta"):
    print(f"{log.sec(f):6.2f}s", f.data["delta"], end="")

# matched request/response latency
for p in log.pairs():
    if p.method == "SessionManagerService.submitMessage":
        print(p.latency_ms)

# biggest frames
for f in sorted(log.frames, key=lambda f: -f.size)[:10]:
    print(f.n, f.dir, f.size, f.raw[:120])
```

`Frame` exposes `.n`, `.t`, `.dir`, `.raw`, `.obj`, `.size`, `.is_event`,
`.event`, `.data`, `.method`, `.msg_id`, `.is_request`, `.is_response`.
`WsLog` exposes `.frames`, `.malformed`, `.start`, `.end`, `.duration_s`,
`.sec(f)`, `.events(name)`, `.requests(method)`, `.pairs()`,
`.latency_by_method()`, `.summary()`.

## How We Read a Report (methodology)

Work top-down; stop when you've found the real cost.

1. **`wslog.py` first.** Confirm the capture is well-formed (0 malformed, 0
   non-JSON) and the window/scenario is what you intended. A capture of an idle
   client proves nothing.
2. **Bandwidth, ranked.** The top 3-4 categories are the whole story. Anything
   under ~2% is not worth optimizing. Ask of each big row: *is this payload, or
   is this overhead?* Payload = the user's actual content. Overhead = polling,
   logging, duplicate delivery, response envelopes.
3. **Latency to rule the network in or out.** Sub-millisecond p50 means a local
   server and the socket is *not* your bottleneck — bandwidth/overhead findings
   still matter for battery and chatty-network clients, but don't chase latency.
   If p95 is high, look for head-of-line blocking behind large frames.
4. **Cadence to separate polling from event-driven traffic.** A steady rate with
   a tight modal gap (e.g. 2.0 s) is a timer. A bursty rate is event-driven.
   Same-instant duplicate polls are always a bug (N components, one endpoint).
5. **Redundancy last**, because it's where the "half the wire is wasted" number
   comes from. Three recurring kinds: byte-identical rebroadcasts, the
   legacy/`sessionData*` dual bus, and log-calls-that-echo-received-events.
6. **`timeline.py --content` to sanity-check correctness**, not just volume: the
   reassembled text should match what the UI showed.

## What to Look For (finding taxonomy)

- **Log traffic as a top bandwidth consumer.** `DebugLogService.info` is a full
  client→server RPC + response per UI-internal log line. When it's the #1 row,
  the fix is: make it a notification (no response), batch client-side, and gate
  behind a debug flag.
- **Dual event channels.** A legacy bus (`contentDelta`, `toolResult`,
  `turnStarted`…) and a `sessionData*` bus carrying the same information. If
  counts match 1:1, one is dead weight. If they *disagree*, that's a correctness
  bug on top of the waste.
- **Heartbeats disguised as state updates.** Many `taskUpdated` frames with few
  distinct payloads = broadcast without change-detection.
- **Static fields on hot paths.** e.g. `contextWindow` repeated on every
  progress frame.
- **Token-rate / token-count accounting bugs.** Negative rates, `inputTokens=0`
  with non-zero output — `timeline.py` flags these.

## Baseline: 2026-09-06 capture

A single "run ls and stop" message, 6 turns, one `Bash` call, 27.8 s, 1543
frames / 352 KB. Latency excellent (p50 0.10 ms, max 6.7 ms). Findings:

| finding | share |
|---|---|
| `DebugLogService.info` (35% debug-log, of which 148 calls just echo received events) | **34.7%** |
| RPC response envelopes | 24.5% |
| `taskUpdated`: 100 frames, 42 distinct (58 byte-identical repeats) | 9.3% |
| dual-channel second copy (`contentDelta`/`sessionDataTurnDelta` etc.) | ~10.8% |
| `getTask`: 101 polls in 22 same-instant bursts of 3 | 3.1% |

~59% of the wire was debug-log + response overhead; combined fixes
(notification-ize + batch logs, retire one event bus, coalesce `taskUpdated`
and duplicate polls) should bring a session like this to roughly a third of its
current bytes.

Bugs surfaced: negative `currentTokenRate` (worst −35.5 tok/s), `turnStarted`
fired 2× for turn 1, turns 2/3 never finish, `sessionDataStreamDone` reports
`inputTokens=0` with `outputTokens=127`, `turnFinished`(4) vs
`sessionDataTurnFinished`(7) mismatch.

## Notes & Gotchas

- **Captures are self-referential.** `captureStatus` polls and the captured
  session's own traffic appear in the same file. Filter `TrafficCaptureService.*`
  when reasoning about application traffic.
- **Pretty vs compact JSON** (see Capture Format) — compare parsed objects, not
  raw strings, when matching a request to its response.
- **`id` is a string** on the wire but sometimes numeric; the parser coerces to
  `str` for pairing.
- **Timestamps are UTC, microsecond, `Z`-suffixed.** Parse with
  `datetime.fromisoformat(s.replace("Z","+00:00"))`.
- Captures live outside the repo (`~/.local/share/balloons/captures/`) and are
  not committed. Don't add `.wslog` files to git.