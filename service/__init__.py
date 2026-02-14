"""Service layer for WebSocket exposure.

This module contains WebSocket-exposed services that wrap core state managers.
Services use @ws_expose decorators to mark methods for RPC and @ws_event for events.

The pattern is:
1. Core state managers (TreeState, GoalTreeState) remain pure Python, no network concerns
2. Service classes wrap state managers and expose them via WebSocket
3. Codegen produces TypeScript/Rust clients from the decorated services

Available services:
- TreeStateService: Tree view state (sessions, turns, context modes)
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

from service.tree_state_service import TreeStateService
from service.queue_state_service import QueueStateService
from service.session_manager_service import SessionManagerService
from service.goal_tree_state_service import GoalTreeStateService
from service.task_state_service import TaskStateService
from service.ws_server import WsServer, create_server
from service.jwt_auth import JWTAuth, JWTConfig, TokenClaims

__all__ = [
    "TreeStateService",
    "QueueStateService",
    "SessionManagerService",
    "GoalTreeStateService",
    "TaskStateService",
    "WsServer",
    "create_server",
    "JWTAuth",
    "JWTConfig",
    "TokenClaims",
]
