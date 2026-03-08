"""Chess domain plugin for Balloons.

Provides a complete chess playing experience with:
- Full chess rules validation
- Position tracking per session
- Move history
- Game state (check, checkmate, stalemate)
- ASCII board rendering
"""

# Lazy imports to avoid circular dependencies
# Use create_domain() as the entry point for the registry

def create_domain():
    """Factory function to create the chess domain."""
    from .domain import ChessDomain
    return ChessDomain()


def __getattr__(name):
    if name == "ChessDomain":
        from .domain import ChessDomain
        return ChessDomain
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ChessDomain", "create_domain"]
