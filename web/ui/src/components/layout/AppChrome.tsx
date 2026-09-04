/**
 * Presentational chrome for the app shell: mobile header, main content
 * header (tab bar), session list item, and sidebar content. Extracted from
 * App.tsx (WS3) so the god component shrinks and these view components have
 * a home alongside the rest of the layout.
 */
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import type { BalloonsClient, ConnectionState, SessionInfo, TaskInfo, TurnInfo } from '../../../../generated/balloons-client';
import { SLOT_PORTS, type ServerSlot } from '../../utils/serverSlots';
import { formatTokens } from '../../utils/turnTransforms';
import { useLayout } from './LayoutContext';
import { useLongPress, useVisualViewport } from '../../hooks';
import { createLogger } from '../../utils/debugLog';
import { SessionTreeView } from '../SessionTreeView';
import { HierarchyView } from '../HierarchyView';
import { RenameSessionModal } from '../RenameSessionModal';
import type { GitStatusInfo } from '../CodeTab';

const debugLog = createLogger('AppChrome');


interface MobileHeaderProps {
  connectionState: ConnectionState;
  selectedSession?: SessionInfo | null;
}

export function MobileHeader({ connectionState, selectedSession }: MobileHeaderProps) {
  const { openSidebar, openDetail } = useLayout();

  // Format title: session name (or title) + hash prefix
  const headerTitle = selectedSession
    ? `${selectedSession.forkName || selectedSession.title || 'Session'} #${selectedSession.id.slice(0, 6)}`
    : 'Balloons';

  const handleOpenDetail = () => {
    debugLog('Detail button clicked, openDetail:', openDetail);
    openDetail();
  };

  const [isFullscreen, setIsFullscreen] = useState(false);

  // Track fullscreen state changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  // Handle virtual keyboard in fullscreen mode
  // This hook sets --keyboard-offset CSS variable when keyboard appears
  // Always enable on mobile to handle keyboard regardless of fullscreen state
  const isMobile = typeof window !== 'undefined' && window.innerWidth < 768;
  useVisualViewport(isFullscreen || isMobile);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      document.documentElement.requestFullscreen();
    }
  }, []);

  return (
    <>
      <button className="menu-button" onClick={openSidebar} aria-label="Open menu">
        ☰
      </button>
      <div className={`connection-status ${connectionState}`} title={connectionState} />
      <h1>{headerTitle}</h1>
      <button
        className="menu-button menu-button--fullscreen"
        onClick={toggleFullscreen}
        aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
        title={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
      >
        {isFullscreen ? '⛶' : '⛶'}
      </button>
      <button className="menu-button menu-button--right" onClick={handleOpenDetail} aria-label="Open detail panel">
        ⋮
      </button>
    </>
  );
}

// Main content tab type
// Session tabs: streaming, context, properties, slides (depend on selected session)
// Global tabs: code, logs, llm, settings (app-wide)
//
// URL ROUTING: When adding new tabs, also update:
// - docs/specs/url-routing.md (add route to URL scheme)
// - routes.ts (add route constant when created)
// - useRouter hook (add route handler when created)
export type MainContentTab = 'streaming' | 'context' | 'properties' | 'slides' | 'code' | 'logs' | 'llm' | 'settings' | 'surveys';
export type OuterTab = 'session' | 'global';

// Helper to determine which outer tab a content tab belongs to
// URL ROUTING: Add new session tabs to SESSION_TABS, global tabs to GLOBAL_TABS
const SESSION_TABS: MainContentTab[] = ['streaming', 'context', 'properties', 'slides'];
const GLOBAL_TABS: MainContentTab[] = ['code', 'logs', 'llm', 'settings', 'surveys'];

function getOuterTab(tab: MainContentTab): OuterTab {
  return SESSION_TABS.includes(tab) ? 'session' : 'global';
}

/**
 * Subtabs container with scroll indicators (arrows) when content overflows
 */
function SubtabsContainer({ children }: { children: React.ReactNode }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const updateScrollState = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;

    const hasOverflow = el.scrollWidth > el.clientWidth;
    setCanScrollLeft(hasOverflow && el.scrollLeft > 1);
    setCanScrollRight(hasOverflow && el.scrollLeft < el.scrollWidth - el.clientWidth - 1);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    // Initial check after a small delay to let layout settle
    const timeoutId = setTimeout(updateScrollState, 50);

    el.addEventListener('scroll', updateScrollState);

    // Also check on resize
    const resizeObserver = new ResizeObserver(updateScrollState);
    resizeObserver.observe(el);

    return () => {
      clearTimeout(timeoutId);
      el.removeEventListener('scroll', updateScrollState);
      resizeObserver.disconnect();
    };
  }, [updateScrollState, children]); // Re-run when children change

  const scrollBy = (amount: number) => {
    scrollRef.current?.scrollBy({ left: amount, behavior: 'smooth' });
  };

  return (
    <div className="subtabs-wrapper">
      {canScrollLeft && (
        <button
          className="subtabs-arrow subtabs-arrow-left"
          onClick={() => scrollBy(-100)}
          aria-label="Scroll left"
        >
          ‹
        </button>
      )}
      <div className="subtabs" ref={scrollRef}>
        {children}
      </div>
      {canScrollRight && (
        <button
          className="subtabs-arrow subtabs-arrow-right"
          onClick={() => scrollBy(100)}
          aria-label="Scroll right"
        >
          ›
        </button>
      )}
    </div>
  );
}

/**
 * Header bar for the main content area with two-level tabs:
 * - Outer tabs: Session | Global
 * - Subtabs: depend on which outer tab is selected
 */
export function MainContentHeader({
  activeTab,
  onTabChange,
  gitStatus,
}: {
  activeTab: MainContentTab;
  onTabChange: (tab: MainContentTab) => void;
  gitStatus?: GitStatusInfo | null;
}) {
  const { layoutMode, isDetailCollapsed, toggleDetailCollapse } = useLayout();

  // Show badge if there are git changes (unstaged or staged)
  const hasGitChanges = gitStatus && (gitStatus.hasUnstaged || gitStatus.hasStaged);

  // Determine which outer tab is active based on current subtab
  const activeOuterTab = getOuterTab(activeTab);

  // When switching outer tabs, go to the first subtab of that group
  const handleOuterTabChange = (outer: OuterTab) => {
    if (outer === 'session' && activeOuterTab !== 'session') {
      onTabChange('streaming');
    } else if (outer === 'global' && activeOuterTab !== 'global') {
      onTabChange('code');
    }
  };

  return (
    <div className="conversation-view-toggle">
      {/* Outer tabs: Session | Global */}
      <div className="outer-tabs">
        <button
          className={`outer-tab-btn ${activeOuterTab === 'session' ? 'active' : ''}`}
          onClick={() => handleOuterTabChange('session')}
        >
          Session
        </button>
        <button
          className={`outer-tab-btn ${activeOuterTab === 'global' ? 'active' : ''}`}
          onClick={() => handleOuterTabChange('global')}
        >
          Global
        </button>
      </div>

      {/* Separator */}
      <div className="tab-group-separator" />

      {/* Subtabs - show based on which outer tab is active */}
      <SubtabsContainer>
        {activeOuterTab === 'session' ? (
          <>
            <button
              className={`view-toggle-btn ${activeTab === 'streaming' ? 'active' : ''}`}
              onClick={() => onTabChange('streaming')}
            >
              Streaming
            </button>
            <button
              className={`view-toggle-btn ${activeTab === 'context' ? 'active' : ''}`}
              onClick={() => onTabChange('context')}
            >
              Context
            </button>
            <button
              className={`view-toggle-btn ${activeTab === 'properties' ? 'active' : ''}`}
              onClick={() => onTabChange('properties')}
            >
              Properties
            </button>
            <button
              className={`view-toggle-btn ${activeTab === 'slides' ? 'active' : ''}`}
              onClick={() => onTabChange('slides')}
            >
              Slides
            </button>
          </>
        ) : (
          <>
            <button
              className={`view-toggle-btn ${activeTab === 'code' ? 'active' : ''}`}
              onClick={() => onTabChange('code')}
              title={hasGitChanges ? `${gitStatus.fileCount} uncommitted change${gitStatus.fileCount !== 1 ? 's' : ''}` : undefined}
            >
              Code
              {hasGitChanges && (
                <span className="code-tab-changes-indicator" />
              )}
            </button>
            <button
              className={`view-toggle-btn ${activeTab === 'logs' ? 'active' : ''}`}
              onClick={() => onTabChange('logs')}
            >
              Logs
            </button>
            <button
              className={`view-toggle-btn ${activeTab === 'llm' ? 'active' : ''}`}
              onClick={() => onTabChange('llm')}
            >
              LLM
            </button>
            <button
              className={`view-toggle-btn ${activeTab === 'settings' ? 'active' : ''}`}
              onClick={() => onTabChange('settings')}
            >
              Settings
            </button>
            <button
              className={`view-toggle-btn ${activeTab === 'surveys' ? 'active' : ''}`}
              onClick={() => onTabChange('surveys')}
            >
              Surveys
            </button>
          </>
        )}
      </SubtabsContainer>

      {/* Detail panel toggle - only show on desktop, pushed to right */}
      {layoutMode === 'desktop' && (
        <button
          className={`view-toggle-btn detail-toggle-btn ${!isDetailCollapsed ? 'active' : ''}`}
          onClick={toggleDetailCollapse}
          title={isDetailCollapsed ? 'Show detail panel' : 'Hide detail panel'}
          style={{ marginLeft: 'auto' }}
        >
          {isDetailCollapsed ? '◀ More Stuff' : 'Less Stuff ▶'}
        </button>
      )}
    </div>
  );
}

// Sidebar view mode
export type SidebarView = 'list' | 'tree' | 'hierarchy';

// Exchange action type from SessionTreeView
export type ExchangeAction = 'archive' | 'delete';

/**
 * Session list item with long-press to rename support
 */
interface SessionListItemProps {
  session: SessionInfo;
  isSelected: boolean;
  isPinned: boolean;
  showStreamingDetails: boolean;
  streamingTask: TaskInfo | null;
  onSelect: () => void;
  onTogglePin?: () => void;
  /** Called when user wants to rename this session (long press on title) */
  onRequestRename?: () => void;
  itemRef?: (el: HTMLDivElement | null) => void;
}

function SessionListItem({
  session,
  isSelected,
  isPinned,
  showStreamingDetails,
  streamingTask,
  onSelect,
  onTogglePin,
  onRequestRename,
  itemRef,
}: SessionListItemProps) {
  const titleLongPress = useLongPress({
    onLongPress: () => {
      onRequestRename?.();
    },
    delay: 500,
  });

  return (
    <div
      ref={itemRef}
      className={`session-item ${isSelected ? 'selected' : ''} ${session.isStreaming ? 'streaming' : ''} ${isPinned ? 'pinned' : ''}`}
      onClick={onSelect}
    >
      <div className="session-header">
        {onTogglePin && (
          <span
            className={`session-pin ${isPinned ? 'session-pin--active' : ''}`}
            onClick={(e) => { e.stopPropagation(); onTogglePin(); }}
            title={isPinned ? 'Unpin session' : 'Pin session'}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill={isPinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 17v5" />
              <path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1z" />
            </svg>
          </span>
        )}
        <div
          className="session-title"
          title="Long press to rename"
          {...titleLongPress}
        >
          {session.title || session.forkName || `Session ${session.id.slice(0, 8)}`}
        </div>
      </div>
      <div className="session-meta">
        {session.messageCount} messages
        {session.isStreaming && !showStreamingDetails && ' • streaming'}
      </div>
      {showStreamingDetails && streamingTask && (
        <div className="session-streaming-info">
          <span className="streaming-badge">
            <span className="streaming-dot" />
            {streamingTask.toolName ? (
              <span>{streamingTask.toolName}</span>
            ) : (
              <span>{formatTokens(streamingTask.tokensStreamed)} tokens</span>
            )}
          </span>
        </div>
      )}
    </div>
  );
}

interface SidebarContentProps {
  connectionState: ConnectionState;
  sessions: SessionInfo[];
  /** Balloons client for rename operations */
  client?: BalloonsClient | null;
  selectedSessionId: string | null;
  selectedSession?: SessionInfo | null;
  turns: TurnInfo[];
  streamingTask: TaskInfo | null;
  onSelectSession: (sessionId: string) => void;
  onSelectTurn?: (turnIdx: number) => void;
  onTogglePin?: (sessionId: string) => void;
  onLoadTurns?: (sessionId: string) => Promise<TurnInfo[]>;
  isLoadingTurns?: boolean;
  onNewBareSession?: () => void;
  onNewBoundSession?: (entityType: string, entityId: string) => Promise<void>;
  creatingSessionFor?: string | null; // "entityType:entityId" when creating bound session
  // Exchange context menu callbacks
  onExchangeAction?: (sessionId: string, turnIndices: number[], turnIds: string[], action: ExchangeAction) => void;
  onDeleteTurn?: (sessionId: string, turnIdx: number) => void;
  // Session review callback
  onReviewSession?: (sessionId: string) => void;
  // Link session callback
  onLinkSession?: (sessionId: string) => void;
  // Watch session callback (create watcher session)
  onWatchSession?: (sessionId: string) => void;
  // Delete session callback
  onDeleteSession?: (sessionId: string) => Promise<boolean>;
  // Conclude session callback
  onConcludeSession?: (sessionId: string) => void;
  // Fork session callback
  onForkSession?: (sessionId: string) => void;
  // Server slot props
  serverSlot: ServerSlot;
  onSlotChange: (slot: ServerSlot) => void;
  // Auth
  onLogout?: () => void;
  // Archiving state
  archivingTurnIds?: Set<string>;
  // Unread sessions (finished streaming but not viewed)
  unreadSessionIds?: Set<string>;
}

export function SidebarContent({
  connectionState,
  sessions,
  client,
  selectedSessionId,
  selectedSession,
  turns,
  streamingTask,
  onSelectSession,
  onSelectTurn,
  onTogglePin,
  onLoadTurns,
  isLoadingTurns = false,
  onNewBareSession,
  onNewBoundSession,
  creatingSessionFor = null,
  onExchangeAction,
  onDeleteTurn,
  onReviewSession,
  onLinkSession,
  onWatchSession,
  onDeleteSession,
  onConcludeSession,
  onForkSession,
  serverSlot,
  onSlotChange,
  onLogout,
  archivingTurnIds,
  unreadSessionIds,
}: SidebarContentProps) {
  const { closeSidebar, layoutMode } = useLayout();

  // State for the shared rename modal (one modal, not one per session)
  const [renameModalSession, setRenameModalSession] = useState<SessionInfo | null>(null);

  // Memoized handler for closing rename modal to prevent re-renders during typing
  const handleCloseRenameModal = useCallback(() => {
    setRenameModalSession(null);
  }, []);

  // View mode state (persisted in localStorage)
  const [viewMode, setViewMode] = useState<SidebarView>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('balloons:sidebar-view');
      return (stored === 'tree' || stored === 'list' || stored === 'hierarchy') ? stored : 'list';
    }
    return 'list';
  });

  // Persist view mode changes
  const handleViewModeChange = useCallback((mode: SidebarView) => {
    setViewMode(mode);
    localStorage.setItem('balloons:sidebar-view', mode);
  }, []);

  const handleSelectSession = useCallback((sessionId: string) => {
    onSelectSession(sessionId);
    // Close sidebar on mobile after selection
    if (layoutMode === 'mobile') {
      closeSidebar();
    }
  }, [onSelectSession, closeSidebar, layoutMode]);

  // Ref for session items - keyed by session ID
  const sessionItemRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // Scroll to selected session when it changes
  useEffect(() => {
    if (selectedSessionId && viewMode === 'list') {
      const element = sessionItemRefs.current.get(selectedSessionId);
      if (element) {
        // Only scroll if the element is not fully visible
        const rect = element.getBoundingClientRect();
        const container = element.closest('.session-list');
        if (container) {
          const containerRect = container.getBoundingClientRect();
          const isVisible = rect.top >= containerRect.top && rect.bottom <= containerRect.bottom;
          if (!isVisible) {
            element.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
        }
      }
    }
  }, [selectedSessionId, viewMode]);

  // Sort sessions: pinned first, then by last modified (most recent first)
  const sortedSessions = useMemo(() => {
    return [...sessions].sort((a, b) => {
      // Pinned sessions come first
      const aPinned = a.isPinned ?? false;
      const bPinned = b.isPinned ?? false;
      if (aPinned && !bPinned) return -1;
      if (!aPinned && bPinned) return 1;

      // Then by last modified
      return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
    });
  }, [sessions]);

  // Format title: session name (or title) + hash prefix
  const headerTitle = selectedSession
    ? `${selectedSession.forkName || selectedSession.title || 'Session'} #${selectedSession.id.slice(0, 6)}`
    : 'Balloons';

  const toggleSlot = useCallback(() => {
    onSlotChange(serverSlot === 'A' ? 'B' : 'A');
  }, [serverSlot, onSlotChange]);

  return (
    <>
      <header className="sidebar-header">
        {/* Connection status with server slot indicator */}
        <button
          className={`connection-status-btn ${connectionState}`}
          onClick={toggleSlot}
          title={`${connectionState} - Server ${serverSlot} (:${SLOT_PORTS[serverSlot]}). Click to switch.`}
        >
          <span className="connection-dot" />
          <span className="server-slot">{serverSlot}</span>
        </button>
        <h1>{headerTitle}</h1>

        {onLogout && (
          <button
            className="signout-btn"
            onClick={onLogout}
            title="Sign out"
          >
            Sign out
          </button>
        )}

        {layoutMode === 'mobile' && (
          <button className="close-button" onClick={closeSidebar} aria-label="Close menu">
            ✕
          </button>
        )}
      </header>

      {/* View mode tabs */}
      <div className="sidebar-view-tabs">
        <button
          className={`sidebar-view-tab ${viewMode === 'list' ? 'active' : ''}`}
          onClick={() => handleViewModeChange('list')}
          title="List view"
        >
          List
        </button>
        <button
          className={`sidebar-view-tab ${viewMode === 'tree' ? 'active' : ''}`}
          onClick={() => handleViewModeChange('tree')}
          title="Tree view"
        >
          Tree
        </button>
        <button
          className={`sidebar-view-tab ${viewMode === 'hierarchy' ? 'active' : ''}`}
          onClick={() => handleViewModeChange('hierarchy')}
          title="Hierarchy view - unified fork tree"
        >
          Hierarchy
        </button>
      </div>

      {onNewBareSession && (
        <button
          className="new-session-row"
          onClick={onNewBareSession}
          aria-label="New session"
          title="Start new session"
        >
          + New Session
        </button>
      )}

      {viewMode === 'tree' ? (
        <SessionTreeView
          sessions={sessions}
          selectedSessionId={selectedSessionId}
          onSelectSession={handleSelectSession}
          onTogglePin={onTogglePin}
          isLoading={connectionState !== 'connected'}
          onReviewSession={onReviewSession}
          onLinkSession={onLinkSession}
          onWatchSession={onWatchSession}
          sessionDataClient={connectionState === 'connected' ? client?.sessionData : undefined}
        />
      ) : viewMode === 'hierarchy' ? (
        <HierarchyView
          sessions={sessions}
          selectedSessionId={selectedSessionId}
          onSelectSession={handleSelectSession}
          onDeleteSession={onDeleteSession}
          onLinkSession={onLinkSession}
          onConcludeSession={onConcludeSession}
          onForkSession={onForkSession}
          isLoading={connectionState !== 'connected'}
          unreadSessionIds={unreadSessionIds}
        />
      ) : (
        <div className="session-list">
          {sortedSessions.length === 0 && connectionState === 'connected' && (
            <div style={{ padding: '16px', color: '#666', textAlign: 'center' }}>
              No sessions
            </div>
          )}

          {sortedSessions.map(session => {
            const isSelected = session.id === selectedSessionId;
            const showStreamingDetails = isSelected && session.isStreaming && streamingTask;
            const isPinned = session.isPinned ?? false;
            return (
              <SessionListItem
                key={session.id}
                session={session}
                isSelected={isSelected}
                isPinned={isPinned}
                showStreamingDetails={!!showStreamingDetails}
                streamingTask={streamingTask}
                onSelect={() => handleSelectSession(session.id)}
                onTogglePin={onTogglePin ? () => onTogglePin(session.id) : undefined}
                onRequestRename={client?.isConnected ? () => setRenameModalSession(session) : undefined}
                itemRef={(el) => {
                  if (el) sessionItemRefs.current.set(session.id, el);
                  else sessionItemRefs.current.delete(session.id);
                }}
              />
            );
          })}
        </div>
      )}

      {/* Single shared rename modal for all sessions in the list */}
      {client?.isConnected && renameModalSession && (
        <RenameSessionModal
          isOpen={!!renameModalSession}
          onClose={handleCloseRenameModal}
          sessionId={renameModalSession.id}
          currentTitle={renameModalSession.title || renameModalSession.forkName || ''}
          client={client.sessions}
          sessionDataClient={client.sessionData}
          onRenamed={handleCloseRenameModal}
          onNavigateToSession={onSelectSession}
        />
      )}
    </>
  );
}
