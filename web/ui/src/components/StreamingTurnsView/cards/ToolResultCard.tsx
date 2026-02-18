/**
 * ToolResultCard - Renders tool_result content blocks
 *
 * This is used for standalone tool results that aren't paired with a tool_use.
 * Typically, tool results are displayed inline with their tool_use via ToolUseCard.
 */

import React from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolResultBlock } from '../../../../../generated/types';
import './cards.css';

interface ToolResultCardProps {
  turn: SessionDataTurn;
}

export function ToolResultCard({ turn }: ToolResultCardProps) {
  const { contentBlock, streaming } = turn;

  // Extract content from tool_result block
  const resultBlock = contentBlock?.type === 'tool_result'
    ? (contentBlock as ToolResultBlock)
    : null;
  const content = resultBlock?.content || '';
  const isError = resultBlock?.isError || false;

  // Truncate long results
  const truncated = content.length > 5000;
  const displayContent = truncated
    ? content.slice(0, 5000) + '\n... [truncated]'
    : content;

  return (
    <div className={`turn-card tool-result-card ${isError ? 'error' : ''} ${streaming ? 'streaming' : ''}`}>
      <div className="turn-card-header">
        <span className="turn-icon">{isError ? '❌' : '✓'}</span>
        <span className="turn-label">Tool Result</span>
        {streaming && <span className="streaming-indicator">●</span>}
      </div>
      <div className="turn-card-body">
        <pre className={`tool-result-output ${isError ? 'error' : ''}`}>
          <code>{displayContent || (streaming ? 'Waiting for result...' : '(empty)')}</code>
        </pre>
      </div>
    </div>
  );
}
