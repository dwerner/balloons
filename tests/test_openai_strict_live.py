import os
import urllib.error
import urllib.request

import pytest


pytestmark = pytest.mark.integration


MISTRAL_STRICT_URL = os.environ.get("MISTRAL_STRICT_URL", "http://192.168.0.196:8000/v1/chat/completions")
MISTRAL_STRICT_MODEL = os.environ.get("MISTRAL_STRICT_MODEL", "Mistral-Small-4-119B-UD-Q6_K_XL")
MISTRAL_STRICT_API_KEY = os.environ.get("MISTRAL_STRICT_API_KEY", "dummy")


def _post(payload: dict) -> tuple[int | None, str]:
    import json

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        MISTRAL_STRICT_URL,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {MISTRAL_STRICT_API_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return None, f"EXC: {type(e).__name__}: {e}"


def _payload(messages, tools=None, max_tokens=8):
    payload = {"model": MISTRAL_STRICT_MODEL, "messages": messages, "max_tokens": max_tokens}
    if tools is not None:
        payload["tools"] = tools
    return payload


@pytest.mark.integration
def test_mistral_tool_cycle_requires_closing_assistant():
    tools = [{"type": "function", "function": {"name": "ping", "description": "Ping", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}]

    good = _payload([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "ping", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "next"},
    ], tools=tools)

    bad_no_closer = _payload([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "ping", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"},
        {"role": "user", "content": "next"},
    ], tools=tools)

    bad_two_assistants = _payload([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "ping", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"},
        {"role": "assistant", "content": "[Interrupted: user_cancelled]"},
        {"role": "assistant", "content": "more"},
        {"role": "user", "content": "next"},
    ], tools=tools)

    good_status, good_body = _post(good)
    bad_no_closer_status, bad_no_closer_body = _post(bad_no_closer)
    bad_two_assistants_status, bad_two_assistants_body = _post(bad_two_assistants)

    if good_status is None:
        pytest.skip(good_body)
    assert good_status == 200, good_body
    if bad_no_closer_status is None:
        pytest.skip(bad_no_closer_body)
    assert bad_no_closer_status in {400, 500}, bad_no_closer_body
    assert "alternate" in bad_no_closer_body.lower() or "roles" in bad_no_closer_body.lower()
    if bad_two_assistants_status is None:
        pytest.skip(bad_two_assistants_body)
    assert bad_two_assistants_status in {400, 500}, bad_two_assistants_body
    assert "alternate" in bad_two_assistants_body.lower() or "roles" in bad_two_assistants_body.lower()


@pytest.mark.integration
def test_mistral_prefill_with_thinking_rejected_without_override():
    status, body = _post(_payload([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]))

    if status is None:
        pytest.skip(body)
    assert status in {400, 500}
    assert "thinking" in body.lower()
