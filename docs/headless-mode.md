# Headless Mode

Balloons can run without the TUI as a pure WebSocket server. This enables:
- Server deployments (Docker, systemd)
- React/web frontend connections
- A/B testing of code changes (stable vs experimental instances)

## Quick Start

```bash
# Start headless server on default port (from config)
python headless.py

# Start on specific port
python headless.py --port 8766

# List options
python headless.py --help
```

## Server Management

Use `balloons-server.py` to manage headless instances:

```bash
# Start/stop by slot
python balloons-server.py start       # Slot A (port 8765)
python balloons-server.py start -b    # Slot B (port 8766)
python balloons-server.py stop -b     # Stop slot B
python balloons-server.py restart -b  # Restart slot B

# List running instances
python balloons-server.py list

# Custom port
python balloons-server.py start --port 9000
```

## A/B Slot Architecture

Two fixed slots for stable/experimental development:

| Slot | Port | Purpose |
|------|------|---------|
| A | 8765 | Primary/stable instance |
| B | 8766 | Secondary/experimental instance |

### Workflow for Self-Modification

1. **Slot A** runs stable code (the version currently in memory)
2. Make code changes to source files
3. Start **Slot B** with new code: `python balloons-server.py start -b`
4. Test Slot B in React UI (toggle to "B" in sidebar)
5. If changes work: restart Slot A to pick up changes
6. If changes break: Slot A still works, fix and retry on B

The key insight: **modifying source files doesn't affect running servers** until they restart. This provides a safety net for self-modifying code.

### Promoting Changes

When experimental changes are verified:
```bash
python balloons-server.py restart    # Restart Slot A with new code
```

Now both slots run the same (new) code. Slot B becomes available for the next experiment.

## React Frontend Integration

The React UI has a slot toggle in the sidebar:
- Shows current slot (A or B) with port number
- Click to switch between slots
- Persisted to localStorage (`balloons:server-slot`)
- Automatic WebSocket reconnection on switch

## Services Exposed

Both TUI and headless mode expose identical WebSocket APIs:

| Service | Purpose |
|---------|---------|
| SessionManagerService | Session lifecycle, streaming, fork/merge |
| SessionDataService | Session data events, subscription-based streaming |
| TaskStateService | LLM streaming events |
| GoalTreeStateService | Goal/plan/todo management |
| QueueStateService | Message queue management |
| ImageService | Image handling |
| SoundService | Sound state (no playback in headless) |
| DebugLogService | Debug log access |

## Configuration

WebSocket settings in `~/.balloons/config.yaml`:

```yaml
websocket:
  enabled: true      # TUI only starts WS server if true
  host: "0.0.0.0"    # Bind address
  port: 8765         # Default port
  tls:
    enabled: false
    cert_path: ""
    key_path: ""
  jwt:
    enabled: false
    secret: ""
```

Note: `headless.py` ignores `websocket.enabled` and always starts the server.

## Files

- `headless.py` - Headless server entry point
- `balloons-server.py` - Server management script
- `~/.balloons/run/headless-{port}.pid` - PID files for running instances
