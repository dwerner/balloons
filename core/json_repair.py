r"""JSON repair utilities for malformed tool call inputs.

Claude sometimes generates tool calls with improperly escaped JSON,
especially for shell commands containing nested quotes. This module
provides utilities to detect and repair common JSON syntax errors.

Common patterns we repair:
1. Unescaped double quotes inside string values:
   {"command": "ssh host "cmd""}  ->  {"command": "ssh host \"cmd\""}

2. Missing escape sequences:
   {"path": "C:\Users"}  ->  {"path": "C:\\Users"}
"""

import json
import re
from dataclasses import dataclass
from typing import Optional

from core.debug_log import debug_log, Category


@dataclass
class RepairResult:
    """Result of a JSON repair attempt."""
    success: bool
    repaired_json: str
    original_json: str
    repair_description: str = ""
    parsed_value: Optional[dict] = None


def repair_json(malformed: str) -> RepairResult:
    """Attempt to repair malformed JSON.

    Tries multiple repair strategies in order of likelihood.
    Returns the first successful repair, or failure if none work.

    Args:
        malformed: The malformed JSON string

    Returns:
        RepairResult with success status and repaired JSON if successful
    """
    original = malformed.strip()

    # First, try parsing as-is (maybe it's valid)
    try:
        parsed = json.loads(original)
        return RepairResult(
            success=True,
            repaired_json=original,
            original_json=original,
            repair_description="no repair needed",
            parsed_value=parsed,
        )
    except json.JSONDecodeError:
        pass

    # Try each repair strategy
    strategies = [
        _repair_nested_quotes,
        _repair_single_to_double_quotes,
        _repair_unescaped_backslashes,
        _repair_trailing_comma,
    ]

    for strategy in strategies:
        result = strategy(original)
        if result.success:
            debug_log.info(
                f"JSON repair succeeded: {result.repair_description}",
                category=Category.RUNNER,
                details={
                    "original_len": len(original),
                    "repaired_len": len(result.repaired_json),
                },
            )
            return result

    # All strategies failed
    debug_log.warning(
        "JSON repair failed - all strategies exhausted",
        category=Category.RUNNER,
        details={"original_preview": original[:200]},
    )
    return RepairResult(
        success=False,
        repaired_json=original,
        original_json=original,
        repair_description="repair failed",
    )


def _repair_nested_quotes(malformed: str) -> RepairResult:
    """Repair unescaped double quotes inside string values.

    Pattern: {"command": "ssh host "cmd arg""}
    Fixed:   {"command": "ssh host \"cmd arg\""}

    This is the most common Claude error - nested quotes in shell commands.
    """
    # Strategy: Find string values and escape internal quotes
    # This is tricky because we need to identify string boundaries

    result = []
    i = 0
    in_string = False
    string_start = -1
    escape_next = False
    repairs_made = 0

    while i < len(malformed):
        char = malformed[i]

        if escape_next:
            result.append(char)
            escape_next = False
            i += 1
            continue

        if char == '\\':
            result.append(char)
            escape_next = True
            i += 1
            continue

        if char == '"':
            if not in_string:
                # Starting a string
                in_string = True
                string_start = i
                result.append(char)
            else:
                # Potential end of string - look ahead to see if it makes sense
                # A string should end with: ", followed by : , } ] or whitespace
                next_non_ws = _next_non_whitespace(malformed, i + 1)

                if next_non_ws in (':', ',', '}', ']', None):
                    # This is a valid string terminator
                    in_string = False
                    result.append(char)
                else:
                    # This quote is inside the string - escape it
                    result.append('\\"')
                    repairs_made += 1
        else:
            result.append(char)

        i += 1

    if repairs_made == 0:
        return RepairResult(
            success=False,
            repaired_json=malformed,
            original_json=malformed,
            repair_description="no nested quotes found",
        )

    repaired = ''.join(result)

    # Validate the repair
    try:
        parsed = json.loads(repaired)
        return RepairResult(
            success=True,
            repaired_json=repaired,
            original_json=malformed,
            repair_description=f"escaped {repairs_made} nested quote(s)",
            parsed_value=parsed,
        )
    except json.JSONDecodeError:
        return RepairResult(
            success=False,
            repaired_json=malformed,
            original_json=malformed,
            repair_description="nested quote repair didn't produce valid JSON",
        )


def _repair_single_to_double_quotes(malformed: str) -> RepairResult:
    """Convert single-quoted strings to double-quoted.

    Pattern: {'key': 'value'}
    Fixed:   {"key": "value"}
    """
    # Simple replacement - only works for simple cases
    # Be careful not to replace single quotes inside strings

    # This is a heuristic: if the string has more single quotes than double,
    # it might be using Python-style quoting
    if malformed.count("'") <= malformed.count('"'):
        return RepairResult(
            success=False,
            repaired_json=malformed,
            original_json=malformed,
            repair_description="not single-quote style",
        )

    # Try simple replacement
    repaired = malformed.replace("'", '"')

    try:
        parsed = json.loads(repaired)
        return RepairResult(
            success=True,
            repaired_json=repaired,
            original_json=malformed,
            repair_description="converted single quotes to double",
            parsed_value=parsed,
        )
    except json.JSONDecodeError:
        return RepairResult(
            success=False,
            repaired_json=malformed,
            original_json=malformed,
            repair_description="single-quote repair didn't produce valid JSON",
        )


def _repair_unescaped_backslashes(malformed: str) -> RepairResult:
    r"""Escape unescaped backslashes in string values.

    Pattern: {"path": "C:\Users\name"}
    Fixed:   {"path": "C:\\Users\\name"}
    """
    # Find backslashes not followed by valid escape chars
    valid_escapes = set('"\\/bfnrtu')

    result = []
    i = 0
    repairs_made = 0

    while i < len(malformed):
        char = malformed[i]

        if char == '\\' and i + 1 < len(malformed):
            next_char = malformed[i + 1]
            if next_char not in valid_escapes:
                # Unescaped backslash - add another
                result.append('\\\\')
                repairs_made += 1
                i += 1
                continue

        result.append(char)
        i += 1

    if repairs_made == 0:
        return RepairResult(
            success=False,
            repaired_json=malformed,
            original_json=malformed,
            repair_description="no unescaped backslashes found",
        )

    repaired = ''.join(result)

    try:
        parsed = json.loads(repaired)
        return RepairResult(
            success=True,
            repaired_json=repaired,
            original_json=malformed,
            repair_description=f"escaped {repairs_made} backslash(es)",
            parsed_value=parsed,
        )
    except json.JSONDecodeError:
        return RepairResult(
            success=False,
            repaired_json=malformed,
            original_json=malformed,
            repair_description="backslash repair didn't produce valid JSON",
        )


def _repair_trailing_comma(malformed: str) -> RepairResult:
    """Remove trailing commas before } or ].

    Pattern: {"key": "value",}
    Fixed:   {"key": "value"}
    """
    # Remove commas followed by whitespace and closing brackets
    repaired = re.sub(r',(\s*[}\]])', r'\1', malformed)

    if repaired == malformed:
        return RepairResult(
            success=False,
            repaired_json=malformed,
            original_json=malformed,
            repair_description="no trailing commas found",
        )

    try:
        parsed = json.loads(repaired)
        return RepairResult(
            success=True,
            repaired_json=repaired,
            original_json=malformed,
            repair_description="removed trailing comma(s)",
            parsed_value=parsed,
        )
    except json.JSONDecodeError:
        return RepairResult(
            success=False,
            repaired_json=malformed,
            original_json=malformed,
            repair_description="trailing comma repair didn't produce valid JSON",
        )


def _next_non_whitespace(s: str, start: int) -> Optional[str]:
    """Find the next non-whitespace character starting at index.

    Returns the character or None if end of string.
    """
    for i in range(start, len(s)):
        if not s[i].isspace():
            return s[i]
    return None


def repair_tool_input(tool_name: str, raw_input: str) -> RepairResult:
    """Repair a malformed tool input JSON string.

    This is the main entry point for repairing tool call inputs.
    It applies tool-specific heuristics in addition to general JSON repair.

    Args:
        tool_name: Name of the tool (e.g., "Bash", "Read")
        raw_input: The raw JSON input string that failed to parse

    Returns:
        RepairResult with success status and repaired JSON if successful
    """
    debug_log.info(
        f"Attempting to repair {tool_name} tool input",
        category=Category.RUNNER,
        details={"raw_input_len": len(raw_input), "raw_input_preview": raw_input[:100]},
    )

    # For Bash commands, the nested quote issue is most common
    if tool_name == "Bash":
        # Try nested quote repair first
        result = _repair_nested_quotes(raw_input)
        if result.success:
            return result

    # Fall back to general repair
    return repair_json(raw_input)


# Regex to match <tool_use> blocks in text (from context serialization)
TOOL_USE_BLOCK_RE = re.compile(
    r'<tool_use\s+name="([^"]+)"\s+id="([^"]+)">\s*(.*?)\s*</tool_use>',
    re.DOTALL
)


@dataclass
class ParsedToolUse:
    """A parsed tool_use block from context text."""
    name: str
    id: str
    raw_input: str
    input: Optional[dict] = None
    repair_result: Optional[RepairResult] = None

    @property
    def is_valid(self) -> bool:
        """True if input parsed successfully (with or without repair)."""
        return self.input is not None

    @property
    def was_repaired(self) -> bool:
        """True if repair was needed."""
        return (
            self.repair_result is not None
            and self.repair_result.success
            and self.repair_result.repair_description != "no repair needed"
        )


def parse_tool_use_blocks(text: str) -> list[ParsedToolUse]:
    """Parse all <tool_use> blocks from text, repairing malformed JSON.

    This handles tool_use blocks that were serialized to context and may
    have malformed JSON inputs (e.g., unescaped quotes in shell commands).

    Args:
        text: Text that may contain <tool_use> blocks

    Returns:
        List of ParsedToolUse objects, with repair attempted for each
    """
    results = []

    for match in TOOL_USE_BLOCK_RE.finditer(text):
        name = match.group(1)
        tool_id = match.group(2)
        raw_input = match.group(3).strip()

        parsed = ParsedToolUse(name=name, id=tool_id, raw_input=raw_input)

        # Try to parse the JSON input
        try:
            parsed.input = json.loads(raw_input)
        except json.JSONDecodeError:
            # Attempt repair
            repair = repair_tool_input(name, raw_input)
            parsed.repair_result = repair
            if repair.success:
                parsed.input = repair.parsed_value
                debug_log.info(
                    f"Repaired malformed tool_use: {name}",
                    category=Category.RUNNER,
                    details={
                        "tool_id": tool_id,
                        "repair": repair.repair_description,
                    },
                )
            else:
                debug_log.warning(
                    f"Failed to repair malformed tool_use: {name}",
                    category=Category.RUNNER,
                    details={
                        "tool_id": tool_id,
                        "raw_input_preview": raw_input[:200],
                    },
                )

        results.append(parsed)

    return results


def find_malformed_tool_uses(text: str) -> list[ParsedToolUse]:
    """Find <tool_use> blocks with malformed JSON that need repair.

    This is for detecting and reporting malformed tool calls without
    necessarily executing them.

    Args:
        text: Text that may contain <tool_use> blocks

    Returns:
        List of ParsedToolUse objects that had malformed JSON
        (either repaired or failed)
    """
    all_tools = parse_tool_use_blocks(text)
    return [t for t in all_tools if t.repair_result is not None]
