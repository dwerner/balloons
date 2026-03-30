# Streaming Mode

Streaming in Balloons constrains some operations while a turn is actively running, but the old command-mode workflow is removed.

## Current state

- The supported product surface is the **headless server + web UI** architecture.
- The old Textual TUI and `:commands` workflow are removed and unsupported.
- Current clients should handle streaming-safe vs streaming-unsafe actions through their own UI and service interactions rather than command syntax.

## Still-relevant concepts

The useful surviving ideas from the old document are:

- some actions are safe during active streaming and some should be deferred
- queueing, cancellation, and input-required states need clear client behavior
- clients should surface streaming state so users understand what actions are currently available

## Documentation note

This file no longer documents command syntax because that interface has been removed.
Refer to current architecture and feature docs for supported streaming behavior.
