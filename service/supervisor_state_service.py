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
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from codegen import ws_service, ws_expose, ws_event, ws_type
from core.debug_log import debug_log, Category
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
class ProcessOutput:
    """A line of process output for real-time streaming."""

    process_id: str
    source: str  # "stdout", "stderr", or "system"
    content: str
    ts: float  # Unix timestamp


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


@ws_type
@dataclass
class SupervisorEvent:
    """A supervisor event for the event log.

    Event types:
    - "process_started": Process launched (data has ProcessInfo fields)
    - "process_output": stdout/stderr line (data has process_id, source, content)
    - "process_stopped": Process exited (data has ProcessInfo fields + exit_code)
    - "host_status": Host status changed (data has HostInfo fields)
    """
    ts: float  # Unix timestamp
    type: str  # Event type
    data: dict  # Event-specific data


@ws_type
@dataclass
class EventHistoryResult:
    """Result of get_event_history."""
    events: list[SupervisorEvent]
    total_buffered: int


class EventBuffer:
    """In-memory circular buffer for supervisor events.

    Holds recent events for UI replay and pushes new events to subscribers.
    Events are post-filtered - only meaningful events go in.
    """

    def __init__(self, max_size: int = 1000):
        self._events: deque[SupervisorEvent] = deque(maxlen=max_size)
        self._subscribers: set[Callable[[SupervisorEvent], None]] = set()
        self._lock = asyncio.Lock()

    async def append(self, event: SupervisorEvent) -> None:
        """Add event to buffer and notify subscribers."""
        async with self._lock:
            self._events.append(event)

        # Notify subscribers (outside lock)
        for sub in list(self._subscribers):
            try:
                sub(event)
            except Exception as e:
                debug_log.error(f"Event subscriber error: {e}", category=Category.SUPERVISOR)

    def append_sync(self, event: SupervisorEvent) -> None:
        """Synchronous append for use from non-async contexts."""
        self._events.append(event)
        for sub in list(self._subscribers):
            try:
                sub(event)
            except Exception as e:
                debug_log.error(f"Event subscriber error: {e}", category=Category.SUPERVISOR)

    def get_history(
        self,
        limit: int = 100,
        since_ts: float = 0,
        event_types: Optional[list[str]] = None,
        process_id: Optional[str] = None,
    ) -> list[SupervisorEvent]:
        """Get recent events, optionally filtered.

        Args:
            limit: Maximum events to return
            since_ts: Only events after this timestamp
            event_types: Filter to these event types
            process_id: Filter to this process

        Returns:
            List of events, most recent last
        """
        result = []
        for event in self._events:
            if event.ts <= since_ts:
                continue
            if event_types and event.type not in event_types:
                continue
            if process_id and event.data.get("process_id") != process_id:
                continue
            result.append(event)

        return result[-limit:]

    def subscribe(self, callback: Callable[[SupervisorEvent], None]) -> Callable[[], None]:
        """Subscribe to new events.

        Args:
            callback: Function called with each new event

        Returns:
            Unsubscribe function
        """
        self._subscribers.add(callback)
        return lambda: self._subscribers.discard(callback)

    def __len__(self) -> int:
        return len(self._events)


# Global event buffer instance
_event_buffer: Optional[EventBuffer] = None


def get_event_buffer() -> EventBuffer:
    """Get the global event buffer, creating if needed."""
    global _event_buffer
    if _event_buffer is None:
        _event_buffer = EventBuffer()
    return _event_buffer


def emit_supervisor_event(event_type: str, data: dict) -> SupervisorEvent:
    """Create and emit a supervisor event.

    Args:
        event_type: Event type (process_started, process_output, etc.)
        data: Event data

    Returns:
        The created event
    """
    event = SupervisorEvent(
        ts=time.time(),
        type=event_type,
        data=data,
    )
    get_event_buffer().append_sync(event)
    debug_log.debug(
        f"Supervisor event: {event_type}",
        category=Category.SUPERVISOR,
        details=data,
    )
    return event


# Global reference to the service instance for callback access
_service_instance: Optional["SupervisorStateService"] = None


def _output_callback(process_id: str, source: str, content: str) -> None:
    """Callback invoked by Rust supervisor for each process output line.

    This is called from a background thread, so we need to be careful about
    thread safety. We emit a WebSocket event to stream the output to clients.

    Args:
        process_id: UUID of the process
        source: "stdout", "stderr", or "system"
        content: The output line
    """
    # DEBUG: Log that callback was invoked
    print(f"[OUTPUT_CALLBACK] {process_id[:8]} {source}: {content[:50]}")

    # Create the output event
    output = ProcessOutput(
        process_id=process_id,
        source=source,
        content=content,
        ts=time.time(),
    )

    # Emit the WebSocket event if service is initialized
    if _service_instance is not None:
        try:
            print(f"[OUTPUT_CALLBACK] Emitting to WebSocket")
            _service_instance._emit_process_output(output)
        except Exception as e:
            debug_log.error(f"Error emitting process output: {e}", category=Category.SUPERVISOR)
            print(f"[OUTPUT_CALLBACK] ERROR: {e}")
    else:
        print(f"[OUTPUT_CALLBACK] WARNING: _service_instance is None")


def register_output_callback() -> None:
    """Register the output callback with the Rust supervisor.

    Call this after both the supervisor and WebSocket service are initialized.
    """
    from core.supervisor_tools import get_supervisor

    supervisor = get_supervisor()
    if supervisor is None:
        debug_log.warning(
            "Cannot register output callback: supervisor not initialized",
            category=Category.SUPERVISOR,
        )
        return

    try:
        supervisor.set_output_callback(_output_callback)
        debug_log.info("Registered supervisor output callback", category=Category.SUPERVISOR)
    except Exception as e:
        debug_log.error(f"Failed to register output callback: {e}", category=Category.SUPERVISOR)


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

        # Event handlers for WebSocket broadcasting
        self._event_handlers: list[Callable[[str, dict], None]] = []

        # Register this instance globally for callback access
        global _service_instance
        _service_instance = self

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Register an event handler for WebSocket broadcasting."""
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def _emit_event(self, event_name: str, data: dict) -> None:
        """Emit an event to all registered handlers."""
        for handler in self._event_handlers:
            handler(event_name, data)

    def _emit_process_output(self, output: ProcessOutput) -> None:
        """Emit a process_output event to WebSocket clients.

        Called from the output callback when process output arrives.
        This method is thread-safe as it queues the event for async dispatch.
        """
        self._emit_event("processOutput", {
            "processId": output.process_id,
            "source": output.source,
            "content": output.content,
            "ts": output.ts,
        })

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
                debug_log.error(f"Error listing processes: {e}", category=Category.SUPERVISOR)

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
            debug_log.error(f"Error listing processes: {e}", category=Category.SUPERVISOR)
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
            debug_log.error(f"Error reloading supervisor config: {e}", category=Category.SUPERVISOR)
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

            debug_log.info(f"Added host: {request.name}", category=Category.SUPERVISOR)
            return ConfigUpdateResult(success=True)

        except ValueError as e:
            return ConfigUpdateResult(success=False, error=str(e))
        except Exception as e:
            debug_log.error(f"Error adding host: {e}", category=Category.SUPERVISOR)
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
                debug_log.info(f"Renamed host: {lookup_name} -> {request.name}", category=Category.SUPERVISOR)
            else:
                debug_log.info(f"Updated host: {request.name}", category=Category.SUPERVISOR)
            return ConfigUpdateResult(success=True)

        except ValueError as e:
            return ConfigUpdateResult(success=False, error=str(e))
        except Exception as e:
            debug_log.error(f"Error updating host: {e}", category=Category.SUPERVISOR)
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

            debug_log.info(f"Removed host: {host_name}", category=Category.SUPERVISOR)
            return ConfigUpdateResult(success=True)

        except Exception as e:
            debug_log.error(f"Error removing host: {e}", category=Category.SUPERVISOR)
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

            debug_log.info(f"Mapped backend '{backend_name}' to host '{host_name}'", category=Category.SUPERVISOR)
            return ConfigUpdateResult(success=True)

        except Exception as e:
            debug_log.error(f"Error setting backend host: {e}", category=Category.SUPERVISOR)
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

            debug_log.info(f"Removed backend mapping: {backend_name}", category=Category.SUPERVISOR)
            return ConfigUpdateResult(success=True)

        except Exception as e:
            debug_log.error(f"Error removing backend host: {e}", category=Category.SUPERVISOR)
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

    @ws_event
    def process_output(self, output: ProcessOutput) -> ProcessOutput:
        """Fired when a process emits output (stdout/stderr)."""
        pass
