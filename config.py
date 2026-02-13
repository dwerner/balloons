"""Configuration management for Balloons."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import aiofiles
import yaml

from tokenizer import count_tokens


@dataclass
class SoundsConfig:
    """Sound notification configuration.

    Attributes:
        enabled: Whether sound notifications are enabled
        done: Sound file for completion (in ~/.balloons/sounds/)
        error: Sound file for errors
        notification: Sound file for general notifications (e.g., input required)
    """
    enabled: bool = True
    done: str = "Chord.ogg"
    error: str = "Glitch.ogg"
    notification: str = "Polite.ogg"


@dataclass
class TTSConfig:
    """TTS configuration.

    Attributes:
        backend: Which TTS engine to use (say, espeak, piper, tortoise)
        voice: Voice identifier (backend-specific)
        speed: Speech rate multiplier (1.0 = normal)
        enabled: Whether TTS is enabled
        piper_model: Path to Piper .onnx model (for piper backend)
        tortoise_quality: Quality preset for Tortoise (ultra_fast, fast, standard, high_quality)
    """
    backend: str = "say"  # Default to macOS say
    voice: Optional[str] = None
    speed: float = 1.0
    enabled: bool = True
    piper_model: Optional[str] = None
    tortoise_quality: str = "fast"


@dataclass
class BackendConfig:
    """Configuration for an LLM backend.

    Attributes:
        name: Backend identifier
        type: Backend type - "claude" (CLI subprocess) or "openai" (OpenAI-compatible API)
        base_url: API base URL (required for openai type, optional for claude)
        api_key: API key (supports ${ENV_VAR} syntax)
        model: Model identifier (required for openai type)
        system_prompt: Path to system prompt file (supports ~ expansion)
    """
    name: str
    type: str = "claude"  # "claude" or "openai"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None  # Path to system prompt file
    context_window: int = 150000  # Max context tokens for this backend

    # Cached at runtime (not persisted)
    _system_prompt_content: Optional[str] = field(default=None, repr=False, compare=False)
    _system_prompt_tokens: int = field(default=0, repr=False, compare=False)

    def load_system_prompt(self) -> Optional[str]:
        """Load and cache system prompt from file.

        Returns:
            System prompt content, or None if not configured or file not found.
        """
        if self._system_prompt_content is not None:
            return self._system_prompt_content
        if not self.system_prompt:
            return None
        path = Path(self.system_prompt).expanduser()
        if path.exists():
            self._system_prompt_content = path.read_text()
            self._system_prompt_tokens = count_tokens(self._system_prompt_content)
        return self._system_prompt_content

    async def load_system_prompt_async(self) -> Optional[str]:
        """Async version of load_system_prompt()."""
        if self._system_prompt_content is not None:
            return self._system_prompt_content
        if not self.system_prompt:
            return None
        path = Path(self.system_prompt).expanduser()
        if path.exists():
            async with aiofiles.open(path, encoding="utf-8") as f:
                self._system_prompt_content = await f.read()
            self._system_prompt_tokens = count_tokens(self._system_prompt_content)
        return self._system_prompt_content

    def get_system_prompt_tokens(self) -> int:
        """Get the token count for the system prompt.

        Loads the prompt if not already cached.

        Returns:
            Token count, or 0 if no system prompt configured.
        """
        if self._system_prompt_content is None:
            self.load_system_prompt()
        return self._system_prompt_tokens


@dataclass
class Config:
    """Balloons configuration."""
    default_backend: str = "claude"
    backends: dict[str, BackendConfig] = field(default_factory=dict)
    debug_log_file: Optional[str] = None  # Path to persist debug logs
    debug_perf_mode: bool = False  # If true, only log PERF level and above (timing/markers)
    editor: Optional[str] = None  # Editor command (falls back to $VISUAL, $EDITOR, vi)
    last_view_session_id: Optional[str] = None  # Last viewed session ID
    last_view_turn_index: Optional[int] = None  # Last viewed turn index (0-based)
    tts: TTSConfig = field(default_factory=TTSConfig)  # TTS configuration
    sounds: SoundsConfig = field(default_factory=SoundsConfig)  # Sound notifications
    review_backend: Optional[str] = None  # Backend for session quality reviews (defaults to default_backend)
    _config_path: Optional[Path] = field(default=None, repr=False)  # Where config was loaded from

    def get_editor(self) -> str:
        """Get the editor command to use.

        Priority: config editor > $VISUAL > $EDITOR > vi
        """
        return self.editor or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"

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
    async def load_async(cls) -> "Config":
        """Async version of load()."""
        config_paths = [
            os.environ.get("BALLOONS_CONFIG"),
            Path.home() / ".balloons" / "config.yaml",
        ]

        for path in config_paths:
            if path and Path(path).exists():
                return await cls._load_from_file_async(Path(path))

        # Default: just claude backend
        return cls(
            default_backend="claude",
            backends={"claude": BackendConfig(name="claude")}
        )

    @classmethod
    def _build_config_from_data(cls, data: dict, path: Path) -> "Config":
        """Build Config from parsed YAML data."""
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
                system_prompt=backend_data.get("system_prompt"),
                context_window=backend_data.get("context_window", 150000),
            )

        # Ensure claude backend always exists
        if "claude" not in backends:
            backends["claude"] = BackendConfig(name="claude")

        # Load last_view as dict if present
        last_view = data.get("last_view", {})

        # Load TTS config
        tts_data = data.get("tts", {})
        tts_config = TTSConfig(
            backend=tts_data.get("backend", "say"),
            voice=tts_data.get("voice"),
            speed=tts_data.get("speed", 1.0),
            enabled=tts_data.get("enabled", True),
            piper_model=tts_data.get("piper_model"),
            tortoise_quality=tts_data.get("tortoise_quality", "fast"),
        )

        # Load sounds config
        sounds_data = data.get("sounds", {})
        sounds_config = SoundsConfig(
            enabled=sounds_data.get("enabled", True),
            done=sounds_data.get("done", "Chord.ogg"),
            error=sounds_data.get("error", "Glitch.ogg"),
            notification=sounds_data.get("notification", "Polite.ogg"),
        )

        return cls(
            default_backend=data.get("default_backend", "claude"),
            backends=backends,
            debug_log_file=data.get("debug_log_file"),
            debug_perf_mode=data.get("debug_perf_mode", False),
            editor=data.get("editor"),
            last_view_session_id=last_view.get("session_id") if last_view else None,
            last_view_turn_index=last_view.get("turn_index") if last_view else None,
            tts=tts_config,
            sounds=sounds_config,
            review_backend=data.get("review_backend"),
            _config_path=path,
        )

    @classmethod
    def _load_from_file(cls, path: Path) -> "Config":
        """Load configuration from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls._build_config_from_data(data, path)

    @classmethod
    async def _load_from_file_async(cls, path: Path) -> "Config":
        """Async version of _load_from_file()."""
        async with aiofiles.open(path, encoding="utf-8") as f:
            content = await f.read()
        data = yaml.safe_load(content) or {}
        return cls._build_config_from_data(data, path)

    def get_backend(self, name: Optional[str] = None) -> BackendConfig:
        """Get a backend configuration by name, or the default."""
        backend_name = name or self.default_backend
        if backend_name not in self.backends:
            raise ValueError(f"Unknown backend: {backend_name}. Available: {list(self.backends.keys())}")
        return self.backends[backend_name]

    def get_review_backend(self) -> BackendConfig:
        """Get the backend configuration for session quality reviews.

        Falls back to default_backend if review_backend is not configured.
        """
        backend_name = self.review_backend or self.default_backend
        return self.get_backend(backend_name)

    def get_env_for_backend(self, name: Optional[str] = None) -> dict[str, str]:
        """Get environment variables to set for a backend."""
        backend = self.get_backend(name)
        env = {}

        if backend.base_url:
            env["ANTHROPIC_BASE_URL"] = backend.base_url
        if backend.api_key:
            env["ANTHROPIC_API_KEY"] = backend.api_key

        return env

    def _get_save_path(self) -> Path:
        """Get the path to save config to."""
        if self._config_path:
            return self._config_path
        return Path.home() / ".balloons" / "config.yaml"

    def _build_save_data(self, existing_data: dict) -> dict:
        """Build data dict for saving, merging with existing data."""
        data = existing_data.copy()
        if self.last_view_session_id:
            data["last_view"] = {
                "session_id": self.last_view_session_id,
                "turn_index": self.last_view_turn_index,
            }
        elif "last_view" in data:
            del data["last_view"]
        return data

    def save(self) -> None:
        """Save configuration to file.

        Saves user-modifiable settings (last_view, etc).
        Creates config file if it doesn't exist.
        """
        path = self._get_save_path()

        # Load existing data if file exists, to preserve other settings
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}
            path.parent.mkdir(parents=True, exist_ok=True)

        data = self._build_save_data(data)

        with open(path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)

    async def save_async(self) -> None:
        """Async version of save()."""
        path = self._get_save_path()

        # Load existing data if file exists, to preserve other settings
        if path.exists():
            async with aiofiles.open(path, encoding="utf-8") as f:
                content = await f.read()
            data = yaml.safe_load(content) or {}
        else:
            data = {}
            path.parent.mkdir(parents=True, exist_ok=True)

        data = self._build_save_data(data)

        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(yaml.safe_dump(data, default_flow_style=False))


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration, loading it if necessary."""
    global _config
    if _config is None:
        _config = Config.load()
    return _config


async def get_config_async() -> Config:
    """Async version of get_config()."""
    global _config
    if _config is None:
        _config = await Config.load_async()
    return _config


def set_backend(name: str) -> None:
    """Set the active backend for this session."""
    config = get_config()
    if name not in config.backends:
        raise ValueError(f"Unknown backend: {name}. Available: {list(config.backends.keys())}")
    config.default_backend = name


def save_last_view(session_id: str, turn_index: Optional[int] = None) -> None:
    """Save the last viewed session and turn position."""
    config = get_config()
    config.last_view_session_id = session_id
    config.last_view_turn_index = turn_index
    config.save()


async def save_last_view_async(session_id: str, turn_index: Optional[int] = None) -> None:
    """Async version of save_last_view()."""
    config = await get_config_async()
    config.last_view_session_id = session_id
    config.last_view_turn_index = turn_index
    await config.save_async()
