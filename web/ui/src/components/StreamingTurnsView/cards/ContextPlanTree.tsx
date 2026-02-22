/**
 * ContextPlanTree - Interactive tree for fork proposal context editing
 *
 * Displays exchanges as clickable tree nodes where users can:
 * - See each exchange with its mode (☑ copy, Σ compress, ☐ drop)
 * - Click to toggle modes (copy → compress → drop → copy)
 * - View exchange summaries
 *
 * Matches the TUI's ContextPlanTree behavior.
 */

import React, { useState, useCallback, useEffect, memo } from 'react';
import type { ExchangeSummary } from '../../../../../generated/types';
import './cards.css';

// Context mode options
type ContextMode = 'copy' | 'compress' | 'drop';

// Context assignment
export interface ContextAssignment {
  exchangeRange: string;
  mode: ContextMode;
  reason: string;
}

// Mode display configuration - matches TUI colors
const MODE_CONFIG: Record<ContextMode, { icon: string; color: string; label: string }> = {
  copy: { icon: '☑', color: 'var(--color-accent-green, #4caf50)', label: 'COPY' },
  compress: { icon: 'Σ', color: 'var(--color-accent-yellow, #ff9800)', label: 'COMPRESS' },
  drop: { icon: '☐', color: 'var(--color-text-muted, #888)', label: 'DROP' },
};

const MODE_CYCLE: ContextMode[] = ['copy', 'compress', 'drop'];

interface ContextPlanTreeProps {
  /** Original context plan from the proposal */
  contextPlan: ContextAssignment[];
  /** All exchanges in the session (for expanded view) */
  allExchanges?: ExchangeSummary[];
  /** Called when plan changes */
  onPlanChange: (plan: ContextAssignment[]) => void;
  /** Whether editing is disabled */
  disabled?: boolean;
}

/**
 * Resolve an exchange range string to a list of indices.
 *
 * Handles:
 * - "0", "5" - single index
 * - "0-3" - range (inclusive)
 * - "last" - last exchange
 * - "last-2" - last 3 exchanges
 * - "-3" - last 3 exchanges (negative indexing)
 * - "all" - all exchanges
 */
function resolveRange(rangeStr: string, numExchanges: number): number[] {
  const trimmed = rangeStr.trim();

  if (trimmed === 'all') {
    return Array.from({ length: numExchanges }, (_, i) => i);
  }

  if (trimmed === 'last') {
    return numExchanges > 0 ? [numExchanges - 1] : [];
  }

  // Handle "last-N" format
  if (trimmed.startsWith('last-')) {
    const n = parseInt(trimmed.slice(5), 10);
    if (!isNaN(n)) {
      const start = Math.max(0, numExchanges - n - 1);
      return Array.from({ length: numExchanges - start }, (_, i) => start + i);
    }
  }

  // Handle negative indexing "-N"
  if (trimmed.startsWith('-') && !trimmed.slice(1).includes('-')) {
    const n = parseInt(trimmed.slice(1), 10);
    if (!isNaN(n)) {
      const start = Math.max(0, numExchanges - n);
      return Array.from({ length: numExchanges - start }, (_, i) => start + i);
    }
  }

  // Handle "X-Y" range
  if (trimmed.includes('-')) {
    const parts = trimmed.split('-');
    if (parts.length === 2 && parts[0] !== undefined && parts[1] !== undefined) {
      const start = parseInt(parts[0], 10);
      const end = parseInt(parts[1], 10);
      if (!isNaN(start) && !isNaN(end)) {
        return Array.from({ length: end - start + 1 }, (_, i) => start + i);
      }
    }
  }

  // Try single index
  const idx = parseInt(trimmed, 10);
  if (!isNaN(idx)) {
    const resolvedIdx = idx < 0 ? numExchanges + idx : idx;
    return [resolvedIdx];
  }

  return [];
}

/**
 * Expand context plan to cover all exchanges.
 */
function expandContextPlan(
  contextPlan: ContextAssignment[],
  allExchanges: ExchangeSummary[]
): ContextAssignment[] {
  const numExchanges = allExchanges.length;
  if (numExchanges === 0) return [];

  // Start with default mode for all exchanges
  const modes: Map<number, { mode: ContextMode; reason: string }> = new Map();
  for (let i = 0; i < numExchanges; i++) {
    modes.set(i, { mode: 'compress', reason: '' });
  }

  // Apply context plan assignments
  for (const assignment of contextPlan) {
    const indices = resolveRange(assignment.exchangeRange, numExchanges);
    for (const idx of indices) {
      if (idx >= 0 && idx < numExchanges) {
        modes.set(idx, { mode: assignment.mode, reason: assignment.reason });
      }
    }
  }

  // Build expanded plan with exchange summaries
  return allExchanges.map((exchange, i) => {
    const { mode, reason } = modes.get(i) || { mode: 'compress' as ContextMode, reason: '' };
    const summary = exchange.summary || '';
    return {
      exchangeRange: String(i),
      mode,
      reason: reason || summary,
    };
  });
}

/**
 * Single tree node representing an exchange.
 */
const ContextTreeNode = memo(function ContextTreeNode({
  index,
  assignment,
  onToggle,
  disabled,
}: {
  index: number;
  assignment: ContextAssignment;
  onToggle: (index: number) => void;
  disabled?: boolean;
}) {
  const config = MODE_CONFIG[assignment.mode];
  const reason = assignment.reason || '';
  const truncatedReason = reason.length > 55 ? reason.slice(0, 52) + '...' : reason;

  const handleClick = useCallback(() => {
    if (!disabled) {
      onToggle(index);
    }
  }, [index, onToggle, disabled]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!disabled && (e.key === ' ' || e.key === 'Enter')) {
        e.preventDefault();
        onToggle(index);
      }
    },
    [index, onToggle, disabled]
  );

  return (
    <div
      className={`context-tree-node mode-${assignment.mode} ${disabled ? 'disabled' : ''}`}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      tabIndex={disabled ? -1 : 0}
      role="button"
      aria-label={`Exchange ${assignment.exchangeRange}: ${config.label}. ${truncatedReason}`}
    >
      <span className="node-icon" style={{ color: config.color }}>
        {config.icon}
      </span>
      <span className="node-index" style={{ color: config.color }}>
        {assignment.exchangeRange}
      </span>
      <span className={`node-reason ${assignment.mode === 'drop' ? 'dimmed' : ''}`}>
        {truncatedReason}
      </span>
    </div>
  );
});

/**
 * Interactive context plan tree.
 */
export const ContextPlanTree = memo(function ContextPlanTree({
  contextPlan,
  allExchanges,
  onPlanChange,
  disabled,
}: ContextPlanTreeProps) {
  // Expand the context plan to show all exchanges
  const [expandedPlan, setExpandedPlan] = useState<ContextAssignment[]>(() => {
    if (allExchanges && allExchanges.length > 0) {
      return expandContextPlan(contextPlan, allExchanges);
    }
    return contextPlan;
  });

  // Re-expand when allExchanges prop changes (e.g., after async fetch completes)
  // This is critical because the initial render happens before exchanges are loaded
  useEffect(() => {
    if (allExchanges && allExchanges.length > 0) {
      setExpandedPlan(expandContextPlan(contextPlan, allExchanges));
    } else if (contextPlan.length > 0) {
      // If no allExchanges provided, use contextPlan directly
      setExpandedPlan(contextPlan);
    }
  }, [allExchanges, contextPlan]);

  const handleToggle = useCallback(
    (index: number) => {
      setExpandedPlan((prev) => {
        const newPlan = [...prev];
        const assignment = newPlan[index];
        if (!assignment) return prev;

        // Cycle to next mode
        const currentIdx = MODE_CYCLE.indexOf(assignment.mode);
        const nextIdx = (currentIdx + 1) % MODE_CYCLE.length;
        const nextMode = MODE_CYCLE[nextIdx] as ContextMode;
        newPlan[index] = { ...assignment, mode: nextMode };

        // Notify parent
        onPlanChange(newPlan);
        return newPlan;
      });
    },
    [onPlanChange]
  );

  if (expandedPlan.length === 0) {
    return (
      <div className="context-tree-empty">
        No exchanges to display
      </div>
    );
  }

  return (
    <div className="context-plan-tree" role="tree" aria-label="Context plan">
      {!disabled && (
        <div className="context-tree-hint">
          Click to toggle: copy → compress → drop
        </div>
      )}
      <div className="context-tree-nodes">
        {expandedPlan.map((assignment, index) => (
          <ContextTreeNode
            key={`${assignment.exchangeRange}-${index}`}
            index={index}
            assignment={assignment}
            onToggle={handleToggle}
            disabled={disabled}
          />
        ))}
      </div>
    </div>
  );
});

export default ContextPlanTree;
