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
 */

import React, { useRef, useEffect } from 'react';
import type { BalloonsClient } from '../../../../generated/balloons-client';
import { useSessionData } from '../../hooks/useSessionData';
import { TurnCard } from './cards';
import './StreamingTurnsView.css';

interface StreamingTurnsViewProps {
  sessionId: string | null;
  client: BalloonsClient;
}

export function StreamingTurnsView({ sessionId, client }: StreamingTurnsViewProps) {
  const { turns, isLoading, isSubscribed, isStreaming, streamError, error } = useSessionData(client, sessionId);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new content arrives
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [turns]);

  if (!sessionId) {
    return <div className="streaming-turns-view empty">No session selected</div>;
  }

  if (isLoading) {
    return <div className="streaming-turns-view loading">Loading session...</div>;
  }

  if (error) {
    return <div className="streaming-turns-view error">{error}</div>;
  }

  return (
    <div className="streaming-turns-view" ref={scrollRef}>
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
          <TurnCard key={turn.turnId} turn={turn} allTurns={turns} />
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
  );
}

export default StreamingTurnsView;
