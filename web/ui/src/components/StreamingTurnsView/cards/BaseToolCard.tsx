/**
 * BaseToolCard - Shared structure for all tool-specific cards
 *
 * Provides:
 * - Consistent header with status icon, tool name, and custom content
 * - Status-based styling (executing, completed, error)
 * - Optional collapsible content areas
 * - Token count display
 */

import React, { useState } from 'react';
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
 */
export function BaseToolCard({
  toolName,
  headerContent,
  phase,
  tokens = 0,
  children,
  className = '',
}: BaseToolCardProps) {
  const isActive = phase === 'building' || phase === 'executing';
  const statusClass = phase === 'error' ? 'error' : isActive ? 'executing' : 'completed';

  return (
    <div className={`turn-card tool-card ${statusClass} ${isActive ? 'streaming' : ''} ${className}`}>
      <div className="tool-card-header">
        <ToolStatusIcon phase={phase} />
        <span className="tool-card-name">{toolName}</span>
        {headerContent && <div className="tool-card-header-content">{headerContent}</div>}
        {!isActive && tokens > 0 && <span className="tool-card-tokens">{tokens} tokens</span>}
      </div>
      {children && <div className="tool-card-body">{children}</div>}
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
