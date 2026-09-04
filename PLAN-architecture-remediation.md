# Plan: Architecture Remediation

## Goals

Address the architectural issues identified in the codebase review while keeping the system functional during incremental refactors.

Primary goals:
- Reduce hidden coupling across service, plugin, and runtime layers
- Split oversized modules into clearer responsibilities
- Improve import hygiene and test isolation
- Create a staged migration path for legacy code and transitional patterns

## Key Problems

1. **`session.py` is overloaded**
   - Domain model, persistence, migration, dirty tracking, and compatibility logic are mixed together.

2. **`SessionManagerService` is too large and too central**
   - Session lifecycle, stream orchestration, event routing, fork/merge workflows, and compatibility behavior are concentrated.

3. **Boundary between core/application/service layers is unclear**
   - Transport logic and orchestration logic are mixed.

4. **Incremental persistence is complex and high-risk**
   - Save/reorder/delete logic needs clearer invariants and better stress coverage.

5. **Legacy/deprecated paths are interleaved with current behavior**
   - Migration code and compatibility behavior remain inline in production modules.

## Guiding Principles

- Prefer **incremental refactors** over large rewrites.
- Preserve behavior first, then simplify internals.
- Keep runtime wiring explicit rather than global.
- Make package imports cheap and unsurprising.
- Separate **domain**, **application/orchestration**, and **transport** concerns.
- Avoid changing public import/runtime surfaces without characterization tests.
- One logical change at a time, with the smallest relevant test run after each.

## Workstreams

### WS1: Documentation Reconciliation — mostly done

Current-facing docs have been rewritten around the headless/web reality (TUI and `:commands` documented as dead). Stale completed-plan documents have been deleted (recoverable from git history). Remaining: keep pruning historical/stale references as they're encountered.

### WS2: Import Hygiene and Service Package Cleanup — done

Lazy `service` re-exports preserve runtime compatibility while reducing eager import coupling, covered by characterization tests.

### WS3: Remove Global Service Locator from Plugin Runtime — done

Explicit event-emitter wiring replaced global locator usage in all active plugin/runtime event paths. Legacy `get/set_session_manager_service` exports remain in `service/__init__.py` as deprecated compatibility surface; remove them once the import-surface contract allows.

### WS4: Clarify Layer Boundaries — open

- Define `core` as domain/infrastructure-neutral logic
- Define an application/orchestration layer for workflows
- Narrow `service` toward transport adapters and API exposure

Placement rules are documented in `ARCHITECTURE.md` (Layer Boundaries section); enforcement is still convention-only.

### WS5: Break Up `session.py` — open

Candidate target split:
- `session.py` or `core/session_entity.py` — public session model/entity
- `core/session_persistence.py` — save/load/repository concerns
- `core/session_serialization.py` — wire/storage conversions
- `core/session_migration.py` — legacy compatibility/migration helpers
- `core/session_dirty_state.py` — dirty tracking helpers

Extract low-risk helpers first; keep public API compatibility during transition.

### WS6: Break Up `SessionManagerService` — open

Candidate target split:
- `service/session_manager_service.py` — WebSocket-exposed façade
- application-layer collaborators for: session lifecycle, stream orchestration, fork/merge workflows, session event routing

Leave the RPC surface stable while moving internals out.

### WS7: Persistence Invariants and Stress Testing — open

- Document save invariants for sessions/turns/order/deletes
- Add stress tests for concurrent or repeated incremental save scenarios
- Validate behavior under rapid turn mutation/reorder/delete patterns
- Consider whether append-oriented semantics can simplify the model long-term

### WS8: Legacy and Deprecation Cleanup — open

- Catalogue deprecated/legacy paths by module
- Classify each as remove now / remove later / keep for compatibility
- Convert scattered comments into a tracked cleanup checklist

## Risks

- Refactoring large modules may accidentally break serialization or runtime flows.
- Plugin/runtime rewiring may reveal hidden coupling not visible from imports alone.
- Session persistence changes require careful test coverage to avoid data corruption.

## Non-Goals (for now)

- Full rewrite of session/storage architecture
- Replacing WebSocket/JSON-RPC transport
- Reworking the plugin concept itself
- Large-scale renaming of the whole package structure before behavior is stabilized

## Definition of Done

- docs reflect reality
- service imports are isolated and predictable
- plugin/runtime dependencies are explicit
- oversized modules are meaningfully decomposed
- persistence invariants are documented and better tested
- legacy paths are catalogued with a concrete removal strategy