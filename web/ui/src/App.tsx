import React, { useState, useEffect, useCallback, useRef, memo, useMemo, forwardRef, useImperativeHandle } from 'react';
import { BalloonsClient } from '../../generated/balloons-client';
import type { ConnectionState, SessionInfo, TurnInfo, TaskInfo, Unsubscribe, ToolUseStartedEvent, ToolInputDeltaEvent, ToolResultEvent, GoalTreeStateServiceClient, TurnSnapshot, SessionHistoryChunkEvent, SessionHistoryCompleteEvent } from '../../generated/balloons-client';
import { MarkdownContent } from './MarkdownContent';
import { AppLayout, useLayout, useTheme, ThemeProvider, usePreferences, PreferencesProvider, MarkdownThemeApplicator } from './components/layout';
import { SessionTreeView } from './components/SessionTreeView';
import { HierarchyView } from './components/HierarchyView';
import { GoalTreeView } from './components/GoalTreeView';
import { FileBrowserView, type FileBrowserViewRef } from './components/FileBrowserView';
import { SupervisorTab } from './components/SupervisorTab';
import { DomainsTab } from './components/DomainsTab';
import { OptionsTab } from './components/OptionsTab';
import { SettingsTab } from './components/SettingsTab';
// DEPRECATED: KanbanTab and SessionKanbanTab removed - kanban now uses domain plugin system
// import { KanbanTab } from './components/KanbanTab';
// import { SessionKanbanTab } from './components/SessionKanbanTab';
import { LogsTab } from './components/LogsTab';
import { SurveysTab } from './components/SurveysTab';
import { LLMTab } from './components/LLMTab';
import { CodeTab, type CodeReview, type CodeTabHandle, type GitStatusInfo } from './components/CodeTab';
import { SessionStatusBar } from './components/SessionStatusBar';
import { StreamingStatusBar } from './components/StreamingStatusBar';
import { ForkProposalTurn } from './components/ForkProposalTurn';
import { CreateTodoModal, type CreateTodoResult } from './components/CreateTodoModal';
import { SessionReviewModal, type SessionReview, type BackendInfo } from './components/SessionReviewModal';
import { PropertiesTab } from './components/PropertiesTab';
import { StreamingTurnsView, type StreamingProgress } from './components/StreamingTurnsView';
import { ContextTabView, type ExchangeAction as ContextTabExchangeAction } from './components/ContextTabView';
import { DialogProvider, useDialog } from './components/Dialog';
import { useWakeLock, useSoundNotifications, useLongPress, useVisualViewport, useUnreadSessions, useLinkStash, type LinkStashItem } from './hooks';
import { LinkStashArea } from './components/LinkStashArea';
import { RenameSessionModal } from './components/RenameSessionModal';
// LinkSessionModal removed - link stash workflow replaces session picker
import { VoiceInput } from './components/VoiceInput';
import { SendActionButton, type SendAction } from './components/SendActionButton';
import { setDebugClient, createLogger, isDebugEnabled, setDebugEnabled, debugLog as rawDebugLog } from './utils/debugLog';
import { logout, isAuthenticated, getToken } from './utils/auth';
import { Login } from './components/Login';

// Module-level client reference for debug logging
// Set when client connects, cleared on disconnect
let globalClient: BalloonsClient | null = null;

// Create a scoped logger for this module
const debugLog = createLogger('App');

// View mode for conversation display
// StreamingTurnsView uses SessionDataService for real-time streaming

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
          <span className="tool-use-name">{toolUse.name}</span>
        </div>
        {toolUse.inputJson && (
          <Collapsible title="Input" defaultExpanded={true}>
            <FormattedToolInput toolName={toolUse.name} toolInput={toolUse.inputJson} />
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

    // Fork proposal gets special interactive component
    case 'fork_proposal':
      return <ForkProposalTurn turn={turn} />;

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
      const toolName = turn.toolUse?.name || 'Tool';
      return (
        <div className={`turn assistant tool-use-turn ${turn.streaming ? 'streaming' : ''}`}>
          <div className={`tool-use ${turn.streaming ? 'executing' : 'completed'}`}>
            <div className="tool-use-header">
              <span className={`tool-use-status ${turn.streaming ? 'executing' : 'completed'}`}>
                {turn.streaming ? '⚙️' : '✓'}
              </span>
              <span className="tool-use-name">{toolName}</span>
            </div>
            {turn.toolUse?.inputJson && (
              <Collapsible title="Input" defaultExpanded={true}>
                <FormattedToolInput toolName={toolName} toolInput={turn.toolUse.inputJson} />
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

// Helper to convert TurnSnapshot to TurnInfo
function turnSnapshotToInfo(snapshot: TurnSnapshot, idx: number): TurnInfo {
  const block = snapshot.contentBlock;
  const blockType = block?.type || 'text';

  let content = '';
  let toolUse: TurnInfo['toolUse'] = undefined;
  let toolResult: TurnInfo['toolResult'] = undefined;

  if (blockType === 'text' && block && 'text' in block) {
    content = block.text || '';
  } else if (blockType === 'tool_use' && block) {
    const tb = block as { id?: string; name?: string; input?: unknown };
    content = JSON.stringify(tb.input || {});
    toolUse = {
      toolUseId: tb.id || '',
      name: tb.name || '',
      inputJson: content,
    };
  } else if (blockType === 'tool_result' && block) {
    const tr = block as { toolUseId?: string; content?: unknown; isError?: boolean };
    content = String(tr.content || '');
    toolResult = {
      toolUseId: tr.toolUseId || '',
      content,
      isError: tr.isError || false,
    };
  } else if (blockType === 'archive' && block) {
    // Archive block - extract summary for display
    const ab = block as { summary?: string; messageCount?: number };
    content = ab.summary || `Archived ${ab.messageCount || 0} messages`;
  } else if (blockType === 'fork' && block) {
    const fb = block as { forkName?: string; prompt?: string };
    content = fb.forkName ? `**${fb.forkName}**\n\n${fb.prompt || ''}` : fb.prompt || 'Forked session';
  } else if (blockType === 'merge' && block) {
    const mb = block as { forkName?: string; message?: string };
    content = mb.message || `Merged from ${mb.forkName || 'fork'}`;
  } else if (blockType === 'merged_to' && block) {
    const mtb = block as { parentName?: string; message?: string };
    content = mtb.message || `Merged to ${mtb.parentName || 'parent'}`;
  } else if (blockType === 'link' && block) {
    const lb = block as { summary?: string };
    content = lb.summary || 'Linked session';
  } else if (blockType === 'interruption' && block) {
    const ib = block as { reason?: string };
    content = ib.reason || 'User cancelled';
  } else if (blockType === 'error' && block) {
    const eb = block as { reason?: string; details?: string };
    content = `**${eb.reason || 'Error'}**\n\n${eb.details || ''}`;
  }

  return {
    idx,
    role: snapshot.role,
    content,
    streaming: snapshot.streaming,
    viewed: snapshot.viewed,
    tokens: snapshot.tokens,
    contextMode: snapshot.contextMode,
    contentBlockType: blockType,
    exchangeId: snapshot.exchangeId,
    toolUse,
    toolResult,
  };
}

// Helper to convert SessionDataTurn to TurnInfo
// Used to bridge between useSessionData hook and components that use TurnInfo
import type { SessionDataTurn, ContentBlock as SessionDataContentBlock } from './hooks/useSessionData';

function sessionDataTurnToInfo(turn: SessionDataTurn): TurnInfo {
  const block = turn.contentBlock;
  const blockType = block?.type || 'text';

  let content = '';
  let toolUse: TurnInfo['toolUse'] = undefined;
  let toolResult: TurnInfo['toolResult'] = undefined;

  if (blockType === 'text' && block && 'text' in block) {
    content = (block as { text?: string }).text || '';
  } else if (blockType === 'tool_use' && block) {
    const tb = block as { id?: string; name?: string; input?: unknown };
    content = JSON.stringify(tb.input || {});
    toolUse = {
      toolUseId: tb.id || '',
      name: tb.name || '',
      inputJson: content,
    };
  } else if (blockType === 'tool_result' && block) {
    const tr = block as { toolUseId?: string; content?: unknown; isError?: boolean };
    content = String(tr.content || '');
    toolResult = {
      toolUseId: tr.toolUseId || '',
      content,
      isError: tr.isError || false,
    };
  } else if (blockType === 'archive' && block) {
    const ab = block as { summary?: string; messageCount?: number };
    content = ab.summary || `Archived ${ab.messageCount || 0} messages`;
  } else if (blockType === 'fork' && block) {
    const fb = block as { forkName?: string; prompt?: string };
    content = fb.forkName ? `**${fb.forkName}**\n\n${fb.prompt || ''}` : fb.prompt || 'Forked session';
  } else if (blockType === 'merge' && block) {
    const mb = block as { forkName?: string; message?: string };
    content = mb.message || `Merged from ${mb.forkName || 'fork'}`;
  } else if (blockType === 'merged_to' && block) {
    const mtb = block as { parentName?: string; message?: string };
    content = mtb.message || `Merged to ${mtb.parentName || 'parent'}`;
  } else if (blockType === 'link' && block) {
    const lb = block as { summary?: string };
    content = lb.summary || 'Linked session';
  } else if (blockType === 'interruption' && block) {
    const ib = block as { reason?: string };
    content = ib.reason || 'User cancelled';
  } else if (blockType === 'error' && block) {
    const eb = block as { reason?: string; details?: string };
    content = `**${eb.reason || 'Error'}**\n\n${eb.details || ''}`;
  }

  return {
    idx: turn.order,
    role: turn.role,
    content,
    streaming: turn.streaming,
    viewed: turn.viewed,
    tokens: turn.tokens,
    contextMode: turn.contextMode,
    contentBlockType: blockType,
    exchangeId: turn.exchangeId,
    toolUse,
    toolResult,
  };
}

/**
 * Load session turns using layer-based subscriptions.
 *
 * Subscribes with specific layers (header, body, delta, history),
 * collects history via historyChunk events, and keeps the subscription
 * active for real-time updates.
 */
async function loadSessionWithLayers(
  client: BalloonsClient,
  sessionId: string,
  clientId: string,
  layers: string[] = ['header', 'body', 'delta', 'history']
): Promise<TurnInfo[]> {
  return new Promise((resolve, reject) => {
    const collectedTurns: Map<string, TurnSnapshot> = new Map();
    const handlers: Unsubscribe[] = [];
    let timeoutId: ReturnType<typeof setTimeout>;

    const cleanup = () => {
      handlers.forEach(h => h());
      clearTimeout(timeoutId);
    };

    // Set up history chunk handler
    handlers.push(
      client.sessionData.sessionDataHistoryChunk((event: SessionHistoryChunkEvent) => {
        if (event.sessionId !== sessionId) return;
        for (const turn of event.turns || []) {
          if (turn.turnId) {
            collectedTurns.set(turn.turnId, turn);
          }
        }
      })
    );

    // Set up history complete handler
    handlers.push(
      client.sessionData.sessionDataHistoryComplete((event: SessionHistoryCompleteEvent) => {
        if (event.sessionId !== sessionId) return;
        cleanup();

        // Convert to TurnInfo sorted by order
        const snapshots = Array.from(collectedTurns.values())
          .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
        const turns = snapshots.map((s, idx) => turnSnapshotToInfo(s, idx));
        resolve(turns);
      })
    );

    // Timeout after 30 seconds
    timeoutId = setTimeout(() => {
      cleanup();
      reject(new Error('Timeout waiting for history'));
    }, 30000);

    // Subscribe using layer-based API
    client.sessionData.subscribeAdd(sessionId, clientId, layers)
      .then(result => {
        if (!result.subscribed) {
          cleanup();
          reject(new Error(result.error || 'Subscription failed'));
        }
        // If no history layer, resolve immediately with empty
        if (!layers.includes('history')) {
          cleanup();
          resolve([]);
        }
      })
      .catch(err => {
        cleanup();
        reject(err);
      });
  });
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

// Server slots - A is primary (8700), B is secondary (8710)
type ServerSlot = 'A' | 'B';
const SLOT_PORTS: Record<ServerSlot, number> = { A: 8700, B: 8710 };

// Auth server ports - HTTP server for login/auth (WS port + 1)
const AUTH_PORTS: Record<ServerSlot, number> = { A: 8701, B: 8711 };

// Check if TLS should be used (infer from page protocol only)
function shouldUseTls(): boolean {
  if (typeof window === 'undefined') return false;
  // Only use TLS if served over HTTPS - no other magic
  return window.location.protocol === 'https:';
}

// Get WebSocket URL for a given slot (with JWT token if available)
function getWsUrlForSlot(slot: ServerSlot): string {
  // Check for explicit override
  if (typeof window !== 'undefined' && (window as any).BALLOONS_WS_URL) {
    return (window as any).BALLOONS_WS_URL;
  }

  const useTls = shouldUseTls();
  const wsProtocol = useTls ? 'wss' : 'ws';

  // Check URL query param: ?ws=host:port (overrides slot)
  if (typeof window !== 'undefined') {
    const params = new URLSearchParams(window.location.search);
    const wsParam = params.get('ws');
    if (wsParam) {
      const token = getToken();
      const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
      return `${wsProtocol}://${wsParam}${tokenParam}`;
    }

    // Use slot's port with JWT token
    const port = SLOT_PORTS[slot];
    const token = getToken();
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
    return `${wsProtocol}://${window.location.hostname}:${port}${tokenParam}`;
  }

  return `${wsProtocol}://localhost:${SLOT_PORTS[slot]}`;
}

// Get auth server URL for a given slot
function getAuthUrlForSlot(slot: ServerSlot): string {
  const useTls = shouldUseTls();
  const httpProtocol = useTls ? 'https' : 'http';
  const port = AUTH_PORTS[slot];

  if (typeof window !== 'undefined') {
    return `${httpProtocol}://${window.location.hostname}:${port}`;
  }
  return `${httpProtocol}://localhost:${port}`;
}

// Get initial slot from localStorage, default to A
function getInitialSlot(): ServerSlot {
  if (typeof window !== 'undefined') {
    const stored = localStorage.getItem('balloons:server-slot');
    if (stored === 'A' || stored === 'B') {
      return stored;
    }
  }
  return 'A';
}

// ============================================================================
// Fast Input Component - uses uncontrolled input to avoid re-renders
// ============================================================================

interface MessageInputHandle {
  getValue: () => string;
  setValue: (value: string) => void;
  focus: () => void;
}

interface MessageInputProps {
  placeholder: string;
  disabled: boolean;
  onSubmit: (message: string) => void;
  onPaste: (e: React.ClipboardEvent) => void;
  /** Partial voice transcription text to show in italic */
  partialText?: string;
  /** Called when user manually types/edits the input */
  onChange?: (value: string) => void;
}

/**
 * MessageInput - An uncontrolled textarea that doesn't trigger re-renders on typing.
 *
 * This fixes input lag by:
 * 1. Using defaultValue instead of value (uncontrolled)
 * 2. Storing the current value in a ref, not state
 * 3. Only reading the value when needed (submit, clear)
 * 4. Using memo to prevent re-renders from parent state changes
 */
/**
 * MessageInput - An uncontrolled textarea that doesn't trigger re-renders on typing.
 *
 * Performance optimizations:
 * 1. Uses defaultValue instead of value (uncontrolled) - React doesn't manage the DOM value
 * 2. Stores current value in a ref, not state - no re-renders on typing
 * 3. Stores callbacks in refs - allows stable internal handlers even when parent callbacks change
 * 4. Custom memo comparison - only re-renders for placeholder/disabled changes, not callback changes
 */
const MessageInputInner = forwardRef<MessageInputHandle, MessageInputProps>(
  function MessageInput({ placeholder, disabled, onSubmit, onPaste, partialText, onChange }, ref) {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const valueRef = useRef('');
    // Store callbacks in refs to avoid re-creating handlers when they change
    const onSubmitRef = useRef(onSubmit);
    const onPasteRef = useRef(onPaste);
    const onChangeRef = useRef(onChange);
    onSubmitRef.current = onSubmit;
    onPasteRef.current = onPaste;
    onChangeRef.current = onChange;

    // Expose imperative handle for parent to get/set value
    useImperativeHandle(ref, () => ({
      getValue: () => valueRef.current,
      setValue: (value: string) => {
        valueRef.current = value;
        if (textareaRef.current) {
          textareaRef.current.value = value;
        }
      },
      focus: () => textareaRef.current?.focus(),
    }), []);

    const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
      // Just update the ref, no state change = no re-render
      valueRef.current = e.target.value;
      // Notify parent of changes (for voice input sync)
      onChangeRef.current?.(e.target.value);
    }, []);

    const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const value = valueRef.current.trim();
        if (value) {
          onSubmitRef.current(value);
        }
      }
    }, []); // No dependencies - uses ref

    const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      onPasteRef.current(e);
    }, []); // No dependencies - uses ref

    return (
      <div className="input-field-wrapper">
        <textarea
          ref={textareaRef}
          className="input-field"
          placeholder={placeholder}
          defaultValue=""
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          disabled={disabled}
          rows={1}
        />
        {partialText && (
          <div className="input-field-partial">
            <span className="partial-text">{partialText}</span>
          </div>
        )}
      </div>
    );
  }
);

// Custom memo comparison - re-render for placeholder/disabled/partialText changes
// Callbacks are stored in refs inside the component, so we can safely ignore them
const MessageInput = memo(MessageInputInner, (prevProps, nextProps) => {
  return prevProps.placeholder === nextProps.placeholder &&
         prevProps.disabled === nextProps.disabled &&
         prevProps.partialText === nextProps.partialText;
});

/**
 * Main App component - wraps AppContent with DialogProvider
 */
export function App() {
  // Check if user is authenticated
  const [authed, setAuthed] = useState(() => isAuthenticated());
  const [serverSlot] = useState<ServerSlot>(() => getInitialSlot());
  const authUrl = getAuthUrlForSlot(serverSlot);

  // If not authenticated, show login screen
  if (!authed) {
    return (
      <Login
        authUrl={authUrl}
        onLoginSuccess={() => setAuthed(true)}
      />
    );
  }

  return (
    <ThemeProvider>
      <PreferencesProvider>
        <DialogProvider>
          <MarkdownThemeApplicator />
          <AppContent />
        </DialogProvider>
      </PreferencesProvider>
    </ThemeProvider>
  );
}

/**
 * AppContent - the actual app implementation (wrapped by DialogProvider)
 */
function AppContent() {

  // Dialog hook for confirm/alert dialogs
  const { confirm } = useDialog();

  // Voice input and history loading preferences
  const { voiceInputEnabled, voiceInputHost, voiceInputPort, historyLoadMode } = usePreferences();

  // Input area height - resizable by dragging top edge
  // On mobile, cap the height to a reasonable max to prevent huge text areas
  const [inputAreaHeight, setInputAreaHeight] = useState(() => {
    const saved = localStorage.getItem('balloons:input-area-height');
    const height = saved ? parseInt(saved, 10) : 100;
    // On mobile, cap at 150px by default
    const isMobile = typeof window !== 'undefined' && window.innerWidth <= 767;
    return isMobile ? Math.min(height, 150) : height;
  });
  const inputAreaResizing = useRef(false);
  const inputAreaStartY = useRef(0);
  const inputAreaStartHeight = useRef(0);

  // Persist input area height
  useEffect(() => {
    localStorage.setItem('balloons:input-area-height', String(inputAreaHeight));
  }, [inputAreaHeight]);

  // Server slot (A=8765, B=8766) - persisted to localStorage
  const [serverSlot, setServerSlot] = useState<ServerSlot>(getInitialSlot);
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');

  // Debug logging toggle - persisted to localStorage via debugLog module
  const [debugEnabled, setDebugEnabledState] = useState<boolean>(isDebugEnabled);
  const handleToggleDebug = useCallback(() => {
    const newValue = !debugEnabled;
    setDebugEnabledState(newValue);
    setDebugEnabled(newValue);
  }, [debugEnabled]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);

  // Persist slot to localStorage when changed
  useEffect(() => {
    localStorage.setItem('balloons:server-slot', serverSlot);
  }, [serverSlot]);
  // Note: selectedSessionId is NOT initialized from localStorage here to avoid a race condition
  // where selectedSessionId is set before sessions are loaded, causing selectedSession to be
  // undefined. Instead, the persisted session ID is read from localStorage after sessions are
  // loaded in the connection handler (see the "Load initial session list" section below).
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  // Track sessions that finished streaming but haven't been viewed yet
  const { unreadSessionIds } = useUnreadSessions({
    sessions,
    selectedSessionId,
  });

  // Link stash for collecting references to link
  const linkStash = useLinkStash();
  const [linkStashCollapsed, setLinkStashCollapsed] = useState(false);

  const [turns, setTurns] = useState<TurnInfo[]>([]);
  // Raw SessionDataTurns for components that need rich contentBlock data (e.g., ContextTabView)
  const [rawTurns, setRawTurns] = useState<SessionDataTurn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [queuedMessageCount, setQueuedMessageCount] = useState(0);
  const [streamingTask, setStreamingTask] = useState<TaskInfo | null>(null);
  const [toolUses, setToolUses] = useState<ToolUseState[]>([]);
  const [imageAttachments, setImageAttachments] = useState<ImageAttachment[]>([]);
  const [isLoadingTurns, setIsLoadingTurns] = useState(false);
  // History state for ContextTab incomplete history detection
  const [historyState, setHistoryState] = useState<{ totalHistoryTurns: number; isLoadingHistory: boolean; loadFullHistory: () => void }>({
    totalHistoryTurns: -1,
    isLoadingHistory: false,
    loadFullHistory: () => {},
  });
  // Track turn IDs being archived (for showing spinners)
  // Track archiving state: Map from helperId to Set of turn IDs being archived
  // Using turn IDs (stable UUIDs) instead of indices because indices change during reordering
  const [archivingByHelper, setArchivingByHelper] = useState<Map<string, Set<string>>>(new Map());
  // Refresh key: increment to force session data re-subscription (e.g., after archive)
  const [sessionRefreshKey, setSessionRefreshKey] = useState(0);
  // Derived: all turn IDs currently being archived
  const archivingTurnIds = useMemo(() => {
    const allIds = new Set<string>();
    for (const ids of archivingByHelper.values()) {
      for (const id of ids) {
        allIds.add(id);
      }
    }
    return allIds;
  }, [archivingByHelper]);

  // Live context token count computed from turn data
  // Updated as turns complete, more accurate than session.cachedContextTokens
  const liveContextTokens = useMemo(() =>
    rawTurns.reduce((sum, turn) => sum + (turn.tokens ?? 0), 0),
    [rawTurns]
  );
  const [creatingSessionFor, setCreatingSessionFor] = useState<string | null>(null); // "entityType:entityId" when creating bound session
  const [mainContentTab, setMainContentTab] = useState<MainContentTab>('streaming');
  const [sendAction, setSendAction] = useState<SendAction>('send'); // Current action for send button dropdown
  const [gitStatus, setGitStatus] = useState<GitStatusInfo | null>(null);

  // Modal state for CreateTodoModal
  const [createTodoModalState, setCreateTodoModalState] = useState<{
    isOpen: boolean;
    planId: string;
    planTitle: string;
  }>({ isOpen: false, planId: '', planTitle: '' });

  // Modal state for SessionReviewModal
  const [reviewModalState, setReviewModalState] = useState<{
    isOpen: boolean;
    sessionId: string;
    sessionTitle: string;
  }>({ isOpen: false, sessionId: '', sessionTitle: '' });
  const [availableBackends, setAvailableBackends] = useState<BackendInfo[]>([]);
  const [existingReviews, setExistingReviews] = useState<SessionReview[]>([]);
  const [currentReview, setCurrentReview] = useState<SessionReview | null>(null);
  const [isGeneratingReview, setIsGeneratingReview] = useState(false);
  const [reviewStreamingText, setReviewStreamingText] = useState<string>('');
  const reviewHelperIdRef = useRef<string | null>(null);
  const reviewAccumulatedTextRef = useRef<string>('');

  const clientRef = useRef<BalloonsClient | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messageInputRef = useRef<MessageInputHandle>(null);
  const fileBrowserRef = useRef<FileBrowserViewRef>(null);
  const codeTabRef = useRef<CodeTabHandle>(null);

  // Detail panel tab state ('files', 'supervisor', 'domains', or 'options')
  type DetailTab = 'files' | 'supervisor' | 'domains' | 'options';
  const [detailTab, setDetailTab] = useState<DetailTab>('files');

  // Track the session we're currently loading to handle race conditions
  const loadingSessionRef = useRef<string | null>(null);

  // Track whether we should scroll to the latest turn when turns arrive
  // Set to true when switching sessions, cleared after first scroll
  const scrollToLatestOnLoadRef = useRef<boolean>(false);

  // NOTE: Auto-scroll is handled by useAutoScroll hook in StreamingTurnsView.
  // The unconditional scroll-to-bottom effect was removed because it conflicted
  // with the user's ability to scroll up during streaming. See BUGS.md Bug #12.

  // Scroll state from chat view (for status bar indicator)
  const [scrollState, setScrollState] = useState<{ isFollowing: boolean; isAtBottom: boolean } | undefined>(undefined);

  // Handle streaming progress updates from StreamingTurnsView
  // This updates streamingTask with real-time token counts from SessionDataService
  const handleStreamingProgressChange = useCallback((progress: StreamingProgress | null) => {
    if (progress) {
      setStreamingTask(prev => {
        if (!prev) return prev;
        return {
          ...prev,
          tokensStreamed: progress.tokensStreamed,
          currentTokenRate: progress.currentTokenRate,
          toolName: progress.toolName,
          toolCount: progress.toolCount,
          model: progress.model || prev.model,
          contextWindow: progress.contextWindow || prev.contextWindow,
          durationSeconds: progress.durationSeconds,
        };
      });
    }
  }, []);

  // Persist selected session ID to localStorage
  useEffect(() => {
    if (selectedSessionId) {
      localStorage.setItem('balloons:selected-session', selectedSessionId);
    }
  }, [selectedSessionId]);

  // Initialize client and connect - reconnects when slot changes
  useEffect(() => {
    const wsUrl = getWsUrlForSlot(serverSlot);
    debugLog(`Connecting to slot ${serverSlot} at ${wsUrl}`);

    const client = new BalloonsClient(wsUrl, {
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
        // Set global client for debug logging (both local ref and shared utility)
        globalClient = client;
        setDebugClient(client);

        // Load initial session list
        try {
          const sessionList = await client.sessionData.getAllSessions();
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
            // Fall back to most recent session (sessions are sorted by last_modified)
            sessionIdToLoad = sessionList[0]?.id ?? null;
          }

          if (sessionIdToLoad) {
            // Track which session we're loading (for race condition detection)
            // Must be set BEFORE isLoadingTurns so handleTurnsChange can clear loading
            // even for empty sessions
            loadingSessionRef.current = sessionIdToLoad;
            setSelectedSessionId(sessionIdToLoad);
            setIsLoadingTurns(true);

            // Note: Turns will be loaded by StreamingTurnsView via useSessionData hook
            // and reported via onTurnsChange callback. This prevents duplicate subscriptions.
            const [queueInfo, task] = await Promise.all([
              client.queue.getQueue(sessionIdToLoad),
              client.tasks.getSessionTask(sessionIdToLoad),
            ]);

            setQueuedMessageCount(queueInfo.messageCount);
            setStreamingTask(task);
            // Note: setIsLoadingTurns(false) is handled by handleTurnsChange
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
      debugLog(`Disconnecting from slot ${serverSlot}`);
      unsubState();
      globalClient = null;
      setDebugClient(null);
      client.disconnect();
    };
  }, [serverSlot]); // Reconnect when slot changes

  // Subscribe to events when connected
  useEffect(() => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected') return;

    const unsubscribers: Unsubscribe[] = [];

    try {
      // Session events
      unsubscribers.push(
        client.sessionData.sessionDataSessionAdded((data) => {
          // Add the new session directly from the event data
          // This avoids the race condition where selectedSessionId is set
          // but sessions[] doesn't contain it yet (causing status bar to not render)
          const t0 = performance.now();
          rawDebugLog('perf', '[sessionAdded event] received', { sessionId: data.sessionId?.slice(0, 8) });
          if (data.session) {
            setSessions(prev => {
              // Don't add duplicates (in case of reconnection/replay)
              if (prev.some(s => s.id === data.sessionId)) {
                rawDebugLog('perf', '[sessionAdded event] skipped - duplicate', {});
                return prev;
              }
              rawDebugLog('perf', `[sessionAdded event] adding to list, prevLength=${prev.length}`, {});
              return [data.session, ...prev];
            });
            const t1 = performance.now();
            rawDebugLog('perf', `[sessionAdded event] setSessions: ${(t1-t0).toFixed(1)}ms`, {});
          }
        })
      );

      unsubscribers.push(
        client.sessionData.sessionDataSessionUpdated((data) => {
          const tStart = performance.now();
          // Update session in place using the event data - no refetch needed
          // The event includes the full SessionInfo with updated fields like
          // cachedContextTokens, isStreaming, etc.
          // NOTE: Preserve local isPinned state - server events don't include pin status
          if (data.session) {
            setSessions(prev => {
              const result = prev.map(s =>
                s.id === data.sessionId
                  ? { ...data.session, isPinned: s.isPinned }  // Preserve local pin state
                  : s
              );
              const elapsed = performance.now() - tStart;
              if (elapsed > 1) {
                rawDebugLog('perf', `[sessionUpdated event] ${elapsed.toFixed(1)}ms, len=${prev.length}`, {});
              }
              return result;
            });
          }
        })
      );

      unsubscribers.push(
        client.sessionData.sessionDataSessionRemoved(async (data) => {
          console.log('[App] sessionDataSessionRemoved - refetching');
          const sessionList = await client.sessionData.getAllSessions();
          setSessions(sessionList);

          if (data.sessionId === selectedSessionId) {
            setSelectedSessionId(null);
            setTurns([]);
            setArchivingByHelper(new Map()); // Clear session-specific archiving state
          }
        })
      );

      // Pin state changes - refresh sessions to get updated isPinned and re-sort
      unsubscribers.push(
        client.sessionData.sessionDataSessionPinned(async () => {
          console.log('[App] sessionDataSessionPinned - refetching');
          const sessionList = await client.sessionData.getAllSessions();
          setSessions(sessionList);
        })
      );

      // CWD changes - update session working directory when changed via file browser
      unsubscribers.push(
        client.files.onCwdChanged((data) => {
          debugLog('CWD changed', { sessionId: data.sessionId, oldCwd: data.oldCwd, newCwd: data.newCwd });
          setSessions(prev => prev.map(s =>
            s.id === data.sessionId ? { ...s, workingDirectory: data.newCwd } : s
          ));
        })
      );

      // LEGACY TURN HANDLERS DISABLED
      // These handlers (onTurnStarted, onContentDelta, onTurnFinished) were causing
      // duplication bugs because they update `turns` state in parallel with
      // handleTurnsChange (which receives data from StreamingTurnsView's useSessionData).
      //
      // Root cause: Both TaskStateService and SessionDataService emit events for the
      // same streaming content. When both handlers are active, the same text gets
      // applied twice to `turns` state, causing visual duplication.
      //
      // Fix: StreamingTurnsView + handleTurnsChange is now the sole owner of turn
      // content. It subscribes to SessionDataService events, accumulates deltas,
      // and reports final turn state via onTurnsChange callback.
      //
      // See: BUGS.md - Streaming duplication bug

      // Handle sessionDataTurnFinished for non-streaming updates (e.g., context mode changes)
      // Uses contentBlock from event directly instead of fetching via getTurn
      // NOTE: This is kept because it handles updates AFTER streaming completes,
      // which don't conflict with the streaming handlers in useSessionData.
      unsubscribers.push(
        client.sessionData.sessionDataTurnFinished(async (data) => {
          if (data.sessionId === selectedSessionId && data.order != null && data.contentBlock) {
            const turnIdx = data.order;
            setTurns(prev => {
              const existingTurn = prev.find(t => t.idx === turnIdx);
              // If turn is currently streaming, skip - useSessionData handles it
              if (existingTurn?.streaming) {
                return prev;
              }
              // Build TurnInfo from event data
              const contentBlock = data.contentBlock!;
              const updatedTurn: TurnInfo = {
                idx: turnIdx,
                role: data.role || 'assistant',
                content: contentBlock.type === 'text' ? (contentBlock as { text: string }).text : '',
                streaming: false,
                viewed: existingTurn?.viewed ?? false,
                tokens: data.tokens,
                contextMode: existingTurn?.contextMode || 'COPY',
                contentBlockType: contentBlock.type,
                exchangeId: existingTurn?.exchangeId,
                toolUse: contentBlock.type === 'tool_use' ? {
                  toolUseId: (contentBlock as { id: string }).id,
                  name: (contentBlock as { name: string }).name,
                  inputJson: JSON.stringify((contentBlock as { input: unknown }).input || {}),
                } : undefined,
                toolResult: contentBlock.type === 'tool_result' ? {
                  toolUseId: (contentBlock as { toolUseId: string }).toolUseId,
                  content: String((contentBlock as { content: unknown }).content || ''),
                  isError: (contentBlock as { isError?: boolean }).isError || false,
                } : undefined,
              };

              const newTurns = [...prev];
              const idx = newTurns.findIndex(t => t.idx === turnIdx);
              if (idx >= 0) {
                newTurns[idx] = updatedTurn;
              } else {
                newTurns.push(updatedTurn);
              }
              return sortTurnsByIdx(newTurns);
            });
          }
        })
      );

      // Streaming events
      // NOTE: Don't refetch all sessions here - the sessionDataSessionUpdated event
      // already provides incremental updates. Refetching would overwrite in-memory
      // session state (like cachedContextTokens) with stale data from storage.
      // Instead, just update the isStreaming flag locally.
      unsubscribers.push(
        client.sessionData.sessionDataStreamStarted(async (data) => {
          console.log('[App] sessionDataStreamStarted');
          // Update isStreaming flag for the session
          setSessions(prev => prev.map(s =>
            s.id === data.sessionId ? { ...s, isStreaming: true } : s
          ));

          // Clear tool uses when a new streaming session starts
          if (data.sessionId === selectedSessionId) {
            setToolUses([]);
          }
        })
      );

      unsubscribers.push(
        client.sessionData.sessionDataStreamDone(async (data) => {
          console.log('[App] sessionDataStreamDone');
          // Update isStreaming flag for the session
          setSessions(prev => {
            const session = prev.find(s => s.id === data.sessionId);
            console.log('[App] streamDone - current tokens:', session?.cachedContextTokens);
            return prev.map(s =>
              s.id === data.sessionId ? { ...s, isStreaming: false } : s
            );
          });
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
            // Immediately set a minimal task to show the status bar
            // This prevents the race condition where isStreaming=true but streamingTask=null
            // because the getTask() call hasn't completed yet
            // Extract extra data from the event's data field if available
            const extraData = data.data ?? {};
            const minimalTask: TaskInfo = {
              taskId: data.taskId,
              taskType: data.taskType,
              status: data.status,
              sessionId: data.sessionId ?? null,
              backendName: '',
              startedAt: new Date().toISOString(),
              finishedAt: null,
              prompt: '',
              tokensStreamed: (extraData.tokensStreamed as number) ?? 0,
              error: data.error ?? null,
              toolName: (extraData.toolName as string) ?? null,
              toolCount: (extraData.toolCount as number) ?? 0,
              inputTokens: (extraData.inputTokens as number) ?? 0,
              outputTokens: (extraData.outputTokens as number) ?? 0,
              contextWindow: 150000, // Default context window
              model: '',
              durationSeconds: 0,
              isActive: true,
              currentTokenRate: 0,
            };
            setStreamingTask(minimalTask);

            // Then fetch full task info to update with complete data
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

      // Helper to clean up state after task ends (completion, cancel, error)
      // Note: Turn updates are handled by useSessionData via events
      const cleanupAfterTaskEnd = (_sessionId: string) => {
        setStreamingTask(null);
        setToolUses([]);
      };

      unsubscribers.push(
        client.tasks.onTaskCompleted((data) => {
          if (data.sessionId && data.sessionId === selectedSessionId) {
            cleanupAfterTaskEnd(data.sessionId);
          }
        })
      );

      unsubscribers.push(
        client.tasks.onTaskCancelled((data) => {
          if (data.sessionId && data.sessionId === selectedSessionId) {
            cleanupAfterTaskEnd(data.sessionId);
          }
        })
      );

      unsubscribers.push(
        client.tasks.onTaskError((data) => {
          if (data.sessionId && data.sessionId === selectedSessionId) {
            cleanupAfterTaskEnd(data.sessionId);
          }
        })
      );

      // Archive completion - reload turns to show the archive block
      unsubscribers.push(
        client.sessions.onArchiveCompleted(async (data) => {
          debugLog('Archive completed', { sessionId: data.sessionId, turnsArchived: data.turnsArchived, helperId: data.helperId });
          // Clear archiving spinner state for this specific helper
          if (data.helperId) {
            setArchivingByHelper(prev => {
              const next = new Map(prev);
              next.delete(data.helperId!);
              return next;
            });
          } else {
            // Fallback: clear all if no helperId (backwards compatibility)
            setArchivingByHelper(new Map());
          }
          // Note: Turn updates are now handled incrementally via:
          // 1. sessionDataTurnsDeleted event removes the archived turns
          // 2. sessionDataTurnCreated event adds the new archive turn
        })
      );

      // Session review completion - update UI when review finishes
      unsubscribers.push(
        client.sessions.onSessionReviewCompleted(async (data) => {
          debugLog('Session review completed', { sessionId: data.sessionId, summaryId: data.summaryId });
          // Only update if this is for the currently selected session
          if (data.sessionId === selectedSessionId) {
            setIsGeneratingReview(false);
            // Reload reviews to get the newly created one
            try {
              const reviews = await client.sessions.getSessionReviews(data.sessionId);
              setExistingReviews(reviews as unknown as SessionReview[]);
              if (reviews.length > 0) {
                setCurrentReview(reviews[0] as unknown as SessionReview);
              }
            } catch (err) {
              console.error('Failed to load reviews after completion:', err);
            }
          }
        })
      );

      // Helper delta - stream review text as it generates
      unsubscribers.push(
        client.sessions.onHelperDelta((data) => {
          // If this is a session_review helper for our session, update streaming text
          if (data.helperType === 'session_review' && data.sessionId === selectedSessionId) {
            reviewAccumulatedTextRef.current += data.delta;
            setReviewStreamingText(reviewAccumulatedTextRef.current);
          }
        })
      );

      // Helper error handling - clear generating state if helper fails
      unsubscribers.push(
        client.sessions.onHelperError((data) => {
          debugLog('Helper error', { helperId: data.helperId, helperType: data.helperType, error: data.error });
          // If this is a session_review helper for our session, clear the generating state
          if (data.helperType === 'session_review' && data.sessionId === selectedSessionId) {
            setIsGeneratingReview(false);
            setReviewStreamingText('');
          }
        })
      );

      // Tool use events - for visualizing tool calls during streaming
      unsubscribers.push(
        client.tasks.onToolUseStarted((data: ToolUseStartedEvent) => {
          if (data.sessionId === selectedSessionId) {
            // Update the turn to have toolUse info so it renders correctly
            // This fixes the "empty turn" issue during streaming - the turn now
            // has contentBlockType and toolUse set, so filtering logic works
            setTurns(prev => prev.map(t =>
              t.idx === data.turnIndex
                ? {
                    ...t,
                    contentBlockType: 'tool_use',
                    toolUse: {
                      toolUseId: data.toolUseId,
                      name: data.toolName,
                      inputJson: '',  // Will be populated by toolInputDelta/toolUse events
                    },
                  }
                : t
            ));

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
            // Update the turn's toolInput with the complete parsed input
            setTurns(prev => prev.map(t =>
              t.idx === data.turnIndex && t.toolUse?.toolUseId === data.toolUseId
                ? {
                    ...t,
                    toolUse: {
                      ...t.toolUse,
                      toolInput: data.toolInput,
                    },
                  }
                : t
            ));

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

  // Toggle pin status for a session
  const handleTogglePin = useCallback(async (sessionId: string) => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected') return;

    try {
      const isPinned = await client.sessionData.togglePin(sessionId);
      // Update local state immediately for responsive UI
      setSessions(prev => prev.map(s =>
        s.id === sessionId ? { ...s, isPinned } : s
      ));
    } catch (err) {
      console.error('Failed to toggle pin:', err);
    }
  }, [connectionState]);

  // Handle CWD click - open detail panel and navigate file browser
  // Note: We need to use a callback that accesses layout context
  // This will be called from MainContent which has access to layout
  const handleCwdClick = useCallback((cwd: string) => {
    debugLog('CWD clicked, navigating to', { cwd });
    // Navigate the file browser (if it's mounted)
    fileBrowserRef.current?.navigateTo(cwd);
  }, []);

  // Handle setting CWD when no CWD is set - opens file browser for selection
  // The user can then right-click a folder and select "Set as working directory"
  const handleSetCwd = useCallback(() => {
    debugLog('Set CWD requested, opening file browser');
    // File browser will be shown when detail panel expands (handled by onSetCwd caller)
    // Navigate to home or a sensible default
    fileBrowserRef.current?.navigateTo('~');
  }, []);

  // Handle setting working directory from file browser context menu
  const handleSetWorkingDirectory = useCallback(async (path: string) => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected' || !selectedSessionId) {
      console.warn('Cannot set working directory: not connected or no session selected');
      return;
    }

    try {
      debugLog('Setting working directory', { sessionId: selectedSessionId, path });
      // Use session manager method which properly updates the session and emits events
      const success = await client.sessions.setSessionWorkingDirectory(selectedSessionId, path);
      if (success) {
        debugLog('Working directory updated', { path });
        // The sessionDataSessionUpdated event will update the UI automatically
      } else {
        console.error('Failed to set working directory: invalid path or session not found');
      }
    } catch (err) {
      console.error('Failed to set working directory:', err);
    }
  }, [connectionState, selectedSessionId]);

  // Load turns for a session (used by SessionTreeView for lazy loading)
  // Uses header-only subscription to avoid expensive delta streaming for tree view
  const handleLoadTurns = useCallback(async (sessionId: string): Promise<TurnInfo[]> => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected') return [];

    try {
      // For tree view lazy loading, only request history (not delta streaming)
      const sessionTurns = await loadSessionWithLayers(
        client, sessionId, client.clientId, ['header', 'body', 'history']
      );
      return sessionTurns;
    } catch (err) {
      console.error('Failed to load turns for session:', sessionId, err);
      return [];
    }
  }, [connectionState]);

  // Select a session
  // Note: We clear state BEFORE setting the new session ID to prevent race conditions
  // where streaming events for the old session could pollute the new session's state.
  // The loading state prevents rendering partial/stale data during the transition.
  //
  // IMPORTANT: We no longer load turns here - StreamingTurnsView's useSessionData hook
  // is the sole owner of session subscription. It reports turns via onTurnsChange callback.
  // This prevents duplicate subscription conflicts where both this function and useSessionData
  // would try to subscribe to HISTORY layer.
  const handleSelectSession = useCallback(async (sessionId: string) => {
    const t0 = performance.now();
    rawDebugLog('perf', '[handleSelectSession] START', { sessionId: sessionId?.slice(0, 8) });

    const client = clientRef.current;
    if (!client || connectionState !== 'connected') {
      rawDebugLog('perf', '[handleSelectSession] early return - not connected', {});
      return;
    }

    // Skip if already selected (prevents unnecessary refetches)
    if (sessionId === selectedSessionId) {
      rawDebugLog('perf', '[handleSelectSession] early return - already selected', {});
      return;
    }

    // Track which session we're loading (for race condition detection)
    loadingSessionRef.current = sessionId;

    // Mark that we should scroll to the latest turn when turns arrive
    scrollToLatestOnLoadRef.current = true;

    // Clear state immediately to prevent stale data display
    // Note: turns will be populated via onTurnsChange from StreamingTurnsView
    const t1 = performance.now();
    setIsLoadingTurns(true);
    setTurns([]);
    setToolUses([]);
    setStreamingTask(null);
    setQueuedMessageCount(0);
    setError(null);
    // Clear archiving state - it's session-specific and shouldn't persist across session switches
    setArchivingByHelper(new Map());
    const t2 = performance.now();
    rawDebugLog('perf', `[handleSelectSession] state clears: ${(t2-t1).toFixed(1)}ms`, {});

    // Now set the new session ID - this triggers StreamingTurnsView to subscribe
    // and report turns via onTurnsChange callback
    setSelectedSessionId(sessionId);
    const t3 = performance.now();
    rawDebugLog('perf', `[handleSelectSession] setSelectedSessionId: ${(t3-t2).toFixed(1)}ms`, {});

    try {
      // Fetch queue and task info (but NOT turns - those come from StreamingTurnsView)
      const t4 = performance.now();
      rawDebugLog('perf', `[handleSelectSession] starting queue+task fetch`, {});

      // Wrap each call to track individual timing
      const queuePromise = (async () => {
        const start = performance.now();
        rawDebugLog('perf', `[handleSelectSession] getQueue SENT`, {});
        const result = await client.queue.getQueue(sessionId);
        const elapsed = performance.now() - start;
        rawDebugLog('perf', `[handleSelectSession] getQueue RECEIVED: ${elapsed.toFixed(1)}ms`, {});
        return result;
      })();

      const taskPromise = (async () => {
        const start = performance.now();
        rawDebugLog('perf', `[handleSelectSession] getSessionTask SENT`, {});
        const result = await client.tasks.getSessionTask(sessionId);
        const elapsed = performance.now() - start;
        rawDebugLog('perf', `[handleSelectSession] getSessionTask RECEIVED: ${elapsed.toFixed(1)}ms`, {});
        return result;
      })();

      const [queueInfo, task] = await Promise.all([queuePromise, taskPromise]);
      const t5 = performance.now();
      rawDebugLog('perf', `[handleSelectSession] queue+task fetch TOTAL: ${(t5-t4).toFixed(1)}ms`, {});

      // Verify this is still the session we're supposed to load
      // (user might have switched again during the async fetch)
      if (loadingSessionRef.current !== sessionId) {
        return;
      }

      // Apply the loaded data (turns are set via onTurnsChange callback)
      setQueuedMessageCount(queueInfo.messageCount);
      setStreamingTask(task);
      const t6 = performance.now();
      rawDebugLog('perf', `[handleSelectSession] TOTAL: ${(t6-t0).toFixed(1)}ms`, {});
      // Note: setIsLoadingTurns(false) is now done in handleTurnsChange when turns arrive
    } catch (err) {
      console.error('Failed to load session info:', err);
      setError(`Failed to load session info: ${err}`);
      setIsLoadingTurns(false);
    }
  }, [connectionState, selectedSessionId]);

  // Handle turns change from StreamingTurnsView
  // This callback is called whenever useSessionData's turns change
  const handleTurnsChange = useCallback((sessionDataTurns: SessionDataTurn[]) => {
    // Store raw turns for components that need rich contentBlock data
    setRawTurns(sessionDataTurns);
    // Convert SessionDataTurn[] to TurnInfo[]
    const turnInfos = sessionDataTurns.map(sessionDataTurnToInfo);
    debugLog('handleTurnsChange', { turnCount: turnInfos.length });
    setTurns(turnInfos);

    // Clear loading state when we have turns (or confirmed empty session)
    if (isLoadingTurns && (turnInfos.length > 0 || loadingSessionRef.current !== null)) {
      setIsLoadingTurns(false);
    }

    // Scroll to the latest turn when first loading a session
    // Use requestAnimationFrame to ensure DOM has updated with the new turns
    if (scrollToLatestOnLoadRef.current && turnInfos.length > 0) {
      scrollToLatestOnLoadRef.current = false;
      requestAnimationFrame(() => {
        // Find the scroll container and scroll to bottom (same approach as StreamingTurnsView.scrollToBottom)
        const scrollContainer = document.querySelector('.streaming-turns-view-container');
        if (scrollContainer) {
          scrollContainer.scrollTop = scrollContainer.scrollHeight;
        }
      });
    }
  }, [isLoadingTurns]);

  // Handle loading state changes from StreamingTurnsView
  // This ensures isLoadingTurns is cleared when the session data hook finishes loading,
  // even if there's an error or the session is empty
  const handleSessionLoadingChange = useCallback((isLoading: boolean, error: string | null) => {
    debugLog('handleSessionLoadingChange', { isLoading, error, isLoadingTurns });
    // When StreamingTurnsView reports it's done loading, clear our loading state
    if (!isLoading && isLoadingTurns) {
      setIsLoadingTurns(false);
    }
    // If there's an error, also set it on our error state
    if (error) {
      setError(error);
    }
  }, [isLoadingTurns]);

  // Safety net: Clear loading state if connection drops while loading
  // This prevents the input from being stuck in "Loading session..." state
  // when StreamingTurnsView unmounts due to connection loss
  useEffect(() => {
    if (connectionState !== 'connected' && isLoadingTurns) {
      debugLog('Clearing isLoadingTurns due to connection loss', { connectionState });
      setIsLoadingTurns(false);
      loadingSessionRef.current = null;
    }
  }, [connectionState, isLoadingTurns]);

  // Scroll to a specific turn in the chat log
  // Uses data-turn-order attribute on turn wrappers in StreamingTurnsView
  const handleSelectTurn = useCallback((turnIdx: number) => {
    // Find the turn element by data attribute
    const turnElement = document.querySelector(`[data-turn-order="${turnIdx}"]`);
    if (turnElement) {
      turnElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // Flash highlight effect
      turnElement.classList.add('turn-highlight');
      setTimeout(() => turnElement.classList.remove('turn-highlight'), 1500);
    }
  }, []);

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

  // Input area resize handlers
  const handleInputAreaResizeStart = useCallback((e: React.MouseEvent | React.TouchEvent) => {
    e.preventDefault();
    inputAreaResizing.current = true;
    const clientY = 'touches' in e ? e.touches[0]?.clientY ?? 0 : e.clientY;
    inputAreaStartY.current = clientY;
    inputAreaStartHeight.current = inputAreaHeight;
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';
  }, [inputAreaHeight]);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!inputAreaResizing.current) return;
      // Dragging up (negative delta) should increase height
      const delta = inputAreaStartY.current - e.clientY;
      const newHeight = Math.max(60, Math.min(500, inputAreaStartHeight.current + delta));
      setInputAreaHeight(newHeight);
    };

    const handleTouchMove = (e: TouchEvent) => {
      if (!inputAreaResizing.current) return;
      const touch = e.touches[0];
      if (!touch) return;
      const delta = inputAreaStartY.current - touch.clientY;
      const newHeight = Math.max(60, Math.min(500, inputAreaStartHeight.current + delta));
      setInputAreaHeight(newHeight);
    };

    const handleEnd = () => {
      if (inputAreaResizing.current) {
        inputAreaResizing.current = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleEnd);
    document.addEventListener('touchmove', handleTouchMove);
    document.addEventListener('touchend', handleEnd);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleEnd);
      document.removeEventListener('touchmove', handleTouchMove);
      document.removeEventListener('touchend', handleEnd);
    };
  }, []);

  // Track the committed text (from final transcriptions) for voice input
  const voiceCommittedTextRef = useRef('');
  // Track partial (uncommitted) text for display in italic
  const [voicePartialText, setVoicePartialText] = useState('');
  // Track whether there's any voice content (for clear button)
  const [hasVoiceContent, setHasVoiceContent] = useState(false);

  // Clear voice input state
  const handleVoiceClear = useCallback(() => {
    voiceCommittedTextRef.current = '';
    setVoicePartialText('');
    setHasVoiceContent(false);
    messageInputRef.current?.setValue('');
    messageInputRef.current?.focus();
  }, []);

  // Commit partial text to the input (called on disconnect to save work)
  const handleVoiceCommitPartial = useCallback(() => {
    if (voicePartialText) {
      // Append partial text to committed text
      const newCommitted = voiceCommittedTextRef.current
        ? `${voiceCommittedTextRef.current} ${voicePartialText}`
        : voicePartialText;
      voiceCommittedTextRef.current = newCommitted;
      messageInputRef.current?.setValue(newCommitted);
      setVoicePartialText('');
      setHasVoiceContent(true);
    }
  }, [voicePartialText]);

  // Sync voice state when user manually edits the input
  const handleInputChange = useCallback((value: string) => {
    // Sync the committed text ref with what the user typed
    voiceCommittedTextRef.current = value;
    // Clear partial text since user is editing manually
    if (voicePartialText) {
      setVoicePartialText('');
    }
    // Update hasVoiceContent based on whether there's text
    setHasVoiceContent(value.length > 0);
  }, [voicePartialText]);

  // Handle voice transcription from VoiceInput component
  const handleVoiceTranscription = useCallback((text: string, isFinal: boolean) => {
    if (!text) return;

    if (isFinal) {
      // For final transcription, append to committed text
      const newCommitted = voiceCommittedTextRef.current
        ? `${voiceCommittedTextRef.current} ${text}`
        : text;
      voiceCommittedTextRef.current = newCommitted;
      messageInputRef.current?.setValue(newCommitted);
      // Clear partial text since it's now committed
      setVoicePartialText('');
      setHasVoiceContent(true);
    } else {
      // For partial (realtime) transcription, show committed in textarea, partial in overlay
      messageInputRef.current?.setValue(voiceCommittedTextRef.current);
      setVoicePartialText(text);
      // Mark as having content if there's partial text
      if (text) setHasVoiceContent(true);
    }

    // Keep focus on input
    messageInputRef.current?.focus();
  }, []);

  // Send a message - called from MessageInput component or form submit
  // Note: messageContent is passed directly when called from MessageInput's onSubmit
  const handleSubmit = useCallback(async (eOrMessage: React.FormEvent | string) => {
    // Handle both form event and direct message string
    const isFormEvent = typeof eOrMessage !== 'string';
    if (isFormEvent) {
      eOrMessage.preventDefault();
    }

    const client = clientRef.current;
    if (!client || connectionState !== 'connected' || !selectedSessionId) {
      return;
    }

    // Get message either from direct param or from ref
    const message = typeof eOrMessage === 'string'
      ? eOrMessage
      : (messageInputRef.current?.getValue() || '').trim();

    // Allow sending with just images (no text) or just text (no images)
    const hasText = message.length > 0;
    const hasImages = imageAttachments.length > 0;
    if (!hasText && !hasImages) {
      return;
    }

    const content = message;
    const currentImages = [...imageAttachments];

    // Clear input state
    messageInputRef.current?.setValue('');
    voiceCommittedTextRef.current = ''; // Clear voice input buffer
    setVoicePartialText(''); // Clear partial text display
    setHasVoiceContent(false); // Clear voice content flag
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
          messageInputRef.current?.setValue(content);
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
        debugLog('Submitting message', { sessionId: selectedSessionId, contentLength: content.length });
        await client.sessions.submitMessage(selectedSessionId, content);
      }
    } catch (err) {
      debugLog('Failed to send message', { sessionId: selectedSessionId, error: String(err) });
      console.error('Failed to send message:', err);
      setError(`Failed to send message: ${err}`);
      messageInputRef.current?.setValue(content);
      setImageAttachments(currentImages);
    }
  }, [connectionState, selectedSessionId, sessions, imageAttachments]);

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

  // Handle fork action - request LLM to propose a fork
  const handleForkAction = useCallback(async (seedPrompt?: string) => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected' || !selectedSessionId) {
      return;
    }

    try {
      // Request the LLM to propose a fork
      // The LLM will respond with a propose_fork tool call, which renders as ForkProposalCard
      const result = await client.sessions.requestProposal(
        selectedSessionId,
        'fork',
        seedPrompt || ''
      );

      if (!result.success) {
        setError(result.error || 'Failed to request fork proposal');
      }
      // The proposal will appear in the conversation as the LLM responds
    } catch (err) {
      console.error('Failed to request fork proposal:', err);
      setError(`Failed to request fork proposal: ${err}`);
    }
  }, [connectionState, selectedSessionId]);

  // Handle conclude action - mark session as concluded
  // If seedPrompt is provided, include it as the reason
  const handleConcludeAction = useCallback(async (seedPrompt?: string) => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected' || !selectedSessionId) {
      return;
    }

    try {
      // Conclude directly - no LLM proposal needed for conclude
      // The seedPrompt becomes the reason for concluding
      const result = await client.sessions.concludeSession(selectedSessionId, seedPrompt);
      if (!result.success) {
        setError(result.error || 'Failed to conclude session');
        return;
      }
      // Refresh session list
      const sessionList = await client.sessionData.getAllSessions();
      setSessions(sessionList);
    } catch (err) {
      console.error('Failed to conclude session:', err);
      setError(`Failed to conclude session: ${err}`);
    }
  }, [connectionState, selectedSessionId]);

  // Handle link action - link to sessions in the stash
  const handleLinkAction = useCallback(async (description?: string) => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected' || !selectedSessionId) {
      return;
    }

    // Require at least one checked item in the stash
    const checkedItems = linkStash.getCheckedItems();
    if (checkedItems.length === 0) {
      setError('Add items to link stash first (right-click exchanges in Context tab)');
      return;
    }

    // Create links for all checked items
    const summary = description || 'Linked reference';
    for (const item of checkedItems) {
      try {
        const result = await client.sessions.linkSessions(
          selectedSessionId,
          item.sourceSessionId,
          `${summary} (${item.sourceSessionName}: turns ${item.turnIndices.join(', ')})`
        );
        if (!result.linkId) {
          console.error('Failed to link session:', result.error);
        }
      } catch (err) {
        console.error('Failed to link session:', err);
      }
    }

    // Pop the checked items from stash
    linkStash.popChecked();
  }, [connectionState, selectedSessionId, linkStash]);

  // Handle merge action - request LLM to propose a merge
  const handleMergeAction = useCallback(async (seedPrompt?: string) => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected' || !selectedSessionId) {
      return;
    }

    const session = sessions.find(s => s.id === selectedSessionId);
    if (!session?.parentId) {
      setError('Cannot merge: this session has no parent');
      return;
    }

    try {
      // Request the LLM to propose a merge
      // The LLM will respond with a propose_merge tool call, which renders as MergeProposalCard
      const result = await client.sessions.requestProposal(
        selectedSessionId,
        'merge',
        seedPrompt || ''
      );

      if (!result.success) {
        setError(result.error || 'Failed to request merge proposal');
      }
      // The proposal will appear in the conversation as the LLM responds
    } catch (err) {
      console.error('Failed to request merge proposal:', err);
      setError(`Failed to request merge proposal: ${err}`);
    }
  }, [connectionState, selectedSessionId, sessions]);

  // Handle reopen action - reopen a concluded session
  const handleReopenAction = useCallback(async (reason?: string) => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected' || !selectedSessionId) {
      return;
    }

    try {
      const result = await client.sessions.reopenSession(selectedSessionId, reason);
      if (!result.success) {
        setError(result.error || 'Failed to reopen session');
        return;
      }
      // Refresh session list
      const sessionList = await client.sessionData.getAllSessions();
      setSessions(sessionList);
    } catch (err) {
      console.error('Failed to reopen session:', err);
      setError(`Failed to reopen session: ${err}`);
    }
  }, [connectionState, selectedSessionId]);

  // Handle delete session
  const handleDeleteSession = useCallback(async (sessionId: string): Promise<boolean> => {
    const client = clientRef.current;
    if (!client || connectionState !== 'connected') {
      return false;
    }

    try {
      const success = await client.sessions.deleteSession(sessionId);
      if (success) {
        // Refresh session list
        const sessionList = await client.sessionData.getAllSessions();
        setSessions(sessionList);
        // If deleted the selected session, clear selection
        if (sessionId === selectedSessionId) {
          setSelectedSessionId(null);
        }
      }
      return success;
    } catch (err) {
      console.error('Failed to delete session:', err);
      setError(`Failed to delete session: ${err}`);
      return false;
    }
  }, [connectionState, selectedSessionId]);

  // Handle conclude for a specific session (from context menu)
  const handleConcludeSessionFromMenu = useCallback(async (sessionId: string) => {
    // First switch to the session
    setSelectedSessionId(sessionId);
    // Then perform conclude (using empty prompt for quick conclude)
    const client = clientRef.current;
    if (!client || connectionState !== 'connected') return;

    try {
      const result = await client.sessions.concludeSession(sessionId, '');
      if (!result.success) {
        setError(result.error || 'Failed to conclude session');
        return;
      }
      // Refresh session list
      const sessionList = await client.sessionData.getAllSessions();
      setSessions(sessionList);
    } catch (err) {
      console.error('Failed to conclude session:', err);
      setError(`Failed to conclude session: ${err}`);
    }
  }, [connectionState]);

  // Handle fork for a specific session (from context menu)
  const handleForkSessionFromMenu = useCallback(async (sessionId: string) => {
    // First switch to the session
    setSelectedSessionId(sessionId);
    // Then perform fork
    const client = clientRef.current;
    if (!client || connectionState !== 'connected') return;

    try {
      const result = await client.sessions.forkSession(
        sessionId,
        '', // empty prompt - auto-generate
        undefined, // name - auto-generate
        false, // background
        null, // contextModes - auto
        null, // allowedTools
        true, // startStreaming
        true // autoCompleteCompression
      );

      if (result.childSessionId) {
        // Switch to the new forked session
        setSelectedSessionId(result.childSessionId);
        // Refresh session list
        const sessionList = await client.sessionData.getAllSessions();
        setSessions(sessionList);
      }
    } catch (err) {
      console.error('Failed to fork session:', err);
      setError(`Failed to fork session: ${err}`);
    }
  }, [connectionState]);

  // Execute the selected send action
  const handleExecuteAction = useCallback(async () => {
    const content = (messageInputRef.current?.getValue() || '').trim();

    // Handle reopen for concluded sessions
    const session = sessions.find(s => s.id === selectedSessionId);
    if (session?.concluded) {
      messageInputRef.current?.setValue('');
      await handleReopenAction(content || undefined);
      return;
    }

    switch (sendAction) {
      case 'send':
        // Use existing handleSubmit
        if (content || imageAttachments.length > 0) {
          handleSubmit(content);
        }
        break;
      case 'btw':
        // BTW mode: prefix message with instruction not to change course
        if (content) {
          const btwMessage = `BTW (don't change course for this, just acknowledge): ${content}`;
          handleSubmit(btwMessage);
        }
        break;
      case 'fork':
        messageInputRef.current?.setValue('');
        await handleForkAction(content || undefined);
        break;
      case 'conclude':
        messageInputRef.current?.setValue('');
        await handleConcludeAction(content || undefined);
        break;
      case 'link':
        messageInputRef.current?.setValue('');
        await handleLinkAction(content || undefined);
        break;
      case 'merge':
        messageInputRef.current?.setValue('');
        await handleMergeAction(content || undefined);
        break;
    }

    // Reset action to send after any non-send action
    if (sendAction !== 'send') {
      setSendAction('send');
    }
  }, [sendAction, imageAttachments, sessions, selectedSessionId, handleSubmit, handleForkAction, handleConcludeAction, handleLinkAction, handleMergeAction, handleReopenAction]);

  const selectedSession = sessions.find(s => s.id === selectedSessionId);

  // Update document title to show session name and turn count
  useEffect(() => {
    if (selectedSession) {
      const sessionName = selectedSession.forkName || selectedSession.title || 'Session';
      const turnCount = selectedSession.messageCount || 0;
      document.title = `${sessionName} (${turnCount}) - Balloons`;
    } else {
      document.title = 'Balloons';
    }
  }, [selectedSession?.forkName, selectedSession?.title, selectedSession?.messageCount, selectedSession]);

  // Sound notifications for streaming events
  // This hook subscribes to sessionDataStreamDone and sessionDataStreamError events
  // and plays configured notification sounds when they occur
  const soundNotifications = useSoundNotifications(
    connectionState === 'connected' ? clientRef.current : null,
    selectedSessionId
  );

  // Load backends and reviews when Properties tab is active or session changes
  useEffect(() => {
    debugLog('Properties tab useEffect', { mainContentTab, selectedSessionId, connectionState });
    if (mainContentTab !== 'properties' || !selectedSessionId || connectionState !== 'connected') {
      debugLog('Properties tab useEffect: early return', { mainContentTab, selectedSessionId, connectionState });
      return;
    }

    const client = clientRef.current;
    if (!client) {
      debugLog('Properties tab useEffect: no client');
      return;
    }

    // Load available backends
    (async () => {
      debugLog('Properties tab: loading backends...');
      try {
        const backends = await client.sessions.listBackends();
        debugLog('Properties tab: loaded backends', { count: backends.length, backends });
        setAvailableBackends(backends.map(name => ({ name, displayName: name })));
      } catch (err) {
        debugLog('Properties tab: failed to load backends', { error: String(err) });
        console.error('Failed to load backends:', err);
        setAvailableBackends([{ name: 'claude', displayName: 'claude' }]);
      }
    })();

    // Load existing reviews for this session
    (async () => {
      debugLog('Properties tab: loading reviews...');
      try {
        const reviews = await client.sessions.getSessionReviews(selectedSessionId);
        debugLog('Properties tab: loaded reviews', { count: reviews.length });
        setExistingReviews(reviews as unknown as SessionReview[]);
      } catch (err) {
        debugLog('Properties tab: failed to load reviews', { error: String(err) });
        console.error('Failed to load existing reviews:', err);
        setExistingReviews([]);
      }
    })();
  }, [mainContentTab, selectedSessionId, connectionState]);

  return (
    <AppLayout>
      {/* Mobile header */}
      <AppLayout.Header>
        <MobileHeader
          connectionState={connectionState}
          selectedSession={selectedSession}
        />
      </AppLayout.Header>

      {/* Sidebar */}
      <AppLayout.Sidebar>
        <SidebarContent
          connectionState={connectionState}
          sessions={sessions}
          client={clientRef.current}
          selectedSessionId={selectedSessionId}
          selectedSession={selectedSession}
          turns={turns}
          streamingTask={streamingTask}
          onSelectSession={handleSelectSession}
          onSelectTurn={handleSelectTurn}
          onTogglePin={handleTogglePin}
          onLoadTurns={handleLoadTurns}
          isLoadingTurns={isLoadingTurns}
          goalsClient={connectionState === 'connected' ? clientRef.current?.goals : undefined}
          onOpenCreateTodoModal={(planId, planTitle) => {
            setCreateTodoModalState({ isOpen: true, planId, planTitle });
          }}
          creatingSessionFor={creatingSessionFor}
          onDeleteTurn={async (sessionId, turnIdx) => {
            const client = clientRef.current;
            if (!client || connectionState !== 'connected') return;

            // Confirm before deleting
            const confirmed = await confirm({
              title: 'Delete Turn?',
              message: 'Delete this turn? This action cannot be undone.',
              confirmText: 'Delete',
              cancelText: 'Cancel',
              variant: 'danger',
            });
            if (!confirmed) return;

            try {
              const deletedCount = await client.sessionData.deleteTurns(sessionId, [turnIdx]);
              debugLog('Deleted turn', { sessionId, turnIdx, deletedCount });
            } catch (err) {
              console.error('Failed to delete turn:', err);
            }
          }}
          onExchangeAction={async (sessionId, turnIndices, turnIds, action) => {
            const client = clientRef.current;
            if (!client || connectionState !== 'connected') return;

            try {
              if (action === 'delete') {
                // Confirm before deleting
                const turnCount = turnIndices.length;
                const confirmed = await confirm({
                  title: 'Delete Turns?',
                  message: `Delete ${turnCount} turn${turnCount > 1 ? 's' : ''}? This action cannot be undone.`,
                  confirmText: 'Delete',
                  cancelText: 'Cancel',
                  variant: 'danger',
                });
                if (!confirmed) return;

                const deletedCount = await client.sessionData.deleteTurns(sessionId, turnIndices);
                debugLog('Deleted turns', { sessionId, turnIndices, deletedCount });
                // Note: Turn deletion events are handled by useSessionData via subscription
              } else if (action === 'archive') {
                // Start archive (with auto-completion after LLM generates summary)
                const result = await client.sessions.startArchive(sessionId, turnIndices, true);
                if (result.success && result.helperId) {
                  const helperId = result.helperId; // Capture for closure
                  debugLog('Archive started', { sessionId, turnIndices, turnIds, helperId });
                  // Track archiving turns by stable turn IDs (not indices which can shift during reorder)
                  setArchivingByHelper(prev => {
                    const next = new Map(prev);
                    next.set(helperId, new Set(turnIds));
                    return next;
                  });
                  // archivingByHelper cleared on completion via onArchiveCompleted event
                  // (backend emits event on both success AND failure)
                } else {
                  console.warn('Archive request failed:', result.error);
                }
              }
            } catch (err) {
              console.error(`Failed to ${action} turns:`, err);
            }
          }}
          onLinkSession={async (targetSessionId) => {
            const client = clientRef.current;
            if (!client || connectionState !== 'connected') {
              console.error('Cannot link sessions: client not connected');
              return;
            }
            if (!selectedSessionId) {
              console.error('Cannot link sessions: no session selected');
              return;
            }
            if (selectedSessionId === targetSessionId) {
              console.error('Cannot link session to itself');
              return;
            }

            debugLog('Linking sessions', { source: selectedSessionId, target: targetSessionId });
            try {
              const result = await client.sessions.linkSessions(
                selectedSessionId,
                targetSessionId,
              );
              if (result.success) {
                debugLog('Sessions linked', { linkId: result.linkId, source: selectedSessionId, target: targetSessionId });
                // Note: Link turn arrives via useSessionData subscription events
              } else {
                console.error('Failed to link sessions:', result.error);
              }
            } catch (err) {
              console.error('Failed to link sessions:', err);
            }
          }}
          onReviewSession={async (sessionId) => {
            const client = clientRef.current;
            if (!client || connectionState !== 'connected') return;

            // Find session to get title
            const session = sessions.find(s => s.id === sessionId);
            const sessionTitle = session?.forkName || session?.title || `Session ${sessionId.slice(0, 8)}`;

            // Load available backends
            try {
              const backends = await client.sessions.listBackends();
              setAvailableBackends(backends.map(name => ({ name, displayName: name })));
            } catch (err) {
              console.error('Failed to load backends:', err);
              setAvailableBackends([{ name: 'claude', displayName: 'claude' }]);
            }

            // Load existing reviews for this session
            try {
              const reviews = await client.sessions.getSessionReviews(sessionId);
              setExistingReviews(reviews as unknown as SessionReview[]);
            } catch (err) {
              console.error('Failed to load existing reviews:', err);
              setExistingReviews([]);
            }

            // Reset current review state
            setCurrentReview(null);
            setIsGeneratingReview(false);
            reviewHelperIdRef.current = null;
            reviewAccumulatedTextRef.current = '';

            // Open the modal
            setReviewModalState({
              isOpen: true,
              sessionId,
              sessionTitle,
            });
          }}
          onWatchSession={async (targetSessionId) => {
            const client = clientRef.current;
            if (!client || connectionState !== 'connected') {
              console.error('Cannot create watcher: client not connected');
              return;
            }

            debugLog('Creating watcher session', { target: targetSessionId });
            try {
              const result = await client.sessions.createWatcherSession(targetSessionId);
              if (result.success) {
                debugLog('Watcher session created', {
                  watcherId: result.watcherSessionId,
                  target: result.targetSessionId,
                  name: result.watcherName,
                });
                // Switch to the watcher session
                if (result.watcherSessionId) {
                  handleSelectSession(result.watcherSessionId);
                }
              } else {
                console.error('Failed to create watcher session:', result.error);
              }
            } catch (err) {
              console.error('Failed to create watcher session:', err);
            }
          }}
          onDeleteSession={handleDeleteSession}
          onConcludeSession={handleConcludeSessionFromMenu}
          onForkSession={handleForkSessionFromMenu}
          serverSlot={serverSlot}
          onSlotChange={setServerSlot}
          onLogout={() => {
            logout();
            window.location.reload();
          }}
          onNewBareSession={async () => {
            const sessionsClient = clientRef.current?.sessions;
            if (!sessionsClient || connectionState !== 'connected') return;
            try {
              const t0 = performance.now();
              rawDebugLog('perf', '[session_create] START', { currentSelectedSessionId: selectedSessionId?.slice(0, 8) });

              const newSession = await sessionsClient.createSession();
              const t1 = performance.now();
              rawDebugLog('perf', `[session_create] API call: ${(t1-t0).toFixed(1)}ms`, { newSessionId: newSession?.id?.slice(0, 8) });

              if (newSession) {
                // Convert ManagedSessionInfo to SessionInfo and add immediately
                // This prevents the race condition where selectedSessionId is set
                // but sessions[] doesn't contain it yet (status bar won't render)
                const sessionInfo: SessionInfo = {
                  id: newSession.id,
                  title: newSession.title,
                  created: newSession.created,
                  lastModified: newSession.created, // Use created as initial lastModified
                  model: newSession.model,
                  messageCount: newSession.messageCount,
                  totalCost: 0,
                  isStreaming: newSession.isStreaming,
                  forkName: '',
                  forkStatus: '',
                  parentId: newSession.parentId,
                  workingDirectory: newSession.workingDirectory,
                };
                const t2 = performance.now();
                setSessions(prev => {
                  // Don't add if already present (event might have arrived first)
                  if (prev.some(s => s.id === newSession.id)) {
                    rawDebugLog('perf', '[session_create] Session already in list', { newSessionId: newSession.id?.slice(0, 8) });
                    return prev;
                  }
                  rawDebugLog('perf', `[session_create] setSessions: prevLength=${prev.length}`, {});
                  return [sessionInfo, ...prev];
                });
                const t3 = performance.now();
                rawDebugLog('perf', `[session_create] setSessions call: ${(t3-t2).toFixed(1)}ms`, {});

                handleSelectSession(newSession.id);
                const t4 = performance.now();
                rawDebugLog('perf', `[session_create] handleSelectSession: ${(t4-t3).toFixed(1)}ms`, {});
                rawDebugLog('perf', `[session_create] TOTAL: ${(t4-t0).toFixed(1)}ms`, {});
              }
            } catch (error) {
              debugLog('Failed to create new session', { error: String(error) });
              console.error('Failed to create new session:', error);
            }
          }}
          onNewBoundSession={async (entityType, entityId) => {
            const client = clientRef.current;
            const goalsClient = client?.goals;
            if (!client || !goalsClient || connectionState !== 'connected') {
              console.error('Cannot create session: client not connected');
              return;
            }

            // Set loading state
            const loadingKey = `${entityType}:${entityId}`;
            setCreatingSessionFor(loadingKey);

            try {
              // Determine default role based on entity type
              const defaultRole = entityType === 'todo' ? 'implementation' : 'planning';

              // Load entity data for naming and initial prompt
              let entityTitle = '';
              let entityDescription = '';
              let parentGoalTitle = '';
              let parentPlanTitle = '';

              if (entityType === 'goal') {
                const goal = await goalsClient.getGoal(entityId);
                entityTitle = goal?.title || 'Unknown Goal';
                entityDescription = goal?.description || '';
              } else if (entityType === 'plan') {
                const plan = await goalsClient.getPlan(entityId);
                entityTitle = plan?.title || 'Unknown Plan';
                entityDescription = plan?.description || '';
                if (plan?.goalId) {
                  const parentGoal = await goalsClient.getGoal(plan.goalId);
                  parentGoalTitle = parentGoal?.title || '';
                }
              } else if (entityType === 'todo') {
                const todo = await goalsClient.getTodo(entityId);
                entityTitle = todo?.title || 'Unknown Todo';
                entityDescription = todo?.description || '';
                // Get parent plan for context
                if (todo?.planIds && todo.planIds.length > 0) {
                  const firstPlanId = todo.planIds[0];
                  if (firstPlanId) {
                    const plan = await goalsClient.getPlan(firstPlanId);
                    parentPlanTitle = plan?.title || '';
                    if (plan?.goalId) {
                      const parentGoal = await goalsClient.getGoal(plan.goalId);
                      parentGoalTitle = parentGoal?.title || '';
                    }
                  }
                }
              }

              // Create a new session
              const newSession = await client.sessions.createSession();

              // Generate session title: "[role-abbrev] Entity Title"
              const roleAbbrev: Record<string, string> = {
                implementation: 'impl',
                planning: 'plan',
                interview: 'int',
                postmortem: 'post',
                exploration: 'exp',
              };
              const abbrev = roleAbbrev[defaultRole] || defaultRole.slice(0, 4);
              let sessionTitle = `[${abbrev}] ${entityTitle}`;
              if (sessionTitle.length > 60) {
                sessionTitle = sessionTitle.slice(0, 57) + '...';
              }

              // Bind the session to the entity
              await goalsClient.bindSession(
                entityType,
                entityId,
                newSession.id,
                sessionTitle,
                defaultRole,
                0,      // tokenCount
                false,  // isCurrent
                false,  // isStreaming
                undefined // forkStatus
              );

              // Generate initial prompt based on entity type and role
              let initialPrompt = '';
              const context = parentPlanTitle
                ? `Plan: ${parentPlanTitle}${parentGoalTitle ? `\nGoal: ${parentGoalTitle}` : ''}`
                : parentGoalTitle
                  ? `Goal: ${parentGoalTitle}`
                  : '';

              if (defaultRole === 'implementation') {
                initialPrompt = `Let's implement this task:\n\n**${entityTitle}**\n\n${entityDescription || '(No description provided)'}\n\n${context}\n\nI'm ready to start. Please begin the implementation.`;
              } else if (defaultRole === 'planning') {
                initialPrompt = `Let's create a plan for this ${entityType}:\n\n**${entityTitle}**\n\n${entityDescription || '(No description provided)'}\n\n${context}\n\nPlease help me break this down into concrete steps.`;
              }

              // Submit the initial prompt to start the conversation
              if (initialPrompt) {
                await client.sessions.submitMessage(newSession.id, initialPrompt);
              }

              // Refresh the session list
              const sessionList = await client.sessionData.getAllSessions();
              setSessions(sessionList);

              // Switch to the new session
              handleSelectSession(newSession.id);
            } catch (err) {
              console.error('Failed to create bound session:', err);
              setError(`Failed to create session: ${err}`);
            } finally {
              setCreatingSessionFor(null);
            }
          }}
          archivingTurnIds={archivingTurnIds}
          unreadSessionIds={unreadSessionIds}
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
            {/* Tabs and detail panel toggle */}
            <MainContentHeader
              activeTab={mainContentTab}
              onTabChange={setMainContentTab}
              gitStatus={gitStatus}
            />

            {/* Status bar - always visible under tabs */}
            {selectedSession?.isStreaming && streamingTask ? (
              <StreamingStatusBar
                task={streamingTask}
                queuedMessageCount={queuedMessageCount}
                onStop={handleStopStreaming}
                stopDisabled={connectionState !== 'connected'}
                sessionContextTokens={liveContextTokens > 0 ? liveContextTokens : selectedSession.cachedContextTokens}
                isPinned={selectedSession.isPinned ?? false}
                onTogglePin={() => handleTogglePin(selectedSession.id)}
                onSelectSession={setSelectedSessionId}
                scrollState={scrollState}
                session={selectedSession}
                client={clientRef.current}
                cwd={selectedSession.workingDirectory}
                onTitleChange={(newTitle) => {
                  // Force a refresh of session data
                  clientRef.current?.sessions.getSession(selectedSession.id).catch(console.error);
                }}
                onCwdClick={handleCwdClick}
                onSetCwd={handleSetCwd}
              />
            ) : selectedSession && (
              <SessionStatusBar
                session={selectedSession}
                isStreaming={selectedSession.isStreaming}
                liveContextTokens={liveContextTokens}
                client={clientRef.current}
                onTogglePin={() => handleTogglePin(selectedSession.id)}
                onSelectSession={setSelectedSessionId}
                cwd={selectedSession.workingDirectory}
                scrollState={scrollState}
                onCwdClick={handleCwdClick}
                onSetCwd={handleSetCwd}
              />
            )}

            <div className="turns-container">
              {/* Session-specific tabs */}
              {/* StreamingTurnsView is rendered for both 'streaming' and 'context' tabs
                  to keep the useSessionData hook active. It's hidden when on context tab. */}
              {(mainContentTab === 'streaming' || mainContentTab === 'context') && (
                clientRef.current && connectionState === 'connected' ? (
                  <div style={{ display: mainContentTab === 'streaming' ? 'contents' : 'none' }}>
                    <StreamingTurnsView
                      sessionId={selectedSessionId}
                      client={clientRef.current}
                      onSelectSession={setSelectedSessionId}
                      onScrollStateChange={setScrollState}
                      onStreamingProgressChange={handleStreamingProgressChange}
                      onTurnsChange={handleTurnsChange}
                      onLoadingChange={handleSessionLoadingChange}
                      archivingTurnIds={archivingTurnIds}
                      refreshKey={sessionRefreshKey}
                      historyLoadMode={historyLoadMode}
                      onHistoryStateChange={setHistoryState}
                      onArchiveTurns={async (turnIndices, turnIds) => {
                        const client = clientRef.current;
                        if (!client || connectionState !== 'connected' || !selectedSessionId) return;
                        try {
                          const result = await client.sessions.startArchive(selectedSessionId, turnIndices, true);
                          if (result.success && result.helperId) {
                            const helperId = result.helperId;
                            debugLog('Archive started from minimap', { sessionId: selectedSessionId, turnIndices, turnIds, helperId });
                            // Track archiving turns by stable turn IDs (not indices which can shift during reorder)
                            setArchivingByHelper(prev => {
                              const next = new Map(prev);
                              next.set(helperId, new Set(turnIds));
                              return next;
                            });
                          } else {
                            console.warn('Archive request failed:', result.error);
                          }
                        } catch (err) {
                          console.error('Failed to archive turns:', err);
                        }
                      }}
                    />
                  </div>
                ) : (
                  mainContentTab === 'streaming' && (
                    <div className="empty-state">
                      <h2>Connecting...</h2>
                      <p>Waiting for connection.</p>
                    </div>
                  )
                )
              )}
              {mainContentTab === 'context' && (
                <ContextTabView
                  sessionId={selectedSessionId}
                  sessionName={selectedSession?.forkName || selectedSession?.title || undefined}
                  turns={turns}
                  rawTurns={rawTurns}
                  client={clientRef.current}
                  isLoading={connectionState !== 'connected'}
                  archivingTurnIds={archivingTurnIds}
                  totalHistoryTurns={historyState.totalHistoryTurns}
                  isLoadingHistory={historyState.isLoadingHistory}
                  onLoadFullHistory={historyState.loadFullHistory}
                  // No onSelectTurn - clicking nodes just expands/collapses in context view
                  onDeleteTurn={async (turnIdx) => {
                    const client = clientRef.current;
                    if (!client || connectionState !== 'connected' || !selectedSessionId) return;

                    // Confirm before deleting
                    const confirmed = await confirm({
                      title: 'Delete Turn?',
                      message: 'Delete this turn? This action cannot be undone.',
                      confirmText: 'Delete',
                      cancelText: 'Cancel',
                      variant: 'danger',
                    });
                    if (!confirmed) return;

                    try {
                      const deletedCount = await client.sessionData.deleteTurns(selectedSessionId, [turnIdx]);
                      debugLog('Deleted turn', { sessionId: selectedSessionId, turnIdx, deletedCount });
                    } catch (err) {
                      console.error('Failed to delete turn:', err);
                    }
                  }}
                  onExchangeAction={async (turnIndices, turnIds, action) => {
                    const client = clientRef.current;
                    if (!client || connectionState !== 'connected' || !selectedSessionId) return;

                    try {
                      if (action === 'delete') {
                        // Confirm before deleting
                        const turnCount = turnIndices.length;
                        const confirmed = await confirm({
                          title: 'Delete Turns?',
                          message: `Delete ${turnCount} turn${turnCount > 1 ? 's' : ''}? This action cannot be undone.`,
                          confirmText: 'Delete',
                          cancelText: 'Cancel',
                          variant: 'danger',
                        });
                        if (!confirmed) return;

                        const deletedCount = await client.sessionData.deleteTurns(selectedSessionId, turnIndices);
                        debugLog('Deleted turns', { sessionId: selectedSessionId, turnIndices, deletedCount });
                      } else if (action === 'archive') {
                        // Start archive (with auto-completion after LLM generates summary)
                        const result = await client.sessions.startArchive(selectedSessionId, turnIndices, true);
                        if (result.success && result.helperId) {
                          const helperId = result.helperId; // Capture for closure
                          debugLog('Archive started', { sessionId: selectedSessionId, turnIndices, turnIds, helperId });
                          // Track archiving turns by stable turn IDs (not indices which can shift during reorder)
                          setArchivingByHelper(prev => {
                            const next = new Map(prev);
                            next.set(helperId, new Set(turnIds));
                            return next;
                          });
                        } else {
                          console.warn('Archive request failed:', result.error);
                        }
                      } else if (action === 'restore') {
                        // Rehydrate archive - restore archived turns
                        // turnIndices[0] should be the archive turn index
                        const archiveTurnIndex = turnIndices[0];
                        if (archiveTurnIndex !== undefined) {
                          const result = await client.sessions.rehydrate(selectedSessionId, archiveTurnIndex);
                          if (result.success) {
                            debugLog('Rehydrated archive', { sessionId: selectedSessionId, turnIndex: archiveTurnIndex, turnsRestored: result.turnsRestored });
                          } else {
                            console.warn('Rehydrate failed:', result.error);
                          }
                        }
                      }
                    } catch (err) {
                      console.error(`Failed to ${action} turns:`, err);
                    }
                  }}
                  onAddToLinkStash={(turnIndices, excerpt) => {
                    if (!selectedSessionId || !selectedSession) return;
                    const sessionName = selectedSession.forkName || selectedSession.title || selectedSessionId.slice(0, 8);
                    linkStash.addItem({
                      sourceSessionId: selectedSessionId,
                      sourceSessionName: sessionName,
                      turnIndices,
                      excerpt,
                    });
                    debugLog('Added to link stash', { sessionId: selectedSessionId, turnIndices, excerpt });
                  }}
                />
              )}
              {mainContentTab === 'properties' && (
                <PropertiesTab
                  session={selectedSession || null}
                  isConnected={connectionState === 'connected'}
                  availableBackends={availableBackends}
                  onStartReview={async (backendName) => {
                    debugLog('onStartReview callback called', { backendName, selectedSessionId });
                    if (!selectedSessionId) {
                      debugLog('onStartReview: no selectedSessionId');
                      return;
                    }
                    const client = clientRef.current;
                    if (!client) {
                      debugLog('onStartReview: no client');
                      return;
                    }

                    debugLog('onStartReview: starting review');
                    setIsGeneratingReview(true);
                    setCurrentReview(null);
                    setReviewStreamingText('');
                    reviewAccumulatedTextRef.current = '';

                    try {
                      debugLog('calling startSessionReview', { selectedSessionId, backendName });
                      const result = await client.sessions.startSessionReview(selectedSessionId, backendName);
                      debugLog('startSessionReview result', { result });
                      if (result.success && result.helperId) {
                        reviewHelperIdRef.current = result.helperId;
                        debugLog('Review started successfully', {
                          sessionId: selectedSessionId,
                          backendName,
                          helperId: result.helperId
                        });
                        // Completion is handled by onSessionReviewCompleted event subscription
                      } else {
                        debugLog('startSessionReview failed', { result });
                        setIsGeneratingReview(false);
                      }
                    } catch (err) {
                      debugLog('startSessionReview error', { error: String(err) });
                      setIsGeneratingReview(false);
                    }
                  }}
                  isGeneratingReview={isGeneratingReview}
                  reviewStreamingText={reviewStreamingText}
                  currentReview={currentReview}
                  existingReviews={existingReviews}
                  onApproveReview={async (summaryId, title, markdown) => {
                    if (!selectedSessionId) return;
                    const client = clientRef.current;
                    if (!client) return;

                    try {
                      await client.sessions.approveSessionReview(
                        selectedSessionId,
                        summaryId,
                        title,
                        markdown
                      );
                      debugLog('Approved session review', { sessionId: selectedSessionId, summaryId });
                      setCurrentReview(null);
                    } catch (err) {
                      console.error('Failed to approve review:', err);
                    }
                  }}
                  onRename={async (newTitle) => {
                    if (!selectedSessionId) return;
                    const client = clientRef.current;
                    if (!client) return;

                    try {
                      await client.sessions.setSessionTitle(selectedSessionId, newTitle);
                      debugLog('Renamed session', { sessionId: selectedSessionId, newTitle });
                    } catch (err) {
                      console.error('Failed to rename session:', err);
                    }
                  }}
                  onChangeBackend={async (backendName) => {
                    if (!selectedSessionId) return;
                    const client = clientRef.current;
                    if (!client) return;

                    try {
                      await client.sessions.setSessionBackend(selectedSessionId, backendName);
                      debugLog('Changed session backend', { sessionId: selectedSessionId, backendName });
                    } catch (err) {
                      console.error('Failed to change backend:', err);
                    }
                  }}
                  onChangeWorkingDirectory={async (path) => {
                    if (!selectedSessionId) return;
                    const client = clientRef.current;
                    if (!client) return;

                    try {
                      await client.sessions.setSessionWorkingDirectory(selectedSessionId, path);
                      debugLog('Changed working directory', { sessionId: selectedSessionId, path });
                    } catch (err) {
                      console.error('Failed to change working directory:', err);
                    }
                  }}
                />
              )}
              {/* DEPRECATED: session-kanban tab removed - kanban now uses domain plugin system */}
              {mainContentTab === 'slides' && (
                <div className="empty-state">
                  <h2>Slides</h2>
                  <p>Presentation slides created in this session.</p>
                  <p style={{ color: 'var(--color-text-dim)', marginTop: '8px', fontSize: '0.9em' }}>
                    Use the <code>create_slide</code> tool to add slides.
                  </p>
                </div>
              )}

              {/* Global tabs */}
              {mainContentTab === 'logs' && (
                <LogsTab
                  debugLogClient={clientRef.current?.debugLog}
                  isConnected={connectionState === 'connected'}
                />
              )}
              {/* CodeTab is always mounted (hidden when not active) so it can report git status */}
              <div style={{ display: mainContentTab === 'code' ? 'contents' : 'none' }}>
                {connectionState === 'connected' && clientRef.current ? (
                  <CodeTab
                    ref={codeTabRef}
                    cwd={selectedSession?.workingDirectory}
                    client={clientRef.current.files}
                    lspClient={clientRef.current.lsp}
                    onSubmitReview={(review) => {
                      // Format the review as markdown and send to chat
                      const formatReviewAsMarkdown = (review: CodeReview): string => {
                        const lines: string[] = [];
                        lines.push('## Code Review\n');

                        // Group comments by file
                        const commentsByFile = new Map<string, typeof review.comments>();
                        for (const comment of review.comments) {
                          const existing = commentsByFile.get(comment.file_path) || [];
                          existing.push(comment);
                          commentsByFile.set(comment.file_path, existing);
                        }

                        for (const [filePath, comments] of commentsByFile) {
                          lines.push(`### ${filePath}\n`);
                          for (const comment of comments) {
                            // Line range
                            const lineRange = comment.line_end && comment.line_end !== comment.line_start
                              ? `Lines ${comment.line_start}-${comment.line_end}`
                              : `Line ${comment.line_start}`;
                            lines.push(`**${lineRange}**`);

                            // Code context in a code block
                            if (comment.context_lines && comment.context_lines.length > 0) {
                              // Try to infer language from file extension
                              const ext = filePath.split('.').pop() || '';
                              const langMap: Record<string, string> = {
                                ts: 'typescript', tsx: 'tsx', js: 'javascript', jsx: 'jsx',
                                py: 'python', rs: 'rust', go: 'go', rb: 'ruby',
                                java: 'java', c: 'c', cpp: 'cpp', h: 'c', hpp: 'cpp',
                                css: 'css', html: 'html', json: 'json', yaml: 'yaml', yml: 'yaml',
                                md: 'markdown', sh: 'bash', bash: 'bash', zsh: 'bash',
                              };
                              const lang = langMap[ext] || ext;
                              lines.push(`\`\`\`${lang}`);
                              lines.push(...comment.context_lines);
                              lines.push('```');
                            }

                            // The actual comment
                            lines.push(`\n${comment.comment}\n`);
                          }
                        }

                        return lines.join('\n');
                      };

                      const message = formatReviewAsMarkdown(review);
                      // Submit as markdown message so it renders nicely
                      const client = clientRef.current;
                      if (client && selectedSessionId) {
                        client.sessions.submitMarkdownMessage(selectedSessionId, message)
                          .catch(err => {
                            console.error('Failed to submit code review:', err);
                            setError(`Failed to submit code review: ${err}`);
                          });
                      }
                      setMainContentTab('streaming');
                    }}
                    onStartAICommitMessage={(gitRoot, stagedDiff, callbacks) => {
                      const client = clientRef.current;
                      if (!client || connectionState !== 'connected') {
                        callbacks.onError('Not connected');
                        return () => {};
                      }

                      let helperId: string | null = null;
                      let unsubDelta: (() => void) | null = null;
                      let unsubDone: (() => void) | null = null;
                      let unsubError: (() => void) | null = null;
                      let timeoutId: ReturnType<typeof setTimeout> | null = null;

                      // Cleanup function
                      const cleanup = () => {
                        if (timeoutId) clearTimeout(timeoutId);
                        if (unsubDelta) unsubDelta();
                        if (unsubDone) unsubDone();
                        if (unsubError) unsubError();
                      };

                      // Start the generation
                      (async () => {
                        try {
                          const result = await client.sessions.generateCommitMessage(gitRoot, stagedDiff);
                          if (!result.success || !result.helperId) {
                            console.error('Failed to start commit message generation:', result.error);
                            callbacks.onError(result.error || 'Failed to start generation');
                            return;
                          }

                          helperId = result.helperId;

                          // Subscribe to delta events
                          unsubDelta = client.sessions.onHelperDelta((data) => {
                            if (data.helperId === helperId) {
                              callbacks.onDelta(data.delta);
                            }
                          });

                          // Subscribe to done event
                          unsubDone = client.sessions.onHelperDone((data) => {
                            if (data.helperId === helperId) {
                              cleanup();
                              callbacks.onDone(data.result || '');
                            }
                          });

                          // Subscribe to error event
                          unsubError = client.sessions.onHelperError((data) => {
                            if (data.helperId === helperId) {
                              cleanup();
                              callbacks.onError(data.error || 'Generation failed');
                            }
                          });

                          // Timeout after 60 seconds
                          timeoutId = setTimeout(() => {
                            cleanup();
                            callbacks.onError('Generation timed out');
                          }, 60000);
                        } catch (err) {
                          console.error('Failed to generate AI commit message:', err);
                          callbacks.onError(err instanceof Error ? err.message : String(err));
                        }
                      })();

                      return cleanup;
                    }}
                    onGitStatusChange={setGitStatus}
                  />
                ) : (
                  <div className="empty-state">
                    <h2>Code</h2>
                    <p>Connect to server to view changes.</p>
                  </div>
                )}
              </div>
              {mainContentTab === 'llm' && (
                <LLMTab
                  tasksClient={connectionState === 'connected' ? clientRef.current?.tasks : undefined}
                  onJumpToSession={(sessionId) => {
                    setSelectedSessionId(sessionId);
                    setMainContentTab('streaming');
                  }}
                />
              )}
              {mainContentTab === 'settings' && (
                <SettingsTab
                  isConnected={connectionState === 'connected'}
                  soundEnabled={soundNotifications.soundEnabled}
                  onToggleSound={() => soundNotifications.setSoundEnabled(!soundNotifications.soundEnabled)}
                  soundConfig={soundNotifications.soundConfig}
                  availableSounds={soundNotifications.availableSounds}
                  onSetSoundForEvent={soundNotifications.setSoundForEvent}
                  onSetVolume={soundNotifications.setVolume}
                  onPlaySound={soundNotifications.playSound}
                  onRefreshSounds={soundNotifications.refreshSounds}
                  isLoading={soundNotifications.isLoading}
                  error={soundNotifications.error}
                />
              )}
              {/* DEPRECATED: kanban tab removed - kanban now uses domain plugin system */}
              {mainContentTab === 'surveys' && (
                <SurveysTab />
              )}
            </div>

            {/* Input area - show on streaming and context tabs */}
            {(mainContentTab === 'streaming' || mainContentTab === 'context') && (
              <div
                className={`input-area ${selectedSession?.isStreaming ? 'queue-mode' : ''}`}
                style={{ minHeight: inputAreaHeight }}
              >
                {/* Resize handle at top */}
                <div
                  className="input-area-resize-handle"
                  onMouseDown={handleInputAreaResizeStart}
                  onTouchStart={handleInputAreaResizeStart}
                  role="separator"
                  aria-orientation="horizontal"
                  aria-label="Resize input area"
                />
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
                {/* Link stash area */}
                <LinkStashArea
                  items={linkStash.items}
                  checkedCount={linkStash.checkedCount}
                  isLinkMode={sendAction === 'link'}
                  onToggleItem={linkStash.toggleItem}
                  onRemoveItem={linkStash.removeItem}
                  onNavigate={(sessionId, turnIndex) => {
                    // Navigate to the session and turn
                    handleSelectSession(sessionId);
                    // TODO: scroll to turn after session loads
                  }}
                  onApplySingle={async (item) => {
                    const client = clientRef.current;
                    if (!client || connectionState !== 'connected' || !selectedSessionId) return;
                    try {
                      await client.sessions.linkSessions(
                        selectedSessionId,
                        item.sourceSessionId,
                        `Linked: ${item.sourceSessionName} turns ${item.turnIndices.join(', ')}`
                      );
                      linkStash.removeItem(item.id);
                    } catch (err) {
                      console.error('Failed to apply link:', err);
                      setError(`Failed to apply link: ${err}`);
                    }
                  }}
                  onClearAll={linkStash.clearAll}
                  collapsed={linkStashCollapsed}
                  onCollapseChange={setLinkStashCollapsed}
                />
                <form className="input-form" onSubmit={(e) => { e.preventDefault(); handleExecuteAction(); }}>
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
                    disabled={connectionState !== 'connected' || selectedSession?.isStreaming || isLoadingTurns}
                    title="Attach image (or paste from clipboard)"
                  >
                    📎
                  </button>
                  {voiceInputEnabled && (
                    <VoiceInput
                      serverHost={voiceInputHost}
                      dataPort={parseInt(voiceInputPort, 10) || 8012}
                      onTranscription={handleVoiceTranscription}
                      disabled={connectionState !== 'connected' || isLoadingTurns}
                      onClear={handleVoiceClear}
                      hasContent={hasVoiceContent}
                      hasPartialText={!!voicePartialText}
                      onCommitPartial={handleVoiceCommitPartial}
                    />
                  )}
                  <MessageInput
                    ref={messageInputRef}
                    placeholder={isLoadingTurns
                      ? "Loading session..."
                      : selectedSession?.isStreaming
                        ? "Type to queue... (messages will be sent after streaming completes)"
                        : sendAction === 'send'
                          ? "Type a message... (Enter to send, Shift+Enter for newline)"
                          : sendAction === 'btw'
                            ? "Side comment (won't change the current task)..."
                            : sendAction === 'fork'
                              ? "Initial prompt for fork (optional)..."
                              : sendAction === 'conclude'
                                ? "Reason for concluding (optional)..."
                                : sendAction === 'link'
                                  ? "Link description (optional)..."
                                  : sendAction === 'merge'
                                    ? "Merge summary (optional)..."
                                    : "Type a message..."}
                    disabled={connectionState !== 'connected' || isLoadingTurns}
                    onSubmit={sendAction === 'send' ? handleSubmit : handleExecuteAction}
                    onPaste={handlePaste}
                    partialText={voicePartialText}
                    onChange={handleInputChange}
                  />
                  <SendActionButton
                    action={sendAction}
                    onActionChange={setSendAction}
                    onExecute={handleExecuteAction}
                    disabled={connectionState !== 'connected' || isLoadingTurns}
                    canMerge={!!selectedSession?.parentId}
                    isStreaming={selectedSession?.isStreaming}
                    isConcluded={selectedSession?.concluded}
                  />
                </form>
              </div>
            )}
          </>
        )}
      </AppLayout.Main>

      {/* Detail panel (right sidebar) - Tabbed: Files / Supervisor */}
      <AppLayout.Detail>
        {/* Detail panel tabs */}
        <div className="detail-panel-tabs">
          <button
            className={`detail-panel-tab ${detailTab === 'files' ? 'active' : ''}`}
            onClick={() => setDetailTab('files')}
          >
            Files
          </button>
          <button
            className={`detail-panel-tab ${detailTab === 'supervisor' ? 'active' : ''}`}
            onClick={() => setDetailTab('supervisor')}
          >
            Supervisor
          </button>
          <button
            className={`detail-panel-tab ${detailTab === 'domains' ? 'active' : ''}`}
            onClick={() => setDetailTab('domains')}
          >
            🔌 Domains
          </button>
          <button
            className={`detail-panel-tab ${detailTab === 'options' ? 'active' : ''}`}
            onClick={() => setDetailTab('options')}
          >
            Options
          </button>
        </div>

        {/* Tab content */}
        <div className="detail-panel-content">
          {detailTab === 'files' && (
            connectionState === 'connected' && clientRef.current ? (
              <FileBrowserView
                ref={fileBrowserRef}
                sessionId={selectedSessionId || undefined}
                initialPath={selectedSession?.workingDirectory || undefined}
                client={clientRef.current.files}
                onFileSelect={(path) => {
                  debugLog('File selected', { path });
                  // Open the file in the Code tab
                  codeTabRef.current?.openFile(path);
                }}
                onSetWorkingDirectory={handleSetWorkingDirectory}
                onInsertPath={(path) => {
                  // Insert the path into the chat input field
                  const currentValue = messageInputRef.current?.getValue() || '';
                  const newValue = currentValue ? `${currentValue} ${path}` : path;
                  messageInputRef.current?.setValue(newValue);
                  debugLog('Inserted path into input', { path });
                }}
                onAddSessionPrompt={selectedSessionId ? async (path) => {
                  debugLog('Add as session prompt', { path, sessionId: selectedSessionId });
                  if (clientRef.current) {
                    try {
                      const result = await clientRef.current.sessions.addSessionPromptFile(selectedSessionId, path);
                      if (result.success) {
                        debugLog('Added session prompt file', { path });
                      } else {
                        console.error('Failed to add session prompt:', result.error);
                      }
                    } catch (err) {
                      console.error('Error adding session prompt:', err);
                    }
                  }
                } : undefined}
              />
            ) : (
              <div style={{ padding: '16px', color: 'var(--color-text-secondary)' }}>
                Connect to server to browse files
              </div>
            )
          )}

          {detailTab === 'supervisor' && (
            <SupervisorTab
              supervisorClient={connectionState === 'connected' ? clientRef.current?.supervisor : undefined}
              lspClient={connectionState === 'connected' ? clientRef.current?.lsp : undefined}
              isLoading={connectionState !== 'connected'}
              onViewLogs={(processId) => {
                debugLog('View logs for process', { processId });
                // TODO: Open process logs in a modal or new tab
              }}
              onStopProcess={async (processId) => {
                debugLog('Stop process', { processId });
                if (clientRef.current?.supervisor) {
                  const result = await clientRef.current.supervisor.stopProcess(processId);
                  if (!result.success) {
                    console.error('Failed to stop process:', result.error);
                  }
                }
              }}
            />
          )}

          {detailTab === 'domains' && (
            <DomainsTab
              sessionId={selectedSessionId || undefined}
              sessionDataClient={connectionState === 'connected' ? clientRef.current?.sessionData : undefined}
              domainRpcClient={connectionState === 'connected' ? clientRef.current?.domainRpc : undefined}
              isLLMResponding={selectedSession?.isStreaming ?? false}
              sendMessage={(msg) => {
                if (selectedSessionId && clientRef.current) {
                  clientRef.current.sessions.submitMessage(selectedSessionId, msg);
                }
              }}
            />
          )}

          {detailTab === 'options' && (
            <OptionsTab
              key={serverSlot}  // Remount when server slot changes
              debugLogClient={connectionState === 'connected' ? clientRef.current?.debugLog : undefined}
              isConnected={connectionState === 'connected'}
            />
          )}
        </div>
      </AppLayout.Detail>

      {/* CreateTodoModal - rendered at App level for portal */}
      <CreateTodoModal
        isOpen={createTodoModalState.isOpen}
        onClose={() => setCreateTodoModalState({ isOpen: false, planId: '', planTitle: '' })}
        planId={createTodoModalState.planId}
        planTitle={createTodoModalState.planTitle}
        goalsClient={connectionState === 'connected' ? clientRef.current?.goals : undefined}
        onSubmit={(result) => {
          console.log('Todo created:', result);
        }}
        onBeginSession={async (todoId, todoTitle, todoDescription, planId, planTitle, isSpike, timeboxMinutes) => {
          const client = clientRef.current;
          const goalsClient = client?.goals;
          if (!client || !goalsClient || connectionState !== 'connected') {
            console.error('Cannot create session: client not connected');
            return;
          }

          try {
            // Determine role: exploration for spikes, implementation for normal todos
            const role = isSpike ? 'exploration' : 'implementation';

            // Create a new session
            const newSession = await client.sessions.createSession();

            // Bind the session to the todo with appropriate role
            await goalsClient.bindSession(
              'todo',
              todoId,
              newSession.id,
              todoTitle,
              role,
              0,      // tokenCount
              false,  // isCurrent
              false,  // isStreaming
              undefined // forkStatus
            );

            // Generate initial prompt matching Python's generate_initial_prompt()
            // Include plan context and spike note if applicable
            let context = `Plan: ${planTitle}`;
            let spikeNote = '';
            if (isSpike) {
              const timebox = timeboxMinutes ? ` (${timeboxMinutes} minutes)` : '';
              spikeNote = `\n\n*Note: This is a spike${timebox} - focus on learning, not production code.*`;
            }

            const initialPrompt = `Let's implement this task:\n\n**${todoTitle}**\n\n${todoDescription || '(No description provided)'}\n\n${context}${spikeNote}\n\nI'm ready to start. Please begin the implementation.`;
            await client.sessions.submitMessage(newSession.id, initialPrompt);

            // Refresh the session list to include the new session
            const sessionList = await client.sessionData.getAllSessions();
            setSessions(sessionList);

            // Switch to the new session
            handleSelectSession(newSession.id);
          } catch (err) {
            console.error('Failed to create session:', err);
            setError(`Failed to create session: ${err}`);
          }
        }}
      />

      {/* SessionReviewModal - rendered at App level for portal */}
      <SessionReviewModal
        isOpen={reviewModalState.isOpen}
        onClose={() => {
          setReviewModalState({ isOpen: false, sessionId: '', sessionTitle: '' });
          setCurrentReview(null);
          setIsGeneratingReview(false);
          reviewHelperIdRef.current = null;
          reviewAccumulatedTextRef.current = '';
        }}
        sessionId={reviewModalState.sessionId}
        sessionTitle={reviewModalState.sessionTitle}
        availableBackends={availableBackends}
        defaultBackend={availableBackends[0]?.name}
        existingReviews={existingReviews}
        currentReview={currentReview}
        isGenerating={isGeneratingReview}
        onStartReview={async (sessionId, backendName) => {
          debugLog('onStartReview called', { sessionId, backendName });
          const client = clientRef.current;
          if (!client || connectionState !== 'connected') {
            debugLog('onStartReview: client not connected');
            return '';
          }

          setIsGeneratingReview(true);
          setCurrentReview(null);
          reviewAccumulatedTextRef.current = '';

          // Get the current review count before starting
          const existingReviewCount = existingReviews.length;
          debugLog('Starting review', { existingReviewCount });

          try {
            const result = await client.sessions.startSessionReview(sessionId, backendName);
            if (result.success && result.helperId) {
              reviewHelperIdRef.current = result.helperId;
              debugLog('Started session review', { sessionId, backendName, helperId: result.helperId });

              // Poll for the review to appear (auto-complete will add it)
              // Store helper ID in ref so we can check if it's still valid
              const currentHelperId = result.helperId;
              const pollForReview = async () => {
                const maxAttempts = 60; // 60 seconds max
                for (let attempt = 0; attempt < maxAttempts; attempt++) {
                  await new Promise(resolve => setTimeout(resolve, 1000)); // Wait 1 second

                  // Check if this poll is still relevant (helper ID matches)
                  if (reviewHelperIdRef.current !== currentHelperId) {
                    debugLog('Review helper changed, stopping poll');
                    return;
                  }

                  try {
                    const reviews = await client.sessions.getSessionReviews(sessionId);
                    debugLog('Polling for reviews', { attempt, existingCount: existingReviewCount, newCount: reviews.length });

                    // Check if a new review was added
                    if (reviews.length > existingReviewCount) {
                      // Find the newest review (first in list or last, depending on sorting)
                      const newReview = reviews[0] as unknown as SessionReview;
                      setExistingReviews(reviews as unknown as SessionReview[]);
                      setCurrentReview(newReview);
                      setIsGeneratingReview(false);
                      debugLog('Review completed', { summaryId: newReview?.summary_id });
                      return;
                    }
                  } catch (err) {
                    console.error('Error polling for reviews:', err);
                  }
                }

                // Timeout - generation took too long
                setIsGeneratingReview(false);
                console.warn('Review generation timed out');
              };

              // Start polling in background
              pollForReview();

              return result.helperId;
            } else {
              console.error('Failed to start session review:', result.error);
              setIsGeneratingReview(false);
              return '';
            }
          } catch (err) {
            console.error('Failed to start session review:', err);
            setIsGeneratingReview(false);
            return '';
          }
        }}
        onApprove={async (sessionId, summaryId, approvedTitle, editedMarkdown) => {
          const client = clientRef.current;
          if (!client || connectionState !== 'connected') return;

          try {
            const result = await client.sessions.approveSessionReview(
              sessionId,
              summaryId,
              approvedTitle,
              editedMarkdown
            );
            if (result.success) {
              debugLog('Approved session review', { sessionId, summaryId, approvedTitle });
              // Optionally update session title in local state
              if (result.approvedTitle) {
                setSessions(prev => prev.map(s =>
                  s.id === sessionId ? { ...s, title: result.approvedTitle! } : s
                ));
              }
            } else {
              console.error('Failed to approve session review:', result.error);
            }
          } catch (err) {
            console.error('Failed to approve session review:', err);
          }
        }}
      />
    </AppLayout>
  );
}

// ============================================================================
// Header and Sidebar Components (extracted to use layout context)
// ============================================================================

interface MobileHeaderProps {
  connectionState: ConnectionState;
  selectedSession?: SessionInfo | null;
}

function MobileHeader({ connectionState, selectedSession }: MobileHeaderProps) {
  const { openSidebar, openDetail } = useLayout();

  // Format title: session name (or title) + hash prefix
  const headerTitle = selectedSession
    ? `${selectedSession.forkName || selectedSession.title || 'Session'} #${selectedSession.id.slice(0, 6)}`
    : 'Balloons';

  const handleOpenDetail = () => {
    console.log('Detail button clicked, openDetail:', openDetail);
    openDetail();
  };

  const [isFullscreen, setIsFullscreen] = useState(false);

  // Track fullscreen state changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  // Handle virtual keyboard in fullscreen mode
  // This hook sets --keyboard-offset CSS variable when keyboard appears
  // Always enable on mobile to handle keyboard regardless of fullscreen state
  const isMobile = typeof window !== 'undefined' && window.innerWidth < 768;
  useVisualViewport(isFullscreen || isMobile);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      document.documentElement.requestFullscreen();
    }
  }, []);

  return (
    <>
      <button className="menu-button" onClick={openSidebar} aria-label="Open menu">
        ☰
      </button>
      <div className={`connection-status ${connectionState}`} title={connectionState} />
      <h1>{headerTitle}</h1>
      <button
        className="menu-button menu-button--fullscreen"
        onClick={toggleFullscreen}
        aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
        title={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
      >
        {isFullscreen ? '⛶' : '⛶'}
      </button>
      <button className="menu-button menu-button--right" onClick={handleOpenDetail} aria-label="Open detail panel">
        ⋮
      </button>
    </>
  );
}

// Main content tab type
// Session tabs: streaming, context, properties, slides (depend on selected session)
// Global tabs: code, logs, llm, settings (app-wide)
//
// URL ROUTING: When adding new tabs, also update:
// - docs/url-routing.md (add route to URL scheme)
// - routes.ts (add route constant when created)
// - useRouter hook (add route handler when created)
// DEPRECATED: 'session-kanban' and 'kanban' tabs removed - kanban now uses domain plugin system
type MainContentTab = 'streaming' | 'context' | 'properties' | 'slides' | 'code' | 'logs' | 'llm' | 'settings' | 'surveys';
type OuterTab = 'session' | 'global';

// Helper to determine which outer tab a content tab belongs to
// URL ROUTING: Add new session tabs to SESSION_TABS, global tabs to GLOBAL_TABS
const SESSION_TABS: MainContentTab[] = ['streaming', 'context', 'properties', 'slides'];
const GLOBAL_TABS: MainContentTab[] = ['code', 'logs', 'llm', 'settings', 'surveys'];

function getOuterTab(tab: MainContentTab): OuterTab {
  return SESSION_TABS.includes(tab) ? 'session' : 'global';
}

/**
 * Subtabs container with scroll indicators (arrows) when content overflows
 */
function SubtabsContainer({ children }: { children: React.ReactNode }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const updateScrollState = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;

    const hasOverflow = el.scrollWidth > el.clientWidth;
    setCanScrollLeft(hasOverflow && el.scrollLeft > 1);
    setCanScrollRight(hasOverflow && el.scrollLeft < el.scrollWidth - el.clientWidth - 1);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    // Initial check after a small delay to let layout settle
    const timeoutId = setTimeout(updateScrollState, 50);

    el.addEventListener('scroll', updateScrollState);

    // Also check on resize
    const resizeObserver = new ResizeObserver(updateScrollState);
    resizeObserver.observe(el);

    return () => {
      clearTimeout(timeoutId);
      el.removeEventListener('scroll', updateScrollState);
      resizeObserver.disconnect();
    };
  }, [updateScrollState, children]); // Re-run when children change

  const scrollBy = (amount: number) => {
    scrollRef.current?.scrollBy({ left: amount, behavior: 'smooth' });
  };

  return (
    <div className="subtabs-wrapper">
      {canScrollLeft && (
        <button
          className="subtabs-arrow subtabs-arrow-left"
          onClick={() => scrollBy(-100)}
          aria-label="Scroll left"
        >
          ‹
        </button>
      )}
      <div className="subtabs" ref={scrollRef}>
        {children}
      </div>
      {canScrollRight && (
        <button
          className="subtabs-arrow subtabs-arrow-right"
          onClick={() => scrollBy(100)}
          aria-label="Scroll right"
        >
          ›
        </button>
      )}
    </div>
  );
}

/**
 * Header bar for the main content area with two-level tabs:
 * - Outer tabs: Session | Global
 * - Subtabs: depend on which outer tab is selected
 */
function MainContentHeader({
  activeTab,
  onTabChange,
  gitStatus,
}: {
  activeTab: MainContentTab;
  onTabChange: (tab: MainContentTab) => void;
  gitStatus?: GitStatusInfo | null;
}) {
  const { layoutMode, isDetailCollapsed, toggleDetailCollapse } = useLayout();

  // Show badge if there are git changes (unstaged or staged)
  const hasGitChanges = gitStatus && (gitStatus.hasUnstaged || gitStatus.hasStaged);

  // Determine which outer tab is active based on current subtab
  const activeOuterTab = getOuterTab(activeTab);

  // When switching outer tabs, go to the first subtab of that group
  const handleOuterTabChange = (outer: OuterTab) => {
    if (outer === 'session' && activeOuterTab !== 'session') {
      onTabChange('streaming');
    } else if (outer === 'global' && activeOuterTab !== 'global') {
      onTabChange('code');
    }
  };

  return (
    <div className="conversation-view-toggle">
      {/* Outer tabs: Session | Global */}
      <div className="outer-tabs">
        <button
          className={`outer-tab-btn ${activeOuterTab === 'session' ? 'active' : ''}`}
          onClick={() => handleOuterTabChange('session')}
        >
          Session
        </button>
        <button
          className={`outer-tab-btn ${activeOuterTab === 'global' ? 'active' : ''}`}
          onClick={() => handleOuterTabChange('global')}
        >
          Global
        </button>
      </div>

      {/* Separator */}
      <div className="tab-group-separator" />

      {/* Subtabs - show based on which outer tab is active */}
      <SubtabsContainer>
        {activeOuterTab === 'session' ? (
          <>
            <button
              className={`view-toggle-btn ${activeTab === 'streaming' ? 'active' : ''}`}
              onClick={() => onTabChange('streaming')}
            >
              Streaming
            </button>
            <button
              className={`view-toggle-btn ${activeTab === 'context' ? 'active' : ''}`}
              onClick={() => onTabChange('context')}
            >
              Context
            </button>
            {/* DEPRECATED: session-kanban tab button removed - kanban now uses domain plugin system */}
            <button
              className={`view-toggle-btn ${activeTab === 'properties' ? 'active' : ''}`}
              onClick={() => onTabChange('properties')}
            >
              Properties
            </button>
            <button
              className={`view-toggle-btn ${activeTab === 'slides' ? 'active' : ''}`}
              onClick={() => onTabChange('slides')}
            >
              Slides
            </button>
          </>
        ) : (
          <>
            <button
              className={`view-toggle-btn ${activeTab === 'code' ? 'active' : ''}`}
              onClick={() => onTabChange('code')}
              title={hasGitChanges ? `${gitStatus.fileCount} uncommitted change${gitStatus.fileCount !== 1 ? 's' : ''}` : undefined}
            >
              Code
              {hasGitChanges && (
                <span className="code-tab-changes-indicator" />
              )}
            </button>
            <button
              className={`view-toggle-btn ${activeTab === 'logs' ? 'active' : ''}`}
              onClick={() => onTabChange('logs')}
            >
              Logs
            </button>
            <button
              className={`view-toggle-btn ${activeTab === 'llm' ? 'active' : ''}`}
              onClick={() => onTabChange('llm')}
            >
              LLM
            </button>
            <button
              className={`view-toggle-btn ${activeTab === 'settings' ? 'active' : ''}`}
              onClick={() => onTabChange('settings')}
            >
              Settings
            </button>
            {/* DEPRECATED: kanban tab button removed - kanban now uses domain plugin system */}
            <button
              className={`view-toggle-btn ${activeTab === 'surveys' ? 'active' : ''}`}
              onClick={() => onTabChange('surveys')}
            >
              Surveys
            </button>
          </>
        )}
      </SubtabsContainer>

      {/* Detail panel toggle - only show on desktop, pushed to right */}
      {layoutMode === 'desktop' && (
        <button
          className={`view-toggle-btn detail-toggle-btn ${!isDetailCollapsed ? 'active' : ''}`}
          onClick={toggleDetailCollapse}
          title={isDetailCollapsed ? 'Show detail panel' : 'Hide detail panel'}
          style={{ marginLeft: 'auto' }}
        >
          {isDetailCollapsed ? '◀ More Stuff' : 'Less Stuff ▶'}
        </button>
      )}
    </div>
  );
}

// Sidebar view mode
type SidebarView = 'list' | 'tree' | 'hierarchy' | 'goals';

// Exchange action type from SessionTreeView
type ExchangeAction = 'archive' | 'delete';

/**
 * Session list item with long-press to rename support
 */
interface SessionListItemProps {
  session: SessionInfo;
  isSelected: boolean;
  isPinned: boolean;
  showStreamingDetails: boolean;
  streamingTask: TaskInfo | null;
  onSelect: () => void;
  onTogglePin?: () => void;
  /** Called when user wants to rename this session (long press on title) */
  onRequestRename?: () => void;
  itemRef?: (el: HTMLDivElement | null) => void;
}

function SessionListItem({
  session,
  isSelected,
  isPinned,
  showStreamingDetails,
  streamingTask,
  onSelect,
  onTogglePin,
  onRequestRename,
  itemRef,
}: SessionListItemProps) {
  const titleLongPress = useLongPress({
    onLongPress: () => {
      onRequestRename?.();
    },
    delay: 500,
  });

  return (
    <div
      ref={itemRef}
      className={`session-item ${isSelected ? 'selected' : ''} ${session.isStreaming ? 'streaming' : ''} ${isPinned ? 'pinned' : ''}`}
      onClick={onSelect}
    >
      <div className="session-header">
        {onTogglePin && (
          <span
            className={`session-pin ${isPinned ? 'session-pin--active' : ''}`}
            onClick={(e) => { e.stopPropagation(); onTogglePin(); }}
            title={isPinned ? 'Unpin session' : 'Pin session'}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill={isPinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 17v5" />
              <path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1z" />
            </svg>
          </span>
        )}
        <div
          className="session-title"
          title="Long press to rename"
          {...titleLongPress}
        >
          {session.title || session.forkName || `Session ${session.id.slice(0, 8)}`}
        </div>
      </div>
      <div className="session-meta">
        {session.messageCount} messages
        {session.isStreaming && !showStreamingDetails && ' • streaming'}
      </div>
      {showStreamingDetails && streamingTask && (
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
}

interface SidebarContentProps {
  connectionState: ConnectionState;
  sessions: SessionInfo[];
  /** Balloons client for rename operations */
  client?: BalloonsClient | null;
  selectedSessionId: string | null;
  selectedSession?: SessionInfo | null;
  turns: TurnInfo[];
  streamingTask: TaskInfo | null;
  onSelectSession: (sessionId: string) => void;
  onSelectTurn?: (turnIdx: number) => void;
  onTogglePin?: (sessionId: string) => void;
  onLoadTurns?: (sessionId: string) => Promise<TurnInfo[]>;
  isLoadingTurns?: boolean;
  goalsClient?: GoalTreeStateServiceClient;
  onOpenCreateTodoModal?: (planId: string, planTitle: string) => void;
  onNewBareSession?: () => void;
  onNewBoundSession?: (entityType: string, entityId: string) => Promise<void>;
  creatingSessionFor?: string | null; // "entityType:entityId" when creating bound session
  // Exchange context menu callbacks
  onExchangeAction?: (sessionId: string, turnIndices: number[], turnIds: string[], action: ExchangeAction) => void;
  onDeleteTurn?: (sessionId: string, turnIdx: number) => void;
  // Session review callback
  onReviewSession?: (sessionId: string) => void;
  // Link session callback
  onLinkSession?: (sessionId: string) => void;
  // Watch session callback (create watcher session)
  onWatchSession?: (sessionId: string) => void;
  // Delete session callback
  onDeleteSession?: (sessionId: string) => Promise<boolean>;
  // Conclude session callback
  onConcludeSession?: (sessionId: string) => void;
  // Fork session callback
  onForkSession?: (sessionId: string) => void;
  // Server slot props
  serverSlot: ServerSlot;
  onSlotChange: (slot: ServerSlot) => void;
  // Auth
  onLogout?: () => void;
  // Archiving state
  archivingTurnIds?: Set<string>;
  // Unread sessions (finished streaming but not viewed)
  unreadSessionIds?: Set<string>;
}

function SidebarContent({
  connectionState,
  sessions,
  client,
  selectedSessionId,
  selectedSession,
  turns,
  streamingTask,
  onSelectSession,
  onSelectTurn,
  onTogglePin,
  onLoadTurns,
  isLoadingTurns = false,
  goalsClient,
  onOpenCreateTodoModal,
  onNewBareSession,
  onNewBoundSession,
  creatingSessionFor = null,
  onExchangeAction,
  onDeleteTurn,
  onReviewSession,
  onLinkSession,
  onWatchSession,
  onDeleteSession,
  onConcludeSession,
  onForkSession,
  serverSlot,
  onSlotChange,
  onLogout,
  archivingTurnIds,
  unreadSessionIds,
}: SidebarContentProps) {
  const { closeSidebar, layoutMode } = useLayout();

  // State for the shared rename modal (one modal, not one per session)
  const [renameModalSession, setRenameModalSession] = useState<SessionInfo | null>(null);

  // View mode state (persisted in localStorage)
  const [viewMode, setViewMode] = useState<SidebarView>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('balloons:sidebar-view');
      return (stored === 'tree' || stored === 'list' || stored === 'hierarchy' || stored === 'goals') ? stored : 'list';
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

  // Ref for session items - keyed by session ID
  const sessionItemRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // Scroll to selected session when it changes
  useEffect(() => {
    if (selectedSessionId && viewMode === 'list') {
      const element = sessionItemRefs.current.get(selectedSessionId);
      if (element) {
        // Only scroll if the element is not fully visible
        const rect = element.getBoundingClientRect();
        const container = element.closest('.session-list');
        if (container) {
          const containerRect = container.getBoundingClientRect();
          const isVisible = rect.top >= containerRect.top && rect.bottom <= containerRect.bottom;
          if (!isVisible) {
            element.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
        }
      }
    }
  }, [selectedSessionId, viewMode]);

  // Sort sessions: pinned first, then by last modified (most recent first)
  const sortedSessions = useMemo(() => {
    return [...sessions].sort((a, b) => {
      // Pinned sessions come first
      const aPinned = a.isPinned ?? false;
      const bPinned = b.isPinned ?? false;
      if (aPinned && !bPinned) return -1;
      if (!aPinned && bPinned) return 1;

      // Then by last modified
      return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
    });
  }, [sessions]);

  // Format title: session name (or title) + hash prefix
  const headerTitle = selectedSession
    ? `${selectedSession.forkName || selectedSession.title || 'Session'} #${selectedSession.id.slice(0, 6)}`
    : 'Balloons';

  const toggleSlot = useCallback(() => {
    onSlotChange(serverSlot === 'A' ? 'B' : 'A');
  }, [serverSlot, onSlotChange]);

  return (
    <>
      <header className="sidebar-header">
        {/* Connection status with server slot indicator */}
        <button
          className={`connection-status-btn ${connectionState}`}
          onClick={toggleSlot}
          title={`${connectionState} - Server ${serverSlot} (:${SLOT_PORTS[serverSlot]}). Click to switch.`}
        >
          <span className="connection-dot" />
          <span className="server-slot">{serverSlot}</span>
        </button>
        <h1>{headerTitle}</h1>

        {onLogout && (
          <button
            className="signout-btn"
            onClick={onLogout}
            title="Sign out"
          >
            Sign out
          </button>
        )}

        {layoutMode === 'mobile' && (
          <button className="close-button" onClick={closeSidebar} aria-label="Close menu">
            ✕
          </button>
        )}
      </header>

      {/* View mode tabs */}
      <div className="sidebar-view-tabs">
        <button
          className={`sidebar-view-tab ${viewMode === 'list' ? 'active' : ''}`}
          onClick={() => handleViewModeChange('list')}
          title="List view"
        >
          List
        </button>
        <button
          className={`sidebar-view-tab ${viewMode === 'tree' ? 'active' : ''}`}
          onClick={() => handleViewModeChange('tree')}
          title="Tree view"
        >
          Tree
        </button>
        <button
          className={`sidebar-view-tab ${viewMode === 'hierarchy' ? 'active' : ''}`}
          onClick={() => handleViewModeChange('hierarchy')}
          title="Hierarchy view - unified fork tree"
        >
          Hierarchy
        </button>
        <button
          className={`sidebar-view-tab ${viewMode === 'goals' ? 'active' : ''}`}
          onClick={() => handleViewModeChange('goals')}
          title="Goals view"
        >
          Goals
        </button>
      </div>

      {onNewBareSession && (
        <button
          className="new-session-row"
          onClick={onNewBareSession}
          aria-label="New session"
          title="Start new session"
        >
          + New Session
        </button>
      )}

      {viewMode === 'goals' ? (
        <GoalTreeView
          goalsClient={goalsClient}
          onSelectSession={handleSelectSession}
          onSelectEntity={(entityType, entityId) => {
            // TODO: Update detail pane with entity info
            console.log('Selected entity:', entityType, entityId);
          }}
          onNewPlan={(goalId) => {
            goalsClient?.addPlan({ goalId, title: 'New Plan', status: 'draft' });
          }}
          onNewTodo={(planId) => {
            // Fetch plan title and open the modal via App-level callback
            if (onOpenCreateTodoModal && goalsClient) {
              goalsClient.getPlan(planId).then(plan => {
                onOpenCreateTodoModal(planId, plan?.title || 'Unknown Plan');
              }).catch(() => {
                // Still open modal with fallback title
                onOpenCreateTodoModal(planId, 'Unknown Plan');
              });
            } else if (onOpenCreateTodoModal) {
              // No goalsClient, open modal anyway with fallback
              onOpenCreateTodoModal(planId, 'Unknown Plan');
            }
          }}
          onNewSession={(entityType, entityId) => {
            if (onNewBoundSession) {
              onNewBoundSession(entityType, entityId);
            }
          }}
          onMarkTodoDone={(todoId) => {
            // Update todo status to completed
            goalsClient?.getTodo(todoId).then(todo => {
              if (todo) {
                const now = new Date().toISOString();
                goalsClient?.addTodo({ ...todo, status: 'completed', updated_at: now, completed_at: now }, todo.planIds);
              }
            });
          }}
          onMarkTodoUndone={(todoId) => {
            // Update todo status back to pending
            goalsClient?.getTodo(todoId).then(todo => {
              if (todo) {
                const now = new Date().toISOString();
                goalsClient?.addTodo({ ...todo, status: 'pending', updated_at: now, completed_at: undefined }, todo.planIds);
              }
            });
          }}
          onMoveSession={(sessionId) => {
            // TODO: Show entity picker to move session
            console.log('Move session:', sessionId);
          }}
          onUnbindSession={(sessionId) => {
            // Get current binding and unbind
            goalsClient?.getSessionBinding(sessionId).then(binding => {
              if (binding) {
                const [, entityId] = binding;
                goalsClient?.unbindSession(entityId, sessionId);
              }
            });
          }}
          onRollup={(scopeType, scopeId) => {
            // TODO: Trigger rollup generation
            console.log('Generate rollup for:', scopeType, scopeId);
          }}
          onNewBareSession={onNewBareSession}
          isLoading={connectionState !== 'connected'}
          creatingSessionFor={creatingSessionFor}
        />
      ) : viewMode === 'tree' ? (
        <SessionTreeView
          sessions={sessions}
          selectedSessionId={selectedSessionId}
          onSelectSession={handleSelectSession}
          onTogglePin={onTogglePin}
          isLoading={connectionState !== 'connected'}
          onReviewSession={onReviewSession}
          onLinkSession={onLinkSession}
          onWatchSession={onWatchSession}
          sessionDataClient={connectionState === 'connected' ? client?.sessionData : undefined}
        />
      ) : viewMode === 'hierarchy' ? (
        <HierarchyView
          sessions={sessions}
          selectedSessionId={selectedSessionId}
          onSelectSession={handleSelectSession}
          onDeleteSession={onDeleteSession}
          onLinkSession={onLinkSession}
          onConcludeSession={onConcludeSession}
          onForkSession={onForkSession}
          isLoading={connectionState !== 'connected'}
          unreadSessionIds={unreadSessionIds}
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
            const isPinned = session.isPinned ?? false;
            return (
              <SessionListItem
                key={session.id}
                session={session}
                isSelected={isSelected}
                isPinned={isPinned}
                showStreamingDetails={!!showStreamingDetails}
                streamingTask={streamingTask}
                onSelect={() => handleSelectSession(session.id)}
                onTogglePin={onTogglePin ? () => onTogglePin(session.id) : undefined}
                onRequestRename={client?.isConnected ? () => setRenameModalSession(session) : undefined}
                itemRef={(el) => {
                  if (el) sessionItemRefs.current.set(session.id, el);
                  else sessionItemRefs.current.delete(session.id);
                }}
              />
            );
          })}
        </div>
      )}

      {/* Single shared rename modal for all sessions in the list */}
      {client?.isConnected && renameModalSession && (
        <RenameSessionModal
          isOpen={!!renameModalSession}
          onClose={() => setRenameModalSession(null)}
          sessionId={renameModalSession.id}
          currentTitle={renameModalSession.title || renameModalSession.forkName || ''}
          client={client.sessions}
          sessionDataClient={client.sessionData}
          onRenamed={() => setRenameModalSession(null)}
          onNavigateToSession={onSelectSession}
        />
      )}
    </>
  );
}
