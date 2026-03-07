/**
 * StreamingTurnsView - Chat log view using SessionDataService (v2)
 *
 * This component displays turns using the new SessionDataService subscription
 * model (turn_id based) rather than TaskStateService (turn_index based).
 *
 * NOTE: This version renders all turns directly (no virtualization).
 * We're testing whether recent performance improvements make virtualization
 * unnecessary. If performance is poor with many turns, we can revert.
 *
 * Uses specialized card components for different content block types:
 * - TextCard: User and assistant text messages
 * - ToolUseCard: Tool calls with formatted input
 * - ToolResultCard: Tool results (or paired with ToolUseCard)
 * - SystemCard: Fork, merge, link, and other system events
 * - ForkProposalCard: Interactive fork proposal with accept/reject
 * - MergeProposalCard: Interactive merge proposal with accept/reject
 *
 * Features robust autoscroll behavior:
 * - Autoscrolls when user is near bottom (following the stream)
 * - Pauses autoscroll when user scrolls up to review
 * - Shows "scroll to bottom" indicator to resume following
 */

import React, { useMemo, useEffect, useRef, useCallback, useState } from 'react';
import type { BalloonsClient } from '../../../../generated/balloons-client';
import { useSessionData, type SessionDataTurn, type StreamingProgress } from '../../hooks';
import type { ToolResultBlock } from '../../../../generated/types';
import { TurnCard, ClientContext } from './cards';
import { ScrollToBottom } from '../ScrollToBottom';
import { ChatMinimap, type MinimapExchange, type ExchangeDOMRect } from '../ChatMinimap';
import { createLogger } from '../../utils/debugLog';
import './StreamingTurnsView.css';

const debugLog = createLogger('StreamingTurnsView');

// Re-export StreamingProgress for consumers
export type { StreamingProgress } from '../../hooks';

/**
 * Represents either a single turn or a group of parallel turns
 */
interface TurnOrGroup {
  type: 'single' | 'parallel';
  turns: SessionDataTurn[];
  parallelGroupId?: string;
  /** Unique key for React reconciliation */
  key: string;
}

/**
 * Represents a group of turns belonging to the same exchange
 */
interface ExchangeGroup {
  exchangeId: string;
  items: TurnOrGroup[];
  /** Color index for visual distinction */
  colorIndex: number;
}

interface StreamingTurnsViewProps {
  sessionId: string | null;
  client: BalloonsClient;
  onSelectSession?: (sessionId: string) => void;
  /** Callback when scroll state changes (for status bar display) */
  onScrollStateChange?: (state: { isFollowing: boolean; isAtBottom: boolean }) => void;
  /** Callback when streaming progress updates (for status bar token counts) */
  onStreamingProgressChange?: (progress: StreamingProgress | null) => void;
  /** Callback when turns change (for sharing with sidebar/tree view) */
  onTurnsChange?: (turns: SessionDataTurn[]) => void;
  /** Callback when session data loading state changes (for clearing parent loading indicators) */
  onLoadingChange?: (isLoading: boolean, error: string | null) => void;
  /** Turn indices currently being archived (show spinner overlay) */
  archivingTurnIndices?: Set<number>;
  /** Increment to force re-subscription (e.g., after archive) */
  refreshKey?: number;
}

// Threshold in pixels to consider "at bottom"
const AT_BOTTOM_THRESHOLD = 150;

export function StreamingTurnsView({ sessionId, client, onSelectSession, onScrollStateChange, onStreamingProgressChange, onTurnsChange, onLoadingChange, archivingTurnIndices, refreshKey }: StreamingTurnsViewProps) {
  // useSessionData now gets the clientId directly from client.clientId when connected
  // refreshKey forces re-subscription when incremented (e.g., after archive)
  const { turns, isLoading, isStreaming, streamError, error, streamingProgress } = useSessionData(client, sessionId, refreshKey);

  // Debug: log turns on every change
  useEffect(() => {
    if (turns.length > 0) {
      const orders = turns.map(t => t.order);
      const minOrder = Math.min(...orders);
      const maxOrder = Math.max(...orders);
      debugLog(`turns changed: count=${turns.length}, orders=${minOrder}-${maxOrder}`, {
        firstFive: turns.slice(0, 5).map(t => ({ order: t.order, type: t.contentBlock?.type, role: t.role }))
      });
    }
  }, [turns]);

  // Report turns changes to parent
  useEffect(() => {
    if (onTurnsChange) {
      onTurnsChange(turns);
    }
  }, [turns, onTurnsChange]);

  // Report loading state changes to parent (for clearing parent loading indicators)
  useEffect(() => {
    if (onLoadingChange) {
      onLoadingChange(isLoading, error);
    }
  }, [isLoading, error, onLoadingChange]);

  // Ref for the scrollable container
  // Also track the element in state so we can re-run effects when it changes
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [scrollContainerElement, setScrollContainerElement] = useState<HTMLDivElement | null>(null);

  // Callback ref to track when the DOM element actually changes
  const scrollContainerCallbackRef = useCallback((node: HTMLDivElement | null) => {
    scrollContainerRef.current = node;
    setScrollContainerElement(node);
  }, []);

  // Track whether user is following the stream (auto-scroll enabled)
  // Use a ref alongside state to avoid race conditions during rapid updates
  const [isFollowing, setIsFollowing] = useState(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('balloons:autoscroll-following');
      return stored !== 'false';
    }
    return true;
  });
  const isFollowingRef = useRef(isFollowing);

  // Track whether we're at the bottom
  const [isAtBottom, setIsAtBottom] = useState(true);

  // Ref to track programmatic scrolls - use a counter to handle overlapping scrolls
  const programmaticScrollCountRef = useRef(0);

  // Track if user is actively scrolling via wheel/touch (direct user input)
  // This takes priority over programmatic scroll detection
  const userScrollingRef = useRef(false);
  const userScrollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Last scroll position for direction detection
  const lastScrollTopRef = useRef(0);

  // Keep ref in sync with state
  useEffect(() => {
    isFollowingRef.current = isFollowing;
  }, [isFollowing]);

  // Memoize context value to prevent unnecessary re-renders
  // Include scrollContainerRef for IntersectionObserver-based lazy loading
  const contextValue = useMemo(() => ({
    client,
    onSelectSession,
    scrollContainerRef,
  }), [client, onSelectSession]);

  // Build a lookup map from tool_use ID to matching tool_result turn
  // This avoids O(n²) scans when rendering each TurnCard
  const toolResultMap = useMemo(() => {
    const map = new Map<string, SessionDataTurn>();
    for (const turn of turns) {
      if (turn.contentBlock?.type === 'tool_result') {
        const resultBlock = turn.contentBlock as ToolResultBlock;
        if (resultBlock.toolUseId) {
          map.set(resultBlock.toolUseId, turn);
        }
      }
    }
    return map;
  }, [turns]);

  // Filter out tool_result turns - they're rendered inline with their matching tool_use
  const filteredTurns = useMemo(() => {
    const filtered = turns.filter((turn) => {
      const blockType = turn.contentBlock?.type || 'text';
      if (blockType !== 'tool_result' && turn.role !== 'tool') {
        return true;
      }
      // Check if there's a matching tool_use turn that will render this result
      const toolResultBlock = turn.contentBlock as { toolUseId?: string } | undefined;
      const toolUseId = toolResultBlock?.toolUseId;
      if (!toolUseId) return true; // No ID, render standalone
      // Use our pre-built map to check for matching tool_use
      return !turns.some(t => {
        const tBlockType = t.contentBlock?.type || 'text';
        const tToolUseBlock = t.contentBlock as { id?: string } | undefined;
        return tBlockType === 'tool_use' && tToolUseBlock?.id === toolUseId;
      });
    });
    // Debug: log filtered vs unfiltered
    if (turns.length > 0 && filtered.length !== turns.length) {
      debugLog(`filteredTurns: ${filtered.length} of ${turns.length} kept`);
    }
    if (filtered.length > 0) {
      const orders = filtered.map(t => t.order);
      const minOrder = Math.min(...orders);
      const maxOrder = Math.max(...orders);
      debugLog(`filteredTurns orders: ${minOrder}-${maxOrder}`);
    }
    return filtered;
  }, [turns]);

  // Group consecutive turns with the same parallelGroupId
  const turnsOrGroups = useMemo((): TurnOrGroup[] => {
    const result: TurnOrGroup[] = [];
    let currentGroup: SessionDataTurn[] = [];
    let currentGroupId: string | undefined;

    for (const turn of filteredTurns) {
      const groupId = turn.parallelGroupId;

      if (groupId && groupId === currentGroupId) {
        // Continue the current parallel group
        currentGroup.push(turn);
      } else {
        // Flush the previous group if any
        if (currentGroup.length > 0) {
          if (currentGroup.length > 1) {
            result.push({
              type: 'parallel',
              turns: currentGroup,
              parallelGroupId: currentGroupId,
              key: `parallel-${currentGroupId}-${result.length}`,
            });
          } else {
            result.push({
              type: 'single',
              turns: currentGroup,
              key: `${currentGroup[0]?.turnId || 'single'}-${result.length}`,
            });
          }
        }

        // Start a new group or single turn
        if (groupId) {
          currentGroup = [turn];
          currentGroupId = groupId;
        } else {
          result.push({
            type: 'single',
            turns: [turn],
            key: `${turn.turnId}-${result.length}`,
          });
          currentGroup = [];
          currentGroupId = undefined;
        }
      }
    }

    // Flush any remaining group
    if (currentGroup.length > 0) {
      if (currentGroup.length > 1) {
        result.push({
          type: 'parallel',
          turns: currentGroup,
          parallelGroupId: currentGroupId,
          key: `parallel-${currentGroupId}`,
        });
      } else {
        result.push({
          type: 'single',
          turns: currentGroup,
          key: `${currentGroup[0]?.turnId || 'single'}-flush-${result.length}`,
        });
      }
    }

    return result;
  }, [filteredTurns]);

  // Group turnsOrGroups by exchangeId for visual grouping
  const exchangeGroups = useMemo((): ExchangeGroup[] => {
    const groups: ExchangeGroup[] = [];
    let currentExchangeId: string | undefined;
    let currentGroup: TurnOrGroup[] = [];
    let colorIndex = 0;
    const exchangeColorMap = new Map<string, number>();

    for (const item of turnsOrGroups) {
      // Get exchangeId from first turn in the item
      const exchangeId = item.turns[0]?.exchangeId;

      if (exchangeId && exchangeId === currentExchangeId) {
        // Continue current exchange group
        currentGroup.push(item);
      } else {
        // Flush previous group
        if (currentGroup.length > 0 && currentExchangeId) {
          groups.push({
            exchangeId: currentExchangeId,
            items: currentGroup,
            colorIndex: exchangeColorMap.get(currentExchangeId) ?? 0,
          });
        }
        // Start new group
        currentGroup = [item];
        currentExchangeId = exchangeId;
        if (exchangeId && !exchangeColorMap.has(exchangeId)) {
          exchangeColorMap.set(exchangeId, colorIndex++ % 6);
        }
      }
    }

    // Flush remaining
    if (currentGroup.length > 0 && currentExchangeId) {
      groups.push({
        exchangeId: currentExchangeId,
        items: currentGroup,
        colorIndex: exchangeColorMap.get(currentExchangeId) ?? 0,
      });
    } else if (currentGroup.length > 0) {
      // Turns without exchangeId - create group with empty exchangeId
      groups.push({
        exchangeId: '',
        items: currentGroup,
        colorIndex: 0,
      });
    }

    return groups;
  }, [turnsOrGroups]);

  // Convert exchange groups to minimap format
  const minimapExchanges = useMemo((): MinimapExchange[] => {
    return exchangeGroups.map((group) => ({
      id: group.exchangeId,
      colorIndex: group.colorIndex,
      turns: group.items.flatMap((item) =>
        item.turns.map((turn) => ({
          id: turn.turnId,
          role: turn.role as 'user' | 'assistant' | 'system' | 'tool',
          contentType: turn.contentBlock?.type || 'text',
          tokens: turn.tokens || 100, // Default to 100 if no token count
          parallelGroupId: turn.parallelGroupId,
        }))
      ),
    }));
  }, [exchangeGroups]);

  // Minimap visibility state (persisted to localStorage)
  const [showMinimap, setShowMinimap] = useState(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('balloons:minimap-visible');
      // Default to true on desktop, false on mobile
      if (stored !== null) return stored === 'true';
      return window.innerWidth > 768;
    }
    return true;
  });

  // Persist minimap visibility
  useEffect(() => {
    localStorage.setItem('balloons:minimap-visible', String(showMinimap));
  }, [showMinimap]);

  // Track scroll metrics for minimap
  const [scrollMetrics, setScrollMetrics] = useState({
    scrollTop: 0,
    scrollHeight: 0,
    clientHeight: 0,
  });

  // DOM-measured exchange positions for accurate minimap
  const [exchangeRects, setExchangeRects] = useState<ExchangeDOMRect[]>([]);
  const exchangeRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());

  // Measure exchange DOM positions for minimap
  const measureExchanges = useCallback(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) return;

    const rects: ExchangeDOMRect[] = [];
    const containerTop = scrollContainer.getBoundingClientRect().top;
    const scrollOffset = scrollContainer.scrollTop;

    exchangeRefsMap.current.forEach((element, id) => {
      if (!element) return;
      const rect = element.getBoundingClientRect();

      // Calculate position relative to scroll container's scroll origin
      const top = rect.top - containerTop + scrollOffset;

      // Find the exchange group to get color index and turn range
      const group = exchangeGroups.find(g => g.exchangeId === id);

      // Calculate turn range from the exchange group
      let turnRange: string | undefined;
      if (group) {
        const allTurns = group.items.flatMap(item => item.turns);
        const firstOrder = allTurns[0]?.order;
        const lastOrder = allTurns[allTurns.length - 1]?.order;
        if (firstOrder !== undefined) {
          turnRange = firstOrder === lastOrder ? `#${firstOrder}` : `#${firstOrder}-${lastOrder}`;
        }
      }

      rects.push({
        id,
        colorIndex: group?.colorIndex ?? 0,
        top,
        height: rect.height,
        turnRange,
      });
    });

    // Sort by top position
    rects.sort((a, b) => a.top - b.top);

    setExchangeRects(rects);
  }, [exchangeGroups]);

  // Measure exchanges when content changes
  useEffect(() => {
    // Defer measurement to allow DOM to settle
    const timeout = setTimeout(measureExchanges, 50);
    return () => clearTimeout(timeout);
  }, [exchangeGroups.length, measureExchanges]);

  // Also measure on scroll (in case of lazy-loaded content)
  useEffect(() => {
    if (scrollContainerRef.current) {
      // Debounced measurement on scroll
      let timeout: ReturnType<typeof setTimeout>;
      const handleScroll = () => {
        clearTimeout(timeout);
        timeout = setTimeout(measureExchanges, 100);
      };
      scrollContainerRef.current.addEventListener('scroll', handleScroll, { passive: true });
      return () => {
        clearTimeout(timeout);
        scrollContainerRef.current?.removeEventListener('scroll', handleScroll);
      };
    }
  }, [scrollContainerElement, measureExchanges]);

  // Track the last turn index seen before scrolling away (for "new content" indicator)
  const lastSeenTurnIndexRef = useRef<number>(turnsOrGroups.length);

  // Update lastSeenTurnIndex when following
  useEffect(() => {
    if (isFollowing) {
      lastSeenTurnIndexRef.current = turnsOrGroups.length;
    }
  }, [isFollowing, turnsOrGroups.length]);

  // Update scroll metrics when content changes (needed for minimap to size correctly)
  useEffect(() => {
    const element = scrollContainerRef.current;
    if (!element) return;

    // Use RAF to ensure DOM has updated
    requestAnimationFrame(() => {
      if (scrollContainerRef.current) {
        setScrollMetrics({
          scrollTop: scrollContainerRef.current.scrollTop,
          scrollHeight: scrollContainerRef.current.scrollHeight,
          clientHeight: scrollContainerRef.current.clientHeight,
        });
      }
    });
  }, [turnsOrGroups.length, exchangeGroups.length]);

  // Report scroll state changes to parent (for status bar indicator)
  useEffect(() => {
    if (onScrollStateChange) {
      onScrollStateChange({ isFollowing, isAtBottom });
    }
  }, [isFollowing, isAtBottom, onScrollStateChange]);

  // Report streaming progress changes to parent (for status bar token counts)
  useEffect(() => {
    if (onStreamingProgressChange) {
      onStreamingProgressChange(streamingProgress);
    }
  }, [streamingProgress, onStreamingProgressChange]);

  // Persist isFollowing to localStorage
  useEffect(() => {
    localStorage.setItem('balloons:autoscroll-following', String(isFollowing));
  }, [isFollowing]);

  // Check if we're at the bottom
  const checkAtBottom = useCallback(() => {
    const element = scrollContainerRef.current;
    if (!element) return false;

    const { scrollTop, scrollHeight, clientHeight } = element;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    return distanceFromBottom <= AT_BOTTOM_THRESHOLD;
  }, []);

  // Scroll to bottom and resume following
  const scrollToBottom = useCallback(() => {
    if (!scrollContainerRef.current) return;

    programmaticScrollCountRef.current++;
    setIsFollowing(true);
    isFollowingRef.current = true;
    setIsAtBottom(true);

    const element = scrollContainerRef.current;

    // Use scrollTo with behavior smooth for better UX, then force to exact bottom
    element.scrollTo({
      top: element.scrollHeight,
      behavior: 'instant'
    });

    // Double-check we're at the bottom after a short delay (DOM might update)
    requestAnimationFrame(() => {
      if (scrollContainerRef.current) {
        scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
      }
      setTimeout(() => {
        programmaticScrollCountRef.current = Math.max(0, programmaticScrollCountRef.current - 1);
      }, 50);
    });
  }, []);

  // Handle minimap navigation - scroll to position and pause following
  const handleMinimapNavigate = useCallback((scrollPosition: number) => {
    if (!scrollContainerRef.current) return;

    programmaticScrollCountRef.current++;

    // Pause following when using minimap to navigate
    setIsFollowing(false);
    isFollowingRef.current = false;

    scrollContainerRef.current.scrollTop = scrollPosition;

    // Reset flag after scroll settles
    setTimeout(() => {
      programmaticScrollCountRef.current = Math.max(0, programmaticScrollCountRef.current - 1);
    }, 100);
  }, []);

  // Mark user as actively scrolling - used by wheel and touch handlers
  const markUserScrolling = useCallback(() => {
    userScrollingRef.current = true;
    if (userScrollTimeoutRef.current) {
      clearTimeout(userScrollTimeoutRef.current);
    }
    // Clear the flag after user stops scrolling for a bit
    userScrollTimeoutRef.current = setTimeout(() => {
      userScrollingRef.current = false;
    }, 150);
  }, []);

  // Handle wheel events - direct user input, should always take priority
  const handleWheel = useCallback((e: WheelEvent) => {
    // Any upward wheel movement (negative deltaY = scrolling up) immediately stops following
    if (e.deltaY < 0) {
      setIsFollowing(false);
      isFollowingRef.current = false;
    }
    markUserScrolling();
  }, [markUserScrolling]);

  // Handle touch events - for mobile scroll support
  const handleTouchStart = useCallback(() => {
    // User touching the screen = they might scroll, prepare to respect their intent
    markUserScrolling();
  }, [markUserScrolling]);

  // Handle scroll events (fires for both user and programmatic scrolls)
  const handleScroll = useCallback(() => {
    const element = scrollContainerRef.current;
    if (!element) return;

    const atBottom = checkAtBottom();
    const scrollDirection = element.scrollTop - lastScrollTopRef.current;

    lastScrollTopRef.current = element.scrollTop;

    setIsAtBottom(atBottom);

    // Update scroll metrics for minimap
    setScrollMetrics({
      scrollTop: element.scrollTop,
      scrollHeight: element.scrollHeight,
      clientHeight: element.clientHeight,
    });

    // Skip following-state changes if this is a programmatic scroll
    // Check this FIRST to avoid fighting with scrollToBottom/auto-scroll
    if (programmaticScrollCountRef.current > 0 && !userScrollingRef.current) {
      return;
    }

    // User scrolled UP - pause following (only if not programmatic)
    if (scrollDirection < -5) {
      setIsFollowing(false);
      isFollowingRef.current = false;
      return;
    }

    // User scrolled DOWN to bottom - resume following
    if (atBottom && scrollDirection > 5 && !isFollowingRef.current) {
      setIsFollowing(true);
      isFollowingRef.current = true;
    }
  }, [checkAtBottom]);

  // Attach scroll, wheel, and touch listeners
  useEffect(() => {
    const element = scrollContainerRef.current;
    if (!element) return;

    // Initialize scroll metrics on mount
    const updateScrollMetrics = () => {
      if (scrollContainerRef.current) {
        setScrollMetrics({
          scrollTop: scrollContainerRef.current.scrollTop,
          scrollHeight: scrollContainerRef.current.scrollHeight,
          clientHeight: scrollContainerRef.current.clientHeight,
        });
      }
    };

    updateScrollMetrics();

    element.addEventListener('scroll', handleScroll, { passive: true });
    element.addEventListener('wheel', handleWheel, { passive: true });
    element.addEventListener('touchstart', handleTouchStart, { passive: true });

    // Use ResizeObserver to detect content size changes
    // When content grows (e.g., large tool result loads) and we're following,
    // we need to scroll to bottom and protect against scroll-up detection
    let lastScrollHeight = element.scrollHeight;
    const resizeObserver = new ResizeObserver(() => {
      updateScrollMetrics();

      // Check if scrollHeight increased (content grew)
      const newScrollHeight = element.scrollHeight;
      if (newScrollHeight > lastScrollHeight && isFollowingRef.current && !userScrollingRef.current) {
        // Content grew while following - auto-scroll to bottom
        programmaticScrollCountRef.current++;
        element.scrollTop = newScrollHeight;
        setTimeout(() => {
          programmaticScrollCountRef.current = Math.max(0, programmaticScrollCountRef.current - 1);
        }, 100);
      }
      lastScrollHeight = newScrollHeight;
    });
    resizeObserver.observe(element);

    return () => {
      element.removeEventListener('scroll', handleScroll);
      element.removeEventListener('wheel', handleWheel);
      element.removeEventListener('touchstart', handleTouchStart);
      resizeObserver.disconnect();
      if (userScrollTimeoutRef.current) {
        clearTimeout(userScrollTimeoutRef.current);
      }
    };
  }, [handleScroll, handleWheel, handleTouchStart, scrollContainerElement]);

  // Auto-scroll when NEW content arrives and we're following
  // Use ref to check following state to avoid race conditions with setState
  const prevTurnsLengthRef = useRef(turnsOrGroups.length);
  useEffect(() => {
    const prevLength = prevTurnsLengthRef.current;
    const currentLength = turnsOrGroups.length;
    prevTurnsLengthRef.current = currentLength;

    // Only scroll if content was ADDED (not on initial load or removals)
    // and user is following (check ref to avoid race conditions)
    if (currentLength <= prevLength || currentLength === 0) return;
    if (!isFollowingRef.current) return;

    // Don't fight with user - if they're actively scrolling, skip this update
    if (userScrollingRef.current) return;

    programmaticScrollCountRef.current++;

    // Use requestAnimationFrame to ensure DOM has updated
    requestAnimationFrame(() => {
      // Double-check we're still following and user isn't scrolling
      if (!isFollowingRef.current || userScrollingRef.current || !scrollContainerRef.current) {
        programmaticScrollCountRef.current = Math.max(0, programmaticScrollCountRef.current - 1);
        return;
      }

      const element = scrollContainerRef.current;

      // Native scroll to bottom
      element.scrollTop = element.scrollHeight;

      // Update scroll metrics for minimap
      setScrollMetrics({
        scrollTop: element.scrollTop,
        scrollHeight: element.scrollHeight,
        clientHeight: element.clientHeight,
      });

      setTimeout(() => {
        programmaticScrollCountRef.current = Math.max(0, programmaticScrollCountRef.current - 1);
      }, 50);
    });
  }, [turnsOrGroups.length]);

  // Early returns AFTER all hooks have been called
  if (!sessionId) {
    return <div className="streaming-turns-view empty">No session selected</div>;
  }

  if (isLoading) {
    return (
      <div className="streaming-turns-view loading">
        <div className="loading-spinner-container">
          <span className="loading-spinner" />
          <span className="loading-text">Loading session...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return <div className="streaming-turns-view error">{error}</div>;
  }

  // Show scroll-to-bottom button when user has scrolled away
  const showScrollIndicator = !isFollowing;

  return (
    <ClientContext.Provider value={contextValue}>
      <div className="streaming-turns-view-wrapper">
        {/* Minimap toggle button - outside scroll container so it stays fixed */}
        <button
          className={`chat-minimap-toggle ${showMinimap ? 'chat-minimap-toggle--active chat-minimap-toggle--with-minimap' : ''}`}
          style={{ '--minimap-width': '60px' } as React.CSSProperties}
          onClick={() => setShowMinimap(!showMinimap)}
          title={showMinimap ? 'Hide minimap' : 'Show minimap'}
          aria-label={showMinimap ? 'Hide minimap' : 'Show minimap'}
        >
          <svg
            className="chat-minimap-toggle__icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            {/* Minimap icon: small rectangles representing overview */}
            <rect x="3" y="3" width="7" height="4" rx="1" />
            <rect x="3" y="10" width="7" height="4" rx="1" />
            <rect x="3" y="17" width="7" height="4" rx="1" />
            <rect x="14" y="3" width="7" height="18" rx="1" />
          </svg>
        </button>

        {/* Minimap - outside scroll container */}
        <ChatMinimap
          exchangeRects={exchangeRects}
          exchanges={minimapExchanges}
          scrollTop={scrollMetrics.scrollTop}
          scrollHeight={scrollMetrics.scrollHeight}
          viewportHeight={scrollMetrics.clientHeight}
          isFollowing={isFollowing}
          lastSeenTurnIndex={lastSeenTurnIndexRef.current}
          onNavigate={handleMinimapNavigate}
          visible={showMinimap && exchangeRects.length > 0}
          width={60}
        />

        <div
          className={`streaming-turns-view-container ${showMinimap ? 'streaming-turns-view-container--with-minimap' : ''}`}
          ref={scrollContainerCallbackRef}
        >
        <div className="streaming-turns-view">
          {/* Direct rendering of all turns grouped by exchange */}
          <div className="streaming-turns-list">
            {exchangeGroups.map((exchangeGroup, groupIndex) => {
              // Compute exchange stats for header/footer
              const allTurnsInExchange = exchangeGroup.items.flatMap(item => item.turns);
              const firstTurn = allTurnsInExchange[0];
              const lastTurn = allTurnsInExchange[allTurnsInExchange.length - 1];
              const turnCount = allTurnsInExchange.length;
              const totalTokens = allTurnsInExchange.reduce((sum, t) => sum + (t.tokens || 0), 0);
              const firstOrder = firstTurn?.order ?? 0;
              const lastOrder = lastTurn?.order ?? firstOrder;
              const turnRange = firstOrder === lastOrder ? `#${firstOrder}` : `#${firstOrder}-${lastOrder}`;
              const timestamp = firstTurn?.timestamp ? new Date(firstTurn.timestamp).toLocaleTimeString() : '';

              // Check if any turns in this exchange are being archived
              const isArchivingExchange = archivingTurnIndices && allTurnsInExchange.some(
                t => archivingTurnIndices.has(t.order ?? -1)
              );

              return (
                <div
                  key={`${exchangeGroup.exchangeId || 'no-exchange'}-${groupIndex}`}
                  ref={(el) => {
                    const id = exchangeGroup.exchangeId;
                    if (id) {
                      if (el) {
                        exchangeRefsMap.current.set(id, el);
                      } else {
                        exchangeRefsMap.current.delete(id);
                      }
                    }
                  }}
                  className={`exchange-group exchange-group--color-${exchangeGroup.colorIndex} ${isArchivingExchange ? 'exchange-group--archiving' : ''}`}
                  data-exchange-id={exchangeGroup.exchangeId || undefined}
                >
                  {/* Archiving overlay */}
                  {isArchivingExchange && (
                    <div className="exchange-group__archiving-overlay">
                      <span className="exchange-group__archiving-icon">📦</span>
                      <span className="exchange-group__archiving-text">Archiving...</span>
                    </div>
                  )}
                  {/* Exchange header */}
                  <div className="exchange-group__header">
                    <span className="exchange-group__turn-range">{turnRange}</span>
                    {timestamp && <span className="exchange-group__timestamp">{timestamp}</span>}
                  </div>

                  {exchangeGroup.items.map((item, index) => (
                  <div key={item.key} data-index={index}>
                    {item.type === 'single' ? (
                      <div data-turn-order={item.turns[0]?.order}>
                        <TurnCard
                          turn={item.turns[0]!}
                          toolResultMap={toolResultMap}
                          sessionId={sessionId || undefined}
                        />
                      </div>
                    ) : (
                      <div className="parallel-group">
                        <div className="parallel-group-header">
                          <span className="turn-order">
                            {item.turns.length > 1
                              ? `${item.turns[0]?.order}-${item.turns[item.turns.length - 1]?.order}`
                              : item.turns[0]?.order}
                          </span>
                          <span className="parallel-icon">⚡</span>
                          <span className="parallel-label">{item.turns.length} parallel tool calls</span>
                        </div>
                        <div className="parallel-group-content">
                          {item.turns.map((turn) => (
                            <div key={turn.turnId} data-turn-order={turn.order}>
                              <TurnCard
                                turn={turn}
                                toolResultMap={toolResultMap}
                                sessionId={sessionId || undefined}
                              />
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}

                  {/* Exchange footer */}
                  <div className="exchange-group__footer">
                    <span className="exchange-group__turn-count">{turnCount} {turnCount === 1 ? 'turn' : 'turns'}</span>
                    {totalTokens > 0 && <span className="exchange-group__tokens">{totalTokens.toLocaleString()} tokens</span>}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Loading state when session is being loaded */}
          {isLoading && turns.length === 0 && (
            <div className="empty-session-placeholder">
              <div className="loading-spinner-container">
                <span className="streaming-dots">
                  <span className="dot">●</span>
                  <span className="dot">●</span>
                  <span className="dot">●</span>
                </span>
              </div>
              <div className="empty-title">Loading Session...</div>
            </div>
          )}

          {/* Empty state when no turns and not streaming/loading */}
          {!isStreaming && !isLoading && turns.length === 0 && (
            <div className="empty-session-placeholder">
              <div className="empty-icon">💬</div>
              <div className="empty-title">New Session</div>
              <div className="empty-description">
                Send a message to start the conversation.
              </div>
            </div>
          )}

          {/* Streaming placeholder when no turns yet */}
          {isStreaming && turns.length === 0 && (
            <div className="streaming-placeholder">
              <span className="streaming-dots">
                <span className="dot">●</span>
                <span className="dot">●</span>
                <span className="dot">●</span>
              </span>
              <span>Waiting for response...</span>
            </div>
          )}
        </div>
      </div>

        {/* ScrollToBottom - outside scroll container so it stays fixed */}
        <ScrollToBottom
          visible={showScrollIndicator}
          onClick={scrollToBottom}
          isStreaming={isStreaming}
        />
      </div>
    </ClientContext.Provider>
  );
}

export default StreamingTurnsView;
