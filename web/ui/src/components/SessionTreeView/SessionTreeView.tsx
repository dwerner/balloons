/**
 * SessionTreeView - Tree view showing sessions with exchanges and turns
 *
 * Following standard tree view patterns:
 * - Semantic <ul>/<li> structure
 * - Recursive node rendering
 * - CSS for visual hierarchy via padding
 * - Arrow icons for expand/collapse
 *
 * Features:
 * - Exchange grouping (user + assistant turns grouped together)
 * - Multi-selection with Shift+click (range) and Ctrl/Cmd+click (toggle)
 * - Lazy turn loading when expanding non-selected sessions
 * - Archive/delete bulk actions
 */

import React, { useState, useCallback, useMemo, memo, useEffect, useImperativeHandle, forwardRef } from 'react';
import { createPortal } from 'react-dom';
import type { SessionInfo, TurnInfo } from '../../../../generated/balloons-client';
import { createLogger } from '../../utils/debugLog';
import './SessionTreeView.css';

// Create scoped logger for this module
const debugLog = createLogger('SessionTreeView');

// Context modes for turns
export type ContextMode = 'COPY' | 'COMPRESS' | 'DROP';

// Exchange represents a user prompt + assistant response pair
export interface Exchange {
  id: string;
  userTurn: TurnInfo | null;
  assistantTurns: TurnInfo[];  // Can have multiple (e.g., tool use, then text)
  systemTurns: TurnInfo[];     // System messages in this exchange
}

// Group turns into exchanges
// Uses exchangeId when available to group related turns
function groupTurnsIntoExchanges(turns: TurnInfo[]): Exchange[] {
  const exchanges: Exchange[] = [];
  const exchangeMap = new Map<string, Exchange>();
  let exchangeIndex = 0;
  let currentExchangeId: string | null = null;

  for (const turn of turns) {
    // Check if this turn has its own exchangeId
    const turnExchangeId = turn.exchangeId;

    if (turn.role === 'user') {
      // User turn starts a new exchange
      const exchangeId = turnExchangeId || `exchange-${exchangeIndex++}`;
      const exchange: Exchange = {
        id: exchangeId,
        userTurn: turn,
        assistantTurns: [],
        systemTurns: [],
      };
      exchangeMap.set(exchangeId, exchange);
      exchanges.push(exchange);
      currentExchangeId = exchangeId;
    } else if (turn.role === 'assistant') {
      // Assistant turns belong to current exchange or create new one
      const exchangeId: string = turnExchangeId || currentExchangeId || `exchange-${exchangeIndex++}`;
      let exchange = exchangeMap.get(exchangeId);
      if (!exchange) {
        exchange = {
          id: exchangeId,
          userTurn: null,
          assistantTurns: [],
          systemTurns: [],
        };
        exchangeMap.set(exchangeId, exchange);
        exchanges.push(exchange);
        currentExchangeId = exchangeId;
      }
      exchange.assistantTurns.push(turn);
    } else {
      // System turn - check if it has its own exchangeId (e.g., archive)
      if (turnExchangeId && turnExchangeId !== currentExchangeId) {
        // System turn with unique exchangeId - create its own exchange
        const exchange: Exchange = {
          id: turnExchangeId,
          userTurn: null,
          assistantTurns: [],
          systemTurns: [turn],
        };
        exchangeMap.set(turnExchangeId, exchange);
        exchanges.push(exchange);
      } else if (currentExchangeId) {
        // Add to current exchange
        const exchange = exchangeMap.get(currentExchangeId);
        if (exchange) {
          exchange.systemTurns.push(turn);
        }
      } else {
        // System turn at start - create exchange for it
        const exchangeId = turnExchangeId || `exchange-${exchangeIndex++}`;
        const exchange: Exchange = {
          id: exchangeId,
          userTurn: null,
          assistantTurns: [],
          systemTurns: [turn],
        };
        exchangeMap.set(exchangeId, exchange);
        exchanges.push(exchange);
      }
    }
  }

  return exchanges;
}

// Session colors for visual distinction
const SESSION_COLORS = [
  '#60a5fa', // blue
  '#c084fc', // purple
  '#22d3ee', // cyan
  '#4ade80', // green
  '#facc15', // yellow
  '#f87171', // red
];

// Format token count as kt
function formatKt(tokens: number): string {
  if (tokens <= 0) return '';
  const kt = Math.ceil(tokens / 100) / 10;
  if (kt < 1) return `.${Math.floor(kt * 10)}kt`;
  return `${kt.toFixed(1)}kt`;
}

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

// Turn node component (used inside exchanges)
function TurnNode({
  turn,
  indent = false,
  onClick,
}: {
  turn: TurnInfo;
  indent?: boolean;
  onClick?: (turnIdx: number) => void;
}) {
  // Get icon based on role and content block type
  const getIcon = () => {
    if (turn.role === 'user') return '👤';
    if (turn.role === 'assistant') return '🤖';
    // System role - check content block type
    const blockType = turn.contentBlockType;
    switch (blockType) {
      case 'archive': return '📦';
      case 'fork': return '⑂';
      case 'merge': return '⤴';
      case 'merged_to': return '⤴';
      case 'link': return '🔗';
      case 'interruption': return '⚠';
      case 'error': return '✗';
      default: return '⚙';
    }
  };
  const icon = getIcon();
  const preview = (turn.content || '').slice(0, 60).replace(/\n/g, ' ');
  const tokenStr = formatKt(turn.tokens);

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onClick?.(turn.idx);
  };

  return (
    <li className={`tree-node tree-node--turn ${indent ? 'tree-node--indented' : ''}`}>
      <div
        className={`tree-node__content ${onClick ? 'tree-node__content--clickable' : ''}`}
        onClick={onClick ? handleClick : undefined}
      >
        <span key="spacer" className="tree-node__spacer" />
        <span key="turnNum" className="tree-node__turn-num">{turn.idx}</span>
        <span key="icon" className="tree-node__icon">{icon}</span>
        <span key="label" className="tree-node__label tree-node__label--muted">
          {preview || '\u00A0'}
          {(turn.content || '').length > 60 ? '...' : ''}
        </span>
        {tokenStr && (
          <span key="meta" className="tree-node__meta tree-node__meta--green">
            {tokenStr}
          </span>
        )}
      </div>
    </li>
  );
}

// Context menu for exchanges
interface ExchangeMenuProps {
  position: { x: number; y: number };
  contextMode?: ContextMode;
  onSetContextMode: (mode: ContextMode) => void;
  onArchive: () => void;
  onDelete: () => void;
  onClose: () => void;
}

function ExchangeContextMenu({
  position,
  contextMode,
  onSetContextMode,
  onArchive,
  onDelete,
  onClose,
}: ExchangeMenuProps) {
  const menuRef = React.useRef<HTMLDivElement>(null);

  // Wrap callbacks with logging
  const handleSetContextMode = useCallback((mode: ContextMode) => {
    debugLog('Context mode selected', { mode });
    onSetContextMode(mode);
  }, [onSetContextMode]);

  const handleArchive = useCallback(() => {
    debugLog('Archive action triggered');
    onArchive();
  }, [onArchive]);

  const handleDelete = useCallback(() => {
    debugLog('Delete action triggered');
    onDelete();
  }, [onDelete]);

  // Debug log when menu mounts
  useEffect(() => {
    debugLog('ExchangeContextMenu mounted', { position, contextMode });
    return () => {
      debugLog('ExchangeContextMenu unmounted');
    };
  }, [position, contextMode]);

  // Close on click outside (delay to avoid closing immediately on the opening click)
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        debugLog('ExchangeContextMenu click outside, closing');
        onClose();
      }
    };
    // Small delay to avoid the mousedown that opened the menu from closing it
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
        debugLog('ExchangeContextMenu escape pressed, closing');
        onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Use portal to render at document root to avoid overflow issues
  return createPortal(
    <div
      ref={menuRef}
      className="exchange-context-menu"
      style={{
        position: 'fixed',
        left: position.x,
        top: position.y,
        zIndex: 9999,  // Very high z-index to ensure visibility
      }}
    >
      <div className="exchange-context-menu__section">
        <div className="exchange-context-menu__label">Context Mode</div>
        <button
          className={`exchange-context-menu__item ${contextMode === 'COPY' ? 'exchange-context-menu__item--active' : ''}`}
          onClick={() => { handleSetContextMode('COPY'); onClose(); }}
        >
          <span className="exchange-context-menu__icon">📋</span>
          Copy
          <span className="exchange-context-menu__hint">Include verbatim</span>
        </button>
        <button
          className={`exchange-context-menu__item ${contextMode === 'COMPRESS' ? 'exchange-context-menu__item--active' : ''}`}
          onClick={() => { handleSetContextMode('COMPRESS'); onClose(); }}
        >
          <span className="exchange-context-menu__icon">📦</span>
          Compress
          <span className="exchange-context-menu__hint">Summarize</span>
        </button>
        <button
          className={`exchange-context-menu__item ${contextMode === 'DROP' ? 'exchange-context-menu__item--active' : ''}`}
          onClick={() => { handleSetContextMode('DROP'); onClose(); }}
        >
          <span className="exchange-context-menu__icon">🗑️</span>
          Drop
          <span className="exchange-context-menu__hint">Exclude from context</span>
        </button>
      </div>
      <div className="exchange-context-menu__divider" />
      <div className="exchange-context-menu__section">
        <button
          className="exchange-context-menu__item"
          onClick={() => { handleArchive(); onClose(); }}
        >
          <span className="exchange-context-menu__icon"><ArchiveIcon /></span>
          Archive
        </button>
        <button
          className="exchange-context-menu__item exchange-context-menu__item--danger"
          onClick={() => { handleDelete(); onClose(); }}
        >
          <span className="exchange-context-menu__icon"><TrashIcon /></span>
          Delete
        </button>
      </div>
    </div>,
    document.body
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

// Long press hook for touch devices
function useLongPress(
  onLongPress: (position: { x: number; y: number }) => void,
  onClick?: () => void,
  { delay = 500 }: { delay?: number } = {}
) {
  const timeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPressTriggeredRef = React.useRef(false);
  const isActiveRef = React.useRef(false);  // Track if we started a valid press
  const positionRef = React.useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  const start = useCallback((e: React.MouseEvent | React.TouchEvent) => {
    // Only trigger on primary button for mouse (left-click)
    if ('button' in e && e.button !== 0) return;

    isActiveRef.current = true;
    longPressTriggeredRef.current = false;

    // Capture position immediately (before React event pooling)
    if ('touches' in e) {
      const touch = e.touches[0];
      if (touch) {
        positionRef.current = { x: touch.clientX, y: touch.clientY };
      }
    } else {
      positionRef.current = { x: e.clientX, y: e.clientY };
    }

    timeoutRef.current = setTimeout(() => {
      longPressTriggeredRef.current = true;
      onLongPress(positionRef.current);
    }, delay);
  }, [onLongPress, delay]);

  const clear = useCallback((shouldTriggerClick = true) => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    // Only trigger onClick if we had an active press that wasn't a long-press
    if (shouldTriggerClick && isActiveRef.current && !longPressTriggeredRef.current && onClick) {
      onClick();
    }
    isActiveRef.current = false;
  }, [onClick]);

  return {
    onMouseDown: start,
    onMouseUp: () => clear(true),
    onMouseLeave: () => clear(false),
    onTouchStart: start,
    onTouchEnd: () => clear(true),
  };
}

// Exchange node component - groups user + assistant turns
function ExchangeNode({
  exchange,
  isExpanded,
  contextMode,
  isArchiving,
  onToggle,
  onContextModeChange,
  onArchive,
  onDelete,
  onTurnClick,
}: {
  exchange: Exchange;
  isExpanded: boolean;
  contextMode?: ContextMode;
  isArchiving?: boolean;
  onToggle: () => void;
  onContextModeChange?: (mode: ContextMode) => void;
  onArchive?: () => void;
  onDelete?: () => void;
  onTurnClick?: (turnIdx: number) => void;
}) {
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

  // Debug log when menuPosition changes
  useEffect(() => {
    if (menuPosition) {
      debugLog('menuPosition set', { menuPosition, exchangeId: exchange.id });
    }
  }, [menuPosition, exchange.id]);

  // Check if this is a system-only exchange (like archive, fork, merge)
  const isSystemOnly = !exchange.userTurn && exchange.assistantTurns.length === 0 && exchange.systemTurns.length > 0;
  const firstSystemTurn = exchange.systemTurns[0];
  const systemBlockType = firstSystemTurn?.contentBlockType;

  // Get exchange icon based on content
  const getExchangeIcon = () => {
    if (exchange.userTurn) return '💬';
    if (isSystemOnly && systemBlockType) {
      switch (systemBlockType) {
        case 'archive': return '📦';
        case 'fork': return '⑂';
        case 'merge': return '⤴';
        case 'merged_to': return '⤴';
        case 'link': return '🔗';
        case 'interruption': return '⚠';
        case 'error': return '✗';
      }
    }
    return '💬';
  };
  const exchangeIcon = getExchangeIcon();

  // Get preview text
  const userPreview = exchange.userTurn
    ? (exchange.userTurn.content || '').slice(0, 50).replace(/\n/g, ' ')
    : isSystemOnly
      ? (firstSystemTurn?.content || '').slice(0, 50).replace(/\n/g, ' ')
      : null;

  const totalTokens = (exchange.userTurn?.tokens || 0) +
    exchange.assistantTurns.reduce((sum, t) => sum + (t.tokens || 0), 0) +
    exchange.systemTurns.reduce((sum, t) => sum + (t.tokens || 0), 0);

  const tokenStr = formatKt(totalTokens);
  const turnCount = (exchange.userTurn ? 1 : 0) + exchange.assistantTurns.length + exchange.systemTurns.length;
  const hasChildren = turnCount > 1;

  // Get context mode badge color
  const getModeColor = (mode?: ContextMode) => {
    switch (mode) {
      case 'COPY': return '#4ade80';      // green
      case 'COMPRESS': return '#facc15';  // yellow
      case 'DROP': return '#f87171';      // red
      default: return undefined;
    }
  };

  const handleLongPress = useCallback((position: { x: number; y: number }) => {
    debugLog('Long press triggered', { x: position.x, y: position.y, exchangeId: exchange.id });
    setMenuPosition(position);
  }, [exchange.id]);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    debugLog('Context menu triggered', { x: e.clientX, y: e.clientY, exchangeId: exchange.id });
    setMenuPosition({ x: e.clientX, y: e.clientY });
  }, [exchange.id]);

  // Get the first turn index for jumping to the exchange
  const firstTurnIdx = exchange.systemTurns[0]?.idx
    ?? exchange.userTurn?.idx
    ?? exchange.assistantTurns[0]?.idx;

  const handleClick = useCallback(() => {
    // Jump to first turn in exchange
    if (firstTurnIdx !== undefined && onTurnClick) {
      onTurnClick(firstTurnIdx);
    }
    // Also toggle expansion
    onToggle();
  }, [firstTurnIdx, onTurnClick, onToggle]);

  const longPressHandlers = useLongPress(handleLongPress, handleClick, { delay: 500 });

  return (
    <li className="tree-node tree-node--exchange">
      <div
        className="tree-node__content"
        {...longPressHandlers}
        onContextMenu={handleContextMenu}
      >
        <span className="tree-node__toggle" onClick={(e) => { e.stopPropagation(); onToggle(); }}>
          {hasChildren ? <Arrow open={isExpanded} /> : <span className="tree-node__spacer" />}
        </span>
        <span className="tree-node__turn-num">{firstTurnIdx}</span>
        <span className="tree-node__icon">
          {isArchiving ? <span className="tree-node__spinner">⏳</span> : exchangeIcon}
        </span>
        {contextMode && (
          <span
            className="tree-node__mode-badge"
            style={{ backgroundColor: getModeColor(contextMode) }}
            title={`Context: ${contextMode}`}
          >
            {contextMode.charAt(0)}
          </span>
        )}
        <span className="tree-node__label tree-node__label--muted">
          {userPreview || (isSystemOnly ? (systemBlockType || 'System') : 'System')}
          {userPreview && userPreview.length >= 50 ? '...' : ''}
        </span>
        <span className="tree-node__meta">
          {turnCount > 1 && `${turnCount} turns`}
        </span>
        {tokenStr && (
          <span className="tree-node__meta tree-node__meta--green">
            {tokenStr}
          </span>
        )}
      </div>

      {isExpanded && hasChildren && (
        <ul className="tree-children">
          {exchange.systemTurns.map(turn => (
            <TurnNode key={turn.idx} turn={turn} indent onClick={onTurnClick} />
          ))}
          {exchange.userTurn && (
            <TurnNode key={exchange.userTurn.idx} turn={exchange.userTurn} indent onClick={onTurnClick} />
          )}
          {exchange.assistantTurns.map(turn => (
            <TurnNode key={turn.idx} turn={turn} indent onClick={onTurnClick} />
          ))}
        </ul>
      )}

      {menuPosition && (
        <ExchangeContextMenu
          position={menuPosition}
          contextMode={contextMode}
          onSetContextMode={(mode) => onContextModeChange?.(mode)}
          onArchive={() => onArchive?.()}
          onDelete={() => onDelete?.()}
          onClose={() => setMenuPosition(null)}
        />
      )}
    </li>
  );
}

// Exchange action type for callbacks
export type ExchangeAction = 'archive' | 'delete';

// Session node component
function SessionNode({
  session,
  index,
  isSelected,
  isChecked,
  isExpanded,
  turns,
  isLoadingTurns,
  showCheckboxes,
  onToggle,
  onSelect,
  onTogglePin,
  onToggleCheck,
  onExchangeContextModeChange,
  onExchangeAction,
  onTurnClick,
  onReview,
  onRename,
  onLinkSession,
  onWatchSession,
  selectedSessionId,
  archivingTurnIndices,
}: {
  session: SessionInfo;
  index: number;
  isSelected: boolean;
  isChecked: boolean;
  isExpanded: boolean;
  turns: TurnInfo[];
  isLoadingTurns: boolean;
  showCheckboxes: boolean;
  onToggle: () => void;
  onSelect: (e: React.MouseEvent) => void;
  onTogglePin?: () => void;
  onToggleCheck?: (e: React.MouseEvent) => void;
  onExchangeContextModeChange?: (turnIndices: number[], mode: ContextMode) => void;
  onExchangeAction?: (turnIndices: number[], action: ExchangeAction) => void;
  onTurnClick?: (turnIdx: number) => void;
  onReview?: () => void;
  onRename?: () => void;
  onLinkSession?: () => void;
  onWatchSession?: () => void;
  selectedSessionId: string | null;
  archivingTurnIndices?: Set<number>;
}) {
  const sessionColor = SESSION_COLORS[index % SESSION_COLORS.length] || '#60a5fa';
  const sessionName = session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
  const isPinned = session.isPinned ?? false;

  // Use message count as indicator when not expanded
  const hasContent = session.messageCount > 0;

  // Session context menu state
  const [sessionMenuPosition, setSessionMenuPosition] = useState<{ x: number; y: number } | null>(null);

  // Group turns into exchanges for display
  const exchanges = useMemo(() => {
    const result = groupTurnsIntoExchanges(turns);
    return result;
  }, [turns, session.id]);

  // Track which exchanges are expanded
  const [expandedExchanges, setExpandedExchanges] = useState<Set<string>>(new Set());

  const toggleExchange = useCallback((exchangeId: string) => {
    setExpandedExchanges(prev => {
      const next = new Set(prev);
      if (next.has(exchangeId)) {
        next.delete(exchangeId);
      } else {
        next.add(exchangeId);
      }
      return next;
    });
  }, []);

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
          {hasContent ? <Arrow open={isExpanded} color={sessionColor} /> : <span className="tree-node__spacer" />}
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

      {isExpanded && (
        <ul className="tree-children">
          {isLoadingTurns ? (
            <li className="tree-node tree-node--loading">
              <div className="tree-node__content">
                <span className="tree-node__spacer" />
                <span className="tree-node__label tree-node__label--muted">Loading...</span>
              </div>
            </li>
          ) : exchanges.length > 0 ? (
            exchanges.map(exchange => {
              // Get all turn indices in this exchange for callbacks
              const turnIndices: number[] = [
                ...exchange.systemTurns.map(t => t.idx),
                ...(exchange.userTurn ? [exchange.userTurn.idx] : []),
                ...exchange.assistantTurns.map(t => t.idx),
              ];
              // Get context mode from the first turn (they should all be the same in an exchange)
              const firstTurn = exchange.userTurn || exchange.assistantTurns[0] || exchange.systemTurns[0];
              const contextMode = firstTurn?.contextMode as ContextMode | undefined;

              // Check if any turns in this exchange are being archived
              const isArchiving = archivingTurnIndices && turnIndices.some(idx => archivingTurnIndices.has(idx));

              return (
                <ExchangeNode
                  key={exchange.id}
                  exchange={exchange}
                  isExpanded={expandedExchanges.has(exchange.id)}
                  contextMode={contextMode}
                  isArchiving={isArchiving}
                  onToggle={() => toggleExchange(exchange.id)}
                  onContextModeChange={onExchangeContextModeChange
                    ? (mode) => onExchangeContextModeChange(turnIndices, mode)
                    : undefined}
                  onArchive={onExchangeAction
                    ? () => onExchangeAction(turnIndices, 'archive')
                    : undefined}
                  onDelete={onExchangeAction
                    ? () => onExchangeAction(turnIndices, 'delete')
                    : undefined}
                  onTurnClick={onTurnClick}
                />
              );
            })
          ) : (
            <li className="tree-node tree-node--empty">
              <div className="tree-node__content">
                <span className="tree-node__spacer" />
                <span className="tree-node__label tree-node__label--muted">No messages</span>
              </div>
            </li>
          )}
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
}

// Bulk action type
export type BulkAction = 'archive' | 'delete' | 'unarchive';

// Imperative handle for external control
export interface SessionTreeViewHandle {
  /** Update or add a turn in the cache for a specific session */
  updateTurn: (sessionId: string, turn: TurnInfo) => void;
  /** Invalidate the cache for a session, forcing reload on next expand */
  invalidateCache: (sessionId: string) => void;
  /** Check if a session's turns are currently cached */
  isCached: (sessionId: string) => boolean;
}

// Props for main component
interface SessionTreeViewProps {
  sessions: SessionInfo[];
  selectedSessionId: string | null;
  turns: TurnInfo[];
  onSelectSession: (sessionId: string) => void;
  onSelectTurn?: (turnIdx: number) => void;
  onContextModeChange?: (sessionId: string, turnIdx: number, mode: ContextMode) => void;
  onExchangeContextModeChange?: (sessionId: string, turnIndices: number[], mode: ContextMode) => void;
  onExchangeAction?: (sessionId: string, turnIndices: number[], action: ExchangeAction) => void;
  onLinkSession?: (sessionId: string) => void;
  onWatchSession?: (sessionId: string) => void;
  onTogglePin?: (sessionId: string) => void;
  onBulkAction?: (sessionIds: string[], action: BulkAction) => void;
  onLoadTurns?: (sessionId: string) => Promise<TurnInfo[]>;
  onReviewSession?: (sessionId: string) => void;
  onRenameSession?: (sessionId: string) => void;
  isLoading?: boolean;
  /** Turn indices currently being archived (show spinner) */
  archivingTurnIndices?: Set<number>;
}

// Helper to sort turns by index
function sortTurnsByIdx(turns: TurnInfo[]): TurnInfo[] {
  return [...turns].sort((a, b) => a.idx - b.idx);
}

export const SessionTreeView = memo(forwardRef<SessionTreeViewHandle, SessionTreeViewProps>(function SessionTreeView({
  sessions,
  selectedSessionId,
  turns,
  onSelectSession,
  onSelectTurn,
  onTogglePin,
  onBulkAction,
  onLoadTurns,
  onExchangeContextModeChange,
  onExchangeAction,
  onReviewSession,
  onRenameSession,
  onLinkSession,
  onWatchSession,
  isLoading = false,
  archivingTurnIndices,
}, ref) {
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
  const [loadingTurns, setLoadingTurns] = useState<Set<string>>(new Set());
  const [sessionTurnsCache, setSessionTurnsCache] = useState<Map<string, TurnInfo[]>>(new Map());

  // Expose imperative methods for external cache updates
  useImperativeHandle(ref, () => ({
    updateTurn: (sessionId: string, turn: TurnInfo) => {
      // Only update if we have this session cached (don't create cache entries for non-expanded sessions)
      setSessionTurnsCache(prev => {
        if (!prev.has(sessionId)) {
          return prev; // Don't cache if not already cached
        }
        const existingTurns = prev.get(sessionId) || [];
        const turnIndex = existingTurns.findIndex(t => t.idx === turn.idx);
        let newTurns: TurnInfo[];
        if (turnIndex >= 0) {
          // Update existing turn
          newTurns = [...existingTurns];
          newTurns[turnIndex] = turn;
        } else {
          // Add new turn
          newTurns = sortTurnsByIdx([...existingTurns, turn]);
        }
        return new Map(prev).set(sessionId, newTurns);
      });
    },
    invalidateCache: (sessionId: string) => {
      setSessionTurnsCache(prev => {
        if (!prev.has(sessionId)) return prev;
        const next = new Map(prev);
        next.delete(sessionId);
        return next;
      });
    },
    isCached: (sessionId: string) => {
      return sessionTurnsCache.has(sessionId);
    },
  }), [sessionTurnsCache]);

  // Show checkboxes when any session is checked
  const showCheckboxes = checkedSessions.size > 0;

  // Auto-expand selected session when it changes
  useEffect(() => {
    if (selectedSessionId) {
      setExpandedSessions(prev => {
        if (prev.has(selectedSessionId)) return prev;
        const next = new Set(prev);
        next.add(selectedSessionId);
        return next;
      });
    }
  }, [selectedSessionId]);

  // Load turns for a session when expanding (if not selected)
  const loadTurnsForSession = useCallback(async (sessionId: string) => {
    if (!onLoadTurns || sessionTurnsCache.has(sessionId) || loadingTurns.has(sessionId)) {
      return;
    }

    setLoadingTurns(prev => new Set(prev).add(sessionId));
    try {
      const sessionTurns = await onLoadTurns(sessionId);
      setSessionTurnsCache(prev => new Map(prev).set(sessionId, sessionTurns));
    } catch (error) {
      console.error('Failed to load turns for session:', sessionId, error);
    } finally {
      setLoadingTurns(prev => {
        const next = new Set(prev);
        next.delete(sessionId);
        return next;
      });
    }
  }, [onLoadTurns, sessionTurnsCache, loadingTurns]);

  const toggleSession = useCallback((sessionId: string) => {
    setExpandedSessions(prev => {
      const next = new Set(prev);
      const isExpanding = !next.has(sessionId);
      if (isExpanding) {
        next.add(sessionId);
        // Select the session when expanding to ensure turns are loaded
        // This prevents "No messages" for sessions that weren't loaded
        if (sessionId !== selectedSessionId) {
          onSelectSession(sessionId);
        }
      } else {
        next.delete(sessionId);
      }
      return next;
    });
  }, [selectedSessionId, onSelectSession]);

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

  // Helper to get turns for a session (selected uses props, others use cache)
  const getTurnsForSession = (sessionId: string): TurnInfo[] => {
    if (sessionId === selectedSessionId) {
      return turns;
    }
    return sessionTurnsCache.get(sessionId) || [];
  };

  // Helper to render a session node with all the new props
  const renderSessionNode = (session: SessionInfo) => {
    const isSelected = session.id === selectedSessionId;
    const isChecked = checkedSessions.has(session.id);
    const isExpanded = expandedSessions.has(session.id);
    const sessionTurns = getTurnsForSession(session.id);
    const isLoadingSessionTurns = loadingTurns.has(session.id);
    const idx = sessionIndex++;

    // Handle turn click: select session if not selected, then scroll to turn
    const handleTurnClick = onSelectTurn && isSelected
      ? (turnIdx: number) => onSelectTurn(turnIdx)
      : undefined;

    return (
      <SessionNode
        key={session.id}
        session={session}
        index={idx}
        isSelected={isSelected}
        isChecked={isChecked}
        isExpanded={isExpanded}
        turns={sessionTurns}
        isLoadingTurns={isLoadingSessionTurns}
        showCheckboxes={showCheckboxes}
        onToggle={() => toggleSession(session.id)}
        onSelect={(e) => handleSessionClick(session.id, e)}
        onTogglePin={onTogglePin ? () => onTogglePin(session.id) : undefined}
        onToggleCheck={(e) => handleCheckboxClick(session.id, e)}
        onExchangeContextModeChange={onExchangeContextModeChange
          ? (turnIndices, mode) => onExchangeContextModeChange(session.id, turnIndices, mode)
          : undefined}
        onExchangeAction={onExchangeAction
          ? (turnIndices, action) => onExchangeAction(session.id, turnIndices, action)
          : undefined}
        onTurnClick={handleTurnClick}
        onReview={onReviewSession ? () => onReviewSession(session.id) : undefined}
        onRename={onRenameSession ? () => onRenameSession(session.id) : undefined}
        onLinkSession={onLinkSession ? () => onLinkSession(session.id) : undefined}
        onWatchSession={onWatchSession ? () => onWatchSession(session.id) : undefined}
        selectedSessionId={selectedSessionId}
        archivingTurnIndices={isSelected ? archivingTurnIndices : undefined}
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
}));

export default SessionTreeView;
