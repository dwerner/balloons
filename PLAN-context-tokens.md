# Plan: Enhanced Context Token Display

## Status: Base feature implemented, now enhancing

## Current State (Implemented)

- Status bar shows: `[backend:model] 12,345 / 200,000 ctx (6.2%) | $0.0000`
- Single `context_tokens` value combining system + conversation + input
- Fixed 200,000 context window for all backends

---

## Phase 2: New Requirements

### 1. Simplified Token Display

Format: `session+(system) / budget (%)`

```
[openrouter:opus-4.5] 8.3k+(19.3k) / 200k (13.8%)
                       │      │       │      └── percentage used
                       │      │       └── context window (configurable)
                       │      └── system overhead (in parens, secondary)
                       └── session tokens (conversation + pending input)
```

- **session**: conversation context + pending input (combined, since input goes into session)
- **system**: system overhead (Claude's ~19.3k OR custom system_prompt)
- **budget**: context_window from backend config
- **%**: (session + system) / budget

For OpenAI with smaller system prompt:
```
8.1k+(2.1k) / 128k (8.0%)
```

### 2. Configurable Context Window per Backend

Add `context_window` to BackendConfig:

```yaml
backends:
  openrouter:
    type: openai
    model: anthropic/claude-sonnet-4
    context_window: 200000
    system_prompt: ~/.balloons/prompts/coding.md

  local-llama:
    type: openai
    base_url: http://localhost:8080/v1
    model: llama-3-8b
    context_window: 8192
```

Default values by type:
- Claude backend: 200,000 (Claude's standard)
- OpenAI backend: 128,000 (sensible default, user should override)

### 3. Color-Coded Values

Color the token values based on usage level:

| Metric | Color Logic |
|--------|-------------|
| Total % | Green (<50%), Yellow (50-80%), Red (>80%) |
| Individual components | Dim when 0, normal otherwise |

Example with colors:
```
[openrouter:opus-4.5] [dim]19.3k[/]+[green]8.2k[/]+[dim]0[/] / 200k [green](13.8%)[/]
```

---

## Files to Modify

### 1. `config.py` - Add context_window to BackendConfig

```python
@dataclass
class BackendConfig:
    name: str
    type: str = "claude"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    context_window: int = 0  # 0 means use default for type

    def get_context_window(self) -> int:
        """Get context window, using type-specific default if not set."""
        if self.context_window > 0:
            return self.context_window
        if self.type == "claude":
            return 200_000
        return 128_000  # Default for openai-compatible
```

Also update `_load_from_file()` to parse the new field.

### 2. `widgets/status_bar.py` - Simplified display with colors

Replace single `context_tokens` reactive with:
```python
session_tokens: reactive[int] = reactive(0)   # conversation + input combined
system_tokens: reactive[int] = reactive(0)    # system overhead
context_window: reactive[int] = reactive(200000)
```

Update `render()` to show `session+(system) / budget (%)`:
```python
def render(self) -> str:
    total = self.session_tokens + self.system_tokens
    percent = (total / self.context_window) * 100 if self.context_window > 0 else 0

    # Color based on percentage
    if percent > 80:
        pct_color = "red"
    elif percent > 50:
        pct_color = "yellow"
    else:
        pct_color = "green"

    # Format with k suffix
    def fmt(n: int) -> str:
        if n >= 1000:
            return f"{n/1000:.1f}k"
        return str(n)

    # Dim zero values
    session_display = f"[dim]0[/]" if self.session_tokens == 0 else fmt(self.session_tokens)
    system_display = f"[dim](0)[/]" if self.system_tokens == 0 else f"({fmt(self.system_tokens)})"

    return (
        f"[{backend_display}{model_display}] "
        f"{session_display}+{system_display} / {fmt(self.context_window)} "
        f"[{pct_color}]({percent:.1f}%)[/]"
        # ... rest of status bar
    )
```

Update `update_stats()` signature:
```python
def update_stats(
    self,
    model: str = None,
    backend: str = None,
    session_tokens: int = None,  # conversation + pending input
    system_tokens: int = None,   # system overhead
    context_window: int = None,
    cost: float = None,
):
```

### 3. `app.py` - Return breakdown from calculation

Change `_calculate_context_tokens` to return session and system separately:
```python
@dataclass
class ContextBreakdown:
    session: int   # conversation + pending input
    system: int    # system overhead

    @property
    def total(self) -> int:
        return self.session + self.system

def _calculate_context_tokens(self, pending_prompt: str = "") -> ContextBreakdown:
    # System overhead
    if backend.type == "claude":
        system_tokens = 19300
    else:
        system_tokens = 0
    system_tokens += backend._system_prompt_tokens

    # Session = conversation + pending input
    conversation_tokens = count_tokens(context) if context else 0
    input_tokens = count_tokens(pending_prompt) if pending_prompt else 0
    session_tokens = conversation_tokens + input_tokens

    return ContextBreakdown(session=session_tokens, system=system_tokens)

def _update_context_tokens(self, pending_prompt: str = "") -> None:
    breakdown = self._calculate_context_tokens(pending_prompt)
    status_bar.update_stats(
        session_tokens=breakdown.session,
        system_tokens=breakdown.system,
        context_window=backend.get_context_window(),
    )
```

### 4. `config/config.sample.yaml` - Document context_window

Add `context_window` examples to sample config.

---

## Verification

1. Start with Claude backend - shows `0+(19.3k) / 200k (9.7%)`
2. Type in input box - session value increases live
3. Load a session with messages - session value includes conversation
4. Toggle context modes - session value changes
5. Switch to OpenAI backend with custom prompt - system shows only custom prompt tokens
6. Configure different `context_window` per backend - budget updates
7. Fill context past 50% - percentage turns yellow
8. Fill context past 80% - percentage turns red
9. Zero session shows dimmed `0+(19.3k)`
