/**
 * SessionTreeView - Tree view showing sessions with exchanges and turns
 *
 * Following standard tree view patterns:
 * - Semantic <ul>/<li> structure
 * - Recursive node rendering
 * - CSS for visual hierarchy via padding
 * - Arrow icons for expand/collapse
 */

import React, { useState, useCallback, useMemo, memo, useEffect } from 'react';
import type { SessionInfo, TurnInfo } from '../../../../generated/balloons-client';
import './SessionTreeView.css';

// Context modes for turns
export type ContextMode = 'COPY' | 'COMPRESS' | 'DROP';

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

// Turn node component
function TurnNode({ turn }: { turn: TurnInfo }) {
  const icon = turn.role === 'user' ? '👤' :
               turn.role === 'assistant' ? '🤖' : '⚙';
  const preview = (turn.content || '').slice(0, 60).replace(/\n/g, ' ');
  const tokenStr = formatKt(turn.tokens);

  return (
    <li className="tree-node tree-node--turn">
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

// Session node component
function SessionNode({
  session,
  index,
  isSelected,
  isExpanded,
  turns,
  onToggle,
  onSelect,
  onTogglePin,
}: {
  session: SessionInfo;
  index: number;
  isSelected: boolean;
  isExpanded: boolean;
  turns: TurnInfo[];
  onToggle: () => void;
  onSelect: () => void;
  onTogglePin?: () => void;
}) {
  const sessionColor = SESSION_COLORS[index % SESSION_COLORS.length] || '#60a5fa';
  const sessionName = session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
  const hasTurns = turns.length > 0;
  const isPinned = session.isPinned ?? false;

  const handlePinClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onTogglePin?.();
  };

  return (
    <li className={`tree-node tree-node--session ${isPinned ? 'tree-node--pinned' : ''}`}>
      <div
        className={`tree-node__content ${isSelected ? 'tree-node__content--selected' : ''}`}
        onClick={onSelect}
        style={{ borderLeftColor: sessionColor }}
      >
        <span
          key="toggle"
          className="tree-node__toggle"
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
        >
          {hasTurns ? <Arrow open={isExpanded} color={sessionColor} /> : <span className="tree-node__spacer" />}
        </span>

        {/* Pin toggle on the left - always visible for pinned, hover for unpinned */}
        {onTogglePin && (
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

      {isExpanded && hasTurns && (
        <ul className="tree-children">
          {turns.map(turn => (
            <TurnNode key={turn.idx} turn={turn} />
          ))}
        </ul>
      )}
    </li>
  );
}

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
  isLoading?: boolean;
}

export const SessionTreeView = memo(function SessionTreeView({
  sessions,
  selectedSessionId,
  turns,
  onSelectSession,
  onTogglePin,
  isLoading = false,
}: SessionTreeViewProps) {
  const [expandedSessions, setExpandedSessions] = useState<Set<string>>(new Set());

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

  return (
    <ul className="tree-view">
      {/* Pinned sessions first */}
      {groupedSessions.pinned.length > 0 && (
        <li className="tree-group tree-group--pinned">
          <div className="tree-group__header">Pinned</div>
          <ul className="tree-group__sessions">
            {groupedSessions.pinned.map((session) => {
              const isSelected = session.id === selectedSessionId;
              const isExpanded = expandedSessions.has(session.id);
              const sessionTurns = isSelected ? turns : [];
              const idx = sessionIndex++;

              return (
                <SessionNode
                  key={session.id}
                  session={session}
                  index={idx}
                  isSelected={isSelected}
                  isExpanded={isExpanded}
                  turns={sessionTurns}
                  onToggle={() => toggleSession(session.id)}
                  onSelect={() => onSelectSession(session.id)}
                  onTogglePin={onTogglePin ? () => onTogglePin(session.id) : undefined}
                />
              );
            })}
          </ul>
        </li>
      )}

      {/* Day groups */}
      {groupedSessions.dayGroups.map((group) => (
        <li key={group.key} className="tree-group">
          <div className="tree-group__header">{group.label}</div>
          <ul className="tree-group__sessions">
            {group.sessions.map((session) => {
              const isSelected = session.id === selectedSessionId;
              const isExpanded = expandedSessions.has(session.id);
              const sessionTurns = isSelected ? turns : [];
              const idx = sessionIndex++;

              return (
                <SessionNode
                  key={session.id}
                  session={session}
                  index={idx}
                  isSelected={isSelected}
                  isExpanded={isExpanded}
                  turns={sessionTurns}
                  onToggle={() => toggleSession(session.id)}
                  onSelect={() => onSelectSession(session.id)}
                  onTogglePin={onTogglePin ? () => onTogglePin(session.id) : undefined}
                />
              );
            })}
          </ul>
        </li>
      ))}
    </ul>
  );
});

export default SessionTreeView;
