"""Kanban board domain plugin.

Provides persistent kanban board functionality with session-scoped boards.

Note: Import create_domain and KanbanDomain from .domain directly to avoid
circular imports when loading the domain via the registry.
"""

# Imports are done lazily to avoid circular import issues
# Use: from plugins.kanban.domain import create_domain
