/**
 * TextCard - Renders text content blocks (user or assistant)
 *
 * Features:
 * - Markdown rendering for assistant responses
 * - Plain text for user messages
 * - Raw JSON view toggle for debugging turn data
 */

import React, { useState } from 'react';
import { MarkdownContent } from '../../../MarkdownContent';
import { SyntaxHighlightedCode } from './SyntaxHighlighter';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { TextBlock } from '../../../../../generated/types';
import './cards.css';

type DisplayMode = 'formatted' | 'raw';

interface TextCardProps {
  turn: SessionDataTurn;
}

/**
 * Mode switcher component - allows toggling between formatted and raw views
 */
function ModeSwitcher({
  mode,
  onModeChange,
}: {
  mode: DisplayMode;
  onModeChange: (mode: DisplayMode) => void;
}) {
  const handleFormatted = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    onModeChange('formatted');
  };

  const handleRaw = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    onModeChange('raw');
  };

  return (
    <div className="turn-card-mode-switcher" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className={`mode-btn ${mode === 'formatted' ? 'active' : ''}`}
        onClick={handleFormatted}
        title="Formatted view"
      >
        <span className="mode-icon">◈</span>
      </button>
      <button
        type="button"
        className={`mode-btn ${mode === 'raw' ? 'active' : ''}`}
        onClick={handleRaw}
        title="Raw JSON (debug)"
      >
        <span className="mode-icon">{'{}'}</span>
      </button>
    </div>
  );
}

/**
 * Raw JSON display for debugging - with syntax highlighting
 */
function RawDataDisplay({ data }: { data: unknown }) {
  const formatted = JSON.stringify(data, null, 2);
  return (
    <div className="turn-raw-data">
      <SyntaxHighlightedCode code={formatted} language="json" wrapLongLines />
    </div>
  );
}

export function TextCard({ turn }: TextCardProps) {
  const { role, contentBlock, streaming, tokens, order } = turn;
  const isUser = role === 'user';
  const isAssistant = role === 'assistant';

  // Display mode state - formatted (default) or raw JSON
  const [displayMode, setDisplayMode] = useState<DisplayMode>('formatted');

  // Extract text from content block
  const content = contentBlock?.type === 'text'
    ? (contentBlock as TextBlock).text ?? ''
    : '';

  const roleConfig = {
    user: { icon: '👤', label: 'User', className: 'user' },
    assistant: { icon: '🤖', label: 'Assistant', className: 'assistant' },
  }[role] || { icon: '📄', label: role, className: 'other' };

  // Show "done" indicator for completed assistant turns
  const showDoneIndicator = isAssistant && !streaming && content;

  // Render body content based on display mode
  const renderBody = () => {
    if (displayMode === 'raw') {
      return <RawDataDisplay data={turn} />;
    }

    if (isAssistant) {
      if (content) {
        return <MarkdownContent content={content} />;
      }
      if (streaming) {
        return (
          <div className="thinking-indicator">
            <span className="thinking-spinner" />
            <span className="thinking-text">Thinking...</span>
          </div>
        );
      }
      return null;
    }

    // User content - render as plain text (no markdown)
    return content || (streaming ? <span className="thinking">...</span> : null);
  };

  return (
    <div className={`turn-card text-card ${roleConfig.className} ${streaming ? 'streaming' : ''} ${showDoneIndicator ? 'done' : ''} ${displayMode === 'raw' ? 'raw-mode' : ''}`}>
      <div className="turn-card-header">
        <span className="turn-order">{order}</span>
        <span className="turn-icon">{roleConfig.icon}</span>
        <span className="turn-label">{roleConfig.label}</span>
        {showDoneIndicator && <span className="done-indicator">✓</span>}
        {!streaming && tokens > 0 && (
          <span className="turn-tokens">{tokens} tokens</span>
        )}
        <ModeSwitcher mode={displayMode} onModeChange={setDisplayMode} />
      </div>
      <div className="turn-card-body">
        {renderBody()}
      </div>
    </div>
  );
}
