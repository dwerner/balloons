"""Dynamic tool prompt builder.

Builds tool documentation prompts based on which tools are enabled.
Prompts are loaded from individual files in prompts/tools/.

This allows per-tool control: UI can enable/disable individual tools,
and only enabled tools will have their documentation included in the prompt.
"""

from pathlib import Path
from typing import Optional, Set

from .debug_log import debug_log, Category


# Base directory for tool prompts
_TOOL_PROMPTS_DIR = Path(__file__).parent.parent / "prompts" / "tools"
_USER_TOOL_PROMPTS_DIR = Path.home() / ".balloons" / "prompts" / "tools"


# Core file/shell tools (always available, no per-tool prompts needed)
CORE_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
]

# Tool categories and their tools (balloon-specific, have prompt files)
# Each category has an optional _overview.md and individual tool files
TOOL_CATEGORIES = {
    "balloon": [
        "ask_user",
        "propose_fork",
        "propose_merge",
        "list_links",
        "follow_link",
        "search_linked_session",
        "session_info",
    ],
    "supervisor": [
        "supervisor_start",
        "supervisor_list",
        "supervisor_output",
        "supervisor_stop",
        "supervisor_query",
        "supervisor_host_status",
    ],
    "watcher": [
        "send_to_target",
    ],
    "midi": [
        "play_midi",
    ],
    "debug": [
        "debug_log_query",
        "debug_log_config",
        "debug_log_tail",
    ],
    # Note: LSP tools could be added here when prompt files are created
    # Note: Domain tools (kanban, chess) are handled by domain plugin system
}

# All tool names for quick lookup (balloon-specific only)
ALL_BALLOON_TOOLS: Set[str] = set()
for tools in TOOL_CATEGORIES.values():
    ALL_BALLOON_TOOLS.update(tools)

# All tools including core
ALL_TOOLS: Set[str] = set(CORE_TOOLS) | ALL_BALLOON_TOOLS

# Default enabled tools - core tools plus balloon essentials
# Users can expand this in config or per-session
DEFAULT_ENABLED_TOOLS: Set[str] = {
    # Core file/shell tools
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
    # Core interaction
    "ask_user",
    # Workflow
    "propose_fork",
    "propose_merge",
    # Session navigation
    "list_links",
    "follow_link",
    "search_linked_session",
    "session_info",
}


def _load_file(path: Path) -> str:
    """Load a file if it exists, return empty string otherwise."""
    try:
        if path.exists():
            return path.read_text()
    except Exception as e:
        debug_log.warning(
            f"Failed to load tool prompt: {path}",
            category=Category.RUNNER,
            details={"error": str(e)},
        )
    return ""


def _load_tool_prompt(category: str, tool_name: str) -> str:
    """Load a tool prompt file, checking user dir first.

    Args:
        category: Tool category (balloon, supervisor, etc.)
        tool_name: Tool name (ask_user, supervisor_start, etc.)

    Returns:
        Prompt content, or empty string if not found
    """
    filename = f"{tool_name}.md"

    # Check user directory first
    user_path = _USER_TOOL_PROMPTS_DIR / category / filename
    content = _load_file(user_path)
    if content:
        return content

    # Fall back to source directory
    source_path = _TOOL_PROMPTS_DIR / category / filename
    return _load_file(source_path)


def _load_category_overview(category: str) -> str:
    """Load a category overview file if it exists."""
    filename = "_overview.md"

    # Check user directory first
    user_path = _USER_TOOL_PROMPTS_DIR / category / filename
    content = _load_file(user_path)
    if content:
        return content

    # Fall back to source directory
    source_path = _TOOL_PROMPTS_DIR / category / filename
    return _load_file(source_path)


def _load_template(name: str) -> str:
    """Load a template file from _templates/."""
    filename = f"{name}.md"

    # Check user directory first
    user_path = _USER_TOOL_PROMPTS_DIR / "_templates" / filename
    content = _load_file(user_path)
    if content:
        return content

    # Fall back to source directory
    source_path = _TOOL_PROMPTS_DIR / "_templates" / filename
    return _load_file(source_path)


def build_tool_prompts(
    enabled_tools: Optional[Set[str]] = None,
    include_critical_usage: bool = True,
) -> str:
    """Build tool documentation prompt for enabled tools.

    Args:
        enabled_tools: Set of tool names to include. None means use DEFAULT_ENABLED_TOOLS.
        include_critical_usage: Whether to include the critical usage template.

    Returns:
        Combined tool documentation as markdown string.
    """
    if enabled_tools is None:
        enabled_tools = DEFAULT_ENABLED_TOOLS

    parts = []

    # Include critical usage template
    if include_critical_usage:
        critical = _load_template("tool_usage_critical")
        if critical:
            parts.append(critical)
            parts.append("---\n")

    # Build category sections
    for category, tools in TOOL_CATEGORIES.items():
        # Check which tools in this category are enabled
        category_enabled = [t for t in tools if t in enabled_tools]
        if not category_enabled:
            continue

        # Include category overview if any tools are enabled
        overview = _load_category_overview(category)
        if overview:
            parts.append(overview)

        # Include individual tool prompts
        for tool_name in category_enabled:
            prompt = _load_tool_prompt(category, tool_name)
            if prompt:
                parts.append(prompt)

    return "\n".join(parts)


def get_tools_in_category(category: str) -> list[str]:
    """Get tool names for a category."""
    return TOOL_CATEGORIES.get(category, [])


def get_all_categories() -> list[str]:
    """Get all category names."""
    return list(TOOL_CATEGORIES.keys())


def get_category_for_tool(tool_name: str) -> Optional[str]:
    """Get the category a tool belongs to."""
    for category, tools in TOOL_CATEGORIES.items():
        if tool_name in tools:
            return category
    return None


def get_default_enabled_tools() -> list[str]:
    """Get the default enabled tools as a list (for config serialization)."""
    return sorted(DEFAULT_ENABLED_TOOLS)
