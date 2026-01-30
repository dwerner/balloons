from dataclasses import dataclass, field
from typing import Optional, Any
from datetime import datetime


@dataclass
class Message:
    role: str  # "user" or "assistant"
    content: str
    tokens: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class TextDelta:
    text: str
    raw: dict = field(default_factory=dict)


@dataclass
class ResultEvent:
    input_tokens: int
    output_tokens: int
    total_cost_usd: float
    context_window: int = 200000
    raw: dict = field(default_factory=dict)


@dataclass
class InitEvent:
    model: str
    session_id: str
    context_window: int
    raw: dict = field(default_factory=dict)


@dataclass
class RawEvent:
    """Raw JSON event for inspection (non-parsed events)."""
    data: dict


@dataclass
class ToolUseEvent:
    """Claude is using a tool."""
    tool_name: str
    tool_input: dict


@dataclass
class ToolResultEvent:
    """Result from a tool use."""
    tool_name: str
    result: str
