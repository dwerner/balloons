/**
 * Tests for the debugLog gate.
 *
 * Pins the invariant that the `_debugEnabled` flag governs BOTH outputs:
 * when debug logging is disabled, debugLog() emits nothing to the console and
 * sends NOTHING on the WebSocket. Previously only the console was gated while
 * the socket send was unconditional, which made the debug setting cosmetic and
 * let UI log lines account for ~70% of capture traffic (see tools/wslog).
 */

import { describe, it, expect, afterEach, spyOn } from 'bun:test';
import {
  debugLog,
  createLogger,
  setDebugClient,
  setDebugEnabled,
  isDebugEnabled,
} from './debugLog';

interface SentFrame {
  message: string;
  category: string;
  sessionId: string;
  details: Record<string, unknown>;
}

/** Minimal stand-in for BalloonsClient: only debugLog.info + isConnected are used. */
function createFakeClient(connected = true) {
  const sent: SentFrame[] = [];
  const client = {
    isConnected: connected,
    debugLog: {
      info: (message: string, category: string, sessionId: string, details: Record<string, unknown>) => {
        sent.push({ message, category, sessionId, details });
      },
    },
  };
  return { client: client as any, sent };
}

const originalEnabled = isDebugEnabled();

afterEach(() => {
  setDebugClient(null);
  setDebugEnabled(originalEnabled);
});

describe('debugLog wire gate', () => {
  it('sends nothing on the socket when debug logging is disabled', () => {
    const logSpy = spyOn(console, 'log').mockImplementation(() => {});
    const { client, sent } = createFakeClient();
    setDebugClient(client);
    setDebugEnabled(false);

    debugLog('TestComponent', 'a message', { foo: 1 });

    expect(sent).toHaveLength(0);
    expect(logSpy).not.toHaveBeenCalled();
    logSpy.mockRestore();
  });

  it('sends to the socket with the same payload shape when enabled', () => {
    const logSpy = spyOn(console, 'log').mockImplementation(() => {});
    const { client, sent } = createFakeClient();
    setDebugClient(client);
    setDebugEnabled(true);

    debugLog('TestComponent', 'a message', { foo: 1 });

    expect(sent).toHaveLength(1);
    expect(sent[0]).toEqual({
      message: 'a message',
      category: 'client', // server-side 'client' buffer, not the component name
      sessionId: '',
      details: { foo: 1, source: 'web', component: 'TestComponent' },
    });
    // Console output is still gated on the same flag, so it fires when enabled.
    expect(logSpy).toHaveBeenCalled();
    logSpy.mockRestore();
  });

  it('routes createLogger() through the same gate', () => {
    const logSpy = spyOn(console, 'log').mockImplementation(() => {});
    const { client, sent } = createFakeClient();
    setDebugClient(client);

    const log = createLogger('Scoped');

    setDebugEnabled(false);
    log('while disabled', { a: 1 });
    expect(sent).toHaveLength(0);

    setDebugEnabled(true);
    log('while enabled', { a: 1 });
    expect(sent).toHaveLength(1);
    expect(sent[0]?.details.component).toBe('Scoped');
    logSpy.mockRestore();
  });

  it('does not send when enabled but disconnected', () => {
    const logSpy = spyOn(console, 'log').mockImplementation(() => {});
    const { client, sent } = createFakeClient(false);
    setDebugClient(client);
    setDebugEnabled(true);

    debugLog('TestComponent', 'a message');

    expect(sent).toHaveLength(0);
    logSpy.mockRestore();
  });

  it('is a no-op when disabled even with no client set', () => {
    const logSpy = spyOn(console, 'log').mockImplementation(() => {});
    setDebugClient(null);
    setDebugEnabled(false);

    expect(() => debugLog('TestComponent', 'a message', { foo: 1 })).not.toThrow();
    expect(logSpy).not.toHaveBeenCalled();
    logSpy.mockRestore();
  });
});