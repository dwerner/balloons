# Creating Balloons Domain Plugins

This guide explains how to create domain plugins that extend Balloons with new capabilities.

## What is a Domain?

A **domain** is a coherent state space with its own:
- **Tools**: LLM-callable functions
- **Prompts**: System prompt fragments explaining the domain
- **Context**: Dynamic per-session state injected before each turn
- **Events**: Inter-domain communication
- **Storage**: Optional persistent state

Domains are the fundamental abstraction for extending Balloons. The LLM itself is a domain (the "agent domain"), and it composes with other domains (chess, filesystem, goals, etc.) via events.

## Quick Start

Create a new domain in `plugins/my_domain/`:

```
plugins/
└── my_domain/
    ├── __init__.py     # Entry point with create_domain()
    ├── domain.py       # Domain implementation
    ├── prompt.md       # LLM documentation
    └── README.md       # User documentation
```

### Minimal Domain

```python
# plugins/my_domain/domain.py
from plugins.base import Domain, ToolDef, ToolResult

class MyDomain(Domain):
    @property
    def id(self) -> str:
        return "my_domain"

    @property
    def name(self) -> str:
        return "My Domain"

    def get_tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="my_domain_hello",
                description="Say hello",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name to greet"}
                    },
                    "required": ["name"]
                },
            ),
        ]

    async def handle_tool(self, tool_name, params, session) -> ToolResult:
        if tool_name == "my_domain_hello":
            name = params.get("name", "World")
            return ToolResult(f"Hello, {name}!")
        return ToolResult(f"Unknown tool: {tool_name}", is_error=True)
```

```python
# plugins/my_domain/__init__.py
def create_domain():
    from .domain import MyDomain
    return MyDomain()
```

### Loading the Domain

```python
from plugins import DomainRegistry

registry = DomainRegistry()
registry.load_domain("my_domain")

# Get tools for LLM
tools = registry.get_all_tools()
```

## Domain Protocol

All domains must implement the `Domain` protocol:

```python
class Domain(ABC):
    # Identity
    @property
    def id(self) -> str: ...          # Unique ID (e.g., "chess")
    @property
    def name(self) -> str: ...        # Display name (e.g., "Chess")
    @property
    def version(self) -> str: ...     # Semantic version
    @property
    def dependencies(self) -> list[str]: ...  # Other domain IDs

    # Tools
    def get_tools(self) -> list[ToolDef]: ...
    async def handle_tool(self, tool_name, params, session) -> ToolResult: ...

    # Prompts
    def get_prompt(self) -> str: ...           # Static prompt fragment
    def get_context(self, session) -> str | None: ...  # Dynamic context

    # Events
    async def handle_event(self, event, session) -> list[DomainEvent]: ...

    # UI (optional)
    def get_ui_config(self) -> dict | None: ...

    # Lifecycle
    def on_load(self, runtime) -> None: ...
    def on_unload(self) -> None: ...
```

## Tool Definitions

Tools use OpenAI function calling format:

```python
ToolDef(
    name="chess_move",              # Prefix with domain ID!
    description="Make a chess move using UCI notation",
    parameters={
        "type": "object",
        "properties": {
            "move": {
                "type": "string",
                "description": "Move in UCI notation (e.g., 'e2e4')"
            }
        },
        "required": ["move"]
    }
)
```

**Important:** Prefix all tool names with your domain ID to avoid conflicts.

## Tool Results

Tool execution returns a `ToolResult`:

```python
from plugins.base import ToolResult, DomainEvent

async def handle_tool(self, tool_name, params, session) -> ToolResult:
    # Success
    return ToolResult("Operation completed successfully")

    # Error
    return ToolResult("Something went wrong", is_error=True)

    # With events
    return ToolResult(
        "Move made!",
        events=[
            DomainEvent(
                type="chess_move_made",
                source_domain=self.id,
                payload={"move": "e2e4"},
                target_session=session.id,
            )
        ]
    )
```

## Events

Events enable inter-domain communication:

```python
from plugins.base import DomainEvent

# Emit an event
event = DomainEvent(
    type="game_over",
    source_domain="chess",
    payload={"result": "1-0", "reason": "checkmate"},
    target_session=session.id,  # Optional: route to specific session
)

# Handle events from other domains
async def handle_event(self, event, session) -> list[DomainEvent]:
    if event.type == "user_connected":
        # React to another domain's event
        return [DomainEvent(
            type="welcome_sent",
            source_domain=self.id,
            payload={"message": "Welcome!"},
        )]
    return []
```

## Prompts and Context

### Static Prompt

The `get_prompt()` method returns documentation injected into the system prompt:

```python
def get_prompt(self) -> str:
    # Load from file
    import os
    prompt_path = os.path.join(os.path.dirname(__file__), "prompt.md")
    with open(prompt_path) as f:
        return f.read()
```

### Dynamic Context

The `get_context()` method returns session-specific state injected before each turn:

```python
def get_context(self, session) -> str | None:
    game = self._get_game(session.id)
    if game is None:
        return None
    return f"[Chess: {game.turn} to move, {len(game.moves)} moves played]"
```

## Stateful Domains

For domains that need persistent state, extend `StatefulDomain`:

```python
from plugins.base import StatefulDomain
from plugins.storage import JsonFileStorage

class MyStatefulDomain(StatefulDomain):
    def __init__(self):
        self.storage = JsonFileStorage("my_domain")
        self._cache = {}

    async def save_state(self, session) -> dict:
        """Called when session is saved."""
        state = self._cache.get(session.id, {})
        await self.storage.save(session.id, state)
        return state

    async def load_state(self, session, state) -> None:
        """Called when session is loaded."""
        if not state:
            state = await self.storage.load(session.id)
        if state:
            self._cache[session.id] = state

    async def clear_state(self, session) -> None:
        """Called when session is reset."""
        self._cache.pop(session.id, None)
        await self.storage.delete(session.id)
```

## Storage Backends

Several storage backends are available:

```python
from plugins.storage import (
    JsonFileStorage,      # JSON files in ~/.balloons/plugins/{domain}/
    InMemoryStorage,      # In-memory (testing, temporary data)
    CompositeStorage,     # Layered caching
)

# JSON file storage (default)
storage = JsonFileStorage("my_domain")
await storage.save("key", {"data": "value"})
data = await storage.load("key")

# In-memory with persistent backup
memory = InMemoryStorage()
files = JsonFileStorage("my_domain")
storage = CompositeStorage(memory, files)  # Memory first, files as backup
```

### Custom Storage

Implement the `DomainStorage` protocol:

```python
from plugins.storage import DomainStorage

class MyCustomStorage:
    async def save(self, key: str, data: dict) -> None: ...
    async def load(self, key: str) -> dict | None: ...
    async def delete(self, key: str) -> None: ...
    async def list_keys(self) -> list[str]: ...
    async def clear(self) -> None: ...
```

## UI Components

Domains can register React components:

```python
def get_ui_config(self) -> dict | None:
    return {
        "components": [
            {
                "name": "ChessBoard",
                "file": "plugins/chess/ui/ChessBoard.tsx",
                "props": {"size": 400},
            }
        ],
        "tabs": [
            {
                "id": "chess",
                "label": "Chess",
                "component": "ChessBoard",
            }
        ],
    }
```

## Testing

Create tests in your domain directory:

```python
# plugins/my_domain/test_domain.py
import pytest
from .domain import MyDomain

class MockSession:
    id = "test-session"

@pytest.mark.asyncio
async def test_hello_tool():
    domain = MyDomain()
    result = await domain.handle_tool(
        "my_domain_hello",
        {"name": "Alice"},
        MockSession()
    )
    assert not result.is_error
    assert "Hello, Alice" in result.result
```

Run tests:
```bash
python -m pytest plugins/my_domain/ -v
```

## Best Practices

1. **Prefix tool names** with your domain ID (`chess_move`, not `move`)
2. **Use descriptive errors** - the LLM needs to understand what went wrong
3. **Emit events** for significant state changes so other domains can react
4. **Load prompts from files** - easier to edit and version
5. **Persist state** - games/conversations should survive restarts
6. **Write tests** - at least for tool execution
7. **Document everything** - README.md for users, prompt.md for LLM

## Example Domains

- **`plugins/chess/`** - Full chess implementation with all features
- See the chess domain for examples of:
  - Tool definitions
  - Event emission
  - State persistence
  - Prompt loading
  - Board rendering

## Registry API

```python
from plugins import DomainRegistry, get_registry

# Global registry
registry = get_registry()

# Load/unload
registry.load_domain("chess")
registry.unload_domain("chess")
registry.reload_domain("chess")  # Hot reload

# Query tools
tools = registry.get_all_tools()           # OpenAI format
tool_names = registry.get_tool_names()     # Set of names
registry.handles_tool("chess_move")        # Check ownership

# Query prompts
prompt = registry.get_prompt()             # Combined prompts
context = registry.get_context(session)    # Combined context

# Execute
result = await registry.execute_tool("chess_move", {"move": "e4"}, session)

# Events
events = await registry.emit_event(event, session)
```
