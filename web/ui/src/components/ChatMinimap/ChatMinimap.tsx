/**
 * ChatMinimap - Visual overview of conversation for quick navigation
 *
 * Renders a miniaturized view of all exchanges in a conversation,
 * color-coded by role. Supports click/drag to navigate.
 *
 * Features:
 * - Exchange grouping with colored borders
 * - Turn coloring by role (user/assistant/tool/system)
 * - Parallel tool call visualization (side-by-side)
 * - Viewport indicator showing current scroll position
 * - "New content" highlight when scrolled away
 * - Click to jump, drag to scroll
 */

import React, { useRef, useState, useEffect, useCallback, useMemo } from 'react';
import type { MinimapExchange, ExchangeDOMRect, MinimapExchangeLayout } from './minimapTypes';
import { calculateMinimapLayout, calculateMinimapLayoutFromDOM, minimapYToScrollPosition, findExchangeAtPosition } from './minimapLayout';
import { renderMinimap } from './minimapRender';
import { getMinimapColors } from './minimapColors';
import './ChatMinimap.css';

/** Info for context menu */
interface ContextMenuInfo {
  x: number;
  y: number;
  exchangeLayout: MinimapExchangeLayout;
  tokenCount?: number;
  turnIndices?: number[];
}

export interface ChatMinimapProps {
  /** Exchange data to render (legacy, used if exchangeRects not provided) */
  exchanges?: MinimapExchange[];
  /** DOM-measured exchange positions (preferred - provides accurate mapping) */
  exchangeRects?: ExchangeDOMRect[];
  /** Current scroll position (pixels from top) */
  scrollTop: number;
  /** Total scrollable height */
  scrollHeight: number;
  /** Visible viewport height */
  viewportHeight: number;
  /** Whether user is following the stream (affects new content highlight) */
  isFollowing: boolean;
  /** Index of the last turn seen before scrolling away (for new content indicator) */
  lastSeenTurnIndex?: number;
  /** Callback when user clicks/drags to navigate */
  onNavigate: (scrollPosition: number) => void;
  /** Callback when user clicks on a specific exchange */
  onExchangeClick?: (exchangeId: string) => void;
  /** Callback when user requests to archive an exchange's turns */
  onArchiveExchange?: (turnIndices: number[]) => void;
  /** Currently selected/active exchange ID */
  selectedExchangeId?: string;
  /** Exchange IDs currently being archived */
  archivingExchangeIds?: Set<string>;
  /** Whether the minimap is visible */
  visible?: boolean;
  /** Additional CSS class */
  className?: string;
  /** Width of the minimap in pixels */
  width?: number;
}

export function ChatMinimap({
  exchanges,
  exchangeRects,
  scrollTop,
  scrollHeight,
  viewportHeight,
  isFollowing,
  lastSeenTurnIndex,
  onNavigate,
  onExchangeClick,
  onArchiveExchange,
  selectedExchangeId,
  archivingExchangeIds,
  visible = true,
  className = '',
  width = 60,
}: ChatMinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const contextMenuRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [canvasHeight, setCanvasHeight] = useState(0);
  const [hoveredExchangeId, setHoveredExchangeId] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuInfo | null>(null);
  const [contextMenuPosition, setContextMenuPosition] = useState<{ left: number; top: number } | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);

  // Detect theme (check for data-theme attribute or prefers-color-scheme)
  // Possible values: 'dark', 'light', 'dark-flat'
  const [theme, setTheme] = useState<string>('dark');

  useEffect(() => {
    const checkTheme = () => {
      const dataTheme = document.documentElement.getAttribute('data-theme');
      if (dataTheme) {
        setTheme(dataTheme);
      } else {
        // Fall back to system preference
        setTheme(window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      }
    };

    checkTheme();

    // Watch for theme changes
    const observer = new MutationObserver(checkTheme);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    mediaQuery.addEventListener('change', checkTheme);

    return () => {
      observer.disconnect();
      mediaQuery.removeEventListener('change', checkTheme);
    };
  }, []);

  // Get colors based on theme
  const colors = useMemo(() => getMinimapColors(theme), [theme]);

  // Track canvas height via ResizeObserver
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const newHeight = entry.contentRect.height;
        if (newHeight > 0) {
          setCanvasHeight(newHeight);
        }
      }
    });

    observer.observe(container);
    const initialHeight = container.clientHeight;
    if (initialHeight > 0) {
      setCanvasHeight(initialHeight);
    }

    return () => observer.disconnect();
  }, [visible]);

  // Re-measure when becoming visible (in case height was lost while hidden)
  useEffect(() => {
    if (visible && containerRef.current) {
      const height = containerRef.current.clientHeight;
      if (height > 0) {
        setCanvasHeight(height);
      }
    }
  }, [visible]);

  // Calculate layout - prefer DOM rects if available for accurate mapping
  const layout = useMemo(() => {
    if (canvasHeight <= 0) return null;

    if (exchangeRects && exchangeRects.length > 0) {
      // Use DOM-measured positions for accurate 1:1 mapping
      return calculateMinimapLayoutFromDOM(
        exchangeRects,
        canvasHeight,
        scrollTop,
        scrollHeight,
        viewportHeight
      );
    } else if (exchanges && exchanges.length > 0) {
      // Fall back to legacy token-based layout
      return calculateMinimapLayout(
        exchanges,
        canvasHeight,
        scrollTop,
        scrollHeight,
        viewportHeight
      );
    }

    return null;
  }, [exchanges, exchangeRects, canvasHeight, scrollTop, scrollHeight, viewportHeight]);

  // Calculate new content Y position (when scrolled away)
  const newContentFromY = useMemo(() => {
    if (isFollowing || !layout || lastSeenTurnIndex === undefined) {
      return undefined;
    }

    // Find the Y position where new content starts
    // This is after the last seen turn
    let turnCount = 0;
    for (const exLayout of layout.exchanges) {
      for (const turnLayout of exLayout.turns) {
        if (turnCount >= lastSeenTurnIndex) {
          return exLayout.y + turnLayout.y;
        }
        turnCount++;
      }
    }
    return undefined;
  }, [isFollowing, layout, lastSeenTurnIndex]);

  // Render canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !layout) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Handle high-DPI displays
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();

    // Set canvas resolution
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;

    // Scale context for high-DPI
    ctx.scale(dpr, dpr);

    // Render
    renderMinimap(ctx, layout, rect.width, rect.height, {
      colors,
      showViewport: true,
      newContentFromY,
      hoveredExchangeId: hoveredExchangeId ?? undefined,
      selectedExchangeId,
      archivingExchangeIds,
    });
  }, [layout, colors, newContentFromY, hoveredExchangeId, selectedExchangeId, archivingExchangeIds]);

  // Navigation handlers
  const handleNavigateToY = useCallback((clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas || !layout) return;

    const rect = canvas.getBoundingClientRect();
    const y = clientY - rect.top;

    // Center the viewport on the clicked position
    const targetY = y - layout.viewportHeight / 2;
    const scrollPosition = minimapYToScrollPosition(
      layout,
      targetY,
      scrollHeight,
      viewportHeight
    );

    onNavigate(scrollPosition);
  }, [layout, scrollHeight, viewportHeight, onNavigate]);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    setIsDragging(true);
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    handleNavigateToY(e.clientY);

    // Also check if clicking on a specific exchange
    if (onExchangeClick && layout) {
      const canvas = canvasRef.current;
      if (canvas) {
        const rect = canvas.getBoundingClientRect();
        const y = e.clientY - rect.top;
        const exLayout = findExchangeAtPosition(layout, y);
        if (exLayout) {
          onExchangeClick(exLayout.exchange.id);
        }
      }
    }
  }, [handleNavigateToY, onExchangeClick, layout]);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!isDragging) return;
    handleNavigateToY(e.clientY);
  }, [isDragging, handleNavigateToY]);

  const handlePointerUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  // Handle hover to show exchange highlight and tooltip
  const handlePointerMoveHover = useCallback((e: React.PointerEvent) => {
    if (isDragging) return; // Don't update hover during drag

    const canvas = canvasRef.current;
    if (!canvas || !layout) return;

    const rect = canvas.getBoundingClientRect();
    const y = e.clientY - rect.top;
    const exLayout = findExchangeAtPosition(layout, y);

    setHoveredExchangeId(exLayout?.exchange.id ?? null);

    // Show tooltip with turn range (token count is rendered in the minimap itself)
    if (exLayout) {
      const exchangeRect = exchangeRects?.find(r => r.id === exLayout.exchange.id);
      const turnRange = exLayout.turnRange || exchangeRect?.turnRange;

      if (turnRange) {
        setTooltip({
          x: e.clientX,
          y: e.clientY,
          text: turnRange,
        });
      } else {
        setTooltip(null);
      }
    } else {
      setTooltip(null);
    }
  }, [isDragging, layout, exchangeRects]);

  // Clear hover when leaving
  const handlePointerLeaveHover = useCallback(() => {
    if (!isDragging) {
      setHoveredExchangeId(null);
      setTooltip(null);
    }
  }, [isDragging]);

  // Context menu handler
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    const canvas = canvasRef.current;
    if (!canvas || !layout) return;

    const rect = canvas.getBoundingClientRect();
    const y = e.clientY - rect.top;
    const exLayout = findExchangeAtPosition(layout, y);

    if (!exLayout) {
      setContextMenu(null);
      return;
    }

    // Find the exchange rect to get token count and turn indices
    const exchangeRect = exchangeRects?.find(r => r.id === exLayout.exchange.id);

    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      exchangeLayout: exLayout,
      tokenCount: exchangeRect?.tokenCount,
      turnIndices: exchangeRect?.turnIndices,
    });
  }, [layout, exchangeRects]);

  // Close context menu
  const closeContextMenu = useCallback(() => {
    setContextMenu(null);
  }, []);

  // Handle archive action from context menu
  const handleArchive = useCallback(() => {
    if (!contextMenu?.turnIndices || !onArchiveExchange) return;
    onArchiveExchange(contextMenu.turnIndices);
    closeContextMenu();
  }, [contextMenu, onArchiveExchange, closeContextMenu]);

  // Close context menu when clicking elsewhere
  useEffect(() => {
    if (!contextMenu) return;

    const handleClick = () => closeContextMenu();
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeContextMenu();
    };

    window.addEventListener('click', handleClick);
    window.addEventListener('keydown', handleEscape);

    return () => {
      window.removeEventListener('click', handleClick);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [contextMenu, closeContextMenu]);

  // Adjust context menu position to stay within viewport
  useEffect(() => {
    if (!contextMenu) {
      setContextMenuPosition(null);
      return;
    }

    const menu = contextMenuRef.current;
    if (!menu) return;

    // Measure the menu
    const menuRect = menu.getBoundingClientRect();
    const padding = 8; // Padding from viewport edges

    let left = contextMenu.x;
    let top = contextMenu.y;

    // Adjust if going off right edge
    if (left + menuRect.width > window.innerWidth - padding) {
      left = contextMenu.x - menuRect.width;
    }

    // Adjust if going off bottom edge
    if (top + menuRect.height > window.innerHeight - padding) {
      top = contextMenu.y - menuRect.height;
    }

    // Ensure not going off left/top edges
    left = Math.max(padding, left);
    top = Math.max(padding, top);

    setContextMenuPosition({ left, top });
  }, [contextMenu]);

  // Always render the container but hide it with CSS
  // This ensures ResizeObserver stays connected
  return (
    <>
      <div
        ref={containerRef}
        className={`chat-minimap ${className} ${isDragging ? 'chat-minimap--dragging' : ''} ${!visible ? 'chat-minimap--hidden' : ''}`}
        style={{ width }}
      >
        <canvas
          ref={canvasRef}
          className="chat-minimap__canvas"
          onPointerDown={handlePointerDown}
          onPointerMove={(e) => {
            handlePointerMove(e);
            handlePointerMoveHover(e);
          }}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          onPointerLeave={(e) => {
            handlePointerUp();
            handlePointerLeaveHover();
          }}
          onContextMenu={handleContextMenu}
        />
      </div>

      {/* Hover Tooltip */}
      {tooltip && !contextMenu && (
        <div
          className="chat-minimap-tooltip"
          style={{
            position: 'fixed',
            left: tooltip.x + 12,
            top: tooltip.y - 8,
            zIndex: 999,
          }}
        >
          {tooltip.text}
        </div>
      )}

      {/* Context Menu */}
      {contextMenu && (
        <div
          ref={contextMenuRef}
          className="chat-minimap-context-menu"
          style={{
            position: 'fixed',
            // Initially position off-screen for measurement, then use calculated position
            left: contextMenuPosition?.left ?? -9999,
            top: contextMenuPosition?.top ?? -9999,
            visibility: contextMenuPosition ? 'visible' : 'hidden',
            zIndex: 1000,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Exchange info header */}
          <div className="chat-minimap-context-menu__header">
            <span className="chat-minimap-context-menu__range">
              {contextMenu.exchangeLayout.turnRange || 'Exchange'}
            </span>
            {contextMenu.tokenCount !== undefined && (
              <span className="chat-minimap-context-menu__tokens">
                {contextMenu.tokenCount.toLocaleString()} tokens
              </span>
            )}
          </div>

          {/* Archive action */}
          {onArchiveExchange && contextMenu.turnIndices && contextMenu.turnIndices.length > 0 && (
            <button
              className="chat-minimap-context-menu__action"
              onClick={handleArchive}
            >
              <span className="chat-minimap-context-menu__icon">📦</span>
              Archive
            </button>
          )}
        </div>
      )}
    </>
  );
}

export default ChatMinimap;
