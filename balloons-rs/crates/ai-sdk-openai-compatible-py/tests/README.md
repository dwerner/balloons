# Tests

## Unit Tests
Run unit tests (no external dependencies):
```bash
pytest tests/
```

## Integration Tests
Run integration tests (requires running OpenAI-compatible server):
```bash
pytest tests/integration/ -v -s
```

Or run only integration tests:
```bash
pytest -m integration -v -s
```

### Requirements
- Running OpenAI-compatible server at `http://192.168.0.196:8000`
- Model `Qwen3.5-122B-A10B-Q6_K-00001-of-00004.gguf` loaded
- Adjust `BASE_URL` and `MODEL_ID` in test files as needed
