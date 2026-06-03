"""Per-turn system prompt building.

This module provides functions to build system prompts dynamically each turn,
allowing domain prompts, goal bindings, and other context to be fresh.

The system prompt is composed of multiple parts:
1. User's custom system prompt (from backend config)
2. Balloons tools documentation (per-tool or legacy monolithic)
3. Domain plugin prompts (from loaded domains)
4. Session-specific prompt files
5. Future: Goal binding context

Tool prompts can be built in two modes:
- Legacy: Load monolithic claude-balloons-tools.md or openai-balloons-tools.md
- Per-tool: Build from individual files in prompts/tools/ based on enabled_tools

Usage:
    from core.prompt_builder import build_system_prompt

    # Legacy mode (all tools):
    system_prompt = build_system_prompt(backend_type="openai")

    # Per-tool mode (selective):
    system_prompt = build_system_prompt(
        backend_type="openai",
        enabled_tools={"ask_user", "supervisor_start", "play_midi"},
    )
"""

import re
from pathlib import Path
from typing import Optional, Set, Sequence, TYPE_CHECKING

from config import BackendConfig

if TYPE_CHECKING:
    from session import Session


# Prompt directories - user dir takes precedence over source dir
_USER_PROMPTS_DIR = Path.home() / ".balloons" / "prompts"
_SOURCE_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Regex for include directives: <!-- #include path/to/file.md -->
_INCLUDE_PATTERN = re.compile(r'<!--\s*#include\s+(\S+)\s*-->')


def _get_prompt_path(filename: str) -> Path | None:
    """Get path to a prompt file, checking user dir first then source dir.

    Args:
        filename: Name of the prompt file

    Returns:
        Path to the file, or None if not found in either location.
    """
    # Check user directory first (~/.balloons/prompts/)
    user_path = _USER_PROMPTS_DIR / filename
    if user_path.exists():
        return user_path

    # Fall back to source directory
    source_path = _SOURCE_PROMPTS_DIR / filename
    if source_path.exists():
        return source_path

    return None


def _process_includes(content: str, base_dir: Path, seen: set[Path] | None = None) -> str:
    """Process #include directives in prompt content.

    Replaces <!-- #include path/to/file.md --> with the file contents.
    Paths are relative to prompts/ directory. Handles circular includes.

    Args:
        content: Prompt content with potential includes
        base_dir: Base directory for resolving relative paths
        seen: Set of already-included paths (for cycle detection)

    Returns:
        Content with includes expanded
    """
    if seen is None:
        seen = set()

    def replace_include(match: re.Match) -> str:
        include_path = match.group(1)
        # Resolve relative to prompts directory
        full_path = (base_dir / include_path).resolve()

        # Cycle detection
        if full_path in seen:
            return f"<!-- ERROR: circular include {include_path} -->"
        if not full_path.exists():
            return f"<!-- ERROR: include not found {include_path} -->"

        seen.add(full_path)
        try:
            included_content = full_path.read_text()
            # Recursively process includes in the included file
            return _process_includes(included_content, full_path.parent, seen)
        except Exception as e:
            return f"<!-- ERROR: failed to include {include_path}: {e} -->"

    return _INCLUDE_PATTERN.sub(replace_include, content)


def _load_prompt_file(filename: str) -> str:
    """Load a prompt file from user or source directory.

    Looks in ~/.balloons/prompts/ first, then falls back to source directory.
    Processes <!-- #include path/to/file.md --> directives.

    Args:
        filename: Name of the prompt file to load

    Returns:
        File contents with includes expanded, or empty string if not found
    """
    path = _get_prompt_path(filename)
    if path:
        try:
            content = path.read_text()
            # Process includes relative to the prompts directory
            return _process_includes(content, _SOURCE_PROMPTS_DIR)
        except Exception:
            pass
    return ""


def _load_balloons_tools_prompt(
    backend_type: str,
    enabled_tools: Optional[Sequence[str]] = None,
) -> str:
    """Load the balloons tools prompt using per-tool prompts.

    Args:
        backend_type: "claude", "openai", or "gemini" - determines whether to include
                      balloons-tool XML format instructions (Claude uses XML format,
                      OpenAI and Gemini use native function calling).
        enabled_tools: Ordered list of tool names. Order determines prompt order.
                       None means use default enabled tools.

    Returns:
        The balloons tools documentation prompt
    """
    from .tool_prompts import build_tool_prompts, DEFAULT_ENABLED_TOOLS

    # Use provided list or defaults (order matters!)
    tools_to_include = enabled_tools if enabled_tools is not None else DEFAULT_ENABLED_TOOLS
    # Gemini uses native function calling like OpenAI, so treat it the same
    effective_backend = "openai" if backend_type == "gemini" else backend_type
    return build_tool_prompts(tools_to_include, backend_type=effective_backend)


def _get_domain_prompt() -> str:
    """Get combined domain-level prompt fragments from all loaded domains."""
    try:
        from plugins.integration import get_domain_prompt
        return get_domain_prompt()
    except ImportError:
        return ""



def _get_domain_tool_prompt(enabled_tools: Optional[Sequence[str]] = None) -> str:
    """Get combined tool-level prompt fragments from all loaded domains."""
    try:
        from plugins.integration import get_domain_tool_prompt
        tools = list(enabled_tools) if enabled_tools is not None else None
        return get_domain_tool_prompt(tools)
    except ImportError:
        return ""


def _get_session_prompt_files_content(session: "Session | None") -> str:
    """Load content from session-specific prompt files.

    Args:
        session: Session with prompt_files list

    Returns:
        Combined content from all readable prompt files, or empty string
    """
    if not session or not session.prompt_files:
        return ""

    parts = []
    for file_path in session.prompt_files:
        path = Path(file_path)
        if path.exists():
            try:
                content = path.read_text()
                if content.strip():
                    # Add a header to identify which file this content came from
                    parts.append(f"## Session Prompt: {path.name}\n\n{content}")
            except Exception:
                pass  # Skip unreadable files

    return "\n\n".join(parts)


def build_system_prompt(
    backend_type: str = "claude",
    user_prompt: Optional[str] = None,
    session: "Session | None" = None,
    enabled_tools: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """Build the complete system prompt for a turn.

    This is called per-turn to ensure domain prompts and other dynamic
    context are fresh.

    Args:
        backend_type: "claude" or "openai" - determines which balloons tools
                      documentation to include
        user_prompt: Optional user-provided system prompt (from backend config)
        session: Optional session for session-specific prompts
        enabled_tools: Ordered list of tool names to include documentation for.
                       The order determines the order in the prompt.
                       None means use default enabled tools.

    Returns:
        Complete system prompt string, or None if no content
    """
    parts = []

    # 1. User's custom system prompt
    if user_prompt:
        parts.append(user_prompt)

    # 2. Balloons tools documentation
    balloons_prompt = _load_balloons_tools_prompt(backend_type, enabled_tools)
    if balloons_prompt:
        parts.append(balloons_prompt)

    # 3. Domain plugin prompts (domain-level only)
    domain_prompt = _get_domain_prompt()
    if domain_prompt:
        parts.append(domain_prompt)

    # 4. Domain plugin tool prompts (enabled tools only)
    domain_tool_prompt = _get_domain_tool_prompt(enabled_tools)
    if domain_tool_prompt:
        parts.append(domain_tool_prompt)

    # 5. Session-specific prompt files
    session_prompts = _get_session_prompt_files_content(session)
    if session_prompts:
        parts.append(session_prompts)

    # 5. Future: Goal binding context

    return "\n\n".join(parts) if parts else None


def build_system_prompt_for_backend(
    backend: BackendConfig,
    session: "Session | None" = None,
) -> Optional[str]:
    """Build system prompt using a BackendConfig.

    Convenience function that extracts the user prompt from the backend config.

    Args:
        backend: Backend configuration
        session: Optional session for session-specific prompts

    Returns:
        Complete system prompt string, or None if no content
    """
    backend_type = backend.type or "claude"
    user_prompt = backend.load_system_prompt()
    return build_system_prompt(
        backend_type=backend_type,
        user_prompt=user_prompt,
        session=session,
    )
