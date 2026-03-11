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


// Tree branch connector - shows vertical line with optional horizontal branch
interface TreeConnectorProps {
  depth: number;
  isLast: boolean;  // Is this the last child at this level?
  isLeaf: boolean;  // Is this a leaf node (no children)?
  hasParent: boolean;  // Does this node have a parent?
  continuations: boolean[];  // For each ancestor level, should we show a continuation line?
  color?: string;
}

function TreeConnector({ depth, isLast, isLeaf, hasParent, continuations, color }: TreeConnectorProps) {
  if (depth === 0 || !hasParent) return null;

  const strokeColor = color || '#555';
  // Use viewBox coordinates - SVG will stretch to fill container via CSS
  const vbHeight = 100;

  return (
    <span className="hierarchy-tree-connector" style={{ width: `${depth * 16}px` }}>
      {/* Render continuation lines for ancestors */}
      {continuations.slice(0, depth - 1).map((showLine, idx) => (
        <svg
          key={idx}
          viewBox={`0 0 16 ${vbHeight}`}
          preserveAspectRatio="none"
          className="hierarchy-tree-line"
          style={{ left: `${idx * 16}px`, width: '16px' }}
        >
          {showLine && (
            <line
              x1="8"
              y1="0"
              x2="8"
              y2={vbHeight}
              stroke={strokeColor}
              strokeWidth="1.5"
              strokeOpacity="0.8"
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>
      ))}
      {/* Branch connector for this node */}
      <svg
        viewBox={`0 0 16 ${vbHeight}`}
        preserveAspectRatio="none"
        className="hierarchy-tree-branch"
        style={{ left: `${(depth - 1) * 16}px`, width: '16px' }}
      >
        {/* Vertical line - full height if not last, to middle if last */}
        <line
          x1="8"
          y1="0"
          x2="8"
          y2={isLast ? vbHeight / 2 : vbHeight}
          stroke={strokeColor}
          strokeWidth="1.5"
          strokeOpacity="0.8"
          vectorEffect="non-scaling-stroke"
        />
        {/* Horizontal branch to the node */}
        <line
          x1="8"
          y1={vbHeight / 2}
          x2={isLeaf ? 13 : 16}
          y2={vbHeight / 2}
          stroke={strokeColor}
          strokeWidth="1.5"
          strokeOpacity="0.8"
          vectorEffect="non-scaling-stroke"
        />
        {/* Leaf indicator - small circle at the end */}
        {isLeaf && (
          <circle
            cx="14"
            cy={vbHeight / 2}
            r="2.5"
            fill={strokeColor}
            fillOpacity="0.8"
          />
        )}
      </svg>
    </span>
  );
}

// Streaming spinner - smooth rotation without wobble
function StreamingSpinner() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      className="hierarchy-spinner"
      style={{ display: 'inline-block' }}
    >
      {/* Background track */}
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
        opacity="0.2"
      />
      {/* Spinning arc - uses strokeDasharray to create partial circle */}
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        strokeDasharray="47 63"
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

// Depth tint colors - cycle through these when depth > 10
const DEPTH_TINT_COLORS = [
  '139, 92, 246',   // purple
  '34, 211, 238',   // cyan
  '251, 146, 60',   // orange
];

// Calculate depth-based tint: lerp from 0 to max intensity over 10 levels, then cycle colors
function getDepthTint(depth: number): { color: string; opacity: number } {
  const defaultColor = DEPTH_TINT_COLORS[0]!;
  if (depth === 0) return { color: defaultColor, opacity: 0 };

  const cycleIndex = Math.floor((depth - 1) / 10);
  const depthInCycle = ((depth - 1) % 10) + 1;
  const color = DEPTH_TINT_COLORS[cycleIndex % DEPTH_TINT_COLORS.length] ?? defaultColor;
  const opacity = depthInCycle * 0.03; // 0.03 per level, max 0.3 at depth 10

  return { color, opacity };
}

interface SessionNodeProps {
  session: SessionInfo;
  depth: number;  // Visual indentation depth
  treeDepth: number;  // Actual depth from root (for tint calculation)
  isSelected: boolean;
  isExpanded: boolean;
  isLast: boolean;  // Is this the last sibling?
  continuations: boolean[];  // Which ancestor levels should show continuation lines?
  childSessions: SessionInfo[];  // Direct children from the sessions list
  onSelect: (sessionId: string) => void;
  onToggle: (sessionId: string) => void;
  allSessions: SessionInfo[];  // For recursive rendering
  expandedSessions: Set<string>;
  selectedSessionId: string | null;
  rootColorMap: Map<string, number>;  // Maps session ID to root's color index
  unreadSessionIds: Set<string>;  // Sessions that finished streaming but haven't been viewed
}

const SessionNode = memo(function SessionNode({
  session,
  depth,
  treeDepth,
  isSelected,
  isExpanded,
  isLast,
  continuations,
  childSessions,
  onSelect,
  onToggle,
  allSessions,
  expandedSessions,
  selectedSessionId,
  rootColorMap,
  unreadSessionIds,
}: SessionNodeProps) {
  // Use the root ancestor's color for consistent lineage coloring
  const colorIndex = rootColorMap.get(session.id) ?? 0;
  const sessionColor = SESSION_COLORS[colorIndex % SESSION_COLORS.length] || '#60a5fa';
  const sessionName = session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
  const hasChildren = childSessions.length > 0;
  const isUnread = unreadSessionIds.has(session.id);

  const handleClick = useCallback(() => {
    onSelect(session.id);
  }, [onSelect, session.id]);

  const handleToggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle(session.id);
  }, [onToggle, session.id]);

  // Depth-based background tint: lerp from 0 at root to max at depth 10, then cycle colors
  const depthTint = getDepthTint(treeDepth);

  // Padding for tree connector
  const connectorPadding = depth > 0 && session.parentId ? depth * 16 : 0;

  return (
    <li className="hierarchy-node">
      <div
        className={`hierarchy-node__content ${isSelected ? 'hierarchy-node__content--selected' : ''} ${session.forkStatus === 'merged' ? 'hierarchy-node__content--merged' : ''} ${isUnread ? 'hierarchy-node__content--unread' : ''}`}
        onClick={handleClick}
        style={{
          paddingLeft: `${8 + connectorPadding}px`,
          borderLeftColor: sessionColor,
          '--depth-tint-color': depthTint.color,
          '--depth-tint-opacity': depthTint.opacity,
        } as React.CSSProperties}
      >
        {/* Tree connector graphics */}
        <TreeConnector
          depth={depth}
          isLast={isLast}
          isLeaf={!hasChildren}
          hasParent={!!session.parentId}
          continuations={continuations}
          color={sessionColor}
        />

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

        {/* Children count badge - click to expand/collapse */}
        {hasChildren && (
          <span
            className={`hierarchy-node__badge hierarchy-node__badge--children ${isExpanded ? 'hierarchy-node__badge--expanded' : ''}`}
            title={`${childSessions.length} fork(s) - click to ${isExpanded ? 'collapse' : 'expand'}`}
            onClick={handleToggle}
          >
            ⑂{childSessions.length}
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
          {childSessions.map((child, idx) => {
            const grandchildren = allSessions.filter(s => s.parentId === child.id);
            const childIsLast = idx === childSessions.length - 1;
            // Build continuations for the child: current continuations + whether this child has siblings below
            const childContinuations = [...continuations, !childIsLast];
            return (
              <SessionNode
                key={child.id}
                session={child}
                depth={depth + 1}
                treeDepth={treeDepth + 1}
                isSelected={child.id === selectedSessionId}
                isExpanded={expandedSessions.has(child.id)}
                isLast={childIsLast}
                continuations={childContinuations}
                childSessions={grandchildren}
                onSelect={onSelect}
                onToggle={onToggle}
                allSessions={allSessions}
                expandedSessions={expandedSessions}
                selectedSessionId={selectedSessionId}
                rootColorMap={rootColorMap}
                unreadSessionIds={unreadSessionIds}
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
  /** Set of session IDs that have finished streaming but haven't been viewed */
  unreadSessionIds?: Set<string>;
}

// Reversed node for leaves-first mode - shows parent as child
interface ReversedNodeProps {
  session: SessionInfo;
  depth: number;
  treeDepth: number;  // Actual depth from root (for tint calculation)
  isSelected: boolean;
  isExpanded: boolean;
  isLast: boolean;  // Is this the last sibling?
  continuations: boolean[];  // Which ancestor levels should show continuation lines?
  parentSession: SessionInfo | null;
  onSelect: (sessionId: string) => void;
  onToggle: (sessionId: string) => void;
  allSessions: SessionInfo[];
  childrenByParent: Map<string, SessionInfo[]>;  // For computing sibling counts
  expandedSessions: Set<string>;
  selectedSessionId: string | null;
  rootColorMap: Map<string, number>;  // Maps session ID to root's color index
  unreadSessionIds: Set<string>;  // Sessions that finished streaming but haven't been viewed
}

const ReversedNode = memo(function ReversedNode({
  session,
  depth,
  treeDepth,
  isSelected,
  isExpanded,
  isLast,
  continuations,
  parentSession,
  onSelect,
  onToggle,
  allSessions,
  childrenByParent,
  expandedSessions,
  selectedSessionId,
  rootColorMap,
  unreadSessionIds,
}: ReversedNodeProps) {
  // Use the root ancestor's color for consistent lineage coloring
  const colorIndex = rootColorMap.get(session.id) ?? 0;
  const sessionColor = SESSION_COLORS[colorIndex % SESSION_COLORS.length] || '#60a5fa';
  const sessionName = session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
  const hasParent = parentSession !== null;
  const isUnread = unreadSessionIds.has(session.id);

  const handleClick = useCallback(() => {
    onSelect(session.id);
  }, [onSelect, session.id]);

  const handleToggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle(session.id);
  }, [onToggle, session.id]);

  // Depth-based background tint: lerp from 0 at root to max at depth 10, then cycle colors
  const depthTint = getDepthTint(treeDepth);

  // Padding for tree connector
  const connectorPadding = depth > 0 ? depth * 16 : 0;

  return (
    <li className="hierarchy-node">
      <div
        className={`hierarchy-node__content ${isSelected ? 'hierarchy-node__content--selected' : ''} ${session.forkStatus === 'merged' ? 'hierarchy-node__content--merged' : ''} ${isUnread ? 'hierarchy-node__content--unread' : ''}`}
        onClick={handleClick}
        style={{
          paddingLeft: `${8 + connectorPadding}px`,
          borderLeftColor: sessionColor,
          '--depth-tint-color': depthTint.color,
          '--depth-tint-opacity': depthTint.opacity,
        } as React.CSSProperties}
      >
        {/* Tree connector graphics */}
        <TreeConnector
          depth={depth}
          isLast={isLast}
          isLeaf={!(childrenByParent.get(session.id)?.length || session.children?.length)}
          hasParent={depth > 0}
          continuations={continuations}
          color={sessionColor}
        />

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

        {/* Has parent indicator (in leaves mode) - click to expand/collapse */}
        {/* Shows ↑N where N is total ancestry depth (when collapsed at top level) */}
        {hasParent && (
          <span
            className={`hierarchy-node__badge hierarchy-node__badge--parent ${isExpanded ? 'hierarchy-node__badge--expanded' : ''}`}
            title={`${treeDepth} ancestor${treeDepth > 1 ? 's' : ''} - click to ${isExpanded ? 'collapse' : 'show ancestry'}`}
            onClick={handleToggle}
          >
            ↑{depth === 0 && treeDepth > 1 ? treeDepth : ''}
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
        // Build continuations for the parent - in reversed view, we're always showing a single chain
        const parentContinuations = [...continuations, false];

        return (
          <ul className="hierarchy-children">
            <ReversedNode
              session={parentSession}
              depth={depth + 1}
              treeDepth={treeDepth - 1}
              isSelected={parentSession.id === selectedSessionId}
              isExpanded={expandedSessions.has(parentSession.id)}
              isLast={true}
              continuations={parentContinuations}
              parentSession={grandparent || null}
              onSelect={onSelect}
              onToggle={onToggle}
              allSessions={allSessions}
              childrenByParent={childrenByParent}
              expandedSessions={expandedSessions}
              selectedSessionId={selectedSessionId}
              rootColorMap={rootColorMap}
              unreadSessionIds={unreadSessionIds}
            />
          </ul>
        );
      })()}
    </li>
  );
});

const HIERARCHY_MODE_KEY = 'balloons:hierarchy-mode';

// Empty set to use as default when unreadSessionIds is not provided
const EMPTY_SET = new Set<string>();

export const HierarchyView = memo(function HierarchyView({
  sessions,
  selectedSessionId,
  onSelectSession,
  isLoading = false,
  unreadSessionIds = EMPTY_SET,
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

  // Build session lookup, root-finding function, and depth calculator
  const { sessionById, findRoot, rootIds, getTreeDepth } = useMemo(() => {
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

    // Compute depth from root (0 = root, 1 = child of root, etc.)
    const depthCache = new Map<string, number>();
    const depth = (sessionId: string): number => {
      if (depthCache.has(sessionId)) {
        return depthCache.get(sessionId)!;
      }
      const session = byId.get(sessionId);
      if (!session || !session.parentId) {
        depthCache.set(sessionId, 0);
        return 0;
      }
      const d = depth(session.parentId) + 1;
      depthCache.set(sessionId, d);
      return d;
    };

    // Pre-compute root for each session and collect unique roots
    const roots = new Set<string>();
    for (const session of sessions) {
      roots.add(find(session.id));
    }

    return { sessionById: byId, findRoot: find, rootIds: roots, getTreeDepth: depth };
  }, [sessions]);

  // Compute most recent leaf lastModified for each root (for sorting)
  const mostRecentLeafByRoot = useMemo(() => {
    const map = new Map<string, number>();
    for (const session of sessions) {
      if (!sessionsWithChildren.has(session.id)) {
        // This is a leaf
        const rootId = findRoot(session.id);
        const leafTime = new Date(session.lastModified).getTime();
        const existing = map.get(rootId) || 0;
        if (leafTime > existing) {
          map.set(rootId, leafTime);
        }
      }
    }
    return map;
  }, [sessions, sessionsWithChildren, findRoot]);

  // Compute leaf sessions (no children) for leaves mode
  // Sort by: most recent leaf in each tree, then by lastModified within group
  const leafSessions = useMemo(() => {
    const leaves = sessions
      .filter(s => !sessionsWithChildren.has(s.id));

    // Sort: group by root ancestor (ordered by most recent leaf), then by lastModified within each group
    leaves.sort((a, b) => {
      const rootA = findRoot(a.id);
      const rootB = findRoot(b.id);

      // Different roots: sort by most recent leaf in each tree
      if (rootA !== rootB) {
        const recentA = mostRecentLeafByRoot.get(rootA) || 0;
        const recentB = mostRecentLeafByRoot.get(rootB) || 0;
        return recentB - recentA; // Most recently modified leaf's tree first
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

  // Get root sessions (no parent) sorted by most recent leaf in their tree
  const rootSessions = useMemo(() => {
    return sessions
      .filter(s => !s.parentId)
      .sort((a, b) => {
        const recentA = mostRecentLeafByRoot.get(a.id) || new Date(a.lastModified).getTime();
        const recentB = mostRecentLeafByRoot.get(b.id) || new Date(b.lastModified).getTime();
        return recentB - recentA;
      });
  }, [sessions, mostRecentLeafByRoot]);

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
          rootSessions.map((session, idx) => {
            const children = childrenByParent.get(session.id) || [];
            return (
              <SessionNode
                key={session.id}
                session={session}
                depth={0}
                treeDepth={0}
                isSelected={session.id === selectedSessionId}
                isExpanded={expandedSessions.has(session.id)}
                isLast={idx === rootSessions.length - 1}
                continuations={[]}
                childSessions={children}
                onSelect={onSelectSession}
                onToggle={toggleExpanded}
                allSessions={sessions}
                expandedSessions={expandedSessions}
                selectedSessionId={selectedSessionId}
                rootColorMap={rootColorMap}
                unreadSessionIds={unreadSessionIds}
              />
            );
          })
        ) : (
          // Leaves mode: show leaf sessions with parents nested
          leafSessions.map((session, idx) => {
            const parentSession = session.parentId
              ? sessions.find(s => s.id === session.parentId) || null
              : null;
            return (
              <ReversedNode
                key={session.id}
                session={session}
                depth={0}
                treeDepth={getTreeDepth(session.id)}
                isSelected={session.id === selectedSessionId}
                isExpanded={expandedSessions.has(session.id)}
                isLast={idx === leafSessions.length - 1}
                continuations={[]}
                parentSession={parentSession}
                onSelect={onSelectSession}
                onToggle={toggleExpanded}
                allSessions={sessions}
                childrenByParent={childrenByParent}
                expandedSessions={expandedSessions}
                selectedSessionId={selectedSessionId}
                rootColorMap={rootColorMap}
                unreadSessionIds={unreadSessionIds}
              />
            );
          })
        )}
      </ul>
    </div>
  );
});

export default HierarchyView;
