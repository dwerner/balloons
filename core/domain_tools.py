"""Domain management tools for loading/unloading plugins.

These tools allow the LLM to dynamically load domain plugins
when needed (e.g., load chess when user wants to play).
"""

from typing import Any, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from session import Session


# Domain management tools in OpenAI format
DOMAIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "load_domain",
            "description": """Load a domain plugin to gain new capabilities.

Use this when a user wants to use features provided by a domain plugin.
For example, load "chess" when the user wants to play chess.

Available domains:
- chess: Play chess with full rules validation

Once loaded, the domain's tools become available for use.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain_id": {
                        "type": "string",
                        "description": "ID of the domain to load (e.g., 'chess')",
                    },
                },
                "required": ["domain_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unload_domain",
            "description": "Unload a domain plugin to free resources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain_id": {
                        "type": "string",
                        "description": "ID of the domain to unload",
                    },
                },
                "required": ["domain_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_domains",
            "description": "List available and loaded domain plugins.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

DOMAIN_TOOL_NAMES = {"load_domain", "unload_domain", "list_domains"}


def _discover_available_domains() -> list[str]:
    """Discover available domain plugins in the plugins directory."""
    plugins_dir = Path(__file__).parent.parent / "plugins"
    if not plugins_dir.exists():
        return []

    domains = []
    for item in plugins_dir.iterdir():
        if item.is_dir() and (item / "domain.py").exists():
            domains.append(item.name)
        elif item.is_dir() and (item / "__init__.py").exists():
            # Check if __init__ defines create_domain
            init_file = item / "__init__.py"
            content = init_file.read_text()
            if "def create_domain" in content:
                domains.append(item.name)
    return sorted(domains)


async def execute_domain_management_tool(
    name: str,
    args: dict[str, Any],
    session: "Session",
) -> tuple[str, bool]:
    """Execute a domain management tool.

    Args:
        name: Tool name (load_domain, unload_domain, list_domains)
        args: Tool arguments
        session: Current session

    Returns:
        Tuple of (result_string, is_error)
    """
    try:
        from plugins.integration import load_domain, unload_domain, list_loaded_domains
    except ImportError:
        return "Plugin system not available", True

    if name == "load_domain":
        domain_id = args.get("domain_id", "").strip()
        if not domain_id:
            return "Error: domain_id is required", True

        # Check if available
        available = _discover_available_domains()
        if domain_id not in available:
            return f"Error: Domain '{domain_id}' not found. Available: {', '.join(available)}", True

        # Check if already loaded
        loaded = list_loaded_domains()
        if domain_id in loaded:
            return f"Domain '{domain_id}' is already loaded.", False

        try:
            load_domain(domain_id)
            return f"Loaded domain '{domain_id}'. Its tools are now available.", False
        except Exception as e:
            return f"Error loading domain: {e}", True

    elif name == "unload_domain":
        domain_id = args.get("domain_id", "").strip()
        if not domain_id:
            return "Error: domain_id is required", True

        loaded = list_loaded_domains()
        if domain_id not in loaded:
            return f"Domain '{domain_id}' is not loaded.", True

        try:
            unload_domain(domain_id)
            return f"Unloaded domain '{domain_id}'.", False
        except Exception as e:
            return f"Error unloading domain: {e}", True

    elif name == "list_domains":
        available = _discover_available_domains()
        loaded = list_loaded_domains()

        lines = ["Available domains:"]
        for d in available:
            status = " [loaded]" if d in loaded else ""
            lines.append(f"  - {d}{status}")

        if not available:
            lines.append("  (none)")

        return "\n".join(lines), False

    else:
        return f"Unknown domain tool: {name}", True
