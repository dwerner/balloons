"""Factory for creating LLM runners based on backend configuration."""

import os
import re
from pathlib import Path

from config import BackendConfig
from .base_runner import BaseRunner, PLACEHOLDER_API_KEY

# Prompt directories - user dir takes precedence over source dir
_USER_PROMPTS_DIR = Path.home() / ".balloons" / "prompts"
_SOURCE_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Prompt filenames
_CLAUDE_BALLOONS_TOOLS_FILENAME = "claude-balloons-tools.md"
_OPENAI_BALLOONS_TOOLS_FILENAME = "openai-balloons-tools.md"


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


def validate_backend_config(backend: BackendConfig) -> str | None:
    """Validate a backend configuration before creating a runner.

    Args:
        backend: Backend configuration to validate

    Returns:
        None if valid, error message string if invalid
    """
    backend_type = backend.type or "claude"

    if backend_type in {"openai", "openai_strict"}:
        if not backend.base_url:
            return f"Backend '{backend.name}' requires base_url for type '{backend_type}'"
        # Note: model is optional for local servers like llama.cpp that only have one model loaded
    elif backend_type == "gemini":
        if not backend.api_key:
            return f"Backend '{backend.name}' requires api_key for type 'gemini'"
        # Note: model defaults to gemini-2.5-flash if not specified
    elif backend_type == "ai_sdk":
        if not backend.base_url:
            return f"Backend '{backend.name}' requires base_url for type 'ai_sdk'"
        # Note: model is optional for local servers
    elif backend_type != "claude":
        return f"Unknown backend type: {backend_type}. Valid types: 'claude', 'openai', 'openai_strict', 'gemini', 'ai_sdk'"

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

    System prompts are now built per-turn by the runners to include fresh
    domain prompts and other dynamic context. We only pass the user's
    custom prompt here.

    Args:
        backend: Backend configuration

    Returns:
        A BaseRunner instance (ClaudeRunner, OpenAICompatibleRunner, or GeminiRunner)

    Raises:
        ValueError: If backend type is invalid or required fields are missing
    """
    backend_type = backend.type or "claude"

    # Load user's custom system prompt from backend config
    # The runners will combine this with balloons tools and domain prompts per-turn
    user_prompt = backend.load_system_prompt()

    if backend_type in {"openai", "openai_strict"}:
        # OpenAI-compatible backend (OpenRouter, llamacpp, etc.)
        if not backend.base_url:
            raise ValueError(f"Backend '{backend.name}' requires base_url for type '{backend_type}'")

        api_key = resolve_env_var(backend.api_key or "")

        # Model defaults to "default" for local servers like llama.cpp that ignore this field
        model = backend.model or "default"

        # The OpenAI SDK rejects an empty/missing key with "Missing credentials",
        # but local servers (llama.cpp, vLLM) don't check the Authorization header.
        # Send a placeholder so keyless backends still construct a client.
        api_key = api_key or PLACEHOLDER_API_KEY

        if backend_type == "openai_strict":
            from .strict_openai_runner import StrictOpenAICompatibleRunner

            return StrictOpenAICompatibleRunner(
                base_url=backend.base_url,
                api_key=api_key,
                model=model,
                user_prompt=user_prompt,
                context_window=backend.context_window,
            )

        from .openai_runner import OpenAICompatibleRunner

        return OpenAICompatibleRunner(
            base_url=backend.base_url,
            api_key=api_key,
            model=model,
            user_prompt=user_prompt,
            context_window=backend.context_window,
        )

    elif backend_type == "gemini":
        # Google Gemini backend
        from .gemini_runner import GeminiRunner

        if not backend.api_key:
            raise ValueError(f"Backend '{backend.name}' requires api_key for type 'gemini'")

        api_key = resolve_env_var(backend.api_key)
        model = backend.model or "gemini-2.5-flash"

        return GeminiRunner(
            api_key=api_key,
            model=model,
            user_prompt=user_prompt,
            context_window=backend.context_window or 200000,
        )

    elif backend_type == "ai_sdk":
        # AI SDK runner using Rust ai-sdk-openai-compatible crate
        from .ai_sdk_runner import AISDKRunner

        if not backend.base_url:
            raise ValueError(f"Backend '{backend.name}' requires base_url for type 'ai_sdk'")

        api_key = resolve_env_var(backend.api_key or "")
        model = backend.model or "default"

        return AISDKRunner(
            base_url=backend.base_url,
            model=model,
            api_key=api_key if api_key else None,
            user_prompt=user_prompt,
            context_window=backend.context_window,
        )

    elif backend_type == "claude":
        # Claude CLI backend
        from claude_runner import ClaudeRunner

        # Build environment for Claude CLI
        env = {}
        if backend.base_url:
            env["ANTHROPIC_BASE_URL"] = backend.base_url
        if backend.api_key:
            env["ANTHROPIC_API_KEY"] = resolve_env_var(backend.api_key)

        return ClaudeRunner(
            backend_env=env if env else None,
            user_prompt=user_prompt,
            context_window=backend.context_window,
            model=backend.model,
        )

    else:
        raise ValueError(f"Unknown backend type: {backend_type}. Valid types: 'claude', 'openai', 'openai_strict', 'gemini', 'ai_sdk'")
