"""Custom tools for navigating linked sessions and app state.

These tools are used by the claude-structured backend to allow Claude
to discover and search content in linked sessions, and to interact
with the Balloons app itself.
"""

import json
from typing import Any, Callable

from session import Session


# Tool names for checking if a tool is a link/session tool
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


def execute_link_tool(
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
        return _execute_list_links(current_session)
    elif name == "follow_link":
        return _execute_follow_link(args, current_session)
    elif name == "search_linked_session":
        return _execute_search_linked(args, current_session)
    elif name == "session_info":
        return _execute_session_info(current_session)
    elif name == "screen_snapshot":
        # No handler registered - app not running or not set up
        return "Error: screen_snapshot requires the Balloons app to be running", True
    else:
        return f"Unknown link tool: {name}", True


def _execute_list_links(session: Session) -> tuple[str, bool]:
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
        linked_session = Session.load(linked_session_id)
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


def _execute_follow_link(args: dict[str, Any], current_session: Session) -> tuple[str, bool]:
    """Load context from a linked session."""
    link_id = args.get("link_id")
    if not link_id:
        return "Error: link_id is required", True

    include_messages = args.get("include_messages", 10)

    # Find the link (use get_all_active_links to include turn-based LinkBlocks)
    links = current_session.get_all_active_links()
    link = next((l for l in links if l.get("link_id") == link_id), None)

    if not link:
        return f"Error: Link not found: {link_id}", True

    linked_session_id = link.get("linked_session_id", "")
    linked_session = Session.load(linked_session_id)

    if not linked_session:
        return f"Error: Linked session not found or deleted: {linked_session_id}", True

    # Build result
    result = {
        "session_id": linked_session.id,
        "name": linked_session.title or linked_session.fork_name or linked_session.id[:8],
        "created": linked_session.created,
        "last_modified": linked_session.last_modified,
        "total_turns": len(linked_session.turns),
        "link_summary": link.get("summary", ""),
    }

    # Include recent turns
    turns = linked_session.turns[-include_messages:] if include_messages > 0 else []
    result["recent_turns"] = [
        {
            "role": turn.role,
            "content": turn.content[:1000] + "..." if len(turn.content) > 1000 else turn.content,
            "timestamp": turn.timestamp,
        }
        for turn in turns
    ]

    return json.dumps(result, indent=2), False


def _execute_search_linked(args: dict[str, Any], current_session: Session) -> tuple[str, bool]:
    """Search within a linked session's conversation history."""
    link_id = args.get("link_id")
    query = args.get("query")

    if not link_id:
        return "Error: link_id is required", True
    if not query:
        return "Error: query is required", True

    # Find the link (use get_all_active_links to include turn-based LinkBlocks)
    links = current_session.get_all_active_links()
    link = next((l for l in links if l.get("link_id") == link_id), None)

    if not link:
        return f"Error: Link not found: {link_id}", True

    linked_session_id = link.get("linked_session_id", "")
    linked_session = Session.load(linked_session_id)

    if not linked_session:
        return f"Error: Linked session not found or deleted: {linked_session_id}", True

    # Search through turns
    query_lower = query.lower()
    matches = []

    for i, turn in enumerate(linked_session.turns):
        if query_lower in turn.content.lower():
            # Found a match - include context
            match_preview = turn.content
            if len(match_preview) > 500:
                # Try to center on the match
                idx = match_preview.lower().find(query_lower)
                start = max(0, idx - 200)
                end = min(len(match_preview), idx + len(query) + 200)
                match_preview = "..." + match_preview[start:end] + "..."

            matches.append({
                "turn_index": i,
                "role": turn.role,
                "timestamp": turn.timestamp,
                "content_preview": match_preview,
            })

    if not matches:
        return f"No matches found for '{query}' in linked session.", False

    # Limit results
    if len(matches) > 20:
        matches = matches[:20]
        truncated = True
    else:
        truncated = False

    result = {
        "query": query,
        "session_name": linked_session.title or linked_session.fork_name or linked_session.id[:8],
        "total_matches": len(matches) if not truncated else f"20+ (showing first 20)",
        "matches": matches,
    }

    return json.dumps(result, indent=2), False


def _execute_session_info(session: Session) -> tuple[str, bool]:
    """Get information about the current session.

    Returns context usage, token counts, fork status, and other metadata
    to help the LLM make informed decisions about forking or merging.
    """
    # Calculate context usage
    context_tokens = session.cached_context_tokens
    context_window = session.context_window
    context_usage_pct = (context_tokens / context_window * 100) if context_window > 0 else 0

    # Count exchanges (user prompts, roughly)
    exchange_count = sum(1 for t in session.turns if t.role == "user")

    # Count different turn types
    user_turns = sum(1 for t in session.turns if t.role == "user")
    assistant_turns = sum(1 for t in session.turns if t.role == "assistant")
    tool_turns = sum(1 for t in session.turns if t.role == "tool")

    # Fork/merge status
    is_fork = session.is_fork()
    is_merged = session.is_merged()

    # Get parent info if this is a fork
    parent_info = None
    if is_fork and session.parent_id:
        parent_session = Session.load(session.parent_id)
        if parent_session:
            parent_info = {
                "id": parent_session.id[:8],
                "name": parent_session.title or parent_session.fork_name or parent_session.id[:8],
            }

    # Get active children (forks)
    active_forks = session.get_active_forks()

    result = {
        "session_id": session.id[:8],
        "name": session.title or session.fork_name or session.id[:8],
        "context": {
            "tokens_used": context_tokens,
            "context_window": context_window,
            "usage_percent": round(context_usage_pct, 1),
            "recommendation": _get_context_recommendation(context_usage_pct),
        },
        "conversation": {
            "exchange_count": exchange_count,
            "total_turns": len(session.turns),
            "user_turns": user_turns,
            "assistant_turns": assistant_turns,
            "tool_turns": tool_turns,
        },
        "fork_status": {
            "is_fork": is_fork,
            "is_merged": is_merged,
            "fork_name": session.fork_name if is_fork else None,
            "parent": parent_info,
            "active_child_forks": len(active_forks),
        },
        "tokens": {
            "total_input": session.total_input_tokens,
            "total_output": session.total_output_tokens,
            "total_cost_usd": round(session.total_cost, 4),
        },
    }

    return json.dumps(result, indent=2), False


def _get_context_recommendation(usage_pct: float) -> str:
    """Get a recommendation based on context usage percentage."""
    if usage_pct < 25:
        return "Low usage - plenty of room for continued conversation"
    elif usage_pct < 50:
        return "Moderate usage - consider forking for large new tasks"
    elif usage_pct < 75:
        return "High usage - forking recommended before starting new substantial work"
    elif usage_pct < 90:
        return "Very high usage - strongly recommend forking with compressed context"
    else:
        return "Critical usage - fork immediately to avoid context overflow"
