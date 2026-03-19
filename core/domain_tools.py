"""Domain management tools for loading/unloading plugins.

These tools allow the LLM to dynamically load domain plugins
when needed (e.g., load chess when user wants to play).
"""

from typing import Any, TYPE_CHECKING
from pathlib import Path

from .tool_result import ToolExecutionResult

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
) -> ToolExecutionResult:
    """Execute a domain management tool.

    Args:
        name: Tool name (load_domain, unload_domain, list_domains)
        args: Tool arguments
        session: Current session

    Returns:
        ToolExecutionResult with domains_changed=True for load/unload operations
    """
    try:
        from plugins.integration import load_domain, unload_domain, list_loaded_domains
    except ImportError:
        return ToolExecutionResult("Plugin system not available", is_error=True)

    if name == "load_domain":
        domain_id = args.get("domain_id", "").strip()
        if not domain_id:
            return ToolExecutionResult("Error: domain_id is required", is_error=True)

        # Check if available
        available = _discover_available_domains()
        if domain_id not in available:
            return ToolExecutionResult(
                f"Error: Domain '{domain_id}' not found. Available: {', '.join(available)}",
                is_error=True
            )

        # Check if already loaded
        loaded = list_loaded_domains()
        if domain_id in loaded:
            return ToolExecutionResult(f"Domain '{domain_id}' is already loaded.", is_error=False)

        try:
            load_domain(domain_id)

            # Get the domain's prompt so the LLM can use the tools immediately
            # (since the system prompt was built before this domain was loaded)
            try:
                from plugins.integration import get_domain_prompt
                from plugins.registry import get_registry
                registry = get_registry()
                domain = registry.get_domain(domain_id)
                domain_prompt = domain.get_prompt() if domain else ""
            except Exception:
                domain_prompt = ""

            result_msg = f"Loaded domain '{domain_id}'. Its tools are now available."
            if domain_prompt:
                result_msg += f"\n\n--- Domain Documentation ---\n{domain_prompt}"

            return ToolExecutionResult(
                result_msg,
                is_error=False,
                domains_changed=True,  # Signal that tools need refreshing
            )
        except Exception as e:
            return ToolExecutionResult(f"Error loading domain: {e}", is_error=True)

    elif name == "unload_domain":
        domain_id = args.get("domain_id", "").strip()
        if not domain_id:
            return ToolExecutionResult("Error: domain_id is required", is_error=True)

        loaded = list_loaded_domains()
        if domain_id not in loaded:
            return ToolExecutionResult(f"Domain '{domain_id}' is not loaded.", is_error=True)

        try:
            unload_domain(domain_id)
            return ToolExecutionResult(
                f"Unloaded domain '{domain_id}'.",
                is_error=False,
                domains_changed=True,  # Signal that tools need refreshing
            )
        except Exception as e:
            return ToolExecutionResult(f"Error unloading domain: {e}", is_error=True)

    elif name == "list_domains":
        available = _discover_available_domains()
        loaded = list_loaded_domains()

        lines = ["Available domains:"]
        for d in available:
            status = " [loaded]" if d in loaded else ""
            lines.append(f"  - {d}{status}")

        if not available:
            lines.append("  (none)")

        return ToolExecutionResult("\n".join(lines), is_error=False)

    else:
        return ToolExecutionResult(f"Unknown domain tool: {name}", is_error=True)
