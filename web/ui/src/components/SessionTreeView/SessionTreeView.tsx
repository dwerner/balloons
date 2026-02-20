/**
 * SessionTreeView - Tree view showing sessions with exchanges and turns
 *
 * Following standard tree view patterns:
 * - Semantic <ul>/<li> structure
 * - Recursive node rendering
 * - CSS for visual hierarchy via padding
 * - Arrow icons for expand/collapse
 *
 * Features:
 * - Exchange grouping (user + assistant turns grouped together)
 * - Multi-selection with Shift+click (range) and Ctrl/Cmd+click (toggle)
 * - Lazy turn loading when expanding non-selected sessions
 * - Archive/delete bulk actions
 */

import React, { useState, useCallback, useMemo, memo, useEffect } from 'react';
import type { SessionInfo, TurnInfo } from '../../../../generated/balloons-client';
import './SessionTreeView.css';

// Context modes for turns
export type ContextMode = 'COPY' | 'COMPRESS' | 'DROP';

// Exchange represents a user prompt + assistant response pair
export interface Exchange {
  id: string;
  userTurn: TurnInfo | null;
  assistantTurns: TurnInfo[];  // Can have multiple (e.g., tool use, then text)
  systemTurns: TurnInfo[];     // System messages in this exchange
}

// Group turns into exchanges
function groupTurnsIntoExchanges(turns: TurnInfo[]): Exchange[] {
  const exchanges: Exchange[] = [];
  let currentExchange: Exchange | null = null;
  let exchangeIndex = 0;

  for (const turn of turns) {
    if (turn.role === 'user') {
      // Start a new exchange
      if (currentExchange) {
        exchanges.push(currentExchange);
      }
      currentExchange = {
        id: `exchange-${exchangeIndex++}`,
        userTurn: turn,
        assistantTurns: [],
        systemTurns: [],
      };
    } else if (turn.role === 'assistant') {
      if (!currentExchange) {
        // Assistant turn without user turn (shouldn't happen normally)
        currentExchange = {
          id: `exchange-${exchangeIndex++}`,
          userTurn: null,
          assistantTurns: [],
          systemTurns: [],
        };
      }
      currentExchange.assistantTurns.push(turn);
    } else {
      // System turn
      if (currentExchange) {
        currentExchange.systemTurns.push(turn);
      } else {
        // System turn at start - create exchange for it
        exchanges.push({
          id: `exchange-${exchangeIndex++}`,
          userTurn: null,
          assistantTurns: [],
          systemTurns: [turn],
        });
      }
    }
  }

  // Don't forget the last exchange
  if (currentExchange) {
    exchanges.push(currentExchange);
  }

  return exchanges;
}

// Session colors for visual distinction
const SESSION_COLORS = [
  '#60a5fa', // blue
  '#c084fc', // purple
  '#22d3ee', // cyan
  '#4ade80', // green
  '#facc15', // yellow
  '#f87171', // red
];

// Format token count as kt
function formatKt(tokens: number): string {
  if (tokens <= 0) return '';
  const kt = Math.ceil(tokens / 100) / 10;
  if (kt < 1) return `.${Math.floor(kt * 10)}kt`;
  return `${kt.toFixed(1)}kt`;
}

// Format a date as a day group label
function formatDayGroup(dateStr: string): string {
  if (!dateStr) return 'Unknown';
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return 'Unknown';
  const now = new Date();

  // Get start of today, yesterday, etc.
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);
  const startOfThisWeek = new Date(startOfToday);
  startOfThisWeek.setDate(startOfThisWeek.getDate() - now.getDay());
  const startOfLastWeek = new Date(startOfThisWeek);
  startOfLastWeek.setDate(startOfLastWeek.getDate() - 7);

  if (date >= startOfToday) {
    return 'Today';
  } else if (date >= startOfYesterday) {
    return 'Yesterday';
  } else if (date >= startOfThisWeek) {
    // This week - show day name
    return date.toLocaleDateString(undefined, { weekday: 'long' });
  } else if (date >= startOfLastWeek) {
    return 'Last Week';
  } else {
    // Older - show month and year, or just month if same year
    const sameYear = date.getFullYear() === now.getFullYear();
    if (sameYear) {
      return date.toLocaleDateString(undefined, { month: 'long' });
    } else {
      return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
    }
  }
}

// Get a sortable day key for grouping
function getDayKey(dateStr: string): string {
  if (!dateStr) return '1970-01-01';
  const date = new Date(dateStr);
  // Check for invalid date
  if (isNaN(date.getTime())) return '1970-01-01';
  // Return YYYY-MM-DD format for consistent grouping
  return date.toISOString().split('T')[0] || '1970-01-01';
}

// Arrow icon component
function Arrow({ open, color }: { open: boolean; color?: string }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke={color || 'currentColor'}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`tree-arrow ${open ? 'tree-arrow--open' : ''}`}
    >
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

// Pin icon component
function PinIcon({ isPinned, onClick }: { isPinned: boolean; onClick: (e: React.MouseEvent) => void }) {
  return (
    <span
      className={`tree-pin ${isPinned ? 'tree-pin--active' : ''}`}
      onClick={onClick}
      title={isPinned ? 'Unpin session' : 'Pin session'}
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill={isPinned ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M12 17v5" />
        <path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1z" />
      </svg>
    </span>
  );
}

// Checkbox icon for multi-selection
function CheckboxIcon({ checked, onClick }: { checked: boolean; onClick: (e: React.MouseEvent) => void }) {
  return (
    <span
      className={`tree-checkbox ${checked ? 'tree-checkbox--checked' : ''}`}
      onClick={onClick}
      title={checked ? 'Deselect' : 'Select'}
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill={checked ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect x="3" y="3" width="18" height="18" rx="2" />
        {checked && <path d="M9 12l2 2 4-4" />}
      </svg>
    </span>
  );
}

// Archive icon
function ArchiveIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="2" y="4" width="20" height="5" rx="1" />
      <path d="M4 9v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9" />
      <path d="M10 13h4" />
    </svg>
  );
}

// Trash icon
function TrashIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 6h18" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

// Turn node component (used inside exchanges)
function TurnNode({ turn, indent = false }: { turn: TurnInfo; indent?: boolean }) {
  const icon = turn.role === 'user' ? '👤' :
               turn.role === 'assistant' ? '🤖' : '⚙';
  const preview = (turn.content || '').slice(0, 60).replace(/\n/g, ' ');
  const tokenStr = formatKt(turn.tokens);

  return (
    <li className={`tree-node tree-node--turn ${indent ? 'tree-node--indented' : ''}`}>
      <div className="tree-node__content">
        <span key="spacer" className="tree-node__spacer" />
        <span key="icon" className="tree-node__icon">{icon}</span>
        <span key="label" className="tree-node__label tree-node__label--muted">
          {preview || '\u00A0'}
          {(turn.content || '').length > 60 ? '...' : ''}
        </span>
        {tokenStr && (
          <span key="meta" className="tree-node__meta tree-node__meta--green">
            {tokenStr}
          </span>
        )}
      </div>
    </li>
  );
}

// Exchange node component - groups user + assistant turns
function ExchangeNode({
  exchange,
  isExpanded,
  onToggle,
}: {
  exchange: Exchange;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const userPreview = exchange.userTurn
    ? (exchange.userTurn.content || '').slice(0, 50).replace(/\n/g, ' ')
    : null;

  const totalTokens = (exchange.userTurn?.tokens || 0) +
    exchange.assistantTurns.reduce((sum, t) => sum + (t.tokens || 0), 0) +
    exchange.systemTurns.reduce((sum, t) => sum + (t.tokens || 0), 0);

  const tokenStr = formatKt(totalTokens);
  const turnCount = (exchange.userTurn ? 1 : 0) + exchange.assistantTurns.length + exchange.systemTurns.length;
  const hasChildren = turnCount > 1;

  return (
    <li className="tree-node tree-node--exchange">
      <div className="tree-node__content" onClick={onToggle}>
        <span className="tree-node__toggle">
          {hasChildren ? <Arrow open={isExpanded} /> : <span className="tree-node__spacer" />}
        </span>
        <span className="tree-node__icon">💬</span>
        <span className="tree-node__label tree-node__label--muted">
          {userPreview || 'System'}
          {userPreview && userPreview.length >= 50 ? '...' : ''}
        </span>
        <span className="tree-node__meta">
          {turnCount > 1 && `${turnCount} turns`}
        </span>
        {tokenStr && (
          <span className="tree-node__meta tree-node__meta--green">
            {tokenStr}
          </span>
        )}
      </div>

      {isExpanded && hasChildren && (
        <ul className="tree-children">
          {exchange.systemTurns.map(turn => (
            <TurnNode key={turn.idx} turn={turn} indent />
          ))}
          {exchange.userTurn && (
            <TurnNode key={exchange.userTurn.idx} turn={exchange.userTurn} indent />
          )}
          {exchange.assistantTurns.map(turn => (
            <TurnNode key={turn.idx} turn={turn} indent />
          ))}
        </ul>
      )}
    </li>
  );
}

// Session node component
function SessionNode({
  session,
  index,
  isSelected,
  isChecked,
  isExpanded,
  turns,
  isLoadingTurns,
  showCheckboxes,
  onToggle,
  onSelect,
  onTogglePin,
  onToggleCheck,
}: {
  session: SessionInfo;
  index: number;
  isSelected: boolean;
  isChecked: boolean;
  isExpanded: boolean;
  turns: TurnInfo[];
  isLoadingTurns: boolean;
  showCheckboxes: boolean;
  onToggle: () => void;
  onSelect: (e: React.MouseEvent) => void;
  onTogglePin?: () => void;
  onToggleCheck?: (e: React.MouseEvent) => void;
}) {
  const sessionColor = SESSION_COLORS[index % SESSION_COLORS.length] || '#60a5fa';
  const sessionName = session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
  const isPinned = session.isPinned ?? false;

  // Use message count as indicator when not expanded
  const hasContent = session.messageCount > 0;

  // Group turns into exchanges for display
  const exchanges = useMemo(() => groupTurnsIntoExchanges(turns), [turns]);

  // Track which exchanges are expanded
  const [expandedExchanges, setExpandedExchanges] = useState<Set<string>>(new Set());

  const toggleExchange = useCallback((exchangeId: string) => {
    setExpandedExchanges(prev => {
      const next = new Set(prev);
      if (next.has(exchangeId)) {
        next.delete(exchangeId);
      } else {
        next.add(exchangeId);
      }
      return next;
    });
  }, []);

  const handlePinClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onTogglePin?.();
  };

  return (
    <li className={`tree-node tree-node--session ${isPinned ? 'tree-node--pinned' : ''} ${isChecked ? 'tree-node--checked' : ''}`}>
      <div
        className={`tree-node__content ${isSelected ? 'tree-node__content--selected' : ''}`}
        onClick={onSelect}
        style={{ borderLeftColor: sessionColor }}
      >
        {/* Checkbox for multi-selection */}
        {showCheckboxes && onToggleCheck && (
          <span className="tree-node__checkbox">
            <CheckboxIcon checked={isChecked} onClick={onToggleCheck} />
          </span>
        )}

        <span
          key="toggle"
          className="tree-node__toggle"
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
        >
          {hasContent ? <Arrow open={isExpanded} color={sessionColor} /> : <span className="tree-node__spacer" />}
        </span>

        {/* Pin toggle on the left - always visible for pinned, hover for unpinned */}
        {onTogglePin && !showCheckboxes && (
          <span key="pin-toggle" className={`tree-node__pin-toggle tree-node__pin-toggle--left ${isPinned ? 'tree-node__pin-toggle--pinned' : ''}`}>
            <PinIcon isPinned={isPinned} onClick={handlePinClick} />
          </span>
        )}

        {session.isStreaming && (
          <span key="streaming-badge" className="tree-node__badge tree-node__badge--streaming">⟳</span>
        )}

        {session.parentId && (
          <span key="fork-badge" className="tree-node__badge tree-node__badge--fork">
            {session.forkStatus === 'merged' ? '✓' : '↳'}
          </span>
        )}

        <span key="id" className="tree-node__id">{session.id.slice(0, 8)}</span>
        <span key="label" className="tree-node__label">{sessionName}</span>
        <span key="meta" className="tree-node__meta">({session.messageCount}msg)</span>
      </div>

      {isExpanded && (
        <ul className="tree-children">
          {isLoadingTurns ? (
            <li className="tree-node tree-node--loading">
              <div className="tree-node__content">
                <span className="tree-node__spacer" />
                <span className="tree-node__label tree-node__label--muted">Loading...</span>
              </div>
            </li>
          ) : exchanges.length > 0 ? (
            exchanges.map(exchange => (
              <ExchangeNode
                key={exchange.id}
                exchange={exchange}
                isExpanded={expandedExchanges.has(exchange.id)}
                onToggle={() => toggleExchange(exchange.id)}
              />
            ))
          ) : (
            <li className="tree-node tree-node--empty">
              <div className="tree-node__content">
                <span className="tree-node__spacer" />
                <span className="tree-node__label tree-node__label--muted">No messages</span>
              </div>
            </li>
          )}
        </ul>
      )}
    </li>
  );
}

// Bulk action type
export type BulkAction = 'archive' | 'delete' | 'unarchive';

// Props for main component
interface SessionTreeViewProps {
  sessions: SessionInfo[];
  selectedSessionId: string | null;
  turns: TurnInfo[];
  onSelectSession: (sessionId: string) => void;
  onSelectTurn?: (turnIdx: number) => void;
  onContextModeChange?: (sessionId: string, turnIdx: number, mode: ContextMode) => void;
  onLinkSession?: (sessionId: string) => void;
  onTogglePin?: (sessionId: string) => void;
  onBulkAction?: (sessionIds: string[], action: BulkAction) => void;
  onLoadTurns?: (sessionId: string) => Promise<TurnInfo[]>;
  isLoading?: boolean;
}

export const SessionTreeView = memo(function SessionTreeView({
  sessions,
  selectedSessionId,
  turns,
  onSelectSession,
  onTogglePin,
  onBulkAction,
  onLoadTurns,
  isLoading = false,
}: SessionTreeViewProps) {
  const [expandedSessions, setExpandedSessions] = useState<Set<string>>(new Set());
  const [checkedSessions, setCheckedSessions] = useState<Set<string>>(new Set());
  const [lastClickedSessionId, setLastClickedSessionId] = useState<string | null>(null);
  const [loadingTurns, setLoadingTurns] = useState<Set<string>>(new Set());
  const [sessionTurnsCache, setSessionTurnsCache] = useState<Map<string, TurnInfo[]>>(new Map());

  // Show checkboxes when any session is checked
  const showCheckboxes = checkedSessions.size > 0;

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

  // Load turns for a session when expanding (if not selected)
  const loadTurnsForSession = useCallback(async (sessionId: string) => {
    if (!onLoadTurns || sessionTurnsCache.has(sessionId) || loadingTurns.has(sessionId)) {
      return;
    }

    setLoadingTurns(prev => new Set(prev).add(sessionId));
    try {
      const sessionTurns = await onLoadTurns(sessionId);
      setSessionTurnsCache(prev => new Map(prev).set(sessionId, sessionTurns));
    } catch (error) {
      console.error('Failed to load turns for session:', sessionId, error);
    } finally {
      setLoadingTurns(prev => {
        const next = new Set(prev);
        next.delete(sessionId);
        return next;
      });
    }
  }, [onLoadTurns, sessionTurnsCache, loadingTurns]);

  const toggleSession = useCallback((sessionId: string) => {
    setExpandedSessions(prev => {
      const next = new Set(prev);
      const isExpanding = !next.has(sessionId);
      if (isExpanding) {
        next.add(sessionId);
        // Load turns if not selected session and not already loaded
        if (sessionId !== selectedSessionId) {
          loadTurnsForSession(sessionId);
        }
      } else {
        next.delete(sessionId);
      }
      return next;
    });
  }, [selectedSessionId, loadTurnsForSession]);

  // Get all session IDs in display order for range selection
  const sessionIdOrder = useMemo(() => {
    const order: string[] = [];
    const pinned = sessions.filter(s => s.isPinned);
    const unpinned = sessions.filter(s => !s.isPinned);
    pinned.forEach(s => order.push(s.id));
    unpinned.forEach(s => order.push(s.id));
    return order;
  }, [sessions]);

  // Handle session click with multi-selection support
  const handleSessionClick = useCallback((sessionId: string, e: React.MouseEvent) => {
    const isMetaKey = e.metaKey || e.ctrlKey;
    const isShiftKey = e.shiftKey;

    if (isShiftKey && lastClickedSessionId) {
      // Range selection
      const startIdx = sessionIdOrder.indexOf(lastClickedSessionId);
      const endIdx = sessionIdOrder.indexOf(sessionId);
      if (startIdx !== -1 && endIdx !== -1) {
        const [from, to] = startIdx < endIdx ? [startIdx, endIdx] : [endIdx, startIdx];
        const range = sessionIdOrder.slice(from, to + 1);
        setCheckedSessions(prev => {
          const next = new Set(prev);
          range.forEach(id => next.add(id));
          return next;
        });
      }
    } else if (isMetaKey) {
      // Toggle selection
      setCheckedSessions(prev => {
        const next = new Set(prev);
        if (next.has(sessionId)) {
          next.delete(sessionId);
        } else {
          next.add(sessionId);
        }
        return next;
      });
      setLastClickedSessionId(sessionId);
    } else {
      // Normal click - select session, clear multi-selection
      if (checkedSessions.size > 0) {
        setCheckedSessions(new Set());
      }
      setLastClickedSessionId(sessionId);
      onSelectSession(sessionId);
    }
  }, [lastClickedSessionId, sessionIdOrder, checkedSessions.size, onSelectSession]);

  // Handle checkbox click (doesn't select session)
  const handleCheckboxClick = useCallback((sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setCheckedSessions(prev => {
      const next = new Set(prev);
      if (next.has(sessionId)) {
        next.delete(sessionId);
      } else {
        next.add(sessionId);
      }
      return next;
    });
    setLastClickedSessionId(sessionId);
  }, []);

  // Handle bulk action
  const handleBulkAction = useCallback((action: BulkAction) => {
    if (onBulkAction && checkedSessions.size > 0) {
      onBulkAction(Array.from(checkedSessions), action);
      setCheckedSessions(new Set());
    }
  }, [onBulkAction, checkedSessions]);

  // Clear selection
  const clearSelection = useCallback(() => {
    setCheckedSessions(new Set());
  }, []);

  // Group sessions by day with pinned sessions first
  const groupedSessions = useMemo(() => {
    // Separate pinned and unpinned sessions
    const pinned = sessions.filter(s => s.isPinned);
    const unpinned = sessions.filter(s => !s.isPinned);

    // Sort pinned by last modified (current first)
    pinned.sort((a, b) => {
      if (a.isCurrent) return -1;
      if (b.isCurrent) return 1;
      return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
    });

    // Sort unpinned by last modified
    unpinned.sort((a, b) => {
      if (a.isCurrent) return -1;
      if (b.isCurrent) return 1;
      return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
    });

    // Group unpinned by day
    const dayGroups: { key: string; label: string; sessions: SessionInfo[] }[] = [];
    let currentDayKey = '';
    let currentGroup: SessionInfo[] = [];

    for (const session of unpinned) {
      const dayKey = getDayKey(session.lastModified);
      if (dayKey !== currentDayKey) {
        if (currentGroup.length > 0) {
          dayGroups.push({
            key: currentDayKey,
            label: formatDayGroup(currentGroup[0]?.lastModified || ''),
            sessions: currentGroup,
          });
        }
        currentDayKey = dayKey;
        currentGroup = [session];
      } else {
        currentGroup.push(session);
      }
    }

    // Don't forget the last group
    if (currentGroup.length > 0) {
      dayGroups.push({
        key: currentDayKey,
        label: formatDayGroup(currentGroup[0]?.lastModified || ''),
        sessions: currentGroup,
      });
    }

    return { pinned, dayGroups };
  }, [sessions]);

  if (isLoading) {
    return (
      <div className="tree-view tree-view--empty">
        Loading sessions...
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="tree-view tree-view--empty">
        No sessions
      </div>
    );
  }

  // Track index for consistent coloring across groups
  let sessionIndex = 0;

  // Helper to get turns for a session (selected uses props, others use cache)
  const getTurnsForSession = (sessionId: string): TurnInfo[] => {
    if (sessionId === selectedSessionId) {
      return turns;
    }
    return sessionTurnsCache.get(sessionId) || [];
  };

  // Helper to render a session node with all the new props
  const renderSessionNode = (session: SessionInfo) => {
    const isSelected = session.id === selectedSessionId;
    const isChecked = checkedSessions.has(session.id);
    const isExpanded = expandedSessions.has(session.id);
    const sessionTurns = getTurnsForSession(session.id);
    const isLoadingSessionTurns = loadingTurns.has(session.id);
    const idx = sessionIndex++;

    return (
      <SessionNode
        key={session.id}
        session={session}
        index={idx}
        isSelected={isSelected}
        isChecked={isChecked}
        isExpanded={isExpanded}
        turns={sessionTurns}
        isLoadingTurns={isLoadingSessionTurns}
        showCheckboxes={showCheckboxes}
        onToggle={() => toggleSession(session.id)}
        onSelect={(e) => handleSessionClick(session.id, e)}
        onTogglePin={onTogglePin ? () => onTogglePin(session.id) : undefined}
        onToggleCheck={(e) => handleCheckboxClick(session.id, e)}
      />
    );
  };

  return (
    <div className="tree-view-container">
      {/* Bulk action toolbar */}
      {showCheckboxes && (
        <div className="tree-toolbar">
          <span className="tree-toolbar__count">
            {checkedSessions.size} selected
          </span>
          {onBulkAction && (
            <>
              <button
                className="tree-toolbar__action"
                onClick={() => handleBulkAction('archive')}
                title="Archive selected sessions"
              >
                <ArchiveIcon />
                Archive
              </button>
              <button
                className="tree-toolbar__action tree-toolbar__action--danger"
                onClick={() => handleBulkAction('delete')}
                title="Delete selected sessions"
              >
                <TrashIcon />
                Delete
              </button>
            </>
          )}
          <button
            className="tree-toolbar__action tree-toolbar__action--text"
            onClick={clearSelection}
          >
            Cancel
          </button>
        </div>
      )}

      <ul className="tree-view">
        {/* Pinned sessions first */}
        {groupedSessions.pinned.length > 0 && (
          <li className="tree-group tree-group--pinned">
            <div className="tree-group__header">Pinned</div>
            <ul className="tree-group__sessions">
              {groupedSessions.pinned.map(renderSessionNode)}
            </ul>
          </li>
        )}

        {/* Day groups */}
        {groupedSessions.dayGroups.map((group, groupIndex) => (
          <li key={`${group.key}-${groupIndex}`} className="tree-group">
            <div className="tree-group__header">{group.label}</div>
            <ul className="tree-group__sessions">
              {group.sessions.map(renderSessionNode)}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
});

export default SessionTreeView;
