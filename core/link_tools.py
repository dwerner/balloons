"""Custom tools for navigating linked sessions and app state.

These tools allow the LLM to discover and search content in linked sessions,
and to interact with the Balloons app itself.

Tool definitions are in tools.py (BALLOON_TOOLS). This module contains
the execution logic.
"""

import json
from typing import Any, Callable

from core.async_storage import GoalStorage
from session import Session


# Tool names handled by this module
LINK_TOOL_NAMES = {"list_links", "follow_link", "search_linked_session", "session_info", "screen_snapshot"}

# Registry for app-level tool handlers (tools that need app access, not just session)
# Maps tool_name -> callable that returns (result_string, is_error)
_app_tool_handlers: dict[str, Callable[[], tuple[str, bool]]] = {}


def register_app_tool_handler(tool_name: str, handler: Callable[[], tuple[str, bool]]) -> None:
    """Register a handler for an app-level tool.

    App-level tools need access to the running app instance (e.g., for screen capture).
    The app registers handlers during startup.

    Args:
        tool_name: Name of the tool (e.g., "screen_snapshot")
        handler: Callable that executes the tool and returns (result, is_error)
    """
    _app_tool_handlers[tool_name] = handler


def unregister_app_tool_handler(tool_name: str) -> None:
    """Unregister an app-level tool handler."""
    _app_tool_handlers.pop(tool_name, None)


async def execute_link_tool(
    name: str,
    args: dict[str, Any],
    current_session: Session,
) -> tuple[str, bool]:
    """Execute a link navigation tool.

    Args:
        name: Tool name
        args: Tool arguments
        current_session: The current session (for accessing links)

    Returns:
        Tuple of (result_string, is_error)
    """
    # Check for app-level tools first (registered by the running app)
    if name in _app_tool_handlers:
        return _app_tool_handlers[name]()

    if name == "list_links":
        return await _execute_list_links(current_session)
    elif name == "follow_link":
        return await _execute_follow_link(args, current_session)
    elif name == "search_linked_session":
        return await _execute_search_linked(args, current_session)
    elif name == "session_info":
        return await _execute_session_info(current_session)
    elif name == "screen_snapshot":
        # No handler registered - app not running or not set up
        return "Error: screen_snapshot requires the Balloons app to be running", True
    else:
        return f"Unknown link tool: {name}", True


async def _execute_list_links(session: Session) -> tuple[str, bool]:
    """List all links from the current session."""
    links = session.get_all_active_links()

    if not links:
        return "No links found in the current session.", False

    results = []
    for link in links:
        link_id = link.get("link_id", "")
        linked_session_id = link.get("linked_session_id", "")
        summary = link.get("summary", "")

        # Load the linked session to get its name
        linked_session = await Session.load(linked_session_id)
        if linked_session:
            name = linked_session.title or linked_session.fork_name or linked_session_id[:8]
            message_count = len(linked_session.turns)
        else:
            name = f"[deleted: {linked_session_id[:8]}]"
            message_count = 0

        results.append({
            "link_id": link_id,
            "linked_session_name": name,
            "summary": summary,
            "message_count": message_count,
        })

    return json.dumps(results, indent=2), False


async def _execute_follow_link(args: dict[str, Any], current_session: Session) -> tuple[str, bool]:
    """Load context from a linked session.

    Accepts either:
    - link_id: Follow an explicit LinkBlock by its ID
    - session_id: Directly load any session by ID (for fork/merge traversal)
    """
    link_id = args.get("link_id")
    session_id = args.get("session_id")

    if not link_id and not session_id:
        return "Error: link_id or session_id is required", True

    # Pagination parameters
    limit = args.get("limit", 10)  # Number of turns to return
    offset = args.get("offset", None)  # Turn index to start from (None = from end)

    # Max content per turn - default 10000 chars, can be increased with full_content=true
    full_content = args.get("full_content", False)
    max_content_len = 100000 if full_content else 10000

    # Direct session access (for fork/merge traversal)
    if session_id:
        linked_session = await Session.load(session_id)
        if not linked_session:
            return f"Error: Session not found: {session_id}", True
    else:
        # Find the link (use get_all_active_links to include turn-based LinkBlocks)
        links = current_session.get_all_active_links()
        link = next((l for l in links if l.get("link_id") == link_id), None)

        if not link:
            return f"Error: Link not found: {link_id}", True

        linked_session_id = link.get("linked_session_id", "")
        linked_session = await Session.load(linked_session_id)

        if not linked_session:
            return f"Error: Linked session not found or deleted: {linked_session_id}", True

    total_turns = len(linked_session.turns)

    # Build result
    result = {
        "session_id": linked_session.id,
        "name": linked_session.title or linked_session.fork_name or linked_session.id[:8],
        "created": linked_session.created,
        "last_modified": linked_session.last_modified,
        "total_turns": total_turns,
    }

    # Include link summary if accessed via link_id
    if link_id and not session_id:
        result["link_summary"] = link.get("summary", "")

    # Get turns with pagination
    if offset is not None:
        # Explicit offset: get turns starting at offset
        start_idx = max(0, offset)
        end_idx = min(total_turns, start_idx + limit)
        turns = linked_session.turns[start_idx:end_idx]
        result["pagination"] = {
            "offset": start_idx,
            "limit": limit,
            "returned": len(turns),
            "has_more_before": start_idx > 0,
            "has_more_after": end_idx < total_turns,
        }
    else:
        # No offset: get last N turns (original behavior)
        turns = linked_session.turns[-limit:] if limit > 0 else []
        start_idx = max(0, total_turns - limit)
        result["pagination"] = {
            "offset": start_idx,
            "limit": limit,
            "returned": len(turns),
            "has_more_before": start_idx > 0,
            "has_more_after": False,
        }

    result["turns"] = [
        {
            "index": start_idx + i,
            "role": turn.role,
            "content": turn.content[:max_content_len] + "..." if len(turn.content) > max_content_len else turn.content,
            "timestamp": turn.timestamp,
        }
        for i, turn in enumerate(turns)
    ]

    return json.dumps(result, indent=2), False


async def _execute_search_linked(args: dict[str, Any], current_session: Session) -> tuple[str, bool]:
    """Search within a linked session's conversation history."""
    link_id = args.get("link_id")
    query = args.get("query")

    if not link_id:
        return "Error: link_id is required", True
    if not query:
        return "Error: query is required", True

    # Pagination parameters
    limit = args.get("limit", 20)  # Max results to return
    offset = args.get("offset", 0)  # Skip first N matches

    # Content options
    full_content = args.get("full_content", False)  # Return full turn content
    max_preview_len = 10000 if full_content else 2000  # Preview length

    # Find the link (use get_all_active_links to include turn-based LinkBlocks)
    links = current_session.get_all_active_links()
    link = next((l for l in links if l.get("link_id") == link_id), None)

    if not link:
        return f"Error: Link not found: {link_id}", True

    linked_session_id = link.get("linked_session_id", "")
    linked_session = await Session.load(linked_session_id)

    if not linked_session:
        return f"Error: Linked session not found or deleted: {linked_session_id}", True

    # Search through turns
    query_lower = query.lower()
    all_matches = []

    for i, turn in enumerate(linked_session.turns):
        if query_lower in turn.content.lower():
            all_matches.append((i, turn))

    total_matches = len(all_matches)

    if total_matches == 0:
        return f"No matches found for '{query}' in linked session.", False

    # Apply pagination
    paginated_matches = all_matches[offset:offset + limit]

    matches = []
    for i, turn in paginated_matches:
        # Build content preview
        if full_content:
            content = turn.content[:max_preview_len]
            if len(turn.content) > max_preview_len:
                content += "..."
        else:
            # Try to center on the match
            match_preview = turn.content
            if len(match_preview) > max_preview_len:
                idx = match_preview.lower().find(query_lower)
                start = max(0, idx - max_preview_len // 2)
                end = min(len(match_preview), idx + len(query) + max_preview_len // 2)
                match_preview = ("..." if start > 0 else "") + match_preview[start:end] + ("..." if end < len(turn.content) else "")
            content = match_preview

        matches.append({
            "turn_index": i,
            "role": turn.role,
            "timestamp": turn.timestamp,
            "content_preview": content,
        })

    result = {
        "query": query,
        "session_name": linked_session.title or linked_session.fork_name or linked_session.id[:8],
        "total_matches": total_matches,
        "pagination": {
            "offset": offset,
            "limit": limit,
            "returned": len(matches),
            "has_more": offset + len(matches) < total_matches,
        },
        "matches": matches,
    }

    return json.dumps(result, indent=2), False


async def _execute_session_info(session: Session) -> tuple[str, bool]:
    """Get information about the current session.

    Returns info to help the LLM understand session state and navigate the fork tree.
    """
    # Always recalculate context tokens from turns to ensure accuracy
    # This updates the cached value if it differs from the calculated value
    context_tokens = session.ensure_context_tokens(force_recalculate=True)
    context_window = session.context_window
    context_usage_pct = (context_tokens / context_window * 100) if context_window > 0 else 0

    # Build parents array (empty if root session)
    parents = await _build_parents(session)

    # Get effective backend name (explicit or default)
    backend_name = session.backend_name
    if not backend_name:
        try:
            from config import get_config
            config = get_config()
            backend_name = config.default_backend
        except Exception:
            backend_name = None

    result = {
        "name": session.title or session.fork_name or session.id[:8],
        "session_id": session.id,  # Full session ID for navigation
        "backend": backend_name,  # Current backend (explicit or default)
        "parents": parents,  # empty = root session, non-empty = in a fork
        "context_tokens": context_tokens,
        "context_pct": round(context_usage_pct, 1),
    }

    # If this session was merged TO its parent, include that info
    # First try to get from MergedToBlock turn (has merge_id for proper linking)
    merged_to_block = session.get_merged_to_block()
    if merged_to_block:
        result["merged_to"] = {
            "merge_id": merged_to_block.merge_id,
            "parent_session_id": merged_to_block.parent_session_id,
            "parent_turn": merged_to_block.parent_turn,
            "summary": merged_to_block.message[:500] if merged_to_block.message else "",
        }
    elif session.is_merged() and session.parent_id:
        # Fallback to session metadata for older sessions
        result["merged_to"] = {
            "parent_session_id": session.parent_id,
            "parent_turn": session.merge_point_turn,
            "summary": session.merge_message[:500] if session.merge_message else "",
        }
    else:
        result["merged_to"] = None

    # Find merge turns FROM child forks into this session
    merged_from = []
    for turn_idx, block in session.get_all_merge_blocks():
        merged_from.append({
            "turn": turn_idx,
            "session_id": block.child_session_id,
            "name": block.fork_name,
            "summary": block.message[:200] if block.message else "",
        })
    result["merged_from"] = merged_from

    # Find fork turns TO child sessions (active or merged)
    forked_to = []
    for turn_idx, block in session.get_all_fork_blocks():
        forked_to.append({
            "turn": turn_idx,
            "session_id": block.child_session_id,
            "name": block.fork_name,
            "status": block.status,
        })
    result["forked_to"] = forked_to

    # Get session binding if any
    storage = GoalStorage()
    bindings = await storage.get_bindings_for_session(session.id, active_only=True)
    if bindings:
        # Use the most recent active binding
        binding = bindings[-1]
        result["binding"] = {
            "entity_type": binding.entity_type,
            "entity_id": binding.entity_id,
            "role": binding.role,
        }

    return json.dumps(result, indent=2), False


async def _build_parents(session: Session) -> list[str]:
    """Build list of parent sessions from immediate parent to root.

    Returns list like ["def456:auth-bug", "abc123:root"] (immediate parent first).
    Empty list means this is a root session.
    """
    parents = []
    current = await Session.load(session.parent_id) if session.parent_id else None

    while current:
        name = current.fork_name or current.title or current.id[:8]
        parents.append(f"{current.id[:8]}:{name}")
        current = await Session.load(current.parent_id) if current.parent_id else None

    return parents
