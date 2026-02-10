"""Service layer for WebSocket exposure.

This module contains WebSocket-exposed services that wrap core state managers.
Services use @ws_expose decorators to mark methods for RPC and @ws_event for events.

The pattern is:
1. Core state managers (TreeState, GoalTreeState) remain pure Python, no network concerns
2. Service classes wrap state managers and expose them via WebSocket
3. Codegen produces TypeScript/Rust clients from the decorated services

Available services:
- TreeStateService: Tree view state (sessions, turns, context modes)
- (Future) GoalService: Goal/plan/todo management
- (Future) StreamingService: LLM streaming coordination
"""

from service.tree_state_service import TreeStateService

__all__ = ["TreeStateService"]
