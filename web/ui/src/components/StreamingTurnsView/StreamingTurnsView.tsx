/**
 * StreamingTurnsView - Chat log view using SessionDataService
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
import './StreamingTurnsView.css';

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
  /** Turn indices currently being archived (show spinner overlay) */
  archivingTurnIndices?: Set<number>;
}

// Threshold in pixels to consider "at bottom"
const AT_BOTTOM_THRESHOLD = 150;

export function StreamingTurnsView({ sessionId, client, onSelectSession, onScrollStateChange, onStreamingProgressChange, onTurnsChange, archivingTurnIndices }: StreamingTurnsViewProps) {
  // useSessionData now gets the clientId directly from client.clientId when connected
  const { turns, isLoading, isStreaming, streamError, error, streamingProgress } = useSessionData(client, sessionId);

  // Report turns changes to parent
  useEffect(() => {
    if (onTurnsChange) {
      onTurnsChange(turns);
    }
  }, [turns, onTurnsChange]);

  // Ref for the scrollable container
  const scrollContainerRef = useRef<HTMLDivElement>(null);

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

    // Use native scroll to bottom
    scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;

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

    // Skip following-state changes if this is a programmatic scroll
    // BUT only if user isn't actively scrolling (wheel takes priority)
    if (programmaticScrollCountRef.current > 0 && !userScrollingRef.current) {
      return;
    }

    // User scrolled UP and away from bottom - pause following
    // Use a more significant threshold to avoid false triggers
    if (scrollDirection < -20 && !atBottom) {
      setIsFollowing(false);
      isFollowingRef.current = false;
    }

    // User scrolled to bottom - resume following
    if (atBottom) {
      setIsFollowing(true);
      isFollowingRef.current = true;
    }
  }, [checkAtBottom]);

  // Attach scroll, wheel, and touch listeners
  useEffect(() => {
    const element = scrollContainerRef.current;
    if (!element) return;

    element.addEventListener('scroll', handleScroll, { passive: true });
    element.addEventListener('wheel', handleWheel, { passive: true });
    element.addEventListener('touchstart', handleTouchStart, { passive: true });

    return () => {
      element.removeEventListener('scroll', handleScroll);
      element.removeEventListener('wheel', handleWheel);
      element.removeEventListener('touchstart', handleTouchStart);
      if (userScrollTimeoutRef.current) {
        clearTimeout(userScrollTimeoutRef.current);
      }
    };
  }, [handleScroll, handleWheel, handleTouchStart]);

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

      // Native scroll to bottom
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;

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
      <div
        className="streaming-turns-view-container"
        ref={scrollContainerRef}
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
