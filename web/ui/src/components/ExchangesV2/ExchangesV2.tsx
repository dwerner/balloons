/**
 * ExchangesV2 - Redesigned exchange tree view
 *
 * A cleaner implementation of the context exchange view with:
 * - Stable exchange IDs based on turn IDs (not indices)
 * - Virtualized rendering for large conversations
 * - Better separation of concerns
 * - Fixed event handling for toggle arrows
 */

import React, { useState, useCallback, useMemo, memo, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { TurnInfo, BalloonsClient } from '../../../../generated/balloons-client';
import type { SessionDataTurn } from '../../hooks/useSessionData';
import { TurnCard } from '../StreamingTurnsView/cards';
import { ClientContext } from '../StreamingTurnsView/cards/ClientContext';
import { createLogger } from '../../utils/debugLog';
import { formatTimestamp } from '../../utils';
import './ExchangesV2.css';

const log = createLogger('ExchangesV2');

// ============================================================================
// Types
// ============================================================================

export type ExchangeAction = 'archive' | 'delete' | 'restore';

export interface Exchange {
  /** Stable ID based on first turn ID, or fallback */
  id: string;
  /** User message that started this exchange */
  userTurn: TurnInfo | null;
  /** Assistant responses (text, tool_use) */
  assistantTurns: TurnInfo[];
  /** System messages (archive, fork, merge, etc.) */
  systemTurns: TurnInfo[];
  /** All turn indices in this exchange */
  turnIndices: number[];
  /** All turn IDs in this exchange */
  turnIds: string[];
  /** Total tokens in this exchange */
  totalTokens: number;
  /** Timestamp of first turn */
  timestamp?: string;
}

interface ExchangesV2Props {
  sessionId: string | null;
  turns: TurnInfo[];
  rawTurns?: SessionDataTurn[];
  client?: BalloonsClient | null;
  totalTokens?: number;
  onSelectTurn?: (turnIdx: number) => void;
  onExchangeAction?: (turnIndices: number[], turnIds: string[], action: ExchangeAction) => void;
  onDeleteTurn?: (turnIdx: number) => void;
  onAddToLinkStash?: (turnIndices: number[], excerpt: string) => void;
  onLoadFullHistory?: () => void;
  isLoading?: boolean;
  archivingTurnIds?: Set<string>;
  isLoadingHistory?: boolean;
}

// ============================================================================
// Utility Functions
// ============================================================================

function formatTokens(tokens: number): string {
  if (tokens <= 0) return '';
  const kt = Math.ceil(tokens / 100) / 10;
  if (kt < 1) return `.${Math.floor(kt * 10)}kt`;
  return `${kt.toFixed(1)}kt`;
}

function getTokenWeightClass(tokens: number): string {
  if (tokens >= 10000) return 'exv2-node--tokens-heavy';
  if (tokens >= 5000) return 'exv2-node--tokens-large';
  if (tokens >= 2000) return 'exv2-node--tokens-medium';
  if (tokens >= 500) return 'exv2-node--tokens-light';
  return '';
}

function getTurnIcon(turn: TurnInfo): string {
  if (turn.role === 'user') return '👤';
  if (turn.role === 'assistant') {
    if (turn.contentBlockType === 'tool_use' || turn.toolUse) return '🔧';
    return '🤖';
  }
  // System/tool role
  switch (turn.contentBlockType) {
    case 'tool_result': return '📋';
    case 'archive': return '📦';
    case 'fork': return '⑂';
    case 'merge':
    case 'merged_to': return '⤴';
    case 'link': return '🔗';
    case 'interruption': return '⚠';
    case 'error': return '✗';
    default: return '⚙';
  }
}

function getToolPreview(turn: TurnInfo): string {
  if (!turn.toolUse) return turn.content?.slice(0, 100).replace(/\n/g, ' ') || '';

  const toolName = turn.toolUse.name || 'Tool';
  try {
    const input = JSON.parse(turn.toolUse.inputJson || '{}');
    switch (toolName) {
      case 'Read': {
        const filePath = input.file_path || '';
        const fileName = filePath.split('/').pop() || filePath;
        const parts = [fileName];
        if (input.offset) parts.push(`@${input.offset}`);
        if (input.limit) parts.push(`+${input.limit}`);
        return `Read: ${parts.join(' ')}`;
      }
      case 'Edit': {
        const editPath = input.file_path || '';
        const editName = editPath.split('/').pop() || editPath;
        const oldLines = input.old_string ? input.old_string.split('\n').length : 0;
        const newLines = input.new_string ? input.new_string.split('\n').length : 0;
        if (oldLines === 0 && newLines === 0) return `Edit: ${editName}`;
        return `Edit: ${editName} (${oldLines}→${newLines} lines)`;
      }
      case 'Write': {
        const writePath = input.file_path || '';
        const writeName = writePath.split('/').pop() || writePath;
        const contentLen = (input.content || '').length;
        return `Write: ${writeName} (${contentLen} chars)`;
      }
      case 'Bash': {
        const cmd = input.command || '';
        return `Bash: ${cmd.length > 40 ? cmd.slice(0, 40) + '...' : cmd}`;
      }
      case 'Grep': {
        const pattern = input.pattern || '';
        const grepPath = input.path ? ` in ${input.path.split('/').pop()}` : '';
        return `Grep: "${pattern}"${grepPath}`;
      }
      case 'Glob': {
        const globPattern = input.pattern || '';
        const globPath = input.path ? ` in ${input.path.split('/').pop()}` : '';
        return `Glob: ${globPattern}${globPath}`;
      }
      case 'WebFetch': {
        const url = input.url || '';
        const domain = url.replace(/^https?:\/\//, '').split('/')[0];
        return `WebFetch: ${domain}`;
      }
      case 'WebSearch':
        return `WebSearch: "${input.query || ''}"`;
      default: {
        const entries = Object.entries(input).slice(0, 2);
        if (entries.length === 0) return toolName;
        const summary = entries.map(([k, v]) => {
          const val = typeof v === 'string' ? v.slice(0, 20) : String(v);
          return `${k}=${val}`;
        }).join(', ');
        return `${toolName}: ${summary}`;
      }
    }
  } catch {
    return toolName;
  }
}

// ============================================================================
// Exchange Grouping
// ============================================================================

function groupTurnsIntoExchanges(
  turns: TurnInfo[],
  rawTurnByIdx: Map<number, SessionDataTurn>
): Exchange[] {
  const exchanges: Exchange[] = [];
  const exchangeMap = new Map<string, Exchange>();
  let currentExchangeId: string | null = null;
  let fallbackCounter = 0;

  // Helper to get or create exchange
  const getOrCreateExchange = (id: string, timestamp?: string): Exchange => {
    let exchange = exchangeMap.get(id);
    if (!exchange) {
      exchange = {
        id,
        userTurn: null,
        assistantTurns: [],
        systemTurns: [],
        turnIndices: [],
        turnIds: [],
        totalTokens: 0,
        timestamp,
      };
      exchangeMap.set(id, exchange);
      exchanges.push(exchange);
    }
    return exchange;
  };

  // Sort by idx to ensure proper ordering
  const sortedTurns = [...turns].sort((a, b) => a.idx - b.idx);

  for (const turn of sortedTurns) {
    const rawTurn = rawTurnByIdx.get(turn.idx);
    const turnExchangeId = turn.exchangeId;
    const turnId = rawTurn?.turnId || `turn-${turn.idx}`;

    if (turn.role === 'user') {
      // User turn starts a new exchange
      const exchangeId = turnExchangeId || turnId;
      const exchange = getOrCreateExchange(exchangeId, rawTurn?.timestamp);
      exchange.userTurn = turn;
      exchange.turnIndices.push(turn.idx);
      exchange.turnIds.push(turnId);
      exchange.totalTokens += turn.tokens || 0;
      if (!exchange.timestamp) exchange.timestamp = rawTurn?.timestamp;
      currentExchangeId = exchangeId;
    } else if (turn.role === 'assistant' || turn.role === 'tool') {
      // Assistant/tool turns belong to current exchange or their own exchangeId
      const targetExchangeId: string = turnExchangeId || currentExchangeId || `orphan-${fallbackCounter++}`;
      const exchange = getOrCreateExchange(targetExchangeId, rawTurn?.timestamp);
      exchange.assistantTurns.push(turn);
      exchange.turnIndices.push(turn.idx);
      exchange.turnIds.push(turnId);
      exchange.totalTokens += turn.tokens || 0;
      currentExchangeId = targetExchangeId;
    } else {
      // System turn - use its own exchangeId if it has one, otherwise current exchange
      if (turnExchangeId && turnExchangeId !== currentExchangeId) {
        // System turn with unique exchangeId (e.g., archive)
        const exchange = getOrCreateExchange(turnExchangeId, rawTurn?.timestamp);
        exchange.systemTurns.push(turn);
        exchange.turnIndices.push(turn.idx);
        exchange.turnIds.push(turnId);
        exchange.totalTokens += turn.tokens || 0;
        // Don't update currentExchangeId - system blocks are standalone
      } else if (currentExchangeId) {
        // Add to current exchange
        const exchange = exchangeMap.get(currentExchangeId);
        if (exchange) {
          exchange.systemTurns.push(turn);
          exchange.turnIndices.push(turn.idx);
          exchange.turnIds.push(turnId);
          exchange.totalTokens += turn.tokens || 0;
        }
      } else {
        // System turn at start - create exchange for it
        const exchangeId = turnExchangeId || `system-${fallbackCounter++}`;
        const exchange = getOrCreateExchange(exchangeId, rawTurn?.timestamp);
        exchange.systemTurns.push(turn);
        exchange.turnIndices.push(turn.idx);
        exchange.turnIds.push(turnId);
        exchange.totalTokens += turn.tokens || 0;
      }
    }
  }

  return exchanges;
}

// Group parallel tool calls by parallelGroupId
interface TurnOrGroup {
  type: 'single' | 'parallel';
  turns: TurnInfo[];
  groupId?: string;
}

function groupParallelTurns(
  turns: TurnInfo[],
  rawTurnByIdx: Map<number, SessionDataTurn>
): TurnOrGroup[] {
  const result: TurnOrGroup[] = [];
  let currentGroup: TurnInfo[] = [];
  let currentGroupId: string | undefined;

  for (const turn of turns) {
    const rawTurn = rawTurnByIdx.get(turn.idx);
    const groupId = rawTurn?.parallelGroupId;
    const isToolUse = turn.contentBlockType === 'tool_use' || rawTurn?.contentBlock?.type === 'tool_use';

    if (groupId && groupId === currentGroupId && isToolUse) {
      currentGroup.push(turn);
    } else {
      // Flush previous group
      if (currentGroup.length > 1 && currentGroupId) {
        result.push({ type: 'parallel', turns: currentGroup, groupId: currentGroupId });
      } else {
        for (const t of currentGroup) {
          result.push({ type: 'single', turns: [t] });
        }
      }
      // Start new
      if (groupId && isToolUse) {
        currentGroup = [turn];
        currentGroupId = groupId;
      } else {
        result.push({ type: 'single', turns: [turn] });
        currentGroup = [];
        currentGroupId = undefined;
      }
    }
  }

  // Flush final group
  if (currentGroup.length > 1 && currentGroupId) {
    result.push({ type: 'parallel', turns: currentGroup, groupId: currentGroupId });
  } else {
    for (const t of currentGroup) {
      result.push({ type: 'single', turns: [t] });
    }
  }

  return result;
}

// ============================================================================
// SVG Icons
// ============================================================================

const ArrowIcon = memo(function ArrowIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`exv2-arrow ${open ? 'exv2-arrow--open' : ''}`}
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
});

const ArchiveIcon = memo(function ArchiveIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="4" width="20" height="5" rx="1" />
      <path d="M4 9v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9" />
      <path d="M10 13h4" />
    </svg>
  );
});

const TrashIcon = memo(function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
});

// ============================================================================
// Context Menu
// ============================================================================

interface ContextMenuProps {
  position: { x: number; y: number };
  isArchiveBlock?: boolean;
  isSingleTurn?: boolean;
  onArchive?: () => void;
  onRestore?: () => void;
  onDelete: () => void;
  onAddToLinkStash?: () => void;
  onClose: () => void;
}

const ContextMenu = memo(function ContextMenu({
  position,
  isArchiveBlock,
  isSingleTurn,
  onArchive,
  onRestore,
  onDelete,
  onAddToLinkStash,
  onClose,
}: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const timeoutId = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside);
    }, 100);
    return () => {
      clearTimeout(timeoutId);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [onClose]);

  // Close on escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return createPortal(
    <div
      ref={menuRef}
      className="exv2-menu"
      style={{ left: position.x, top: position.y }}
    >
      {onAddToLinkStash && (
        <button className="exv2-menu__item" onClick={() => { onAddToLinkStash(); onClose(); }}>
          <span className="exv2-menu__icon">🔗</span>
          Add to Link Stash
        </button>
      )}
      {isArchiveBlock ? (
        <button className="exv2-menu__item" onClick={() => { onRestore?.(); onClose(); }}>
          <span className="exv2-menu__icon">↩</span>
          Restore
        </button>
      ) : !isSingleTurn && onArchive ? (
        <button className="exv2-menu__item" onClick={() => { onArchive(); onClose(); }}>
          <span className="exv2-menu__icon"><ArchiveIcon /></span>
          Archive
        </button>
      ) : null}
      <button className="exv2-menu__item exv2-menu__item--danger" onClick={() => { onDelete(); onClose(); }}>
        <span className="exv2-menu__icon"><TrashIcon /></span>
        Delete
      </button>
    </div>,
    document.body
  );
});

// ============================================================================
// Turn Node
// ============================================================================

interface TurnNodeProps {
  turn: TurnInfo;
  isSelected: boolean;
  onClick?: (turnIdx: number) => void;
  onDelete?: (turnIdx: number) => void;
}

const TurnNode = memo(function TurnNode({ turn, isSelected, onClick, onDelete }: TurnNodeProps) {
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (onDelete) {
      setMenuPosition({ x: e.clientX, y: e.clientY });
    }
  }, [onDelete]);

  const handleClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onClick?.(turn.idx);
  }, [onClick, turn.idx]);

  const icon = getTurnIcon(turn);
  const preview = turn.toolUse ? getToolPreview(turn) : (turn.content || '').slice(0, 100).replace(/\n/g, ' ');
  const tokenStr = formatTokens(turn.tokens || 0);

  return (
    <li className="exv2-node exv2-node--turn" data-turn-idx={turn.idx}>
      <div
        className={`exv2-node__row ${isSelected ? 'exv2-node__row--selected' : ''}`}
        onClick={onClick ? handleClick : undefined}
        onContextMenu={handleContextMenu}
      >
        <span className="exv2-node__spacer" />
        <span className="exv2-node__idx">{turn.idx}</span>
        <span className="exv2-node__icon">{icon}</span>
        <span className="exv2-node__label">{preview || '\u00A0'}</span>
        {tokenStr && <span className="exv2-node__tokens">{tokenStr}</span>}
      </div>
      {menuPosition && onDelete && (
        <ContextMenu
          position={menuPosition}
          isSingleTurn
          onDelete={() => onDelete(turn.idx)}
          onClose={() => setMenuPosition(null)}
        />
      )}
    </li>
  );
});

// ============================================================================
// Parallel Group Node
// ============================================================================

interface ParallelGroupNodeProps {
  turns: TurnInfo[];
  groupId: string;
  selectedTurnIdx: number | null;
  onTurnClick?: (turnIdx: number) => void;
}

const ParallelGroupNode = memo(function ParallelGroupNode({
  turns,
  groupId,
  selectedTurnIdx,
  onTurnClick,
}: ParallelGroupNodeProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const totalTokens = turns.reduce((sum, t) => sum + (t.tokens || 0), 0);
  const tokenStr = formatTokens(totalTokens);
  const firstTurnIdx = turns[0]?.idx;
  const isAnySelected = turns.some(t => t.idx === selectedTurnIdx);

  const handleClick = useCallback(() => {
    if (firstTurnIdx !== undefined && onTurnClick) {
      onTurnClick(firstTurnIdx);
    }
  }, [firstTurnIdx, onTurnClick]);

  const handleToggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setIsExpanded(prev => !prev);
  }, []);

  return (
    <li className="exv2-node exv2-node--parallel" data-turn-idx={firstTurnIdx}>
      <div
        className={`exv2-node__row ${isAnySelected ? 'exv2-node__row--selected' : ''}`}
        onClick={handleClick}
      >
        <span
          className="exv2-node__toggle"
          onClick={handleToggle}
          onMouseDown={e => e.stopPropagation()}
          onMouseUp={e => e.stopPropagation()}
        >
          <ArrowIcon open={isExpanded} />
        </span>
        <span className="exv2-node__icon">⚡</span>
        <span className="exv2-node__label">{turns.length} parallel tool calls</span>
        {tokenStr && <span className="exv2-node__tokens">{tokenStr}</span>}
      </div>
      {isExpanded && (
        <ul className="exv2-children">
          {turns.map(turn => (
            <TurnNode
              key={turn.idx}
              turn={turn}
              isSelected={selectedTurnIdx === turn.idx}
              onClick={onTurnClick}
            />
          ))}
        </ul>
      )}
    </li>
  );
});

// ============================================================================
// Exchange Node
// ============================================================================

interface ExchangeNodeProps {
  exchange: Exchange;
  isExpanded: boolean;
  isArchiving: boolean;
  selectedTurnIdx: number | null;
  rawTurnByIdx: Map<number, SessionDataTurn>;
  toolUseIds: Set<string>;
  onToggle: () => void;
  onArchive?: () => void;
  onRestore?: () => void;
  onDelete?: () => void;
  onDeleteTurn?: (turnIdx: number) => void;
  onAddToLinkStash?: () => void;
  onTurnClick?: (turnIdx: number) => void;
}

const ExchangeNode = memo(function ExchangeNode({
  exchange,
  isExpanded,
  isArchiving,
  selectedTurnIdx,
  rawTurnByIdx,
  toolUseIds,
  onToggle,
  onArchive,
  onRestore,
  onDelete,
  onDeleteTurn,
  onAddToLinkStash,
  onTurnClick,
}: ExchangeNodeProps) {
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

  // Determine exchange type
  const isSystemOnly = !exchange.userTurn && exchange.assistantTurns.length === 0;
  const firstSystemTurn = exchange.systemTurns[0];
  const systemBlockType = firstSystemTurn?.contentBlockType;
  const isArchiveBlock = systemBlockType === 'archive';

  // Get icon
  const getIcon = () => {
    if (exchange.userTurn) return '💬';
    if (isSystemOnly && systemBlockType) {
      switch (systemBlockType) {
        case 'archive': return '📦';
        case 'fork': return '⑂';
        case 'merge':
        case 'merged_to': return '⤴';
        case 'link': return '🔗';
        case 'interruption': return '⚠';
        case 'error': return '✗';
      }
    }
    return '💬';
  };

  // Preview text
  const getPreview = (): string | null => {
    if (exchange.userTurn) {
      return (exchange.userTurn.content || '').slice(0, 80).replace(/\n/g, ' ');
    }
    if (!isSystemOnly) return null;

    // For archive blocks, show "Archived N turns: summary..."
    if (systemBlockType === 'archive' && firstSystemTurn) {
      const raw = rawTurnByIdx.get(firstSystemTurn.idx);
      const block = raw?.contentBlock as { messageCount?: number; structuredSummary?: { workDone?: string } } | undefined;
      const count = block?.messageCount || 0;
      const workDone = block?.structuredSummary?.workDone || '';
      const shortWork = workDone.slice(0, 50).replace(/\n/g, ' ');
      return `Archived ${count} turns${shortWork ? `: ${shortWork}...` : ''}`;
    }

    // For other system blocks, show the block type name
    return systemBlockType || 'System';
  };
  const preview = getPreview();

  // Filter out tool_result turns that have matching tool_use
  const visibleAssistantTurns = useMemo(() => {
    return exchange.assistantTurns.filter(turn => {
      if (turn.role !== 'tool' && turn.contentBlockType !== 'tool_result') return true;
      const toolUseId = turn.toolResult?.toolUseId;
      if (!toolUseId) return true;
      return !toolUseIds.has(toolUseId);
    });
  }, [exchange.assistantTurns, toolUseIds]);

  // Group parallel turns
  const assistantTurnsOrGroups = useMemo(() => {
    return groupParallelTurns(visibleAssistantTurns, rawTurnByIdx);
  }, [visibleAssistantTurns, rawTurnByIdx]);

  // Count children
  const childCount = (exchange.userTurn ? 1 : 0) + assistantTurnsOrGroups.length + exchange.systemTurns.length;
  const hasChildren = childCount > 1;

  // First turn index
  const firstTurnIdx = exchange.systemTurns[0]?.idx
    ?? exchange.userTurn?.idx
    ?? exchange.assistantTurns[0]?.idx;

  // Is any turn selected?
  const isAnySelected = selectedTurnIdx !== null && exchange.turnIndices.includes(selectedTurnIdx);

  const handleClick = useCallback(() => {
    if (firstTurnIdx !== undefined && onTurnClick) {
      onTurnClick(firstTurnIdx);
    }
  }, [firstTurnIdx, onTurnClick]);

  const handleToggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle();
  }, [onToggle]);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setMenuPosition({ x: e.clientX, y: e.clientY });
  }, []);

  const tokenStr = formatTokens(exchange.totalTokens);
  const tokenWeightClass = getTokenWeightClass(exchange.totalTokens);
  const timeStr = formatTimestamp(exchange.timestamp);

  return (
    <li className={`exv2-node exv2-node--exchange ${tokenWeightClass}`} data-turn-idx={firstTurnIdx}>
      <div
        className={`exv2-node__row ${isAnySelected ? 'exv2-node__row--selected' : ''}`}
        onClick={handleClick}
        onContextMenu={handleContextMenu}
      >
        <span
          className="exv2-node__toggle"
          onClick={handleToggle}
          onMouseDown={e => e.stopPropagation()}
          onMouseUp={e => e.stopPropagation()}
          onTouchStart={e => e.stopPropagation()}
          onTouchEnd={e => e.stopPropagation()}
        >
          {hasChildren ? <ArrowIcon open={isExpanded} /> : <span className="exv2-node__spacer" />}
        </span>
        <span className="exv2-node__idx">{firstTurnIdx}</span>
        <span className="exv2-node__icon">
          {isArchiving ? <span className="exv2-spinner">⏳</span> : getIcon()}
        </span>
        <span className="exv2-node__label">
          {preview}
          {preview && preview.length >= 80 ? '...' : ''}
        </span>
        {tokenStr && <span className="exv2-node__tokens">{tokenStr}</span>}
        <span className="exv2-node__meta">({childCount})</span>
        {timeStr && <span className="exv2-node__time">{timeStr}</span>}
      </div>

      {isExpanded && hasChildren && (
        <ul className="exv2-children">
          {exchange.systemTurns.map(turn => (
            <TurnNode
              key={turn.idx}
              turn={turn}
              isSelected={selectedTurnIdx === turn.idx}
              onClick={onTurnClick}
              onDelete={onDeleteTurn}
            />
          ))}
          {exchange.userTurn && (
            <TurnNode
              turn={exchange.userTurn}
              isSelected={selectedTurnIdx === exchange.userTurn.idx}
              onClick={onTurnClick}
              onDelete={onDeleteTurn}
            />
          )}
          {assistantTurnsOrGroups.map((item, i) => {
            if (item.type === 'parallel' && item.groupId) {
              return (
                <ParallelGroupNode
                  key={`parallel-${item.groupId}`}
                  turns={item.turns}
                  groupId={item.groupId}
                  selectedTurnIdx={selectedTurnIdx}
                  onTurnClick={onTurnClick}
                />
              );
            }
            const turn = item.turns[0];
            if (!turn) return null;
            return (
              <TurnNode
                key={turn.idx}
                turn={turn}
                isSelected={selectedTurnIdx === turn.idx}
                onClick={onTurnClick}
                onDelete={onDeleteTurn}
              />
            );
          })}
        </ul>
      )}

      {menuPosition && (
        <ContextMenu
          position={menuPosition}
          isArchiveBlock={isArchiveBlock}
          onArchive={onArchive}
          onRestore={onRestore}
          onDelete={() => onDelete?.()}
          onAddToLinkStash={onAddToLinkStash}
          onClose={() => setMenuPosition(null)}
        />
      )}
    </li>
  );
});

// ============================================================================
// Main Component
// ============================================================================

export const ExchangesV2 = memo(function ExchangesV2({
  sessionId,
  turns,
  rawTurns,
  client,
  totalTokens,
  onSelectTurn,
  onExchangeAction,
  onDeleteTurn,
  onAddToLinkStash,
  onLoadFullHistory,
  isLoading = false,
  archivingTurnIds,
  isLoadingHistory = false,
}: ExchangesV2Props) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [selectedTurnIdx, setSelectedTurnIdx] = useState<number | null>(null);
  const lastExchangeIdRef = useRef<string | null>(null);

  // Build raw turn lookup
  const rawTurnByIdx = useMemo(() => {
    const map = new Map<number, SessionDataTurn>();
    for (const rawTurn of rawTurns || []) {
      map.set(rawTurn.order, rawTurn);
    }
    return map;
  }, [rawTurns]);

  // Group turns into exchanges
  const exchanges = useMemo(() => {
    const result = groupTurnsIntoExchanges(turns, rawTurnByIdx);
    // Debug: check for duplicates
    const idxSet = new Set(turns.map(t => t.idx));
    if (idxSet.size !== turns.length) {
      log('WARNING: Duplicate turn indices detected!', {
        turnCount: turns.length,
        uniqueCount: idxSet.size,
        duplicateIdxs: turns.map(t => t.idx).filter((idx, i, arr) => arr.indexOf(idx) !== i),
      });
    }
    return result;
  }, [turns, rawTurnByIdx]);

  // Build tool_use ID set for filtering tool_result
  const toolUseIds = useMemo(() => {
    const ids = new Set<string>();
    for (const turn of turns) {
      if (turn.toolUse?.toolUseId) {
        ids.add(turn.toolUse.toolUseId);
      }
    }
    return ids;
  }, [turns]);

  // Build tool result map for TurnCard
  const toolResultMap = useMemo(() => {
    const map = new Map<string, SessionDataTurn>();
    for (const turn of rawTurns || []) {
      if (turn.contentBlock?.type === 'tool_result') {
        const block = turn.contentBlock as { toolUseId?: string };
        if (block.toolUseId) {
          map.set(block.toolUseId, turn);
        }
      }
    }
    return map;
  }, [rawTurns]);

  // Detect incomplete history
  const hasIncompleteHistory = useMemo(() => {
    if (turns.length === 0) return false;
    const lowestOrder = Math.min(...turns.map(t => t.idx));
    return lowestOrder > 0;
  }, [turns]);

  const missingTurnsCount = useMemo(() => {
    if (!hasIncompleteHistory) return 0;
    return Math.min(...turns.map(t => t.idx));
  }, [hasIncompleteHistory, turns]);

  // Calculate total tokens
  const calculatedTotalTokens = useMemo(() => {
    if (totalTokens !== undefined) return totalTokens;
    return turns.reduce((sum, t) => sum + (t.tokens || 0), 0);
  }, [turns, totalTokens]);

  // Auto-expand new exchanges
  useEffect(() => {
    if (exchanges.length === 0) return;
    const lastExchange = exchanges[exchanges.length - 1];
    if (!lastExchange) return;

    if (lastExchange.id !== lastExchangeIdRef.current) {
      setExpandedIds(prev => new Set(prev).add(lastExchange.id));
      lastExchangeIdRef.current = lastExchange.id;
    }
  }, [exchanges]);

  // Toggle expansion
  const toggleExchange = useCallback((exchangeId: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(exchangeId)) {
        next.delete(exchangeId);
      } else {
        next.add(exchangeId);
      }
      return next;
    });
  }, []);

  // Handle turn selection
  const handleTurnSelect = useCallback((turnIdx: number) => {
    setSelectedTurnIdx(prev => prev === turnIdx ? null : turnIdx);
    onSelectTurn?.(turnIdx);

    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-turn-idx="${turnIdx}"]`);
      el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  }, [onSelectTurn]);

  // Get selected raw turn for preview
  const selectedRawTurn = selectedTurnIdx !== null ? rawTurnByIdx.get(selectedTurnIdx) : undefined;

  // Client context for TurnCard
  const clientContextValue = useMemo(() => ({ client: client || null }), [client]);

  // Empty states
  if (!sessionId) {
    return (
      <div className="exv2 exv2--empty">
        <div className="exv2__empty-state">
          <h2>No Session Selected</h2>
          <p>Select a session to view its exchanges.</p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="exv2 exv2--empty">
        <div className="exv2__empty-state">Loading exchanges...</div>
      </div>
    );
  }

  return (
    <div className={`exv2 ${selectedRawTurn ? 'exv2--with-preview' : ''}`}>
      {/* Header */}
      <div className="exv2__header">
        <div className="exv2__stats">
          <span className="exv2__stat">{exchanges.length} exchange{exchanges.length !== 1 ? 's' : ''}</span>
          <span className="exv2__stat exv2__stat--tokens">{formatTokens(calculatedTotalTokens) || '0kt'}</span>
        </div>
      </div>

      {/* Incomplete history banner */}
      {hasIncompleteHistory && (
        <div className="exv2__banner">
          {isLoadingHistory ? (
            <span className="exv2__banner-loading">Loading older exchanges...</span>
          ) : (
            <>
              <span className="exv2__banner-text">
                {missingTurnsCount > 0 ? `${missingTurnsCount} older turns not loaded` : 'Older turns not loaded'}
              </span>
              {onLoadFullHistory && (
                <button className="exv2__banner-btn" onClick={onLoadFullHistory}>
                  Load All
                </button>
              )}
            </>
          )}
        </div>
      )}

      {/* Tree */}
      <div className="exv2__tree-section">
        <ul className="exv2__tree">
          {exchanges.length > 0 ? (
            exchanges.map(exchange => {
              const isArchiving = archivingTurnIds
                ? exchange.turnIds.some(id => archivingTurnIds.has(id))
                : false;

              const excerpt = (
                exchange.userTurn?.content ||
                exchange.assistantTurns[0]?.content ||
                exchange.systemTurns[0]?.content ||
                ''
              ).slice(0, 100).replace(/\n/g, ' ');

              return (
                <ExchangeNode
                  key={exchange.id}
                  exchange={exchange}
                  isExpanded={expandedIds.has(exchange.id)}
                  isArchiving={isArchiving}
                  selectedTurnIdx={selectedTurnIdx}
                  rawTurnByIdx={rawTurnByIdx}
                  toolUseIds={toolUseIds}
                  onToggle={() => toggleExchange(exchange.id)}
                  onArchive={onExchangeAction
                    ? () => onExchangeAction(exchange.turnIndices, exchange.turnIds, 'archive')
                    : undefined}
                  onRestore={onExchangeAction
                    ? () => onExchangeAction(exchange.turnIndices, exchange.turnIds, 'restore')
                    : undefined}
                  onDelete={onExchangeAction
                    ? () => onExchangeAction(exchange.turnIndices, exchange.turnIds, 'delete')
                    : undefined}
                  onDeleteTurn={onDeleteTurn}
                  onAddToLinkStash={onAddToLinkStash
                    ? () => onAddToLinkStash(exchange.turnIndices, excerpt)
                    : undefined}
                  onTurnClick={handleTurnSelect}
                />
              );
            })
          ) : (
            <li className="exv2-node exv2-node--empty">
              <div className="exv2-node__row">
                <span className="exv2-node__label">No messages yet</span>
              </div>
            </li>
          )}
        </ul>
      </div>

      {/* Preview pane */}
      {selectedRawTurn && (
        <div className="exv2__preview">
          <div className="exv2__preview-header">
            <span className="exv2__preview-title">Turn {selectedTurnIdx}</span>
            <button
              className="exv2__preview-close"
              onClick={() => setSelectedTurnIdx(null)}
              title="Close preview"
            >
              ✕
            </button>
          </div>
          <div className="exv2__preview-content">
            <ClientContext.Provider value={clientContextValue}>
              <TurnCard turn={selectedRawTurn} toolResultMap={toolResultMap} sessionId={sessionId || undefined} />
            </ClientContext.Provider>
          </div>
        </div>
      )}
    </div>
  );
});

export default ExchangesV2;
