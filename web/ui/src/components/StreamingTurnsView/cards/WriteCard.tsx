/**
 * WriteCard - File creation/write display
 *
 * Design goals:
 * - File path in header
 * - Show preview of content being written
 * - Success/error indication
 */

import React from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import { BaseToolCard, calculateToolPhase, formatRelativePath } from './BaseToolCard';
import './cards.css';

interface WriteCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
}

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

// File extension to language mapping for syntax hints
const EXT_TO_LANGUAGE: Record<string, string> = {
  '.py': 'python',
  '.js': 'javascript',
  '.ts': 'typescript',
  '.tsx': 'tsx',
  '.jsx': 'jsx',
  '.rs': 'rust',
  '.go': 'go',
  '.rb': 'ruby',
  '.java': 'java',
  '.c': 'c',
  '.cpp': 'cpp',
  '.css': 'css',
  '.html': 'html',
  '.json': 'json',
  '.yaml': 'yaml',
  '.yml': 'yaml',
  '.md': 'markdown',
  '.sh': 'bash',
  '.sql': 'sql',
};

function guessLanguage(filePath: string): string {
  const ext = filePath.slice(filePath.lastIndexOf('.')).toLowerCase();
  return EXT_TO_LANGUAGE[ext] || 'text';
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
  const language = guessLanguage(filePath);

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

  // Truncate content preview
  const maxPreviewLines = 20;
  const contentLines = content.split('\n');
  const truncated = contentLines.length > maxPreviewLines;
  const previewContent = truncated
    ? contentLines.slice(0, maxPreviewLines).join('\n') + '\n... [truncated]'
    : content;

  // Raw data for debugging mode
  const rawData = { turn, result };

  return (
    <BaseToolCard
      toolName="Write"
      headerContent={headerContent}
      phase={phase}
      tokens={tokens}
      className="write-card"
      rawData={rawData}
    >
      {/* Show content preview */}
      {content && (
        <pre className="tool-write-content" data-language={language}>
          <code>{previewContent}</code>
        </pre>
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
