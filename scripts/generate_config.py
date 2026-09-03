#!/usr/bin/env python3
"""Generate or regenerate ~/.balloons/config.yaml with sensible defaults.

This script:
- Reads API keys from environment variables
- Generates a secure JWT secret
- Sets up TLS if certs exist
- Optionally merges with existing config to preserve settings

Usage:
    python scripts/generate_config.py [--force] [--no-prompt]

Options:
    --force      Overwrite existing config without merging
    --no-prompt  Don't prompt for missing values, use defaults/env only
"""

import os
import sys
import secrets
import base64
from pathlib import Path

import yaml


BALLOONS_DIR = Path.home() / ".balloons"
CONFIG_PATH = BALLOONS_DIR / "config.yaml"
CERTS_DIR = BALLOONS_DIR / "certs"


def generate_jwt_secret() -> str:
    """Generate a cryptographically secure JWT secret."""
    return base64.b64encode(secrets.token_bytes(32)).decode()


def get_env_or_prompt(var_name: str, prompt_text: str, no_prompt: bool = False) -> str | None:
    """Get value from environment or prompt user."""
    value = os.environ.get(var_name)
    if value:
        print(f"  {var_name}: found in environment")
        return value

    if no_prompt:
        print(f"  {var_name}: not set")
        return None

    print(f"  {var_name}: not found in environment")
    user_input = input(f"  Enter {prompt_text} (or press Enter to skip): ").strip()
    return user_input if user_input else None


def check_certs_exist() -> bool:
    """Check if TLS certificates exist."""
    cert_path = CERTS_DIR / "dev.crt"
    key_path = CERTS_DIR / "dev.key"
    return cert_path.exists() and key_path.exists()


def load_existing_config() -> dict:
    """Load existing config if present."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def build_config(
    existing: dict,
    anthropic_key: str | None,
    openai_key: str | None,
    openrouter_key: str | None,
    jwt_secret: str,
    tls_enabled: bool,
    no_prompt: bool = False,
) -> dict:
    """Build the configuration dictionary."""

    config: dict = {}

    # Default backend
    config["default_backend"] = existing.get("default_backend", "claude")

    # Backends
    backends: dict = {}

    # Claude backend (always present)
    existing_claude = existing.get("backends", {}).get("claude", {})
    backends["claude"] = {
        "type": "claude",
        "context_window": existing_claude.get("context_window", 150000),
    }
    # Note: claude CLI uses ANTHROPIC_API_KEY env var directly

    # OpenAI backend
    if openai_key:
        existing_openai = existing.get("backends", {}).get("openai", {})
        backends["openai"] = {
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "${OPENAI_API_KEY}",
            "model": existing_openai.get("model", "gpt-4o"),
            "context_window": existing_openai.get("context_window", 128000),
        }
        if existing_openai.get("system_prompt"):
            backends["openai"]["system_prompt"] = existing_openai["system_prompt"]

    # OpenRouter backend
    if openrouter_key:
        existing_openrouter = existing.get("backends", {}).get("openrouter", {})
        backends["openrouter"] = {
            "type": "openai",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "${OPENROUTER_API_KEY}",
            "model": existing_openrouter.get("model", "anthropic/claude-sonnet-4"),
            "context_window": existing_openrouter.get("context_window", 200000),
        }
        if existing_openrouter.get("system_prompt"):
            backends["openrouter"]["system_prompt"] = existing_openrouter["system_prompt"]

    # Preserve any other backends from existing config
    for name, backend in existing.get("backends", {}).items():
        if name not in backends and backend:
            backends[name] = backend

    config["backends"] = backends

    # WebSocket server
    existing_ws = existing.get("websocket", {})
    config["websocket"] = {
        "enabled": existing_ws.get("enabled", True),
        "host": existing_ws.get("host", "0.0.0.0"),
        "port": existing_ws.get("port", 8700),
        "tls": {
            "enabled": tls_enabled,
            "cert_path": "~/.balloons/certs/dev.crt",
            "key_path": "~/.balloons/certs/dev.key",
        },
        "jwt": {
            "enabled": existing_ws.get("jwt", {}).get("enabled", True),
            "secret": existing_ws.get("jwt", {}).get("secret") or jwt_secret,
            "expiration_seconds": existing_ws.get("jwt", {}).get("expiration_seconds", 86400),
        },
    }

    # Auth
    existing_auth = existing.get("auth", {})
    existing_admin = existing_auth.get("admin", {})
    config["auth"] = {
        "admin": {
            "username": existing_admin.get("username", "admin"),
            "password": existing_admin.get("password", "changeme"),
        }
    }

    # Sounds (preserve existing)
    if "sounds" in existing:
        config["sounds"] = existing["sounds"]

    # TTS (preserve existing)
    if "tts" in existing:
        config["tts"] = existing["tts"]

    # Reports (preserve existing)
    if "reports" in existing:
        config["reports"] = existing["reports"]

    # Debug perf mode (preserve existing)
    if "debug_perf_mode" in existing:
        config["debug_perf_mode"] = existing["debug_perf_mode"]

    # Editor (preserve existing)
    if "editor" in existing:
        config["editor"] = existing["editor"]

    # Default enabled tools (preserve existing)
    if "default_enabled_tools" in existing:
        config["default_enabled_tools"] = existing["default_enabled_tools"]

    # Review backend (preserve existing)
    if "review_backend" in existing:
        config["review_backend"] = existing["review_backend"]

    return config


def main():
    force = "--force" in sys.argv
    no_prompt = "--no-prompt" in sys.argv

    print("Balloons Config Generator")
    print("=" * 40)

    # Ensure directory exists
    BALLOONS_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing config
    existing = {} if force else load_existing_config()
    if existing and not force:
        print(f"Found existing config at {CONFIG_PATH}")
        print("Will merge with existing settings (use --force to overwrite)")

    # Check for API keys
    print("\nChecking API keys...")
    anthropic_key = get_env_or_prompt(
        "ANTHROPIC_API_KEY",
        "Anthropic API key",
        no_prompt
    )
    openai_key = get_env_or_prompt(
        "OPENAI_API_KEY",
        "OpenAI API key",
        no_prompt
    )
    openrouter_key = get_env_or_prompt(
        "OPENROUTER_API_KEY",
        "OpenRouter API key",
        no_prompt
    )

    # Check TLS certs
    print("\nChecking TLS certificates...")
    tls_enabled = check_certs_exist()
    if tls_enabled:
        print(f"  Found certs in {CERTS_DIR}")
    else:
        print(f"  No certs found in {CERTS_DIR}")
        print("  Run: python scripts/generate_dev_certs.py to create them")

    # Generate JWT secret
    print("\nGenerating JWT secret...")
    existing_secret = existing.get("websocket", {}).get("jwt", {}).get("secret")
    if existing_secret and not force:
        print("  Using existing JWT secret")
        jwt_secret = existing_secret
    else:
        jwt_secret = generate_jwt_secret()
        print("  Generated new JWT secret")

    # Build config
    print("\nBuilding configuration...")
    config = build_config(
        existing=existing,
        anthropic_key=anthropic_key,
        openai_key=openai_key,
        openrouter_key=openrouter_key,
        jwt_secret=jwt_secret,
        tls_enabled=tls_enabled,
        no_prompt=no_prompt,
    )

    # Write config
    print(f"\nWriting config to {CONFIG_PATH}...")

    # Add header comment
    header = """# Balloons Configuration
# ----------------------
# Generated by scripts/generate_config.py
# See config/config.sample.yaml for all options

"""

    with open(CONFIG_PATH, "w") as f:
        f.write(header)
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)

    print("Done!")
    print("\nConfigured backends:")
    for name in config["backends"]:
        print(f"  - {name}")

    print(f"\nWebSocket: {'enabled' if config['websocket']['enabled'] else 'disabled'}")
    print(f"TLS: {'enabled' if config['websocket']['tls']['enabled'] else 'disabled'}")

    if not tls_enabled:
        print("\nNote: TLS is disabled. For HTTPS support, generate certs:")
        print("  python scripts/generate_dev_certs.py")

    if config["auth"]["admin"]["password"] == "changeme":
        print("\nWarning: Using default admin password 'changeme'")
        print("Change this in the config file for production use.")


if __name__ == "__main__":
    main()
