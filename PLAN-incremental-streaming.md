# Plan: Incremental (async-generator) streaming in the OpenAI runners

## Problem

Neither HTTP runner streams. Every delta — answer text **and** reasoning — is buffered
until the HTTP response finishes, then delivered in one burst.

Measured against `frank` (192.168.0.120:8000) with `OpenAICompatibleRunner.stream_response`:

```
total events: 62
TextDelta:     count=35  first=1.92s  last=1.92s  span=0.00s
ThinkingDelta: count=25  first=1.92s  last=1.92s
```

The same endpoint via raw `curl` streams progressively, so the server is fine. The
buffering is inside the runner, upstream of the WebSocket. The WS layer, the service
event pump, and the UI all already handle per-delta events correctly — `useSessionData`
even deliberately renders thinking per-delta while batching text at 50 ms.

### User-visible symptom this explains

"Conversation stops when the assistant says it's about to take action."

The announcement text and the tool call come from the *same* LLM call, so the
announcement is withheld until that call completes; the *next* call then runs long
(local model, large context, reasoning tokens first) and emits nothing until it
finishes. From the UI: announces action → silence → looks dead. It is not stopped, it
is buffered. Enabling reasoning makes the pre-output silence longer, so this feels
worse once thinking is turned on.

## Root cause

`core/openai_runner.py` and `core/strict_openai_runner.py` share one shape:

```python
# stream_response (openai_runner.py:779, strict:536)
tool_calls_data, input_tokens, output_tokens = await self._stream_one_response(...)
for event in tool_calls_data.get("events", []):   # <-- replay of a finished list
    yield event
```

`_stream_one_response` (openai_runner.py:1019, strict:812) is a coroutine returning
`tuple[dict, int, int]`, accumulating into a local `events` list:

```python
events = []
async for chunk in stream:
    ...
    events.append(TextDelta(...))          # :1147
    events.append(ThinkingDelta(...))      # :1157 (reasoning)
    events.append(ToolUseStartEvent(...))  # :1212
    events.append(ToolInputDeltaEvent(...))# :1224
...
events.append(ToolUseEvent(...))           # :1294, post-loop finalization
return {"events": events, "tool_calls": finalized_tool_calls, "content": content_buffer}, input_tokens, output_tokens
```

Because nothing is yielded until the coroutine returns, the `await` cannot complete
until the whole HTTP stream is done. The `await asyncio.sleep(0)` calls at :1150, :1155,
:1166 were meant to cooperate with the loop but are inert — there is no suspension point
that surfaces data.

`claude_runner.py` has 30 real `yield`s and genuinely streams. That is the reference
implementation; the CLI backend works, which is why this reads as a regression specific
to the HTTP backends.

## Proposed contract

Make `_stream_one_response` an **async generator of events**, and carry the non-event
results out through an explicit, caller-owned outcome object.

```python
@dataclass
class StreamOutcome:
    """Non-event results produced while streaming one response."""
    tool_calls: list[dict] = field(default_factory=list)
    content: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

async def _stream_one_response(
    self,
    openai_messages: list[dict],
    tools: list[dict] | None,
    outcome: StreamOutcome,          # filled in before the generator finishes
) -> AsyncIterator[RunnerEvent]:
    ...
    yield TextDelta(text=delta.content)      # as it arrives
    ...
    outcome.tool_calls = finalized_tool_calls
    outcome.content = content_buffer
    outcome.input_tokens = input_tokens
    outcome.output_tokens = output_tokens
```

Caller:

```python
outcome = StreamOutcome()
async for event in self._stream_one_response(openai_messages, tools, outcome):
    yield event
tool_calls = outcome.tool_calls
assistant_content = outcome.content
total_input_tokens += outcome.input_tokens
total_output_tokens += outcome.output_tokens
```

### Why this shape

- The generator's yield type stays a pure `RunnerEvent` — nothing non-event leaks into
  the event stream.
- Data flow stays explicit; a caller cannot forget to read a hidden field.
- Test fakes become trivial async generators.

### Alternatives rejected

- **Final sentinel event** (`yield _StreamDone(outcome)`): the caller must filter it, and
  forgetting to filter leaks a non-event into `runner.py`'s `_process_event`.
- **Store on `self`** (`self._last_outcome`): smallest diff, but hides data flow and
  invites cross-talk if a runner instance is ever reused concurrently.

## Mechanical transformation

For each of `openai_runner.py` and `strict_openai_runner.py`:

1. Add the `StreamOutcome` dataclass (module level, or `core/base_runner.py` if shared).
2. Change signature: `-> AsyncIterator[RunnerEvent]`, add `outcome` parameter.
3. Delete `events = []`. Every `events.append(X)` inside the chunk loop becomes
   `yield X`. **Remove the list entirely** — leaving it alongside yields duplicates every
   event.
4. Post-loop `events.append(ToolUseEvent(...))` (:1294) becomes `yield ToolUseEvent(...)`.
5. Replace the `return {...}, input_tokens, output_tokens` tail with assignments into
   `outcome` and a bare `return`.
6. Delete the now-pointless `await asyncio.sleep(0)` calls — `yield` is the suspension
   point.
7. Wrap the body in `try/finally` to preserve cleanup on `GeneratorExit` (consumer stops
   iterating on cancel): confirm `self._running` / `self._run_id` reset still happens.
   Today that reset lives in `stream_response`'s `except`/tail (:1008-1010) — verify it
   still runs when the generator is abandoned mid-iteration.
8. Update the caller loop (openai :779-797, strict :536-554) to the `async for` + outcome
   form above.

## Invariants to preserve

- **Exceptions must keep propagating.** `stream_response`'s `except Exception` (:977)
  builds the `ErrorBlock`, dumps `_collected_chunks`, and adds the `dump_file` marker.
  Do not swallow exceptions inside the generator. `tests/test_strict_openai_runner.py:33`
  asserts exactly this (raises `RuntimeError("boom")`, expects a stream-error event with
  dump path).
- **Event ordering.** `ToolUseStartEvent` / `ToolInputDeltaEvent` surface during the
  stream; `ToolUseEvent` (parsed args) stays after the loop. `runner.py` reacts to
  `ToolUseStartEvent` by flushing the text buffer as a turn — already proven by
  `claude_runner`, which streams.
- **`stream_options: {"include_usage": True}`** — usage still arrives on the final chunk;
  unchanged.
- **`ResultEvent`** (:970) carries only token totals, not content, so it is unaffected.
- **Embedded tool-call detection** and `_dump_interaction` run after the loop off
  `content_buffer` / `_collected_chunks`; they stay in the finalization step.

## Blast radius

| File | Change |
|---|---|
| `core/openai_runner.py` | generator conversion + caller loop |
| `core/strict_openai_runner.py` | same, mirrored |
| `tests/test_strict_openai_runner.py` | 3 fakes (:33, :231, :284) become async generators filling an outcome |

`core/ai_sdk_runner.py` has the identical buffering flaw (`:218` awaits a
`(result, events)` tuple). **Out of scope** — the Rust ai-sdk path is being dropped in
favour of `type: openai`; its tests are already marked stale/xfail. Note it so it is not
mistaken for fixed.

## Verification

1. **Re-measure.** Re-run the probe (`/tmp/stream_probe.py`): assert `span > 0` and that
   the first `TextDelta` lands well before the last, and that `ThinkingDelta` precedes
   `TextDelta`.
2. **Deterministic regression test (no timing flakiness).** Fake the HTTP stream so chunk
   *N* is only produced after event *N-1* has been yielded — a handshake. If the runner
   buffers, the test deadlocks and fails on timeout rather than passing silently. This is
   the test that would have caught the original bug, and the one that prevents
   reintroducing it.
3. **Suite.** `.venv/bin/python -m pytest -q tests -m "not integration"` — currently green
   (1321 passed, 13 xfailed, ~9 s).
4. **Live check.** Restart the headless servers, prompt `frank`, confirm reasoning text
   appears and grows before the answer starts.

## Sequencing

1. `openai_runner.py` only (the default backend `frank`), then re-measure. Proves the
   approach in isolation.
2. Add the handshake test.
3. Mirror into `strict_openai_runner.py` + fix its 3 fakes.
4. Full suite.

## Scope: this is not the history path

"Streaming" appears on both sides of this system, and the two are unrelated code paths —
worth stating before the async-generator word shows up near "history":

| | live token delivery | history load |
|---|---|---|
| path | HTTP SSE → runner → service pump → WS | LMDB → turns → `ContextBuilder` / `HistoryLoader` |
| touched by this refactor | yes | **no** |

History loading is already split in two, and only one half is a bulk query:

- **Bulk.** `AsyncStorage.load_session` → `load_turns()` reads *all* turns and `json.loads`
  the whole blob (`core/async_storage.py:498`, called at `:339`; see also the note at
  `:859`). Used for full session load and context construction. `get_turn_count()` exists
  specifically to avoid that read.
- **Chunked.** `SessionDataService._stream_history_from_storage`
  (`service/session_data_service.py:1300`) already pages via
  `load_turns_range(offset, limit=50)` and emits `sessionDataHistoryChunk` per batch as a
  background task, "allowing clients to render progressively and receive streaming events
  concurrently."

`HistoryLoader.load()` is a pure in-memory transform of already-loaded messages — it is
not a query and issues no I/O.

Reconnect does not double-render: `SessionSnapshot` is atomic at subscribe time and
clients receive incremental `TurnDelta`s afterwards
(`service/session_data_service.py:127`, `:163`).

The one place the two paths meet: because deltas will now arrive *earlier*, a client
subscribing mid-stream gets a snapshot plus deltas that start flowing sooner. The
snapshot-then-delta contract is unchanged, but it belongs in the live verification step.

## Related, not fixed here

- **`_format_block(ThinkingBlock)` returns `None`**, so reasoning is dropped from history
  entirely (verified). A thinking turn therefore renders to *nothing* in context. Before
  any reasoning-replay feature is enabled, confirm an exchange containing an
  assistant-turn-that-produces-no-text does not create an empty assistant entry or break
  strict alternation (`strict_openai_packaging.validate_generation_boundary`).
- **Reasoning replay into context** should be a per-backend opt-in (llama.cpp/Qwen3
  benefits; Anthropic requires signed blocks returned verbatim; OpenAI wants structured
  reasoning items), not a global toggle.
- **Embedded tool-call false positives**: ordinary prose containing
  ` ```json {"name":` or `Read(file=...)` is flagged as a malformed tool call and dumped
  (seen in `runner.log`, and the broken accumulation in `tool_call_debug.log`).