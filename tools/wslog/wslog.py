#!/usr/bin/env python3
"""
Parse Balloons WebSocket traffic captures (.wslog).

Capture format (one frame per line):

    datetime||<client|server>||raw-frame

Split on the FIRST TWO '||' delimiters only -- the payload may itself contain
'||'. The raw-frame is normally a JSON object:
  * client -> server : {"id": ..., "method": ..., "params": {...}}   (request)
  * server -> client : {"id": ..., "result"|"error": ...}            (response)
  * server -> client : {"event": ..., "data": {...}}                 (push event)

Captures are written by TrafficCaptureService and stored under
~/.local/share/balloons/captures/*.wslog

Usage (quick summary):
    python tools/wslog/wslog.py <capture.wslog>

Programmatic use:
    from wslog import WsLog
    log = WsLog.load('capture.wslog')
    print(log.summary())
    for ev in log.events('contentDelta'):
        print(ev.t, ev.data['delta'])
    for req, resp in log.pairs():
        print(req.method, resp.latency_ms)
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

DELIM = "||"


def parse_ts(s: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp (trailing 'Z') into an aware datetime."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass
class Frame:
    """A single captured WebSocket frame."""
    n: int                      # 1-based line number in the file
    t: datetime                 # frame timestamp (UTC)
    dir: str                    # 'client' | 'server'
    raw: str                    # raw-frame payload (pre-JSON)
    obj: Optional[dict]         # parsed JSON, or None if not valid JSON

    # ---- convenience accessors ----
    @property
    def size(self) -> int:
        return len(self.raw)

    @property
    def is_event(self) -> bool:
        return isinstance(self.obj, dict) and "event" in self.obj

    @property
    def event(self) -> Optional[str]:
        return self.obj.get("event") if self.is_event else None

    @property
    def data(self) -> dict:
        return (self.obj or {}).get("data", {}) if isinstance(self.obj, dict) else {}

    @property
    def method(self) -> Optional[str]:
        return self.obj.get("method") if isinstance(self.obj, dict) else None

    @property
    def msg_id(self) -> Optional[str]:
        o = self.obj or {}
        return str(o["id"]) if isinstance(o, dict) and "id" in o else None

    @property
    def is_request(self) -> bool:
        return isinstance(self.obj, dict) and "method" in self.obj and "id" in self.obj

    @property
    def is_response(self) -> bool:
        return (
            isinstance(self.obj, dict)
            and "id" in self.obj
            and ("result" in self.obj or "error" in self.obj)
        )


@dataclass
class Pair:
    """A matched request/response pair with computed latency."""
    req: Frame
    resp: Optional[Frame]

    @property
    def method(self) -> Optional[str]:
        return self.req.method

    @property
    def latency_ms(self) -> Optional[float]:
        if self.resp is None:
            return None
        return (self.resp.t - self.req.t).total_seconds() * 1000.0


@dataclass
class WsLog:
    """A parsed .wslog capture with indexing helpers."""
    path: str
    frames: list = field(default_factory=list)
    malformed: list = field(default_factory=list)   # (lineno, reason, preview)

    # ---- loading ----
    @classmethod
    def load(cls, path: str | Path) -> "WsLog":
        path = str(path)
        log = cls(path=path)
        with open(path, encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f, 1):
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                parts = line.split(DELIM, 2)          # split on first two only
                if len(parts) != 3:
                    log.malformed.append((n, "expected 2 delimiters", line[:120]))
                    continue
                ts, direction, raw = parts
                if direction not in ("client", "server"):
                    log.malformed.append((n, f"bad direction {direction!r}", line[:120]))
                    continue
                try:
                    t = parse_ts(ts)
                except ValueError:
                    log.malformed.append((n, f"bad timestamp {ts!r}", line[:120]))
                    continue
                try:
                    obj = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    obj = None
                log.frames.append(Frame(n=n, t=t, dir=direction, raw=raw, obj=obj))
        return log

    # ---- basic properties ----
    def __len__(self) -> int:
        return len(self.frames)

    @property
    def start(self) -> Optional[datetime]:
        return self.frames[0].t if self.frames else None

    @property
    def end(self) -> Optional[datetime]:
        return self.frames[-1].t if self.frames else None

    @property
    def duration_s(self) -> float:
        if len(self.frames) < 2:
            return 0.0
        return (self.end - self.start).total_seconds()

    def sec(self, frame: Frame) -> float:
        """Seconds since capture start for a frame."""
        return (frame.t - self.start).total_seconds()

    # ---- filtering ----
    def client(self) -> Iterator[Frame]:
        return (f for f in self.frames if f.dir == "client")

    def server(self) -> Iterator[Frame]:
        return (f for f in self.frames if f.dir == "server")

    def events(self, name: Optional[str] = None) -> list:
        return [f for f in self.frames
                if f.is_event and (name is None or f.event == name)]

    def requests(self, method: Optional[str] = None) -> list:
        return [f for f in self.client()
                if f.is_request and (method is None or f.method == method)]

    # ---- request/response pairing ----
    def pairs(self) -> list:
        """Match each client request to the first later server response with
        the same id. Returns list[Pair] in request order (FIFO per id)."""
        pending: dict = defaultdict(list)
        out: list = []
        index: dict = {}
        for f in self.frames:
            if f.dir == "client" and f.is_request:
                p = Pair(req=f, resp=None)
                pending[f.msg_id].append(p)
                out.append(p)
                index[id(p)] = f
            elif f.dir == "server" and f.is_response and pending.get(f.msg_id):
                pending[f.msg_id].pop(0).resp = f
        return out

    def latency_by_method(self) -> dict:
        """method -> list of latency_ms (only matched pairs)."""
        out: dict = defaultdict(list)
        for p in self.pairs():
            ms = p.latency_ms
            if ms is not None:
                out[p.method].append(ms)
        return dict(out)

    # ---- reporting ----
    def summary(self) -> str:
        lines = []
        lines.append(f"capture: {self.path}")
        lines.append(f"frames : {len(self.frames)}  "
                     f"(client {sum(1 for f in self.frames if f.dir=='client')}, "
                     f"server {sum(1 for f in self.frames if f.dir=='server')})")
        if self.frames:
            lines.append(f"window : {self.start:%H:%M:%S} -> {self.end:%H:%M:%S} "
                         f"({self.duration_s:.1f}s)")
        if self.malformed:
            lines.append(f"malformed: {len(self.malformed)} line(s)")
        bad_json = sum(1 for f in self.frames if f.obj is None)
        if bad_json:
            lines.append(f"non-JSON frames: {bad_json}")
        cm = Counter(f.method for f in self.requests())
        ev = Counter(f.event for f in self.events())
        lines.append(f"client methods ({sum(cm.values())}):")
        for k, v in cm.most_common():
            lines.append(f"    {v:5d}  {k}")
        lines.append(f"server events ({sum(ev.values())}):")
        for k, v in ev.most_common():
            lines.append(f"    {v:5d}  {k}")
        return "\n".join(lines)


def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    log = WsLog.load(argv[1])
    print(log.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))