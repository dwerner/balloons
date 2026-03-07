"""Server management tools for safe A/B slot operations.

These tools allow the LLM to manage server instances safely, preventing
self-destructive operations like restarting the server it's currently running on.

Architecture:
- Slot A runs on port 8700
- Slot B runs on port 8710
- The tool can only manage the OTHER slot, never the current one
"""

import asyncio
import os
import signal
from pathlib import Path
from typing import TYPE_CHECKING

from .debug_log import debug_log, Category
from .server_identity import get_identity

if TYPE_CHECKING:
    from session import Session


# Port configuration (must match balloons-server.py)
SLOT_A_PORT = 8700
SLOT_B_PORT = 8710

# PID file location
PID_DIR = Path.home() / ".balloons" / "run"


SERVER_TOOL_NAMES = frozenset([
    "server_manage",
])


def _get_pid_file(port: int) -> Path:
    """Get PID file path for a port."""
    return PID_DIR / f"headless-{port}.pid"


def _read_pid(port: int) -> int | None:
    """Read PID from file, return None if not exists or stale."""
    pid_file = _get_pid_file(port)
    if not pid_file.exists():
        return None

    try:
        pid = int(pid_file.read_text().strip())
        # Check if process is actually running
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        # Stale PID file
        pid_file.unlink(missing_ok=True)
        return None


def _write_pid(port: int, pid: int) -> None:
    """Write PID to file."""
    PID_DIR.mkdir(parents=True, exist_ok=True)
    _get_pid_file(port).write_text(str(pid))


def _remove_pid(port: int) -> None:
    """Remove PID file."""
    _get_pid_file(port).unlink(missing_ok=True)


def _get_other_slot() -> tuple[str, int]:
    """Get the OTHER slot (not the one we're running on).

    Returns:
        Tuple of (slot_name, port) for the other slot
    """
    identity = get_identity()
    if identity is None:
        # Fallback: assume we're on A
        return ("B", SLOT_B_PORT)

    if identity.slot == "A":
        return ("B", SLOT_B_PORT)
    else:
        return ("A", SLOT_A_PORT)


def _get_current_slot() -> tuple[str, int]:
    """Get the current slot we're running on.

    Returns:
        Tuple of (slot_name, port) for the current slot
    """
    identity = get_identity()
    if identity is None:
        return ("?", 0)
    return (identity.slot, identity.port)


async def execute_server_tool(
    name: str,
    args: dict,
    session: "Session | None" = None,
) -> tuple[str, bool]:
    """Execute a server management tool.

    Args:
        name: Tool name
        args: Tool arguments
        session: Session context (optional)

    Returns:
        Tuple of (result_string, is_error)
    """
    if name == "server_manage":
        return await _execute_server_manage(args)
    else:
        return f"Unknown server tool: {name}", True


async def _execute_server_manage(args: dict) -> tuple[str, bool]:
    """Manage the OTHER server slot.

    Actions:
    - status: Get status of both slots (which is running, which is current)
    - start: Start the other slot
    - stop: Stop the other slot
    - restart: Restart the other slot (stop + start)

    SAFETY: This tool can ONLY operate on the other slot, never the current one.
    """
    action = args.get("action")
    if not action:
        return "Error: 'action' is required (status, start, stop, restart)", True

    valid_actions = {"status", "start", "stop", "restart"}
    if action not in valid_actions:
        return f"Error: Invalid action '{action}'. Valid actions: {', '.join(sorted(valid_actions))}", True

    current_slot, current_port = _get_current_slot()
    other_slot, other_port = _get_other_slot()

    debug_log.info(
        f"Server tool: {action}",
        category=Category.LIFECYCLE,
        details={
            "current_slot": current_slot,
            "current_port": current_port,
            "other_slot": other_slot,
            "other_port": other_port,
        },
    )

    if action == "status":
        return _get_status(current_slot, current_port, other_slot, other_port)
    elif action == "start":
        return await _start_other_slot(other_slot, other_port)
    elif action == "stop":
        return await _stop_other_slot(other_slot, other_port)
    elif action == "restart":
        # Stop then start
        debug_log.info(
            f"Restart: stopping Slot {other_slot}",
            category=Category.LIFECYCLE,
            details={"step": "stop", "slot": other_slot, "port": other_port},
        )
        stop_result, stop_error = await _stop_other_slot(other_slot, other_port)
        debug_log.info(
            f"Restart: stop complete",
            category=Category.LIFECYCLE,
            details={"step": "stop_done", "result": stop_result, "error": stop_error},
        )
        if stop_error and "not running" not in stop_result.lower():
            return stop_result, stop_error

        # Small delay to let the process fully terminate
        debug_log.info(
            f"Restart: waiting 0.5s before starting",
            category=Category.LIFECYCLE,
            details={"step": "wait"},
        )
        await asyncio.sleep(0.5)

        debug_log.info(
            f"Restart: starting Slot {other_slot}",
            category=Category.LIFECYCLE,
            details={"step": "start", "slot": other_slot, "port": other_port},
        )
        start_result, start_error = await _start_other_slot(other_slot, other_port)
        debug_log.info(
            f"Restart: start complete",
            category=Category.LIFECYCLE,
            details={"step": "start_done", "result": start_result, "error": start_error},
        )
        if stop_error and "not running" in stop_result.lower():
            return start_result, start_error
        return f"Restarted Slot {other_slot}:\n{stop_result}\n{start_result}", start_error

    return f"Unknown action: {action}", True


def _get_status(
    current_slot: str,
    current_port: int,
    other_slot: str,
    other_port: int,
) -> tuple[str, bool]:
    """Get status of both server slots."""
    lines = [
        "Server Status:",
        f"  Current: Slot {current_slot} (port {current_port}) - YOU ARE HERE",
    ]

    other_pid = _read_pid(other_port)
    if other_pid:
        lines.append(f"  Other:   Slot {other_slot} (port {other_port}) - RUNNING (PID {other_pid})")
    else:
        lines.append(f"  Other:   Slot {other_slot} (port {other_port}) - NOT RUNNING")

    lines.append("")
    lines.append(f"Note: You can only manage Slot {other_slot} from here.")

    return "\n".join(lines), False


async def _start_other_slot(slot: str, port: int) -> tuple[str, bool]:
    """Start the other server slot."""
    existing_pid = _read_pid(port)
    if existing_pid:
        return f"Slot {slot} is already running on port {port} (PID {existing_pid})", False

    # Find the headless.py and venv python
    # We need to find the project root - server_identity.py is in core/
    project_root = Path(__file__).parent.parent
    headless_path = project_root / "headless.py"

    if not headless_path.exists():
        return f"Error: headless.py not found at {headless_path}", True

    # Use .venv Python to ensure Rust extension is available
    venv_python = project_root / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else "python3"

    # Create log directory
    log_dir = Path.home() / ".balloons"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"headless-{slot.lower()}.log"

    try:
        # Start the process detached
        process = await asyncio.create_subprocess_exec(
            python_exe,
            str(headless_path),
            "--port",
            str(port),
            cwd=project_root,
            stdout=open(log_file, "a"),
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )

        _write_pid(port, process.pid)

        debug_log.info(
            f"Started Slot {slot} on port {port}",
            category=Category.LIFECYCLE,
            details={"pid": process.pid, "port": port, "slot": slot},
        )

        return f"Started Slot {slot} on port {port} (PID {process.pid})", False

    except Exception as e:
        debug_log.error(f"Failed to start Slot {slot}: {e}", category=Category.LIFECYCLE)
        return f"Error starting Slot {slot}: {e}", True


async def _stop_other_slot(slot: str, port: int) -> tuple[str, bool]:
    """Stop the other server slot."""
    pid = _read_pid(port)
    if not pid:
        return f"Slot {slot} is not running (no process on port {port})", False

    try:
        os.kill(pid, signal.SIGTERM)
        _remove_pid(port)

        debug_log.info(
            f"Stopped Slot {slot}",
            category=Category.LIFECYCLE,
            details={"pid": pid, "port": port, "slot": slot},
        )

        return f"Stopped Slot {slot} (was PID {pid})", False

    except ProcessLookupError:
        _remove_pid(port)
        return f"Slot {slot} process not found (cleaned up stale PID file)", False
    except PermissionError:
        return f"Error: Permission denied stopping Slot {slot} (PID {pid})", True
    except Exception as e:
        return f"Error stopping Slot {slot}: {e}", True


# Tool definitions for OpenAI-compatible format
SERVER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "server_manage",
            "description": """Manage the Balloons server slots (A/B deployment).

IMPORTANT: This tool can ONLY manage the OTHER slot, not the one you're currently running on.
This prevents you from accidentally killing your own connection.

Use this tool to:
- Check which servers are running (status)
- Start the other slot to test code changes (start)
- Stop the other slot (stop)
- Restart the other slot with new code (restart)

The A/B slot architecture enables safe self-modification:
- Slot A (port 8700): Primary/stable instance
- Slot B (port 8710): Secondary/experimental instance

Typical workflow:
1. server_manage(action="status") - See which slots are running
2. Make code changes to source files
3. server_manage(action="restart") - Restart the OTHER slot to pick up changes
4. Test the other slot - if it works, restart this slot manually later""",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "start", "stop", "restart"],
                        "description": "Action to perform: status (check both slots), start/stop/restart (the OTHER slot only)"
                    }
                },
                "required": ["action"]
            }
        }
    },
]


def _log_server_tool_entry():
    """Log entry for debugging server tool execution."""
    from .server_identity import get_identity
    identity = get_identity()
    if identity:
        debug_log.info(
            f"server_manage tool called",
            category=Category.LIFECYCLE,
            details={
                "identity_slot": identity.slot,
                "identity_port": identity.port,
                "identity_pid": identity.pid,
            },
        )
    else:
        debug_log.info(
            "server_manage tool called with no identity",
            category=Category.LIFECYCLE,
        )
