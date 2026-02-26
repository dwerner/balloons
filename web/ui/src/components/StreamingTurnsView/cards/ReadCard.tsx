/**
 * ReadCard - Compact file reading display with syntax highlighting
 *
 * Design goals:
 * - File path in header (relative to working dir)
 * - Line range shown inline if specified
 * - No "Input" accordion - path IS the input
 * - No "Result" header - content shown directly
 * - Syntax highlighting based on file extension
 * - Left-justified output
 */

import React from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import { BaseToolCard, calculateToolPhase, formatRelativePath } from './BaseToolCard';
import { LazySyntaxHighlightedCode } from './SyntaxHighlighter';
import './cards.css';

interface ReadCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
}

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

export const ReadCard = React.memo(function ReadCard({ turn, result }: ReadCardProps) {
  const { contentBlock, streaming, tokens } = turn;

  // Extract tool info
  const toolUseBlock = contentBlock?.type === 'tool_use'
    ? (contentBlock as ToolUseBlock)
    : null;

  const toolInput = toolUseBlock?.input || {};
  const inputIsStreaming = isStreamingInput(toolInput);

  // Extract Read-specific inputs (support both snake_case and camelCase)
  const filePath = (toolInput.file_path || toolInput.filePath || '') as string;
  const offset = (toolInput.offset) as number | undefined;
  const limit = (toolInput.limit) as number | undefined;

  // Format line range for display
  let lineRange = '';
  if (offset !== undefined && limit !== undefined) {
    lineRange = ` [${offset + 1}-${offset + limit}]`;
  } else if (offset !== undefined) {
    lineRange = ` [from line ${offset + 1}]`;
  } else if (limit !== undefined) {
    lineRange = ` [first ${limit} lines]`;
  }

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

  // Format the display path
  const displayPath = formatRelativePath(filePath);

  // Header content: file path with optional line range
  // Always show the path when we have it, or indicate the state otherwise
  const headerContent = (() => {
    if (filePath) {
      return (
        <>
          <code className="tool-file-path">{displayPath}</code>
          {lineRange && <span className="tool-line-range">{lineRange}</span>}
        </>
      );
    }
    if (inputIsStreaming) {
      return <span className="tool-building">building...</span>;
    }
    // If no file path, show debug info about what we do have
    const inputKeys = Object.keys(toolInput);
    if (inputKeys.length > 0) {
      // Input exists but file_path not found - show what keys we have
      return <span className="tool-description">({inputKeys.join(', ')})</span>;
    }
    if (hasResult) {
      return <span className="tool-description">(reading file)</span>;
    }
    return null;
  })();

  // Strip line number prefixes from Read output
  // Balloons Read tool adds prefixes like "     1→" (spaces + number + arrow)
  // We need to strip these for proper syntax highlighting
  const stripLineNumberPrefixes = (content: string): string => {
    return content
      .split('\n')
      .map(line => {
        // Match pattern: optional spaces + digits + arrow (→) + content
        // Format: "     1→content" or "   123→content"
        const match = line.match(/^\s*\d+→(.*)$/);
        return match ? match[1] : line;
      })
      .join('\n');
  };

  // Show all content (no truncation)
  const displayContent = stripLineNumberPrefixes(resultContent);

  // Raw data for debugging mode
  const rawData = { turn, result };

  return (
    <BaseToolCard
      toolName="Read"
      headerContent={headerContent}
      phase={phase}
      tokens={tokens}
      order={turn.order}
      orderEnd={result?.order}
      className="read-card"
      rawData={rawData}
      timestamp={turn.timestamp}
    >
      {hasResult && (
        <LazySyntaxHighlightedCode
          code={displayContent}
          filePath={filePath}
          showLineNumbers={true}
        />
      )}
      {!hasResult && phase === 'executing' && (
        <div className="tool-executing">Reading file...</div>
      )}
    </BaseToolCard>
  );
});

export default ReadCard;
