/**
 * MergeProposalCard - Interactive card for propose_merge tool calls
 *
 * Renders the propose_merge tool_use as an interactive UI with:
 * - Merge summary (editable)
 * - Files changed
 * - Key accomplishments
 * - Single "Merge" button
 *
 * Uses BaseToolCard for consistent formatting/raw mode switching.
 * The tool input is the source of truth - no synthetic blocks needed.
 */

import React, { useState, useCallback } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock } from '../../../../../generated/types';
import { useClient } from './ClientContext';
import { BaseToolCard, calculateToolPhase, type ToolPhase } from './BaseToolCard';
import './cards.css';

// Status for the merge action
type MergeStatus = 'ready' | 'merging' | 'merged' | 'error';

interface MergeProposalCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
  sessionId?: string;
}

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

// Extract proposal data from tool input
// Handles both camelCase (wire format) and snake_case (legacy) keys
function extractProposalData(input: Record<string, unknown>) {
  return {
    summary: (input.summary as string) || '',
    reason: (input.reason as string) || '',
    filesChanged: (input.filesChanged as string[]) || (input.files_changed as string[]) || [],
    keyAccomplishments: (input.keyAccomplishments as string[]) || (input.key_accomplishments as string[]) || [],
  };
}

/**
 * MergeProposalCard - Renders propose_merge tool_use with interactive UI
 */
export function MergeProposalCard({
  turn,
  result,
  sessionId,
}: MergeProposalCardProps) {
  const client = useClient();
  const { contentBlock, streaming, tokens } = turn;

  // Extract tool info
  const toolUseBlock = contentBlock?.type === 'tool_use'
    ? (contentBlock as ToolUseBlock)
    : null;

  const toolInput = (toolUseBlock?.input || {}) as Record<string, unknown>;
  const inputIsStreaming = isStreamingInput(toolInput);
  const toolUseId = toolUseBlock?.id || '';

  // Extract proposal data from input
  const proposalData = extractProposalData(toolInput);

  // Local state for modifications
  const [summary, setSummary] = useState(proposalData.summary);
  const [isEditing, setIsEditing] = useState(false);
  const [status, setStatus] = useState<MergeStatus>('ready');
  const [error, setError] = useState<string | null>(null);

  // Calculate phase for BaseToolCard
  const hasInput = !inputIsStreaming && proposalData.summary.length > 0;
  const hasResult = !!result;
  const isError = status === 'error';
  const phase: ToolPhase = status === 'merged' ? 'completed'
    : status === 'merging' ? 'executing'
    : calculateToolPhase(streaming || false, hasInput, inputIsStreaming, hasResult, isError);

  // Handler for executing the merge
  const handleMerge = useCallback(async () => {
    if (!client || !sessionId || !toolUseId) return;

    setStatus('merging');
    setError(null);

    try {
      const result = await client.sessions.respondToMergeProposal(
        sessionId,
        toolUseId, // Use tool_use ID as proposal ID
        true, // accepted
        summary || null,
        proposalData.filesChanged.length > 0 ? proposalData.filesChanged : null,
        proposalData.keyAccomplishments.length > 0 ? proposalData.keyAccomplishments : null,
        proposalData.reason || null,
      );

      if (result.success && result.accepted) {
        setStatus('merged');
        // The parent session should auto-refresh with the merge marker
      } else {
        setStatus('error');
        setError(result.error || 'Failed to merge');
      }
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, [client, sessionId, toolUseId, summary, proposalData.filesChanged, proposalData.keyAccomplishments, proposalData.reason]);

  // Raw data for debugging mode
  const rawData = { turn, result, proposalData };

  const isReady = status === 'ready';
  const isMerging = status === 'merging';

  return (
    <BaseToolCard
      toolName="propose_merge"
      phase={phase}
      tokens={tokens}
      order={turn.order}
      orderEnd={result?.order}
      className="merge-proposal-card"
      rawData={rawData}
      timestamp={turn.timestamp}
      headerContent={hasInput && <span className="merge-summary-preview">{proposalData.summary.slice(0, 50)}{proposalData.summary.length > 50 ? '...' : ''}</span>}
    >
      {/* Streaming indicator */}
      {inputIsStreaming && (
        <div className="tool-building-content">
          <span className="streaming-dots">
            <span className="dot">.</span>
            <span className="dot">.</span>
            <span className="dot">.</span>
          </span>
          <span>Building proposal...</span>
        </div>
      )}

      {/* Proposal content when ready */}
      {hasInput && (
        <div className="merge-proposal-content">
          {/* Summary section */}
          <div className="merge-proposal-section">
            <div className="section-header">
              <span className="section-title">Summary</span>
              {isReady && !isEditing && (
                <button
                  className="edit-btn"
                  onClick={() => setIsEditing(true)}
                  type="button"
                >
                  Edit
                </button>
              )}
            </div>
            {isReady && isEditing ? (
              <div className="summary-editor">
                <textarea
                  className="merge-summary-input"
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                  placeholder="Merge summary..."
                  rows={4}
                  autoFocus
                />
                <button
                  className="btn btn-secondary btn-small"
                  onClick={() => setIsEditing(false)}
                  type="button"
                >
                  Done
                </button>
              </div>
            ) : (
              <div className="merge-summary-display">
                {summary || <em className="no-summary">No summary provided</em>}
              </div>
            )}
          </div>

          {/* Reason */}
          {proposalData.reason && (
            <div className="merge-proposal-section">
              <div className="section-header">
                <span className="section-title">Reason</span>
              </div>
              <div className="merge-reason-display">{proposalData.reason}</div>
            </div>
          )}

          {/* Files changed */}
          {proposalData.filesChanged.length > 0 && (
            <div className="merge-proposal-section">
              <div className="section-header">
                <span className="section-title">Files Changed ({proposalData.filesChanged.length})</span>
              </div>
              <ul className="files-changed-list">
                {proposalData.filesChanged.map((file, i) => (
                  <li key={i}><code>{file}</code></li>
                ))}
              </ul>
            </div>
          )}

          {/* Key accomplishments */}
          {proposalData.keyAccomplishments.length > 0 && (
            <div className="merge-proposal-section">
              <div className="section-header">
                <span className="section-title">Key Accomplishments</span>
              </div>
              <ul className="accomplishments-list">
                {proposalData.keyAccomplishments.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Error message */}
          {error && (
            <div className="merge-proposal-error">
              {error}
            </div>
          )}

          {/* Action button */}
          {isReady && (
            <div className="merge-proposal-actions">
              <button
                className="btn btn-primary merge-btn"
                onClick={handleMerge}
                disabled={!client}
                type="button"
              >
                Merge
              </button>
            </div>
          )}

          {isMerging && (
            <div className="merge-proposal-actions">
              <span className="loading-indicator">Merging...</span>
            </div>
          )}

          {/* Completion state */}
          {status === 'merged' && (
            <div className="merge-proposal-resolution status-merged">
              Merge completed successfully
            </div>
          )}
        </div>
      )}

      <style>{`
        .merge-proposal-card .merge-summary-preview {
          color: #9ca3af;
          font-size: 12px;
          font-style: italic;
        }

        .merge-proposal-card .merge-proposal-content {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .merge-proposal-card .merge-proposal-section {
          border-top: 1px solid #374151;
          padding-top: 10px;
        }

        .merge-proposal-card .merge-proposal-section:first-child {
          border-top: none;
          padding-top: 0;
        }

        .merge-proposal-card .section-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 8px;
        }

        .merge-proposal-card .section-title {
          font-size: 12px;
          font-weight: 600;
          color: #9ca3af;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }

        .merge-proposal-card .edit-btn {
          padding: 2px 8px;
          font-size: 11px;
          background: transparent;
          border: 1px solid #4b5563;
          border-radius: 4px;
          color: #9ca3af;
          cursor: pointer;
        }

        .merge-proposal-card .edit-btn:hover {
          background: #374151;
          color: #e5e7eb;
        }

        .merge-proposal-card .summary-editor {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .merge-proposal-card .merge-summary-input {
          width: 100%;
          padding: 8px 10px;
          background: #0d1117;
          border: 1px solid #374151;
          border-radius: 6px;
          color: #e5e7eb;
          font-size: 13px;
          font-family: inherit;
          resize: vertical;
        }

        .merge-proposal-card .merge-summary-input:focus {
          outline: none;
          border-color: #60a5fa;
        }

        .merge-proposal-card .merge-summary-display {
          padding: 8px 10px;
          background: #0d1117;
          border-radius: 6px;
          font-size: 14px;
          color: #e5e7eb;
          line-height: 1.5;
          white-space: pre-wrap;
        }

        .merge-proposal-card .no-summary {
          color: #6b7280;
        }

        .merge-proposal-card .merge-reason-display {
          font-size: 13px;
          color: #d1d5db;
          line-height: 1.4;
        }

        .merge-proposal-card .files-changed-list {
          margin: 0;
          padding-left: 0;
          list-style: none;
        }

        .merge-proposal-card .files-changed-list li {
          padding: 4px 0;
          font-size: 12px;
        }

        .merge-proposal-card .files-changed-list code {
          color: #60a5fa;
          background: #0d1117;
          padding: 2px 6px;
          border-radius: 4px;
        }

        .merge-proposal-card .accomplishments-list {
          margin: 0;
          padding-left: 20px;
        }

        .merge-proposal-card .accomplishments-list li {
          padding: 4px 0;
          font-size: 13px;
          color: #d1d5db;
        }

        .merge-proposal-card .merge-proposal-error {
          padding: 8px 12px;
          background: rgba(239, 68, 68, 0.15);
          border: 1px solid rgba(239, 68, 68, 0.3);
          border-radius: 6px;
          color: #fca5a5;
          font-size: 13px;
        }

        .merge-proposal-card .merge-proposal-actions {
          display: flex;
          align-items: center;
          gap: 12px;
          padding-top: 8px;
        }

        .merge-proposal-card .merge-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 16px;
          background: #22c55e;
          border: none;
          border-radius: 6px;
          color: white;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: background 0.15s ease;
        }

        .merge-proposal-card .merge-btn:hover:not(:disabled) {
          background: #16a34a;
        }

        .merge-proposal-card .merge-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .merge-proposal-card .loading-indicator {
          color: #9ca3af;
          font-size: 13px;
        }

        .merge-proposal-card .merge-proposal-resolution {
          display: flex;
          align-items: center;
          padding: 10px 12px;
          background: rgba(34, 197, 94, 0.1);
          border: 1px solid rgba(34, 197, 94, 0.2);
          border-radius: 6px;
          color: #4ade80;
          font-size: 13px;
        }
      `}</style>
    </BaseToolCard>
  );
}

export default MergeProposalCard;
