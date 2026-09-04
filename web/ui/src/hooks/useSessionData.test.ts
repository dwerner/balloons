/**
 * Characterization tests for useSessionData.
 *
 * These pin the CURRENT behaviour of the streaming state machine so the WS4
 * "single source of truth" refactor is a deliberate, visible change rather
 * than a silent regression. They exercise the real hook against a mock client
 * that captures the event-handler callbacks, then drive events through it.
 *
 * Key behaviours pinned:
 *  - turns are derived sorted by `order`
 *  - non-assistant turnCreated materializes immediately (streaming=true)
 *  - assistant turnCreated stays PENDING until content arrives
 *  - thinking deltas apply immediately; text/markdown deltas batch + flush
 *  - late deltas for a finished turn are discarded
 *  - turnFinished finalizes content and clears streaming
 *  - events for other sessions are ignored
 *  - clear() resets all state
 */

import { describe, it, expect, afterEach } from 'bun:test';
import { renderHook, act, waitFor, cleanup } from '@testing-library/react';
import { useSessionData } from './useSessionData';

// Explicit cleanup (see Modal.test.tsx): RTL auto-cleanup only binds to the
// first importing file, so each rendering file cleans up its own DOM.
afterEach(cleanup);

const SESSION = 'sess-1';
const OTHER = 'sess-other';

/** Flush interval is 50ms; sleep past it so the interval flush fires. */
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

interface MockClient {
  client: any;
  emit: (name: string, data: unknown) => void;
}

/** Build a mock BalloonsClient that records event callbacks so tests can emit. */
function createMockClient(): MockClient {
  const emitters: Record<string, Array<(d: any) => void>> = {};
  const on = (name: string, cb: (d: any) => void) => {
    (emitters[name] ||= []).push(cb);
    return () => {
      emitters[name] = (emitters[name] || []).filter((f) => f !== cb);
    };
  };
  const emit = (name: string, data: unknown) => {
    (emitters[name] || []).forEach((f) => f(data));
  };

  const sessionData = {
    subscribeAdd: async () => ({ subscribed: true }),
    subscribeRemove: async () => ({ subscribed: false }),
    isSessionStreaming: async () => false,
    loadHistoryRange: async () => undefined,
    sessionDataTurnCreated: (cb: any) => on('turnCreated', cb),
    sessionDataTurnDelta: (cb: any) => on('turnDelta', cb),
    sessionDataTurnFinished: (cb: any) => on('turnFinished', cb),
    sessionDataStreamStarted: (cb: any) => on('streamStarted', cb),
    sessionDataStreamDone: (cb: any) => on('streamDone', cb),
    sessionDataStreamError: (cb: any) => on('streamError', cb),
    sessionDataStreamProgress: (cb: any) => on('streamProgress', cb),
    sessionDataToolUseStarted: (cb: any) => on('toolUseStarted', cb),
    sessionDataToolInputDelta: (cb: any) => on('toolInputDelta', cb),
    sessionDataToolUse: (cb: any) => on('toolUse', cb),
    sessionDataToolResultDelta: (cb: any) => on('toolResultDelta', cb),
    sessionDataToolResult: (cb: any) => on('toolResult', cb),
    sessionDataHistoryChunk: (cb: any) => on('historyChunk', cb),
    sessionDataHistoryComplete: (cb: any) => on('historyComplete', cb),
    sessionDataTurnsDeleted: (cb: any) => on('turnsDeleted', cb),
    sessionDataTurnsReordered: (cb: any) => on('turnsReordered', cb),
  };

  const client = {
    hasClientId: true,
    clientId: 'test-client',
    isConnected: true,
    onStateChange: () => () => {},
    sessionData,
  };
  return { client, emit };
}

/** Render the hook and wait until it has subscribed. */
async function setup() {
  const { client, emit } = createMockClient();
  const { result } = renderHook(() => useSessionData(client, SESSION));
  await waitFor(() => {
    if (!result.current.isSubscribed) throw new Error('not subscribed yet');
  });
  return { result, emit };
}

describe('useSessionData', () => {
  it('derives turns sorted by order', async () => {
    const { result, emit } = await setup();

    act(() => {
      emit('turnCreated', { sessionId: SESSION, turnId: 'b', order: 1, role: 'user', contentBlockType: 'text' });
      emit('turnCreated', { sessionId: SESSION, turnId: 'a', order: 0, role: 'user', contentBlockType: 'text' });
    });

    expect(result.current.turns.map((t) => t.turnId)).toEqual(['a', 'b']);
  });

  it('materializes non-assistant turns immediately with streaming=true', async () => {
    const { result, emit } = await setup();

    act(() => {
      emit('turnCreated', { sessionId: SESSION, turnId: 'u1', order: 0, role: 'user', contentBlockType: 'text' });
    });

    const turn = result.current.getTurn('u1');
    expect(turn).toBeDefined();
    expect(turn!.role).toBe('user');
    expect(turn!.streaming).toBe(true);
  });

  it('keeps assistant turns pending until content arrives', async () => {
    const { result, emit } = await setup();

    act(() => {
      emit('streamStarted', { sessionId: SESSION });
      emit('turnCreated', { sessionId: SESSION, turnId: 'as1', order: 0, role: 'assistant', contentBlockType: 'text' });
    });

    // Not in turns yet, but tracked as pending.
    expect(result.current.getTurn('as1')).toBeUndefined();
    expect(result.current.pendingAssistantTurns.map((t) => t.turnId)).toContain('as1');

    // A text delta + flush materializes it.
    act(() => {
      emit('turnDelta', { sessionId: SESSION, turnId: 'as1', delta: 'Hello', contentBlockType: 'text' });
    });
    await act(async () => {
      await sleep(60);
    });

    const turn = result.current.getTurn('as1');
    expect(turn).toBeDefined();
    expect((turn!.contentBlock as { text?: string }).text).toBe('Hello');
  });

  it('applies thinking deltas immediately (no flush wait)', async () => {
    const { result, emit } = await setup();

    act(() => {
      emit('streamStarted', { sessionId: SESSION });
      emit('turnCreated', { sessionId: SESSION, turnId: 'as1', order: 0, role: 'assistant', contentBlockType: 'thinking' });
      emit('turnDelta', { sessionId: SESSION, turnId: 'as1', delta: 'pondering', contentBlockType: 'thinking' });
    });

    const turn = result.current.getTurn('as1');
    expect(turn).toBeDefined();
    expect(turn!.contentBlock.type).toBe('thinking');
    expect((turn!.contentBlock as { text?: string }).text).toBe('pondering');
  });

  it('accumulates text deltas and flushes them onto a streaming turn', async () => {
    const { result, emit } = await setup();

    act(() => {
      emit('streamStarted', { sessionId: SESSION });
      emit('turnCreated', { sessionId: SESSION, turnId: 'u1', order: 0, role: 'user', contentBlockType: 'text' });
      emit('turnDelta', { sessionId: SESSION, turnId: 'u1', delta: 'Hello ', contentBlockType: 'text' });
      emit('turnDelta', { sessionId: SESSION, turnId: 'u1', delta: 'world', contentBlockType: 'text' });
    });

    // Not yet flushed.
    expect((result.current.getTurn('u1')!.contentBlock as { text?: string }).text).toBe('');

    await act(async () => {
      await sleep(60); // interval flush
    });

    expect((result.current.getTurn('u1')!.contentBlock as { text?: string }).text).toBe('Hello world');

    act(() => {
      emit('streamDone', { sessionId: SESSION });
    });
  });

  it('finalizes content and clears streaming on turnFinished', async () => {
    const { result, emit } = await setup();

    act(() => {
      emit('streamStarted', { sessionId: SESSION });
      emit('turnCreated', { sessionId: SESSION, turnId: 'u1', order: 0, role: 'user', contentBlockType: 'text' });
      emit('turnFinished', { sessionId: SESSION, turnId: 'u1', finalContent: 'Done', tokens: 12 });
    });

    const turn = result.current.getTurn('u1');
    expect(turn!.streaming).toBe(false);
    expect((turn!.contentBlock as { text?: string }).text).toBe('Done');
    expect(turn!.tokens).toBe(12);
  });

  it('discards late deltas that arrive after turnFinished', async () => {
    const { result, emit } = await setup();

    act(() => {
      emit('streamStarted', { sessionId: SESSION });
      emit('turnCreated', { sessionId: SESSION, turnId: 'u1', order: 0, role: 'user', contentBlockType: 'text' });
      emit('turnFinished', { sessionId: SESSION, turnId: 'u1', finalContent: 'Final' });
      // Late delta for an already-finished turn.
      emit('turnDelta', { sessionId: SESSION, turnId: 'u1', delta: 'XX', contentBlockType: 'text' });
    });

    await act(async () => {
      await sleep(60); // flush attempt should discard the late delta
    });

    expect((result.current.getTurn('u1')!.contentBlock as { text?: string }).text).toBe('Final');
  });

  it('ignores events for other sessions', async () => {
    const { result, emit } = await setup();

    act(() => {
      emit('turnCreated', { sessionId: OTHER, turnId: 'x', order: 0, role: 'user', contentBlockType: 'text' });
    });

    expect(result.current.turns).toHaveLength(0);
  });

  it('clear() resets all state', async () => {
    const { result, emit } = await setup();

    act(() => {
      emit('turnCreated', { sessionId: SESSION, turnId: 'u1', order: 0, role: 'user', contentBlockType: 'text' });
    });
    expect(result.current.turns.length).toBeGreaterThan(0);

    act(() => {
      result.current.clear();
    });

    expect(result.current.turns).toHaveLength(0);
    expect(result.current.isSubscribed).toBe(false);
    expect(result.current.sessionId).toBeNull();
  });

  it('tracks streaming state via streamStarted/streamDone', async () => {
    const { result, emit } = await setup();

    act(() => {
      emit('streamStarted', { sessionId: SESSION });
    });
    expect(result.current.isStreaming).toBe(true);

    act(() => {
      emit('streamDone', { sessionId: SESSION });
    });
    expect(result.current.isStreaming).toBe(false);
  });
});
