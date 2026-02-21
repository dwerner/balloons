/**
 * Shared debug logger for the web UI
 *
 * Logs to browser console and optionally sends to the TUI debug pane via WebSocket.
 *
 * Usage:
 *   import { debugLog, setDebugClient } from '../utils/debugLog';
 *
 *   // In your main App, set the client when connected:
 *   setDebugClient(client);
 *
 *   // Then use debugLog anywhere:
 *   debugLog('MyComponent', 'Something happened', { data: 123 });
 */

import type { BalloonsClient } from '../../../generated/balloons-client';

// Module-level client reference
let _client: BalloonsClient | null = null;

/**
 * Set the BalloonsClient for WebSocket logging.
 * Call this when the client connects, and pass null when it disconnects.
 */
export function setDebugClient(client: BalloonsClient | null): void {
  _client = client;
}

/**
 * Log a debug message.
 *
 * @param category - Short category name (e.g., 'SessionTreeView', 'App')
 * @param message - The log message
 * @param data - Optional data to include
 */
export function debugLog(
  category: string,
  message: string,
  data?: Record<string, unknown>
): void {
  // Always log to console with timestamp
  const timestamp = new Date().toISOString().split('T')[1]?.slice(0, 12) ?? '';
  console.log(`[${timestamp}][${category}]`, message, data ?? '');

  // Also send to TUI if connected
  if (_client?.isConnected) {
    _client.debugLog.info(message, `web.${category}`, '', data ?? null).catch(() => {
      // Silently ignore WebSocket errors
    });
  }
}

// Log immediately when this module loads
console.log('[debugLog] Module loaded, client:', _client ? 'set' : 'null');

/**
 * Create a scoped logger for a specific component/module.
 *
 * Usage:
 *   const log = createLogger('MyComponent');
 *   log('Something happened', { data: 123 });
 */
export function createLogger(category: string) {
  return (message: string, data?: Record<string, unknown>) => {
    debugLog(category, message, data);
  };
}
