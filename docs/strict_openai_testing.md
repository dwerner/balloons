# Strict OpenAI Backend Testing Procedure

This document describes how to validate `openai_strict` backends against Mistral-style Jinja chat templates using the isolated strict runner path.

## What this tests

The goal is to verify that our strict transcript builder matches the live backend's rules for role alternation and tool-cycle replay.

Confirmed Mistral behavior:

- `user -> assistant(tool_calls) -> tool -> assistant -> user` is valid
- `user -> assistant(tool_calls) -> tool -> assistant(tool_calls) -> tool -> assistant -> user` is valid for successive function calling
- `user -> assistant(tool_calls) -> tool -> user` is invalid
- `user -> assistant(tool_calls) -> tool -> assistant -> assistant -> user` is invalid when that creates two plain assistant turns
- `user -> assistant(text)` is rejected in this strict configuration

## Configuring a strict backend

Use a backend definition with:

```yaml
backends:
  mistral_strict:
    type: openai_strict
    base_url: http://192.168.0.196:8000/v1
    model: Mistral-Small-4-119B-2603-UD-Q6_K-00001-of-00004.gguf
```

The `openai_strict` backend type selects `StrictOpenAICompatibleRunner`.

## Local unit tests

Run the strict packaging and runner-selection tests:

```bash
pytest -q tests/test_runner_factory.py tests/test_openai_strict_backend.py tests/test_strict_openai_packaging.py tests/test_strict_openai_runner.py
```

These tests validate:

- strict backend selection in the runner factory
- canonical transcript rendering
- closing assistant insertion after tool cycles
- no merging across user boundaries
- no orphan tool replay

## Live integration tests

The live Mistral integration tests are in:

- `tests/test_openai_strict_live.py`

Run them with:

```bash
pytest -q tests/test_openai_strict_live.py -m integration
```

By default, the tests target:

- `MISTRAL_STRICT_URL=http://192.168.0.196:8000/v1/chat/completions`
- `MISTRAL_STRICT_MODEL=Mistral-Small-4-119B-2603-UD-Q6_K-00001-of-00004.gguf`
- `MISTRAL_STRICT_API_KEY=dummy`

Override these with environment variables if needed.

### Live cases exercised

The live test matrix checks:

1. **Complete tool cycle**
   - `user -> assistant(tool_calls) -> tool -> assistant -> user`
   - expected: `200 OK`

2. **Missing closing assistant**
   - `user -> assistant(tool_calls) -> tool -> user`
   - expected: server error with alternation complaint

3. **Two assistant closers**
   - `user -> assistant(tool_calls) -> tool -> assistant -> assistant -> user`
   - expected: server error with alternation complaint

4. **Assistant text turn**
   - `user -> assistant(text)`
   - expected: rejected in this strict configuration

## Standalone probe script

For quick manual checks, use:

```bash
python scripts/probe_openai_strict.py --url http://192.168.0.196:8000/v1/chat/completions --model Mistral-Small-4-119B-2603-UD-Q6_K-00001-of-00004.gguf
```

The script prints the status code and a response preview for each case.

## Troubleshooting

If the tests skip or fail to connect:

- verify the Mistral server is running on `192.168.0.196:8000`
- confirm the endpoint responds to `GET /v1/models`
- ensure the model name matches the server’s loaded GGUF
- if the backend is on a different machine, update `MISTRAL_STRICT_URL`

If the backend returns alternation errors:

- ensure a closing assistant exists after every tool result block
- do not allow a `user` turn to follow `assistant(tool_calls) -> tool` directly
- do not emit two consecutive plain assistant messages in the replay sequence
