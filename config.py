"""Configuration management for Balloons."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class BackendConfig:
    """Configuration for an LLM backend.

    Attributes:
        name: Backend identifier
        type: Backend type - "claude" (CLI subprocess) or "openai" (OpenAI-compatible API)
        base_url: API base URL (required for openai type, optional for claude)
        api_key: API key (supports ${ENV_VAR} syntax)
        model: Model identifier (required for openai type)
    """
    name: str
    type: str = "claude"  # "claude" or "openai"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


@dataclass
class Config:
    """Balloons configuration."""
    default_backend: str = "claude"
    backends: dict[str, BackendConfig] = field(default_factory=dict)
    debug_log_file: Optional[str] = None  # Path to persist debug logs
    session_sort_order: str = "modified_desc"  # Default sort order for sessions
    _config_path: Optional[Path] = field(default=None, repr=False)  # Where config was loaded from

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
                type=backend_data.get("type", "claude"),
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
            session_sort_order=data.get("session_sort_order", "modified_desc"),
            _config_path=path,
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

    def save(self) -> None:
        """Save configuration to file.

        Only saves user-modifiable settings (session_sort_order, etc).
        Creates config file if it doesn't exist.
        """
        # Determine path to save to
        if self._config_path:
            path = self._config_path
        else:
            # Default to ~/.balloons/config.yaml
            path = Path.home() / ".balloons" / "config.yaml"

        # Load existing data if file exists, to preserve other settings
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}
            path.parent.mkdir(parents=True, exist_ok=True)

        # Update user-modifiable settings
        data["session_sort_order"] = self.session_sort_order

        with open(path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)


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
