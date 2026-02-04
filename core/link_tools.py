"""Custom tools for navigating linked sessions.

These tools are used by the claude-structured backend to allow Claude
to discover and search content in linked sessions.
"""

import json
from typing import Any

from session import Session


# Tool definitions in the format we'll inject into the prompt
LINK_TOOLS = [
    {
        "name": "list_links",
        "description": "List all links from the current session. Returns link IDs, summaries, and linked session names.",
        "parameters": {}
    },
    {
        "name": "follow_link",
        "description": "Load context from a linked session. Returns the session metadata and recent conversation history.",
        "parameters": {
            "link_id": {
                "type": "string",
                "description": "The link ID to follow (from list_links)",
                "required": True
            },
            "include_messages": {
                "type": "integer",
                "description": "Number of recent messages to include (default 10)",
                "required": False
            }
        }
    },
    {
        "name": "search_linked_session",
        "description": "Search for content within a linked session's conversation history.",
        "parameters": {
            "link_id": {
                "type": "string",
                "description": "The link ID of the session to search",
                "required": True
            },
            "query": {
                "type": "string",
                "description": "Search query (case-insensitive substring match)",
                "required": True
            }
        }
    },
]


def get_link_tools_prompt() -> str:
    """Generate the system prompt section describing available link tools.

    Returns:
        Prompt text describing the tools and expected output format.
    """
    tools_json = json.dumps(LINK_TOOLS, indent=2)

    return f"""## Custom Link Navigation Tools

You have access to custom tools for navigating linked sessions. These links connect
related conversations and allow you to discover context from other chats.

### Available Tools
{tools_json}

### How to Use These Tools

When you need to use one of these tools, output a tool call in this exact format:

<balloons-tool>
{{"name": "tool_name", "args": {{"arg1": "value1"}}}}
</balloons-tool>

For example, to list available links:

<balloons-tool>
{{"name": "list_links", "args": {{}}}}
</balloons-tool>

Or to follow a specific link:

<balloons-tool>
{{"name": "follow_link", "args": {{"link_id": "abc123", "include_messages": 5}}}}
</balloons-tool>

After you output a tool call, the system will execute it and provide the result.
You can then use that information in your response.

### Important Notes
- Only call one tool at a time
- Wait for the tool result before making another tool call
- Tool results will appear in a <balloons-tool-result> block
"""


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
            message_count = len(linked_session.messages)
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
        "total_messages": len(linked_session.messages),
        "link_summary": link.get("summary", ""),
    }

    # Include recent messages
    messages = linked_session.messages[-include_messages:] if include_messages > 0 else []
    result["recent_messages"] = [
        {
            "role": msg.role,
            "content": msg.content[:1000] + "..." if len(msg.content) > 1000 else msg.content,
            "timestamp": msg.timestamp,
        }
        for msg in messages
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

    # Search through messages
    query_lower = query.lower()
    matches = []

    for i, msg in enumerate(linked_session.messages):
        if query_lower in msg.content.lower():
            # Found a match - include context
            match_preview = msg.content
            if len(match_preview) > 500:
                # Try to center on the match
                idx = match_preview.lower().find(query_lower)
                start = max(0, idx - 200)
                end = min(len(match_preview), idx + len(query) + 200)
                match_preview = "..." + match_preview[start:end] + "..."

            matches.append({
                "message_index": i,
                "role": msg.role,
                "timestamp": msg.timestamp,
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
