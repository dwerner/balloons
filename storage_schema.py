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
# Goal-Oriented Task Management Entities
# =============================================================================


@rust_schema
@dataclass
class GoalData:
    """A high-level goal that guides work across sessions.

    Goals have weight (1-10) indicating priority, acceptance criteria for
    completion, and can supersede other goals when priorities change.

    Goals can be nested under parent goals via parent_goal_id. A nested goal's
    completion contributes to its parent's completion state.
    """
    id: str  # UUID
    title: str
    description: str
    weight: int  # 1-10, higher = more important
    status: str  # "active", "completed", "superseded", "abandoned"
    acceptance_criteria: list[str]  # Conditions that define completion
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    completed_at: Optional[str] = None  # ISO 8601, when status became completed
    supersedes_id: Optional[str] = None  # Goal this one replaces
    parent_goal_id: Optional[str] = None  # Parent goal ID for nesting


@rust_schema
@dataclass
class PlanData:
    """A plan for achieving a goal.

    Plans break goals into actionable strategies. A goal may have multiple
    plans (different approaches), but typically one active plan at a time.
    """
    id: str  # UUID
    goal_id: str  # Parent goal
    title: str
    description: str
    status: str  # "draft", "active", "completed", "abandoned"
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    completed_at: Optional[str] = None  # ISO 8601
    postmortem: Optional[str] = None  # Retrospective notes when plan completes


@rust_schema
@dataclass
class TodoData:
    """A concrete task to be completed.

    Todos are linked to plans via TodoPlanLink (many-to-many). Spikes are
    timeboxed exploration tasks exempt from priority computation.
    """
    id: str  # UUID
    title: str
    description: str
    status: str  # "pending", "in_progress", "completed", "blocked", "abandoned"
    is_spike: bool  # Timeboxed exploration, exempt from priority
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    completed_at: Optional[str] = None  # ISO 8601
    timebox_minutes: Optional[int] = None  # For spikes: max time to spend
    completed_by_session: Optional[str] = None  # Session ID that completed this todo
    completed_by: Optional[str] = None  # "llm" or "user" - who initiated completion


@rust_schema
@dataclass
class TodoPlanLink:
    """Links todos to plans (many-to-many relationship).

    A todo can contribute to multiple plans, and completing it once
    satisfies all linked plans.
    """
    todo_id: str
    plan_id: str
    created_at: str  # ISO 8601


@rust_schema
@dataclass
class TodoDependency:
    """Dependency edge in the todo graph.

    todo_id cannot be started until depends_on_id is completed.
    Dependencies affect availability, not priority ranking.
    """
    todo_id: str  # The dependent todo
    depends_on_id: str  # The todo that must complete first
    created_at: str  # ISO 8601


@rust_schema
@dataclass
class SessionBinding:
    """Binds a session to goal-oriented entities.

    Tracks which goals, plans, and todos a session is working on,
    and what role the session plays in that work.
    """
    id: str  # UUID
    session_id: str
    entity_type: str  # "goal", "plan", "todo"
    entity_id: str  # ID of the bound entity
    role: str  # "interview", "planning", "implementation", "postmortem", "exploration"
    created_at: str  # ISO 8601
    released_at: Optional[str] = None  # ISO 8601, when binding ended


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

    The goal_tree_collapsed_ids field stores IDs of nodes that should be
    collapsed when the goal tree is displayed. By default, nodes are expanded;
    this list tracks nodes the user explicitly collapsed.

    The pinned_session_ids field stores session IDs that should appear at the
    top of session lists and tree views. Pinned sessions are sorted by last
    modified within their group.
    """
    # Goal tree UI state
    goal_tree_collapsed_ids: list[str] = field(default_factory=list)  # IDs of collapsed nodes

    # Session pinning
    pinned_session_ids: list[str] = field(default_factory=list)  # IDs of pinned sessions


# =============================================================================
# Kanban / Graph System
# =============================================================================


@rust_schema
@dataclass
class TaskData:
    """A work item in the kanban system.

    Tasks are the primary work unit. They can be placed on boards via edges
    and associated with other entities (goals, sessions) via the graph.
    """
    id: str  # UUID
    title: str
    description: str
    resolution: str = ""  # What was done to complete/resolve this task
    created_at: str = ""  # ISO 8601
    updated_at: str = ""  # ISO 8601


@rust_schema
@dataclass
class BoardData:
    """A kanban board with configurable columns.

    Boards track task progress through columns. Each board has a default
    column where new tasks are placed.
    """
    id: str  # UUID
    name: str
    default_column_id: str  # Column ID for new tasks
    created_at: str  # ISO 8601


@rust_schema
@dataclass
class ColumnData:
    """A column in a kanban board.

    Columns represent stages in a workflow (e.g., Todo, In Progress, Done).
    Position determines display order within the board.
    """
    id: str  # UUID
    name: str
    position: int  # Ordering within board (0-indexed)


@rust_schema
@dataclass
class EdgeData:
    """A directed relationship between two entities in the graph.

    Edges connect entities with typed relationships. The position field
    enables ordering (e.g., task order within a column).

    Entity types: "task", "board", "column", "session"
    Relationships:
      - "tracked_on": Task → Board (task appears on board)
      - "part_of": Column → Board (column belongs to board)
      - "in_column": Task → Column (task's position in column)
    """
    id: str  # UUID
    source_type: str  # Entity type of source
    source_id: str
    target_type: str  # Entity type of target
    target_id: str
    relationship: str  # Relationship type
    position: Optional[int] = None  # For ordering (e.g., task in column)
    created_at: str = ""  # ISO 8601


@rust_schema
@dataclass
class SessionBoardAssociation:
    """Associates a kanban board with a session.

    Enables per-session kanban boards while allowing boards to be
    shared across multiple sessions if needed. Associations are
    inherited when a session is forked.

    Roles:
      - "primary": Main board for session's work tracking
      - "reference": Board viewed but not actively managed
      - "archive": Completed/historical board

    created_by tracks who created the association:
      - "user": Manual association via UI
      - "llm": Created by LLM tool
      - "fork": Inherited from parent session
    """
    id: str  # UUID
    session_id: str
    board_id: str
    role: str  # "primary", "reference", "archive"
    created_at: str  # ISO 8601
    created_by: str  # "user" | "llm" | "fork"
    inherited_from: Optional[str] = None  # Parent session ID if inherited via fork