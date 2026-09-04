/**
 * Server-slot selection and URL construction.
 *
 * The UI can connect to one of two backend slots (A/B), each with a WebSocket
 * port and an auth (HTTP) port. Extracted from App.tsx so the connection
 * wiring has a single, testable home.
 */

import { getToken } from './auth';

export type ServerSlot = 'A' | 'B';

export const SLOT_PORTS: Record<ServerSlot, number> = { A: 8700, B: 8710 };

// Auth server ports - HTTP server for login/auth (WS port + 1)
export const AUTH_PORTS: Record<ServerSlot, number> = { A: 8701, B: 8711 };

/** Check if TLS should be used (infer from page protocol only). */
export function shouldUseTls(): boolean {
  if (typeof window === 'undefined') return false;
  // Only use TLS if served over HTTPS - no other magic
  return window.location.protocol === 'https:';
}

/** Get WebSocket URL for a given slot (with JWT token if available). */
export function getWsUrlForSlot(slot: ServerSlot): string {
  // Check for explicit override
  if (typeof window !== 'undefined' && (window as any).BALLOONS_WS_URL) {
    return (window as any).BALLOONS_WS_URL;
  }

  const useTls = shouldUseTls();
  const wsProtocol = useTls ? 'wss' : 'ws';

  // Check URL query param: ?ws=host:port (overrides slot)
  if (typeof window !== 'undefined') {
    const params = new URLSearchParams(window.location.search);
    const wsParam = params.get('ws');
    if (wsParam) {
      const token = getToken();
      const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
      return `${wsProtocol}://${wsParam}${tokenParam}`;
    }

    // Use slot's port with JWT token
    const port = SLOT_PORTS[slot];
    const token = getToken();
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
    return `${wsProtocol}://${window.location.hostname}:${port}${tokenParam}`;
  }

  return `${wsProtocol}://localhost:${SLOT_PORTS[slot]}`;
}

/** Get auth server URL for a given slot. */
export function getAuthUrlForSlot(slot: ServerSlot): string {
  const useTls = shouldUseTls();
  const httpProtocol = useTls ? 'https' : 'http';
  const port = AUTH_PORTS[slot];

  if (typeof window !== 'undefined') {
    return `${httpProtocol}://${window.location.hostname}:${port}`;
  }
  return `${httpProtocol}://localhost:${port}`;
}

/** Get initial slot from localStorage, default to A. */
export function getInitialSlot(): ServerSlot {
  if (typeof window !== 'undefined') {
    const stored = localStorage.getItem('balloons:server-slot');
    if (stored === 'A' || stored === 'B') {
      return stored;
    }
  }
  return 'A';
}
