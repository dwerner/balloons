import React, { memo, useState, useEffect, useCallback } from 'react';
import type { SessionInfo, BalloonsClient } from '../../../../generated/balloons-client';
import './SessionStatusBar.css';

export interface SessionStatusBarProps {
  /** Current session info */
  session: SessionInfo;
  /** Whether the session is actively streaming (from useSessionData) */
  isStreaming?: boolean;
  /** Balloons client for backend operations */
  client?: BalloonsClient | null;
  /** Callback when backend is changed */
  onBackendChange?: (backendName: string) => void;
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
 * - Model name with streaming indicator
 * - Backend selector dropdown
 * - Context usage progress bar (always visible)
 *
 * This bar is always shown when a session is selected,
 * regardless of streaming state.
 */
export const SessionStatusBar = memo(function SessionStatusBar({
  session,
  isStreaming = false,
  client,
  onBackendChange,
}: SessionStatusBarProps) {
  const contextTokens = session.cachedContextTokens ?? 0;
  const contextWindow = session.contextWindow ?? 200000;

  const contextUsage = contextWindow > 0
    ? Math.min(100, (contextTokens / contextWindow) * 100)
    : 0;
  const contextColorClass = getContextBarColorClass(contextUsage);

  const modelDisplay = getModelDisplayName(session.model);

  // Backend selector state
  const [backends, setBackends] = useState<string[]>([]);
  const [selectedBackend, setSelectedBackend] = useState<string>(session.backendName || '');
  const [isChangingBackend, setIsChangingBackend] = useState(false);
  const [showBackendSelector, setShowBackendSelector] = useState(false);

  // Load available backends
  useEffect(() => {
    if (client && client.isConnected) {
      client.sessions.listBackends()
        .then(setBackends)
        .catch(err => console.error('Failed to load backends:', err));
    }
  }, [client]);

  // Update selected backend when session changes
  // If session has no explicit backend, fetch the effective one (including default)
  useEffect(() => {
    if (session.backendName) {
      setSelectedBackend(session.backendName);
    } else if (client && client.isConnected) {
      // Fetch effective backend (which includes the default backend name)
      client.sessions.getSessionBackend(session.id)
        .then(backend => {
          if (backend) setSelectedBackend(backend);
        })
        .catch(err => console.error('Failed to get session backend:', err));
    }
  }, [session.backendName, session.id, client]);

  // Handle backend change
  const handleBackendChange = useCallback(async (newBackend: string) => {
    if (!client || isStreaming || newBackend === selectedBackend) {
      return;
    }

    setIsChangingBackend(true);
    try {
      const success = await client.sessions.setSessionBackend(session.id, newBackend);
      if (success) {
        setSelectedBackend(newBackend);
        onBackendChange?.(newBackend);
      }
    } catch (err) {
      console.error('Failed to change backend:', err);
    } finally {
      setIsChangingBackend(false);
      setShowBackendSelector(false);
    }
  }, [client, isStreaming, selectedBackend, session.id, onBackendChange]);

  return (
    <div className="session-status-bar" role="status">
      {/* Model and context info */}
      <div className="session-status-bar__header">
        <div className="session-status-bar__model-section">
          {/* Streaming indicator */}
          {isStreaming && (
            <span
              className="session-status-bar__streaming-indicator"
              aria-label="Streaming active"
              title="Streaming active"
            />
          )}

          {/* Model/Backend display with dropdown */}
          <div className="session-status-bar__backend-container">
            <button
              type="button"
              className={`session-status-bar__model ${backends.length > 1 ? 'session-status-bar__model--clickable' : ''}`}
              onClick={() => backends.length > 1 && !isStreaming && setShowBackendSelector(!showBackendSelector)}
              disabled={isStreaming || backends.length <= 1}
              title={backends.length > 1 ? 'Click to change backend' : modelDisplay}
            >
              {selectedBackend || modelDisplay}
              {backends.length > 1 && !isStreaming && (
                <span className="session-status-bar__dropdown-arrow">
                  {showBackendSelector ? '▼' : '▲'}
                </span>
              )}
            </button>

            {/* Backend dropdown */}
            {showBackendSelector && backends.length > 1 && (
              <div className="session-status-bar__backend-dropdown">
                {backends.map(backend => (
                  <button
                    key={backend}
                    type="button"
                    className={`session-status-bar__backend-option ${backend === selectedBackend ? 'session-status-bar__backend-option--selected' : ''}`}
                    onClick={() => handleBackendChange(backend)}
                    disabled={isChangingBackend}
                  >
                    {backend}
                    {backend === selectedBackend && ' ✓'}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

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
