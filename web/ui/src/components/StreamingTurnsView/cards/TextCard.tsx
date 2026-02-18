/**
 * TextCard - Renders text content blocks (user or assistant)
 */

import React from 'react';
import { MarkdownContent } from '../../../MarkdownContent';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import './cards.css';

interface TextCardProps {
  turn: SessionDataTurn;
}

export function TextCard({ turn }: TextCardProps) {
  const { role, content, streaming, tokens } = turn;
  const isUser = role === 'user';
  const isAssistant = role === 'assistant';

  const roleConfig = {
    user: { icon: '👤', label: 'User', className: 'user' },
    assistant: { icon: '🤖', label: 'Assistant', className: 'assistant' },
  }[role] || { icon: '📄', label: role, className: 'other' };

  return (
    <div className={`turn-card text-card ${roleConfig.className} ${streaming ? 'streaming' : ''}`}>
      <div className="turn-card-header">
        <span className="turn-icon">{roleConfig.icon}</span>
        <span className="turn-label">{roleConfig.label}</span>
        {streaming && <span className="streaming-indicator">●</span>}
        {!streaming && tokens > 0 && (
          <span className="turn-tokens">{tokens} tokens</span>
        )}
      </div>
      <div className="turn-card-body">
        {isAssistant ? (
          content ? (
            <MarkdownContent content={content} />
          ) : streaming ? (
            <span className="thinking">Thinking...</span>
          ) : null
        ) : (
          // User content - render as plain text (no markdown)
          content || (streaming ? <span className="thinking">...</span> : null)
        )}
      </div>
    </div>
  );
}
