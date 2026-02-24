/**
 * StreamingTurnsView - Virtualized chat log view using SessionDataService
 *
 * This component displays turns using the new SessionDataService subscription
 * model (turn_id based) rather than TaskStateService (turn_index based).
 *
 * Uses @tanstack/react-virtual for virtualization - only renders turns that
 * are visible in the viewport plus a small overscan buffer. This enables
 * smooth scrolling through sessions with thousands of turns.
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
import { useVirtualizer } from '@tanstack/react-virtual';
import type { BalloonsClient } from '../../../../generated/balloons-client';
import { useSessionData, type SessionDataTurn, type StreamingProgress } from '../../hooks';
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

interface StreamingTurnsViewProps {
  sessionId: string | null;
  client: BalloonsClient;
  onSelectSession?: (sessionId: string) => void;
  /** Callback when scroll state changes (for status bar display) */
  onScrollStateChange?: (state: { isFollowing: boolean; isAtBottom: boolean }) => void;
  /** Callback when streaming progress updates (for status bar token counts) */
  onStreamingProgressChange?: (progress: StreamingProgress | null) => void;
}

// Default estimated height for items before measurement
const ESTIMATED_ITEM_HEIGHT = 100;

// Overscan count - how many items to render outside the visible area
const OVERSCAN_COUNT = 5;

// Threshold in pixels to consider "at bottom"
const AT_BOTTOM_THRESHOLD = 150;

export function StreamingTurnsView({ sessionId, client, onSelectSession, onScrollStateChange, onStreamingProgressChange }: StreamingTurnsViewProps) {
  const { turns, isLoading, isSubscribed, isStreaming, streamError, error, streamingProgress } = useSessionData(client, sessionId);

  // Ref for the scrollable container
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Track whether user is following the stream (auto-scroll enabled)
  const [isFollowing, setIsFollowing] = useState(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('balloons:autoscroll-following');
      return stored !== 'false';
    }
    return true;
  });

  // Track whether we're at the bottom
  const [isAtBottom, setIsAtBottom] = useState(true);

  // Ref to track programmatic scrolls
  const isProgrammaticScrollRef = useRef(false);

  // Last scroll position for direction detection
  const lastScrollTopRef = useRef(0);

  // Memoize context value to prevent unnecessary re-renders
  const contextValue = useMemo(() => ({
    client,
    onSelectSession,
  }), [client, onSelectSession]);

  // Filter out tool_result turns - they're rendered inline with their matching tool_use
  const filteredTurns = useMemo(() => {
    return turns.filter((turn) => {
      const blockType = turn.contentBlock?.type || 'text';
      if (blockType !== 'tool_result' && turn.role !== 'tool') {
        return true;
      }
      // Check if there's a matching tool_use turn that will render this result
      const toolResultBlock = turn.contentBlock as { toolUseId?: string } | undefined;
      const toolUseId = toolResultBlock?.toolUseId;
      if (!toolUseId) return true; // No ID, render standalone
      return !turns.some(t => {
        const tBlockType = t.contentBlock?.type || 'text';
        const tToolUseBlock = t.contentBlock as { id?: string } | undefined;
        return tBlockType === 'tool_use' && tToolUseBlock?.id === toolUseId;
      });
    });
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
              key: `parallel-${currentGroupId}`,
            });
          } else {
            result.push({
              type: 'single',
              turns: currentGroup,
              key: currentGroup[0]?.turnId || `single-${result.length}`,
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
            key: turn.turnId,
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
          key: currentGroup[0]?.turnId || `single-${result.length}`,
        });
      }
    }

    return result;
  }, [filteredTurns]);

  // Set up the virtualizer
  const virtualizer = useVirtualizer({
    count: turnsOrGroups.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => ESTIMATED_ITEM_HEIGHT,
    overscan: OVERSCAN_COUNT,
    // Use item keys for stable identity across re-renders
    getItemKey: (index) => turnsOrGroups[index]?.key || index,
  });

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

    isProgrammaticScrollRef.current = true;
    setIsFollowing(true);
    setIsAtBottom(true);

    // Use virtualizer's scrollToIndex for efficiency
    virtualizer.scrollToIndex(turnsOrGroups.length - 1, {
      align: 'end',
      behavior: 'auto', // 'auto' gives instant scroll, 'smooth' animates
    });

    // Reset flag after scroll
    setTimeout(() => {
      isProgrammaticScrollRef.current = false;
    }, 50);
  }, [virtualizer, turnsOrGroups.length]);

  // Handle scroll events
  const handleScroll = useCallback(() => {
    const element = scrollContainerRef.current;
    if (!element) return;

    // Skip if programmatic scroll
    if (isProgrammaticScrollRef.current) {
      lastScrollTopRef.current = element.scrollTop;
      return;
    }

    const atBottom = checkAtBottom();
    const scrollDirection = element.scrollTop - lastScrollTopRef.current;
    lastScrollTopRef.current = element.scrollTop;

    setIsAtBottom(atBottom);

    // User scrolled UP and away from bottom - pause following
    if (scrollDirection < -10 && !atBottom) {
      setIsFollowing(false);
    }

    // User scrolled to bottom - resume following
    if (atBottom) {
      setIsFollowing(true);
    }
  }, [checkAtBottom]);

  // Attach scroll listener
  useEffect(() => {
    const element = scrollContainerRef.current;
    if (!element) return;

    element.addEventListener('scroll', handleScroll, { passive: true });
    return () => element.removeEventListener('scroll', handleScroll);
  }, [handleScroll]);

  // Auto-scroll when content changes and we're following
  useEffect(() => {
    if (!isFollowing || turnsOrGroups.length === 0) return;

    isProgrammaticScrollRef.current = true;

    // Use requestAnimationFrame to ensure DOM has updated
    requestAnimationFrame(() => {
      virtualizer.scrollToIndex(turnsOrGroups.length - 1, {
        align: 'end',
        behavior: 'auto', // 'auto' gives instant scroll
      });

      setTimeout(() => {
        isProgrammaticScrollRef.current = false;
      }, 16);
    });
  }, [turnsOrGroups.length, isFollowing, virtualizer]);

  // Re-measure items when streaming (last item may grow)
  useEffect(() => {
    if (isStreaming && turnsOrGroups.length > 0) {
      // Measure the last few items which might be changing
      const lastIndex = turnsOrGroups.length - 1;
      virtualizer.measureElement(null); // Force re-measurement
    }
  }, [isStreaming, turns, virtualizer, turnsOrGroups.length]);

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

  const virtualItems = virtualizer.getVirtualItems();

  return (
    <ClientContext.Provider value={contextValue}>
      <div
        className="streaming-turns-view-container"
        ref={scrollContainerRef}
      >
        <div className="streaming-turns-view">
          <div className="streaming-turns-header">
            <span className="session-info">
              Session: {sessionId?.substring(0, 8)}... ({turns.length} turns)
            </span>
            {isSubscribed && <span className="subscribed-badge">● subscribed</span>}
            {isStreaming && <span className="streaming-badge">● streaming</span>}
            {streamError && <span className="stream-error-badge" title={streamError}>⚠ error</span>}
          </div>

          {/* Virtualized list */}
          <div
            className="streaming-turns-list"
            style={{
              height: virtualizer.getTotalSize(),
              width: '100%',
              position: 'relative',
            }}
          >
            {virtualItems.map((virtualItem) => {
              const item = turnsOrGroups[virtualItem.index];
              if (!item) return null;

              return (
                <div
                  key={virtualItem.key}
                  data-index={virtualItem.index}
                  ref={virtualizer.measureElement}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${virtualItem.start}px)`,
                  }}
                >
                  {item.type === 'single' ? (
                    <div data-turn-order={item.turns[0]?.order}>
                      <TurnCard
                        turn={item.turns[0]!}
                        allTurns={turns}
                        sessionId={sessionId || undefined}
                      />
                    </div>
                  ) : (
                    <div className="parallel-group">
                      <div className="parallel-group-header">
                        <span className="parallel-icon">⚡</span>
                        <span className="parallel-label">{item.turns.length} parallel tool calls</span>
                      </div>
                      <div className="parallel-group-content">
                        {item.turns.map((turn) => (
                          <div key={turn.turnId} data-turn-order={turn.order}>
                            <TurnCard
                              turn={turn}
                              allTurns={turns}
                              sessionId={sessionId || undefined}
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

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
