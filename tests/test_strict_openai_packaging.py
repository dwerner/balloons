import pytest

from core.strict_openai_packaging import (
    MISTRAL_STRICT_PROFILE,
    StrictOpenAIMessagePackager,
)


@pytest.fixture
def packager():
    return StrictOpenAIMessagePackager(MISTRAL_STRICT_PROFILE)


def test_inserts_closing_assistant_after_tool_cycle_before_user(packager):
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u1"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"},
        {"role": "user", "content": "u2"},
    ]

    result = packager.package(messages)

    assert result == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u1"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "u2"},
    ]


def test_preserves_empty_closing_assistant(packager):
    messages = [
        {"role": "user", "content": "u1"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "[cancelled]"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "u2"},
    ]

    result = packager.package(messages)
    assert result[3] == {"role": "assistant", "content": ""}
    assert result[4] == {"role": "user", "content": "u2"}
    assert len([m for m in result if m.get("role") == "assistant" and not m.get("tool_calls")]) == 1


def test_does_not_merge_across_user_boundary(packager):
    messages = [
        {"role": "user", "content": "u1"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "r1"},
        {"role": "user", "content": "u2"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_2", "type": "function", "function": {"name": "Glob", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_2", "content": "r2"},
        {"role": "user", "content": "u3"},
    ]

    result = packager.package(messages)
    assert [m for m in result if m.get("tool_calls")][0]["tool_calls"][0]["id"] == "call_1"
    assert [m for m in result if m.get("tool_calls")][1]["tool_calls"][0]["id"] == "call_2"


def test_orphan_tool_result_is_dropped(packager):
    messages = [
        {"role": "user", "content": "u1"},
        {"role": "tool", "tool_call_id": "call_1", "content": "orphan"},
        {"role": "user", "content": "u2"},
    ]

    result = packager.package(messages)
    assert result == [
        {"role": "user", "content": "u1"},
        {"role": "user", "content": "u2"},
    ]


def test_adjacent_plain_assistant_messages_remain_separate(packager):
    messages = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "assistant", "content": "a2"},
    ]

    result = packager.package(messages)
    assert result == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "assistant", "content": "a2"},
    ]
