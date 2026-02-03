"""Tests for the streaming JSON parser."""

import sys
import importlib.util
from pathlib import Path

import pytest

# Import json_stream directly to avoid core/__init__.py dependency chain
_spec = importlib.util.spec_from_file_location(
    'json_stream',
    Path(__file__).parent.parent / 'core' / 'json_stream.py'
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
StreamingJsonParser = _module.StreamingJsonParser


class TestBasicParsing:
    """Tests for parsing complete JSON."""

    def test_empty_buffer(self):
        parser = StreamingJsonParser()
        assert parser.get_partial() is None
        assert not parser.is_complete()

    def test_whitespace_only(self):
        parser = StreamingJsonParser()
        parser.feed("   \n\t  ")
        assert parser.get_partial() is None

    def test_complete_object(self):
        parser = StreamingJsonParser()
        parser.feed('{"name": "Alice", "age": 30}')
        result = parser.get_partial()
        assert result == {"name": "Alice", "age": 30}
        assert parser.is_complete()

    def test_complete_array(self):
        parser = StreamingJsonParser()
        parser.feed('[1, 2, 3]')
        result = parser.get_partial()
        assert result == [1, 2, 3]
        assert parser.is_complete()

    def test_complete_string(self):
        parser = StreamingJsonParser()
        parser.feed('"hello"')
        assert parser.get_partial() == "hello"
        assert parser.is_complete()

    def test_complete_number_int(self):
        parser = StreamingJsonParser()
        parser.feed('42')
        # Note: numbers at EOF need a delimiter to be "complete"
        # so we test within an object
        parser = StreamingJsonParser()
        parser.feed('{"x": 42}')
        assert parser.get_partial() == {"x": 42}

    def test_complete_number_float(self):
        parser = StreamingJsonParser()
        parser.feed('{"x": 3.14}')
        assert parser.get_partial() == {"x": 3.14}

    def test_complete_number_negative(self):
        parser = StreamingJsonParser()
        parser.feed('{"x": -42}')
        assert parser.get_partial() == {"x": -42}

    def test_complete_number_exponent(self):
        parser = StreamingJsonParser()
        parser.feed('{"x": 1.5e10}')
        assert parser.get_partial() == {"x": 1.5e10}

    def test_complete_true(self):
        parser = StreamingJsonParser()
        parser.feed('{"flag": true}')
        assert parser.get_partial() == {"flag": True}

    def test_complete_false(self):
        parser = StreamingJsonParser()
        parser.feed('{"flag": false}')
        assert parser.get_partial() == {"flag": False}

    def test_complete_null(self):
        parser = StreamingJsonParser()
        parser.feed('{"value": null}')
        assert parser.get_partial() == {"value": None}

    def test_nested_objects(self):
        parser = StreamingJsonParser()
        parser.feed('{"user": {"name": "Alice", "address": {"city": "NYC"}}}')
        result = parser.get_partial()
        assert result == {"user": {"name": "Alice", "address": {"city": "NYC"}}}

    def test_nested_arrays(self):
        parser = StreamingJsonParser()
        parser.feed('[[1, 2], [3, 4]]')
        assert parser.get_partial() == [[1, 2], [3, 4]]

    def test_mixed_nesting(self):
        parser = StreamingJsonParser()
        parser.feed('{"items": [{"id": 1}, {"id": 2}]}')
        assert parser.get_partial() == {"items": [{"id": 1}, {"id": 2}]}


class TestStringEscapes:
    """Tests for string escape sequences."""

    def test_escaped_quote(self):
        parser = StreamingJsonParser()
        parser.feed('{"text": "say \\"hello\\""}')
        assert parser.get_partial() == {"text": 'say "hello"'}

    def test_escaped_backslash(self):
        parser = StreamingJsonParser()
        parser.feed('{"path": "c:\\\\users"}')
        assert parser.get_partial() == {"path": "c:\\users"}

    def test_escaped_newline(self):
        parser = StreamingJsonParser()
        parser.feed('{"text": "line1\\nline2"}')
        assert parser.get_partial() == {"text": "line1\nline2"}

    def test_escaped_tab(self):
        parser = StreamingJsonParser()
        parser.feed('{"text": "col1\\tcol2"}')
        assert parser.get_partial() == {"text": "col1\tcol2"}

    def test_unicode_escape(self):
        parser = StreamingJsonParser()
        parser.feed('{"emoji": "\\u263A"}')
        assert parser.get_partial() == {"emoji": "☺"}

    def test_all_escapes(self):
        parser = StreamingJsonParser()
        parser.feed('{"text": "\\"\\\\\\b\\f\\n\\r\\t"}')
        assert parser.get_partial() == {"text": "\"\\\b\f\n\r\t"}


class TestPartialObjects:
    """Tests for streaming partial objects."""

    def test_empty_object_no_close(self):
        parser = StreamingJsonParser()
        parser.feed('{')
        assert parser.get_partial() == {}
        assert not parser.is_complete()

    def test_one_complete_field(self):
        parser = StreamingJsonParser()
        parser.feed('{"name": "Alice"')
        assert parser.get_partial() == {"name": "Alice"}

    def test_two_complete_fields(self):
        parser = StreamingJsonParser()
        parser.feed('{"name": "Alice", "age": 30')
        assert parser.get_partial() == {"name": "Alice", "age": 30}

    def test_field_with_incomplete_string_value(self):
        parser = StreamingJsonParser()
        parser.feed('{"name": "Ali')
        # String is incomplete, so the field is omitted
        assert parser.get_partial() == {}

    def test_field_with_incomplete_string_key(self):
        parser = StreamingJsonParser()
        parser.feed('{"name": "Alice", "ag')
        # Key is incomplete, field omitted
        assert parser.get_partial() == {"name": "Alice"}

    def test_field_with_incomplete_number(self):
        parser = StreamingJsonParser()
        parser.feed('{"name": "Alice", "age": 30')
        # 30 is followed by end-of-buffer, might continue
        # But since no more chars, we include it
        assert parser.get_partial() == {"name": "Alice", "age": 30}

    def test_field_with_partial_true(self):
        parser = StreamingJsonParser()
        parser.feed('{"flag": tr')
        assert parser.get_partial() == {}

    def test_field_with_partial_false(self):
        parser = StreamingJsonParser()
        parser.feed('{"flag": fals')
        assert parser.get_partial() == {}

    def test_field_with_partial_null(self):
        parser = StreamingJsonParser()
        parser.feed('{"value": nul')
        assert parser.get_partial() == {}

    def test_nested_object_incomplete(self):
        parser = StreamingJsonParser()
        parser.feed('{"user": {"name": "Alice"')
        result = parser.get_partial()
        assert result == {"user": {"name": "Alice"}}

    def test_deeply_nested_incomplete(self):
        parser = StreamingJsonParser()
        parser.feed('{"a": {"b": {"c": "d"')
        result = parser.get_partial()
        assert result == {"a": {"b": {"c": "d"}}}


class TestPartialArrays:
    """Tests for streaming partial arrays."""

    def test_empty_array_no_close(self):
        parser = StreamingJsonParser()
        parser.feed('[')
        assert parser.get_partial() == []

    def test_one_complete_element(self):
        parser = StreamingJsonParser()
        parser.feed('[1')
        assert parser.get_partial() == [1]

    def test_two_complete_elements(self):
        parser = StreamingJsonParser()
        parser.feed('[1, 2')
        assert parser.get_partial() == [1, 2]

    def test_incomplete_string_element(self):
        parser = StreamingJsonParser()
        parser.feed('["hello", "wor')
        assert parser.get_partial() == ["hello"]

    def test_array_of_objects_incomplete(self):
        parser = StreamingJsonParser()
        parser.feed('[{"id": 1}, {"id": 2')
        assert parser.get_partial() == [{"id": 1}, {"id": 2}]

    def test_array_of_objects_very_incomplete(self):
        parser = StreamingJsonParser()
        parser.feed('[{"id": 1}, {"id')
        # When an object is started but has no complete keys, we return {}
        # to indicate an object is in progress
        assert parser.get_partial() == [{"id": 1}, {}]


class TestIncrementalFeeding:
    """Tests for feeding data incrementally."""

    def test_feed_char_by_char(self):
        parser = StreamingJsonParser()
        data = '{"name": "Alice"}'

        for i, char in enumerate(data):
            parser.feed(char)
            result = parser.get_partial()
            # Before the string completes, should be {}
            # After it completes, should have the value
            if i < 16:  # Before final }
                # May or may not have partial data depending on position
                pass
            else:
                assert result == {"name": "Alice"}

    def test_feed_chunks(self):
        parser = StreamingJsonParser()

        parser.feed('{"name')
        assert parser.get_partial() == {}

        parser.feed('": "Al')
        assert parser.get_partial() == {}

        parser.feed('ice"')
        assert parser.get_partial() == {"name": "Alice"}

        parser.feed(', "age": ')
        assert parser.get_partial() == {"name": "Alice"}

        parser.feed('30}')
        assert parser.get_partial() == {"name": "Alice", "age": 30}
        assert parser.is_complete()

    def test_get_buffer(self):
        parser = StreamingJsonParser()
        parser.feed('{"hello')
        parser.feed('": "world')
        assert parser.get_buffer() == '{"hello": "world'

    def test_clear(self):
        parser = StreamingJsonParser()
        parser.feed('{"name": "Alice"}')
        assert parser.get_partial() == {"name": "Alice"}

        parser.clear()
        assert parser.get_buffer() == ""
        assert parser.get_partial() is None


class TestCaching:
    """Tests for result caching."""

    def test_cached_result_returned(self):
        parser = StreamingJsonParser()
        parser.feed('{"name": "Alice"}')

        result1 = parser.get_partial()
        result2 = parser.get_partial()

        # Same object should be returned (cached)
        assert result1 is result2

    def test_cache_invalidated_on_feed(self):
        parser = StreamingJsonParser()
        parser.feed('{"name": "Alice"')
        result1 = parser.get_partial()

        parser.feed('}')
        result2 = parser.get_partial()

        # Results should be equal but potentially different objects
        assert result1 == {"name": "Alice"}
        assert result2 == {"name": "Alice"}


class TestEdgeCases:
    """Tests for edge cases and unusual input."""

    def test_empty_object(self):
        parser = StreamingJsonParser()
        parser.feed('{}')
        assert parser.get_partial() == {}
        assert parser.is_complete()

    def test_empty_array(self):
        parser = StreamingJsonParser()
        parser.feed('[]')
        assert parser.get_partial() == []
        assert parser.is_complete()

    def test_empty_string(self):
        parser = StreamingJsonParser()
        parser.feed('{"text": ""}')
        assert parser.get_partial() == {"text": ""}

    def test_whitespace_around_values(self):
        parser = StreamingJsonParser()
        parser.feed('{ "name" : "Alice" , "age" : 30 }')
        assert parser.get_partial() == {"name": "Alice", "age": 30}

    def test_unicode_in_string(self):
        parser = StreamingJsonParser()
        parser.feed('{"emoji": "😀"}')
        assert parser.get_partial() == {"emoji": "😀"}

    def test_very_long_string(self):
        parser = StreamingJsonParser()
        long_value = "x" * 10000
        parser.feed(f'{{"data": "{long_value}"}}')
        assert parser.get_partial() == {"data": long_value}

    def test_many_nested_levels(self):
        parser = StreamingJsonParser()
        # 10 levels of nesting
        json_str = '{"a":' * 10 + '1' + '}' * 10
        parser.feed(json_str)
        result = parser.get_partial()
        # Verify structure
        for _ in range(10):
            assert "a" in result
            result = result["a"]
        assert result == 1

    def test_array_trailing_comma_tolerance(self):
        # Many JSON parsers are lenient about trailing commas
        parser = StreamingJsonParser()
        parser.feed('[1, 2, ')  # Trailing comma, more coming
        assert parser.get_partial() == [1, 2]

    def test_number_at_end_of_buffer(self):
        parser = StreamingJsonParser()
        parser.feed('{"x": 12')
        # 12 at end of buffer - might be 123 next
        # Our parser is conservative here
        result = parser.get_partial()
        # Since number isn't followed by delimiter, it's incomplete
        # But since we're in object context, we can include it if
        # we see end of buffer
        assert result == {"x": 12}

    def test_escape_at_end_of_string(self):
        parser = StreamingJsonParser()
        parser.feed('{"text": "hello\\')
        # Incomplete escape sequence
        assert parser.get_partial() == {}

    def test_unicode_escape_incomplete(self):
        parser = StreamingJsonParser()
        parser.feed('{"text": "\\u00')
        # Incomplete unicode escape
        assert parser.get_partial() == {}


class TestToolInputScenarios:
    """Tests simulating real tool_input_delta streaming scenarios."""

    def test_read_file_tool(self):
        """Simulate streaming a read_file tool call."""
        parser = StreamingJsonParser()

        parser.feed('{"path":')
        assert parser.get_partial() == {}

        parser.feed(' "/home/')
        assert parser.get_partial() == {}

        parser.feed('user/file.txt"')
        assert parser.get_partial() == {"path": "/home/user/file.txt"}

        parser.feed('}')
        assert parser.get_partial() == {"path": "/home/user/file.txt"}
        assert parser.is_complete()

    def test_write_file_tool(self):
        """Simulate streaming a write_file tool call."""
        parser = StreamingJsonParser()

        parser.feed('{"path": "/test.py", "content": "def hello')
        assert parser.get_partial() == {"path": "/test.py"}

        parser.feed('():\\n    print(\\"Hi\\")')
        assert parser.get_partial() == {"path": "/test.py"}

        parser.feed('"')
        result = parser.get_partial()
        assert result["path"] == "/test.py"
        assert "def hello" in result["content"]

        parser.feed('}')
        assert parser.is_complete()

    def test_bash_tool(self):
        """Simulate streaming a bash tool call."""
        parser = StreamingJsonParser()

        parser.feed('{"command": "ls -la /home/')
        assert parser.get_partial() == {}

        parser.feed('user", "timeout": 30000')
        result = parser.get_partial()
        assert result["command"] == "ls -la /home/user"
        assert result["timeout"] == 30000

        parser.feed('}')
        assert parser.is_complete()

    def test_complex_tool_input(self):
        """Simulate a tool with complex nested input."""
        parser = StreamingJsonParser()

        parser.feed('{"files": [{"path": "/a.txt", "content": "hello"')
        result = parser.get_partial()
        assert result["files"][0] == {"path": "/a.txt", "content": "hello"}

        parser.feed('}, {"path": "/b.txt", "content": "world"')
        result = parser.get_partial()
        assert len(result["files"]) == 2
        assert result["files"][1]["path"] == "/b.txt"

        parser.feed('}], "overwrite": true}')
        result = parser.get_partial()
        assert len(result["files"]) == 2
        assert result["overwrite"] is True
        assert parser.is_complete()


class TestRealWorldStreaming:
    """Tests simulating realistic streaming scenarios from LLM APIs."""

    def test_anthropic_style_edit_tool(self):
        """Simulate streaming an edit tool call like Claude Code uses."""
        parser = StreamingJsonParser()

        # First chunk: opening and path start
        parser.feed('{"file_path": "/home/user/')
        assert parser.get_partial() == {}

        # Path continues
        parser.feed('project/src/main.py", ')
        result = parser.get_partial()
        assert result["file_path"] == "/home/user/project/src/main.py"

        # old_string starts
        parser.feed('"old_string": "def hello')
        assert parser.get_partial()["file_path"] == "/home/user/project/src/main.py"
        assert "old_string" not in parser.get_partial()

        # old_string completes
        parser.feed('():\\n    pass", ')
        result = parser.get_partial()
        assert "old_string" in result

        # new_string
        parser.feed('"new_string": "def hello():\\n    print(\\"hi\\")"}')
        result = parser.get_partial()
        assert result["new_string"] == 'def hello():\n    print("hi")'
        assert parser.is_complete()

    def test_tool_with_very_long_content(self):
        """Test streaming a tool with very long content field."""
        parser = StreamingJsonParser()

        parser.feed('{"path": "/test.py", "content": "')
        assert parser.get_partial() == {"path": "/test.py"}

        # Feed long content in chunks
        for i in range(100):
            parser.feed(f"line {i}\\n")
        assert parser.get_partial() == {"path": "/test.py"}  # Still incomplete

        parser.feed('"}')
        result = parser.get_partial()
        assert result["path"] == "/test.py"
        assert "line 0\n" in result["content"]
        assert "line 99\n" in result["content"]

    def test_multiple_tool_calls(self):
        """Test streaming array of tool calls."""
        parser = StreamingJsonParser()

        parser.feed('[{"type": "read", "path": "/a.txt"')
        result = parser.get_partial()
        assert len(result) == 1
        assert result[0]["type"] == "read"

        parser.feed('}, {"type": "write"')
        result = parser.get_partial()
        assert len(result) == 2
        assert result[0]["path"] == "/a.txt"
        assert result[1]["type"] == "write"

        parser.feed(', "path": "/b.txt", "content": "hello"}]')
        result = parser.get_partial()
        assert len(result) == 2
        assert result[1]["content"] == "hello"
        assert parser.is_complete()

    def test_boolean_at_end_of_stream(self):
        """Test booleans that complete at stream end."""
        parser = StreamingJsonParser()
        parser.feed('{"enabled": true')
        assert parser.get_partial() == {"enabled": True}

        parser.feed(', "disabled": false')
        assert parser.get_partial() == {"enabled": True, "disabled": False}

    def test_nested_code_with_escapes(self):
        """Test complex code content with many escapes."""
        parser = StreamingJsonParser()

        # Use properly escaped JSON - inner quotes need \" and inner newlines need \\n
        # Result: code contains literal \n (the characters) and literal quotes
        json_str = '{"code": "def test():\\n    x = \\"hello\\\\nworld\\"\\n    return x"}'
        parser.feed(json_str)

        result = parser.get_partial()
        assert 'def test()' in result["code"]
        # After JSON parsing, \\n becomes \n (two chars) and \n becomes newline
        assert 'hello\\nworld' in result["code"]  # Literal backslash-n in string

    def test_incremental_number_completion(self):
        """Test numbers completing incrementally."""
        parser = StreamingJsonParser()

        parser.feed('{"value": 12')
        assert parser.get_partial() == {"value": 12}

        parser.feed('34')
        assert parser.get_partial() == {"value": 1234}

        parser.feed('.5')
        # After decimal, need more digits
        parser.feed('6')
        assert parser.get_partial() == {"value": 1234.56}

        parser.feed('}')
        assert parser.get_partial() == {"value": 1234.56}
        assert parser.is_complete()


class TestNumberParsing:
    """Detailed tests for number parsing edge cases."""

    def test_zero(self):
        parser = StreamingJsonParser()
        parser.feed('[0]')
        assert parser.get_partial() == [0]

    def test_negative_zero(self):
        parser = StreamingJsonParser()
        parser.feed('[-0]')
        assert parser.get_partial() == [0]  # -0 == 0 in Python

    def test_large_integer(self):
        parser = StreamingJsonParser()
        parser.feed('[12345678901234567890]')
        assert parser.get_partial() == [12345678901234567890]

    def test_small_float(self):
        parser = StreamingJsonParser()
        parser.feed('[0.0001]')
        assert parser.get_partial() == [0.0001]

    def test_negative_exponent(self):
        parser = StreamingJsonParser()
        parser.feed('[1e-10]')
        assert parser.get_partial() == [1e-10]

    def test_positive_exponent(self):
        parser = StreamingJsonParser()
        parser.feed('[1e+10]')
        assert parser.get_partial() == [1e10]

    def test_capital_exponent(self):
        parser = StreamingJsonParser()
        parser.feed('[1E10]')
        assert parser.get_partial() == [1e10]

    def test_incomplete_decimal(self):
        parser = StreamingJsonParser()
        parser.feed('{"x": 3.')
        # Decimal not complete
        assert parser.get_partial() == {}

    def test_incomplete_exponent(self):
        parser = StreamingJsonParser()
        parser.feed('{"x": 1e')
        assert parser.get_partial() == {}

    def test_incomplete_exponent_sign(self):
        parser = StreamingJsonParser()
        parser.feed('{"x": 1e-')
        assert parser.get_partial() == {}
