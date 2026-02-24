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
import { SyntaxHighlightedCode } from './SyntaxHighlighter';
import './cards.css';

interface WriteCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
}

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

export function WriteCard({ turn, result }: WriteCardProps) {
  const { contentBlock, streaming, tokens } = turn;

  // Extract tool info
  const toolUseBlock = contentBlock?.type === 'tool_use'
    ? (contentBlock as ToolUseBlock)
    : null;

  const toolInput = toolUseBlock?.input || {};
  const inputIsStreaming = isStreamingInput(toolInput);

  // Extract Write-specific inputs
  const filePath = (toolInput.file_path || '') as string;
  const content = (toolInput.content || '') as string;

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
    >
      {/* Show content preview with syntax highlighting */}
      {content && (
        <SyntaxHighlightedCode
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
}

export default WriteCard;
