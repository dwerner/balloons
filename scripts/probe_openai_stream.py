#!/usr/bin/env python3
"""Stream probe for OpenAI-compatible backends.

Usage:
  python scripts/probe_openai_stream.py --url http://192.168.0.196:8000/v1/chat/completions
"""

from __future__ import annotations

import argparse
import json
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", default="default")
    parser.add_argument("--api-key", default="dummy")
    args = parser.parse_args()

    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": "Say hello in one short sentence."}],
        "stream": True,
        "max_tokens": 32,
    }

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        args.url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {args.api_key}",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=90) as resp:
        print(f"STATUS: {resp.status}")
        for raw_line in resp:
            line = raw_line.decode(errors="replace").rstrip()
            if not line:
                continue
            print(line)


if __name__ == "__main__":
    main()
