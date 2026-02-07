# Balloons Roadmap

Active development plans and future enhancements.

## In Progress

### Multi-Session Background Streaming
Allow multiple sessions to stream simultaneously while switching between them.

**Status**: Partially implemented - background fork streaming works, UI polish remaining

**Key features**:
- Background streaming infrastructure via `poll_all()`
- Background forks with `:fork --bg`
- TODO: Input enable/disable per-session, tree streaming indicators

See: [PLAN-multi-session.md](PLAN-multi-session.md)

### OpenRouter & LlamaCpp Backends
Direct SDK integration for OpenAI-compatible APIs.

**Status**: Architecture planned, implementation pending

**Key features**:
- `OpenAICompatibleRunner` using openai Python SDK
- Backend type: `claude` (CLI) or `openai` (SDK)
- Per-backend configuration (base_url, api_key, model)

See: [PLAN-openrouter-backend.md](PLAN-openrouter-backend.md)

### Enhanced Context Token Display
Improved token breakdown in status bar.

**Status**: Base feature implemented, Phase 2 enhancements planned

**Key features**:
- Format: `session+(system) / budget (%)`
- Configurable `context_window` per backend
- Color-coded values by usage level

See: [PLAN-context-tokens.md](PLAN-context-tokens.md)

---

## Completed

Archived plans in [docs/archived-plans/](docs/archived-plans/):

- **Context Tree & Fork/Merge Rework** - Git-like fork/merge workflow with COPY/COMPRESS/DROP modes
- **TreeState Shared Layer** - Framework-agnostic state for multiple tree views
- **Delete Turns** - Ability to delete turns from conversations

---

## Future Ideas

- **Project config modernization** - Add `pyproject.toml`, ruff config, pinned dependencies
- **App.py refactoring** - Split 186KB file into modular components
- **Picker UI for `:switch`** - Modal picker instead of status bar list
- **Fork from historical turn** - Enable "what if we'd done this differently"
