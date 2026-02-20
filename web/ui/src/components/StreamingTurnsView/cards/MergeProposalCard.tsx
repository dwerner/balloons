/**
 * MergeProposalCard - Interactive card for merge proposals
 *
 * Displays Claude's merge proposals with:
 * - Merge summary (editable)
 * - Files changed
 * - Key accomplishments
 * - Accept/Reject buttons
 *
 * Uses the respondToMergeProposal API to accept/reject proposals.
 */

import React, { useState, useCallback, memo } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { MergeProposalBlock } from '../../../../../generated/types';
import { useClient } from './ClientContext';
import './cards.css';

interface MergeProposalCardProps {
  turn: SessionDataTurn;
  sessionId?: string;
}

/**
 * Main MergeProposalCard component.
 */
export const MergeProposalCard = memo(function MergeProposalCard({
  turn,
  sessionId,
}: MergeProposalCardProps) {
  const client = useClient();
  const block = turn.contentBlock as MergeProposalBlock | undefined;

  // Local state
  const [summary, setSummary] = useState(block?.summary || '');
  const [status, setStatus] = useState<'pending' | 'accepted' | 'rejected' | 'loading'>(
    (block?.status as any) || 'pending'
  );
  const [isEditing, setIsEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // If no block, render nothing
  if (!block) {
    return null;
  }

  const { proposalId, reason, filesChanged, keyAccomplishments } = block;
  const isPending = status === 'pending';
  const isLoading = status === 'loading';

  const handleAccept = useCallback(async () => {
    if (!client || !sessionId || !proposalId) return;

    setStatus('loading');
    setError(null);

    try {
      const result = await client.sessions.respondToMergeProposal(
        sessionId,
        proposalId,
        true, // accepted
        summary || null,
        filesChanged || null,
        keyAccomplishments || null,
        reason || null,
      );

      if (result.success && result.accepted) {
        setStatus('accepted');
        // The parent session should auto-refresh with the merge marker
      } else {
        setStatus('pending');
        setError(result.error || 'Failed to accept proposal');
      }
    } catch (err) {
      setStatus('pending');
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, [client, sessionId, proposalId, summary, filesChanged, keyAccomplishments, reason]);

  const handleReject = useCallback(async () => {
    if (!client || !sessionId || !proposalId) return;

    setStatus('loading');
    setError(null);

    try {
      const result = await client.sessions.respondToMergeProposal(
        sessionId,
        proposalId,
        false, // rejected
      );

      if (result.success) {
        setStatus('rejected');
      } else {
        setStatus('pending');
        setError(result.error || 'Failed to reject proposal');
      }
    } catch (err) {
      setStatus('pending');
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, [client, sessionId, proposalId]);

  const statusClass = status === 'loading' ? 'pending' : status;

  return (
    <div className={`turn-card merge-proposal-card status-${statusClass}`}>
      {/* Header */}
      <div className="turn-card-header merge-proposal-header">
        <span className="turn-icon">⤴</span>
        <span className="turn-label">Merge Proposal</span>
        <span className={`merge-proposal-status status-${statusClass}`}>
          {status === 'pending' && '⏳ Pending'}
          {status === 'loading' && '⏳ Processing...'}
          {status === 'accepted' && '✓ Accepted'}
          {status === 'rejected' && '✗ Rejected'}
        </span>
      </div>

      <div className="turn-card-body">
        {/* Summary section */}
        <div className="merge-proposal-section">
          <div className="section-header">
            <span className="section-title">Summary</span>
            {isPending && !isEditing && (
              <span className="section-hint">Click Edit to modify</span>
            )}
          </div>
          {isPending && isEditing ? (
            <textarea
              className="merge-summary-input"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="Merge summary..."
              rows={4}
            />
          ) : (
            <div className="merge-summary-display">
              {summary || <em className="no-summary">No summary provided</em>}
            </div>
          )}
        </div>

        {/* Reason */}
        {reason && (
          <div className="merge-proposal-section">
            <div className="section-header">
              <span className="section-title">Reason</span>
            </div>
            <div className="merge-reason-display">{reason}</div>
          </div>
        )}

        {/* Files changed */}
        {filesChanged && filesChanged.length > 0 && (
          <div className="merge-proposal-section">
            <div className="section-header">
              <span className="section-title">Files Changed ({filesChanged.length})</span>
            </div>
            <ul className="files-changed-list">
              {filesChanged.map((file, i) => (
                <li key={i}><code>{file}</code></li>
              ))}
            </ul>
          </div>
        )}

        {/* Key accomplishments */}
        {keyAccomplishments && keyAccomplishments.length > 0 && (
          <div className="merge-proposal-section">
            <div className="section-header">
              <span className="section-title">Key Accomplishments</span>
            </div>
            <ul className="accomplishments-list">
              {keyAccomplishments.map((item, i) => (
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

        {/* Action buttons */}
        {isPending && !isLoading && (
          <div className="merge-proposal-actions">
            {isEditing ? (
              <button className="btn btn-primary" onClick={() => setIsEditing(false)}>
                Done Editing
              </button>
            ) : (
              <button className="btn btn-secondary" onClick={() => setIsEditing(true)}>
                Edit
              </button>
            )}
            <button className="btn btn-success" onClick={handleAccept} disabled={!client}>
              Accept
            </button>
            <button className="btn btn-danger" onClick={handleReject} disabled={!client}>
              Reject
            </button>
          </div>
        )}

        {isLoading && (
          <div className="merge-proposal-actions">
            <span className="loading-indicator">Processing...</span>
          </div>
        )}

        {/* Status message for resolved proposals */}
        {!isPending && !isLoading && (
          <div className={`merge-proposal-resolution status-${status}`}>
            {status === 'accepted' && 'Merge completed successfully'}
            {status === 'rejected' && 'Merge proposal was rejected'}
          </div>
        )}
      </div>
    </div>
  );
});

export default MergeProposalCard;
