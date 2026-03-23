/**
 * RepairedToolCard - Shows when a malformed tool call was repaired
 *
 * This card is displayed when the system detects a <tool_use> block with
 * malformed JSON (e.g., unescaped quotes in shell commands), repairs it,
 * and executes the tool. It shows:
 * - The repair that was performed
 * - The original malformed input (collapsed by default)
 * - The repaired input that was executed
 */

import React, { useState } from 'react';
import { SyntaxHighlightedCode } from './SyntaxHighlighter';
import './cards.css';

interface RepairedToolCardProps {
  toolName: string;
  toolUseId: string;
  originalInput: string;
  repairedInput: Record<string, unknown>;
  repairDescription: string;
  order?: number;
  timestamp?: string;
}

export const RepairedToolCard = React.memo(function RepairedToolCard({
  toolName,
  toolUseId,
  originalInput,
  repairedInput,
  repairDescription,
  order,
  timestamp,
}: RepairedToolCardProps) {
  const [showOriginal, setShowOriginal] = useState(false);

  return (
    <div className="turn-card repaired-tool-card">
      <div className="turn-card-header">
        {order !== undefined && <span className="turn-order">{order}</span>}
        <span className="turn-icon repaired-icon">🔧</span>
        <span className="turn-label">Repaired Tool Call</span>
        <span className="tool-name">{toolName}</span>
        {timestamp && <span className="turn-timestamp">{timestamp}</span>}
      </div>

      <div className="turn-card-body">
        <div className="repair-description">
          <span className="repair-badge">Auto-repaired</span>
          <span className="repair-text">{repairDescription}</span>
        </div>

        <div className="repair-section">
          <div className="repair-section-header">
            <span className="repair-section-label">Repaired Input</span>
            <span className="tool-id">{toolUseId.slice(0, 12)}...</span>
          </div>
          <SyntaxHighlightedCode
            code={JSON.stringify(repairedInput, null, 2)}
            language="json"
          />
        </div>

        <div className="repair-toggle">
          <button
            type="button"
            className="btn btn-link btn-small"
            onClick={() => setShowOriginal(!showOriginal)}
          >
            {showOriginal ? '▼ Hide' : '▶ Show'} original malformed input
          </button>
        </div>

        {showOriginal && (
          <div className="repair-section original-section">
            <div className="repair-section-header">
              <span className="repair-section-label">Original (Malformed)</span>
            </div>
            <pre className="malformed-input">
              <code>{originalInput}</code>
            </pre>
          </div>
        )}
      </div>
    </div>
  );
});
