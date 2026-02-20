import React, { memo, useEffect, useState, useRef } from 'react';
import type { TaskInfo } from '../../../../generated/balloons-client';
import './StreamingStatusBar.css';

export interface StreamingStatusBarProps {
  /** Current streaming task info */
  task: TaskInfo;
  /** Number of messages in the queue */
  queuedMessageCount: number;
  /** Callback when stop button is clicked */
  onStop?: () => void;
  /** Whether the stop action is disabled */
  stopDisabled?: boolean;
  /** Session's cached context tokens (running total from session data) */
  sessionContextTokens?: number;
  /** Whether the session is pinned */
  isPinned?: boolean;
  /** Callback when pin state is toggled */
  onTogglePin?: () => void;
}

/**
 * Format duration in seconds to a human-readable string
 */
function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${Math.floor(seconds)}s`;
  }
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}m ${secs}s`;
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
 * Format token rate to a readable string
 */
function formatTokenRate(rate: number): string {
  if (rate < 1) {
    return '<1';
  }
  return String(Math.round(rate));
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
 * Pin icon component for session pinning
 */
function PinIcon({ isPinned }: { isPinned: boolean }) {
  return (
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
  );
}

/**
 * StreamingStatusBar - Enhanced streaming status display
 *
 * Shows:
 * - Model name with streaming indicator
 * - Duration timer
 * - Token count with rate (tokens/sec)
 * - Current tool being executed
 * - Context usage progress bar
 * - Queue count badge
 * - Integrated stop button
 */
export const StreamingStatusBar = memo(function StreamingStatusBar({
  task,
  queuedMessageCount,
  onStop,
  stopDisabled = false,
  sessionContextTokens,
  isPinned = false,
  onTogglePin,
}: StreamingStatusBarProps) {
  // Track duration locally for smoother updates
  const [duration, setDuration] = useState(task.durationSeconds);
  const startTimeRef = useRef<number>(Date.now() - task.durationSeconds * 1000);

  // Update duration every second
  useEffect(() => {
    // Reset start time when task changes
    startTimeRef.current = Date.now() - task.durationSeconds * 1000;
    setDuration(task.durationSeconds);

    const interval = setInterval(() => {
      const elapsed = (Date.now() - startTimeRef.current) / 1000;
      setDuration(elapsed);
    }, 1000);

    return () => clearInterval(interval);
  }, [task.taskId, task.durationSeconds]);

  // Calculate context usage
  // Use session's cached context tokens if available (more accurate during streaming)
  // Fall back to task's input/output tokens (populated at end of streaming from API)
  const totalContextTokens = sessionContextTokens ?? (task.inputTokens + task.outputTokens);
  const contextUsage = task.contextWindow > 0
    ? Math.min(100, (totalContextTokens / task.contextWindow) * 100)
    : 0;
  const contextColorClass = getContextBarColorClass(contextUsage);

  // Determine what to show in the status area
  const isToolRunning = !!task.toolName;
  const hasTokens = task.tokensStreamed > 0;
  const hasRate = task.currentTokenRate > 0;

  return (
    <div className="streaming-status-bar" role="status" aria-live="polite">
      {/* Top row: Model, Duration, Stop */}
      <div className="streaming-status-bar__header">
        <div className="streaming-status-bar__model">
          <span className="streaming-status-bar__indicator" aria-hidden="true" />
          <span className="streaming-status-bar__model-name">
            {task.model || task.backendName || 'Streaming'}
          </span>
        </div>

        <div className="streaming-status-bar__timer">
          {formatDuration(duration)}
        </div>

        {/* Pin toggle button */}
        {onTogglePin && (
          <button
            type="button"
            className={`streaming-status-bar__pin-button ${isPinned ? 'streaming-status-bar__pin-button--active' : ''}`}
            onClick={onTogglePin}
            title={isPinned ? 'Unpin session' : 'Pin session'}
            aria-label={isPinned ? 'Unpin session' : 'Pin session'}
          >
            <PinIcon isPinned={isPinned} />
          </button>
        )}

        {onStop && (
          <button
            type="button"
            className="streaming-status-bar__stop"
            onClick={onStop}
            disabled={stopDisabled}
            aria-label="Stop streaming"
          >
            Stop
          </button>
        )}
      </div>

      {/* Middle row: Tokens/Tool info */}
      <div className="streaming-status-bar__details">
        {isToolRunning ? (
          <div className="streaming-status-bar__tool">
            <span className="streaming-status-bar__tool-icon" aria-hidden="true">
              ⚙
            </span>
            <span className="streaming-status-bar__tool-name">{task.toolName}</span>
            {task.toolCount > 1 && (
              <span className="streaming-status-bar__tool-count">
                ({task.toolCount})
              </span>
            )}
          </div>
        ) : hasTokens ? (
          <div className="streaming-status-bar__tokens">
            <span className="streaming-status-bar__token-count">
              {formatTokens(task.tokensStreamed)} tokens
            </span>
            {hasRate && (
              <span className="streaming-status-bar__token-rate">
                {formatTokenRate(task.currentTokenRate)}/s
              </span>
            )}
          </div>
        ) : (
          <div className="streaming-status-bar__waiting">
            Starting...
          </div>
        )}

        {queuedMessageCount > 0 && (
          <div className="streaming-status-bar__queue-badge">
            {queuedMessageCount} queued
          </div>
        )}
      </div>

      {/* Bottom row: Context usage bar */}
      {task.contextWindow > 0 && (
        <div className="streaming-status-bar__context">
          <div className="streaming-status-bar__context-label">
            <span className="streaming-status-bar__context-text">Context</span>
            <span className="streaming-status-bar__context-values">
              {formatTokens(totalContextTokens)} / {formatTokens(task.contextWindow)}
              <span className="streaming-status-bar__context-percent">
                ({contextUsage.toFixed(0)}%)
              </span>
            </span>
          </div>
          <div className="streaming-status-bar__context-track">
            <div
              className={`streaming-status-bar__context-bar ${contextColorClass}`}
              style={{ width: `${contextUsage}%` }}
              role="progressbar"
              aria-valuenow={contextUsage}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`Context usage: ${contextUsage.toFixed(0)}%`}
            />
          </div>
        </div>
      )}
    </div>
  );
});

export default StreamingStatusBar;
