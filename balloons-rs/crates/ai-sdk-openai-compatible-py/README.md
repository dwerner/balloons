# ai-sdk-openai-compatible-py

Python bindings for the `ai-sdk-openai-compatible` Rust crate.

## Installation

```bash
maturin develop
```

## Usage

```python
import asyncio
from ai_sdk_openai_compatible_py import create_chat_model_py, PyMessage

async def main():
    model = create_chat_model_py("http://localhost:8000", "my-model", None)
    
    # Generate
    result = await model.generate(
        messages=[PyMessage("user", "Hello")],
        max_tokens=500,
        temperature=0.7,
    )
    print(result)
    
    # Stream
    stream = await model.stream(
        messages=[PyMessage("user", "Hello")],
        max_tokens=500,
        temperature=0.7,
    )
    async for chunk in stream:
        print(chunk)

asyncio.run(main())
```

## Testing

### Unit Tests
```bash
pytest tests/
```

### Integration Tests
Requires a running OpenAI-compatible server:
```bash
pytest tests/integration/ -v -s
```

Or with marker:
```bash
pytest -m integration -v -s
```

See `tests/README.md` for more details.
