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

from config import get_config
from core import (
    SessionManager,
    get_stream_state,
    ensure_prompts_installed,
)
from core.debug_log import debug_log
from core.goal_tree_state import GoalTreeState
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
        debug_log.info("Process supervisor initialized", category="startup")
    except ImportError:
        debug_log.warning(
            "balloons_storage not available, supervisor disabled",
            category="startup",
        )
    except Exception as e:
        debug_log.error(f"Failed to initialize supervisor: {e}", category="startup")


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
        debug_log.info(f"Loaded {len(goals)} goals from storage", category="startup")
        for goal in goals:
            goal_tree_state.add_goal(goal)

        # Load plans
        plans = await storage.list_plans()
        debug_log.info(f"Loaded {len(plans)} plans from storage", category="startup")
        for plan in plans:
            goal_tree_state.add_plan(plan)

        # Load todos with their plan links
        todos = await storage.list_todos(include_spikes=True)
        debug_log.info(f"Loaded {len(todos)} todos from storage", category="startup")
        for todo in todos:
            plan_ids = await storage.get_plans_for_todo(todo.id)
            goal_tree_state.add_todo(todo, plan_ids)
    finally:
        goal_tree_state.end_batch_loading()

    debug_log.info(
        f"Goal tree loaded: {len(goal_tree_state._goals)} goals",
        category="startup",
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

    # Configure debug log if enabled
    if config.debug_log_file:
        debug_log.set_log_file(config.debug_log_file)

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

    # Start event pump
    session_service.start_event_pump()

    # Load goal tree data (goals, plans, todos)
    await _load_goal_tree_data(goal_tree_state)

    # Configure WebSocket server
    ws_config = config.websocket
    # Override with CLI args if provided
    if host is not None:
        ws_config.host = host
    if port is not None:
        ws_config.port = port
    # Force enabled for headless mode
    ws_config.enabled = True

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

    # Start WebSocket server directly
    await ws_server.start()
    scheme = "wss" if ws_config.tls.enabled else "ws"
    print(f"Balloons headless server listening on {scheme}://{ws_config.host}:{ws_config.port}")
    debug_log.info(
        f"Headless server started on {ws_config.get_url()}",
        category="startup",
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
    debug_log.info("Shutting down headless server", category="startup")
    session_service.stop_event_pump()
    await ws_server.stop()
    await http_auth_server.stop()
    shutdown_supervisor()

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
