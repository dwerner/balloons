"""Storage schema definitions for Rust code generation.

These are the "wire format" types used for storage - simplified versions of
domain entities optimized for serialization to Rust/redb.

The @rust_schema decorator registers these for Rust code generation.
To regenerate: python -m codegen.generate_rust
"""

from dataclasses import dataclass, field
from typing import Optional

from codegen import rust_schema


@rust_schema
@dataclass
class TurnData:
    """A single conversation turn for storage.

    Simplified version of Turn from models.py.
    Content blocks are stored as JSON (serde_json::Value) for flexibility.
    """
    id: str
    role: str  # "user", "assistant", "tool", "system"
    content_block: dict  # Serialized ContentBlock (TextBlock, ToolUseBlock, etc.)
    tokens: int
    timestamp: str  # ISO 8601 format
    context_mode: str  # "copy", "compress", "drop"
    summary: str  # Cached summary for compress mode
    exchange_id: Optional[str] = None  # Groups turns in an agentic loop


@rust_schema
@dataclass
class SessionData:
    """Full session data for storage.

    Simplified version of Session from session.py.
    """
    id: str
    created: str  # ISO 8601 format
    last_modified: str  # ISO 8601 format
    model: str
    turns: list[TurnData]

    # Token/cost tracking
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float
    context_window: int

    # Forking
    parent_id: Optional[str] = None
    children: list[dict] = field(default_factory=list)  # [{session_id, status, ...}]
    returned: bool = False
    return_condition: str = "manual"

    # Working state
    working_directories: list[str] = field(default_factory=list)
    title: str = ""
    summary: str = ""

    # Fork/merge tracking
    fork_name: str = ""
    fork_status: str = "active"  # "active", "merged", "abandoned"
    fork_point_turn: int = -1
    merge_point_turn: int = -1
    merge_message: str = ""

    # Backend
    backend_name: str = ""
    cached_context_tokens: int = 0

    # Message queue (stored as dict for flexibility)
    message_queue: dict = field(default_factory=dict)


@rust_schema
@dataclass
class SessionMetadata:
    """Lightweight session metadata for listing.

    Used by list_sessions() to avoid loading full session data.
    """
    id: str
    name: str  # Same as title in SessionData
    created_at: int  # Unix timestamp
    updated_at: int  # Unix timestamp
    turn_count: int
