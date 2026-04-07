"""Load OpenAI tool schemas from JSON files.

Tool schemas are stored in prompts/tools/openai/*.json and define the
function calling format sent to OpenAI-compatible APIs.

This replaces the hardcoded BALLOON_TOOLS in tools.py with file-based
schemas that can be:
1. Edited independently of code
2. Enabled/disabled via the UI
3. Previewed in the Context tab
"""

import json
from pathlib import Path
from typing import Optional

from .debug_log import debug_log, Category

# Schema directories
_SOURCE_SCHEMAS_DIR = Path(__file__).parent.parent / "prompts" / "tools" / "openai"
_USER_SCHEMAS_DIR = Path.home() / ".balloons" / "prompts" / "tools" / "openai"

# Cache for loaded schemas
_schema_cache: dict[str, dict] = {}


def _load_schema_file(tool_name: str) -> dict | None:
    """Load a tool schema from JSON file.

    Checks user directory first, then falls back to source directory.

    Args:
        tool_name: Name of the tool (e.g., 'propose_fork')

    Returns:
        Parsed JSON schema dict, or None if not found
    """
    filename = f"{tool_name}.json"

    # Check cache first
    if tool_name in _schema_cache:
        return _schema_cache[tool_name]

    # Check user directory first
    user_path = _USER_SCHEMAS_DIR / filename
    if user_path.exists():
        try:
            schema = json.loads(user_path.read_text())
            _schema_cache[tool_name] = schema
            return schema
        except Exception as e:
            debug_log.warning(
                f"Failed to load user tool schema: {tool_name}",
                category=Category.RUNNER,
                details={"error": str(e), "path": str(user_path)},
            )

    # Fall back to source directory
    source_path = _SOURCE_SCHEMAS_DIR / filename
    if source_path.exists():
        try:
            schema = json.loads(source_path.read_text())
            _schema_cache[tool_name] = schema
            return schema
        except Exception as e:
            debug_log.warning(
                f"Failed to load tool schema: {tool_name}",
                category=Category.RUNNER,
                details={"error": str(e), "path": str(source_path)},
            )

    return None


def get_balloon_tool_schema(tool_name: str) -> dict | None:
    """Get the OpenAI tool schema for a balloon tool.

    Args:
        tool_name: Name of the tool (e.g., 'propose_fork')

    Returns:
        OpenAI function calling schema dict, or None if not found
    """
    return _load_schema_file(tool_name)


def get_balloon_tool_schemas(tool_names: list[str] | None = None) -> list[dict]:
    """Get OpenAI tool schemas for multiple balloon tools.

    Args:
        tool_names: List of tool names, or None for all available

    Returns:
        List of OpenAI function calling schema dicts
    """
    if tool_names is None:
        tool_names = list_available_balloon_schemas()

    schemas = []
    for name in tool_names:
        schema = get_balloon_tool_schema(name)
        if schema:
            schemas.append(schema)
    return schemas


def list_available_balloon_schemas() -> list[str]:
    """List all available balloon tool schemas.

    Returns:
        List of tool names that have JSON schema files
    """
    tools = set()

    # Check source directory
    if _SOURCE_SCHEMAS_DIR.exists():
        for path in _SOURCE_SCHEMAS_DIR.glob("*.json"):
            tools.add(path.stem)

    # Check user directory (may override or add)
    if _USER_SCHEMAS_DIR.exists():
        for path in _USER_SCHEMAS_DIR.glob("*.json"):
            tools.add(path.stem)

    return sorted(tools)


def clear_schema_cache() -> None:
    """Clear the schema cache (useful after editing files)."""
    _schema_cache.clear()


def get_schemas_preview(tool_names: list[str] | None = None) -> str:
    """Get a formatted JSON preview of tool schemas.

    Useful for displaying in the Context tab.

    Args:
        tool_names: List of tool names, or None for all

    Returns:
        Pretty-printed JSON string of all schemas
    """
    schemas = get_balloon_tool_schemas(tool_names)
    return json.dumps(schemas, indent=2)
