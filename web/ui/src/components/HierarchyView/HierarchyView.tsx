/**
 * HierarchyView - Virtualized session hierarchy using react-arborist
 *
 * Two modes:
 * - 'roots': Show root sessions at top, forks nested below (standard tree)
 * - 'leaves': Show leaf sessions at top, ancestors nested below (inverted tree)
 *
 * Uses react-arborist for efficient virtualized rendering of 1000+ sessions.
 */

import React, { useState, useCallback, useMemo, memo, useRef, useEffect } from 'react';
import { Tree, TreeApi } from 'react-arborist';
import type { NodeRendererProps } from 'react-arborist';
import useResizeObserver from 'use-resize-observer';
import type { SessionInfo } from '../../../../generated/balloons-client';
import { createLogger } from '../../utils/debugLog';
import { usePreferences } from '../layout/PreferencesContext';
import './HierarchyView.css';

const debugLog = createLogger('HierarchyView');

// ==================== Helper Functions ====================

function formatTokenCount(tokens: number): string {
  if (tokens >= 1000000) {
    return `${(tokens / 1000000).toFixed(1)}M`;
  } else if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(0)}k`;
  }
  return String(tokens);
}

function getTokenCountClass(tokens: number, contextWindow?: number): string {
  if (!contextWindow || contextWindow === 0) return '';
  const pct = (tokens / contextWindow) * 100;
  if (pct >= 80) return 'hierarchy-node__tokens--high';
  if (pct >= 50) return 'hierarchy-node__tokens--medium';
  return 'hierarchy-node__tokens--low';
}

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

// Session colors for visual distinction
const SESSION_COLORS = [
  '#60a5fa', // blue
  '#c084fc', // purple
  '#22d3ee', // cyan
  '#4ade80', // green
  '#facc15', // yellow
  '#f87171', // red
  '#fb923c', // orange
  '#f472b6', // pink
  '#a78bfa', // violet
  '#2dd4bf', // teal
  '#a3e635', // lime
  '#fbbf24', // amber
];

function hexToRgb(hex: string): string {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result) return '96, 165, 250';
  return `${parseInt(result[1]!, 16)}, ${parseInt(result[2]!, 16)}, ${parseInt(result[3]!, 16)}`;
}

// ==================== Icons ====================

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
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" fill="none" opacity="0.2" />
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeDasharray="47 63" />
    </svg>
  );
}

// ==================== Depth Indicators ====================

const MAX_VISIBLE_NOTCHES = 12;
const DEPTH_NOTCH_PATH = 'M0 0 L4 0 L8 8 L4 16 L0 16 L4 8 Z';

// Dragon curve cache
const dragonCurveCache = new Map<number, string>();

const DRAGON_ITERATION_COLORS = [
  '#8b7cb5', '#7986a8', '#6b9a9b', '#7ba68f', '#8aab7c', '#a3a873',
  '#b5a06d', '#c29572', '#c4877f', '#bb7f94', '#a67fa8', '#9481b0',
  '#8186b3', '#7590af',
];

function generateDragonCurve(iterations: number): string {
  const cached = dragonCurveCache.get(iterations);
  if (cached) return cached;

  let turns: number[] = [0];
  for (let i = 1; i < iterations; i++) {
    const reversed = [...turns].reverse().map(t => 1 - t);
    turns = [...turns, 0, ...reversed];
  }

  const segmentLength = 4;
  let x = 0, y = 0, dir = 0;
  const points: [number, number][] = [[x, y]];

  for (const turn of turns) {
    switch (dir) {
      case 0: x += segmentLength; break;
      case 1: y += segmentLength; break;
      case 2: x -= segmentLength; break;
      case 3: y -= segmentLength; break;
    }
    points.push([x, y]);
    dir = (dir + (turn === 0 ? 1 : 3)) % 4;
  }

  switch (dir) {
    case 0: x += segmentLength; break;
    case 1: y += segmentLength; break;
    case 2: x -= segmentLength; break;
    case 3: y -= segmentLength; break;
  }
  points.push([x, y]);

  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const [px, py] of points) {
    minX = Math.min(minX, px);
    maxX = Math.max(maxX, px);
    minY = Math.min(minY, py);
    maxY = Math.max(maxY, py);
  }

  const width = maxX - minX || 1;
  const height = maxY - minY || 1;
  const scale = Math.min(96 / width, 96 / height);
  const offsetX = (100 - width * scale) / 2 - minX * scale;
  const offsetY = (100 - height * scale) / 2 - minY * scale;

  const pathParts = points.map(([px, py], i) => {
    const nx = px * scale + offsetX;
    const ny = py * scale + offsetY;
    return i === 0 ? `M${nx.toFixed(1)} ${ny.toFixed(1)}` : `L${nx.toFixed(1)} ${ny.toFixed(1)}`;
  });

  const path = pathParts.join(' ');
  dragonCurveCache.set(iterations, path);
  return path;
}

function depthToIterations(depth: number): number {
  return Math.min(Math.max(depth, 1), 14);
}

const dragonSliceCache = new Map<string, string>();

function getDragonSliceDataUrl(totalDepth: number, rowIndex: number): string {
  const cacheKey = `${totalDepth}-${rowIndex}`;
  if (dragonSliceCache.has(cacheKey)) {
    return dragonSliceCache.get(cacheKey)!;
  }

  const iterations = depthToIterations(totalDepth);
  let turns: Array<{turn: number, iteration: number}> = [{turn: 0, iteration: 1}];

  for (let i = 2; i <= iterations; i++) {
    const reversed = [...turns].reverse().map(t => ({turn: 1 - t.turn, iteration: i}));
    turns = [...turns, {turn: 0, iteration: i}, ...reversed];
  }

  const fullSize = 600;
  const canvas = document.createElement('canvas');
  canvas.width = fullSize;
  canvas.height = fullSize;
  const ctx = canvas.getContext('2d')!;
  ctx.imageSmoothingEnabled = false;
  ctx.translate(fullSize / 2, fullSize / 2);
  ctx.rotate(Math.PI / 4);
  ctx.translate(-fullSize / 2, -fullSize / 2);

  const segmentLength = 4;
  const scale = fullSize / 100;
  let x = 0, y = 0, dir = 0;
  let minX = 0, maxX = 0, minY = 0, maxY = 0;
  const points: Array<{x: number, y: number, iteration: number}> = [{x: 0, y: 0, iteration: 1}];

  for (const {turn, iteration} of turns) {
    switch (dir) {
      case 0: x += segmentLength; break;
      case 1: y += segmentLength; break;
      case 2: x -= segmentLength; break;
      case 3: y -= segmentLength; break;
    }
    points.push({x, y, iteration});
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
    dir = (dir + (turn === 0 ? 1 : 3)) % 4;
  }

  switch (dir) {
    case 0: x += segmentLength; break;
    case 1: y += segmentLength; break;
    case 2: x -= segmentLength; break;
    case 3: y -= segmentLength; break;
  }
  points.push({x, y, iteration: iterations});
  minX = Math.min(minX, x);
  maxX = Math.max(maxX, x);
  minY = Math.min(minY, y);
  maxY = Math.max(maxY, y);

  const width = maxX - minX || 1;
  const height = maxY - minY || 1;
  const zoomFactor = 2.2;
  const normalizeScale = Math.min(96 / width, 96 / height) * zoomFactor;
  const offsetX = 80 - ((minX + maxX) / 2) * normalizeScale;
  const offsetY = 20 - ((minY + maxY) / 2) * normalizeScale;

  ctx.lineWidth = Math.max(2, 8 - iterations * 0.4);
  ctx.lineCap = 'square';
  ctx.lineJoin = 'miter';
  ctx.globalAlpha = 0.6;

  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1]!;
    const curr = points[i]!;
    const colorIdx = (curr.iteration - 1) % DRAGON_ITERATION_COLORS.length;
    ctx.strokeStyle = DRAGON_ITERATION_COLORS[colorIdx]!;
    ctx.beginPath();
    ctx.moveTo((prev.x * normalizeScale + offsetX) * scale, (prev.y * normalizeScale + offsetY) * scale);
    ctx.lineTo((curr.x * normalizeScale + offsetX) * scale, (curr.y * normalizeScale + offsetY) * scale);
    ctx.stroke();
  }

  const sliceHeight = fullSize / totalDepth;
  const sliceCanvas = document.createElement('canvas');
  sliceCanvas.width = fullSize;
  sliceCanvas.height = Math.ceil(sliceHeight);
  const sliceCtx = sliceCanvas.getContext('2d')!;
  sliceCtx.imageSmoothingEnabled = false;
  sliceCtx.drawImage(canvas, 0, rowIndex * sliceHeight, fullSize, sliceHeight, 0, 0, fullSize, sliceHeight);

  const dataUrl = sliceCanvas.toDataURL('image/png');
  dragonSliceCache.set(cacheKey, dataUrl);
  return dataUrl;
}

function DragonCurveSlice({ totalDepth, rowIndex }: { totalDepth: number; rowIndex: number }) {
  const dataUrl = useMemo(() => getDragonSliceDataUrl(totalDepth, rowIndex), [totalDepth, rowIndex]);
  return <img className="hierarchy-node__dragon-slice" src={dataUrl} alt="" draggable={false} />;
}

function FractalNotch({ overflow, color }: { overflow: number; color: string }) {
  const miniCount = Math.min(Math.ceil(overflow / 4), 3);
  return (
    <svg className="hierarchy-node__depth-notch hierarchy-node__depth-notch--fractal" viewBox="0 0 24 16" preserveAspectRatio="none" style={{ color }}>
      <path d="M0 0 L12 0 L24 8 L12 16 L0 16 L12 8 Z" fill="currentColor" opacity="0.4" />
      {Array.from({ length: miniCount }, (_, i) => (
        <g key={i} transform={`translate(${3 + i * 4}, 4) scale(0.35)`}>
          <path d={DEPTH_NOTCH_PATH} fill="currentColor" opacity={0.6 + i * 0.15} />
        </g>
      ))}
      <text x="12" y="10" textAnchor="middle" dominantBaseline="middle" fontSize="6" fontWeight="600" fill="currentColor" opacity="0.8">+{overflow}</text>
    </svg>
  );
}

function ChevronDepthBar({ depth, color }: { depth: number; color: string }) {
  const visibleNotches = Math.min(depth, MAX_VISIBLE_NOTCHES);
  const overflow = depth - MAX_VISIBLE_NOTCHES;
  return (
    <div className="hierarchy-node__depth-bar">
      <div className="hierarchy-node__depth-notches">
        {overflow > 0 && <FractalNotch overflow={overflow} color={color} />}
        {Array.from({ length: visibleNotches }, (_, i) => (
          <svg key={i} className="hierarchy-node__depth-notch" viewBox="0 0 8 16" preserveAspectRatio="none" style={{ color }}>
            <path d={DEPTH_NOTCH_PATH} fill="currentColor" />
          </svg>
        ))}
      </div>
    </div>
  );
}

interface DepthBarProps {
  depth: number;
  totalDepth: number;
  color: string;
  style: 'chevrons' | 'fractal';
}

function DepthBar({ depth, totalDepth, color, style }: DepthBarProps) {
  if (totalDepth <= 0) return null;
  if (style === 'fractal') {
    return (
      <div className="hierarchy-node__depth-bar hierarchy-node__depth-bar--fractal">
        <DragonCurveSlice totalDepth={totalDepth} rowIndex={depth} />
      </div>
    );
  }
  if (depth !== 0) return null;
  return <ChevronDepthBar depth={totalDepth} color={color} />;
}

function getDepthOpacity(depth: number): number {
  if (depth === 0) return 0;
  return Math.min(depth * 0.03, 0.4);
}

// ==================== Tree Data Types ====================

interface TreeNodeData {
  id: string;
  session: SessionInfo;
  colorIndex: number;
  treeDepth: number;       // Actual depth from root
  maxTreeDepth: number;    // For fractal depth display
  siblingCount?: number;   // For leaves mode
  children?: TreeNodeData[];
}

// ==================== Node Renderer ====================

interface SessionNodeRendererProps {
  nodeProps: NodeRendererProps<TreeNodeData>;
  onSelectSession: (sessionId: string) => void;
  selectedSessionId: string | null;
  mode: HierarchyMode;
  unreadSessionIds: Set<string>;
  depthStyle: 'chevrons' | 'fractal';
}

const SessionNodeRenderer = memo(function SessionNodeRenderer({
  nodeProps,
  onSelectSession,
  selectedSessionId,
  mode,
  unreadSessionIds,
  depthStyle,
}: SessionNodeRendererProps) {
  const { node, style } = nodeProps;
  const { session, colorIndex, treeDepth, maxTreeDepth, siblingCount } = node.data;
  const sessionColor = SESSION_COLORS[colorIndex % SESSION_COLORS.length] || '#60a5fa';
  const sessionName = session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
  const hasChildren = !node.isLeaf;
  const isSelected = session.id === selectedSessionId;
  const isUnread = unreadSessionIds.has(session.id);

  // react-arborist provides indentation via node.level - we use treeDepth for tinting
  const depthOpacity = getDepthOpacity(treeDepth);

  const handleClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onSelectSession(session.id);
  }, [onSelectSession, session.id]);

  const handleToggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    node.toggle();
  }, [node]);

  return (
    <div
      style={style}
      className={`hierarchy-node__row ${isSelected ? 'hierarchy-node__row--selected' : ''} ${session.forkStatus === 'merged' ? 'hierarchy-node__row--merged' : ''} ${isUnread ? 'hierarchy-node__row--unread' : ''}`}
      onClick={handleClick}
    >
      <div
        className="hierarchy-node__content"
        style={{
          paddingLeft: '8px',
          borderLeftColor: sessionColor,
          '--depth-tint-color': hexToRgb(sessionColor),
          '--depth-tint-opacity': depthOpacity,
        } as React.CSSProperties}
      >
        {/* Expand/collapse toggle */}
        {hasChildren && (
          <span className="hierarchy-node__toggle" onClick={handleToggle}>
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke={sessionColor}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={`hierarchy-arrow ${node.isOpen ? 'hierarchy-arrow--open' : ''}`}
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </span>
        )}
        {!hasChildren && <span className="hierarchy-node__toggle-placeholder" />}

        {/* Status indicators */}
        {session.isStreaming && (
          <span className="hierarchy-node__badge hierarchy-node__badge--streaming" title="Streaming">
            <StreamingSpinner />
          </span>
        )}

        {session.forkStatus === 'merged' && (
          <span className="hierarchy-node__badge hierarchy-node__badge--merged" title="Merged">✓</span>
        )}

        {/* Mode-specific badges */}
        {mode === 'roots' ? (
          <>
            {hasChildren && (
              <span
                className={`hierarchy-node__badge hierarchy-node__badge--children ${node.isOpen ? 'hierarchy-node__badge--expanded' : ''}`}
                title={`${node.children?.length || 0} fork(s)`}
              >
                ⑂{node.children?.length || 0}
              </span>
            )}
          </>
        ) : (
          <>
            {hasChildren && treeDepth > 0 && (
              <span
                className={`hierarchy-node__badge hierarchy-node__badge--parent ${node.isOpen ? 'hierarchy-node__badge--expanded' : ''}`}
                title={`${treeDepth} ancestor${treeDepth > 1 ? 's' : ''}`}
              >
                ↑{treeDepth}
              </span>
            )}
          </>
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

        {/* Depth bar (leaves mode only) */}
        {mode === 'leaves' && (
          <DepthBar
            depth={node.level}
            totalDepth={maxTreeDepth}
            color={sessionColor}
            style={depthStyle}
          />
        )}
      </div>
    </div>
  );
});

// ==================== Props ====================

export type HierarchyMode = 'roots' | 'leaves';

export interface HierarchyViewProps {
  sessions: SessionInfo[];
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  isLoading?: boolean;
  unreadSessionIds?: Set<string>;
}

const HIERARCHY_MODE_KEY = 'balloons:hierarchy-mode';
const EMPTY_SET = new Set<string>();

// ==================== Main Component ====================

export const HierarchyView = memo(function HierarchyView({
  sessions,
  selectedSessionId,
  onSelectSession,
  isLoading = false,
  unreadSessionIds = EMPTY_SET,
}: HierarchyViewProps) {
  const treeRef = useRef<TreeApi<TreeNodeData>>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const { depthIndicatorStyle } = usePreferences();

  // View mode persisted in localStorage
  const [mode, setMode] = useState<HierarchyMode>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem(HIERARCHY_MODE_KEY);
      return (stored === 'roots' || stored === 'leaves') ? stored : 'leaves';
    }
    return 'leaves';
  });

  const handleModeChange = useCallback((newMode: HierarchyMode) => {
    setMode(newMode);
    localStorage.setItem(HIERARCHY_MODE_KEY, newMode);
  }, []);

  // Use useResizeObserver to track container dimensions
  const { ref: treeWrapperRef, width: containerWidth, height: containerHeight } = useResizeObserver<HTMLDivElement>();

  // Build session lookups
  const { sessionById, childrenByParent, rootColorMap, findRoot, getTreeDepth, mostRecentLeafByRoot } = useMemo(() => {
    const byId = new Map(sessions.map(s => [s.id, s]));

    // Children lookup
    const childMap = new Map<string, SessionInfo[]>();
    for (const session of sessions) {
      if (session.parentId) {
        const existing = childMap.get(session.parentId) || [];
        existing.push(session);
        childMap.set(session.parentId, existing);
      }
    }
    for (const [, children] of childMap) {
      children.sort((a, b) => new Date(a.created).getTime() - new Date(b.created).getTime());
    }

    // Root finding with cache
    const rootCache = new Map<string, string>();
    const find = (sessionId: string): string => {
      if (rootCache.has(sessionId)) return rootCache.get(sessionId)!;
      const session = byId.get(sessionId);
      if (!session || !session.parentId) {
        rootCache.set(sessionId, sessionId);
        return sessionId;
      }
      const rootId = find(session.parentId);
      rootCache.set(sessionId, rootId);
      return rootId;
    };

    // Depth calculation
    const depthCache = new Map<string, number>();
    const depth = (sessionId: string): number => {
      if (depthCache.has(sessionId)) return depthCache.get(sessionId)!;
      const session = byId.get(sessionId);
      if (!session || !session.parentId) {
        depthCache.set(sessionId, 0);
        return 0;
      }
      const d = depth(session.parentId) + 1;
      depthCache.set(sessionId, d);
      return d;
    };

    // Sessions with children
    const withChildren = new Set<string>();
    for (const session of sessions) {
      if (session.parentId) withChildren.add(session.parentId);
      if (session.children?.length) withChildren.add(session.id);
    }

    // Most recent leaf per root
    const recentLeaf = new Map<string, number>();
    for (const session of sessions) {
      if (!withChildren.has(session.id)) {
        const rootId = find(session.id);
        const leafTime = new Date(session.lastModified).getTime();
        const existing = recentLeaf.get(rootId) || 0;
        if (leafTime > existing) recentLeaf.set(rootId, leafTime);
      }
    }

    // Root sessions sorted
    const rootSessions = sessions
      .filter(s => !s.parentId)
      .sort((a, b) => {
        const recentA = recentLeaf.get(a.id) || new Date(a.lastModified).getTime();
        const recentB = recentLeaf.get(b.id) || new Date(b.lastModified).getTime();
        return recentB - recentA;
      });

    // Color index by root
    const rootColorIndices = new Map<string, number>();
    rootSessions.forEach((root, idx) => rootColorIndices.set(root.id, idx));

    const colorMap = new Map<string, number>();
    for (const session of sessions) {
      const rootId = find(session.id);
      colorMap.set(session.id, rootColorIndices.get(rootId) ?? 0);
    }

    return {
      sessionById: byId,
      childrenByParent: childMap,
      rootColorMap: colorMap,
      findRoot: find,
      getTreeDepth: depth,
      mostRecentLeafByRoot: recentLeaf,
    };
  }, [sessions]);

  // Build tree data for roots mode
  const rootsTreeData = useMemo((): TreeNodeData[] => {
    const rootSessions = sessions
      .filter(s => !s.parentId)
      .sort((a, b) => {
        const recentA = mostRecentLeafByRoot.get(a.id) || new Date(a.lastModified).getTime();
        const recentB = mostRecentLeafByRoot.get(b.id) || new Date(b.lastModified).getTime();
        return recentB - recentA;
      });

    const buildNode = (session: SessionInfo, depth: number): TreeNodeData => {
      const children = childrenByParent.get(session.id) || [];
      return {
        id: session.id,
        session,
        colorIndex: rootColorMap.get(session.id) ?? 0,
        treeDepth: depth,
        maxTreeDepth: depth,
        children: children.length > 0 ? children.map(c => buildNode(c, depth + 1)) : undefined,
      };
    };

    return rootSessions.map(s => buildNode(s, 0));
  }, [sessions, childrenByParent, rootColorMap, mostRecentLeafByRoot]);

  // Build tree data for leaves mode (inverted)
  const leavesTreeData = useMemo((): TreeNodeData[] => {
    const sessionsWithChildren = new Set<string>();
    for (const session of sessions) {
      if (session.parentId) sessionsWithChildren.add(session.parentId);
      if (session.children?.length) sessionsWithChildren.add(session.id);
    }

    const leaves = sessions
      .filter(s => !sessionsWithChildren.has(s.id))
      .sort((a, b) => {
        const rootA = findRoot(a.id);
        const rootB = findRoot(b.id);
        if (rootA !== rootB) {
          const recentA = mostRecentLeafByRoot.get(rootA) || 0;
          const recentB = mostRecentLeafByRoot.get(rootB) || 0;
          return recentB - recentA;
        }
        return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
      });

    const buildInvertedNode = (session: SessionInfo, visualDepth: number, leafTreeDepth: number): TreeNodeData => {
      const parentSession = session.parentId ? sessionById.get(session.parentId) : undefined;
      const treeDepth = getTreeDepth(session.id);

      let siblingCount = 0;
      if (parentSession) {
        const siblings = childrenByParent.get(parentSession.id) || [];
        siblingCount = siblings.length - 1;
      }

      return {
        id: session.id,
        session,
        colorIndex: rootColorMap.get(session.id) ?? 0,
        treeDepth,
        maxTreeDepth: leafTreeDepth,
        siblingCount,
        children: parentSession ? [buildInvertedNode(parentSession, visualDepth + 1, leafTreeDepth)] : undefined,
      };
    };

    return leaves.map(s => buildInvertedNode(s, 0, getTreeDepth(s.id)));
  }, [sessions, sessionById, childrenByParent, rootColorMap, findRoot, getTreeDepth, mostRecentLeafByRoot]);

  const treeData = mode === 'roots' ? rootsTreeData : leavesTreeData;

  // Initial open state
  const initialOpenState = useMemo(() => {
    const openMap: Record<string, boolean> = {};
    const collectIds = (nodes: TreeNodeData[]) => {
      for (const node of nodes) {
        if (node.children?.length) {
          openMap[node.id] = true;
          collectIds(node.children);
        }
      }
    };
    collectIds(treeData);
    return openMap;
  }, [treeData]);

  // Scroll to selected session
  useEffect(() => {
    if (!selectedSessionId || !treeRef.current) return;
    const timeoutId = setTimeout(() => {
      treeRef.current?.scrollTo(selectedSessionId, 'smart');
    }, 50);
    return () => clearTimeout(timeoutId);
  }, [selectedSessionId, mode]);

  // Create the node renderer component
  const NodeRenderer = useCallback((props: NodeRendererProps<TreeNodeData>) => (
    <SessionNodeRenderer
      nodeProps={props}
      onSelectSession={onSelectSession}
      selectedSessionId={selectedSessionId}
      mode={mode}
      unreadSessionIds={unreadSessionIds}
      depthStyle={depthIndicatorStyle}
    />
  ), [onSelectSession, selectedSessionId, mode, unreadSessionIds, depthIndicatorStyle]);

  useEffect(() => {
    debugLog('HierarchyView mounted with react-arborist', { sessionCount: sessions.length, mode });
  }, [sessions.length, mode]);

  if (isLoading) {
    return <div className="hierarchy-view hierarchy-view--empty">Loading sessions...</div>;
  }

  if (sessions.length === 0) {
    return <div className="hierarchy-view hierarchy-view--empty">No sessions</div>;
  }

  return (
    <div className="hierarchy-view" ref={containerRef}>
      <div className="hierarchy-mode-toggle">
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
      </div>

      <div className="hierarchy-tree-wrapper" ref={treeWrapperRef}>
        {containerHeight && containerHeight > 0 && (
          <Tree<TreeNodeData>
            ref={treeRef}
            data={treeData}
            width={containerWidth || '100%'}
            height={containerHeight}
            rowHeight={36}
            indent={16}
            openByDefault={true}
            initialOpenState={initialOpenState}
            selection={selectedSessionId || undefined}
            disableDrag={true}
            disableDrop={true}
            disableEdit={true}
            disableMultiSelection={true}
          >
            {NodeRenderer}
          </Tree>
        )}
      </div>
    </div>
  );
});

export default HierarchyView;
