"""Tool execution result type.

Separated into its own module to avoid circular imports between
tool_executor.py and domain_tools.py.
"""

from dataclasses import dataclass


@dataclass
class ToolExecutionResult:
    """Result of executing a tool.

    Attributes:
        result: The result string to return to the LLM
        is_error: Whether the result is an error
        domains_changed: Whether domain tools were loaded/unloaded (requires tool refresh)
    """
    result: str
    is_error: bool
    domains_changed: bool = False
