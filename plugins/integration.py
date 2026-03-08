"""Integration between the plugin system and Balloons core.

This module provides functions to integrate domain plugins with:
- Tool lists (get_tools_for_request)
- System prompts (runner_factory)
- Tool execution (tool_executor)
- Dynamic context injection

Usage:
    from plugins.integration import get_domain_tools, get_domain_prompt, execute_domain_tool

    # In core/tools.py get_tools_for_request():
    domain_tools = get_domain_tools()
    all_tools = TOOLS + domain_tools

    # In runner_factory.py:
    domain_prompt = get_domain_prompt()
    system_prompt = user_prompt + domain_prompt

    # In tool_executor.py:
    if is_domain_tool(tool_name):
        return await execute_domain_tool(tool_name, params, session, working_dir)
"""

from typing import Any, TYPE_CHECKING

from .registry import get_registry

if TYPE_CHECKING:
    from session import Session


def get_domain_tools() -> list[dict]:
    """Get all tools from loaded domains in OpenAI format.

    Call this from get_tools_for_request() to include domain tools
    in the tool list sent to the LLM.

    Returns:
        List of tool definitions in OpenAI function calling format
    """
    registry = get_registry()
    return registry.get_all_tools()


def get_domain_tool_names() -> set[str]:
    """Get all tool names from loaded domains.

    Returns:
        Set of tool name strings
    """
    registry = get_registry()
    return registry.get_tool_names()


def is_domain_tool(tool_name: str) -> bool:
    """Check if a tool belongs to a loaded domain.

    Call this from tool_executor to route domain tools appropriately.

    Args:
        tool_name: Name of the tool

    Returns:
        True if tool belongs to a loaded domain
    """
    registry = get_registry()
    return registry.handles_tool(tool_name)


def get_domain_prompt() -> str:
    """Get combined prompt fragments from all loaded domains.

    Call this from runner_factory to include domain documentation
    in the system prompt.

    Returns:
        Combined prompt string, or empty string if no domains loaded
    """
    registry = get_registry()
    return registry.get_prompt()


def get_domain_context(session: "Session") -> str | None:
    """Get combined dynamic context from all loaded domains.

    Call this before each LLM turn to inject domain-specific state.

    Args:
        session: Current session

    Returns:
        Combined context string, or None if no context
    """
    registry = get_registry()
    return registry.get_context(session)


async def execute_domain_tool(
    tool_name: str,
    params: dict[str, Any],
    session: "Session",
    working_dir: str,
) -> tuple[str, bool]:
    """Execute a domain tool.

    Call this from tool_executor when is_domain_tool() returns True.

    Args:
        tool_name: Name of the tool to execute
        params: Tool parameters from the LLM
        session: Current session
        working_dir: Working directory (may be unused by domains)

    Returns:
        Tuple of (result_string, is_error)
    """
    registry = get_registry()
    return await registry.execute_tool_as_provider(tool_name, params, session, working_dir)


# Convenience function for loading domains
def load_domain(domain_id: str) -> None:
    """Load a domain into the global registry.

    Args:
        domain_id: ID of the domain to load (e.g., "chess")
    """
    registry = get_registry()
    registry.load_domain(domain_id)


def unload_domain(domain_id: str) -> None:
    """Unload a domain from the global registry.

    Args:
        domain_id: ID of the domain to unload
    """
    registry = get_registry()
    registry.unload_domain(domain_id)


def list_loaded_domains() -> list[str]:
    """List all currently loaded domains.

    Returns:
        List of domain IDs
    """
    registry = get_registry()
    return registry.loaded_domains
