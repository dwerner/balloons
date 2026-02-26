"""Supervisor tools for managing long-running processes.

Provides LLM tools to start, monitor, and stop supervised processes.
The actual process management is handled by the Rust balloons-supervisor
crate via PyO3 bindings.

Tool definitions are in tools.py (SUPERVISOR_TOOLS). This module contains
the execution logic.

Extended to support remote hosts via SSH. Host configuration is loaded from
~/.balloons/supervisor.yaml.
"""

import asyncio
import json
import shlex
import subprocess
from typing import Any, TYPE_CHECKING

from .debug_log import debug_log

if TYPE_CHECKING:
    from session import Session

# Tool names handled by this module
SUPERVISOR_TOOL_NAMES = {
    "supervisor_start",
    "supervisor_list",
    "supervisor_output",
    "supervisor_stop",
    "supervisor_query",
    "supervisor_host_status",
}

# Global supervisor instance - set by app on startup
_supervisor = None


def set_supervisor(supervisor) -> None:
    """Set the global supervisor instance.

    Called by the app during startup after initializing the Rust supervisor.

    Args:
        supervisor: The balloons_storage.Supervisor instance
    """
    global _supervisor
    _supervisor = supervisor
    debug_log.info("Supervisor tools: supervisor instance set", category="supervisor")


def get_supervisor():
    """Get the global supervisor instance.

    Returns:
        The supervisor instance, or None if not initialized
    """
    return _supervisor


async def execute_supervisor_tool(
    name: str,
    args: dict[str, Any],
    session: "Session",
    working_dir: str,
) -> tuple[str, bool]:
    """Execute a supervisor tool.

    Args:
        name: Tool name
        args: Tool arguments
        session: The current session (for session-scoping)
        working_dir: Working directory for new processes

    Returns:
        Tuple of (result_string, is_error)
    """
    # These tools don't need the supervisor instance
    if name == "supervisor_query":
        return await _execute_query(args)
    elif name == "supervisor_host_status":
        return await _execute_host_status(args)

    if _supervisor is None:
        return "Error: Process supervisor not initialized", True

    try:
        if name == "supervisor_start":
            return await _execute_start(args, session, working_dir)
        elif name == "supervisor_list":
            return _execute_list(args, session)
        elif name == "supervisor_output":
            return _execute_output(args)
        elif name == "supervisor_stop":
            return _execute_stop(args)
        else:
            return f"Unknown supervisor tool: {name}", True
    except Exception as e:
        debug_log.error(f"Supervisor tool error: {e}", category="supervisor")
        return f"Error: {str(e)}", True


async def _execute_start(
    args: dict[str, Any],
    session: "Session",
    working_dir: str,
) -> tuple[str, bool]:
    """Start a new supervised process.

    Args:
        args: Tool arguments (command, host, name, env)
        session: Current session for scoping
        working_dir: Default working directory

    Returns:
        Tuple of (result_string, is_error)
    """
    from supervisor_config import get_supervisor_config

    command = args.get("command")
    if not command:
        return "Error: command is required", True

    host_name = args.get("host", "local")
    name = args.get("name")
    cwd = args.get("working_dir")
    env = args.get("env")

    # Get host configuration
    try:
        config = get_supervisor_config()
        host = config.get_host(host_name)
    except KeyError as e:
        return f"Error: {e}", True

    # Build the actual command based on host type
    if host.type == "ssh":
        # For SSH hosts, wrap command in ssh
        # Use -tt to force PTY allocation for proper output streaming
        ssh_args = ["ssh", "-tt", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        if host.port != 22:
            ssh_args.extend(["-p", str(host.port)])
        ssh_args.append(host.ssh_target())

        # If working directory specified, cd to it first
        if cwd:
            actual_command = f"cd {shlex.quote(cwd)} && {command}"
        else:
            actual_command = command

        ssh_args.append(actual_command)
        final_command = " ".join(shlex.quote(arg) for arg in ssh_args)

        # For SSH, working_dir is handled in the remote command
        effective_cwd = working_dir  # Local cwd doesn't matter for SSH
    else:
        # Local execution
        final_command = command
        effective_cwd = cwd or working_dir

    # Convert env dict to JSON string if provided
    env_json = json.dumps(env) if env else None

    try:
        process_id = _supervisor.start(
            command=final_command,
            session_id=session.id,
            working_dir=effective_cwd,
            name=name,
            env_json=env_json,
        )

        debug_log.info(
            f"Started process: {process_id[:8]}",
            category="supervisor",
            details={
                "command": command,
                "host": host_name,
                "name": name,
                "session": session.id[:8],
            },
        )

        result = {
            "process_id": process_id,
            "status": "started",
            "command": command,
            "host": host_name,
            "name": name,
            "working_dir": cwd or effective_cwd,
        }
        return json.dumps(result, indent=2), False

    except Exception as e:
        return f"Error starting process: {e}", True


def _execute_list(
    args: dict[str, Any],
    session: "Session",
) -> tuple[str, bool]:
    """List supervised processes.

    Args:
        args: Tool arguments (all_sessions flag)
        session: Current session for default filtering

    Returns:
        Tuple of (result_string, is_error)
    """
    all_sessions = args.get("all_sessions", False)

    # Filter by session unless all_sessions=True
    session_id = None if all_sessions else session.id

    try:
        processes_json = _supervisor.list_processes(session_id)
        processes = json.loads(processes_json)

        if not processes:
            scope = "any session" if all_sessions else "this session"
            return f"No supervised processes found for {scope}.", False

        # Add helpful summary
        running = sum(1 for p in processes if p.get("status", {}).get("state") == "running")
        total = len(processes)

        result = {
            "summary": f"{running} running, {total} total",
            "processes": processes,
        }
        return json.dumps(result, indent=2), False

    except Exception as e:
        return f"Error listing processes: {e}", True


def _execute_output(args: dict[str, Any]) -> tuple[str, bool]:
    """Get output from a supervised process.

    Args:
        args: Tool arguments (process_id, limit)

    Returns:
        Tuple of (result_string, is_error)
    """
    process_id = args.get("process_id")
    if not process_id:
        return "Error: process_id is required", True

    limit = args.get("limit", 50)

    try:
        # Get process info first
        process_json = _supervisor.get_process(process_id)
        process = json.loads(process_json)

        # Get output
        output_json = _supervisor.get_output(process_id, limit)
        logs = json.loads(output_json)

        # Format output nicely
        result = {
            "process_id": process_id,
            "name": process.get("name"),
            "command": process.get("command"),
            "status": process.get("status"),
            "log_count": len(logs),
            "logs": logs,
        }
        return json.dumps(result, indent=2), False

    except Exception as e:
        return f"Error getting output: {e}", True


def _execute_stop(args: dict[str, Any]) -> tuple[str, bool]:
    """Stop a supervised process.

    Args:
        args: Tool arguments (process_id)

    Returns:
        Tuple of (result_string, is_error)
    """
    process_id = args.get("process_id")
    if not process_id:
        return "Error: process_id is required", True

    try:
        _supervisor.stop_process(process_id)

        debug_log.info(f"Stopped process: {process_id[:8]}", category="supervisor")

        return json.dumps({
            "process_id": process_id,
            "status": "stopped",
        }, indent=2), False

    except Exception as e:
        return f"Error stopping process: {e}", True


# =============================================================================
# Helper functions for app integration
# =============================================================================

def get_running_count() -> int:
    """Get the count of running processes.

    Returns:
        Number of running processes, or 0 if supervisor not initialized
    """
    if _supervisor is None:
        return 0
    try:
        return _supervisor.running_count()
    except Exception:
        return 0


def stop_session_processes(session_id: str) -> int:
    """Stop all processes for a session.

    Called when a session is closed or archived.

    Args:
        session_id: The session ID

    Returns:
        Number of processes stopped
    """
    if _supervisor is None:
        return 0
    try:
        count = _supervisor.stop_session_processes(session_id)
        if count > 0:
            debug_log.info(
                f"Stopped {count} processes for session {session_id[:8]}",
                category="supervisor",
            )
        return count
    except Exception as e:
        debug_log.error(f"Error stopping session processes: {e}", category="supervisor")
        return 0


def shutdown_supervisor() -> None:
    """Shutdown the supervisor, stopping all running processes.

    Called when the app is exiting to cleanly stop all supervised processes
    and avoid panics from orphaned background tasks.
    """
    global _supervisor
    if _supervisor is None:
        return
    try:
        _supervisor.shutdown()
        debug_log.info("Supervisor shutdown complete", category="supervisor")
    except Exception as e:
        debug_log.error(f"Error during supervisor shutdown: {e}", category="supervisor")
    finally:
        _supervisor = None


# =============================================================================
# Host query and status tools
# =============================================================================

async def _execute_query(args: dict[str, Any]) -> tuple[str, bool]:
    """Query available hosts by tags and type.

    Args:
        args: Tool arguments (tags, type)

    Returns:
        Tuple of (result_string, is_error)
    """
    from supervisor_config import get_supervisor_config

    tags = args.get("tags")
    host_type = args.get("type")

    try:
        config = get_supervisor_config()
        hosts = config.query_hosts(tags=tags, host_type=host_type)

        result = []
        for host in hosts:
            host_info = {
                "name": host.name,
                "type": host.type,
                "tags": host.tags,
            }
            if host.type == "ssh":
                host_info["host"] = host.host
                host_info["user"] = host.user
                if host.port != 22:
                    host_info["port"] = host.port
            if host.description:
                host_info["description"] = host.description

            result.append(host_info)

        if not result:
            filters = []
            if tags:
                filters.append(f"tags={tags}")
            if host_type:
                filters.append(f"type={host_type}")
            filter_str = ", ".join(filters) if filters else "none"
            return f"No hosts found matching filters: {filter_str}", False

        return json.dumps({"hosts": result}, indent=2), False

    except Exception as e:
        return f"Error querying hosts: {e}", True


async def _execute_host_status(args: dict[str, Any]) -> tuple[str, bool]:
    """Check connectivity status of a host.

    Args:
        args: Tool arguments (host)

    Returns:
        Tuple of (result_string, is_error)
    """
    from supervisor_config import get_supervisor_config

    host_name = args.get("host")
    if not host_name:
        return "Error: host is required", True

    try:
        config = get_supervisor_config()
        host = config.get_host(host_name)
    except KeyError as e:
        return f"Error: {e}", True

    if host.type == "local":
        return json.dumps({
            "host": host_name,
            "type": "local",
            "status": "ready",
        }, indent=2), False

    # For SSH hosts, do a quick connectivity test
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
        ssh_args.append("true")  # Just run 'true' to test connectivity

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
            return json.dumps({
                "host": host_name,
                "type": "ssh",
                "status": "reachable",
                "latency_ms": latency_ms,
            }, indent=2), False
        else:
            error_msg = stderr.decode().strip() if stderr else "Connection failed"
            return json.dumps({
                "host": host_name,
                "type": "ssh",
                "status": "unreachable",
                "error": error_msg,
            }, indent=2), False

    except asyncio.TimeoutError:
        return json.dumps({
            "host": host_name,
            "type": "ssh",
            "status": "unreachable",
            "error": "Connection timeout",
        }, indent=2), False
    except Exception as e:
        return json.dumps({
            "host": host_name,
            "type": "ssh",
            "status": "error",
            "error": str(e),
        }, indent=2), False
