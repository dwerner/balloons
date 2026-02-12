"""Tests for the Rust codegen schema generation."""

import pytest
from dataclasses import dataclass
from typing import Optional

from codegen.rust_schema import (
    RustSchemaRegistry,
    rust_schema,
    needs_serde_default,
    generate_rust_struct,
)


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the registry before each test."""
    RustSchemaRegistry.clear()
    yield
    RustSchemaRegistry.clear()


class TestNeedsSerdeDefault:
    """Tests for the needs_serde_default function."""

    def test_optional_needs_default(self):
        """Optional[T] should need #[serde(default)]."""
        assert needs_serde_default(Optional[str]) is True
        assert needs_serde_default(Optional[int]) is True

    def test_list_needs_default(self):
        """list[T] should need #[serde(default)]."""
        assert needs_serde_default(list[str]) is True
        assert needs_serde_default(list[int]) is True

    def test_basic_types_no_default(self):
        """Basic types should not need #[serde(default)]."""
        assert needs_serde_default(str) is False
        assert needs_serde_default(int) is False
        assert needs_serde_default(float) is False
        assert needs_serde_default(bool) is False


class TestGenerateRustStruct:
    """Tests for Rust struct generation with #[serde(default)]."""

    def test_optional_field_gets_serde_default(self):
        """Optional fields should have #[serde(default)] attribute."""

        @rust_schema
        @dataclass
        class TestStruct:
            required: str
            optional: Optional[str]

        rust_code = generate_rust_struct(TestStruct)

        # Should have serde(default) before the optional field
        assert "#[serde(default)]" in rust_code
        assert "pub optional: Option<String>" in rust_code

        # Should NOT have serde(default) before the required field
        lines = rust_code.split("\n")
        for i, line in enumerate(lines):
            if "pub required:" in line:
                # Check that the previous line is not serde(default)
                assert "#[serde(default)]" not in lines[i - 1]

    def test_vec_field_gets_serde_default(self):
        """Vec fields should have #[serde(default)] attribute."""

        @rust_schema
        @dataclass
        class TestStruct:
            items: list[str]

        rust_code = generate_rust_struct(TestStruct)

        assert "#[serde(default)]" in rust_code
        assert "pub items: Vec<String>" in rust_code

    def test_mixed_fields(self):
        """Test struct with mix of required, optional, and vec fields."""

        @rust_schema
        @dataclass
        class MixedStruct:
            id: str
            name: str
            tags: list[str]
            description: Optional[str]
            count: int

        rust_code = generate_rust_struct(MixedStruct)

        # Count occurrences of serde(default)
        # Should be 2: one for tags (Vec) and one for description (Option)
        serde_default_count = rust_code.count("#[serde(default)]")
        assert serde_default_count == 2

        # Verify the struct is valid Rust
        assert "pub struct MixedStruct {" in rust_code
        assert "pub id: String," in rust_code
        assert "pub name: String," in rust_code
        assert "pub tags: Vec<String>," in rust_code
        assert "pub description: Option<String>," in rust_code
        assert "pub count: i64," in rust_code
