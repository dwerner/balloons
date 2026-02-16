import React, { memo, useState, useEffect, useRef, useCallback } from 'react';
import type { LogEntry, LogLevel } from './DebugPaneTypes';
import { LOG_LEVELS, LOG_LEVEL_LABELS, LOG_LEVEL_SEVERITY } from './DebugPaneTypes';
import './DebugPane.css';

export interface DebugPaneProps {
  /** Log entries to display */
  entries: LogEntry[];
  /** Initial minimum log level to display (default: 'debug') */
  initialMinLevel?: LogLevel;
  /** Initial collapsed state (default: true) */
  initialCollapsed?: boolean;
  /** Callback when user Ctrl+clicks a log line to copy to input */
  onLogLineCopy?: (text: string, entry: LogEntry) => void;
  /** Callback when entries are cleared */
  onClear?: () => void;
  /** Callback when minimum level changes */
  onMinLevelChange?: (level: LogLevel) => void;
  /** Whether to auto-expand when an error is logged */
  autoExpandOnError?: boolean;
  /** Custom class name */
  className?: string;
}

/**
 * Format a log entry as a full text string for copying.
 */
function formatEntryFull(entry: LogEntry): string {
  const parts: string[] = [];

  parts.push(`[${entry.timestamp}]`);
  parts.push(`[${LOG_LEVEL_LABELS[entry.level]}]`);

  if (entry.runId) {
    parts.push(`pid:${entry.runId}`);
  }

  if (entry.category) {
    parts.push(`${entry.category}:`);
  }

  parts.push(entry.message);

  // Include full details for context
  if (entry.details && Object.keys(entry.details).length > 0) {
    const detailsParts: string[] = [];
    for (const [k, v] of Object.entries(entry.details)) {
      detailsParts.push(`${k}=${String(v)}`);
    }
    parts.push(`(${detailsParts.join(', ')})`);
  }

  return parts.join(' ');
}

/**
 * Truncate message if too long.
 */
function truncateMessage(message: string, maxLength = 100): string {
  if (message.length <= maxLength) {
    return message;
  }
  return message.slice(0, maxLength - 3) + '...';
}

/**
 * Format details for inline display.
 */
function formatDetails(details: Record<string, unknown>): string {
  const parts: string[] = [];

  for (const [k, v] of Object.entries(details)) {
    if (k === 'stderr' && v) {
      const lines = String(v).split('\n');
      const firstLine = (lines[0] ?? '').slice(0, 40);
      parts.push(`stderr=${firstLine}...`);
    } else if (k === 'text' && v) {
      let content = String(v).replace(/\n/g, '\\n');
      if (content.length > 40) {
        content = content.slice(0, 37) + '...';
      }
      parts.push(`text="${content}"`);
    } else if (k !== 'prompt_len' && k !== 'json') {
      let strV = String(v);
      if (strV.length > 30) {
        strV = strV.slice(0, 27) + '...';
      }
      parts.push(`${k}=${strV}`);
    }
  }

  return parts.length > 0 ? `(${parts.join(', ')})` : '';
}

/**
 * LogLevelSelector - Clickable log level filter buttons.
 */
interface LogLevelSelectorProps {
  currentLevel: LogLevel;
  onLevelChange: (level: LogLevel) => void;
}

const LogLevelSelector = memo(function LogLevelSelector({
  currentLevel,
  onLevelChange,
}: LogLevelSelectorProps) {
  const currentSeverity = LOG_LEVEL_SEVERITY[currentLevel];

  return (
    <div className="debug-pane__level-selector">
      <span className="debug-pane__level-label">Level:</span>
      {LOG_LEVELS.map((level) => {
        const isActive = LOG_LEVEL_SEVERITY[level] >= currentSeverity;
        return (
          <button
            key={level}
            type="button"
            className={`debug-pane__level-btn debug-pane__level-btn--${level} ${
              isActive ? 'debug-pane__level-btn--active' : 'debug-pane__level-btn--inactive'
            }`}
            onClick={(e) => {
              e.stopPropagation();
              onLevelChange(level);
            }}
            title={`Filter to ${level} and above`}
          >
            [{LOG_LEVEL_LABELS[level]}]
          </button>
        );
      })}
    </div>
  );
});

/**
 * LogEntryView - A single log entry row.
 */
interface LogEntryViewProps {
  entry: LogEntry;
  isHighlighted: boolean;
  onClick: (e: React.MouseEvent, entry: LogEntry) => void;
}

const LogEntryView = memo(function LogEntryView({
  entry,
  isHighlighted,
  onClick,
}: LogEntryViewProps) {
  const details = entry.details ? formatDetails(entry.details) : '';

  return (
    <div
      className={`debug-pane__entry debug-pane__entry--${entry.level} ${
        isHighlighted ? 'debug-pane__entry--highlighted' : ''
      }`}
      onClick={(e) => onClick(e, entry)}
      role="listitem"
    >
      <span className="debug-pane__timestamp">[{entry.timestamp}]</span>
      <span className={`debug-pane__level debug-pane__level--${entry.level}`}>
        [{LOG_LEVEL_LABELS[entry.level]}]
      </span>
      {entry.runId && (
        <span className="debug-pane__run-id">pid:{entry.runId}</span>
      )}
      {entry.category && (
        <span className="debug-pane__category">{entry.category}:</span>
      )}
      <span className="debug-pane__message">
        {truncateMessage(entry.message)}
        {details && <span className="debug-pane__details">{details}</span>}
      </span>
    </div>
  );
});

/**
 * DebugPane - Collapsible debug log viewer.
 *
 * Shows debug log entries with:
 * - Log level selector buttons (T/D/P/I/W/E) for filtering
 * - Color-coded log entries by level
 * - Auto-expand on ERROR with red border
 * - Collapsible header showing error count
 * - Ctrl+click to copy log line to input
 */
export const DebugPane = memo(function DebugPane({
  entries,
  initialMinLevel = 'debug',
  initialCollapsed = true,
  onLogLineCopy,
  onClear,
  onMinLevelChange,
  autoExpandOnError = true,
  className = '',
}: DebugPaneProps) {
  const [isCollapsed, setIsCollapsed] = useState(initialCollapsed);
  const [isAutoExpanded, setIsAutoExpanded] = useState(false);
  const [minLevel, setMinLevel] = useState<LogLevel>(initialMinLevel);
  const [highlightedSeq, setHighlightedSeq] = useState<number | null>(null);
  const [lineSelectedFeedback, setLineSelectedFeedback] = useState(false);

  const logContainerRef = useRef<HTMLDivElement>(null);
  const prevErrorCountRef = useRef(0);

  // Count errors for badge
  const errorCount = entries.filter((e) => e.level === 'error').length;

  // Filter entries by minimum level
  const minSeverity = LOG_LEVEL_SEVERITY[minLevel];
  const filteredEntries = entries.filter(
    (e) => LOG_LEVEL_SEVERITY[e.level] >= minSeverity
  );

  // Auto-expand on new error
  useEffect(() => {
    if (autoExpandOnError && errorCount > prevErrorCountRef.current && isCollapsed) {
      setIsAutoExpanded(true);
    }
    prevErrorCountRef.current = errorCount;
  }, [errorCount, autoExpandOnError, isCollapsed]);

  // Auto-scroll to bottom on new entries
  useEffect(() => {
    if (logContainerRef.current && (!isCollapsed || isAutoExpanded)) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [filteredEntries.length, isCollapsed, isAutoExpanded]);

  // Handle level change
  const handleLevelChange = useCallback((level: LogLevel) => {
    setMinLevel(level);
    onMinLevelChange?.(level);
  }, [onMinLevelChange]);

  // Handle header click (toggle)
  const handleToggle = useCallback(() => {
    if (isCollapsed || isAutoExpanded) {
      setIsCollapsed(false);
      setIsAutoExpanded(false);
    } else {
      setIsCollapsed(true);
    }
  }, [isCollapsed, isAutoExpanded]);

  // Handle entry click (Ctrl+click to copy)
  const handleEntryClick = useCallback((e: React.MouseEvent, entry: LogEntry) => {
    if (e.ctrlKey || e.metaKey) {
      const fullText = formatEntryFull(entry);

      // Visual feedback
      setHighlightedSeq(entry.seq);
      setLineSelectedFeedback(true);

      // Clear feedback after a short delay
      setTimeout(() => {
        setHighlightedSeq(null);
        setLineSelectedFeedback(false);
      }, 500);

      // Call the copy callback
      onLogLineCopy?.(fullText, entry);
    }
  }, [onLogLineCopy]);

  // Handle clear button
  const handleClear = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onClear?.();
  }, [onClear]);

  // Determine container state class
  const getStateClass = () => {
    if (isCollapsed && !isAutoExpanded) {
      return 'debug-pane--collapsed';
    }
    if (isAutoExpanded) {
      return 'debug-pane--auto-expanded';
    }
    return 'debug-pane--expanded';
  };

  const isExpanded = !isCollapsed || isAutoExpanded;

  return (
    <div
      className={`debug-pane ${getStateClass()} ${
        lineSelectedFeedback ? 'debug-pane--line-selected' : ''
      } ${className}`}
      role="region"
      aria-label="Debug Log"
    >
      {/* Header */}
      <div
        className="debug-pane__header"
        onClick={handleToggle}
        role="button"
        tabIndex={0}
        aria-expanded={isExpanded}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            handleToggle();
          }
        }}
      >
        <span className="debug-pane__toggle-icon" aria-hidden="true">
          {isExpanded ? '\u25BC' : '\u25B6'}
        </span>
        <span className="debug-pane__title">Debug Log</span>
        {errorCount > 0 && (
          <span className="debug-pane__error-badge" aria-label={`${errorCount} errors`}>
            {errorCount}
          </span>
        )}
        <span className="debug-pane__spacer" />

        {/* Level selector - only show when expanded */}
        {isExpanded && (
          <LogLevelSelector
            currentLevel={minLevel}
            onLevelChange={handleLevelChange}
          />
        )}

        {/* Clear button - only show when expanded and has entries */}
        {isExpanded && entries.length > 0 && onClear && (
          <button
            type="button"
            className="debug-pane__clear-btn"
            onClick={handleClear}
            title="Clear log entries"
          >
            Clear
          </button>
        )}
      </div>

      {/* Log entries */}
      {isExpanded && (
        <div
          ref={logContainerRef}
          className="debug-pane__log-container"
          role="list"
          aria-label="Log entries"
        >
          {filteredEntries.length === 0 ? (
            <div className="debug-pane__empty">No log entries</div>
          ) : (
            filteredEntries.map((entry) => (
              <LogEntryView
                key={entry.seq}
                entry={entry}
                isHighlighted={highlightedSeq === entry.seq}
                onClick={handleEntryClick}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
});

export default DebugPane;
