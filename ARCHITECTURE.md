# Balloons Architecture

## Current State

Balloons is a **headless server + web UI** system for LLM-powered coding agents.

### Supported runtime
- **Headless server** (`headless.py`) is the supported backend runtime
- **React web UI** (`web/ui/`) is the supported frontend
- **WebSocket JSON-RPC API** is the primary integration surface between frontend and backend

### Unsupported / removed surfaces
- The **Textual TUI is dead and unsupported**
- **`:commands` are dead and unsupported**
- References to `app.py`, `main.py`, `widgets/`, and command-mode workflows in older docs should be treated as historical only unless explicitly marked otherwise

## Core Architectural Decisions

1. **Session-based conversation model**
   - Conversations are organized as sessions with turns
   - Sessions support forking, merging, linking, and derived conversations

2. **Context management as a first-class concept**
   - Per-turn COPY/COMPRESS/DROP modes control prompt context construction

3. **Service-oriented backend**
   - Core state and orchestration are exposed through WebSocket services
   - Services are the source of truth for generated client types

4. **Headless-first frontend architecture**
   - The backend is designed to support multiple clients over WebSocket
   - The currently supported client is the React web UI
   - Historical TUI-oriented design docs remain in the repo but do not describe the supported product surface

## Runtime Architecture

```text
┌─────────────────┐     WebSocket      ┌─────────────────────────────────┐
│   React Web UI  │◄──────────────────►│       Headless Server           │
│   (web/ui/)     │                    │                                 │
└─────────────────┘                    │  ┌─────────────────────────┐   │
                                       │  │   Service Layer          │   │
                                       │  │   - SessionManagerService│   │
                                       │  │   - SessionDataService   │   │
                                       │  │   - GoalTreeStateService │   │
                                       │  │   - TaskStateService     │   │
                                       │  │   - QueueStateService    │   │
                                       │  │   - etc.                 │   │
                                       │  └─────────────────────────┘   │
                                       │              │                  │
                                       │  ┌───────────▼─────────────┐   │
                                       │  │   Core Layer             │   │
                                       │  │   - SessionManager       │   │
                                       │  │   - SessionRunner (LLM)  │   │
                                       │  │   - AsyncStorage         │   │
                                       │  │   - GoalTreeState        │   │
                                       │  │   - Queue/Stream State   │   │
                                       │  └─────────────────────────┘   │
                                       └─────────────────────────────────┘
```

## Storage Status

Rust-backed storage is part of the **current architecture**, not just an aspirational plan.

- Sessions and goals are stored through a Rust backend exposed to Python
- The active Python integration uses `core/async_storage.py`
- Legacy JSON paths remain in parts of the codebase for migration/cleanup compatibility
- Some documentation still describes the old JSON/TUI world; those references are stale unless explicitly archived

This means the repo is in a **transitional cleanup state**, not an early storage prototype state.

## Module Overview

```text
balloons/
├── headless.py              # Supported server entry point
├── balloons-server.py       # Headless server manager
├── session.py               # Session model + persistence-heavy logic (needs decomposition)
├── models.py                # Domain entities and content block types
├── storage_schema.py        # Storage DTOs for Rust/codegen
│
├── core/                    # Core logic and state management
│   ├── manager.py           # Session lifecycle manager
│   ├── runner.py            # LLM execution
│   ├── async_storage.py     # Rust-backed async persistence wrapper
│   ├── goal_tree_state.py   # Goal/plan/todo state
│   ├── queue_state.py       # Queue state
│   ├── stream_state.py      # Stream/task state
│   └── ...
│
├── service/                 # WebSocket-exposed services
│   ├── session_manager_service.py
│   ├── session_data_service.py
│   ├── goal_tree_state_service.py
│   ├── task_state_service.py
│   ├── queue_state_service.py
│   └── ws_server.py
│
├── web/
│   ├── generated/           # Generated TypeScript clients/types
│   └── ui/                  # Supported React frontend
│
├── plugins/                 # Domain plugins
├── codegen/                 # Wire/schema generation
└── balloons-rs/             # Rust storage/supervisor workspace
```

## Transitional Debt

The bulk documentation cleanup is done: completed/superseded plan documents have been removed (recoverable from git history) and current-facing docs are rewritten around the headless/web product. Remaining debt:
- comments/docstrings that still describe deleted UI ownership or outdated workflows
- command-mode references that no longer reflect supported behavior
- deprecated compatibility exports (e.g. the service-locator shims in `service/__init__.py`) pending import-surface cleanup

## Layer Boundaries and Placement Rules

The current codebase has three meaningful backend strata, even though the directory structure does not yet cleanly enforce them.

### 1. Domain / infrastructure-neutral core

**Primary home today:** `session.py`, `models.py`, parts of `core/`

This layer should contain:
- session/domain entities and value objects
- context-shaping rules and prompt-building logic that do not depend on WebSocket/RPC transport
- fork/merge/link/archive rules as domain workflows when they are independent of delivery mechanism
- persistence abstractions and storage adapters that are not tied to WebSocket request handling
- queue/stream/session state models that can be exercised without a network server

This layer should **not** contain:
- WebSocket RPC decorators or transport payload shaping
- direct client event emission
- HTTP auth/server concerns
- frontend-specific subscription mechanics

Current examples that already fit reasonably well:
- `core/manager.py`
- `core/context.py`
- `core/fork.py`
- `core/async_storage.py`
- `core/stream_state.py`
- `core/queue_state.py`
- much of `session.py` (though it is overloaded and still mixes multiple concerns)

### 2. Application / orchestration workflows

**Primary home today:** mostly embedded inside `service/session_manager_service.py`, with some workflow code in `core/manager.py` and `core/fork.py`

This layer should contain:
- multi-step use cases such as submit-message, fork, derive, merge, archive, review, watcher flows, and queue draining
- coordination across sessions, runners, helper runners, storage, and event streams
- translation from low-level runner/storage events into higher-level workflow state changes
- dependency injection boundaries for collaborators used by transport-facing services

This layer should **not** contain:
- WebSocket-specific decorators or RPC naming concerns
- raw frontend event formatting as the source of truth
- persistence wire-format details when those can live in storage/domain modules

In other words: if logic is a product workflow and would still exist with a CLI, tests, or another transport, it belongs here rather than in transport-facing services.

### 3. Transport / service adapters

**Primary home today:** `service/`

This layer should contain:
- WebSocket-exposed service classes and generated-schema-facing dataclasses
- subscription/event fanout for connected clients
- JSON-RPC/API shape decisions
- transport-specific translation between internal workflow/domain events and wire payloads
- server/auth bootstrapping in HTTP/WebSocket entrypoints

This layer should **not** contain:
- the full implementation of product workflows
- hidden global runtime state
- business/domain rules that are unrelated to WebSocket delivery

## Current Placement Assessment

### `session.py`

`session.py` is mostly **domain + persistence** and should stay on the core side of the boundary, but it is too large because it currently combines:
- session entity state
- dirty tracking
- serialization/deserialization
- storage compatibility/migration helpers
- persistence entrypoints (`load`, `save`, `list_sessions`, etc.)

That makes it a candidate for later Workstream 5 decomposition, but not for transport/service ownership.

### `core/manager.py`

`core/manager.py` is best treated as **core application support**, not transport. It owns in-memory session/runner registration and lifecycle helpers, but it should remain free of WebSocket concerns.

### `service/session_manager_service.py`

`SessionManagerService` currently mixes two roles:
1. **transport adapter** responsibilities that belong in `service/`
2. **application workflow orchestration** that should eventually move to dedicated collaborators outside the transport layer

Transport-facing responsibilities that should remain in `service/session_manager_service.py` over time:
- `@ws_expose` RPC surface
- wire dataclasses returned to the UI
- observer registration for transport consumers
- relaying workflow events to `TaskStateService` / `SessionDataService`

Workflow responsibilities that are candidates to move out over time:
- streaming event pump coordination
- helper-runner lifecycle handling
- fork/derive/merge/archive/review workflow coordination
- watcher workflow coordination
- queue-drain orchestration after streaming completion
- turn-mutation concurrency coordination beyond thin delegation

## Candidate Module Placement Model

This workstream is design-first, so the model below defines **intended ownership** before broad refactors.

### Keep in `core/` or other non-service modules
- `Session` entity behavior and persistence decomposition from `session.py`
- `SessionManager` in-memory lifecycle/state coordination
- `ForkManager` and context-selection logic
- storage adapters and serialization helpers
- stream/queue state models
- prompt/context assembly

### Introduce or grow an application/orchestration area over time
Potential future homes:
- `app/session_workflows.py`
- `app/streaming_orchestrator.py`
- `app/helper_workflows.py`
- `app/fork_merge_workflows.py`
- `app/archive_review_workflows.py`
- `app/watcher_workflows.py`

These would own reusable product workflows and expose narrower interfaces to services.

### Keep in `service/`
- `SessionManagerService` as a WebSocket façade
- `SessionDataService`, `TaskStateService`, `QueueStateService`, `GoalTreeStateService` as transport-facing state/event adapters
- `ws_server.py`, `http_server.py`, auth route/server integration
- service-local event schemas and subscription mechanics

## Concrete Placement Rules for Future Changes

When touching code in later workstreams, use these rules:

1. If code primarily answers **"what is the session/workflow state and how does it evolve?"**, prefer core/application placement.
2. If code primarily answers **"how is this exposed over WebSocket/HTTP?"**, prefer `service/` placement.
3. If logic would still be needed with a different client transport, it should not originate in a WebSocket service class.
4. `service/` may translate events and invoke workflows, but should become thinner over time.
5. New workflow helpers should depend on injected collaborators, not hidden globals or package-level runtime state.
6. `session.py` and `SessionManagerService` should be split along these boundaries rather than merely cut into arbitrary smaller files.

## Near-Term Architectural Priorities

1. Keep docs aligned with the headless/web reality as it evolves
2. Use these boundary rules to guide decomposition of `session.py`
3. Extract workflow orchestration responsibilities out of `SessionManagerService` incrementally
4. Keep `service/` focused on transport/API exposure and event delivery
5. Document and harden persistence invariants
