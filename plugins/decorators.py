"""Domain method decorators for LLM tools and WebSocket RPC.

Provides decorators to expose domain methods as:
- LLM-callable tools (via @llm_callable)
- WebSocket RPC methods (via @ws_expose from codegen)

Usage:
    from plugins.decorators import llm_callable, Param
    from codegen.ws_expose import ws_expose

    class MyDomain(Domain):
        @llm_callable
        async def my_tool(self, param1: str, param2: int = 10) -> ToolResult:
            '''Tool description for the LLM.'''
            ...

        @llm_callable(
            params={
                "chart_type": Param(str, "Type of chart", enum=["line", "bar", "area"]),
                "title": Param(str, "Chart title", required=False),
            }
        )
        async def chart_create(self, name: str, chart_type: str = "line", ...) -> ToolResult:
            '''Create a new chart.'''
            ...

        @ws_expose
        @llm_callable
        async def delete_item(self, item_id: str) -> ToolResult:
            '''Delete an item. Callable by both LLM and UI.'''
            ...

The @llm_callable decorator:
- Extracts parameter info from function signature
- Uses docstring as tool description
- Generates ToolDef automatically
- Supports rich parameter schemas via Param() for enums, descriptions, nested objects
"""

import inspect
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, TypeVar, get_type_hints, get_origin, get_args, Union, TYPE_CHECKING, Literal

from .base import ToolDef, ToolResult

if TYPE_CHECKING:
    from session import Session


@dataclass
class Param:
    """Rich parameter specification for @llm_callable.

    Use this when simple type hints aren't enough:
    - Add descriptions per parameter
    - Specify enum values
    - Mark required/optional explicitly
    - Define nested object schemas

    Usage:
        @llm_callable(params={
            "chart_type": Param(str, "Type of chart to create", enum=["line", "bar"]),
            "config": Param(dict, "Configuration object", properties={
                "show_grid": Param(bool, "Show grid lines"),
                "colors": Param(list, "Color list", items=Param(str)),
            }),
        })
    """
    type: type | str  # Python type or "object", "array", etc.
    description: str = ""
    enum: list[str] | None = None
    required: bool | None = None  # None = infer from default value
    properties: dict[str, "Param"] | None = None  # For nested objects
    items: "Param | None" = None  # For arrays
    default: Any = None  # Default value

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema."""
        schema: dict[str, Any] = {}

        # Handle type
        if self.type == str or self.type == "string":
            schema["type"] = "string"
        elif self.type == int or self.type == "integer":
            schema["type"] = "integer"
        elif self.type == float or self.type == "number":
            schema["type"] = "number"
        elif self.type == bool or self.type == "boolean":
            schema["type"] = "boolean"
        elif self.type == list or self.type == "array":
            schema["type"] = "array"
            if self.items:
                schema["items"] = self.items.to_json_schema()
        elif self.type == dict or self.type == "object":
            schema["type"] = "object"
            if self.properties:
                schema["properties"] = {
                    k: v.to_json_schema() for k, v in self.properties.items()
                }
                # Collect required properties
                required = [k for k, v in self.properties.items() if v.required is True]
                if required:
                    schema["required"] = required

        # Add description
        if self.description:
            schema["description"] = self.description

        # Add enum
        if self.enum:
            schema["enum"] = self.enum

        return schema


@dataclass
class LLMCallableSpec:
    """Specification for an LLM-callable method."""

    name: str  # Tool name (e.g., "chart_delete")
    method_name: str  # Python method name
    description: str  # From docstring
    parameters: dict[str, Any]  # JSON Schema for parameters
    required: list[str]  # Required parameter names
    handler: Callable  # The decorated method


class LLMCallableRegistry:
    """Registry of LLM-callable methods per domain class."""

    # Maps domain class name -> list of LLMCallableSpec
    _registry: dict[str, list[LLMCallableSpec]] = {}

    @classmethod
    def register(cls, domain_class_name: str, spec: LLMCallableSpec) -> None:
        """Register an LLM-callable method for a domain."""
        if domain_class_name not in cls._registry:
            cls._registry[domain_class_name] = []
        cls._registry[domain_class_name].append(spec)

    @classmethod
    def get_specs(cls, domain_class_name: str) -> list[LLMCallableSpec]:
        """Get all registered specs for a domain class."""
        return cls._registry.get(domain_class_name, [])

    @classmethod
    def get_tool_defs(cls, domain_class_name: str) -> list[ToolDef]:
        """Get ToolDef list for a domain class."""
        specs = cls.get_specs(domain_class_name)
        return [
            ToolDef(
                name=spec.name,
                description=spec.description,
                parameters={
                    "type": "object",
                    "properties": spec.parameters,
                    "required": spec.required,
                },
            )
            for spec in specs
        ]

    @classmethod
    def get_handler(cls, domain_class_name: str, tool_name: str) -> Callable | None:
        """Get the handler for a specific tool."""
        specs = cls.get_specs(domain_class_name)
        for spec in specs:
            if spec.name == tool_name:
                return spec.handler
        return None

    @classmethod
    def clear(cls) -> None:
        """Clear the registry (for testing)."""
        cls._registry = {}


def _python_type_to_json_schema(py_type: Any) -> dict[str, Any]:
    """Convert Python type annotation to JSON Schema."""
    if py_type is None or py_type is type(None):
        return {"type": "null"}

    origin = get_origin(py_type)

    # Handle Optional[T] (Union[T, None])
    if origin is Union:
        args = get_args(py_type)
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1 and type(None) in args:
            # Optional[T] -> T with nullable
            inner = _python_type_to_json_schema(non_none_args[0])
            return inner  # JSON Schema doesn't have "nullable", optional is handled by required
        else:
            # General union - use anyOf
            return {"anyOf": [_python_type_to_json_schema(a) for a in args]}

    # Handle list[T]
    if origin is list:
        args = get_args(py_type)
        if args:
            return {"type": "array", "items": _python_type_to_json_schema(args[0])}
        return {"type": "array"}

    # Handle dict[K, V]
    if origin is dict:
        args = get_args(py_type)
        if len(args) == 2:
            return {
                "type": "object",
                "additionalProperties": _python_type_to_json_schema(args[1]),
            }
        return {"type": "object"}

    # Basic types
    if py_type is str:
        return {"type": "string"}
    if py_type is int:
        return {"type": "integer"}
    if py_type is float:
        return {"type": "number"}
    if py_type is bool:
        return {"type": "boolean"}

    # Enum
    if hasattr(py_type, "__members__"):
        return {"type": "string", "enum": list(py_type.__members__.keys())}

    # Fallback
    return {}


def llm_callable(
    method: Callable = None,
    *,
    name: str = None,
    description: str = None,
    params: dict[str, Param] | None = None,
):
    """Mark a method as LLM-callable.

    The method must:
    - Be an async method
    - Take 'self' and a 'session' parameter
    - Return ToolResult

    Parameters are extracted from the method signature. The docstring
    is used as the tool description unless overridden.

    Args:
        method: The method to decorate (when used without parentheses)
        name: Override the tool name (default: method name)
        description: Override the description (default: docstring)
        params: Dict of param_name -> Param for rich schemas (enums, descriptions)

    Usage:
        @llm_callable
        async def chart_delete(self, chart_id: str, session: "Session") -> ToolResult:
            '''Delete a chart by ID.'''
            ...

        @llm_callable(
            params={
                "chart_type": Param(str, "Type of chart", enum=["line", "bar"]),
            }
        )
        async def chart_create(self, name: str, chart_type: str = "line", session=None) -> ToolResult:
            '''Create a new chart.'''
            ...
    """

    def decorator(fn: Callable) -> Callable:
        # Extract type hints and signature
        # Use try/except because forward references (like "Session") may not resolve
        try:
            hints = get_type_hints(fn, include_extras=True)
        except NameError:
            # Forward references couldn't be resolved - use annotations directly
            hints = getattr(fn, "__annotations__", {})
        sig = inspect.signature(fn)

        # Build parameters dict and required list
        parameters: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            # Skip 'self' and 'session'
            if param_name in ("self", "session"):
                continue

            # Check if we have a rich Param specification
            if params and param_name in params:
                param_spec = params[param_name]
                schema = param_spec.to_json_schema()
                parameters[param_name] = schema

                # Determine required status
                if param_spec.required is True:
                    required.append(param_name)
                elif param_spec.required is None and param.default is inspect.Parameter.empty:
                    required.append(param_name)
            else:
                # Fall back to type hint inference
                type_hint = hints.get(param_name, Any)
                schema = _python_type_to_json_schema(type_hint)
                parameters[param_name] = schema

                # Check if required (no default value)
                if param.default is inspect.Parameter.empty:
                    required.append(param_name)

        # Get description from docstring or override
        tool_description = description or (fn.__doc__ or "").strip()

        # Determine tool name
        tool_name = name or fn.__name__

        # Create spec
        spec = LLMCallableSpec(
            name=tool_name,
            method_name=fn.__name__,
            description=tool_description,
            parameters=parameters,
            required=required,
            handler=fn,
        )

        # Store spec on function for later retrieval
        fn._llm_callable_spec = spec

        @wraps(fn)
        async def wrapper(self, *args, **kwargs):
            return await fn(self, *args, **kwargs)

        # Copy spec to wrapper
        wrapper._llm_callable_spec = spec

        return wrapper

    if method is not None:
        return decorator(method)
    return decorator


def collect_llm_tools(domain_class: type) -> list[ToolDef]:
    """Collect all @llm_callable tools from a domain class.

    Call this in get_tools() to automatically include decorated methods.

    Usage:
        def get_tools(self) -> list[ToolDef]:
            return collect_llm_tools(self.__class__)
    """
    tools = []

    for attr_name in dir(domain_class):
        if attr_name.startswith("_"):
            continue

        attr = getattr(domain_class, attr_name, None)
        if attr is None:
            continue

        if hasattr(attr, "_llm_callable_spec"):
            spec: LLMCallableSpec = attr._llm_callable_spec
            tools.append(ToolDef(
                name=spec.name,
                description=spec.description,
                parameters={
                    "type": "object",
                    "properties": spec.parameters,
                    "required": spec.required,
                },
            ))

    return tools


async def dispatch_llm_tool(
    domain: Any,
    tool_name: str,
    params: dict[str, Any],
    session: "Session",
) -> ToolResult | None:
    """Dispatch a tool call to the appropriate @llm_callable handler.

    NOTE: If you use DecoratedDomain or DecoratedStatefulDomain, dispatch
    is handled automatically. This function is only needed if you're
    extending plain Domain and want to mix decorated and manual tools.

    Returns None if no handler found (allows fallback to manual routing).

    Usage:
        async def handle_tool(self, tool_name, params, session) -> ToolResult:
            result = await dispatch_llm_tool(self, tool_name, params, session)
            if result is not None:
                return result
            # Fallback to manual handling...
    """
    domain_class = domain.__class__

    for attr_name in dir(domain_class):
        if attr_name.startswith("_"):
            continue

        attr = getattr(domain_class, attr_name, None)
        if attr is None:
            continue

        if hasattr(attr, "_llm_callable_spec"):
            spec: LLMCallableSpec = attr._llm_callable_spec
            if spec.name == tool_name:
                # Get the bound method
                method = getattr(domain, attr_name)
                # Call with params and session
                return await method(session=session, **params)

    return None
