/**
 * BaseToolCard - Shared structure for all tool-specific cards
 *
 * Provides:
 * - Consistent header with status icon, tool name, and custom content
 * - Status-based styling (executing, completed, error)
 * - Collapsible content - shows first N lines by default, expands on header tap
 * - Token count display
 */

import React, { useState, useRef, useEffect } from 'react';
import './cards.css';

// Tool execution phase
export type ToolPhase = 'building' | 'executing' | 'completed' | 'error';

export interface BaseToolCardProps {
  /** Tool name displayed in header */
  toolName: string;
  /** Custom content for the header (file path, pattern, etc.) */
  headerContent?: React.ReactNode;
  /** Current tool execution phase */
  phase: ToolPhase;
  /** Token count (shown when completed) */
  tokens?: number;
  /** Main body content */
  children?: React.ReactNode;
  /** Additional CSS class */
  className?: string;
  /** Number of lines to show when collapsed (default: 5) */
  collapsedLines?: number;
  /** Start expanded (default: false for completed, true for active) */
  defaultExpanded?: boolean;
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
 * BaseToolCard - Wrapper component for tool-specific cards
 *
 * Content is collapsible - shows first N lines by default (when completed).
 * Tap/click the header to expand/collapse.
 */
export function BaseToolCard({
  toolName,
  headerContent,
  phase,
  tokens = 0,
  children,
  className = '',
  collapsedLines = 5,
  defaultExpanded,
}: BaseToolCardProps) {
  const isActive = phase === 'building' || phase === 'executing';
  const statusClass = phase === 'error' ? 'error' : isActive ? 'executing' : 'completed';

  // Active states are always expanded; completed states collapse by default
  const [expanded, setExpanded] = useState(defaultExpanded ?? isActive);
  const [needsCollapse, setNeedsCollapse] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  // Calculate if content is tall enough to need collapsing
  // Using line-height of ~18px (11px font * 1.4 line-height + padding)
  const collapsedHeight = collapsedLines * 18 + 12; // +12 for padding

  useEffect(() => {
    if (bodyRef.current && !isActive) {
      const contentHeight = bodyRef.current.scrollHeight;
      setNeedsCollapse(contentHeight > collapsedHeight + 20); // +20 threshold
    }
  }, [children, collapsedHeight, isActive]);

  // Keep expanded while active
  useEffect(() => {
    if (isActive) {
      setExpanded(true);
    }
  }, [isActive]);

  const toggleExpanded = () => {
    if (!isActive && needsCollapse) {
      setExpanded(!expanded);
    }
  };

  const isCollapsible = !isActive && needsCollapse;
  const isCollapsed = isCollapsible && !expanded;

  return (
    <div className={`turn-card tool-card ${statusClass} ${isActive ? 'streaming' : ''} ${className}`}>
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
        <ToolStatusIcon phase={phase} />
        <span className="tool-card-name">{toolName}</span>
        {headerContent && <div className="tool-card-header-content">{headerContent}</div>}
        {!isActive && tokens > 0 && <span className="tool-card-tokens">{tokens} tokens</span>}
        {isCollapsible && (
          <span className="tool-card-collapse-indicator">
            {expanded ? '▼' : '▶'}
          </span>
        )}
      </div>
      {children && (
        <div
          ref={bodyRef}
          className={`tool-card-body ${isCollapsed ? 'collapsed' : ''}`}
          style={isCollapsed ? { maxHeight: `${collapsedHeight}px` } : undefined}
        >
          {children}
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
