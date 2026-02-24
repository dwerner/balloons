/**
 * BaseToolCard - Shared structure for all tool-specific cards
 *
 * Provides:
 * - Consistent header with status icon, tool name, and custom content
 * - Status-based styling (executing, completed, error)
 * - Collapsible content - shows first N lines by default, expands on header tap
 * - Token count display
 * - Three display modes: formatted (default), collapsed, raw (for debugging)
 */

import React, { useState, useRef, useEffect, useDeferredValue } from 'react';
import { SyntaxHighlightedCode } from './SyntaxHighlighter';
import { usePreferences } from '../../layout';
import './cards.css';

// Tool execution phase
export type ToolPhase = 'building' | 'executing' | 'completed' | 'error';

// Display mode for the card
export type ToolCardDisplayMode = 'formatted' | 'collapsed' | 'raw';

export interface BaseToolCardProps {
  /** Tool name displayed in header */
  toolName: string;
  /** Custom content for the header (file path, pattern, etc.) */
  headerContent?: React.ReactNode;
  /** Current tool execution phase */
  phase: ToolPhase;
  /** Token count (shown when completed) */
  tokens?: number;
  /** Turn order number (for scroll position indicator) */
  order?: number;
  /** End of order range (for cards that combine tool_use + tool_result) */
  orderEnd?: number;
  /** Main body content (for formatted mode) */
  children?: React.ReactNode;
  /** Additional CSS class */
  className?: string;
  /** Number of lines to show when collapsed (default: 5) */
  collapsedLines?: number;
  /** Start expanded (default: false for completed, true for active) */
  defaultExpanded?: boolean;
  /** Initial display mode: formatted (default), collapsed, or raw for debugging */
  initialDisplayMode?: ToolCardDisplayMode;
  /** Raw data for debugging (required for mode switcher to work) */
  rawData?: unknown;
}

// Phase to icon mapping
function getPhaseIcon(phase: ToolPhase): string {
  switch (phase) {
    case 'building':
      return '⋯';
    case 'executing':
      return '⏳';
    case 'completed':
      return '✓';
    case 'error':
      return '✗';
  }
}

// Status icon component with animation for active states
function ToolStatusIcon({ phase }: { phase: ToolPhase }) {
  const icon = getPhaseIcon(phase);
  const isActive = phase === 'building' || phase === 'executing';

  return (
    <span className={`tool-status-icon ${phase}`}>
      {isActive ? <span className="tool-spinner">{icon}</span> : icon}
    </span>
  );
}

/**
 * Raw JSON display for debugging - with syntax highlighting
 */
function RawDataDisplay({ data }: { data: unknown }) {
  const formatted = JSON.stringify(data, null, 2);
  return (
    <div className="tool-raw-data">
      <SyntaxHighlightedCode code={formatted} language="json" wrapLongLines />
    </div>
  );
}

/**
 * Mode switcher component - allows toggling between formatted and raw views
 */
function ModeSwitcher({
  mode,
  onModeChange,
  hasRawData,
}: {
  mode: ToolCardDisplayMode;
  onModeChange: (mode: ToolCardDisplayMode) => void;
  hasRawData: boolean;
}) {
  if (!hasRawData) return null;

  const handleFormatted = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    console.log('ModeSwitcher: switching to formatted, current mode:', mode);
    onModeChange('formatted');
  };

  const handleRaw = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    console.log('ModeSwitcher: switching to raw, current mode:', mode);
    onModeChange('raw');
  };

  return (
    <div className="tool-card-mode-switcher" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className={`mode-btn ${mode === 'formatted' ? 'active' : ''}`}
        onClick={handleFormatted}
        title="Formatted view"
      >
        <span className="mode-icon">◈</span>
      </button>
      <button
        type="button"
        className={`mode-btn ${mode === 'raw' ? 'active' : ''}`}
        onClick={handleRaw}
        title="Raw JSON"
      >
        <span className="mode-icon">{'{}'}</span>
      </button>
    </div>
  );
}

/**
 * BaseToolCard - Wrapper component for tool-specific cards
 *
 * Content is collapsible - shows first N lines by default (when completed).
 * Tap/click the header to expand/collapse.
 *
 * Display modes:
 * - 'formatted' (default): Shows formatted children with collapsible behavior
 * - 'collapsed': Always starts collapsed
 * - 'raw': Shows raw JSON data for debugging
 */
export function BaseToolCard({
  toolName,
  headerContent,
  phase,
  tokens = 0,
  order,
  orderEnd,
  children,
  className = '',
  collapsedLines = 5,
  defaultExpanded,
  initialDisplayMode = 'formatted',
  rawData,
}: BaseToolCardProps) {
  const { expandToolCards: expandToolCardsPref } = usePreferences();
  // Use deferred value to make preference changes non-blocking
  const expandToolCards = useDeferredValue(expandToolCardsPref);
  const isActive = phase === 'building' || phase === 'executing';
  const statusClass = phase === 'error' ? 'error' : isActive ? 'executing' : 'completed';

  // Internal display mode state (can be toggled by user)
  const [displayMode, setDisplayMode] = useState<ToolCardDisplayMode>(initialDisplayMode);

  // Determine expanded state - respect user preference, don't auto-expand for streaming
  const getInitialExpanded = () => {
    if (displayMode === 'collapsed') return false;
    if (displayMode === 'raw') return true; // Raw mode is always expanded
    // Priority: explicit prop > user preference
    if (defaultExpanded !== undefined) return defaultExpanded;
    return expandToolCards; // Respect user preference (default: false = collapsed)
  };

  // Start with the correct collapsed state immediately
  const [expanded, setExpanded] = useState(getInitialExpanded);
  // Assume content needs collapse until we measure (prevents reflow)
  const [needsCollapse, setNeedsCollapse] = useState(!expandToolCards);
  const bodyRef = useRef<HTMLDivElement>(null);

  // Calculate if content is tall enough to need collapsing
  // Using line-height of ~18px (11px font * 1.4 line-height + padding)
  const collapsedHeight = collapsedLines * 18 + 12; // +12 for padding

  useEffect(() => {
    if (bodyRef.current && displayMode !== 'raw') {
      const contentHeight = bodyRef.current.scrollHeight;
      setNeedsCollapse(contentHeight > collapsedHeight + 20); // +20 threshold
    }
  }, [children, collapsedHeight, displayMode]);

  // When mode changes, adjust expanded state
  useEffect(() => {
    if (displayMode === 'raw') {
      setExpanded(true);
    }
  }, [displayMode]);

  const toggleExpanded = () => {
    if (displayMode === 'raw') {
      // In raw mode, always allow toggle
      setExpanded(!expanded);
    } else if (needsCollapse) {
      // Allow toggle whenever content is tall enough to collapse
      setExpanded(!expanded);
    }
  };

  // Content is collapsible when it's tall enough OR in raw mode
  const isCollapsible = displayMode === 'raw' || needsCollapse;
  // Apply collapsed state based on user's expanded preference
  const isCollapsed = isCollapsible && !expanded;

  // Determine what content to show based on current mode
  const bodyContent = displayMode === 'raw' && rawData !== undefined
    ? <RawDataDisplay data={rawData} />
    : children;

  const hasRawData = rawData !== undefined;

  return (
    <div className={`turn-card tool-card ${statusClass} ${isActive ? 'streaming' : ''} ${displayMode === 'raw' ? 'raw-mode' : ''} ${className}`}>
      <div
        className={`tool-card-header ${isCollapsible ? 'collapsible-header-clickable' : ''}`}
        onClick={toggleExpanded}
        role={isCollapsible ? 'button' : undefined}
        tabIndex={isCollapsible ? 0 : undefined}
        onKeyDown={isCollapsible ? (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            toggleExpanded();
          }
        } : undefined}
      >
        {order !== undefined && (
          <span className="turn-order">
            {orderEnd !== undefined && orderEnd !== order ? `${order}-${orderEnd}` : order}
          </span>
        )}
        <ToolStatusIcon phase={phase} />
        <span className="tool-card-name">{toolName}</span>
        {displayMode !== 'raw' && headerContent && <div className="tool-card-header-content">{headerContent}</div>}
        {!isActive && tokens > 0 && <span className="tool-card-tokens">{tokens} tokens</span>}
        <ModeSwitcher
          mode={displayMode}
          onModeChange={setDisplayMode}
          hasRawData={hasRawData}
        />
        {isCollapsible && (
          <span className="tool-card-collapse-indicator">
            {expanded ? '▼' : '▶'}
          </span>
        )}
      </div>
      {bodyContent && (
        <div
          ref={bodyRef}
          className={`tool-card-body ${isCollapsed ? 'collapsed' : ''}`}
          style={isCollapsed ? { maxHeight: `${collapsedHeight}px` } : undefined}
        >
          {bodyContent}
          {isCollapsed && <div className="tool-card-fade-overlay" />}
        </div>
      )}
    </div>
  );
}

/**
 * CollapsibleContent - Optional collapsible section for tool output
 *
 * Unlike the old accordion pattern, this:
 * - Has no header label (implicit content)
 * - Defaults to expanded
 * - Only collapses for very long content
 */
export interface CollapsibleContentProps {
  children: React.ReactNode;
  /** Maximum height before showing collapse toggle (default: 300px worth of content) */
  maxLines?: number;
  /** Force collapsed state */
  defaultCollapsed?: boolean;
}

export function CollapsibleContent({
  children,
  maxLines = 20,
  defaultCollapsed = false,
}: CollapsibleContentProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  // For now, simple implementation - can enhance with actual line counting later
  return (
    <div className={`tool-collapsible-content ${collapsed ? 'collapsed' : ''}`}>
      {children}
      {collapsed && (
        <button
          className="tool-expand-button"
          onClick={() => setCollapsed(false)}
          type="button"
        >
          Show more...
        </button>
      )}
    </div>
  );
}

/**
 * Utility: Format file path relative to base (removes common prefix)
 */
export function formatRelativePath(fullPath: string, basePath?: string): string {
  if (!basePath || !fullPath.startsWith(basePath)) {
    // If no base path or doesn't match, just show filename for very long paths
    if (fullPath.length > 60) {
      const parts = fullPath.split('/');
      if (parts.length > 3) {
        return `.../${parts.slice(-2).join('/')}`;
      }
    }
    return fullPath;
  }

  // Remove base path prefix
  let relative = fullPath.slice(basePath.length);
  if (relative.startsWith('/')) {
    relative = relative.slice(1);
  }
  return relative || fullPath;
}

/**
 * Utility: Calculate tool phase from turn state
 */
export function calculateToolPhase(
  streaming: boolean,
  hasInput: boolean,
  isInputStreaming: boolean,
  hasResult: boolean,
  isError: boolean
): ToolPhase {
  if (isError) return 'error';
  if (hasResult) return 'completed';
  if (!streaming) return 'completed';
  if (isInputStreaming) return 'building';
  if (hasInput) return 'executing';
  return 'building';
}

export default BaseToolCard;
