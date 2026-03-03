/**
 * LLMTab - Monitor and manage active LLM streams
 *
 * Shows:
 * - Active streams (streaming, executing, pending)
 * - Recent completed/failed/cancelled streams
 * - Token rates and counts
 * - Tool execution status
 *
 * Features:
 * - Real-time event-driven updates (no polling)
 * - Cancel active streams
 * - Jump to session
 *
 * URL ROUTING: This is a global tab at #/llm
 * - Task selection could use #/llm/:taskId
 * - "Jump to session" should navigate to #/sessions/:sessionId
 * - See docs/url-routing.md for the full routing design
 */

import React, { useState, useCallback, useEffect, memo } from 'react';
import type { TaskInfo, TaskEventData, BackendSummary } from '../../../../generated/types';
import type { TaskStateServiceClient } from '../../../../generated/client';
import './LLMTab.css';

// Status indicator component
function StatusIndicator({ status }: { status: string }) {
  const statusConfig: Record<string, { icon: string; className: string; label: string }> = {
    pending: { icon: '⏳', className: 'status--pending', label: 'Pending' },
    streaming: { icon: '🟢', className: 'status--streaming', label: 'Streaming' },
    executing: { icon: '🔧', className: 'status--executing', label: 'Executing Tool' },
    completed: { icon: '✓', className: 'status--completed', label: 'Completed' },
    error: { icon: '✗', className: 'status--error', label: 'Error' },
    cancelled: { icon: '⊘', className: 'status--cancelled', label: 'Cancelled' },
  };

  const fallback = { icon: '⚪', className: 'status--unknown', label: 'Unknown' };
  const config = statusConfig[status || 'unknown'] || fallback;

  return (
    <span className={`llm-status ${config.className}`} title={config.label}>
      {config.icon}
    </span>
  );
}

// Task type badge
function TaskTypeBadge({ taskType }: { taskType: string }) {
  const typeLabels: Record<string, string> = {
    chat: 'CHAT',
    compression: 'COMPRESS',
    merge: 'MERGE',
    link: 'LINK',
    archive: 'ARCHIVE',
    title: 'TITLE',
    report: 'REPORT',
    session_review: 'REVIEW',
  };

  const label = typeLabels[taskType] || taskType.toUpperCase();

  return <span className={`llm-type-badge llm-type-badge--${taskType}`}>{label}</span>;
}

// Format token rate with sparkline-like bar
function TokenRate({ rate }: { rate: number }) {
  if (rate <= 0) return null;

  // Simple rate bar visualization
  const maxRate = 100; // tokens/sec baseline
  const fillPct = Math.min(100, (rate / maxRate) * 100);

  return (
    <span className="llm-token-rate">
      <span className="llm-token-rate__bar">
        <span className="llm-token-rate__fill" style={{ width: `${fillPct}%` }} />
      </span>
      <span className="llm-token-rate__value">{Math.round(rate)} tok/s</span>
    </span>
  );
}

// Format duration
function formatDuration(seconds: number): string {
  if (seconds < 1) return '<1s';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m${secs}s`;
}

// Format token count
function formatTokens(count: number): string {
  if (count < 1000) return String(count);
  if (count < 10000) return `${(count / 1000).toFixed(1)}k`;
  return `${Math.round(count / 1000)}k`;
}

// Active stream card
const ActiveStreamCard = memo(function ActiveStreamCard({
  task,
  onCancel,
  onJumpToSession,
}: {
  task: TaskInfo;
  onCancel: (taskId: string) => void;
  onJumpToSession?: (sessionId: string) => void;
}) {
  const isExecuting = task.status === 'executing';

  return (
    <div className={`llm-stream-card llm-stream-card--${task.status}`}>
      <div className="llm-stream-card__header">
        <StatusIndicator status={task.status} />
        <TaskTypeBadge taskType={task.taskType} />
        {task.model && <span className="llm-stream-card__model">{task.model}</span>}
        <TokenRate rate={task.currentTokenRate} />
      </div>

      <div className="llm-stream-card__details">
        {task.sessionId && (
          <span
            className="llm-stream-card__session"
            onClick={() => onJumpToSession?.(task.sessionId!)}
            title="Jump to session"
          >
            {task.sessionId.slice(0, 8)}
          </span>
        )}
        <span className="llm-stream-card__tokens">
          {formatTokens(task.inputTokens)}↓ {formatTokens(task.outputTokens)}↑
        </span>
        <span className="llm-stream-card__duration">{formatDuration(task.durationSeconds)}</span>
      </div>

      {isExecuting && task.toolName && (
        <div className="llm-stream-card__tool">
          <span className="llm-stream-card__tool-icon">🔧</span>
          <span className="llm-stream-card__tool-name">{task.toolName}</span>
          {task.toolCount > 1 && (
            <span className="llm-stream-card__tool-count">#{task.toolCount}</span>
          )}
        </div>
      )}

      {task.prompt && (
        <div className="llm-stream-card__prompt" title={task.prompt}>
          {task.prompt}
        </div>
      )}

      <div className="llm-stream-card__actions">
        <button
          className="llm-action llm-action--cancel"
          onClick={(e) => {
            e.stopPropagation();
            onCancel(task.taskId);
          }}
          title="Cancel stream"
        >
          Cancel
        </button>
      </div>
    </div>
  );
});

// Recent stream card (compact)
const RecentStreamCard = memo(function RecentStreamCard({
  task,
  onJumpToSession,
}: {
  task: TaskInfo;
  onJumpToSession?: (sessionId: string) => void;
}) {
  return (
    <div className={`llm-recent-card llm-recent-card--${task.status}`}>
      <StatusIndicator status={task.status} />
      <TaskTypeBadge taskType={task.taskType} />
      <span className="llm-recent-card__duration">{formatDuration(task.durationSeconds)}</span>
      <span className="llm-recent-card__tokens">
        {formatTokens(task.inputTokens)}↓ {formatTokens(task.outputTokens)}↑
      </span>
      {task.error && (
        <span className="llm-recent-card__error" title={task.error}>
          {task.error.slice(0, 30)}
          {task.error.length > 30 ? '...' : ''}
        </span>
      )}
      {task.sessionId && (
        <span
          className="llm-recent-card__session"
          onClick={() => onJumpToSession?.(task.sessionId!)}
          title="Jump to session"
        >
          {task.sessionId.slice(0, 8)}
        </span>
      )}
    </div>
  );
});

// Backend summary
function BackendSummaryView({ summaries }: { summaries: BackendSummary[] }) {
  if (summaries.length === 0) return null;

  return (
    <div className="llm-backend-summary">
      {summaries.map((s) => (
        <span key={s.backendName} className="llm-backend-summary__item">
          <span className="llm-backend-summary__name">{s.backendName}</span>
          <span className="llm-backend-summary__count">({s.activeCount})</span>
        </span>
      ))}
    </div>
  );
}

// Main component props
export interface LLMTabProps {
  /** Task state service client */
  tasksClient?: TaskStateServiceClient;
  /** Callback to jump to a session */
  onJumpToSession?: (sessionId: string) => void;
}

export function LLMTab({ tasksClient, onJumpToSession }: LLMTabProps) {
  const [activeTasks, setActiveTasks] = useState<TaskInfo[]>([]);
  const [recentTasks, setRecentTasks] = useState<TaskInfo[]>([]);
  const [backendSummary, setBackendSummary] = useState<BackendSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Load initial state
  const loadState = useCallback(async () => {
    if (!tasksClient) return;

    console.log('[LLMTab] Loading initial state...');

    try {
      const [allTasks, summary] = await Promise.all([
        tasksClient.getAllTasks(),
        tasksClient.getBackendSummary(),
      ]);

      console.log('[LLMTab] getAllTasks result:', allTasks);
      console.log('[LLMTab] getBackendSummary result:', summary);

      // Split into active and recent
      const active = allTasks.filter((t) => t.isActive);
      const recent = allTasks.filter((t) => !t.isActive).slice(0, 10);

      console.log('[LLMTab] Active tasks:', active.length, 'Recent tasks:', recent.length);

      setActiveTasks(active);
      setRecentTasks(recent);
      setBackendSummary(summary);
      setError(null);
    } catch (e) {
      console.error('[LLMTab] Error loading state:', e);
      setError(e instanceof Error ? e.message : 'Failed to load LLM streams');
    }
  }, [tasksClient]);

  // Initial load
  useEffect(() => {
    loadState();
  }, [loadState]);

  // Subscribe to events
  useEffect(() => {
    if (!tasksClient) return;

    console.log('[LLMTab] Subscribing to task events');

    const unsubs: Array<() => void> = [];

    // Task started - add to active
    unsubs.push(
      tasksClient.onTaskStarted((event: TaskEventData) => {
        console.log('[LLMTab] taskStarted event:', event);
        // Fetch full task info
        tasksClient.getTask(event.taskId).then((task) => {
          console.log('[LLMTab] getTask result:', task);
          if (task) {
            setActiveTasks((prev) => [task, ...prev]);
          }
        });
        // Update backend summary
        tasksClient.getBackendSummary().then(setBackendSummary);
      })
    );

    // Task updated - update in active list
    unsubs.push(
      tasksClient.onTaskUpdated((event: TaskEventData) => {
        console.log('[LLMTab] taskUpdated event:', event);
        tasksClient.getTask(event.taskId).then((task) => {
          if (task) {
            setActiveTasks((prev) =>
              prev.map((t) => (t.taskId === event.taskId ? task : t))
            );
          }
        });
      })
    );

    // Task completed - move from active to recent
    unsubs.push(
      tasksClient.onTaskCompleted((event: TaskEventData) => {
        console.log('[LLMTab] taskCompleted event:', event);
        tasksClient.getTask(event.taskId).then((task) => {
          setActiveTasks((prev) => prev.filter((t) => t.taskId !== event.taskId));
          if (task) {
            setRecentTasks((prev) => [task, ...prev].slice(0, 10));
          }
        });
        tasksClient.getBackendSummary().then(setBackendSummary);
      })
    );

    // Task error - move to recent
    unsubs.push(
      tasksClient.onTaskError((event: TaskEventData) => {
        tasksClient.getTask(event.taskId).then((task) => {
          setActiveTasks((prev) => prev.filter((t) => t.taskId !== event.taskId));
          if (task) {
            setRecentTasks((prev) => [task, ...prev].slice(0, 10));
          }
        });
        tasksClient.getBackendSummary().then(setBackendSummary);
      })
    );

    // Task cancelled - move to recent
    unsubs.push(
      tasksClient.onTaskCancelled((event: TaskEventData) => {
        tasksClient.getTask(event.taskId).then((task) => {
          setActiveTasks((prev) => prev.filter((t) => t.taskId !== event.taskId));
          if (task) {
            setRecentTasks((prev) => [task, ...prev].slice(0, 10));
          }
        });
        tasksClient.getBackendSummary().then(setBackendSummary);
      })
    );

    return () => {
      unsubs.forEach((unsub) => unsub());
    };
  }, [tasksClient]);

  // Cancel a task
  const handleCancel = useCallback(
    async (taskId: string) => {
      if (!tasksClient) return;
      try {
        await tasksClient.cancelTask(taskId);
      } catch (e) {
        console.error('Failed to cancel task:', e);
      }
    },
    [tasksClient]
  );

  // Error state
  if (error) {
    return (
      <div className="llm-tab llm-tab--error">
        <div className="llm-error">
          <span className="llm-error__icon">⚠️</span>
          <span className="llm-error__message">{error}</span>
        </div>
      </div>
    );
  }

  const activeCount = activeTasks.length;

  return (
    <div className="llm-tab">
      {/* Header */}
      <div className="llm-tab__header">
        <h2>
          LLM Streams
          {activeCount > 0 && (
            <span className="llm-tab__active-count">
              {activeCount} <span className="llm-tab__active-dot">●</span>
            </span>
          )}
        </h2>
        <BackendSummaryView summaries={backendSummary} />
      </div>

      {/* Active streams */}
      <section className="llm-section">
        <div className="llm-section__header">
          <span className="llm-section__title">Active</span>
          {activeCount === 0 && <span className="llm-section__empty">No active streams</span>}
        </div>
        {activeCount > 0 && (
          <div className="llm-active-list">
            {activeTasks.map((task) => (
              <ActiveStreamCard
                key={task.taskId}
                task={task}
                onCancel={handleCancel}
                onJumpToSession={onJumpToSession}
              />
            ))}
          </div>
        )}
      </section>

      {/* Recent streams */}
      {recentTasks.length > 0 && (
        <section className="llm-section">
          <div className="llm-section__header">
            <span className="llm-section__title">Recent</span>
          </div>
          <div className="llm-recent-list">
            {recentTasks.map((task) => (
              <RecentStreamCard
                key={task.taskId}
                task={task}
                onJumpToSession={onJumpToSession}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export default LLMTab;
