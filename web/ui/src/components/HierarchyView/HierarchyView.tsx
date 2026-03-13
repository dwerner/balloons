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
import { usePreferences } from '../layout/PreferencesContext';
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
  '#fb923c', // orange
  '#f472b6', // pink
  '#a78bfa', // violet
  '#2dd4bf', // teal
  '#a3e635', // lime
  '#fbbf24', // amber
];

// Convert hex color to RGB string for use in rgba()
function hexToRgb(hex: string): string {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result) return '96, 165, 250'; // fallback blue
  return `${parseInt(result[1]!, 16)}, ${parseInt(result[2]!, 16)}, ${parseInt(result[3]!, 16)}`;
}

// Stream depth bar - shows ancestry as stacked chevron/page edges
const MAX_VISIBLE_NOTCHES = 12;
const DEPTH_NOTCH_PATH = 'M0 0 L4 0 L8 8 L4 16 L0 16 L4 8 Z';

// ============================================================================
// Dragon Curve Fractal Generator (cached)
// ============================================================================

// Cache for dragon curve paths at various iterations
const dragonCurveCache = new Map<number, string>();

/**
 * Generate dragon curve path at a given iteration level.
 * Dragon curve: Start with R, then for each iteration, take the sequence,
 * add R, then add the reverse of the sequence with L/R flipped.
 *
 * We build it as a series of direction changes (L=left turn, R=right turn)
 * then convert to SVG path coordinates.
 */
function generateDragonCurve(iterations: number): string {
  // Check cache first
  const cached = dragonCurveCache.get(iterations);
  if (cached) return cached;

  // Generate turn sequence (L = left turn = 1, R = right turn = 0)
  // Start with single R
  let turns: number[] = [0]; // 0 = R

  for (let i = 1; i < iterations; i++) {
    // New sequence = old + R + reversed(old with flips)
    const reversed = [...turns].reverse().map(t => 1 - t);
    turns = [...turns, 0, ...reversed];
  }

  // Convert turns to path
  // We trace the curve, each segment is a fixed length
  // Direction: 0=right, 1=down, 2=left, 3=up
  const segmentLength = 4;
  let x = 0;
  let y = 0;
  let dir = 0; // Start facing right

  const points: [number, number][] = [[x, y]];

  for (const turn of turns) {
    // Move forward in current direction
    switch (dir) {
      case 0: x += segmentLength; break; // right
      case 1: y += segmentLength; break; // down
      case 2: x -= segmentLength; break; // left
      case 3: y -= segmentLength; break; // up
    }
    points.push([x, y]);

    // Turn: 0 = turn right (+1), 1 = turn left (-1)
    dir = (dir + (turn === 0 ? 1 : 3)) % 4;
  }

  // One more segment after last turn
  switch (dir) {
    case 0: x += segmentLength; break;
    case 1: y += segmentLength; break;
    case 2: x -= segmentLength; break;
    case 3: y -= segmentLength; break;
  }
  points.push([x, y]);

  // Find bounds to normalize
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const [px, py] of points) {
    minX = Math.min(minX, px);
    maxX = Math.max(maxX, px);
    minY = Math.min(minY, py);
    maxY = Math.max(maxY, py);
  }

  // Normalize to fit in viewBox (we'll use 0-100 range)
  const width = maxX - minX || 1;
  const height = maxY - minY || 1;
  const scale = Math.min(96 / width, 96 / height);
  const offsetX = (100 - width * scale) / 2 - minX * scale;
  const offsetY = (100 - height * scale) / 2 - minY * scale;

  // Build SVG path
  const pathParts = points.map(([px, py], i) => {
    const nx = px * scale + offsetX;
    const ny = py * scale + offsetY;
    return i === 0 ? `M${nx.toFixed(1)} ${ny.toFixed(1)}` : `L${nx.toFixed(1)} ${ny.toFixed(1)}`;
  });

  const path = pathParts.join(' ');
  dragonCurveCache.set(iterations, path);
  return path;
}

// Map depth to dragon curve iterations (1-12 depth = 1-12 iterations, capped)
function depthToIterations(depth: number): number {
  return Math.min(Math.max(depth, 1), 14); // Cap at 14 iterations (complex but not insane)
}

// Dragon curve depth indicator - single node version (legacy)
function DragonCurveIndicator({ depth, color }: { depth: number; color: string }) {
  const iterations = depthToIterations(depth);
  const path = useMemo(() => generateDragonCurve(iterations), [iterations]);

  return (
    <svg
      className="hierarchy-node__dragon-curve"
      viewBox="0 0 100 100"
      preserveAspectRatio="xMidYMid meet"
      style={{ color }}
    >
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        strokeWidth={Math.max(1, 4 - iterations * 0.2)}
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={0.5}
      />
    </svg>
  );
}

// ============================================================================
// Pre-rendered Dragon Curve Slice Cache (by depth + color)
// ============================================================================

// Cache structure: Map<cacheKey, dataURL> where cacheKey = `${totalDepth}-${rowIndex}-${color}`
const dragonSliceCache = new Map<string, string>();

// Color palette for dragon curve iterations - muted/desaturated, rotated order
// Starting from violet/purple and flowing through spectrum for subtle visual depth
const DRAGON_ITERATION_COLORS = [
  '#8b7cb5', // muted violet
  '#7986a8', // muted slate-blue
  '#6b9a9b', // muted teal
  '#7ba68f', // muted sage
  '#8aab7c', // muted olive-green
  '#a3a873', // muted khaki
  '#b5a06d', // muted gold
  '#c29572', // muted tan
  '#c4877f', // muted coral
  '#bb7f94', // muted rose
  '#a67fa8', // muted orchid
  '#9481b0', // muted lavender
  '#8186b3', // muted periwinkle
  '#7590af', // muted steel-blue
];

/**
 * Render a dragon curve slice to canvas with colors varying by iteration level.
 * The curve is drawn in segments, each iteration level gets a different color.
 * Results are cached by (depth, row) for reuse.
 */
function getDragonSliceDataUrl(totalDepth: number, rowIndex: number): string {
  const cacheKey = `${totalDepth}-${rowIndex}`;

  // Check cache
  if (dragonSliceCache.has(cacheKey)) {
    return dragonSliceCache.get(cacheKey)!;
  }

  // Generate turn sequence for the dragon curve
  const iterations = depthToIterations(totalDepth);

  // Build turns array with iteration level tracking
  // Each segment knows which iteration added it
  let turns: Array<{turn: number, iteration: number}> = [{turn: 0, iteration: 1}];

  for (let i = 2; i <= iterations; i++) {
    // New sequence = old + R + reversed(old with flips)
    const reversed = [...turns].reverse().map(t => ({turn: 1 - t.turn, iteration: i}));
    turns = [...turns, {turn: 0, iteration: i}, ...reversed];
  }

  // Create a canvas to render the full curve at high resolution for crisp lines
  const fullSize = 600; // Higher res = sharper lines
  const canvas = document.createElement('canvas');
  canvas.width = fullSize;
  canvas.height = fullSize;
  const ctx = canvas.getContext('2d')!;

  // Disable image smoothing for crisp lines
  ctx.imageSmoothingEnabled = false;

  // Apply 45 degree rotation around center
  ctx.translate(fullSize / 2, fullSize / 2);
  ctx.rotate(Math.PI / 4);
  ctx.translate(-fullSize / 2, -fullSize / 2);

  // Trace the curve segment by segment, coloring by iteration
  const segmentLength = 4;
  const scale = fullSize / 100;

  // Find bounds first to center properly (trace full curve for consistent layout)
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
  // Final segment
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

  // Normalize and position in top-right with zoom
  const width = maxX - minX || 1;
  const height = maxY - minY || 1;
  // Zoom factor: 2.2x bigger than "fit to canvas" for more detail
  const zoomFactor = 2.2;
  const normalizeScale = Math.min(96 / width, 96 / height) * zoomFactor;
  // Position toward top-right: offset so center of curve is at ~80% right, ~20% down
  const offsetX = 80 - ((minX + maxX) / 2) * normalizeScale;
  const offsetY = 20 - ((minY + maxY) / 2) * normalizeScale;

  // Draw segments with iteration-based colors
  // Thicker lines at higher res, scale with canvas size
  ctx.lineWidth = Math.max(2, 8 - iterations * 0.4);
  ctx.lineCap = 'square'; // Square caps = crisper
  ctx.lineJoin = 'miter';
  ctx.globalAlpha = 0.6;

  // Draw all segments
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1]!;
    const curr = points[i]!;

    // Color based on which iteration added this segment
    const colorIdx = (curr.iteration - 1) % DRAGON_ITERATION_COLORS.length;
    ctx.strokeStyle = DRAGON_ITERATION_COLORS[colorIdx]!;

    ctx.beginPath();
    ctx.moveTo((prev.x * normalizeScale + offsetX) * scale, (prev.y * normalizeScale + offsetY) * scale);
    ctx.lineTo((curr.x * normalizeScale + offsetX) * scale, (curr.y * normalizeScale + offsetY) * scale);
    ctx.stroke();
  }

  // Extract just this row's slice
  const sliceHeight = fullSize / totalDepth;
  const sliceCanvas = document.createElement('canvas');
  sliceCanvas.width = fullSize;
  sliceCanvas.height = Math.ceil(sliceHeight);
  const sliceCtx = sliceCanvas.getContext('2d')!;

  // Disable smoothing for crisp slice extraction
  sliceCtx.imageSmoothingEnabled = false;

  // Copy the relevant horizontal strip
  sliceCtx.drawImage(
    canvas,
    0, rowIndex * sliceHeight, fullSize, sliceHeight,
    0, 0, fullSize, sliceHeight
  );

  // Cache and return
  const dataUrl = sliceCanvas.toDataURL('image/png');
  dragonSliceCache.set(cacheKey, dataUrl);
  return dataUrl;
}

/**
 * Dragon curve slice - displays a pre-rendered bitmap slice.
 * The curve is colored by iteration level (each fractal depth gets its own color).
 */
function DragonCurveSlice({
  totalDepth,
  rowIndex,
}: {
  totalDepth: number;
  rowIndex: number;
}) {
  // Get pre-rendered slice from cache (renders on first access)
  const dataUrl = useMemo(
    () => getDragonSliceDataUrl(totalDepth, rowIndex),
    [totalDepth, rowIndex]
  );

  return (
    <img
      className="hierarchy-node__dragon-slice"
      src={dataUrl}
      alt=""
      draggable={false}
    />
  );
}

// ============================================================================
// Chevron-based depth indicator (original)
// ============================================================================

// Fractal notch - contains smaller notches inside to represent overflow
function FractalNotch({ overflow, color }: { overflow: number; color: string }) {
  // Each mini-notch represents ~4 levels of overflow
  const miniCount = Math.min(Math.ceil(overflow / 4), 3);

  return (
    <svg
      className="hierarchy-node__depth-notch hierarchy-node__depth-notch--fractal"
      viewBox="0 0 24 16"
      preserveAspectRatio="none"
      style={{ color }}
    >
      {/* Outer container notch */}
      <path d="M0 0 L12 0 L24 8 L12 16 L0 16 L12 8 Z" fill="currentColor" opacity="0.4" />
      {/* Mini notches inside, stacked */}
      {Array.from({ length: miniCount }, (_, i) => {
        const scale = 0.35;
        const offsetX = 3 + i * 4;
        const offsetY = 4;
        return (
          <g key={i} transform={`translate(${offsetX}, ${offsetY}) scale(${scale})`}>
            <path d={DEPTH_NOTCH_PATH} fill="currentColor" opacity={0.6 + i * 0.15} />
          </g>
        );
      })}
      {/* Overflow count badge */}
      <text
        x="12"
        y="10"
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="6"
        fontWeight="600"
        fill="currentColor"
        opacity="0.8"
      >
        +{overflow}
      </text>
    </svg>
  );
}

function ChevronDepthBar({ depth, color }: { depth: number; color: string }) {
  const visibleNotches = Math.min(depth, MAX_VISIBLE_NOTCHES);
  const overflow = depth - MAX_VISIBLE_NOTCHES;

  return (
    <div className="hierarchy-node__depth-bar">
      <div className="hierarchy-node__depth-notches">
        {overflow > 0 && (
          <FractalNotch overflow={overflow} color={color} />
        )}
        {Array.from({ length: visibleNotches }, (_, i) => (
          <svg
            key={i}
            className="hierarchy-node__depth-notch"
            viewBox="0 0 8 16"
            preserveAspectRatio="none"
            style={{ color }}
          >
            <path d={DEPTH_NOTCH_PATH} fill="currentColor" />
          </svg>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// Unified DepthBar that switches based on preference
// ============================================================================

interface DepthBarProps {
  depth: number;         // Current node's depth from leaf (0 = leaf)
  totalDepth: number;    // Total tree depth (for video wall effect)
  color: string;
  style: 'chevrons' | 'fractal';
}

function DepthBar({ depth, totalDepth, color, style }: DepthBarProps) {
  if (totalDepth <= 0) return null;

  if (style === 'fractal') {
    return (
      <div className="hierarchy-node__depth-bar hierarchy-node__depth-bar--fractal">
        <DragonCurveSlice
          totalDepth={totalDepth}
          rowIndex={depth}
        />
      </div>
    );
  }

  // Chevron mode only shows on leaf nodes (depth=0)
  if (depth !== 0) return null;
  return <ChevronDepthBar depth={totalDepth} color={color} />;
}

// Calculate depth-based opacity - increases with depth, no max
function getDepthOpacity(depth: number): number {
  if (depth === 0) return 0;
  return Math.min(depth * 0.03, 0.4); // 0.03 per level, cap at 0.4
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

  // Depth-based background tint using session color
  const depthOpacity = getDepthOpacity(treeDepth);

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
          '--depth-tint-color': hexToRgb(sessionColor),
          '--depth-tint-opacity': depthOpacity,
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
  depth: number;           // Visual indentation depth (0 = leaf at top, increases going to ancestors)
  treeDepth: number;       // Current node's depth from root (decreases going to ancestors)
  maxTreeDepth: number;    // Total tree depth (constant, for video wall effect)
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
  depthStyle: 'chevrons' | 'fractal';  // Depth indicator style preference
}

const ReversedNode = memo(function ReversedNode({
  session,
  depth,
  treeDepth,
  maxTreeDepth,
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
  depthStyle,
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

  // Depth-based background tint using session color
  const depthOpacity = getDepthOpacity(treeDepth);

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
          '--depth-tint-color': hexToRgb(sessionColor),
          '--depth-tint-opacity': depthOpacity,
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

        {/* Depth bar - video wall shows slice on every node, chevrons only on leaf */}
        <DepthBar
          depth={depth}
          totalDepth={maxTreeDepth}
          color={sessionColor}
          style={depthStyle}
        />
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
              maxTreeDepth={maxTreeDepth}
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
              depthStyle={depthStyle}
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
  // Get depth indicator style preference
  const { depthIndicatorStyle } = usePreferences();

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
            const leafTreeDepth = getTreeDepth(session.id);
            return (
              <ReversedNode
                key={session.id}
                session={session}
                depth={0}
                treeDepth={leafTreeDepth}
                maxTreeDepth={leafTreeDepth}
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
                depthStyle={depthIndicatorStyle}
              />
            );
          })
        )}
      </ul>
    </div>
  );
});

export default HierarchyView;
