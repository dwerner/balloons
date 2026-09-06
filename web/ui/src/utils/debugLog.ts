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
  // Single gate for both outputs: when debug logging is disabled, debugLog()
  // is a no-op -- nothing is printed AND nothing goes on the wire.
  //
  // The socket send used to be unconditional ("Always send to server if
  // connected"), so toggling this setting silenced the devtools console while
  // every log line still cost a frame on the WebSocket. On a single
  // "run ls and stop" session that was 866 notifications / 239 KB = 70% of all
  // traffic, the largest category by far (see tools/wslog).
  //
  // Accepted consequence: the server-side debug pane (LogsTab, which reads the
  // 'client' category buffer) only shows web-UI logs while debug is enabled.
  // Server-side logs and this pane's read/control RPCs are unaffected.
  //
  // The gate lives here rather than at call sites on purpose: callers still
  // evaluate their arguments, so disabling saves wire bytes but not the cost of
  // building the message. Scattering `if (isDebugEnabled())` guards across the
  // UI was judged not worth it.
  if (!_debugEnabled) return;

  const timestamp = new Date().toISOString().split('T')[1]?.slice(0, 12) ?? '';
  console.log(`[${timestamp}][${category}]`, message, data ?? '');

  // Send to the 'client' category (which has a dedicated buffer on the server),
  // carrying the component category in details for filtering.
  //
  // debugLog.info is a fire-and-forget call (JSON-RPC notification): it sends
  // with no "id", the server never replies, and it returns void. The client
  // helper already swallows send errors, so there is nothing to await or catch
  // here. This removes a full request/response round-trip per log line, which
  // previously dominated UI traffic (see tools/wslog analysis).
  if (_client?.isConnected) {
    _client.debugLog.info(message, 'client', '', { ...(data ?? {}), source: 'web', component: category });
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
