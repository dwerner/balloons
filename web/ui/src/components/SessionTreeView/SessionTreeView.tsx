/**
 * SessionTreeView - Tree view showing sessions and fork hierarchy
 *
 * Following standard tree view patterns:
 * - Semantic <ul>/<li> structure
 * - Recursive node rendering
 * - CSS for visual hierarchy via padding
 * - Arrow icons for expand/collapse
 *
 * Features:
 * - Fork hierarchy display (parent/child sessions)
 * - Multi-selection with Shift+click (range) and Ctrl/Cmd+click (toggle)
 * - Archive/delete bulk actions
 *
 * Note: Turn/exchange display is now handled by the Context tab.
 * This view focuses on session/fork navigation.
 *
 * URL ROUTING INTEGRATION:
 * - onSelectSession should trigger URL navigation to #/sessions/:sessionId
 * - Router should call onSelectSession when URL changes to a session route
 * - See docs/url-routing.md for the full routing design
 */

import React, { useState, useCallback, useMemo, memo, useEffect } from 'react';
import { createPortal } from 'react-dom';
import type { SessionInfo, ForkChild } from '../../../../generated/balloons-client';
import { createLogger } from '../../utils/debugLog';
import './SessionTreeView.css';

// Create scoped logger for this module
const debugLog = createLogger('SessionTreeView');

// Session colors for visual distinction
const SESSION_COLORS = [
  '#60a5fa', // blue
  '#c084fc', // purple
  '#22d3ee', // cyan
  '#4ade80', // green
  '#facc15', // yellow
  '#f87171', // red
];

// Format a date as a day group label
function formatDayGroup(dateStr: string): string {
  if (!dateStr) return 'Unknown';
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return 'Unknown';
  const now = new Date();

  // Get start of today, yesterday, etc.
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);
  const startOfThisWeek = new Date(startOfToday);
  startOfThisWeek.setDate(startOfThisWeek.getDate() - now.getDay());
  const startOfLastWeek = new Date(startOfThisWeek);
  startOfLastWeek.setDate(startOfLastWeek.getDate() - 7);

  if (date >= startOfToday) {
    return 'Today';
  } else if (date >= startOfYesterday) {
    return 'Yesterday';
  } else if (date >= startOfThisWeek) {
    // This week - show day name
    return date.toLocaleDateString(undefined, { weekday: 'long' });
  } else if (date >= startOfLastWeek) {
    return 'Last Week';
  } else {
    // Older - show month and year, or just month if same year
    const sameYear = date.getFullYear() === now.getFullYear();
    if (sameYear) {
      return date.toLocaleDateString(undefined, { month: 'long' });
    } else {
      return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
    }
  }
}

// Get a sortable day key for grouping
function getDayKey(dateStr: string): string {
  if (!dateStr) return '1970-01-01';
  const date = new Date(dateStr);
  // Check for invalid date
  if (isNaN(date.getTime())) return '1970-01-01';
  // Return YYYY-MM-DD format for consistent grouping
  return date.toISOString().split('T')[0] || '1970-01-01';
}

// Arrow icon component
function Arrow({ open, color }: { open: boolean; color?: string }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke={color || 'currentColor'}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`tree-arrow ${open ? 'tree-arrow--open' : ''}`}
    >
      {/* Down arrow: points down when closed, rotates to point right when open */}
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

// Pin icon component
function PinIcon({ isPinned, onClick }: { isPinned: boolean; onClick: (e: React.MouseEvent) => void }) {
  return (
    <span
      className={`tree-pin ${isPinned ? 'tree-pin--active' : ''}`}
      onClick={onClick}
      title={isPinned ? 'Unpin session' : 'Pin session'}
    >
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
    </span>
  );
}

// Checkbox icon for multi-selection
function CheckboxIcon({ checked, onClick }: { checked: boolean; onClick: (e: React.MouseEvent) => void }) {
  return (
    <span
      className={`tree-checkbox ${checked ? 'tree-checkbox--checked' : ''}`}
      onClick={onClick}
      title={checked ? 'Deselect' : 'Select'}
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill={checked ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect x="3" y="3" width="18" height="18" rx="2" />
        {checked && <path d="M9 12l2 2 4-4" />}
      </svg>
    </span>
  );
}

// Archive icon
function ArchiveIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="2" y="4" width="20" height="5" rx="1" />
      <path d="M4 9v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9" />
      <path d="M10 13h4" />
    </svg>
  );
}

// Trash icon
function TrashIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 6h18" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

// Session-level context menu
interface SessionMenuProps {
  position: { x: number; y: number };
  sessionId: string;
  sessionTitle: string;
  currentSessionId: string | null;  // The currently selected session (for linking)
  onReview: () => void;
  onRename?: () => void;
  onLinkToCurrentSession?: () => void;  // Link this session to the current session
  onWatchSession?: () => void;  // Create a watcher session to observe this session
  onClose: () => void;
}

function SessionContextMenu({
  position,
  sessionId,
  sessionTitle,
  currentSessionId,
  onReview,
  onRename,
  onLinkToCurrentSession,
  onWatchSession,
  onClose,
}: SessionMenuProps) {
  // Can link if there's a current session and it's different from the one being right-clicked
  const canLink = currentSessionId && currentSessionId !== sessionId;
  const menuRef = React.useRef<HTMLDivElement>(null);

  // Debug log when menu mounts
  useEffect(() => {
    debugLog('SessionContextMenu mounted', { position, sessionId });
    return () => {
      debugLog('SessionContextMenu unmounted');
    };
  }, [position, sessionId]);

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        debugLog('SessionContextMenu click outside, closing');
        onClose();
      }
    };
    const timeoutId = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside);
    }, 100);
    return () => {
      clearTimeout(timeoutId);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [onClose]);

  // Close on escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        debugLog('SessionContextMenu escape pressed, closing');
        onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return createPortal(
    <div
      ref={menuRef}
      className="exchange-context-menu session-context-menu"
      style={{
        position: 'fixed',
        left: position.x,
        top: position.y,
        zIndex: 9999,
      }}
    >
      <div className="exchange-context-menu__section">
        <button
          className="exchange-context-menu__item"
          onClick={() => { onReview(); onClose(); }}
        >
          <span className="exchange-context-menu__icon">📋</span>
          Review &amp; Summarize
          <span className="exchange-context-menu__hint">Generate summary</span>
        </button>
        {onRename && (
          <button
            className="exchange-context-menu__item"
            onClick={() => { onRename(); onClose(); }}
          >
            <span className="exchange-context-menu__icon">✏️</span>
            Rename
          </button>
        )}
        {canLink && onLinkToCurrentSession && (
          <button
            className="exchange-context-menu__item"
            onClick={() => { onLinkToCurrentSession(); onClose(); }}
          >
            <span className="exchange-context-menu__icon">🔗</span>
            Link to Current Session
            <span className="exchange-context-menu__hint">Create bidirectional link</span>
          </button>
        )}
        {onWatchSession && (
          <button
            className="exchange-context-menu__item"
            onClick={() => { onWatchSession(); onClose(); }}
          >
            <span className="exchange-context-menu__icon">👁</span>
            Watch this Session
            <span className="exchange-context-menu__hint">Create watcher session</span>
          </button>
        )}
      </div>
    </div>,
    document.body
  );
}

// Session node props for memoization
interface SessionNodeProps {
  session: SessionInfo;
  index: number;
  isSelected: boolean;
  isChecked: boolean;
  isExpanded: boolean;
  showCheckboxes: boolean;
  onToggle: () => void;
  onSelect: (e: React.MouseEvent) => void;
  onTogglePin?: () => void;
  onToggleCheck?: (e: React.MouseEvent) => void;
  onReview?: () => void;
  onRename?: () => void;
  onLinkSession?: () => void;
  onWatchSession?: () => void;
  onNavigateToSession?: (sessionId: string) => void;  // Navigate to a fork child
  selectedSessionId: string | null;
}

/**
 * Custom comparison for SessionNode memoization.
 * Only re-render when meaningful props change.
 */
function sessionNodePropsAreEqual(prev: SessionNodeProps, next: SessionNodeProps): boolean {
  // Always re-render if selection, expansion, or checkbox state changed
  if (prev.isSelected !== next.isSelected) return false;
  if (prev.isChecked !== next.isChecked) return false;
  if (prev.isExpanded !== next.isExpanded) return false;
  if (prev.showCheckboxes !== next.showCheckboxes) return false;

  // Session identity and metadata
  if (prev.session.id !== next.session.id) return false;
  if (prev.session.messageCount !== next.session.messageCount) return false;
  if (prev.session.isStreaming !== next.session.isStreaming) return false;
  if (prev.session.isPinned !== next.session.isPinned) return false;
  if (prev.session.title !== next.session.title) return false;
  if (prev.session.forkName !== next.session.forkName) return false;
  if (prev.session.forkStatus !== next.session.forkStatus) return false;

  // Check for children changes (fork tree)
  const prevChildren = prev.session.children || [];
  const nextChildren = next.session.children || [];
  if (prevChildren.length !== nextChildren.length) return false;

  return true;
}

// Session node component - memoized to prevent unnecessary re-renders
const SessionNode = memo(function SessionNode({
  session,
  index,
  isSelected,
  isChecked,
  isExpanded,
  showCheckboxes,
  onToggle,
  onSelect,
  onTogglePin,
  onToggleCheck,
  onReview,
  onRename,
  onLinkSession,
  onWatchSession,
  onNavigateToSession,
  selectedSessionId,
}: SessionNodeProps) {
  const sessionColor = SESSION_COLORS[index % SESSION_COLORS.length] || '#60a5fa';
  const sessionName = session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
  const isPinned = session.isPinned ?? false;

  // Fork children from this session
  const forkChildren = session.children || [];
  const hasForkChildren = forkChildren.length > 0;

  // Note: watchTargets/watchedBy are lazily loaded and not available in session list.
  // Full watcher navigation is available in the long-press modal (RenameSessionModal)
  // which uses get_session_fork_tree() to load the complete watcher relationships.

  // Session context menu state
  const [sessionMenuPosition, setSessionMenuPosition] = useState<{ x: number; y: number } | null>(null);

  const handlePinClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onTogglePin?.();
  };

  const handleSessionContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    debugLog('Session context menu triggered', { x: e.clientX, y: e.clientY, sessionId: session.id });
    setSessionMenuPosition({ x: e.clientX, y: e.clientY });
  }, [session.id]);

  return (
    <li className={`tree-node tree-node--session ${isPinned ? 'tree-node--pinned' : ''} ${isChecked ? 'tree-node--checked' : ''}`}>
      <div
        className={`tree-node__content ${isSelected ? 'tree-node__content--selected' : ''}`}
        onClick={onSelect}
        onContextMenu={handleSessionContextMenu}
        style={{ borderLeftColor: sessionColor }}
      >
        {/* Checkbox for multi-selection */}
        {showCheckboxes && onToggleCheck && (
          <span className="tree-node__checkbox">
            <CheckboxIcon checked={isChecked} onClick={onToggleCheck} />
          </span>
        )}

        <span
          key="toggle"
          className="tree-node__toggle"
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
        >
          {hasForkChildren ? <Arrow open={isExpanded} color={sessionColor} /> : <span className="tree-node__spacer" />}
        </span>

        {/* Pin toggle on the left - always visible for pinned, hover for unpinned */}
        {onTogglePin && !showCheckboxes && (
          <span key="pin-toggle" className={`tree-node__pin-toggle tree-node__pin-toggle--left ${isPinned ? 'tree-node__pin-toggle--pinned' : ''}`}>
            <PinIcon isPinned={isPinned} onClick={handlePinClick} />
          </span>
        )}

        {session.isStreaming && (
          <span key="streaming-badge" className="tree-node__badge tree-node__badge--streaming">⟳</span>
        )}

        {session.parentId && (
          <span key="fork-badge" className="tree-node__badge tree-node__badge--fork">
            {session.forkStatus === 'merged' ? '✓' : '↳'}
          </span>
        )}

        <span key="id" className="tree-node__id">{session.id.slice(0, 8)}</span>
        <span key="label" className="tree-node__label">{sessionName}</span>
        <span key="meta" className="tree-node__meta">({session.messageCount}msg)</span>
      </div>

      {/* Fork children - show when expanded */}
      {isExpanded && hasForkChildren && (
        <ul className="tree-children">
          {forkChildren.map(child => (
            <li
              key={child.sessionId}
              className={`tree-node tree-node--fork-child tree-node--fork-child--${child.status}`}
            >
              <div
                className="tree-node__content tree-node__content--clickable"
                onClick={() => onNavigateToSession?.(child.sessionId)}
                title={`Navigate to ${child.name || child.sessionId.slice(0, 8)}`}
              >
                <span className="tree-node__spacer" />
                <span className="tree-node__badge tree-node__badge--fork">
                  {child.status === 'merged' ? '✓' : '↳'}
                </span>
                <span className="tree-node__id">{child.sessionId.slice(0, 8)}</span>
                <span className="tree-node__label">
                  {child.name || `Fork ${child.sessionId.slice(0, 8)}`}
                </span>
                {child.status !== 'active' && (
                  <span className="tree-node__meta">({child.status})</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Session context menu */}
      {sessionMenuPosition && (
        <SessionContextMenu
          position={sessionMenuPosition}
          sessionId={session.id}
          sessionTitle={sessionName}
          currentSessionId={selectedSessionId}
          onReview={() => onReview?.()}
          onRename={onRename}
          onLinkToCurrentSession={onLinkSession}
          onWatchSession={onWatchSession}
          onClose={() => setSessionMenuPosition(null)}
        />
      )}
    </li>
  );
}, sessionNodePropsAreEqual);

// Bulk action type
export type BulkAction = 'archive' | 'delete' | 'unarchive';

// Props for main component
interface SessionTreeViewProps {
  sessions: SessionInfo[];
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onLinkSession?: (sessionId: string) => void;
  onWatchSession?: (sessionId: string) => void;
  onTogglePin?: (sessionId: string) => void;
  onBulkAction?: (sessionIds: string[], action: BulkAction) => void;
  onReviewSession?: (sessionId: string) => void;
  onRenameSession?: (sessionId: string) => void;
  isLoading?: boolean;
}

export const SessionTreeView = memo(function SessionTreeView({
  sessions,
  selectedSessionId,
  onSelectSession,
  onTogglePin,
  onBulkAction,
  onReviewSession,
  onRenameSession,
  onLinkSession,
  onWatchSession,
  isLoading = false,
}: SessionTreeViewProps) {
  // Log on mount
  useEffect(() => {
    debugLog('SessionTreeView mounted', { sessionCount: sessions.length });
  }, [sessions.length]);

  // Debug: global contextmenu listener to see if events are being captured
  useEffect(() => {
    const handleGlobalContextMenu = (e: MouseEvent) => {
      debugLog('Global contextmenu event', {
        target: (e.target as HTMLElement)?.className,
        tagName: (e.target as HTMLElement)?.tagName,
        defaultPrevented: e.defaultPrevented,
      });
    };
    document.addEventListener('contextmenu', handleGlobalContextMenu, true); // capture phase
    return () => document.removeEventListener('contextmenu', handleGlobalContextMenu, true);
  }, []);

  const [expandedSessions, setExpandedSessions] = useState<Set<string>>(new Set());
  const [checkedSessions, setCheckedSessions] = useState<Set<string>>(new Set());
  const [lastClickedSessionId, setLastClickedSessionId] = useState<string | null>(null);

  // Show checkboxes when any session is checked
  const showCheckboxes = checkedSessions.size > 0;

  const toggleSession = useCallback((sessionId: string) => {
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

  // Get all session IDs in display order for range selection
  const sessionIdOrder = useMemo(() => {
    const order: string[] = [];
    const pinned = sessions.filter(s => s.isPinned);
    const unpinned = sessions.filter(s => !s.isPinned);
    pinned.forEach(s => order.push(s.id));
    unpinned.forEach(s => order.push(s.id));
    return order;
  }, [sessions]);

  // Handle session click with multi-selection support
  const handleSessionClick = useCallback((sessionId: string, e: React.MouseEvent) => {
    const isMetaKey = e.metaKey || e.ctrlKey;
    const isShiftKey = e.shiftKey;

    if (isShiftKey && lastClickedSessionId) {
      // Range selection
      const startIdx = sessionIdOrder.indexOf(lastClickedSessionId);
      const endIdx = sessionIdOrder.indexOf(sessionId);
      if (startIdx !== -1 && endIdx !== -1) {
        const [from, to] = startIdx < endIdx ? [startIdx, endIdx] : [endIdx, startIdx];
        const range = sessionIdOrder.slice(from, to + 1);
        setCheckedSessions(prev => {
          const next = new Set(prev);
          range.forEach(id => next.add(id));
          return next;
        });
      }
    } else if (isMetaKey) {
      // Toggle selection
      setCheckedSessions(prev => {
        const next = new Set(prev);
        if (next.has(sessionId)) {
          next.delete(sessionId);
        } else {
          next.add(sessionId);
        }
        return next;
      });
      setLastClickedSessionId(sessionId);
    } else {
      // Normal click - select session, clear multi-selection
      if (checkedSessions.size > 0) {
        setCheckedSessions(new Set());
      }
      setLastClickedSessionId(sessionId);
      onSelectSession(sessionId);
    }
  }, [lastClickedSessionId, sessionIdOrder, checkedSessions.size, onSelectSession]);

  // Handle checkbox click (doesn't select session)
  const handleCheckboxClick = useCallback((sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setCheckedSessions(prev => {
      const next = new Set(prev);
      if (next.has(sessionId)) {
        next.delete(sessionId);
      } else {
        next.add(sessionId);
      }
      return next;
    });
    setLastClickedSessionId(sessionId);
  }, []);

  // Handle bulk action
  const handleBulkAction = useCallback((action: BulkAction) => {
    if (onBulkAction && checkedSessions.size > 0) {
      onBulkAction(Array.from(checkedSessions), action);
      setCheckedSessions(new Set());
    }
  }, [onBulkAction, checkedSessions]);

  // Clear selection
  const clearSelection = useCallback(() => {
    setCheckedSessions(new Set());
  }, []);

  // Group sessions by day with pinned sessions first, plus a "Watching" group
  const groupedSessions = useMemo(() => {
    // Separate pinned and unpinned sessions
    const pinned = sessions.filter(s => s.isPinned);
    const unpinned = sessions.filter(s => !s.isPinned);

    // Debug: log pinned state
    debugLog('groupedSessions computation', {
      totalSessions: sessions.length,
      pinnedCount: pinned.length,
      pinnedIds: pinned.map(s => ({ id: s.id.slice(0, 8), title: s.title, isPinned: s.isPinned })),
      sessionsWithIsPinned: sessions.filter(s => s.isPinned !== undefined).length,
    });

    // Sort pinned by last modified (most recent first)
    pinned.sort((a, b) => {
      return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
    });

    // Identify watcher sessions and their targets
    // Watchers have titles like "watching:target-name"
    const watcherSessions = new Set<string>();
    const watcherToTargetName = new Map<string, string>(); // watcher session id -> target name it's watching
    const targetNameToSession = new Map<string, SessionInfo>(); // target name -> target session

    // First pass: identify watchers and build target name index
    for (const session of unpinned) {
      const title = session.title || session.forkName || '';
      if (title.startsWith('watching:')) {
        watcherSessions.add(session.id);
        const targetName = title.slice('watching:'.length);
        watcherToTargetName.set(session.id, targetName);
      }
      // Index all sessions by their name for target matching
      const sessionName = session.title || session.forkName || '';
      if (sessionName && !sessionName.startsWith('watching:')) {
        targetNameToSession.set(sessionName, session);
      }
    }

    // Build watcher groups: each target with its watchers
    // Structure: { target: SessionInfo | null, watchers: SessionInfo[], groupTime: number }
    type WatcherGroup = { target: SessionInfo | null; watchers: SessionInfo[]; groupTime: number; targetName: string };
    const watcherGroups: WatcherGroup[] = [];
    const usedSessionIds = new Set<string>();

    // Group watchers by their target
    const targetNameToWatchers = new Map<string, SessionInfo[]>();
    for (const session of unpinned) {
      if (watcherSessions.has(session.id)) {
        const targetName = watcherToTargetName.get(session.id)!;
        if (!targetNameToWatchers.has(targetName)) {
          targetNameToWatchers.set(targetName, []);
        }
        targetNameToWatchers.get(targetName)!.push(session);
      }
    }

    // Create groups for each unique target name
    for (const [targetName, watchers] of targetNameToWatchers) {
      const targetSession = targetNameToSession.get(targetName) || null;

      // Calculate group time as most recent activity in the group
      let groupTime = 0;
      if (targetSession) {
        groupTime = new Date(targetSession.lastModified).getTime();
        usedSessionIds.add(targetSession.id);
      }
      for (const watcher of watchers) {
        const watcherTime = new Date(watcher.lastModified).getTime();
        if (watcherTime > groupTime) groupTime = watcherTime;
        usedSessionIds.add(watcher.id);
      }

      // Sort watchers by last modified (most recent first)
      watchers.sort((a, b) =>
        new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime()
      );

      watcherGroups.push({ target: targetSession, watchers, groupTime, targetName });
    }

    // Sort groups by most recent activity
    watcherGroups.sort((a, b) => b.groupTime - a.groupTime);

    // Separate regular sessions (not in any watcher group)
    const regularUnpinned: SessionInfo[] = [];
    for (const session of unpinned) {
      if (!usedSessionIds.has(session.id)) {
        regularUnpinned.push(session);
      }
    }

    // Group regular unpinned by day label first, THEN sort within groups
    // This ensures all "Today" sessions are together even if isCurrent bumps one to the top
    const dayGroupMap = new Map<string, { key: string; label: string; sessions: SessionInfo[]; sortKey: number }>();

    for (const session of regularUnpinned) {
      const dayKey = getDayKey(session.lastModified);
      const label = formatDayGroup(session.lastModified);

      if (!dayGroupMap.has(label)) {
        // Calculate a sort key for ordering groups (more recent = higher/earlier)
        // Use the dayKey (YYYY-MM-DD) as the basis for sorting groups
        dayGroupMap.set(label, {
          key: dayKey,
          label,
          sessions: [],
          sortKey: new Date(dayKey).getTime(),
        });
      }
      dayGroupMap.get(label)!.sessions.push(session);
    }

    // Sort sessions within each group by last modified (most recent first)
    for (const group of dayGroupMap.values()) {
      group.sessions.sort((a, b) => {
        return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
      });
      // Update sortKey to be the most recent session in the group
      const mostRecent = group.sessions[0];
      if (mostRecent) {
        group.sortKey = new Date(mostRecent.lastModified).getTime();
      }
    }

    // Sort groups by their most recent session (descending - most recent first)
    // "Unknown" group always goes to the bottom
    const dayGroups = Array.from(dayGroupMap.values())
      .sort((a, b) => {
        // Unknown always goes last
        if (a.label === 'Unknown') return 1;
        if (b.label === 'Unknown') return -1;
        // Handle NaN sortKeys (treat as very old)
        const aKey = isNaN(a.sortKey) ? 0 : a.sortKey;
        const bKey = isNaN(b.sortKey) ? 0 : b.sortKey;
        return bKey - aKey;
      })
      .map(({ key, label, sessions }) => ({ key, label, sessions }));

    return { pinned, watcherGroups, dayGroups };
  }, [sessions]);

  if (isLoading) {
    return (
      <div className="tree-view tree-view--empty">
        Loading sessions...
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="tree-view tree-view--empty">
        No sessions
      </div>
    );
  }

  // Track index for consistent coloring across groups
  let sessionIndex = 0;

  // Helper to render a session node
  const renderSessionNode = (session: SessionInfo) => {
    const isSelected = session.id === selectedSessionId;
    const isChecked = checkedSessions.has(session.id);
    const isExpanded = expandedSessions.has(session.id);
    const idx = sessionIndex++;

    return (
      <SessionNode
        key={session.id}
        session={session}
        index={idx}
        isSelected={isSelected}
        isChecked={isChecked}
        isExpanded={isExpanded}
        showCheckboxes={showCheckboxes}
        onToggle={() => toggleSession(session.id)}
        onSelect={(e) => handleSessionClick(session.id, e)}
        onTogglePin={onTogglePin ? () => onTogglePin(session.id) : undefined}
        onToggleCheck={(e) => handleCheckboxClick(session.id, e)}
        onReview={onReviewSession ? () => onReviewSession(session.id) : undefined}
        onRename={onRenameSession ? () => onRenameSession(session.id) : undefined}
        onLinkSession={onLinkSession ? () => onLinkSession(session.id) : undefined}
        onWatchSession={onWatchSession ? () => onWatchSession(session.id) : undefined}
        onNavigateToSession={onSelectSession}
        selectedSessionId={selectedSessionId}
      />
    );
  };

  return (
    <div className="tree-view-container">
      {/* Bulk action toolbar */}
      {showCheckboxes && (
        <div className="tree-toolbar">
          <span className="tree-toolbar__count">
            {checkedSessions.size} selected
          </span>
          {onBulkAction && (
            <>
              <button
                className="tree-toolbar__action"
                onClick={() => handleBulkAction('archive')}
                title="Archive selected sessions"
              >
                <ArchiveIcon />
                Archive
              </button>
              <button
                className="tree-toolbar__action tree-toolbar__action--danger"
                onClick={() => handleBulkAction('delete')}
                title="Delete selected sessions"
              >
                <TrashIcon />
                Delete
              </button>
            </>
          )}
          <button
            className="tree-toolbar__action tree-toolbar__action--text"
            onClick={clearSelection}
          >
            Cancel
          </button>
        </div>
      )}

      <ul className="tree-view">
        {/* Pinned sessions first */}
        {groupedSessions.pinned.length > 0 && (
          <li className="tree-group tree-group--pinned">
            <div className="tree-group__header">Pinned</div>
            <ul className="tree-group__sessions">
              {groupedSessions.pinned.map(renderSessionNode)}
            </ul>
          </li>
        )}

        {/* Watching sessions (watchers and their targets grouped together) */}
        {groupedSessions.watcherGroups.length > 0 && (
          <li className="tree-group tree-group--watching">
            <div className="tree-group__header">👁 Watching</div>
            <ul className="tree-group__sessions">
              {groupedSessions.watcherGroups.map((group, groupIndex) => (
                <React.Fragment key={`watcher-group-${groupIndex}`}>
                  {/* Watcher sessions first */}
                  {group.watchers.map(renderSessionNode)}
                  {/* Target session (the watched one) - SessionNode renders its own <li> */}
                  {group.target ? (
                    renderSessionNode(group.target)
                  ) : (
                    <li key={`missing-${group.targetName}`} className="watcher-pair__missing-target">
                      <span className="watcher-pair__missing-icon">?</span>
                      <span className="watcher-pair__missing-name">{group.targetName}</span>
                      <span className="watcher-pair__missing-hint">(session not found)</span>
                    </li>
                  )}
                </React.Fragment>
              ))}
            </ul>
          </li>
        )}

        {/* Day groups */}
        {groupedSessions.dayGroups.map((group, groupIndex) => (
          <li key={`${group.key}-${groupIndex}`} className="tree-group">
            <div className="tree-group__header">{group.label}</div>
            <ul className="tree-group__sessions">
              {group.sessions.map(renderSessionNode)}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
});

export default SessionTreeView;
