"""Supervisor tools for managing long-running processes.

Provides LLM tools to start, monitor, and stop supervised processes.
The actual process management is handled by the Rust balloons-supervisor
crate via PyO3 bindings.

Tool definitions are in tools.py (SUPERVISOR_TOOLS). This module contains
the execution logic.
"""

import json
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
    if _supervisor is None:
        return "Error: Process supervisor not initialized", True

    try:
        if name == "supervisor_start":
            return _execute_start(args, session, working_dir)
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


def _execute_start(
    args: dict[str, Any],
    session: "Session",
    working_dir: str,
) -> tuple[str, bool]:
    """Start a new supervised process.

    Args:
        args: Tool arguments (command, name, env)
        session: Current session for scoping
        working_dir: Default working directory

    Returns:
        Tuple of (result_string, is_error)
    """
    command = args.get("command")
    if not command:
        return "Error: command is required", True

    name = args.get("name")
    cwd = args.get("working_dir", working_dir)
    env = args.get("env")

    # Convert env dict to JSON string if provided
    env_json = json.dumps(env) if env else None

    try:
        process_id = _supervisor.start(
            command=command,
            session_id=session.id,
            working_dir=cwd,
            name=name,
            env_json=env_json,
        )

        debug_log.info(
            f"Started process: {process_id[:8]}",
            category="supervisor",
            details={"command": command, "name": name, "session": session.id[:8]},
        )

        result = {
            "process_id": process_id,
            "status": "started",
            "command": command,
            "name": name,
            "working_dir": cwd,
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
