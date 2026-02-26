"""WebSocket-exposed service for supervisor state.

This service provides access to:
- Host configuration and status
- Process management (list, start, stop)
- Backend-to-host mappings

It wraps the supervisor_config and supervisor_tools modules for web client access.
"""

import asyncio
import json
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
        return HostInfo(
            name=host.name,
            type=host.type,
            host=host.host,
            user=host.user,
            port=host.port,
            tags=host.tags,
            description=host.description,
            status=status,
        )

    @ws_expose
    def get_state(self) -> SupervisorState:
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
                processes_json = supervisor.list_processes(None)  # All processes
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
    def list_processes(
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
            processes_json = supervisor.list_processes(session_id)
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
