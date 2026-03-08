"""Tool and Prompt Provider protocols.

These protocols define the interface for providing tools and prompts
to the main Balloons system. The DomainRegistry implements these
protocols, allowing domains to seamlessly integrate with the existing
tool/prompt infrastructure.
"""

from abc import ABC, abstractmethod
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from session import Session


class ToolProvider(Protocol):
    """Protocol for providing tools to the LLM.

    Any object implementing this protocol can contribute tools
    to the tool list sent to the LLM.
    """

    def get_tools(self) -> list[dict]:
        """Return tool definitions in OpenAI function calling format.

        Returns:
            List of tool definitions, each with:
                - type: "function"
                - function: {name, description, parameters}
        """
        ...

    def get_tool_names(self) -> set[str]:
        """Return the set of tool names this provider offers.

        Returns:
            Set of tool name strings
        """
        ...

    def handles_tool(self, tool_name: str) -> bool:
        """Check if this provider handles a given tool.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if this provider handles the tool
        """
        ...

    async def execute_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        session: "Session",
        working_dir: str,
    ) -> tuple[str, bool]:
        """Execute a tool and return the result.

        Args:
            tool_name: Name of the tool to execute
            params: Tool parameters from the LLM
            session: Current session context
            working_dir: Working directory for file operations

        Returns:
            Tuple of (result_string, is_error)
        """
        ...


class PromptProvider(Protocol):
    """Protocol for providing system prompt fragments.

    Any object implementing this protocol can contribute prompt
    text to the system prompt.
    """

    def get_prompt(self) -> str:
        """Return static system prompt fragment.

        Returns:
            Prompt text to inject into system prompt
        """
        ...


class ToolAndPromptProvider(ToolProvider, PromptProvider, Protocol):
    """Combined protocol for providers that offer both tools and prompts."""
    pass
