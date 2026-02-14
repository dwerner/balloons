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
"""

from service.tree_state_service import TreeStateService
from service.queue_state_service import QueueStateService
from service.session_manager_service import SessionManagerService
from service.goal_tree_state_service import GoalTreeStateService
from service.task_state_service import TaskStateService

__all__ = [
    "TreeStateService",
    "QueueStateService",
    "SessionManagerService",
    "GoalTreeStateService",
    "TaskStateService",
]
