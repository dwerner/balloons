/**
 * EditCard - Diff-focused file editing display with syntax highlighting
 *
 * Design goals:
 * - File path in header
 * - Proper unified diff display with syntax highlighting
 * - No unnecessary accordions
 * - Shows old_string vs new_string as a diff
 */

import React, { useMemo } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import { BaseToolCard, calculateToolPhase, formatRelativePath } from './BaseToolCard';
import { LazyDiffHighlightedCode, LazySyntaxHighlightedCode, getLanguageFromPath } from './SyntaxHighlighter';
import { getStringInputWithFallback, ensureString } from './toolInputUtils';
import './cards.css';

interface EditCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
}

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

/**
 * Generate a proper unified diff between two strings
 */
function generateUnifiedDiff(oldStr: string, newStr: string, filePath: string): string[] {
  // Handle empty strings
  if (!oldStr && !newStr) {
    return [];
  }

  // Ensure we have strings (defensive for malformed input)
  const safeOldStr = ensureString(oldStr);
  const safeNewStr = ensureString(newStr);
  const safeFilePath = ensureString(filePath);

  const oldLines = safeOldStr ? safeOldStr.split('\n') : [];
  const newLines = safeNewStr ? safeNewStr.split('\n') : [];
  const fileName = safeFilePath.split('/').pop() || safeFilePath;

  const result: string[] = [];
  result.push(`--- a/${fileName}`);
  result.push(`+++ b/${fileName}`);

  // Simple line-by-line diff (can be improved with proper diff algorithm)
  // For now, show all old lines as removed and all new lines as added
  // This gives correct output even if the naive comparison fails

  // Find common prefix
  let commonPrefix = 0;
  while (
    commonPrefix < oldLines.length &&
    commonPrefix < newLines.length &&
    oldLines[commonPrefix] === newLines[commonPrefix]
  ) {
    commonPrefix++;
  }

  // Find common suffix (from the end)
  let commonSuffix = 0;
  while (
    commonSuffix < oldLines.length - commonPrefix &&
    commonSuffix < newLines.length - commonPrefix &&
    oldLines[oldLines.length - 1 - commonSuffix] === newLines[newLines.length - 1 - commonSuffix]
  ) {
    commonSuffix++;
  }

  // Context lines before change
  const contextBefore = Math.min(3, commonPrefix);
  for (let i = commonPrefix - contextBefore; i < commonPrefix; i++) {
    if (i >= 0) {
      result.push(` ${oldLines[i]}`);
    }
  }

  // Changed lines from old (removed)
  for (let i = commonPrefix; i < oldLines.length - commonSuffix; i++) {
    result.push(`-${oldLines[i]}`);
  }

  // Changed lines from new (added)
  for (let i = commonPrefix; i < newLines.length - commonSuffix; i++) {
    result.push(`+${newLines[i]}`);
  }

  // Context lines after change
  const contextAfter = Math.min(3, commonSuffix);
  for (let i = 0; i < contextAfter; i++) {
    const idx = oldLines.length - commonSuffix + i;
    if (idx < oldLines.length) {
      result.push(` ${oldLines[idx]}`);
    }
  }

  return result;
}

export const EditCard = React.memo(function EditCard({ turn, result }: EditCardProps) {
  const { contentBlock, streaming, tokens } = turn;

  // Extract tool info
  const toolUseBlock = contentBlock?.type === 'tool_use'
    ? (contentBlock as ToolUseBlock)
    : null;

  const toolInput = toolUseBlock?.input || {};
  const inputIsStreaming = isStreamingInput(toolInput);

  // Extract Edit-specific inputs (support both snake_case and camelCase, with safe string conversion)
  const filePath = getStringInputWithFallback(toolInput, ['file_path', 'filePath']);
  const oldString = getStringInputWithFallback(toolInput, ['old_string', 'oldString']);
  const newString = getStringInputWithFallback(toolInput, ['new_string', 'newString']);
  const replaceAll = (toolInput.replace_all ?? toolInput.replaceAll) as boolean | undefined;

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

  // Generate diff
  const diffLines = useMemo(() => {
    if (!oldString && !newString) return [];
    return generateUnifiedDiff(oldString, newString, filePath);
  }, [oldString, newString, filePath]);

  // Format display path
  const displayPath = formatRelativePath(filePath);

  // Header content
  const headerContent = filePath ? (
    <>
      <code className="tool-file-path">{displayPath}</code>
      {replaceAll && <span className="tool-badge">replace all</span>}
    </>
  ) : inputIsStreaming ? (
    <span className="tool-building">building...</span>
  ) : null;

  // Raw data for debugging mode
  const rawData = { turn, result };

  return (
    <BaseToolCard
      toolName="Edit"
      dataAttributes={{
        'data-turn-id': turn.turnId,
        'data-file-path': filePath || undefined,
      }}
      minimapKind="edit"
      minimapLabel={filePath ? `Edit · ${formatRelativePath(filePath)}` : 'Edit'}
      headerContent={headerContent}
      phase={phase}
      tokens={tokens}
      order={turn.order}
      orderEnd={result?.order}
      className="edit-card"
      rawData={rawData}
      timestamp={turn.timestamp}
    >
      {/* Show diff when we have input */}
      {diffLines.length > 0 ? (
        <LazyDiffHighlightedCode diffLines={diffLines} filePath={filePath} />
      ) : (oldString || newString) && !inputIsStreaming ? (
        /* Show raw strings with syntax highlighting if we have them but diff is empty */
        <div className="tool-edit-raw">
          {oldString && (
            <div className="tool-edit-section">
              <div className="tool-edit-label">Old:</div>
              <LazySyntaxHighlightedCode
                code={oldString}
                filePath={filePath}
              />
            </div>
          )}
          {newString && (
            <div className="tool-edit-section">
              <div className="tool-edit-label">New:</div>
              <LazySyntaxHighlightedCode
                code={newString}
                filePath={filePath}
              />
            </div>
          )}
        </div>
      ) : filePath && !inputIsStreaming && hasResult && !oldString && !newString ? (
        /* No input strings available */
        <div className="tool-edit-missing">
          <span className="tool-warning">⚠</span>
          <span>Edit input missing - old_string and new_string not available</span>
        </div>
      ) : null}

      {/* Show streaming indicator while building */}
      {inputIsStreaming && (
        <div className="tool-building-content">
          <span className="streaming-dots">
            <span className="dot">●</span>
            <span className="dot">●</span>
            <span className="dot">●</span>
          </span>
          <span>Building edit...</span>
        </div>
      )}

      {/* Show result/error message */}
      {hasResult && resultContent && (
        <div className={`tool-result-message ${isError ? 'error' : 'success'}`}>
          {isError ? '✗ ' : '✓ '}{resultContent}
        </div>
      )}

      {/* Executing state */}
      {!hasResult && phase === 'executing' && diffLines.length > 0 && (
        <div className="tool-executing">Applying edit...</div>
      )}
    </BaseToolCard>
  );
});

export default EditCard;
