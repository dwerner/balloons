"""Tool preferences - GUI-independent preferences model.

This module provides the data model for tool preferences,
separate from the GUI widget that displays/edits them.
"""

from dataclasses import dataclass, field


# Default tools available
DEFAULT_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch"]


@dataclass
class ToolPreferences:
    """Tool preferences for a backend."""
    enabled_tools: set[str] = field(default_factory=lambda: set(DEFAULT_TOOLS))
