/**
 * ToolUseCard - Renders tool_use content blocks
 *
 * Shows tool name, formatted input, and streaming status.
 * Tool input is formatted based on tool type (Edit shows diff, Bash shows command, etc.)
 */

import React, { useState, useMemo } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
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

// Formatted tool input based on tool type
function FormattedToolInput({
  toolName,
  toolInput,
}: {
  toolName: string;
  toolInput: Record<string, unknown> | string;
}) {
  const input = typeof toolInput === 'string' ? JSON.parse(toolInput || '{}') : toolInput;

  if (toolName === 'Edit') {
    const filePath = (input.file_path || '') as string;
    const oldString = (input.old_string || '') as string;
    const newString = (input.new_string || '') as string;
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
    const filePath = (input.file_path || '') as string;
    const content = (input.content || '') as string;
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
    const filePath = (input.file_path || '') as string;
    const offset = input.offset as number | undefined;
    const limit = input.limit as number | undefined;
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
    const command = (input.command || '') as string;
    const description = (input.description || '') as string;
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
    const pattern = (input.pattern || '') as string;
    const path = (input.path || '.') as string;
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
    const pattern = (input.pattern || '') as string;
    const path = (input.path || '.') as string;
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
      <code>{formatJson(input)}</code>
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

export function ToolUseCard({ turn, result }: ToolUseCardProps) {
  const { content, streaming, tokens } = turn;

  // Parse tool info from content or structured data
  // The streaming view stores tool info in the turn content as JSON during streaming
  const toolInfo = useMemo(() => {
    // First, check if we have structured tool info in the content
    if (!content) {
      return { toolName: 'Tool', toolInput: {} };
    }

    try {
      // Try to parse as JSON (tool input being streamed)
      const parsed = JSON.parse(content);
      if (parsed.name && parsed.input) {
        return { toolName: parsed.name, toolInput: parsed.input };
      }
      // Just raw input
      return { toolName: 'Tool', toolInput: parsed };
    } catch {
      // Not JSON, might be a tool name or raw content
      return { toolName: content.slice(0, 50) || 'Tool', toolInput: {} };
    }
  }, [content]);

  const { toolName, toolInput } = toolInfo;
  const hasInput = Object.keys(toolInput).length > 0;
  const hasResult = result && result.content;
  const isError = result?.contentBlockType === 'tool_result' && result.content?.startsWith('Error');

  const statusIcon = streaming ? '⏳' : hasResult ? (isError ? '✗' : '✓') : '✓';
  const statusClass = streaming ? 'executing' : isError ? 'error' : 'completed';

  return (
    <div className={`turn-card tool-use-card ${statusClass} ${streaming ? 'streaming' : ''}`}>
      <div className="turn-card-header">
        <span className={`tool-use-status ${statusClass}`}>
          {streaming ? <span className="tool-spinner">{statusIcon}</span> : statusIcon}
        </span>
        <span className="turn-label tool-name">{toolName}</span>
        {!streaming && tokens > 0 && <span className="turn-tokens">{tokens} tokens</span>}
      </div>

      {hasInput && (
        <Collapsible title="Input" defaultExpanded={true}>
          <FormattedToolInput toolName={toolName} toolInput={toolInput} />
        </Collapsible>
      )}

      {hasResult && (
        <Collapsible title={isError ? 'Error' : 'Result'} defaultExpanded={true}>
          <FormattedToolResult result={result.content} isError={isError} />
        </Collapsible>
      )}
    </div>
  );
}
