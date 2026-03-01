/**
 * GrepCard - Search pattern + results display with pattern highlighting
 *
 * Design goals:
 * - Pattern in header as code block
 * - Search path shown inline
 * - Results shown directly (no accordion)
 * - Matched patterns highlighted in results
 * - Compact result display
 */

import React from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import { BaseToolCard, calculateToolPhase, formatRelativePath } from './BaseToolCard';
import { GrepHighlightedResults } from './SyntaxHighlighter';
import { getStringInput, ensureString } from './toolInputUtils';
import './cards.css';

interface GrepCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
}

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

export const GrepCard = React.memo(function GrepCard({ turn, result }: GrepCardProps) {
  const { contentBlock, streaming, tokens } = turn;

  // Extract tool info
  const toolUseBlock = contentBlock?.type === 'tool_use'
    ? (contentBlock as ToolUseBlock)
    : null;

  const toolInput = toolUseBlock?.input || {};
  const inputIsStreaming = isStreamingInput(toolInput);

  // Extract Grep-specific inputs (with safe string conversion)
  const pattern = getStringInput(toolInput, 'pattern');
  const path = getStringInput(toolInput, 'path', '.');
  const glob = toolInput.glob ? ensureString(toolInput.glob) : undefined;
  const caseInsensitive = toolInput['-i'] as boolean | undefined;

  // Get result info
  const resultBlock = result?.contentBlock?.type === 'tool_result'
    ? (result.contentBlock as ToolResultBlock)
    : null;
  const hasResult = !!resultBlock;
  const resultContent = resultBlock?.content || '';
  const isError = resultBlock?.isError || false;

  // Calculate phase
  const hasInput = !inputIsStreaming && !!pattern;
  const phase = calculateToolPhase(streaming, hasInput, inputIsStreaming, hasResult, isError);

  // Format display path
  const displayPath = formatRelativePath(path);

  // Parse results to count matches (safely handle non-string content)
  const safeResultContent = ensureString(resultContent);
  const resultLines = safeResultContent.split('\n').filter(line => line.trim());
  const matchCount = resultLines.length;

  // Header content: pattern, path, and match count
  const headerContent = pattern ? (
    <>
      <code className="tool-pattern">/{pattern}/</code>
      <span className="tool-in-label">in</span>
      <code className="tool-search-path">{displayPath}</code>
      {glob && <code className="tool-glob">{glob}</code>}
      {caseInsensitive && <span className="tool-badge">-i</span>}
      {hasResult && !isError && matchCount > 0 && (
        <span className="tool-match-count">{matchCount} match{matchCount !== 1 ? 'es' : ''}</span>
      )}
    </>
  ) : inputIsStreaming ? (
    <span className="tool-building">building...</span>
  ) : null;

  // Show all results (no truncation)
  const displayContent = resultContent;

  // Raw data for debugging mode
  const rawData = { turn, result };

  return (
    <BaseToolCard
      toolName="Grep"
      headerContent={headerContent}
      phase={phase}
      tokens={tokens}
      order={turn.order}
      orderEnd={result?.order}
      className="grep-card"
      rawData={rawData}
      timestamp={turn.timestamp}
    >
      {hasResult && (
        <>
          {isError ? (
            <pre className="tool-search-results error">
              <code>{resultContent}</code>
            </pre>
          ) : (
            <GrepHighlightedResults
              content={displayContent}
              pattern={pattern}
            />
          )}
        </>
      )}
      {!hasResult && phase === 'executing' && (
        <div className="tool-executing">Searching...</div>
      )}
    </BaseToolCard>
  );
});

export default GrepCard;
