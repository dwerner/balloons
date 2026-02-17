/**
 * StreamingTurnsView - Chat log view using SessionDataService
 *
 * This component displays turns using the new SessionDataService subscription
 * model (turn_id based) rather than TaskStateService (turn_index based).
 */

import React, { useRef, useEffect } from 'react';
import type { BalloonsClient } from '../../../../generated/balloons-client';
import { useSessionData } from '../../hooks/useSessionData';
import { MarkdownContent } from '../../MarkdownContent';
import './StreamingTurnsView.css';

interface StreamingTurnsViewProps {
  sessionId: string | null;
  client: BalloonsClient;
}

export function StreamingTurnsView({ sessionId, client }: StreamingTurnsViewProps) {
  const { turns, isLoading, isSubscribed, error } = useSessionData(client, sessionId);
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
        SessionDataService View ({turns.length} turns)
        {isSubscribed && <span className="subscribed-badge">● subscribed</span>}
      </div>
      <div className="streaming-turns-list">
        {turns.map((turn) => (
          <TurnCard key={turn.turnId} turn={turn} />
        ))}
      </div>
    </div>
  );
}

interface TurnCardProps {
  turn: {
    turnId: string;
    idx: number;
    role: string;
    content: string;
    streaming: boolean;
    tokens: number;
    contentBlockType?: string;
  };
}

function TurnCard({ turn }: TurnCardProps) {
  const { role, content, streaming, tokens, contentBlockType } = turn;

  // Determine icon and label based on role
  const roleConfig = {
    user: { icon: '👤', label: 'User', className: 'user' },
    assistant: { icon: '🤖', label: 'Assistant', className: 'assistant' },
    tool: { icon: '🔧', label: 'Tool', className: 'tool' },
  }[role] || { icon: '📄', label: role, className: 'other' };

  return (
    <div className={`streaming-turn-card ${roleConfig.className} ${streaming ? 'streaming' : ''}`}>
      <div className="streaming-turn-header">
        <span className="turn-icon">{roleConfig.icon}</span>
        <span className="turn-label">{roleConfig.label}</span>
        {contentBlockType && contentBlockType !== 'text' && (
          <span className="turn-type">{contentBlockType}</span>
        )}
        {streaming && <span className="streaming-indicator">●</span>}
        {!streaming && tokens > 0 && (
          <span className="turn-tokens">{tokens} tokens</span>
        )}
      </div>
      <div className="streaming-turn-body">
        {role === 'assistant' ? (
          content ? (
            <MarkdownContent content={content} />
          ) : streaming ? (
            <span className="thinking">Thinking...</span>
          ) : null
        ) : (
          content || (streaming ? <span className="thinking">...</span> : null)
        )}
      </div>
    </div>
  );
}

export default StreamingTurnsView;
