"""Code generation for Rust and TypeScript from Python dataclasses.

Usage:
    python -m codegen.generate_rust      # Generate Rust structs
    python -m codegen.generate_typescript  # Generate TypeScript types (future)

This module provides:
- @rust_schema decorator to mark dataclasses for Rust generation
- @ws_expose decorator to mark methods for WebSocket RPC exposure
- @ws_event decorator to mark methods that emit events
- @ws_type decorator to mark types for both Rust and TypeScript generation
- @ws_service decorator to mark a class as a WebSocket service
- Type mapping from Python to Rust/TypeScript
- Generation of serde-compatible Rust structs
- Generation of TypeScript interfaces (future)
"""

from codegen.rust_schema import rust_schema, RustSchemaRegistry
from codegen.ws_expose import (
    ws_expose,
    ws_event,
    ws_type,
    ws_service,
    WsExposeRegistry,
    MethodSpec,
    EventSpec,
    ParamSpec,
    ServiceSpec,
)

__all__ = [
    # Rust schema
    "rust_schema",
    "RustSchemaRegistry",
    # WebSocket exposure
    "ws_expose",
    "ws_event",
    "ws_type",
    "ws_service",
    "WsExposeRegistry",
    # Spec types
    "MethodSpec",
    "EventSpec",
    "ParamSpec",
    "ServiceSpec",
]
