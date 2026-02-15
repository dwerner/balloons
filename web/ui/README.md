# Balloons Web UI

React/TypeScript web interface for Balloons that connects via WebSocket to a running TUI instance.

## Requirements

- [Bun](https://bun.sh/) >= 1.0
- Balloons TUI with WebSocket server enabled

## Quick Start

1. **Enable WebSocket server** in `~/.balloons/config.yaml`:
   ```yaml
   websocket:
     enabled: true
     host: localhost  # Use 0.0.0.0 for LAN access
     port: 8765
   ```

2. **Start the TUI** (in one terminal):
   ```bash
   python main.py
   ```

3. **Start the web UI** (in another terminal):
   ```bash
   cd web/ui
   bun install
   bun run dev
   ```

4. **Open** http://localhost:3000 in your browser.

## Features

- [x] WebSocket connection with auto-reconnect
- [x] Session list display with streaming indicators
- [x] Real-time streaming of LLM responses
- [x] Message submission with Enter key
- [x] Event-driven updates (session/turn changes)
- [x] Responsive mobile layout with slide-out sidebar

## Architecture

```
src/
  main.tsx    - Entry point, renders App
  App.tsx     - Main component with all functionality

../generated/
  balloons-client.ts  - Generated unified client
  client.ts           - Generated service clients
  types.ts            - Generated TypeScript types
```

The app uses the generated TypeScript clients from `web/generated/` which are
auto-generated from Python service decorators via `python -m codegen.generate_typescript`.

## Configuration

WebSocket URL defaults to `ws://localhost:8765`. Override via:

```javascript
window.BALLOONS_WS_URL = 'ws://your-server:port';
```

## Development

- `bun run dev` - Start dev server with hot reload
- `bun run typecheck` - Run TypeScript type checking

## Mobile Support

The UI is responsive and works on mobile devices:
- **Desktop (≥768px)**: Fixed sidebar with chat panel
- **Mobile (<768px)**: Hamburger menu with slide-out sidebar overlay

Access from your phone by binding to `0.0.0.0` in the websocket config and using your machine's LAN IP.

## Notes

This is an experimental UI. Future enhancements may include:

- Error boundaries for better crash recovery
- Virtualized scrolling for large conversations
- Authentication UI (TLS/JWT support exists in backend)
- Proper design system
- Keyboard shortcuts
- Context mode toggling (COPY/COMPRESS/DROP)
- Fork/merge UI

## Regenerating the TypeScript Client

If the Python WebSocket API changes, regenerate the client:

```bash
cd /path/to/balloons
python -m codegen.generate_typescript
```

This updates `web/generated/` from Python `@ws_expose` decorators.
