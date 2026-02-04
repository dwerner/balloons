"""Tool definitions for OpenAI-compatible backends.

Defines tools in OpenAI function calling format for use with OpenRouter,
llamacpp, and other OpenAI-compatible APIs.
"""

# Standard file/shell tools in OpenAI function format
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read the contents of a file. Returns the file content as text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to read (absolute or relative to working directory)"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start reading from (1-indexed). Optional."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to read. Optional."
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Write",
            "description": "Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to write"
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file"
                    }
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Execute a bash command and return its output. Use for git, npm, running tests, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 120, max 600)"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "Find files matching a glob pattern. Returns list of matching file paths.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match (e.g., '**/*.py', 'src/**/*.ts')"
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in. Defaults to working directory."
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search for a pattern in files. Returns matching lines with file paths and line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regular expression pattern to search for"
                    },
                    "path": {
                        "type": "string",
                        "description": "File or directory to search in. Defaults to working directory."
                    },
                    "glob": {
                        "type": "string",
                        "description": "Glob pattern to filter files (e.g., '*.py')"
                    },
                    "case_insensitive": {
                        "type": "boolean",
                        "description": "Whether to ignore case (default false)"
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "List",
            "description": "List files and directories in a path. Like 'ls -la'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list. Defaults to working directory."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "balloon",
            "description": "Send a message or notification to the user through the Balloons UI. Use this to provide status updates, ask questions, or display information that should be highlighted in the chat interface.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to display to the user"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["info", "warning", "error", "success", "question"],
                        "description": "The type of message (affects styling). Defaults to 'info'."
                    }
                },
                "required": ["message"]
            }
        }
    },
]

# Link navigation tools - for traversing linked sessions
LINK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_links",
            "description": "List all links from the current session. Returns link IDs, summaries, and linked session names. Use this to discover what other conversations are linked to this one.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "follow_link",
            "description": "Load context from a linked session. Returns the session metadata and recent conversation history. Use after list_links to explore a specific linked conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "link_id": {
                        "type": "string",
                        "description": "The link ID to follow (from list_links)"
                    },
                    "include_messages": {
                        "type": "integer",
                        "description": "Number of recent messages to include (default 10)"
                    }
                },
                "required": ["link_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_linked_session",
            "description": "Search for content within a linked session's conversation history. Use to find specific information in a linked conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "link_id": {
                        "type": "string",
                        "description": "The link ID of the session to search"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query (case-insensitive substring match)"
                    }
                },
                "required": ["link_id", "query"]
            }
        }
    },
]

# Names of link tools for easy checking
LINK_TOOL_NAMES = {"list_links", "follow_link", "search_linked_session"}


def get_tools_for_request(
    allowed_tools: list[str] | None = None,
    disable_tools: bool = False
) -> list[dict] | None:
    """Get the list of tools to include in an API request.

    Includes both standard file/shell tools and link navigation tools.

    Args:
        allowed_tools: List of tool names to allow, or None for all
        disable_tools: If True, return None (no tools)

    Returns:
        List of tool definitions, or None if tools disabled
    """
    if disable_tools:
        return None

    # Combine standard tools and link tools
    all_tools = TOOLS + LINK_TOOLS

    if allowed_tools is None:
        return all_tools

    # Filter to only allowed tools
    return [
        tool for tool in all_tools
        if tool["function"]["name"] in allowed_tools
    ]
