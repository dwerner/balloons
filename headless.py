#!/usr/bin/env python3
"""Balloons Headless Server - WebSocket API without TUI.

This module provides a headless entry point for running Balloons as a
WebSocket server without the Textual TUI. Use this for:

- Server deployments (Docker, systemd, etc.)
- React/web frontend connections
- API-only access to Balloons functionality

Usage:
    python headless.py [--host HOST] [--port PORT]

The server exposes the same WebSocket API as the TUI mode, including:
- SessionManagerService: Session lifecycle, streaming, fork/merge
- SessionDataService: Subscription-based session data and streaming
- TaskStateService: LLM streaming events
- GoalTreeStateService: Goal/plan/todo management
- QueueStateService: Message queue management
- ImageService: Image handling
- SoundService: Sound state (no actual playback in headless)
- DebugLogService: Debug log access
"""

import argparse
import asyncio
import signal
from pathlib import Path

from config import get_config
from core import (
    SessionManager,
    get_stream_state,
    ensure_prompts_installed,
)
from core.debug_log import debug_log, Category
from core.server_identity import capture_identity, get_identity, identity_to_dict
from core.goal_tree_state import GoalTreeState
import time

_server_start_time: float = 0.0


def _compute_uptime() -> float:
    """Compute server uptime in seconds."""
    if _server_start_time == 0.0:
        return 0.0
    return time.time() - _server_start_time
from core.queue_state import get_queue_state
from core.supervisor_tools import set_supervisor, shutdown_supervisor
from service import (
    WsServer,
    QueueStateService,
    SessionManagerService,
    GoalTreeStateService,
    TaskStateService,
    SessionDataService,
    ImageService,
    SoundService,
    DebugLogService,
    FileStateService,
    KanbanWebSocketService,
    # Auth
    UserAuthService,
    get_user_storage,
    create_http_auth_server,
)


def _initialize_supervisor() -> None:
    """Initialize the process supervisor for dev server management.

    Creates a Supervisor instance from the Rust backend and registers it
    with supervisor_tools for use by LLM tools.
    """
    try:
        import balloons_storage
        supervisor = balloons_storage.Supervisor()
        set_supervisor(supervisor)
        debug_log.info("Process supervisor initialized", category=Category.LIFECYCLE)
    except ImportError:
        debug_log.warning(
            "balloons_storage not available, supervisor disabled",
            category=Category.LIFECYCLE,
        )
    except Exception as e:
        debug_log.error(f"Failed to initialize supervisor: {e}", category=Category.LIFECYCLE)


async def _load_goal_tree_data(goal_tree_state: GoalTreeState) -> None:
    """Load goal tree data (goals, plans, todos) into GoalTreeState.

    This populates the goal tree so the frontend can see all goals and their
    associated plans and todos. Session bindings are associated dynamically.

    Args:
        goal_tree_state: The GoalTreeState to populate
    """
    from core.async_storage import get_goal_storage

    storage = await get_goal_storage()

    # Begin batch loading to suppress individual notifications
    goal_tree_state.begin_batch_loading()

    try:
        # Load goals
        goals = await storage.list_goals()
        debug_log.info(f"Loaded {len(goals)} goals from storage", category=Category.LIFECYCLE)
        for goal in goals:
            goal_tree_state.add_goal(goal)

        # Load plans
        plans = await storage.list_plans()
        debug_log.info(f"Loaded {len(plans)} plans from storage", category=Category.LIFECYCLE)
        for plan in plans:
            goal_tree_state.add_plan(plan)

        # Load todos with their plan links
        todos = await storage.list_todos(include_spikes=True)
        debug_log.info(f"Loaded {len(todos)} todos from storage", category=Category.LIFECYCLE)
        for todo in todos:
            plan_ids = await storage.get_plans_for_todo(todo.id)
            goal_tree_state.add_todo(todo, plan_ids)
    finally:
        goal_tree_state.end_batch_loading()

    debug_log.info(
        f"Goal tree loaded: {len(goal_tree_state._goals)} goals",
        category=Category.LIFECYCLE,
    )


def _create_session_runner_factory():
    """Create a runner factory function for SessionManager.

    This factory respects per-session backend preferences while falling
    back to the config default when needed.
    """
    from core.runner import SessionRunner
    from core.runner_factory import create_runner
    from session import Session

    def factory(session: Session) -> SessionRunner:
        config = get_config()
        # Use session's preferred backend if set, otherwise config default
        if session.backend_name and session.backend_name in config.backends:
            backend = config.get_backend(session.backend_name)
        else:
            backend = config.get_backend(config.default_backend)
        runner = create_runner(backend)
        return SessionRunner(session, runner=runner)

    return factory


async def run_server(
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Run the headless WebSocket server.

    Args:
        host: Bind address (overrides config)
        port: Bind port (overrides config)
    """
    config = get_config()

    # Enable category-based logging to ~/.balloons/logs/
    # Categories are written when enabled via set_categories() or enable_category()
    debug_log.set_log_dir(Path.home() / ".balloons" / "logs")

    # Configure WebSocket server early to capture port for identity
    ws_config = config.websocket
    if host is not None:
        ws_config.host = host
    if port is not None:
        ws_config.port = port
    ws_config.enabled = True

    # Determine slot from port (A=8700, B=8710, etc.)
    slot = "A" if ws_config.port % 100 == 0 else "B"

    # Track server start time for uptime calculation
    global _server_start_time
    _server_start_time = time.time()

    # Capture server identity (git state, metadata)
    identity = capture_identity(port=ws_config.port, slot=slot)

    # Log server startup with identity
    debug_log.info(
        f"Server starting: {identity.git_commit_short} "
        f"({'dirty' if identity.git_dirty else 'clean'}) "
        f"on {identity.git_branch}",
        category=Category.LIFECYCLE,
        details=identity_to_dict(),
    )

    # Initialize process supervisor
    _initialize_supervisor()

    # Ensure default prompts are installed
    ensure_prompts_installed()

    # Create core components
    runner_factory = _create_session_runner_factory()
    session_manager = SessionManager(runner_factory=runner_factory)
    goal_tree_state = GoalTreeState()
    queue_state = get_queue_state()
    stream_state = get_stream_state()

    # Create services
    session_service = SessionManagerService(
        session_manager,
        stream_state=stream_state,
        queue_state=queue_state,
    )

    # Session loader for SessionDataService
    async def load_session(session_id: str):
        return await session_manager.load_session(session_id)

    # Initialize AsyncStorage for direct LMDB queries
    from core.async_storage import AsyncStorage
    storage = AsyncStorage()

    queue_service = QueueStateService(queue_state)
    goal_service = GoalTreeStateService(goal_tree_state)
    task_service = TaskStateService(stream_state)

    # Initialize SessionDataService with storage for chunked history loading
    # Pass stream_state so it can report accurate isStreaming status
    session_data_service = SessionDataService(storage=storage, stream_state=stream_state)
    session_data_service.set_session_loader(load_session)

    image_service = ImageService()
    sound_service = SoundService()
    debug_log_service = DebugLogService()
    file_service = FileStateService()

    # Wire up event pumping for streaming
    session_service.set_task_state_service(task_service)
    session_service.set_session_data_service(session_data_service)

    # Initialize async components (rebuilds watcher relationships)
    await session_service.initialize()

    # Start event pump
    session_service.start_event_pump()

    # Load goal tree data (goals, plans, todos)
    await _load_goal_tree_data(goal_tree_state)

    # Set up HTTP auth server on port + 1 (e.g. 8701 for WS on 8700)
    auth_port = ws_config.port + 1
    user_storage = await get_user_storage()
    user_service = UserAuthService(user_storage)

    # Bootstrap admin user if configured and no users exist
    if config.auth and config.auth.admin:
        admin_created = await user_service.ensure_admin_exists(
            admin_username=config.auth.admin.username,
            admin_password=config.auth.admin.password,
        )
        if admin_created:
            print(f"Created bootstrap admin user: {config.auth.admin.username}")

    # Create HTTP auth server (handles /auth/login, /users, etc.)
    # Create a modified ws_config with the auth port
    from copy import deepcopy
    auth_ws_config = deepcopy(ws_config)
    auth_ws_config.port = auth_port
    http_auth_server = await create_http_auth_server(auth_ws_config, user_service)

    # Start HTTP auth server
    await http_auth_server.start()
    auth_scheme = "https" if ws_config.tls.enabled else "http"
    print(f"Auth server listening on {auth_scheme}://{ws_config.host}:{auth_port}")

    # Create WebSocket handler with services
    ws_server = WsServer(config=ws_config)
    ws_server.register_service(queue_service)
    ws_server.register_service(session_service)
    ws_server.register_service(goal_service)
    ws_server.register_service(task_service)
    ws_server.register_service(session_data_service)
    ws_server.register_service(image_service)
    ws_server.register_service(sound_service)
    ws_server.register_service(debug_log_service)
    ws_server.register_service(file_service)

    # Kanban service for board/task management
    from core.kanban_service import KanbanService
    kanban_service = KanbanService(storage)
    kanban_ws_service = KanbanWebSocketService(kanban_service)
    ws_server.register_service(kanban_ws_service)

    # Supervisor service for process/host management
    from service import SupervisorStateService
    from service.supervisor_state_service import register_output_callback
    supervisor_service = SupervisorStateService()
    ws_server.register_service(supervisor_service)

    # Register output callback for real-time process output streaming
    register_output_callback()

    # Start WebSocket server directly
    await ws_server.start()
    scheme = "wss" if ws_config.tls.enabled else "ws"
    print(f"Balloons headless server listening on {scheme}://{ws_config.host}:{ws_config.port}")
    debug_log.info(
        f"Headless server started on {ws_config.get_url()}",
        category=Category.LIFECYCLE,
    )

    # Set up signal handlers for graceful shutdown
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()

    def signal_handler():
        print("\nShutting down...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Wait for shutdown signal
    await stop_event.wait()

    # Graceful shutdown
    debug_log.info(
        "Server stopping (graceful shutdown)",
        category=Category.LIFECYCLE,
        details={"reason": "signal", "uptime_seconds": _compute_uptime()},
    )
    session_service.stop_event_pump()
    await ws_server.stop()
    await http_auth_server.stop()
    shutdown_supervisor()

    debug_log.info("Server stopped", category=Category.LIFECYCLE)
    print("Server stopped.")


def main():
    parser = argparse.ArgumentParser(
        description="Balloons Headless Server - WebSocket API without TUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Start with default config
    python headless.py

    # Listen on all interfaces, custom port
    python headless.py --host 0.0.0.0 --port 9000
        """,
    )
    parser.add_argument(
        "--host",
        metavar="HOST",
        help="Bind address (default: from config)",
    )
    parser.add_argument(
        "--port",
        type=int,
        metavar="PORT",
        help="Bind port (default: from config)",
    )

    args = parser.parse_args()

    # Run the server
    try:
        asyncio.run(run_server(
            host=args.host,
            port=args.port,
        ))
    except KeyboardInterrupt:
        # Already handled by signal handler
        pass


if __name__ == "__main__":
    main()
