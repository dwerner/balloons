/**
 * ToolUseCard - Renders tool_use content blocks
 *
 * Generic fallback for tool types that don't have specialized cards.
 * Shows tool name, formatted input, and streaming status.
 * Tool input is formatted based on tool type (Edit shows diff, Bash shows command, etc.)
 *
 * Uses BaseToolCard for consistent collapsible behavior.
 */

import React from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import { BaseToolCard, calculateToolPhase, type ToolCardDisplayMode } from './BaseToolCard';
import './cards.css';

interface ToolUseCardProps {
  turn: SessionDataTurn;
  /** Optional tool result to display inline */
  result?: SessionDataTurn | null;
  /** Display mode: formatted (default), collapsed, or raw for debugging */
  displayMode?: ToolCardDisplayMode;
}

// File extension to language mapping
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

// Check if tool input is still streaming (partial JSON)
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

// Get partial JSON from streaming input
function getStreamingJson(input: Record<string, unknown>): string {
  return (input._streaming as string) || '';
}

// Generate simple diff
function generateDiff(oldStr: string, newStr: string, filePath: string): string[] {
  const oldLines = oldStr.split('\n');
  const newLines = newStr.split('\n');
  const fileName = filePath.split('/').pop() || filePath;

  const result: string[] = [];
  result.push(`--- a/${fileName}`);
  result.push(`+++ b/${fileName}`);

  let oldIdx = 0;
  let newIdx = 0;

  while (oldIdx < oldLines.length || newIdx < newLines.length) {
    if (oldIdx >= oldLines.length) {
      result.push(`+${newLines[newIdx]}`);
      newIdx++;
    } else if (newIdx >= newLines.length) {
      result.push(`-${oldLines[oldIdx]}`);
      oldIdx++;
    } else if (oldLines[oldIdx] === newLines[newIdx]) {
      result.push(` ${oldLines[oldIdx]}`);
      oldIdx++;
      newIdx++;
    } else {
      result.push(`-${oldLines[oldIdx]}`);
      oldIdx++;
      if (newIdx < newLines.length && (oldIdx >= oldLines.length || newLines[newIdx] !== oldLines[oldIdx])) {
        result.push(`+${newLines[newIdx]}`);
        newIdx++;
      }
    }
  }

  return result;
}

// Streaming input indicator
function StreamingInputIndicator({ partialJson }: { partialJson: string }) {
  // Try to extract tool name or file path from partial JSON for context
  const fileMatch = partialJson.match(/"file_path"\s*:\s*"([^"]+)"/);
  const commandMatch = partialJson.match(/"command"\s*:\s*"([^"]+)"/);
  const patternMatch = partialJson.match(/"pattern"\s*:\s*"([^"]+)"/);

  let hint = '';
  if (fileMatch && fileMatch[1]) {
    hint = fileMatch[1];
  } else if (commandMatch && commandMatch[1]) {
    hint = commandMatch[1].substring(0, 50);
  } else if (patternMatch && patternMatch[1]) {
    hint = patternMatch[1];
  }

  return (
    <div className="streaming-input-indicator">
      <div className="streaming-input-header">
        <span className="streaming-dots">
          <span className="dot">●</span>
          <span className="dot">●</span>
          <span className="dot">●</span>
        </span>
        <span className="streaming-label">Building input...</span>
      </div>
      {hint && (
        <code className="streaming-hint">{hint}</code>
      )}
      <pre className="streaming-json">
        <code>{partialJson || '{'}</code>
      </pre>
    </div>
  );
}

// Formatted tool input based on tool type
function FormattedToolInput({
  toolName,
  toolInput,
}: {
  toolName: string;
  toolInput: Record<string, unknown>;
}) {
  // Handle streaming input - show partial JSON
  if (isStreamingInput(toolInput)) {
    return <StreamingInputIndicator partialJson={getStreamingJson(toolInput)} />;
  }
  if (toolName === 'Edit') {
    const filePath = (toolInput.file_path || '') as string;
    const oldString = (toolInput.old_string || '') as string;
    const newString = (toolInput.new_string || '') as string;
    const diffLines = generateDiff(oldString, newString, filePath);

    return (
      <div className="tool-input-formatted">
        <div className="tool-input-header">
          <span className="tool-input-label">Edit</span>
          <code className="tool-input-path">{filePath}</code>
        </div>
        <div className="diff-view">
          {diffLines.map((line, idx) => {
            let className = 'diff-line diff-context';
            if (line.startsWith('+++') || line.startsWith('---')) {
              className = 'diff-line diff-header';
            } else if (line.startsWith('+')) {
              className = 'diff-line diff-add';
            } else if (line.startsWith('-')) {
              className = 'diff-line diff-remove';
            }
            return (
              <div key={idx} className={className}>
                {line}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  if (toolName === 'Write') {
    const filePath = (toolInput.file_path || '') as string;
    const content = (toolInput.content || '') as string;
    const language = guessLanguage(filePath);
    const truncated = content.length > 1000;
    const displayContent = truncated ? content.slice(0, 1000) + '\n... [truncated]' : content;

    return (
      <div className="tool-input-formatted">
        <div className="tool-input-header">
          <span className="tool-input-label">Write</span>
          <code className="tool-input-path">{filePath}</code>
        </div>
        <pre className="tool-code-block" data-language={language}>
          <code>{displayContent}</code>
        </pre>
      </div>
    );
  }

  if (toolName === 'Read') {
    const filePath = (toolInput.file_path || '') as string;
    const offset = toolInput.offset as number | undefined;
    const limit = toolInput.limit as number | undefined;
    let rangeInfo = '';
    if (offset || limit) {
      const start = offset || 1;
      if (limit) {
        rangeInfo = ` (lines ${start}-${(offset || 0) + limit})`;
      } else {
        rangeInfo = ` (from line ${start})`;
      }
    }
    return (
      <div className="tool-input-formatted">
        <div className="tool-input-header">
          <span className="tool-input-label">Read</span>
          <code className="tool-input-path">
            {filePath}
            {rangeInfo}
          </code>
        </div>
      </div>
    );
  }

  if (toolName === 'Bash') {
    const command = (toolInput.command || '') as string;
    const description = (toolInput.description || '') as string;
    return (
      <div className="tool-input-formatted">
        <div className="tool-input-header">
          <span className="tool-input-label">Bash</span>
          {description && <span className="tool-input-desc">{description}</span>}
        </div>
        <pre className="tool-code-block" data-language="bash">
          <code>{command}</code>
        </pre>
      </div>
    );
  }

  if (toolName === 'Glob') {
    const pattern = (toolInput.pattern || '') as string;
    const path = (toolInput.path || '.') as string;
    return (
      <div className="tool-input-formatted">
        <div className="tool-input-header">
          <span className="tool-input-label">Glob</span>
          <code className="tool-input-path">{pattern}</code>
          <span className="tool-input-in">in</span>
          <code className="tool-input-path">{path}</code>
        </div>
      </div>
    );
  }

  if (toolName === 'Grep') {
    const pattern = (toolInput.pattern || '') as string;
    const path = (toolInput.path || '.') as string;
    return (
      <div className="tool-input-formatted">
        <div className="tool-input-header">
          <span className="tool-input-label">Grep</span>
          <code className="tool-input-path">{pattern}</code>
          <span className="tool-input-in">in</span>
          <code className="tool-input-path">{path}</code>
        </div>
      </div>
    );
  }

  // Default: show formatted JSON
  return (
    <pre className="tool-use-json">
      <code>{formatJson(toolInput)}</code>
    </pre>
  );
}

// Formatted tool result
function FormattedToolResult({
  result,
  isError,
}: {
  result: string;
  isError?: boolean;
}) {
  const truncated = result.length > 5000;
  const displayResult = truncated ? result.slice(0, 5000) + '\n... [truncated]' : result;

  return (
    <pre className={`tool-result-output ${isError ? 'error' : ''}`}>
      <code>{displayResult}</code>
    </pre>
  );
}

// Build header content based on tool type
function buildHeaderContent(
  toolName: string,
  toolInput: Record<string, unknown>,
  inputIsStreaming: boolean
): React.ReactNode {
  if (inputIsStreaming) {
    return <span className="tool-building">building...</span>;
  }

  switch (toolName) {
    case 'Edit': {
      const filePath = (toolInput.file_path || '') as string;
      return filePath ? <code className="tool-file-path">{filePath}</code> : null;
    }
    case 'Write': {
      const filePath = (toolInput.file_path || '') as string;
      return filePath ? <code className="tool-file-path">{filePath}</code> : null;
    }
    case 'Read': {
      const filePath = (toolInput.file_path || '') as string;
      return filePath ? <code className="tool-file-path">{filePath}</code> : null;
    }
    case 'Bash': {
      const description = (toolInput.description || '') as string;
      const command = (toolInput.command || '') as string;
      if (description) {
        return <span className="tool-description">{description}</span>;
      }
      if (command) {
        const shortCmd = command.length > 50 ? command.slice(0, 50) + '...' : command;
        return <code className="tool-command-preview">{shortCmd}</code>;
      }
      return null;
    }
    case 'Glob': {
      const pattern = (toolInput.pattern || '') as string;
      return pattern ? <code className="tool-pattern">{pattern}</code> : null;
    }
    case 'Grep': {
      const pattern = (toolInput.pattern || '') as string;
      return pattern ? <code className="tool-pattern">{pattern}</code> : null;
    }
    default:
      return null;
  }
}

export function ToolUseCard({ turn, result, displayMode = 'formatted' }: ToolUseCardProps) {
  const { contentBlock, streaming, tokens } = turn;

  // Extract tool info from contentBlock
  const toolUseBlock = contentBlock?.type === 'tool_use'
    ? (contentBlock as ToolUseBlock)
    : null;

  const toolName = toolUseBlock?.name || 'Tool';
  const toolInput = toolUseBlock?.input || {};
  const inputIsStreaming = isStreamingInput(toolInput);
  // hasInput is true if we have real keys (not just _streaming) or if we're streaming
  const hasInput = inputIsStreaming || Object.keys(toolInput).filter(k => k !== '_streaming').length > 0;

  // Get result info if available
  const resultBlock = result?.contentBlock?.type === 'tool_result'
    ? (result.contentBlock as ToolResultBlock)
    : null;
  const resultIsStreaming = result?.streaming ?? false;
  const hasResult = !!resultBlock;
  const resultContent = resultBlock?.content || '';
  const isError = resultBlock?.isError || false;

  // Determine tool phase using the shared utility
  const phase = calculateToolPhase(streaming, hasInput, inputIsStreaming, hasResult, isError);

  // Build header content based on tool type
  const headerContent = buildHeaderContent(toolName, toolInput, inputIsStreaming);

  // Build raw data for debugging mode (user can toggle to this via the mode switcher)
  const rawData = { turn, result };

  return (
    <BaseToolCard
      toolName={toolName}
      headerContent={headerContent}
      phase={phase}
      tokens={tokens}
      className="tool-use-card-v2"
      initialDisplayMode={displayMode}
      rawData={rawData}
    >
      {/* Tool input section */}
      {hasInput && !inputIsStreaming && (
        <FormattedToolInput toolName={toolName} toolInput={toolInput} />
      )}

      {/* Streaming input indicator */}
      {inputIsStreaming && (
        <StreamingInputIndicator partialJson={getStreamingJson(toolInput)} />
      )}

      {/* Tool result */}
      {hasResult && (
        <div className="tool-result-section">
          <FormattedToolResult result={resultContent} isError={isError} />
        </div>
      )}

      {/* Waiting for result indicator */}
      {resultIsStreaming && !resultContent && (
        <div className="tool-result-streaming">
          <span className="streaming-dots">
            <span className="dot">●</span>
            <span className="dot">●</span>
            <span className="dot">●</span>
          </span>
          <span>Waiting for result...</span>
        </div>
      )}

      {/* Executing state */}
      {!hasResult && !resultIsStreaming && phase === 'executing' && (
        <div className="tool-executing">Executing...</div>
      )}
    </BaseToolCard>
  );
}
