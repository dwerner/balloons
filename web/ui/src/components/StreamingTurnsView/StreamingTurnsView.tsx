/**
 * StreamingTurnsView - Chat log view using SessionDataService
 *
 * This component displays turns using the new SessionDataService subscription
 * model (turn_id based) rather than TaskStateService (turn_index based).
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

import React, { useMemo, useEffect } from 'react';
import type { BalloonsClient } from '../../../../generated/balloons-client';
import { useSessionData, useAutoScroll, type SessionDataTurn } from '../../hooks';
import { TurnCard, ClientContext } from './cards';
import { ScrollToBottom } from '../ScrollToBottom';
import './StreamingTurnsView.css';

/**
 * Represents either a single turn or a group of parallel turns
 */
interface TurnOrGroup {
  type: 'single' | 'parallel';
  turns: SessionDataTurn[];
  parallelGroupId?: string;
}

interface StreamingTurnsViewProps {
  sessionId: string | null;
  client: BalloonsClient;
  onSelectSession?: (sessionId: string) => void;
  /** Callback when scroll state changes (for status bar display) */
  onScrollStateChange?: (state: { isFollowing: boolean; isAtBottom: boolean }) => void;
}

export function StreamingTurnsView({ sessionId, client, onSelectSession, onScrollStateChange }: StreamingTurnsViewProps) {
  const { turns, isLoading, isSubscribed, isStreaming, streamError, error } = useSessionData(client, sessionId);

  // Memoize context value to prevent unnecessary re-renders
  const contextValue = useMemo(() => ({
    client,
    onSelectSession,
  }), [client, onSelectSession]);

  // Robust autoscroll: follows stream, pauses on user scroll-up, resumes on click
  const { scrollRef, isFollowing, isAtBottom, scrollToBottom } = useAutoScroll({
    deps: [turns], // Re-check scroll position when turns change
    threshold: 150, // Consider "at bottom" within 150px
    enabled: true,
  });

  // Report scroll state changes to parent (for status bar indicator)
  useEffect(() => {
    if (onScrollStateChange) {
      onScrollStateChange({ isFollowing, isAtBottom });
    }
  }, [isFollowing, isAtBottom, onScrollStateChange]);

  // Filter out tool_result turns - they're rendered inline with their matching tool_use
  // NOTE: All hooks must be called before any early returns
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
            result.push({ type: 'parallel', turns: currentGroup, parallelGroupId: currentGroupId });
          } else {
            result.push({ type: 'single', turns: currentGroup });
          }
        }

        // Start a new group or single turn
        if (groupId) {
          currentGroup = [turn];
          currentGroupId = groupId;
        } else {
          result.push({ type: 'single', turns: [turn] });
          currentGroup = [];
          currentGroupId = undefined;
        }
      }
    }

    // Flush any remaining group
    if (currentGroup.length > 0) {
      if (currentGroup.length > 1) {
        result.push({ type: 'parallel', turns: currentGroup, parallelGroupId: currentGroupId });
      } else {
        result.push({ type: 'single', turns: currentGroup });
      }
    }

    return result;
  }, [filteredTurns]);

  // Early returns AFTER all hooks have been called
  if (!sessionId) {
    return <div className="streaming-turns-view empty">No session selected</div>;
  }

  if (isLoading) {
    return <div className="streaming-turns-view loading">Loading session...</div>;
  }

  if (error) {
    return <div className="streaming-turns-view error">{error}</div>;
  }

  // Show scroll-to-bottom button when user has scrolled away
  const showScrollIndicator = !isFollowing;

  return (
    <ClientContext.Provider value={contextValue}>
      <div className="streaming-turns-view-container" ref={scrollRef}>
        <div className="streaming-turns-view">
          <div className="streaming-turns-header">
            <span className="session-info">
              Session: {sessionId?.substring(0, 8)}... ({turns.length} turns)
            </span>
            {isSubscribed && <span className="subscribed-badge">● subscribed</span>}
            {isStreaming && <span className="streaming-badge">● streaming</span>}
            {streamError && <span className="stream-error-badge" title={streamError}>⚠ error</span>}
          </div>
          <div className="streaming-turns-list">
            {turnsOrGroups.map((item, idx) => {
              if (item.type === 'single') {
                const turn = item.turns[0];
                if (!turn) return null;
                return (
                  <div key={turn.turnId} data-turn-order={turn.order}>
                    <TurnCard turn={turn} allTurns={turns} sessionId={sessionId || undefined} />
                  </div>
                );
              } else {
                // Parallel group
                return (
                  <div key={`parallel-${item.parallelGroupId || idx}`} className="parallel-group">
                    <div className="parallel-group-header">
                      <span className="parallel-icon">⚡</span>
                      <span className="parallel-label">{item.turns.length} parallel tool calls</span>
                    </div>
                    <div className="parallel-group-content">
                      {item.turns.map((turn) => (
                        <div key={turn.turnId} data-turn-order={turn.order}>
                          <TurnCard turn={turn} allTurns={turns} sessionId={sessionId || undefined} />
                        </div>
                      ))}
                    </div>
                  </div>
                );
              }
            })}
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
