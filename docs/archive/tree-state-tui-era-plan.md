# TreeState TUI-Era Plan (Archived)

This document was archived during the architecture remediation pass because it is tightly coupled to the removed Textual TUI architecture (`widgets/`, tree views, `app.py`, keyboard shortcuts, and observer-driven UI wiring).

Why archived instead of rewritten:
- the implementation path is no longer the supported product path
- the remaining useful ideas are either already reflected in current service/runtime code or superseded by headless/web architecture docs
- keeping the original detailed plan in a current-facing location was more misleading than helpful

Original source: `docs/archived-plans/PLAN-tree-state.md`
Archive action: condensed and replaced with this archive note

Potentially still-useful themes to recover later if needed:
- separating tree/session state from rendering concerns
- observer/event patterns for derived views
- reducing duplicated in-memory state
