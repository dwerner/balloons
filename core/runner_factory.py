"""Factory for creating LLM runners based on backend configuration."""

import os
import re

from config import BackendConfig
from .base_runner import BaseRunner


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
        if not backend.model:
            raise ValueError(f"Backend '{backend.name}' requires model for type 'openai'")

        api_key = resolve_env_var(backend.api_key or "")

        # Load system prompt if configured
        system_prompt = backend.load_system_prompt()

        return OpenAICompatibleRunner(
            base_url=backend.base_url,
            api_key=api_key,
            model=backend.model,
            system_prompt=system_prompt,
        )

    elif backend_type == "claude":
        # Claude CLI backend (default)
        from claude_runner import ClaudeRunner

        # Build environment for Claude CLI
        env = {}
        if backend.base_url:
            env["ANTHROPIC_BASE_URL"] = backend.base_url
        if backend.api_key:
            env["ANTHROPIC_API_KEY"] = resolve_env_var(backend.api_key)

        # Load system prompt if configured
        system_prompt = backend.load_system_prompt()

        return ClaudeRunner(backend_env=env if env else None, system_prompt=system_prompt)

    else:
        raise ValueError(f"Unknown backend type: {backend_type}. Valid types: 'claude', 'openai'")
