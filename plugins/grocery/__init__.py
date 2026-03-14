"""PC Express Grocery domain plugin.

Provides grocery shopping capabilities for Canadian Loblaw stores
(Real Canadian Superstore, No Frills, Loblaws, etc.) and SaveOn Foods.
"""

# Lazy imports to avoid circular dependencies
# Use create_domain() as the entry point for the registry


def create_domain():
    """Factory function to create the grocery domain."""
    from .domain import GroceryDomain
    return GroceryDomain()


def __getattr__(name):
    if name == "GroceryDomain":
        from .domain import GroceryDomain
        return GroceryDomain
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["GroceryDomain", "create_domain"]
