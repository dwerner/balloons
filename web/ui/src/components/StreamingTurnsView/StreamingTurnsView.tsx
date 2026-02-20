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

import React from 'react';
import type { BalloonsClient } from '../../../../generated/balloons-client';
import { useSessionData, useAutoScroll } from '../../hooks';
import { TurnCard, ClientContext } from './cards';
import { ScrollToBottom } from '../ScrollToBottom';
import './StreamingTurnsView.css';

interface StreamingTurnsViewProps {
  sessionId: string | null;
  client: BalloonsClient;
}

export function StreamingTurnsView({ sessionId, client }: StreamingTurnsViewProps) {
  const { turns, isLoading, isSubscribed, isStreaming, streamError, error } = useSessionData(client, sessionId);

  // Robust autoscroll: follows stream, pauses on user scroll-up, resumes on click
  const { scrollRef, isFollowing, scrollToBottom } = useAutoScroll({
    deps: [turns], // Re-check scroll position when turns change
    threshold: 150, // Consider "at bottom" within 150px
    enabled: true,
  });

  if (!sessionId) {
    return <div className="streaming-turns-view empty">No session selected</div>;
  }

  if (isLoading) {
    return <div className="streaming-turns-view loading">Loading session...</div>;
  }

  if (error) {
    return <div className="streaming-turns-view error">{error}</div>;
  }

  // Show scroll indicator when streaming and user scrolled away
  const showScrollIndicator = isStreaming && !isFollowing;

  return (
    <ClientContext.Provider value={client}>
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
            {turns.map((turn) => (
              <TurnCard key={turn.turnId} turn={turn} allTurns={turns} sessionId={sessionId || undefined} />
            ))}
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
