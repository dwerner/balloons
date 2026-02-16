import React, { memo, useMemo } from 'react';
import type { TurnInfo } from '../../../../generated/balloons-client';
import { ExchangeView } from './ExchangeView';
import type { ToolUseState } from './ExchangeView';

interface ExchangeListViewProps {
  turns: TurnInfo[];
  toolUses?: ToolUseState[];
}

// Group for turns that share an exchangeId, or standalone turns without one
interface TurnGroup {
  exchangeId: string | null;
  turns: TurnInfo[];
}

// Group turns by exchangeId
function groupTurnsByExchange(turns: TurnInfo[]): TurnGroup[] {
  const groups: TurnGroup[] = [];
  const exchangeMap = new Map<string, TurnInfo[]>();

  // First pass: group by exchangeId
  for (const turn of turns) {
    if (turn.exchangeId) {
      const existing = exchangeMap.get(turn.exchangeId);
      if (existing) {
        existing.push(turn);
      } else {
        exchangeMap.set(turn.exchangeId, [turn]);
      }
    }
  }

  // Build groups in order of first turn appearance
  const seenExchanges = new Set<string>();

  for (const turn of turns) {
    if (turn.exchangeId) {
      if (!seenExchanges.has(turn.exchangeId)) {
        seenExchanges.add(turn.exchangeId);
        groups.push({
          exchangeId: turn.exchangeId,
          turns: exchangeMap.get(turn.exchangeId)!
        });
      }
    } else {
      // Standalone turn - add as its own group
      groups.push({
        exchangeId: null,
        turns: [turn]
      });
    }
  }

  return groups;
}

// Render turns without exchangeId as simple blocks
const StandaloneTurn = memo(function StandaloneTurn({ turn }: { turn: TurnInfo }) {
  const blockType = turn.contentBlockType ?? 'text';

  // System-level block types get special treatment
  const systemTypes = ['fork', 'merge', 'merged_to', 'link', 'interruption', 'error', 'image', 'slide', 'review', 'fork_proposal', 'merge_proposal', 'archive'];

  if (systemTypes.includes(blockType)) {
    const labels: Record<string, string> = {
      'fork': '⑂ fork',
      'merge': '⤴ merge',
      'merged_to': '⤴ merged',
      'link': '🔗 link',
      'interruption': '⚠ interrupted',
      'error': '✗ error',
      'image': '🖼 image',
      'slide': '📊 slide',
      'review': '📋 review',
      'fork_proposal': '⑂ fork proposal',
      'merge_proposal': '⤴ merge proposal',
      'archive': '📦 archive',
    };

    return (
      <div className={`standalone-turn system ${blockType}`}>
        <div className="standalone-turn-header">{labels[blockType] || blockType}</div>
        <div className="standalone-turn-content">{turn.content}</div>
      </div>
    );
  }

  // Regular turn without exchange grouping
  return (
    <div className={`standalone-turn ${turn.role}`}>
      <div className="standalone-turn-header">{turn.role}</div>
      <div className="standalone-turn-content">{turn.content}</div>
    </div>
  );
});

export const ExchangeListView = memo(function ExchangeListView({
  turns,
  toolUses = []
}: ExchangeListViewProps) {
  // Group turns by exchangeId
  const groups = useMemo(() => groupTurnsByExchange(turns), [turns]);

  // Filter tool uses by exchange for passing to each ExchangeView
  const toolUsesByExchange = useMemo(() => {
    const map = new Map<string, ToolUseState[]>();
    for (const tu of toolUses) {
      if (tu.exchangeId) {
        const existing = map.get(tu.exchangeId);
        if (existing) {
          existing.push(tu);
        } else {
          map.set(tu.exchangeId, [tu]);
        }
      }
    }
    return map;
  }, [toolUses]);

  // Debug mode - show exchange grouping info visually
  const showDebug = false;

  return (
    <div className="exchange-list-view">
      {showDebug && (
        <div style={{
          padding: '8px 12px',
          background: '#ffe0b2',
          fontSize: '11px',
          fontFamily: 'monospace',
          marginBottom: '8px',
          borderRadius: '4px',
          maxHeight: '200px',
          overflow: 'auto',
          color: '#333'
        }}>
          <strong>DEBUG:</strong> {groups.length} exchanges, {turns.length} turns total
          {groups.map((g, i) => (
            <div key={g.exchangeId ?? `group-${i}`} style={{ marginTop: '4px', borderTop: '1px solid #ccc', paddingTop: '4px' }}>
              <strong>Exchange {i}:</strong> <code style={{ background: '#fff', padding: '2px 4px' }}>{g.exchangeId?.slice(0, 8) || 'NULL'}</code>
              <div style={{ marginLeft: '8px' }}>
                {g.turns.map(t => (
                  <div key={`debug-turn-${t.idx}`} style={{
                    color: t.streaming ? '#d32f2f' : '#333',
                    fontWeight: t.streaming ? 'bold' : 'normal'
                  }}>
                    Turn {t.idx}: {t.role} {t.streaming ? '⏳' : '✓'}
                    {t.contentBlockType ? ` [${t.contentBlockType}]` : ''}
                    {t.content ? ` "${t.content.slice(0, 30)}${t.content.length > 30 ? '...' : ''}"` : ' (empty)'}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      {groups.map((group, idx) => {
        if (group.exchangeId) {
          // Grouped exchange
          return (
            <ExchangeView
              key={group.exchangeId}
              exchangeId={group.exchangeId}
              turns={group.turns}
              toolUses={toolUsesByExchange.get(group.exchangeId)}
              defaultExpanded={idx === groups.length - 1} // Last exchange expanded by default
            />
          );
        } else {
          // Standalone turn (no exchangeId)
          const turn = group.turns[0];
          if (!turn) return null;
          return (
            <StandaloneTurn
              key={`standalone-${idx}-${turn.idx}`}
              turn={turn}
            />
          );
        }
      })}
    </div>
  );
});

export default ExchangeListView;
