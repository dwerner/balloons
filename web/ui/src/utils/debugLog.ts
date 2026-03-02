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

// Debug enabled state - persisted to localStorage
let _debugEnabled = typeof localStorage !== 'undefined'
  ? localStorage.getItem('balloons:debug-enabled') === 'true'
  : false;

/**
 * Check if debug logging is enabled
 */
export function isDebugEnabled(): boolean {
  return _debugEnabled;
}

/**
 * Enable or disable debug logging
 */
export function setDebugEnabled(enabled: boolean): void {
  _debugEnabled = enabled;
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem('balloons:debug-enabled', String(enabled));
  }
}

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
  // Console logging is gated by _debugEnabled
  if (_debugEnabled) {
    const timestamp = new Date().toISOString().split('T')[1]?.slice(0, 12) ?? '';
    console.log(`[${timestamp}][${category}]`, message, data ?? '');
  }

  // Always send to server if connected (for server-side debugging)
  if (_client?.isConnected) {
    _client.debugLog.info(message, `web.${category}`, '', data ?? null).catch(() => {
      // Silently ignore WebSocket errors
    });
  }
}

// Log immediately when this module loads
if (_debugEnabled) {
  console.log('[debugLog] Module loaded, client:', _client ? 'set' : 'null');
}

/**
 * Create a scoped logger for a specific component/module.
 *
 * Usage:
 *   const log = createLogger('MyComponent');
 *   log('Something happened', { data: 123 });
 */
export function createLogger(category: string) {
  return (message: string, data?: unknown) => {
    // Convert to Record<string, unknown> if it's an object, otherwise wrap it
    const dataRecord = data === undefined ? undefined
      : (typeof data === 'object' && data !== null ? data as Record<string, unknown>
        : { value: data });
    debugLog(category, message, dataRecord);
  };
}
