# Plan: Add OpenRouter and LlamaCpp Backends via Direct SDK

## Background

Balloons currently uses the `claude` CLI as its sole backend interface. While this works for Claude API (and LiteLLM proxy), we want to:
1. Remove the LiteLLM dependency entirely
2. Add direct OpenRouter support via Python SDK
3. Add direct llamacpp support via Python SDK
4. Keep Claude unchanged (still uses `claude` CLI)

## Architecture Overview

```
Balloons App
    |
    +--> Backend: "claude"
    |       └── ClaudeRunner (spawns `claude` CLI subprocess)
    |
    +--> Backend: "openrouter"
    |       └── OpenRouterRunner (direct API via openai SDK)
    |
    +--> Backend: "llamacpp"
            └── LlamaCppRunner (direct API via openai SDK)
```

**Key insight**: Both OpenRouter and llamacpp expose OpenAI-compatible APIs, so we can use the `openai` Python SDK for both. The `claude` backend continues using the CLI.

## New Architecture

### Runner Abstraction

Create a base runner interface that all backends implement:

```python
# core/base_runner.py
class BaseRunner(ABC):
    """Base class for all LLM runners."""

    @abstractmethod
    async def stream_response(
        self, messages: list[Message], prompt: str,
        allowed_tools: list[str] | None = None,
        working_dir: str | None = None,
        disable_tools: bool = False
    ) -> AsyncIterator[Union[TextDelta, ResultEvent, InitEvent, RawEvent, ...]]:
        """Stream a response from the LLM."""

    @abstractmethod
    def terminate(self):
        """Terminate any running request."""
```

### OpenAI-Compatible Runner

New runner for OpenRouter and llamacpp using the OpenAI SDK:

```python
# core/openai_runner.py
from openai import AsyncOpenAI

class OpenAICompatibleRunner(BaseRunner):
    """Runner for OpenAI-compatible APIs (OpenRouter, llamacpp, etc.)"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model
```

This runner will:
1. Convert our internal Message format to OpenAI chat format
2. Stream responses using the OpenAI SDK
3. Emit the same event types as ClaudeRunner (TextDelta, ResultEvent, etc.)
4. **NOT support tools** initially (just text responses) - tool support can be added later

### Config Changes

Update config to support new backend types:

```yaml
# config.yaml
backends:
  claude:
    # Uses claude CLI (default)
    type: claude  # optional, inferred from name

  openrouter:
    type: openai  # Uses OpenAI-compatible runner
    base_url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}  # or literal key
    model: anthropic/claude-sonnet-4

  llamacpp:
    type: openai
    base_url: http://localhost:8080/v1
    api_key: not-needed
    model: local-model
```

## Implementation Steps

### 1. Create base runner interface
**File: `core/base_runner.py`** (new)

Define abstract base class with the streaming interface that both ClaudeRunner and OpenAICompatibleRunner will implement.

### 2. Create OpenAI-compatible runner
**File: `core/openai_runner.py`** (new)

Implement runner using `openai` Python SDK:
- Constructor takes `base_url`, `api_key`, `model`
- `stream_response()` converts messages, calls API, yields events
- `terminate()` cancels the async request
- Yields same event types as ClaudeRunner

### 3. Update config schema
**File: `config.py`**

Add `type` field to BackendConfig:
```python
@dataclass
class BackendConfig:
    name: str
    type: str = "claude"  # "claude" or "openai"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
```

Add helper to resolve env vars in api_key (e.g., `${OPENROUTER_API_KEY}`).

### 4. Create runner factory
**File: `core/runner_factory.py`** (new)

Factory function to create the right runner based on backend config:
```python
def create_runner(backend: BackendConfig) -> BaseRunner:
    if backend.type == "openai":
        return OpenAICompatibleRunner(
            base_url=backend.base_url,
            api_key=backend.api_key,
            model=backend.model,
        )
    else:  # "claude" or default
        return ClaudeRunner(backend_env=get_env_for_backend(backend))
```

### 5. Update SessionRunner and HelperRunner
**File: `core/runner.py`**

Change to accept a BaseRunner instead of creating ClaudeRunner directly:
```python
class SessionRunner:
    def __init__(self, session: Session, runner: BaseRunner):
        self._runner = runner  # Was: self._claude_runner = ClaudeRunner(...)
```

### 6. Update app.py to use factory
**File: `app.py`**

When creating SessionRunner/HelperRunner, use the factory to get the appropriate runner based on current backend config.

### 7. Update config.sample.yaml
**File: `config/config.sample.yaml`**

Add documented examples for OpenRouter and llamacpp backends.

### 8. Add openai dependency
**File: `requirements.txt` or `pyproject.toml`**

Add `openai>=1.0.0` as a dependency.

## File Changes Summary

| File | Change |
|------|--------|
| `core/base_runner.py` | **NEW** - Abstract base class |
| `core/openai_runner.py` | **NEW** - OpenAI-compatible runner |
| `core/runner_factory.py` | **NEW** - Factory function |
| `config.py` | Add `type` field, env var resolution |
| `core/runner.py` | Accept BaseRunner, not create ClaudeRunner |
| `app.py` | Use factory to create runners |
| `config/config.sample.yaml` | Add OpenRouter/llamacpp examples |
| `requirements.txt` | Add `openai` |
| `claude_runner.py` | Make it extend BaseRunner |

## Event Mapping

The OpenAI-compatible runner will emit the same events as ClaudeRunner:

| OpenAI Event | Balloons Event |
|--------------|----------------|
| Stream start | `InitEvent(model=..., context_window=...)` |
| Delta chunk | `TextDelta(text=...)` |
| Stream end | `ResultEvent(input_tokens=..., output_tokens=..., total_cost=0)` |

Note: Cost tracking won't work for non-Claude backends (we don't know their pricing). We'll emit `total_cost=0` for these.

## Tool Support (Future)

Initially, OpenRouter/llamacpp backends will only support text responses (no tools). The `disable_tools=True` path already exists. For full tool support later:
1. Convert our tool definitions to OpenAI function format
2. Handle function_call responses
3. Map back to ToolUseEvent/ToolResultEvent

This is out of scope for the initial implementation.

## Testing

1. Test claude backend still works (regression)
2. Test OpenRouter backend with simple prompts
3. Test llamacpp backend with local server
4. Test switching backends at runtime
5. Test invalid backend configurations

## Dependencies

```
openai>=1.0.0
```

No other new dependencies needed.
