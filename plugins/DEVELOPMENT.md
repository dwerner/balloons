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

### Minimal Domain (Decorator-Based)

The recommended approach uses `@llm_callable` decorators for automatic tool generation:

```python
# plugins/my_domain/domain.py
from plugins import DecoratedDomain, ToolResult, llm_callable, Param

class MyDomain(DecoratedDomain):
    @property
    def id(self) -> str:
        return "my_domain"

    @property
    def name(self) -> str:
        return "My Domain"

    @llm_callable
    async def my_domain_hello(self, name: str, session=None) -> ToolResult:
        """Say hello to someone."""
        return ToolResult(f"Hello, {name}!")

    @llm_callable(
        description="Create something with options",
        params={
            "type": Param(str, "Type to create", enum=["a", "b", "c"]),
            "count": Param(int, "How many to create", required=False),
        }
    )
    async def my_domain_create(self, type: str, count: int = 1, session=None) -> ToolResult:
        """Create items of a specific type."""
        return ToolResult(f"Created {count} items of type {type}")
```

The `@llm_callable` decorator:
- Extracts parameter types from the function signature
- Uses the docstring as the tool description
- Generates JSON Schema for the LLM automatically
- Handles dispatching in `handle_tool()` automatically

### Exposing Methods to the UI (WebSocket RPC)

To make a method callable from the UI as well as the LLM, add `@ws_expose`:

```python
from codegen.ws_expose import ws_expose

class MyDomain(DecoratedDomain):
    @ws_expose  # Makes method available as WebSocket RPC
    @llm_callable  # Makes method available to LLM
    async def my_domain_delete(self, item_id: str, session=None) -> ToolResult:
        """Delete an item. Callable by both LLM and UI."""
        # ... implementation
        return ToolResult(f"Deleted {item_id}")
```

The UI can then call this directly:
```typescript
// Generated client provides typed method
await client.domains.callDomainMethod({
  methodName: "myDomainDelete",  // camelCase wire name
  sessionId: "...",
  params: { itemId: "abc123" }
});
```

This is the recommended pattern for UI actions like delete buttons, configuration updates,
etc. - it avoids the overhead of going through the LLM.

For rich parameter schemas (enums, descriptions, nested objects), use `Param()`:

```python
@llm_callable(params={
    "choice": Param(str, "Pick one", enum=["a", "b", "c"]),
    "config": Param(dict, "Configuration", properties={
        "enabled": Param(bool, "Is enabled"),
        "count": Param(int, "Count", required=False),
    }),
})
async def my_tool(self, choice: str, config: dict, session=None) -> ToolResult:
    ...
```

### Minimal Domain (Manual)

For full control, you can manually define tools:

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

    async def get_state(self, session) -> dict | None:
        """Return current state (called by requestDomainState)."""
        # Auto-load from storage if not in memory
        if session.id not in self._cache:
            state = await self.storage.load(session.id)
            if state:
                self._cache[session.id] = state
        return self._cache.get(session.id)

    async def clear_state(self, session) -> None:
        """Called when session is reset."""
        self._cache.pop(session.id, None)
        await self.storage.delete(session.id)
```

### Auto-Save Pattern

For domains where state should persist immediately after each mutation (not just on session save),
add an auto-save helper:

```python
class MyStatefulDomain(StatefulDomain):
    async def _auto_save(self, session) -> None:
        """Auto-save state to persistent storage after mutations."""
        await self.save_state(session)

    async def handle_tool(self, tool_name, params, session) -> ToolResult:
        # Ensure state is loaded first
        await self._ensure_loaded(session)

        if tool_name == "my_domain_create":
            # Perform mutation
            self._cache[session.id]["items"].append(params["item"])

            # Auto-save after mutation
            await self._auto_save(session)

            return ToolResult("Item created")
        ...

    async def _ensure_loaded(self, session) -> None:
        """Ensure state is loaded from storage."""
        if session.id not in self._cache:
            state = await self.storage.load(session.id)
            self._cache[session.id] = state or {"items": []}
```

### Auto-Load Pattern

The `get_state()` method should auto-load from storage to support `requestDomainState`:

```python
async def get_state(self, session) -> dict | None:
    """Return current state, auto-loading from storage if needed."""
    if session.id not in self._cache:
        state = await self.storage.load(session.id)
        if state:
            self._cache[session.id] = state
    return self._cache.get(session.id)
```

This ensures:
1. State survives domain unload/reload cycles
2. State survives server restarts
3. UI can request current state on tab switch/page reload

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

Domains can register React components that appear in the Balloons sidebar.

### Directory Structure

```
plugins/
└── my_domain/
    ├── __init__.py
    ├── domain.py
    ├── prompt.md
    └── ui/
        ├── src/
        │   ├── index.tsx        # Entry point (required)
        │   ├── MyDomainTab.tsx  # Main component
        │   └── MyDomainTab.css  # Styles
        ├── package.json         # Dependencies
        └── node_modules -> ../../../web/ui/node_modules  # Symlink to shared deps
```

### Domain UI Config

Register your UI in the domain's `get_ui_config()`:

```python
def get_ui_config(self) -> dict | None:
    return {
        "components": [
            {
                "name": "MyDomainPanel",
                "path": "plugins/my_domain/ui/MyDomainPanel.tsx",
                "description": "Main domain panel",
            }
        ],
        "tabs": [
            {
                "id": "my_domain",
                "label": "My Domain",
                "icon": "🔧",
                "component": "MyDomainPanel",
            }
        ],
    }
```

### Entry Point (index.tsx)

Your `ui/src/index.tsx` must export a manifest and self-register:

```tsx
import React from 'react';
import { MyDomainTab, type PluginContext } from './MyDomainTab';

export const pluginId = 'my_domain';
export const pluginName = 'My Domain';
export const pluginVersion = '0.1.0';

export const manifest = {
  id: pluginId,
  name: pluginName,
  version: pluginVersion,
  tab: {
    id: 'my_domain',
    label: 'My Domain',
    icon: '🔧',
  },
  component: MyDomainTab,
};

// Self-register when loaded as a script
if (typeof window !== 'undefined') {
  const plugins = (window as any).__BALLOONS_PLUGINS__;
  if (plugins && typeof plugins.register === 'function') {
    plugins.register('my_domain', manifest);
  }
}
```

### Plugin Context

Your main component receives a `PluginContext` with these props:

```tsx
interface PluginContext {
  /** Send a message to the LLM */
  sendMessage?: (message: string) => void;
  /** Current session ID */
  sessionId?: string;
  /** Subscribe to domain events */
  subscribeToDomainEvents?: (
    domainId: string,
    callback: (event: DomainEventData) => void
  ) => () => void;
  /** Request current domain state (triggers state sync) */
  requestDomainState?: (domainId: string) => Promise<boolean>;
  /** Whether the LLM is currently streaming */
  isLLMResponding?: boolean;
}
```

### Building Plugin UI

Plugins are built with **Bun** into self-contained bundles:

```bash
# Build a specific plugin
cd plugins && bun run build-plugin-ui.ts my_domain

# Build all plugins
cd plugins && bun run build-plugin-ui.ts

# Watch mode for development
cd plugins && bun run build-plugin-ui.ts my_domain --watch
```

This produces:
```
plugins/dist/my_domain/
├── bundle.js       # Bundled React component
├── bundle.css      # Bundled styles
└── manifest.json   # Plugin metadata
```

### package.json

Minimal package.json for a plugin with dependencies:

```json
{
  "name": "@balloons-plugins/my-domain-ui",
  "version": "0.1.0",
  "private": true,
  "dependencies": {
    "some-library": "^1.0.0"
  }
}
```

**Note:** React is provided by the host app - don't include it as a dependency.

### Symlink node_modules

To share dependencies with the main UI and enable proper resolution:

```bash
cd plugins/my_domain/ui
ln -s ../../../web/ui/node_modules node_modules
```

### Domain Events

Subscribe to domain events in your component:

```tsx
useEffect(() => {
  if (!subscribeToDomainEvents || !sessionId) return;

  return subscribeToDomainEvents('my_domain', (event) => {
    if (event.sessionId !== sessionId) return;

    switch (event.eventType) {
      case 'my_domain_state_sync':
        // Handle full state sync
        setState(event.data);
        break;
      case 'my_domain_item_created':
        // Handle incremental update
        addItem(event.data.item);
        break;
    }
  });
}, [subscribeToDomainEvents, sessionId]);
```

### Requesting State on Mount

Request current state when the tab is opened:

```tsx
useEffect(() => {
  if (!requestDomainState || !sessionId) return;

  // This triggers a state sync event from the backend
  requestDomainState('my_domain').catch(console.error);
}, [requestDomainState, sessionId]);
```

**Important:** Your domain's `get_state()` method should return data, and you should handle
the `{domain_id}_state_sync` event (e.g., `my_domain_state_sync`) in your component.

### Event Type Naming

Domain events use two naming conventions:

1. **Domain-emitted events**: `{action}` (e.g., `chart_created`, `game_over`)
2. **State sync from requestDomainState**: `{domain_id}_state_sync` (e.g., `charts_state_sync`)

Handle both in your component if needed:

```tsx
case 'my_domain_state_sync':  // From requestDomainState
case 'state_sync':            // From domain tool calls
  handleStateSync(event.data);
  break;
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

## Logging

Plugins have access to a dedicated logging system with their own category buffer.

### PluginLogger

Use `PluginLogger` for structured, filterable logs:

```python
from plugins import PluginLogger

class MyDomain(DecoratedDomain):
    def __init__(self):
        self.log = PluginLogger("my_domain")

    @llm_callable
    async def my_domain_create(self, name: str, session=None) -> ToolResult:
        self.log.info("Creating item", session_id=session.id, details={"name": name})
        try:
            # ... implementation
            self.log.debug("Item created successfully", details={"item_id": item.id})
            return ToolResult(f"Created: {item.id}")
        except Exception as e:
            self.log.error("Failed to create item", details={"error": str(e)})
            return ToolResult(f"Error: {e}", is_error=True)
```

### Log Levels

- `log.error(...)` - Errors that need attention
- `log.warning(...)` - Warning conditions
- `log.info(...)` - General informational messages
- `log.debug(...)` - Debug details (hidden by default)
- `log.trace(...)` - Very verbose (scroll events, etc.)
- `log.perf(...)` - Performance timing markers

### Plugin Category

Logs are automatically prefixed with `plugin:` so they appear as `plugin:my_domain` in the
debug UI and log files. This makes them easy to filter:

```bash
# Tail plugin logs
tail -f ~/.balloons/logs/plugin:my_domain.log

# Enable file logging for your plugin
debug_log.enable_category("plugin:my_domain")
```

### Querying Plugin Logs

```python
# Get recent entries for this plugin
entries = self.log.query(limit=50, level=LogLevel.ERROR)
```

### Direct debug_log Access

For advanced use cases, access the underlying debug_log singleton:

```python
from core.debug_log import debug_log, Category

# Use core categories (API, RUNNER, etc.)
debug_log.info("Message", category=Category.API)

# Register a custom category (automatically done by PluginLogger)
debug_log.register_category("plugin:my_domain")
```

## Best Practices

1. **Prefix tool names** with your domain ID (`chess_move`, not `move`)
2. **Use descriptive errors** - the LLM needs to understand what went wrong
3. **Emit events** for significant state changes so other domains can react
4. **Load prompts from files** - easier to edit and version
5. **Persist state** - games/conversations should survive restarts
6. **Write tests** - at least for tool execution
7. **Document everything** - README.md for users, prompt.md for LLM
8. **Use PluginLogger** - structured logs with automatic category filtering
9. **Automation First** - see below for the pattern

## Automation First Pattern

While plugins provide `@llm_callable` tools for exploratory and conversational use, the goal
is **scripted automation**. When the LLM discovers how to accomplish a task (e.g., searching
a grocery site), encode that knowledge into reproducible UI-triggered operations. Users should
be able to click a button and get consistent results without LLM involvement.

### Development Workflow

1. **Explore with LLM tools**: Use `@llm_callable` tools to figure out how something works
   (e.g., finding the right selectors, understanding API responses)

2. **Script the solution**: Once you know the steps, create a dedicated method that performs
   them reliably

3. **Expose to UI**: Add `@ws_expose` to make it callable from the plugin's React component

4. **Keep LLM fallback**: Keep `@llm_callable` for conversational flexibility, but the UI
   should call `@ws_expose` methods directly

### Example: Browser Automation

```python
# Both decorators - LLM can use it conversationally, UI can call it directly
@ws_expose
@llm_callable(description="Search for products on the grocery site")
async def grocery_browser_search(self, query: str, session=None) -> ToolResult:
    # Scripted browser automation - no LLM reasoning needed
    await self._browser.fill_search_box(query)
    await self._browser.submit_search()
    await self._browser.wait_for_results()
    return ToolResult("Search complete")
```

```tsx
// UI calls the method directly - no LLM round-trip
const handleSearch = async () => {
  const result = await callDomainMethod('groceryBrowserSearch', { query });
  // Handle result...
};
```

### Why This Matters

- **Reliability**: Scripted actions are deterministic; LLM responses vary
- **Speed**: Direct method calls are instant; LLM calls take seconds
- **Cost**: No token usage for routine operations
- **Offline**: Works without API access once scripted

### Lifecycle Cleanup

When a plugin manages external resources (browsers, connections, processes), implement
`on_unload()` to clean them up:

```python
def on_unload(self) -> None:
    """Clean up resources when domain is unloaded."""
    for session_id, state in list(_session_states.items()):
        if state._browser is not None:
            try:
                asyncio.run(state._browser.disconnect())
            except Exception:
                pass
            state._browser = None
```

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

## Future Work

### Plugin Scaffolding Generator

A CLI tool to generate new plugin scaffolds:

```bash
# Proposed command
balloons create-plugin my_domain --with-ui
```

Would generate:

```
plugins/my_domain/
├── __init__.py         # Entry point with create_domain()
├── domain.py           # Domain class skeleton
├── models.py           # Data classes for state
├── events.py           # Event payload definitions
├── prompt.md           # LLM documentation template
├── test_domain.py      # Test skeleton
├── README.md           # User documentation template
├── .gitignore          # Build artifacts, node_modules, etc.
└── ui/                 # (if --with-ui)
    ├── package.json    # Dependencies (react, recharts, etc.)
    ├── tsconfig.json   # TypeScript config
    ├── src/
    │   ├── index.tsx   # Plugin entry point
    │   └── MyDomainTab.tsx  # Main component
    └── .gitignore
```

Features to include:
- Interactive prompts for plugin name, description, tools
- Template for StatefulDomain with storage integration
- Template for event emission patterns
- Build script integration (`bun run build`)
- Test fixtures and mocks
- Example tool implementations
