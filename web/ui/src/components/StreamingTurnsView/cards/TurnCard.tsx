/**
 * TurnCard - Main dispatcher component for turn rendering
 *
 * Routes to the appropriate card component based on contentBlock.type.
 * For tool_use blocks, further routes to tool-specific cards (Read, Edit, etc.)
 * Also handles pairing tool_use turns with their matching tool_result.
 */

import React, { useMemo, useCallback } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import { TextCard } from './TextCard';
import { ToolResultCard } from './ToolResultCard';
import { SystemCard } from './SystemCard';
import { ForkProposalCard } from './ForkProposalCard';
import { MergeProposalCard } from './MergeProposalCard';
import { useClient } from './ClientContext';

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

// System content block types (non-interactive)
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
]);

// Interactive proposal types (need special handling)
const PROPOSAL_TYPES = new Set([
  'fork_proposal',
  'merge_proposal',
]);

// Map of tool names to their specific card components
const TOOL_CARD_MAP: Record<string, React.ComponentType<{ turn: SessionDataTurn; result?: SessionDataTurn | null }>> = {
  Read: ReadCard,
  Edit: EditCard,
  Write: WriteCard,
  Bash: BashCard,
  Grep: GrepCard,
  Glob: GlobCard,
  play_midi: MidiPlayerCard,
};

export function TurnCard({ turn, allTurns = [], sessionId }: TurnCardProps) {
  const { role, contentBlock } = turn;
  const blockType = contentBlock?.type || 'text';
  const client = useClient();

  // Debug logger that sends to server via WebSocket
  const debugLog = useCallback((message: string, data?: Record<string, unknown>) => {
    if (client?.isConnected) {
      client.debugLog.info(message, 'web.TurnCard', '', data ?? null).catch(() => {});
    }
  }, [client]);

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
    const toolUseId = toolUseBlock?.id || '';

    // Special handling for propose_fork tool - render as ForkProposalCard
    // The tool input contains the fork proposal data
    if (toolName === 'propose_fork' && toolUseId.startsWith('balloons-')) {
      const input = toolUseBlock?.input as Record<string, unknown> | undefined;
      if (input && !('_streaming' in input)) {
        // Build a synthetic fork proposal block from the tool input
        const syntheticBlock = {
          type: 'fork_proposal' as const,
          proposalId: toolUseId,
          name: (input.name as string) || '',
          description: (input.description as string) || '',
          contextPlan: ((input.context_plan as unknown[]) || []).map((cp: unknown) => {
            const item = cp as Record<string, unknown>;
            return {
              exchangeRange: (item.exchange_range as string) || '',
              mode: (item.mode as string) || 'compress',
              reason: (item.reason as string) || '',
            };
          }),
          initialPrompt: (input.initial_prompt as string) || '',
          bindTo: input.bind_to && typeof input.bind_to === 'object' ? {
            entityType: ((input.bind_to as Record<string, unknown>).entity_type as string) || '',
            entityId: ((input.bind_to as Record<string, unknown>).entity_id as string) || '',
            role: ((input.bind_to as Record<string, unknown>).role as string) || '',
          } : null,
          bindToInherit: input.bind_to === 'inherit',
          status: 'pending' as const,
          allExchanges: [],
        };
        // Create a synthetic turn with the fork proposal block
        const syntheticTurn = {
          ...turn,
          contentBlock: syntheticBlock,
        };
        return <ForkProposalCard turn={syntheticTurn} sessionId={sessionId} />;
      }
    }

    // Try to get a tool-specific card
    const ToolCardComponent = TOOL_CARD_MAP[toolName];

    if (ToolCardComponent) {
      return <ToolCardComponent turn={turn} result={matchingResult} />;
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

  // Interactive proposal cards
  if (blockType === 'fork_proposal') {
    return <ForkProposalCard turn={turn} sessionId={sessionId} />;
  }

  if (blockType === 'merge_proposal') {
    return <MergeProposalCard turn={turn} sessionId={sessionId} />;
  }

  // Non-interactive system cards
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
