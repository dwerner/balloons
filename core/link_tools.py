"""Custom tools for navigating linked sessions.

These tools are used by the claude-structured backend to allow Claude
to discover and search content in linked sessions.
"""

import json
from typing import Any

from session import Session


# Tool names for checking if a tool is a link tool
LINK_TOOL_NAMES = {"list_links", "follow_link", "search_linked_session"}


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
    if name == "list_links":
        return _execute_list_links(current_session)
    elif name == "follow_link":
        return _execute_follow_link(args, current_session)
    elif name == "search_linked_session":
        return _execute_search_linked(args, current_session)
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
