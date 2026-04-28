"""Strict OpenAI transcript building for Jinja backends.

This module implements a conservative, profile-driven renderer for
OpenAI-compatible backends whose chat templates validate conversation shape
strictly (for example, Mistral/llama.cpp Jinja templates).

Design goals:
- preserve real user turn boundaries
- keep tool messages immediately after the assistant tool call they answer
- synthesize a closing assistant turn when a strict profile requires one
- provide a clean seam for future profiles (e.g. Qwen3 variants)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STRICT_PLACEHOLDER_ASSISTANT_TEXTS = {
    "[Interrupted: user_cancelled]",
    "[Interrupted: user_cancelled]\n\n[Interrupted: user_cancelled]",
    "[Error: api_error]",
}


@dataclass(frozen=True)
class StrictChatProfile:
    """Rules for a strict OpenAI-compatible chat-template backend."""

    name: str
    requires_tool_cycle_closing_assistant: bool = True
    synthetic_closing_assistant_text: str = ""


MISTRAL_STRICT_PROFILE = StrictChatProfile(name="mistral_strict")
QWEN3_CODER_PROFILE = StrictChatProfile(name="qwen3_coder_strict")


class StrictOpenAIMessagePackager:
    """Render OpenAI-format messages for strict Jinja backends.

    The packager preserves the transcript shape and only performs the
    canonicalization needed for strict backends.
    """
    def __init__(self, profile: StrictChatProfile = MISTRAL_STRICT_PROFILE):
        self.profile = profile

    def package(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return a canonical strict transcript."""
        return self._render_tool_cycles(messages)

    def _render_tool_cycles(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        i = 0

        while i < len(messages):
            msg = messages[i]
            role = msg.get("role")

            if role == "tool":
                # Drop orphan tool results.
                i += 1
                continue

            if role == "assistant" and msg.get("tool_calls"):
                assistant_msg = dict(msg)
                result.append(assistant_msg)

                expected_ids = [tc.get("id") for tc in assistant_msg.get("tool_calls", []) if tc.get("id")]
                matched_ids: set[str] = set()
                j = i + 1
                while j < len(messages) and messages[j].get("role") == "tool":
                    tool_msg = messages[j]
                    tc_id = tool_msg.get("tool_call_id")
                    if tc_id in expected_ids and tc_id not in matched_ids:
                        result.append(dict(tool_msg))
                        matched_ids.add(tc_id)
                    j += 1

                for tc_id in expected_ids:
                    if tc_id not in matched_ids:
                        result.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": "[Tool result not available]",
                        })

                i = j
                continue

            result.append(dict(msg))
            i += 1

        return self._ensure_tool_cycle_closers(result)

    def _ensure_tool_cycle_closers(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.profile.requires_tool_cycle_closing_assistant:
            return messages

        result: list[dict[str, Any]] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            result.append(msg)

            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                j = i + 1
                while j < len(messages) and messages[j].get("role") == "tool":
                    result.append(messages[j])
                    j += 1

                next_msg = messages[j] if j < len(messages) else None
                if not self._is_closing_assistant(next_msg):
                    result.append({
                        "role": "assistant",
                        "content": self.profile.synthetic_closing_assistant_text,
                    })
                i = j
                continue

            i += 1

        return result

    def _merge_adjacent_plain_text_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not messages:
            return messages

        merged: list[dict[str, Any]] = []
        for msg in messages:
            if not merged:
                merged.append(dict(msg))
                continue

            prev = merged[-1]
            if self._can_merge_plain(prev, msg):
                prev_content = prev.get("content") or ""
                next_content = msg.get("content") or ""
                if next_content:
                    prev["content"] = f"{prev_content}\n\n{next_content}" if prev_content else next_content
                continue

            merged.append(dict(msg))

        return merged

    def _can_merge_plain(self, prev: dict[str, Any], msg: dict[str, Any]) -> bool:
        return (
            prev.get("role") == msg.get("role")
            and prev.get("role") in {"user", "assistant"}
            and not prev.get("tool_calls")
            and not msg.get("tool_calls")
            and isinstance(prev.get("content"), str)
            and isinstance(msg.get("content"), str)
            and prev.get("role") != "assistant"
        )

    def _is_closing_assistant(self, msg: dict[str, Any] | None) -> bool:
        return bool(
            msg
            and msg.get("role") == "assistant"
            and not msg.get("tool_calls")
            and isinstance(msg.get("content"), str)
            and (msg.get("content", "") == "" or msg.get("content", "").isspace())
        )
