/**
 * HierarchyView - Unified session hierarchy showing fork relationships
 *
 * Unlike SessionTreeView which shows multiple views of the same tree,
 * HierarchyView shows a single unified tree where:
 * - Only root sessions (no parent) appear at the top level
 * - Expanding a session shows its fork children
 * - Single source of truth for the entire fork hierarchy
 *
 * This avoids the sync issues where multiple views of the same tree
 * can get out of date when forks are created or merged.
 */

import React, { useState, useCallback, useMemo, memo, useEffect } from 'react';
import type { SessionInfo, ForkChild, SessionDataServiceClient } from '../../../../generated/balloons-client';
import { createLogger } from '../../utils/debugLog';
import './HierarchyView.css';

const debugLog = createLogger('HierarchyView');

// Helper to format token count compactly
function formatTokenCount(tokens: number): string {
  if (tokens >= 1000000) {
    return `${(tokens / 1000000).toFixed(1)}M`;
  } else if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(0)}k`;
  }
  return String(tokens);
}

// Helper to get CSS class based on token usage percentage
function getTokenCountClass(tokens: number, contextWindow?: number): string {
  if (!contextWindow || contextWindow === 0) return '';
  const pct = (tokens / contextWindow) * 100;
  if (pct >= 80) return 'hierarchy-node__tokens--high';
  if (pct >= 50) return 'hierarchy-node__tokens--medium';
  return 'hierarchy-node__tokens--low';
}

// Format a date as a day group label
function formatDayGroup(dateStr: string): string {
  if (!dateStr) return 'Unknown';
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return 'Unknown';
  const now = new Date();

  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);

  if (date >= startOfToday) {
    return 'Today';
  } else if (date >= startOfYesterday) {
    return 'Yesterday';
  } else {
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
}

// Arrow icon
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
      className={`hierarchy-arrow ${open ? 'hierarchy-arrow--open' : ''}`}
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

// Streaming spinner - smooth rotation without wobble
function StreamingSpinner() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      className="hierarchy-spinner"
    >
      {/* Background circle (faded) */}
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="2"
        opacity="0.25"
      />
      {/* Arc segment that rotates */}
      <path
        d="M12 3 A9 9 0 0 1 21 12"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
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

interface SessionNodeProps {
  session: SessionInfo;
  depth: number;
  isSelected: boolean;
  isExpanded: boolean;
  childSessions: SessionInfo[];  // Direct children from the sessions list
  onSelect: (sessionId: string) => void;
  onToggle: (sessionId: string) => void;
  allSessions: SessionInfo[];  // For recursive rendering
  expandedSessions: Set<string>;
  selectedSessionId: string | null;
  rootColorMap: Map<string, number>;  // Maps session ID to root's color index
}

const SessionNode = memo(function SessionNode({
  session,
  depth,
  isSelected,
  isExpanded,
  childSessions,
  onSelect,
  onToggle,
  allSessions,
  expandedSessions,
  selectedSessionId,
  rootColorMap,
}: SessionNodeProps) {
  // Use the root ancestor's color for consistent lineage coloring
  const colorIndex = rootColorMap.get(session.id) ?? 0;
  const sessionColor = SESSION_COLORS[colorIndex % SESSION_COLORS.length] || '#60a5fa';
  const sessionName = session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
  const hasChildren = childSessions.length > 0;

  const handleClick = useCallback(() => {
    onSelect(session.id);
  }, [onSelect, session.id]);

  const handleToggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle(session.id);
  }, [onToggle, session.id]);

  // Depth-based background tint (gets stronger as depth increases)
  const depthOpacity = Math.min(depth * 0.03, 0.15);

  return (
    <li className="hierarchy-node">
      <div
        className={`hierarchy-node__content ${isSelected ? 'hierarchy-node__content--selected' : ''} ${session.forkStatus === 'merged' ? 'hierarchy-node__content--merged' : ''}`}
        onClick={handleClick}
        style={{
          paddingLeft: `${depth * 16 + 8}px`,
          borderLeftColor: sessionColor,
          '--depth-tint': depthOpacity,
        } as React.CSSProperties}
      >
        {/* Expand/collapse toggle */}
        <span
          className="hierarchy-node__toggle"
          onClick={hasChildren ? handleToggle : undefined}
          style={{ visibility: hasChildren ? 'visible' : 'hidden' }}
        >
          <Arrow open={isExpanded} color={sessionColor} />
        </span>

        {/* Status indicators */}
        {session.isStreaming && (
          <span className="hierarchy-node__badge hierarchy-node__badge--streaming" title="Streaming">
            <StreamingSpinner />
          </span>
        )}

        {/* Merge status - prominent indicator */}
        {session.forkStatus === 'merged' && (
          <span className="hierarchy-node__badge hierarchy-node__badge--merged" title="Merged">✓</span>
        )}

        {/* Fork indicator (only show if not merged) */}
        {session.parentId && session.forkStatus !== 'merged' && (
          <span
            className="hierarchy-node__badge hierarchy-node__badge--fork"
            title={`Fork of ${session.parentId.slice(0, 8)}`}
          >
            ↳
          </span>
        )}

        {/* Children count badge */}
        {hasChildren && (
          <span
            className="hierarchy-node__badge hierarchy-node__badge--children"
            title={`${childSessions.length} fork(s)`}
          >
            ⑂{childSessions.length}
          </span>
        )}

        {/* Leaf indicator (no children) - debug */}
        {!hasChildren && (
          <span
            className="hierarchy-node__badge hierarchy-node__badge--leaf"
            title="Leaf (no children)"
          >
            🍃
          </span>
        )}

        {/* Session name */}
        <span className="hierarchy-node__label">{sessionName}</span>

        {/* Token count */}
        {session.cachedContextTokens !== undefined && session.cachedContextTokens > 0 && (
          <span
            className={`hierarchy-node__tokens ${getTokenCountClass(session.cachedContextTokens, session.contextWindow)}`}
            title={session.contextWindow
              ? `${session.cachedContextTokens.toLocaleString()} / ${session.contextWindow.toLocaleString()} tokens`
              : `${session.cachedContextTokens.toLocaleString()} tokens`
            }
          >
            {formatTokenCount(session.cachedContextTokens)}
          </span>
        )}

        {/* Message count */}
        <span className="hierarchy-node__meta">({session.messageCount})</span>

        {/* Timestamp */}
        <span className="hierarchy-node__time">{formatDayGroup(session.lastModified)}</span>
      </div>

      {/* Children (recursive) */}
      {isExpanded && hasChildren && (
        <ul className="hierarchy-children">
          {childSessions.map((child) => {
            const grandchildren = allSessions.filter(s => s.parentId === child.id);
            return (
              <SessionNode
                key={child.id}
                session={child}
                depth={depth + 1}
                isSelected={child.id === selectedSessionId}
                isExpanded={expandedSessions.has(child.id)}
                childSessions={grandchildren}
                onSelect={onSelect}
                onToggle={onToggle}
                allSessions={allSessions}
                expandedSessions={expandedSessions}
                selectedSessionId={selectedSessionId}
                rootColorMap={rootColorMap}
              />
            );
          })}
        </ul>
      )}
    </li>
  );
});

export type HierarchyMode = 'roots' | 'leaves';

export interface HierarchyViewProps {
  sessions: SessionInfo[];
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  isLoading?: boolean;
}

// Reversed node for leaves-first mode - shows parent as child
interface ReversedNodeProps {
  session: SessionInfo;
  depth: number;
  isSelected: boolean;
  isExpanded: boolean;
  parentSession: SessionInfo | null;
  siblingCount: number;  // Number of other children of this session's parent (siblings)
  onSelect: (sessionId: string) => void;
  onToggle: (sessionId: string) => void;
  allSessions: SessionInfo[];
  childrenByParent: Map<string, SessionInfo[]>;  // For computing sibling counts
  expandedSessions: Set<string>;
  selectedSessionId: string | null;
  rootColorMap: Map<string, number>;  // Maps session ID to root's color index
}

const ReversedNode = memo(function ReversedNode({
  session,
  depth,
  isSelected,
  isExpanded,
  parentSession,
  siblingCount,
  onSelect,
  onToggle,
  allSessions,
  childrenByParent,
  expandedSessions,
  selectedSessionId,
  rootColorMap,
}: ReversedNodeProps) {
  // Use the root ancestor's color for consistent lineage coloring
  const colorIndex = rootColorMap.get(session.id) ?? 0;
  const sessionColor = SESSION_COLORS[colorIndex % SESSION_COLORS.length] || '#60a5fa';
  const sessionName = session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
  const hasParent = parentSession !== null;

  const handleClick = useCallback(() => {
    onSelect(session.id);
  }, [onSelect, session.id]);

  const handleToggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle(session.id);
  }, [onToggle, session.id]);

  // Depth-based background tint (gets stronger as depth increases)
  const depthOpacity = Math.min(depth * 0.03, 0.15);

  return (
    <li className="hierarchy-node">
      <div
        className={`hierarchy-node__content ${isSelected ? 'hierarchy-node__content--selected' : ''} ${session.forkStatus === 'merged' ? 'hierarchy-node__content--merged' : ''}`}
        onClick={handleClick}
        style={{
          paddingLeft: `${depth * 16 + 8}px`,
          borderLeftColor: sessionColor,
          '--depth-tint': depthOpacity,
        } as React.CSSProperties}
      >
        {/* Expand/collapse toggle - shows parent when expanded */}
        <span
          className="hierarchy-node__toggle"
          onClick={hasParent ? handleToggle : undefined}
          style={{ visibility: hasParent ? 'visible' : 'hidden' }}
        >
          <Arrow open={isExpanded} color={sessionColor} />
        </span>

        {/* Status indicators */}
        {session.isStreaming && (
          <span className="hierarchy-node__badge hierarchy-node__badge--streaming">⟳</span>
        )}

        {/* Merge status - prominent indicator */}
        {session.forkStatus === 'merged' && (
          <span className="hierarchy-node__badge hierarchy-node__badge--merged" title="Merged">✓</span>
        )}

        {/* Has parent indicator (in leaves mode) */}
        {hasParent && (
          <span className="hierarchy-node__badge hierarchy-node__badge--parent" title={`Parent: ${parentSession.id.slice(0, 8)}`}>
            ↑
          </span>
        )}

        {/* Sibling indicator - shows when parent has other children we're not showing */}
        {siblingCount > 0 && (
          <span
            className="hierarchy-node__badge hierarchy-node__badge--siblings"
            title={`${siblingCount} sibling branch${siblingCount > 1 ? 'es' : ''} (switch to Roots mode to see all)`}
          >
            +{siblingCount}
          </span>
        )}

        {/* Leaf indicator - show if session has no children (debug) */}
        {/* In ReversedNode we need to check both childrenByParent and session.children */}
        {!childrenByParent.get(session.id)?.length && !session.children?.length && (
          <span
            className="hierarchy-node__badge hierarchy-node__badge--leaf"
            title="Leaf (no children)"
          >
            🍃
          </span>
        )}

        {/* Children indicator - ONLY at depth 0 (top-level in leaves mode) */}
        {/* If a session has children but appears as a leaf, that's a bug */}
        {depth === 0 && (childrenByParent.get(session.id)?.length || session.children?.length) ? (
          <span
            className="hierarchy-node__badge hierarchy-node__badge--has-children"
            title={`Has ${childrenByParent.get(session.id)?.length || session.children?.length || 0} children (shouldn't be a leaf!)`}
          >
            ⚠️{childrenByParent.get(session.id)?.length || session.children?.length}
          </span>
        ) : null}

        {/* Session name */}
        <span className="hierarchy-node__label">{sessionName}</span>

        {/* Token count */}
        {session.cachedContextTokens !== undefined && session.cachedContextTokens > 0 && (
          <span
            className={`hierarchy-node__tokens ${getTokenCountClass(session.cachedContextTokens, session.contextWindow)}`}
            title={session.contextWindow
              ? `${session.cachedContextTokens.toLocaleString()} / ${session.contextWindow.toLocaleString()} tokens`
              : `${session.cachedContextTokens.toLocaleString()} tokens`
            }
          >
            {formatTokenCount(session.cachedContextTokens)}
          </span>
        )}

        {/* Message count */}
        <span className="hierarchy-node__meta">({session.messageCount})</span>

        {/* Timestamp */}
        <span className="hierarchy-node__time">{formatDayGroup(session.lastModified)}</span>
      </div>

      {/* Parent (recursive upward) */}
      {isExpanded && parentSession && (() => {
        // Compute sibling count for the parent: how many children does the grandparent have besides parentSession?
        const grandparent = parentSession.parentId
          ? allSessions.find(s => s.id === parentSession.parentId)
          : null;
        const parentSiblingCount = grandparent
          ? (childrenByParent.get(grandparent.id)?.length ?? 1) - 1
          : 0;

        return (
          <ul className="hierarchy-children">
            <ReversedNode
              session={parentSession}
              depth={depth + 1}
              isSelected={parentSession.id === selectedSessionId}
              isExpanded={expandedSessions.has(parentSession.id)}
              parentSession={grandparent || null}
              siblingCount={parentSiblingCount}
              onSelect={onSelect}
              onToggle={onToggle}
              allSessions={allSessions}
              childrenByParent={childrenByParent}
              expandedSessions={expandedSessions}
              selectedSessionId={selectedSessionId}
              rootColorMap={rootColorMap}
            />
          </ul>
        );
      })()}
    </li>
  );
});

const HIERARCHY_MODE_KEY = 'balloons:hierarchy-mode';

export const HierarchyView = memo(function HierarchyView({
  sessions,
  selectedSessionId,
  onSelectSession,
  isLoading = false,
}: HierarchyViewProps) {
  // View mode: 'roots' = roots at top, 'leaves' = leaves at top (default)
  // Persisted in localStorage
  const [mode, setMode] = useState<HierarchyMode>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem(HIERARCHY_MODE_KEY);
      return (stored === 'roots' || stored === 'leaves') ? stored : 'leaves';
    }
    return 'leaves';
  });

  // Persist mode changes
  const handleModeChange = useCallback((newMode: HierarchyMode) => {
    setMode(newMode);
    localStorage.setItem(HIERARCHY_MODE_KEY, newMode);
  }, []);

  // Compute all sessions that have children (for auto-expand in roots mode)
  const sessionsWithChildren = useMemo(() => {
    const withChildren = new Set<string>();
    for (const session of sessions) {
      // Method 1: Session references a parent (so parent has children)
      if (session.parentId) {
        withChildren.add(session.parentId);
      }
      // Method 2: Session has children array populated (from server data)
      // This catches cases where child sessions are archived/deleted but parent still knows about them
      if (session.children && session.children.length > 0) {
        withChildren.add(session.id);
      }
    }
    return withChildren;
  }, [sessions]);

  // Build session lookup and root-finding function (shared by leafSessions and rootColorMap)
  const { sessionById, findRoot, rootIds } = useMemo(() => {
    const byId = new Map(sessions.map(s => [s.id, s]));

    // Memoized root finding with cache
    const rootCache = new Map<string, string>();
    const find = (sessionId: string): string => {
      if (rootCache.has(sessionId)) {
        return rootCache.get(sessionId)!;
      }
      const session = byId.get(sessionId);
      if (!session || !session.parentId) {
        rootCache.set(sessionId, sessionId);
        return sessionId; // This is a root
      }
      const rootId = find(session.parentId);
      rootCache.set(sessionId, rootId);
      return rootId;
    };

    // Pre-compute root for each session and collect unique roots
    const roots = new Set<string>();
    for (const session of sessions) {
      roots.add(find(session.id));
    }

    return { sessionById: byId, findRoot: find, rootIds: roots };
  }, [sessions]);

  // Compute leaf sessions (no children) for leaves mode
  // Sort by: 1) root ancestor (to group relatives), 2) last modified within group
  const leafSessions = useMemo(() => {
    const leaves = sessions
      .filter(s => !sessionsWithChildren.has(s.id));

    // Sort: group by root ancestor, then by lastModified within each group
    leaves.sort((a, b) => {
      const rootA = findRoot(a.id);
      const rootB = findRoot(b.id);

      // Different roots: sort by root's lastModified to keep related groups together
      if (rootA !== rootB) {
        const rootSessionA = sessionById.get(rootA);
        const rootSessionB = sessionById.get(rootB);
        const rootTimeA = rootSessionA ? new Date(rootSessionA.lastModified).getTime() : 0;
        const rootTimeB = rootSessionB ? new Date(rootSessionB.lastModified).getTime() : 0;
        return rootTimeB - rootTimeA; // Most recently modified root first
      }

      // Same root: sort by lastModified
      return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
    });

    // Debug: log sessions that have children array but weren't counted
    if (process.env.NODE_ENV === 'development') {
      const sessionsMissingFromLeaves = sessions.filter(s =>
        s.children && s.children.length > 0 && leaves.some(l => l.id === s.id)
      );
      if (sessionsMissingFromLeaves.length > 0) {
        debugLog('BUG: Sessions with children incorrectly in leaves:', {
          sessions: sessionsMissingFromLeaves.map(s => ({
            id: s.id.slice(0, 8),
            name: s.forkName || s.title,
            childrenCount: s.children?.length,
            children: s.children?.map(c => ({ id: c.sessionId.slice(0, 8), name: c.name }))
          }))
        });
      }
    }

    return leaves;
  }, [sessions, sessionsWithChildren, findRoot, sessionById]);

  // Sessions with parents (for auto-expand in leaves mode)
  const sessionsWithParents = useMemo(() => {
    const withParents = new Set<string>();
    for (const session of sessions) {
      if (session.parentId) {
        withParents.add(session.id);
      }
    }
    return withParents;
  }, [sessions]);

  // Start with appropriate sessions expanded based on mode
  const [expandedSessions, setExpandedSessions] = useState<Set<string>>(new Set());

  // Auto-expand based on mode and ensure selected session is visible
  useEffect(() => {
    setExpandedSessions(prev => {
      const next = new Set(prev);

      // Auto-expand all relevant sessions for the current mode
      if (mode === 'roots') {
        sessionsWithChildren.forEach(id => next.add(id));
      } else {
        sessionsWithParents.forEach(id => next.add(id));
      }

      // Ensure selected session's ancestors are expanded (for roots mode)
      // or the session itself is expanded (for leaves mode)
      if (selectedSessionId) {
        const selectedSession = sessions.find(s => s.id === selectedSessionId);
        if (selectedSession) {
          if (mode === 'roots') {
            // Expand all ancestors to make the selected session visible
            let current = selectedSession;
            while (current.parentId) {
              next.add(current.parentId);
              const parent = sessions.find(s => s.id === current.parentId);
              if (!parent) break;
              current = parent;
            }
          } else {
            // In leaves mode, expand the selected session to show its ancestry
            next.add(selectedSessionId);
          }
        }
      }

      return next;
    });
  }, [mode, sessionsWithChildren, sessionsWithParents, selectedSessionId, sessions]);

  // Log mount
  useEffect(() => {
    debugLog('HierarchyView mounted', { sessionCount: sessions.length, mode, withChildren: sessionsWithChildren.size });
  }, [sessions.length, mode, sessionsWithChildren.size]);

  // Scroll selected session into view when mode changes, selection changes, or sessions list changes
  // The sessions.length dependency ensures this runs when a new fork is added to the list
  useEffect(() => {
    if (!selectedSessionId) return;

    // Small delay to let the DOM update after expand state changes
    const timeoutId = setTimeout(() => {
      const selectedElement = document.querySelector(
        `.hierarchy-node__content--selected`
      );
      if (selectedElement) {
        selectedElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }, 100);

    return () => clearTimeout(timeoutId);
  }, [selectedSessionId, mode, sessions.length]);

  const toggleExpanded = useCallback((sessionId: string) => {
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

  // Get root sessions (no parent) sorted by last modified
  const rootSessions = useMemo(() => {
    return sessions
      .filter(s => !s.parentId)
      .sort((a, b) => new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime());
  }, [sessions]);

  // Build lookup for children
  const childrenByParent = useMemo(() => {
    const map = new Map<string, SessionInfo[]>();
    for (const session of sessions) {
      if (session.parentId) {
        const existing = map.get(session.parentId) || [];
        existing.push(session);
        map.set(session.parentId, existing);
      }
    }
    // Sort children by creation date
    for (const [, children] of map) {
      children.sort((a, b) => new Date(a.created).getTime() - new Date(b.created).getTime());
    }
    return map;
  }, [sessions]);

  // Build a map from session ID to its root ancestor's color index
  // This ensures all sessions in the same lineage share the same color
  const rootColorMap = useMemo(() => {
    const map = new Map<string, number>();

    // Assign color indices to roots based on their order in rootSessions
    const rootColorIndices = new Map<string, number>();
    rootSessions.forEach((root, idx) => {
      rootColorIndices.set(root.id, idx);
    });

    // Map each session to its root's color index
    for (const session of sessions) {
      const rootId = findRoot(session.id);
      const colorIndex = rootColorIndices.get(rootId) ?? 0;
      map.set(session.id, colorIndex);
    }

    return map;
  }, [sessions, rootSessions]);

  if (isLoading) {
    return (
      <div className="hierarchy-view hierarchy-view--empty">
        Loading sessions...
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="hierarchy-view hierarchy-view--empty">
        No sessions
      </div>
    );
  }

  return (
    <div className="hierarchy-view">
      <ul className="hierarchy-root">
        {/* Mode toggle - scrolls with content */}
        <li className="hierarchy-mode-toggle">
          <button
            className={`hierarchy-mode-btn ${mode === 'leaves' ? 'active' : ''}`}
            onClick={() => handleModeChange('leaves')}
            title="Show leaves at top, parents nested below"
          >
            ↑ Leaves
          </button>
          <button
            className={`hierarchy-mode-btn ${mode === 'roots' ? 'active' : ''}`}
            onClick={() => handleModeChange('roots')}
            title="Show roots at top, forks nested below"
          >
            ↓ Roots
          </button>
        </li>
        {mode === 'roots' ? (
          // Roots mode: show root sessions with children nested
          rootSessions.map((session) => {
            const children = childrenByParent.get(session.id) || [];
            return (
              <SessionNode
                key={session.id}
                session={session}
                depth={0}
                isSelected={session.id === selectedSessionId}
                isExpanded={expandedSessions.has(session.id)}
                childSessions={children}
                onSelect={onSelectSession}
                onToggle={toggleExpanded}
                allSessions={sessions}
                expandedSessions={expandedSessions}
                selectedSessionId={selectedSessionId}
                rootColorMap={rootColorMap}
              />
            );
          })
        ) : (
          // Leaves mode: show leaf sessions with parents nested
          leafSessions.map((session) => {
            const parentSession = session.parentId
              ? sessions.find(s => s.id === session.parentId) || null
              : null;
            // Compute sibling count: how many other children does the parent have?
            const siblingCount = parentSession
              ? (childrenByParent.get(parentSession.id)?.length ?? 1) - 1
              : 0;
            return (
              <ReversedNode
                key={session.id}
                session={session}
                depth={0}
                isSelected={session.id === selectedSessionId}
                isExpanded={expandedSessions.has(session.id)}
                parentSession={parentSession}
                siblingCount={siblingCount}
                onSelect={onSelectSession}
                onToggle={toggleExpanded}
                allSessions={sessions}
                childrenByParent={childrenByParent}
                expandedSessions={expandedSessions}
                selectedSessionId={selectedSessionId}
                rootColorMap={rootColorMap}
              />
            );
          })
        )}
      </ul>
    </div>
  );
});

export default HierarchyView;
