"""LSP tools for LLM semantic code understanding.

These tools wrap the LSP client to provide semantic code intelligence
capabilities to the LLM. Unlike simple text search, these tools understand
code structure and provide accurate type information, references, and more.

Tool categories:
- Navigation: go_to_definition, find_references, get_type_hierarchy
- Understanding: get_hover_info, get_document_symbols, get_workspace_symbols
- Queries: semantic queries about code structure

All tools are designed to provide formatted, LLM-friendly output.
"""

import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .debug_log import debug_log, Category
from .lsp_client import get_lsp_client

if TYPE_CHECKING:
    from session import Session


# Tool names handled by this module
LSP_TOOL_NAMES = {
    "lsp_hover",
    "lsp_definition",
    "lsp_references",
    "lsp_symbols",
    "lsp_workspace_symbols",
    "lsp_status",
    "lsp_start",
    "lsp_stop",
    "lsp_restart",
}


async def execute_lsp_tool(
    name: str,
    args: dict[str, Any],
    session: "Session",
    working_dir: str,
) -> tuple[str, bool]:
    """Execute an LSP tool.

    Args:
        name: Tool name
        args: Tool arguments
        session: The current session
        working_dir: Working directory

    Returns:
        Tuple of (result_string, is_error)
    """
    try:
        if name == "lsp_hover":
            return await _execute_hover(args, working_dir)
        elif name == "lsp_definition":
            return await _execute_definition(args, working_dir)
        elif name == "lsp_references":
            return await _execute_references(args, working_dir)
        elif name == "lsp_symbols":
            return await _execute_symbols(args, working_dir)
        elif name == "lsp_workspace_symbols":
            return await _execute_workspace_symbols(args, working_dir)
        elif name == "lsp_status":
            return await _execute_status(args, working_dir)
        elif name == "lsp_start":
            return await _execute_start(args, working_dir)
        elif name == "lsp_stop":
            return await _execute_stop(args, working_dir)
        elif name == "lsp_restart":
            return await _execute_restart(args, working_dir)
        else:
            return f"Unknown LSP tool: {name}", True
    except Exception as e:
        debug_log.error(f"LSP tool error: {e}", category=Category.SUPERVISOR)
        return f"Error: {str(e)}", True


def _resolve_path(file_path: str, working_dir: str) -> str:
    """Resolve a file path to absolute."""
    path = Path(file_path)
    if not path.is_absolute():
        path = Path(working_dir) / path
    return str(path.resolve())


def _format_location(location: dict) -> str:
    """Format an LSP Location for display."""
    uri = location.get("uri", "")
    if uri.startswith("file://"):
        uri = uri[7:]

    range_info = location.get("range", {})
    start = range_info.get("start", {})
    line = start.get("line", 0) + 1  # 1-indexed for display
    char = start.get("character", 0)

    return f"{uri}:{line}:{char}"


def _format_hover_contents(contents: Any) -> str:
    """Format hover contents for display."""
    if isinstance(contents, str):
        return contents
    elif isinstance(contents, dict):
        # MarkedString or MarkupContent
        value = contents.get("value", "")
        kind = contents.get("kind", "")
        if kind == "markdown":
            return value
        return value
    elif isinstance(contents, list):
        # Array of MarkedString
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("value", ""))
        return "\n\n".join(parts)
    return str(contents)


def _format_symbol(symbol: dict, indent: int = 0) -> str:
    """Format a DocumentSymbol or SymbolInformation for display."""
    prefix = "  " * indent
    name = symbol.get("name", "?")
    kind = _symbol_kind_name(symbol.get("kind", 0))

    # DocumentSymbol has 'range', SymbolInformation has 'location'
    if "range" in symbol:
        range_info = symbol["range"]
        line = range_info.get("start", {}).get("line", 0) + 1
        detail = symbol.get("detail", "")
        if detail:
            line_str = f"{prefix}{kind} {name}: {detail} (line {line})"
        else:
            line_str = f"{prefix}{kind} {name} (line {line})"
    else:
        location = symbol.get("location", {})
        line_str = f"{prefix}{kind} {name} @ {_format_location(location)}"

    lines = [line_str]

    # Recursively format children
    for child in symbol.get("children", []):
        lines.append(_format_symbol(child, indent + 1))

    return "\n".join(lines)


def _symbol_kind_name(kind: int) -> str:
    """Convert LSP SymbolKind to string."""
    kinds = {
        1: "File",
        2: "Module",
        3: "Namespace",
        4: "Package",
        5: "Class",
        6: "Method",
        7: "Property",
        8: "Field",
        9: "Constructor",
        10: "Enum",
        11: "Interface",
        12: "Function",
        13: "Variable",
        14: "Constant",
        15: "String",
        16: "Number",
        17: "Boolean",
        18: "Array",
        19: "Object",
        20: "Key",
        21: "Null",
        22: "EnumMember",
        23: "Struct",
        24: "Event",
        25: "Operator",
        26: "TypeParameter",
    }
    return kinds.get(kind, "Symbol")


async def _execute_hover(
    args: dict[str, Any],
    working_dir: str,
) -> tuple[str, bool]:
    """Get hover information for a position.

    Shows type information, documentation, and signature for the symbol
    at the given position.
    """
    file_path = args.get("file_path")
    if not file_path:
        return "Error: file_path is required", True

    line = args.get("line")
    if line is None:
        return "Error: line is required (0-indexed)", True

    character = args.get("character", 0)

    file_path = _resolve_path(file_path, working_dir)
    client = get_lsp_client()

    result = await client.get_hover(file_path, line, character)

    if not result:
        return "No hover information available at this position.", False

    contents = result.get("contents")
    if not contents:
        return "No hover information available at this position.", False

    formatted = _format_hover_contents(contents)

    output = {
        "file": file_path,
        "position": {"line": line + 1, "character": character},
        "info": formatted,
    }

    return json.dumps(output, indent=2), False


async def _execute_definition(
    args: dict[str, Any],
    working_dir: str,
) -> tuple[str, bool]:
    """Go to definition for a symbol.

    Returns the location(s) where the symbol at the given position is defined.
    """
    file_path = args.get("file_path")
    if not file_path:
        return "Error: file_path is required", True

    line = args.get("line")
    if line is None:
        return "Error: line is required (0-indexed)", True

    character = args.get("character", 0)

    file_path = _resolve_path(file_path, working_dir)
    client = get_lsp_client()

    result = await client.get_definition(file_path, line, character)

    if not result:
        return "No definition found at this position.", False

    # Format locations
    locations = []
    for loc in result:
        locations.append(_format_location(loc))

    output = {
        "file": file_path,
        "position": {"line": line + 1, "character": character},
        "definitions": locations,
    }

    return json.dumps(output, indent=2), False


async def _execute_references(
    args: dict[str, Any],
    working_dir: str,
) -> tuple[str, bool]:
    """Find all references to a symbol.

    Returns all locations where the symbol at the given position is used.
    """
    file_path = args.get("file_path")
    if not file_path:
        return "Error: file_path is required", True

    line = args.get("line")
    if line is None:
        return "Error: line is required (0-indexed)", True

    character = args.get("character", 0)
    include_declaration = args.get("include_declaration", True)

    file_path = _resolve_path(file_path, working_dir)
    client = get_lsp_client()

    result = await client.get_references(
        file_path, line, character, include_declaration
    )

    if not result:
        return "No references found at this position.", False

    # Format and group by file
    by_file: dict[str, list[str]] = {}
    for loc in result:
        uri = loc.get("uri", "")
        if uri.startswith("file://"):
            uri = uri[7:]

        range_info = loc.get("range", {})
        start = range_info.get("start", {})
        line_num = start.get("line", 0) + 1

        if uri not in by_file:
            by_file[uri] = []
        by_file[uri].append(f"line {line_num}")

    output = {
        "file": file_path,
        "position": {"line": line + 1, "character": character},
        "reference_count": len(result),
        "references_by_file": by_file,
    }

    return json.dumps(output, indent=2), False


async def _execute_symbols(
    args: dict[str, Any],
    working_dir: str,
) -> tuple[str, bool]:
    """Get all symbols in a document.

    Returns a hierarchical list of all symbols (functions, classes, variables, etc.)
    defined in the file.
    """
    file_path = args.get("file_path")
    if not file_path:
        return "Error: file_path is required", True

    file_path = _resolve_path(file_path, working_dir)
    client = get_lsp_client()

    result = await client.get_document_symbols(file_path)

    if not result:
        return "No symbols found in this file.", False

    # Format symbols
    lines = [f"Symbols in {Path(file_path).name}:", ""]
    for symbol in result:
        lines.append(_format_symbol(symbol))

    return "\n".join(lines), False


async def _execute_workspace_symbols(
    args: dict[str, Any],
    working_dir: str,
) -> tuple[str, bool]:
    """Search for symbols across the workspace.

    Searches all files in the workspace for symbols matching the query.
    """
    query = args.get("query")
    if not query:
        return "Error: query is required", True

    language = args.get("language", "python")
    workspace = args.get("workspace", working_dir)

    client = get_lsp_client()

    result = await client.get_workspace_symbols(workspace, query, language)

    if not result:
        return f"No symbols matching '{query}' found in workspace.", False

    # Format results
    lines = [f"Symbols matching '{query}':", ""]
    for symbol in result[:50]:  # Limit to 50 results
        lines.append(_format_symbol(symbol))

    if len(result) > 50:
        lines.append(f"\n... and {len(result) - 50} more results")

    return "\n".join(lines), False


async def _execute_status(
    args: dict[str, Any],
    working_dir: str,
) -> tuple[str, bool]:
    """Get detailed status of LSP servers."""
    from supervisor_config import get_supervisor_config
    from .supervisor_tools import get_supervisor
    import time

    config = get_supervisor_config()
    configured = config.list_lsp_servers()
    client = get_lsp_client()
    supervisor = get_supervisor()

    # Build detailed status
    result = {
        "configured_servers": [],
        "running_instances": [],
    }

    # Configured servers
    for server in configured:
        result["configured_servers"].append({
            "name": server.name,
            "command": server.command,
            "extensions": server.extensions,
            "languages": server.languages,
            "idle_timeout": server.idle_timeout_seconds,
        })

    # Running instances with details
    for key, instance in client._instances.items():
        uptime = int(time.time() - instance.last_activity)
        idle_for = int(time.time() - instance.last_activity)

        instance_info = {
            "key": key,
            "server": instance.server_name,
            "workspace": instance.workspace_root,
            "process_id": instance.process_id,
            "initialized": instance.initialized,
            "idle_seconds": idle_for,
            "pending_requests": len(instance.pending_requests),
        }

        # Get process status from supervisor
        if supervisor:
            try:
                process_json = await supervisor.get_process(instance.process_id)
                process = json.loads(process_json)
                status = process.get("status", {})
                instance_info["process_status"] = status.get("state", "unknown")
            except Exception:
                instance_info["process_status"] = "unknown"

        result["running_instances"].append(instance_info)

    return json.dumps(result, indent=2), False


async def _execute_start(
    args: dict[str, Any],
    working_dir: str,
) -> tuple[str, bool]:
    """Start an LSP server for a language/workspace."""
    language = args.get("language")
    if not language:
        return "Error: language is required (e.g., 'python', 'typescript', 'rust')", True

    workspace = args.get("workspace", working_dir)
    workspace = str(Path(workspace).resolve())

    client = get_lsp_client()

    # Check if already running
    key = client._instance_key(language, workspace)
    if key in client._instances:
        return json.dumps({
            "status": "already_running",
            "key": key,
            "message": f"LSP server '{language}' already running for {workspace}",
        }, indent=2), False

    # Start the server
    instance = await client.ensure_server(language, workspace)
    if not instance:
        return f"Error: Failed to start LSP server '{language}'", True

    return json.dumps({
        "status": "started",
        "key": key,
        "server": language,
        "workspace": workspace,
        "process_id": instance.process_id,
        "initialized": instance.initialized,
    }, indent=2), False


async def _execute_stop(
    args: dict[str, Any],
    working_dir: str,
) -> tuple[str, bool]:
    """Stop an LSP server."""
    language = args.get("language")
    workspace = args.get("workspace", working_dir)

    # Allow stopping by key directly
    key = args.get("key")
    if key:
        # Parse key to get language and workspace
        parts = key.split(":", 1)
        if len(parts) == 2:
            language, workspace = parts

    if not language:
        return "Error: language or key is required", True

    workspace = str(Path(workspace).resolve())

    client = get_lsp_client()
    key = client._instance_key(language, workspace)

    if key not in client._instances:
        return json.dumps({
            "status": "not_running",
            "key": key,
            "message": f"LSP server '{language}' not running for {workspace}",
        }, indent=2), False

    # Get process ID before stopping
    process_id = client._instances[key].process_id

    success = await client.stop_server(language, workspace)

    if success:
        return json.dumps({
            "status": "stopped",
            "key": key,
            "server": language,
            "workspace": workspace,
            "process_id": process_id,
        }, indent=2), False
    else:
        return f"Error: Failed to stop LSP server '{language}'", True


async def _execute_restart(
    args: dict[str, Any],
    working_dir: str,
) -> tuple[str, bool]:
    """Restart an LSP server."""
    language = args.get("language")
    workspace = args.get("workspace", working_dir)

    # Allow restarting by key directly
    key = args.get("key")
    if key:
        parts = key.split(":", 1)
        if len(parts) == 2:
            language, workspace = parts

    if not language:
        return "Error: language or key is required", True

    workspace = str(Path(workspace).resolve())

    client = get_lsp_client()
    key = client._instance_key(language, workspace)

    # Stop if running
    was_running = key in client._instances
    if was_running:
        await client.stop_server(language, workspace)

    # Start fresh
    instance = await client.ensure_server(language, workspace)
    if not instance:
        return f"Error: Failed to restart LSP server '{language}'", True

    return json.dumps({
        "status": "restarted" if was_running else "started",
        "key": key,
        "server": language,
        "workspace": workspace,
        "process_id": instance.process_id,
        "initialized": instance.initialized,
    }, indent=2), False


# Tool definitions in OpenAI format
LSP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lsp_hover",
            "description": """Get semantic information about a symbol at a position.

Returns type information, documentation, and function signatures - much more precise
than text search. Use this when you need to understand what a symbol is or does.

Example: Get type info for a variable
  lsp_hover(file_path="src/auth.py", line=42, character=10)
  → Returns: "authenticate(user: User, token: str) -> bool"

The line and character are 0-indexed (first line is 0, first char is 0).""",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file (absolute or relative to working directory)"
                    },
                    "line": {
                        "type": "integer",
                        "description": "0-indexed line number"
                    },
                    "character": {
                        "type": "integer",
                        "description": "0-indexed character position on the line (default: 0)"
                    }
                },
                "required": ["file_path", "line"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_definition",
            "description": """Find where a symbol is defined.

Jump to the definition of a function, class, variable, or type. Unlike text search,
this uses semantic analysis to find the actual definition, handling imports, inheritance,
and complex type relationships correctly.

Example: Find where a function is defined
  lsp_definition(file_path="src/main.py", line=10, character=5)
  → Returns: "/src/utils.py:42:0" (the function is defined in utils.py line 42)

Returns one or more locations (there may be multiple for overloaded functions).""",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file"
                    },
                    "line": {
                        "type": "integer",
                        "description": "0-indexed line number"
                    },
                    "character": {
                        "type": "integer",
                        "description": "0-indexed character position (default: 0)"
                    }
                },
                "required": ["file_path", "line"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_references",
            "description": """Find all references to a symbol.

Locates every place where a symbol is used across the codebase. This is semantic -
it finds actual usages, not just text matches. Useful for understanding impact of
changes and for refactoring.

Example: Find all places a function is called
  lsp_references(file_path="src/utils.py", line=42, character=4)
  → Returns all files and lines where this function is called

Results are grouped by file for easier reading.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file"
                    },
                    "line": {
                        "type": "integer",
                        "description": "0-indexed line number"
                    },
                    "character": {
                        "type": "integer",
                        "description": "0-indexed character position (default: 0)"
                    },
                    "include_declaration": {
                        "type": "boolean",
                        "description": "Include the symbol's declaration in results (default: true)"
                    }
                },
                "required": ["file_path", "line"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_symbols",
            "description": """Get all symbols defined in a file.

Returns a hierarchical list of all symbols (classes, functions, methods, variables)
in the file. Useful for understanding file structure and finding specific definitions.

Example: Get all symbols in a Python module
  lsp_symbols(file_path="src/models.py")
  → Returns:
    Class User (line 10)
      Method __init__ (line 12)
      Method authenticate (line 20)
    Class Session (line 45)
      ...""",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_workspace_symbols",
            "description": """Search for symbols across the entire workspace.

Searches all files in the project for symbols matching the query. Useful for finding
definitions when you don't know which file contains them.

Example: Find all classes with "Cache" in the name
  lsp_workspace_symbols(query="Cache")
  → Returns all classes, functions, etc. matching "Cache" across all files

Results are limited to 50 items.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Symbol name or pattern to search for"
                    },
                    "language": {
                        "type": "string",
                        "description": "Language server to use (default: 'python'). Options: python, typescript, rust, go"
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Workspace root directory (default: working directory)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_status",
            "description": """Get detailed status of all LSP servers.

Shows configured servers and running instances with details like:
- Which workspaces have active servers
- Process status and IDs
- Idle time (time since last request)
- Initialization state

Use this to understand what LSP servers are available and their current state.""",
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
            "name": "lsp_start",
            "description": """Start an LSP server for a language and workspace.

Manually start a language server. Useful for:
- Pre-warming a server before making queries
- Ensuring a server is running for a specific workspace
- Starting a server after it was stopped

The server will remain running until stopped or the app exits.

Example: Start Python LSP for current workspace
  lsp_start(language="python")

Example: Start for specific workspace
  lsp_start(language="rust", workspace="/path/to/project")""",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "Language server to start: 'python', 'typescript', 'rust', 'go'"
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Workspace root directory (default: working directory)"
                    }
                },
                "required": ["language"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_stop",
            "description": """Stop a running LSP server.

Stop a language server to free resources. The server can be restarted later.

You can stop by language+workspace or by the instance key from lsp_status.

Example: Stop Python LSP
  lsp_stop(language="python")

Example: Stop by key
  lsp_stop(key="python:/path/to/project")""",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "Language server to stop"
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Workspace root (default: working directory)"
                    },
                    "key": {
                        "type": "string",
                        "description": "Instance key from lsp_status (alternative to language+workspace)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_restart",
            "description": """Restart an LSP server.

Stop and restart a language server. Useful when:
- The server is misbehaving
- Configuration has changed
- You want to clear cached state

Example: Restart Python LSP
  lsp_restart(language="python")""",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "Language server to restart"
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Workspace root (default: working directory)"
                    },
                    "key": {
                        "type": "string",
                        "description": "Instance key from lsp_status (alternative to language+workspace)"
                    }
                },
                "required": []
            }
        }
    },
]
