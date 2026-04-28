#!/usr/bin/env python3
"""Live probe for strict OpenAI-compatible backends.

Usage:
  python scripts/probe_openai_strict.py --url http://192.168.0.196:8000/v1/chat/completions --model Mistral-Small-4-119B-UD-Q6_K_XL
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


TOOLS = [{
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Ping tool",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}]


CASES = {
    "tool_cycle_complete": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "ping", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "next"},
    ],
    "tool_cycle_no_closer": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "ping", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"},
        {"role": "user", "content": "next"},
    ],
    "two_assistant_closers": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "ping", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"},
        {"role": "assistant", "content": "[Interrupted: user_cancelled]"},
        {"role": "assistant", "content": "more"},
        {"role": "user", "content": "next"},
    ],
    "assistant_prefill": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ],
}


def post(url: str, model: str, messages: list[dict], api_key: str, max_tokens: int = 8) -> tuple[int | None, str]:
    payload = {"model": model, "messages": messages, "tools": TOOLS, "max_tokens": max_tokens}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return None, f"EXC: {type(e).__name__}: {e}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key", default="dummy")
    args = parser.parse_args()

    for name, messages in CASES.items():
        status, body = post(args.url, args.model, messages, args.api_key)
        print(f"=== {name}: {status} ===")
        print(body[:1200].replace("\n", " "))


if __name__ == "__main__":
    main()
