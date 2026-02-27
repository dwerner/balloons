"""WebSocket-exposed service for supervisor state.

This service provides access to:
- Host configuration and status
- Process management (list, start, stop)
- Backend-to-host mappings

It wraps the supervisor_config and supervisor_tools modules for web client access.
"""

import asyncio
import json
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from codegen import ws_service, ws_expose, ws_event, ws_type
from core.debug_log import debug_log
from supervisor_config import get_supervisor_config, reload_supervisor_config, HostConfig


@ws_type
@dataclass
class HostInfo:
    """Host information for web clients."""

    name: str
    type: str  # "local" or "ssh"
    host: Optional[str] = None  # Hostname/IP for SSH hosts
    user: Optional[str] = None  # Username for SSH hosts
    port: int = 22
    tags: list[str] = field(default_factory=list)
    description: Optional[str] = None
    status: str = "unknown"  # "ready", "reachable", "unreachable", "checking", "unknown"
    latency_ms: Optional[int] = None
    error: Optional[str] = None


@ws_type
@dataclass
class ProcessInfo:
    """Process information for web clients."""

    process_id: str
    command: str
    name: Optional[str]
    host: str  # Host name where process is running
    session_id: str
    status: str  # "running", "exited", "failed"
    exit_code: Optional[int] = None
    started_at: Optional[str] = None
    runtime_seconds: Optional[float] = None


@ws_type
@dataclass
class BackendHostMapping:
    """Mapping between LLM backend and host."""

    backend_name: str
    host_name: str


@ws_type
@dataclass
class SupervisorState:
    """Complete supervisor state for web clients."""

    hosts: list[HostInfo]
    processes: list[ProcessInfo]
    backend_hosts: list[BackendHostMapping]


@ws_type
@dataclass
class HostQueryResult:
    """Result of host query."""

    hosts: list[HostInfo]


@ws_type
@dataclass
class HostStatusResult:
    """Result of host status check."""

    host: str
    type: str
    status: str
    latency_ms: Optional[int] = None
    error: Optional[str] = None


@ws_type
@dataclass
class ProcessListResult:
    """Result of process list."""

    summary: str
    processes: list[ProcessInfo]


@ws_type
@dataclass
class HostUpdateRequest:
    """Request to add or update a host."""

    name: str
    type: str = "ssh"  # "local" or "ssh"
    host: Optional[str] = None  # Required for SSH
    user: Optional[str] = None  # Required for SSH
    port: int = 22
    tags: list[str] = field(default_factory=list)
    description: Optional[str] = None
    originalName: Optional[str] = None  # For renaming: the old name to replace


@ws_type
@dataclass
class ConfigUpdateResult:
    """Result of a config update operation."""

    success: bool
    error: Optional[str] = None


@ws_service
class SupervisorStateService:
    """WebSocket-exposed service for supervisor state management.

    Provides:
    - Host configuration and status queries
    - Process listing and management
    - Real-time status updates via events
    """

    def __init__(self) -> None:
        """Initialize the supervisor state service."""
        # Cache for host status (to avoid spamming SSH checks)
        self._host_status_cache: dict[str, HostInfo] = {}
        self._status_check_lock = asyncio.Lock()

    def _host_config_to_info(self, host: HostConfig, status: str = "unknown") -> HostInfo:
        """Convert HostConfig to HostInfo for web clients."""
        # For local host, populate 'host' field with the actual hostname
        host_value = host.host
        if host.type == "local" and not host_value:
            try:
                host_value = socket.gethostname()
            except Exception:
                host_value = "localhost"

        return HostInfo(
            name=host.name,
            type=host.type,
            host=host_value,
            user=host.user,
            port=host.port,
            tags=host.tags,
            description=host.description,
            status=status,
        )

    @ws_expose
    async def get_state(self) -> SupervisorState:
        """Get the complete supervisor state.

        Returns all hosts, processes, and backend mappings.
        """
        from core.supervisor_tools import get_supervisor

        config = get_supervisor_config()

        # Build host list
        hosts = []
        for name, host in config.hosts.items():
            # Use cached status if available
            if name in self._host_status_cache:
                hosts.append(self._host_status_cache[name])
            else:
                status = "ready" if host.type == "local" else "unknown"
                hosts.append(self._host_config_to_info(host, status))

        # Build process list
        processes = []
        supervisor = get_supervisor()
        if supervisor:
            try:
                processes_json = await supervisor.list_processes(None)  # All processes
                process_list = json.loads(processes_json)
                for p in process_list:
                    status_info = p.get("status", {})
                    state = status_info.get("state", "unknown")
                    processes.append(ProcessInfo(
                        process_id=p.get("id", ""),
                        command=p.get("command", ""),
                        name=p.get("name"),
                        host=p.get("host", "local"),
                        session_id=p.get("session_id", ""),
                        status=state,
                        exit_code=status_info.get("code"),
                        started_at=p.get("started_at"),
                    ))
            except Exception as e:
                debug_log.error(f"Error listing processes: {e}", category="supervisor")

        # Build backend-host mappings
        backend_hosts = [
            BackendHostMapping(backend_name=backend, host_name=host)
            for backend, host in config.backend_hosts.items()
        ]

        return SupervisorState(
            hosts=hosts,
            processes=processes,
            backend_hosts=backend_hosts,
        )

    @ws_expose
    def list_hosts(
        self,
        tags: Optional[list[str]] = None,
        host_type: Optional[str] = None,
    ) -> HostQueryResult:
        """Query hosts by tags and/or type.

        Args:
            tags: Filter to hosts with ALL specified tags
            host_type: Filter to hosts of this type ("local" or "ssh")

        Returns:
            List of matching hosts
        """
        config = get_supervisor_config()
        hosts = config.query_hosts(tags=tags, host_type=host_type)

        result = []
        for host in hosts:
            if host.name in self._host_status_cache:
                result.append(self._host_status_cache[host.name])
            else:
                status = "ready" if host.type == "local" else "unknown"
                result.append(self._host_config_to_info(host, status))

        return HostQueryResult(hosts=result)

    @ws_expose
    async def check_host_status(self, host_name: str) -> HostStatusResult:
        """Check connectivity status of a host.

        For SSH hosts, performs a quick connection test.
        For local, always returns ready.

        Args:
            host_name: Name of the host to check

        Returns:
            Status result with connectivity info
        """
        config = get_supervisor_config()

        try:
            host = config.get_host(host_name)
        except KeyError:
            return HostStatusResult(
                host=host_name,
                type="unknown",
                status="error",
                error=f"Unknown host: {host_name}",
            )

        if host.type == "local":
            result = HostStatusResult(
                host=host_name,
                type="local",
                status="ready",
            )
            self._host_status_cache[host_name] = self._host_config_to_info(host, "ready")
            return result

        # SSH connectivity check
        async with self._status_check_lock:
            try:
                ssh_args = [
                    "ssh",
                    "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=5",
                    "-o", "StrictHostKeyChecking=accept-new",
                ]
                if host.port != 22:
                    ssh_args.extend(["-p", str(host.port)])
                ssh_args.append(host.ssh_target())
                ssh_args.append("true")

                start_time = asyncio.get_event_loop().time()

                proc = await asyncio.create_subprocess_exec(
                    *ssh_args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)

                end_time = asyncio.get_event_loop().time()
                latency_ms = int((end_time - start_time) * 1000)

                if proc.returncode == 0:
                    result = HostStatusResult(
                        host=host_name,
                        type="ssh",
                        status="reachable",
                        latency_ms=latency_ms,
                    )
                    # Update cache
                    cached = self._host_config_to_info(host, "reachable")
                    cached.latency_ms = latency_ms
                    self._host_status_cache[host_name] = cached
                else:
                    error_msg = stderr.decode().strip() if stderr else "Connection failed"
                    result = HostStatusResult(
                        host=host_name,
                        type="ssh",
                        status="unreachable",
                        error=error_msg,
                    )
                    # Update cache
                    cached = self._host_config_to_info(host, "unreachable")
                    cached.error = error_msg
                    self._host_status_cache[host_name] = cached

                return result

            except asyncio.TimeoutError:
                result = HostStatusResult(
                    host=host_name,
                    type="ssh",
                    status="unreachable",
                    error="Connection timeout",
                )
                cached = self._host_config_to_info(host, "unreachable")
                cached.error = "Connection timeout"
                self._host_status_cache[host_name] = cached
                return result

            except Exception as e:
                return HostStatusResult(
                    host=host_name,
                    type="ssh",
                    status="error",
                    error=str(e),
                )

    @ws_expose
    async def list_processes(
        self,
        session_id: Optional[str] = None,
        host: Optional[str] = None,
    ) -> ProcessListResult:
        """List supervised processes.

        Args:
            session_id: Filter to processes for this session
            host: Filter to processes on this host

        Returns:
            List of processes with summary
        """
        from core.supervisor_tools import get_supervisor

        supervisor = get_supervisor()
        if not supervisor:
            return ProcessListResult(
                summary="Supervisor not initialized",
                processes=[],
            )

        try:
            processes_json = await supervisor.list_processes(session_id)
            process_list = json.loads(processes_json)

            processes = []
            for p in process_list:
                proc_host = p.get("host", "local")
                # Filter by host if specified
                if host and proc_host != host:
                    continue

                status_info = p.get("status", {})
                state = status_info.get("state", "unknown")
                processes.append(ProcessInfo(
                    process_id=p.get("id", ""),
                    command=p.get("command", ""),
                    name=p.get("name"),
                    host=proc_host,
                    session_id=p.get("session_id", ""),
                    status=state,
                    exit_code=status_info.get("code"),
                    started_at=p.get("started_at"),
                ))

            running = sum(1 for p in processes if p.status == "running")
            summary = f"{running} running, {len(processes)} total"

            return ProcessListResult(summary=summary, processes=processes)

        except Exception as e:
            debug_log.error(f"Error listing processes: {e}", category="supervisor")
            return ProcessListResult(
                summary=f"Error: {e}",
                processes=[],
            )

    @ws_expose
    def reload_config(self) -> bool:
        """Reload supervisor configuration from disk.

        Returns:
            True if reload succeeded
        """
        try:
            reload_supervisor_config()
            # Clear status cache so hosts are re-checked
            self._host_status_cache.clear()
            return True
        except Exception as e:
            debug_log.error(f"Error reloading supervisor config: {e}", category="supervisor")
            return False

    @ws_expose
    def add_host(self, request: HostUpdateRequest | dict) -> ConfigUpdateResult:
        """Add a new host to the configuration.

        Args:
            request: Host configuration

        Returns:
            Success/failure result
        """
        try:
            # Convert dict to dataclass if needed (WS layer passes raw dicts)
            if isinstance(request, dict):
                request = HostUpdateRequest(
                    name=request["name"],
                    type=request.get("type", "ssh"),
                    host=request.get("host"),
                    user=request.get("user"),
                    port=request.get("port", 22),
                    tags=request.get("tags", []),
                    description=request.get("description"),
                )

            config = get_supervisor_config()

            # Validate name doesn't exist (unless updating)
            if request.name in config.hosts:
                return ConfigUpdateResult(
                    success=False,
                    error=f"Host '{request.name}' already exists. Use updateHost to modify.",
                )

            # Create and validate host config
            host = HostConfig(
                name=request.name,
                type=request.type,
                host=request.host,
                user=request.user,
                port=request.port,
                tags=request.tags,
                description=request.description,
            )
            host.validate()

            # Add to config and save
            config.hosts[request.name] = host
            config.save()

            # Clear cache
            self._host_status_cache.clear()

            debug_log.info(f"Added host: {request.name}", category="supervisor")
            return ConfigUpdateResult(success=True)

        except ValueError as e:
            return ConfigUpdateResult(success=False, error=str(e))
        except Exception as e:
            debug_log.error(f"Error adding host: {e}", category="supervisor")
            return ConfigUpdateResult(success=False, error=str(e))

    @ws_expose
    def update_host(self, request: HostUpdateRequest | dict) -> ConfigUpdateResult:
        """Update an existing host in the configuration.

        Args:
            request: Host configuration (name must exist, or originalName for rename)

        Returns:
            Success/failure result
        """
        try:
            # Convert dict to dataclass if needed (WS layer passes raw dicts)
            if isinstance(request, dict):
                request = HostUpdateRequest(
                    name=request["name"],
                    type=request.get("type", "ssh"),
                    host=request.get("host"),
                    user=request.get("user"),
                    port=request.get("port", 22),
                    tags=request.get("tags", []),
                    description=request.get("description"),
                    originalName=request.get("originalName"),
                )

            config = get_supervisor_config()

            # Determine which host we're updating (support renaming via originalName)
            lookup_name = request.originalName if request.originalName else request.name
            is_rename = request.originalName and request.originalName != request.name

            if lookup_name not in config.hosts:
                return ConfigUpdateResult(
                    success=False,
                    error=f"Host '{lookup_name}' not found. Use addHost to create.",
                )

            # Don't allow renaming or changing type of local host
            if lookup_name == "local":
                if is_rename:
                    return ConfigUpdateResult(
                        success=False,
                        error="Cannot rename local host",
                    )
                if request.type != "local":
                    return ConfigUpdateResult(
                        success=False,
                        error="Cannot change local host type",
                    )

            # If renaming, check new name doesn't exist
            if is_rename and request.name in config.hosts:
                return ConfigUpdateResult(
                    success=False,
                    error=f"Host '{request.name}' already exists",
                )

            # Create and validate host config
            host = HostConfig(
                name=request.name,
                type=request.type,
                host=request.host,
                user=request.user,
                port=request.port,
                tags=request.tags,
                description=request.description,
            )
            host.validate()

            # If renaming, delete old entry
            if is_rename:
                del config.hosts[lookup_name]
                self._host_status_cache.pop(lookup_name, None)

            # Update config and save
            config.hosts[request.name] = host
            config.save()

            # Clear cache for this host
            self._host_status_cache.pop(request.name, None)

            if is_rename:
                debug_log.info(f"Renamed host: {lookup_name} -> {request.name}", category="supervisor")
            else:
                debug_log.info(f"Updated host: {request.name}", category="supervisor")
            return ConfigUpdateResult(success=True)

        except ValueError as e:
            return ConfigUpdateResult(success=False, error=str(e))
        except Exception as e:
            debug_log.error(f"Error updating host: {e}", category="supervisor")
            return ConfigUpdateResult(success=False, error=str(e))

    @ws_expose
    def remove_host(self, host_name: str) -> ConfigUpdateResult:
        """Remove a host from the configuration.

        Args:
            host_name: Name of the host to remove

        Returns:
            Success/failure result
        """
        try:
            config = get_supervisor_config()

            if host_name not in config.hosts:
                return ConfigUpdateResult(
                    success=False,
                    error=f"Host '{host_name}' not found",
                )

            if host_name == "local":
                return ConfigUpdateResult(
                    success=False,
                    error="Cannot remove local host",
                )

            # Remove host
            del config.hosts[host_name]

            # Remove any backend mappings that referenced this host
            config.backend_hosts = {
                backend: host
                for backend, host in config.backend_hosts.items()
                if host != host_name
            }

            config.save()

            # Clear cache
            self._host_status_cache.pop(host_name, None)

            debug_log.info(f"Removed host: {host_name}", category="supervisor")
            return ConfigUpdateResult(success=True)

        except Exception as e:
            debug_log.error(f"Error removing host: {e}", category="supervisor")
            return ConfigUpdateResult(success=False, error=str(e))

    @ws_expose
    def set_backend_host(self, backend_name: str, host_name: str) -> ConfigUpdateResult:
        """Map a backend to a host.

        Args:
            backend_name: Name of the LLM backend
            host_name: Name of the host it runs on

        Returns:
            Success/failure result
        """
        try:
            config = get_supervisor_config()

            # Validate host exists
            if host_name not in config.hosts:
                return ConfigUpdateResult(
                    success=False,
                    error=f"Host '{host_name}' not found",
                )

            config.backend_hosts[backend_name] = host_name
            config.save()

            debug_log.info(f"Mapped backend '{backend_name}' to host '{host_name}'", category="supervisor")
            return ConfigUpdateResult(success=True)

        except Exception as e:
            debug_log.error(f"Error setting backend host: {e}", category="supervisor")
            return ConfigUpdateResult(success=False, error=str(e))

    @ws_expose
    def remove_backend_host(self, backend_name: str) -> ConfigUpdateResult:
        """Remove a backend-to-host mapping.

        Args:
            backend_name: Name of the backend to unmap

        Returns:
            Success/failure result
        """
        try:
            config = get_supervisor_config()

            if backend_name not in config.backend_hosts:
                return ConfigUpdateResult(
                    success=False,
                    error=f"Backend '{backend_name}' has no host mapping",
                )

            del config.backend_hosts[backend_name]
            config.save()

            debug_log.info(f"Removed backend mapping: {backend_name}", category="supervisor")
            return ConfigUpdateResult(success=True)

        except Exception as e:
            debug_log.error(f"Error removing backend host: {e}", category="supervisor")
            return ConfigUpdateResult(success=False, error=str(e))

    # Events for real-time updates
    # Note: The return type hint indicates the event payload type for codegen
    @ws_event
    def supervisor_state_updated(self, state: SupervisorState) -> SupervisorState:
        """Fired when supervisor state changes (processes started/stopped, etc)."""
        pass

    @ws_event
    def host_status_changed(self, host: HostInfo) -> HostInfo:
        """Fired when a host's status changes."""
        pass

    @ws_event
    def process_started(self, process: ProcessInfo) -> ProcessInfo:
        """Fired when a new process starts."""
        pass

    @ws_event
    def process_stopped(self, process: ProcessInfo) -> ProcessInfo:
        """Fired when a process stops."""
        pass
