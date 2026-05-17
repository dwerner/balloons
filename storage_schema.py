"""Storage schema definitions for Rust code generation.

These are the "wire format" types used for storage - simplified versions of
domain entities optimized for serialization to Rust.

The @rust_schema decorator registers these for Rust code generation.
To regenerate: python -m codegen.generate_rust
"""

from dataclasses import dataclass, field
from typing import Optional

from codegen import rust_schema


@rust_schema
@dataclass
class ForkChildData:
    """A child fork reference stored in the parent session.

    Contains the essential info needed to reconstruct the fork tree
    without loading the full child session.
    """
    session_id: str
    name: str  # Fork name or first 50 chars of prompt
    status: str  # "active", "merged", "abandoned"
    fork_point: int  # Turn index where fork was created (-1 if unknown)
    merge_point: int = -1  # Turn index where merged (-1 if not merged)
    return_condition: str = "manual"  # "manual" or "auto"
    prompt: str = ""  # Initial prompt (may be truncated)


@rust_schema
@dataclass
class TurnData:
    """A single conversation turn for storage.

    Simplified version of Turn from models.py.
    Content blocks are stored as JSON (serde_json::Value) for flexibility.

    Timing fields for diagnosing streaming issues:
    - started_at: When the turn began (streaming started)
    - ended_at: When the turn completed (streaming finished)
    """
    id: str
    role: str  # "user", "assistant", "tool", "system"
    content_block: dict  # Serialized ContentBlock (TextBlock, ToolUseBlock, etc.)
    tokens: int
    timestamp: str  # ISO 8601 format
    context_mode: str  # "copy", "compress", "drop"
    summary: str  # Cached summary for compress mode
    exchange_id: Optional[str] = None  # Groups turns in an agentic loop
    sentiment: Optional[str] = None  # "excellent", "good", "review", "poor", "terrible"
    started_at: Optional[str] = None  # ISO 8601 format, when streaming began
    ended_at: Optional[str] = None  # ISO 8601 format, when streaming completed
    parallel_group_id: Optional[str] = None  # Groups parallel tool calls from same LLM response


@rust_schema
@dataclass
class SessionData:
    """Session metadata for storage (turns stored separately).

    Simplified version of Session from session.py.
    Turns are stored in TURNS table, linked via TURN_ORDER table.
    """
    id: str
    created: str  # ISO 8601 format
    last_modified: str  # ISO 8601 format
    model: str
    # NOTE: turns are stored separately in TURNS table, linked via TURN_ORDER

    # Token/cost tracking
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float
    context_window: int

    # Forking
    parent_id: Optional[str] = None
    children: list[ForkChildData] = field(default_factory=list)
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

    # Session-specific prompt files (absolute paths included in system prompt)
    prompt_files: list[str] = field(default_factory=list)

    # Enabled tools for this session (empty list = defaults)
    enabled_tools: list[str] = field(default_factory=list)

    # Conclude metadata
    concluded: bool = False
    concluded_at: Optional[str] = None
    concluded_reason: str = ""

    # Message queue (stored as dict for flexibility)
    message_queue: dict = field(default_factory=dict)

    # Loaded domain plugins for this session
    # Domains listed here are auto-loaded when the session is activated
    loaded_domains: list[str] = field(default_factory=list)


@rust_schema
@dataclass
class TurnOrder:
    """Ordered list of turn IDs for a session.

    This is the relationship entity that links sessions to their turns.
    Stored in TURN_ORDER table keyed by session_id.
    """
    session_id: str
    turn_ids: list[str]


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
    cached_context_tokens: int = 0  # Context tokens for display in session tree
    context_window: int = 150000  # Model's context window for percentage calculation
    working_directories: list[str] = field(default_factory=list)
    # Fork hierarchy fields (for HierarchyView)
    parent_id: Optional[str] = None
    fork_name: str = ""
    fork_status: str = "active"  # "active", "merged", "abandoned"
    children: list[ForkChildData] = field(default_factory=list)
    # Loaded domain plugins for this session
    loaded_domains: list[str] = field(default_factory=list)
    # Backend configuration used by this session
    backend_name: str = ""


@rust_schema
@dataclass
class ReviewData:
    """Quality review of a session.

    Created by the :review command when evaluating LLM performance.
    Stored in REVIEWS table keyed by id.
    """
    id: str  # UUID
    session_id: str  # Session being reviewed
    reviewed_at: str  # ISO 8601 timestamp

    # What was being evaluated
    model_under_review: str  # Backend name active during session
    review_backend: str  # Backend that performed the analysis

    # User-provided rubric scores (1-5)
    score_correctness: int
    score_efficiency: int
    score_instruction_following: int
    score_recovery: int
    score_autonomy: int
    score_judgment: int
    score_communication: int

    # Task categorization
    task_category: str  # enum value: debugging, feature, refactor, exploration, documentation, review, learning, ops, other
    task_description: str  # freeform 1-sentence

    # Summaries
    user_summary: str  # User's freeform comments
    llm_commentary: str  # Analysis LLM's commentary

    # Metadata
    spec_version: str = "0.1.0"  # Version of this spec used
    session_duration_minutes: Optional[int] = None  # Optional
    turn_count: int = 0  # Number of turns in session
    sentiment_counts: dict = field(default_factory=dict)  # {"excellent": 2, "poor": 1, ...}



# =============================================================================
# Watcher Relationships
# =============================================================================


@rust_schema
@dataclass
class WatcherRelation:
    """A watcher session observing a target session.

    Tracks which sessions are watching which targets, enabling notification
    when target sessions complete exchanges. Persisted to LMDB for fast
    lookup at startup.
    """
    id: str  # UUID (watcher_id:target_id composite)
    watcher_session_id: str  # The session doing the watching
    target_session_id: str  # The session being watched
    target_session_name: str  # Display name at time of creation
    created_at: str  # ISO 8601


# =============================================================================
# User Authentication
# =============================================================================


@rust_schema
@dataclass
class UserData:
    """A user account for authentication.

    Users authenticate via username/password and receive a JWT token.
    The admin role grants access to user management endpoints.
    """
    id: str  # UUID
    username: str  # Unique, case-insensitive
    password_hash: str  # argon2id hash
    role: str  # "admin" | "user"
    created_at: str  # ISO 8601
    created_by: Optional[str] = None  # User ID who created this user
    last_login: Optional[str] = None  # ISO 8601
    disabled: bool = False


# =============================================================================
# User Preferences
# =============================================================================


@rust_schema
@dataclass
class UserPrefs:
    """User preferences for UI state and settings.

    Stores persistent UI state like which tree nodes are collapsed,
    and user settings. Each field is optional to allow incremental updates.

    The pinned_session_ids field stores session IDs that should appear at the
    top of session lists and tree views. Pinned sessions are sorted by last
    modified within their group.
    """
    # Session pinning
    pinned_session_ids: list[str] = field(default_factory=list)  # IDs of pinned sessions
