# Delete Turns TUI-Era Plan (Archived)

This document was archived during the architecture remediation pass because it described a removed TUI-specific interaction model (`widgets/context_tree.py`, Textual messages, keyboard handlers, and `app.py` UI refresh flows).

Why archived instead of rewritten:
- the user interaction and implementation path are no longer current
- any still-relevant work should be re-specified against the current headless/web service surfaces
- preserving the old detailed steps in a current docs area created confusion

Original source: `docs/archived-plans/PLAN-delete-turns.md`
Archive action: condensed and replaced with this archive note

If revisited, a fresh doc should describe:
- current delete-turn behavior/product expectations
- service/API surfaces involved
- persistence and fork/merge edge cases under the current architecture
