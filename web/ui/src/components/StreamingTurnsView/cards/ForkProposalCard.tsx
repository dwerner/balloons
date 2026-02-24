/**
 * ForkProposalCard - Interactive card for propose_fork tool calls
 *
 * Renders the propose_fork tool_use as an interactive UI with:
 * - Fork name and description
 * - Interactive context tree (click to toggle modes)
 * - Editable initial prompt
 * - Single "Begin Fork" button
 *
 * Uses BaseToolCard for consistent formatting/raw mode switching.
 * The tool input is the source of truth - no synthetic blocks needed.
 */

import React, { useState, useCallback, useEffect } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ExchangeSummary } from '../../../../../generated/types';
import { useClient, useSelectSession } from './ClientContext';
import { ContextPlanTree, type ContextAssignment } from './ContextPlanTree';
import { BaseToolCard, calculateToolPhase, type ToolPhase } from './BaseToolCard';
import './cards.css';

// Context mode type
type ContextMode = 'copy' | 'compress' | 'drop';

// Status for the fork action
type ForkStatus = 'ready' | 'creating' | 'created' | 'error';

interface ForkProposalCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
  sessionId?: string;
}

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

// Extract proposal data from tool input
function extractProposalData(input: Record<string, unknown>) {
  return {
    name: (input.name as string) || '',
    description: (input.description as string) || '',
    contextPlan: ((input.context_plan as unknown[]) || []).map((cp: unknown) => {
      const item = cp as Record<string, unknown>;
      return {
        exchangeRange: (item.exchange_range as string) || '',
        mode: ((item.mode as string) || 'compress').toLowerCase() as ContextMode,
        reason: (item.reason as string) || '',
      };
    }),
    initialPrompt: (input.initial_prompt as string) || '',
    bindTo: input.bind_to && typeof input.bind_to === 'object' ? {
      entityType: ((input.bind_to as Record<string, unknown>).entity_type as string) || '',
      entityId: ((input.bind_to as Record<string, unknown>).entity_id as string) || '',
      role: ((input.bind_to as Record<string, unknown>).role as string) || '',
    } : null,
    bindToInherit: input.bind_to === 'inherit',
  };
}

/**
 * ForkProposalCard - Renders propose_fork tool_use with interactive UI
 */
export function ForkProposalCard({
  turn,
  result,
  sessionId,
}: ForkProposalCardProps) {
  const client = useClient();
  const selectSession = useSelectSession();
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
  const [contextPlan, setContextPlan] = useState<ContextAssignment[]>(proposalData.contextPlan);
  const [initialPrompt, setInitialPrompt] = useState(proposalData.initialPrompt);
  const [isEditingPrompt, setIsEditingPrompt] = useState(false);
  const [status, setStatus] = useState<ForkStatus>('ready');
  const [error, setError] = useState<string | null>(null);
  const [childSessionId, setChildSessionId] = useState<string | null>(null);
  const [exchanges, setExchanges] = useState<ExchangeSummary[]>([]);

  // Update local state when proposal data changes (during streaming)
  useEffect(() => {
    if (!inputIsStreaming) {
      setContextPlan(proposalData.contextPlan);
      setInitialPrompt(proposalData.initialPrompt);
    }
  }, [inputIsStreaming, proposalData.contextPlan.length, proposalData.initialPrompt]);

  // Fetch exchange summaries on mount when ready
  useEffect(() => {
    if (status === 'ready' && client && sessionId && !inputIsStreaming) {
      client.sessions.getExchangeSummaries(sessionId, true)
        .then(setExchanges)
        .catch((err) => console.warn('Failed to fetch exchanges:', err));
    }
  }, [status, client, sessionId, inputIsStreaming]);

  // Calculate phase for BaseToolCard
  const hasInput = !inputIsStreaming && proposalData.name.length > 0;
  const hasResult = !!result;
  const isError = status === 'error';
  const phase: ToolPhase = status === 'created' ? 'completed'
    : status === 'creating' ? 'executing'
    : calculateToolPhase(streaming || false, hasInput, inputIsStreaming, hasResult, isError);

  // Handler for beginning the fork
  const handleBeginFork = useCallback(async () => {
    if (!client || !sessionId || !toolUseId) return;

    setStatus('creating');
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
        toolUseId, // Use tool_use ID as proposal ID
        true, // accepted
        apiContextPlan,
        initialPrompt || null,
        proposalData.name || null,
        proposalData.description || null,
        true, // start streaming
      );

      if (result.success && result.accepted) {
        setStatus('created');
        setChildSessionId(result.childSessionId || null);
        // Navigate to the new fork session
        if (result.childSessionId && selectSession) {
          if (result.needsCompression) {
            console.warn('[ForkProposalCard] Fork needs compression - context may not be ready yet');
          }
          selectSession(result.childSessionId);
        }
      } else {
        setStatus('error');
        setError(result.error || 'Failed to create fork');
      }
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, [client, sessionId, toolUseId, contextPlan, initialPrompt, proposalData.name, proposalData.description, selectSession]);

  // Handler for navigating to the created fork
  const handleGoToFork = useCallback(() => {
    if (childSessionId && selectSession) {
      selectSession(childSessionId);
    }
  }, [childSessionId, selectSession]);

  const handlePlanChange = useCallback((newPlan: ContextAssignment[]) => {
    setContextPlan(newPlan);
  }, []);

  // Raw data for debugging mode
  const rawData = { turn, result, proposalData };

  const isReady = status === 'ready';
  const isCreating = status === 'creating';

  return (
    <BaseToolCard
      toolName="propose_fork"
      phase={phase}
      tokens={tokens}
      order={turn.order}
      orderEnd={result?.order}
      className="fork-proposal-card"
      rawData={rawData}
      headerContent={hasInput && <code className="fork-name">{proposalData.name}</code>}
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
        <div className="fork-proposal-content">
          {/* Fork details */}
          <div className="fork-proposal-details">
            <div className="fork-proposal-description">
              {proposalData.description}
            </div>

            {/* Binding info */}
            {(proposalData.bindTo || proposalData.bindToInherit) && (
              <div className="fork-proposal-binding">
                <span className="label">Bind to:</span>
                {proposalData.bindToInherit ? (
                  <span className="value binding-inherit">inherit from parent</span>
                ) : proposalData.bindTo ? (
                  <span className="value">
                    {proposalData.bindTo.entityType} <code>{proposalData.bindTo.entityId.slice(0, 8)}...</code>
                    {proposalData.bindTo.role && ` (${proposalData.bindTo.role})`}
                  </span>
                ) : null}
              </div>
            )}
          </div>

          {/* Context plan section - interactive tree */}
          <div className="fork-proposal-section">
            <div className="section-header">
              <span className="section-title">
                Context ({exchanges.length || contextPlan.length} {(exchanges.length || contextPlan.length) === 1 ? 'exchange' : 'exchanges'})
              </span>
            </div>
            <ContextPlanTree
              contextPlan={contextPlan}
              allExchanges={exchanges.length > 0 ? exchanges : undefined}
              onPlanChange={handlePlanChange}
              disabled={!isReady || isCreating}
            />
          </div>

          {/* Initial prompt section */}
          <div className="fork-proposal-section">
            <div className="section-header">
              <span className="section-title">Initial Prompt</span>
              {isReady && !isEditingPrompt && (
                <button
                  className="edit-prompt-btn"
                  onClick={() => setIsEditingPrompt(true)}
                  type="button"
                >
                  Edit
                </button>
              )}
            </div>
            {isReady && isEditingPrompt ? (
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
                  type="button"
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

          {/* Action button */}
          {isReady && (
            <div className="fork-proposal-actions">
              <button
                className="btn btn-primary begin-fork-btn"
                onClick={handleBeginFork}
                disabled={!client}
                type="button"
              >
                Begin Fork
              </button>
            </div>
          )}

          {isCreating && (
            <div className="fork-proposal-actions">
              <span className="loading-indicator">Creating fork...</span>
            </div>
          )}

          {/* Completion state */}
          {status === 'created' && (
            <div className="fork-proposal-resolution status-created">
              <span>Fork created successfully</span>
              {childSessionId && selectSession && (
                <button
                  className="btn btn-primary btn-small go-to-fork-btn"
                  onClick={handleGoToFork}
                  type="button"
                >
                  Go to fork
                </button>
              )}
            </div>
          )}
        </div>
      )}

      <style>{`
        .fork-proposal-card .fork-name {
          color: #60a5fa;
          font-size: 13px;
        }

        .fork-proposal-card .fork-proposal-content {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .fork-proposal-card .fork-proposal-details {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .fork-proposal-card .fork-proposal-description {
          color: #e5e7eb;
          font-size: 14px;
          line-height: 1.5;
        }

        .fork-proposal-card .fork-proposal-binding {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 12px;
          color: #9ca3af;
        }

        .fork-proposal-card .fork-proposal-binding .label {
          color: #6b7280;
        }

        .fork-proposal-card .fork-proposal-binding .binding-inherit {
          color: #a78bfa;
          font-style: italic;
        }

        .fork-proposal-card .fork-proposal-section {
          border-top: 1px solid #374151;
          padding-top: 10px;
        }

        .fork-proposal-card .section-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 8px;
        }

        .fork-proposal-card .section-title {
          font-size: 12px;
          font-weight: 600;
          color: #9ca3af;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }

        .fork-proposal-card .edit-prompt-btn {
          padding: 2px 8px;
          font-size: 11px;
          background: transparent;
          border: 1px solid #4b5563;
          border-radius: 4px;
          color: #9ca3af;
          cursor: pointer;
        }

        .fork-proposal-card .edit-prompt-btn:hover {
          background: #374151;
          color: #e5e7eb;
        }

        .fork-proposal-card .prompt-editor {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .fork-proposal-card .initial-prompt-input {
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

        .fork-proposal-card .initial-prompt-input:focus {
          outline: none;
          border-color: #60a5fa;
        }

        .fork-proposal-card .initial-prompt-display {
          padding: 8px 10px;
          background: #0d1117;
          border-radius: 6px;
          font-size: 13px;
          color: #d1d5db;
          white-space: pre-wrap;
        }

        .fork-proposal-card .no-prompt {
          color: #6b7280;
        }

        .fork-proposal-card .fork-proposal-error {
          padding: 8px 12px;
          background: rgba(239, 68, 68, 0.15);
          border: 1px solid rgba(239, 68, 68, 0.3);
          border-radius: 6px;
          color: #fca5a5;
          font-size: 13px;
        }

        .fork-proposal-card .fork-proposal-actions {
          display: flex;
          align-items: center;
          gap: 12px;
          padding-top: 8px;
        }

        .fork-proposal-card .begin-fork-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 16px;
          background: #2563eb;
          border: none;
          border-radius: 6px;
          color: white;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: background 0.15s ease;
        }

        .fork-proposal-card .begin-fork-btn:hover:not(:disabled) {
          background: #1d4ed8;
        }

        .fork-proposal-card .begin-fork-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .fork-proposal-card .loading-indicator {
          color: #9ca3af;
          font-size: 13px;
        }

        .fork-proposal-card .fork-proposal-resolution {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 10px 12px;
          background: rgba(34, 197, 94, 0.1);
          border: 1px solid rgba(34, 197, 94, 0.2);
          border-radius: 6px;
          color: #4ade80;
          font-size: 13px;
        }

        .fork-proposal-card .go-to-fork-btn {
          margin-left: auto;
          padding: 4px 10px;
          background: #22c55e;
          border: none;
          border-radius: 4px;
          color: white;
          font-size: 12px;
          cursor: pointer;
        }

        .fork-proposal-card .go-to-fork-btn:hover {
          background: #16a34a;
        }
      `}</style>
    </BaseToolCard>
  );
}

export default ForkProposalCard;
