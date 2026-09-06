#!/usr/bin/env python3
"""
Reconstruct a session timeline from a Balloons .wslog capture.

Prints the structural story of the capture -- submitted message, turns, tool
calls, stream progress, completion -- with polling and debug-log noise filtered
out. Also runs protocol sanity checks and can reassemble streamed content.

Usage:
    python tools/wslog/timeline.py <capture.wslog>            # timeline + checks
    python tools/wslog/timeline.py <capture.wslog> --content  # + reassembled text
    python tools/wslog/timeline.py <capture.wslog> --quiet    # checks only
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict

from wslog import WsLog

# High-volume, low-signal traffic excluded from the narrative timeline.
NOISE_METHODS = {
    "DebugLogService.info",
    "TaskStateService.getTask",
    "TrafficCaptureService.captureStatus",
    "ping",
}
STRUCTURAL_EVENTS = {
    "messageSubmitted", "turnStarted", "turnFinished",
    "toolUseStarted", "toolInputDelta", "toolUse",
    "toolResult", "streamingStarted", "streamingStopped",
    "taskStarted", "taskCompleted",
    "sessionDataStreamStarted", "sessionDataStreamProgress",
    "sessionDataStreamDone", "sessionDataSessionUpdated",
}
SHOW_KEYS = ("turnIndex", "role", "toolName", "status", "isError",
             "tokensStreamed", "currentTokenRate", "contextWindow",
             "outputTokens", "inputTokens", "order")


def timeline(log: WsLog) -> None:
    print("=== session timeline ===")
    for f in log.frames:
        if f.method in NOISE_METHODS:
            continue
        off = log.sec(f)
        if f.is_request:
            extra = ""
            params = (f.obj or {}).get("params", {})
            if "content" in params:
                extra = repr(params["content"])[:70]
            elif "filename" in params:
                extra = str(params["filename"])
            print(f"+{off:6.2f}s {f.dir:6s} CALL {f.method:42s} {extra}")
        elif f.is_event and f.event in STRUCTURAL_EVENTS:
            bits = [f"{k}={f.data[k]}" for k in SHOW_KEYS
                    if k in f.data and f.data[k] not in (None, "", [])]
            print(f"+{off:6.2f}s {f.dir:6s} EVT  {f.event:42s} "
                  f"{' '.join(map(str, bits))[:110]}")


def reassemble(log: WsLog) -> None:
    """Rebuild streamed assistant text and tool output from delta events."""
    print("\n=== reassembled stream content ===")
    text: dict = defaultdict(str)
    for f in log.events("contentDelta"):
        key = (f.data.get("turnIndex"), f.data.get("turnId"))
        text[key] += f.data.get("delta", "")
    for (turn_index, turn_id), body in sorted(text.items(),
                                              key=lambda kv: str(kv[0][0])):
        print(f"\n--- assistant turn {turn_index} "
              f"({turn_id[:8] if turn_id else '?'}, {len(body)} chars) ---")
        print(body)

    tool_out: dict = defaultdict(str)
    streams: dict = {}
    for f in log.events("toolResultDelta"):
        key = f.data.get("toolUseId")
        tool_out[key] += f.data.get("delta", "")
        streams[key] = f.data.get("stream", "?")
    for tool_use_id, body in tool_out.items():
        print(f"\n--- tool result {streams.get(tool_use_id)} "
              f"({str(tool_use_id)[:8]}, {len(body)} chars) ---")
        print(body)

    for f in log.events("toolUse"):
        print(f"\n--- tool call: {f.data.get('toolName')} "
              f"input={f.data.get('toolInput')} ---")


def checks(log: WsLog) -> list:
    """Protocol sanity checks. Returns list of (severity, message)."""
    out = []
    ev = log.events()
    names = Counter(f.event for f in ev)

    # negative token rate
    neg = [f for f in log.events("sessionDataStreamProgress")
           if isinstance(f.data.get("currentTokenRate"), (int, float))
           and f.data["currentTokenRate"] < 0]
    if neg:
        worst = min(f.data["currentTokenRate"] for f in neg)
        out.append(("BUG", f"sessionDataStreamProgress currentTokenRate is "
                    f"negative in {len(neg)}/{names['sessionDataStreamProgress']} "
                    f"frames (worst {worst:.1f} tok/s) -- rate computed against a "
                    f"stale token baseline across turn boundaries"))

    # turn lifecycle
    started = Counter((f.data.get("turnIndex"), f.data.get("role"))
                      for f in log.events("turnStarted"))
    finished = Counter((f.data.get("turnIndex"), f.data.get("role"))
                       for f in log.events("turnFinished"))
    for key, n in sorted(started.items(), key=lambda kv: str(kv[0])):
        if finished.get(key, 0) == 0:
            out.append(("WARN", f"turn {key} started but never finished"))
        elif n > 1:
            out.append(("WARN", f"turnStarted fired {n}x for turn {key}"))

    # token accounting
    for f in log.events("sessionDataStreamDone"):
        if f.data.get("inputTokens") in (0, None) and f.data.get("outputTokens"):
            out.append(("BUG", f"sessionDataStreamDone reports "
                        f"inputTokens={f.data.get('inputTokens')} with "
                        f"outputTokens={f.data.get('outputTokens')}"))

    # dual-channel count mismatch
    pairs = {"turnStarted": "sessionDataTurnCreated",
             "turnFinished": "sessionDataTurnFinished",
             "contentDelta": "sessionDataTurnDelta",
             "toolResultDelta": "sessionDataToolResultDelta"}
    for legacy, modern in pairs.items():
        a, b = names.get(legacy, 0), names.get(modern, 0)
        if a and b and a != b:
            out.append(("WARN", f"dual-channel mismatch: {legacy}={a} but "
                        f"{modern}={b} -- the two buses disagree"))

    # duplicate frames
    seen = Counter(f.raw for f in ev)
    dup = sum(v - 1 for v in seen.values() if v > 1)
    if dup:
        out.append(("INFO", f"{dup} byte-identical duplicate event frames "
                    f"(broadcast without change-detection)"))

    # unanswered requests
    un = [p for p in log.pairs() if p.resp is None]
    un = [p for p in un if p.req is not log.frames[-1]]
    if un:
        out.append(("WARN", f"{len(un)} unanswered request(s): "
                    f"{[p.method for p in un][:5]}"))

    # constant fields worth trimming
    prog = log.events("sessionDataStreamProgress")
    if prog:
        cw = {f.data.get("contextWindow") for f in prog}
        if len(cw) == 1 and None not in cw:
            out.append(("INFO", f"contextWindow={next(iter(cw))} is constant on "
                        f"all {len(prog)} progress frames -- static field on a "
                        f"hot path"))

    print("=== sanity checks ===")
    if not out:
        print("  clean: no anomalies detected")
    for sev, msg in out:
        print(f"  [{sev}] {msg}")
    return out


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description="Session timeline from a .wslog capture")
    ap.add_argument("capture")
    ap.add_argument("--content", action="store_true", help="reassemble streamed text")
    ap.add_argument("--quiet", action="store_true", help="sanity checks only")
    args = ap.parse_args(argv[1:])

    log = WsLog.load(args.capture)
    if not args.quiet:
        timeline(log)
    issues = checks(log)
    if args.content:
        reassemble(log)
    return 1 if any(s == "BUG" for s, _ in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))