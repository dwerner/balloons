"""Supervisor configuration for remote hosts and process management.

This module handles the ~/.balloons/supervisor.yaml configuration which defines:
- Hosts (local and SSH-accessible remote machines)
- Backend-to-host mappings (which LLM backend runs on which host)
- LSP server definitions (language servers for code intelligence)

The supervisor config is separate from the main config.yaml to keep concerns
separated and allow independent evolution.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import aiofiles
import yaml


@dataclass
class LSPServerConfig:
    """Configuration for a language server.

    Attributes:
        name: Server identifier (e.g., "python", "typescript", "rust")
        command: Shell command to start the server (must support --stdio)
        extensions: File extensions this server handles (e.g., [".py", ".pyi"])
        languages: Language identifiers for LSP (e.g., ["python", "pythonpath"])
        idle_timeout_seconds: Stop server after this many seconds of inactivity (0 = never)
        memory_limit_mb: Memory limit in MB (0 = no limit)
        root_patterns: Files/dirs that indicate project root (e.g., ["pyproject.toml"])
        initialization_options: Extra options passed during LSP initialize
    """

    name: str
    command: str
    extensions: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    idle_timeout_seconds: int = 300  # 5 minutes default
    memory_limit_mb: int = 0  # No limit by default
    root_patterns: list[str] = field(default_factory=list)
    initialization_options: dict = field(default_factory=dict)

    def validate(self) -> None:
        """Validate LSP server configuration.

        Raises:
            ValueError: If required fields are missing.
        """
        if not self.command:
            raise ValueError(f"LSP server '{self.name}' requires 'command' field")
        if not self.extensions and not self.languages:
            raise ValueError(
                f"LSP server '{self.name}' requires 'extensions' or 'languages' field"
            )


@dataclass
class HostConfig:
    """Configuration for a managed host.

    Attributes:
        name: Host identifier (e.g., "gpu-box", "local")
        type: Host type - "local" or "ssh"
        host: Hostname or IP address (for SSH hosts)
        user: SSH username (for SSH hosts)
        port: SSH port (default 22, for SSH hosts)
        tags: List of tags for querying (e.g., ["docker", "ml", "amd"])
        description: Human-readable description
    """

    name: str
    type: str = "local"  # "local" or "ssh"
    host: Optional[str] = None
    user: Optional[str] = None
    port: int = 22
    tags: list[str] = field(default_factory=list)
    description: Optional[str] = None

    def validate(self) -> None:
        """Validate host configuration.

        Raises:
            ValueError: If SSH host is missing required fields.
        """
        if self.type == "ssh":
            if not self.host:
                raise ValueError(f"SSH host '{self.name}' requires 'host' field")
            if not self.user:
                raise ValueError(f"SSH host '{self.name}' requires 'user' field")
        elif self.type != "local":
            raise ValueError(f"Unknown host type '{self.type}' for host '{self.name}'")

    def ssh_target(self) -> str:
        """Get the SSH target string (user@host).

        Returns:
            SSH target string for use with ssh command.

        Raises:
            ValueError: If not an SSH host.
        """
        if self.type != "ssh":
            raise ValueError(f"Host '{self.name}' is not an SSH host")
        return f"{self.user}@{self.host}"

    def ssh_args(self) -> list[str]:
        """Get SSH command arguments for this host.

        Returns:
            List of arguments for ssh command (excluding the command to run).
        """
        if self.type != "ssh":
            raise ValueError(f"Host '{self.name}' is not an SSH host")

        args = []
        if self.port != 22:
            args.extend(["-p", str(self.port)])
        args.append(self.ssh_target())
        return args


@dataclass
class SupervisorConfig:
    """Supervisor configuration for hosts and process management.

    Attributes:
        hosts: Dictionary of host configurations by name
        backend_hosts: Mapping of backend names to host names
        lsp_servers: Dictionary of LSP server configurations by name
    """

    hosts: dict[str, HostConfig] = field(default_factory=dict)
    backend_hosts: dict[str, str] = field(default_factory=dict)
    lsp_servers: dict[str, LSPServerConfig] = field(default_factory=dict)
    _config_path: Optional[Path] = field(default=None, repr=False)

    @classmethod
    def default_config_path(cls) -> Path:
        """Get the default config file path."""
        return Path.home() / ".balloons" / "supervisor.yaml"

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "SupervisorConfig":
        """Load supervisor configuration from file.

        Args:
            path: Path to config file. If None, uses default location.

        Returns:
            SupervisorConfig instance. Returns default config if file doesn't exist.
        """
        config_path = path or cls.default_config_path()

        if not config_path.exists():
            # Return default config with just local host
            return cls(
                hosts={"local": HostConfig(name="local", type="local")},
                _config_path=config_path,
            )

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        return cls._build_from_data(data, config_path)

    @classmethod
    async def load_async(cls, path: Optional[Path] = None) -> "SupervisorConfig":
        """Async version of load()."""
        config_path = path or cls.default_config_path()

        if not config_path.exists():
            return cls(
                hosts={"local": HostConfig(name="local", type="local")},
                _config_path=config_path,
            )

        async with aiofiles.open(config_path, encoding="utf-8") as f:
            content = await f.read()

        data = yaml.safe_load(content) or {}
        return cls._build_from_data(data, config_path)

    @classmethod
    def _build_from_data(cls, data: dict, path: Path) -> "SupervisorConfig":
        """Build config from parsed YAML data."""
        hosts = {}

        # Always include local host
        hosts["local"] = HostConfig(name="local", type="local")

        # Parse host definitions
        for name, host_data in data.get("hosts", {}).items():
            if name == "local":
                # Allow overriding local host tags/description
                if host_data:
                    hosts["local"] = HostConfig(
                        name="local",
                        type="local",
                        tags=host_data.get("tags", []),
                        description=host_data.get("description"),
                    )
                continue

            if host_data is None:
                host_data = {}

            host = HostConfig(
                name=name,
                type=host_data.get("type", "ssh"),
                host=host_data.get("host"),
                user=host_data.get("user"),
                port=host_data.get("port", 22),
                tags=host_data.get("tags", []),
                description=host_data.get("description"),
            )
            host.validate()
            hosts[name] = host

        # Parse backend-to-host mappings
        backend_hosts = data.get("backend_hosts", {})

        # Parse LSP server definitions
        lsp_servers = cls._parse_lsp_servers(data.get("lsp_servers", {}))

        return cls(
            hosts=hosts,
            backend_hosts=backend_hosts,
            lsp_servers=lsp_servers,
            _config_path=path,
        )

    @classmethod
    def _parse_lsp_servers(cls, lsp_data: dict) -> dict[str, LSPServerConfig]:
        """Parse LSP server definitions from config data.

        Includes built-in defaults that can be overridden.
        """
        # Default LSP servers (can be overridden by config)
        defaults = {
            "python": LSPServerConfig(
                name="python",
                command="pyright-langserver --stdio",
                extensions=[".py", ".pyi"],
                languages=["python"],
                root_patterns=["pyproject.toml", "setup.py", "requirements.txt"],
            ),
            "typescript": LSPServerConfig(
                name="typescript",
                command="typescript-language-server --stdio",
                extensions=[".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"],
                languages=["typescript", "typescriptreact", "javascript", "javascriptreact"],
                root_patterns=["package.json", "tsconfig.json"],
            ),
            "rust": LSPServerConfig(
                name="rust",
                command="rust-analyzer",
                extensions=[".rs"],
                languages=["rust"],
                idle_timeout_seconds=600,  # RA is slow to start
                root_patterns=["Cargo.toml"],
            ),
            "go": LSPServerConfig(
                name="go",
                command="gopls",
                extensions=[".go"],
                languages=["go"],
                root_patterns=["go.mod"],
            ),
        }

        servers = dict(defaults)

        # Parse and merge user config
        for name, server_data in lsp_data.items():
            if server_data is None:
                # Explicitly disabled
                servers.pop(name, None)
                continue

            if not isinstance(server_data, dict):
                continue

            # Check if this is disabling a default
            if server_data.get("enabled") is False:
                servers.pop(name, None)
                continue

            server = LSPServerConfig(
                name=name,
                command=server_data.get("command", defaults.get(name, LSPServerConfig(name=name, command="")).command),
                extensions=server_data.get("extensions", defaults.get(name, LSPServerConfig(name=name, command="")).extensions),
                languages=server_data.get("languages", defaults.get(name, LSPServerConfig(name=name, command="")).languages),
                idle_timeout_seconds=server_data.get("idle_timeout_seconds", 300),
                memory_limit_mb=server_data.get("memory_limit_mb", 0),
                root_patterns=server_data.get("root_patterns", defaults.get(name, LSPServerConfig(name=name, command="")).root_patterns),
                initialization_options=server_data.get("initialization_options", {}),
            )
            if server.command:  # Only validate if command is set
                server.validate()
                servers[name] = server

        return servers

    def get_host(self, name: str) -> HostConfig:
        """Get a host configuration by name.

        Args:
            name: Host name

        Returns:
            HostConfig for the host

        Raises:
            KeyError: If host not found
        """
        if name not in self.hosts:
            raise KeyError(f"Unknown host: {name}. Available: {list(self.hosts.keys())}")
        return self.hosts[name]

    def query_hosts(
        self,
        tags: Optional[list[str]] = None,
        host_type: Optional[str] = None,
    ) -> list[HostConfig]:
        """Query hosts by tags and/or type.

        Args:
            tags: List of tags to filter by (host must have ALL tags)
            host_type: Host type to filter by ("local" or "ssh")

        Returns:
            List of matching HostConfig objects
        """
        results = []

        for host in self.hosts.values():
            # Filter by type
            if host_type and host.type != host_type:
                continue

            # Filter by tags (must have ALL specified tags)
            if tags:
                if not all(tag in host.tags for tag in tags):
                    continue

            results.append(host)

        return results

    def get_host_for_backend(self, backend_name: str) -> Optional[HostConfig]:
        """Get the host that runs a specific backend.

        Args:
            backend_name: Name of the backend (from config.yaml)

        Returns:
            HostConfig if mapping exists, None otherwise
        """
        host_name = self.backend_hosts.get(backend_name)
        if host_name and host_name in self.hosts:
            return self.hosts[host_name]
        return None

    def get_lsp_server(self, name: str) -> Optional[LSPServerConfig]:
        """Get an LSP server configuration by name.

        Args:
            name: Server name (e.g., "python", "typescript")

        Returns:
            LSPServerConfig if found, None otherwise
        """
        return self.lsp_servers.get(name)

    def get_lsp_server_for_file(self, file_path: str) -> Optional[LSPServerConfig]:
        """Get the LSP server that handles a given file.

        Args:
            file_path: Path to a file

        Returns:
            LSPServerConfig if a matching server is found, None otherwise
        """
        # Get file extension
        ext = Path(file_path).suffix.lower()
        if not ext:
            return None

        for server in self.lsp_servers.values():
            if ext in server.extensions:
                return server

        return None

    def get_lsp_server_for_language(self, language_id: str) -> Optional[LSPServerConfig]:
        """Get the LSP server for a language ID.

        Args:
            language_id: LSP language identifier (e.g., "python", "typescript")

        Returns:
            LSPServerConfig if found, None otherwise
        """
        for server in self.lsp_servers.values():
            if language_id in server.languages:
                return server
        return None

    def list_lsp_servers(self) -> list[LSPServerConfig]:
        """Get all configured LSP servers.

        Returns:
            List of all LSP server configurations
        """
        return list(self.lsp_servers.values())

    def to_dict(self) -> dict:
        """Convert config to dictionary for serialization."""
        hosts_data = {}
        for name, host in self.hosts.items():
            if name == "local" and host.type == "local" and not host.tags:
                # Skip default local host
                continue

            host_dict = {"type": host.type}
            if host.host:
                host_dict["host"] = host.host
            if host.user:
                host_dict["user"] = host.user
            if host.port != 22:
                host_dict["port"] = host.port
            if host.tags:
                host_dict["tags"] = host.tags
            if host.description:
                host_dict["description"] = host.description

            hosts_data[name] = host_dict

        return {
            "hosts": hosts_data,
            "backend_hosts": self.backend_hosts,
        }

    def save(self) -> None:
        """Save configuration to file."""
        path = self._config_path or self.default_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False)

    async def save_async(self) -> None:
        """Async version of save()."""
        path = self._config_path or self.default_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(yaml.safe_dump(self.to_dict(), default_flow_style=False))


# Global instance
_supervisor_config: Optional[SupervisorConfig] = None


def get_supervisor_config() -> SupervisorConfig:
    """Get the global supervisor configuration, loading if necessary."""
    global _supervisor_config
    if _supervisor_config is None:
        _supervisor_config = SupervisorConfig.load()
    return _supervisor_config


async def get_supervisor_config_async() -> SupervisorConfig:
    """Async version of get_supervisor_config()."""
    global _supervisor_config
    if _supervisor_config is None:
        _supervisor_config = await SupervisorConfig.load_async()
    return _supervisor_config


def reload_supervisor_config() -> SupervisorConfig:
    """Force reload of supervisor configuration."""
    global _supervisor_config
    _supervisor_config = SupervisorConfig.load()
    return _supervisor_config
