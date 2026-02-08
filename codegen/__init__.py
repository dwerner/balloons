"""Code generation for Rust schema from Python dataclasses.

Usage:
    python -m codegen.generate_rust

This module provides:
- @rust_schema decorator to mark dataclasses for Rust generation
- Type mapping from Python to Rust (str -> String, int -> i64, etc.)
- Generation of serde-compatible Rust structs
"""

from codegen.rust_schema import rust_schema, RustSchemaRegistry

__all__ = ["rust_schema", "RustSchemaRegistry"]
