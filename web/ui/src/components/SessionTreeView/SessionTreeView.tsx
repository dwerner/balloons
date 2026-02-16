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

// Turn node component
function TurnNode({ turn }: { turn: TurnInfo }) {
  const icon = turn.role === 'user' ? '👤' :
               turn.role === 'assistant' ? '🤖' : '⚙';
  const preview = (turn.content || '').slice(0, 60).replace(/\n/g, ' ');
  const tokenStr = formatKt(turn.tokens);

  return (
    <li className="tree-node tree-node--turn">
      <div className="tree-node__content">
        <span className="tree-node__spacer" />
        <span className="tree-node__icon">{icon}</span>
        <span className="tree-node__label tree-node__label--muted">
          {preview || '\u00A0'}
          {(turn.content || '').length > 60 ? '...' : ''}
        </span>
        {tokenStr && (
          <span className="tree-node__meta tree-node__meta--green">
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
}: {
  session: SessionInfo;
  index: number;
  isSelected: boolean;
  isExpanded: boolean;
  turns: TurnInfo[];
  onToggle: () => void;
  onSelect: () => void;
}) {
  const sessionColor = SESSION_COLORS[index % SESSION_COLORS.length] || '#60a5fa';
  const sessionName = session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
  const hasTurns = turns.length > 0;

  return (
    <li className="tree-node tree-node--session">
      <div
        className={`tree-node__content ${isSelected ? 'tree-node__content--selected' : ''}`}
        onClick={onSelect}
        style={{ borderLeftColor: sessionColor }}
      >
        <span
          className="tree-node__toggle"
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
        >
          {hasTurns ? <Arrow open={isExpanded} color={sessionColor} /> : <span className="tree-node__spacer" />}
        </span>

        {session.isStreaming && (
          <span className="tree-node__badge tree-node__badge--streaming">⟳</span>
        )}

        {session.parentId && (
          <span className="tree-node__badge tree-node__badge--fork">
            {session.forkStatus === 'merged' ? '✓' : '↳'}
          </span>
        )}

        <span className="tree-node__id">{session.id.slice(0, 8)}</span>
        <span className="tree-node__label">{sessionName}</span>
        <span className="tree-node__meta">({session.messageCount}msg)</span>
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
  isLoading?: boolean;
}

export const SessionTreeView = memo(function SessionTreeView({
  sessions,
  selectedSessionId,
  turns,
  onSelectSession,
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

  // Sort sessions: current first, then by last modified
  const sortedSessions = useMemo(() => {
    return [...sessions].sort((a, b) => {
      if (a.isCurrent) return -1;
      if (b.isCurrent) return 1;
      return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
    });
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

  return (
    <ul className="tree-view">
      {sortedSessions.map((session, index) => {
        const isSelected = session.id === selectedSessionId;
        const isExpanded = expandedSessions.has(session.id);
        // Only pass turns for the selected session
        const sessionTurns = isSelected ? turns : [];

        return (
          <SessionNode
            key={session.id}
            session={session}
            index={index}
            isSelected={isSelected}
            isExpanded={isExpanded}
            turns={sessionTurns}
            onToggle={() => toggleSession(session.id)}
            onSelect={() => onSelectSession(session.id)}
          />
        );
      })}
    </ul>
  );
});

export default SessionTreeView;
