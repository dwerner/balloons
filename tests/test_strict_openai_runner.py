from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.runner import SessionRunner
from core.strict_openai_runner import StrictOpenAICompatibleRunner
from session import Session


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


def test_strict_runner_rebuilds_messages_before_each_backend_call(monkeypatch):
    runner = StrictOpenAICompatibleRunner(
        base_url="http://test",
        api_key="test",
        model="test-model",
    )

    rebuilt_snapshots = []

    monkeypatch.setattr(
        runner,
        "build_messages",
        lambda messages, prompt: [
            {"role": "system", "content": "sys v2"},
            {"role": "user", "content": prompt},
        ],
    )

    def fake_package(messages):
        rebuilt_snapshots.append([dict(m) for m in messages])
        return messages

    monkeypatch.setattr(runner._strict_packager, "package", fake_package)

    call_count = {"n": 0}

    async def fake_stream_one_response(openai_messages, tools):
        call_count["n"] += 1
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

    assert len(rebuilt_snapshots) >= 2
    assert rebuilt_snapshots[0][0] == {"role": "system", "content": "sys v2"}
    assert rebuilt_snapshots[1][0] == {"role": "system", "content": "sys v2"}
    assert any(msg.get("role") == "assistant" and msg.get("tool_calls") for msg in rebuilt_snapshots[1])
