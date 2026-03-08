"""Typed event system for domain plugins.

This module provides the infrastructure for strongly-typed domain events.
Each domain defines its own event payload dataclasses in its events.py file.

Example usage:

    from plugins.events import DomainEvent, EventPayload
    from plugins.chess.events import ChessMovePayload

    # Create a typed event
    event = DomainEvent(
        type="chess_move_made",
        source_domain="chess",
        payload=ChessMovePayload(
            move="e2e4",
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            legal_moves=["a7a6", "b7b6", ...],
        ),
    )

    # Serialize for WebSocket transmission
    data = event.to_dict()  # payload becomes a dict automatically
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventPayload(Protocol):
    """Protocol for typed event payloads.

    Domains define concrete dataclasses that match this protocol.
    The protocol just requires that the object can be converted to a dict.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Payloads must be dataclasses or have similar __init__."""
        ...


@dataclass
class RawPayload:
    """Fallback payload wrapper for untyped dict payloads.

    Used for backwards compatibility or when domain doesn't define
    typed payloads yet.
    """
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.data


def _snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase.

    Examples:
        legal_moves -> legalMoves
        game_over -> gameOver
        fen -> fen (no change)
    """
    components = name.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def _convert_keys_to_camel(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively convert dictionary keys from snake_case to camelCase."""
    result = {}
    for key, value in data.items():
        camel_key = _snake_to_camel(key)
        if isinstance(value, dict):
            result[camel_key] = _convert_keys_to_camel(value)
        elif isinstance(value, list):
            result[camel_key] = [
                _convert_keys_to_camel(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[camel_key] = value
    return result


def payload_to_dict(payload: Any, camel_case: bool = True) -> dict[str, Any]:
    """Convert an event payload to a dictionary.

    Handles:
    - Dataclasses (uses asdict, then converts to camelCase)
    - RawPayload (extracts data)
    - Dicts (passthrough, assumes already in correct format)
    - Objects with to_dict() method

    Args:
        payload: The event payload to convert
        camel_case: If True, convert snake_case keys to camelCase for JSON.
                   Default True for WebSocket transmission.

    Returns:
        Dictionary representation of the payload
    """
    if isinstance(payload, dict):
        # Dict payloads are assumed to already be in correct format
        return payload
    if isinstance(payload, RawPayload):
        return payload.data
    if hasattr(payload, "to_dict"):
        return payload.to_dict()
    try:
        d = asdict(payload)
        if camel_case:
            d = _convert_keys_to_camel(d)
        return d
    except TypeError:
        # Not a dataclass, try __dict__
        d = vars(payload) if hasattr(payload, "__dict__") else {"value": payload}
        if camel_case:
            d = _convert_keys_to_camel(d)
        return d


@dataclass
class DomainEvent:
    """Event emitted by or sent to a domain.

    Events are the primary mechanism for inter-domain communication
    and for broadcasting state changes to the UI.

    The payload can be either:
    - A typed dataclass (preferred, for type safety)
    - A RawPayload wrapper (for backwards compatibility)
    - A plain dict (deprecated but supported)

    Attributes:
        type: Event type identifier (e.g., "chess_move_made")
        source_domain: Domain ID that emitted this event
        payload: Typed event data
        target_session: Optional specific session to route to
    """

    type: str
    source_domain: str
    payload: Any = field(default_factory=dict)  # EventPayload or dict
    target_session: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event for WebSocket transmission."""
        return {
            "type": self.type,
            "sourceDomain": self.source_domain,
            "payload": payload_to_dict(self.payload),
            "targetSession": self.target_session,
        }

    def get_payload_dict(self) -> dict[str, Any]:
        """Get the payload as a dictionary."""
        return payload_to_dict(self.payload)


# Type alias for event handlers
EventHandler = Any  # Callable[[DomainEvent, Session], Awaitable[list[DomainEvent]]]
