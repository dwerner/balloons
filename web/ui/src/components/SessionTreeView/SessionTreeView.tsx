/**
 * SessionTreeView - Tree view showing sessions with exchanges and turns
 *
 * This is the React equivalent of context_tree.py from the TUI.
 * Features:
 * - Expandable session nodes with token counts
 * - Exchange grouping with COPY/COMPRESS/DROP dropdowns
 * - Turn nodes showing user/assistant messages
 * - Inline tool use display with collapsible input/output
 * - Fork/merge indicators
 * - Mobile-optimized touch interactions
 */

import React, { useState, useCallback, useMemo, memo, useEffect, useRef } from 'react';
import type { SessionInfo, TurnInfo } from '../../../../generated/balloons-client';
import './SessionTreeView.css';

// Context modes for turns
export type ContextMode = 'COPY' | 'COMPRESS' | 'DROP';

// Session colors for visual distinction (matches Python SESSION_COLORS)
const SESSION_COLORS = [
  '#60a5fa', // blue
  '#c084fc', // magenta/purple
  '#22d3ee', // cyan
  '#4ade80', // green
  '#facc15', // yellow
  '#f87171', // red
];

// Get color for a session based on its index
function getSessionColor(index: number): string {
  const color = SESSION_COLORS[index % SESSION_COLORS.length];
  return color !== undefined ? color : '#60a5fa';
}

// Format token count as kt (e.g., 1500 -> "1.5kt", 200 -> ".2kt")
function formatKt(tokens: number): string {
  if (tokens <= 0) return '';
  const kt = Math.ceil(tokens / 100) / 10;
  if (kt < 1) return `.${Math.floor(kt * 10)}kt`;
  return `${kt.toFixed(1)}kt`;
}

// Get color for token count (green -> yellow -> red based on size)
function getTokenColor(tokens: number, maxTokens: number = 50000): string {
  if (tokens <= 0) return 'var(--color-accent-green)';
  if (tokens >= maxTokens) return 'rgb(255, 50, 50)';

  const t = tokens / maxTokens;
  const midPoint = 0.5;

  if (t <= midPoint) {
    // Phase 1: green -> yellow
    const phaseT = t / midPoint;
    const r = Math.floor(255 * phaseT);
    return `rgb(${r}, 255, 0)`;
  } else {
    // Phase 2: yellow -> red
    const phaseT = (t - midPoint) / (1 - midPoint);
    const g = Math.floor(255 * (1 - phaseT) + 50 * phaseT);
    const b = Math.floor(50 * phaseT);
    return `rgb(255, ${g}, ${b})`;
  }
}

// Get model icon based on model name
function getModelIcon(model: string | null | undefined): { icon: string; color: string } | null {
  if (!model) return null;
  const modelLower = model.toLowerCase();

  if (modelLower.includes('opus')) return { icon: '◆', color: '#c084fc' };
  if (modelLower.includes('sonnet')) return { icon: '◇', color: '#22d3ee' };
  if (modelLower.includes('haiku')) return { icon: '○', color: '#4ade80' };
  if (modelLower.includes('claude')) return { icon: '●', color: '#60a5fa' };
  if (modelLower.includes('gpt-4') || modelLower.includes('gpt4')) return { icon: '★', color: '#facc15' };
  if (modelLower.includes('gpt-3') || modelLower.includes('gpt3')) return { icon: '☆', color: '#facc15' };
  if (modelLower.includes('o1') || modelLower.includes('o3')) return { icon: '✦', color: '#f87171' };
  if (modelLower.includes('llama')) return { icon: '▲', color: '#fb923c' };

  return null;
}

// ----- Types -----

interface ExchangeGroup {
  exchangeId: string;
  turns: TurnInfo[];
  totalTokens: number;
  mode: ContextMode;
}

interface SessionTreeViewProps {
  sessions: SessionInfo[];
  selectedSessionId: string | null;
  turns: TurnInfo[];
  onSelectSession: (sessionId: string) => void;
  onSelectTurn?: (turnIdx: number) => void;
  onContextModeChange?: (sessionId: string, turnIdx: number, mode: ContextMode) => void;
  onLinkSession?: (sessionId: string) => void;
  isLoading?: boolean;
}

// ----- Sub-components -----

// Mode selector dropdown
const ModeSelector = memo(function ModeSelector({
  mode,
  onChange,
  disabled = false,
}: {
  mode: ContextMode;
  onChange: (mode: ContextMode) => void;
  disabled?: boolean;
}) {
  const handleChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    e.stopPropagation();
    onChange(e.target.value as ContextMode);
  }, [onChange]);

  const modeConfig: Record<string, { label: string; color: string; title: string }> = {
    COPY: { label: '☑', color: 'var(--color-accent-green)', title: 'Copy (include in context)' },
    COMPRESS: { label: 'Σ', color: 'var(--color-accent-yellow)', title: 'Compress (summarize)' },
    DROP: { label: '☐', color: 'var(--color-text-muted)', title: 'Drop (exclude from context)' },
  };

  // Handle case-insensitive mode matching with guaranteed fallback
  const normalizedMode = mode.toUpperCase();
  const defaultConfig = { label: '☑', color: 'var(--color-accent-green)', title: 'Copy (include in context)' };
  const config = modeConfig[normalizedMode] || defaultConfig;

  return (
    <select
      className="tree-mode-selector"
      value={mode}
      onChange={handleChange}
      onClick={e => e.stopPropagation()}
      disabled={disabled}
      title={config.title}
      style={{ color: config.color }}
    >
      <option value="COPY">☑</option>
      <option value="COMPRESS">Σ</option>
      <option value="DROP">☐</option>
    </select>
  );
});

// Turn node component
const TurnNode = memo(function TurnNode({
  turn,
  sessionId,
  isSelected,
  onSelect,
  onModeChange,
}: {
  turn: TurnInfo;
  sessionId: string;
  isSelected: boolean;
  onSelect?: () => void;
  onModeChange?: (mode: ContextMode) => void;
}) {
  const blockType = turn.contentBlockType ?? 'text';

  // Get role icon and color
  const getRoleDisplay = () => {
    switch (turn.role) {
      case 'user':
        return { icon: '👤', label: 'user', color: 'var(--color-accent-blue)' };
      case 'assistant':
        return { icon: '🤖', label: 'assistant', color: 'var(--color-accent-green)' };
      case 'tool':
        return { icon: '⚙', label: 'tool', color: 'var(--color-accent-yellow)' };
      case 'system':
        return { icon: '⚡', label: 'system', color: 'var(--color-text-muted)' };
      default:
        return { icon: '?', label: turn.role, color: 'var(--color-text-secondary)' };
    }
  };

  // Get special block type display
  const getBlockTypeDisplay = () => {
    switch (blockType) {
      case 'fork':
        return { icon: '🔀', label: 'Fork', color: '#60a5fa' };
      case 'merge':
        return { icon: '⬅️', label: 'Merged', color: '#34d399' };
      case 'merged_to':
        return { icon: '➡️', label: 'Merged to parent', color: '#34d399' };
      case 'link':
        return { icon: '🔗', label: 'Link', color: '#a78bfa' };
      case 'archive':
        return { icon: '📦', label: 'Archive', color: '#6b7280' };
      case 'error':
        return { icon: '✗', label: 'Error', color: '#f87171' };
      case 'interruption':
        return { icon: '⚠', label: 'Interrupted', color: '#f87171' };
      case 'tool_use':
        return { icon: '⚙', label: turn.toolUse?.toolName ?? 'Tool', color: '#facc15' };
      case 'tool_result':
        return { icon: '📋', label: 'Result', color: '#facc15' };
      default:
        return null;
    }
  };

  const roleDisplay = getRoleDisplay();
  const blockDisplay = getBlockTypeDisplay();
  const displayInfo = blockDisplay || roleDisplay;

  // Truncate content for preview
  const preview = useMemo(() => {
    const content = turn.content || '';
    const truncated = content.slice(0, 50).replace(/\n/g, ' ');
    return content.length > 50 ? truncated + '...' : truncated;
  }, [turn.content]);

  const tokenStr = formatKt(turn.tokens);
  const tokenColor = getTokenColor(turn.tokens);

  return (
    <div
      className={`tree-turn-node ${isSelected ? 'selected' : ''} ${turn.streaming ? 'streaming' : ''}`}
      onClick={onSelect}
      role="treeitem"
      aria-selected={isSelected}
    >
      <div className="tree-turn-content">
        {onModeChange && (
          <ModeSelector
            mode={turn.contextMode as ContextMode}
            onChange={onModeChange}
          />
        )}
        <span className="tree-turn-icon" style={{ color: displayInfo.color }}>
          {displayInfo.icon}
        </span>
        <span className="tree-turn-preview">{preview || '\u00A0'}</span>
        {tokenStr && (
          <span className="tree-turn-tokens" style={{ color: tokenColor }}>
            {tokenStr}
          </span>
        )}
      </div>
    </div>
  );
});

// Exchange group component (collapsible group of turns)
const ExchangeGroupNode = memo(function ExchangeGroupNode({
  group,
  sessionId,
  isExpanded,
  onToggle,
  onTurnSelect,
  onModeChange,
  selectedTurnIdx,
}: {
  group: ExchangeGroup;
  sessionId: string;
  isExpanded: boolean;
  onToggle: () => void;
  onTurnSelect?: (turnIdx: number) => void;
  onModeChange?: (turnIdx: number, mode: ContextMode) => void;
  selectedTurnIdx?: number;
}) {
  // Get first user message for preview
  const firstUserTurn = group.turns.find(t => t.role === 'user');
  const preview = useMemo(() => {
    const content = firstUserTurn?.content || '';
    const truncated = content.slice(0, 30).replace(/\n/g, ' ');
    return content.length > 30 ? truncated + '...' : truncated;
  }, [firstUserTurn?.content]);

  const tokenStr = formatKt(group.totalTokens);
  const tokenColor = getTokenColor(group.totalTokens);

  // Determine group mode based on constituent turns
  const groupModeConfig = {
    COPY: { label: '☑', color: 'var(--color-accent-green)' },
    COMPRESS: { label: 'Σ', color: 'var(--color-accent-yellow)' },
    DROP: { label: '☐', color: 'var(--color-text-muted)' },
  };
  const modeConfig = groupModeConfig[group.mode];

  return (
    <div className="tree-exchange-group">
      <div
        className="tree-exchange-header"
        onClick={onToggle}
        role="treeitem"
        aria-expanded={isExpanded}
      >
        <span className={`tree-expand-icon ${isExpanded ? 'expanded' : ''}`}>
          {isExpanded ? '▼' : '▶'}
        </span>
        {tokenStr && (
          <span className="tree-group-tokens" style={{ color: tokenColor }}>
            {tokenStr}
          </span>
        )}
        <span className="tree-group-mode" style={{ color: modeConfig.color }}>
          {modeConfig.label}
        </span>
        <span className="tree-group-icon">🤖</span>
        <span className="tree-group-preview">{preview || 'Agent exchange'}</span>
        <span className="tree-group-count">({group.turns.length} turns)</span>
      </div>

      {isExpanded && (
        <div className="tree-exchange-children" role="group">
          {group.turns.map(turn => (
            <TurnNode
              key={turn.idx}
              turn={turn}
              sessionId={sessionId}
              isSelected={selectedTurnIdx === turn.idx}
              onSelect={onTurnSelect ? () => onTurnSelect(turn.idx) : undefined}
              onModeChange={onModeChange ? (mode) => onModeChange(turn.idx, mode) : undefined}
            />
          ))}
        </div>
      )}
    </div>
  );
});

// Session node component
const SessionNode = memo(function SessionNode({
  session,
  index,
  isSelected,
  isExpanded,
  turns,
  onToggle,
  onSelect,
  onTurnSelect,
  onModeChange,
  onLink,
  selectedTurnIdx,
}: {
  session: SessionInfo;
  index: number;
  isSelected: boolean;
  isExpanded: boolean;
  turns: TurnInfo[];
  onToggle: () => void;
  onSelect: () => void;
  onTurnSelect?: (turnIdx: number) => void;
  onModeChange?: (turnIdx: number, mode: ContextMode) => void;
  onLink?: () => void;
  selectedTurnIdx?: number;
}) {
  const sessionColor = getSessionColor(index);
  const modelIcon = getModelIcon(session.model);

  // Calculate total tokens (use cachedContextTokens if available, otherwise estimate)
  const totalTokens = session.cachedContextTokens ?? (session.messageCount * 500);
  const tokenStr = formatKt(totalTokens);
  const tokenColor = getTokenColor(totalTokens);

  // Group turns by exchange ID
  const exchangeGroups = useMemo(() => {
    const groups: ExchangeGroup[] = [];
    const exchangeMap = new Map<string, TurnInfo[]>();
    const noExchangeTurns: TurnInfo[] = [];

    turns.forEach(turn => {
      if (turn.exchangeId) {
        const existing = exchangeMap.get(turn.exchangeId);
        if (existing) {
          existing.push(turn);
        } else {
          exchangeMap.set(turn.exchangeId, [turn]);
        }
      } else {
        noExchangeTurns.push(turn);
      }
    });

    // Add exchange groups
    exchangeMap.forEach((groupTurns, exchangeId) => {
      const totalTokens = groupTurns.reduce((sum, t) => sum + t.tokens, 0);
      const modes = groupTurns.map(t => t.contextMode as ContextMode);
      let mode: ContextMode = 'COPY';
      if (modes.every(m => m === 'DROP')) mode = 'DROP';
      else if (modes.every(m => m === 'COPY')) mode = 'COPY';
      else mode = 'COMPRESS';

      groups.push({
        exchangeId,
        turns: groupTurns,
        totalTokens,
        mode,
      });
    });

    // Add standalone turns as single-turn groups
    noExchangeTurns.forEach(turn => {
      groups.push({
        exchangeId: `standalone-${turn.idx}`,
        turns: [turn],
        totalTokens: turn.tokens,
        mode: turn.contextMode as ContextMode,
      });
    });

    // Sort by first turn index
    groups.sort((a, b) => {
      const aFirst = a.turns[0];
      const bFirst = b.turns[0];
      if (!aFirst || !bFirst) return 0;
      return aFirst.idx - bFirst.idx;
    });

    return groups;
  }, [turns]);

  // Track expanded exchange groups
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  const toggleGroup = useCallback((exchangeId: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      if (next.has(exchangeId)) {
        next.delete(exchangeId);
      } else {
        next.add(exchangeId);
      }
      return next;
    });
  }, []);

  // Handle link action (ctrl+click on desktop, long press on mobile)
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    if (onLink) {
      e.preventDefault();
      onLink();
    }
  }, [onLink]);

  // Fork status indicator
  const getForkIndicator = () => {
    if (!session.parentId) return null;
    if (session.forkStatus === 'merged') {
      return <span className="tree-fork-indicator merged" title="Merged">✓</span>;
    }
    return <span className="tree-fork-indicator" title="Fork">↳</span>;
  };

  // Session name: fork name, title, or ID prefix
  const sessionName = session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;

  return (
    <div
      className={`tree-session-node ${isSelected ? 'selected' : ''} ${session.isStreaming ? 'streaming' : ''}`}
      role="treeitem"
      aria-expanded={isExpanded}
      aria-selected={isSelected}
    >
      <div
        className="tree-session-header"
        onClick={onSelect}
        onContextMenu={handleContextMenu}
      >
        <span
          className={`tree-expand-icon ${isExpanded ? 'expanded' : ''}`}
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
          style={{ color: sessionColor }}
        >
          {isExpanded ? '▼' : '▶'}
        </span>

        {session.isStreaming && (
          <span className="tree-streaming-indicator" title="Streaming">⟳</span>
        )}

        {getForkIndicator()}

        {modelIcon && (
          <span className="tree-model-icon" style={{ color: modelIcon.color }}>
            {modelIcon.icon}
          </span>
        )}

        <span className="tree-session-id">{session.id.slice(0, 8)}</span>
        <span className="tree-session-name">{sessionName}</span>

        {session.bindingIndicator && (
          <span className="tree-binding-indicator" title={session.bindingIndicator}>
            [{session.bindingIndicator.slice(0, 15)}]
          </span>
        )}

        <span className="tree-session-meta">
          ({session.messageCount}msg {tokenStr && <span style={{ color: tokenColor }}>{tokenStr}</span>})
        </span>
      </div>

      {isExpanded && turns.length > 0 && (
        <div className="tree-session-children" role="group">
          {exchangeGroups.map(group => {
            // Render single-turn groups directly as turns
            if (group.turns.length === 1) {
              const turn = group.turns[0];
              if (!turn) return null;
              return (
                <TurnNode
                  key={turn.idx}
                  turn={turn}
                  sessionId={session.id}
                  isSelected={selectedTurnIdx === turn.idx}
                  onSelect={onTurnSelect ? () => onTurnSelect(turn.idx) : undefined}
                  onModeChange={onModeChange ? (mode) => onModeChange(turn.idx, mode) : undefined}
                />
              );
            }

            // Render multi-turn groups as collapsible exchanges
            return (
              <ExchangeGroupNode
                key={group.exchangeId}
                group={group}
                sessionId={session.id}
                isExpanded={expandedGroups.has(group.exchangeId)}
                onToggle={() => toggleGroup(group.exchangeId)}
                onTurnSelect={onTurnSelect}
                onModeChange={onModeChange}
                selectedTurnIdx={selectedTurnIdx}
              />
            );
          })}
        </div>
      )}
    </div>
  );
});

// ----- Main Component -----

export const SessionTreeView = memo(function SessionTreeView({
  sessions,
  selectedSessionId,
  turns,
  onSelectSession,
  onSelectTurn,
  onContextModeChange,
  onLinkSession,
  isLoading = false,
}: SessionTreeViewProps) {
  // Track which sessions are expanded
  const [expandedSessions, setExpandedSessions] = useState<Set<string>>(() => {
    // Auto-expand the selected session
    return selectedSessionId ? new Set([selectedSessionId]) : new Set();
  });

  // Track selected turn within the selected session
  const [selectedTurnIdx, setSelectedTurnIdx] = useState<number | undefined>();

  // Scroll container ref for auto-scroll
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-expand selected session when it changes
  useEffect(() => {
    if (selectedSessionId) {
      setExpandedSessions(prev => {
        if (prev.has(selectedSessionId)) return prev;
        const next = new Set(prev);
        next.add(selectedSessionId);
        return next;
      });
    }
  }, [selectedSessionId]);

  const toggleSession = useCallback((sessionId: string) => {
    setExpandedSessions(prev => {
      const next = new Set(prev);
      if (next.has(sessionId)) {
        next.delete(sessionId);
      } else {
        next.add(sessionId);
      }
      return next;
    });
  }, []);

  const handleSelectSession = useCallback((sessionId: string) => {
    onSelectSession(sessionId);
    setSelectedTurnIdx(undefined);
  }, [onSelectSession]);

  const handleSelectTurn = useCallback((turnIdx: number) => {
    setSelectedTurnIdx(turnIdx);
    onSelectTurn?.(turnIdx);
  }, [onSelectTurn]);

  const handleModeChange = useCallback((turnIdx: number, mode: ContextMode) => {
    if (selectedSessionId && onContextModeChange) {
      onContextModeChange(selectedSessionId, turnIdx, mode);
    }
  }, [selectedSessionId, onContextModeChange]);

  // Sort sessions by last modified (most recent first)
  const sortedSessions = useMemo(() => {
    return [...sessions].sort((a, b) => {
      // Current session always first
      if (a.isCurrent) return -1;
      if (b.isCurrent) return 1;
      // Then by last modified
      return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
    });
  }, [sessions]);

  if (isLoading) {
    return (
      <div className="tree-view-container">
        <div className="tree-loading">
          <span className="tree-loading-spinner">⟳</span>
          <span>Loading sessions...</span>
        </div>
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="tree-view-container">
        <div className="tree-empty">
          <span>No sessions</span>
        </div>
      </div>
    );
  }

  return (
    <div className="tree-view-container" ref={containerRef} role="tree" aria-label="Session tree">
      {sortedSessions.map((session, index) => (
        <SessionNode
          key={session.id}
          session={session}
          index={index}
          isSelected={session.id === selectedSessionId}
          isExpanded={expandedSessions.has(session.id)}
          turns={session.id === selectedSessionId ? turns : []}
          onToggle={() => toggleSession(session.id)}
          onSelect={() => handleSelectSession(session.id)}
          onTurnSelect={session.id === selectedSessionId ? handleSelectTurn : undefined}
          onModeChange={session.id === selectedSessionId ? handleModeChange : undefined}
          onLink={onLinkSession ? () => onLinkSession(session.id) : undefined}
          selectedTurnIdx={session.id === selectedSessionId ? selectedTurnIdx : undefined}
        />
      ))}
    </div>
  );
});

export default SessionTreeView;
