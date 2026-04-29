from pathlib import Path

import pytest

from core.strict_openai_packaging import StrictTranscriptValidationError
from core.strict_openai_runner import StrictOpenAICompatibleRunner


def test_strict_runner_is_independent_class_definition():
    runner = StrictOpenAICompatibleRunner(
        base_url="http://test",
        api_key="test",
        model="test-model",
    )
    assert runner.__class__.__name__ == "StrictOpenAICompatibleRunner"
    assert runner.__class__.__mro__[1].__name__ != "OpenAICompatibleRunner"


def test_strict_runner_error_text_mentions_debug_dump_path():
    dump_path = "/tmp/strict-interaction.json"
    error_text = f"Detected invalid embedded tool-call markup in content (debug dump: {dump_path})"
    assert dump_path in error_text
    assert "tool-call markup" in error_text


def test_strict_runner_re_raises_stream_error_with_dump_path(monkeypatch):
    runner = StrictOpenAICompatibleRunner(
        base_url="http://test",
        api_key="test",
        model="test-model",
    )

    async def fake_stream_one_response(openai_messages, tools):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "_stream_one_response", fake_stream_one_response)
    monkeypatch.setattr(
        "core.strict_openai_runner._dump_interaction",
        lambda **kwargs: Path("/tmp/strict-built-session.json"),
    )

    async def consume():
        events = []
        async for event in runner.stream_response([], "hello"):
            events.append(event)
        return events

    with pytest.raises(RuntimeError, match=r"boom \(debug dump: /tmp/strict-built-session\.json\)"):
        import asyncio
        asyncio.run(consume())


def test_strict_runner_rejects_trailing_assistant_prefill(monkeypatch):
    runner = StrictOpenAICompatibleRunner(
        base_url="http://test",
        api_key="test",
        model="test-model",
    )

    monkeypatch.setattr(
        runner._strict_packager,
        "package",
        lambda messages: [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "prefill"},
        ],
    )

    with pytest.raises(StrictTranscriptValidationError, match="assistant prefill"):
        runner.build_messages([], "hello")


def test_rebuild_strict_messages_allows_open_tool_cycle_at_end(monkeypatch):
    runner = StrictOpenAICompatibleRunner(
        base_url="http://test",
        api_key="test",
        model="test-model",
    )

    monkeypatch.setattr(
        runner,
        "build_messages",
        lambda messages, prompt: [
            {"role": "system", "content": "sys v2"},
            {"role": "user", "content": prompt},
        ],
    )

    rebuilt = runner._rebuild_strict_messages(
        [],
        "hello",
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ],
    )

    assert rebuilt == [
        {"role": "system", "content": "sys v2"},
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
    ]


def test_rebuild_strict_messages_drops_trailing_closer_for_send_boundary(monkeypatch):
    runner = StrictOpenAICompatibleRunner(
        base_url="http://test",
        api_key="test",
        model="test-model",
    )

    monkeypatch.setattr(
        runner,
        "build_messages",
        lambda messages, prompt: [
            {"role": "system", "content": "sys v2"},
            {"role": "user", "content": prompt},
        ],
    )

    rebuilt = runner._rebuild_strict_messages(
        [],
        "review the codebase",
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
            {"role": "assistant", "content": ""},
        ],
    )

    assert rebuilt == [
        {"role": "system", "content": "sys v2"},
        {"role": "user", "content": "review the codebase"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
    ]


def test_rebuild_strict_messages_stops_live_tail_at_next_user(monkeypatch):
    runner = StrictOpenAICompatibleRunner(
        base_url="http://test",
        api_key="test",
        model="test-model",
    )

    monkeypatch.setattr(
        runner,
        "build_messages",
        lambda messages, prompt: [
            {"role": "system", "content": "sys v2"},
            {"role": "user", "content": prompt},
        ],
    )

    rebuilt = runner._rebuild_strict_messages(
        [],
        "review the codebase",
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "review the codebase"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_2", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_2", "content": "later"},
            {"role": "assistant", "content": ""},
        ],
    )

    assert rebuilt == [
        {"role": "system", "content": "sys v2"},
        {"role": "user", "content": "review the codebase"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
    ]


def test_stream_response_runtime_rebuild_drops_trailing_closer_from_send_boundary(monkeypatch):
    runner = StrictOpenAICompatibleRunner(
        base_url="http://test",
        api_key="test",
        model="test-model",
    )

    captured_requests = []

    async def fake_stream_one_response(openai_messages, tools):
        captured_requests.append([dict(m) for m in openai_messages])
        if len(captured_requests) == 1:
            return {
                "events": [],
                "tool_calls": [{"id": "call_1", "name": "Bash", "arguments": {"command": "echo hi"}}],
                "content": "I'll start by exploring the structure of the codebase to understand what we're working with.",
            }, 1, 1
        return {
            "events": [],
            "tool_calls": [],
            "content": "done",
        }, 1, 1

    async def fake_execute_tool(*args, **kwargs):
        return ("ok", False)

    monkeypatch.setattr(runner, "_stream_one_response", fake_stream_one_response)
    monkeypatch.setattr("core.strict_openai_runner.execute_tool", fake_execute_tool)

    async def consume():
        return [event async for event in runner.stream_response([], "review the codebase")]

    import asyncio
    asyncio.run(consume())

    assert len(captured_requests) >= 2
    second = captured_requests[1]
    assert second[-2]["role"] == "assistant"
    assert second[-2].get("tool_calls")
    assert second[-2]["content"] == "I'll start by exploring the structure of the codebase to understand what we're working with."
    assert second[-1] == {"role": "tool", "tool_call_id": "call_1", "content": "ok"}


def test_strict_runner_rebuilds_messages_before_each_backend_call(monkeypatch):
    runner = StrictOpenAICompatibleRunner(
        base_url="http://test",
        api_key="test",
        model="test-model",
    )

    monkeypatch.setattr(
        runner,
        "build_messages",
        lambda messages, prompt: [
            {"role": "system", "content": "sys v2"},
            {"role": "user", "content": prompt},
        ],
    )

    call_count = {"n": 0}
    captured_requests = []

    async def fake_stream_one_response(openai_messages, tools):
        call_count["n"] += 1
        captured_requests.append([dict(m) for m in openai_messages])
        if call_count["n"] == 1:
            return {
                "events": [],
                "tool_calls": [{"id": "call_1", "name": "Bash", "arguments": {"command": "echo hi"}}],
                "content": "",
            }, 1, 1
        return {
            "events": [],
            "tool_calls": [],
            "content": "done",
        }, 1, 1

    async def fake_execute_tool(*args, **kwargs):
        return ("ok", False)

    monkeypatch.setattr(runner, "_stream_one_response", fake_stream_one_response)
    monkeypatch.setattr("core.strict_openai_runner.execute_tool", fake_execute_tool)

    async def consume():
        return [event async for event in runner.stream_response([], "hello")]

    import asyncio
    asyncio.run(consume())

    assert len(captured_requests) >= 2
    assert captured_requests[0][0] == {"role": "system", "content": "sys v2"}
    assert captured_requests[1][0] == {"role": "system", "content": "sys v2"}
    assert captured_requests[1][-2]["role"] == "assistant"
    assert captured_requests[1][-2].get("tool_calls")
    assert captured_requests[1][-1] == {"role": "tool", "tool_call_id": "call_1", "content": "ok"}
