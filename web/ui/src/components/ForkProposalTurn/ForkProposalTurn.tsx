/**
 * ForkProposalTurn - Inline component for displaying fork proposals in chat flow.
 *
 * Displays Claude's fork proposals with:
 * - Fork name and description
 * - Editable context plan table with COPY/COMPRESS/DROP dropdowns
 * - Token reduction estimate
 * - Editable initial prompt
 * - Accept/Edit/Reject buttons
 *
 * Parses balloons-tool JSON with name="propose_fork" from assistant content.
 */

import React, { useState, useMemo, useCallback, memo } from 'react';
import type { TurnInfo } from '../../../../generated/balloons-client';
import './ForkProposalTurn.css';

// Context mode options
type ContextMode = 'copy' | 'compress' | 'drop';

// Context assignment from the proposal
interface ContextAssignment {
  exchangeRange: string;  // e.g., "0-2", "5", "last", "all"
  mode: ContextMode;
  reason: string;
}

// Exchange info for the interactive tree
interface ExchangeInfo {
  index: number;
  summary: string;
  mode: ContextMode;
}

// Binding specification
interface ForkBinding {
  entityType: string;  // "goal", "plan", or "todo"
  entityId: string;
  role: string;  // "interview", "planning", "implementation", etc.
}

// Parsed fork proposal data
export interface ForkProposalData {
  proposalId: string;
  name: string;
  description: string;
  contextPlan: ContextAssignment[];
  initialPrompt: string;
  bindTo: ForkBinding | null;
  bindToInherit: boolean;
  status: 'pending' | 'accepted' | 'rejected';
  allExchanges: ExchangeInfo[];
}

// Props for the component
interface ForkProposalTurnProps {
  turn: TurnInfo;
  onAccept?: (proposal: ForkProposalData) => void;
  onReject?: (proposalId: string) => void;
}

// Mode display configuration
const MODE_CONFIG: Record<ContextMode, { icon: string; color: string; label: string }> = {
  copy: { icon: '\u2611', color: 'var(--color-accent-green)', label: 'COPY' },
  compress: { icon: '\u03A3', color: 'var(--color-accent-yellow)', label: 'COMPRESS' },
  drop: { icon: '\u2610', color: 'var(--color-text-muted)', label: 'DROP' },
};

const MODE_CYCLE: ContextMode[] = ['copy', 'compress', 'drop'];

/**
 * Parse balloons-tool JSON from assistant content to extract fork proposal.
 */
export function parseForkProposal(content: string): ForkProposalData | null {
  // Look for <balloons-tool>...</balloons-tool> blocks
  const toolMatch = content.match(/<balloons-tool>\s*([\s\S]*?)\s*<\/balloons-tool>/);
  if (!toolMatch || !toolMatch[1]) {
    return null;
  }

  try {
    const toolJson = JSON.parse(toolMatch[1]);

    // Check if this is a propose_fork tool call
    if (toolJson.name !== 'propose_fork') {
      return null;
    }

    const args = toolJson.args || {};

    // Parse context plan
    const contextPlan: ContextAssignment[] = (args.context_plan || []).map((item: any) => ({
      exchangeRange: item.exchange_range || '',
      mode: (item.mode || 'compress').toLowerCase() as ContextMode,
      reason: item.reason || '',
    }));

    // Parse binding
    let bindTo: ForkBinding | null = null;
    let bindToInherit = false;
    if (args.bind_to === 'inherit') {
      bindToInherit = true;
    } else if (args.bind_to && typeof args.bind_to === 'object') {
      bindTo = {
        entityType: args.bind_to.entity_type || '',
        entityId: args.bind_to.entity_id || '',
        role: args.bind_to.role || '',
      };
    }

    // Generate a proposal ID if not present
    const proposalId = args.proposal_id || `fp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    return {
      proposalId,
      name: args.name || 'unnamed-fork',
      description: args.description || '',
      contextPlan,
      initialPrompt: args.initial_prompt || '',
      bindTo,
      bindToInherit,
      status: 'pending',
      allExchanges: [], // Would be populated from session data if available
    };
  } catch (e) {
    console.warn('Failed to parse fork proposal:', e);
    return null;
  }
}

/**
 * Context mode dropdown component.
 */
const ContextModeDropdown = memo(function ContextModeDropdown({
  mode,
  onChange,
  disabled,
}: {
  mode: ContextMode;
  onChange: (mode: ContextMode) => void;
  disabled?: boolean;
}) {
  const config = MODE_CONFIG[mode];

  return (
    <select
      className={`context-mode-dropdown mode-${mode}`}
      value={mode}
      onChange={(e) => onChange(e.target.value as ContextMode)}
      disabled={disabled}
      style={{ color: config.color }}
    >
      {MODE_CYCLE.map((m) => (
        <option key={m} value={m}>
          {MODE_CONFIG[m].icon} {MODE_CONFIG[m].label}
        </option>
      ))}
    </select>
  );
});

/**
 * Context plan row component.
 */
const ContextPlanRow = memo(function ContextPlanRow({
  assignment,
  index,
  onModeChange,
  onReasonChange,
  disabled,
}: {
  assignment: ContextAssignment;
  index: number;
  onModeChange: (index: number, mode: ContextMode) => void;
  onReasonChange: (index: number, reason: string) => void;
  disabled?: boolean;
}) {
  const config = MODE_CONFIG[assignment.mode];

  return (
    <tr className={`context-plan-row mode-${assignment.mode}`}>
      <td className="context-plan-range">
        <span className="mode-icon" style={{ color: config.color }}>
          {config.icon}
        </span>
        <code>{assignment.exchangeRange}</code>
      </td>
      <td className="context-plan-mode">
        <ContextModeDropdown
          mode={assignment.mode}
          onChange={(mode) => onModeChange(index, mode)}
          disabled={disabled}
        />
      </td>
      <td className="context-plan-reason">
        {disabled ? (
          <span className="reason-text">{assignment.reason}</span>
        ) : (
          <input
            type="text"
            className="reason-input"
            value={assignment.reason}
            onChange={(e) => onReasonChange(index, e.target.value)}
            placeholder="Reason for this mode..."
          />
        )}
      </td>
    </tr>
  );
});

/**
 * Context plan table component.
 */
const ContextPlanTable = memo(function ContextPlanTable({
  contextPlan,
  onPlanChange,
  disabled,
}: {
  contextPlan: ContextAssignment[];
  onPlanChange: (plan: ContextAssignment[]) => void;
  disabled?: boolean;
}) {
  const handleModeChange = useCallback(
    (index: number, mode: ContextMode) => {
      const newPlan = contextPlan.map((item, i) =>
        i === index ? { ...item, mode } : item
      );
      onPlanChange(newPlan);
    },
    [contextPlan, onPlanChange]
  );

  const handleReasonChange = useCallback(
    (index: number, reason: string) => {
      const newPlan = contextPlan.map((item, i) =>
        i === index ? { ...item, reason } : item
      );
      onPlanChange(newPlan);
    },
    [contextPlan, onPlanChange]
  );

  if (contextPlan.length === 0) {
    return (
      <div className="context-plan-empty">
        No context assignments specified
      </div>
    );
  }

  return (
    <table className="context-plan-table">
      <thead>
        <tr>
          <th>Exchange</th>
          <th>Mode</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {contextPlan.map((assignment, index) => (
          <ContextPlanRow
            key={`${assignment.exchangeRange}-${index}`}
            assignment={assignment}
            index={index}
            onModeChange={handleModeChange}
            onReasonChange={handleReasonChange}
            disabled={disabled}
          />
        ))}
      </tbody>
    </table>
  );
});

/**
 * Token estimate display component.
 */
const TokenEstimate = memo(function TokenEstimate({
  currentTokens,
  estimatedTokens,
}: {
  currentTokens?: number;
  estimatedTokens?: number;
}) {
  // For now, show placeholder if we don't have real token counts
  const current = currentTokens || 0;
  const estimated = estimatedTokens || 0;
  const reduction = current > 0 ? Math.round((1 - estimated / current) * 100) : 0;

  if (current === 0) {
    return null;
  }

  return (
    <div className="token-estimate">
      <span className="token-label">Token estimate:</span>
      <span className="token-current">{current.toLocaleString()}</span>
      <span className="token-arrow">\u2192</span>
      <span className="token-estimated">{estimated.toLocaleString()}</span>
      {reduction > 0 && (
        <span className="token-reduction">(-{reduction}%)</span>
      )}
    </div>
  );
});

/**
 * Main ForkProposalTurn component.
 */
export const ForkProposalTurn = memo(function ForkProposalTurn({
  turn,
  onAccept,
  onReject,
}: ForkProposalTurnProps) {
  // Parse proposal from turn content
  const parsedProposal = useMemo(
    () => parseForkProposal(turn.content || ''),
    [turn.content]
  );

  // Local state for editing
  const [contextPlan, setContextPlan] = useState<ContextAssignment[]>(
    parsedProposal?.contextPlan || []
  );
  const [initialPrompt, setInitialPrompt] = useState(
    parsedProposal?.initialPrompt || ''
  );
  const [status, setStatus] = useState<'pending' | 'accepted' | 'rejected'>(
    parsedProposal?.status || 'pending'
  );
  const [isEditing, setIsEditing] = useState(false);

  // Hooks must run unconditionally, so the "no proposal" guard lives below
  // them. The handlers guard against a null proposal internally.
  const handleAccept = useCallback(() => {
    setStatus('accepted');
    if (onAccept && parsedProposal) {
      onAccept({
        ...parsedProposal,
        contextPlan,
        initialPrompt,
        status: 'accepted',
      });
    }
  }, [parsedProposal, contextPlan, initialPrompt, onAccept]);

  const handleReject = useCallback(() => {
    setStatus('rejected');
    if (onReject && parsedProposal) {
      onReject(parsedProposal.proposalId);
    }
  }, [parsedProposal, onReject]);

  const handleEdit = useCallback(() => {
    setIsEditing(true);
  }, []);

  const handleSaveEdit = useCallback(() => {
    setIsEditing(false);
  }, []);

  // If no proposal found, render nothing
  if (!parsedProposal) {
    return null;
  }

  const { proposalId, name, description, bindTo, bindToInherit } = parsedProposal;
  const isPending = status === 'pending';

  return (
    <div className={`fork-proposal-turn status-${status}`}>
      {/* Header */}
      <div className="fork-proposal-header">
        <span className="fork-proposal-icon">\u2442</span>
        <span className="fork-proposal-title">Fork Proposal</span>
        <span className={`fork-proposal-status status-${status}`}>
          {status === 'pending' && '\u23F3 Pending'}
          {status === 'accepted' && '\u2713 Accepted'}
          {status === 'rejected' && '\u2717 Rejected'}
        </span>
      </div>

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
            ) : (
              <span className="value">
                {bindTo?.entityType} <code>{bindTo?.entityId.slice(0, 8)}...</code>
                {bindTo?.role && ` (${bindTo.role})`}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Context plan section */}
      <div className="fork-proposal-section">
        <div className="section-header">
          <span className="section-title">Context Plan</span>
          <span className="section-hint">
            {isPending && !isEditing && 'Click Edit to modify'}
          </span>
        </div>
        <ContextPlanTable
          contextPlan={contextPlan}
          onPlanChange={setContextPlan}
          disabled={!isEditing && !isPending}
        />
      </div>

      {/* Token estimate */}
      <TokenEstimate />

      {/* Initial prompt section */}
      <div className="fork-proposal-section">
        <div className="section-header">
          <span className="section-title">Initial Prompt</span>
        </div>
        {isPending && isEditing ? (
          <textarea
            className="initial-prompt-input"
            value={initialPrompt}
            onChange={(e) => setInitialPrompt(e.target.value)}
            placeholder="Initial prompt for the fork..."
            rows={3}
          />
        ) : (
          <div className="initial-prompt-display">
            {initialPrompt || <em className="no-prompt">No initial prompt specified</em>}
          </div>
        )}
      </div>

      {/* Action buttons */}
      {isPending && (
        <div className="fork-proposal-actions">
          {isEditing ? (
            <button className="btn btn-primary" onClick={handleSaveEdit}>
              Done Editing
            </button>
          ) : (
            <button className="btn btn-secondary" onClick={handleEdit}>
              Edit
            </button>
          )}
          <button className="btn btn-success" onClick={handleAccept}>
            Accept
          </button>
          <button className="btn btn-danger" onClick={handleReject}>
            Reject
          </button>
        </div>
      )}

      {/* Status message for resolved proposals */}
      {!isPending && (
        <div className={`fork-proposal-resolution status-${status}`}>
          {status === 'accepted' && 'Fork created successfully'}
          {status === 'rejected' && 'Fork proposal was rejected'}
        </div>
      )}
    </div>
  );
});

export default ForkProposalTurn;
