# Balloons Web UI

Minimal React/TypeScript web UI prototype for Balloons.

## Requirements

- Bun >= 1.0
- Balloons WebSocket server running on ws://localhost:8765

## Quick Start

```bash
# From this directory
bun install
bun run dev
```

Then open http://localhost:3000 in your browser.

## Features (Spike)

This is a proof-of-concept demonstrating:

- [x] WebSocket connection to Balloons backend
- [x] Session list display (from TreeStateService)
- [x] Turn display for selected session
- [x] Message submission (queued via QueueStateService)
- [x] Real-time streaming updates via event subscriptions

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

## Notes

This is a spike/prototype. For production:

- Add proper error boundaries
- Implement virtualized scrolling for large conversations
- Add authentication UI
- Style with a proper design system
- Add keyboard shortcuts
- Implement context mode toggling UI
