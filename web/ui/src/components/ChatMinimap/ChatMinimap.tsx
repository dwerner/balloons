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
import type { MinimapExchange, ExchangeDOMRect } from './minimapTypes';
import { calculateMinimapLayout, calculateMinimapLayoutFromDOM, minimapYToScrollPosition, findExchangeAtPosition } from './minimapLayout';
import { renderMinimap } from './minimapRender';
import { getMinimapColors } from './minimapColors';
import './ChatMinimap.css';

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
  visible = true,
  className = '',
  width = 60,
}: ChatMinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [canvasHeight, setCanvasHeight] = useState(0);

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
    });
  }, [layout, colors, newContentFromY]);

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

  // Always render the container but hide it with CSS
  // This ensures ResizeObserver stays connected
  return (
    <div
      ref={containerRef}
      className={`chat-minimap ${className} ${isDragging ? 'chat-minimap--dragging' : ''} ${!visible ? 'chat-minimap--hidden' : ''}`}
      style={{ width }}
    >
      <canvas
        ref={canvasRef}
        className="chat-minimap__canvas"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onPointerLeave={handlePointerUp}
      />
    </div>
  );
}

export default ChatMinimap;
