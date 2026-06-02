# Testing Guide

This guide captures general testing rules and conventions.

## Async vs sync tests

- If an API is async, its tests should also be async.
- Do not call async APIs from sync tests without awaiting them.
- Do not make sync tests async just to silence warnings.
- If only some tests in a file are async, mark only those tests with `@pytest.mark.asyncio`.
- Avoid blanket `pytestmark = pytest.mark.asyncio` on mixed sync/async test modules.

## Pytest asyncio warnings

If you see warnings like:

- `The test <Function ...> is marked with '@pytest.mark.asyncio' but it is not an async function`

then the usual fix is:

- remove blanket asyncio marking for the module, or
- move the mark to only the real `async def` tests

Do not convert plain sync/unit/dataclass tests to async unless the code under test is actually async.

## Async API expectations

- Assume that when an API is async, its tests should also be.
- Persistence, I/O, network, and service-dispatch tests should await async methods.
- In-memory helper tests can remain sync when they do not touch async APIs.

## Import and type identity pitfalls

- If `repr(obj)` shows the expected class name but `isinstance(obj, ExpectedClass)` is false, suspect duplicate imports or multiple module identities.
- Prefer normal package imports over loading the same source file under alternate module names.
- Avoid test import patterns that load a module directly from file when the application imports it through the package path.

## JWT test secrets

- Use HMAC secrets that are at least 32 bytes long for HS256 in tests.
- This avoids `InsecureKeyLengthWarning` noise and better matches production expectations.
- Prefer explicit test secrets such as:
  - `0123456789abcdef0123456789abcdef`
  - `test-secret-key-at-least-32-bytes!`

## Keep contract decisions explicit

- When tests fail because a public contract changed, decide whether code or tests define the intended behavior.
- Update tests when they are stale.
- Update implementation when the code drifted from the intended public contract.
