"""Charts domain plugin for Balloons.

Provides persistent charting capabilities with:
- Multiple chart instances per session
- Time series data management (add/remove rows)
- Style configuration (colors, axis labels, etc.)
- CRUD operations via LLM tools
"""

# Lazy imports to avoid circular dependencies
# Use create_domain() as the entry point for the registry


def create_domain():
    """Factory function to create the charts domain."""
    from .domain import ChartsDomain
    return ChartsDomain()


def __getattr__(name):
    if name == "ChartsDomain":
        from .domain import ChartsDomain
        return ChartsDomain
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ChartsDomain", "create_domain"]
