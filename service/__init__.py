"""Service layer for WebSocket exposure.

This module contains WebSocket-exposed services that wrap core state managers.
Services use @ws_expose decorators to mark methods for RPC and @ws_event for events.

The pattern is:
1. Core state managers (GoalTreeState, StreamState, etc.) remain pure Python, no network concerns
2. Service classes wrap state managers and expose them via WebSocket
3. Codegen produces TypeScript/Rust clients from the decorated services

Available services:
- SessionDataService: Session lifecycle and subscription-based streaming
- QueueStateService: Message queue state (enqueue, dequeue, pause, priority)
- SessionManagerService: Session lifecycle (create, switch, list, delete, streaming status)
- GoalTreeStateService: Goal/plan/todo management with session bindings
- TaskStateService: LLM task lifecycle (streaming, progress, completion)

WebSocket server:
- WsServer: WebSocket server with JSON-RPC dispatch to services
- create_server: Convenience function to create and start a server

Authentication:
- JWTAuth: JWT token generation and validation
- JWTConfig: JWT authentication configuration

Frontend Interaction API:
    For web/mobile frontends to interact with the LLM, use:

    1. SessionManagerService.submit_message(sessionId, content)
       - Submits a prompt and starts streaming
       - Returns SubmitMessageResult with exchange_id for tracking

    2. TaskStateService streaming events:
       - onContentDelta: Text chunks as they arrive
       - onTurnStarted: New turn (assistant, tool_use, tool_result)
       - onToolUseStarted: Tool execution beginning
       - onToolInputDelta: Tool input JSON streaming
       - onToolUse: Tool input complete
       - onToolResult: Tool execution completed
       - onTurnFinished: Turn completed

    Frontend Pattern:
       1. Subscribe to TaskStateService events
       2. Call submitMessage(sessionId, content)
       3. Receive deltas via onContentDelta
       4. Render incrementally
       5. turnFinished signals completion

    Integration (headless mode without TUI):
       # Create services with event pump wiring
       task_service = TaskStateService(get_stream_state())
       session_service = SessionManagerService(
           session_manager,
           task_state_service=task_service,
       )

       # Start event pump to relay streaming events
       session_service.start_event_pump()

       # Register services with WebSocket server
       ws_server.register_service(session_service)
       ws_server.register_service(task_service)

       # Stop pump on shutdown
       session_service.stop_event_pump()
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from service.auth_routes import AuthRoutes
    from service.debug_log_service import DebugLogService
    from service.file_state_service import FileStateService
    from service.goal_tree_state_service import GoalTreeStateService
    from service.http_server import HttpAuthServer, ServerConfig, create_http_auth_server
    from service.image_service import ImageService
    from service.jwt_auth import JWTAuth, JWTConfig, TokenClaims
    from service.kanban_ws_service import KanbanWebSocketService
    from service.lsp_service import LSPService
    from service.queue_state_service import QueueStateService
    from service.session_data_service import SessionDataService
    from service.session_manager_service import SessionManagerService
    from service.sound_service import SoundService
    from service.supervisor_state_service import SupervisorStateService
    from service.task_state_service import TaskStateService
    from service.user_auth import (
        InvalidCredentialsError,
        PasswordHasher,
        User,
        UserAuthError,
        UserAuthService,
        UserDisabledError,
        UserNotFoundError,
        UsernameExistsError,
    )
    from service.user_storage import JsonFileUserStorage, get_user_storage
    from service.ws_server import WsServer, create_server

__all__ = [
    "QueueStateService",
    "SessionManagerService",
    "GoalTreeStateService",
    "TaskStateService",
    "SessionDataService",
    "ImageService",
    "SoundService",
    "DebugLogService",
    "FileStateService",
    "SupervisorStateService",
    "LSPService",
    "KanbanWebSocketService",
    "WsServer",
    "create_server",
    "JWTAuth",
    "JWTConfig",
    "TokenClaims",
    # User authentication
    "UserAuthService",
    "User",
    "PasswordHasher",
    "UserAuthError",
    "UserNotFoundError",
    "InvalidCredentialsError",
    "UserDisabledError",
    "UsernameExistsError",
    "JsonFileUserStorage",
    "get_user_storage",
    # HTTP/Auth
    "AuthRoutes",
    "HttpAuthServer",
    "ServerConfig",
    "create_http_auth_server",
]

_EXPORT_MAP = {
    "QueueStateService": ("service.queue_state_service", "QueueStateService"),
    "SessionManagerService": ("service.session_manager_service", "SessionManagerService"),
    "GoalTreeStateService": ("service.goal_tree_state_service", "GoalTreeStateService"),
    "TaskStateService": ("service.task_state_service", "TaskStateService"),
    "SessionDataService": ("service.session_data_service", "SessionDataService"),
    "ImageService": ("service.image_service", "ImageService"),
    "SoundService": ("service.sound_service", "SoundService"),
    "DebugLogService": ("service.debug_log_service", "DebugLogService"),
    "FileStateService": ("service.file_state_service", "FileStateService"),
    "SupervisorStateService": ("service.supervisor_state_service", "SupervisorStateService"),
    "LSPService": ("service.lsp_service", "LSPService"),
    "KanbanWebSocketService": ("service.kanban_ws_service", "KanbanWebSocketService"),
    "WsServer": ("service.ws_server", "WsServer"),
    "create_server": ("service.ws_server", "create_server"),
    "JWTAuth": ("service.jwt_auth", "JWTAuth"),
    "JWTConfig": ("service.jwt_auth", "JWTConfig"),
    "TokenClaims": ("service.jwt_auth", "TokenClaims"),
    "UserAuthService": ("service.user_auth", "UserAuthService"),
    "User": ("service.user_auth", "User"),
    "PasswordHasher": ("service.user_auth", "PasswordHasher"),
    "UserAuthError": ("service.user_auth", "UserAuthError"),
    "UserNotFoundError": ("service.user_auth", "UserNotFoundError"),
    "InvalidCredentialsError": ("service.user_auth", "InvalidCredentialsError"),
    "UserDisabledError": ("service.user_auth", "UserDisabledError"),
    "UsernameExistsError": ("service.user_auth", "UsernameExistsError"),
    "JsonFileUserStorage": ("service.user_storage", "JsonFileUserStorage"),
    "get_user_storage": ("service.user_storage", "get_user_storage"),
    "AuthRoutes": ("service.auth_routes", "AuthRoutes"),
    "HttpAuthServer": ("service.http_server", "HttpAuthServer"),
    "ServerConfig": ("service.http_server", "ServerConfig"),
    "create_http_auth_server": ("service.http_server", "create_http_auth_server"),
}

def __getattr__(name: str) -> Any:
    if name in _EXPORT_MAP:
        module_name, attr_name = _EXPORT_MAP[name]
        module = import_module(module_name)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


