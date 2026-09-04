#!/usr/bin/env python3
"""Balloons Headless Server - WebSocket API without TUI."""

import argparse
import asyncio
import signal
import time
from copy import deepcopy
from pathlib import Path

from config import get_config
from core import SessionManager, get_stream_state, ensure_prompts_installed
from core.debug_log import debug_log, Category
from core.server_identity import capture_identity, identity_to_dict
from core.queue_state import get_queue_state
from core.supervisor_tools import set_supervisor, shutdown_supervisor
from service import (
    WsServer,
    QueueStateService,
    SessionManagerService,
    TaskStateService,
    SessionDataService,
    ImageService,
    SoundService,
    DebugLogService,
    TrafficCaptureService,
    FileStateService,
    UserAuthService,
    get_user_storage,
    create_http_auth_server,
)

_server_start_time: float = 0.0


def _compute_uptime() -> float:
    if _server_start_time == 0.0:
        return 0.0
    return time.time() - _server_start_time


def _initialize_supervisor() -> None:
    try:
        import balloons_py
        supervisor = balloons_py.Supervisor()
        set_supervisor(supervisor)
        debug_log.info("Process supervisor initialized", category=Category.LIFECYCLE)
    except ImportError:
        debug_log.warning(
            "balloons_py not available, supervisor disabled",
            category=Category.LIFECYCLE,
        )
    except Exception as e:
        debug_log.error(f"Failed to initialize supervisor: {e}", category=Category.LIFECYCLE)


def _create_session_runner_factory():
    from core.runner import SessionRunner
    from core.runner_factory import create_runner
    from session import Session

    def factory(session: Session) -> SessionRunner:
        config = get_config()
        if session.backend_name and session.backend_name in config.backends:
            backend = config.get_backend(session.backend_name)
        else:
            backend = config.get_backend(config.default_backend)
        runner = create_runner(backend)
        return SessionRunner(session, runner=runner)

    return factory


async def run_server(host: str | None = None, port: int | None = None) -> None:
    config = get_config()
    debug_log.set_log_dir(Path.home() / ".balloons" / "logs")

    ws_config = config.websocket
    if host is not None:
        ws_config.host = host
    if port is not None:
        ws_config.port = port
    ws_config.enabled = True

    slot = "A" if ws_config.port % 100 == 0 else "B"

    global _server_start_time
    _server_start_time = time.time()

    identity = capture_identity(port=ws_config.port, slot=slot)
    debug_log.info(
        f"Server starting: {identity.git_commit_short} "
        f"({'dirty' if identity.git_dirty else 'clean'}) "
        f"on {identity.git_branch}",
        category=Category.LIFECYCLE,
        details=identity_to_dict(),
    )

    _initialize_supervisor()
    ensure_prompts_installed()

    runner_factory = _create_session_runner_factory()
    session_manager = SessionManager(
        runner_factory=runner_factory,
        default_enabled_tools=config.default_enabled_tools,
    )
    queue_state = get_queue_state()
    stream_state = get_stream_state()

    session_service = SessionManagerService(
        session_manager,
        stream_state=stream_state,
        queue_state=queue_state,
    )
    session_manager.set_service(session_service)

    async def load_session(session_id: str):
        return await session_manager.load_session(session_id)

    from core.async_storage import AsyncStorage
    storage = AsyncStorage()

    queue_service = QueueStateService(queue_state)
    task_service = TaskStateService(stream_state)
    session_data_service = SessionDataService(storage=storage, stream_state=stream_state)
    session_data_service.set_session_loader(load_session)

    image_service = ImageService()
    sound_service = SoundService()
    debug_log_service = DebugLogService()
    traffic_capture_service = TrafficCaptureService()
    file_service = FileStateService()

    session_service.set_task_state_service(task_service)
    session_service.set_session_data_service(session_data_service)
    session_data_service.set_manager(session_service)

    from plugins import get_registry
    get_registry().set_event_emitter(session_service.emit_domain_event)

    await session_service.initialize()
    session_service.start_event_pump()

    # Load the pinned-session cache so synchronous event emission reports
    # accurate is_pinned (see SessionDataService.refresh_pinned_cache).
    await session_data_service.refresh_pinned_cache()

    auth_port = ws_config.port + 1
    user_storage = await get_user_storage()
    user_service = UserAuthService(user_storage)

    if config.auth and config.auth.admin:
        admin_created = await user_service.ensure_admin_exists(
            admin_username=config.auth.admin.username,
            admin_password=config.auth.admin.password,
        )
        if admin_created:
            print(f"Created bootstrap admin user: {config.auth.admin.username}")

    auth_ws_config = deepcopy(ws_config)
    auth_ws_config.port = auth_port
    http_auth_server = await create_http_auth_server(
        auth_ws_config, user_service, upload_dir=image_service.upload_dir
    )
    await http_auth_server.start()
    auth_scheme = "https" if ws_config.tls.enabled else "http"
    print(f"Auth server listening on {auth_scheme}://{ws_config.host}:{auth_port}")

    ws_server = WsServer(config=ws_config)
    ws_server.register_service(queue_service)
    ws_server.register_service(session_service)
    ws_server.register_service(task_service)
    ws_server.register_service(session_data_service)
    ws_server.register_service(image_service)
    ws_server.register_service(sound_service)
    ws_server.register_service(debug_log_service)
    ws_server.register_service(traffic_capture_service)
    ws_server.register_service(file_service)

    from service import SupervisorStateService, LSPService, BrowserStateService
    from service.supervisor_state_service import register_output_callback
    supervisor_service = SupervisorStateService()
    ws_server.register_service(supervisor_service)

    lsp_service = LSPService()
    ws_server.register_service(lsp_service)

    browser_service = BrowserStateService()
    ws_server.register_service(browser_service)

    from plugins.rpc_service import DomainRpcService
    domain_rpc_service = DomainRpcService()
    domain_rpc_service.set_manager(session_service)
    domain_rpc_service.set_event_emitter(session_service.emit_domain_event)
    ws_server.register_service(domain_rpc_service)
    get_registry().set_rpc_service(domain_rpc_service)

    register_output_callback()

    await ws_server.start()
    scheme = "wss" if ws_config.tls.enabled else "ws"
    print(f"Balloons headless server listening on {scheme}://{ws_config.host}:{ws_config.port}")
    debug_log.info(
        f"Headless server started on {ws_config.get_url()}",
        category=Category.LIFECYCLE,
    )

    shutdown_event = asyncio.Event()

    def signal_handler():
        debug_log.info("Shutdown signal received", category=Category.LIFECYCLE)
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await shutdown_event.wait()
    finally:
        debug_log.info("Shutting down headless server", category=Category.LIFECYCLE)
        session_service.stop_event_pump()
        await ws_server.stop()
        await http_auth_server.stop()
        shutdown_supervisor()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Balloons headless WebSocket server")
    parser.add_argument("--host", help="Bind host (overrides config)")
    parser.add_argument("--port", type=int, help="Bind port (overrides config)")
    args = parser.parse_args()
    asyncio.run(run_server(host=args.host, port=args.port))


if __name__ == "__main__":
    main()
