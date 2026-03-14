"""WebSocket exposure decorators and registry.

The @ws_expose decorator marks methods for WebSocket RPC exposure.
The @ws_event decorator marks methods that emit events.
The @ws_type decorator marks types for TypeScript/Rust generation.

These decorators build a registry that code generators use to produce:
- TypeScript interfaces and client code
- Rust trait definitions and client code
- JSON schemas for validation

Usage:
    from codegen.ws_expose import ws_expose, ws_event, ws_type

    @ws_type
    @dataclass
    class SessionData:
        id: str
        title: str

    class SessionDataService:
        @ws_expose
        async def get_session(self, session_id: str) -> SessionData | None:
            ...

        @ws_event
        async def on_session_updated(self) -> SessionData:
            ...
"""

import inspect
import re
from dataclasses import dataclass, field, is_dataclass, fields
from typing import Callable, TypeVar, get_type_hints, get_origin, get_args, Union, Any
from functools import wraps

from codegen.rust_schema import rust_schema, RustSchemaRegistry


def to_camel_case(snake_str: str) -> str:
    """Convert snake_case to camelCase."""
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def to_snake_case(camel_str: str) -> str:
    """Convert camelCase to snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", camel_str).lower()


@dataclass
class ParamSpec:
    """Specification for a method parameter."""

    name: str  # Python param name (snake_case)
    wire_name: str  # Wire name (camelCase)
    type_hint: Any  # Python type annotation
    default: Any = None  # Default value (None means no default)
    required: bool = True  # Whether parameter is required


@dataclass
class MethodSpec:
    """Specification for an exposed method."""

    name: str  # Python method name
    wire_name: str  # Wire name (camelCase)
    service_name: str  # Service class name
    params: list[ParamSpec]  # Parameter specifications
    return_type: Any  # Return type annotation
    docstring: str  # Method docstring
    is_async: bool = True  # Whether method is async


@dataclass
class EventSpec:
    """Specification for an exposed event."""

    name: str  # Python event name
    wire_name: str  # Wire name (camelCase)
    service_name: str  # Service class name
    payload_type: Any  # Event payload type
    pattern: str | None = None  # Optional wildcard pattern (e.g., "tree.*")
    docstring: str = ""


@dataclass
class ServiceSpec:
    """Specification for an exposed service class."""

    name: str  # Python class name
    wire_name: str  # Wire name (camelCase)
    methods: list[MethodSpec] = field(default_factory=list)
    events: list[EventSpec] = field(default_factory=list)
    docstring: str = ""


class WsExposeRegistry:
    """Registry of WebSocket-exposed services, methods, events, and types."""

    _services: dict[str, ServiceSpec] = {}
    _types: list[type] = []

    @classmethod
    def register_service(cls, service_cls: type, spec: ServiceSpec) -> None:
        """Register a service class."""
        cls._services[spec.name] = spec

    @classmethod
    def register_method(cls, service_name: str, spec: MethodSpec) -> None:
        """Register a method under a service."""
        if service_name not in cls._services:
            # Create placeholder service that will be filled in later
            cls._services[service_name] = ServiceSpec(
                name=service_name,
                wire_name=to_camel_case(service_name),
            )
        cls._services[service_name].methods.append(spec)

    @classmethod
    def register_event(cls, service_name: str, spec: EventSpec) -> None:
        """Register an event under a service."""
        if service_name not in cls._services:
            cls._services[service_name] = ServiceSpec(
                name=service_name,
                wire_name=to_camel_case(service_name),
            )
        cls._services[service_name].events.append(spec)

    @classmethod
    def register_type(cls, type_cls: type) -> None:
        """Register a type for codegen."""
        if type_cls not in cls._types:
            cls._types.append(type_cls)

    @classmethod
    def get_services(cls) -> dict[str, ServiceSpec]:
        """Get all registered services."""
        return cls._services.copy()

    @classmethod
    def get_types(cls) -> list[type]:
        """Get all registered types."""
        return cls._types.copy()

    @classmethod
    def clear(cls) -> None:
        """Clear the registry (mainly for testing)."""
        cls._services = {}
        cls._types = []


def _extract_params(fn: Callable) -> list[ParamSpec]:
    """Extract parameter specifications from a function."""
    import inspect

    # Use try/except because forward references may not resolve
    try:
        hints = get_type_hints(fn)
    except NameError:
        hints = getattr(fn, "__annotations__", {})

    sig = inspect.signature(fn)
    params = []

    for param_name, param in sig.parameters.items():
        # Skip 'self' and 'session' parameters
        if param_name in ("self", "session"):
            continue

        type_hint = hints.get(param_name, Any)
        has_default = param.default is not inspect.Parameter.empty
        default_value = param.default if has_default else None

        params.append(
            ParamSpec(
                name=param_name,
                wire_name=to_camel_case(param_name),
                type_hint=type_hint,
                default=default_value,
                required=not has_default,
            )
        )

    return params


def ws_expose(method: Callable = None, *, name: str = None):
    """Mark a method as WebSocket-exposed for RPC.

    Can be used as:
        @ws_expose
        async def get_session(self, session_id: str) -> SessionData: ...

        @ws_expose(name="fetchSession")
        async def get_session(self, session_id: str) -> SessionData: ...

    Args:
        method: The method to expose (when used without parentheses)
        name: Override the wire name (defaults to camelCase of method name)
    """

    def decorator(fn: Callable) -> Callable:
        # Use try/except because forward references (like "Session") may not resolve
        try:
            hints = get_type_hints(fn)
        except NameError:
            # Forward references couldn't be resolved - use annotations directly
            hints = getattr(fn, "__annotations__", {})
        params = _extract_params(fn)

        spec = MethodSpec(
            name=fn.__name__,
            wire_name=name or to_camel_case(fn.__name__),
            service_name="",  # Will be set when class is registered
            params=params,
            return_type=hints.get("return"),
            docstring=fn.__doc__ or "",
            is_async=inspect.iscoroutinefunction(fn),
        )

        # Store spec on function for later retrieval during class registration
        fn._ws_method_spec = spec
        return fn

    if method is not None:
        return decorator(method)
    return decorator


def ws_event(pattern_or_fn=None, *, name: str = None):
    """Mark a method as emitting WebSocket events.

    Can be used as:
        @ws_event
        async def on_session_updated(self) -> SessionData: ...

        @ws_event("tree.*")
        async def on_tree_event(self) -> TreeEvent: ...

        @ws_event(name="sessionChanged")
        async def on_session_updated(self) -> SessionData: ...

    Args:
        pattern_or_fn: Either the method (when used without args) or a pattern string
        name: Override the wire name (defaults to camelCase of method name)
    """

    def decorator(fn: Callable, pattern: str = None) -> Callable:
        hints = get_type_hints(fn)

        spec = EventSpec(
            name=fn.__name__,
            wire_name=name or to_camel_case(fn.__name__),
            service_name="",  # Will be set when class is registered
            payload_type=hints.get("return"),
            pattern=pattern,
            docstring=fn.__doc__ or "",
        )

        fn._ws_event_spec = spec
        return fn

    if callable(pattern_or_fn):
        # Used as @ws_event without parentheses
        return decorator(pattern_or_fn)
    elif isinstance(pattern_or_fn, str):
        # Used as @ws_event("pattern")
        return lambda fn: decorator(fn, pattern_or_fn)
    else:
        # Used as @ws_event() or @ws_event(name="...")
        return lambda fn: decorator(fn, None)


def ws_service(cls: type = None, *, name: str = None):
    """Mark a class as a WebSocket service.

    This decorator:
    1. Collects all @ws_expose methods on the class
    2. Collects all @ws_event methods on the class
    3. Registers the service in WsExposeRegistry

    Can be used as:
        @ws_service
        class SessionDataService:
            @ws_expose
            async def get_session(self, session_id: str) -> SessionData: ...

        @ws_service(name="Sessions")
        class SessionDataService: ...
    """

    def decorator(service_cls: type) -> type:
        wire_name = name or to_camel_case(service_cls.__name__)

        # Create service spec
        spec = ServiceSpec(
            name=service_cls.__name__,
            wire_name=wire_name,
            methods=[],
            events=[],
            docstring=service_cls.__doc__ or "",
        )

        # Collect methods and events from class
        for attr_name in dir(service_cls):
            if attr_name.startswith("_"):
                continue

            attr = getattr(service_cls, attr_name, None)
            if attr is None:
                continue

            # Check for @ws_expose methods
            if hasattr(attr, "_ws_method_spec"):
                method_spec: MethodSpec = attr._ws_method_spec
                method_spec.service_name = service_cls.__name__
                spec.methods.append(method_spec)

            # Check for @ws_event methods
            if hasattr(attr, "_ws_event_spec"):
                event_spec: EventSpec = attr._ws_event_spec
                event_spec.service_name = service_cls.__name__
                spec.events.append(event_spec)

        # Register service
        WsExposeRegistry.register_service(service_cls, spec)

        # Store spec on class for runtime introspection
        service_cls._ws_service_spec = spec
        return service_cls

    if cls is not None:
        return decorator(cls)
    return decorator


def ws_type(cls: type) -> type:
    """Mark a type for WebSocket API exposure.

    This extends @rust_schema to also generate TypeScript types.
    The type must be a dataclass.

    Usage:
        @ws_type
        @dataclass
        class SessionData:
            id: str
            title: str
            turn_count: int
    """
    if not is_dataclass(cls):
        raise TypeError(f"@ws_type can only be applied to dataclasses, got {cls}")

    # Register for Rust codegen via existing mechanism
    cls = rust_schema(cls)

    # Also register for TypeScript codegen
    WsExposeRegistry.register_type(cls)

    return cls


# --- Type Conversion Utilities ---


def python_to_ts_type(py_type: Any) -> str:
    """Convert Python type annotation to TypeScript type string."""
    if py_type is None or py_type is type(None):
        return "null"

    origin = get_origin(py_type)

    # Handle Optional[T] (which is Union[T, None])
    if origin is Union:
        args = get_args(py_type)
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1 and type(None) in args:
            inner_type = python_to_ts_type(non_none_args[0])
            return f"{inner_type} | null"
        else:
            # General union
            types = [python_to_ts_type(a) for a in args]
            return " | ".join(types)

    # Handle list[T]
    if origin is list:
        args = get_args(py_type)
        if args:
            inner_type = python_to_ts_type(args[0])
            return f"{inner_type}[]"
        return "unknown[]"

    # Handle dict[K, V]
    if origin is dict:
        args = get_args(py_type)
        if len(args) == 2:
            key_type = python_to_ts_type(args[0])
            val_type = python_to_ts_type(args[1])
            # TypeScript Record type
            return f"Record<{key_type}, {val_type}>"
        return "Record<string, unknown>"

    # Handle tuple
    if origin is tuple:
        args = get_args(py_type)
        if args:
            types = [python_to_ts_type(a) for a in args]
            return f"[{', '.join(types)}]"
        return "unknown[]"

    # Handle basic types
    if py_type is str:
        return "string"
    if py_type is int or py_type is float:
        return "number"
    if py_type is bool:
        return "boolean"
    if py_type is Any:
        return "unknown"

    # Handle dataclass references
    if is_dataclass(py_type):
        return py_type.__name__

    # Handle other classes by name - special cases for unparameterized containers
    if hasattr(py_type, "__name__"):
        name = py_type.__name__
        if name == "dict":
            return "Record<string, unknown>"
        if name == "list":
            return "unknown[]"
        return name

    return "unknown"


def generate_ts_interface(cls: type) -> str:
    """Generate TypeScript interface from a Python dataclass."""
    from dataclasses import MISSING

    if not is_dataclass(cls):
        raise TypeError(f"Expected dataclass, got {cls}")

    hints = get_type_hints(cls)
    lines = [f"export interface {cls.__name__} {{"]

    for f in fields(cls):
        ts_type = python_to_ts_type(hints.get(f.name, Any))
        # Field is optional if it has a default value (not MISSING)
        has_default = f.default is not MISSING or f.default_factory is not MISSING
        optional = "?" if has_default else ""
        lines.append(f"  {to_camel_case(f.name)}{optional}: {ts_type};")

    lines.append("}")
    return "\n".join(lines)
