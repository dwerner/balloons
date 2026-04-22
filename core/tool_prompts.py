"""Dynamic tool prompt builder.

Builds tool documentation prompts based on which tools are enabled.
Prompts are loaded from individual files in prompts/tools/.

This allows per-tool control: UI can enable/disable individual tools,
and only enabled tools will have their documentation included in the prompt.

The order of tools in the enabled list determines the order in the prompt.
Category overviews are inserted when a tool from that category first appears.

Tool Discovery:
- Categories are discovered from subdirectories of prompts/tools/
- Tools are discovered from *.md files within each category directory
- Both source (prompts/tools/) and user (~/.balloons/prompts/tools/) directories are scanned
- Directories starting with _ (like _templates) and 'openai' are excluded from categories
"""

from pathlib import Path
from typing import Optional, Set, Sequence

from .debug_log import debug_log, Category


# Base directory for tool prompts
_TOOL_PROMPTS_DIR = Path(__file__).parent.parent / "prompts" / "tools"
_USER_TOOL_PROMPTS_DIR = Path.home() / ".balloons" / "prompts" / "tools"

# Directories to exclude from category discovery
_EXCLUDED_DIRS = {"_templates", "openai"}

# Cache for discovered categories and tools
_discovery_cache: dict[str, dict[str, list[str]]] | None = None


def _discover_tools_in_directory(base_dir: Path) -> dict[str, list[str]]:
    """Discover tool categories and tools from a directory.

    Args:
        base_dir: Directory to scan (e.g., prompts/tools/)

    Returns:
        Dict mapping category name to list of tool names
    """
    categories: dict[str, list[str]] = {}

    if not base_dir.exists():
        return categories

    for category_dir in base_dir.iterdir():
        if not category_dir.is_dir():
            continue

        category_name = category_dir.name

        # Skip excluded directories
        if category_name in _EXCLUDED_DIRS or category_name.startswith("_"):
            continue

        # Find all .md files (excluding _overview.md)
        tools = []
        for md_file in category_dir.glob("*.md"):
            if md_file.name.startswith("_"):
                continue  # Skip _overview.md and similar
            tool_name = md_file.stem
            tools.append(tool_name)

        if tools:
            # Sort tools alphabetically for consistent ordering
            categories[category_name] = sorted(tools)

    return categories


def discover_tool_categories() -> dict[str, list[str]]:
    """Discover all tool categories and their tools from the filesystem.

    Scans both source directory (prompts/tools/) and user directory
    (~/.balloons/prompts/tools/). User directory takes precedence for
    individual tool prompts, but categories are merged.

    Returns:
        Dict mapping category name to list of tool names.
        Results are cached - call clear_discovery_cache() to refresh.
    """
    global _discovery_cache

    if _discovery_cache is not None:
        return _discovery_cache

    # Start with source directory
    categories = _discover_tools_in_directory(_TOOL_PROMPTS_DIR)

    # Merge user directory (adds new categories, adds new tools to existing categories)
    user_categories = _discover_tools_in_directory(_USER_TOOL_PROMPTS_DIR)
    for category, tools in user_categories.items():
        if category in categories:
            # Merge tools, avoiding duplicates
            existing = set(categories[category])
            for tool in tools:
                if tool not in existing:
                    categories[category].append(tool)
            categories[category] = sorted(categories[category])
        else:
            categories[category] = tools

    _discovery_cache = categories
    return categories


def clear_discovery_cache() -> None:
    """Clear the tool discovery cache.

    Call this after adding/removing tool prompt files to refresh discovery.
    """
    global _discovery_cache
    _discovery_cache = None


# For backward compatibility, these reference discovered categories
def _get_tool_categories() -> dict[str, list[str]]:
    """Get tool categories (discovered from filesystem)."""
    return discover_tool_categories()


# Core file/shell tools (always available, no per-tool prompts needed)
CORE_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
]


def _compute_all_balloon_tools() -> Set[str]:
    """Compute set of all balloon tool names from discovered categories."""
    all_tools: Set[str] = set()
    for tools in discover_tool_categories().values():
        all_tools.update(tools)
    return all_tools


def _compute_all_tools() -> Set[str]:
    """Compute set of all tools including core."""
    return set(CORE_TOOLS) | _compute_all_balloon_tools()


# Backward compatibility properties - now computed from discovery
# Note: These are functions to ensure they reflect current discovery state
def get_all_balloon_tools() -> Set[str]:
    """Get set of all balloon tool names (discovered from filesystem)."""
    return _compute_all_balloon_tools()


def get_all_tools() -> Set[str]:
    """Get set of all tool names including core (discovered from filesystem)."""
    return _compute_all_tools()


# Legacy aliases for backward compatibility (computed on first access)
# These will be populated lazily
ALL_BALLOON_TOOLS: Set[str] = set()  # Use get_all_balloon_tools() instead
ALL_TOOLS: Set[str] = set()  # Use get_all_tools() instead

# Legacy alias for backward compatibility - returns discovered categories
# Code should use discover_tool_categories() or get_tools_in_category() instead
TOOL_CATEGORIES: dict[str, list[str]] = {}  # Populated on init

# Populate legacy sets/dicts on module load
def _init_legacy_data():
    global ALL_BALLOON_TOOLS, ALL_TOOLS, TOOL_CATEGORIES
    ALL_BALLOON_TOOLS = _compute_all_balloon_tools()
    ALL_TOOLS = _compute_all_tools()
    TOOL_CATEGORIES = discover_tool_categories()

_init_legacy_data()

# Default enabled tools - core tools plus balloon essentials
# Users can expand this in config or per-session
# NOTE: This is a LIST - order determines prompt order!
DEFAULT_ENABLED_TOOLS: list[str] = [
    # Core file/shell tools (no prompts, but tracked for availability)
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
    # Domain plugins
    "load_domain",
    "unload_domain",
    "list_domains",
]

# Set version for quick membership checks
DEFAULT_ENABLED_TOOLS_SET: Set[str] = set(DEFAULT_ENABLED_TOOLS)


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
    enabled_tools: Optional[Sequence[str]] = None,
    include_critical_usage: bool = True,
    backend_type: str = "openai",
) -> str:
    """Build tool documentation prompt for enabled tools.

    The order of tools in enabled_tools determines the prompt order.
    Category overviews are inserted when a tool from that category first appears.

    Args:
        enabled_tools: Ordered sequence of tool names. None uses DEFAULT_ENABLED_TOOLS.
                       Can be a list (ordered) or set (uses default category order).
        include_critical_usage: Whether to include the critical usage template.
        backend_type: "claude" or "openai" - determines whether to include
                      balloons-tool XML format instructions (Claude only).

    Returns:
        Combined tool documentation as markdown string.
    """
    if enabled_tools is None:
        enabled_tools = DEFAULT_ENABLED_TOOLS

    # Convert set to list using default category order
    if isinstance(enabled_tools, set):
        enabled_tools = _order_tools_by_category(enabled_tools)

    parts = []

    # Include critical usage template
    if include_critical_usage:
        critical = _load_template("tool_usage_critical")
        if critical:
            parts.append(critical)
            parts.append("---\n")

    # For Claude backend, include balloons-tool XML format instructions
    if backend_type == "claude":
        balloons_format = _load_template("balloons_tool_format")
        if balloons_format:
            parts.append(balloons_format)
            parts.append("---\n")

    # Track which category overviews we've already included
    included_categories: set[str] = set()

    # Build prompt in the order of enabled_tools
    for tool_name in enabled_tools:
        category = get_category_for_tool(tool_name)
        if not category:
            # Core tool or unknown - no prompt file
            continue

        # Include category overview on first encounter
        if category not in included_categories:
            overview = _load_category_overview(category)
            if overview:
                parts.append(overview)
            included_categories.add(category)

        # Include the tool's prompt
        prompt = _load_tool_prompt(category, tool_name)
        if prompt:
            parts.append(prompt)

    return "\n".join(parts)


def _order_tools_by_category(tools: Set[str]) -> list[str]:
    """Order a set of tools by their category order.

    Used when a set is passed to maintain backward compatibility.
    """
    result = []
    categories = discover_tool_categories()
    for category, cat_tools in categories.items():
        for tool in cat_tools:
            if tool in tools:
                result.append(tool)
    # Add any tools not in categories (core tools, etc.)
    for tool in tools:
        if tool not in result:
            result.append(tool)
    return result


def get_tools_in_category(category: str) -> list[str]:
    """Get tool names for a category (discovered from filesystem)."""
    return discover_tool_categories().get(category, [])


def get_all_categories() -> list[str]:
    """Get all category names (discovered from filesystem)."""
    return list(discover_tool_categories().keys())


def get_category_for_tool(tool_name: str) -> Optional[str]:
    """Get the category a tool belongs to (discovered from filesystem)."""
    for category, tools in discover_tool_categories().items():
        if tool_name in tools:
            return category
    return None


def get_default_enabled_tools() -> list[str]:
    """Get the default enabled tools as a list (preserving order)."""
    return list(DEFAULT_ENABLED_TOOLS)
