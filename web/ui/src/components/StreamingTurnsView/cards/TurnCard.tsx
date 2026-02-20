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

// Tool-specific cards
import { ReadCard } from './ReadCard';
import { EditCard } from './EditCard';
import { WriteCard } from './WriteCard';
import { BashCard } from './BashCard';
import { GrepCard } from './GrepCard';
import { GlobCard } from './GlobCard';
import { GenericToolCard } from './GenericToolCard';

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
};

export function TurnCard({ turn, allTurns = [], sessionId }: TurnCardProps) {
  const { role, contentBlock } = turn;
  const blockType = contentBlock?.type || 'text';

  // Debug: log ALL system turns to understand what's coming through
  // TODO: Remove after debugging
  if (role === 'system') {
    console.log('[TurnCard] System turn:', { role, blockType, hasContentBlock: !!contentBlock, contentBlockKeys: contentBlock ? Object.keys(contentBlock) : [], turnId: turn.turnId });
  }

  // Debug: log when we see proposal-related blocks
  if (blockType === 'fork_proposal' || blockType === 'merge_proposal') {
    console.log('[TurnCard] Rendering proposal card:', { blockType, sessionId, turn });
  }

  // Find matching tool_result for tool_use turns
  const matchingResult = useMemo(() => {
    if (blockType !== 'tool_use') return null;

    // Get the tool_use_id for precise matching
    const toolUseBlock = contentBlock as ToolUseBlock;
    const toolUseId = toolUseBlock?.id;

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
      return <ToolCardComponent turn={turn} result={matchingResult} />;
    }

    // Fall back to generic tool card
    return <GenericToolCard turn={turn} result={matchingResult} />;
  }

  if (blockType === 'tool_result') {
    // Check if there's a matching tool_use that will render this result
    const resultBlock = contentBlock as ToolResultBlock;
    const toolUseId = resultBlock?.toolUseId;

    const hasMatchingToolUse = allTurns.some((t) => {
      if (t.contentBlock?.type !== 'tool_use') return false;
      if (t.order >= turn.order) return false;

      const toolBlock = t.contentBlock as ToolUseBlock;

      // Match by toolUseId if available
      if (toolUseId && toolBlock?.id) {
        return toolBlock.id === toolUseId;
      }

      // Fall back to exchange matching
      if (turn.exchangeId) {
        return t.exchangeId === turn.exchangeId;
      }

      return true;
    });

    // If there's a matching tool_use, skip rendering (it will include the result)
    if (hasMatchingToolUse) {
      return null;
    }

    // Standalone tool result
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

  return <TextCard turn={turn} />;
}

export default TurnCard;
