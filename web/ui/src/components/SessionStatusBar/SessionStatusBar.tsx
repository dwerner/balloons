import React, { memo, useState, useEffect, useCallback, useMemo } from 'react';
import type { SessionInfo, BalloonsClient } from '../../../../generated/balloons-client';
import { useLongPress, useNotifications } from '../../hooks';
import { useLayout } from '../layout';
import { usePreferences } from '../layout/PreferencesContext';
import { RenameSessionModal } from '../RenameSessionModal';
import { getModelColor } from '../../utils';
import { createLogger } from '../../utils/debugLog';
import './SessionStatusBar.css';

const debugLog = createLogger('SessionStatusBar');

export interface SessionStatusBarProps {
  /** Current session info */
  session: SessionInfo;
  /** Whether the session is actively streaming (from useSessionData) */
  isStreaming?: boolean;
  /** Live context token count from turn data - more accurate than session.cachedContextTokens */
  liveContextTokens?: number;
  /** Balloons client for backend operations */
  client?: BalloonsClient | null;
  /** Callback when backend is changed */
  onBackendChange?: (backendName: string) => void;
  /** Callback when pin state is toggled */
  onTogglePin?: () => void;
  /** Callback when session title is changed */
  onTitleChange?: (newTitle: string) => void;
  /** Callback when user wants to select/navigate to a different session */
  onSelectSession?: (sessionId: string) => void;
  /** Scroll state from chat view */
  scrollState?: { isFollowing: boolean; isAtBottom: boolean };
  /** Current working directory for the session */
  cwd?: string;
  /** Callback when CWD is clicked - opens file browser at that path */
  onCwdClick?: (cwd: string) => void;
  /** Callback to set CWD when none is set - opens file browser for selection */
  onSetCwd?: () => void;
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
 * Bell icon component for notifications toggle
 */
function BellIcon({ enabled, muted }: { enabled: boolean; muted?: boolean }) {
  // Bell with optional slash for muted state
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill={enabled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
      {muted && <path d="M2 2l20 20" strokeWidth="2.5" />}
    </svg>
  );
}

/**
 * Get session display name (title, forkName, or fallback to short ID)
 */
function getSessionDisplayName(session: SessionInfo): string {
  return session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
}

/**
 * Format CWD for display - show abbreviated path
 * e.g., "/home/dan/Development/balloons" -> "~/Development/balloons"
 */
function formatCwd(cwd: string | undefined, homePath?: string): string {
  if (!cwd) return '';

  // Replace home directory with ~
  if (homePath && cwd.startsWith(homePath)) {
    cwd = '~' + cwd.slice(homePath.length);
  }

  return cwd;
}

export const SessionStatusBar = memo(function SessionStatusBar({
  session,
  isStreaming = false,
  liveContextTokens,
  client,
  onBackendChange,
  onTogglePin,
  onTitleChange,
  onSelectSession,
  scrollState,
  cwd,
  onCwdClick,
  onSetCwd,
}: SessionStatusBarProps) {
  const { expandDetail } = useLayout();
  const { expandToolCards, togglePreference } = usePreferences();
  // Prefer live token count from turns when available, fall back to cached session value
  const contextTokens = (liveContextTokens !== undefined && liveContextTokens > 0)
    ? liveContextTokens
    : (session.cachedContextTokens ?? 0);
  const contextWindow = session.contextWindow ?? 150000;

  const contextUsage = contextWindow > 0
    ? Math.min(100, (contextTokens / contextWindow) * 100)
    : 0;
  const contextColorClass = getContextBarColorClass(contextUsage);

  const modelDisplay = getModelDisplayName(session.model);
  const isPinned = session.isPinned ?? false;
  const sessionName = getSessionDisplayName(session);

  // Get model-specific color for the streaming indicator
  const modelColor = useMemo(
    () => getModelColor(session.model, session.backendName),
    [session.model, session.backendName]
  );

  // Notifications hook for per-session notifications
  const {
    notificationsEnabled,
    toggleNotifications,
    permissionState,
    showNotification,
  } = useNotifications(session.id, client);

  // Collapsed state - persist in localStorage
  const [isCollapsed, setIsCollapsed] = useState(() => {
    const stored = localStorage.getItem('sessionStatusBar.collapsed');
    return stored === 'true';
  });

  const toggleCollapsed = useCallback(() => {
    setIsCollapsed(prev => {
      const next = !prev;
      localStorage.setItem('sessionStatusBar.collapsed', String(next));
      return next;
    });
  }, []);

  // Backend selector state
  const [backends, setBackends] = useState<string[]>([]);
  const [inlineNotification, setInlineNotification] = useState<string | null>(null);
  const [selectedBackend, setSelectedBackend] = useState<string>(session.backendName || '');
  const [isChangingBackend, setIsChangingBackend] = useState(false);
  const [showBackendSelector, setShowBackendSelector] = useState(false);

  // Rename modal state
  const [showRenameModal, setShowRenameModal] = useState(false);

  // Track connection state for dependency
  const isConnected = client?.isConnected ?? false;

  // Long press handler for session title
  const titleLongPress = useLongPress({
    onLongPress: () => {
      if (client?.isConnected) {
        setShowRenameModal(true);
      }
    },
    delay: 500,
  });

  // Long press handler for working directory - long press opens file browser
  const cwdLongPress = useLongPress({
    onLongPress: () => {
      if (cwd && onCwdClick) {
        expandDetail();
        onCwdClick(cwd);
      }
    },
    onClick: () => {
      // Regular click copies to clipboard
      if (cwd) {
        navigator.clipboard.writeText(cwd);
      }
    },
    delay: 500,
  });

  // Handle rename completion
  const handleRenamed = useCallback((newTitle: string) => {
    onTitleChange?.(newTitle);
  }, [onTitleChange]);

  // Memoized handler for closing rename modal to prevent re-renders
  const handleCloseRenameModal = useCallback(() => {
    setShowRenameModal(false);
  }, []);

  // Load available backends
  useEffect(() => {
    if (client && isConnected) {
      client.sessions.listBackends()
        .then(backends => {
          debugLog('Loaded backends:', backends);
          setBackends(backends);
        })
        .catch(err => debugLog('Failed to load backends', { sessionId: session.id, error: String(err) }));
    }
  }, [client, isConnected]);

  // Update selected backend when session changes
  // If session has no explicit backend, fetch the effective one (including default)
  useEffect(() => {
    if (session.backendName) {
      setSelectedBackend(session.backendName);
    } else if (client && isConnected) {
      // Fetch effective backend (which includes the default backend name)
      client.sessions.getSessionBackend(session.id)
        .then(backend => {
          if (backend) setSelectedBackend(backend);
        })
        .catch(err => debugLog('Failed to get session backend', { sessionId: session.id, error: String(err) }));
    }
  }, [session.backendName, session.id, client, isConnected]);

  // Handle backend change
  const handleBackendChange = useCallback(async (newBackend: string) => {
    if (!client || !client.isConnected) {
      debugLog('Cannot change backend: client not connected', { sessionId: session.id });
      return;
    }
    if (isStreaming) {
      debugLog('Cannot change backend: session is streaming', { sessionId: session.id });
      return;
    }
    if (newBackend === selectedBackend) {
      debugLog('Backend already selected', { sessionId: session.id, backend: newBackend });
      setShowBackendSelector(false);
      return;
    }

    setIsChangingBackend(true);
    try {
      debugLog('Changing backend', { sessionId: session.id, from: selectedBackend, to: newBackend });
      const success = await client.sessions.setSessionBackend(session.id, newBackend);
      debugLog('setSessionBackend result', { sessionId: session.id, success });
      if (success) {
        setSelectedBackend(newBackend);
        onBackendChange?.(newBackend);
        debugLog('Changed backend successfully', { sessionId: session.id, backend: newBackend });
      } else {
        debugLog('Backend change failed - server returned false', { sessionId: session.id, backend: newBackend });
        setInlineNotification('Backend change failed');
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      debugLog('Failed to change backend', { sessionId: session.id, backend: newBackend, error: errorMessage });
      setInlineNotification(`Backend change failed: ${errorMessage}`);
      showNotification(
        'Backend Change Failed',
        errorMessage,
        { tag: `backend-change-${session.id}`, requireInteraction: true }
      );
    } finally {
      setIsChangingBackend(false);
      setShowBackendSelector(false);
    }
  }, [client, isStreaming, selectedBackend, session.id, onBackendChange]);

  return (
    <>
    <div className={`session-status-bar ${isCollapsed ? 'session-status-bar--collapsed' : ''}`} role="status">
      {/* Inline notification gutter */}
      {inlineNotification && (
        <div className="session-status-bar__notification-gutter" aria-live="polite">
          <span className="session-status-bar__notification-gutter-icon">⚠</span>
          <span className="session-status-bar__notification-gutter-text">{inlineNotification}</span>
        </div>
      )}

      {/* Collapsed view: toggle + minimal progress bar */}
      {isCollapsed ? (
        <div className="session-status-bar__collapsed-view">
          <button
            type="button"
            className="session-status-bar__toggle"
            onClick={toggleCollapsed}
            title="Expand status bar"
            aria-label="Expand status bar"
            aria-expanded={false}
          >
            <span className="session-status-bar__toggle-icon">▲</span>
          </button>
          <div className="session-status-bar__mini-track">
            <div
              className={`session-status-bar__mini-bar ${contextColorClass}`}
              style={{ width: `${contextUsage}%` }}
              role="progressbar"
              aria-valuenow={contextUsage}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`Context usage: ${contextUsage.toFixed(0)}%`}
            />
          </div>
        </div>
      ) : (
        <>
          {/* Row 1: Session identity + actions */}
          <div className="session-status-bar__row">
            <button
              type="button"
              className="session-status-bar__toggle"
              onClick={toggleCollapsed}
              title="Collapse status bar"
              aria-label="Collapse status bar"
              aria-expanded={true}
            >
              <span className="session-status-bar__toggle-icon">▼</span>
            </button>
            <div
              className="session-status-bar__title-content"
              title="Long press to rename session"
              {...titleLongPress}
            >
              <span className="session-status-bar__session-title">{sessionName}</span>
              {/* Only show ID separately if we have a real name (not the fallback) */}
              {(session.forkName || session.title) && (
                <span className="session-status-bar__session-id">{session.id.slice(0, 8)}</span>
              )}
            </div>
            {/* Pin toggle button - right after session name */}
            {onTogglePin && (
              <button
                type="button"
                className={`session-status-bar__pin-button ${isPinned ? 'session-status-bar__pin-button--active' : ''}`}
                onClick={onTogglePin}
                title={isPinned ? 'Unpin session' : 'Pin session'}
                aria-label={isPinned ? 'Unpin session' : 'Pin session'}
              >
                <PinIcon isPinned={isPinned} />
              </button>
            )}
            {/* Notification toggle button */}
            <button
              type="button"
              className={`session-status-bar__bell-button ${notificationsEnabled ? 'session-status-bar__bell-button--active' : ''} ${permissionState === 'denied' ? 'session-status-bar__bell-button--denied' : ''}`}
              onClick={toggleNotifications}
              title={
                permissionState === 'denied'
                  ? 'Notifications blocked by browser'
                  : permissionState === 'unsupported'
                  ? 'Notifications not supported'
                  : notificationsEnabled
                  ? 'Disable notifications for this session'
                  : 'Enable notifications for this session'
              }
              aria-label={notificationsEnabled ? 'Disable notifications' : 'Enable notifications'}
              disabled={permissionState === 'denied' || permissionState === 'unsupported'}
            >
              <BellIcon enabled={notificationsEnabled} muted={permissionState === 'denied'} />
            </button>
            {cwd ? (
              <div
                className={`session-status-bar__cwd ${onCwdClick ? 'session-status-bar__cwd--clickable' : ''}`}
                title={onCwdClick ? `${cwd}\n(Tap to copy, long-press to open in file browser)` : `${cwd}\n(Tap to copy)`}
                {...cwdLongPress}
              >
                <span className="session-status-bar__cwd-icon">📁</span>
                <span className="session-status-bar__cwd-path">{formatCwd(cwd)}</span>
              </div>
            ) : onSetCwd && (
              <button
                type="button"
                className="session-status-bar__cwd session-status-bar__cwd--unset"
                title="Set working directory for this session"
                onClick={() => {
                  expandDetail();
                  onSetCwd();
                }}
              >
                <span className="session-status-bar__cwd-icon">📁</span>
                <span className="session-status-bar__cwd-path">Set folder...</span>
              </button>
            )}
            {/* Spacer to push actions to the right */}
            <div className="session-status-bar__spacer" />
            {/* Expand tool cards toggle */}
            <button
              type="button"
              className={`session-status-bar__expand-toggle ${expandToolCards ? 'active' : ''}`}
              onClick={() => togglePreference('expandToolCards')}
              title={expandToolCards ? 'Tool cards: expanded (click to collapse)' : 'Tool cards: collapsed (click to expand)'}
              aria-label={expandToolCards ? 'Collapse tool cards by default' : 'Expand tool cards by default'}
            >
              {expandToolCards ? '▼' : '▶'}
            </button>
            {/* Scroll state indicator */}
            {scrollState && !scrollState.isFollowing && (
              <div
                className="session-status-bar__scroll-state paused"
                title="Auto-scroll: PAUSED (scrolled up)"
              >
                ⏸
              </div>
            )}
          </div>

          {/* Row 2: Model/backend + context bar + tokens */}
          <div className="session-status-bar__row">
            <div className="session-status-bar__model-section">
              {/* Streaming indicator */}
              {isStreaming && (
                <span
                  className="session-status-bar__streaming-indicator"
                  style={{ background: modelColor }}
                  aria-label="Streaming active"
                  title="Streaming active"
                />
              )}

              {/* Model/Backend display with dropdown */}
              <div className="session-status-bar__backend-container">
                <button
                  type="button"
                  className={`session-status-bar__model ${backends.length > 1 ? 'session-status-bar__model--clickable' : ''} ${showBackendSelector ? 'session-status-bar__model--open' : ''}`}
                  onClick={() => backends.length > 1 && !isStreaming && setShowBackendSelector(!showBackendSelector)}
                  disabled={isStreaming || backends.length <= 1}
                  title={backends.length > 1 ? 'Click to change backend' : modelDisplay}
                  aria-expanded={showBackendSelector}
                  aria-haspopup="listbox"
                >
                  <span
                    className="session-status-bar__backend-color"
                    style={{ background: getModelColor(session.model, selectedBackend || session.backendName) }}
                  />
                  {selectedBackend || modelDisplay}
                  {backends.length > 1 && !isStreaming && (
                    <span className="session-status-bar__dropdown-arrow" aria-hidden="true">
                      ▼
                    </span>
                  )}
                </button>

                {/* Backend dropdown with click-outside overlay */}
                {showBackendSelector && backends.length > 1 && (
                  <>
                    <div
                      className="session-status-bar__dropdown-overlay"
                      onClick={() => setShowBackendSelector(false)}
                      aria-hidden="true"
                    />
                    <div className="session-status-bar__backend-dropdown" role="listbox">
                      {backends.map(backend => (
                        <button
                          key={backend}
                          type="button"
                          role="option"
                          aria-selected={backend === selectedBackend}
                          className={`session-status-bar__backend-option ${backend === selectedBackend ? 'session-status-bar__backend-option--selected' : ''}`}
                          onClick={() => handleBackendChange(backend)}
                          disabled={isChangingBackend}
                        >
                          <span
                            className="session-status-bar__backend-color"
                            style={{ background: getModelColor(null, backend) }}
                          />
                          {backend}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Inline context bar */}
            <div className="session-status-bar__context-inline">
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

            <span className="session-status-bar__context-values">
              {formatTokens(contextTokens)} / {formatTokens(contextWindow)}
              <span className="session-status-bar__context-percent">
                ({contextUsage.toFixed(0)}%)
              </span>
            </span>
          </div>
        </>
      )}
    </div>

    {/* Rename session modal */}
    {client && isConnected && (
      <RenameSessionModal
        isOpen={showRenameModal}
        onClose={handleCloseRenameModal}
        sessionId={session.id}
        currentTitle={session.title || session.forkName || ''}
        client={client.sessions}
        sessionDataClient={client.sessionData}
        onRenamed={handleRenamed}
        onNavigateToSession={onSelectSession}
      />
    )}
    </>
  );
});

export default SessionStatusBar;
