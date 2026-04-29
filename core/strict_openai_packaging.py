"""Strict OpenAI transcript rendering and validation for strict chat templates.

This module renders OpenAI-format messages into the canonical replay shape
required by strict chat templates such as Mistral/llama.cpp Jinja templates,
and validates the final outgoing transcript before send.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STRICT_PLACEHOLDER_ASSISTANT_TEXTS = {
    "[Interrupted: user_cancelled]",
    "[Interrupted: user_cancelled]\n\n[Interrupted: user_cancelled]",
    "[Error: api_error]",
}


class StrictTranscriptValidationError(ValueError):
    """Raised when a strict transcript violates replay or boundary rules."""


@dataclass(frozen=True)
class StrictChatProfile:
    """Rules for a strict OpenAI-compatible chat-template backend."""

    name: str
    requires_tool_cycle_closing_assistant: bool = True
    synthetic_closing_assistant_text: str = ""
    forbid_trailing_assistant_prefill: bool = True


MISTRAL_STRICT_PROFILE = StrictChatProfile(name="mistral_strict")
QWEN3_CODER_PROFILE = StrictChatProfile(name="qwen3_coder_strict")


class StrictOpenAIMessagePackager:
    """Render OpenAI-format messages into canonical strict transcript form."""

    def __init__(self, profile: StrictChatProfile = MISTRAL_STRICT_PROFILE):
        self.profile = profile

    def package(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return a canonical strict transcript.

        Rules:
        - keep optional leading system message
        - fold consecutive user turns together
        - render tool cycles atomically as assistant(tool_calls) -> tool+ -> closer
        - drop orphan tool messages
        - do not emit consecutive assistant turns unless the latter is a tool-call turn
        """
        if not messages:
            return []

        system_msg = None
        idx = 0
        if messages and messages[0].get("role") == "system":
            system_msg = dict(messages[0])
            idx = 1

        canonical: list[dict[str, Any]] = []
        pending_user_parts: list[str] = []
        pending_plain_assistant: dict[str, Any] | None = None

        def flush_user() -> None:
            nonlocal pending_user_parts
            if pending_user_parts:
                canonical.append({"role": "user", "content": "\n\n".join(pending_user_parts)})
                pending_user_parts = []

        def flush_plain_assistant() -> None:
            nonlocal pending_plain_assistant
            if pending_plain_assistant is not None:
                canonical.append(pending_plain_assistant)
                pending_plain_assistant = None

        while idx < len(messages):
            msg = messages[idx]
            role = msg.get("role")

            if role == "user":
                flush_plain_assistant()
                content = msg.get("content")
                if isinstance(content, str) and content:
                    pending_user_parts.append(content)
                elif content == "":
                    pending_user_parts.append("")
                idx += 1
                continue

            if role == "tool":
                idx += 1
                continue

            if role != "assistant":
                idx += 1
                continue

            if msg.get("tool_calls"):
                flush_user()
                pending_plain_assistant = None

                assistant_msg = dict(msg)
                expected_ids = [tc.get("id") for tc in assistant_msg.get("tool_calls", []) if tc.get("id")]
                tool_results: list[dict[str, Any]] = []
                matched_ids: set[str] = set()

                j = idx + 1
                while j < len(messages):
                    candidate = messages[j]
                    if candidate.get("role") == "tool":
                        tc_id = candidate.get("tool_call_id")
                        if tc_id in expected_ids and tc_id not in matched_ids:
                            tool_results.append(dict(candidate))
                            matched_ids.add(tc_id)
                            j += 1
                            continue
                        break
                    if candidate.get("role") == "assistant" and candidate.get("tool_calls"):
                        lookahead = j + 1
                        found_matching_tool = False
                        while lookahead < len(messages) and messages[lookahead].get("role") == "tool":
                            if messages[lookahead].get("tool_call_id") in expected_ids and messages[lookahead].get("tool_call_id") not in matched_ids:
                                tool_results.append(dict(messages[lookahead]))
                                matched_ids.add(messages[lookahead].get("tool_call_id"))
                                found_matching_tool = True
                            lookahead += 1
                        if found_matching_tool:
                            j = lookahead
                            continue
                    break

                for tc_id in expected_ids:
                    if tc_id not in matched_ids:
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": "[Tool result not available]",
                        })

                canonical.append(assistant_msg)
                canonical.extend(tool_results)

                next_msg = messages[j] if j < len(messages) else None

                if next_msg and next_msg.get("role") == "assistant":
                    if next_msg.get("tool_calls"):
                        canonical.append(dict(next_msg))
                        idx = j
                    else:
                        content = next_msg.get("content")
                        canonical.append({
                            "role": "assistant",
                            "content": content if isinstance(content, str) else self.profile.synthetic_closing_assistant_text,
                        })
                        idx = j + 1
                elif self.profile.requires_tool_cycle_closing_assistant:
                    canonical.append({
                        "role": "assistant",
                        "content": self.profile.synthetic_closing_assistant_text,
                    })
                    idx = j
                else:
                    idx = j
                continue

            content = msg.get("content")
            if isinstance(content, str):
                pending_plain_assistant = {"role": "assistant", "content": content}
            idx += 1

        flush_user()
        flush_plain_assistant()

        if system_msg is not None:
            return [system_msg, *canonical]
        return canonical

    def _is_closing_assistant(self, msg: dict[str, Any] | None) -> bool:
        return bool(
            msg
            and msg.get("role") == "assistant"
            and not msg.get("tool_calls")
            and isinstance(msg.get("content"), str)
            and (
                msg.get("content", "") == ""
                or msg.get("content", "").isspace()
                or self._is_placeholder_text(msg.get("content", ""))
            )
        )

    def _is_placeholder_text(self, content: str) -> bool:
        return content.strip() in STRICT_PLACEHOLDER_ASSISTANT_TEXTS


class StrictTranscriptValidator:
    """Validate canonical strict transcripts before backend send."""

    def __init__(self, profile: StrictChatProfile = MISTRAL_STRICT_PROFILE):
        self.profile = profile

    def validate(self, messages: list[dict[str, Any]], *, reasoning_enabled: bool = True) -> None:
        self.validate_replay(messages)
        self.validate_generation_boundary(messages, reasoning_enabled=reasoning_enabled)

    def validate_replay(self, messages: list[dict[str, Any]], *, allow_open_tool_cycle_at_end: bool = False) -> None:
        if not messages:
            raise StrictTranscriptValidationError("Strict transcript cannot be empty.")

        start_idx = 0
        if messages[0].get("role") == "system":
            start_idx = 1

        for i in range(start_idx, len(messages)):
            if messages[i].get("role") == "system":
                raise StrictTranscriptValidationError("System message is only allowed at the start of a strict transcript.")

        if start_idx >= len(messages):
            raise StrictTranscriptValidationError("Strict transcript must contain at least one non-system message.")

        expected_role = "user"
        i = start_idx
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role")

            if role == "user":
                if expected_role != "user":
                    raise StrictTranscriptValidationError("Conversation roles must alternate user and assistant roles.")
                expected_role = "assistant"
                i += 1
                continue

            if role == "assistant" and expected_role == "user" and msg.get("tool_calls"):
                if i != start_idx:
                    raise StrictTranscriptValidationError("Conversation roles must alternate user and assistant roles.")

            elif role != "assistant":
                raise StrictTranscriptValidationError(f"Unexpected role '{role}' in strict transcript.")

            elif expected_role != "assistant":
                raise StrictTranscriptValidationError("Conversation roles must alternate user and assistant roles.")

            if msg.get("tool_calls"):
                tool_calls = msg.get("tool_calls") or []
                expected_ids = [tc.get("id") for tc in tool_calls if tc.get("id")]
                if not expected_ids:
                    raise StrictTranscriptValidationError("Assistant tool-call turn must include at least one tool call id.")

                i += 1
                seen_ids: list[str] = []
                while i < len(messages) and messages[i].get("role") == "tool":
                    tool_msg = messages[i]
                    tc_id = tool_msg.get("tool_call_id")
                    if tc_id not in expected_ids:
                        raise StrictTranscriptValidationError("Tool message does not match the immediately preceding assistant tool calls.")
                    if tc_id in seen_ids:
                        raise StrictTranscriptValidationError("Duplicate tool result for the same tool_call_id in one tool cycle.")
                    seen_ids.append(tc_id)
                    i += 1

                missing_ids = [tc_id for tc_id in expected_ids if tc_id not in seen_ids]
                if missing_ids:
                    raise StrictTranscriptValidationError("Tool cycle is missing one or more tool results.")

                if self.profile.requires_tool_cycle_closing_assistant:
                    if i >= len(messages):
                        if allow_open_tool_cycle_at_end:
                            return
                        raise StrictTranscriptValidationError("Tool cycle must be followed by exactly one assistant followup.")
                    followup_msg = messages[i]
                    if followup_msg.get("role") != "assistant":
                        raise StrictTranscriptValidationError("Tool cycle must be followed by exactly one assistant followup.")
                    if not followup_msg.get("tool_calls") and not isinstance(followup_msg.get("content"), str):
                        if allow_open_tool_cycle_at_end and i == len(messages) - 1:
                            return
                        raise StrictTranscriptValidationError("Tool cycle must be followed by exactly one assistant followup.")
                    i += 1
                    if followup_msg.get("tool_calls"):
                        expected_role = "assistant"
                        continue
                    else:
                        if i < len(messages) and messages[i].get("role") == "assistant" and not messages[i].get("tool_calls"):
                            raise StrictTranscriptValidationError("Tool cycle cannot be followed by multiple plain assistant turns.")
                        expected_role = "user"

                continue

            expected_role = "user"
            i += 1

    def validate_generation_boundary(self, messages: list[dict[str, Any]], *, reasoning_enabled: bool = True) -> None:
        non_system = [m for m in messages if m.get("role") != "system"]
        if not non_system:
            raise StrictTranscriptValidationError("Strict transcript must contain at least one non-system message.")

        last = non_system[-1]
        if last.get("role") == "tool":
            raise StrictTranscriptValidationError("Strict transcript cannot end with a tool message.")

        if last.get("role") == "assistant":
            if self.profile.forbid_trailing_assistant_prefill:
                if reasoning_enabled:
                    raise StrictTranscriptValidationError(
                        "Strict reasoning-enabled replay cannot end with an assistant message; trailing assistant would be interpreted as assistant prefill."
                    )
                raise StrictTranscriptValidationError(
                    "Strict replay cannot end with an assistant message; trailing assistant would be interpreted as assistant prefill."
                )

    def _is_closing_assistant(self, msg: dict[str, Any] | None) -> bool:
        return bool(
            msg
            and msg.get("role") == "assistant"
            and not msg.get("tool_calls")
            and isinstance(msg.get("content"), str)
            and (
                msg.get("content", "") == ""
                or msg.get("content", "").isspace()
                or msg.get("content", "").strip() in STRICT_PLACEHOLDER_ASSISTANT_TEXTS
            )
        )
