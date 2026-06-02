/**
 * WriteCard - File creation/write display
 *
 * Design goals:
 * - File path in header
 * - Show preview of content being written with syntax highlighting
 * - Success/error indication
 */

import React from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import { BaseToolCard, calculateToolPhase, formatRelativePath } from './BaseToolCard';
import { LazySyntaxHighlightedCode } from './SyntaxHighlighter';
import { getStringInput } from './toolInputUtils';
import './cards.css';

interface WriteCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
}

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

export const WriteCard = React.memo(function WriteCard({ turn, result }: WriteCardProps) {
  const { contentBlock, streaming, tokens } = turn;

  // Extract tool info
  const toolUseBlock = contentBlock?.type === 'tool_use'
    ? (contentBlock as ToolUseBlock)
    : null;

  const toolInput = toolUseBlock?.input || {};
  const inputIsStreaming = isStreamingInput(toolInput);

  // Extract Write-specific inputs (with defensive string conversion for malformed data)
  const filePath = getStringInput(toolInput, 'file_path');
  const content = getStringInput(toolInput, 'content');

  // Get result info
  const resultBlock = result?.contentBlock?.type === 'tool_result'
    ? (result.contentBlock as ToolResultBlock)
    : null;
  const hasResult = !!resultBlock;
  const resultContent = resultBlock?.content || '';
  const isError = resultBlock?.isError || false;

  // Calculate phase
  const hasInput = !inputIsStreaming && !!filePath;
  const phase = calculateToolPhase(streaming, hasInput, inputIsStreaming, hasResult, isError);

  // Format display path
  const displayPath = formatRelativePath(filePath);

  // Count lines for info
  const lineCount = content ? content.split('\n').length : 0;

  // Header content
  const headerContent = filePath ? (
    <>
      <code className="tool-file-path">{displayPath}</code>
      {lineCount > 0 && <span className="tool-line-count">{lineCount} lines</span>}
    </>
  ) : inputIsStreaming ? (
    <span className="tool-building">building...</span>
  ) : null;

  // Show all content (no truncation)
  const previewContent = content;

  // Raw data for debugging mode
  const rawData = { turn, result };

  return (
    <BaseToolCard
      toolName="Write"
      headerContent={headerContent}
      phase={phase}
      tokens={tokens}
      order={turn.order}
      orderEnd={result?.order}
      className="write-card"
      rawData={rawData}
      timestamp={turn.timestamp}
      dataAttributes={{
        'data-turn-id': turn.turnId,
        'data-file-path': filePath || undefined,
      }}
      minimapKind="write"
      minimapLabel={filePath ? `Write · ${formatRelativePath(filePath)}` : 'Write'}
    >
      {/* Show content preview with syntax highlighting */}
      {content && (
        <LazySyntaxHighlightedCode
          code={previewContent}
          filePath={filePath}
          showLineNumbers={true}
        />
      )}

      {/* Show streaming indicator while building */}
      {inputIsStreaming && (
        <div className="tool-building-content">
          <span className="streaming-dots">
            <span className="dot">●</span>
            <span className="dot">●</span>
            <span className="dot">●</span>
          </span>
          <span>Building content...</span>
        </div>
      )}

      {/* Show result/error message */}
      {hasResult && (
        <div className={`tool-result-message ${isError ? 'error' : 'success'}`}>
          {isError ? '✗ ' : '✓ '}{resultContent || (isError ? 'Write failed' : 'File written')}
        </div>
      )}

      {/* Executing state */}
      {!hasResult && phase === 'executing' && (
        <div className="tool-executing">Writing file...</div>
      )}
    </BaseToolCard>
  );
});

export default WriteCard;
