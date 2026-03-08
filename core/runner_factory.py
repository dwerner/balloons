"""Factory for creating LLM runners based on backend configuration."""

import os
import re
from pathlib import Path

from config import BackendConfig
from .base_runner import BaseRunner

# Prompt directories - user dir takes precedence over source dir
_USER_PROMPTS_DIR = Path.home() / ".balloons" / "prompts"
_SOURCE_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Prompt filenames
_CLAUDE_BALLOONS_TOOLS_FILENAME = "claude-balloons-tools.md"
_OPENAI_BALLOONS_TOOLS_FILENAME = "openai-balloons-tools.md"


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


def ensure_prompts_installed() -> None:
    """Copy default prompts to user directory if missing or outdated.

    Creates ~/.balloons/prompts/ and copies default prompts from the
    source directory if they don't exist or are older than the source.
    """
    _USER_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

    # List of prompts to install
    prompts = [_CLAUDE_BALLOONS_TOOLS_FILENAME, _OPENAI_BALLOONS_TOOLS_FILENAME]

    for filename in prompts:
        user_path = _USER_PROMPTS_DIR / filename
        source_path = _SOURCE_PROMPTS_DIR / filename

        if not source_path.exists():
            continue

        # Copy if user file doesn't exist or source is newer
        should_copy = not user_path.exists()
        if not should_copy and user_path.exists():
            should_copy = source_path.stat().st_mtime > user_path.stat().st_mtime

        if should_copy:
            user_path.write_text(source_path.read_text())


# Regex for include directives: <!-- #include path/to/file.md -->
_INCLUDE_PATTERN = re.compile(r'<!--\s*#include\s+(\S+)\s*-->')


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


def _load_claude_balloons_tools_prompt() -> str:
    """Load the Claude-specific balloons tools prompt from file.

    This prompt instructs Claude to use XML-style <balloons-tool> tags for
    workflow and link navigation tools.
    """
    return _load_prompt_file(_CLAUDE_BALLOONS_TOOLS_FILENAME)


def _load_openai_balloons_tools_prompt() -> str:
    """Load the OpenAI-specific balloons tools prompt from file.

    This prompt documents the supervisor and other Balloons tools
    for OpenAI-compatible backends that use native function calling.
    """
    return _load_prompt_file(_OPENAI_BALLOONS_TOOLS_FILENAME)


def validate_backend_config(backend: BackendConfig) -> str | None:
    """Validate a backend configuration before creating a runner.

    Args:
        backend: Backend configuration to validate

    Returns:
        None if valid, error message string if invalid
    """
    backend_type = backend.type or "claude"

    if backend_type == "openai":
        if not backend.base_url:
            return f"Backend '{backend.name}' requires base_url for type 'openai'"
        # Note: model is optional for local servers like llama.cpp that only have one model loaded
    elif backend_type != "claude":
        return f"Unknown backend type: {backend_type}. Valid types: 'claude', 'openai'"

    return None


def resolve_env_var(value: str) -> str:
    """Resolve environment variable references in a string.

    Supports ${VAR_NAME} syntax. Returns the original value if no match
    or if the environment variable is not set.

    Args:
        value: String potentially containing ${VAR_NAME}

    Returns:
        Resolved string with env var substituted
    """
    if not value:
        return value

    # Match ${VAR_NAME} pattern
    match = re.match(r'^\$\{([^}]+)\}$', value)
    if match:
        var_name = match.group(1)
        return os.environ.get(var_name, value)

    return value


def create_runner(backend: BackendConfig) -> BaseRunner:
    """Create the appropriate runner for a backend configuration.

    Args:
        backend: Backend configuration

    Returns:
        A BaseRunner instance (ClaudeRunner or OpenAICompatibleRunner)

    Raises:
        ValueError: If backend type is invalid or required fields are missing
    """
    backend_type = backend.type or "claude"

    # Build system prompt from user's custom prompt
    parts = []
    user_prompt = backend.load_system_prompt()
    if user_prompt:
        parts.append(user_prompt)

    if backend_type == "openai":
        # OpenAI-compatible backend (OpenRouter, llamacpp, etc.)
        # Uses native function calling for tools - add documentation prompt
        from .openai_runner import OpenAICompatibleRunner

        if not backend.base_url:
            raise ValueError(f"Backend '{backend.name}' requires base_url for type 'openai'")

        api_key = resolve_env_var(backend.api_key or "")

        # Model defaults to "default" for local servers like llama.cpp that ignore this field
        model = backend.model or "default"

        # Add OpenAI-specific tool documentation prompt
        balloons_prompt = _load_openai_balloons_tools_prompt()
        if balloons_prompt:
            parts.append(balloons_prompt)

        # Add domain plugin prompts
        try:
            from plugins.integration import get_domain_prompt
            domain_prompt = get_domain_prompt()
            if domain_prompt:
                parts.append(domain_prompt)
        except ImportError:
            pass  # Plugin system not available

        system_prompt = "\n\n".join(parts) if parts else None

        return OpenAICompatibleRunner(
            base_url=backend.base_url,
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            context_window=backend.context_window,
        )

    elif backend_type == "claude":
        # Claude CLI backend
        # Add Claude-specific tool prompts for XML-style <balloons-tool> calls
        balloons_prompt = _load_claude_balloons_tools_prompt()
        if balloons_prompt:
            parts.append(balloons_prompt)

        # Add domain plugin prompts
        try:
            from plugins.integration import get_domain_prompt
            domain_prompt = get_domain_prompt()
            if domain_prompt:
                parts.append(domain_prompt)
        except ImportError:
            pass  # Plugin system not available

        system_prompt = "\n\n".join(parts) if parts else None

        from claude_runner import ClaudeRunner

        # Build environment for Claude CLI
        env = {}
        if backend.base_url:
            env["ANTHROPIC_BASE_URL"] = backend.base_url
        if backend.api_key:
            env["ANTHROPIC_API_KEY"] = resolve_env_var(backend.api_key)

        return ClaudeRunner(
            backend_env=env if env else None,
            system_prompt=system_prompt,
            context_window=backend.context_window,
        )

    else:
        raise ValueError(f"Unknown backend type: {backend_type}. Valid types: 'claude', 'openai'")
