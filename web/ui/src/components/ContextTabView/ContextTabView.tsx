/**
 * ContextTabView - Tree view of context for the current session
 *
 * This component shows the exchanges (grouped user + assistant turns) for the
 * currently selected session. It provides right-click context menus to:
 * - Set context mode (COPY/COMPRESS/DROP) for exchanges
 * - Archive or delete exchanges
 * - Click to scroll to that turn in the main chat view
 *
 * This is the foundation for more advanced context transformation features.
 */

import React, { useState, useCallback, useMemo, memo, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { TurnInfo, BalloonsClient } from '../../../../generated/balloons-client';
import type { SessionDataTurn } from '../../hooks/useSessionData';
import { TurnCard } from '../StreamingTurnsView/cards';
import { ClientContext } from '../StreamingTurnsView/cards/ClientContext';
import { SystemPromptView } from './SystemPromptView';
import { createLogger } from '../../utils/debugLog';
import './ContextTabView.css';

// createPortal is still used for ExchangeContextMenu

// Create scoped logger for this module
const debugLog = createLogger('ContextTabView');

// Context modes for turns
export type ContextMode = 'COPY' | 'COMPRESS' | 'DROP';

// Exchange represents a user prompt + assistant response pair
export interface Exchange {
  id: string;
  userTurn: TurnInfo | null;
  assistantTurns: TurnInfo[];  // Can have multiple (e.g., tool use, then text)
  systemTurns: TurnInfo[];     // System messages in this exchange
}

// Group turns into exchanges
// Uses exchangeId when available to group related turns
// tool_result turns are kept in the data but rendered merged with their tool_use in TurnCard
function groupTurnsIntoExchanges(turns: TurnInfo[]): Exchange[] {
  const exchanges: Exchange[] = [];
  const exchangeMap = new Map<string, Exchange>();
  let exchangeIndex = 0;
  let currentExchangeId: string | null = null;

  // Sort by idx to ensure proper ordering
  const sortedTurns = [...turns].sort((a, b) => a.idx - b.idx);

  for (const turn of sortedTurns) {
    // Check if this turn has its own exchangeId
    const turnExchangeId = turn.exchangeId;

    if (turn.role === 'user') {
      // User turn starts a new exchange
      const exchangeId = turnExchangeId || `exchange-${exchangeIndex++}`;
      const exchange: Exchange = {
        id: exchangeId,
        userTurn: turn,
        assistantTurns: [],
        systemTurns: [],
      };
      exchangeMap.set(exchangeId, exchange);
      exchanges.push(exchange);
      currentExchangeId = exchangeId;
    } else if (turn.role === 'assistant' || turn.role === 'tool') {
      // Assistant and tool (tool_result) turns belong to current exchange
      // tool_result turns will be rendered merged with their tool_use in TurnCard
      const exchangeId: string = turnExchangeId || currentExchangeId || `exchange-${exchangeIndex++}`;
      let exchange = exchangeMap.get(exchangeId);
      if (!exchange) {
        exchange = {
          id: exchangeId,
          userTurn: null,
          assistantTurns: [],
          systemTurns: [],
        };
        exchangeMap.set(exchangeId, exchange);
        exchanges.push(exchange);
        currentExchangeId = exchangeId;
      }
      exchange.assistantTurns.push(turn);
    } else {
      // System turn - check if it has its own exchangeId (e.g., archive)
      if (turnExchangeId && turnExchangeId !== currentExchangeId) {
        // System turn with unique exchangeId - create its own exchange
        const exchange: Exchange = {
          id: turnExchangeId,
          userTurn: null,
          assistantTurns: [],
          systemTurns: [turn],
        };
        exchangeMap.set(turnExchangeId, exchange);
        exchanges.push(exchange);
      } else if (currentExchangeId) {
        // Add to current exchange
        const exchange = exchangeMap.get(currentExchangeId);
        if (exchange) {
          exchange.systemTurns.push(turn);
        }
      } else {
        // System turn at start - create exchange for it
        const exchangeId = turnExchangeId || `exchange-${exchangeIndex++}`;
        const exchange: Exchange = {
          id: exchangeId,
          userTurn: null,
          assistantTurns: [],
          systemTurns: [turn],
        };
        exchangeMap.set(exchangeId, exchange);
        exchanges.push(exchange);
      }
    }
  }

  return exchanges;
}

// Format token count as kt
function formatKt(tokens: number): string {
  if (tokens <= 0) return '';
  const kt = Math.ceil(tokens / 100) / 10;
  if (kt < 1) return `.${Math.floor(kt * 10)}kt`;
  return `${kt.toFixed(1)}kt`;
}

// Arrow icon component
function Arrow({ open }: { open: boolean }) {
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
      className={`ctx-tree-arrow ${open ? 'ctx-tree-arrow--open' : ''}`}
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

// Archive icon
function ArchiveIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="2" y="4" width="20" height="5" rx="1" />
      <path d="M4 9v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9" />
      <path d="M10 13h4" />
    </svg>
  );
}

// Trash icon
function TrashIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 6h18" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

// Turn node component (used inside exchanges)
function TurnNode({
  turn,
  indent = false,
  onClick,
  isSelected = false,
  onDelete,
}: {
  turn: TurnInfo;
  indent?: boolean;
  onClick?: (turnIdx: number) => void;
  isSelected?: boolean;
  onDelete?: (turnIdx: number) => void;
}) {
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (onDelete) {
      debugLog('Turn context menu triggered', { turnIdx: turn.idx });
      setMenuPosition({ x: e.clientX, y: e.clientY });
    }
  }, [turn.idx, onDelete]);
  // Get icon based on role and content block type
  const getIcon = () => {
    if (turn.role === 'user') return '👤';
    if (turn.role === 'assistant') {
      // Check if it's a tool_use turn
      if (turn.contentBlockType === 'tool_use' || turn.toolUse) return '🔧';
      return '🤖';
    }
    // System/tool role - check content block type
    const blockType = turn.contentBlockType;
    switch (blockType) {
      case 'tool_result': return '📋';
      case 'archive': return '📦';
      case 'fork': return '⑂';
      case 'merge': return '⤴';
      case 'merged_to': return '⤴';
      case 'link': return '🔗';
      case 'interruption': return '⚠';
      case 'error': return '✗';
      default: return '⚙';
    }
  };
  const icon = getIcon();

  // Format preview based on turn type
  const getPreview = (): string => {
    // For tool_use turns, format like the card header: "Read: file.txt ..."
    if (turn.toolUse) {
      const toolName = turn.toolUse.name || 'Tool';
      try {
        const input = JSON.parse(turn.toolUse.inputJson || '{}');
        // Format based on tool type
        switch (toolName) {
          case 'Read':
            const filePath = input.file_path || '';
            const fileName = filePath.split('/').pop() || filePath;
            const parts = [fileName];
            if (input.offset) parts.push(`@${input.offset}`);
            if (input.limit) parts.push(`+${input.limit}`);
            return `Read: ${parts.join(' ')}`;
          case 'Edit': {
            const editPath = input.file_path || '';
            const editName = editPath.split('/').pop() || editPath;
            const oldStr = input.old_string || '';
            const newStr = input.new_string || '';
            // Count lines (more useful than chars for edits)
            const oldLines = oldStr ? oldStr.split('\n').length : 0;
            const newLines = newStr ? newStr.split('\n').length : 0;
            if (oldLines === 0 && newLines === 0) {
              return `Edit: ${editName}`;
            }
            return `Edit: ${editName} (${oldLines}→${newLines} lines)`;
          }
          case 'Write':
            const writePath = input.file_path || '';
            const writeName = writePath.split('/').pop() || writePath;
            const contentLen = (input.content || '').length;
            return `Write: ${writeName} (${contentLen} chars)`;
          case 'Bash':
            const cmd = input.command || '';
            const cmdPreview = cmd.length > 40 ? cmd.slice(0, 40) + '...' : cmd;
            return `Bash: ${cmdPreview}`;
          case 'Grep':
            const pattern = input.pattern || '';
            const grepPath = input.path ? ` in ${input.path.split('/').pop()}` : '';
            return `Grep: "${pattern}"${grepPath}`;
          case 'Glob':
            const globPattern = input.pattern || '';
            const globPath = input.path ? ` in ${input.path.split('/').pop()}` : '';
            return `Glob: ${globPattern}${globPath}`;
          case 'WebFetch':
            const url = input.url || '';
            const domain = url.replace(/^https?:\/\//, '').split('/')[0];
            return `WebFetch: ${domain}`;
          case 'WebSearch':
            const query = input.query || '';
            return `WebSearch: "${query}"`;
          default:
            // Generic format: show first few input keys/values
            const entries = Object.entries(input).slice(0, 2);
            if (entries.length === 0) return toolName;
            const summary = entries.map(([k, v]) => {
              const val = typeof v === 'string' ? v.slice(0, 20) : String(v);
              return `${k}=${val}`;
            }).join(', ');
            return `${toolName}: ${summary}`;
        }
      } catch {
        return toolName;
      }
    }

    // Default: use content preview
    return (turn.content || '').slice(0, 60).replace(/\n/g, ' ');
  };

  const preview = getPreview();
  const tokenStr = formatKt(turn.tokens);

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onClick?.(turn.idx);
  };

  return (
    <li
      className={`ctx-tree-node ctx-tree-node--turn ${indent ? 'ctx-tree-node--indented' : ''}`}
      data-ctx-turn-idx={turn.idx}
    >
      <div
        className={`ctx-tree-node__content ${onClick ? 'ctx-tree-node__content--clickable' : ''} ${isSelected ? 'ctx-tree-node__content--selected' : ''}`}
        onClick={onClick ? handleClick : undefined}
        onContextMenu={handleContextMenu}
      >
        <span key="spacer" className="ctx-tree-node__spacer" />
        <span key="turnNum" className="ctx-tree-node__turn-num">{turn.idx}</span>
        <span key="icon" className="ctx-tree-node__icon">{icon}</span>
        <span key="label" className="ctx-tree-node__label ctx-tree-node__label--muted">
          {preview || '\u00A0'}
        </span>
        {tokenStr && (
          <span key="meta" className="ctx-tree-node__meta ctx-tree-node__meta--green">
            {tokenStr}
          </span>
        )}
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
}

// Context menu for exchanges and turns
interface ContextMenuProps {
  position: { x: number; y: number };
  isArchiveBlock?: boolean;  // True if this is an archive block (show Restore instead of Archive)
  isSingleTurn?: boolean;    // True if this is for a single turn (no Archive option)
  onArchive?: () => void;
  onRestore?: () => void;  // Called for rehydrating archive blocks
  onDelete: () => void;
  onAddToLinkStash?: () => void;  // Add exchange/turn to link stash
  onClose: () => void;
}

function ContextMenu({
  position,
  isArchiveBlock,
  isSingleTurn,
  onArchive,
  onRestore,
  onDelete,
  onAddToLinkStash,
  onClose,
}: ContextMenuProps) {
  const menuRef = React.useRef<HTMLDivElement>(null);

  const handleArchive = useCallback(() => {
    debugLog('Archive action triggered');
    onArchive?.();
  }, [onArchive]);

  const handleRestore = useCallback(() => {
    debugLog('Restore (rehydrate) action triggered');
    onRestore?.();
  }, [onRestore]);

  const handleDelete = useCallback(() => {
    debugLog('Delete action triggered');
    onDelete();
  }, [onDelete]);

  const handleAddToLinkStash = useCallback(() => {
    debugLog('Add to link stash triggered');
    onAddToLinkStash?.();
  }, [onAddToLinkStash]);

  // Debug log when menu mounts
  useEffect(() => {
    debugLog('ContextMenu mounted', { position, isArchiveBlock, isSingleTurn });
    return () => {
      debugLog('ContextMenu unmounted');
    };
  }, [position, isArchiveBlock, isSingleTurn]);

  // Close on click outside (delay to avoid closing immediately on the opening click)
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        debugLog('ContextMenu click outside, closing');
        onClose();
      }
    };
    // Small delay to avoid the mousedown that opened the menu from closing it
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
      if (e.key === 'Escape') {
        debugLog('ContextMenu escape pressed, closing');
        onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Use portal to render at document root to avoid overflow issues
  return createPortal(
    <div
      ref={menuRef}
      className="ctx-exchange-menu"
      style={{
        position: 'fixed',
        left: position.x,
        top: position.y,
        zIndex: 9999,
      }}
    >
      <div className="ctx-exchange-menu__section">
        {onAddToLinkStash && (
          <button
            className="ctx-exchange-menu__item"
            onClick={() => { handleAddToLinkStash(); onClose(); }}
          >
            <span className="ctx-exchange-menu__icon">🔗</span>
            Add to Link Stash
          </button>
        )}
        {isArchiveBlock ? (
          <button
            className="ctx-exchange-menu__item"
            onClick={() => { handleRestore(); onClose(); }}
          >
            <span className="ctx-exchange-menu__icon">↩</span>
            Restore
          </button>
        ) : !isSingleTurn && onArchive ? (
          <button
            className="ctx-exchange-menu__item"
            onClick={() => { handleArchive(); onClose(); }}
          >
            <span className="ctx-exchange-menu__icon"><ArchiveIcon /></span>
            Archive
          </button>
        ) : null}
        <button
          className="ctx-exchange-menu__item ctx-exchange-menu__item--danger"
          onClick={() => { handleDelete(); onClose(); }}
        >
          <span className="ctx-exchange-menu__icon"><TrashIcon /></span>
          Delete
        </button>
      </div>
    </div>,
    document.body
  );
}

// Long press hook for touch devices
function useLongPress(
  onLongPress: (position: { x: number; y: number }) => void,
  onClick?: () => void,
  { delay = 500 }: { delay?: number } = {}
) {
  const timeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPressTriggeredRef = React.useRef(false);
  const isActiveRef = React.useRef(false);
  const positionRef = React.useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  const start = useCallback((e: React.MouseEvent | React.TouchEvent) => {
    if ('button' in e && e.button !== 0) return;

    isActiveRef.current = true;
    longPressTriggeredRef.current = false;

    if ('touches' in e) {
      const touch = e.touches[0];
      if (touch) {
        positionRef.current = { x: touch.clientX, y: touch.clientY };
      }
    } else {
      positionRef.current = { x: e.clientX, y: e.clientY };
    }

    timeoutRef.current = setTimeout(() => {
      longPressTriggeredRef.current = true;
      onLongPress(positionRef.current);
    }, delay);
  }, [onLongPress, delay]);

  const clear = useCallback((shouldTriggerClick = true) => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (shouldTriggerClick && isActiveRef.current && !longPressTriggeredRef.current && onClick) {
      onClick();
    }
    isActiveRef.current = false;
  }, [onClick]);

  return {
    onMouseDown: start,
    onMouseUp: () => clear(true),
    onMouseLeave: () => clear(false),
    onTouchStart: start,
    onTouchEnd: () => clear(true),
  };
}

// Parallel group node - shows "N parallel tool calls" with expandable children
function ParallelGroupNode({
  turns,
  groupId,
  onTurnClick,
  selectedTurnIdx,
}: {
  turns: TurnInfo[];
  groupId: string;
  onTurnClick?: (turnIdx: number) => void;
  selectedTurnIdx?: number | null;
}) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Debug: log when parallel group renders
  useEffect(() => {
    debugLog('ParallelGroupNode rendered', {
      groupId: groupId.substring(0, 8),
      turnCount: turns.length,
      turnIdxs: turns.map(t => t.idx),
    });
  }, [groupId, turns]);

  const totalTokens = turns.reduce((sum, t) => sum + (t.tokens || 0), 0);
  const tokenStr = formatKt(totalTokens);
  const firstTurnIdx = turns[0]?.idx;

  // Check if any turn in this group is selected
  const isAnySelected = turns.some(t => t.idx === selectedTurnIdx);

  const handleClick = useCallback(() => {
    // Click on the group header selects the first turn
    if (firstTurnIdx !== undefined && onTurnClick) {
      onTurnClick(firstTurnIdx);
    }
  }, [firstTurnIdx, onTurnClick]);

  return (
    <li className="ctx-tree-node ctx-tree-node--parallel-group" data-ctx-turn-idx={firstTurnIdx}>
      <div
        className={`ctx-tree-node__content ctx-tree-node__content--clickable ${isAnySelected ? 'ctx-tree-node__content--selected' : ''}`}
        onClick={handleClick}
      >
        <span className="ctx-tree-node__toggle" onClick={(e) => { e.stopPropagation(); setIsExpanded(prev => !prev); }}>
          <Arrow open={isExpanded} />
        </span>
        <span className="ctx-tree-node__icon">⚡</span>
        <span className="ctx-tree-node__label ctx-tree-node__label--muted">
          {turns.length} parallel tool calls
        </span>
        {tokenStr && (
          <span className="ctx-tree-node__meta ctx-tree-node__meta--green">
            {tokenStr}
          </span>
        )}
      </div>
      {isExpanded && (
        <ul className="ctx-tree-children">
          {turns.map(turn => (
            <TurnNode
              key={turn.idx}
              turn={turn}
              indent
              onClick={onTurnClick}
              isSelected={selectedTurnIdx === turn.idx}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

// Exchange action type for callbacks
export type ExchangeAction = 'archive' | 'delete' | 'restore';

// Represents either a single turn or a group of parallel turns
type TurnOrGroup =
  | { type: 'single'; turn: TurnInfo }
  | { type: 'parallel'; turns: TurnInfo[]; groupId: string };

// Group consecutive tool_use turns with the same parallelGroupId
// Note: Only group tool_use turns - tool_result turns are filtered out earlier
function groupParallelTurns(turns: TurnInfo[], rawTurnByIdx: Map<number, SessionDataTurn>): TurnOrGroup[] {
  const result: TurnOrGroup[] = [];
  let currentGroup: TurnInfo[] = [];
  let currentGroupId: string | undefined;

  // Debug: log incoming turns info
  const toolUseTurns = turns.filter(t => t.contentBlockType === 'tool_use');
  if (toolUseTurns.length > 0) {
    debugLog('groupParallelTurns: checking tool_use turns', {
      toolUseCount: toolUseTurns.length,
      toolUseTurnIdxs: toolUseTurns.map(t => t.idx),
      rawTurnByIdxSize: rawTurnByIdx.size,
      parallelGroupIds: toolUseTurns.map(t => {
        const raw = rawTurnByIdx.get(t.idx);
        return { idx: t.idx, parallelGroupId: raw?.parallelGroupId };
      }),
    });
  }

  for (const turn of turns) {
    const rawTurn = rawTurnByIdx.get(turn.idx);
    const groupId = rawTurn?.parallelGroupId;

    // Only group tool_use turns - don't include tool_result or other types in parallel groups
    const isToolUse = turn.contentBlockType === 'tool_use' || rawTurn?.contentBlock?.type === 'tool_use';

    if (groupId && groupId === currentGroupId && isToolUse) {
      // Continue current parallel group (only for tool_use turns)
      currentGroup.push(turn);
    } else {
      // Flush previous group if any
      if (currentGroup.length > 0) {
        if (currentGroup.length > 1 && currentGroupId) {
          result.push({ type: 'parallel', turns: currentGroup, groupId: currentGroupId });
        } else {
          // Single turn, not a real group
          for (const t of currentGroup) {
            result.push({ type: 'single', turn: t });
          }
        }
      }
      // Start new group or single
      // Only start a parallel group for tool_use turns with a groupId
      if (groupId && isToolUse) {
        currentGroup = [turn];
        currentGroupId = groupId;
      } else {
        result.push({ type: 'single', turn });
        currentGroup = [];
        currentGroupId = undefined;
      }
    }
  }

  // Flush final group
  if (currentGroup.length > 0) {
    if (currentGroup.length > 1 && currentGroupId) {
      result.push({ type: 'parallel', turns: currentGroup, groupId: currentGroupId });
    } else {
      for (const t of currentGroup) {
        result.push({ type: 'single', turn: t });
      }
    }
  }

  return result;
}

// Exchange node props
interface ExchangeNodeProps {
  exchange: Exchange;
  isExpanded: boolean;
  isArchiving?: boolean;
  onToggle: () => void;
  onArchive?: () => void;
  onRestore?: () => void;  // For rehydrating archive blocks
  onDelete?: () => void;
  onDeleteTurn?: (turnIdx: number) => void;  // For deleting individual turns
  onAddToLinkStash?: () => void;  // Add exchange to link stash
  onTurnClick?: (turnIdx: number) => void;
  /** Currently selected turn index for preview highlight */
  selectedTurnIdx?: number | null;
  /** Map from turn idx to raw SessionDataTurn for parallel grouping */
  rawTurnByIdx?: Map<number, SessionDataTurn>;
}

// Exchange node component - groups user + assistant turns
const ExchangeNode = memo(function ExchangeNode({
  exchange,
  isExpanded,
  isArchiving,
  onToggle,
  onArchive,
  onRestore,
  onDelete,
  onDeleteTurn,
  onAddToLinkStash,
  onTurnClick,
  selectedTurnIdx,
  rawTurnByIdx,
}: ExchangeNodeProps) {
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

  // Debug log when menuPosition changes
  useEffect(() => {
    if (menuPosition) {
      debugLog('menuPosition set', { menuPosition, exchangeId: exchange.id });
    }
  }, [menuPosition, exchange.id]);

  // Check if this is a system-only exchange (like archive, fork, merge)
  const isSystemOnly = !exchange.userTurn && exchange.assistantTurns.length === 0 && exchange.systemTurns.length > 0;
  const firstSystemTurn = exchange.systemTurns[0];
  const systemBlockType = firstSystemTurn?.contentBlockType;
  const isArchiveBlock = systemBlockType === 'archive';

  // Get exchange icon based on content
  const getExchangeIcon = () => {
    if (exchange.userTurn) return '💬';
    if (isSystemOnly && systemBlockType) {
      switch (systemBlockType) {
        case 'archive': return '📦';
        case 'fork': return '⑂';
        case 'merge': return '⤴';
        case 'merged_to': return '⤴';
        case 'link': return '🔗';
        case 'interruption': return '⚠';
        case 'error': return '✗';
      }
    }
    return '💬';
  };
  const exchangeIcon = getExchangeIcon();

  // Get preview text
  const userPreview = exchange.userTurn
    ? (exchange.userTurn.content || '').slice(0, 50).replace(/\n/g, ' ')
    : isSystemOnly
      ? (firstSystemTurn?.content || '').slice(0, 50).replace(/\n/g, ' ')
      : null;

  const totalTokens = (exchange.userTurn?.tokens || 0) +
    exchange.assistantTurns.reduce((sum, t) => sum + (t.tokens || 0), 0) +
    exchange.systemTurns.reduce((sum, t) => sum + (t.tokens || 0), 0);

  const tokenStr = formatKt(totalTokens);

  // Build set of tool_use IDs to filter out tool_result turns from display
  // (they're rendered merged with their tool_use in TurnCard)
  const toolUseIds = useMemo(() => {
    const ids = new Set<string>();
    for (const turn of exchange.assistantTurns) {
      if (turn.toolUse?.toolUseId) {
        ids.add(turn.toolUse.toolUseId);
      }
    }
    return ids;
  }, [exchange.assistantTurns]);

  // Filter out tool_result turns that have a matching tool_use for display
  const visibleAssistantTurns = useMemo(() => {
    return exchange.assistantTurns.filter(turn => {
      // Keep if not a tool result
      if (turn.role !== 'tool' && turn.contentBlockType !== 'tool_result') {
        return true;
      }
      // Keep if no matching tool_use (standalone result)
      const toolUseId = turn.toolResult?.toolUseId;
      if (!toolUseId) return true;
      return !toolUseIds.has(toolUseId);
    });
  }, [exchange.assistantTurns, toolUseIds]);

  // Group visible assistant turns into parallel groups
  const assistantTurnsOrGroups = useMemo(() => {
    if (!rawTurnByIdx) {
      // No raw turn data, show all as singles
      return visibleAssistantTurns.map(t => ({ type: 'single' as const, turn: t }));
    }
    return groupParallelTurns(visibleAssistantTurns, rawTurnByIdx);
  }, [visibleAssistantTurns, rawTurnByIdx]);

  // Count visible items (each group counts as 1)
  const turnCount = (exchange.userTurn ? 1 : 0) + assistantTurnsOrGroups.length + exchange.systemTurns.length;
  const hasChildren = turnCount > 1;

  const handleLongPress = useCallback((position: { x: number; y: number }) => {
    debugLog('Long press triggered', { x: position.x, y: position.y, exchangeId: exchange.id });
    setMenuPosition(position);
  }, [exchange.id]);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    debugLog('Context menu triggered', { x: e.clientX, y: e.clientY, exchangeId: exchange.id });
    setMenuPosition({ x: e.clientX, y: e.clientY });
  }, [exchange.id]);

  // Get the first turn index for jumping to the exchange
  const firstTurnIdx = exchange.systemTurns[0]?.idx
    ?? exchange.userTurn?.idx
    ?? exchange.assistantTurns[0]?.idx;

  const handleClick = useCallback(() => {
    // Select the first turn for preview
    if (firstTurnIdx !== undefined && onTurnClick) {
      onTurnClick(firstTurnIdx);
    }
  }, [firstTurnIdx, onTurnClick]);

  // Check if any turn in this exchange is selected
  const isAnyTurnSelected = selectedTurnIdx !== null && (
    exchange.systemTurns.some(t => t.idx === selectedTurnIdx) ||
    exchange.userTurn?.idx === selectedTurnIdx ||
    exchange.assistantTurns.some(t => t.idx === selectedTurnIdx)
  );

  const longPressHandlers = useLongPress(handleLongPress, handleClick, { delay: 500 });

  return (
    <li
      className="ctx-tree-node ctx-tree-node--exchange"
      data-ctx-turn-idx={firstTurnIdx}
    >
      <div
        className={`ctx-tree-node__content ${isAnyTurnSelected ? 'ctx-tree-node__content--selected' : ''}`}
        {...longPressHandlers}
        onContextMenu={handleContextMenu}
      >
        <span className="ctx-tree-node__toggle" onClick={(e) => { e.stopPropagation(); onToggle(); }}>
          {hasChildren ? <Arrow open={isExpanded} /> : <span className="ctx-tree-node__spacer" />}
        </span>
        <span className="ctx-tree-node__turn-num">{firstTurnIdx}</span>
        <span className="ctx-tree-node__icon">
          {isArchiving ? <span className="ctx-tree-node__spinner">⏳</span> : exchangeIcon}
        </span>
        <span className="ctx-tree-node__label ctx-tree-node__label--muted">
          {userPreview || (isSystemOnly ? (systemBlockType || 'System') : 'System')}
          {userPreview && userPreview.length >= 50 ? '...' : ''}
        </span>
        <span className="ctx-tree-node__meta">
          {turnCount > 1 && `${turnCount} turns`}
        </span>
        {tokenStr && (
          <span className="ctx-tree-node__meta ctx-tree-node__meta--green">
            {tokenStr}
          </span>
        )}
      </div>

      {isExpanded && hasChildren && (
        <ul className="ctx-tree-children">
          {exchange.systemTurns.map(turn => (
            <TurnNode
              key={turn.idx}
              turn={turn}
              indent
              onClick={onTurnClick}
              isSelected={selectedTurnIdx === turn.idx}
              onDelete={onDeleteTurn}
            />
          ))}
          {exchange.userTurn && (
            <TurnNode
              key={exchange.userTurn.idx}
              turn={exchange.userTurn}
              indent
              onClick={onTurnClick}
              isSelected={selectedTurnIdx === exchange.userTurn.idx}
              onDelete={onDeleteTurn}
            />
          )}
          {assistantTurnsOrGroups.map((item) => {
            if (item.type === 'parallel') {
              return (
                <ParallelGroupNode
                  key={`parallel-${item.groupId}`}
                  turns={item.turns}
                  groupId={item.groupId}
                  onTurnClick={onTurnClick}
                  selectedTurnIdx={selectedTurnIdx}
                />
              );
            }
            return (
              <TurnNode
                key={item.turn.idx}
                turn={item.turn}
                indent
                onClick={onTurnClick}
                isSelected={selectedTurnIdx === item.turn.idx}
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

// Props for main component
interface ContextTabViewProps {
  sessionId: string | null;
  sessionName?: string;
  turns: TurnInfo[];
  /** Raw SessionDataTurns for hover preview with full TurnCard rendering */
  rawTurns?: SessionDataTurn[];
  /** Client for TurnCard interactions (e.g., fork proposal) */
  client?: BalloonsClient | null;
  totalTokens?: number;
  onSelectTurn?: (turnIdx: number) => void;
  onExchangeAction?: (turnIndices: number[], action: ExchangeAction) => void;
  /** Called when a single turn should be deleted */
  onDeleteTurn?: (turnIdx: number) => void;
  /** Called when user wants to add exchange to link stash */
  onAddToLinkStash?: (turnIndices: number[], excerpt: string) => void;
  isLoading?: boolean;
  /** Turn indices currently being archived (show spinner) */
  archivingTurnIndices?: Set<number>;
}

// Sub-tab type for context view
type ContextSubTab = 'exchanges' | 'system';

export const ContextTabView = memo(function ContextTabView({
  sessionId,
  sessionName,
  turns,
  rawTurns,
  client,
  totalTokens,
  onSelectTurn,
  onExchangeAction,
  onDeleteTurn,
  onAddToLinkStash,
  isLoading = false,
  archivingTurnIndices,
}: ContextTabViewProps) {
  // Log on mount
  useEffect(() => {
    debugLog('ContextTabView mounted', { sessionId, turnCount: turns.length });
  }, [sessionId, turns.length]);

  // Active sub-tab
  const [activeSubTab, setActiveSubTab] = useState<ContextSubTab>('exchanges');

  // Track which exchanges are expanded
  const [expandedExchanges, setExpandedExchanges] = useState<Set<string>>(new Set());

  // Track the selected turn for persistent preview in bottom pane
  const [selectedTurnIdx, setSelectedTurnIdx] = useState<number | null>(null);

  // Track the last exchange ID we've seen to detect new exchanges
  const lastExchangeIdRef = React.useRef<string | null>(null);

  // Group turns into exchanges for display
  const exchanges = useMemo(() => {
    const result = groupTurnsIntoExchanges(turns);
    debugLog('groupTurnsIntoExchanges', { turnCount: turns.length, exchangeCount: result.length });
    return result;
  }, [turns]);

  // Build map from turn idx to raw SessionDataTurn for hover preview
  const rawTurnByIdx = useMemo(() => {
    if (!rawTurns) return new Map<number, SessionDataTurn>();
    const map = new Map<number, SessionDataTurn>();
    for (const rawTurn of rawTurns) {
      map.set(rawTurn.order, rawTurn);
    }
    return map;
  }, [rawTurns]);

  // Build tool result map for pairing tool_use with tool_result
  const toolResultMap = useMemo(() => {
    if (!rawTurns) return new Map<string, SessionDataTurn>();
    const map = new Map<string, SessionDataTurn>();
    for (const turn of rawTurns) {
      if (turn.contentBlock?.type === 'tool_result') {
        // Note: ToolResultBlock uses camelCase toolUseId
        const toolResultBlock = turn.contentBlock as { toolUseId?: string };
        if (toolResultBlock.toolUseId) {
          map.set(toolResultBlock.toolUseId, turn);
        }
      }
    }
    debugLog('toolResultMap built', { size: map.size, keys: Array.from(map.keys()).slice(0, 5) });
    return map;
  }, [rawTurns]);

  // Auto-expand the last exchange, and when a new exchange starts, expand it
  useEffect(() => {
    if (exchanges.length === 0) return;

    const lastExchange = exchanges[exchanges.length - 1];
    if (!lastExchange) return;

    const lastExchangeId = lastExchange.id;

    // If this is a new exchange (different from what we were tracking), expand it
    if (lastExchangeId !== lastExchangeIdRef.current) {
      setExpandedExchanges(prev => {
        const next = new Set(prev);
        // Optionally collapse the previous last exchange
        // if (lastExchangeIdRef.current) {
        //   next.delete(lastExchangeIdRef.current);
        // }
        next.add(lastExchangeId);
        return next;
      });
      lastExchangeIdRef.current = lastExchangeId;
    }
  }, [exchanges]);

  // Calculate total tokens from turns if not provided
  const calculatedTotalTokens = useMemo(() => {
    if (totalTokens !== undefined) return totalTokens;
    return turns.reduce((sum, t) => sum + (t.tokens || 0), 0);
  }, [turns, totalTokens]);

  const toggleExchange = useCallback((exchangeId: string) => {
    setExpandedExchanges(prev => {
      const next = new Set(prev);
      if (next.has(exchangeId)) {
        next.delete(exchangeId);
      } else {
        next.add(exchangeId);
      }
      return next;
    });
  }, []);

  // Handle selecting a turn for preview
  const handleTurnSelect = useCallback((turnIdx: number) => {
    setSelectedTurnIdx(prev => prev === turnIdx ? null : turnIdx); // Toggle if clicking same turn

    // Scroll the selected node into view after a brief delay for state to update
    requestAnimationFrame(() => {
      const turnElement = document.querySelector(`[data-ctx-turn-idx="${turnIdx}"]`);
      if (turnElement) {
        turnElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    });
  }, []);

  // Get the selected raw turn for preview
  const selectedRawTurn = selectedTurnIdx !== null ? rawTurnByIdx.get(selectedTurnIdx) : undefined;

  // ClientContext value for TurnCard in preview
  const clientContextValue = useMemo(() => ({
    client: client || null,
  }), [client]);

  if (!sessionId) {
    return (
      <div className="ctx-tab-view ctx-tab-view--empty">
        <div className="ctx-tab-view__empty-state">
          <h2>No Session Selected</h2>
          <p>Select a session to view its context.</p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="ctx-tab-view ctx-tab-view--empty">
        <div className="ctx-tab-view__empty-state">
          Loading context...
        </div>
      </div>
    );
  }

  return (
    <div className={`ctx-tab-view ${selectedRawTurn ? 'ctx-tab-view--with-preview' : ''}`}>
      {/* Header with session info and sub-tabs */}
      <div className="ctx-tab-view__header">
        {/* Sub-tabs */}
        <div className="ctx-tab-view__subtabs">
          <button
            className={`ctx-tab-view__subtab ${activeSubTab === 'exchanges' ? 'ctx-tab-view__subtab--active' : ''}`}
            onClick={() => setActiveSubTab('exchanges')}
          >
            Exchanges
          </button>
          <button
            className={`ctx-tab-view__subtab ${activeSubTab === 'system' ? 'ctx-tab-view__subtab--active' : ''}`}
            onClick={() => setActiveSubTab('system')}
          >
            System
          </button>
        </div>

        {/* Stats - only show on exchanges tab */}
        {activeSubTab === 'exchanges' && (
          <div className="ctx-tab-view__stats">
            <span className="ctx-tab-view__stat">
              {exchanges.length} exchange{exchanges.length !== 1 ? 's' : ''}
            </span>
            <span className="ctx-tab-view__stat ctx-tab-view__stat--tokens">
              {formatKt(calculatedTotalTokens) || '0kt'}
            </span>
          </div>
        )}
      </div>

      {/* System Prompt view */}
      {activeSubTab === 'system' && (
        <SystemPromptView
          sessionId={sessionId}
          client={client}
          isLoading={isLoading}
        />
      )}

      {/* Exchanges view - Tree section (top half when preview is open) */}
      {activeSubTab === 'exchanges' && (
        <div className="ctx-tab-view__tree-section">
        <ul className="ctx-tree-view">
          {exchanges.length > 0 ? (
            exchanges.map(exchange => {
              // Get all turn indices in this exchange for callbacks
              const turnIndices: number[] = [
                ...exchange.systemTurns.map(t => t.idx),
                ...(exchange.userTurn ? [exchange.userTurn.idx] : []),
                ...exchange.assistantTurns.map(t => t.idx),
              ];

              // Check if any turns in this exchange are being archived
              const isArchiving = archivingTurnIndices && turnIndices.some(idx => archivingTurnIndices.has(idx));

              // Build excerpt from user turn or first content
              const excerptSource = exchange.userTurn?.content
                || exchange.assistantTurns[0]?.content
                || exchange.systemTurns[0]?.content
                || '';
              const excerpt = excerptSource.slice(0, 100).replace(/\n/g, ' ');

              return (
                <ExchangeNode
                  key={exchange.id}
                  exchange={exchange}
                  isExpanded={expandedExchanges.has(exchange.id)}
                  isArchiving={isArchiving}
                  onToggle={() => toggleExchange(exchange.id)}
                  onArchive={onExchangeAction
                    ? () => onExchangeAction(turnIndices, 'archive')
                    : undefined}
                  onRestore={onExchangeAction
                    ? () => onExchangeAction(turnIndices, 'restore')
                    : undefined}
                  onDelete={onExchangeAction
                    ? () => onExchangeAction(turnIndices, 'delete')
                    : undefined}
                  onDeleteTurn={onDeleteTurn}
                  onAddToLinkStash={onAddToLinkStash
                    ? () => onAddToLinkStash(turnIndices, excerpt)
                    : undefined}
                  onTurnClick={handleTurnSelect}
                  selectedTurnIdx={selectedTurnIdx}
                  rawTurnByIdx={rawTurnByIdx}
                />
              );
            })
        ) : (
          <li className="ctx-tree-node ctx-tree-node--empty">
            <div className="ctx-tree-node__content">
              <span className="ctx-tree-node__label ctx-tree-node__label--muted">
                No messages yet
              </span>
            </div>
          </li>
        )}
        </ul>
      </div>
      )}

      {/* Preview section (bottom half when a turn is selected) - only on exchanges tab */}
      {activeSubTab === 'exchanges' && selectedRawTurn && (
        <div className="ctx-tab-view__preview-section">
          <div className="ctx-tab-view__preview-header">
            <span className="ctx-tab-view__preview-title">
              Turn {selectedTurnIdx}
            </span>
            <button
              className="ctx-tab-view__preview-close"
              onClick={() => setSelectedTurnIdx(null)}
              title="Close preview"
            >
              ✕
            </button>
          </div>
          <div className="ctx-tab-view__preview-content">
            <ClientContext.Provider value={clientContextValue}>
              <TurnCard turn={selectedRawTurn} toolResultMap={toolResultMap} sessionId={sessionId || undefined} />
            </ClientContext.Provider>
          </div>
        </div>
      )}
    </div>
  );
});

export default ContextTabView;
