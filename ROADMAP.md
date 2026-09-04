# Balloons Roadmap

Active development plans and future enhancements. Small open items live in [docs/bugs-and-todos.md](docs/bugs-and-todos.md); this file tracks only substantial workstreams.

## In Progress

### Architecture Remediation
Incremental decomposition of the remaining oversized modules.
- WS4: enforce layer boundaries (`core` vs orchestration vs `service`)
- WS5: split `session.py`
- WS6: split `SessionManagerService` into a thin façade + workflow collaborators
- WS7: persistence invariants + stress coverage
- WS8: legacy/deprecation inventory and retirement

See: [PLAN-architecture-remediation.md](PLAN-architecture-remediation.md)

### URL Routing (designed, not implemented)
Hash-based deep links for sessions, turns, goals, and tabs. Design complete, implementation not started.

See: [docs/specs/url-routing.md](docs/specs/url-routing.md)

## Recently Completed

- OpenAI-compatible backend (`type: openai`, replaces the LiteLLM path)
- Incremental (async-generator) streaming in the HTTP runners
- Layer-based subscriptions (header/body/delta/history)
- Configurable per-backend `context_window` with usage display
- Watcher mode MVP (see [docs/specs/watcher-mode.md](docs/specs/watcher-mode.md))
- Supervisor tab, Code tab, session review modal
- Service-locator removal from plugin/runtime event paths

## Future Ideas

- **Maturing the `ai_sdk` (Rust) runner** — experimental backend kept alongside the primary `openai` runner; next step is the async-generator streaming conversion (see [docs/ai-sdk-backend.md](docs/ai-sdk-backend.md))
- **Project config modernization** — `pyproject.toml`, ruff config, pinned dependencies
- **Fork from historical turn** — "what if we'd done this differently"
- **Watcher split/swap UI** — side-by-side watcher/target viewing (see watcher doc)
- **Scheduling / cron-style session watching**