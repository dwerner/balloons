"""Factory for creating LLM runners based on backend configuration."""

import os
import re
from pathlib import Path

from config import BackendConfig
from .base_runner import BaseRunner

# Load balloons tools prompt from file
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_BALLOONS_TOOLS_PROMPT_PATH = _PROMPTS_DIR / "balloons-tools.md"


def _load_balloons_tools_prompt() -> str:
    """Load the balloons tools prompt from file."""
    try:
        return _BALLOONS_TOOLS_PROMPT_PATH.read_text()
    except Exception:
        # Fallback if file not found
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
    elif backend_type not in ("claude", "claude-structured"):
        return f"Unknown backend type: {backend_type}. Valid types: 'claude', 'claude-structured', 'openai'"

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

    if backend_type == "openai":
        # OpenAI-compatible backend (OpenRouter, llamacpp, etc.)
        from .openai_runner import OpenAICompatibleRunner

        if not backend.base_url:
            raise ValueError(f"Backend '{backend.name}' requires base_url for type 'openai'")

        api_key = resolve_env_var(backend.api_key or "")

        # Load system prompt if configured
        system_prompt = backend.load_system_prompt()

        # Model defaults to "default" for local servers like llama.cpp that ignore this field
        model = backend.model or "default"

        return OpenAICompatibleRunner(
            base_url=backend.base_url,
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            context_window=backend.context_window,
        )

    elif backend_type in ("claude", "claude-structured"):
        # Claude CLI backend - always enables structured tools for link navigation
        from claude_runner import ClaudeRunner

        # Build environment for Claude CLI
        env = {}
        if backend.base_url:
            env["ANTHROPIC_BASE_URL"] = backend.base_url
        if backend.api_key:
            env["ANTHROPIC_API_KEY"] = resolve_env_var(backend.api_key)

        # Build system prompt: user's custom prompt + Balloons tool prompts
        parts = []
        user_prompt = backend.load_system_prompt()
        if user_prompt:
            parts.append(user_prompt)
        # Add Balloons-specific tool prompts (link navigation and propose_fork)
        balloons_prompt = _load_balloons_tools_prompt()
        if balloons_prompt:
            parts.append(balloons_prompt)
        system_prompt = "\n\n".join(parts) if parts else None

        return ClaudeRunner(
            backend_env=env if env else None,
            system_prompt=system_prompt,
            context_window=backend.context_window,
        )

    else:
        raise ValueError(f"Unknown backend type: {backend_type}. Valid types: 'claude', 'claude-structured', 'openai'")
