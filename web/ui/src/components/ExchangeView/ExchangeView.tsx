import React, { useState, useRef, useEffect, useMemo } from 'react';
import type { TurnInfo } from '../../../../generated/balloons-client';
import { MarkdownContent } from '../../MarkdownContent';
import './ExchangeView.css';

// Tool use state tracked during streaming (matches App.tsx ToolUseState)
export interface ToolUseState {
  toolUseId: string;
  toolName: string;
  turnIndex: number;
  toolIndex: number;
  exchangeId?: string;
  status: 'streaming' | 'executing' | 'completed' | 'error';
  inputJson: string;
  result?: string;
  isError?: boolean;
  startTime: number;
  endTime?: number;
}

interface ExchangeViewProps {
  exchangeId: string;
  turns: TurnInfo[];
  toolUses?: ToolUseState[];
  defaultExpanded?: boolean;
}

// Format JSON for display
const formatJson = (json: string | Record<string, unknown>) => {
  try {
    if (typeof json === 'string') {
      const parsed = JSON.parse(json);
      return JSON.stringify(parsed, null, 2);
    }
    return JSON.stringify(json, null, 2);
  } catch {
    return typeof json === 'string' ? json : JSON.stringify(json);
  }
};

// Get a preview of tool input/result
function getToolPreview(toolName: string, input: Record<string, unknown> | string | undefined, result?: string): string {
  try {
    const parsedInput = typeof input === 'string' ? JSON.parse(input || '{}') : (input || {});

    switch (toolName) {
      case 'Read': {
        const filePath = (parsedInput.file_path || '') as string;
        const fileName = filePath.split('/').pop() || filePath;
        if (result) {
          const lines = result.split('\n').length;
          return `${fileName} → ${lines} lines`;
        }
        return fileName;
      }
      case 'Edit': {
        const filePath = (parsedInput.file_path || '') as string;
        const fileName = filePath.split('/').pop() || filePath;
        const oldStr = (parsedInput.old_string || '') as string;
        const newStr = (parsedInput.new_string || '') as string;
        const oldLines = oldStr.split('\n').length;
        const newLines = newStr.split('\n').length;
        return `${fileName} → +${newLines}/-${oldLines}`;
      }
      case 'Write': {
        const filePath = (parsedInput.file_path || '') as string;
        const fileName = filePath.split('/').pop() || filePath;
        const content = (parsedInput.content || '') as string;
        const lines = content.split('\n').length;
        return `${fileName} → ${lines} lines`;
      }
      case 'Bash': {
        const command = (parsedInput.command || '') as string;
        return command.length > 40 ? command.slice(0, 40) + '...' : command;
      }
      case 'Glob': {
        const pattern = (parsedInput.pattern || '') as string;
        if (result) {
          const files = result.split('\n').filter(Boolean).length;
          return `${pattern} → ${files} files`;
        }
        return pattern;
      }
      case 'Grep': {
        const pattern = (parsedInput.pattern || '') as string;
        if (result) {
          const matches = result.split('\n').filter(Boolean).length;
          return `${pattern} → ${matches} matches`;
        }
        return pattern;
      }
      default:
        return toolName;
    }
  } catch {
    return toolName;
  }
}

// Get icon for tool
function getToolIcon(toolName: string): string {
  const icons: Record<string, string> = {
    'Read': '📖',
    'Edit': '✏️',
    'Write': '📝',
    'Bash': '$',
    'Glob': '🔍',
    'Grep': '🔎',
  };
  return icons[toolName] || '🔧';
}

// Get status icon
function getStatusIcon(status: 'streaming' | 'executing' | 'completed' | 'error' | undefined): string {
  switch (status) {
    case 'streaming': return '⏳';
    case 'executing': return '⚙️';
    case 'completed': return '✓';
    case 'error': return '✗';
    default: return '✓';
  }
}

// Compact turn row for the turn list
function TurnRow({
  turn,
  toolUse,
  toolResult,
  onClick,
  isActive
}: {
  turn: TurnInfo;
  toolUse?: ToolUseState;
  toolResult?: string;
  onClick?: () => void;
  isActive?: boolean;
}) {
  const role = turn.role;
  const blockType = turn.contentBlockType ?? 'text';

  // Determine what to display based on turn type
  if (role === 'user') {
    const preview = (turn.content || '').slice(0, 60) + ((turn.content?.length || 0) > 60 ? '...' : '');
    return (
      <div className={`turn-row user ${isActive ? 'active' : ''}`} onClick={onClick}>
        <span className="turn-row-icon">👤</span>
        <span className="turn-row-content">{preview || 'User message'}</span>
        <span className="turn-row-status">✓</span>
      </div>
    );
  }

  if (blockType === 'tool_use' || turn.toolUse) {
    const toolName = turn.toolUse?.toolName || toolUse?.toolName || 'Tool';
    const toolInput = turn.toolUse?.toolInput || (toolUse?.inputJson ? JSON.parse(toolUse.inputJson) : {});
    const result = toolUse?.result || toolResult;
    const status = toolUse?.status || (turn.streaming ? 'executing' : 'completed');
    const preview = getToolPreview(toolName, toolInput, result);

    return (
      <div className={`turn-row tool ${isActive ? 'active' : ''} ${status}`} onClick={onClick}>
        <span className="turn-row-icon">{getToolIcon(toolName)}</span>
        <span className="turn-row-content">{preview}</span>
        <span className={`turn-row-status ${status}`}>{getStatusIcon(status)}</span>
      </div>
    );
  }

  if (role === 'assistant') {
    const preview = (turn.content || '').slice(0, 60) + ((turn.content?.length || 0) > 60 ? '...' : '');
    const status = turn.streaming ? 'streaming' : 'completed';
    return (
      <div className={`turn-row assistant ${isActive ? 'active' : ''} ${status}`} onClick={onClick}>
        <span className="turn-row-icon">💬</span>
        <span className="turn-row-content">{preview || (turn.streaming ? 'Thinking...' : 'Response')}</span>
        <span className={`turn-row-status ${status}`}>{getStatusIcon(status)}</span>
      </div>
    );
  }

  // Fallback for other types
  return (
    <div className={`turn-row ${role} ${isActive ? 'active' : ''}`} onClick={onClick}>
      <span className="turn-row-icon">📄</span>
      <span className="turn-row-content">{turn.content?.slice(0, 60) || blockType}</span>
      <span className="turn-row-status">✓</span>
    </div>
  );
}

// Active preview panel for user message
function UserPanel({ turn }: { turn: TurnInfo }) {
  return (
    <div className="preview-panel user-panel">
      <div className="preview-panel-header">
        <span className="preview-panel-icon">👤</span>
        <span className="preview-panel-title">User</span>
      </div>
      <div className="preview-panel-content">
        {turn.content}
      </div>
    </div>
  );
}

// Active preview panel for assistant text
function AssistantPanel({
  turn,
  isStreaming
}: {
  turn: TurnInfo | null;
  isStreaming?: boolean;
}) {
  if (!turn) return null;

  return (
    <div className={`preview-panel assistant-panel ${isStreaming ? 'streaming' : ''}`}>
      <div className="preview-panel-header">
        <span className="preview-panel-icon">💬</span>
        <span className="preview-panel-title">Assistant</span>
        {isStreaming && <span className="streaming-indicator">●</span>}
      </div>
      <div className="preview-panel-content resizable">
        <MarkdownContent content={turn.content} />
      </div>
    </div>
  );
}

// Display tool input based on tool type
function ToolInputDisplay({
  toolName,
  input
}: {
  toolName: string;
  input: Record<string, unknown>;
}) {
  if (toolName === 'Edit') {
    const filePath = (input.file_path || '') as string;
    const oldString = (input.old_string || '') as string;
    const newString = (input.new_string || '') as string;

    return (
      <div className="tool-input-edit">
        <div className="tool-input-path">{filePath}</div>
        <div className="diff-view">
          {oldString.split('\n').map((line, i) => (
            <div key={`old-${i}`} className="diff-line diff-remove">-{line}</div>
          ))}
          {newString.split('\n').map((line, i) => (
            <div key={`new-${i}`} className="diff-line diff-add">+{line}</div>
          ))}
        </div>
      </div>
    );
  }

  if (toolName === 'Bash') {
    return (
      <pre className="tool-input-bash"><code>{input.command as string}</code></pre>
    );
  }

  if (toolName === 'Read' || toolName === 'Write' || toolName === 'Glob' || toolName === 'Grep') {
    const filePath = (input.file_path || input.path || input.pattern || '') as string;
    return (
      <div className="tool-input-path">{filePath}</div>
    );
  }

  // Default: show JSON
  return (
    <pre className="tool-input-json"><code>{formatJson(input)}</code></pre>
  );
}

// Active preview panel for tool execution
function ToolPanel({
  turn,
  toolUse,
  toolResult
}: {
  turn?: TurnInfo | null;
  toolUse?: ToolUseState | null;
  toolResult?: string | null;
}) {
  // Prefer streaming toolUse state, fall back to turn data
  const toolName = toolUse?.toolName || turn?.toolUse?.toolName || 'Tool';
  const status = toolUse?.status || (turn?.streaming ? 'executing' : 'completed');
  const inputJson = toolUse?.inputJson || (turn?.toolUse?.toolInput ? JSON.stringify(turn.toolUse.toolInput) : '{}');
  // Use result from streaming toolUse, or from matched tool_result turn
  const result = toolUse?.result ?? toolResult;
  const isError = toolUse?.isError;

  if (!turn && !toolUse) return null;

  let parsedInput: Record<string, unknown> = {};
  try {
    parsedInput = JSON.parse(inputJson);
  } catch {
    // Streaming, incomplete JSON
  }

  const hasInput = Object.keys(parsedInput).length > 0;
  const hasResult = result !== undefined && result !== null;

  return (
    <div className={`preview-panel tool-panel ${status}`}>
      <div className="preview-panel-header">
        <span className="preview-panel-icon">{getToolIcon(toolName)}</span>
        <span className="preview-panel-title">{toolName}</span>
        <span className={`preview-panel-status ${status}`}>{getStatusIcon(status)}</span>
      </div>

      {/* Tool input */}
      {hasInput && (
        <div className="tool-section">
          <div className="tool-section-header">Input</div>
          <div className="tool-section-content">
            <ToolInputDisplay toolName={toolName} input={parsedInput} />
          </div>
        </div>
      )}

      {/* Tool result */}
      {hasResult && (
        <div className={`tool-section ${isError ? 'error' : ''}`}>
          <div className="tool-section-header">{isError ? 'Error' : 'Result'}</div>
          <div className="tool-section-content resizable">
            <pre className="tool-result"><code>{result.slice(0, 2000)}{result.length > 2000 ? '\n...[truncated]' : ''}</code></pre>
          </div>
        </div>
      )}

      {/* Executing indicator */}
      {status === 'executing' && !hasResult && (
        <div className="tool-executing">
          <span className="spinner">⚙️</span> Executing...
        </div>
      )}

      {/* No content fallback */}
      {!hasInput && !hasResult && status !== 'executing' && (
        <div className="tool-section">
          <div className="tool-section-content">
            <em>No details available</em>
          </div>
        </div>
      )}
    </div>
  );
}

// Detail view for a selected turn
function TurnDetail({
  turn,
  toolUse,
  toolResult,
  onClose
}: {
  turn: TurnInfo;
  toolUse?: ToolUseState;
  toolResult?: string;
  onClose: () => void;
}) {
  const role = turn.role;
  const blockType = turn.contentBlockType ?? 'text';

  // Tool turn
  if (blockType === 'tool_use' || turn.toolUse) {
    const toolName = turn.toolUse?.toolName || toolUse?.toolName || 'Tool';
    const status = toolUse?.status || (turn.streaming ? 'executing' : 'completed');
    const inputJson = toolUse?.inputJson || (turn.toolUse?.toolInput ? JSON.stringify(turn.toolUse.toolInput) : '{}');
    const result = toolUse?.result || toolResult;
    const isError = toolUse?.isError;

    let parsedInput: Record<string, unknown> = {};
    try {
      parsedInput = JSON.parse(inputJson);
    } catch {
      // Streaming, incomplete JSON
    }

    const hasInput = Object.keys(parsedInput).length > 0;
    const hasResult = result !== undefined && result !== null;

    return (
      <div className="turn-detail">
        <div className="turn-detail-header">
          <span className="turn-detail-icon">{getToolIcon(toolName)}</span>
          <span className="turn-detail-title">{toolName}</span>
          <span className="turn-detail-idx">Turn #{turn.idx}</span>
          <button className="turn-detail-close" onClick={onClose}>×</button>
        </div>

        {hasInput && (
          <div className="tool-section">
            <div className="tool-section-header">Input</div>
            <div className="tool-section-content resizable">
              <ToolInputDisplay toolName={toolName} input={parsedInput} />
            </div>
          </div>
        )}

        {hasResult && (
          <div className={`tool-section ${isError ? 'error' : ''}`}>
            <div className="tool-section-header">{isError ? 'Error' : 'Result'}</div>
            <div className="tool-section-content resizable">
              <pre className="tool-result"><code>{result}</code></pre>
            </div>
          </div>
        )}

        {status === 'executing' && !hasResult && (
          <div className="tool-executing">
            <span className="spinner">⚙️</span> Executing...
          </div>
        )}
      </div>
    );
  }

  // User turn
  if (role === 'user') {
    return (
      <div className="turn-detail">
        <div className="turn-detail-header">
          <span className="turn-detail-icon">👤</span>
          <span className="turn-detail-title">User</span>
          <span className="turn-detail-idx">Turn #{turn.idx}</span>
          <button className="turn-detail-close" onClick={onClose}>×</button>
        </div>
        <div className="turn-detail-content">
          {turn.content}
        </div>
      </div>
    );
  }

  // Assistant turn
  if (role === 'assistant') {
    return (
      <div className="turn-detail">
        <div className="turn-detail-header">
          <span className="turn-detail-icon">💬</span>
          <span className="turn-detail-title">Assistant</span>
          <span className="turn-detail-idx">Turn #{turn.idx}</span>
          <button className="turn-detail-close" onClick={onClose}>×</button>
        </div>
        <div className="turn-detail-content resizable">
          <MarkdownContent content={turn.content} />
        </div>
      </div>
    );
  }

  // Fallback
  return (
    <div className="turn-detail">
      <div className="turn-detail-header">
        <span className="turn-detail-icon">📄</span>
        <span className="turn-detail-title">{blockType}</span>
        <span className="turn-detail-idx">Turn #{turn.idx}</span>
        <button className="turn-detail-close" onClick={onClose}>×</button>
      </div>
      <div className="turn-detail-content">
        {turn.content}
      </div>
    </div>
  );
}

// Helper to find matching tool result for a tool_use turn
function findToolResult(turns: TurnInfo[], toolUseId: string | undefined): string | null {
  if (!toolUseId) return null;

  const resultTurn = turns.find(t =>
    (t.contentBlockType === 'tool_result' || t.role === 'tool') &&
    t.toolResult?.toolUseId === toolUseId
  );

  return resultTurn?.toolResult?.content || resultTurn?.content || null;
}

// Main ExchangeView component
export function ExchangeView({
  exchangeId,
  turns,
  toolUses = [],
  defaultExpanded = false
}: ExchangeViewProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [selectedTurnIdx, setSelectedTurnIdx] = useState<number | null>(null);
  const turnListRef = useRef<HTMLDivElement>(null);

  // Determine if exchange is streaming
  const isStreaming = turns.some(t => t.streaming) || toolUses.some(tu =>
    tu.status === 'streaming' || tu.status === 'executing'
  );

  // Auto-expand when streaming
  useEffect(() => {
    if (isStreaming) {
      setExpanded(true);
    }
  }, [isStreaming]);

  // Derive exchange components from turns (no memoization to ensure updates flow through)
  const userTurn = turns.find(t => t.role === 'user');

  const assistantTextTurns = turns.filter(t =>
    t.role === 'assistant' &&
    (t.contentBlockType === 'text' || !t.contentBlockType) &&
    !t.toolUse // Exclude tool_use turns that might have role=assistant
  );

  // Tool turns: include turns with tool_use content type OR that have toolUse property
  const toolTurns = turns.filter(t =>
    t.contentBlockType === 'tool_use' ||
    t.toolUse != null ||
    t.role === 'tool'
  );

  // All turns for display in the list
  // - Exclude tool_result (shown with tool_use)
  // - Exclude tool role (tool results)
  // - Exclude empty streaming assistant turns that will become tool_use turns
  const allDisplayTurns = turns.filter(t => {
    if (t.contentBlockType === 'tool_result') return false;
    if (t.role === 'tool') return false;
    // Hide empty assistant turns that are placeholders for tool_use
    // (they'll be properly shown once toolUse property is populated)
    if (t.role === 'assistant' && t.streaming && !t.content?.trim() && !t.toolUse) {
      // Keep the first streaming assistant turn (the text response)
      // But hide subsequent empty ones that are tool_use placeholders
      const firstStreamingAssistant = turns.find(
        turn => turn.role === 'assistant' && turn.streaming
      );
      if (firstStreamingAssistant && t.idx !== firstStreamingAssistant.idx) {
        return false;
      }
    }
    return true;
  });

  // Latest assistant text (for preview panel)
  const latestAssistantText = assistantTextTurns[assistantTextTurns.length - 1];

  // Active tool - prefer streaming, fall back to latest tool turn
  const activeStreamingTool = toolUses.find(tu =>
    tu.exchangeId === exchangeId && (tu.status === 'streaming' || tu.status === 'executing')
  ) || toolUses.filter(tu => tu.exchangeId === exchangeId).pop();

  const latestToolTurn = toolTurns[toolTurns.length - 1];

  // Find the result for the latest tool turn
  const latestToolResult = latestToolTurn?.toolUse?.toolUseId
    ? findToolResult(turns, latestToolTurn.toolUse.toolUseId)
    : null;

  // Calculate exchange stats
  const turnCount = turns.length;
  const tokenCount = turns.reduce((sum, t) => sum + (t.tokens || 0), 0);

  // Auto-scroll turn list to bottom during streaming
  useEffect(() => {
    if (isStreaming && turnListRef.current) {
      turnListRef.current.scrollTop = turnListRef.current.scrollHeight;
    }
  }, [isStreaming, allDisplayTurns.length]);

  // Create a map of toolUses by turn index for matching
  const toolUsesByTurnIdx = useMemo(() => {
    const map = new Map<number, ToolUseState>();
    for (const tu of toolUses) {
      if (tu.exchangeId === exchangeId) {
        map.set(tu.turnIndex, tu);
      }
    }
    return map;
  }, [toolUses, exchangeId]);

  // Create a map of tool results by toolUseId
  const toolResultsByUseId = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of turns) {
      if ((t.contentBlockType === 'tool_result' || t.role === 'tool') && t.toolResult?.toolUseId) {
        map.set(t.toolResult.toolUseId, t.toolResult.content || t.content || '');
      }
    }
    return map;
  }, [turns]);

  if (!expanded) {
    // Collapsed view - single line summary
    const userPreview = userTurn?.content?.slice(0, 60) || 'Exchange';
    const suffix = userPreview.length < (userTurn?.content?.length || 0) ? '...' : '';
    const status = isStreaming ? 'streaming' : 'complete';

    return (
      <div className={`exchange-view collapsed ${status}`} onClick={() => setExpanded(true)}>
        <div className="exchange-header">
          <span className="exchange-icon">💬</span>
          <code className="exchange-id">{exchangeId.slice(0, 8)}</code>
          <span className="exchange-summary">
            <span className="exchange-user-preview">{userPreview}{suffix}</span>
            {!isStreaming && <span className="exchange-outcome"> {'→'} {toolTurns.length} tools</span>}
          </span>
          <span className="exchange-stats">{turnCount} turns{tokenCount > 0 ? ` • ${(tokenCount / 1000).toFixed(1)}k` : ''}</span>
          {isStreaming && <span className="streaming-dot">●</span>}
        </div>
      </div>
    );
  }

  // Expanded view
  return (
    <div className={`exchange-view expanded ${isStreaming ? 'streaming' : ''}`}>
      <div className="exchange-header" onClick={() => setExpanded(false)}>
        <span className="exchange-icon">▼</span>
        <span className="exchange-title">Exchange</span>
        <code className="exchange-id">{exchangeId.slice(0, 8)}</code>
        <span className="exchange-stats">{turnCount} turns{tokenCount > 0 ? ` • ${(tokenCount / 1000).toFixed(1)}k` : ''}</span>
        {isStreaming && <span className="streaming-dot">●</span>}
      </div>

      {/* Active Preview Panels */}
      <div className="active-preview">
        {userTurn && <UserPanel turn={userTurn} />}

        {latestAssistantText && (
          <AssistantPanel
            turn={latestAssistantText}
            isStreaming={latestAssistantText.streaming}
          />
        )}

        {(activeStreamingTool || latestToolTurn) && (
          <ToolPanel
            turn={latestToolTurn}
            toolUse={activeStreamingTool}
            toolResult={latestToolResult}
          />
        )}
      </div>

      {/* Selected Turn Detail (replaces preview panels when a turn is selected) */}
      {selectedTurnIdx !== null && (() => {
        const selectedTurn = allDisplayTurns.find(t => t.idx === selectedTurnIdx);
        if (!selectedTurn) return null;
        const toolUse = toolUsesByTurnIdx.get(selectedTurnIdx);
        const toolResult = selectedTurn.toolUse?.toolUseId
          ? toolResultsByUseId.get(selectedTurn.toolUse.toolUseId)
          : undefined;

        return (
          <TurnDetail
            turn={selectedTurn}
            toolUse={toolUse}
            toolResult={toolResult}
            onClose={() => setSelectedTurnIdx(null)}
          />
        );
      })()}

      {/* Turn List */}
      <div className="turn-list" ref={turnListRef}>
        {allDisplayTurns.map((turn) => {
          const toolUse = toolUsesByTurnIdx.get(turn.idx);
          const toolResult = turn.toolUse?.toolUseId
            ? toolResultsByUseId.get(turn.toolUse.toolUseId)
            : undefined;

          return (
            <TurnRow
              key={`${exchangeId}-turn-${turn.idx}`}
              turn={turn}
              toolUse={toolUse}
              toolResult={toolResult}
              isActive={selectedTurnIdx === turn.idx}
              onClick={() => setSelectedTurnIdx(selectedTurnIdx === turn.idx ? null : turn.idx)}
            />
          );
        })}
      </div>
    </div>
  );
}

export default ExchangeView;
