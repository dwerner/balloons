"""Streaming JSON parser for partial/incomplete JSON.

This module provides a parser that can handle incomplete JSON as it streams in,
making partial data available as early as possible while maintaining correctness.

Key features:
- Tracks raw buffer of received bytes
- Parses partial objects/arrays, returning complete fields
- Handles unterminated strings by omitting that field until it completes
- Gracefully handles missing closing delimiters

Usage:
    parser = StreamingJsonParser()

    # Feed chunks as they arrive
    parser.feed('{"name": "Al')
    parser.get_partial()  # Returns {} - string not complete

    parser.feed('ice", "age": 30')
    parser.get_partial()  # Returns {"name": "Alice", "age": 30}

    parser.feed('}')
    parser.get_partial()  # Returns {"name": "Alice", "age": 30}
    parser.is_complete()  # Returns True
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional
import json


class TokenType(Enum):
    """Token types for JSON lexing."""
    LBRACE = auto()      # {
    RBRACE = auto()      # }
    LBRACKET = auto()    # [
    RBRACKET = auto()    # ]
    COLON = auto()       # :
    COMMA = auto()       # ,
    STRING = auto()      # "..."
    NUMBER = auto()      # 123, -45.6, 1e10
    TRUE = auto()        # true
    FALSE = auto()       # false
    NULL = auto()        # null
    INCOMPLETE = auto()  # Partial token (unterminated string, etc.)
    EOF = auto()         # End of input


@dataclass
class Token:
    """A JSON token."""
    type: TokenType
    value: Any
    start: int  # Start position in buffer
    end: int    # End position in buffer (exclusive)


class StreamingJsonParser:
    """Parses streaming/partial JSON, extracting complete values.

    The parser maintains a buffer of raw input and extracts as much valid
    data as possible at any point. Incomplete strings or values are omitted
    from the result until they complete.

    The parser is designed to be fed chunks incrementally and queried for
    the current partial parse result at any time.
    """

    def __init__(self):
        self._buffer: str = ""
        self._cached_result: Optional[Any] = None
        self._cache_valid: bool = False

    def feed(self, chunk: str) -> None:
        """Add more data to the buffer.

        Args:
            chunk: New JSON text to append
        """
        self._buffer += chunk
        self._cache_valid = False

    def get_buffer(self) -> str:
        """Return the raw accumulated buffer."""
        return self._buffer

    def clear(self) -> None:
        """Clear the buffer and reset state."""
        self._buffer = ""
        self._cached_result = None
        self._cache_valid = False

    def get_partial(self) -> Any:
        """Parse and return the partial result.

        Returns whatever complete data can be extracted from the current
        buffer. Incomplete strings/values are omitted.

        Returns:
            The partial parse result (dict, list, or primitive)
            Returns None if buffer is empty or no valid data yet
        """
        if self._cache_valid:
            return self._cached_result

        if not self._buffer.strip():
            return None

        result = self._parse_value(0)
        if result is not None:
            self._cached_result = result[0]
        else:
            self._cached_result = None
        self._cache_valid = True
        return self._cached_result

    def is_complete(self) -> bool:
        """Check if the JSON is syntactically complete.

        Returns:
            True if the buffer contains complete, valid JSON
        """
        try:
            json.loads(self._buffer)
            return True
        except json.JSONDecodeError:
            return False

    def _skip_whitespace(self, pos: int) -> int:
        """Skip whitespace characters starting at pos."""
        while pos < len(self._buffer) and self._buffer[pos] in ' \t\n\r':
            pos += 1
        return pos

    def _parse_value(self, pos: int) -> Optional[tuple[Any, int]]:
        """Parse a JSON value starting at pos.

        Returns:
            Tuple of (value, end_position) or None if incomplete
        """
        pos = self._skip_whitespace(pos)
        if pos >= len(self._buffer):
            return None

        char = self._buffer[pos]

        if char == '{':
            return self._parse_object(pos)
        elif char == '[':
            return self._parse_array(pos)
        elif char == '"':
            return self._parse_string(pos)
        elif char == 't':
            return self._parse_literal(pos, 'true', True)
        elif char == 'f':
            return self._parse_literal(pos, 'false', False)
        elif char == 'n':
            return self._parse_literal(pos, 'null', None)
        elif char == '-' or char.isdigit():
            return self._parse_number(pos)
        else:
            # Invalid character
            return None

    def _parse_object(self, pos: int) -> Optional[tuple[dict, int]]:
        """Parse a JSON object starting at pos.

        Returns complete key-value pairs, omitting pairs where the
        value is incomplete.
        """
        if self._buffer[pos] != '{':
            return None
        pos += 1

        result = {}

        while True:
            pos = self._skip_whitespace(pos)
            if pos >= len(self._buffer):
                # Incomplete - return what we have
                return (result, pos)

            char = self._buffer[pos]

            if char == '}':
                return (result, pos + 1)

            if char == ',':
                pos += 1
                continue

            # Expect a key (string)
            if char != '"':
                # Invalid or incomplete
                return (result, pos)

            key_result = self._parse_string(pos)
            if key_result is None:
                # Key string incomplete - return what we have
                return (result, pos)

            key, pos = key_result

            # Expect colon
            pos = self._skip_whitespace(pos)
            if pos >= len(self._buffer):
                return (result, pos)

            if self._buffer[pos] != ':':
                return (result, pos)
            pos += 1

            # Parse value
            pos = self._skip_whitespace(pos)
            value_result = self._parse_value(pos)

            if value_result is None:
                # Value incomplete - don't include this key
                return (result, pos)

            value, pos = value_result
            result[key] = value

    def _parse_array(self, pos: int) -> Optional[tuple[list, int]]:
        """Parse a JSON array starting at pos.

        Returns complete elements, stopping when an incomplete element
        is encountered.
        """
        if self._buffer[pos] != '[':
            return None
        pos += 1

        result = []

        while True:
            pos = self._skip_whitespace(pos)
            if pos >= len(self._buffer):
                return (result, pos)

            char = self._buffer[pos]

            if char == ']':
                return (result, pos + 1)

            if char == ',':
                pos += 1
                continue

            # Parse element
            elem_result = self._parse_value(pos)
            if elem_result is None:
                # Element incomplete - return what we have
                return (result, pos)

            elem, pos = elem_result
            result.append(elem)

    def _parse_string(self, pos: int) -> Optional[tuple[str, int]]:
        """Parse a JSON string starting at pos.

        Returns None if the string is unterminated.
        """
        if self._buffer[pos] != '"':
            return None
        pos += 1

        result = []

        while pos < len(self._buffer):
            char = self._buffer[pos]

            if char == '"':
                return (''.join(result), pos + 1)

            if char == '\\':
                # Escape sequence
                if pos + 1 >= len(self._buffer):
                    return None  # Incomplete escape

                next_char = self._buffer[pos + 1]

                if next_char == 'u':
                    # Unicode escape: \uXXXX
                    if pos + 5 >= len(self._buffer):
                        return None  # Incomplete unicode escape

                    hex_digits = self._buffer[pos + 2:pos + 6]
                    try:
                        code_point = int(hex_digits, 16)
                        result.append(chr(code_point))
                        pos += 6
                    except ValueError:
                        # Invalid hex - treat as literal
                        result.append('\\')
                        result.append('u')
                        pos += 2
                else:
                    escape_map = {
                        '"': '"',
                        '\\': '\\',
                        '/': '/',
                        'b': '\b',
                        'f': '\f',
                        'n': '\n',
                        'r': '\r',
                        't': '\t',
                    }
                    if next_char in escape_map:
                        result.append(escape_map[next_char])
                    else:
                        # Unknown escape - keep as-is
                        result.append('\\')
                        result.append(next_char)
                    pos += 2
            else:
                result.append(char)
                pos += 1

        # Reached end of buffer without closing quote
        return None

    def _parse_number(self, pos: int, allow_at_eof: bool = True) -> Optional[tuple[float | int, int]]:
        """Parse a JSON number starting at pos.

        Numbers are tricky with streaming because we don't know when they
        end. We typically need to see a delimiter (whitespace, comma, bracket, etc.)
        to know the number is complete.

        Args:
            pos: Position to start parsing
            allow_at_eof: If True, accept numbers at end of buffer as complete.
                          This is useful for streaming where we want to show
                          numbers as soon as they look syntactically complete.
        """
        start = pos

        # Optional minus
        if pos < len(self._buffer) and self._buffer[pos] == '-':
            pos += 1

        if pos >= len(self._buffer):
            return None

        # Integer part
        if self._buffer[pos] == '0':
            pos += 1
        elif self._buffer[pos].isdigit():
            while pos < len(self._buffer) and self._buffer[pos].isdigit():
                pos += 1
        else:
            return None

        # Fractional part
        if pos < len(self._buffer) and self._buffer[pos] == '.':
            pos += 1
            if pos >= len(self._buffer):
                return None  # Incomplete decimal
            if not self._buffer[pos].isdigit():
                return None  # Invalid
            while pos < len(self._buffer) and self._buffer[pos].isdigit():
                pos += 1

        # Exponent part
        if pos < len(self._buffer) and self._buffer[pos] in 'eE':
            pos += 1
            if pos >= len(self._buffer):
                return None  # Incomplete exponent
            if self._buffer[pos] in '+-':
                pos += 1
            if pos >= len(self._buffer):
                return None  # Incomplete exponent
            if not self._buffer[pos].isdigit():
                return None  # Invalid
            while pos < len(self._buffer) and self._buffer[pos].isdigit():
                pos += 1

        # Check if we've reached a delimiter or end of buffer
        if pos < len(self._buffer):
            if self._buffer[pos] not in ' \t\n\r,}]':
                # More characters coming - might not be complete
                return None
        else:
            # At end of buffer - number might continue
            # If allow_at_eof is True, we accept it anyway for streaming display
            if not allow_at_eof:
                return None

        # Parse the number
        num_str = self._buffer[start:pos]
        try:
            if '.' in num_str or 'e' in num_str or 'E' in num_str:
                return (float(num_str), pos)
            else:
                return (int(num_str), pos)
        except ValueError:
            return None

    def _parse_literal(self, pos: int, expected: str, value: Any) -> Optional[tuple[Any, int]]:
        """Parse a literal (true, false, null) starting at pos."""
        end = pos + len(expected)

        if end > len(self._buffer):
            # Check if what we have matches the prefix
            if self._buffer[pos:] == expected[:len(self._buffer) - pos]:
                return None  # Incomplete but valid prefix
            return None  # Invalid

        if self._buffer[pos:end] == expected:
            # Make sure it's not a prefix of something else
            if end < len(self._buffer) and self._buffer[end].isalnum():
                return None  # Invalid
            return (value, end)

        return None
