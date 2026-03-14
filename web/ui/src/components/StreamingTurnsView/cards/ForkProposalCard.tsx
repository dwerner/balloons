/**
 * ForkProposalCard - Interactive card for propose_fork tool calls
 *
 * Renders the propose_fork tool_result as an interactive UI with:
 * - Fork name and description
 * - Interactive context tree (click to toggle modes)
 * - Editable initial prompt
 * - "Begin Fork" button (hidden after fork is created)
 * - "Go to fork" button (shown after fork is created)
 *
 * The tool_result JSON is the source of truth for proposal state.
 * When the user accepts the fork, the result is updated with _status and _child_session_id.
 *
 * Uses BaseToolCard for consistent formatting/raw mode switching.
 */

import React, { useState, useCallback, useEffect, useMemo } from 'react';
import type { SessionDataTurn } from '../../../hooks/useSessionData';
import type { ToolUseBlock, ToolResultBlock, ExchangeSummary } from '../../../../../generated/types';
import { useClient, useSelectSession } from './ClientContext';
import { ContextPlanTree, type ContextAssignment } from './ContextPlanTree';
import { BaseToolCard, calculateToolPhase, type ToolPhase } from './BaseToolCard';
import './cards.css';

// Context mode type
type ContextMode = 'copy' | 'compress' | 'drop';

// Status for the fork action
type ForkStatus = 'pending' | 'creating' | 'accepted' | 'rejected' | 'error';

interface ForkProposalCardProps {
  turn: SessionDataTurn;
  result?: SessionDataTurn | null;
  sessionId?: string;
}

// Check if tool input is still streaming
function isStreamingInput(input: Record<string, unknown>): boolean {
  return typeof input._streaming === 'string';
}

// Parse proposal data from tool_result JSON content
// Returns null if not valid JSON or not a fork_proposal
function parseResultProposal(resultContent: string): {
  name: string;
  description: string;
  contextPlan: ContextAssignment[];
  initialPrompt: string;
  bindTo: { entityType: string; entityId: string; role: string } | null;
  bindToInherit: boolean;
  status: ForkStatus;
  childSessionId: string | null;
} | null {
  if (!resultContent) return null;

  try {
    const data = JSON.parse(resultContent);
    if (data._type !== 'fork_proposal') return null;

    const rawContextPlan = Array.isArray(data.context_plan) ? data.context_plan : [];
    const bindToRaw = data.bind_to;

    return {
      name: data.name || '',
      description: data.description || '',
      contextPlan: rawContextPlan.map((cp: Record<string, unknown>) => ({
        exchangeRange: (cp.exchange_range as string) || '',
        mode: ((cp.mode as string) || 'compress').toLowerCase() as ContextMode,
        reason: (cp.reason as string) || '',
      })),
      initialPrompt: data.initial_prompt || '',
      bindTo: bindToRaw && typeof bindToRaw === 'object' ? {
        entityType: bindToRaw.entity_type || '',
        entityId: bindToRaw.entity_id || '',
        role: bindToRaw.role || '',
      } : null,
      bindToInherit: bindToRaw === 'inherit',
      status: (data._status as ForkStatus) || 'pending',
      childSessionId: data._child_session_id || null,
    };
  } catch {
    return null;
  }
}

// Legacy: Extract proposal data from tool_use input (fallback for old proposals)
function extractProposalFromInput(input: Record<string, unknown>) {
  const rawContextPlanValue = input.contextPlan ?? input.context_plan;
  const rawContextPlan = Array.isArray(rawContextPlanValue) ? rawContextPlanValue : [];
  const bindToRaw = input.bindTo ?? input.bind_to;

  return {
    name: (input.name as string) || '',
    description: (input.description as string) || '',
    contextPlan: rawContextPlan.map((cp: unknown) => {
      const item = cp as Record<string, unknown>;
      return {
        exchangeRange: (item.exchangeRange as string) || (item.exchange_range as string) || '',
        mode: ((item.mode as string) || 'compress').toLowerCase() as ContextMode,
        reason: (item.reason as string) || '',
      };
    }),
    initialPrompt: (input.initialPrompt as string) || (input.initial_prompt as string) || '',
    bindTo: bindToRaw && typeof bindToRaw === 'object' ? {
      entityType: ((bindToRaw as Record<string, unknown>).entityType as string) || ((bindToRaw as Record<string, unknown>).entity_type as string) || '',
      entityId: ((bindToRaw as Record<string, unknown>).entityId as string) || ((bindToRaw as Record<string, unknown>).entity_id as string) || '',
      role: ((bindToRaw as Record<string, unknown>).role as string) || '',
    } : null,
    bindToInherit: bindToRaw === 'inherit',
    // Legacy: check if status was persisted in tool_use input (old behavior)
    status: ((input._status as string) === 'accepted' ? 'accepted' : 'pending') as ForkStatus,
    childSessionId: (input._child_session_id as string) || null,
  };
}

/**
 * ForkProposalCard - Renders propose_fork with interactive UI
 *
 * State is sourced from tool_result (preferred) or tool_use input (legacy fallback).
 */
export const ForkProposalCard = React.memo(function ForkProposalCard({
  turn,
  result,
  sessionId,
}: ForkProposalCardProps) {
  const client = useClient();
  const selectSession = useSelectSession();
  const { contentBlock, streaming, tokens } = turn;

  // Extract tool_use info
  const toolUseBlock = contentBlock?.type === 'tool_use'
    ? (contentBlock as ToolUseBlock)
    : null;
  const toolInput = (toolUseBlock?.input || {}) as Record<string, unknown>;
  const inputIsStreaming = isStreamingInput(toolInput);
  const toolUseId = toolUseBlock?.id || '';

  // Extract tool_result info
  const resultBlock = result?.contentBlock?.type === 'tool_result'
    ? (result.contentBlock as ToolResultBlock)
    : null;
  const resultContent = typeof resultBlock?.content === 'string' ? resultBlock.content : '';

  // Parse proposal data from result (preferred) or input (legacy fallback)
  // Note: _status and _child_session_id are set in tool_use input by the server
  // when the fork is accepted, so we need to check both places
  const proposalData = useMemo(() => {
    // Try parsing from tool_result first (new behavior)
    const fromResult = parseResultProposal(resultContent);
    if (fromResult) {
      // Override status/childSessionId from tool_use input if the server set them
      // (server updates tool_use.input, not tool_result content)
      const serverStatus = toolInput._status as string | undefined;
      const serverChildId = toolInput._child_session_id as string | undefined;
      if (serverStatus === 'accepted' && serverChildId) {
        return {
          ...fromResult,
          status: 'accepted' as ForkStatus,
          childSessionId: serverChildId,
        };
      }
      return fromResult;
    }

    // Fallback to tool_use input (legacy behavior)
    return extractProposalFromInput(toolInput);
  }, [resultContent, toolInput]);

  // Local state for modifications
  const [contextPlan, setContextPlan] = useState<ContextAssignment[]>(proposalData.contextPlan);
  const [initialPrompt, setInitialPrompt] = useState(proposalData.initialPrompt);
  const [isEditingPrompt, setIsEditingPrompt] = useState(false);
  const [status, setStatus] = useState<ForkStatus>(proposalData.status);
  const [error, setError] = useState<string | null>(null);
  const [childSessionId, setChildSessionId] = useState<string | null>(proposalData.childSessionId);
  const [exchanges, setExchanges] = useState<ExchangeSummary[]>([]);

  // Update local state when proposal data changes (e.g., after fork accepted and result updated)
  useEffect(() => {
    if (!inputIsStreaming) {
      setContextPlan(proposalData.contextPlan);
      setInitialPrompt(proposalData.initialPrompt);
      setStatus(proposalData.status);
      setChildSessionId(proposalData.childSessionId);
    }
  }, [inputIsStreaming, proposalData]);

  // Fetch exchange summaries on mount when pending
  useEffect(() => {
    if (status === 'pending' && client && sessionId && !inputIsStreaming) {
      client.sessions.getExchangeSummaries(sessionId, true)
        .then(setExchanges)
        .catch((err) => console.warn('Failed to fetch exchanges:', err));
    }
  }, [status, client, sessionId, inputIsStreaming]);

  // Calculate phase for BaseToolCard
  const hasInput = !inputIsStreaming && proposalData.name.length > 0;
  const hasResult = !!result;
  const isError = status === 'error';
  const phase: ToolPhase = status === 'accepted' ? 'completed'
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

      const forkResult = await client.sessions.respondToForkProposal(
        sessionId,
        toolUseId, // Use tool_use ID as proposal ID
        true, // accepted
        apiContextPlan,
        initialPrompt || null,
        proposalData.name || null,
        proposalData.description || null,
        true, // start streaming
      );

      if (forkResult.success && forkResult.accepted) {
        setStatus('accepted');
        setChildSessionId(forkResult.childSessionId || null);
        // Navigate to the new fork session
        if (forkResult.childSessionId && selectSession) {
          if (forkResult.needsCompression) {
            console.warn('[ForkProposalCard] Fork needs compression - context may not be ready yet');
          }
          selectSession(forkResult.childSessionId);
        }
      } else {
        setStatus('error');
        setError(forkResult.error || 'Failed to create fork');
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

  const isPending = status === 'pending';
  const isCreating = status === 'creating';
  const isAccepted = status === 'accepted';

  return (
    <BaseToolCard
      toolName="propose_fork"
      phase={phase}
      tokens={tokens}
      order={turn.order}
      orderEnd={result?.order}
      className="fork-proposal-card"
      rawData={rawData}
      timestamp={turn.timestamp}
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
          {/* Summary row - always visible (description + action) */}
          <div className="fork-proposal-summary">
            <div className="fork-proposal-description">
              {proposalData.description}
            </div>

            {/* Action buttons inline with description */}
            {isPending && (
              <button
                className="btn btn-primary begin-fork-btn"
                onClick={handleBeginFork}
                disabled={!client}
                type="button"
              >
                Begin Fork
              </button>
            )}

            {isCreating && (
              <span className="loading-indicator">Creating fork...</span>
            )}

            {isAccepted && childSessionId && selectSession && (
              <button
                className="btn btn-primary btn-small go-to-fork-btn"
                onClick={handleGoToFork}
                type="button"
              >
                Go to fork
              </button>
            )}
          </div>

          {/* Completion state message */}
          {isAccepted && (
            <div className="fork-proposal-resolution status-accepted">
              <span>✓ Fork created successfully</span>
            </div>
          )}

          {/* Error message */}
          {error && (
            <div className="fork-proposal-error">
              {error}
            </div>
          )}

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
              disabled={!isPending || isCreating}
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
                  type="button"
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

        .fork-proposal-card .fork-proposal-summary {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          justify-content: space-between;
        }

        .fork-proposal-card .fork-proposal-summary .fork-proposal-description {
          flex: 1;
          min-width: 0;
        }

        .fork-proposal-card .fork-proposal-summary .begin-fork-btn,
        .fork-proposal-card .fork-proposal-summary .go-to-fork-btn {
          flex-shrink: 0;
        }

        .fork-proposal-card .fork-proposal-summary .loading-indicator {
          flex-shrink: 0;
          color: #9ca3af;
          font-size: 13px;
        }

        .fork-proposal-card .fork-proposal-details {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .fork-proposal-card .fork-proposal-description {
          color: var(--color-text-primary, #e5e7eb);
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
});

export default ForkProposalCard;
