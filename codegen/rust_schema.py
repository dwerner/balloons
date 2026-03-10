"""Decorator and registry for Rust schema generation.

The @rust_schema decorator marks dataclasses that should be generated as Rust structs.
The registry collects all marked classes for the code generator.
"""

from dataclasses import fields, is_dataclass
from typing import get_type_hints, get_origin, get_args, Union, Optional
import typing


class RustSchemaRegistry:
    """Registry of dataclasses marked for Rust generation."""

    _classes: list[type] = []

    @classmethod
    def register(cls, dataclass_type: type) -> None:
        """Register a dataclass for Rust generation."""
        if dataclass_type not in cls._classes:
            cls._classes.append(dataclass_type)

    @classmethod
    def get_all(cls) -> list[type]:
        """Get all registered dataclasses."""
        return cls._classes.copy()

    @classmethod
    def clear(cls) -> None:
        """Clear the registry (mainly for testing)."""
        cls._classes = []


def rust_schema(cls: type) -> type:
    """Decorator to mark a dataclass for Rust code generation.

    Example:
        @rust_schema
        @dataclass
        class TurnData:
            id: str
            role: str
            tokens: int
            archived: bool = False

    This will generate:
        #[derive(Debug, Clone, Serialize, Deserialize)]
        pub struct TurnData {
            pub id: String,
            pub role: String,
            pub tokens: i64,
            pub archived: bool,
        }
    """
    if not is_dataclass(cls):
        raise TypeError(f"@rust_schema can only be applied to dataclasses, got {cls}")

    RustSchemaRegistry.register(cls)
    return cls


def python_type_to_rust(py_type: type, type_hints: dict) -> str:
    """Convert a Python type annotation to Rust type string.

    Supports:
        str -> String
        int -> i64
        float -> f64
        bool -> bool
        Optional[T] -> Option<T>
        list[T] -> Vec<T>
        dict[K, V] -> HashMap<K, V>
        Nested dataclasses -> struct name
    """
    origin = get_origin(py_type)

    # Handle Optional[T] (which is Union[T, None])
    if origin is Union:
        args = get_args(py_type)
        # Optional[T] is Union[T, None]
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1 and type(None) in args:
            inner_type = python_type_to_rust(non_none_args[0], type_hints)
            return f"Option<{inner_type}>"
        else:
            # Complex union - not supported yet
            return "serde_json::Value"

    # Handle list[T]
    if origin is list:
        args = get_args(py_type)
        if args:
            inner_type = python_type_to_rust(args[0], type_hints)
            return f"Vec<{inner_type}>"
        return "Vec<serde_json::Value>"

    # Handle dict[K, V]
    if origin is dict:
        args = get_args(py_type)
        if len(args) == 2:
            key_type = python_type_to_rust(args[0], type_hints)
            val_type = python_type_to_rust(args[1], type_hints)
            return f"HashMap<{key_type}, {val_type}>"
        return "HashMap<String, serde_json::Value>"

    # Handle basic types
    if py_type is str:
        return "String"
    if py_type is int:
        return "i64"
    if py_type is float:
        return "f64"
    if py_type is bool:
        return "bool"

    # Handle dataclass references (nested structs)
    if is_dataclass(py_type):
        return py_type.__name__

    # Fallback for unknown types
    return "serde_json::Value"


def collect_rust_imports(cls: type) -> set[str]:
    """Collect required Rust imports for a dataclass."""
    imports = set()
    type_hints = get_type_hints(cls)

    for f in fields(cls):
        rust_type = python_type_to_rust(type_hints[f.name], type_hints)
        if "HashMap" in rust_type:
            imports.add("std::collections::HashMap")
        if "serde_json::Value" in rust_type:
            imports.add("serde_json")

    return imports


def needs_serde_default(py_type: type, has_default: bool = False) -> bool:
    """Check if a field type should have #[serde(default)].

    Returns True for:
    - Optional<T> and Vec<T> types
    - Fields with default values in Python

    This enables graceful deserialization when fields are missing from stored data,
    supporting schema evolution - new fields can be added without breaking existing data.
    """
    # If field has a default value in Python, it should use #[serde(default)] in Rust
    if has_default:
        return True

    origin = get_origin(py_type)

    # Check for Optional[T] (Union[T, None])
    if origin is Union:
        args = get_args(py_type)
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1 and type(None) in args:
            return True

    # Check for list[T] (becomes Vec<T>)
    if origin is list:
        return True

    return False


def generate_rust_struct(cls: type) -> str:
    """Generate Rust struct definition from a Python dataclass."""
    from dataclasses import MISSING

    if not is_dataclass(cls):
        raise TypeError(f"Expected dataclass, got {cls}")

    type_hints = get_type_hints(cls)
    lines = [
        "#[derive(Debug, Clone, Serialize, Deserialize)]",
        f"pub struct {cls.__name__} {{"
    ]

    for f in fields(cls):
        py_type = type_hints[f.name]
        rust_type = python_type_to_rust(py_type, type_hints)

        # Check if field has a default value in Python
        has_default = f.default is not MISSING or f.default_factory is not MISSING

        # Add #[serde(default)] for Option<T>, Vec<T>, and fields with defaults
        # This enables graceful schema evolution - new optional/collection fields
        # will deserialize as None/[]/default even if missing from stored data
        if needs_serde_default(py_type, has_default):
            lines.append(f"    #[serde(default)]")

        lines.append(f"    pub {f.name}: {rust_type},")

    lines.append("}")
    return "\n".join(lines)
