"""Allow running the kanban plugin as a module.

Usage:
    python -m plugins.kanban [command] [options]
    python -m plugins.kanban interactive
"""

from .cli import run

if __name__ == "__main__":
    run()
