import React, { useState, useEffect, useCallback, useRef, memo, useMemo } from 'react';
import { BalloonsClient } from '../../generated/balloons-client';
import type { ConnectionState, SessionInfo, TurnInfo, TaskInfo, Unsubscribe, ToolUseStartedEvent, ToolInputDeltaEvent, ToolResultEvent, ContentDeltaEvent, TurnStartedEvent, TurnFinishedEvent } from '../../generated/balloons-client';
import { MarkdownContent } from './MarkdownContent';
import { AppLayout, useLayout, useTheme } from './components/layout';
import { SessionTreeView } from './components/SessionTreeView';
import { SessionStatusBar } from './components/SessionStatusBar';
import { StreamingStatusBar } from './components/StreamingStatusBar';
import { ExchangeListView } from './components/ExchangeView';
import { useWakeLock } from './hooks';

// View mode for conversation display
type ConversationViewMode = 'turns' | 'exchange';

// Tool use state tracked during streaming
interface ToolUseState {
  toolUseId: string;
  toolName: string;
  turnIndex: number;
  toolIndex: number;
  exchangeId?: string;  // Used for matching tool uses to assistant turns
  status: 'streaming' | 'executing' | 'completed' | 'error';
  inputJson: string;
  result?: string;
  isError?: boolean;
  startTime: number;
  endTime?: number;
}

// Image attachment state
interface ImageAttachment {
  id: string;
  file: File;
  previewUrl: string;
  uploading: boolean;
  uploaded: boolean;
  filePath?: string;
  mediaType: string;
  width?: number;
  height?: number;
  error?: string;
}

// Collapsible component for tool input/output
const Collapsible = memo(function Collapsible({
  title,
  children,
  defaultExpanded = true  // Default to expanded now
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
      {expanded && (
        <div className="collapsible-content">
          {children}
        </div>
      )}
    </div>
  );
});

// File extension to language mapping for syntax highlighting
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
  '.h': 'c',
  '.hpp': 'cpp',
  '.css': 'css',
  '.html': 'html',
  '.json': 'json',
  '.yaml': 'yaml',
  '.yml': 'yaml',
  '.md': 'markdown',
  '.sh': 'bash',
  '.bash': 'bash',
  '.sql': 'sql',
};

// Guess language from file path
const guessLanguage = (filePath: string): string => {
  const ext = filePath.slice(filePath.lastIndexOf('.')).toLowerCase();
  return EXT_TO_LANGUAGE[ext] || 'text';
};

// Format JSON for display (shared utility)
const formatJson = (json: string | Record<string, unknown>) => {
  try {
    if (typeof json === 'string') {
      const parsed = JSON.parse(json);
      return JSON.stringify(parsed, null, 2);
    }
    return JSON.stringify(json, null, 2);
  } catch {
    // If not valid JSON yet (streaming), just return as-is
    return typeof json === 'string' ? json : JSON.stringify(json);
  }
};

// Generate unified diff between two strings
const generateDiff = (oldStr: string, newStr: string, filePath: string): string[] => {
  const oldLines = oldStr.split('\n');
  const newLines = newStr.split('\n');
  const fileName = filePath.split('/').pop() || filePath;

  const result: string[] = [];
  result.push(`--- a/${fileName}`);
  result.push(`+++ b/${fileName}`);

  // Simple diff algorithm - find changes
  let oldIdx = 0;
  let newIdx = 0;

  while (oldIdx < oldLines.length || newIdx < newLines.length) {
    if (oldIdx >= oldLines.length) {
      // Rest are additions
      result.push(`+${newLines[newIdx]}`);
      newIdx++;
    } else if (newIdx >= newLines.length) {
      // Rest are deletions
      result.push(`-${oldLines[oldIdx]}`);
      oldIdx++;
    } else if (oldLines[oldIdx] === newLines[newIdx]) {
      // Context line
      result.push(` ${oldLines[oldIdx]}`);
      oldIdx++;
      newIdx++;
    } else {
      // Changed - show deletion then addition
      result.push(`-${oldLines[oldIdx]}`);
      oldIdx++;
      // Look ahead to see if this is a replacement or just deletion
      if (newIdx < newLines.length && (oldIdx >= oldLines.length || newLines[newIdx] !== oldLines[oldIdx])) {
        result.push(`+${newLines[newIdx]}`);
        newIdx++;
      }
    }
  }

  return result;
};

// Component for displaying formatted tool input
const FormattedToolInput = memo(function FormattedToolInput({
  toolName,
  toolInput
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
            return <div key={idx} className={className}>{line}</div>;
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
          <code className="tool-input-path">{filePath}{rangeInfo}</code>
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
});

// Component for displaying formatted tool result
const FormattedToolResult = memo(function FormattedToolResult({
  result,
  isError
}: {
  result: string;
  isError?: boolean;
}) {
  // Truncate very long results
  const truncated = result.length > 5000;
  const displayResult = truncated ? result.slice(0, 5000) + '\n... [truncated]' : result;

  return (
    <pre className={`tool-use-result ${isError ? 'error' : ''}`}>
      <code>{displayResult}</code>
    </pre>
  );
});

// Tool use component for displaying individual tool calls (streaming)
const StreamingToolUseDisplay = memo(function StreamingToolUseDisplay({ toolUse }: { toolUse: ToolUseState }) {
  const duration = toolUse.endTime
    ? ((toolUse.endTime - toolUse.startTime) / 1000).toFixed(1)
    : null;

  const statusIcon = {
    streaming: '⏳',
    executing: '⚙️',
    completed: '✓',
    error: '✗',
  }[toolUse.status];

  const statusClass = toolUse.status;

  // Parse the input JSON for formatting
  let parsedInput: Record<string, unknown> | null = null;
  if (toolUse.inputJson) {
    try {
      parsedInput = JSON.parse(toolUse.inputJson);
    } catch {
      // Still streaming, JSON incomplete
    }
  }

  return (
    <div className={`tool-use ${statusClass}`}>
      <div className="tool-use-header">
        <span className={`tool-use-status ${statusClass}`}>
          {toolUse.status === 'executing' ? (
            <span className="tool-spinner">{statusIcon}</span>
          ) : (
            statusIcon
          )}
        </span>
        <span className="tool-use-name">{toolUse.toolName}</span>
        {duration && (
          <span className="tool-use-duration">{duration}s</span>
        )}
      </div>

      {toolUse.inputJson && (
        <Collapsible title="Input" defaultExpanded={true}>
          {parsedInput ? (
            <FormattedToolInput toolName={toolUse.toolName} toolInput={parsedInput} />
          ) : (
            <pre className="tool-use-json">
              <code>{toolUse.inputJson}</code>
            </pre>
          )}
        </Collapsible>
      )}

      {toolUse.result !== undefined && (
        <Collapsible title={toolUse.isError ? "Error" : "Result"} defaultExpanded={true}>
          <FormattedToolResult result={toolUse.result} isError={toolUse.isError} />
        </Collapsible>
      )}
    </div>
  );
});

// ============================================================================
// Content Block Type-Specific Turn Renderers
// ============================================================================

// TextTurn: Renders text content blocks
const TextTurn = memo(function TextTurn({
  turn,
  streamingToolUses = []
}: {
  turn: TurnInfo;
  streamingToolUses?: ToolUseState[];
}) {
  return (
    <div className={`turn ${turn.role} ${turn.streaming ? 'streaming' : ''}`}>
      <div className="turn-role">{turn.role}</div>
      <div className="turn-content">
        {turn.role === 'user' ? (
          turn.content || '\u00A0'
        ) : (
          <MarkdownContent content={turn.content} />
        )}
      </div>
      {/* Display streaming tool uses for assistant text turns */}
      {turn.role === 'assistant' && streamingToolUses.length > 0 && (
        <div className="turn-tool-uses">
          {streamingToolUses.map(tu => (
            <StreamingToolUseDisplay key={tu.toolUseId} toolUse={tu} />
          ))}
        </div>
      )}
    </div>
  );
});

// ToolUseTurn: Renders tool_use content blocks (from loaded history)
// Includes the matching tool_result if available, to match streaming display
const ToolUseTurn = memo(function ToolUseTurn({
  turn,
  toolResult
}: {
  turn: TurnInfo;
  toolResult?: TurnInfo | null;
}) {
  const toolUse = turn.toolUse;
  if (!toolUse) {
    // Fallback if toolUse info not available
    return (
      <div className={`turn assistant tool-use-turn ${turn.streaming ? 'streaming' : ''}`}>
        <div className="turn-role">tool use</div>
        <div className="turn-content">{turn.content}</div>
      </div>
    );
  }

  // Get result content - prefer structured toolResult, fall back to turn content
  const structuredResult = toolResult?.toolResult;
  const resultContent = structuredResult?.content || toolResult?.content || '';
  const isError = structuredResult?.isError ?? false;
  const hasResult = resultContent.length > 0;

  return (
    <div className={`turn assistant tool-use-turn ${turn.streaming ? 'streaming' : ''}`}>
      <div className={`tool-use completed`}>
        <div className="tool-use-header">
          <span className={`tool-use-status ${isError ? 'error' : 'completed'}`}>
            {isError ? '✗' : '✓'}
          </span>
          <span className="tool-use-name">{toolUse.toolName}</span>
        </div>
        {toolUse.toolInput && Object.keys(toolUse.toolInput).length > 0 && (
          <Collapsible title="Input" defaultExpanded={true}>
            <FormattedToolInput toolName={toolUse.toolName} toolInput={toolUse.toolInput} />
          </Collapsible>
        )}
        {hasResult && (
          <Collapsible title={isError ? "Error" : "Result"} defaultExpanded={true}>
            <FormattedToolResult result={resultContent} isError={isError} />
          </Collapsible>
        )}
      </div>
    </div>
  );
});

// SystemTurn: Renders system-level content blocks (fork, merge, link, etc.)
const SystemTurn = memo(function SystemTurn({ turn, blockType }: { turn: TurnInfo; blockType: string }) {
  // Map block types to display info
  const displayInfo: Record<string, { label: string; className: string }> = {
    'fork': { label: '⑂ fork', className: 'system-fork' },
    'merge': { label: '⤴ merge', className: 'system-merge' },
    'merged_to': { label: '⤴ merged', className: 'system-merged-to' },
    'link': { label: '🔗 link', className: 'system-link' },
    'interruption': { label: '⚠ interrupted', className: 'system-interruption' },
    'error': { label: '✗ error', className: 'system-error' },
    'image': { label: '🖼 image', className: 'system-image' },
    'slide': { label: '📊 slide', className: 'system-slide' },
    'review': { label: '📋 review', className: 'system-review' },
    'fork_proposal': { label: '⑂ fork proposal', className: 'system-fork-proposal' },
    'merge_proposal': { label: '⤴ merge proposal', className: 'system-merge-proposal' },
    'archive': { label: '📦 archive', className: 'system-archive' },
  };

  const info = displayInfo[blockType] || { label: blockType, className: 'system-unknown' };

  return (
    <div className={`turn system ${info.className}`}>
      <div className="turn-role">{info.label}</div>
      <div className="turn-content">
        <MarkdownContent content={turn.content} />
      </div>
    </div>
  );
});

// Memoized Turn component - dispatches to appropriate renderer based on content_block_type
const Turn = memo(function Turn({
  turn,
  toolUses,
  allTurns,
  exchangeId
}: {
  turn: TurnInfo;
  toolUses?: ToolUseState[];
  allTurns?: TurnInfo[];
  exchangeId?: string;
}) {
  // Get content block type (default to 'text' for backwards compat)
  const blockType = turn.contentBlockType ?? 'text';

  // Filter streaming tool uses for this turn (only used for text assistant turns)
  const turnToolUses = toolUses?.filter(tu => {
    if (turn.exchangeId) {
      return tu.exchangeId === turn.exchangeId;
    }
    return tu.turnIndex === turn.idx;
  }) || [];

  // Dispatch to appropriate renderer based on content block type
  switch (blockType) {
    case 'tool_use': {
      // Find matching tool_result turn by toolUseId
      // Check both contentBlockType and role='tool' for compatibility with older sessions
      const toolUseId = turn.toolUse?.toolUseId;
      const matchingResult = toolUseId
        ? allTurns?.find(t =>
            (t.contentBlockType === 'tool_result' || t.role === 'tool') &&
            (t.toolResult?.toolUseId === toolUseId)
          )
        : null;
      return <ToolUseTurn turn={turn} toolResult={matchingResult} />;
    }

    case 'tool_result':
      // Skip tool_result turns - they're rendered as part of tool_use turns
      return null;

    // System-level block types (fork, merge, link, etc.)
    case 'fork':
    case 'merge':
    case 'merged_to':
    case 'link':
    case 'interruption':
    case 'error':
    case 'image':
    case 'slide':
    case 'review':
    case 'fork_proposal':
    case 'merge_proposal':
    case 'archive':
      return <SystemTurn turn={turn} blockType={blockType} />;

    case 'text':
    default:
      // Handle tool result turns that might have role='tool' but blockType='text'
      // (backwards compatibility with older sessions)
      if (turn.role === 'tool') {
        // Check if there's a matching tool_use turn that will render this
        const hasMatchingToolUse = turn.toolResult?.toolUseId
          ? allTurns?.some(t =>
              (t.contentBlockType === 'tool_use' || t.toolUse) &&
              t.toolUse?.toolUseId === turn.toolResult?.toolUseId
            )
          : false;

        if (hasMatchingToolUse) {
          // Will be rendered as part of tool_use turn
          return null;
        }

        // Standalone tool result - render it with FormattedToolResult
        return (
          <div className="turn assistant tool-use-turn">
            <div className="tool-use completed">
              <div className="tool-use-header">
                <span className="tool-use-status completed">✓</span>
                <span className="tool-use-name">Tool Result</span>
              </div>
              <Collapsible title={turn.toolResult?.isError ? "Error" : "Result"} defaultExpanded={true}>
                <FormattedToolResult result={turn.content || turn.toolResult?.content || ''} isError={turn.toolResult?.isError} />
              </Collapsible>
            </div>
          </div>
        );
      }

      // Skip empty text turns (assistant turns with no content and no streaming tool uses)
      if (turn.role === 'assistant' && !turn.content?.trim() && turnToolUses.length === 0 && !turn.streaming) {
        return null;
      }
      // For text blocks (and unknown types), use text renderer
      // Streaming tool uses are displayed inline with text assistant turns
      return <TextTurn turn={turn} streamingToolUses={turnToolUses} />;
  }
});

// Simple turn component for flat turn list view (no exchange grouping, no tool use/result merging)
const SimpleTurn = memo(function SimpleTurn({ turn }: { turn: TurnInfo }) {
  const blockType = turn.contentBlockType ?? 'text';
  const role = turn.role;

  // Render based on role and block type
  if (role === 'user') {
    return (
      <div className={`turn user`}>
        <div className="turn-role">user</div>
        <div className="turn-content">{turn.content || '\u00A0'}</div>
      </div>
    );
  }

  if (role === 'assistant') {
    // Tool use turn
    if (blockType === 'tool_use' || turn.toolUse) {
      const toolName = turn.toolUse?.toolName || 'Tool';
      return (
        <div className={`turn assistant tool-use-turn ${turn.streaming ? 'streaming' : ''}`}>
          <div className={`tool-use ${turn.streaming ? 'executing' : 'completed'}`}>
            <div className="tool-use-header">
              <span className={`tool-use-status ${turn.streaming ? 'executing' : 'completed'}`}>
                {turn.streaming ? '⚙️' : '✓'}
              </span>
              <span className="tool-use-name">{toolName}</span>
            </div>
            {turn.toolUse?.toolInput && Object.keys(turn.toolUse.toolInput).length > 0 && (
              <Collapsible title="Input" defaultExpanded={true}>
                <FormattedToolInput toolName={toolName} toolInput={turn.toolUse.toolInput} />
              </Collapsible>
            )}
          </div>
        </div>
      );
    }

    // Text turn
    return (
      <div className={`turn assistant ${turn.streaming ? 'streaming' : ''}`}>
        <div className="turn-role">assistant</div>
        <div className="turn-content">
          <MarkdownContent content={turn.content} />
        </div>
      </div>
    );
  }

  if (role === 'tool') {
    // Tool result turn
    const isError = turn.toolResult?.isError ?? false;
    const content = turn.toolResult?.content || turn.content || '';
    return (
      <div className={`turn assistant tool-use-turn`}>
        <div className={`tool-use ${isError ? 'error' : 'completed'}`}>
          <div className="tool-use-header">
            <span className={`tool-use-status ${isError ? 'error' : 'completed'}`}>
              {isError ? '✗' : '✓'}
            </span>
            <span className="tool-use-name">Tool Result</span>
          </div>
          <Collapsible title={isError ? "Error" : "Result"} defaultExpanded={true}>
            <FormattedToolResult result={content} isError={isError} />
          </Collapsible>
        </div>
      </div>
    );
  }

  // System turns (fork, merge, etc.)
  if (['fork', 'merge', 'merged_to', 'link', 'interruption', 'error', 'image', 'slide', 'review', 'fork_proposal', 'merge_proposal', 'archive'].includes(blockType)) {
    return <SystemTurn turn={turn} blockType={blockType} />;
  }

  // Fallback
  return (
    <div className={`turn ${role}`}>
      <div className="turn-role">{role || blockType}</div>
      <div className="turn-content">{turn.content || '\u00A0'}</div>
    </div>
  );
});

// Sort turns by index and deduplicate (keep latest version of each turn by idx)
function sortTurnsByIdx(turns: TurnInfo[]): TurnInfo[] {
  // Dedupe by idx - keep the last occurrence (most recent update)
  const byIdx = new Map<number, TurnInfo>();
  for (const turn of turns) {
    byIdx.set(turn.idx, turn);
  }
  return Array.from(byIdx.values()).sort((a, b) => a.idx - b.idx);
}

// Format duration in seconds to a human-readable string
function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${Math.floor(seconds)}s`;
  }
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}m ${secs}s`;
}

// Format token count with thousands separator
function formatTokens(count: number): string {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k`;
  }
  return String(count);
}

// Get WebSocket URL from environment, query param, or derive from current host
function getWsUrl(): string {
  // Check for explicit override
  if (typeof window !== 'undefined' && (window as any).BALLOONS_WS_URL) {
    return (window as any).BALLOONS_WS_URL;
  }

  // Check URL query param: ?ws=host:port
  if (typeof window !== 'undefined') {
    const params = new URLSearchParams(window.location.search);
    const wsParam = params.get('ws');
    if (wsParam) {
      return `ws://${wsParam}`;
    }

    // Default: use same host as the page, port 8765
    return `ws://${window.location.hostname}:8765`;
  }

  return 'ws://localhost:8765';
}

const WS_URL = getWsUrl();

export function App() {
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(() => {
    // Restore persisted session ID on load
    if (typeof window !== 'undefined') {
      return localStorage.getItem('balloons:selected-session');
    }
    return null;
  });
  const [turns, setTurns] = useState<TurnInfo[]>([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [queuedMessageCount, setQueuedMessageCount] = useState(0);
  const [streamingTask, setStreamingTask] = useState<TaskInfo | null>(null);
  const [toolUses, setToolUses] = useState<ToolUseState[]>([]);
  const [imageAttachments, setImageAttachments] = useState<ImageAttachment[]>([]);
  const [isLoadingTurns, setIsLoadingTurns] = useState(false);
  const [conversationViewMode, setConversationViewMode] = useState<ConversationViewMode>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('balloons:conversation-view');
      return (stored === 'exchange' || stored === 'turns') ? stored : 'exchange';
    }
    return 'exchange';
  });

  const clientRef = useRef<BalloonsClient | null>(null);
  const turnsEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Track the session we're currently loading to handle race conditions
  const loadingSessionRef = useRef<string | null>(null);

  // Auto-scroll to bottom when turns update
  // Use a small delay to allow markdown/syntax highlighting to render first
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      turnsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, 50);
    return () => clearTimeout(timeoutId);
  }, [turns]);

  // Persist selected session ID to localStorage
  useEffect(() => {
    if (selectedSessionId) {
      localStorage.setItem('balloons:selected-session', selectedSessionId);
    }
  }, [selectedSessionId]);

  // Initialize client and connect
  useEffect(() => {
    const client = new BalloonsClient(WS_URL, {
      autoReconnect: true,
      reconnectDelay: 2000,
      maxReconnectAttempts: 10,
    });
    clientRef.current = client;

    // Track connection state
    const unsubState = client.onStateChange(setConnectionState);

    // Connect
    client.connect()
      .then(async () => {
        setError(null);

        // Load initial session list
        try {
          const sessionList = await client.tree.getAllSessions();
          setSessions(sessionList);

          // Determine which session to select:
          // 1. Check for persisted session ID in localStorage
          // 2. Fall back to current session from backend
          const persistedId = localStorage.getItem('balloons:selected-session');
          const persistedSessionExists = persistedId && sessionList.some(s => s.id === persistedId);

          let sessionIdToLoad: string | null = null;

          if (persistedSessionExists) {
            // Use persisted session if it still exists
            sessionIdToLoad = persistedId;
          } else {
            // Fall back to current session from backend
            sessionIdToLoad = await client.tree.getCurrentSessionId();
          }

          if (sessionIdToLoad) {
            setSelectedSessionId(sessionIdToLoad);
            setIsLoadingTurns(true);

            // Load all session data in parallel
            const [sessionTurns, queueInfo, task] = await Promise.all([
              client.tree.getTurns(sessionIdToLoad),
              client.queue.getQueue(sessionIdToLoad),
              client.tasks.getSessionTask(sessionIdToLoad),
            ]);

            setTurns(sessionTurns);
            setQueuedMessageCount(queueInfo.messageCount);
            setStreamingTask(task);
            setIsLoadingTurns(false);
          }
        } catch (err) {
          console.error('Failed to load sessions:', err);
          setError(`Failed to load sessions: ${err}`);
        }
      })
      .catch(err => {
        console.error('Connection failed:', err);
        setError(`Connection failed: ${err.message}`);
      });

    return () => {
      unsubState();
      client.disconnect();
    };
  }, []);

  // Subscribe to events when connected
  useEffect(() => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected') return;

    const unsubscribers: Unsubscribe[] = [];

    try {
      // Session events
      unsubscribers.push(
        client.tree.onSessionAdded(async () => {
          const sessionList = await client.tree.getAllSessions();
          setSessions(sessionList);
        })
      );

      unsubscribers.push(
        client.tree.onSessionUpdated(async (data) => {
          const sessionList = await client.tree.getAllSessions();
          setSessions(sessionList);

          // NOTE: Do NOT refetch turns here for the selected session.
          // Turn updates during streaming are handled by TaskStateService events
          // (onTurnStarted, onContentDelta, onTurnFinished) which provide
          // incremental updates without duplicating turns.
          // Refetching here would cause duplicate turns because both event
          // sources would be populating the turns state simultaneously.
        })
      );

      unsubscribers.push(
        client.tree.onSessionRemoved(async (data) => {
          const sessionList = await client.tree.getAllSessions();
          setSessions(sessionList);

          if (data.sessionId === selectedSessionId) {
            setSelectedSessionId(null);
            setTurns([]);
          }
        })
      );

      // Turn events for streaming - use TaskStateService events for efficient incremental updates
      // onTurnStarted: Create a placeholder turn immediately when streaming begins
      // Note: We only create visible turns for 'user' and primary 'assistant' turns.
      // Tool-related turns (additional assistant turns for tool_use, and 'tool' role for results)
      // are handled inline within the main assistant turn via tool use events.
      //
      // IMPORTANT: These handlers check data.sessionId === selectedSessionId to filter events.
      // When switching sessions:
      // 1. handleSelectSession clears turns[] and sets isLoadingTurns=true
      // 2. The useEffect re-runs (due to selectedSessionId dependency), unsubscribing old handlers
      // 3. New handlers are subscribed with the new selectedSessionId
      // This ensures events for the wrong session are ignored during the transition.
      unsubscribers.push(
        client.tasks.onTurnStarted((data: TurnStartedEvent) => {
          if (data.sessionId === selectedSessionId) {
            // Skip creating separate turns for tool-related events
            // Tool uses are tracked separately and displayed inline in the assistant turn
            // The 'tool' role turns are for tool results which we display as part of the tool use
            if (data.role === 'tool') {
              return;
            }

            setTurns(prev => {
              // Check if turn already exists by its index
              const existing = prev.find(t => t.idx === data.turnIndex);
              if (existing) {
                // Update existing turn to streaming state
                return prev.map(t => t.idx === data.turnIndex ? {
                  idx: existing.idx,
                  role: existing.role,
                  content: existing.content,
                  streaming: true,
                  viewed: existing.viewed,
                  tokens: existing.tokens,
                  contextMode: existing.contextMode,
                  exchangeId: existing.exchangeId,
                } : t);
              }

              // Create new turn for this index
              // Note: We used to skip creating assistant turns if one already existed
              // in the same exchange, but this was wrong - each turn has a unique index
              // and should be tracked separately. Tool_use turns (which are also role=assistant)
              // have different indices than text turns.
              const placeholderTurn: TurnInfo = {
                idx: data.turnIndex,
                role: data.role,
                content: '',
                streaming: true,
                viewed: false,
                tokens: 0,
                contextMode: 'COPY',
                exchangeId: data.exchangeId,
              };
              return sortTurnsByIdx([...prev, placeholderTurn]);
            });
          }
        })
      );

      // onContentDelta: Incrementally update turn content without re-fetching
      unsubscribers.push(
        client.tasks.onContentDelta((data: ContentDeltaEvent) => {
          if (data.sessionId === selectedSessionId) {
            setTurns(prev => {
              const turnIdx = data.turnIndex;
              const existing = prev.find(t => t.idx === turnIdx);
              if (existing) {
                // Update existing turn with accumulated content
                return prev.map(t => t.idx === turnIdx ? {
                  idx: existing.idx,
                  role: existing.role,
                  content: data.accumulated,
                  streaming: true,
                  viewed: existing.viewed,
                  tokens: existing.tokens,
                  contextMode: existing.contextMode,
                  exchangeId: existing.exchangeId,
                } : t);
              }

              // Turn doesn't exist yet - create it
              // This can happen if onContentDelta arrives before onTurnStarted
              const newTurn: TurnInfo = {
                idx: turnIdx,
                role: 'assistant',
                content: data.accumulated,
                streaming: true,
                viewed: false,
                tokens: 0,
                contextMode: 'COPY',
                exchangeId: data.exchangeId,
              };
              return sortTurnsByIdx([...prev, newTurn]);
            });
          }
        })
      );

      // onTurnFinished: Finalize turn state with complete content
      unsubscribers.push(
        client.tasks.onTurnFinished((data: TurnFinishedEvent) => {
          if (data.sessionId === selectedSessionId) {
            // Skip tool result turns - they're displayed inline via tool use events
            if (data.role === 'tool') {
              return;
            }

            setTurns(prev => {
              const turnIdx = data.turnIndex;
              const existing = prev.find(t => t.idx === turnIdx);
              if (existing) {
                // Finalize existing turn
                return prev.map(t => t.idx === turnIdx ? {
                  idx: existing.idx,
                  role: data.role,
                  content: data.content,
                  streaming: false,
                  viewed: existing.viewed,
                  tokens: existing.tokens,
                  contextMode: existing.contextMode,
                  exchangeId: existing.exchangeId,
                } : t);
              }

              // Turn doesn't exist - create it with final content
              // This can happen if events arrive out of order
              const newTurn: TurnInfo = {
                idx: turnIdx,
                role: data.role,
                content: data.content,
                streaming: false,
                viewed: false,
                tokens: 0,
                contextMode: 'COPY',
                exchangeId: data.exchangeId,
              };
              return sortTurnsByIdx([...prev, newTurn]);
            });
          }
          // Also refresh session list to update streaming indicator
          client.tree.getAllSessions().then(sessionList => {
            setSessions(sessionList);
          });
        })
      );

      // Keep the tree-based onTurnUpdated for non-streaming updates (e.g., context mode changes)
      unsubscribers.push(
        client.tree.onTurnUpdated(async (data) => {
          if (data.sessionId === selectedSessionId && data.turnIdx != null) {
            const turnIdx = data.turnIdx;
            // Use setTurns callback to check streaming state without stale closure
            setTurns(prev => {
              const existingTurn = prev.find(t => t.idx === turnIdx);
              // If turn is currently streaming, skip fetch - onContentDelta handles it
              if (existingTurn?.streaming) {
                return prev;
              }
              // Fetch updated turn asynchronously and update state
              client.tree.getTurn(data.sessionId, turnIdx).then(updatedTurn => {
                if (updatedTurn) {
                  setTurns(current => {
                    const newTurns = [...current];
                    const idx = newTurns.findIndex(t => t.idx === turnIdx);
                    if (idx >= 0) {
                      newTurns[idx] = updatedTurn;
                    } else {
                      newTurns.push(updatedTurn);
                    }
                    // Sort to ensure correct order after adding/updating
                    return sortTurnsByIdx(newTurns);
                  });
                }
              });
              return prev;
            });
          }
        })
      );

      // Streaming events
      unsubscribers.push(
        client.tree.onStreamingStarted(async (data) => {
          const sessionList = await client.tree.getAllSessions();
          setSessions(sessionList);

          // Clear tool uses when a new streaming session starts
          if (data.sessionId === selectedSessionId) {
            setToolUses([]);
          }
        })
      );

      unsubscribers.push(
        client.tree.onStreamingStopped(async (data) => {
          const sessionList = await client.tree.getAllSessions();
          setSessions(sessionList);
        })
      );

      // Queue events - track queued messages for the selected session
      unsubscribers.push(
        client.queue.onMessageAdded(async (data) => {
          if (data.sessionId === selectedSessionId) {
            const queueInfo = await client.queue.getQueue(data.sessionId);
            setQueuedMessageCount(queueInfo.messageCount);
          }
        })
      );

      unsubscribers.push(
        client.queue.onMessageRemoved(async (data) => {
          if (data.sessionId === selectedSessionId) {
            const queueInfo = await client.queue.getQueue(data.sessionId);
            setQueuedMessageCount(queueInfo.messageCount);
          }
        })
      );

      unsubscribers.push(
        client.queue.onQueueDrained(async (data) => {
          if (data.sessionId === selectedSessionId) {
            // Queue was drained - messages are being processed
            const queueInfo = await client.queue.getQueue(data.sessionId);
            setQueuedMessageCount(queueInfo.messageCount);
          }
        })
      );

      unsubscribers.push(
        client.queue.onQueueCleared(async (data) => {
          if (data.sessionId === selectedSessionId) {
            setQueuedMessageCount(0);
          }
        })
      );

      // Task events - for streaming progress indicators
      unsubscribers.push(
        client.tasks.onTaskStarted(async (data) => {
          if (data.sessionId === selectedSessionId) {
            const task = await client.tasks.getTask(data.taskId);
            if (task) {
              setStreamingTask(task);
            }
          }
        })
      );

      unsubscribers.push(
        client.tasks.onTaskUpdated(async (data) => {
          if (data.sessionId === selectedSessionId) {
            const task = await client.tasks.getTask(data.taskId);
            if (task) {
              setStreamingTask(task);
            }
          }
        })
      );

      // Helper to reload turns after task ends (completion, cancel, error)
      // This ensures web UI matches TUI by discarding incremental streaming state
      const reloadTurnsAfterTaskEnd = async (sessionId: string) => {
        setStreamingTask(null);
        const sessionTurns = await client.tree.getTurns(sessionId);
        setTurns(sessionTurns);
        setToolUses([]);
      };

      unsubscribers.push(
        client.tasks.onTaskCompleted(async (data) => {
          if (data.sessionId && data.sessionId === selectedSessionId) {
            await reloadTurnsAfterTaskEnd(data.sessionId);
          }
        })
      );

      unsubscribers.push(
        client.tasks.onTaskCancelled(async (data) => {
          if (data.sessionId && data.sessionId === selectedSessionId) {
            await reloadTurnsAfterTaskEnd(data.sessionId);
          }
        })
      );

      unsubscribers.push(
        client.tasks.onTaskError(async (data) => {
          if (data.sessionId && data.sessionId === selectedSessionId) {
            await reloadTurnsAfterTaskEnd(data.sessionId);
          }
        })
      );

      // Tool use events - for visualizing tool calls during streaming
      unsubscribers.push(
        client.tasks.onToolUseStarted((data: ToolUseStartedEvent) => {
          if (data.sessionId === selectedSessionId) {
            setToolUses(prev => {
              // Check if this tool use already exists
              if (prev.some(tu => tu.toolUseId === data.toolUseId)) {
                return prev;
              }
              return [...prev, {
                toolUseId: data.toolUseId,
                toolName: data.toolName,
                turnIndex: data.turnIndex,
                toolIndex: data.toolIndex,
                exchangeId: data.exchangeId,  // Capture exchange ID for matching
                status: 'streaming',
                inputJson: '',
                startTime: Date.now(),
              }];
            });
          }
        })
      );

      unsubscribers.push(
        client.tasks.onToolInputDelta((data: ToolInputDeltaEvent) => {
          if (data.sessionId === selectedSessionId) {
            setToolUses(prev => prev.map(tu =>
              tu.toolUseId === data.toolUseId
                ? { ...tu, inputJson: tu.inputJson + data.partialJson }
                : tu
            ));
          }
        })
      );

      unsubscribers.push(
        client.tasks.onToolUse((data) => {
          if (data.sessionId === selectedSessionId) {
            setToolUses(prev => prev.map(tu =>
              tu.toolUseId === data.toolUseId
                ? {
                    ...tu,
                    status: 'executing' as const,
                    inputJson: JSON.stringify(data.toolInput),
                  }
                : tu
            ));
          }
        })
      );

      unsubscribers.push(
        client.tasks.onToolResult((data: ToolResultEvent) => {
          if (data.sessionId === selectedSessionId) {
            setToolUses(prev => prev.map(tu =>
              tu.toolUseId === data.toolUseId
                ? {
                    ...tu,
                    status: data.isError ? 'error' as const : 'completed' as const,
                    result: data.result,
                    isError: data.isError,
                    endTime: Date.now(),
                  }
                : tu
            ));
          }
        })
      );
    } catch (err) {
      console.error('Failed to set up event subscriptions:', err);
    }

    return () => {
      unsubscribers.forEach(unsub => unsub());
    };
  }, [connectionState, selectedSessionId]);

  // Select a session
  // Note: We clear state BEFORE setting the new session ID to prevent race conditions
  // where streaming events for the old session could pollute the new session's state.
  // The loading state prevents rendering partial/stale data during the transition.
  const handleSelectSession = useCallback(async (sessionId: string) => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected') return;

    // Skip if already selected (prevents unnecessary refetches)
    if (sessionId === selectedSessionId) return;

    // Track which session we're loading (for race condition detection)
    loadingSessionRef.current = sessionId;

    // Clear state immediately to prevent stale data display
    setIsLoadingTurns(true);
    setTurns([]);
    setToolUses([]);
    setStreamingTask(null);
    setQueuedMessageCount(0);
    setError(null);

    // Now set the new session ID - this triggers the event subscription useEffect
    // to re-subscribe with the new session ID
    setSelectedSessionId(sessionId);

    try {
      // Fetch all session data in parallel for faster loading
      const [sessionTurns, queueInfo, task] = await Promise.all([
        client.tree.getTurns(sessionId),
        client.queue.getQueue(sessionId),
        client.tasks.getSessionTask(sessionId),
      ]);

      // Verify this is still the session we're supposed to load
      // (user might have switched again during the async fetch)
      if (loadingSessionRef.current !== sessionId) {
        return;
      }

      // Apply the loaded data
      setTurns(sessionTurns);
      setQueuedMessageCount(queueInfo.messageCount);
      setStreamingTask(task);
      setIsLoadingTurns(false);
    } catch (err) {
      console.error('Failed to load turns:', err);
      setError(`Failed to load turns: ${err}`);
      setIsLoadingTurns(false);
    }
  }, [connectionState, selectedSessionId]);

  // Generate unique ID for image attachments
  const generateImageId = () => `img-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;

  // Upload image to server
  const uploadImage = useCallback(async (attachment: ImageAttachment): Promise<ImageAttachment> => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected') {
      return { ...attachment, error: 'Not connected' };
    }

    try {
      // Read file as base64
      const arrayBuffer = await attachment.file.arrayBuffer();
      const base64 = btoa(
        new Uint8Array(arrayBuffer).reduce((data, byte) => data + String.fromCharCode(byte), '')
      );

      // Upload via WebSocket RPC (images service)
      // Note: We need to call the images service - for now, we'll extend sessions
      // Actually, let's store the base64 data directly and let the backend handle it
      // when we submit the message

      // For now, mark as uploaded with the base64 data stored
      return {
        ...attachment,
        uploading: false,
        uploaded: true,
        // We'll send the base64 data with the message
      };
    } catch (err) {
      console.error('Failed to upload image:', err);
      return { ...attachment, uploading: false, error: `Upload failed: ${err}` };
    }
  }, [connectionState]);

  // Handle file selection (from file input or paste)
  const handleImageFiles = useCallback(async (files: FileList | File[]) => {
    const imageFiles = Array.from(files).filter(f => f.type.startsWith('image/'));
    if (imageFiles.length === 0) return;

    // Create attachments with preview URLs
    const newAttachments: ImageAttachment[] = await Promise.all(
      imageFiles.map(async (file) => {
        const previewUrl = URL.createObjectURL(file);

        // Get image dimensions
        const dimensions = await new Promise<{ width: number; height: number }>((resolve) => {
          const img = new Image();
          img.onload = () => resolve({ width: img.width, height: img.height });
          img.onerror = () => resolve({ width: 0, height: 0 });
          img.src = previewUrl;
        });

        return {
          id: generateImageId(),
          file,
          previewUrl,
          uploading: false,
          uploaded: false,
          mediaType: file.type,
          width: dimensions.width,
          height: dimensions.height,
        };
      })
    );

    setImageAttachments(prev => [...prev, ...newAttachments]);
  }, []);

  // Handle paste event
  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    const imageItems = Array.from(items).filter(item => item.type.startsWith('image/'));
    if (imageItems.length === 0) return;

    // Prevent default paste behavior for images
    e.preventDefault();

    const files = imageItems
      .map(item => item.getAsFile())
      .filter((f): f is File => f !== null);

    handleImageFiles(files);
  }, [handleImageFiles]);

  // Handle file input change
  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleImageFiles(files);
    }
    // Reset input so same file can be selected again
    e.target.value = '';
  }, [handleImageFiles]);

  // Remove an image attachment
  const removeImageAttachment = useCallback((id: string) => {
    setImageAttachments(prev => {
      const attachment = prev.find(a => a.id === id);
      if (attachment) {
        URL.revokeObjectURL(attachment.previewUrl);
      }
      return prev.filter(a => a.id !== id);
    });
  }, []);

  // Send a message
  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();

    const client = clientRef.current;
    if (!client || connectionState !== 'connected' || !selectedSessionId) {
      return;
    }

    // Allow sending with just images (no text) or just text (no images)
    const hasText = message.trim().length > 0;
    const hasImages = imageAttachments.length > 0;
    if (!hasText && !hasImages) {
      return;
    }

    const content = message.trim();
    const currentImages = [...imageAttachments];

    // Clear input state
    setMessage('');
    setImageAttachments([]);
    setError(null);

    // Check if session is currently streaming
    const session = sessions.find(s => s.id === selectedSessionId);
    const isStreaming = session?.isStreaming ?? false;

    try {
      if (isStreaming) {
        // Session is streaming - add to queue instead of submitting directly
        // Note: Image queueing not yet supported
        if (hasImages) {
          setError('Cannot queue messages with images while streaming. Please wait.');
          setMessage(content);
          setImageAttachments(currentImages);
          return;
        }
        await client.queue.addMessage(selectedSessionId, content);
      } else if (hasImages) {
        // Submit with images - need to upload images first
        // Convert images to base64 and upload
        const imageData = await Promise.all(
          currentImages.map(async (img) => {
            const arrayBuffer = await img.file.arrayBuffer();
            const base64 = btoa(
              new Uint8Array(arrayBuffer).reduce((data, byte) => data + String.fromCharCode(byte), '')
            );

            // Upload via images service
            try {
              const result = await client.images.uploadImage(
                base64,
                img.mediaType,
                selectedSessionId,
                img.file.name
              );
              return {
                file_path: result.filePath,
                media_type: result.mediaType,
                filename: result.filename,
                width: result.width || img.width || 0,
                height: result.height || img.height || 0,
              };
            } catch (uploadErr) {
              console.error('Image upload failed:', uploadErr);
              throw uploadErr;
            }
          })
        );

        // Submit message with uploaded images
        await client.sessions.submitMessageWithImages(
          selectedSessionId,
          content || 'Please analyze this image.',
          imageData
        );

        // Clean up preview URLs
        currentImages.forEach(img => URL.revokeObjectURL(img.previewUrl));
      } else {
        // Session is not streaming - submit directly (text only)
        await client.sessions.submitMessage(selectedSessionId, content);
      }
    } catch (err) {
      console.error('Failed to send message:', err);
      setError(`Failed to send message: ${err}`);
      setMessage(content);
      setImageAttachments(currentImages);
    }
  }, [connectionState, selectedSessionId, message, sessions, imageAttachments]);

  // Handle Enter key in textarea
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  }, [handleSubmit]);

  // Stop streaming
  const handleStopStreaming = useCallback(async () => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected' || !selectedSessionId) {
      return;
    }

    try {
      await client.sessions.cancelStreaming(selectedSessionId);
    } catch (err) {
      console.error('Failed to stop streaming:', err);
      setError(`Failed to stop streaming: ${err}`);
    }
  }, [connectionState, selectedSessionId]);

  const selectedSession = sessions.find(s => s.id === selectedSessionId);

  return (
    <AppLayout>
      {/* Mobile header */}
      <AppLayout.Header>
        <MobileHeader connectionState={connectionState} />
      </AppLayout.Header>

      {/* Sidebar */}
      <AppLayout.Sidebar>
        <SidebarContent
          connectionState={connectionState}
          sessions={sessions}
          selectedSessionId={selectedSessionId}
          turns={turns}
          streamingTask={streamingTask}
          onSelectSession={handleSelectSession}
          isLoadingTurns={isLoadingTurns}
        />
      </AppLayout.Sidebar>

      {/* Main content */}
      <AppLayout.Main>
        {error && (
          <div className="error-message">
            {error}
          </div>
        )}

        {!selectedSessionId ? (
          <div className="empty-state">
            <h2>No Session Selected</h2>
            <p>Select a session from the sidebar to view its conversation.</p>
          </div>
        ) : (
          <>
            {/* View mode toggle */}
            <div className="conversation-view-toggle">
              <button
                className={`view-toggle-btn ${conversationViewMode === 'exchange' ? 'active' : ''}`}
                onClick={() => {
                  setConversationViewMode('exchange');
                  localStorage.setItem('balloons:conversation-view', 'exchange');
                }}
                title="Exchange view - grouped by conversation exchange"
              >
                Exchange
              </button>
              <button
                className={`view-toggle-btn ${conversationViewMode === 'turns' ? 'active' : ''}`}
                onClick={() => {
                  setConversationViewMode('turns');
                  localStorage.setItem('balloons:conversation-view', 'turns');
                }}
                title="Turn list view - flat list of all turns"
              >
                Turns
              </button>
            </div>

            <div className="turns-container">
              {isLoadingTurns ? (
                <div className="empty-state">
                  <h2>Loading...</h2>
                  <p>Loading session messages.</p>
                </div>
              ) : turns.length === 0 ? (
                <div className="empty-state">
                  <h2>No Messages Yet</h2>
                  <p>Send a message to start the conversation.</p>
                </div>
              ) : conversationViewMode === 'exchange' ? (
                <ExchangeListView turns={turns} toolUses={toolUses} />
              ) : (
                turns.map(turn => (
                  <SimpleTurn key={`simple-${turn.idx}`} turn={turn} />
                ))
              )}
              <div ref={turnsEndRef} />
            </div>

            <div className={`input-area ${selectedSession?.isStreaming ? 'queue-mode' : ''}`}>
              {selectedSession?.isStreaming && streamingTask ? (
                <StreamingStatusBar
                  task={streamingTask}
                  queuedMessageCount={queuedMessageCount}
                  onStop={handleStopStreaming}
                  stopDisabled={connectionState !== 'connected'}
                  sessionContextTokens={selectedSession.cachedContextTokens}
                />
              ) : selectedSession && (
                <SessionStatusBar session={selectedSession} />
              )}
              {/* Image preview area */}
              {imageAttachments.length > 0 && (
                <div className="image-preview-area">
                  {imageAttachments.map(img => (
                    <div key={img.id} className={`image-preview ${img.error ? 'error' : ''}`}>
                      <img src={img.previewUrl} alt={img.file.name} />
                      <button
                        type="button"
                        className="image-remove-button"
                        onClick={() => removeImageAttachment(img.id)}
                        title="Remove image"
                      >
                        ×
                      </button>
                      {img.error && <span className="image-error">{img.error}</span>}
                    </div>
                  ))}
                </div>
              )}
              <form className="input-form" onSubmit={handleSubmit}>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp"
                  multiple
                  onChange={handleFileInputChange}
                  style={{ display: 'none' }}
                />
                <button
                  type="button"
                  className="attach-button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={connectionState !== 'connected' || selectedSession?.isStreaming}
                  title="Attach image (or paste from clipboard)"
                >
                  📎
                </button>
                <textarea
                  className="input-field"
                  placeholder={selectedSession?.isStreaming
                    ? "Type to queue... (messages will be sent after streaming completes)"
                    : "Type a message... (Enter to send, Shift+Enter for newline, Ctrl+V to paste image)"}
                  value={message}
                  onChange={e => setMessage(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onPaste={handlePaste}
                  disabled={connectionState !== 'connected'}
                  rows={1}
                />
                {selectedSession?.isStreaming ? (
                  <button
                    type="submit"
                    className="queue-button"
                    disabled={connectionState !== 'connected' || !message.trim()}
                  >
                    Queue
                  </button>
                ) : (
                  <button
                    type="submit"
                    className="send-button"
                    disabled={connectionState !== 'connected' || (!message.trim() && imageAttachments.length === 0)}
                  >
                    Send
                  </button>
                )}
              </form>
            </div>
          </>
        )}
      </AppLayout.Main>
    </AppLayout>
  );
}

// ============================================================================
// Header and Sidebar Components (extracted to use layout context)
// ============================================================================

interface MobileHeaderProps {
  connectionState: ConnectionState;
}

function MobileHeader({ connectionState }: MobileHeaderProps) {
  const { openSidebar } = useLayout();

  return (
    <>
      <button className="menu-button" onClick={openSidebar} aria-label="Open menu">
        ☰
      </button>
      <div className={`connection-status ${connectionState}`} title={connectionState} />
      <h1>Balloons</h1>
    </>
  );
}

// Sidebar view mode
type SidebarView = 'list' | 'tree';

interface SidebarContentProps {
  connectionState: ConnectionState;
  sessions: SessionInfo[];
  selectedSessionId: string | null;
  turns: TurnInfo[];
  streamingTask: TaskInfo | null;
  onSelectSession: (sessionId: string) => void;
  isLoadingTurns?: boolean;
}

function SidebarContent({
  connectionState,
  sessions,
  selectedSessionId,
  turns,
  streamingTask,
  onSelectSession,
  isLoadingTurns = false,
}: SidebarContentProps) {
  const { closeSidebar, layoutMode } = useLayout();
  const { resolvedTheme, toggleTheme } = useTheme();
  const { isActive: wakeLockActive, isSupported: wakeLockSupported, toggle: toggleWakeLock } = useWakeLock();

  // View mode state (persisted in localStorage)
  const [viewMode, setViewMode] = useState<SidebarView>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('balloons:sidebar-view');
      return (stored === 'tree' || stored === 'list') ? stored : 'list';
    }
    return 'list';
  });

  // Persist view mode changes
  const handleViewModeChange = useCallback((mode: SidebarView) => {
    setViewMode(mode);
    localStorage.setItem('balloons:sidebar-view', mode);
  }, []);

  const handleSelectSession = useCallback((sessionId: string) => {
    onSelectSession(sessionId);
    // Close sidebar on mobile after selection
    if (layoutMode === 'mobile') {
      closeSidebar();
    }
  }, [onSelectSession, closeSidebar, layoutMode]);

  // Sort sessions: current first, then by last modified (most recent first)
  const sortedSessions = useMemo(() => {
    return [...sessions].sort((a, b) => {
      if (a.isCurrent) return -1;
      if (b.isCurrent) return 1;
      return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
    });
  }, [sessions]);

  return (
    <>
      <header className="sidebar-header">
        <div className={`connection-status ${connectionState}`} title={connectionState} />
        <h1>Balloons</h1>

        {/* View mode toggle */}
        <div className="view-toggle">
          <button
            className={`view-toggle-btn ${viewMode === 'list' ? 'active' : ''}`}
            onClick={() => handleViewModeChange('list')}
            title="List view"
            aria-label="List view"
          >
            ☰
          </button>
          <button
            className={`view-toggle-btn ${viewMode === 'tree' ? 'active' : ''}`}
            onClick={() => handleViewModeChange('tree')}
            title="Tree view"
            aria-label="Tree view"
          >
            🌲
          </button>
        </div>

        {/* Wake lock toggle - keeps screen awake on mobile */}
        {wakeLockSupported && (
          <button
            className={`wake-lock-toggle ${wakeLockActive ? 'active' : ''}`}
            onClick={toggleWakeLock}
            aria-label={wakeLockActive ? 'Allow screen to sleep' : 'Keep screen awake'}
            title={wakeLockActive ? 'Screen: staying awake' : 'Screen: can sleep'}
          >
            {wakeLockActive ? '☀️' : '💤'}
          </button>
        )}

        <button
          className="theme-toggle"
          onClick={toggleTheme}
          aria-label={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} theme`}
          title={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} theme`}
        >
          {resolvedTheme === 'dark' ? '☀️' : '🌙'}
        </button>
        {layoutMode === 'mobile' && (
          <button className="close-button" onClick={closeSidebar} aria-label="Close menu">
            ✕
          </button>
        )}
      </header>

      {viewMode === 'tree' ? (
        <SessionTreeView
          sessions={sessions}
          selectedSessionId={selectedSessionId}
          turns={turns}
          onSelectSession={handleSelectSession}
          isLoading={isLoadingTurns}
        />
      ) : (
        <div className="session-list">
          {sortedSessions.length === 0 && connectionState === 'connected' && (
            <div style={{ padding: '16px', color: '#666', textAlign: 'center' }}>
              No sessions
            </div>
          )}

          {sortedSessions.map(session => {
            const isSelected = session.id === selectedSessionId;
            const showStreamingDetails = isSelected && session.isStreaming && streamingTask;
            return (
              <div
                key={session.id}
                className={`session-item ${isSelected ? 'selected' : ''} ${session.isStreaming ? 'streaming' : ''}`}
                onClick={() => handleSelectSession(session.id)}
              >
                <div className="session-title">
                  {session.title || `Session ${session.id.slice(0, 8)}`}
                </div>
                <div className="session-meta">
                  {session.messageCount} messages
                  {session.isStreaming && !showStreamingDetails && ' • streaming'}
                </div>
                {showStreamingDetails && (
                  <div className="session-streaming-info">
                    <span className="streaming-badge">
                      <span className="streaming-dot" />
                      {streamingTask.toolName ? (
                        <span>{streamingTask.toolName}</span>
                      ) : (
                        <span>{formatTokens(streamingTask.tokensStreamed)} tokens</span>
                      )}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
