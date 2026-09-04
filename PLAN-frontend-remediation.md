# Plan: Frontend Remediation (web/ui)

Companion to [PLAN-architecture-remediation.md](PLAN-architecture-remediation.md) (backend). This plan covers the React web UI (`web/ui/`, ~47.5k LOC TS/TSX + ~25k LOC CSS) and the generated client contract (`web/generated/`).

## Status (branch `feat/frontend-remediation`)

Completed and verified (typecheck + build + tests green at each commit):

- **WS0 — build gate**: restored the regressed `create_watcher_session` backend method (the UI "Watch session" action was calling a method that no longer existed); deleted dead `SessionDataContext`; wired `tsc --noEmit` into the dev-server watch loop.
- **WS1 — dead-code purge**: removed ~2.9k lines (dead turn components, ChessTab, DebugPaneDemo, LinkSessionModal, orphaned `.collapsible*` CSS = Bug #17); routed all debug `console.log` through `debugLog`.
- **WS2 — test + lint pipeline**: happy-dom + jest-dom preload, `bun test` (52 tests, was 9), ESLint flat config (0 errors), tests included in typecheck. Fixed all 8 `react-hooks/rules-of-hooks` violations (hooks after early returns). Extracted `utils/sessionGrouping.ts` + 14 characterization tests pinning tree-grouping behaviour (guards WS5 / Bugs #7/#23).
- **WS3 — partial**: extracted `utils/serverSlots.ts` and `utils/turnTransforms.ts`; removed dead `MessageInput`. **App.tsx 4757 → 3696 lines.**
- **WS5 — contract fixes**: real `is_pinned` in session events via a server-side pinned cache (Bug #23); generated client now calls qualified RPC names (Bug #11), collision warnings downgraded.

Remaining (larger / need live-app verification — left at a clean checkpoint rather than risk regressions):

- **WS3 (rest)**: move presentational chrome (`MobileHeader`, `MainContentHeader`, `SidebarContent`, `SessionListItem`) out of `AppContent`.
- **WS4 — single source of truth**: introduce a store to retire the child→parent→sibling turn round-trip and the parallel `TurnInfo`/`SessionDataTurn` state (Bugs #13, #18, #22, #9). Highest bug leverage; needs the `useSessionData` characterization test written first.
- **WS6 — theme tokens**: migrate hardcoded hex in `cards.css`/`styles.css` to CSS custom properties (Bug #6). Best done with visual QA.
- **WS7 — caching + routing**: IndexedDB cache (Bug #5), lazy tree turn-loading (Bug #4), implement the URL-routing spec.
- **WS8 — polish**: tool-error single-line rendering (Bug #21), rename-while-streaming (Bug #16 — not gated in code; needs live repro).

## Review Snapshot

**Stack**: React 19 + TypeScript (strict), Bun bundler dev server, generated WebSocket JSON-RPC client, no router, no state library, no linter, no working test pipeline.

### Key Problems (ranked by impact)

1. **Typecheck is currently failing — and nothing notices.**
   - `src/App.tsx:3113` calls `client.sessions.createWatcherSession()`, which exists neither in the generated client nor anywhere in the backend (the real method is `startWatchingSession`). The "Watch session" menu action is broken at runtime.
   - `src/contexts/SessionDataContext.tsx` imports `../lib/SessionDataManager`, a module that no longer exists (9 errors).
   - The dev server uses `Bun.build` (no typecheck), so the app still runs; `bun run typecheck`/`build` is not wired into any loop or CI.

2. **`App.tsx` is a 4,757-line god component** (40 `useState`, ~131 hook calls, ~50 handlers, 94 commits of churn). It holds: connection lifecycle + slot switching, all global event subscriptions, session CRUD, fork/merge/link/conclude flows, composer/draft/voice/image handling, review-modal state, and layout chrome (`MobileHeader`, `MainContentHeader`, `SidebarContent`, `SessionListItem`). It also contains ~600 lines of **dead** turn-rendering components (`Turn`, `TextTurn`, `ToolUseTurn`, `SystemTurn`, `SimpleTurn`, `Collapsible`, `StreamingToolUseDisplay`, `FormattedToolInput`) with zero references.

3. **Inverted, duplicated data flow.** `StreamingTurnsView` (a child) owns session data via `useSessionData` and pushes it *up* to `App` through 6 callbacks (`onTurnsChange`, `onStreamingProgressChange`, `onLoadingChange`, `onHistoryStateChange`, …). `App` stores **two parallel representations** (`turns: TurnInfo[]` and `rawTurns: SessionDataTurn[]`, bridged by conversion shims) plus copies of streaming/loading/history state, then redistributes to siblings (tree, status bar, minimap, ContextTabView). The in-code "LEGACY TURN HANDLERS DISABLED … same text gets applied twice" comment is a scar from this design. This is the shared root cause of Bugs #13, #18, #22 and a contributor to #4 and #9.

4. **Pin/date state is a client-side patch over a server contract gap.** `sessionUpdated` events omit `isPinned`; `App` hand-patches it ("Preserve local isPinned state"). Date grouping sorts by `lastModified` instead of a stable `modifiedAt`. Root cause of Bugs #23 and #7, entangled with #18.

5. **RPC surface drift (Bug #11).** Duplicate method names across services (`getSession`, `clear`, `getActiveSessionId`, `getStreamingSessions`) with no namespacing; the generated client resolves collisions arbitrarily, and there is no CI check that `web/generated/` matches the backend `@ws_expose` surface (the `createWatcherSession` breakage is exactly this failure mode).

6. **CSS has no token discipline.** 43 CSS files; two global sheets (`styles.css` 2,712 lines / 325 top-level classes; `cards.css` 3,459 lines with **400 hardcoded hex colors** vs 749 `var()` uses). Hardcoded colors are the direct cause of Bug #6 (turn types ignoring theme). Orphaned SimpleTurnsView styles remain (Bug #17).

7. **Test pipeline is non-functional.** 5 test files with mixed runners: some `bun:test` (9 pass / 1 fail / 1 error), others import `@testing-library/react`, which is not installed. No `test` script, no DOM environment, tsconfig excludes tests from typecheck. The most fragile logic — `useSessionData` delta accumulation, tree grouping/sorting — has zero coverage.

8. **Dead code and orphans**: `SessionDataContext` (+ missing `lib/SessionDataManager`), `ChessTab` (zero references), `DebugPaneDemo`, `LinkSessionModal` directory (removed per comment), commented-out kanban imports, `DebugPane.test.tsx.disabled`.

9. **No router, no cache.** URL routing is designed (`docs/specs/url-routing.md`) but unimplemented; deep links, tab/session state, and Bug #5 (caching) all wait on this. 55 stray `console.log`s coexist with the `debugLog` system.

### Bug Mapping

| Bug | Root cause area | Fixed by |
|-----|-----------------|----------|
| #4 tree shows empty when not loaded | no lazy turn loading on expand; duplicated turn state | WS4, WS7 |
| #5 no local caching | no cache layer | WS7 |
| #6 turn types ignore theme | hardcoded hex in cards.css | WS6 |
| #7 "Today" only last-loaded session | client sorts by `lastModified`, not stored `modifiedAt` | WS5 |
| #9 fork shows full parent tree | tree reads stale/duplicated session state | WS4 |
| #11 RPC name collisions | no namespacing in codegen/dispatch | WS5 |
| #13 status bar tokens zero / no streaming state | progress round-trips child→App→status bar | WS4 |
| #14 tool cards fixed-height scroll | cards.css layout | WS6/WS8 |
| #16 rename blocked while streaming | status bar composer coupling | WS8 |
| #17 SimpleTurnsView CSS remnants | dead CSS | WS1 |
| #18 tokens drop to zero on pin | pin flow refetches/overwrites session state | WS4, WS5 |
| #21 tool errors not rendered as error turns | turn rendering | WS8 |
| #22 double pulsing dots | duplicate streaming indicators from dual ownership | WS4 |
| #23 pinned sessions fall into date groups | `isPinned` missing from server events | WS5 |
| #3 rotation axis, #6, #14, #21, #22 | cosmetic/rendering | WS6/WS8 |

(Bug #24 is backend-only; out of scope here.)

## Guiding Principles

- **Restore the feedback loop first**: a failing typecheck that nobody runs is worse than no typecheck. Gates before refactors.
- **Characterization tests before behavior-preserving refactors** of data flow.
- **One source of truth per datum**; data flows down, events flow up.
- Prefer a **small store + contexts** over prop-drilling; avoid framework-scale rewrites (no Next.js, no Redux migration).
- Fix **contracts (codegen)** before patching symptoms in components.
- Delete dead code immediately; it inflates every future review.

## Workstreams

### WS0: Restore the build gate — immediate, low risk
- Delete `src/contexts/SessionDataContext.tsx` (dead; references removed `lib/SessionDataManager`).
- Fix `App.tsx` watcher action to call `client.sessions.startWatchingSession(...)` (or remove the menu item if watcher creation UX is being redesigned).
- Add `typecheck` to the dev-server build step and to CI; the dev server should surface type errors on save.
- **Done when**: `bun run typecheck` passes and a deliberately broken type fails the dev build.

### WS1: Dead-code purge — low risk, high clarity
- Remove: dead turn components in `App.tsx` (~600 lines), `ChessTab`, `DebugPaneDemo`, `LinkSessionModal/`, kanban comment imports, `DebugPane.test.tsx.disabled`, orphaned SimpleTurnsView CSS in `styles.css` (**Bug #17**).
- Sweep `console.log` (55) into `debugLog` or delete.
- **Done when**: `grep` for removed symbols is clean; typecheck passes.

### WS2: Real test + lint pipeline — enabler for everything after
- Add `bun test` script with a DOM environment (`happy-dom` preload) or install `@testing-library/react` + a runner; port the 5 existing test files to one runner.
- Add ESLint (typescript-eslint + react-hooks rules; `react-hooks/exhaustive-deps` as warn initially).
- Include tests in typecheck (drop the tsconfig `exclude`).
- Write **characterization tests** for `useSessionData` (delta accumulation, reorder, history chunks) and tree grouping (pinned/date/watcher) before WS4/WS5 change them.
- **Done when**: `bun test` green in CI; lint runs with a ratchet (no new warnings).

### WS3: Decompose `App.tsx` — behavior-preserving
Extract, in order of independence:
1. `useConnection(serverSlot)` — client lifecycle, reconnect, slot persistence.
2. `useSessions()` — session list + `sessionAdded/Updated/Removed/Pinned` handlers.
3. `useSessionSelection()` — select/load race handling, draft save/restore.
4. `useComposer()` — input, drafts, voice, image attachments, send actions.
5. `useReviewModal()`, `useInputAreaResize()`.
6. Move chrome (`MobileHeader`, `MainContentHeader`, `SidebarContent`, `SessionListItem`) into `components/layout/`.
- Target: `App.tsx` < ~400 lines of composition.
- **Done when**: same behavior, App.tsx under target size, no new state duplication introduced.

### WS4: Single source of truth for session data — highest bug-fix leverage
- Introduce a small store (decision point: zustand vs hand-rolled external store; avoid reviving the abandoned `SessionDataManager` unless it earns its keep) owning: turns (`SessionDataTurn[]` only), streaming progress, loading/history state, per-session cache.
- Retire the `TurnInfo` conversion shims in `App.tsx`; pick one view model.
- Remove the child→parent→sibling round-trip: `StreamingTurnsView` subscribes via the store; status bar, minimap, tree, ContextTabView read from it directly.
- Fixes **Bugs #13, #18, #22, #9**, enables **#4**.
- **Done when**: `App.tsx` holds no turn/streaming state; duplication bugs cannot recur (guarded by WS2 characterization tests).

### WS5: Contract fixes via codegen — server-assisted
- Include `isPinned` and a stable `modifiedAt` in `SessionInfo` and all session events; drop the client-side "preserve local pin" patch → fixes **Bugs #23, #7**, hardens **#18**.
- Namespace RPC methods (`SessionManagerService.getActiveSessionId`) in dispatch + generated client (**Bug #11**); keep an alias table during transition.
- CI check: regenerate `web/generated/` and fail on diff (prevents `createWatcherSession`-class drift).
- **Done when**: no collision warnings on `headless.py` startup; generated-client drift fails CI.

### WS6: Theme token system
- Audit `cards.css` (400 hex) + `styles.css` (194 hex) into CSS custom properties with a documented token set; per-turn-type colors reference tokens only.
- Add stylelint rule: no raw hex outside the token definition file (ratchet).
- Fixes **Bug #6**; makes custom themes (PreferencesContext) actually universal. Also rework tool-card layout for **Bug #14** (collapsible, no internal scroll) and **Bug #3** (rotation axis).
- **Done when**: switching themes visibly restyles every turn type; lint rule enforced.

### WS7: Caching, lazy loading, routing
- IndexedDB cache: session list + recent-session turns; render cache-first, refresh on events (**Bug #5**).
- Lazy-load turns when expanding a session in the tree (**Bug #4**).
- Implement the existing URL-routing spec (hash-based): session/turn/tab deep links; replaces scattered localStorage state (`balloons:selected-session`, tab state).
- **Done when**: cold open renders cached sessions instantly; a session URL deep-links from a clean tab.

### WS8: Turn rendering & status bar polish — small, user-visible
- Tool-use errors as compact single-line error turns (**Bug #21**).
- Status bar: editable session name during streaming (**Bug #16**), live streaming indicator wired to WS4 store.
- **Done when**: listed bugs closed with a UI smoke test each.

## Sequencing

```
WS0 ──► WS1 ──► WS2 ──┬─► WS3 ──► WS4 ──► WS7
                      ├─► WS5 (parallel; WS4 depends on its isPinned/modifiedAt part)
                      └─► WS6/WS8 (parallel, low coupling)
```

Rough effort: WS0–WS1 days; WS2 ~week; WS3 ~week; WS4 1–2 weeks; WS5 ~week (crosses backend); WS6 ~week; WS7 1–2 weeks; WS8 days.

## Risks

- WS4 touches the streaming hot path — WS2 characterization tests are a hard prerequisite.
- WS5 changes the wire contract; old clients break — ship alias table first.
- Store adoption (WS4) can leak into a big-bang rewrite; keep components reading via selectors, migrate view-by-view.
- New deps (happy-dom, eslint, zustand?) — `bunfig.toml` enforces a 15-day minimum package age; plan around it.

## Non-Goals

- No framework migration (stay React + Bun bundler).
- No Monaco/virtualization rewrites; perf work limited to what WS4 removes (duplicate renders).
- No redesign of the plugin/tab model.

## Definition of Done

- `typecheck`, `lint`, `bun test` green in CI and in the dev loop.
- `App.tsx` < 400 lines; no duplicated turn/streaming state.
- Generated client verified against backend in CI; no RPC name collisions.
- Theme tokens cover all turn types; no raw hex outside tokens.
- Bugs #4–#7, #9, #13, #14, #16–#18, #21–#23 closed or reclassified.