/**
 * GenericToolCard - Fallback for unknown or less common tools
 *
 * Shows tool name, JSON input, and result
 * Used for tools we don't have specific cards for
 */

import React, { useState } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import { BaseToolCard, calculateToolPhase } from './BaseToolCard';
import './cards.css';

interface GenericToolCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
}

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

// Get partial JSON from streaming input
function getStreamingJson(input: Record<string, unknown>): string {
  return (input._streaming as string) || '';
}

// Format JSON for display
function formatJson(json: string | Record<string, unknown>): string {
  try {
    if (typeof json === 'string') {
      const parsed = JSON.parse(json);
      return JSON.stringify(parsed, null, 2);
    }
    return JSON.stringify(json, null, 2);
  } catch {
    return typeof json === 'string' ? json : JSON.stringify(json);
  }
}

export const GenericToolCard = React.memo(function GenericToolCard({ turn, result }: GenericToolCardProps) {
  const { contentBlock, streaming, tokens } = turn;
  const [inputExpanded, setInputExpanded] = useState(false);

  // Extract tool info
  const toolUseBlock = contentBlock?.type === 'tool_use'
    ? (contentBlock as ToolUseBlock)
    : null;

  const toolName = toolUseBlock?.name || 'Tool';
  const toolInput = toolUseBlock?.input || {};
  const inputIsStreaming = isStreamingInput(toolInput);

  // Get result info
  const resultBlock = result?.contentBlock?.type === 'tool_result'
    ? (result.contentBlock as ToolResultBlock)
    : null;
  const hasResult = !!resultBlock;
  const resultContent = resultBlock?.content || '';
  const previewChunks = turn.toolResultPreview || [];
  const previewText = previewChunks.map((chunk) => chunk.delta).join('');
  const previewIsError = previewChunks.every((chunk) => chunk.stream === 'stderr') && previewChunks.length > 0;
  const hasPreviewChunks = previewChunks.length > 0;
  const isError = resultBlock?.isError || false;

  // Calculate phase
  const hasInput = !inputIsStreaming && Object.keys(toolInput).filter(k => k !== '_streaming').length > 0;
  const phase = calculateToolPhase(streaming, hasInput, inputIsStreaming, hasResult, isError);

  // Format input for display
  const formattedInput = inputIsStreaming
    ? getStreamingJson(toolInput)
    : formatJson(toolInput);

  // Show all output (no truncation)
  const displayOutput = resultContent;

  // Raw data for debugging mode
  const rawData = { turn, result };

  return (
    <BaseToolCard
      toolName={toolName}
      phase={phase}
      tokens={tokens}
      order={turn.order}
      orderEnd={result?.order}
      className="generic-tool-card"
      rawData={rawData}
      timestamp={turn.timestamp}
    >
      {/* Input section - collapsible */}
      {(hasInput || inputIsStreaming) && (
        <div className="tool-section">
          <button
            className="tool-section-toggle"
            onClick={() => setInputExpanded(!inputExpanded)}
            type="button"
          >
            <span className="toggle-icon">{inputExpanded ? '▼' : '▶'}</span>
            <span className="toggle-label">Input</span>
          </button>
          {inputExpanded && (
            <pre className="tool-json-content">
              <code>{formattedInput}</code>
            </pre>
          )}
        </div>
      )}

      {/* Streaming indicator */}
      {inputIsStreaming && (
        <div className="tool-building-content">
          <span className="streaming-dots">
            <span className="dot">●</span>
            <span className="dot">●</span>
            <span className="dot">●</span>
          </span>
          <span>Building input...</span>
        </div>
      )}

      {/* Result */}
      {hasResult && (
        <pre className={`tool-output ${isError ? 'error' : ''}`}>
          <code>{displayOutput || '(no output)'}</code>
        </pre>
      )}

      {/* Executing state */}
      {!hasResult && phase === 'executing' && (
        hasPreviewChunks ? (
          <>
            <pre className={`tool-output ${previewIsError ? 'error' : ''}`}>
              <code>{previewText || '(waiting for output...)'}</code>
            </pre>
            <div className="tool-executing">Executing...</div>
          </>
        ) : (
          <div className="tool-executing">Executing...</div>
        )
      )}
    </BaseToolCard>
  );
});

export default GenericToolCard;
