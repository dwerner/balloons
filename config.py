"""Configuration management for Balloons."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class BackendConfig:
    """Configuration for an LLM backend."""
    name: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


@dataclass
class Config:
    """Balloons configuration."""
    default_backend: str = "claude"
    backends: dict[str, BackendConfig] = field(default_factory=dict)
    debug_log_file: Optional[str] = None  # Path to persist debug logs

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from file.

        Search order:
        1. BALLOONS_CONFIG environment variable
        2. ./config/balloons.yaml (project directory)
        3. ~/.config/balloons/config.yaml
        4. Default configuration (claude backend)
        """
        config_paths = [
            os.environ.get("BALLOONS_CONFIG"),
            Path.home() / ".balloons" / "config.yaml",
        ]

        for path in config_paths:
            if path and Path(path).exists():
                return cls._load_from_file(Path(path))

        # Default: just claude backend
        return cls(
            default_backend="claude",
            backends={"claude": BackendConfig(name="claude")}
        )

    @classmethod
    def _load_from_file(cls, path: Path) -> "Config":
        """Load configuration from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        backends = {}
        for name, backend_data in data.get("backends", {}).items():
            if backend_data is None:
                backend_data = {}
            backends[name] = BackendConfig(
                name=name,
                base_url=backend_data.get("base_url"),
                api_key=backend_data.get("api_key"),
                model=backend_data.get("model"),
            )

        # Ensure claude backend always exists
        if "claude" not in backends:
            backends["claude"] = BackendConfig(name="claude")

        return cls(
            default_backend=data.get("default_backend", "claude"),
            backends=backends,
            debug_log_file=data.get("debug_log_file"),
        )

    def get_backend(self, name: Optional[str] = None) -> BackendConfig:
        """Get a backend configuration by name, or the default."""
        backend_name = name or self.default_backend
        if backend_name not in self.backends:
            raise ValueError(f"Unknown backend: {backend_name}. Available: {list(self.backends.keys())}")
        return self.backends[backend_name]

    def get_env_for_backend(self, name: Optional[str] = None) -> dict[str, str]:
        """Get environment variables to set for a backend."""
        backend = self.get_backend(name)
        env = {}

        if backend.base_url:
            env["ANTHROPIC_BASE_URL"] = backend.base_url
        if backend.api_key:
            env["ANTHROPIC_API_KEY"] = backend.api_key

        return env


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration, loading it if necessary."""
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def set_backend(name: str) -> None:
    """Set the active backend for this session."""
    config = get_config()
    if name not in config.backends:
        raise ValueError(f"Unknown backend: {name}. Available: {list(config.backends.keys())}")
    config.default_backend = name
