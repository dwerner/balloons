import React, { memo } from 'react';
import type { SessionInfo } from '../../../../generated/balloons-client';
import './SessionStatusBar.css';

export interface SessionStatusBarProps {
  /** Current session info */
  session: SessionInfo;
}

/**
 * Format token count with thousands separator
 */
function formatTokens(count: number): string {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k`;
  }
  return String(count);
}

/**
 * Get context bar color class based on usage percentage
 */
function getContextBarColorClass(percentage: number): string {
  if (percentage >= 90) return 'context-bar--critical';
  if (percentage >= 75) return 'context-bar--warning';
  if (percentage >= 50) return 'context-bar--moderate';
  return 'context-bar--healthy';
}

/**
 * Extract a display name from the model identifier
 */
function getModelDisplayName(model: string | undefined): string {
  // Return "Context" as label when no model is set
  if (!model) return 'Context';

  if (model.startsWith('claude-')) {
    // Claude models: "claude-opus-4-5-20251101" -> "opus-4.5"
    const parts = model.split('-');
    if (parts.length >= 3) {
      const variant = parts[1] ?? '';  // e.g., "opus"
      const part2 = parts[2] ?? '';
      const part3 = parts[3] ?? '';
      // Try to get version like "4.5" from "4-5"
      if (parts.length >= 4 && /^\d+$/.test(part2) && /^\d+$/.test(part3)) {
        return `${variant}-${part2}.${part3}`;
      }
      return variant || model.split('-')[0] || 'Context';
    }
    return model.split('-')[0] ?? 'Context';
  }

  // Other models: return first part
  return model.split('-')[0] ?? 'Context';
}

/**
 * SessionStatusBar - Persistent session status display
 *
 * Shows:
 * - Model name
 * - Context usage progress bar (always visible)
 *
 * This bar is always shown when a session is selected,
 * regardless of streaming state.
 */
export const SessionStatusBar = memo(function SessionStatusBar({
  session,
}: SessionStatusBarProps) {
  const contextTokens = session.cachedContextTokens ?? 0;
  const contextWindow = session.contextWindow ?? 200000;

  const contextUsage = contextWindow > 0
    ? Math.min(100, (contextTokens / contextWindow) * 100)
    : 0;
  const contextColorClass = getContextBarColorClass(contextUsage);

  const modelDisplay = getModelDisplayName(session.model);

  return (
    <div className="session-status-bar" role="status">
      {/* Model and context info */}
      <div className="session-status-bar__header">
        <span className="session-status-bar__model">
          {modelDisplay}
        </span>
        <span className="session-status-bar__context-values">
          {formatTokens(contextTokens)} / {formatTokens(contextWindow)}
          <span className="session-status-bar__context-percent">
            ({contextUsage.toFixed(0)}%)
          </span>
        </span>
      </div>

      {/* Context usage bar */}
      <div className="session-status-bar__context-track">
        <div
          className={`session-status-bar__context-bar ${contextColorClass}`}
          style={{ width: `${contextUsage}%` }}
          role="progressbar"
          aria-valuenow={contextUsage}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Context usage: ${contextUsage.toFixed(0)}%`}
        />
      </div>
    </div>
  );
});

export default SessionStatusBar;
