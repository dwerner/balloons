"""Dedicated tests for core/openai_runner.py.

These were extracted from a code-review repro that traced two areas:

1. build_messages() history normalization, specifically how assistant turns
   that contain ONLY a ThinkingBlock (reasoning, no answer text) are handled.
2. _parse_embedded_tool_calls(), the text fallback that parses tool calls a
   model writes into its prose instead of using native function calling.

Most of these are CHARACTERIZATION tests: they lock in current behavior so a
future change is deliberate rather than accidental. Where the locked behavior
is a known limitation or risk, the docstring says so and notes what to update
if the behavior is intentionally changed.

Note: literal angle-bracket tool-call tags are assembled from LT/GT strings
throughout, to keep this source free of raw markup-looking tag sequences.
"""

import pytest

from models import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)
from core.openai_runner import OpenAICompatibleRunner, _parse_embedded_tool_calls

# Angle brackets assembled at runtime so this file contains no raw markup tags.
LT = "<"
GT = ">"


def xml_tool_call(name, params, close_function=True, close_tool_call=True):
    """Build an embedded XML tool-call string of the form the parser expects:
    tool_call-open, function=open Name close, one or more parameter blocks,
    optional function/tool_call closing tags.
    """
    parts = [f"{LT}tool_call{GT}", f"{LT}function={name}{GT}"]
    for key, value in params.items():
        parts.append(f"{LT}parameter={key}{GT}{value}{LT}/parameter{GT}")
    if close_function:
        parts.append(f"{LT}/function{GT}")
    if close_tool_call:
        parts.append(f"{LT}/tool_call{GT}")
    return "\n".join(parts)


@pytest.fixture
def runner():
    """Runner with no user_prompt; build_messages still adds the balloons system prompt."""
    return OpenAICompatibleRunner(
        base_url="http://test",
        api_key="test",
        model="test-model",
    )


def non_system(messages):
    """Drop the leading system message so assertions focus on turn structure."""
    return [m for m in messages if m.get("role") != "system"]


# ---------------------------------------------------------------------------
# 1. History normalization: thinking-only assistant turns
# ---------------------------------------------------------------------------


class TestThinkingOnlyTurns:
    """A ThinkingBlock matches none of build_messages' isinstance branches, so an
    assistant turn carrying only reasoning contributes no content. These tests pin
    down the consequence: the turn is dropped and adjacent same-role turns merge,
    which keeps strict user/assistant alternation valid (no empty assistant message
    is emitted). The trade-off is that reasoning-only turns vanish from history.
    """

    def test_thinking_only_assistant_between_users_is_dropped_and_users_merge(self, runner):
        history = [
            Message(role="user", content="u1", content_blocks=[TextBlock(text="u1")]),
            Message(role="assistant", content="", content_blocks=[ThinkingBlock(text="deep thought")]),
            Message(role="user", content="u2", content_blocks=[TextBlock(text="u2")]),
        ]
        result = non_system(runner.build_messages(history, "NEW_PROMPT"))

        # The assistant turn disappears entirely; the two user turns and the new
        # prompt collapse into a single user message.
        assert [m["role"] for m in result] == ["user"]
        assert result[0]["content"] == "u1\n\nu2\n\nNEW_PROMPT"

    def test_thinking_plus_text_keeps_text_drops_thinking(self, runner):
        history = [
            Message(role="user", content="u1", content_blocks=[TextBlock(text="u1")]),
            Message(
                role="assistant",
                content="answer",
                content_blocks=[ThinkingBlock(text="deep thought"), TextBlock(text="answer")],
            ),
        ]
        result = non_system(runner.build_messages(history, "NEW_PROMPT"))

        assert [m["role"] for m in result] == ["user", "assistant", "user"]
        assistant = result[1]
        assert assistant["content"] == "answer"
        # Reasoning text must not leak into the resent history.
        assert "deep thought" not in assistant["content"]

    def test_thinking_plus_tool_use_preserves_tool_call_with_null_content(self, runner):
        # History ends with a closing assistant-text turn (the normal shape of a
        # completed agentic turn), so the new prompt is preserved and we can
        # isolate the thinking+tool_use serialization behavior.
        history = [
            Message(role="user", content="u1", content_blocks=[TextBlock(text="u1")]),
            Message(
                role="assistant",
                content="",
                content_blocks=[
                    ThinkingBlock(text="deep thought"),
                    ToolUseBlock(id="t1", name="Read", input={"file_path": "a"}),
                ],
            ),
            Message(role="tool", content="", content_blocks=[ToolResultBlock(tool_use_id="t1", content="ok")]),
            Message(role="assistant", content="done", content_blocks=[TextBlock(text="done")]),
        ]
        result = non_system(runner.build_messages(history, "NEW_PROMPT"))

        roles = [m["role"] for m in result]
        assert roles == ["user", "assistant", "tool", "assistant", "user"]
        assistant = result[1]
        assert assistant.get("tool_calls")
        # Thinking contributes nothing, so content is null (OpenAI requires the key).
        assert assistant["content"] is None
        # The tool result must immediately follow the assistant tool_calls message.
        assert result[2]["role"] == "tool"
        assert result[2]["tool_call_id"] == "t1"
        # New prompt survives when history ends with assistant text.
        assert result[-1]["content"] == "NEW_PROMPT"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "KNOWN BUG: when history ends at a tool result (aborted/cancelled tool "
            "phase, or an ask_user turn), _reorder_tool_messages' look-ahead skips the "
            "trailing user message and the new prompt is silently dropped. "
            "core/openai_runner.py:656-658. This test should xpass once fixed."
        ),
    )
    def test_new_prompt_survives_when_history_ends_at_tool_result(self, runner):
        # Reproduction of the dropped-prompt bug. A completed tool phase with no
        # closing assistant text (e.g. cancelled mid-tool, or ask_user) leaves the
        # history ending on a tool message; the next user prompt must still be sent.
        history = [
            Message(role="user", content="read the file", content_blocks=[TextBlock(text="read the file")]),
            Message(
                role="assistant",
                content="",
                content_blocks=[ToolUseBlock(id="t1", name="Read", input={"file_path": "a"})],
            ),
            Message(role="tool", content="", content_blocks=[ToolResultBlock(tool_use_id="t1", content="data")]),
        ]
        result = non_system(runner.build_messages(history, "NOW SUMMARIZE IT"))

        # The new prompt must appear somewhere in the outbound messages.
        assert any("NOW SUMMARIZE IT" in str(m.get("content")) for m in result)

    def test_thinking_only_assistant_as_last_turn_merges_into_new_prompt(self, runner):
        history = [
            Message(role="user", content="u1", content_blocks=[TextBlock(text="u1")]),
            Message(role="assistant", content="", content_blocks=[ThinkingBlock(text="deep thought")]),
        ]
        result = non_system(runner.build_messages(history, "NEW_PROMPT"))

        assert [m["role"] for m in result] == ["user"]
        assert result[0]["content"] == "u1\n\nNEW_PROMPT"


# ---------------------------------------------------------------------------
# 2. Embedded tool-call parser
# ---------------------------------------------------------------------------


class TestParseEmbeddedToolCalls:
    """The parser only understands the XML form (tool_call / function=Name /
    parameter=k). It does NOT parse the JSON form, even though its own docstring
    claims to and even though the embedded-detector in _stream_one_response
    matches a JSON-in-code-fence pattern. That detector/parser mismatch is the
    root of the known false-positive noise: a planning answer containing a fenced
    json name block trips the detector, the parser returns nothing, and the
    interaction is dumped. These tests lock in that mismatch.
    """

    def test_parses_well_formed_xml_tool_call(self):
        text = xml_tool_call("Read", {"file_path": "/tmp/x"})
        parsed = _parse_embedded_tool_calls(text)

        assert len(parsed) == 1
        assert parsed[0]["name"] == "Read"
        assert parsed[0]["arguments"] == {"file_path": "/tmp/x"}
        assert parsed[0]["id"].startswith("embedded_")

    def test_parses_multiple_xml_tool_calls(self):
        text = (
            xml_tool_call("Read", {"file_path": "/a"})
            + "\n"
            + xml_tool_call("Read", {"file_path": "/b"})
        )
        parsed = _parse_embedded_tool_calls(text)

        assert [c["arguments"]["file_path"] for c in parsed] == ["/a", "/b"]

    def test_parses_xml_without_closing_function_tag(self):
        # Pattern 2 fallback: tool_call-open + function=open + parameters, no
        # closing function/tool_call tags.
        text = xml_tool_call("Edit", {"file_path": "/a"}, close_function=False, close_tool_call=False)
        parsed = _parse_embedded_tool_calls(text)

        assert len(parsed) == 1
        assert parsed[0]["name"] == "Edit"
        assert parsed[0]["arguments"] == {"file_path": "/a"}

    def test_does_not_parse_json_form_documented_but_unimplemented(self):
        # The docstring advertises a JSON form, but there is no code path for it.
        # If JSON parsing is ever implemented, this test should start failing and
        # be updated to assert the parsed result.
        text = 'Plan:\n```json\n{"name": "Read", "arguments": {"file_path": "x"}}\n```\nDone.'
        assert _parse_embedded_tool_calls(text) == []

    def test_returns_empty_for_plain_prose(self):
        assert _parse_embedded_tool_calls("Just a normal sentence about work.") == []

    def test_requires_nonempty_arguments(self):
        # A tool_call with a function name but no parameters yields no call
        # (the parser guards on `if tool_name and arguments`).
        text = f"{LT}tool_call{GT}{LT}function=Read{GT}{LT}/function{GT}{LT}/tool_call{GT}"
        assert _parse_embedded_tool_calls(text) == []

    def test_xml_form_embedded_in_prose_is_actually_executed(self):
        # IMPORTANT / RISK. When the parser DOES match, _stream_one_response turns
        # the result into real ToolUseStart/ToolUse events and the agentic loop
        # executes the tool. So a model that writes a well-formed XML tool call
        # anywhere in its output text -- including inside reasoning, which is
        # folded into the same content buffer -- gets that call executed, even if
        # it was only illustrating a format. This test documents that the parser
        # returns a call for XML embedded in prose; the phantom-execution risk is
        # the reason to gate the detector (e.g. only when content is otherwise
        # empty, or behind a capability flag).
        text = (
            "Here is an example of the format:\n"
            + xml_tool_call("Read", {"file_path": "/etc/hosts"})
            + "\nHope that helps!"
        )
        parsed = _parse_embedded_tool_calls(text)

        assert len(parsed) == 1
        assert parsed[0]["name"] == "Read"
        assert parsed[0]["arguments"] == {"file_path": "/etc/hosts"}