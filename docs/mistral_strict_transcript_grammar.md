# Mistral Strict Transcript Grammar

This document defines the outbound transcript grammar for strict Mistral-style Jinja chat templates and maps internal session-history/runtime cases onto that grammar.

## Purpose

The strict backend is the spec.
The builder must emit only transcripts that conform to the template's accepted role language.

## Empirically confirmed backend rules

Confirmed against the live backend at `192.168.0.196:8000`:

- Valid:
  - `system? -> user -> assistant`
  - `system? -> user -> assistant(tool_calls) -> tool+ -> assistant -> user`
  - `system? -> user -> assistant(tool_calls) -> tool+ -> assistant(tool_calls) -> tool+ -> assistant -> user`
  - runtime live-tail fragments that begin with `assistant(tool_calls)`
- Invalid:
  - `assistant(tool_calls) -> tool -> user`
  - two plain assistant turns in a row
  - orphan `tool` messages
  - repeated plain `user` turns in the final replay transcript
- Also observed:
  - the assistant followup after a tool cycle may be:
    - real text
    - empty string
    - whitespace
    - `[Interrupted: user_cancelled]`
    - `[Error: api_error]`
    - another assistant turn containing `tool_calls` for successive function calling
  - assistant response text replay may be rejected when `enable_thinking` is active

## Canonical grammar

Using a compact EBNF-like notation:

```text
Transcript        := System? Conversation
System            := system
Conversation      := UserTurn (AssistantPhase UserTurn)* AssistantPhase?
AssistantPhase    := PlainAssistant | ToolCycle
PlainAssistant    := assistant_text
ToolCycle         := assistant_tool_calls ToolResult+ AssistantFollowup
ToolResult        := tool
AssistantFollowup := assistant_closing | assistant_tool_calls
```

## Role-level constraints

### 1. System
- At most one `system`
- If present, it must be first

### 2. User backbone
- The replay backbone alternates on `user` / `assistant`
- Multiple internal user inputs must be folded into one replayable `user` turn when no assistant boundary exists between them

### 3. Plain assistant
- A plain assistant turn is a single assistant message with no `tool_calls`
- Two plain assistant turns may not appear consecutively in the final transcript

### 4. Tool cycle
A tool cycle is atomic:

```text
assistant(tool_calls) -> tool+ -> assistant_followup
```

Where `assistant_followup` is either:
- a plain/closing assistant
- or another `assistant(tool_calls)` starting the next tool round

Constraints:
- tool results must immediately follow the matching assistant tool-call turn
- all replayed `tool` messages must belong to the immediately preceding assistant tool-call turn
- orphan tool messages are not allowed
- if a tool cycle is followed by a `user`, an assistant followup is required
- exactly one assistant followup is allowed for a tool cycle in the final replay transcript

### 5. Assistant followup
Allowed forms:
- empty string
- whitespace
- placeholder interruption/error closers
- real assistant text, if it is the single assistant closer completing the tool cycle
- another assistant turn containing `tool_calls`, if it starts the next tool cycle

Not allowed:
- one plain closer plus another plain assistant turn before the next user

## Session-history mapping rules

The builder must project internal history into the grammar above.

### A. Consecutive user inputs
Internal shape:

```text
user, user, user
```

Replay shape:

```text
user_combined
```

Rule:
- merge adjacent user inputs until an assistant boundary is encountered

### B. Assistant text only
Internal shape:

```text
user, assistant_text
```

Replay shape:

```text
user, assistant_text
```

Rule:
- replay once as a plain assistant turn

### C. Assistant tool call with tool results
Internal shape:

```text
assistant(tool_calls), tool_result(s)
```

Replay shape:

```text
assistant(tool_calls), tool+, assistant_closing
```

Rule:
- always emit the tool cycle atomically
- synthesize an empty assistant followup if none exists in replayable history

### D. Placeholder assistant after tool cycle
Internal shape:

```text
assistant(tool_calls), tool, [Interrupted: user_cancelled]
```

Replay shape:

```text
assistant(tool_calls), tool, assistant_closing
```

Rule:
- preserve placeholder closers if they are the single legal closer for the cycle

### E. Orphan tool result
Internal shape:

```text
tool
```

Replay shape:

```text
(drop)
```

Rule:
- do not replay orphan tools

### F. Multiple assistant messages without user boundary
Internal shape:

```text
assistant_text, assistant_text
```

Replay shape:
- invalid as-is
- must be interpreted, folded, or rejected by the strict builder logic

Rule:
- the builder must not emit this shape
- if one is a tool-cycle closer and the next starts a new tool cycle, rebuild from canonical turn semantics rather than replaying both verbatim

### G. Live runtime tool loop
Runtime shape may temporarily accumulate:
- assistant tool-call turn
- tool results
- steering / extra user input
- system prompt changes due to tool/domain changes

Replay rule:
- do not treat the mutable OpenAI message buffer as canonical truth
- before each backend call, rebuild a canonical transcript from:
  - current session history
  - current effective system prompt
  - current enabled tool set
  - current unresolved live exchange state

## Derived builder invariants

The strict builder must guarantee:

1. output contains at most one system message, at the front
2. no orphan tool messages
3. no `tool -> user` transitions
4. no `assistant -> assistant` transitions except the internal structure of a single tool cycle as interpreted by the template
5. no repeated replay `user` turns
6. every replayed tool cycle has exactly one assistant followup
7. the transcript is rebuilt from canonical state before each backend call

## Empirical verification matrix

These cases should be exercised against the live backend.

### Expected valid
1. `user -> assistant`
2. `user -> assistant(tool_calls) -> tool -> assistant("") -> user`
3. `user -> assistant(tool_calls) -> tool -> assistant(" ") -> user`
4. `user -> assistant(tool_calls) -> tool -> assistant("[Interrupted: user_cancelled]") -> user`
5. `user -> assistant(tool_calls) -> tool -> assistant("[Error: api_error]") -> user`

### Expected invalid
1. `user -> assistant(tool_calls) -> tool -> user`
2. `user -> assistant(tool_calls) -> tool -> assistant -> assistant -> user`
3. `user -> user`
4. `assistant -> assistant(tool_calls)`
5. orphan `tool`

## Implementation guidance

The strict builder should be implemented as a canonical transcript renderer, not a repair pass.

Recommended structure:
- define canonical turn/state objects
- fold session history into those canonical states
- render only legal transcript productions
- keep runtime unresolved exchange state separate from historical replay
- rebuild from canonical state before each request
