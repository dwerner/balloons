"""Watcher mode tools for cross-session communication.

Provides tools that allow a watcher session to interact with its target session.
"""

import json
from typing import Any

from session import Session
from core.debug_log import debug_log, Category


# Tool names handled by this module
WATCHER_TOOL_NAMES = {
    "send_to_target",
    "start_watching_session",
    "stop_watching_session",
}


async def execute_watcher_tool(
    name: str,
    args: dict[str, Any],
    current_session: Session,
) -> tuple[str, bool]:
    """Execute a watcher tool.

    Args:
        name: Tool name
        args: Tool arguments
        current_session: The watcher session executing the tool

    Returns:
        Tuple of (result_string, is_error)
    """
    if name == "send_to_target":
        return await _execute_send_to_target(args, current_session)
    elif name == "start_watching_session":
        return await _execute_start_watching_session(args, current_session)
    elif name == "stop_watching_session":
        return await _execute_stop_watching_session(args, current_session)
    else:
        return f"Unknown watcher tool: {name}", True


async def _execute_send_to_target(args: dict[str, Any], watcher_session: Session) -> tuple[str, bool]:
    """Send a message to the target session.

    The message is queued and sent after any current exchange completes.
    Uses both:
    - The target session's persisted message_queue for durability
    - The runtime QueueState for UI updates (if available)

    Args:
        args: {"message": str} - The message to send
        watcher_session: The watcher session

    Returns:
        Tuple of (result_string, is_error)
    """
    message = args.get("message")
    if not message:
        return "Error: message is required", True

    # Find the target session ID from the most recent WatchStartBlock
    target_session_id = watcher_session.get_watch_target_id()
    if not target_session_id:
        return "Error: This session is not watching any target session", True

    # Load the target session
    target_session = await Session.load(target_session_id)
    if not target_session:
        return f"Error: Target session not found: {target_session_id}", True

    # Get session names for the response
    watcher_name = watcher_session.title or watcher_session.fork_name or watcher_session.id[:8]
    target_name = target_session.title or target_session.fork_name or target_session.id[:8]

    # Format the message with attribution
    attributed_message = f"[Message from watcher: {watcher_name}]\n\n{message}"

    # Add message to target session's persisted queue with source attribution
    queued_msg = target_session.message_queue.add(
        content=attributed_message,
        source=f"watcher:{watcher_session.id}",
        source_name=watcher_name,
    )

    # Save the target session to persist the queued message
    await target_session.save()

    # Also add to runtime QueueState for UI updates
    try:
        from core.queue_state import get_queue_state
        queue_state = get_queue_state()
        # Pass source so SessionManagerService can identify this as a watcher message
        # and trigger immediate processing if target is idle
        queue_state.add_message(
            target_session_id,
            attributed_message,
            source=f"watcher:{watcher_session.id}",
        )
    except Exception as e:
        # QueueState may not be initialized in all contexts
        debug_log.debug(
            f"Could not add to QueueState: {e}",
            category=Category.SESSION,
        )

    debug_log.info(
        f"Watcher {watcher_session.id[:8]} sent message to target {target_session_id[:8]}",
        category=Category.SESSION,
        details={
            "message_id": queued_msg.id,
            "message_preview": message[:100],
            "queue_size": len(target_session.message_queue.messages),
        },
    )

    result = {
        "status": "queued",
        "message_id": queued_msg.id,
        "message_preview": message[:100] + "..." if len(message) > 100 else message,
        "target_session": target_name,
        "from_watcher": watcher_name,
        "queue_position": len(target_session.message_queue.messages),
        "note": "Message queued. It will be sent when the target completes its current exchange.",
    }

    return json.dumps(result, indent=2), False



async def _execute_start_watching_session(args: dict[str, Any], current_session: Session) -> tuple[str, bool]:
    """Attach a session as a watcher of a target session."""
    session_id = args.get("session_id")
    target_session_id = args.get("target_session_id")
    if not session_id:
        return "Error: session_id is required", True
    if not target_session_id:
        return "Error: target_session_id is required", True

    try:
        from service.session_manager_service import SessionManagerService
        from core.stream_state import get_stream_state
        from core.manager import SessionManager
        manager = SessionManager()
        service = SessionManagerService(manager, stream_state=get_stream_state())
        await service.initialize()
        result = await service.start_watching_session(
            session_id=session_id,
            target_session_id=target_session_id,
        )
    except Exception as e:
        debug_log.error(
            f"Failed to start watching session via watcher tool from {current_session.id[:8]}: {e}",
            category=Category.SESSION,
        )
        return f"Error: Failed to start watching session: {e}", True

    if not result.success:
        return result.error or "Error: Failed to start watching session", True

    payload = {
        "status": "watching",
        "watcher_session_id": result.watcher_session_id,
        "target_session_id": result.target_session_id,
        "target_session_name": result.target_session_name,
        "watcher_name": result.watcher_name,
    }
    return json.dumps(payload, indent=2), False


async def _execute_stop_watching_session(args: dict[str, Any], current_session: Session) -> tuple[str, bool]:
    """Stop a session from watching one or more target sessions."""
    session_id = args.get("session_id")
    if not session_id:
        return "Error: session_id is required", True

    target_session_id = args.get("target_session_id")
    reason = args.get("reason", "user")

    try:
        from service.session_manager_service import SessionManagerService
        from core.stream_state import get_stream_state
        from core.manager import SessionManager
        manager = SessionManager()
        service = SessionManagerService(manager, stream_state=get_stream_state())
        await service.initialize()
        success = await service.stop_watching_session(
            session_id=session_id,
            target_session_id=target_session_id,
            reason=reason,
        )
    except Exception as e:
        debug_log.error(
            f"Failed to stop watching session via watcher tool from {current_session.id[:8]}: {e}",
            category=Category.SESSION,
        )
        return f"Error: Failed to stop watching session: {e}", True

    if not success:
        return "Error: Failed to stop watching session", True

    payload = {
        "status": "stopped",
        "session_id": session_id,
        "target_session_id": target_session_id,
        "reason": reason,
    }
    return json.dumps(payload, indent=2), False
