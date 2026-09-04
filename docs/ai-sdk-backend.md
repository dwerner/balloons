# AI SDK Backend (Rust)

**Status: experimental.** `type: openai` is the primary OpenAI-compatible backend; `ai_sdk` is kept as an active experiment to see how far the Rust path goes.

The AI SDK backend uses the Rust implementation of the OpenAI-compatible protocol via the `ai-sdk-openai-compatible` crate, with Python bindings.

## Current State

- Tool calling and image support are implemented (commit `c4aacbf`)
- **Streaming is buffered**: `_stream_one_response` awaits a `(result, events)` tuple and replays events after the HTTP response completes, so deltas arrive in one burst (`core/ai_sdk_runner.py:218`). The openai runner had the identical flaw and was fixed by converting it to an async generator with a caller-owned outcome object — the same transformation applies here and is the main thing standing between this runner and parity.
- Several tests are xfail-marked as **stale** (they mock out `_stream_one_response` and then assert on events it emits) — they need rewriting against the async-generator form, not bug-hunting.

## Comparison with OpenAI Runner

| Feature | OpenAI Runner | AI SDK Runner |
|---------|---------------|---------------|
| Implementation | Python (OpenAI SDK) | Rust (native) |
| Incremental streaming | Yes | No (buffered) |
| Reasoning separation | Yes | Yes |
| Tool calling | Yes | Yes |
| Test health | Green | Partially xfail (stale tests) |

## Setup

### 1. Build Python Bindings

```bash
cd balloons-rs/crates/ai-sdk-openai-compatible-py
maturin develop
```

### 2. Run OpenAI-Compatible Server

Example with llama.cpp:

```bash
llama-server --port 8000 --model /path/to/Qwen3.5-122B.gguf
```

### 3. Configure Balloons

Copy the example config:

```bash
cp config/config.ai-sdk.example.yaml ~/.balloons/config.yaml
```

Edit `~/.balloons/config.yaml`:

```yaml
default_backend: ai_sdk

backends:
  ai_sdk:
    type: ai_sdk
    base_url: http://192.168.0.196:8000
    model: Qwen3.5-122B-A10B-Q6_K-00001-of-00004.gguf
    context_window: 200000
    system_prompt: ~/.balloons/prompts/coding-assistant.md
```

### 4. Start Balloons

```bash
./balloons-server.py
```

## Configuration Options

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | Must be `ai_sdk` |
| `base_url` | Yes | OpenAI-compatible server URL (without `/v1`) |
| `model` | Yes | Model identifier loaded on the server |
| `api_key` | No | API key for servers requiring authentication |
| `context_window` | No | Maximum context size (default: 200000) |
| `system_prompt` | Yes | Path to system prompt file |

## Known Limitations

1. **Buffered streaming** — see Current State; no incremental deltas yet
2. **Max tokens**: Requires 500+ tokens for models with thinking/reasoning phases

## Testing

Test the Python bindings directly:

```bash
cd balloons-rs/crates/ai-sdk-openai-compatible-py
source venv/bin/activate
pytest tests/integration/ -v -s
```

## Comparison with OpenAI Runner

| Feature | OpenAI Runner | AI SDK Runner |
|---------|---------------|---------------|
| Implementation | Python (OpenAI SDK) | Rust (native) |
| Streaming | Yes | Yes |
| Reasoning separation | No | Yes |
| Tool calling | Yes | Not yet |
| Performance | Good | Better |

## Troubleshooting

### ImportError: ai_sdk_openai_compatible_py not found

```bash
cd balloons-rs/crates/ai-sdk-openai-compatible-py
maturin develop
```

### Model hits token limit during thinking

Increase `max_tokens` in the runner or use a model with shorter thinking phases.

### Connection refused

Check that your OpenAI-compatible server is running:

```bash
curl http://192.168.0.196:8000/v1/models
```
