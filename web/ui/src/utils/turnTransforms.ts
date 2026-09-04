/**
 * Turn conversion helpers.
 *
 * Bridges between the wire/hook representations (TurnSnapshot, SessionDataTurn)
 * and the flattened TurnInfo used by sidebar/tree components. Extracted from
 * App.tsx so the conversion rules live in one testable place.
 *
 * NOTE: these are a transitional bridge. WS4 (single source of truth) aims to
 * retire the parallel TurnInfo representation in favour of SessionDataTurn.
 */

import type {
  TurnInfo,
  TurnSnapshot,
  Unsubscribe,
  SessionHistoryChunkEvent,
  SessionHistoryCompleteEvent,
  BalloonsClient,
} from '../../../generated/balloons-client';
import type { SessionDataTurn } from '../hooks/useSessionData';

/** Dedupe by idx (keep latest) and sort ascending. */
export function sortTurnsByIdx(turns: TurnInfo[]): TurnInfo[] {
  const byIdx = new Map<number, TurnInfo>();
  for (const turn of turns) {
    byIdx.set(turn.idx, turn);
  }
  return Array.from(byIdx.values()).sort((a, b) => a.idx - b.idx);
}

/** Convert a TurnSnapshot (wire) to TurnInfo. */
export function turnSnapshotToInfo(snapshot: TurnSnapshot, idx: number): TurnInfo {
  const block = snapshot.contentBlock;
  const blockType = block?.type || 'text';

  let content = '';
  let toolUse: TurnInfo['toolUse'] = undefined;
  let toolResult: TurnInfo['toolResult'] = undefined;

  if (blockType === 'text' && block && 'text' in block) {
    content = block.text || '';
  } else if (blockType === 'tool_use' && block) {
    const tb = block as { id?: string; name?: string; input?: unknown };
    content = JSON.stringify(tb.input || {});
    toolUse = {
      toolUseId: tb.id || '',
      name: tb.name || '',
      inputJson: content,
    };
  } else if (blockType === 'tool_result' && block) {
    const tr = block as { toolUseId?: string; content?: unknown; isError?: boolean };
    content = String(tr.content || '');
    toolResult = {
      toolUseId: tr.toolUseId || '',
      content,
      isError: tr.isError || false,
    };
  } else if (blockType === 'archive' && block) {
    const ab = block as { summary?: string; messageCount?: number };
    content = ab.summary || `Archived ${ab.messageCount || 0} messages`;
  } else if (blockType === 'fork' && block) {
    const fb = block as { forkName?: string; prompt?: string };
    content = fb.forkName ? `**${fb.forkName}**\n\n${fb.prompt || ''}` : fb.prompt || 'Forked session';
  } else if (blockType === 'merge' && block) {
    const mb = block as { forkName?: string; message?: string };
    content = mb.message || `Merged from ${mb.forkName || 'fork'}`;
  } else if (blockType === 'merged_to' && block) {
    const mtb = block as { parentName?: string; message?: string };
    content = mtb.message || `Merged to ${mtb.parentName || 'parent'}`;
  } else if (blockType === 'link' && block) {
    const lb = block as { summary?: string };
    content = lb.summary || 'Linked session';
  } else if (blockType === 'interruption' && block) {
    const ib = block as { reason?: string };
    content = ib.reason || 'User cancelled';
  } else if (blockType === 'error' && block) {
    const eb = block as { reason?: string; details?: string };
    content = `**${eb.reason || 'Error'}**\n\n${eb.details || ''}`;
  }

  return {
    idx,
    role: snapshot.role,
    content,
    streaming: snapshot.streaming,
    viewed: snapshot.viewed,
    tokens: snapshot.tokens,
    contextMode: snapshot.contextMode,
    contentBlockType: blockType,
    exchangeId: snapshot.exchangeId,
    toolUse,
    toolResult,
  };
}

/** Convert a SessionDataTurn (hook) to TurnInfo. */
export function sessionDataTurnToInfo(turn: SessionDataTurn): TurnInfo {
  const block = turn.contentBlock;
  const blockType = block?.type || 'text';

  let content = '';
  let toolUse: TurnInfo['toolUse'] = undefined;
  let toolResult: TurnInfo['toolResult'] = undefined;

  if (blockType === 'text' && block && 'text' in block) {
    content = (block as { text?: string }).text || '';
  } else if (blockType === 'tool_use' && block) {
    const tb = block as { id?: string; name?: string; input?: unknown };
    content = JSON.stringify(tb.input || {});
    toolUse = {
      toolUseId: tb.id || '',
      name: tb.name || '',
      inputJson: content,
    };
  } else if (blockType === 'tool_result' && block) {
    const tr = block as { toolUseId?: string; content?: unknown; isError?: boolean };
    content = String(tr.content || '');
    toolResult = {
      toolUseId: tr.toolUseId || '',
      content,
      isError: tr.isError || false,
    };
  } else if (blockType === 'archive' && block) {
    const ab = block as { summary?: string; messageCount?: number };
    content = ab.summary || `Archived ${ab.messageCount || 0} messages`;
  } else if (blockType === 'fork' && block) {
    const fb = block as { forkName?: string; prompt?: string };
    content = fb.forkName ? `**${fb.forkName}**\n\n${fb.prompt || ''}` : fb.prompt || 'Forked session';
  } else if (blockType === 'merge' && block) {
    const mb = block as { forkName?: string; message?: string };
    content = mb.message || `Merged from ${mb.forkName || 'fork'}`;
  } else if (blockType === 'merged_to' && block) {
    const mtb = block as { parentName?: string; message?: string };
    content = mtb.message || `Merged to ${mtb.parentName || 'parent'}`;
  } else if (blockType === 'link' && block) {
    const lb = block as { summary?: string };
    content = lb.summary || 'Linked session';
  } else if (blockType === 'interruption' && block) {
    const ib = block as { reason?: string };
    content = ib.reason || 'User cancelled';
  } else if (blockType === 'error' && block) {
    const eb = block as { reason?: string; details?: string };
    content = `**${eb.reason || 'Error'}**\n\n${eb.details || ''}`;
  }

  return {
    idx: turn.order,
    role: turn.role,
    content,
    streaming: turn.streaming,
    viewed: turn.viewed,
    tokens: turn.tokens,
    contextMode: turn.contextMode,
    contentBlockType: blockType,
    exchangeId: turn.exchangeId,
    toolUse,
    toolResult,
  };
}

/**
 * Load session turns using layer-based subscriptions.
 *
 * Subscribes with specific layers (header, body, delta, history), collects
 * history via historyChunk events, and keeps the subscription active for
 * real-time updates.
 */
export async function loadSessionWithLayers(
  client: BalloonsClient,
  sessionId: string,
  clientId: string,
  layers: string[] = ['header', 'body', 'delta', 'history']
): Promise<TurnInfo[]> {
  return new Promise((resolve, reject) => {
    const collectedTurns: Map<string, TurnSnapshot> = new Map();
    const handlers: Unsubscribe[] = [];
    // Declared before `cleanup` (which clears it) but assigned after (the
    // timeout callback calls `cleanup`) — a genuine circular dependency, so
    // this cannot be a const.
    // eslint-disable-next-line prefer-const
    let timeoutId: ReturnType<typeof setTimeout>;

    const cleanup = () => {
      handlers.forEach(h => h());
      clearTimeout(timeoutId);
    };

    handlers.push(
      client.sessionData.sessionDataHistoryChunk((event: SessionHistoryChunkEvent) => {
        if (event.sessionId !== sessionId) return;
        for (const turn of event.turns || []) {
          if (turn.turnId) {
            collectedTurns.set(turn.turnId, turn);
          }
        }
      })
    );

    handlers.push(
      client.sessionData.sessionDataHistoryComplete((event: SessionHistoryCompleteEvent) => {
        if (event.sessionId !== sessionId) return;
        cleanup();

        const snapshots = Array.from(collectedTurns.values())
          .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
        const turns = snapshots.map((s, idx) => turnSnapshotToInfo(s, idx));
        resolve(turns);
      })
    );

    timeoutId = setTimeout(() => {
      cleanup();
      reject(new Error('Timeout waiting for history'));
    }, 30000);

    client.sessionData.subscribeAdd(sessionId, clientId, layers)
      .then(result => {
        if (!result.subscribed) {
          cleanup();
          reject(new Error(result.error || 'Subscription failed'));
        }
        if (!layers.includes('history')) {
          cleanup();
          resolve([]);
        }
      })
      .catch(err => {
        cleanup();
        reject(err);
      });
  });
}

/** Format token count with thousands separator. */
export function formatTokens(count: number): string {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k`;
  }
  return String(count);
}
