"""Factory for creating LLM runners based on backend configuration."""

import os
import re
from pathlib import Path

from config import BackendConfig
from .base_runner import BaseRunner

# Prompt directories - user dir takes precedence over source dir
_USER_PROMPTS_DIR = Path.home() / ".balloons" / "prompts"
_SOURCE_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Claude-specific balloons tools prompt filename
_CLAUDE_BALLOONS_TOOLS_FILENAME = "claude-balloons-tools.md"


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
    """Copy default prompts to user directory if not present.

    Creates ~/.balloons/prompts/ and copies default prompts from the
    source directory if they don't already exist in the user directory.
    """
    _USER_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

    # List of prompts to install
    prompts = [_CLAUDE_BALLOONS_TOOLS_FILENAME]

    for filename in prompts:
        user_path = _USER_PROMPTS_DIR / filename
        if not user_path.exists():
            source_path = _SOURCE_PROMPTS_DIR / filename
            if source_path.exists():
                user_path.write_text(source_path.read_text())


def _load_claude_balloons_tools_prompt() -> str:
    """Load the Claude-specific balloons tools prompt from file.

    This prompt instructs Claude to use XML-style <balloons-tool> tags for
    workflow and link navigation tools. It's only used for Claude backends.
    OpenAI-compatible backends use native function calling via tools.py instead.

    Looks in ~/.balloons/prompts/ first, then falls back to source directory.
    """
    path = _get_prompt_path(_CLAUDE_BALLOONS_TOOLS_FILENAME)
    if path:
        try:
            return path.read_text()
        except Exception:
            pass
    return ""


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
        # Uses native function calling - no XML tool prompt needed
        from .openai_runner import OpenAICompatibleRunner

        if not backend.base_url:
            raise ValueError(f"Backend '{backend.name}' requires base_url for type 'openai'")

        api_key = resolve_env_var(backend.api_key or "")

        # Model defaults to "default" for local servers like llama.cpp that ignore this field
        model = backend.model or "default"

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
