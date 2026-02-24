/**
 * TurnCard - Main dispatcher component for turn rendering
 *
 * Routes to the appropriate card component based on contentBlock.type.
 * For tool_use blocks, further routes to tool-specific cards (Read, Edit, etc.)
 * Also handles pairing tool_use turns with their matching tool_result.
 */

import React, { useMemo } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import { TextCard } from './TextCard';
import { ToolResultCard } from './ToolResultCard';
import { SystemCard } from './SystemCard';
import { ForkProposalCard } from './ForkProposalCard';
import { MergeProposalCard } from './MergeProposalCard';
import { createLogger } from '../../../utils/debugLog';

// Tool-specific cards
import { ReadCard } from './ReadCard';
import { EditCard } from './EditCard';
import { WriteCard } from './WriteCard';
import { BashCard } from './BashCard';
import { GrepCard } from './GrepCard';
import { GlobCard } from './GlobCard';
import { GenericToolCard } from './GenericToolCard';
import { MidiPlayerCard } from './MidiPlayerCard';

import './cards.css';

export interface TurnCardProps {
  turn: SessionDataTurn;
  /** All turns for finding matching tool results */
  allTurns?: SessionDataTurn[];
  /** Session ID for proposal cards that need API access */
  sessionId?: string;
}

// System content block types (non-interactive, rendered by SystemCard)
const SYSTEM_TYPES = new Set([
  'fork',
  'forked_from',
  'merge',
  'merged_to',
  'link',
  'interruption',
  'error',
  'image',
  'slide',
  'review',
  'archive',
  // Legacy proposal block types (deprecated - new proposals are tool_use blocks)
  'fork_proposal',
  'merge_proposal',
]);

// Note: fork_proposal and merge_proposal block types are deprecated.
// These are now rendered as tool_use blocks via TOOL_CARD_MAP.
// The block type handlers below are kept for backwards compatibility
// with any existing sessions that have these block types.

// Map of tool names to their specific card components
// Note: sessionId is passed via props for tools that need API access (propose_fork, propose_merge)
const TOOL_CARD_MAP: Record<string, React.ComponentType<{ turn: SessionDataTurn; result?: SessionDataTurn | null; sessionId?: string }>> = {
  Read: ReadCard,
  Edit: EditCard,
  Write: WriteCard,
  Bash: BashCard,
  Grep: GrepCard,
  Glob: GlobCard,
  play_midi: MidiPlayerCard,
  propose_fork: ForkProposalCard,
  propose_merge: MergeProposalCard,
};

// Module-level logger that respects global debug toggle
const debugLog = createLogger('TurnCard');

export function TurnCard({ turn, allTurns = [], sessionId }: TurnCardProps) {
  const { role, contentBlock } = turn;
  const blockType = contentBlock?.type || 'text';

  // Debug: log ALL system turns to understand what's coming through
  // TODO: Remove after debugging
  if (role === 'system') {
    debugLog('System turn', { role, blockType, hasContentBlock: !!contentBlock, contentBlockKeys: contentBlock ? Object.keys(contentBlock) : [], turnId: turn.turnId });
  }

  // Debug: log when we see proposal-related blocks
  if (blockType === 'fork_proposal' || blockType === 'merge_proposal') {
    debugLog('Rendering proposal card', { blockType, sessionId, turn: turn.turnId });
  }

  // Find matching tool_result for tool_use turns
  const matchingResult = useMemo(() => {
    if (blockType !== 'tool_use') return null;

    // Get the tool_use_id for precise matching
    const toolUseBlock = contentBlock as ToolUseBlock;
    const toolUseId = toolUseBlock?.id;

    // DEBUG: Log tool_use state when looking for results
    if (!toolUseId) {
      debugLog('tool_use has no ID yet (still streaming)', {
        turnId: turn.turnId?.substring(0, 8),
        order: turn.order,
        toolName: toolUseBlock?.name || '(empty)',
        streaming: turn.streaming,
      });
    }

    // Look for a tool_result turn that matches
    const turnOrder = turn.order;
    const results = allTurns.filter((t) => {
      if (t.contentBlock?.type !== 'tool_result') return false;
      if (t.order <= turnOrder) return false;

      const resultBlock = t.contentBlock as ToolResultBlock;

      // Match by toolUseId if available (most precise)
      if (toolUseId && resultBlock?.toolUseId) {
        return resultBlock.toolUseId === toolUseId;
      }

      // Fall back to exchange matching
      if (turn.exchangeId) {
        return t.exchangeId === turn.exchangeId;
      }

      // Last resort: just match by order (first result after this tool_use)
      return true;
    });

    // Return the first matching result
    return results.length > 0 ? results[0] : null;
  }, [turn, blockType, contentBlock, allTurns]);

  // Dispatch to appropriate card type
  if (blockType === 'tool_use') {
    const toolUseBlock = contentBlock as ToolUseBlock;
    const toolName = toolUseBlock?.name || '';

    // Try to get a tool-specific card
    const ToolCardComponent = TOOL_CARD_MAP[toolName];

    if (ToolCardComponent) {
      // Pass sessionId for tools that need API access (propose_fork, propose_merge)
      return <ToolCardComponent turn={turn} result={matchingResult} sessionId={sessionId} />;
    }

    // Fall back to generic tool card
    return <GenericToolCard turn={turn} result={matchingResult} />;
  }

  if (blockType === 'tool_result') {
    // Check if there's a matching tool_use that will render this result
    const resultBlock = contentBlock as ToolResultBlock;
    // Tool results with matching tool_use turns are filtered out at the parent level
    // (StreamingTurnsView). If we get here, it's a standalone tool result.
    return <ToolResultCard turn={turn} />;
  }

  // Legacy fork_proposal and merge_proposal block types fall through to SystemCard
  // (These are deprecated - new proposals come through as tool_use blocks)

  // Non-interactive system cards (includes legacy proposal block types)
  if (SYSTEM_TYPES.has(blockType)) {
    return <SystemCard turn={turn} />;
  }

  // Default to text card for text blocks and unknown types
  // Also handle role='tool' for backwards compatibility
  if (role === 'tool') {
    return <ToolResultCard turn={turn} />;
  }

  // DEBUG: Catch-all for any turns that would otherwise render empty
  // This shouldn't happen in normal operation - if you see this, investigate the turn data
  if (!contentBlock || Object.keys(contentBlock).length === 0) {
    return (
      <div className="debug-empty-turn-card" style={{
        background: 'rgba(255, 100, 0, 0.15)',
        border: '2px dashed #ff6400',
        borderRadius: '8px',
        padding: '12px',
        margin: '8px 0',
        fontFamily: 'monospace',
        fontSize: '12px',
      }}>
        <div style={{ fontWeight: 'bold', marginBottom: '8px', color: '#ff6400' }}>
          ⚠️ DEBUG: Empty/Missing Content Block
        </div>
        <div><strong>Turn ID:</strong> {turn.turnId}</div>
        <div><strong>Role:</strong> {role}</div>
        <div><strong>Block Type:</strong> {blockType}</div>
        <div><strong>Order:</strong> {turn.order}</div>
        <div><strong>Exchange ID:</strong> {turn.exchangeId || 'none'}</div>
        <div style={{ marginTop: '8px' }}>
          <strong>Full turn data:</strong>
          <pre style={{ fontSize: '10px', overflow: 'auto', maxHeight: '200px' }}>
            {JSON.stringify(turn, null, 2)}
          </pre>
        </div>
      </div>
    );
  }

  return <TextCard turn={turn} />;
}

export default TurnCard;
