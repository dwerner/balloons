"""Per-turn system prompt building.

This module provides functions to build system prompts dynamically each turn,
allowing domain prompts, goal bindings, and other context to be fresh.

The system prompt is composed of multiple parts:
1. User's custom system prompt (from backend config)
2. Balloons tools documentation (Claude or OpenAI style)
3. Domain plugin prompts (from loaded domains)
4. Future: Goal binding context, session-specific injections

Usage:
    from core.prompt_builder import build_system_prompt

    # In runner.stream_response():
    system_prompt = build_system_prompt(backend_type="claude")
"""

import re
from pathlib import Path
from typing import Optional

from config import BackendConfig


# Prompt directories - user dir takes precedence over source dir
_USER_PROMPTS_DIR = Path.home() / ".balloons" / "prompts"
_SOURCE_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Prompt filenames
_CLAUDE_BALLOONS_TOOLS_FILENAME = "claude-balloons-tools.md"
_OPENAI_BALLOONS_TOOLS_FILENAME = "openai-balloons-tools.md"

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


def _load_balloons_tools_prompt(backend_type: str) -> str:
    """Load the backend-appropriate balloons tools prompt.

    Args:
        backend_type: "claude" or "openai"

    Returns:
        The balloons tools documentation prompt
    """
    if backend_type == "openai":
        return _load_prompt_file(_OPENAI_BALLOONS_TOOLS_FILENAME)
    else:
        return _load_prompt_file(_CLAUDE_BALLOONS_TOOLS_FILENAME)


def _get_domain_prompt() -> str:
    """Get combined prompt fragments from all loaded domains.

    Returns:
        Combined prompt string, or empty string if no domains loaded
    """
    try:
        from plugins.integration import get_domain_prompt
        return get_domain_prompt()
    except ImportError:
        return ""


def build_system_prompt(
    backend_type: str = "claude",
    user_prompt: Optional[str] = None,
) -> Optional[str]:
    """Build the complete system prompt for a turn.

    This is called per-turn to ensure domain prompts and other dynamic
    context are fresh.

    Args:
        backend_type: "claude" or "openai" - determines which balloons tools
                      documentation to include
        user_prompt: Optional user-provided system prompt (from backend config)

    Returns:
        Complete system prompt string, or None if no content
    """
    parts = []

    # 1. User's custom system prompt
    if user_prompt:
        parts.append(user_prompt)

    # 2. Balloons tools documentation
    balloons_prompt = _load_balloons_tools_prompt(backend_type)
    if balloons_prompt:
        parts.append(balloons_prompt)

    # 3. Domain plugin prompts (from currently loaded domains)
    domain_prompt = _get_domain_prompt()
    if domain_prompt:
        parts.append(domain_prompt)

    # 4. Future: Goal binding context
    # 5. Future: Session-specific injections

    return "\n\n".join(parts) if parts else None


def build_system_prompt_for_backend(backend: BackendConfig) -> Optional[str]:
    """Build system prompt using a BackendConfig.

    Convenience function that extracts the user prompt from the backend config.

    Args:
        backend: Backend configuration

    Returns:
        Complete system prompt string, or None if no content
    """
    backend_type = backend.type or "claude"
    user_prompt = backend.load_system_prompt()
    return build_system_prompt(backend_type=backend_type, user_prompt=user_prompt)
