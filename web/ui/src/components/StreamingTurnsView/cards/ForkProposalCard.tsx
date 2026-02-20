/**
 * ForkProposalCard - Interactive card for fork proposals
 *
 * Displays Claude's fork proposals with:
 * - Fork name and description
 * - Interactive context tree (click to toggle modes)
 * - Editable initial prompt
 * - Accept/Reject buttons
 *
 * Uses the respondToForkProposal API to accept/reject proposals.
 */

import React, { useState, useCallback, memo, useEffect } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ForkProposalBlock, ExchangeSummary } from '../../../../../generated/types';
import { useClient, useSelectSession } from './ClientContext';
import { ContextPlanTree, type ContextAssignment } from './ContextPlanTree';
import './cards.css';

// Context mode type
type ContextMode = 'copy' | 'compress' | 'drop';

interface ForkProposalCardProps {
  turn: SessionDataTurn;
  sessionId?: string;
}

/**
 * Main ForkProposalCard component.
 */
export const ForkProposalCard = memo(function ForkProposalCard({
  turn,
  sessionId,
}: ForkProposalCardProps) {
  const client = useClient();
  const selectSession = useSelectSession();
  const block = turn.contentBlock as ForkProposalBlock | undefined;

  // Parse context plan from block
  const initialContextPlan: ContextAssignment[] = (block?.contextPlan || []).map((cp) => ({
    exchangeRange: cp.exchangeRange || '',
    mode: (cp.mode || 'compress').toLowerCase() as ContextMode,
    reason: cp.reason || '',
  }));

  // Local state
  const [contextPlan, setContextPlan] = useState<ContextAssignment[]>(initialContextPlan);
  const [initialPrompt, setInitialPrompt] = useState(block?.initialPrompt || '');
  const [status, setStatus] = useState<'pending' | 'accepted' | 'rejected' | 'loading'>(
    (block?.status as 'pending' | 'accepted' | 'rejected') || 'pending'
  );
  const [isEditingPrompt, setIsEditingPrompt] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exchanges, setExchanges] = useState<ExchangeSummary[]>([]);

  // Fetch exchange summaries on mount for pending proposals
  useEffect(() => {
    if (status === 'pending' && client && sessionId) {
      client.sessions.getExchangeSummaries(sessionId, true)
        .then(setExchanges)
        .catch((err) => console.warn('Failed to fetch exchanges:', err));
    }
  }, [status, client, sessionId]);

  // If no block, render nothing
  if (!block) {
    return null;
  }

  const { proposalId, name, description, bindTo, bindToInherit, childSessionId } = block;
  const isPending = status === 'pending';
  const isLoading = status === 'loading';

  // Handler for navigating to the created fork
  const handleGoToFork = useCallback(() => {
    if (childSessionId && selectSession) {
      selectSession(childSessionId);
    }
  }, [childSessionId, selectSession]);

  const handleAccept = useCallback(async () => {
    if (!client || !sessionId || !proposalId) return;

    setStatus('loading');
    setError(null);

    try {
      // Convert context plan to API format (snake_case)
      const apiContextPlan = contextPlan.map((cp) => ({
        exchange_range: cp.exchangeRange,
        mode: cp.mode,
        reason: cp.reason,
      }));

      const result = await client.sessions.respondToForkProposal(
        sessionId,
        proposalId,
        true, // accepted
        apiContextPlan,
        initialPrompt || null,
        name || null,
        description || null,
        true, // start streaming
      );

      if (result.success && result.accepted) {
        setStatus('accepted');
        // Navigate to the new fork session
        if (result.childSessionId && selectSession) {
          // TODO: If needsCompression is true, we should wait for helper completion
          // before navigating. For now, navigate immediately - the session exists
          // but may not have context populated yet if compression was needed.
          if (result.needsCompression) {
            console.warn('[ForkProposalCard] Fork needs compression - context may not be ready yet');
          }
          selectSession(result.childSessionId);
        }
      } else {
        setStatus('pending');
        setError(result.error || 'Failed to accept proposal');
      }
    } catch (err) {
      setStatus('pending');
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, [client, sessionId, proposalId, contextPlan, initialPrompt, name, description, selectSession]);

  const handleReject = useCallback(async () => {
    if (!client || !sessionId || !proposalId) return;

    setStatus('loading');
    setError(null);

    try {
      const result = await client.sessions.respondToForkProposal(
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

  const handlePlanChange = useCallback((newPlan: ContextAssignment[]) => {
    setContextPlan(newPlan);
  }, []);

  const statusClass = status === 'loading' ? 'pending' : status;

  return (
    <div className={`turn-card fork-proposal-card status-${statusClass}`}>
      {/* Header */}
      <div className="turn-card-header fork-proposal-header">
        <span className="turn-icon">⑂</span>
        <span className="turn-label">Fork Proposal</span>
        <span className={`fork-proposal-status status-${statusClass}`}>
          {status === 'pending' && '⏳ Pending'}
          {status === 'loading' && '⏳ Processing...'}
          {status === 'accepted' && '✓ Accepted'}
          {status === 'rejected' && '✗ Rejected'}
        </span>
      </div>

      <div className="turn-card-body">
        {/* Fork details */}
        <div className="fork-proposal-details">
          <div className="fork-proposal-name">
            <span className="label">Name:</span>
            <code className="value">{name}</code>
          </div>
          <div className="fork-proposal-description">
            <span className="label">Description:</span>
            <span className="value">{description}</span>
          </div>

          {/* Binding info */}
          {(bindTo || bindToInherit) && (
            <div className="fork-proposal-binding">
              <span className="label">Binding:</span>
              {bindToInherit ? (
                <span className="value binding-inherit">inherit from parent</span>
              ) : bindTo ? (
                <span className="value">
                  {bindTo.entityType} <code>{(bindTo.entityId || '').slice(0, 8)}...</code>
                  {bindTo.role && ` (${bindTo.role})`}
                </span>
              ) : null}
            </div>
          )}
        </div>

        {/* Context plan section - interactive tree */}
        <div className="fork-proposal-section">
          <div className="section-header">
            <span className="section-title">
              Context ({exchanges.length || contextPlan.length} {exchanges.length === 1 ? 'exchange' : 'exchanges'})
            </span>
          </div>
          <ContextPlanTree
            contextPlan={contextPlan}
            allExchanges={exchanges.length > 0 ? exchanges : undefined}
            onPlanChange={handlePlanChange}
            disabled={!isPending || isLoading}
          />
        </div>

        {/* Initial prompt section */}
        <div className="fork-proposal-section">
          <div className="section-header">
            <span className="section-title">Initial Prompt</span>
            {isPending && !isEditingPrompt && (
              <button
                className="edit-prompt-btn"
                onClick={() => setIsEditingPrompt(true)}
                disabled={isLoading}
              >
                Edit
              </button>
            )}
          </div>
          {isPending && isEditingPrompt ? (
            <div className="prompt-editor">
              <textarea
                className="initial-prompt-input"
                value={initialPrompt}
                onChange={(e) => setInitialPrompt(e.target.value)}
                placeholder="Initial prompt for the fork..."
                rows={4}
                autoFocus
              />
              <button
                className="btn btn-secondary btn-small"
                onClick={() => setIsEditingPrompt(false)}
              >
                Done
              </button>
            </div>
          ) : (
            <div className="initial-prompt-display">
              {initialPrompt || <em className="no-prompt">No initial prompt specified</em>}
            </div>
          )}
        </div>

        {/* Error message */}
        {error && (
          <div className="fork-proposal-error">
            {error}
          </div>
        )}

        {/* Action buttons */}
        {isPending && !isLoading && (
          <div className="fork-proposal-actions">
            <button className="btn btn-success" onClick={handleAccept} disabled={!client}>
              ✓ Accept
            </button>
            <button className="btn btn-danger" onClick={handleReject} disabled={!client}>
              ✗ Reject
            </button>
          </div>
        )}

        {isLoading && (
          <div className="fork-proposal-actions">
            <span className="loading-indicator">Processing...</span>
          </div>
        )}

        {/* Status message for resolved proposals */}
        {!isPending && !isLoading && (
          <div className={`fork-proposal-resolution status-${status}`}>
            {status === 'accepted' && (
              <>
                <span>✓ Fork created successfully</span>
                {childSessionId && selectSession && (
                  <button
                    className="btn btn-primary btn-small go-to-fork-btn"
                    onClick={handleGoToFork}
                  >
                    Go to fork →
                  </button>
                )}
              </>
            )}
            {status === 'rejected' && '✗ Fork proposal was rejected'}
          </div>
        )}
      </div>
    </div>
  );
});

export default ForkProposalCard;
