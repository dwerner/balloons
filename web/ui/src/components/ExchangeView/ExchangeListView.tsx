import React, { memo, useMemo } from 'react';
import type { TurnInfo } from '../../../../generated/balloons-client';
import { ExchangeView } from './ExchangeView';
import type { ToolUseState } from './ExchangeView';
import { ForkProposalTurn } from '../ForkProposalTurn';

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

  // Fork proposals get special interactive component
  if (blockType === 'fork_proposal') {
    return <ForkProposalTurn turn={turn} />;
  }

  // System-level block types get special treatment
  const systemTypes = ['fork', 'merge', 'merged_to', 'link', 'interruption', 'error', 'image', 'slide', 'review', 'merge_proposal', 'archive'];

  if (systemTypes.includes(blockType)) {
    const labels: Record<string, string> = {
      'fork': '\u2442 fork',
      'merge': '\u2934 merge',
      'merged_to': '\u2934 merged',
      'link': '\uD83D\uDD17 link',
      'interruption': '\u26A0 interrupted',
      'error': '\u2717 error',
      'image': '\uD83D\uDDBC image',
      'slide': '\uD83D\uDCCA slide',
      'review': '\uD83D\uDCCB review',
      'merge_proposal': '\u2934 merge proposal',
      'archive': '\uD83D\uDCE6 archive',
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

  return (
    <div className="exchange-list-view">
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
