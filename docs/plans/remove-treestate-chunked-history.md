# Remove TreeState / Chunked History Migration Notes

## Current usefulness

This document mixes two different things:
- still-relevant migration ideas around direct storage access, chunked history loading, and reducing redundant in-memory state
- obsolete TUI-era implementation details and execution notes

Because of that, the original long-form plan was no longer a good current-facing document.

## Retained takeaways

The still-useful architectural ideas are:
- prefer direct storage reads over redundant in-memory TreeState copies where practical
- support incremental/chunked history loading for large sessions
- keep runtime streaming state separate from persisted history state
- document ownership of session metadata, turn history, and subscription/event responsibilities clearly

## What to do instead now

If this workstream continues, create a fresh, test-driven plan scoped to the current headless/web architecture that references the current modules and service surfaces directly.

That new plan should cover:
- current `SessionDataService` responsibilities
- current runtime state ownership
- current storage/query interfaces
- characterization tests before behavioral changes
- migration steps that do not depend on removed TUI codepaths

## Disposition

The previous detailed migration plan has been intentionally condensed because too much of it was tied to removed architecture and stale execution context.
