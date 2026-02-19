/**
 * ToolUseCard - Renders tool_use content blocks
 *
 * Shows tool name, formatted input, and streaming status.
 * Tool input is formatted based on tool type (Edit shows diff, Bash shows command, etc.)
 */

import React, { useState } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock } from '../../../../../generated/types';
import './cards.css';

interface ToolUseCardProps {
  turn: SessionDataTurn;
  /** Optional tool result to display inline */
  result?: SessionDataTurn | null;
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

// Collapsible component
function Collapsible({
  title,
  children,
  defaultExpanded = true,
}: {
  title: string;
  children: React.ReactNode;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div className="collapsible">
      <button
        className="collapsible-header"
        onClick={() => setExpanded(!expanded)}
        type="button"
      >
        <span className="collapsible-icon">{expanded ? '▼' : '▶'}</span>
        <span className="collapsible-title">{title}</span>
      </button>
      {expanded && <div className="collapsible-content">{children}</div>}
    </div>
  );
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
  isStreaming = false,
}: {
  toolName: string;
  toolInput: Record<string, unknown>;
  isStreaming?: boolean;
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

// Tool execution phase enum
type ToolPhase = 'building' | 'executing' | 'waiting_result' | 'completed' | 'error';

function getToolPhase(
  streaming: boolean,
  hasInput: boolean,
  isInputStreaming: boolean,
  hasResult: boolean,
  isError: boolean
): ToolPhase {
  if (isError) return 'error';
  if (hasResult) return 'completed';
  if (!streaming) return 'completed';
  if (isInputStreaming) return 'building';
  if (hasInput) return 'executing';
  return 'building';
}

function getPhaseIcon(phase: ToolPhase): string {
  switch (phase) {
    case 'building': return '⋯';
    case 'executing': return '⏳';
    case 'waiting_result': return '⏳';
    case 'completed': return '✓';
    case 'error': return '✗';
  }
}

function getPhaseLabel(phase: ToolPhase): string {
  switch (phase) {
    case 'building': return 'Building input...';
    case 'executing': return 'Executing...';
    case 'waiting_result': return 'Waiting for result...';
    case 'completed': return '';
    case 'error': return 'Failed';
  }
}

export function ToolUseCard({ turn, result }: ToolUseCardProps) {
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

  // Determine tool phase
  const phase = getToolPhase(streaming, hasInput, inputIsStreaming, hasResult, isError);
  const phaseIcon = getPhaseIcon(phase);
  const phaseLabel = getPhaseLabel(phase);

  const isActive = phase === 'building' || phase === 'executing' || phase === 'waiting_result';
  const statusClass = isError ? 'error' : isActive ? 'executing' : 'completed';

  return (
    <div className={`turn-card tool-use-card ${statusClass} ${isActive ? 'streaming' : ''}`}>
      <div className="turn-card-header">
        <span className={`tool-use-status ${statusClass}`}>
          {isActive ? <span className="tool-spinner">{phaseIcon}</span> : phaseIcon}
        </span>
        <span className="turn-label tool-name">{toolName}</span>
        {phaseLabel && <span className="tool-phase-label">{phaseLabel}</span>}
        {!isActive && tokens > 0 && <span className="turn-tokens">{tokens} tokens</span>}
      </div>

      {hasInput && (
        <Collapsible title="Input" defaultExpanded={true}>
          <FormattedToolInput toolName={toolName} toolInput={toolInput} isStreaming={inputIsStreaming} />
        </Collapsible>
      )}

      {(hasResult || resultIsStreaming) && (
        <Collapsible title={isError ? 'Error' : 'Result'} defaultExpanded={true}>
          {resultIsStreaming && !resultContent ? (
            <div className="tool-result-streaming">
              <span className="streaming-dots">
                <span className="dot">●</span>
                <span className="dot">●</span>
                <span className="dot">●</span>
              </span>
              <span>Waiting for result...</span>
            </div>
          ) : (
            <FormattedToolResult result={resultContent} isError={isError} />
          )}
        </Collapsible>
      )}
    </div>
  );
}
