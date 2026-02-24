/**
 * ToolResultCard - Renders tool_result content blocks
 *
 * This is used for standalone tool results that aren't paired with a tool_use.
 * Typically, tool results are displayed inline with their tool_use via ToolUseCard.
 *
 * Features:
 * - Raw JSON view toggle for debugging turn data
 */

import React, { useState } from 'react';
import { SyntaxHighlightedCode } from './SyntaxHighlighter';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolResultBlock } from '../../../../../generated/types';
import './cards.css';

type DisplayMode = 'formatted' | 'raw';

interface ToolResultCardProps {
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

export function ToolResultCard({ turn }: ToolResultCardProps) {
  const { contentBlock, streaming } = turn;

  // Display mode state - formatted (default) or raw JSON
  const [displayMode, setDisplayMode] = useState<DisplayMode>('formatted');

  // Extract content from tool_result block
  const resultBlock = contentBlock?.type === 'tool_result'
    ? (contentBlock as ToolResultBlock)
    : null;
  const content = resultBlock?.content || '';
  const isError = resultBlock?.isError || false;

  // Show all content (no truncation)
  const displayContent = content;

  // Render body content based on display mode
  const renderBody = () => {
    if (displayMode === 'raw') {
      return <RawDataDisplay data={turn} />;
    }

    return (
      <pre className={`tool-result-output ${isError ? 'error' : ''}`}>
        <code>{displayContent || (streaming ? 'Waiting for result...' : '(empty)')}</code>
      </pre>
    );
  };

  return (
    <div className={`turn-card tool-result-card ${isError ? 'error' : ''} ${streaming ? 'streaming' : ''} ${displayMode === 'raw' ? 'raw-mode' : ''}`}>
      <div className="turn-card-header">
        <span className="turn-icon">{isError ? '❌' : '✓'}</span>
        <span className="turn-label">Tool Result</span>
        {streaming && <span className="streaming-indicator">●</span>}
        <ModeSwitcher mode={displayMode} onModeChange={setDisplayMode} />
      </div>
      <div className="turn-card-body">
        {renderBody()}
      </div>
    </div>
  );
}
