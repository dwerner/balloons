/**
 * TurnCard - Main dispatcher component for turn rendering
 *
 * Routes to the appropriate card component based on contentBlock.type.
 * Also handles pairing tool_use turns with their matching tool_result.
 */

import React, { useMemo } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import { TextCard } from './TextCard';
import { ToolUseCard } from './ToolUseCard';
import { ToolResultCard } from './ToolResultCard';
import { SystemCard } from './SystemCard';
import './cards.css';

export interface TurnCardProps {
  turn: SessionDataTurn;
  /** All turns for finding matching tool results */
  allTurns?: SessionDataTurn[];
}

// System content block types
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
  'fork_proposal',
  'merge_proposal',
  'archive',
]);

export function TurnCard({ turn, allTurns = [] }: TurnCardProps) {
  const { role, contentBlock } = turn;
  const blockType = contentBlock?.type || 'text';

  // Find matching tool_result for tool_use turns
  const matchingResult = useMemo(() => {
    if (blockType !== 'tool_use') return null;

    // Look for a tool_result turn that matches
    const turnOrder = turn.order;
    const results = allTurns.filter(
      (t) =>
        t.contentBlock?.type === 'tool_result' &&
        t.order > turnOrder &&
        // Same exchange if available
        (turn.exchangeId ? t.exchangeId === turn.exchangeId : true)
    );

    // Return the first matching result
    return results.length > 0 ? results[0] : null;
  }, [turn, blockType, allTurns]);

  // Dispatch to appropriate card type
  if (blockType === 'tool_use') {
    return <ToolUseCard turn={turn} result={matchingResult} />;
  }

  if (blockType === 'tool_result') {
    // Check if there's a matching tool_use that will render this result
    const hasMatchingToolUse = allTurns.some(
      (t) =>
        t.contentBlock?.type === 'tool_use' &&
        t.order < turn.order &&
        (turn.exchangeId ? t.exchangeId === turn.exchangeId : true)
    );

    // If there's a matching tool_use, skip rendering (it will include the result)
    if (hasMatchingToolUse) {
      return null;
    }

    // Standalone tool result
    return <ToolResultCard turn={turn} />;
  }

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
