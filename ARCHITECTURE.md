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

The repo still contains documentation and comments that drift from the supported headless/web product, including:
- old plan documents
- pre-removal design docs
- comments/docstrings that still describe deleted UI ownership or outdated workflows
- command-mode references that no longer reflect supported behavior

These are cleanup debt, not part of the supported architecture.

## Near-Term Architectural Priorities

1. Reconcile docs with current headless/web-only reality
2. Reduce import-time coupling in `service/`
3. Remove global runtime coupling from plugin integrations
4. Decompose oversized modules like `session.py` and `service/session_manager_service.py`
5. Document and harden persistence invariants
