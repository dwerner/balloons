#!/usr/bin/env python3
"""
Traffic report for a Balloons .wslog capture.

Answers: where do the bytes go, how slow are RPCs, what is being polled, and
what traffic is redundant.

Usage:
    python tools/wslog/traffic_report.py <capture.wslog> [--top N] [--json]

Sections:
    1. Bandwidth by category   -- bytes per request method / event name
    2. RPC latency             -- p50/p95/max per method
    3. Polling cadence         -- request rate + inter-arrival gaps per method
    4. Redundancy              -- duplicate frames, dual event channels,
                                  event/ack log echo
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict

from wslog import WsLog


def pct(part: float, whole: float) -> float:
    return 100.0 * part / whole if whole else 0.0


def percentile(sorted_vals: list, q: float) -> float:
    if not sorted_vals:
        return 0.0
    return sorted_vals[min(int(q * (len(sorted_vals) - 1)), len(sorted_vals) - 1)]


# --------------------------------------------------------------------------
# 1. bandwidth
# --------------------------------------------------------------------------
def bandwidth(log: WsLog, top: int) -> None:
    total = sum(f.size + 2 for f in log.frames)   # +2 ~ delimiter/framing
    sizes: Counter = Counter()
    counts: Counter = Counter()
    for f in log.frames:
        if f.is_event:
            key = f"event:{f.event}"
        elif f.is_request:
            key = f"req:{f.method}"
        elif f.is_response:
            err = isinstance(f.obj, dict) and "error" in f.obj
            key = "resp:error" if err else "resp:ok"
        else:
            key = "other"
        sizes[key] += f.size + 2
        counts[key] += 1

    print("=== 1. Bandwidth by category ===")
    print(f"{'category':44s} {'bytes':>9} {'%':>6} {'n':>5} {'avg':>6}")
    for key, byt in sizes.most_common(top):
        print(f"{key:44s} {byt:9d} {pct(byt,total):5.1f}% {counts[key]:5d} "
              f"{byt//counts[key]:6d}")
    print(f"{'TOTAL':44s} {total:9d} 100.0% {len(log.frames):5d} "
          f"{total//max(len(log.frames),1):6d}")

    # group into overhead vs payload-ish for a headline number
    overhead = sum(byt for k, byt in sizes.items()
                   if k.startswith("req:DebugLogService") or k.startswith("resp:"))
    print(f"\n  debug-log + RPC-response overhead: {overhead}B "
          f"({pct(overhead,total):.1f}% of capture)")


# --------------------------------------------------------------------------
# 2. latency
# --------------------------------------------------------------------------
def latency(log: WsLog) -> None:
    print("\n=== 2. RPC latency (ms) ===")
    lat = log.latency_by_method()
    if not lat:
        print("  (no matched request/response pairs)")
        return
    print(f"{'method':44s} {'n':>4} {'p50':>8} {'p95':>8} {'max':>8}")
    for method, vals in sorted(lat.items(),
                               key=lambda kv: -statistics.median(kv[1])):
        vals = sorted(vals)
        print(f"{str(method):44s} {len(vals):4d} {percentile(vals,.5):8.2f} "
              f"{percentile(vals,.95):8.2f} {vals[-1]:8.2f}")

    unanswered = [p for p in log.pairs() if p.resp is None]
    if unanswered:
        print(f"\n  unanswered requests: {len(unanswered)}")
        for p in unanswered[:10]:
            note = "  <- last frame; capture stopped before reply" \
                if p.req is log.frames[-1] else ""
            print(f"    +{log.sec(p.req):6.2f}s {p.method}{note}")


# --------------------------------------------------------------------------
# 3. polling cadence
# --------------------------------------------------------------------------
def cadence(log: WsLog) -> None:
    print("\n=== 3. Polling cadence ===")
    by_method: dict = defaultdict(list)
    for f in log.requests():
        by_method[f.method].append(log.sec(f))

    rows = []
    for method, ts in by_method.items():
        ts.sort()
        gaps = [round(b - a, 3) for a, b in zip(ts, ts[1:])]
        span = ts[-1] - ts[0] if len(ts) > 1 else 0.0
        rate = len(ts) / span if span > 0 else float("inf")
        modal = Counter(gaps).most_common(1)[0] if gaps else (None, 0)
        rows.append((rate, method, len(ts), ts[0], ts[-1], modal))

    print(f"{'method':44s} {'n':>4} {'rate/s':>7} {'modal gap':>12}")
    for rate, method, n, first, last, modal in sorted(rows, reverse=True):
        gap = f"{modal[0]}s x{modal[1]}" if modal[0] is not None else "-"
        rate_s = f"{rate:7.1f}" if rate != float("inf") else "      -"
        print(f"{str(method):44s} {n:4d} {rate_s} {gap:>12}")

    # Burst detection: identical requests fired in the same instant. Meaningful
    # only for read-style polling, where N simultaneous identical requests mean
    # N independent pollers with no in-flight coalescing. Write/log traffic
    # (DebugLogService.info) is legitimately bursty, so it is excluded.
    print("\n  same-instant duplicate polls (>2 identical requests within 50ms):")
    found = False
    for method, ts in by_method.items():
        if method in NON_POLLING:
            continue
        ts = sorted(ts)
        bursts, cur = [], ([ts[0]] if ts else [])
        for a, b in zip(ts, ts[1:]):
            if b - a > 0.05:
                bursts.append(cur)
                cur = [b]
            else:
                cur.append(b)
        if cur:
            bursts.append(cur)
        big = [b for b in bursts if len(b) > 2]
        if big:
            found = True
            sizes = Counter(len(b) for b in big)
            print(f"    {method}: {len(big)} bursts, sizes {dict(sizes)} "
                  f"-> likely N independent pollers, no in-flight coalescing")
    if not found:
        print("    none")


# Methods that are writes/logs rather than reads: burstiness is expected, so
# they are excluded from duplicate-poll detection.
NON_POLLING = {"DebugLogService.info"}


# --------------------------------------------------------------------------
# 4. redundancy
# --------------------------------------------------------------------------
# Legacy event names and their sessionData* counterpart, as observed in the
# protocol. Used only to *detect* double delivery; absence is not an error.
DUAL_CHANNELS = {
    "contentDelta": "sessionDataTurnDelta",
    "toolResultDelta": "sessionDataToolResultDelta",
    "toolUse": "sessionDataToolUse",
    "toolResult": "sessionDataToolResult",
    "toolUseStarted": "sessionDataToolUseStarted",
    "toolInputDelta": "sessionDataToolInputDelta",
    "turnStarted": "sessionDataTurnCreated",
    "turnFinished": "sessionDataTurnFinished",
    "streamingStarted": "sessionDataStreamStarted",
    "streamingStopped": "sessionDataStreamDone",
}


def redundancy(log: WsLog) -> None:
    print("=== 4. Redundancy ===")

    # 4a. byte-identical duplicate frames
    ev = log.events()
    seen = Counter(json.dumps(f.obj, sort_keys=True) for f in ev)
    dups = {k: v for k, v in seen.items() if v > 1}
    redundant = sum(v - 1 for v in dups.values())
    print(f"\n  a) duplicate event frames: {len(ev)} events, "
          f"{len(seen)} distinct payloads, {redundant} redundant frames")
    if dups:
        by_name: Counter = Counter()
        for k, v in seen.items():
            if v > 1:
                by_name[json.loads(k)["event"]] += v - 1
        print(f"     redundant frames by event: {dict(by_name.most_common())}")
        worst = max(seen.items(), key=lambda kv: kv[1])
        print(f"     worst repeat: x{worst[1]} "
              f"event={json.loads(worst[0])['event']}")

    # 4b. dual-channel delivery
    names = Counter(f.event for f in ev)
    matched = [(a, b) for a, b in DUAL_CHANNELS.items()
               if names.get(a) and names.get(b)]
    if matched:
        print("\n  b) dual event channels (legacy + sessionData* both delivered):")
        waste = 0
        for legacy, modern in matched:
            la = sum(f.size for f in ev if f.event == legacy)
            ma = sum(f.size for f in ev if f.event == modern)
            n = min(names[legacy], names[modern])
            waste += min(la, ma)
            flag = "" if names[legacy] == names[modern] else \
                f"  !! count mismatch {names[legacy]} vs {names[modern]}"
            print(f"     {legacy:20s} {names[legacy]:4d}  <->  "
                  f"{modern:26s} {names[modern]:4d}{flag}")
        print(f"     ~{waste}B ({pct(waste, sum(f.size for f in log.frames)):.1f}%) "
              f"is the second copy of the same information")

    # 4c. client logging receipt of events it just received
    logs = log.requests("DebugLogService.info")
    if logs:
        lb = sum(f.size for f in logs)
        total = sum(f.size for f in log.frames)
        echoed = Counter()
        for f in logs:
            msg = (f.obj or {}).get("params", {}).get("message", "")
            for name in names:
                if name in msg:
                    echoed[name] += 1
                    break
        print("\n  c) DebugLogService.info: "
              f"{len(logs)} calls, {lb}B ({pct(lb,total):.1f}% of capture)")
        if echoed:
            tot_echo = sum(echoed.values())
            print(f"     {tot_echo} of these log receipt of an event that was "
                  f"just pushed on the socket")
            print(f"     top echoes: {dict(echoed.most_common(5))}")
        print("     each is a full client->server RPC + response for a UI-internal log line")


def as_json(log: WsLog) -> str:
    lat = {m: {"n": len(v), "p50_ms": round(percentile(sorted(v), .5), 3),
               "p95_ms": round(percentile(sorted(v), .95), 3),
               "max_ms": round(max(v), 3)}
           for m, v in log.latency_by_method().items()}
    ev = log.events()
    seen = Counter(json.dumps(f.obj, sort_keys=True) for f in ev)
    return json.dumps({
        "path": log.path,
        "frames": len(log.frames),
        "duration_s": round(log.duration_s, 3),
        "bytes": sum(f.size for f in log.frames),
        "malformed": len(log.malformed),
        "client_methods": dict(Counter(f.method for f in log.requests())),
        "server_events": dict(Counter(f.event for f in ev)),
        "latency": lat,
        "duplicate_event_frames": sum(v - 1 for v in seen.values() if v > 1),
    }, indent=2)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description="Traffic report for a .wslog capture")
    ap.add_argument("capture")
    ap.add_argument("--top", type=int, default=15, help="bandwidth rows to show")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv[1:])

    log = WsLog.load(args.capture)
    if args.json:
        print(as_json(log))
        return 0

    print(log.summary())
    print()
    bandwidth(log, args.top)
    latency(log)
    cadence(log)
    redundancy(log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))