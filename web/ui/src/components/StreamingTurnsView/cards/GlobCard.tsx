/**
 * GlobCard - File pattern matching display
 *
 * Design goals:
 * - Pattern in header
 * - Search directory shown inline
 * - File list shown directly
 * - Compact display
 */

import React from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import { BaseToolCard, calculateToolPhase, formatRelativePath } from './BaseToolCard';
import './cards.css';

interface GlobCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
}

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

export function GlobCard({ turn, result }: GlobCardProps) {
  const { contentBlock, streaming, tokens } = turn;

  // Extract tool info
  const toolUseBlock = contentBlock?.type === 'tool_use'
    ? (contentBlock as ToolUseBlock)
    : null;

  const toolInput = toolUseBlock?.input || {};
  const inputIsStreaming = isStreamingInput(toolInput);

  // Extract Glob-specific inputs
  const pattern = (toolInput.pattern || '') as string;
  const path = (toolInput.path || '.') as string;

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

  // Header content: pattern and path
  const headerContent = pattern ? (
    <>
      <code className="tool-pattern">{pattern}</code>
      {path !== '.' && (
        <>
          <span className="tool-in-label">in</span>
          <code className="tool-search-path">{displayPath}</code>
        </>
      )}
    </>
  ) : inputIsStreaming ? (
    <span className="tool-building">building...</span>
  ) : null;

  // Parse results to get file list
  const fileList = resultContent.split('\n').filter(line => line.trim());
  const fileCount = fileList.length;

  // Raw data for debugging mode
  const rawData = { turn, result };

  return (
    <BaseToolCard
      toolName="Glob"
      headerContent={headerContent}
      phase={phase}
      tokens={tokens}
      order={turn.order}
      orderEnd={result?.order}
      className="glob-card"
      rawData={rawData}
    >
      {hasResult && (
        <>
          {!isError && (
            <div className="tool-match-count">{fileCount} file{fileCount !== 1 ? 's' : ''}</div>
          )}
          <div className={`tool-file-list ${isError ? 'error' : ''}`}>
            {isError ? (
              <span className="error-text">{resultContent}</span>
            ) : fileCount === 0 ? (
              <span className="no-matches">No files found</span>
            ) : (
              <>
                {fileList.map((file, idx) => (
                  <div key={idx} className="tool-file-item">
                    <code>{formatRelativePath(file)}</code>
                  </div>
                ))}
              </>
            )}
          </div>
        </>
      )}
      {!hasResult && phase === 'executing' && (
        <div className="tool-executing">Finding files...</div>
      )}
    </BaseToolCard>
  );
}

export default GlobCard;
