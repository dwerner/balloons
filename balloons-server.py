#!/usr/bin/env python3
"""Balloons Server Manager - Start/stop headless instances and UI server.

Usage:
    python balloons-server.py start [--port PORT]   # Start instance on port
    python balloons-server.py stop [--port PORT]    # Stop instance on port
    python balloons-server.py list                  # List running instances
    python balloons-server.py restart [--port PORT] # Restart instance
    python balloons-server.py ui start              # Start bun dev server (TLS)
    python balloons-server.py ui stop               # Stop bun dev server
    python balloons-server.py ui restart            # Restart bun dev server

Default ports:
    A: 8700 (primary backend)
    B: 8710 (secondary backend)
    UI: 3030 (bun dev server with TLS)
"""

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

# Default slots
SLOT_A_PORT = 8700
SLOT_B_PORT = 8710
UI_PORT = 3030

# PID file location
PID_DIR = Path.home() / ".balloons" / "run"
LOG_DIR = Path.home() / ".balloons"

# UI server PID file
UI_PID_FILE = PID_DIR / "bun-dev.pid"
UI_LOG_FILE = LOG_DIR / "bun-dev.log"


def get_pid_file(port: int) -> Path:
    """Get PID file path for a port."""
    return PID_DIR / f"headless-{port}.pid"


def get_log_file(port: int) -> Path:
    """Get log file path for a port."""
    if port == SLOT_A_PORT:
        return LOG_DIR / "headless-a.log"
    elif port == SLOT_B_PORT:
        return LOG_DIR / "headless-b.log"
    return LOG_DIR / f"headless-{port}.log"


def read_pid(port: int) -> int | None:
    """Read PID from file, return None if not exists or stale."""
    pid_file = get_pid_file(port)
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


def write_pid(port: int, pid: int) -> None:
    """Write PID to file."""
    PID_DIR.mkdir(parents=True, exist_ok=True)
    get_pid_file(port).write_text(str(pid))


def remove_pid(port: int) -> None:
    """Remove PID file."""
    get_pid_file(port).unlink(missing_ok=True)


def start_instance(port: int) -> bool:
    """Start a headless instance on the given port.

    Returns True if started, False if already running.
    """
    existing_pid = read_pid(port)
    if existing_pid:
        print(f"Instance already running on port {port} (PID {existing_pid})")
        return False

    # Get the directory where this script lives
    script_dir = Path(__file__).parent
    headless_path = script_dir / "headless.py"

    if not headless_path.exists():
        print(f"Error: headless.py not found at {headless_path}")
        return False

    # Start the process with log file output
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = get_log_file(port)
    log_handle = open(log_file, "a")

    # Use .venv Python to ensure Rust extension is available
    venv_python = script_dir / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    process = subprocess.Popen(
        [python_exe, str(headless_path), "--port", str(port)],
        cwd=script_dir,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # Detach from terminal
    )

    write_pid(port, process.pid)
    print(f"Started instance on port {port} (PID {process.pid})")
    return True


def stop_instance(port: int) -> bool:
    """Stop a headless instance on the given port.

    Returns True if stopped, False if not running.
    """
    pid = read_pid(port)
    if not pid:
        print(f"No instance running on port {port}")
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Stopped instance on port {port} (PID {pid})")
        remove_pid(port)
        return True
    except ProcessLookupError:
        print(f"Process {pid} not found, cleaning up PID file")
        remove_pid(port)
        return False
    except PermissionError:
        print(f"Permission denied stopping PID {pid}")
        return False


# ============================================================================
# UI Server Management (bun dev:tls)
# ============================================================================


def read_ui_pid() -> int | None:
    """Read UI server PID from file, return None if not exists or stale."""
    if not UI_PID_FILE.exists():
        return None

    try:
        pid = int(UI_PID_FILE.read_text().strip())
        # Check if process is actually running
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        # Stale PID file
        UI_PID_FILE.unlink(missing_ok=True)
        return None


def write_ui_pid(pid: int) -> None:
    """Write UI server PID to file."""
    PID_DIR.mkdir(parents=True, exist_ok=True)
    UI_PID_FILE.write_text(str(pid))


def remove_ui_pid() -> None:
    """Remove UI server PID file."""
    UI_PID_FILE.unlink(missing_ok=True)


def start_ui_server() -> bool:
    """Start the bun dev server with TLS.

    Returns True if started, False if already running.
    """
    existing_pid = read_ui_pid()
    if existing_pid:
        print(f"UI server already running (PID {existing_pid})")
        return False

    # Get the directory where this script lives
    script_dir = Path(__file__).parent
    ui_dir = script_dir / "web" / "ui"

    if not ui_dir.exists():
        print(f"Error: web/ui not found at {ui_dir}")
        return False

    # Start bun with the dev:tls script
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = open(UI_LOG_FILE, "a")

    # Find bun executable
    bun_path = subprocess.run(
        ["which", "bun"],
        capture_output=True,
        text=True
    ).stdout.strip()

    if not bun_path:
        print("Error: bun not found in PATH")
        return False

    process = subprocess.Popen(
        [bun_path, "run", "dev:tls"],
        cwd=ui_dir,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # Detach from terminal
    )

    write_ui_pid(process.pid)
    print(f"Started UI server on port {UI_PORT} (PID {process.pid})")
    return True


def stop_ui_server() -> bool:
    """Stop the bun dev server.

    Returns True if stopped, False if not running.
    """
    pid = read_ui_pid()
    if not pid:
        print("UI server not running")
        return False

    try:
        # Kill the process group to ensure bun and its children are stopped
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        print(f"Stopped UI server (PID {pid})")
        remove_ui_pid()
        return True
    except ProcessLookupError:
        print(f"Process {pid} not found, cleaning up PID file")
        remove_ui_pid()
        return False
    except PermissionError:
        print(f"Permission denied stopping PID {pid}")
        return False


def list_instances() -> None:
    """List all running instances."""
    found = False

    # List backend instances
    for port in [SLOT_A_PORT, SLOT_B_PORT]:
        pid = read_pid(port)
        if pid:
            slot = "A" if port == SLOT_A_PORT else "B"
            print(f"Backend {slot}: port {port}, PID {pid}")
            found = True

    # Also check for any other instances via PID files
    if PID_DIR.exists():
        for pid_file in PID_DIR.glob("headless-*.pid"):
            try:
                port = int(pid_file.stem.split("-")[1])
                if port not in [SLOT_A_PORT, SLOT_B_PORT]:
                    pid = read_pid(port)
                    if pid:
                        print(f"Custom: port {port}, PID {pid}")
                        found = True
            except (ValueError, IndexError):
                pass

    # List UI server
    ui_pid = read_ui_pid()
    if ui_pid:
        print(f"UI Server: port {UI_PORT}, PID {ui_pid}")
        found = True

    if not found:
        print("No instances running")


def resolve_port(args) -> int:
    """Resolve port from args, defaulting to slot A."""
    if hasattr(args, 'port') and args.port:
        return args.port
    if hasattr(args, 'slot') and args.slot:
        return SLOT_A_PORT if args.slot.upper() == 'A' else SLOT_B_PORT
    return SLOT_A_PORT


def main():
    parser = argparse.ArgumentParser(
        description="Balloons Server Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Slots:
    A: port 8700 (primary/stable backend)
    B: port 8710 (secondary/experimental backend)
    UI: port 3030 (bun dev server with TLS)

Examples:
    balloons-server.py start             # Start backend slot A
    balloons-server.py start -b          # Start backend slot B
    balloons-server.py start --port 9000 # Start backend on custom port
    balloons-server.py stop -b           # Stop backend slot B
    balloons-server.py restart           # Restart backend slot A
    balloons-server.py list              # Show all running instances
    balloons-server.py ui start          # Start bun dev:tls server
    balloons-server.py ui stop           # Stop bun dev server
    balloons-server.py ui restart        # Restart bun dev server
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Start command
    start_parser = subparsers.add_parser("start", help="Start an instance")
    start_group = start_parser.add_mutually_exclusive_group()
    start_group.add_argument("-a", "--slot-a", dest="slot", action="store_const",
                             const="A", help="Start slot A (8765)")
    start_group.add_argument("-b", "--slot-b", dest="slot", action="store_const",
                             const="B", help="Start slot B (8766)")
    start_group.add_argument("--port", type=int, help="Custom port")

    # Stop command
    stop_parser = subparsers.add_parser("stop", help="Stop an instance")
    stop_group = stop_parser.add_mutually_exclusive_group()
    stop_group.add_argument("-a", "--slot-a", dest="slot", action="store_const",
                            const="A", help="Stop slot A (8765)")
    stop_group.add_argument("-b", "--slot-b", dest="slot", action="store_const",
                            const="B", help="Stop slot B (8766)")
    stop_group.add_argument("--port", type=int, help="Custom port")

    # Restart command
    restart_parser = subparsers.add_parser("restart", help="Restart an instance")
    restart_group = restart_parser.add_mutually_exclusive_group()
    restart_group.add_argument("-a", "--slot-a", dest="slot", action="store_const",
                               const="A", help="Restart slot A (8765)")
    restart_group.add_argument("-b", "--slot-b", dest="slot", action="store_const",
                               const="B", help="Restart slot B (8766)")
    restart_group.add_argument("--port", type=int, help="Custom port")

    # List command
    subparsers.add_parser("list", help="List running instances")

    # UI command (for bun dev server)
    ui_parser = subparsers.add_parser("ui", help="Manage the bun dev server (UI)")
    ui_subparsers = ui_parser.add_subparsers(dest="ui_command", required=True)
    ui_subparsers.add_parser("start", help="Start bun dev:tls server")
    ui_subparsers.add_parser("stop", help="Stop bun dev server")
    ui_subparsers.add_parser("restart", help="Restart bun dev server")
    ui_subparsers.add_parser("status", help="Check if bun dev server is running")

    args = parser.parse_args()

    if args.command == "start":
        port = resolve_port(args)
        start_instance(port)

    elif args.command == "stop":
        port = resolve_port(args)
        stop_instance(port)

    elif args.command == "restart":
        port = resolve_port(args)
        stop_instance(port)
        start_instance(port)

    elif args.command == "list":
        list_instances()

    elif args.command == "ui":
        if args.ui_command == "start":
            start_ui_server()
        elif args.ui_command == "stop":
            stop_ui_server()
        elif args.ui_command == "restart":
            stop_ui_server()
            import time
            time.sleep(1)  # Give bun time to clean up
            start_ui_server()
        elif args.ui_command == "status":
            pid = read_ui_pid()
            if pid:
                print(f"UI server running on port {UI_PORT} (PID {pid})")
            else:
                print("UI server not running")


if __name__ == "__main__":
    main()
