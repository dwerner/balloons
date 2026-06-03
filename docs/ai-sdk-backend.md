# AI SDK Backend (Rust)

The AI SDK backend uses the high-performance Rust implementation of the OpenAI-compatible protocol via the `ai-sdk-openai-compatible` crate.

## Features

- **Native async streaming** with proper SSE handling
- **Reasoning/Text separation** - Qwen's thinking process is emitted separately from the final response
- **Type-safe** Rust implementation with Python bindings
- **Better performance** compared to pure Python implementations

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

1. **Tool calling**: Not yet implemented in this runner (falls back to text-only)
2. **Image support**: Not yet implemented
3. **Max tokens**: Requires 500+ tokens for models with thinking/reasoning phases

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
