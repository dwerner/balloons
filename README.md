# Balloons

A conversation platform for LLM-powered coding agents with session forking, context curation, and a WebSocket API for multiple frontends.

**Current state:** Headless server + React web UI. The Textual TUI is dead and unsupported, and `:commands` are dead and unsupported.

## What Balloons Does

- **Session forking & merging** — Branch conversations like git branches. Fork to explore, merge results back.
- **Context curation** — Per-turn COPY/COMPRESS/DROP modes control what context goes into prompts.
- **Multi-backend support** — Claude API, OpenRouter, Ollama, or any OpenAI-compatible endpoint.
- **Process supervision** — Start dev servers, builds, or long-running commands with log capture.
- **Goal/plan/todo tracking** — Persistent task hierarchies with session bindings.
- **Plugin system** — Domain plugins (chess, kanban, charts) with custom UI components.

## Architecture

```
┌─────────────────┐     WebSocket      ┌─────────────────────────────────┐
│   React Web UI  │◄──────────────────►│       Headless Server           │
│   (web/ui/)     │                    │                                 │
└─────────────────┘                    │  ┌─────────────────────────┐   │
                                       │  │   Service Layer          │   │
                                       │  │   - SessionManagerService │   │
                                       │  │   - SessionDataService   │   │
                                       │  │   - GoalTreeStateService │   │
                                       │  │   - TaskStateService     │   │
                                       │  │   - etc.                 │   │
                                       │  └─────────────────────────┘   │
                                       │              │                  │
                                       │  ┌───────────▼─────────────┐   │
                                       │  │   Core Layer             │   │
                                       │  │   - SessionManager       │   │
                                       │  │   - SessionRunner (LLM)  │   │
                                       │  │   - AsyncStorage (LMDB)  │   │
                                       │  │   - GoalTreeState        │   │
                                       │  └─────────────────────────┘   │
                                       └─────────────────────────────────┘
```

**Storage:** Sessions and goals are stored in LMDB via a Rust backend (`balloons-rs`), exposed through PyO3. Legacy JSON file paths are kept for migration only.

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js / Bun (for web UI)
- `ANTHROPIC_API_KEY` environment variable (for Claude backend)
- **Optional:** The Rust storage backend (`balloons-rs`) for ACID-compliant persistence

### Installation

```bash
git clone https://github.com/your-org/balloons.git
cd balloons

# Python environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional: Build Rust storage backend
cd balloons-rs
maturin develop --release
cd ..

# Web UI dependencies
cd web/ui
bun install
cd ../..
```

### Running

**Start the headless server:**

```bash
# Direct invocation
python headless.py --port 8700

# Or use the server manager (supports multiple instances)
python balloons-server.py start --port 8700
python balloons-server.py list
python balloons-server.py stop --port 8700
```

**Start the web UI:**

```bash
cd web/ui
bun run dev
```

Open http://localhost:3030 to use the web interface.

## Server Management

The `balloons-server.py` script manages headless instances:

```bash
python balloons-server.py start              # Start on default port 8700
python balloons-server.py start --port 8710  # Start on alternate port
python balloons-server.py list               # Show running instances
python balloons-server.py stop --port 8700   # Stop instance
python balloons-server.py restart            # Restart instance

# UI server management
python balloons-server.py ui start           # Start bun dev server
python balloons-server.py ui stop            # Stop bun dev server
```

Default ports:
- **8700** — Primary backend (slot A)
- **8710** — Secondary backend (slot B)
- **3030** — Web UI dev server

### A/B Slots

Two fixed slots support safe self-modification: run stable code on slot A, start slot B with edited source, and test in the web UI via the sidebar slot toggle (persisted, auto-reconnects). Since running servers are unaffected by source edits until restart, a broken experiment never takes down slot A. When changes are verified, `restart` slot A to promote them.

## Configuration

Create `~/.balloons/config.yaml`:

```yaml
default_backend: claude

backends:
  claude:
    type: claude
    context_window: 200000

  openrouter:
    type: openai
    base_url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
    model: anthropic/claude-sonnet-4
    system_prompt: ~/.balloons/prompts/coding-assistant.md

  ollama:
    type: openai
    base_url: http://localhost:11434/v1
    api_key: ollama
    model: llama3.2
    system_prompt: ~/.balloons/prompts/minimal.md

websocket:
  enabled: true
  host: localhost
  port: 8700
  jwt:
    enabled: true
```

See `config/config.sample.yaml` for full options including TLS, auth, sounds, and TTS.

## Project Structure

```
balloons/
├── headless.py              # Main server entrypoint
├── balloons-server.py       # Server instance manager
├── session.py               # Session model and persistence
├── config.py                # Configuration management
├── models.py                # Domain models (Turn, Message, ContentBlock types)
│
├── core/                    # Core logic (no network concerns)
│   ├── manager.py           # SessionManager
│   ├── runner.py            # LLM execution (SessionRunner)
│   ├── async_storage.py     # LMDB storage via Rust
│   ├── goal_tree_state.py   # Goal/plan/todo state
│   ├── fork.py              # Fork/merge operations
│   └── ...
│
├── service/                 # WebSocket-exposed services
│   ├── ws_server.py         # WebSocket server with JSON-RPC dispatch
│   ├── session_manager_service.py  # Session lifecycle, streaming
│   ├── session_data_service.py     # Session subscriptions
│   ├── goal_tree_state_service.py  # Goal management
│   ├── task_state_service.py       # Streaming events
│   └── ...
│
├── web/
│   ├── generated/           # Auto-generated TypeScript clients
│   └── ui/                  # React web frontend
│
├── plugins/                 # Domain plugins (chess, kanban, charts, etc.)
│
├── balloons-rs/             # Rust workspace
│   └── crates/
│       ├── balloons-core/   # LMDB storage engine
│       ├── balloons-py/     # PyO3 bindings
│       └── balloons-supervisor/  # Process supervisor
│
└── codegen/                 # Code generation
    ├── generate_typescript.py  # TypeScript client from Python services
    └── generate_rust.py        # Rust structs from Python schemas
```

## WebSocket API

The server exposes a JSON-RPC API over WebSocket. Methods are organized by service:

**SessionManagerService:**
- `submitMessage(sessionId, content)` — Submit prompt and start streaming
- `createSession(workingDirectory?)` — Create new session
- `forkSession(parentId, ...)` — Fork a session
- `switchSession(sessionId)` — Switch active session

**TaskStateService events:**
- `onContentDelta` — Text chunks during streaming
- `onTurnStarted` — New turn began
- `onToolUse` / `onToolResult` — Tool execution
- `onTurnFinished` — Turn completed

**SessionDataService:**
- `subscribeSession(sessionId)` — Subscribe to session updates
- `getSessionTurns(sessionId, ...)` — Paginated turn history

See `web/generated/types.ts` and `web/generated/client.ts` for the full TypeScript API.

## Development

```bash
# Run tests
pip install pytest
pytest

# Regenerate TypeScript client from Python services
python -m codegen.generate_typescript

# Type check
mypy .
```

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture and design decisions
- [FEATURES.md](FEATURES.md) — Feature specification
- [ROADMAP.md](ROADMAP.md) — Active workstreams and future ideas
- [docs/](docs/) — Additional design docs and guides

## Status

This project is in active development. The service layer and storage backend are stable. The web UI is functional but evolving.

**Recent changes:**
- Migrated from JSON file storage to LMDB (via Rust)
- Supported product surface is the headless server + web UI
- `:commands` are removed and unsupported
- Added plugin system for domain-specific tools and UI

## License

See [LICENSE](LICENSE)
