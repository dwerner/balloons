import pytest

from core.strict_openai_packaging import (
    MISTRAL_STRICT_PROFILE,
    StrictOpenAIMessagePackager,
    StrictTranscriptValidationError,
    StrictTranscriptValidator,
)


@pytest.fixture
def packager():
    return StrictOpenAIMessagePackager(MISTRAL_STRICT_PROFILE)


@pytest.fixture
def validator():
    return StrictTranscriptValidator(MISTRAL_STRICT_PROFILE)


def test_inserts_closing_assistant_after_tool_cycle_before_user(packager, validator):
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
    validator.validate(result, reasoning_enabled=True)

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


def test_preserves_empty_closing_assistant(packager, validator):
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
    validator.validate(result, reasoning_enabled=True)
    assert result[3] == {"role": "assistant", "content": ""}
    assert result[4] == {"role": "user", "content": "u2"}
    assert len([m for m in result if m.get("role") == "assistant" and not m.get("tool_calls")]) == 1


def test_does_not_merge_across_user_boundary(packager, validator):
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
    validator.validate(result, reasoning_enabled=True)
    assert [m for m in result if m.get("tool_calls")][0]["tool_calls"][0]["id"] == "call_1"
    assert [m for m in result if m.get("tool_calls")][1]["tool_calls"][0]["id"] == "call_2"


def test_orphan_tool_result_is_dropped(packager, validator):
    messages = [
        {"role": "user", "content": "u1"},
        {"role": "tool", "tool_call_id": "call_1", "content": "orphan"},
        {"role": "user", "content": "u2"},
    ]

    result = packager.package(messages)
    validator.validate(result, reasoning_enabled=True)
    assert result == [
        {"role": "user", "content": "u1\n\nu2"},
    ]


def test_preserves_successive_tool_call_followup(packager, validator):
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
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_2", "type": "function", "function": {"name": "Glob", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_2", "content": "r2"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "u2"},
    ]

    result = packager.package(messages)
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in result)
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "call_2" for m in result)
    assert any(m.get("role") == "assistant" and m.get("content") == "done" for m in result)
    validator.validate_replay(result)


def test_validator_rejects_missing_tool_cycle_followup(validator):
    messages = [
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

    with pytest.raises(StrictTranscriptValidationError, match="assistant followup"):
        validator.validate(messages, reasoning_enabled=True)


def test_validator_rejects_two_plain_assistants_after_tool_cycle(validator):
    messages = [
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
        {"role": "assistant", "content": "more"},
        {"role": "user", "content": "u2"},
    ]

    with pytest.raises(StrictTranscriptValidationError, match="multiple plain assistant"):
        validator.validate(messages, reasoning_enabled=True)


def test_validator_allows_successive_tool_call_followup(packager, validator):
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
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_2", "type": "function", "function": {"name": "Glob", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_2", "content": "r2"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "u2"},
    ]

    validator.validate_replay(packager.package(messages))


def test_validator_rejects_orphan_tool(validator):
    messages = [
        {"role": "user", "content": "u1"},
        {"role": "tool", "tool_call_id": "call_1", "content": "orphan"},
        {"role": "user", "content": "u2"},
    ]

    with pytest.raises(StrictTranscriptValidationError, match="Unexpected role 'tool'"):
        validator.validate(messages, reasoning_enabled=True)


def test_validator_rejects_mismatched_tool_id(validator):
    messages = [
        {"role": "user", "content": "u1"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "wrong", "content": "pong"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "u2"},
    ]

    with pytest.raises(StrictTranscriptValidationError, match="does not match"):
        validator.validate(messages, reasoning_enabled=True)


def test_validator_rejects_trailing_assistant_prefill_in_reasoning_mode(validator):
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]

    with pytest.raises(StrictTranscriptValidationError, match="assistant prefill"):
        validator.validate(messages, reasoning_enabled=True)


def test_validator_allows_open_tool_cycle_at_end_with_plain_assistant_tail_for_runtime_boundary(validator):
    messages = [
        {"role": "user", "content": "u1"},
        {
            "role": "assistant",
            "content": "I will inspect the repository.",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"},
        {"role": "assistant", "content": "I found the top-level files."},
    ]

    validator.validate_replay(messages, allow_open_tool_cycle_at_end=True)


    messages = [
        {"role": "assistant",
         "content": None,
         "tool_calls": [
             {"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}
         ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"},
        {"role": "assistant", "content": ""},
    ]

    validator.validate_replay(messages, allow_open_tool_cycle_at_end=True)


    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"},
    ]

    with pytest.raises(StrictTranscriptValidationError):
        validator.validate_generation_boundary(messages, reasoning_enabled=True)
