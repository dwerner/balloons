# Plan: Architecture Remediation

## Goals

Address the architectural issues identified in the codebase review while keeping the system functional during incremental refactors.

Primary goals:
- Reduce hidden coupling across service, plugin, and runtime layers
- Split oversized modules into clearer responsibilities
- Reconcile documentation with the current implementation
- Improve import hygiene and test isolation
- Create a staged migration path for legacy code and transitional patterns

## Key Problems To Fix

1. **Architecture docs are out of sync with reality**
   - `README.md` and `ARCHITECTURE.md` describe different systems/states.
   - TUI/headless/storage status is inconsistent.
   - The TUI and `:commands` are dead and unsupported, but many docs and comments still imply otherwise.

2. **`session.py` is overloaded**
   - Domain model, persistence, migration, dirty tracking, and compatibility logic are mixed together.

3. **`service/__init__.py` is too eager and creates import-time coupling**
   - Importing a single service can pull in auth/http dependencies.
   - This harms tests and modularity.

4. **Global service locator couples plugins to runtime state**
   - `get_session_manager_service()` / `set_session_manager_service()` hide dependencies.

5. **`SessionManagerService` is too large and too central**
   - Session lifecycle, stream orchestration, event routing, fork/merge workflows, and compatibility behavior are concentrated.

6. **Boundary between core/application/service layers is unclear**
   - Transport logic and orchestration logic are mixed.

7. **Incremental persistence is complex and high-risk**
   - Save/reorder/delete logic needs clearer invariants and better stress coverage.

8. **Legacy/deprecated paths are interleaved with current behavior**
   - Migration code and compatibility behavior remain inline in production modules.

## Guiding Principles

- Prefer **incremental refactors** over large rewrites.
- Preserve behavior first, then simplify internals.
- Keep runtime wiring explicit rather than global.
- Make package imports cheap and unsurprising.
- Separate **domain**, **application/orchestration**, and **transport** concerns.
- Create tests before or alongside refactors that reduce coupling.
- Avoid changing public import/runtime surfaces without characterization tests.
- Use failing or targeted tests to drive each code change.
- Make **one logical change at a time**.
- A logical change may include a few tightly related edits, but only if they implement a single intention (for example: moving one function, updating one module import surface, or rewriting one bounded doc section).
- After **every logical change**, run the smallest relevant test or validation before proceeding.
- Do not batch multiple unrelated behavioral changes into one step.
- After every large change or milestone, check session context usage.
- If session context exceeds 100,000 tokens or is trending too high for the next task, propose creating a fork with curated context before continuing.

## Proposed Workstreams

### Workstream 1: Documentation Reconciliation

**Status:** In progress — current-facing docs substantially reconciled; historical/stale doc cleanup still ongoing.

#### Deliverables
- Update `ARCHITECTURE.md` to reflect current reality
- Clarify current runtime architecture, transitional pieces, and future direction
- Move outdated/historical material into clearly labeled sections or archive docs

#### Tasks
- [x] Rewrite architecture overview around headless server + web UI
- [x] State explicitly that the TUI is dead and unsupported
- [x] State explicitly that `:commands` are dead and unsupported
- [~] Document current Rust-backed storage status accurately
- [~] Add explicit "current state" vs "transitional debt" sections
- [~] Remove or archive outdated references to TUI-first architecture and command-mode workflows

#### Success Criteria
- A new contributor can understand the actual runtime architecture from docs alone.

---

### Workstream 2: Import Hygiene and Service Package Cleanup

**Status:** Completed in fork and merged — lazy `service` re-exports now preserve runtime compatibility while reducing eager import coupling, covered by characterization tests.

#### Deliverables
- Make `service` submodule imports independent of unrelated optional features
- Reduce side effects in `service/__init__.py`
- Preserve existing runtime/public import behavior while refactoring internals

#### Test Strategy
- Add characterization tests for current package exports used by the server
- Add targeted import tests for specific submodules
- Only then change internals incrementally

#### Tasks
- [x] Audit all imports in `service/__init__.py`
- [x] Identify actual public import contracts relied on by runtime code
- [x] Add characterization tests for `from service import ...` compatibility
- [x] Add targeted import tests for isolated service submodules
- [x] Stop eagerly importing optional auth/http modules from package init only when compatibility is preserved
- [x] Keep `service/__init__.py` minimal or convert it to safe re-exports only
- [~] Update tests/import sites to import concrete modules where appropriate

#### Success Criteria
- Importing `service.goal_tree_state_service` does not require unrelated dependencies.
- Existing server/runtime imports from `service` continue to work.
- Tests for one service do not fail due to package-level eager imports.

---

### Workstream 3: Remove Global Service Locator from Plugin Runtime

**Status:** Completed in fork and merged for active plugin/runtime eventing paths — explicit event-emitter wiring replaced active global locator usage.

#### Deliverables
- Replace implicit runtime lookups with explicit dependency injection

#### Status
- Completed for active runtime paths. The headless/plugin runtime now uses explicit event-emitter wiring instead of the global locator. Legacy locator exports remain in `service/__init__.py` as deprecated compatibility surface pending any future import-surface cleanup.

#### Tasks
- [x] Identify all plugin/runtime call paths using `get_session_manager_service()`
- [x] Introduce explicit runtime/service references where needed
- [x] Keep a compatibility shim temporarily if necessary
- [x] Deprecate and later remove service locator fallback

#### Success Criteria
- Plugin execution/event emission works without relying on module-global service state.

---

### Workstream 4: Clarify Layer Boundaries

#### Deliverables
- Establish explicit architectural vocabulary and code placement rules

#### Tasks
- [ ] Define `core` as domain/infrastructure-neutral logic
- [ ] Define an application/orchestration layer for workflows
- [ ] Narrow `service` toward transport adapters and API exposure
- [ ] Identify existing code that should move from service to orchestration

#### Success Criteria
- New workflow logic has a clear place to live.
- `service` becomes thinner over time.

---

### Workstream 5: Break Up `session.py`

#### Deliverables
- Smaller modules with clearer responsibilities around session entity and persistence

#### Candidate target split
- `session.py` or `core/session_entity.py` — public session model/entity
- `core/session_persistence.py` — save/load/repository concerns
- `core/session_serialization.py` — wire/storage conversions
- `core/session_migration.py` — legacy compatibility/migration helpers
- `core/session_dirty_state.py` — dirty tracking helpers

#### Tasks
- [ ] Identify cohesive sections in `session.py`
- [ ] Extract low-risk helpers first (serialization/migration)
- [ ] Add tests around extracted behaviors
- [ ] Keep public API compatibility where possible during transition

#### Success Criteria
- `session.py` is substantially smaller and easier to reason about.

---

### Workstream 6: Break Up `SessionManagerService`

#### Deliverables
- Move orchestration logic into smaller collaborators

#### Candidate target split
- `service/session_manager_service.py` — WebSocket-exposed façade
- `core/session_lifecycle.py` or `app/session_lifecycle.py`
- `core/stream_orchestrator.py` or `app/stream_orchestrator.py`
- `core/fork_merge_workflows.py` or `app/fork_merge_workflows.py`
- `core/session_event_router.py` or `app/session_event_router.py`

#### Tasks
- [ ] Identify the main workflow clusters in the service
- [ ] Extract pure orchestration helpers with tests
- [ ] Leave RPC surface stable while moving internals out

#### Success Criteria
- `SessionManagerService` becomes a thin façade rather than a god object.

---

### Workstream 7: Persistence Invariants and Stress Testing

#### Deliverables
- Better confidence in incremental save correctness

#### Tasks
- [ ] Document save invariants for sessions/turns/order/deletes
- [ ] Add stress tests for concurrent or repeated incremental save scenarios
- [ ] Validate behavior under rapid turn mutation/reorder/delete patterns
- [ ] Consider whether append-oriented semantics can simplify the model long-term

#### Success Criteria
- Persistence behavior is documented and tested for race-prone scenarios.

---

### Workstream 8: Legacy and Deprecation Cleanup

#### Deliverables
- Explicit inventory of transitional code

#### Tasks
- [ ] Catalogue deprecated/legacy paths by module
- [ ] Classify each as remove now / remove later / keep for compatibility
- [ ] Convert scattered comments into a tracked cleanup checklist

#### Success Criteria
- Legacy debt is managed intentionally rather than accumulating silently.

## Execution Protocol

For every workstream, use this loop:

1. Pick exactly one logical change.
2. Define the intended behavior being preserved or introduced.
3. Identify the smallest relevant test or validation for that logical change.
4. Run the test first when writing a new characterization/regression test, or immediately after the change for doc-only updates.
5. Make the tightly related edits needed for that one logical change.
6. Run the targeted test/validation.
7. Only continue if it passes.
8. If the completed work was a large change or milestone, check session context usage before continuing.
9. If context is above 100,000 tokens or likely to impede the next task, propose a fork with curated context.
10. Then choose the next logical change.

Examples of acceptable validations:
- targeted `pytest` invocation for the touched behavior
- import smoke test for package/import changes
- doc grep/consistency check for documentation-only changes
- narrow runtime smoke test for startup/import compatibility
- `session_info` check after large changes or milestones

Examples of a single logical change:
- moving one helper function from a large module into a new helper module
- changing one package import surface while preserving compatibility
- rewriting one architecture section in one document
- extracting one workflow cluster from a service into a collaborator

## Reorganized Substantive Workstreams

### Chunk A: Product Surface and Documentation Alignment
- Finish Workstream 1 documentation reconciliation
- Complete current-vs-historical doc cleanup
- Continue Workstream 8 only for documentation-facing legacy inventory

### Chunk B: Service Boundary Cleanup (Completed core milestones)
- Workstream 2 completed: `service/__init__.py` import hygiene behind tests
- Workstream 3 completed: active plugin/runtime service-locator removal
- Remaining follow-up: remove residual compatibility shims only when proven unused

### Chunk C: Architectural Boundary Definition
- Continue Workstream 4 by defining clear placement rules for `core`, orchestration/application workflow code, and `service`
- Identify candidate module moves before changing implementation structure broadly

### Chunk D: Stateful Core Decomposition
- Workstream 5: split `session.py`
- Workstream 6: split `SessionManagerService`
- Coordinate these together conceptually, but execute as one logical change at a time with tests after each extraction

### Chunk E: Persistence and Reliability Hardening
- Workstream 7: document invariants and add stress/characterization coverage
- Continue Workstream 8 for runtime/code legacy classification once invariants and ownership are clearer

## Recommended Execution Order

### Phase 1: Finish safe structural cleanup
1. Finish current-facing and historical documentation reconciliation
   - one logical doc change at a time
   - validate after each change
2. Reflect merged work accurately in the plan and supporting docs
   - keep workstream status current

### Phase 2: Define architecture before broad refactors
3. Clarify layer boundaries and placement rules
   - documentation/design first
   - one module family or boundary rule at a time
4. Identify residual locator/import compatibility shims that can later be removed
   - no speculative cleanup without evidence/tests

### Phase 3: Decompose the core stateful modules
5. Split `session.py`
   - one extraction seam at a time
   - test after each extraction
6. Split `SessionManagerService`
   - one workflow cluster at a time
   - test after each extraction

### Phase 4: Reliability + debt retirement
7. Persistence invariants and stress tests
   - one invariant/test case at a time
8. Runtime/code legacy cleanup pass
   - one dead path or compatibility cleanup at a time
   - validate after each cleanup

## Immediate Next Steps

1. Start with one documentation file change
   - Prefer `ARCHITECTURE.md`
   - Update one bounded section only
   - Run a targeted validation after that single edit

2. Then add one characterization test around current package/runtime behavior
   - Especially `from service import ...` compatibility used by the server
   - Run that test immediately after adding it

3. Only then make one incremental runtime refactor behind that test
   - Preserve public behavior first
   - Re-run the same targeted test immediately after the change

4. Repeat the one-change / one-test loop
   - No grouped refactors
   - No unvalidated follow-up edits

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

This effort is successful when:
- docs reflect reality
- service imports are isolated and predictable
- plugin/runtime dependencies are explicit
- oversized modules are meaningfully decomposed
- persistence invariants are documented and better tested
- legacy paths are catalogued with a concrete removal strategy
