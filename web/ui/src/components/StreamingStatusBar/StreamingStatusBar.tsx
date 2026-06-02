import React, { memo, useEffect, useState, useRef, useCallback, useMemo } from 'react';
import type { TaskInfo, SessionInfo, BalloonsClient } from '../../../../generated/balloons-client';
import { useLongPress, useNotifications } from '../../hooks';
import { useLayout } from '../layout';
import { usePreferences } from '../layout/PreferencesContext';
import { RenameSessionModal } from '../RenameSessionModal';
import { getModelColor, getModelColorVars } from '../../utils';
import { createLogger } from '../../utils/debugLog';
import './StreamingStatusBar.css';

const debugLog = createLogger('StreamingStatusBar');

export interface StreamingStatusBarProps {
  /** Current streaming task info */
  task: TaskInfo;
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
  /** Callback when user wants to select/navigate to a different session */
  onSelectSession?: (sessionId: string) => void;
  /** Scroll state from chat view */
  scrollState?: { isFollowing: boolean; isAtBottom: boolean };
  /** Session info for displaying/editing name */
  session?: SessionInfo;
  /** Balloons client for rename operations */
  client?: BalloonsClient | null;
  /** Callback when session title is changed */
  onTitleChange?: (newTitle: string) => void;
  /** Current working directory for the session */
  cwd?: string;
  /** Callback when CWD is clicked - opens file browser at that path */
  onCwdClick?: (cwd: string) => void;
  /** Callback to set CWD when none is set - opens file browser for selection */
  onSetCwd?: () => void;
}

function formatExchangeDuration(seconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const secs = safeSeconds % 60;
  const hundredths = Math.floor((seconds - Math.floor(seconds)) * 100);
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}:${String(hundredths).padStart(2, '0')}`;
}

function getTaskExchangeStart(task: TaskInfo): number {
  const startedAt = task.startedAt ? new Date(task.startedAt).getTime() : Date.now();
  return Number.isFinite(startedAt) ? startedAt : Date.now();
}

function getLiveExchangeDuration(task: TaskInfo): number {
  const start = getTaskExchangeStart(task);
  return Math.max(0, (Date.now() - start) / 1000);
}

function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${Math.floor(seconds)}s`;
  }
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}m ${secs}s`;
}

function formatTokens(count: number): string {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k`;
  }
  return String(count);
}

function formatTokenRate(rate: number): string {
  if (rate < 1) {
    return '<1';
  }
  return String(Math.round(rate));
}

function getContextBarColorClass(percentage: number): string {
  if (percentage >= 90) return 'context-bar--critical';
  if (percentage >= 75) return 'context-bar--warning';
  if (percentage >= 50) return 'context-bar--moderate';
  return 'context-bar--healthy';
}

function PinIcon({ isPinned }: { isPinned: boolean }) {
  return (<svg width="14" height="14" viewBox="0 0 24 24" fill={isPinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 17v5" /><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1z" /></svg>);
}

function BellIcon({ enabled, muted }: { enabled: boolean; muted?: boolean }) {
  return (<svg width="14" height="14" viewBox="0 0 24 24" fill={enabled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />{muted && <path d="M2 2l20 20" strokeWidth="2.5" />}</svg>);
}

function getSessionDisplayName(session: SessionInfo): string {
  return session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
}

function formatCwd(cwd: string | undefined): string {
  if (!cwd) return '';
  return cwd;
}

export const StreamingStatusBar = memo(function StreamingStatusBar({ task, onStop, stopDisabled = false, sessionContextTokens, isPinned = false, onTogglePin, onSelectSession, scrollState, session, client, onTitleChange, cwd, onCwdClick, onSetCwd, }: StreamingStatusBarProps) {
  const { expandDetail } = useLayout();
  const { expandToolCards, togglePreference } = usePreferences();
  const { notificationsEnabled, toggleNotifications, permissionState } = useNotifications(session?.id ?? null, client);
  const [isCollapsed, setIsCollapsed] = useState(() => localStorage.getItem('sessionStatusBar.collapsed') === 'true');
  const [inlineNotification, setInlineNotification] = useState<string | null>(null);
  const notificationTimerRef = useRef<number | null>(null);
  const [duration, setDuration] = useState(task.durationSeconds);
  const startTimeRef = useRef<number>(getTaskExchangeStart(task));
  const isConnected = client?.isConnected ?? false;

  const pushInlineNotification = useCallback((message: string) => {
    setInlineNotification(message);
    if (notificationTimerRef.current) window.clearTimeout(notificationTimerRef.current);
    notificationTimerRef.current = window.setTimeout(() => { setInlineNotification(null); notificationTimerRef.current = null; }, 6000);
  }, []);

  const toggleCollapsed = useCallback(() => {
    setIsCollapsed(prev => { const next = !prev; localStorage.setItem('sessionStatusBar.collapsed', String(next)); return next; });
  }, []);

  const [showRenameModal, setShowRenameModal] = useState(false);
  const titleLongPress = useLongPress({ onLongPress: () => { if (client?.isConnected && session) setShowRenameModal(true); }, delay: 500 });
  const cwdLongPress = useLongPress({ onLongPress: () => { if (cwd && onCwdClick) { expandDetail(); onCwdClick(cwd); } }, onClick: () => { if (cwd) navigator.clipboard.writeText(cwd); }, delay: 500 });
  const handleRenamed = useCallback((newTitle: string) => { onTitleChange?.(newTitle); }, [onTitleChange]);
  const handleCloseRenameModal = useCallback(() => setShowRenameModal(false), []);
  const sessionName = session ? getSessionDisplayName(session) : null;

  useEffect(() => { startTimeRef.current = getTaskExchangeStart(task); setDuration(task.durationSeconds); const interval = setInterval(() => { setDuration(getLiveExchangeDuration(task)); }, 100); return () => clearInterval(interval); }, [task.taskId, task.startedAt, task.durationSeconds]);

  const totalContextTokens = sessionContextTokens ?? (task.inputTokens + task.outputTokens);
  const contextUsage = task.contextWindow > 0 ? Math.min(100, (totalContextTokens / task.contextWindow) * 100) : 0;
  const contextColorClass = getContextBarColorClass(contextUsage);
  const isToolRunning = !!task.toolName;
  const modelColor = useMemo(() => getModelColor(task.model, task.backendName), [task.model, task.backendName]);
  const modelColorVars = useMemo(() => getModelColorVars(task.model, task.backendName), [task.model, task.backendName]) as React.CSSProperties;
  const timerText = task.isActive ? formatExchangeDuration(duration) : formatExchangeDuration(task.durationSeconds);

  return (<>
    <div className={`streaming-status-bar ${isCollapsed ? 'streaming-status-bar--collapsed' : ''}`} role="status" aria-live="polite" style={modelColorVars}>
      {isCollapsed ? (<div className="streaming-status-bar__collapsed-view"><button type="button" className="streaming-status-bar__toggle" onClick={toggleCollapsed} title="Expand status bar" aria-label="Expand status bar" aria-expanded={false}><span className="streaming-status-bar__toggle-icon">▲</span></button><span className="streaming-status-bar__indicator streaming-status-bar__indicator--mini" style={{ background: modelColor }} aria-hidden="true" />{scrollState && !scrollState.isFollowing && (<span className="streaming-status-bar__scroll-state paused mini" title="Auto-scroll PAUSED">⏸</span>)}<div className="streaming-status-bar__mini-track"><div className={`streaming-status-bar__mini-bar ${contextColorClass}`} style={{ width: `${contextUsage}%` }} role="progressbar" aria-valuenow={contextUsage} aria-valuemin={0} aria-valuemax={100} aria-label={`Context usage: ${contextUsage.toFixed(0)}%`} /></div><span className="streaming-status-bar__mini-timer">{timerText}</span>{onStop && (<button type="button" className="streaming-status-bar__stop streaming-status-bar__stop--mini" onClick={onStop} disabled={stopDisabled} aria-label="Stop streaming">Stop</button>)}</div>) : (<>
        <div className="streaming-status-bar__row">
          <button type="button" className="streaming-status-bar__toggle" onClick={toggleCollapsed} title="Collapse status bar" aria-label="Collapse status bar" aria-expanded={true}><span className="streaming-status-bar__toggle-icon">▼</span></button>
          {sessionName && (<div className="streaming-status-bar__title-content" title="Long press to rename session" {...titleLongPress}><span className="streaming-status-bar__session-title">{sessionName}</span>{session && (session.forkName || session.title) && (<span className="streaming-status-bar__session-id">{session.id.slice(0, 8)}</span>)}</div>)}
          {onTogglePin && (<button type="button" className={`streaming-status-bar__pin-button ${isPinned ? 'streaming-status-bar__pin-button--active' : ''}`} onClick={onTogglePin} title={isPinned ? 'Unpin session' : 'Pin session'} aria-label={isPinned ? 'Unpin session' : 'Pin session'}><PinIcon isPinned={isPinned} /></button>)}
          <button type="button" className={`streaming-status-bar__bell-button ${notificationsEnabled ? 'streaming-status-bar__bell-button--active' : ''} ${permissionState === 'denied' ? 'streaming-status-bar__bell-button--denied' : ''}`} onClick={toggleNotifications} title={permissionState === 'denied' ? 'Notifications blocked by browser' : permissionState === 'unsupported' ? 'Notifications not supported' : notificationsEnabled ? 'Disable notifications for this session' : 'Enable notifications for this session'} aria-label={notificationsEnabled ? 'Disable notifications' : 'Enable notifications'} disabled={permissionState === 'denied' || permissionState === 'unsupported'}><BellIcon enabled={notificationsEnabled} muted={permissionState === 'denied'} /></button>
          {cwd ? (<div className={`streaming-status-bar__cwd ${onCwdClick ? 'streaming-status-bar__cwd--clickable' : ''}`} title={onCwdClick ? `${cwd}\n(Tap to copy, long-press to open in file browser)` : `${cwd}\n(Tap to copy)`} {...cwdLongPress}><span className="streaming-status-bar__cwd-icon">📁</span><span className="streaming-status-bar__cwd-path">{formatCwd(cwd)}</span></div>) : onSetCwd && (<button type="button" className="streaming-status-bar__cwd streaming-status-bar__cwd--unset" title="Set working directory for this session" onClick={() => { expandDetail(); onSetCwd(); }}><span className="streaming-status-bar__cwd-icon">📁</span><span className="streaming-status-bar__cwd-path">Set folder...</span></button>)}
          <div className="streaming-status-bar__spacer" />
          <button type="button" className={`streaming-status-bar__expand-toggle ${expandToolCards ? 'active' : ''}`} onClick={() => togglePreference('expandToolCards')} title={expandToolCards ? 'Tool cards: expanded (click to collapse)' : 'Tool cards: collapsed (click to expand)'} aria-label={expandToolCards ? 'Collapse tool cards by default' : 'Expand tool cards by default'}>{expandToolCards ? '▼' : '▶'}</button>
          {scrollState && !scrollState.isFollowing && (<div className="streaming-status-bar__scroll-state paused" title="Auto-scroll: PAUSED (scrolled up)">⏸</div>)}
          {onStop && (<button type="button" className="streaming-status-bar__stop" onClick={onStop} disabled={stopDisabled} aria-label="Stop streaming">Stop</button>)}
        </div>
        <div className="streaming-status-bar__row">
          <div className="streaming-status-bar__model"><span className="streaming-status-bar__indicator" style={{ background: modelColor }} aria-hidden="true" />{isToolRunning ? (<span className="streaming-status-bar__tool-name">{task.toolName}</span>) : (<span className="streaming-status-bar__model-name" style={{ color: modelColor }}>{task.model || task.backendName || 'Streaming'}</span>)}</div>
          <span className="streaming-status-bar__mini-timer">{timerText}</span>
          {task.contextWindow > 0 && (<div className="streaming-status-bar__context-inline"><div className="streaming-status-bar__context-track"><div className={`streaming-status-bar__context-bar ${contextColorClass}`} style={{ width: `${contextUsage}%` }} role="progressbar" aria-valuenow={contextUsage} aria-valuemin={0} aria-valuemax={100} aria-label={`Context usage: ${contextUsage.toFixed(0)}%`} /></div></div>)}
          <span className="streaming-status-bar__context-values">{formatTokens(totalContextTokens)} / {formatTokens(task.contextWindow)}<span className="streaming-status-bar__context-percent">({contextUsage.toFixed(0)}%)</span></span>
        </div>
      </>)}
    </div>
    {client && isConnected && session && (<RenameSessionModal isOpen={showRenameModal} onClose={handleCloseRenameModal} sessionId={session.id} currentTitle={session.title || session.forkName || ''} client={client.sessions} sessionDataClient={client.sessionData} onRenamed={handleRenamed} onNavigateToSession={onSelectSession} />)}
  </>);
});

export default StreamingStatusBar;
