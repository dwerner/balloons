"""Balloons Plugin System.

Domains are the fundamental abstraction for extending Balloons.
Each domain provides:
- Tools (LLM-callable functions)
- Prompts (system prompt fragments)
- Context (dynamic per-session state)
- Event handling (inter-domain communication)
- Optional UI components

Example usage:
    from plugins import DomainRegistry

    registry = DomainRegistry()
    registry.load_domain("chess")

    # Get tools for LLM
    tools = registry.get_all_tools()

    # Get prompt fragments
    prompts = registry.get_all_prompts()

The registry implements the ToolProvider and PromptProvider protocols,
allowing it to integrate with the main Balloons tool/prompt system.
"""

from .base import Domain, ToolDef, DomainEvent, ToolResult, StatefulDomain, DecoratedDomain, DecoratedStatefulDomain
from .registry import DomainRegistry, get_registry, set_registry
from .providers import ToolProvider, PromptProvider, ToolAndPromptProvider
from .storage import DomainStorage, JsonFileStorage, InMemoryStorage, CompositeStorage
from .decorators import llm_callable, Param, collect_llm_tools
from core.debug_log import PluginLogger

__all__ = [
    # Core types
    "Domain",
    "StatefulDomain",
    "DecoratedDomain",
    "DecoratedStatefulDomain",
    "ToolDef",
    "DomainEvent",
    "ToolResult",
    # Decorators
    "llm_callable",
    "Param",
    "collect_llm_tools",
    # Registry
    "DomainRegistry",
    "get_registry",
    "set_registry",
    # Provider protocols
    "ToolProvider",
    "PromptProvider",
    "ToolAndPromptProvider",
    # Storage
    "DomainStorage",
    "JsonFileStorage",
    "InMemoryStorage",
    "CompositeStorage",
    # Logging
    "PluginLogger",
]
