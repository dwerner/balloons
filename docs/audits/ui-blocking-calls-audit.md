# UI Thread Blocking Calls Audit

This audit is no longer maintained as a current engineering document.

It focused on the removed Textual TUI era (`app.py`, `widgets/`, and UI-thread handlers), so most of its findings are not directly actionable in the current headless server + web UI architecture.

## Disposition

Discard as a current audit. If we need a performance/concurrency audit now, create a new one focused on:
- headless server startup/import behavior
- WebSocket/service-layer blocking calls
- storage and persistence latency
- web-client subscription/history loading behavior
- tool/process supervisor concurrency

## Historical note

The old audit may still contain isolated low-level findings that were independently valid at the time, but they should be rediscovered and revalidated in the current code rather than relied on through a TUI-era checklist.
